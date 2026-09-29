## What changes

<!-- Which skill(s), and what the change does for someone using them. -->

## Checklist

- [ ] `metadata.version` bumped in each changed skill's `SKILL.md` (patch / minor / major, see CONTRIBUTING.md)
- [ ] `CHANGELOG.md` entry added under the skill for the new version
- [ ] `python tools/build_index.py` run (README table and marketplace file regenerated)
- [ ] `python tools/validate_skills.py` and `pytest -q tests` pass locally
- [ ] Test fixtures are synthetic: no manuscripts, review notes, data or other unpublished material
