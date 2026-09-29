---
name: manuscript-review-annotator
description: Review a research manuscript (Word .docx, LaTeX source or PDF) thoroughly and deliver the review as an interactive annotation page — the full paper with figures and tables, every issue pre-highlighted in the text or boxed on the figure, shared with co-authors who discuss notes in signed reply threads and edit the manuscript text in place to address them (tracked changes, one-click suggestions) — plus clean exports, a read-only report, and a patch that carries the page's edits back into the LaTeX source. Use this whenever someone uploads a paper draft and asks to check it for issues or inconsistencies, wants review comments placed on the manuscript, wants a page to highlight, box, comment on, discuss or edit a paper with co-authors, wants to address or resolve review comments by editing the text, wants edits made in such a page applied to their .tex/Overleaf or Word files, or wants to clean up, relabel, export or snapshot the notes from such a page, even if they never say "annotation", "artifact" or "skill".
license: MIT
compatibility: Python 3.10+ with pandoc, beautifulsoup4, lxml, pillow, pdfplumber and pypdfium2 (see requirements.txt); playwright for smoke tests. The live page needs the Artifact publishing tool (claude.ai); elsewhere deliver the standalone report.
metadata:
  version: "1.3.0"
---

# Manuscript review annotator

Turns a manuscript into a living review: Claude reviews the paper, anchors every note to the
exact text or figure region it concerns, publishes an annotation page backed by a shared
notes database, and later cleans up, relabels or snapshots those notes on request.

The page is also where the notes get addressed: co-authors switch to **Edit text**, change a
paragraph, heading, caption, table cell or reference in place, tick the notes the change
resolves, and save. Suggestions apply with one click. Edits are shared (their own `edits`
collection), shown as tracked changes, revertible, and can be carried back into the LaTeX
source with `scripts/apply_edits.py`.

Co-authors discuss a note in its **reply thread** ("Reply" under any note; people can edit or
delete their own replies). Replies are signed like notes and edits: with the signature the person
set for the session under "Signing as", else their account name, and a session signature shows
the account name on hover. Replies live in their own `replies` collection.

Scripts live in `scripts/`, the page template in `assets/tool_template.html`, and detailed
guidance in `references/` (read each when its step comes up).

## Before starting

- Inputs, best first: LaTeX source (`.tex`, or a `.zip` of the project with figures and `.bib`),
  Word `.docx`, then PDF. Source files keep exact text and structure; a PDF is reflowed from its
  text layer, so check `outline.txt` and the figure crops after extraction. If the user has both
  a PDF and the source, use the source. Scanned PDFs (no text layer) are rejected; ask for the
  source or an OCR'd file.
- Signatures belong to whoever is asking in this session. If they say how their notes should be
  signed, use exactly that, capitalization included (e.g. "cabbage"). Otherwise do not hold the
  review up to ask: leave the signature off and the page shows their account name. Never reuse a
  signature from an earlier session, another person or memory, and never sign notes as Claude.
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
  several candidates. EPS figures show as placeholders. The extractor rewrites table constructs
  that make pandoc drop cell text, and retries without local `.sty`/`.cls` files when pandoc
  hangs on them (it prints a warning; layout only). It also warns when fewer figures come out
  than the source declares. See "LaTeX projects" below before accepting warnings.
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

To seed a discussion under a note (an author's response to a reviewer, a co-author's earlier
answer), give it `"replies": [{"text": "...", "author": "Authors (rebuttal)", "date": "2026-07-28"}]`.
A reply without `author` is signed like the notes (`--author`, else the page owner's account
name). Quote or summarise the source; never invent a response.

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
    [--author "<signature>"] --comments /home/claude/review/doc/comments.json
```
Pass `--author` only with a signature the person gave in this session. Without it the notes are
marked as the requester's (`byOwner`) and the page shows the page owner's account name, which is
the requester's once they publish it. Fix every ERROR and rerun until it prints OK. Output:
`seed/seeds.json`, one file per note, `seed/replies.json` when there are replies, and
`seed/batches/batch_N.json` for seeding (notes first, then replies).

### 4. Build and test the page

```bash
python scripts/build_html.py tool /home/claude/review/doc /mnt/user-data/outputs/<stem>_review.html --doc-name "Paper.docx"
python scripts/smoke_test.py /mnt/user-data/outputs/<stem>_review.html --notes /home/claude/review/seed/seeds.json --shot /home/claude/review/shot.png
```
The smoke test must print OK (no JavaScript errors, no unmatched quotes). Look at the
screenshot. Pass `--replies seed/replies.json` when the draft had replies. After any change to
the template, also run it with `--exercise-edits --exercise-comments`: they edit a paragraph,
apply a suggestion (including one in a table), open a note's "Edit text", sign for the session,
post, edit, search and delete a reply, reload, and push hostile HTML through the sanitizer and
the reply box; every check must print PASS.

### 5. Publish and seed

Follow `references/artifact_ops.md` section 1: capabilities check, publish with
`{"db": {}, "downloads": true, "user": {"scopes": ["profile"]}}`, then one `write_db` batch
call per `batches/batch_N.json`, then verify with `read_db`.

No Artifact tool in this environment (e.g. a local Claude Code session)? Skip publishing and
deliver the standalone report instead:
`python scripts/build_html.py report DOC_DIR SEED_DIR/seeds.json OUT.html --doc-name Paper.docx`

### 6. Hand over

Reply briefly, in prose: what the review found at the highest level (the few issues that matter
most), how many notes by category, and how to use the page (select text to highlight or
comment, "Box on figure" to draw on figures, "Reply" to discuss a note, "Edit text" to change
the manuscript and tick the notes an edit addresses, "Apply" on a suggestion, "Show changes" for
tracked changes, notes, replies and edits save automatically, export buttons). Say how the notes are signed, and that everyone
signs with their own account name unless they set a different signature for their session with
"Signing as" in the toolbar. Mention that it is private until shared and can be shared within
the organization. Do not paste the full list of notes into the chat; the page is
the deliverable.

## Later requests on the same page

Read `references/artifact_ops.md` for the exact calls.

| User says | Do |
|---|---|
| "I finished reviewing; delete dismissed ones, keep the open ones in a clean source" | read notes back, `notes_ops.py batch --delete-status dismissed`, write_db, `notes_ops.py clean` → present .md and .json |
| "Make a standalone report / bake the comments in" | read notes back, `build_html.py report` with author mapping, smoke test, present the file |
| "Sign them as X" / "use my account name" | `notes_ops.py batch --relabel "old=X"` in the live tool (`"=X"` signs Claude's unsigned notes; `"X="` returns them to the account name); also rebuild any report; replies: the same on `_notes/replies` with `--collection replies`. For their own future notes and replies, point them to "Signing as" |
| "Add the rebuttal / the authors' answers to the reviewer notes" | draft them as `"replies"` on those notes (quote or summarise the source), validate, write the reply batch; on a published page, see artifact_ops.md section 2 |
| "Change a colour / default / layout" | edit the template, rebuild, republish with the same `url` |
| "Where is this stored? Who can see it? Do invitees' names show?" | answer from artifact_ops.md section 6 |
| "Apply the edits from the page to my LaTeX / Overleaf project" | read the `edits` collection back, run `apply_edits.py DOC_DIR <edits dir> <project> OUT`, present `apply_report.md`, `changes.diff` and the changed files; say which changes need a manual fix and why (artifact_ops.md section 7) |
| "Apply the edits / accepted suggestions to the Word file" | read the `edits` collection back, run `apply_edits.py` for `hunks.json` (before/after with context), then write them into the .docx as tracked changes following the docx skill |
| "What did we change?" / "Undo that edit" | Export report lists every text edit with its diff; in the page, open the block, "Use original", Save. Each edit keeps its last 10 versions in `history` if an older one is needed |

## LaTeX projects

pandoc covers most papers, but these showed up on a real project and silently lost content:
- A project's own style file (`.sty`) sent pandoc into an endless loop. The extractor now times
  out and retries without local style files; nothing to do unless macros defined only in those
  files are needed (then define them in a copy of the main file).
- Figures inside `minipage` with `\captionof`, and `sidewaysfigure`/`sidewaystable`, come out
  without captions or not at all. Rewrite them as ordinary `figure`/`table` floats in a scratch
  copy of the project (never in the user's folder) and extract again.
- `\Cref`/`\ref` to such floats render as bare numbers or `[fig:label]`, appendix sections
  are numbered 6, 7… instead of A, B…, and `--citeproc` gives author-date citations for a
  numbered bibliography. When fidelity matters, resolve numbering and `\cite` numbers in the
  scratch copy, and check the citation order against the compiled PDF's reference list.
- Text inside MathML cannot be highlighted: quote the words next to the maths instead.

## Things that went wrong before (avoid them)

- Box coordinates estimated from a thumbnail were wrong three times; always run `lines` and `draw`.
- A suggestion that repeated words outside the quote produced garbled inline edits.
- Notes were first signed "Claude review", and later one session's signature was saved as a
  default for the next. A signature is whatever the person using the skill or the page chose for
  that session, else their account name: never Claude, never remembered from before.
- Grey highlights for co-author comments were hard to read; teal is the default now.
- Suggested edits should be visible on load in both the tool and the report.
- Cleaning up `/mnt/user-data/outputs` once deleted files the user still needed.
- "Accept edit" used to only mark a note done; users expected the text to change. "Apply" now
  edits the text; keep it that way.
- A suggestion whose quote started exactly at a table cell boundary was once inserted between
  cells, emptying the cell. The range helper now starts inside the containing text node, and a
  suggestion that spans cells opens the editor instead; the smoke test guards this.
- Edits are HTML that other viewers render: keep the sanitizer on both save and display.
