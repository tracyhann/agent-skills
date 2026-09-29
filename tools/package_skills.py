#!/usr/bin/env python3
"""Build uploadable .skill archives (zip) for claude.ai into dist/.

    python tools/package_skills.py              # every skill
    python tools/package_skills.py NAME [...]   # selected skills
"""
import fnmatch
import sys
import zipfile
from skill_meta import ROOT, skills

SKIP_DIRS = {"__pycache__", "node_modules", ".pytest_cache"}
SKIP_FILES = {".DS_Store"}
SKIP_GLOBS = ("*.pyc",)


def main():
    want = set(sys.argv[1:])
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
        print(f"{out.relative_to(ROOT)}  ({s['version']})")


if __name__ == "__main__":
    main()
