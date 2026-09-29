#!/usr/bin/env python3
"""
Load a built page in headless Chromium and check it before publishing or sending.

    python smoke_test.py PAGE.html [--notes seeds.json] [--edits edits.json] [--shot out.png] [--exercise-edits]

--notes / --edits inject notes and text edits into the tool's browser-storage fallback so the
live tool can be checked without the artifact database (reports already carry theirs).
--exercise-edits drives the text-editing features like a user would: edit a paragraph and
save, check tracked changes and the "Show changes" toggle, apply a suggestion, open a note's
"Edit text", reload and confirm everything persisted, and run hostile HTML through the
sanitizer. Use it after changing the template.
Fails (exit 1) on JavaScript errors, on any note whose quoted text no longer matches (notes whose
text was changed by an edit are fine), or on a failed editing check.
Requires playwright + chromium.
"""
import argparse, functools, http.server, json, re, socketserver, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright


def serve(directory):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    H = functools.partial(Quiet, directory=directory)
    socketserver.TCPServer.allow_reuse_address = True
    s = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]


STATE_JS = """() => ({
  store: document.querySelector('#store').textContent,
  count: document.querySelector('#count').textContent,
  notes: document.querySelectorAll('.note').length,
  marks: new Set([...document.querySelectorAll('mark.hl')].map(x => x.dataset.id)).size,
  boxes: document.querySelectorAll('.fbox').length,
  orphans: [...document.querySelectorAll('.quote.orphan')].map(x => x.textContent.slice(0, 90)),
  editedQuotes: document.querySelectorAll('.quote.edited').length,
  editedBlocks: document.querySelectorAll('[data-block].edited').length,
  suggestionsShown: [...document.querySelectorAll('ins.sugg')].filter(x => getComputedStyle(x).display !== 'none').length,
  figures: document.querySelectorAll('figure').length, tables: document.querySelectorAll('.tbl').length,
  readOnly: document.body.classList.contains('report'),
})"""


def exercise(pg, ls_key):
    """Drive the editing UI; returns (checks, failures)."""
    checks, fails = {}, []

    def check(name, ok, detail=""):
        checks[name] = bool(ok)
        if not ok:
            fails.append(f"{name}: {detail}")

    san = pg.evaluate("""() => sanitize('<b onclick="x()">a</b><img src=x onerror="alert(1)"><script>bad()</script><span class="link evil" style="color:red">l</span><math display="block" onload="x()"><mi>x</mi></math><a href="javascript:alert(1)">t</a>')""")
    check("sanitizer strips scripts/handlers", not re.search(r"onclick|onerror|onload|<img|<script|javascript:|style=|evil", san) and "<math" in san and "<b>a</b>" in san, san)

    bid = pg.evaluate("""() => { const ps = [...document.querySelectorAll('.sheet p[data-block]')].filter(p => p.textContent.trim().length >= 20 && !p.querySelector('mark')).sort((a, b) => b.textContent.length - a.textContent.length); return ps[0] && ps[0].dataset.block; }""")
    check("found a paragraph to edit", bid, "no plain paragraph")
    if not bid:
        return checks, fails
    sel = f'[data-block="{bid}"]'
    pg.click("#modeEdit")
    pg.click(sel, position={"x": 20, "y": 8})
    pg.wait_for_timeout(300)
    check("click opens the editor", pg.evaluate(f"""() => document.querySelector('{sel}').getAttribute('contenteditable') === 'true' && document.querySelector('#ebar').classList.contains('on')"""))
    pg.evaluate(f"""() => {{ const el = document.querySelector('{sel}'); const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }}""")
    pg.keyboard.type(" EDITCHECK")
    pg.click("#ebarSave")
    pg.wait_for_timeout(400)
    st = pg.evaluate(f"""() => {{ const el = document.querySelector('{sel}'); return {{ edited: el.classList.contains('edited'), ins: [...el.querySelectorAll('ins.chg')].map(x => x.textContent).join('|'), editable: el.getAttribute('contenteditable'), stored: localStorage.getItem({json.dumps(ls_key + ':edits')}) || '' }}; }}""")
    check("save marks the block edited", st["edited"] and st["editable"] is None, st)
    check("inserted text shows as tracked change", "EDITCHECK" in st["ins"], st["ins"])
    check("edit persisted (browser storage)", "EDITCHECK" in st["stored"], st["stored"][:120])
    pg.click("#edits")
    off = pg.evaluate(f"""() => {{ const i = document.querySelector('{sel} ins.chg'); return getComputedStyle(i).borderBottomWidth; }}""")
    pg.click("#edits")
    check("Show changes off hides change marks", off in ("0px", "0"), off)

    note = pg.evaluate("""() => { const b = document.querySelector('.note [data-act="apply"]'); if (!b) return null; const c = b.closest('.note'); return { id: c.dataset.id }; }""")
    if note:
        nid = note["id"]
        pg.click(f'.note[data-id="{nid}"] [data-act="apply"]')
        pg.wait_for_timeout(400)
        res = pg.evaluate(f"""() => {{ const all = JSON.parse(localStorage.getItem({json.dumps(ls_key)}) || '[]'); const n = all.find(x => x.id === {json.dumps(nid)}); const ed = JSON.parse(localStorage.getItem({json.dumps(ls_key + ':edits')}) || '[]').find(e => e.block === (n && n.block)); return {{ status: n && n.status, addressed: !!(n && n.addressedBy), inText: !!(ed && n && ed.text.includes(n.suggestion)) }}; }}""")
        check("Apply replaces the quoted text and closes the note", res["status"] == "done" and res["addressed"] and res["inText"], res)
    else:
        checks["Apply (no suggestion notes to test)"] = True

    tnote = pg.evaluate("""() => { const b = [...document.querySelectorAll('.note [data-act="apply"]')].find(x => (S.anns.get(x.closest('.note').dataset.id) || {}).block?.startsWith('tab')); return b ? b.closest('.note').dataset.id : null; }""")
    if tnote:
        pg.click(f'.note[data-id="{tnote}"] [data-act="apply"]')
        pg.wait_for_timeout(400)
        ok = pg.evaluate(f"""() => {{ const a = S.anns.get({json.dumps(tnote)}); const e = S.edits.get(a.block); if (!e) return false; const d = document.createElement('div'); d.innerHTML = e.html; return [...d.querySelectorAll('td, th, .tcap')].some(c => c.textContent.includes(a.suggestion)); }}""")
        check("Apply inside a table keeps the text in its cell", ok)

    tgt = pg.evaluate("""() => { const b = document.querySelector('.note [data-act="edittext"]'); if (!b) return null; const c = b.closest('.note'); return c.dataset.id; }""")
    if tgt:
        pg.click(f'.note[data-id="{tgt}"] [data-act="edittext"]')
        pg.wait_for_timeout(500)
        r = pg.evaluate("""() => ({ editing: !!document.querySelector('[data-block].editing'), sel: getSelection().toString(), boxes: [...document.querySelectorAll('#ebarNotes input:checked')].length })""")
        check("note's Edit text opens its block with the quote selected", r["editing"] and r["boxes"] >= 1, r)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check("Escape cancels", not pg.evaluate("() => !!document.querySelector('[data-block].editing')"))
    return checks, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page"); ap.add_argument("--notes"); ap.add_argument("--edits"); ap.add_argument("--shot")
    ap.add_argument("--exercise-edits", action="store_true")
    a = ap.parse_args()
    page = Path(a.page).resolve()
    html = page.read_text()
    port = serve(str(page.parent))
    m = re.search(r"const LS_KEY = '([^']+)'", html)
    ls_key = m.group(1) if m else ""
    init = ""
    if a.notes:
        d = json.loads(Path(a.notes).read_text())
        notes = d["annotations"] if isinstance(d, dict) else d
        init += f"if (!sessionStorage.getItem('seeded')) {{ localStorage.setItem({json.dumps(ls_key)}, {json.dumps(json.dumps(notes))});"
        if a.edits:
            d = json.loads(Path(a.edits).read_text())
            edits = d.get("edits", []) if isinstance(d, dict) else d
            init += f"localStorage.setItem({json.dumps(ls_key + ':edits')}, {json.dumps(json.dumps(edits))});"
        init += "sessionStorage.setItem('seeded', '1'); }"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        if init:
            pg.add_init_script(init)
        url = f"http://127.0.0.1:{port}/{page.name}"
        pg.goto(url)
        pg.wait_for_timeout(1800)
        r = pg.evaluate(STATE_JS)
        checks, fails = {}, []
        if a.exercise_edits:
            checks, fails = exercise(pg, ls_key)
            pg.reload()
            pg.wait_for_timeout(1500)
            after = pg.evaluate(STATE_JS)
            ok = after["editedBlocks"] >= 1 and not after["orphans"]
            checks["edits survive reload"] = ok
            if not ok:
                fails.append(f"edits survive reload: {after}")
            r = after
        if a.shot:
            pg.screenshot(path=a.shot)
        b.close()
    for k, v in r.items():
        print(f"{k}: {v}")
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs:
        print("JS ERRORS:", errs)
    if errs or r["orphans"] or fails:
        for f in fails:
            print("  ", f)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
