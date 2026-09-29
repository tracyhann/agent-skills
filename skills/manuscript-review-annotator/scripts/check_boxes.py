#!/usr/bin/env python3
"""
Two helpers for figure boxes. Estimating box coordinates by eye is error-prone
(panels rarely sit where they seem to in a thumbnail), so always do both.

1) Find panel borders before writing boxes:
    python check_boxes.py lines DOC_DIR fig-3
   Prints long horizontal and vertical dark lines as fractions of the image (panel frames),
   and the bounding box of non-white content (catches figures that leave empty canvas).

2) Verify boxes after writing them:
    python check_boxes.py draw DOC_DIR NOTES.json OUT.png [--draft]
   NOTES.json is seeds.json from validate_notes.py (or the draft with --draft).
   Draws every box, labelled with its index, onto its figure and writes a contact sheet.
   Open OUT.png with the image viewer and fix any box that misses its target.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def lines(doc_dir, fig):
    figs = json.loads((Path(doc_dir) / "figures.json").read_text())
    if fig not in figs:
        sys.exit(f"{fig} not in figures.json: {list(figs)}")
    g = np.array(Image.open(figs[fig]["media"]).convert("L")).astype(int)
    H, W = g.shape
    dark = g < 90

    def groups(idx, n):
        out, cur = [], []
        for i in idx:
            if cur and i - cur[-1] > 2:
                out.append(cur); cur = []
            cur.append(i)
        if cur:
            out.append(cur)
        return [round(float(np.mean(c)) / n, 3) for c in out]
    for frac in (0.5, 0.3):
        h = groups(np.where(dark.sum(1) > W * frac)[0], H)
        v = groups(np.where(dark.sum(0) > H * frac)[0], W)
        print(f"lines spanning >{int(frac * 100)}%: horizontal y={h}  vertical x={v}")
    # half-width scan catches frames of side-by-side panels
    for name, sl in (("left half", slice(0, W // 2)), ("right half", slice(W // 2, W))):
        h = groups(np.where(dark[:, sl].sum(1) > (W // 2) * 0.6)[0], H)
        print(f"{name}: horizontal y={h}")
    content = np.where(g < 240)
    print(f"content bbox: x {content[1].min() / W:.3f}-{content[1].max() / W:.3f}, y {content[0].min() / H:.3f}-{content[0].max() / H:.3f}")


def draw(doc_dir, notes_path, out, draft):
    figs = json.loads((Path(doc_dir) / "figures.json").read_text())
    notes = json.loads(Path(notes_path).read_text())
    if isinstance(notes, dict):
        notes = notes.get("annotations", [])
    by = {}
    for i, n in enumerate(notes, 1):
        if draft and "box" in n:
            fig, (x, y, w, h) = n["fig"], n["box"]
        elif n.get("kind") == "box":
            fig, x, y, w, h = n["block"], n["x"], n["y"], n["w"], n["h"]
        else:
            continue
        by.setdefault(fig, []).append((n.get("id", f"#{i}"), x, y, w, h))
    if not by:
        sys.exit("no boxes found")
    tiles = []
    for fig, boxes in by.items():
        im = Image.open(figs[fig]["media"]).convert("RGB")
        W, H = im.size
        d = ImageDraw.Draw(im)
        lw = max(3, W // 250)
        fs = max(16, W // 45)
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        for bid, x, y, w, h in boxes:
            d.rectangle([x * W, y * H, (x + w) * W, (y + h) * H], outline=(255, 0, 200), width=lw)
            tw = d.textlength(bid, font=font)
            d.rectangle([x * W, y * H, x * W + tw + 12, y * H + fs + 10], fill=(255, 0, 200))
            d.text((x * W + 6, y * H + 4), bid, fill=(255, 255, 255), font=font)
        im.thumbnail((900, 900))
        d2 = ImageDraw.Draw(im)
        d2.text((6, 6), fig, fill=(0, 0, 0))
        tiles.append(im)
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (900 * cols + 10 * (cols - 1), max(t.height for t in tiles) * rows + 10 * (rows - 1)), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 910, (i // cols) * (max(x.height for x in tiles) + 10)))
    sheet.save(out)
    print(f"wrote {out}: {sum(len(v) for v in by.values())} boxes on {len(by)} figures")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("lines"); l.add_argument("doc_dir"); l.add_argument("fig")
    d = sub.add_parser("draw"); d.add_argument("doc_dir"); d.add_argument("notes"); d.add_argument("out"); d.add_argument("--draft", action="store_true")
    a = ap.parse_args()
    lines(a.doc_dir, a.fig) if a.cmd == "lines" else draw(a.doc_dir, a.notes, a.out, a.draft)
