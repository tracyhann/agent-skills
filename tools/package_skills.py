#!/usr/bin/env python3
"""Build uploadable .skill archives (zip) for claude.ai into dist/.

    python tools/package_skills.py              # every skill
    python tools/package_skills.py NAME [...]   # selected skills

Each archive holds one top-level folder, <name>/, with the skill's files. The repository
LICENSE is added as <name>/LICENSE.txt unless the skill ships its own licence file.
"""
import fnmatch
import sys
import zipfile
from skill_meta import ROOT, skills

SKIP_DIRS = {"__pycache__", "node_modules", ".pytest_cache"}
SKIP_FILES = {".DS_Store"}
SKIP_GLOBS = ("*.pyc",)
LICENSE = ROOT / "LICENSE"


def main():
    want = set(sys.argv[1:])
    unknown = want - {s["name"] for s in skills()}
    if unknown:
        sys.exit(f"unknown skill(s): {sorted(unknown)}")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for s in skills():
        if want and s["name"] not in want:
            continue
        out = dist / f"{s['name']}.skill"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(s["dir"].rglob("*")):
                rel = p.relative_to(s["dir"].parent)
                if p.is_dir() or SKIP_DIRS & set(rel.parts) or p.name in SKIP_FILES or any(fnmatch.fnmatch(p.name, g) for g in SKIP_GLOBS):
                    continue
                z.write(p, rel)
            if LICENSE.is_file() and not any(s["dir"].glob("LICENSE*")):
                z.write(LICENSE, f"{s['name']}/LICENSE.txt")
        print(f"{out.relative_to(ROOT)}  ({s['version']})")


if __name__ == "__main__":
    main()
