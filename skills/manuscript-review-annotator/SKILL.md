---
name: manuscript-review-annotator
description: Review a research manuscript (Word .docx, LaTeX source or PDF) thoroughly and deliver the review as an interactive annotation page — the full paper with figures and tables, every issue pre-highlighted in the text or boxed on the figure, editable and shareable with co-authors — plus clean exports and a standalone read-only report. Use this whenever someone uploads a paper draft and asks to check it for issues or inconsistencies, wants review comments placed on the manuscript, wants a page to highlight, box or comment on a paper with co-authors, or wants to clean up, relabel, export or snapshot the notes from such a page, even if they never say "annotation", "artifact" or "skill".
license: MIT
compatibility: Python 3.10+ with pandoc, beautifulsoup4, lxml, pillow, pdfplumber and pypdfium2 (see requirements.txt); playwright for smoke tests. The live page needs the Artifact publishing tool (claude.ai); elsewhere deliver the standalone report.
metadata:
  version: "1.1.0"
---

# Manuscript review annotator

Turns a manuscript into a living review: Claude reviews the paper, anchors every note to the
exact text or figure region it concerns, publishes an annotation page backed by a shared
notes database, and later cleans up, relabels or snapshots those notes on request.

Scripts live in `scripts/`, the page template in `assets/tool_template.html`, and detailed
guidance in `references/` (read each when its step comes up).

## Before starting

- Inputs, best first: LaTeX source (`.tex`, or a `.zip` of the project with figures and `.bib`),
  Word `.docx`, then PDF. Source files keep exact text and structure; a PDF is reflowed from its
  text layer, so check `outline.txt` and the figure crops after extraction. If the user has both
  a PDF and the source, use the source. Scanned PDFs (no text layer) are rejected; ask for the
  source or an OCR'd file.
- Ask once, if not already known, how review notes should be signed. Use exactly the name the
  user gives, including capitalization (e.g. "tracy"). Never sign notes as Claude: the
  review goes out from the user and their team.
- Work in `/home/claude/review/` and write deliverables to `/mnt/user-data/outputs/`. Never
  delete user deliverables there; only remove temporary folders you created (e.g. `_notes`).

## Workflow

### 1. Extract the manuscript

```bash
python scripts/extract.py /mnt/user-data/uploads/Paper.docx /home/claude/review/doc   # or .tex / .zip / .pdf
```
Produces `doc.json` (blocks), `texts.json` (the exact text each block renders; anchors must
come from here), `imgs.json`, `figures.json`, `comments.json` (existing reviewer comments:
Word comments, or PDF sticky notes and highlights) and `outline.txt`. Check the printout:
every figure and table should have a caption; fix warnings before going on.

Format notes:
- LaTeX: pandoc renders the source (math as MathML, `\ref` numbers, citations from `.bib`,
  starred floats handled, PDF figures rasterised). Pass `--main file.tex` if the project has
  several candidates. EPS figures show as placeholders.
- PDF: headings, captions, figures (cropped from the page), tables (parsed, or cropped as an
  image), display equations (cropped, ids `eq-N`) and references are reconstructed. Open a few
  crops in `pdf_figs/` and skim `outline.txt`; inline maths in PDFs comes out as plain text.

### 2. Review the paper

Read `references/review_checklist.md`, then read the whole of `texts.json` and view every
figure at full resolution. Recompute statistics rather than trusting them. Write each
finding into `/home/claude/review/draft.json`:

```json
[
  {"cat": "numbers", "exact": "z = 1.72, p = 0.043", "comment": "These p-values are one-tailed ...", "suggestion": ""},
  {"cat": "typos", "exact": "Animal studies suggests", "comment": "Agreement.", "suggestion": "Animal studies suggest"},
  {"cat": "figures", "fig": "fig-2", "box": [0.715, 0.0, 0.115, 0.07], "comment": "Stray palette swatch; remove."},
  {"cat": "blocker", "kind": "note", "comment": "No data availability or competing-interests statement."}
]
```
Add `"block": "b019"` when the quote occurs in several blocks, `"occ": n` to pick a repeat
within one block. A suggestion must replace exactly the quoted words.

For figure boxes, get panel borders first, then check placement visually:
```bash
python scripts/check_boxes.py lines /home/claude/review/doc fig-3
python scripts/check_boxes.py draw  /home/claude/review/doc /home/claude/review/draft.json /home/claude/review/boxes.png --draft
```
View `boxes.png` and correct any box that misses its target. This step matters: boxes placed
by eye routinely land on the wrong panel.

### 3. Validate the notes

```bash
python scripts/validate_notes.py /home/claude/review/doc /home/claude/review/draft.json /home/claude/review/seed \
    --author "<signature>" --comments /home/claude/review/doc/comments.json
```
Fix every ERROR and rerun until it prints OK. Output: `seed/seeds.json`, one file per note,
and `seed/batches/batch_N.json` for seeding.

### 4. Build and test the page

```bash
python scripts/build_html.py tool /home/claude/review/doc /mnt/user-data/outputs/<stem>_review.html --doc-name "Paper.docx"
python scripts/smoke_test.py /mnt/user-data/outputs/<stem>_review.html --notes /home/claude/review/seed/seeds.json --shot /home/claude/review/shot.png
```
The smoke test must print OK (no JavaScript errors, no unmatched quotes). Look at the
screenshot.

### 5. Publish and seed

Follow `references/artifact_ops.md` section 1: capabilities check, publish with
`{"db": {}, "downloads": true, "user": {"scopes": ["profile"]}}`, then one `write_db` batch
call per `batches/batch_N.json`, then verify with `read_db`.

No Artifact tool in this environment (e.g. a local Claude Code session)? Skip publishing and
deliver the standalone report instead:
`python scripts/build_html.py report DOC_DIR SEED_DIR/seeds.json OUT.html --doc-name Paper.docx`

### 6. Hand over

Reply briefly, in prose: what the review found at the highest level (the few issues that
matter most), how many notes by category, and how to use the page (select text to highlight
or comment, "Box on figure" to draw on figures, notes save automatically, suggested edits
shown inline, export buttons). Mention that it is private until shared and can be shared
within the organization. Do not paste the full list of notes into the chat; the page is the
deliverable.

## Later requests on the same page

Read `references/artifact_ops.md` for the exact calls.

| User says | Do |
|---|---|
| "I finished reviewing; delete dismissed ones, keep the open ones in a clean source" | read notes back, `notes_ops.py batch --delete-status dismissed`, write_db, `notes_ops.py clean` → present .md and .json |
| "Make a standalone report / bake the comments in" | read notes back, `build_html.py report` with author mapping, smoke test, present the file |
| "Sign them as X" / "use my account name" | `notes_ops.py batch --relabel "old=X"` in the live tool; also rebuild any report |
| "Change a colour / default / layout" | edit the template, rebuild, republish with the same `url` |
| "Where is this stored? Who can see it? Do invitees' names show?" | answer from artifact_ops.md section 6 |
| "Apply the accepted edits to the Word file" | read notes back, then edit the .docx with tracked changes following the docx skill |

## Things that went wrong before (avoid them)

- Box coordinates estimated from a thumbnail were wrong three times; always run `lines` and `draw`.
- A suggestion that repeated words outside the quote produced garbled inline edits.
- Notes were first signed "Claude review"; the user wanted their own account name, lowercase.
- Grey highlights for co-author comments were hard to read; teal is the default now.
- Suggested edits should be visible on load in both the tool and the report.
- Cleaning up `/mnt/user-data/outputs` once deleted files the user still needed.
