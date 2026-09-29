#!/usr/bin/env python3
"""
Resolve drafted review notes against the extracted manuscript, fail loudly on bad anchors,
and write everything needed to seed the published tool.

Usage:
    python validate_notes.py DOC_DIR NOTES_DRAFT.json OUTDIR [--author "cabbage"] [--comments DOC_DIR/comments.json]

--author is the signature the person asking for the review chose for this session, exactly as
given. Without it the notes carry no signature and the page shows the account name of the page
owner (the person who asked for the review) instead.

NOTES_DRAFT.json is a list. Each item is one of:
    {"cat": "numbers", "exact": "z = 1.72, p = 0.043", "block": "b019"?, "occ": 0?,
     "comment": "...", "suggestion": "replacement for exactly the quoted span"?}
    {"cat": "figures", "fig": "fig-2", "box": [x, y, w, h], "comment": "..."}   # fractions of the image
    {"cat": "blocker", "kind": "note", "comment": "..."}                         # not tied to any text
"block" is only needed when the exact text occurs in more than one block; "occ" picks the
n-th occurrence (0-based) inside the block when it repeats there.
Any item may carry a reply thread, seeded into the page's `replies` collection:
    "replies": [{"text": "...", "author": "Authors (rebuttal)"?, "date": "2026-07-28"?}, ...]
A reply is signed with its "author", else --author, else (like notes) the page owner's account
name. "date" orders and dates it (default: now).

Writes to OUTDIR:
    seeds.json          resolved notes (ids r001...), in manuscript order
    notes/<id>.json     one file per note (write_db batch entries point at these)
    replies.json, replies/<id>.json   reply threads (ids r001-c1, ...), when the draft has any
    batches/batch_N.json write_db "writes" arrays (notes, then replies), at most 50 entries each
Exit code 1 if any anchor fails; fix the draft and rerun.
"""
import argparse, datetime, json, sys
from pathlib import Path

CATS = {"blocker", "numbers", "stats", "figures", "framing", "refs", "typos", "coauthor", "mine"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_dir"); ap.add_argument("draft"); ap.add_argument("outdir")
    ap.add_argument("--author", default="", help="signature chosen for this session, exactly as given (case-sensitive); "
                    "omit to show the page owner's account name")
    ap.add_argument("--comments", help="comments.json from extract.py, imported as co-author notes")
    ap.add_argument("--collection", default="annotations")
    a = ap.parse_args()

    doc = Path(a.doc_dir)
    texts = json.loads((doc / "texts.json").read_text())
    blocks = json.loads((doc / "doc.json").read_text())["blocks"]
    order = {b["id"]: i for i, b in enumerate(blocks)}
    kinds = {b["id"]: b["kind"] for b in blocks}
    draft = json.loads(Path(a.draft).read_text())
    if a.comments:
        for c in json.loads(Path(a.comments).read_text()):
            if c.get("block"):
                draft.append({"cat": "coauthor", "exact": c["exact"], "block": c["block"], "comment": c["text"], "author": c["author"]})
            else:
                draft.append({"cat": "coauthor", "kind": "note", "comment": f"{c['text']} (on: \u201c{c['exact'][:120]}\u201d)", "author": c["author"]})

    errors, warns, out = [], [], []
    for i, d in enumerate(draft):
        tag = f"#{i + 1} ({d.get('exact') or d.get('fig') or d.get('kind')!r})"
        cat = d.get("cat", "mine")
        if cat not in CATS:
            errors.append(f"{tag}: unknown cat {cat!r}; use one of {sorted(CATS)}"); continue
        n = {"kind": "text", "cat": cat, "comment": (d.get("comment") or "").strip(),
             "suggestion": (d.get("suggestion") or "").strip(), "status": "open",
             "author": d.get("author") or a.author}
        if not n["author"]:
            n["byOwner"] = True
        thread = []
        for k, r in enumerate(d.get("replies") or [], 1):
            txt = (r.get("text") or "").strip() if isinstance(r, dict) else ""
            if not txt:
                errors.append(f"{tag}: reply {k} has no text"); continue
            if len(txt) > 4000:
                errors.append(f"{tag}: reply {k} is longer than 4000 characters"); continue
            when = r.get("date") or ""
            if when:
                try:
                    datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
                except ValueError:
                    errors.append(f"{tag}: reply {k} date {when!r} is not ISO (YYYY-MM-DD)"); continue
            thread.append({"text": txt, "author": (r.get("author") or a.author).strip(), "date": when})
        n["_replies"] = thread
        if d.get("kind") == "note":
            n.update(kind="note", block=None)
        elif "box" in d or "fig" in d:
            fig = d.get("fig")
            if kinds.get(fig) != "figure":
                errors.append(f"{tag}: fig {fig!r} is not a figure id"); continue
            x, y, w, h = [float(v) for v in d["box"]]
            if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 - x + 1e-6 and 0 < h <= 1 - y + 1e-6):
                errors.append(f"{tag}: box {d['box']} must be fractions inside the image"); continue
            n.update(kind="box", block=fig, x=round(x, 4), y=round(y, 4), w=round(w, 4), h=round(h, 4))
            n["suggestion"] = ""
        else:
            ex = d.get("exact") or ""
            if not ex.strip():
                errors.append(f"{tag}: empty exact"); continue
            if ex != ex.strip():
                warns.append(f"{tag}: exact has leading/trailing whitespace; trimmed")
                ex = ex.strip()
            blk = d.get("block")
            if blk:
                if blk not in texts:
                    errors.append(f"{tag}: block {blk!r} does not exist"); continue
                if ex not in texts[blk]:
                    errors.append(f"{tag}: text not found in {blk}. Copy it from texts.json (superscripts are inline, e.g. 'as prior49–54')"); continue
            else:
                hits = [k for k in texts if ex in texts[k]]
                if not hits:
                    errors.append(f"{tag}: text not found anywhere. Copy the exact characters from texts.json"); continue
                if len(hits) > 1:
                    errors.append(f"{tag}: text occurs in {len(hits)} blocks {hits[:6]}; add \"block\""); continue
                blk = hits[0]
            cnt = texts[blk].count(ex)
            occ = int(d.get("occ", 0))
            if occ >= cnt:
                errors.append(f"{tag}: occ={occ} but text occurs {cnt}x in {blk}"); continue
            if cnt > 1 and "occ" not in d:
                warns.append(f"{tag}: text occurs {cnt}x in {blk}; anchoring the first (set \"occ\" to choose)")
            if n["suggestion"] and len(ex) < 4:
                warns.append(f"{tag}: very short quote with a suggestion; make sure the suggestion replaces exactly {ex!r}")
            n.update(block=blk, exact=ex, occ=occ)
        out.append(n)

    def key(n):
        if n["kind"] == "note":
            return (-1, 0, 0)
        if n["kind"] == "box":
            return (order[n["block"]], -1, n["y"])
        t = texts[n["block"]]; i, frm = -1, 0
        for _ in range(n["occ"] + 1):
            i = t.find(n["exact"], frm); frm = i + len(n["exact"])
        return (order[n["block"]], 0, i)
    out.sort(key=key)

    for w in warns:
        print("warn:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        print(f"\n{len(errors)} error(s); nothing written.")
        sys.exit(1)

    od = Path(a.outdir); (od / "notes").mkdir(parents=True, exist_ok=True); (od / "batches").mkdir(exist_ok=True)
    base = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    now = base.strftime("%Y-%m-%dT%H:%M:%SZ")
    replies = []
    for i, n in enumerate(out, 1):
        n.update(id=f"r{i:03d}", seq=i, createdAt=now, updatedAt=now)
        for k, r in enumerate(n.pop("_replies"), 1):
            if r["date"]:
                t = datetime.datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                t = (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)) + datetime.timedelta(seconds=k)
            else:
                t = base + datetime.timedelta(seconds=k)
            ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            rep_ = {"id": f"{n['id']}-c{k}", "note": n["id"], "text": r["text"], "author": r["author"], "authorId": None,
                    "createdAt": ts, "updatedAt": ts}
            if not r["author"]:
                rep_["byOwner"] = True
            replies.append(rep_)
        (od / "notes" / f"{n['id']}.json").write_text(json.dumps(n, ensure_ascii=False))
    (od / "seeds.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    writes = [{"op": "set", "collection": a.collection, "doc_id": n["id"],
               "file_path": str((od / "notes" / f"{n['id']}.json").resolve())} for n in out]
    if replies:
        (od / "replies").mkdir(exist_ok=True)
        for r in replies:
            (od / "replies" / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False))
        (od / "replies.json").write_text(json.dumps(replies, ensure_ascii=False, indent=1))
        writes += [{"op": "set", "collection": "replies", "doc_id": r["id"],
                    "file_path": str((od / "replies" / f"{r['id']}.json").resolve())} for r in replies]
    for k in range(0, len(writes), 50):
        (od / "batches" / f"batch_{k // 50 + 1}.json").write_text(json.dumps(writes[k:k + 50]))
    from collections import Counter
    print(f"OK: {len(out)} notes ({dict(Counter(n['kind'] for n in out))}); categories {dict(Counter(n['cat'] for n in out))}"
          + (f"; {len(replies)} replies on {len({r['note'] for r in replies})} notes" if replies else ""))
    print(f"signed: {dict(Counter(n['author'] or '(page owner account name)' for n in out))}")
    print(f"write_db batches: {(len(writes) + 49) // 50} in {od / 'batches'}")


if __name__ == "__main__":
    main()
