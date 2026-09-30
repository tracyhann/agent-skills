#!/usr/bin/env python3
"""
Build the annotation pages from the extracted manuscript.

Live tool (published as an artifact; notes live in the artifact's database, never in the file):
    python build_html.py tool DOC_DIR OUT.html --doc-name "Paper_v3.docx" [--title "..."]

Standalone read-only report (notes baked in; works offline; nothing to publish):
    python build_html.py report DOC_DIR NOTES OUT.html --doc-name "Paper_v3.docx" \
        [--author-map "Claude review=cabbage"] [--include-dismissed] [--date "September 28, 2026"]
  NOTES = a JSON export ({"annotations": [...], "edits": [...], "replies": [...]} or a list), or the
  folder read_db wrote with out_dir (…/annotations/*.json). Text edits made in the page are baked
  in as tracked changes and reply threads under their notes: they come from the export's
  "edits"/"replies", from the sibling edits/ and replies/ folders read_db wrote next to
  annotations/, or from --edits / --replies. Replies are signed like notes (see --author-map).

Both pages open with "Show changes" switched on (suggestions and text edits shown as tracked changes).
"""
import argparse, datetime, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "tool_template.html"

REPORT_PATCHES = [
    ("<title>__TITLE__</title>", "<title>__TITLE__ (snapshot)</title>"),
    ("const IMGS = __IMGS__;", "const IMGS = __IMGS__;\nconst STATIC = __STATIC__;"),
    ("  renderDoc(); render();\n  let db = null;",
     "  renderDoc(); render();\n"
     "  if (STATIC) {\n"
     "    document.body.classList.add('report');\n"
     "    S.readOnly = true; S.status = 'all'; syncStatusSeg();\n"
     "    for (const a of STATIC.notes) S.anns.set(a.id, a);\n"
     "    for (const e of (STATIC.edits || [])) S.edits.set(e.block, e);\n"
     "    for (const c of (STATIC.replies || [])) S.replies.set(c.id, c);\n"
     "    reindexReplies(); refreshEdits();\n"
     "    S.store = 'static';\n"
     "    $('#store').textContent = `Review snapshot: ${STATIC.notes.length} notes, ${STATIC.date}`;\n"
     "    render(); return;\n"
     "  }\n"
     "  let db = null;"),
    ("  else if (e.key === 'b' || e.key === 'B') setMode(S.mode === 'box' ? 'text' : 'box');",
     "  else if ((e.key === 'b' || e.key === 'B') && !S.readOnly) setMode(S.mode === 'box' ? 'text' : 'box');"),
    ("  if (dl) {\n    try { await dl.save({ filename, data }); toast('Saved ' + filename); return; }",
     "  if (!window.claude) {\n"
     "    try {\n"
     "      const type = filename.endsWith('.json') ? 'application/json' : 'text/markdown';\n"
     "      const url = URL.createObjectURL(new Blob([data], { type }));\n"
     "      const a = document.createElement('a'); a.href = url; a.download = filename;\n"
     "      document.body.appendChild(a); a.click(); a.remove();\n"
     "      setTimeout(() => URL.revokeObjectURL(url), 4000); toast('Saved ' + filename); return;\n"
     "    } catch (_) {}\n"
     "  }\n"
     "  if (dl) {\n    try { await dl.save({ filename, data }); toast('Saved ' + filename); return; }"),
    ("@media (max-width: 960px){",
     ".report .bar > .seg, .report #importBtn, .report #addGeneral, .report .pop, .report .rail-tools:has(#statusSeg){display:none!important}\n"
     "@media (max-width: 960px){"),
    ("counts[c.id] || S.cats.has(c.id) || c.id === 'mine')",
     "counts[c.id] || S.cats.has(c.id) || (c.id === 'mine' && !S.readOnly))"),
    ("  $('#count').textContent = `${list.length} shown, ${open} open of ${all.length}`;",
     "  $('#count').textContent = S.store === 'static' ? `${list.length} of ${all.length} notes` : `${list.length} shown, ${open} open of ${all.length}`;"),
]


def J(x):
    return json.dumps(x, ensure_ascii=False).replace("</", "<\\/")


def fill(tpl, doc_dir, doc_name, title):
    doc = json.loads((Path(doc_dir) / "doc.json").read_text())
    imgs = json.loads((Path(doc_dir) / "imgs.json").read_text())
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", doc_name)
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "manuscript"
    rep = {"__TITLE__": title or f"{stem} review notes", "__DOC_NAME__": doc_name, "__SLUG__": slug,
           "__EXPORT_BASE__": re.sub(r"[^A-Za-z0-9_-]+", "_", stem) + "_review_notes"}
    for k, v in rep.items():
        tpl = tpl.replace(k, v.replace("<", "&lt;") if k in ("__TITLE__", "__DOC_NAME__") else v)
    return tpl.replace("__DOC__", J(doc)).replace("__IMGS__", J(imgs))


def load_edits(src, notes_file=False):
    p = Path(src)
    if p.is_dir():
        return [json.loads(f.read_text()) for f in sorted(p.glob("*.json"))]
    d = json.loads(p.read_text())
    if isinstance(d, dict):
        return d.get("edits", [])
    return [] if notes_file else d


def load_replies(src, notes_file=False):
    p = Path(src)
    if p.is_dir():
        return [json.loads(f.read_text()) for f in sorted(p.glob("*.json"))]
    d = json.loads(p.read_text())
    if isinstance(d, dict):
        return d.get("replies", [])
    return [] if notes_file else d


def sibling(src, name):
    """read_db writes each collection to <out_dir>/<collection>/: given .../annotations (or the
    out_dir itself), find another collection's folder next to it."""
    p = Path(src)
    if not p.is_dir():
        return None
    root = p.parent if p.name == "annotations" else p
    return root / name if (root / name).is_dir() else None


def sign(n, amap, unsigned):
    """The label a note or reply shows in the report: its signature, else the account name the
    page exported (authorName), else a mapping; "Page owner" / "Reviewer" when nothing names it."""
    au = n.get("author") or ""
    if "*" in amap:
        n["author"] = amap["*"]
    elif au in amap and (au or not n.get("byOwner")):
        n["author"] = amap[au]
    elif not au:   # signed by account name: use the name the page exported, else a mapping
        n["author"] = n.get("authorName") or (amap.get("@owner") if n.get("byOwner") else "") or ""
    if not n["author"]:
        unsigned.append(n["id"])
        n["author"] = "Page owner" if n.get("byOwner") else "Reviewer"
    n.pop("authorName", None)
    return n


def load_notes(src):
    p = Path(src)
    if p.is_dir():
        if (p / "annotations").is_dir():
            p = p / "annotations"
        files = sorted(p.glob("*.json")) or sorted(p.glob("*/*.json"))
        return [json.loads(f.read_text()) for f in files]
    d = json.loads(p.read_text())
    return d["annotations"] if isinstance(d, dict) else d


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tool"); t.add_argument("doc_dir"); t.add_argument("out")
    r = sub.add_parser("report"); r.add_argument("doc_dir"); r.add_argument("notes"); r.add_argument("out")
    for s in (t, r):
        s.add_argument("--doc-name", required=True); s.add_argument("--title")
    r.add_argument("--author-map", action="append", default=[], help='"old=new", repeatable; "*=name" relabels every author')
    r.add_argument("--include-dismissed", action="store_true")
    r.add_argument("--edits", help="edits export/folder; default: the notes export's own \"edits\" list")
    r.add_argument("--replies", help="replies export/folder; default: the notes export's own \"replies\" list")
    r.add_argument("--date", default=datetime.date.today().strftime("%B %-d, %Y"))
    a = ap.parse_args()

    tpl = TEMPLATE.read_text()
    if a.cmd == "tool":
        html = fill(tpl, a.doc_dir, a.doc_name, a.title)
        Path(a.out).write_text(html)
        print(f"wrote {a.out} ({len(html) / 1e6:.2f} MB)")
        return

    for old, new in REPORT_PATCHES:
        if tpl.count(old) != 1:
            raise SystemExit(f"template changed; report patch no longer applies: {old[:60]!r}")
        tpl = tpl.replace(old, new)
    notes = load_notes(a.notes)
    amap = dict(m.split("=", 1) for m in a.author_map)
    keep, unsigned = [], []
    for n in notes:
        if n.get("status") == "dismissed" and not a.include_dismissed:
            continue
        n = {k: v for k, v in n.items() if k not in ("authorId", "createdAt", "updatedAt")}
        keep.append(sign(n, amap, unsigned))
    kept = {n["id"] for n in keep}
    src_r = a.replies or sibling(a.notes, "replies")
    replies = load_replies(src_r) if src_r else (load_replies(a.notes, notes_file=True) if Path(a.notes).is_file() else [])
    replies = [sign({k: v for k, v in r.items() if k != "authorId"}, amap, unsigned) for r in replies if r.get("note") in kept]
    src_e = a.edits or sibling(a.notes, "edits")
    edits = load_edits(src_e) if src_e else (load_edits(a.notes, notes_file=True) if Path(a.notes).is_file() else [])
    for e in edits:
        e.pop("history", None)
        au = e.get("author") or ""
        if "*" in amap:
            e["author"] = amap["*"]
        elif au in amap:
            e["author"] = amap[au]
        elif not au and e.get("authorName"):
            e["author"] = e["authorName"]
        e.pop("authorName", None)
    html = fill(tpl, a.doc_dir, a.doc_name, a.title).replace("__STATIC__", J({"notes": keep, "edits": edits, "replies": replies, "date": a.date}))
    Path(a.out).write_text(html)
    from collections import Counter
    print(f"wrote {a.out} ({len(html) / 1e6:.2f} MB): {len(keep)} notes, {len(replies)} replies, {len(edits)} text edits, "
          f"authors {dict(Counter(n.get('author', '') for n in keep))}")
    if unsigned:
        print(f"note: {len(unsigned)} notes are signed by account name and the report cannot look names up, so they show "
              f"\"Page owner\" / \"Reviewer\". Build from the page's Export JSON (it carries the names), or map them: "
              f"--author-map \"@owner=name\" for the notes Claude seeded unsigned, \"=name\" for notes made in the page")


if __name__ == "__main__":
    main()
