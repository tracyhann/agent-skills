#!/usr/bin/env python3
"""
Carry text edits made in the review page back to the LaTeX source.

    python apply_edits.py DOC_DIR EDITS SOURCE OUT_DIR

DOC_DIR  the extraction folder the page was built from (texts.json holds the original text)
EDITS    the page's Export JSON ({"edits": [...]}) or the folder read_db wrote for the
         "edits" collection (…/edits/*.json)
SOURCE   the LaTeX project folder, a .zip of it, or a single .tex
OUT_DIR  receives:
           project/          a patched COPY of the project (only .tex files change)
           changes.diff      unified diff of every changed file
           apply_report.md   what was applied where (file:line) and what needs a manual fix
           hunks.json        every hunk (block, before/after, context, status) - also the input
                             for carrying edits into a Word file with tracked changes

Each edit is split into word-level hunks (a rewritten phrase is one hunk). A hunk is located in
the .tex files through a normalized view of the source: comments dropped, whitespace collapsed,
\\emph{}-style wrappers unwrapped, simple \\newcommand macros expanded, dashes and quotes mapped,
and citations, cross-references, maths and other commands kept as barriers. The hunk is applied
only when its surrounding words identify one place and the replaced span stays brace-balanced;
everything else is listed for a manual fix. The source is never modified in place.
"""
import argparse
import difflib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

BARRIER = "\ue000"
WRAPPERS = {"emph", "textbf", "textit", "textrm", "textsf", "texttt", "textsc", "textup", "textmd", "textnormal",
            "mbox", "text", "underline", "uline", "textsuperscript", "textsubscript"}
# arguments: t = rendered text (searchable), b = not rendered as text (barrier)
ARGS = {"title": "t", "section": "t", "subsection": "t", "subsubsection": "t", "chapter": "t", "paragraph": "t",
        "subparagraph": "t", "caption": "t", "footnote": "t", "keywords": "t", "author": "t",
        "captionof": "bt", "textcolor": "bt", "colorbox": "bt", "href": "bt"}
ESCAPES = {"%": "%", "&": "&", "_": "_", "#": "#", "$": "$", "{": "{", "}": "}", " ": " ", ",": " ", ";": " ", ":": " ", "!": ""}
CANON = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2018": "'", "\u2019": "'", "\u201a": "'",
                       "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ", "\u2009": " ", "\u202f": " "})


def canon(s):
    return re.sub(r"\s+", " ", (s or "").translate(CANON))


def read_group(s, i):
    """s[i] == '{' -> index after the matching '}' (or len(s))."""
    d, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return j + 1
        j += 1
    return len(s)


def simple_macros(tex_files):
    """Zero-argument \\newcommand whose body is plain text, e.g. \\newcommand{\\method}{GraphNet}."""
    out = {}
    for t in tex_files:
        for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z@]+)\}?\s*\{([^{}\\]*)\}", t):
            out[m.group(1)] = m.group(2)
    return out


def normalize(src, macros):
    """Plain-ish view of LaTeX source plus a map from each output char to its source index."""
    out, idx, end = [], [], []
    i, n = 0, len(src)
    brace_stack = []

    def emit(ch, pos, stop=None):
        if ch == " " and out and out[-1] == " ":
            end[-1] = stop if stop is not None else pos + 1
            return
        out.append(ch)
        idx.append(pos)
        end.append(stop if stop is not None else pos + 1)
    while i < n:
        c = src[i]
        if c == "%":
            j = src.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c.isspace() or c == "~":
            emit(" ", i); i += 1; continue
        if c == "-" and src.startswith("--", i):
            k = 3 if src.startswith("---", i) else 2
            emit("-", i, i + k); i += k; continue
        if src.startswith("``", i) or src.startswith("''", i):
            emit('"', i, i + 2); i += 2; continue
        if c == "`":
            emit("'", i); i += 1; continue
        if c == "$" or src.startswith("\\(", i) or src.startswith("\\[", i):
            if c == "$":
                j = src.find("$$", i + 2) + 2 if src.startswith("$$", i) else src.find("$", i + 1) + 1
            else:
                j = src.find("\\)" if src[i + 1] == "(" else "\\]", i + 2) + 2
            j = j if j > i else n
            emit(BARRIER, i, j); i = j; continue
        if c == "\\":
            if i + 1 < n and src[i + 1] in ESCAPES:
                ch = ESCAPES[src[i + 1]]
                if ch:
                    emit(ch, i, i + 2)
                i += 2; continue
            if src.startswith("\\\\", i):
                emit(" ", i, i + 2); i += 2; continue
            m = re.match(r"\\([A-Za-z@]+)\*?", src[i:])
            if not m:
                emit(BARRIER, i, i + 2); i += 2; continue
            name, j = m.group(1), i + m.end()
            if name in WRAPPERS and j < n and src[j] == "{":
                brace_stack.append("wrap")
                i = j + 1
                continue
            if name in ARGS:
                k = j
                while k < n and src[k] == "[":
                    e = src.find("]", k)
                    k = e + 1 if e > 0 else n
                spec = ARGS[name]
                for kind in spec[:-1]:          # leading non-text arguments
                    while k < n and src[k].isspace():
                        k += 1
                    if k < n and src[k] == "{":
                        k = read_group(src, k)
                while k < n and src[k].isspace():
                    k += 1
                if k < n and src[k] == "{":
                    emit(BARRIER, i, k)
                    brace_stack.append("wrap")
                    i = k + 1
                    continue
                emit(BARRIER, i, k); i = k; continue
            if name in macros:
                k = j + 2 if src.startswith("{}", j) else j
                for ch in macros[name]:
                    emit(ch, i, k)
                i = k; continue
            # any other command: swallow optional/required arguments as one barrier
            k = j
            while k < n and src[k] in "[{":
                if src[k] == "{":
                    k = read_group(src, k)
                else:
                    e = src.find("]", k)
                    k = e + 1 if e > 0 else n
            emit(BARRIER, i, k); i = k; continue
        if c == "{":
            brace_stack.append("group"); i += 1; continue
        if c == "}":
            if brace_stack:
                brace_stack.pop()
            i += 1; continue
        emit(c, i); i += 1
    return "".join(out), idx, end


def to_latex(s):
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "\u201c": "``", "\u201d": "''", "\u2018": "`", "\u2019": "'",
           "\u2013": "--", "\u2014": "---", "\u00a0": "~"}
    return "".join(rep.get(ch, ch) for ch in s)


def tokens(s):
    return re.findall(r"\s+|\w+|[^\w\s]", s or "")


def hunks_for(before, after):
    a, b = tokens(before), tokens(after)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    groups = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if groups and all(t.isspace() for t in a[groups[-1]["i2"]:i1]):
            groups[-1]["i2"], groups[-1]["j2"] = i2, j2
        else:
            groups.append({"i1": i1, "i2": i2, "j1": j1, "j2": j2})
    out = []
    for g in groups:
        out.append({"old": "".join(a[g["i1"]:g["i2"]]), "new": "".join(b[g["j1"]:g["j2"]]),
                    "left": a[max(0, g["i1"] - 14):g["i1"]], "right": a[g["i2"]:g["i2"] + 14]})
    return out


def locate(h, files):
    """Try shrinking context until the hunk matches exactly one place. Returns (file, s, e) or reason."""
    for n in (14, 8, 5, 3, 2, 1, 0):
        old = canon(h["old"])
        left, right = canon("".join(h["left"][-n:]) if n else ""), canon("".join(h["right"][:n]) if n else "")
        if left.endswith(" ") and old.startswith(" "):
            old = old[1:]
        if (old or left).endswith(" ") and right.startswith(" "):
            right = right[1:]
        if not old.strip() and not (left.strip() and right.strip()):
            continue
        needle = left + old + right
        if len(needle.strip()) < 12 and n:      # too short to be distinctive
            continue
        if n == 0 and len(old.strip()) < 12:     # a bare short word says nothing about where it is
            break
        hits = []
        for f, (norm, idx, end) in files.items():
            k = norm.find(needle)
            while k >= 0:
                hits.append((f, k))
                k = norm.find(needle, k + 1)
        if len(hits) == 1:
            f, k = hits[0]
            norm, idx, end = files[f]
            s, e = k + len(left), k + len(left) + len(old)
            if BARRIER in norm[s:e]:
                return "the changed text spans a citation, reference, maths or command"
            if s == e:
                pos = idx[s] if s < len(idx) else end[-1]
                return (f, pos, pos)
            return (f, idx[s], end[e - 1])
        if len(hits) > 1 and n == 0:
            return f"the text occurs {len(hits)} times; context did not single one out"
    return "not found in the source: the surrounding text is probably generated there (\\ref/\\Cref, \\cite, maths or a macro)"


def balanced(s):
    d = 0
    for i, c in enumerate(s):
        if c == "{" and (i == 0 or s[i - 1] != "\\"):
            d += 1
        elif c == "}" and (i == 0 or s[i - 1] != "\\"):
            d -= 1
            if d < 0:
                return False
    return d == 0


def cell_texts_from_html(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("annotation"):
        a.decompose()
    cap = soup.select_one(".tcap")
    rows = [[td.get_text() for td in tr.find_all(["td", "th"])] for tr in soup.find_all("tr")]
    return (cap.get_text() if cap else ""), rows


def table_hunks(block, edit_html):
    """Diff a table cell by cell; context is the neighbouring cells joined by ' & ' as in the source."""
    from bs4 import BeautifulSoup
    txt = lambda h: BeautifulSoup(re.sub(r"<annotation.*?</annotation>", "", h or "", flags=re.S), "html.parser").get_text()
    old_rows = [[txt(c) for c in r] for r in block.get("rows", [])]
    new_cap, new_rows = cell_texts_from_html(edit_html)
    out = []
    old_cap = txt(block.get("caption", ""))
    if canon(old_cap) != canon(new_cap):
        out += [dict(h, cell="caption") for h in hunks_for(old_cap, new_cap)]
    if [len(r) for r in old_rows] != [len(r) for r in new_rows]:
        return out, "the table's rows or columns changed; apply by hand"
    for ri, (ro, rn) in enumerate(zip(old_rows, new_rows)):
        for ci, (co, cn) in enumerate(zip(ro, rn)):
            if canon(co).strip() == canon(cn).strip():
                continue
            left = " & ".join(x.strip() for x in ro[:ci]) + (" & " if ci else "")
            right = (" & " if ci < len(ro) - 1 else "") + " & ".join(x.strip() for x in ro[ci + 1:])
            for h in hunks_for(co.strip(), cn.strip()):
                h["left"] = tokens(left) + h["left"]
                h["right"] = h["right"] + tokens(right)
                out.append(dict(h, cell=f"row {ri + 1}, column {ci + 1}"))
    return out, None


def load_edits(p):
    p = Path(p)
    if p.is_dir():
        return [json.loads(f.read_text()) for f in sorted(p.rglob("*.json"))]
    d = json.loads(p.read_text())
    return d.get("edits", []) if isinstance(d, dict) else d


def change_md(h):
    o, n = h["old"].strip(), h["new"].strip()
    if not o and not n:
        return "(see reason)"
    if not o:
        return f"insert **{n}**"
    if not n:
        return f"delete ~~{o}~~"
    return f"~~{o}~~ → **{n}**"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_dir"); ap.add_argument("edits"); ap.add_argument("source"); ap.add_argument("out")
    a = ap.parse_args()
    doc = Path(a.doc_dir)
    texts = json.loads((doc / "texts.json").read_text())
    blocks = {b["id"]: b for b in json.loads((doc / "doc.json").read_text())["blocks"]}
    edits = [e for e in load_edits(a.edits) if e.get("block")]
    out = Path(a.out)
    proj = out / "project"
    if proj.exists():
        shutil.rmtree(proj)
    src = Path(a.source)
    if src.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp())
        zipfile.ZipFile(src).extractall(tmp)
        shutil.copytree(tmp, proj)
    elif src.is_dir():
        shutil.copytree(src, proj, ignore=shutil.ignore_patterns("output", ".git"))
    else:
        proj.mkdir(parents=True)
        shutil.copy(src, proj / src.name)
    tex_paths = sorted(proj.rglob("*.tex"))
    raw = {p: p.read_text(errors="ignore") for p in tex_paths}
    macros = simple_macros(raw.values())
    files = {p: normalize(t, macros) for p, t in raw.items()}

    all_hunks, plan = [], {p: [] for p in tex_paths}
    for e in edits:
        bid = e["block"]
        before = texts.get(bid, e.get("baseText", ""))
        after = e.get("text", "")
        where = blocks.get(bid, {}).get("label") or e.get("location") or bid
        kind = blocks.get(bid, {}).get("kind")
        table_note = None
        if kind == "table":
            hs, table_note = table_hunks(blocks[bid], e.get("html", ""))
        else:
            hs = hunks_for(before, after)
        if table_note:
            all_hunks.append({"block": bid, "where": where, "old": "", "new": "", "context": "", "status": "manual", "reason": table_note})
        for h in hs:
            rec = {"block": bid, "where": where + (f" ({h['cell']})" if h.get("cell") else ""), "old": h["old"], "new": h["new"],
                   "context": ("".join(h["left"][-8:]) + "[" + h["old"] + "]" + "".join(h["right"][:8])).strip()}
            if kind == "ref":
                rec.update(status="manual", reason="the reference list is generated from the .bib file: edit the matching entry there (wrap capitals in braces so the style keeps them)")
            else:
                r = locate(h, files)
                if isinstance(r, str):
                    rec.update(status="manual", reason=r)
                else:
                    f, s, t = r
                    if not balanced(raw[f][s:t]):
                        rec.update(status="manual", reason="the span crosses LaTeX braces (e.g. part of an \\emph{})")
                    else:
                        rec.update(status="applied", file=str(f.relative_to(proj)), line=raw[f].count("\n", 0, s) + 1)
                        plan[f].append((s, t, to_latex(h["new"]), rec))
            all_hunks.append(rec)

    diffs = []
    for f, items in plan.items():
        if not items:
            continue
        items.sort(key=lambda x: x[0])
        for x, y in zip(items, items[1:]):
            if y[0] < x[1]:
                y[3].update(status="manual", reason="overlaps another hunk")
        text = raw[f]
        for s, t, new, rec in sorted((it for it in items if it[3]["status"] == "applied"), key=lambda x: -x[0]):
            text = text[:s] + new + text[t:]
        if text != raw[f]:
            f.write_text(text)
            rel = str(f.relative_to(proj))
            diffs += difflib.unified_diff(raw[f].splitlines(True), text.splitlines(True), f"a/{rel}", f"b/{rel}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "changes.diff").write_text("".join(diffs))
    (out / "hunks.json").write_text(json.dumps(all_hunks, ensure_ascii=False, indent=1))
    ok = [h for h in all_hunks if h["status"] == "applied"]
    man = [h for h in all_hunks if h["status"] != "applied"]
    md = [f"# Applying page edits to the LaTeX source", "",
          f"{len(edits)} edited blocks, {len(all_hunks)} changes: {len(ok)} applied, {len(man)} need a manual fix.", "",
          "The patched copy is in `project/`; `changes.diff` shows every change. Review the diff before replacing your files.", ""]
    if ok:
        md += ["## Applied", ""]
        md += [f"- `{h['file']}:{h['line']}` ({h['where']}): {change_md(h)}" for h in ok]
        md.append("")
    if man:
        md += ["## Needs a manual fix", ""]
        md += [f"- **{h['where']}**: {change_md(h)}" + (f"  \n  context: “{h['context']}”" if h['context'] else "") + f"  \n  why: {h['reason']}" for h in man]
    (out / "apply_report.md").write_text("\n".join(md) + "\n")
    print(f"{len(edits)} edits -> {len(all_hunks)} hunks: {len(ok)} applied, {len(man)} manual. See {out / 'apply_report.md'}")


if __name__ == "__main__":
    main()
