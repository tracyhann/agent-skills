# Contributing

## Add a skill

1. Create `skills/<skill-name>/SKILL.md`. The folder name and the `name` field must match and be
   kebab-case. Frontmatter allows `name`, `description`, `license`, `allowed-tools`,
   `compatibility` and `metadata`; set `metadata.version` (start at `1.0.0`).
2. Put code in `scripts/`, long guidance in `references/`, templates in `assets/`, and Python
   dependencies in `requirements.txt`. Keep `SKILL.md` under 500 lines.
3. Write the `description` for triggering: what the skill does and the situations it should
   be used in (at most 1024 characters, no angle brackets).
4. Add tests under `tests/<skill-name>/` with small synthetic fixtures.
5. Run the checks below, add a CHANGELOG entry, and open a pull request.

## Update a skill

- Change the skill, then bump `metadata.version`:
  - patch (1.1.0 → 1.1.1): fixes that do not change behaviour users rely on
  - minor (1.1.0 → 1.2.0): new capability, backwards compatible (new input format, new option)
  - major (1.x → 2.0.0): breaking change (renamed scripts, changed note or file formats)
- Add an entry under the skill in `CHANGELOG.md`.
- Regenerate the index: `python tools/build_index.py`.

## Checks

```bash
python tools/validate_skills.py
python tools/build_index.py --check
pytest -q tests
```
CI runs the same checks and uploads the packaged `.skill` files as a build artifact.

## Release

```bash
python tools/package_skills.py
git tag <skill-name>-v<version>      # e.g. manuscript-review-annotator-v1.1.0
git push --tags
```
Attach `dist/<skill-name>.skill` to the GitHub release so claude.ai users can download it.
