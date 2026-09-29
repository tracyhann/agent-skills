# Changelog

Changes are grouped by skill (alphabetical), newest version first. Skill versions follow
[Semantic Versioning](https://semver.org/); CONTRIBUTING.md says when to bump which part.
Each released version is tagged `<skill-name>-v<version>`. Repository-wide changes (tooling,
CI, docs) are listed under "Repository" at the end.

## manuscript-review-annotator

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

### 2026-09-28
- Published to GitHub under the MIT license.
- `tools/new_skill.py` scaffolds a skill, its tests folder and its CHANGELOG section.
- `tools/validate_skills.py` also requires a CHANGELOG entry for each skill's current version,
  rejects placeholder or multi-line descriptions, and warns when a skill has no tests.
- Release workflow: pushing `<skill-name>-v<version>` publishes a GitHub release with the
  CHANGELOG notes and the `.skill` file (`tools/release_notes.py` checks the tag first).
- CI runs on Python 3.10 and 3.12; `tools/build_index.py` no longer needs Python 3.12.
- Packaged `.skill` files include the license; pull request and issue templates added.
