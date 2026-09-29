#!/usr/bin/env python3
"""Scaffold a new skill: skills/<name>/SKILL.md, a tests/<name>/ folder and a CHANGELOG section.

    python tools/new_skill.py my-skill-name
    python tools/new_skill.py my-skill-name --scripts   # also create scripts/ with a stub

The generated SKILL.md fails validation until its TODO description is replaced, so a
half-finished skill cannot slip through CI.
"""
import argparse
import re
import sys
from skill_meta import ROOT, SKILLS

TEMPLATE = """\
---
name: {name}
description: TODO what this skill does, then the situations and phrasings that should trigger it. One line, at most 1024 characters, no angle brackets.
license: MIT
metadata:
  version: "1.0.0"
---

# {title}

One or two sentences: what the skill produces and for whom.

## Before starting

- Inputs the skill expects and how to handle missing or unusual ones.
- Questions to ask the user once, if the answer is not already known.

## Workflow

### 1. First step

What to do, with the exact command if a script is involved:

```bash
python scripts/example.py INPUT OUTPUT
```

### 2. Next step

Keep SKILL.md under 500 lines; move long guidance into files under references/ and say
which step should read each one.

## Things that went wrong before (avoid them)

- Record real failures here as they happen, so later runs do not repeat them.
"""

STUB = '''#!/usr/bin/env python3
"""Describe what this script does and how SKILL.md calls it.

    python scripts/example.py INPUT OUTPUT
"""
import sys


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    raise SystemExit("not implemented yet")


if __name__ == "__main__":
    main(sys.argv)
'''


def add_changelog_section(name):
    path = ROOT / "CHANGELOG.md"
    text = path.read_text()
    section = f"## {name}\n\n### 1.0.0\n- Initial version.\n\n"
    # keep skill sections alphabetical; "Repository" always stays last
    for m in re.finditer(r"^## (.+?)\s*$", text, re.M):
        heading = m.group(1)
        if heading == "Repository" or heading > name:
            path.write_text(text[:m.start()] + section + text[m.start():])
            return
    path.write_text(text.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="kebab-case skill name, e.g. figure-style-checker")
    ap.add_argument("--scripts", action="store_true", help="also create scripts/example.py")
    args = ap.parse_args()

    name = args.name
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        sys.exit("name must be kebab-case (lowercase letters, digits, hyphens), at most 64 characters")
    skill = SKILLS / name
    if skill.exists():
        sys.exit(f"{skill.relative_to(ROOT)} already exists")

    skill.mkdir(parents=True)
    title = name.replace("-", " ").capitalize()
    (skill / "SKILL.md").write_text(TEMPLATE.format(name=name, title=title))
    if args.scripts:
        (skill / "scripts").mkdir()
        (skill / "scripts" / "example.py").write_text(STUB)
    tests = ROOT / "tests" / name
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "fixtures").mkdir(exist_ok=True)
    (tests / "fixtures" / ".gitkeep").touch()
    add_changelog_section(name)

    print(f"created skills/{name}/SKILL.md, tests/{name}/ and a CHANGELOG section")
    print("next: write the description and body, add tests, then run")
    print("  python tools/validate_skills.py && python tools/build_index.py && pytest -q tests")


if __name__ == "__main__":
    main()
