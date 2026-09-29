#!/usr/bin/env python3
"""
Extract a manuscript into the structures the annotation tool needs.

Usage:
    python extract.py MANUSCRIPT OUTDIR [--max-width 1500] [--main main.tex]

MANUSCRIPT may be:
    .docx          Word file (captions from text boxes or caption paragraphs; Word comments imported)
    .tex / .zip    LaTeX source, or a zipped project (e.g. Overleaf download) with figures and .bib
    .pdf           PDF with a text layer (reflowed into paragraphs; figure regions cropped from pages;
                   PDF sticky notes / highlights imported as co-author comments)

Writes to OUTDIR:
    doc.json      {"blocks": [...]}  ordered blocks (title, h2, h3, p, ref, figure, table)
    imgs.json     {fig_id: {"src": data-URI (webp), "w", "h"}}  compressed figures for the page
    texts.json    {block_id: plain text}  exactly the browser's textContent for each block;
                  every text anchor ("exact") must be copied from here
    figures.json  {fig_id: {"media": image path, "label", "w", "h"}}  used by check_boxes.py
    comments.json existing reviewer comments [{author, text, exact, block}]
    outline.txt   one line per block (id, kind, start of text) for orientation
Requires: pandoc (docx/LaTeX), beautifulsoup4, lxml, pillow; pdfplumber + pypdfium2 (PDF, LaTeX PDF figures).
"""
import argparse, base64, io, json, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CAP_RE = re.compile(r"^\s*(?:Supplementary\s+|Extended\s+Data\s+)?(Figure|Fig\.?|eFigure|Table|eTable)\s*(S?\d+[A-Za-z]?)", re.I)
TAB_RE = re.compile(r"^\s*(?:Supplementary\s+|Extended\s+Data\s+)?e?Table", re.I)
REF_HEAD = re.compile(r"^(?:\d+\.?\s*)?(references|bibliography|literature cited|works cited|reference list)\s*:?\s*$", re.I)


# ----------------------------------------------------------------- shared helpers
def compress(im, max_w):
    im = im.convert("RGB")
    w, h = im.size
    if w > max_w:
        im = im.resize((max_w, round(h * max_w / w)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=84, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode(), im.size


def slug_label(text, kind, n):
    m = CAP_RE.match(text or "")
    if m:
        num = m.group(2).upper()
        word = "Table" if m.group(1).lower() in ("table", "etable") else "Figure"
        return f"{'tab' if word == 'Table' else 'fig'}-{num.lower()}", f"{word} {num}"
    return (f"tab-{n}" if kind == "table" else f"fig-{n}"), (f"Table {n}" if kind == "table" else f"Figure {n}")


def plain(h):
    return BeautifulSoup(h or "", "html.parser").get_text()


def block_text(b):
    if b["kind"] == "figure":
        return plain(b["caption"])
    if b["kind"] == "table":
        return plain(b["caption"]) + "".join(plain(c) for r in b["rows"] for c in r)
    return plain(b["html"])


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def anchor_comments(raw, texts):
    """Find each comment's quoted text in the blocks (exact, then whitespace-normalised, then prefixes)."""
    out = []
    for c in raw:
        ex, blk = c.get("exact", ""), None
        for probe in (ex, norm_ws(ex), norm_ws(ex)[:120], norm_ws(ex)[:60], norm_ws(ex)[:30]):
            if probe and len(probe) >= 3:
                hits = [k for k, t in texts.items() if probe in t]
                if hits:
                    ex, blk = probe, hits[0]
                    break
        out.append({**c, "exact": ex, "block": blk})
    return out


def write_outputs(out, blocks, imgs, figs, raw_comments):
    for b in blocks:  # MathML annotations duplicate the TeX source in textContent: drop them
        for k in ("html", "caption"):
            if b.get(k) and "<annotation" in b[k]:
                s = BeautifulSoup(b[k], "html.parser")
                for a in s.find_all("annotation"):
                    a.decompose()
                b[k] = str(s)
        if b["kind"] == "table":
            b["rows"] = [[re.sub(r"<annotation.*?</annotation>", "", c, flags=re.S) for c in r] for r in b["rows"]]
    texts = {b["id"]: block_text(b) for b in blocks}
    comments = anchor_comments(raw_comments, texts)
    (out / "doc.json").write_text(json.dumps({"blocks": blocks}, ensure_ascii=False))
    (out / "imgs.json").write_text(json.dumps(imgs))
    (out / "texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=0))
    (out / "figures.json").write_text(json.dumps(figs, indent=1))
    (out / "comments.json").write_text(json.dumps(comments, ensure_ascii=False, indent=1))
    with open(out / "outline.txt", "w") as f:
        for b in blocks:
            t = texts[b["id"]].replace("\n", " ")
            lab = (b.get("label") or "") + " " if b["kind"] in ("figure", "table") else ""
            f.write(f"{b['id']:<10} {b['kind']:<7} {lab}{t[:100]}\n")
    kinds = {}
    for b in blocks:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    print(f"blocks: {len(blocks)} {kinds}")
    print(f"figures: {len(imgs)} ({sum(len(v['src']) for v in imgs.values()) / 1e6:.2f} MB inlined)")
    missing = [b["id"] for b in blocks if b["kind"] in ("figure", "table") and not b.get("caption")]
    if missing:
        print(f"WARNING: no caption found for {missing}; check outline.txt", file=sys.stderr)
    print(f"reviewer comments: {len(comments)} ({sum(1 for c in comments if c['block'])} anchored)")


# ----------------------------------------------------------------- pandoc HTML -> blocks (docx, LaTeX)
class Builder:
    def __init__(self, max_w, resolve_img, fig_caps=None, tab_caps=None, number_captions=False):
        self.max_w, self.resolve_img = max_w, resolve_img
        self.fig_caps, self.tab_caps = list(fig_caps or []), list(tab_caps or [])
        self.number_captions = number_captions
        self.blocks, self.imgs, self.figs, self.used = [], {}, {}, set()
        self.pc = self.nfig = self.ntab = 0
        self.in_refs, self.last_fig, self.pending_tab_cap, self.base = False, None, None, 1
        self.media_dir = Path(tempfile.mkdtemp(prefix="figs_"))

    def uid(self, base):
        k, i = base, 2
        while k in self.used:
            k = f"{base}-{i}"; i += 1
        self.used.add(k)
        return k

    def add(self, kind, html, **kw):
        self.pc += 1
        b = dict(id=self.uid(kw.pop("id", f"b{self.pc:03d}")), kind=kind, html=html, **kw)
        self.blocks.append(b)
        return b

    @staticmethod
    def delink(h):
        h = re.sub(r"<a [^>]*>(.*?)</a>", r'<span class="link">\1</span>', h, flags=re.S)
        return re.sub(r"\s*\n\s*", " ", h).strip()

    def figure(self, images, cap_html):
        self.nfig += 1
        if not cap_html and self.fig_caps:
            cap_html = self.fig_caps.pop(0)
        cap_text = plain(cap_html)
        fid, label = slug_label(cap_text, "figure", self.nfig)
        if cap_html and self.number_captions and not CAP_RE.match(cap_text):
            cap_html = f"<strong>{label}.</strong> {cap_html}"
        fid = self.uid(fid)
        if len(images) == 1:
            im = images[0]
        else:  # sub-figures: place side by side at a common height
            h = min(i.height for i in images)
            parts = [i.resize((round(i.width * h / i.height), h), Image.LANCZOS) for i in images]
            im = Image.new("RGB", (sum(p.width for p in parts) + 20 * (len(parts) - 1), h), "white")
            x = 0
            for p in parts:
                im.paste(p.convert("RGB"), (x, 0)); x += p.width + 20
        path = self.media_dir / f"{fid}.png"
        im.convert("RGB").save(path)
        uri, size = compress(im, self.max_w)
        self.imgs[fid] = {"src": uri, "w": size[0], "h": size[1]}
        self.figs[fid] = {"media": str(path), "label": label, "w": im.width, "h": im.height}
        b = {"id": fid, "kind": "figure", "html": "", "fig": fid, "caption": self.delink(cap_html), "label": label}
        self.blocks.append(b)
        self.last_fig = b

    def table(self, el, cap_html):
        rows = []
        for tr in el.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                ps = td.find_all("p")
                h = " ".join(p.decode_contents() for p in ps) if ps else td.decode_contents()
                cells.append(re.sub(r"\s+", " ", h).strip())
            rows.append(cells)
        self.ntab += 1
        if not cap_html:
            cap_html = self.tab_caps.pop(0) if self.tab_caps else (self.pending_tab_cap or "")
        self.pending_tab_cap = None
        tid, label = slug_label(plain(cap_html), "table", self.ntab)
        if cap_html and self.number_captions and not CAP_RE.match(plain(cap_html)):
            cap_html = f"<strong>{label}.</strong> {cap_html}"
        self.blocks.append({"id": self.uid(tid), "kind": "table", "html": "", "rows": rows,
                            "caption": self.delink(cap_html), "label": label})
        self.last_fig = None

    def heading(self, level, text):
        text = text.strip().rstrip(":")
        if not text:
            return
        kind = "h2" if level <= self.base else "h3"
        self.add(kind, text)
        if kind == "h2" or REF_HEAD.match(text):
            self.in_refs = bool(REF_HEAD.match(text))
        self.last_fig = None

    def para(self, el):
        imgs = el.find_all("img")
        if imgs:  # each inline image in a paragraph is its own figure (Word places one per caption)
            for i in imgs:
                im = self.resolve_img(i.get("src", ""))
                if im is not None:
                    self.figure([im], "")
            return
        inner = self.delink(el.decode_contents().strip())
        text = el.get_text().strip()
        if not text:
            return
        if CAP_RE.match(text):
            if TAB_RE.match(text):
                self.pending_tab_cap = inner
                return
            if self.last_fig is not None and not self.last_fig["caption"]:
                fid, label = slug_label(text, "figure", self.nfig)
                self.last_fig["caption"], self.last_fig["label"] = inner, label
                return
        strong = el.find("strong")
        if strong and strong.get_text().strip() == text and len(text) < 90:
            self.heading(self.base, text)
            return
        first = next((c for c in el.children if not (isinstance(c, NavigableString) and not c.strip())), None)
        if isinstance(first, Tag) and first.name == "em" and first.find("br"):
            head = first.get_text().strip(); first.extract()
            self.add("h3", head)
            if el.get_text().strip():
                self.add("p", self.delink(el.decode_contents().strip()))
            return
        em = el.find("em")
        if em and em.get_text().strip() == text and len(text) < 70:
            self.add("h3", text)
            return
        if self.in_refs:
            m = re.match(r"\s*\[?(\d+)[\].]", text)
            self.add("ref", inner, id=f"ref-{m.group(1)}" if m else f"ref-x{self.pc + 1}")
        elif not self.blocks:
            self.add("title", inner)
        else:
            self.add("p", inner)
        self.last_fig = None

    def walk(self, nodes):
        for el in nodes:
            if not isinstance(el, Tag):
                continue
            n = el.name
            if n == "header":
                for c in el.children:
                    if not isinstance(c, Tag):
                        continue
                    cls = c.get("class") or []
                    if c.name == "h1" and "title" in cls:
                        self.add("title", self.delink(c.decode_contents()))
                    elif "author" in cls or "date" in cls or "subtitle" in cls:
                        self.add("p", self.delink(c.decode_contents()))
                    elif "abstract" in cls:
                        self.add("h2", "Abstract")
                        for p in c.find_all("p"):
                            self.add("p", self.delink(p.decode_contents()))
            elif n in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.heading(int(n[1]), el.get_text())
            elif n == "figure":
                cap = el.find("figcaption")
                cap_html = cap.decode_contents() if cap else ""
                if cap:
                    cap.extract()
                loaded = [x for x in (self.resolve_img(i.get("src", "")) for i in el.find_all("img")) if x is not None]
                if loaded:
                    self.figure(loaded, cap_html)
                elif el.find("table"):
                    self.table(el.find("table"), cap_html)
            elif n == "table":
                cap = el.find("caption")
                cap_html = cap.decode_contents() if cap else ""
                if cap:
                    cap.extract()
                self.table(el, cap_html)
            elif n == "div" and "csl-entry" in (el.get("class") or []):
                self.in_refs = True
                self.add("ref", self.delink(el.decode_contents()), id=f"ref-{el.get('id', '').replace('ref-', '') or self.pc + 1}")
            elif n == "div" and ("references" in (el.get("class") or []) or el.get("id") == "refs"):
                if not any(b["kind"] == "h2" and REF_HEAD.match(b["html"]) for b in self.blocks):
                    self.add("h2", "References")
                self.in_refs = True
                self.walk(el.children)
            elif n in ("div", "section", "article", "main", "blockquote"):
                self.walk(el.children)
            elif n in ("ol", "ul"):
                for li in el.find_all("li", recursive=False):
                    self.para(li)
            elif n in ("p",):
                self.para(el)


def run_pandoc(args, cwd=None):
    r = subprocess.run(["pandoc", *args], capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        sys.exit(f"pandoc failed:\n{r.stderr[-2000:]}")
    return r.stdout


def heading_base(soup):
    lv = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$")) if h.get_text().strip()
          and not (h.name == "h1" and "title" in (h.get("class") or []))]
    return min(lv) if lv else 1


# ----------------------------------------------------------------- .docx
def docx_captions(docxml):
    from lxml import etree

    def run_html(r):
        t = "".join(x.text or "" for x in r.iter(f"{{{W}}}t"))
        if not t:
            return ""
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rpr = r.find(f"{{{W}}}rPr")
        if rpr is not None:
            va = rpr.find(f"{{{W}}}vertAlign")
            if va is not None and va.get(f"{{{W}}}val") == "superscript":
                t = f"<sup>{t}</sup>"
            elif va is not None and va.get(f"{{{W}}}val") == "subscript":
                t = f"<sub>{t}</sub>"
            b = rpr.find(f"{{{W}}}b")
            if b is not None and b.get(f"{{{W}}}val") not in ("0", "false"):
                t = f"<strong>{t}</strong>"
            i = rpr.find(f"{{{W}}}i")
            if i is not None and i.get(f"{{{W}}}val") not in ("0", "false"):
                t = f"<em>{t}</em>"
        return t
    root = etree.fromstring(docxml)
    caps, seen = [], set()
    for tb in root.iter(f"{{{W}}}txbxContent"):
        paras = ["".join(run_html(r) for r in p.iter(f"{{{W}}}r")) for p in tb.iter(f"{{{W}}}p")]
        html = re.sub(r"</(strong|em)><\1>", "", " ".join(x for x in paras if x.strip()))
        t = plain(html).strip()
        if t and t not in seen:
            seen.add(t)
            if CAP_RE.match(t):
                caps.append(html)
    return caps


def docx_comments(z, docxml):
    from lxml import etree
    if "word/comments.xml" not in z.namelist():
        return []
    croot = etree.fromstring(z.read("word/comments.xml"))
    meta = {}
    for c in croot.iter(f"{{{W}}}comment"):
        text = "\n".join("".join(t.text or "" for t in p.iter(f"{{{W}}}t")) for p in c.iter(f"{{{W}}}p")).strip()
        meta[c.get(f"{{{W}}}id")] = {"author": c.get(f"{{{W}}}author") or "", "text": text}
    root = etree.fromstring(docxml)
    open_ids, anchor, context, para = set(), {k: "" for k in meta}, {}, ""
    for _, el in etree.iterwalk(root, events=("start",)):
        tag = etree.QName(el).localname if isinstance(el.tag, str) else ""
        if tag == "p":
            para = ""
        elif tag == "commentRangeStart":
            cid = el.get(f"{{{W}}}id"); open_ids.add(cid); context[cid] = para
        elif tag == "commentRangeEnd":
            open_ids.discard(el.get(f"{{{W}}}id"))
        elif tag == "t":
            para += el.text or ""
            for cid in open_ids:
                if cid in anchor:
                    anchor[cid] += el.text or ""
    res = []
    for cid, m in meta.items():
        ex = anchor.get(cid, "").strip()
        if len(ex) < 20:  # a one-word or punctuation anchor is not a useful quote: add preceding context
            ctx = context.get(cid, "")[-90:]
            ctx = ctx[ctx.find(" ") + 1:] if " " in ctx[:-1] else ctx
            ex = (ctx + anchor.get(cid, "")).strip()
        res.append({"author": m["author"], "text": m["text"], "exact": ex})
    return res


def from_docx(path, out, max_w):
    z = zipfile.ZipFile(path)
    docxml = z.read("word/document.xml")
    tmp = Path(tempfile.mkdtemp()); z.extractall(tmp)
    soup = BeautifulSoup(run_pandoc(["-f", "docx", "-t", "html", "--wrap=none", "--mathml", str(path)]), "html.parser")
    caps = docx_captions(docxml)

    def resolve(src):
        p = tmp / "word" / src
        if not p.exists():
            c = list((tmp / "word" / "media").glob(Path(src).name))
            p = c[0] if c else p
        return Image.open(p) if p.exists() else None
    b = Builder(max_w, resolve, [c for c in caps if not TAB_RE.match(plain(c))], [c for c in caps if TAB_RE.match(plain(c))])
    b.base = heading_base(soup)
    b.walk(soup.children)
    write_outputs(out, b.blocks, b.imgs, b.figs, docx_comments(z, docxml))


# ----------------------------------------------------------------- LaTeX
def render_pdf_page(path, scale=3.0, page=0):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    im = doc[page].render(scale=scale).to_pil().convert("RGB")
    # trim white margins
    from PIL import ImageChops
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bbox = ImageChops.difference(im, bg).getbbox()
    return im.crop(bbox) if bbox else im


def from_latex(path, out, max_w, main=None):
    src = Path(path)
    proj = Path(tempfile.mkdtemp(prefix="tex_"))
    if src.suffix.lower() == ".zip":
        zipfile.ZipFile(src).extractall(proj)
    else:
        for f in src.parent.iterdir():  # sibling figures/.bib travel with a lone .tex upload
            if f.is_file():
                shutil.copy(f, proj / f.name)
            elif f.is_dir():
                shutil.copytree(f, proj / f.name, dirs_exist_ok=True)
    texs = list(proj.rglob("*.tex"))
    if main:
        cand = [t for t in texs if t.name == main]
    else:
        cand = [t for t in texs if re.search(r"\\documentclass", t.read_text(errors="ignore")) and "\\begin{document}" in t.read_text(errors="ignore")]
        if src.suffix.lower() == ".tex":
            cand = [t for t in cand if t.name == src.name] or cand
        cand.sort(key=lambda t: (t.stem.lower() not in ("main", "ms", "manuscript", "paper"), -t.stat().st_size))
    if not cand:
        sys.exit("no main .tex (with \\documentclass and \\begin{document}) found; pass --main")
    mainf = cand[0]
    for t in texs:  # pandoc drops captions of starred floats; unstar them
        s = t.read_text(errors="ignore")
        s2 = re.sub(r"\\(begin|end)\{(figure|table)\*\}", r"\\\1{\2}", s)
        if s2 != s:
            t.write_text(s2)
    tex = mainf.read_text(errors="ignore")
    m = re.search(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\})+)\s*\}", tex)
    gpaths = [mainf.parent] + [mainf.parent / d for d in (re.findall(r"\{([^{}]*)\}", m.group(1)) if m else [])]
    args = ["-f", "latex", "-t", "html", "-s", "--wrap=none", "--mathml", "--number-sections", mainf.name]
    if list(proj.rglob("*.bib")):
        args.insert(-1, "--citeproc")
    html = run_pandoc(args, cwd=mainf.parent)
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    def resolve(s):
        s = s.strip()
        cands = []
        for g in gpaths:
            p = (g / s)
            cands += [p] + [p.with_name(p.name + e) for e in (".pdf", ".png", ".jpg", ".jpeg", ".eps")]
        cands += list(proj.rglob(Path(s).name + "*"))
        for p in cands:
            if p.is_file():
                ext = p.suffix.lower()
                if ext == ".pdf":
                    return render_pdf_page(p)
                if ext in (".eps", ".ps"):
                    print(f"WARNING: {p.name} is EPS and cannot be rendered here; convert it to PDF/PNG for a preview", file=sys.stderr)
                    ph = Image.new("RGB", (800, 300), "white")
                    from PIL import ImageDraw
                    ImageDraw.Draw(ph).text((20, 140), f"{p.name} (EPS not rendered)", fill="black")
                    return ph
                return Image.open(p)
        print(f"WARNING: figure file not found: {s}", file=sys.stderr)
        return None
    b = Builder(max_w, resolve, number_captions=True)
    b.base = heading_base(body)
    b.walk(body.children)
    write_outputs(out, b.blocks, b.imgs, b.figs, [])


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manuscript"); ap.add_argument("outdir")
    ap.add_argument("--max-width", type=int, default=1500)
    ap.add_argument("--main", help="main .tex file name inside a LaTeX project")
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    ext = Path(a.manuscript).suffix.lower()
    if ext == ".docx":
        from_docx(a.manuscript, out, a.max_width)
    elif ext in (".tex", ".zip"):
        from_latex(a.manuscript, out, a.max_width, a.main)
    elif ext == ".pdf":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pdf_extract import extract_pdf
        blocks, imgs, figs, comments = extract_pdf(a.manuscript, out, a.max_width, Builder, compress, slug_label, CAP_RE, TAB_RE, REF_HEAD)
        write_outputs(out, blocks, imgs, figs, comments)
    else:
        sys.exit(f"unsupported file type {ext}; use .docx, .tex, .zip (LaTeX project) or .pdf")


if __name__ == "__main__":
    main()
