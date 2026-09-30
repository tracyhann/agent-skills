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


def static_of(html):
    """The notes, edits and replies baked into a read-only report."""
    return json.loads(html.split("<script>window.REVIEW_SNAPSHOT = ", 1)[1].split(";</script>", 1)[0])


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
        {"cat": "numbers", "exact": phrase[:22], "comment": "Check against the abstract.",
         "replies": [{"text": "Checked: <b>matches</b> the abstract.", "author": "coauthor", "date": "2026-07-28"}]},
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
    replies = json.loads((seed / "replies.json").read_text())
    assert len(replies) == 1 and replies[0]["author"] == "coauthor" and replies[0]["createdAt"].startswith("2026-07-28")
    assert replies[0]["note"] in {s["id"] for s in seeds} and replies[0]["id"] == replies[0]["note"] + "-c1"
    writes = [w for f in sorted((seed / "batches").glob("batch_*.json")) for w in json.loads(f.read_text())]
    assert [w["collection"] for w in writes].count("replies") == 1 and writes[-1]["collection"] == "replies"

    tool, report = tmp_path / "tool.html", tmp_path / "report.html"
    run(SCRIPTS / "build_html.py", "tool", doc, tool, "--doc-name", Path(fixture).name)
    run(SCRIPTS / "build_html.py", "report", doc, seed / "seeds.json", report, "--doc-name", Path(fixture).name,
        "--author-map", "tester=reviewer", "--replies", seed / "replies.json")
    html = tool.read_text()
    assert "__DOC__" not in html and "__IMGS__" not in html and "showEdits: true" in html
    assert "__STATIC__" not in report.read_text()

    clean = tmp_path / "clean"
    run(SCRIPTS / "notes_ops.py", "clean", doc, seed / "seeds.json", clean, "--replies", seed / "replies.json")
    cj = json.loads(clean.with_suffix(".json").read_text())
    assert cj["annotations"] and len(cj["replies"]) == 1
    assert "**coauthor** (2026-07-28): Checked: <b>matches</b> the abstract." in clean.with_suffix(".md").read_text()

    if browser_ok:
        out = run(SCRIPTS / "smoke_test.py", tool, "--notes", seed / "seeds.json")
        assert "OK" in out and "orphans: []" in out
        out = run(SCRIPTS / "smoke_test.py", report)
        assert "readOnly: True" in out and "signingAs: None" in out and "replies: 1" in out
        out = run(SCRIPTS / "smoke_test.py", tool, "--notes", seed / "seeds.json", "--replies", seed / "replies.json",
                  "--exercise-edits", "--exercise-comments", "--exercise-report")
        assert "PASS  the report carries every note, reply and text edit" in out
        assert "OK" in out and "FAIL" not in out and "PASS  Apply replaces the quoted text" in out
        assert "PASS  reply is posted and signed" in out and "PASS  reply text is shown as text, never HTML" in out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_latex_tables_keep_cell_text(tmp_path):
    """Column specs with >{..}/@{..}, \\resizebox, \\shortstack and a longtable head used to lose cells."""
    doc = tmp_path / "doc"
    out = run(SCRIPTS / "extract.py", FIX / "latex_tables" / "tables.tex", doc)
    assert "WARNING" not in out
    tables = [b for b in json.loads((doc / "doc.json").read_text())["blocks"] if b["kind"] == "table"]
    assert len(tables) == 2
    assert tables[0]["rows"] == [["Site name", "Mean score", "N"], ["North clinic", "12.5", "30"], ["South clinic", "14.0", "28"]]
    assert tables[1]["rows"] == [["Visit", "Window"], ["Baseline", "Day 0"], ["Follow-up", "Week 4"]]
    assert all(t.get("caption") for t in tables)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_edits_carry_back_to_latex(tmp_path, browser_ok):
    src = FIX / "latex"
    before = (src / "main.tex").read_text()
    doc = tmp_path / "doc"
    run(SCRIPTS / "extract.py", src / "main.tex", doc)
    texts = json.loads((doc / "texts.json").read_text())
    blocks = json.loads((doc / "doc.json").read_text())["blocks"]
    starts = lambda s: next(k for k, v in texts.items() if v.startswith(s))
    para, abstract = starts("Forty-two participants"), starts("We tested 40")
    tab = next(b for b in blocks if b["kind"] == "table")
    ref = next(b for b in blocks if b["kind"] == "ref")
    rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in tab["rows"])
    edits = [
        {"block": para, "text": texts[para].replace("from the clinic", "from two clinics")},
        # the abstract uses a \newcommand macro next to the edited word
        {"block": abstract, "text": texts[abstract].replace("connectivity decreased", "connectivity declined")},
        {"block": tab["id"], "html": f'<div class="tcap">{tab["caption"]}</div><table>{rows.replace("42.1", "42.4")}</table>'},
        {"block": ref["id"], "text": texts[ref["id"]].replace("Respiration", "Breathing")},
    ]
    for e in edits:
        e.setdefault("html", e.get("text"))
        e.setdefault("text", e["html"])
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"format": "review-notes", "version": 2, "annotations": [], "edits": edits}))

    out = tmp_path / "applied"
    run(SCRIPTS / "apply_edits.py", doc, export, src, out)
    patched = (out / "project" / "main.tex").read_text()
    assert "from two clinics" in patched and "\\roi{} connectivity declined" in patched
    assert "Active & 21 & 42.4" in patched
    assert (src / "main.tex").read_text() == before, "the source must never be modified"
    hunks = json.loads((out / "hunks.json").read_text())
    assert sum(h["status"] == "applied" for h in hunks) == 3
    manual = [h for h in hunks if h["status"] == "manual"]
    assert len(manual) == 1 and manual[0]["block"] == ref["id"] and ".bib" in manual[0]["reason"]
    diff = (out / "changes.diff").read_text().splitlines()
    assert sum(l.startswith("+") and not l.startswith("+++") for l in diff) == 3
    assert "Breathing" in (out / "apply_report.md").read_text()

    report = tmp_path / "report.html"
    run(SCRIPTS / "build_html.py", "report", doc, export, report, "--doc-name", "main.tex")
    if browser_ok:
        res = run(SCRIPTS / "smoke_test.py", report)
        assert "readOnly: True" in res and "editedBlocks: 4" in res


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_signatures_default_to_the_account_name(tmp_path):
    """Without --author, Claude's notes are unsigned and shown under the page owner's account name;
    an empty relabel touches only those, never notes people made in the page under their account."""
    doc = tmp_path / "doc"
    run(SCRIPTS / "extract.py", FIX / "sample.docx", doc)
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps([{"cat": "blocker", "kind": "note", "comment": "General note."},
                                 {"cat": "typos", "exact": "Forty-two participants", "comment": "Wording."}]))
    seed = tmp_path / "seed"
    out = run(SCRIPTS / "validate_notes.py", doc, draft, seed)
    assert "page owner account name" in out
    seeds = json.loads((seed / "seeds.json").read_text())
    assert all(n["author"] == "" and n["byOwner"] for n in seeds)

    # the same notes after co-authors worked in the page: one signed for a session, one by account
    notes = seeds + [
        {**seeds[0], "id": "u1", "author": "Alex", "byOwner": False},
        {**seeds[0], "id": "u2", "author": "", "authorId": "u_abc", "byOwner": False},
    ]
    live = tmp_path / "live.json"
    live.write_text(json.dumps(notes))
    r = subprocess.run([sys.executable, SCRIPTS / "notes_ops.py", "batch", live, "--relabel", "=cabbage"],
                       capture_output=True, text=True, check=True)
    writes = [w for line in r.stdout.splitlines() for w in json.loads(line)]
    assert sorted(w["doc_id"] for w in writes) == sorted(n["id"] for n in seeds)
    assert all(w["data"] == {"author": "cabbage"} for w in writes)
    signed = tmp_path / "signed.json"
    signed.write_text(json.dumps([{**n, "author": "cabbage", "byOwner": False} for n in seeds]))
    r = subprocess.run([sys.executable, SCRIPTS / "notes_ops.py", "batch", signed, "--relabel", "cabbage="],
                       capture_output=True, text=True, check=True)
    writes = [w for line in r.stdout.splitlines() for w in json.loads(line)]
    assert len(writes) == len(seeds) and all(w["data"] == {"author": "", "byOwner": True} for w in writes)

    report = tmp_path / "report.html"
    out = run(SCRIPTS / "build_html.py", "report", doc, live, report, "--doc-name", "sample.docx",
              "--author-map", "@owner=cabbage")
    static = static_of(report.read_text())
    by = {n["id"]: n["author"] for n in static["notes"]}
    assert [by[n["id"]] for n in seeds] == ["cabbage", "cabbage"]
    assert by["u1"] == "Alex" and by["u2"] == "Reviewer" and "1 notes are signed by account name" in out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_report_reply_threads(tmp_path):
    """Replies are signed like notes in the report: their signature, else the account name the page
    exported, else a mapping; replies to notes that are not in the report are dropped."""
    doc = tmp_path / "doc"
    run(SCRIPTS / "extract.py", FIX / "sample.docx", doc)
    note = {"id": "n1", "kind": "note", "cat": "mine", "comment": "General.", "status": "open", "author": "Robin"}
    export = tmp_path / "export.json"
    export.write_text(json.dumps({
        "annotations": [note, {**note, "id": "n2", "status": "dismissed"}],
        "replies": [
            {"id": "c1", "note": "n1", "text": "Agreed.", "author": "Alex", "authorId": "u_a", "createdAt": "2026-09-29T10:00:00Z"},
            {"id": "c2", "note": "n1", "text": "Done.", "author": "", "authorId": "u_b", "authorName": "Sam Sample", "createdAt": "2026-09-29T11:00:00Z"},
            {"id": "c3", "note": "n1", "text": "Seeded.", "author": "", "authorId": None, "byOwner": True, "createdAt": "2026-09-29T12:00:00Z"},
            {"id": "c4", "note": "n2", "text": "On a dismissed note.", "author": "Alex", "authorId": "u_a"},
        ],
    }))
    report = tmp_path / "report.html"
    out = run(SCRIPTS / "build_html.py", "report", doc, export, report, "--doc-name", "sample.docx", "--author-map", "@owner=Kim Test")
    static = static_of(report.read_text())
    assert [(r["id"], r["author"]) for r in static["replies"]] == [("c1", "Alex"), ("c2", "Sam Sample"), ("c3", "Kim Test")]
    assert not any("authorId" in r or "authorName" in r for r in static["replies"])
    assert "3 replies" in out

    clean = tmp_path / "clean"
    run(SCRIPTS / "notes_ops.py", "clean", doc, export, clean, "--author-map", "@owner=Kim Test")
    md = clean.with_suffix(".md").read_text()
    assert "> **Alex** (2026-09-29): Agreed." in md and "> **Sam Sample**" in md and "> **Kim Test**" in md
    assert "dismissed note" not in md


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


MOCK_RUNTIME = """(() => {
  const V = %s;
  const store = { annotations: new Map(Object.entries(V.notes)), replies: new Map(Object.entries(V.replies)), edits: new Map(),
                  editlocks: new Map(), meta: new Map(V.owner ? [['owner', { id: V.owner }]] : []) };
  window.__writes = [];
  const snap = c => ({ docs: [...(store[c] || new Map()).entries()].map(([id, v]) => ({ id, exists: true, data: () => v, metadata: {} })) });
  const ref = (c, id) => ({
    get: async () => ({ id, exists: store[c].has(id), data: () => store[c].get(id), metadata: {} }),
    set: async d => { window.__writes.push([c, id, d]); store[c].set(id, d); },
    update: async () => {}, delete: async () => {}, acquire: async () => ({ release: async () => {}, renew: async () => {} }),
  });
  const db = { collection: c => ({ onSnapshot: cb => { setTimeout(() => cb(snap(c)), 0); return () => {}; }, doc: id => ref(c, id) }),
               doc: path => ref(...path.split('/')) };
  const user = {
    me: async () => ({ id: V.me, name: V.names[V.me] || '', isOwner: V.me === 'u_owner', canEdit: true, avatarUrl: '', color: '#888', email: null }),
    id: async () => V.me, can: async () => true, isOwner: async () => V.me === 'u_owner',
    profiles: async ids => Object.fromEntries([].concat(ids).map(i => [i, { id: i, name: V.names[i] || '', isMe: i === V.me }])),
  };
  const downloads = { save: async ({ filename, data }) => { window.__saved = { filename, data: typeof data === 'string' ? data : await data.text() }; } };
  window.claude = { use: async n => n === 'db' ? db : n === 'user' ? user : n === 'downloads' ? downloads : null };
})();"""


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_signatures_in_the_live_page(tmp_path, browser_ok):
    """Against a stand-in for the page runtime: each kind of signature shows the right name, only the
    owner records meta/owner, and one click exports a report that still names everyone offline."""
    if not browser_ok:
        pytest.skip("playwright/chromium not available")
    from playwright.sync_api import sync_playwright
    doc = tmp_path / "doc"
    run(SCRIPTS / "extract.py", FIX / "sample.docx", doc)
    tool = tmp_path / "tool.html"
    run(SCRIPTS / "build_html.py", "tool", doc, tool, "--doc-name", "sample.docx")
    note = lambda i, **k: {"id": i, "kind": "note", "cat": "mine", "comment": i, "status": "open", "seq": int(i[1:]), **k}
    notes = {"n1": note("n1", author="", byOwner=True),                        # Claude, unsigned
             "n2": note("n2", author="cabbage"),                               # Claude, signed
             "n3": note("n3", author="Alex", authorId="u_alex"),               # session signature
             "n4": note("n4", author="", authorId="u_sam")}                    # account name
    replies = {"c1": {"id": "c1", "note": "n1", "text": "ok", "author": "", "authorId": "u_sam", "createdAt": "2026-09-29T10:00:00Z"}}
    names = {"u_owner": "Owner Name", "u_alex": "Alex Account", "u_sam": "Sam Account"}
    want = {"n1": "Owner Name", "n2": "cabbage", "n3": "Alex", "n4": "Sam Account"}
    labels = """() => ({ by: Object.fromEntries([...document.querySelectorAll('.note')].map(n => [n.dataset.id, n.querySelector('footer .by').textContent])),
                        reply: document.querySelector('.reply .who').textContent, report: document.body.classList.contains('report') })"""
    with sync_playwright() as p:
        b = p.chromium.launch()
        for me, owner_doc in (("u_owner", None), ("u_sam", "u_owner")):
            pg = b.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.add_init_script(MOCK_RUNTIME % json.dumps({"notes": notes, "replies": replies, "names": names, "me": me, "owner": owner_doc}))
            pg.goto(tool.as_uri()); pg.wait_for_timeout(1500)
            got = pg.evaluate(labels)
            assert not errs, errs
            assert got == {"by": want, "reply": "Sam Account", "report": False}, got
            assert len(pg.evaluate("window.__writes.filter(w => w[0] === 'meta')")) == (1 if me == "u_owner" else 0)
            if me == "u_sam":
                pg.click("#exportHtml"); pg.wait_for_timeout(800)
                saved = pg.evaluate("window.__saved")
                assert saved and saved["filename"].endswith(".html")
                report = tmp_path / saved["filename"]
                report.write_text(saved["data"])
                rp = b.new_page()
                rp.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
                rp.goto(report.as_uri()); rp.wait_for_timeout(1200)
                assert rp.evaluate(labels) == {"by": want, "reply": "Sam Account", "report": True}
                rp.close()
            pg.close()
        b.close()
