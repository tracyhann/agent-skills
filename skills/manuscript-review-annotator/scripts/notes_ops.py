#!/usr/bin/env python3
"""
Housekeeping on notes read back from the live tool.

Read the notes first with the Artifact tool:
    action "read_db", collection "annotations", db_op "query", query {"limit": 1000},
    out_dir "/mnt/user-data/outputs/_notes"      (out_dir must be under /mnt/user-data/outputs)
and save the listing it prints (the lines `- "r001" ... version 2`) to a text file,
because write_db needs each document's version to pin its writes.

1) Clean source of the open notes (Markdown for reading, JSON the tool can import):
    python notes_ops.py clean DOC_DIR /mnt/user-data/outputs/_notes/annotations OUTBASE [--author-map "Claude review=tracy"]

2) Batched write_db payloads (<= 50 writes each), pinned with if_version:
    python notes_ops.py batch /mnt/user-data/outputs/_notes/annotations --listing listing.txt --delete-status dismissed
    python notes_ops.py batch /mnt/user-data/outputs/_notes/annotations --listing listing.txt --relabel "Claude review=tracy"
   Prints each batch as JSON to paste into Artifact write_db (db_op "batch", writes=...).
Delete the temporary _notes folder afterwards.
"""
import argparse, json, re, sys
from pathlib import Path

CAT = {"blocker": "Fix before sharing", "numbers": "Numbers don't match", "stats": "Methods and stats",
       "figures": "Figures", "framing": "Accuracy and framing", "refs": "References",
       "typos": "Typos and wording", "coauthor": "Co-author comments", "mine": "My notes"}


def load(src):
    p = Path(src)
    if p.is_dir():
        return [json.loads(f.read_text()) for f in sorted(p.glob("*.json"))]
    d = json.loads(p.read_text())
    return d["annotations"] if isinstance(d, dict) else d


def clean(a):
    doc = Path(a.doc_dir)
    blocks = json.loads((doc / "doc.json").read_text())["blocks"]
    texts = json.loads((doc / "texts.json").read_text())
    order, section, sub = {}, {}, {}
    h2, h3 = "Front matter", ""
    for i, b in enumerate(blocks):
        order[b["id"]] = i
        if b["kind"] == "h2": h2, h3 = b["html"], ""
        elif b["kind"] == "h3": h3 = b["html"]
        section[b["id"]] = h2
        sub[b["id"]] = b.get("label") if b["kind"] in ("figure", "table") else ("Reference " + b["id"][4:] if b["kind"] == "ref" else ("Title" if b["kind"] == "title" else h3))
    amap = dict(m.split("=", 1) for m in a.author_map)

    def pos(n):
        if n["kind"] == "note": return (-1, n.get("seq", 0), 0)
        bi = order.get(n.get("block"), 10 ** 6)
        if n["kind"] == "box": return (bi, -1, n["y"])
        t, i, frm = texts.get(n["block"], ""), -1, 0
        for _ in range(n.get("occ", 0) + 1):
            i = t.find(n["exact"], frm)
            if i < 0: break
            frm = i + len(n["exact"])
        return (bi, 0, i)
    notes = sorted([n for n in load(a.notes) if n.get("status", "open") == "open"], key=pos)
    keep = ["id", "kind", "cat", "block", "exact", "occ", "x", "y", "w", "h", "comment", "suggestion", "status", "author", "authorId", "seq"]
    out = []
    for n in notes:
        m = {k: n[k] for k in keep if k in n and n[k] is not None}
        if m.get("author", "") in amap: m["author"] = amap[m.get("author", "")]
        out.append(m)
    Path(a.outbase + ".json").write_text(json.dumps({"format": "review-notes", "version": 1, "annotations": out}, ensure_ascii=False, indent=1))
    q = lambda s: (s or "").replace("\n", " ").strip()
    from collections import Counter
    cc = Counter(n["cat"] for n in out)
    md = [f"# Open review notes", "", f"{len(out)} open notes, in manuscript order.", "",
          "By category: " + ", ".join(f"{CAT.get(c, c)} {k}" for c, k in cc.most_common()) + ".", ""]
    cur = None
    for i, n in enumerate(out, 1):
        sec = "General" if n["kind"] == "note" else section.get(n.get("block"), "Other")
        if sec != cur:
            md += [f"## {sec}", ""]; cur = sec
        where = "" if n["kind"] == "note" else sub.get(n.get("block"), "")
        head = f"**{i}. {CAT.get(n['cat'], n['cat'])}**" + (f" ({where})" if where and where != sec else "")
        if n["kind"] == "text": head += f": \u201c{q(n['exact'])}\u201d"
        elif n["kind"] == "box": head += f": box on {where or n['block']}"
        md.append(head + "  ")
        md.append((q(n.get("comment")) or "_(highlight, no comment)_") + ("  " if n.get("suggestion") else ""))
        if n.get("suggestion"): md.append(f"Suggested: {q(n['suggestion'])}")
        if n.get("author"): md.append(f"_{n['author']}_")
        md.append("")
    Path(a.outbase + ".md").write_text("\n".join(md))
    print(f"wrote {a.outbase}.md and .json: {len(out)} open notes")


def batch(a):
    notes = load(a.notes)
    ver = {}
    if a.listing:
        for m in re.finditer(r'-\s+"([^"]+)"\s+\d+\s+bytes\s+"[^"]*"\s+version\s+(\d+)', Path(a.listing).read_text()):
            ver[m.group(1)] = int(m.group(2))
    writes = []
    if a.delete_status:
        for n in notes:
            if n.get("status") == a.delete_status:
                w = {"op": "delete", "collection": a.collection, "doc_id": n["id"]}
                if n["id"] in ver: w["if_version"] = ver[n["id"]]
                writes.append(w)
    elif a.relabel:
        old, new = a.relabel.split("=", 1)
        for n in notes:
            if (n.get("author") or "") == old:
                w = {"op": "update", "collection": a.collection, "doc_id": n["id"], "data": {"author": new}}
                if n["id"] in ver: w["if_version"] = ver[n["id"]]
                writes.append(w)
    else:
        sys.exit("choose --delete-status or --relabel")
    missing = [w["doc_id"] for w in writes if "if_version" not in w]
    if missing:
        print(f"warning: no version for {len(missing)} docs (pass --listing); those writes are unpinned", file=sys.stderr)
    print(f"{len(writes)} writes in {(len(writes) + 49) // 50} batch(es)", file=sys.stderr)
    for k in range(0, len(writes), 50):
        print(json.dumps(writes[k:k + 50]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clean"); c.add_argument("doc_dir"); c.add_argument("notes"); c.add_argument("outbase")
    c.add_argument("--author-map", action="append", default=[])
    b = sub.add_parser("batch"); b.add_argument("notes"); b.add_argument("--listing")
    b.add_argument("--delete-status"); b.add_argument("--relabel"); b.add_argument("--collection", default="annotations")
    a = ap.parse_args()
    clean(a) if a.cmd == "clean" else batch(a)
