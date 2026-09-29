# agent-skills

Agent Skills for research work: packaged instructions, scripts and templates that Claude loads
when a task calls for them. Each skill lives in its own folder under [`skills/`](skills/) and works
in Claude Code, claude.ai and the Claude API.

## Skills

<!-- skills-index:start -->
| Skill | Version | What it does |
|---|---|---|
| [`manuscript-review-annotator`](skills/manuscript-review-annotator/SKILL.md) | 1.1.0 | Review a research manuscript (Word .docx, LaTeX source or PDF) thoroughly and deliver the review as an interactive annotation page — the full paper with figures and tables, every issue pre-highlighted in the text or boxed on the figure, editable and shareable with co-authors — plus clean exports and a standalone read-only report. |
<!-- skills-index:end -->

The table and the Claude Code marketplace file are generated from each skill's `SKILL.md`
(`python tools/build_index.py`); edit the skill, not the table.

## Install

### Claude Code

Add this repository as a plugin marketplace, then install the skills you want:

```
/plugin marketplace add tracyhann/agent-skills
/plugin install manuscript-review-annotator@tracyhann-agent-skills
```

Or copy a skill folder into `~/.claude/skills/` (all your projects) or `.claude/skills/`
(one project). See the [Claude Code skills docs](https://docs.claude.com/en/docs/claude-code/skills).

### claude.ai

Download a `.skill` file from [Releases](https://github.com/tracyhann/agent-skills/releases)
(or build one with `python tools/package_skills.py`) and upload it under Skills in your
claude.ai settings.

### Dependencies

Skills that run code list their Python packages in `skills/<name>/requirements.txt` and
system tools in the `compatibility` field of their `SKILL.md`. For
`manuscript-review-annotator`:

```bash
pip install -r skills/manuscript-review-annotator/requirements.txt
python -m playwright install chromium     # optional, for smoke tests
# plus pandoc: brew install pandoc  |  sudo apt-get install pandoc
```

## Repository layout

```
agent-skills/
├── skills/                     one folder per skill (this is what gets installed)
│   └── <skill-name>/
│       ├── SKILL.md            instructions + frontmatter (name, description, metadata.version)
│       ├── scripts/            code the skill runs
│       ├── references/         detail loaded only when a step needs it
│       ├── assets/             templates and other files used in outputs
│       └── requirements.txt    Python dependencies, if any
├── tests/<skill-name>/         end-to-end tests and small synthetic fixtures
├── tools/                      repo tooling: validate, index, package
├── .claude-plugin/             Claude Code marketplace definition (generated plugin list)
├── .github/workflows/ci.yml    validation, tests and packaging on every push
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## Maintaining

```bash
python tools/validate_skills.py     # frontmatter and structure rules
python tools/build_index.py         # refresh the table above and the marketplace file
pytest -q tests                     # end-to-end tests
python tools/package_skills.py      # dist/<name>.skill for claude.ai
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for adding a skill, versioning and releases.

Never commit manuscripts, review notes or other unpublished material: test fixtures must be
synthetic.
