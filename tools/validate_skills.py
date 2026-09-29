#!/usr/bin/env python3
"""Validate every skill in skills/ against the Agent Skills rules claude.ai and the API enforce.

    python tools/validate_skills.py
"""
import re
import sys
from pathlib import Path
from skill_meta import SKILLS, skills, parse_frontmatter

ALLOWED = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}


def check(s):
    errs = []
    d, fm = s["dir"], s["frontmatter"]
    extra = [p for p in d.rglob("SKILL.md") if p != d / "SKILL.md"]
    if extra:
        errs.append(f"extra SKILL.md files: {[str(p.relative_to(d)) for p in extra]}")
    if not fm:
        return errs + ["SKILL.md has no YAML frontmatter"]
    if set(fm) - ALLOWED:
        errs.append(f"unexpected frontmatter keys {sorted(set(fm) - ALLOWED)}")
    name = s["name"]
    if name != d.name:
        errs.append(f"name {name!r} must match folder {d.name!r}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name or "") or len(name) > 64:
        errs.append("name must be kebab-case, at most 64 characters")
    desc = s["description"]
    if not desc or len(desc) > 1024 or "<" in desc or ">" in desc:
        errs.append("description required, at most 1024 characters, no angle brackets")
    comp = fm.get("compatibility")
    if comp and len(comp) > 500:
        errs.append("compatibility at most 500 characters")
    if not s["version"]:
        errs.append("set metadata.version (semver) so releases and the index can track it")
    body = (d / "SKILL.md").read_text()
    if len(body.splitlines()) > 500:
        errs.append("SKILL.md over 500 lines; move detail into references/")
    for ref in set(re.findall(r"`((?:scripts|references|assets)/[^`\s]+)`", body)):
        if not (d / ref.split()[0]).exists():
            errs.append(f"SKILL.md mentions missing file {ref}")
    return errs


def main():
    found = list(skills())
    if not found:
        sys.exit("no skills found under skills/")
    bad = 0
    for s in found:
        errs = check(s)
        status = "ok" if not errs else "FAIL"
        print(f"{status:4} {s['name'] or s['dir'].name} {s['version']}")
        for e in errs:
            print(f"     - {e}")
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
