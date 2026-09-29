# Manuscript review checklist

Use this for step 2 of the workflow. The goal is a review a careful co-author or journal
reviewer would recognise as thorough: every number checked against every other place it
appears, every figure inspected at full resolution, and every note anchored to the exact
spot it concerns.

## Contents
1. Reading the manuscript
2. What to check
3. Recomputing statistics
4. Writing notes
5. Categories

## 1. Reading the manuscript

- Read `texts.json` end to end (or `outline.txt` first for structure). It is exactly the text
  the page renders, so anchors copied from it always match.
- Open every figure image (paths in `figures.json`) with the image viewer. Crop and zoom dense
  panels with PIL; small labels, axis ticks and legends hide most figure errors.
- When a claim depends on values read off a plot, measure them (pixel positions against the
  axis ticks) and say "reading off the plot" in the note.
- Look at captions and tables as carefully as body text; they drift out of sync with it.

## 2. What to check

**Fix before sharing (blocker)**
- Leftover artifacts: screenshots, palette swatches, file names or participant IDs in figures,
  planning lines ("Target journals"), unresolved Word comments, placeholder text ("N = ").
- Missing items the paper type requires. For a clinical trial: N per arm, Table 1
  (demographics/baseline), CONSORT flow, trial registration, data availability, funding,
  competing interests (especially for commercial interventions), author list.

**Numbers don't match (numbers)**
- The same quantity in abstract, results, tables, figures and captions (N, means, t/z/p,
  percentages). Rounding differences are fine; different values are not.
- Counts derivable from figures (flow diagrams, histograms, random-effect lists) versus the text.
- Percent claims ("23% larger"): recompute from the underlying estimates and check the
  denominator. A common error is dividing by the subset estimate instead of the reference.
- Axis ranges and labels versus what the text says was plotted (e.g. visit numbers 3-8
  shown where treatment days 0-5 are meant).
- Units (mm vs mm³ for isotropic voxels), standard constants (HCP grayordinates 91,282;
  fsaverage5 20,484 vertices), acquisition parameters repeated in two places.

**Methods and stats (stats)**
- Model specification: random slopes for time-varying effects, df method, software and versions.
- Baseline imbalance and regression to the mean when groups start at different values.
- Direction claims ("X precedes Y") need both cross-lagged paths tested.
- Non-independence: tests run at scan/trial level when observations are nested in people.
- One- vs two-tailed tests, multiplicity, exploratory analyses presented as confirmatory.
- Analytic choices that look post hoc relative to the pre-registration.
- ROI definitions: overlap between ROIs, atlas named, match to other definitions in the paper.
- Preprocessing choices with interpretive consequences (e.g. global signal regression).

**Figures (figures)**
- Matrix/equation schematics that are not mathematically valid.
- Undefined error bars, "(Adj.)" axes, dual y-axes with arbitrary scaling.
- Raw variable names as labels, oversized legends, draft titles, inconsistent capitalization
  between figures, labels that do not say which measure (self vs clinician rated).
- Caption text versus panels (panel letters, counts, statistics quoted in captions).

**Accuracy and framing (framing)**
- Mechanistic misstatements (what the intervention actually targets).
- Overclaims: "systematically", "strongly implicated", "validated", "critically" on
  exploratory or single-measure results; effect sizes described as "modest" when the
  cumulative effect is large.
- Claims with no supporting data shown; missing limitations.

**References (refs)**
- Duplicates (same title/DOI twice, often one entry missing fields), preprint plus published
  version of the same work, corrupted author fields, missing authors, web-page titles,
  low-quality or obscure sources, formatting glitches.

**Typos and wording (typos)**
- Spelling, agreement, missing words, wrong words ("proceeded" for "followed"),
  capitalization of eponyms (Shapiro-Wilk, Fisher), acronyms (BIDS), registry names.

## 3. Recomputing statistics

```python
from scipy import stats
2 * stats.t.sf(abs(t), df)        # two-tailed p for a t statistic
2 * stats.norm.sf(abs(z))         # two-tailed p for z; stats.norm.sf(z) is one-tailed
stats.chi2.sf(x2, dof)            # chi-square
```
- Mixed models: between-subject terms have df near the number of participants,
  within-subject terms near the number of observations. A p-value that needs an implausible
  df (or is smaller than the infinite-df limit) is a transcription error.
- If reported p-values equal the one-tailed value, say so and give the two-tailed value.

## 4. Writing notes

- One issue per note. Put the evidence in the comment (what was compared, the numbers).
- Anchor on the shortest distinctive phrase that locates the issue, copied character for
  character from `texts.json`. Citation superscripts are inline in that text
  ("as prior49–54"), minus signs may be hyphens, and LaTeX `~` becomes a non-breaking space
  ("Figure\u00a01"). Text inside equations cannot be highlighted; anchor on the words around
  it, or box the equation image (PDF input, ids `eq-N`).
- A `suggestion` must be a drop-in replacement for exactly the quoted span. If the fix
  needs text outside the quote, widen the quote or leave the suggestion empty and describe
  the fix in the comment. (Quoting "≥ 1.72" and suggesting "|z|s ≥ 1.72" duplicates text.)
- Figure problems get box notes. Place boxes from `check_boxes.py lines` output, then verify
  with `check_boxes.py draw`; eyeballed coordinates are usually off by a panel.
- Write comments in a neutral, direct voice without "I". They are signed with the user's
  name, not Claude's.
- Existing reviewer comments (Word comments, PDF sticky notes and highlights) are imported
  with `--comments` as co-author notes with their original authors.

## 5. Categories

| id | shown as | use for |
|---|---|---|
| blocker | Fix before sharing | embarrassing leftovers, missing required sections |
| numbers | Numbers don't match | internal inconsistencies, miscalculations |
| stats | Methods and stats | analysis design and reporting |
| figures | Figures | figure construction and labelling |
| framing | Accuracy and framing | factual errors, overclaims |
| refs | References | bibliography problems |
| typos | Typos and wording | language fixes (usually with a suggestion) |
| coauthor | Co-author comments | imported Word comments; users often move their own notes here |
| mine | My notes | default for notes users add in the tool |
