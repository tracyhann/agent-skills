"""
PDF -> manuscript blocks. Used by extract.py; not run directly.

Strategy (text-layer PDFs; scanned PDFs are rejected with a message):
  1. words with font/size from pdfplumber, grouped into lines, split at column gutters
  2. running headers/footers and margin line numbers dropped
  3. reading order per page: full-width lines split the page into bands; within a band,
     left column then right column
  4. figure captions ("Figure N"/"Fig. N") -> the graphic region above them is cropped from a
     page render; words inside it are removed from the text flow
     table captions -> pdfplumber table below/above, else the region is cropped as an image
  5. remaining lines -> paragraphs (gaps, indents, style changes), headings by size/bold/numbering,
     references after a References heading, superscripts/italics/bold kept as HTML
  6. PDF annotations (sticky notes, highlights) -> reviewer comments with the highlighted text
"""
import html as htmlmod
import re
import statistics
from collections import Counter
from pathlib import Path

SECTION_NAMES = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?(abstract|introduction|background|methods?|materials and methods|results|discussion|conclusions?|references|acknowledg(e)?ments|supplementary.*|appendix.*|data availability.*|funding|author contributions|competing interests|limitations)\s*:?\s*$", re.I)
NUM_HEAD = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z]")


def _style(fontname):
    f = (fontname or "").lower().split("+")[-1]
    bold = any(k in f for k in ("bold", "black", "heavy", "semibold", "cmbx", "-bd", "demi"))
    ital = any(k in f for k in ("italic", "oblique", "cmti", "cmmi", "-it", "slant"))
    return bold, ital


def extract_pdf(path, out, max_w, Builder, compress, slug_label, CAP_RE, TAB_RE, REF_HEAD):
    import pdfplumber
    import pypdfium2 as pdfium
    from PIL import Image

    pdf = pdfplumber.open(path)
    rdoc = pdfium.PdfDocument(str(path))
    npages = len(pdf.pages)
    SCALE = 2.5
    renders = {}

    def render(pno):
        if pno not in renders:
            renders[pno] = rdoc[pno].render(scale=SCALE).to_pil().convert("RGB")
        return renders[pno]

    # ---------------------------------------------------------- 1. lines per page
    pages = []
    all_sizes = Counter()
    for pno, page in enumerate(pdf.pages):
        Wp, Hp = float(page.width), float(page.height)
        words = page.extract_words(x_tolerance=1.2, y_tolerance=2.5, keep_blank_chars=False,
                                   use_text_flow=False, extra_attrs=["fontname", "size"])
        words = [w for w in words if not (re.fullmatch(r"\d{1,4}", w["text"]) and (w["x1"] < 0.1 * Wp or w["x0"] > 0.9 * Wp))]
        for w in words:
            w["cid"] = "(cid:" in w["text"]
            w["text"] = re.sub(r"\(cid:\d+\)", "\ufffd", w["text"])
        for w in words:
            all_sizes[round(w["size"] * 2) / 2] += len(w["text"])
        pages.append({"W": Wp, "H": Hp, "words": words, "page": page})
    total_chars = sum(all_sizes.values())
    if total_chars < 500:
        raise SystemExit("This PDF has (almost) no text layer. It is probably scanned: OCR it first or ask for the .docx/.tex source.")
    body = all_sizes.most_common(1)[0][0]

    def make_lines(pg, gutter=None):
        ws = sorted(pg["words"], key=lambda w: (w["bottom"], w["x0"]))
        lines = []
        for w in ws:  # words sharing a baseline form a line (columns rarely share baselines exactly)
            for L in reversed(lines[-12:]):
                if abs(L["base"] - w["bottom"]) <= max(1.2, 0.2 * max(w["size"], L["ref"])):
                    L["words"].append(w)
                    L["top"], L["bottom"] = min(L["top"], w["top"]), max(L["bottom"], w["bottom"])
                    L["ref"] = max(L["ref"], w["size"])
                    break
            else:
                lines.append({"words": [w], "top": w["top"], "bottom": w["bottom"], "ref": w["size"], "base": w["bottom"]})
        # superscripts/subscripts are raised or lowered, so they cluster apart from their line;
        # move each small word to the line it touches (adjacent word, overlapping vertically)
        side = lambda w: gutter is not None and w["x0"] >= gutter[1] - 3
        for L in lines:
            keep = []
            for w in L["words"]:
                host = None
                for M in lines:
                    if M is L or M["ref"] * 0.8 <= w["size"] or not (w["bottom"] > M["top"] and w["top"] < M["bottom"]):
                        continue
                    if any(min(abs(w["x0"] - v["x1"]), abs(v["x0"] - w["x1"])) < 0.6 * M["ref"] and side(w) == side(v) for v in M["words"]):
                        host = M; break
                if host is not None:
                    host.setdefault("adopted", []).append(w)
                else:
                    keep.append(w)
            L["words"] = keep
        for L in lines:
            L["words"].extend(L.pop("adopted", []))
        merged = [L for L in lines if L["words"]]
        segs = []
        for L in merged:
            L["words"].sort(key=lambda w: w["x0"])
            cur = [L["words"][0]]
            for w in L["words"][1:]:
                gap = w["x0"] - cur[-1]["x1"]
                at_gutter = gutter is not None and cur[-1]["x1"] <= gutter[0] + 3 and w["x0"] >= gutter[1] - 3 and gap > 2
                if gap > max(2.2 * L["ref"], 10) or at_gutter:
                    segs.append(cur); cur = [w]
                else:
                    cur.append(w)
            segs.append(cur)
        res = []
        for sg in segs:
            ref = max(w["size"] for w in sg)
            main_ws = [w for w in sg if w["size"] >= 0.8 * ref]
            res.append({"words": sg, "x0": min(w["x0"] for w in sg), "x1": max(w["x1"] for w in sg),
                        "top": min(w["top"] for w in main_ws), "bottom": max(w["bottom"] for w in main_ws),
                        "size": statistics.median(w["size"] for w in main_ws), "text": " ".join(w["text"] for w in sg)})
        return res

    # column gutter: right edge of left-column text and left edge of right-column text (modes)
    for pg in pages:
        pg["lines"] = make_lines(pg)
    # every right-column line starts at the same x and every justified left-column line ends at the same x
    rx = Counter(round(w["x0"]) for pg in pages for w in pg["words"] if 0.45 * pg["W"] < w["x0"] < 0.6 * pg["W"] and w["size"] >= body * 0.8)
    lx = Counter(round(w["x1"]) for pg in pages for w in pg["words"] if 0.4 * pg["W"] < w["x1"] < 0.55 * pg["W"] and w["size"] >= body * 0.8)
    gutter = None
    if rx and lx and rx.most_common(1)[0][1] >= 4 and lx.most_common(1)[0][1] >= 4:
        gutter = (lx.most_common(1)[0][0], rx.most_common(1)[0][0])
        if 1 < gutter[1] - gutter[0] < 0.12 * pages[0]["W"]:
            for pg in pages:
                pg["lines"] = make_lines(pg, gutter)

    # ---------------------------------------------------------- 2. headers / footers
    key = lambda t: re.sub(r"\d+", "#", t.strip().lower())
    edge = Counter()
    for pg in pages:
        for L in pg["lines"]:
            if L["top"] < 0.08 * pg["H"] or L["bottom"] > 0.92 * pg["H"]:
                edge[key(L["text"])] += 1
    for pg in pages:
        keep = []
        for L in pg["lines"]:
            at_edge = L["top"] < 0.08 * pg["H"] or L["bottom"] > 0.92 * pg["H"]
            if (L["top"] < 0.1 * pg["H"] or L["bottom"] > 0.88 * pg["H"]) and re.fullmatch(r"(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?", L["text"].strip().lower()):
                continue
            if at_edge and (edge[key(L["text"])] >= max(2, 0.3 * npages) or re.fullmatch(r"(page\s*)?#(\s*(of|/)\s*#)?", key(L["text"]))):
                continue
            keep.append(L)
        pg["lines"] = keep

    # ---------------------------------------------------------- 3. reading order
    for pg in pages:
        Wp = pg["W"]
        for L in pg["lines"]:
            wdt = L["x1"] - L["x0"]
            if wdt > 0.55 * Wp or (L["x0"] < 0.42 * Wp and L["x1"] > 0.58 * Wp):
                L["col"] = "full"
            elif L["x1"] <= 0.56 * Wp:
                L["col"] = "left"
            else:
                L["col"] = "right"
        fulls = sorted(L["top"] for L in pg["lines"] if L["col"] == "full")
        import bisect
        for L in pg["lines"]:
            band = bisect.bisect_right(fulls, L["top"] + 0.1)
            L["key"] = (band, 0 if L["col"] in ("full", "left") else 1, L["top"], L["x0"])
        pg["lines"].sort(key=lambda L: L["key"])
    n_right = sum(1 for pg in pages for L in pg["lines"] if L["col"] == "right")
    n_all = sum(len(pg["lines"]) for pg in pages) or 1
    two_col = n_right > 0.15 * n_all
    for pg in pages:
        Wp = pg["W"]
        for L in pg["lines"]:
            if L["col"] == "full" or not two_col:
                L["span"] = (0.0, Wp)
            elif L["col"] == "left":
                L["span"] = (0.0, Wp / 2)
            else:
                L["span"] = (Wp / 2, Wp)
        pg["two_col"] = two_col
        if not two_col:
            for L in pg["lines"]:
                L["col"] = "full"

    def body_like(L):
        return abs(L["size"] - body) <= 1 and (L["x1"] - L["x0"]) > 0.6 * (L["span"][1] - L["span"][0]) * (0.85 if L["col"] != "full" else 0.75)

    # ---------------------------------------------------------- 4. figure / table regions
    figs_found = []   # (pno, kind, caption_line_index, region bbox or ("page", n), table rows or None)
    used_fig_pages = set()
    for pno, pg in enumerate(pages):
        lines = pg["lines"]
        pg.setdefault("consumed", set())
        tables = []
        try:
            tables = pg["page"].find_tables()
        except Exception:
            tables = []
        graphics = [(float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"])) for o in
                    list(pg["page"].images) + list(pg["page"].rects) + list(pg["page"].curves) + list(pg["page"].lines)]
        for i, L in enumerate(lines):
            m = CAP_RE.match(L["text"])
            if not m or i in pg["consumed"]:
                continue
            first_bold = _style(L["words"][0]["fontname"])[0]
            after = L["text"][m.end():].lstrip()[:1]
            if after in (";", ",", ")", "]"):
                continue  # an in-text reference such as "(Figure 2C; ...)"
            prev_same = [x for x in lines[:i] if x["col"] == L["col"] and x["bottom"] <= L["top"]]
            gap_before = (L["top"] - prev_same[-1]["bottom"]) if prev_same else 99
            labelled = re.match(CAP_RE.pattern + r"\s*[:.|\u2014\u2013-]", L["text"], re.I)
            if not (labelled or first_bold and (abs(L["size"] - body) > 0.5 or gap_before > 0.8 * L["size"])):
                continue
            is_tab = bool(TAB_RE.match(L["text"]))
            sx0, sx1 = L["span"]
            if not is_tab:
                # region: from the last body-like line above (same span) to the caption top
                stop = [x for x in lines if x["bottom"] <= L["top"] - 1 and x["x1"] > sx0 and x["x0"] < sx1 and not CAP_RE.match(x["text"])
                        and (body_like(x) or x["col"] == "full" and (x["x1"] - x["x0"]) > 0.3 * pg["W"] or x["size"] >= body * 1.1)]
                top = max([x["bottom"] for x in stop], default=0.04 * pg["H"])
                region = [sx0, top + 2, sx1, L["top"] - 1]
                gs = [g for g in graphics if g[1] >= top - 2 and g[3] <= L["top"] + 2 and g[2] > sx0 and g[0] < sx1 and (g[2] - g[0]) * (g[3] - g[1]) > 4]
                inner = [x for x in lines if x["top"] >= top and x["bottom"] <= L["top"] and x["x1"] > sx0 and x["x0"] < sx1]
                if gs:  # graphics define the figure; keep only labels that sit on or right next to them
                    gy0, gy1 = min(g[1] for g in gs), max(g[3] for g in gs)
                    inner = [x for x in inner if x["bottom"] >= gy0 - 2 * body and x["top"] <= gy1 + 2 * body]
                boxes = gs + [(x["x0"], x["top"], x["x1"], x["bottom"]) for x in inner]
                if boxes:
                    region = [max(sx0, min(b[0] for b in boxes) - 4), max(top, min(b[1] for b in boxes) - 4),
                              min(sx1, max(b[2] for b in boxes) + 4), min(L["top"] - 1, max(b[3] for b in boxes) + 4)]
                if region[3] - region[1] < 20:
                    # full-page figure on the neighbouring page (caption on the next/previous page)
                    for q in (pno - 1, pno + 1):
                        if 0 <= q < npages and len(pages[q]["words"]) < 60 and q not in used_fig_pages:
                            used_fig_pages.add(q)
                            pages[q]["consumed"] = set(range(len(pages[q]["lines"])))
                            figs_found.append((pno, "figure", i, ("page", q), None))
                            break
                    continue
                for j, x in enumerate(lines):
                    if x["top"] >= region[1] - 1 and x["bottom"] <= region[3] + 1 and x["x0"] >= region[0] - 2 and x["x1"] <= region[2] + 2:
                        pg["consumed"].add(j)
                figs_found.append((pno, "figure", i, region, None))
            else:
                best = None
                for t in tables:
                    x0, t0, x1, t1 = t.bbox
                    if x1 > sx0 and x0 < sx1:
                        d = t0 - L["bottom"] if t0 >= L["bottom"] - 2 else L["top"] - t1
                        if d >= -2 and (best is None or d < best[0]):
                            best = (d, t)
                rows, region = None, None
                cap_end = L["bottom"]
                k = i + 1
                while k < len(lines) and lines[k]["col"] == L["col"] and lines[k]["top"] - lines[k - 1]["bottom"] < 0.6 * body and not body_like(lines[k]) is False and lines[k]["top"] > L["top"]:
                    cap_end = lines[k]["bottom"]; k += 1
                if best and best[0] < 0.4 * pg["H"]:
                    rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in best[1].extract()]
                    region = list(best[1].bbox)
                else:
                    below = [x for x in lines if x["top"] > cap_end + 2 and x["span"][0] <= sx0 + 1 and x["span"][1] >= sx1 - 1 and (body_like(x) or x["size"] >= body * 1.1 or SECTION_NAMES.match(x["text"].strip())) and not CAP_RE.match(x["text"])]
                    bottom = min([x["top"] for x in below], default=0.95 * pg["H"])
                    inner = [x for x in lines if x["top"] > cap_end + 1 and x["bottom"] < bottom and x["x1"] > sx0 and x["x0"] < sx1]
                    if inner:
                        region = [max(sx0, min(x["x0"] for x in inner) - 4), cap_end + 2, min(sx1, max(x["x1"] for x in inner) + 4), max(x["bottom"] for x in inner) + 4]
                        gs = [g for g in graphics if g[1] >= cap_end - 2 and g[3] <= bottom + 2 and g[2] > sx0 and g[0] < sx1]
                        if gs:
                            region[1] = min(region[1], max(cap_end + 1, min(g[1] for g in gs) - 2)); region[3] = max(region[3], max(g[3] for g in gs) + 2)
                        for strat in ({"vertical_strategy": "text", "horizontal_strategy": "lines"}, {"vertical_strategy": "text", "horizontal_strategy": "text"}):
                            try:
                                tb = pg["page"].crop(tuple(region)).extract_table(strat)
                            except Exception:
                                tb = None
                            if tb and len(tb) >= 2 and max(len(r) for r in tb) >= 2:
                                rows = []
                                for r in tb:
                                    parts = [(c or "").split("\n") for c in r]
                                    ks = {len(pp) for pp, c in zip(parts, r) if (c or "").strip()}
                                    if len(ks) == 1 and ks.pop() > 1:
                                        k = len(next(pp for pp, c in zip(parts, r) if (c or "").strip()))
                                        rows += [[(pp[i] if len(pp) == k else "").strip() for pp in parts] for i in range(k)]
                                    elif any((c or "").strip() for c in r):
                                        rows.append([(c or "").replace("\n", " ").strip() for c in r])
                                break
                    else:
                        region = [sx0, cap_end + 2, sx1, bottom - 2]
                    if region[3] - region[1] < 12:
                        continue
                for j, x in enumerate(lines):
                    if j != i and x["top"] >= region[1] - 1 and x["bottom"] <= region[3] + 1 and x["x0"] >= region[0] - 2 and x["x1"] <= region[2] + 2:
                        pg["consumed"].add(j)
                figs_found.append((pno, "table", i, region, rows))

    # ---------------------------------------------------------- 4b. display equations -> cropped images
    MATHF = re.compile(r"cmmi|cmsy|cmex|msbm|msam|math|symbol|stix|cambriamath|mtextra|euler|rsfs|lmroman.*math", re.I)
    eqs_found = []
    for pno, pg in enumerate(pages):
        lines = pg["lines"]
        cand = []
        for j, L in enumerate(lines):
            if j in pg["consumed"] or body_like(L) and "\ufffd" not in L["text"]:
                continue
            chars = sum(len(w["text"]) for w in L["words"]) or 1
            mathc = sum(len(w["text"]) for w in L["words"] if MATHF.search(w["fontname"] or "") or w.get("cid"))
            if "\ufffd" in L["text"] or (mathc / chars >= 0.5 and len(L["text"]) < 140):
                cand.append(j)
        groups = []
        for j in sorted(cand, key=lambda j: (lines[j]["key"][0], lines[j]["key"][1], lines[j]["top"])):
            L = lines[j]
            if groups and lines[groups[-1][-1]]["col"] == L["col"] and L["top"] - max(lines[k]["bottom"] for k in groups[-1]) < 1.6 * body:
                groups[-1].append(j)
            else:
                groups.append([j])
        for g in groups:
            sx0, sx1 = lines[g[0]]["span"]
            col = lines[g[0]]["col"]
            changed = True
            while changed:  # pull in adjacent short non-body lines (numerators, denominators, equation numbers)
                changed = False
                gt = min(lines[k]["top"] for k in g)
                gb = max(lines[k]["bottom"] for k in g)
                for k, x in enumerate(lines):
                    if k in g or k in pg["consumed"] or x["col"] != col or body_like(x) or len(x["text"]) > 140:
                        continue
                    if CAP_RE.match(x["text"]) or x["size"] >= body * 1.1 or SECTION_NAMES.match(x["text"].strip()):
                        continue
                    xc = sum(len(w["text"]) for w in x["words"]) or 1
                    xm = sum(len(w["text"]) for w in x["words"] if MATHF.search(w["fontname"] or "") or w.get("cid"))
                    if xm / xc < 0.15 and re.search(r"[A-Za-z]{3,}", x["text"]):
                        continue  # a short prose line (end of a paragraph), not part of the equation
                    if x["top"] <= gb + 1.2 * body and x["bottom"] >= gt - 1.2 * body:
                        g.append(k); changed = True
            gt = min(lines[k]["top"] for k in g) - 2
            gb = max(lines[k]["bottom"] for k in g) + 2
            band = [k for k, x in enumerate(lines) if k not in pg["consumed"] and x["top"] >= gt - 1 and x["bottom"] <= gb + 1 and x["x1"] > sx0 and x["x0"] < sx1 and not body_like(x)]
            if not band:
                continue
            region = [min(lines[k]["x0"] for k in band) - 3, gt, max(lines[k]["x1"] for k in band) + 3, gb]
            num = next((m.group(1) for k in band for m in [re.search(r"\((\d+[a-z]?)\)\s*$", lines[k]["text"])] if m), None)
            for k in band:
                pg["consumed"].add(k)
            eqs_found.append((pno, min(band, key=lambda k: lines[k]["key"]), region, num))

    # ---------------------------------------------------------- 5. paragraphs
    def word_html(w, line_bottom, ref):
        t = htmlmod.escape(w["text"], quote=False)
        bold, ital = _style(w["fontname"])
        if w["size"] < ref * 0.8:
            if w["bottom"] < line_bottom - 0.2 * ref:
                return f"<sup>{t}</sup>", ("sup",)
            return f"<sub>{t}</sub>", ("sub",)
        if bold:
            t = f"<strong>{t}</strong>"
        if ital:
            t = f"<em>{t}</em>"
        return t, ()

    def line_html(L):
        parts, prev = [], None
        ref = L["size"]
        base = L["bottom"]
        for w in L["words"]:
            h, _ = word_html(w, base, ref)
            if prev is not None and w["x0"] - prev["x1"] > 0.12 * min(w["size"], prev["size"]) and not (w["size"] < ref * 0.8 and w["x0"] - prev["x1"] < 1.0):
                parts.append(" ")
            parts.append(h)
            prev = w
        s = "".join(parts)
        return re.sub(r"</(strong|em|sup|sub)><\1>", "", s)

    seen_section = [False]

    def is_heading(L, nxt):
        t = L["text"].strip()
        if L["pno"] == 0 and not seen_section[0] and not SECTION_NAMES.match(t) and not NUM_HEAD.match(t):
            return None
        if len(t) > 120 or len(t) < 2 or CAP_RE.match(t):
            return None
        bold = all(_style(w["fontname"])[0] for w in L["words"] if w["size"] >= L["size"] * 0.8)
        bigger = L["size"] >= body * 1.12
        if SECTION_NAMES.match(t) and (bold or bigger or t.isupper()):
            return "h2"
        if not (bold or bigger) or t.endswith(".") and not NUM_HEAD.match(t):
            return None
        m = NUM_HEAD.match(t)
        if m:
            return "h2" if "." not in m.group(1) else "h3"
        return "h2" if L["size"] >= body * 1.3 else "h3"

    def is_italic_head(L, nxt):
        t = L["text"].strip()
        if len(t) > 80 or t.endswith((".", ",", ";")) or CAP_RE.match(t) or not nxt:
            return False
        main_ws = [w for w in L["words"] if w["size"] >= 0.8 * L["size"]]
        ital = main_ws and all(_style(w["fontname"])[1] for w in main_ws)
        return bool(ital) and abs(L["size"] - body) <= 1 and body_like(nxt) and nxt["top"] > L["bottom"]

    stream = []
    for pno, pg in enumerate(pages):
        for j, L in enumerate(pg["lines"]):
            if j in pg["consumed"]:
                continue
            L["pno"], L["j"] = pno, j
            stream.append(L)

    cap_at = {(p, i): (k, r, rows) for p, k, i, r, rows in figs_found}
    eq_at = {(p, i): (r, num) for p, i, r, num in eqs_found}
    for p_, i_, r_, n_ in eqs_found:  # re-insert the anchor line of each equation into the stream
        L = pages[p_]["lines"][i_]
        L["pno"], L["j"] = p_, i_
        stream.append(L)
    stream.sort(key=lambda L: (L["pno"], L["key"]))
    title_done = False
    paras = []  # dicts: kind, lines
    cur = None
    in_refs = False
    numbered_refs = [False]
    first_page_max = max((L["size"] for L in stream if L["pno"] == 0), default=body)

    def close():
        nonlocal cur
        if cur:
            paras.append(cur)
        cur = None

    for idx, L in enumerate(stream):
        nxt = stream[idx + 1] if idx + 1 < len(stream) else None
        text = L["text"].strip()
        if (L["pno"], L["j"]) in eq_at:
            close()
            paras.append({"kind": "equation", "lines": [L], "eq": (L["pno"],) + eq_at[(L["pno"], L["j"])]})
            continue
        if (L["pno"], L["j"]) in cap_at:
            close()
            k, r, rows = cap_at[(L["pno"], L["j"])]
            cur = {"kind": "caption", "lines": [L], "fig": (L["pno"], k, r, rows)}
            continue
        if not title_done and L["pno"] == 0 and L["size"] >= first_page_max - 0.5 and L["size"] > body * 1.15:
            if cur and cur["kind"] == "title":
                cur["lines"].append(L); continue
            close(); cur = {"kind": "title", "lines": [L]}; continue
        if cur and cur["kind"] == "title":
            title_done = True; close()
        h = is_heading(L, nxt) or ("h3" if is_italic_head(L, nxt) else None)
        if h:
            seen_section[0] = True
            if cur and cur["kind"] == h and cur["lines"][-1]["pno"] == L["pno"] and L["top"] - cur["lines"][-1]["bottom"] < L["size"] * 0.8:
                cur["lines"].append(L); continue
            close(); cur = {"kind": h, "lines": [L]}
            in_refs = bool(REF_HEAD.match(re.sub(r"^\d+(\.\d+)*\.?\s*", "", text))) if h == "h2" or REF_HEAD.match(text) else in_refs
            continue
        if cur is None or cur["kind"] in ("h2", "h3", "title"):
            close(); cur = {"kind": "ref" if in_refs else "p", "lines": [L]}; continue
        prev = cur["lines"][-1]
        if in_refs and cur["kind"] == "ref" and re.match(r"^\[?\d{1,3}[\].)]\s", cur["lines"][0]["text"]):
            numbered_refs[0] = True
        new = False
        same_flow = prev["pno"] == L["pno"] and prev["col"] == L["col"] and prev["key"][0] == L["key"][0] or (prev["pno"] == L["pno"] and prev["col"] == L["col"])
        gap = L["top"] - prev["bottom"]
        if abs(L["size"] - prev["size"]) > 1.2:
            new = True
        elif same_flow and gap > 0.9 * L["size"]:
            new = True
        elif same_flow and L["x0"] - prev["x0"] > 0.8 * body and prev["x1"] < L["span"][1] - 3 * body:
            new = True
        elif same_flow and L["x0"] - prev["x0"] > 0.8 * body and cur["kind"] != "caption" and len(cur["lines"]) > 1 and abs(cur["lines"][-2]["x0"] - prev["x0"]) < 2:
            new = True
        elif not same_flow:
            ends = prev["text"].rstrip()[-1:] in ".!?:"
            new = ends and (L["text"][:1].isupper() or L["text"][:1].isdigit())
        elif prev["x1"] < prev["span"][1] - 0.2 * (prev["span"][1] - prev["span"][0]) and prev["text"].rstrip()[-1:] in ".!?:" and cur["kind"] != "caption":
            new = True
        if in_refs and numbered_refs[0]:
            new = bool(re.match(r"^\[?\d{1,3}[\].)]\s", text)) or abs(L["size"] - prev["size"]) > 1.2

        if cur["kind"] == "caption" and new is False and CAP_RE.match(text):
            new = True
        if new:
            close(); cur = {"kind": "ref" if in_refs else "p", "lines": [L]}
        else:
            cur["lines"].append(L)
    close()

    if not any(P["kind"] == "title" for P in paras):
        for P in paras:
            if P["kind"] in ("h2", "h3", "caption", "equation"):
                break
            if P["lines"][0]["pno"] == 0 and all(_style(w["fontname"])[0] for L in P["lines"] for w in L["words"] if w["size"] >= 0.8 * L["size"]):
                P["kind"] = "title"
                break

    def para_html(ls):
        out = ""
        for L in ls:
            h = line_html(L)
            if not out:
                out = h
            elif re.search(r"[A-Za-z]-$", out) and re.match(r"[a-z]", L["text"]):
                out = out[:-1] + h
            else:
                out += " " + h
        return out

    # ---------------------------------------------------------- 6. blocks
    b = Builder(max_w, lambda s: None)
    fig_media = Path(out) / "pdf_figs"
    fig_media.mkdir(parents=True, exist_ok=True)
    for P in paras:
        h = para_html(P["lines"])
        t = re.sub(r"<[^>]+>", "", h)
        if P["kind"] == "title":
            b.add("title", h)
        elif P["kind"] in ("h2", "h3"):
            b.add(P["kind"], htmlmod.unescape(t).strip().rstrip(":"))
            if P["kind"] == "h2":
                b.in_refs = bool(REF_HEAD.match(re.sub(r"^\d+(\.\d+)*\.?\s*", "", htmlmod.unescape(t).strip())))
        elif P["kind"] == "caption":
            pno, kind, region, rows = P["fig"]
            if kind == "table" and rows:
                b.ntab += 1
                tid, label = slug_label(htmlmod.unescape(t), "table", b.ntab)
                b.blocks.append({"id": b.uid(tid), "kind": "table", "html": "", "rows": [[htmlmod.escape(c) for c in r] for r in rows],
                                 "caption": h, "label": label})
                continue
            if isinstance(region, tuple) and region[0] == "page":
                from PIL import ImageChops
                im = render(region[1])
                bbox = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
                crop = im.crop(bbox) if bbox else im
            else:
                crop = render(pno).crop(tuple(int(v * SCALE) for v in region))
            b.nfig += 1
            fid, label = slug_label(htmlmod.unescape(t), "table" if kind == "table" else "figure", b.nfig)
            fid = b.uid(fid)
            path_ = fig_media / f"{fid}.png"
            crop.save(path_)
            uri, size = compress(crop, max_w)
            b.imgs[fid] = {"src": uri, "w": size[0], "h": size[1]}
            b.figs[fid] = {"media": str(path_), "label": label, "w": crop.width, "h": crop.height, "page": pno + 1}
            b.blocks.append({"id": fid, "kind": "figure", "html": "", "fig": fid, "caption": h, "label": label})
        elif P["kind"] == "equation":
            pno, region, num = P["eq"]
            crop = render(pno).crop(tuple(int(v * SCALE) for v in region))
            b.pc += 1
            fid = b.uid(f"eq-{num}" if num else f"eq-x{b.pc}")
            label = f"Equation ({num})" if num else "Equation"
            path_ = fig_media / f"{fid}.png"
            crop.save(path_)
            uri, size = compress(crop, max_w)
            b.imgs[fid] = {"src": uri, "w": size[0], "h": size[1]}
            b.figs[fid] = {"media": str(path_), "label": label, "w": crop.width, "h": crop.height, "page": pno + 1}
            b.blocks.append({"id": fid, "kind": "figure", "html": "", "fig": fid, "caption": f"<em>{label}</em>", "label": label, "equation": True})
        elif P["kind"] == "ref":
            m = re.match(r"\s*\[?(\d+)[\].)]", t)
            b.add("ref", h, id=f"ref-{m.group(1)}" if m else f"ref-x{b.pc + 1}")
        else:
            b.add("p", h)

    # ---------------------------------------------------------- 7. PDF annotations -> comments
    comments = []
    for pg in pages:
        page = pg["page"]
        for an in (page.annots or []):
            data = an.get("data") or {}
            sub = str(data.get("Subtype", "")).strip("/'\" ")
            if sub in ("Link", "Widget", "Popup"):
                continue
            contents = (an.get("contents") or "").strip()
            author = (an.get("title") or "").strip()
            quote = ""
            if sub in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                try:
                    bb = (max(0, an["x0"] - 1.5), max(0, an["top"] - 1), min(pg["W"], an["x1"] + 1.5), min(pg["H"], an["bottom"] + 1))
                    quote = " ".join((page.within_bbox(bb).extract_text(x_tolerance=1.2) or "").split())
                except Exception:
                    quote = ""
            else:  # sticky note: quote the line it sits next to
                near = sorted(pg["lines"], key=lambda L: abs((L["top"] + L["bottom"]) / 2 - (an["top"] + an["bottom"]) / 2))
                quote = near[0]["text"] if near else ""
            if not contents and sub == "Highlight":
                contents = "(highlight)"
            if contents or quote:
                comments.append({"author": author, "text": contents, "exact": quote})

    n_img_tables = sum(1 for bl in b.blocks if bl["kind"] == "figure" and bl["label"].startswith("Table"))
    print(f"pdf: {npages} pages, body text {body}pt, two-column pages {sum(1 for p in pages if p['two_col'])}; "
          f"tables kept as images: {n_img_tables}. Review outline.txt and the figure crops (pdf_figs/).")
    return b.blocks, b.imgs, b.figs, comments
