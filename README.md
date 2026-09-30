# agent-skills

[![CI](https://github.com/tracyhann/agent-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/tracyhann/agent-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A library of [Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
for research work: packaged instructions, scripts and templates that Claude loads when a task
calls for them. Each skill lives in its own folder under [`skills/`](skills/) and works in
Claude Code, claude.ai and the Claude API.

## Skills

<!-- skills-index:start -->
| Skill | Version | What it does |
|---|---|---|
| [`manuscript-review-annotator`](skills/manuscript-review-annotator/SKILL.md) | 1.4.0 | Review a research manuscript (Word .docx, LaTeX source or PDF) thoroughly and deliver the review as an interactive annotation page — the full paper with figures and tables, every issue pre-highlighted in the text or boxed on the figure, shared with co-authors who discuss notes in signed reply threads and edit the manuscript text in place to address them (tracked changes, one-click suggestions) — plus clean exports, a read-only report, and a patch that carries the page's edits back into the LaTeX source. |
<!-- skills-index:end -->

The table and the Claude Code marketplace file are generated from each skill's `SKILL.md`
(`python tools/build_index.py`); edit the skill, not the table. Each skill's history is in
[CHANGELOG.md](CHANGELOG.md).

## Install

### Claude Code

Add this repository as a plugin marketplace, then install the skills you want:

```
/plugin marketplace add tracyhann/agent-skills
/plugin install manuscript-review-annotator@tracyhann-agent-skills
```

Or copy a skill folder into `~/.claude/skills/` (all your projects) or `.claude/skills/`
(one project). See [Claude Code skills](https://code.claude.com/docs/en/skills).

### claude.ai

Download `<skill-name>.skill` from [Releases](https://github.com/tracyhann/agent-skills/releases)
(or build it with `python tools/package_skills.py`) and upload it under Skills in your
claude.ai settings. Code execution must be enabled.

### Claude API

Upload the skill folder through the Skills API and use it with the code execution tool. See
[Using Agent Skills with the API](https://platform.claude.com/docs/en/build-with-claude/skills-guide).

### Dependencies

Skills that run code list their Python packages in `skills/<name>/requirements.txt` and
system tools in the `compatibility` field of their `SKILL.md`. For
`manuscript-review-annotator`:

```bash
pip install -r skills/manuscript-review-annotator/requirements.txt
python -m playwright install chromium     # optional, for smoke tests
# plus pandoc: brew install pandoc  |  sudo apt-get install pandoc
```

### Updating

- Claude Code: `claude plugin marketplace update tracyhann-agent-skills`, then
  `claude plugin update manuscript-review-annotator@tracyhann-agent-skills`.
- claude.ai: download the newer `.skill` from Releases and upload it again.
- Copied folders: pull this repository and copy the folder again.

## Repository layout

```
agent-skills/
├── skills/                     one folder per skill (this is what gets installed)
│   └── <skill-name>/
│       ├── SKILL.md            instructions + frontmatter (name, description, license, metadata.version)
│       ├── scripts/            code the skill runs
│       ├── references/         detail loaded only when a step needs it
│       ├── assets/             templates and other files used in outputs
│       └── requirements.txt    Python dependencies, if any
├── tests/<skill-name>/         end-to-end tests and small synthetic fixtures
├── tools/                      repo tooling: scaffold, validate, index, package, release notes
├── .claude-plugin/             Claude Code marketplace definition (generated plugin list)
├── .github/                    CI and release workflows, issue and pull request templates
├── CHANGELOG.md                per-skill version history
├── CONTRIBUTING.md             how to add, update and release skills
└── LICENSE                     MIT
```

## Maintaining

```bash
python tools/new_skill.py <skill-name>   # scaffold a new skill
python tools/validate_skills.py          # frontmatter, structure and CHANGELOG rules
python tools/build_index.py              # refresh the table above and the marketplace file
pytest -q tests                          # end-to-end tests
python tools/package_skills.py           # dist/<name>.skill for claude.ai
```

Versioning, conventions for writing skills, and the release process (push a
`<skill-name>-v<version>` tag) are in [CONTRIBUTING.md](CONTRIBUTING.md).

Never commit manuscripts, review notes or other unpublished material: test fixtures must be
synthetic.

## License

[MIT](LICENSE)
