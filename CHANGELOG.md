# Changelog

## manuscript-review-annotator

### 1.1.0
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

### 1.0.0
- Word (`.docx`) manuscripts: extraction with text-box captions and Word comments.
- Review checklist, anchored notes with validation, figure-box helpers.
- Live annotation tool (published artifact with shared notes), standalone read-only report,
  clean export, pinned delete/relabel batches.
- Defaults: suggested edits shown on load, teal co-author notes, notes signed with the
  user's own name.
