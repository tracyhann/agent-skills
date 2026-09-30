# Changelog

Changes are grouped by skill (alphabetical), newest version first. Skill versions follow
[Semantic Versioning](https://semver.org/); CONTRIBUTING.md says when to bump which part.
Each released version is tagged `<skill-name>-v<version>`. Repository-wide changes (tooling,
CI, docs) are listed under "Repository" at the end.

## manuscript-review-annotator

### 1.4.0 — 2026-09-29
- "Export HTML" in the page: one click downloads a standalone, read-only copy of the paper with
  every note (except dismissed ones), reply thread and text edit, with account-signed items
  named as the exporter sees them, so it opens offline in any browser and reads the same for
  anyone.
- Report mode is part of the page (`window.REVIEW_SNAPSHOT`); `build_html.py report` injects the
  same snapshot instead of patching the template, so the two kinds of report cannot drift apart.
- "Export report" is now "Export Markdown"; a report opened from disk saves its JSON and Markdown
  exports with a plain browser download.
- `smoke_test.py --exercise-report` exports the report, opens it offline and checks it; a test
  exports one through the downloads capability of a stand-in page runtime and checks the names.

### 1.3.0 — 2026-09-29
- Signatures follow whoever is using the skill or the page. "Signing as" in the page's toolbar
  lets each person set a signature for their session (kept until the tab closes); otherwise
  their notes, edits and "addressed by" records show their account name, looked up for each
  viewer when the page draws and never stored.
- Claude no longer has to ask for a signature before reviewing: `validate_notes.py --author` is
  optional, and unsigned notes show the account name of the page owner (the person who asked
  for the review). The owner's id is recorded once in `meta/owner` by their own view.
- `notes_ops.py batch --relabel "=name"` signs only Claude's unsigned notes, never notes people
  made in the page under their account name; `--relabel "name="` returns them to the account
  name.
- Export JSON includes the account names its viewer sees (`authorName`, dropped again on
  import); `build_html.py report` uses them, and `--author-map "@owner=name"` names Claude's
  unsigned notes. Unmapped account-signed notes show "Page owner" / "Reviewer" instead of "You".
- Examples use "cabbage" as the sample signature; no signature is stored as a default.
- Reply threads on notes: "Reply" under any note, stored and shown as plain text, signed like
  notes (session signature, else account name; a session signature shows the account name on
  hover). People can edit or delete their own replies; long threads show the latest two
  ("Show N earlier replies"); search covers replies; deleting a note deletes its replies.
  Replies live in their own `replies` collection (one document per reply), so simultaneous
  replies never overwrite each other.
- `validate_notes.py`: a drafted note can carry `"replies"` (text, author, date), written to
  `replies.json` and seeded in the same write batches (ids `r001-c1`, …).
- Exports carry replies (JSON version 3, with `authorName` for account-signed ones); the Markdown
  export quotes each thread under its note; `build_html.py report` bakes threads in (`--replies`,
  or the sibling `_notes/replies` folder) and names them like notes; `notes_ops.py clean`
  includes each note's thread.
- `smoke_test.py --exercise-comments` drives reply threads (session signature, post, edit,
  search, reload, delete, hostile HTML in a reply); `--replies` seeds threads.

### 1.2.0 — 2026-09-29
- Edit the manuscript in the page to address notes: "Edit text" (shortcut E) makes any
  paragraph, heading, caption, table cell or reference editable in place; tick the notes the
  change resolves and they are marked done with a link back to the edit. A note's own
  "Edit text" opens its block with the quote selected.
- "Apply" on a suggestion now replaces the quoted text (it used to only mark the note done).
  Suggestions that span table cells open the editor instead.
- Edits are stored in a shared `edits` collection (last 10 versions each, "Use original" to
  revert) with a 45-second lease per block so two people do not overwrite each other, and
  are shown as tracked changes; "Show changes" toggles them.
- Edit HTML is sanitized on save and on display (only text formatting and MathML survive).
- Exports carry the edits (JSON version 2); the Markdown export lists each edit as a diff;
  `build_html.py report --edits` bakes them into the read-only report.
- New `scripts/apply_edits.py` carries page edits back to a LaTeX project: a patched copy,
  `changes.diff`, `apply_report.md` (what was applied at which file:line, what needs a manual
  fix and why) and `hunks.json` for Word tracked changes. The source is never modified.
- LaTeX extraction: `>{...}`/`@{}` column specs, `\multicolumn` specs, `\resizebox` around a
  tabular, `\shortstack`, `\rowcolor`/`\cellcolor` and longtable `\endfirsthead` headers no
  longer drop cell text; pandoc is run with a timeout and retried without local `.sty`/`.cls`
  files when it hangs; PDF figures included as `<embed>` are rasterised; a warning when fewer
  figures come out than the source declares (figure floats and `\captionof{figure}`).
- Numeric table cells are right-aligned instead of every column after the first.
- `smoke_test.py --exercise-edits` drives the editing features (edit, save, tracked changes,
  Apply, a table-cell Apply, a note's Edit text, reload, sanitizer); `--edits` seeds edits.

### 1.1.0 — 2026-09-28
- Accept LaTeX source (`.tex`, or a zipped project with figures and `.bib`) and PDFs with a
  text layer, alongside Word files. One extractor (`scripts/extract.py`) handles all three.
- LaTeX: maths rendered as MathML, citations resolved from `.bib`, `\ref` numbers, starred
  floats, PDF figures rasterised, sub-figures combined.
- PDF: single- and two-column reflow, headings, captions with cropped figures (including
  full-page figures next to their caption), parsed tables, display equations as images,
  headers/footers/line numbers removed, PDF sticky notes and highlights imported as comments.
- Highlights skip MathML so equations render correctly.
- Standalone report is the delivery path where the Artifact tool is unavailable.
- `requirements.txt` added.
- `license: MIT` in the frontmatter.

### 1.0.0
- Word (`.docx`) manuscripts: extraction with text-box captions and Word comments.
- Review checklist, anchored notes with validation, figure-box helpers.
- Live annotation tool (published artifact with shared notes), standalone read-only report,
  clean export, pinned delete/relabel batches.
- Defaults: suggested edits shown on load, teal co-author notes, notes signed with the
  user's own name.

## Repository

### 2026-09-29
- Tests: a synthetic LaTeX tables fixture (`>{..}` column specs, `\resizebox`, `\shortstack`,
  longtable head), a page-edits round trip through `apply_edits.py` and the baked report, and
  `smoke_test.py --exercise-edits` on every input format.

### 2026-09-28
- Published to GitHub under the MIT license.
- `tools/new_skill.py` scaffolds a skill, its tests folder and its CHANGELOG section.
- `tools/validate_skills.py` also requires a CHANGELOG entry for each skill's current version,
  rejects placeholder or multi-line descriptions, and warns when a skill has no tests.
- Release workflow: pushing `<skill-name>-v<version>` publishes a GitHub release with the
  CHANGELOG notes and the `.skill` file (`tools/release_notes.py` checks the tag first).
- CI runs on Python 3.10 and 3.12; `tools/build_index.py` no longer needs Python 3.12.
- Packaged `.skill` files include the license; pull request and issue templates added.
