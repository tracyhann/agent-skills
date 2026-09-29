#!/usr/bin/env python3
"""Check a release tag against the skill it names and print that version's CHANGELOG notes.

    python tools/release_notes.py manuscript-review-annotator-v1.1.0

Exits 1 if the skill does not exist, its metadata.version differs from the tag, or the
CHANGELOG has no entry for that version. Used by .github/workflows/release.yml.
"""
import re
import sys
from skill_meta import ROOT, skills


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tag = sys.argv[1]
    m = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)-v(\d+\.\d+\.\d+)", tag)
    if not m:
        sys.exit(f"tag {tag!r} is not <skill-name>-v<major.minor.patch>")
    name, version = m.groups()
    skill = next((s for s in skills() if s["name"] == name), None)
    if skill is None:
        sys.exit(f"no skill named {name!r} under skills/")
    if skill["version"] != version:
        sys.exit(f"tag says {version} but skills/{name}/SKILL.md has metadata.version {skill['version']}")

    text = (ROOT / "CHANGELOG.md").read_text()
    sec = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    ver = sec and re.search(rf"^### {re.escape(version)}\b[^\n]*\n(.*?)(?=^### |\Z)", sec.group(1), re.M | re.S)
    if not ver:
        sys.exit(f"CHANGELOG.md has no '### {version}' entry under '## {name}'")
    print(ver.group(1).strip())


if __name__ == "__main__":
    main()
