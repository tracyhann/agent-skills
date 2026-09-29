"""Shared helpers: find skills and read their SKILL.md frontmatter (stdlib only)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return None
    data, key = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")) and key:
            sub = line.strip()
            if ":" in sub:
                k, v = sub.split(":", 1)
                data.setdefault(key, {})
                if isinstance(data[key], dict):
                    data[key][k.strip()] = v.strip().strip('"').strip("'")
            continue
        k, _, v = line.partition(":")
        key = k.strip()
        v = v.strip()
        data[key] = v.strip('"').strip("'") if v else {}
    return data


def skills():
    for d in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()):
        fm = parse_frontmatter((d / "SKILL.md").read_text()) or {}
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        yield {"dir": d, "name": fm.get("name", ""), "description": fm.get("description", ""),
               "version": meta.get("version", ""), "frontmatter": fm}
