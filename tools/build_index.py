#!/usr/bin/env python3
"""Regenerate the skills table in README.md and the plugin list in .claude-plugin/marketplace.json
from each skill's SKILL.md, so the index never drifts from the skills themselves.

    python tools/build_index.py          # rewrite both files
    python tools/build_index.py --check  # exit 1 if either is out of date (used in CI)
"""
import json
import re
import sys
from skill_meta import ROOT, skills

README = ROOT / "README.md"
MARKET = ROOT / ".claude-plugin" / "marketplace.json"
START, END = "<!-- skills-index:start -->", "<!-- skills-index:end -->"


def short(desc):
    first = re.split(r"(?<=[.!?])\s", desc.strip(), maxsplit=1)[0]
    return first.replace("|", "\\|")


def table(items):
    rows = ["| Skill | Version | What it does |", "|---|---|---|"]
    for s in items:
        rows.append(f"| [`{s["name"]}`](skills/{s["name"]}/SKILL.md) | {s['version']} | {short(s['description'])} |")
    return "\n".join(rows)


def main():
    items = list(skills())
    readme = README.read_text()
    new_readme = re.sub(re.escape(START) + r".*?" + re.escape(END), f"{START}\n{table(items)}\n{END}", readme, flags=re.S)
    market = json.loads(MARKET.read_text())
    market["plugins"] = [{"name": s["name"], "description": short(s["description"]), "version": s["version"],
                          "source": "./", "strict": False, "skills": [f"./skills/{s['name']}"]} for s in items]
    new_market = json.dumps(market, indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        stale = [p.name for p, old, new in ((README, readme, new_readme), (MARKET, MARKET.read_text(), new_market)) if old != new]
        if stale:
            sys.exit(f"out of date: {stale}; run python tools/build_index.py")
        print("index up to date")
        return
    README.write_text(new_readme)
    MARKET.write_text(new_market)
    print(f"indexed {len(items)} skill(s)")


if __name__ == "__main__":
    main()
