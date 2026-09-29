"""End-to-end checks for manuscript-review-annotator on small fixtures (Word, LaTeX, PDF).

    pytest tests/manuscript-review-annotator -q
Needs pandoc on PATH and skills/manuscript-review-annotator/requirements.txt installed.
The browser smoke tests run only when playwright + chromium are available.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "manuscript-review-annotator" / "scripts"
FIX = Path(__file__).resolve().parent / "fixtures"

CASES = {
    # fixture: (min figures, min tables, min refs, reviewer comments, a phrase that must be extractable)
    "sample.docx": (1, 1, 2, 1, "Forty-two participants were recruited"),
    "latex/main.tex": (2, 1, 2, 0, "Forty-two participants were recruited from the clinic"),
    "sample_two_column.pdf": (2, 1, 2, 2, "Forty-two participants were recruited from the clinic"),
}


def run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, f"{args[0]} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def have_browser():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser_ok():
    return have_browser()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
@pytest.mark.parametrize("fixture", list(CASES))
def test_pipeline(fixture, tmp_path, browser_ok):
    nfig, ntab, nref, ncom, phrase = CASES[fixture]
    doc = tmp_path / "doc"
    run(SCRIPTS / "extract.py", FIX / fixture, doc)

    blocks = json.loads((doc / "doc.json").read_text())["blocks"]
    texts = json.loads((doc / "texts.json").read_text())
    kinds = [b["kind"] for b in blocks]
    assert kinds.count("figure") >= nfig
    assert kinds.count("table") >= ntab
    assert kinds.count("ref") >= nref
    assert any(k in ("h2", "h3") for k in kinds)
    assert all(b.get("caption") for b in blocks if b["kind"] in ("figure", "table") and not b.get("equation"))
    assert any(phrase in t for t in texts.values()), f"{phrase!r} not found"
    comments = json.loads((doc / "comments.json").read_text())
    assert len(comments) == ncom and all(c["block"] for c in comments)

    fig = next(b["id"] for b in blocks if b["kind"] == "figure")
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps([
        {"cat": "numbers", "exact": phrase[:22], "comment": "Check against the abstract."},
        {"cat": "typos", "exact": phrase[:22], "comment": "Wording.", "suggestion": phrase[:22].upper()},
        {"cat": "figures", "fig": fig, "box": [0.05, 0.05, 0.4, 0.4], "comment": "Panel label?"},
        {"cat": "blocker", "kind": "note", "comment": "General note."},
    ]))
    seed = tmp_path / "seed"
    run(SCRIPTS / "validate_notes.py", doc, draft, seed, "--author", "tester", "--comments", doc / "comments.json")
    seeds = json.loads((seed / "seeds.json").read_text())
    assert len(seeds) == 4 + ncom
    assert all(s["author"] for s in seeds)
    assert list((seed / "batches").glob("batch_*.json"))

    tool, report = tmp_path / "tool.html", tmp_path / "report.html"
    run(SCRIPTS / "build_html.py", "tool", doc, tool, "--doc-name", Path(fixture).name)
    run(SCRIPTS / "build_html.py", "report", doc, seed / "seeds.json", report, "--doc-name", Path(fixture).name,
        "--author-map", "tester=reviewer")
    html = tool.read_text()
    assert "__DOC__" not in html and "__IMGS__" not in html and "showEdits: true" in html
    assert "__STATIC__" not in report.read_text()

    clean = tmp_path / "clean"
    run(SCRIPTS / "notes_ops.py", "clean", doc, seed / "seeds.json", clean)
    assert json.loads(clean.with_suffix(".json").read_text())["annotations"]

    if browser_ok:
        out = run(SCRIPTS / "smoke_test.py", tool, "--notes", seed / "seeds.json")
        assert "OK" in out and "orphans: []" in out
        out = run(SCRIPTS / "smoke_test.py", report)
        assert "readOnly: True" in out


def test_invalid_anchor_is_rejected(tmp_path):
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not installed")
    doc = tmp_path / "doc"
    run(SCRIPTS / "extract.py", FIX / "sample.docx", doc)
    draft = tmp_path / "bad.json"
    draft.write_text(json.dumps([{"cat": "typos", "exact": "text that is not in the paper", "comment": "x"}]))
    r = subprocess.run([sys.executable, SCRIPTS / "validate_notes.py", doc, draft, tmp_path / "s", "--author", "t"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "not found" in r.stdout
