# Contributing

How to add, change and release skills in this library. For installing and using them, see the
[README](README.md).

- [Set up](#set-up)
- [Add a skill](#add-a-skill)
- [Writing a good skill](#writing-a-good-skill)
- [Update a skill](#update-a-skill)
- [Checks](#checks)
- [Release](#release)
- [Repository tooling](#repository-tooling)

## Set up

```bash
git clone https://github.com/tracyhann/agent-skills.git && cd agent-skills
python -m venv .venv && source .venv/bin/activate
pip install pytest
for req in skills/*/requirements.txt; do pip install -r "$req"; done
python -m playwright install chromium      # browser smoke tests (optional)
brew install pandoc                        # or: sudo apt-get install pandoc
```

The repository tools in `tools/` use only the Python standard library (3.10+).

## Add a skill

1. Scaffold it:
   ```bash
   python tools/new_skill.py my-skill-name            # add --scripts for a scripts/ stub
   ```
   This creates `skills/my-skill-name/SKILL.md` from the template, an empty
   `tests/my-skill-name/fixtures/` folder and a `1.0.0` section in `CHANGELOG.md`.
2. Replace the TODO description and write the body (see below). Validation fails until the
   TODO is gone.
3. Put code in `scripts/`, long guidance in `references/`, templates and other output files in
   `assets/`, and Python dependencies in `requirements.txt`. List system tools (pandoc, a
   browser, ...) in the `compatibility` frontmatter field.
4. Add tests under `tests/my-skill-name/` with small synthetic fixtures.
5. Run the [checks](#checks), regenerate the index (`python tools/build_index.py`) and open a
   pull request.

## Writing a good skill

**Folder.** One folder per skill under `skills/`, named in kebab-case, with the same value in
the `name` field. Everything in the folder ships with the skill, so keep it to what Claude
needs at run time: no README, notes or build output inside it. `SKILL.md` is the
documentation, and the README table links to it.

**Frontmatter.** Allowed keys: `name`, `description`, `license` (`MIT`), `compatibility`,
`allowed-tools` and `metadata` (with `version`). Keep each value on one line; the tools read
the frontmatter without a YAML library.

**Description.** This is what decides whether Claude loads the skill, so write it for
triggering: first what the skill does, then the requests and phrasings that should load it,
including indirect ones ("even if they never say ..."). At most 1024 characters, no angle
brackets. The first sentence becomes the summary in the README table and the plugin listing.

**Body.**
- Write instructions for Claude, in the imperative, as numbered workflow steps with the exact
  commands to run.
- Keep `SKILL.md` under 500 lines. Move detail into `references/` and say which step should
  read each file, so it only loads when needed.
- Put deterministic work (parsing, validation, building outputs) in `scripts/`, with a usage
  docstring and clear `OK` / `ERROR` output that Claude can act on.
- Skills run in more than one place (claude.ai's sandbox, Claude Code on a laptop, the API).
  Name default paths, and say what to do where a tool or path is missing.
- Keep a "Things that went wrong before" section and add to it whenever a run goes wrong in a
  way written instructions would have prevented.

**Privacy.** Never commit manuscripts, review notes, datasets, real names or other
unpublished material. Fixtures must be synthetic and small.

## Update a skill

- Change the skill, then bump `metadata.version` in its `SKILL.md`:
  - patch (1.1.0 → 1.1.1): fixes that do not change behaviour users rely on
  - minor (1.1.0 → 1.2.0): new capability, backwards compatible (new input format, new option)
  - major (1.x → 2.0.0): breaking change (renamed scripts, changed note or file formats)
- Add a `### <version> — <date>` entry under the skill's section in `CHANGELOG.md`; the
  validator fails without one.
- Regenerate the index: `python tools/build_index.py`.

Repository-only changes (tooling, CI, docs) do not bump any skill; note them under
"Repository" in the CHANGELOG.

## Checks

```bash
python tools/validate_skills.py     # frontmatter, structure, CHANGELOG entry for each version
python tools/build_index.py --check # README table and marketplace file are current
pytest -q tests                     # end-to-end tests
```

CI runs the same checks on Python 3.10 and 3.12 for every push to `main` and every pull
request, and uploads the packaged `.skill` files as a build artifact.

## Release

Release one skill at a time, after its version bump is merged to `main`:

```bash
git tag -a manuscript-review-annotator-v1.1.0 -m "manuscript-review-annotator 1.1.0"
git push origin manuscript-review-annotator-v1.1.0
```

Pushing a `<skill-name>-v<version>` tag runs the release workflow: it checks that the tag
matches the skill's `metadata.version`, takes the release notes from the CHANGELOG, and
publishes a GitHub release with `<skill-name>.skill` attached for claude.ai users. Claude Code
users pick up the new version from `main` through the marketplace (see
[Updating](README.md#updating) in the README).

## Repository tooling

| Script | Purpose |
|---|---|
| `tools/new_skill.py` | scaffold a skill, its tests folder and its CHANGELOG section |
| `tools/validate_skills.py` | check every skill against the Agent Skills rules and the conventions above |
| `tools/build_index.py` | regenerate the README table and `.claude-plugin/marketplace.json` from the skills |
| `tools/package_skills.py` | build `dist/<name>.skill` archives for claude.ai |
| `tools/release_notes.py` | check a release tag and print its CHANGELOG notes (used by the release workflow) |
| `tools/skill_meta.py` | shared helpers: find skills, read frontmatter |
