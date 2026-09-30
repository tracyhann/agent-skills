#!/usr/bin/env python3
"""
Load a built page in headless Chromium and check it before publishing or sending.

    python smoke_test.py PAGE.html [--notes seeds.json] [--edits edits.json] [--replies replies.json]
                         [--shot out.png] [--exercise-edits] [--exercise-comments] [--exercise-report]

--notes / --edits / --replies inject notes, text edits and reply threads into the tool's
browser-storage fallback so the live tool can be checked without the artifact database (reports
already carry theirs).
--exercise-comments drives reply threads: sign as someone for the session, reply to a note, check
the reply is signed and kept as plain text (hostile HTML stays text), edit it, search finds it,
reload keeps it, delete it, and go back to the account name.
--exercise-edits drives the text-editing features like a user would: set a signature for the
session with "Signing as", edit a paragraph and save, check tracked changes and the "Show changes" toggle, apply a suggestion, open a note's
"Edit text", reload and confirm everything persisted, and run hostile HTML through the
sanitizer. Use it after changing the template.
--exercise-report clicks "Export HTML", opens the downloaded file from disk with the network cut
off, and checks it runs read-only, without errors, with every note (except dismissed ones),
reply and text edit, without the editing controls, and with the page's styling. It then exports
again from the page wrapped the way the artifact viewer serves it, and checks that report is
styled too.
Fails (exit 1) on JavaScript errors, on any note whose quoted text no longer matches (notes whose
text was changed by an edit are fine), or on a failed editing check.
Requires playwright + chromium.
"""
import argparse, functools, http.server, json, re, socketserver, sys, tempfile, threading
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
  replies: document.querySelectorAll('.reply').length,
  signingAs: (() => { const b = document.querySelector('#sigBtn'); return b && getComputedStyle(b).display !== 'none' ? document.querySelector('#sigName').textContent : null; })(),
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

    SIG = "cabbage"
    before = pg.evaluate("() => document.querySelector('#sigName').textContent")
    pg.click("#sigBtn")
    pg.fill("#sigInput", SIG)
    pg.click("#sigSave")
    sg = pg.evaluate("() => ({ label: document.querySelector('#sigName').textContent, note: baseNote({}).author, open: document.querySelector('#sigPop').classList.contains('on') })")
    check("Signing as sets this session's signature", before == "you" and sg["label"] == SIG and sg["note"] == SIG and not sg["open"], {"before": before, **sg})

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
    check("the edit carries the session signature", f'"author":"{SIG}"' in st["stored"], st["stored"][:160])
    pg.click("#edits")
    off = pg.evaluate(f"""() => {{ const i = document.querySelector('{sel} ins.chg'); return getComputedStyle(i).borderBottomWidth; }}""")
    pg.click("#edits")
    check("Show changes off hides change marks", off in ("0px", "0"), off)

    note = pg.evaluate("""() => { const b = document.querySelector('.note [data-act="apply"]'); if (!b) return null; const c = b.closest('.note'); return { id: c.dataset.id }; }""")
    if note:
        nid = note["id"]
        pg.click(f'.note[data-id="{nid}"] [data-act="apply"]')
        pg.wait_for_timeout(400)
        res = pg.evaluate(f"""() => {{ const all = JSON.parse(localStorage.getItem({json.dumps(ls_key)}) || '[]'); const n = all.find(x => x.id === {json.dumps(nid)}); const ed = JSON.parse(localStorage.getItem({json.dumps(ls_key + ':edits')}) || '[]').find(e => e.block === (n && n.block)); return {{ status: n && n.status, addressed: !!(n && n.addressedBy), by: n && n.addressedBy && n.addressedBy.author, inText: !!(ed && n && ed.text.includes(n.suggestion)) }}; }}""")
        check("Apply replaces the quoted text and closes the note", res["status"] == "done" and res["addressed"] and res["inText"], res)
        check("the note records who addressed it", res["by"] == SIG, res)
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


def exercise_comments(pg, ls_key):
    """Drive reply threads with a session signature; returns (checks, failures)."""
    checks, fails = {}, []

    def check(name, ok, detail=""):
        checks[name] = bool(ok)
        if not ok:
            fails.append(f"{name}: {detail}")

    SIG = "QA Signer"
    stored = lambda key: pg.evaluate(f"() => localStorage.getItem({json.dumps(key)}) || ''")
    pg.click("#sigBtn")
    pg.fill("#sigInput", SIG)
    pg.click("#sigSave")
    nid = pg.evaluate("""() => { const c = document.querySelector('.note[data-id]'); return c && c.dataset.id; }""")
    check("found a note to reply to", nid, "no notes")
    if not nid:
        return checks, fails
    card = f'.note[data-id="{nid}"]'
    pg.click(f'{card} [data-act="reply"]')
    pg.wait_for_timeout(150)
    pg.fill(f'{card} textarea[data-field="__reply"]', 'First reply <img src=x onerror="window.__pwned=1"> ok')
    pg.click(f'{card} [data-act="postreply"]')
    pg.wait_for_timeout(400)
    r = pg.evaluate(f"""() => {{ const c = document.querySelector('{card}'); const rs = [...c.querySelectorAll('.reply')]; const last = rs[rs.length - 1]; return {{ n: rs.length, who: last && last.querySelector('.who').textContent, text: last && last.querySelector('.rt').textContent, img: !!c.querySelector('.reply img'), pwned: !!window.__pwned }}; }}""")
    check("reply is posted and signed", r["n"] >= 1 and r["who"] == SIG and "First reply" in (r["text"] or ""), r)
    check("reply text is shown as text, never HTML", not r["img"] and not r["pwned"] and "<img" in (r["text"] or ""), r)
    raw = stored(ls_key + ":replies")
    check("reply persisted (browser storage)", "First reply" in raw and f'"author":"{SIG}"' in raw and f'"note":"{nid}"' in raw, raw[:160])

    pg.click(f'{card} .reply:last-child [data-act="editreply"]')
    pg.wait_for_timeout(150)
    pg.fill(f'{card} textarea[data-field="__replyedit"]', "Edited reply text")
    pg.keyboard.press("Control+Enter")
    pg.wait_for_timeout(300)
    e = pg.evaluate(f"""() => {{ const x = [...document.querySelectorAll('{card} .reply')].pop(); return {{ text: x.querySelector('.rt').textContent, when: x.querySelector('.when').textContent }}; }}""")
    check("own reply can be edited", e["text"] == "Edited reply text" and "edited" in e["when"], e)

    pg.fill("#search", "Edited reply text")
    pg.wait_for_timeout(250)
    found = pg.evaluate("() => [...document.querySelectorAll('.note')].map(n => n.dataset.id)")
    pg.fill("#search", "")
    pg.wait_for_timeout(150)
    check("search finds reply text", found == [nid], found)

    pg.reload()
    pg.wait_for_timeout(1500)
    after = pg.evaluate(f"""() => ({{ sig: document.querySelector('#sigName').textContent, reply: [...document.querySelectorAll('{card} .reply .rt')].map(x => x.textContent).includes('Edited reply text') }})""")
    check("reply and session signature survive reload", after["sig"] == SIG and after["reply"], after)

    pg.click(f'{card} .reply:last-child [data-act="delreply"]')
    pg.click(f'{card} [data-act="delreplyyes"]')
    pg.wait_for_timeout(400)
    gone = pg.evaluate(f"() => ![...document.querySelectorAll('{card} .reply .rt')].some(x => x.textContent === 'Edited reply text')")
    check("own reply can be deleted", gone and "Edited reply text" not in stored(ls_key + ":replies"))

    pg.click("#sigBtn")
    pg.fill("#sigInput", "")
    pg.click("#sigSave")
    pg.click(f'{card} [data-act="reply"]')
    pg.fill(f'{card} textarea[data-field="__reply"]', "Unsigned reply")
    pg.click(f'{card} [data-act="postreply"]')
    pg.wait_for_timeout(300)
    last = pg.evaluate(f"() => [...document.querySelectorAll('{card} .reply .who')].pop().textContent")
    check("without a signature, replies use the account name (\"You\" without an account)", last == "You", last)
    return checks, fails


# The artifact viewer serves a published page inside its own document, like this. The browser then
# moves the page's <style> and font links into <body>, which an export must still pick up.
VIEWER_WRAP = ('<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1">'
               '<style>:root{color-scheme:light}body{margin:0;font:14px -apple-system,sans-serif;background:#faf9f5;color:#141413}</style>'
               '</head><body>\n{page}\n</body></html>')

# The page's own stylesheet is applied: the notes rail is laid out and the manuscript is set in the document face.
STYLED_JS = """() => { const rail = document.querySelector('.rail'), sheet = document.querySelector('.sheet');
  return !!rail && getComputedStyle(rail).display === 'flex' && !!sheet && getComputedStyle(sheet).fontFamily.includes('Literata'); }"""


def export_report(pg):
    """Click "Export HTML" and save the download; returns its path."""
    with pg.expect_download() as info:
        pg.click("#exportHtml")
    path = Path(tempfile.mkdtemp()) / info.value.suggested_filename
    info.value.save_as(path)
    return path


def open_offline(browser, path):
    """Open a saved report from disk with the network cut off; returns (state, page errors)."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    rp = ctx.new_page()
    errs = []
    rp.on("pageerror", lambda e: errs.append(str(e)))
    rp.goto(path.as_uri())
    rp.wait_for_timeout(1500)
    got = rp.evaluate("""() => { const gone = q => { const el = document.querySelector(q); return !el || el.hidden || !el.offsetParent; };   // hidden itself or inside a hidden group
      return { readOnly: document.body.classList.contains('report'), notes: S.anns.size, replies: S.replies.size, edits: S.edits.size,
        title: document.title, hidden: ['#exportHtml', '#modeEdit', '#importBtn', '#addGeneral', '#sigBtn'].every(gone),
        replyButtons: document.querySelectorAll('[data-act="reply"]').length }; }""")
    got["styled"] = rp.evaluate(STYLED_JS)
    ctx.close()
    return got, errs


def exercise_report(pg, page):
    """Export HTML from the tool, open the file offline, check it; then export again from the page
    wrapped the way the artifact viewer serves it. Returns (checks, failures)."""
    checks, fails = {}, []

    def check(name, ok, detail=""):
        checks[name] = bool(ok)
        if not ok:
            fails.append(f"{name}: {detail}")

    want = pg.evaluate("""() => { const kept = new Set([...S.anns.values()].filter(a => a.status !== 'dismissed').map(a => a.id));
      return { notes: kept.size, replies: [...S.replies.values()].filter(r => kept.has(r.note)).length, edits: S.edits.size }; }""")
    path = export_report(pg)
    check("Export HTML downloads one standalone file", path.suffix == ".html" and path.stat().st_size > 2000, path.name)
    browser = pg.context.browser
    got, errs = open_offline(browser, path)
    check("the report opens offline without errors", not errs and got["readOnly"], {"errors": errs[:2], **got})
    check("the report carries every note, reply and text edit", (got["notes"], got["replies"], got["edits"]) == (want["notes"], want["replies"], want["edits"]),
          {"want": want, "got": got})
    check("the report has no editing, signing or reply controls", got["hidden"] and got["replyButtons"] == 0, got)
    check("the report is titled as a snapshot", got["title"].endswith("(snapshot)"), got["title"])
    check("the report keeps the page's styling", got["styled"], got)

    wrapped = Path(tempfile.mkdtemp()) / page.name
    wrapped.write_text(VIEWER_WRAP.replace("{page}", page.read_text()))
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True)
    ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    wp = ctx.new_page()
    wp.goto(wrapped.as_uri())
    wp.wait_for_timeout(1500)
    live_styled = wp.evaluate(STYLED_JS)
    got2, errs2 = open_offline(browser, export_report(wp))
    ctx.close()
    check("an export made inside the viewer's wrapper keeps the page's styling",
          live_styled and got2["styled"] and got2["readOnly"] and not errs2, {"page styled": live_styled, "errors": errs2[:2], **got2})
    return checks, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page"); ap.add_argument("--notes"); ap.add_argument("--edits"); ap.add_argument("--shot")
    ap.add_argument("--replies")
    ap.add_argument("--exercise-edits", action="store_true")
    ap.add_argument("--exercise-comments", action="store_true")
    ap.add_argument("--exercise-report", action="store_true")
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
        if a.replies:
            d = json.loads(Path(a.replies).read_text())
            reps = d.get("replies", []) if isinstance(d, dict) else d
            init += f"localStorage.setItem({json.dumps(ls_key + ':replies')}, {json.dumps(json.dumps(reps))});"
        init += "sessionStorage.setItem('seeded', '1'); }"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
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
            checks["the signature lasts for the session"] = after["signingAs"] == "cabbage"
            if after["signingAs"] != "cabbage":
                fails.append(f"the signature lasts for the session: {after['signingAs']!r}")
            r = after
        if a.exercise_comments:
            c2, f2 = exercise_comments(pg, ls_key)
            checks.update(c2); fails += f2
            r = pg.evaluate(STATE_JS)
        if a.exercise_report:
            c3, f3 = exercise_report(pg, page)
            checks.update(c3); fails += f3
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
