#!/usr/bin/env python3
"""Validate every skill in skills/ against the Agent Skills rules claude.ai and the API enforce,
plus this repository's own conventions (versioned, changelogged, tested).

    python tools/validate_skills.py

Errors fail the run (exit 1); warnings are printed but do not fail it.
"""
import re
import sys
from skill_meta import ROOT, skills

ALLOWED = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
SEMVER = re.compile(r"\d+\.\d+\.\d+")
CHANGELOG = ROOT / "CHANGELOG.md"


def changelog_has(name, version):
    """True if CHANGELOG.md has a '## <name>' section containing a '### <version>' heading."""
    text = CHANGELOG.read_text() if CHANGELOG.is_file() else ""
    m = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return bool(m and re.search(rf"^### {re.escape(version)}\b", m.group(1), re.M))


def check(s):
    """Return (errors, warnings) for one skill."""
    errs, warns = [], []
    d, fm = s["dir"], s["frontmatter"]
    extra = [p for p in d.rglob("SKILL.md") if p != d / "SKILL.md"]
    if extra:
        errs.append(f"extra SKILL.md files: {[str(p.relative_to(d)) for p in extra]}")
    if not fm:
        return errs + ["SKILL.md has no YAML frontmatter"], warns
    if set(fm) - ALLOWED:
        errs.append(f"unexpected frontmatter keys {sorted(set(fm) - ALLOWED)}")
    name = s["name"]
    if name != d.name:
        errs.append(f"name {name!r} must match folder {d.name!r}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name or "") or len(name) > 64:
        errs.append("name must be kebab-case, at most 64 characters")
    desc = s["description"]
    if isinstance(desc, dict) or desc.strip() in {">", ">-", "|", "|-"}:
        errs.append("description must be a single line in the frontmatter (no YAML block scalars)")
        desc = ""
    if not desc or len(desc) > 1024 or "<" in desc or ">" in desc:
        errs.append("description required, at most 1024 characters, no angle brackets")
    elif "TODO" in desc:
        errs.append("description still has the TODO placeholder from tools/new_skill.py")
    comp = fm.get("compatibility")
    if comp and len(comp) > 500:
        errs.append("compatibility at most 500 characters")
    if not SEMVER.fullmatch(s["version"] or ""):
        errs.append("set metadata.version to a semver string (e.g. \"1.0.0\") so releases and the index can track it")
    elif not changelog_has(name, s["version"]):
        errs.append(f"CHANGELOG.md needs a '### {s['version']}' entry under '## {name}'")
    if not (ROOT / "tests" / d.name).is_dir():
        warns.append(f"no tests/{d.name}/ folder; add tests if the skill ships scripts")
    body = (d / "SKILL.md").read_text()
    if len(body.splitlines()) > 500:
        errs.append("SKILL.md over 500 lines; move detail into references/")
    for ref in set(re.findall(r"`((?:scripts|references|assets)/[^`\s]+)`", body)):
        if not (d / ref.split()[0]).exists():
            errs.append(f"SKILL.md mentions missing file {ref}")
    return errs, warns


def main():
    found = list(skills())
    if not found:
        sys.exit("no skills found under skills/")
    bad = 0
    for s in found:
        errs, warns = check(s)
        status = "ok" if not errs else "FAIL"
        print(f"{status:4} {s['name'] or s['dir'].name} {s['version']}")
        for e in errs:
            print(f"     - {e}")
        for w in warns:
            print(f"     ~ warning: {w}")
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
