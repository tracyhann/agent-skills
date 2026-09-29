#!/usr/bin/env python3
"""
Load a built page in headless Chromium and check it before publishing or sending.

    python smoke_test.py PAGE.html [--notes seeds.json] [--shot out.png]

--notes injects notes into the tool's browser-storage fallback so the live tool can be
checked without the artifact database (reports already carry their notes).
Fails (exit 1) on JavaScript errors or on any note whose quoted text no longer matches.
Requires playwright + chromium (present in the claude.ai sandbox).
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page"); ap.add_argument("--notes"); ap.add_argument("--shot")
    a = ap.parse_args()
    page = Path(a.page).resolve()
    html = page.read_text()
    port = serve(str(page.parent))
    init = ""
    if a.notes:
        m = re.search(r"const LS_KEY = '([^']+)'", html)
        d = json.loads(Path(a.notes).read_text())
        notes = d["annotations"] if isinstance(d, dict) else d
        init = f"localStorage.setItem({json.dumps(m.group(1))}, {json.dumps(json.dumps(notes))});"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        if init:
            pg.add_init_script(init)
        pg.goto(f"http://127.0.0.1:{port}/{page.name}")
        pg.wait_for_timeout(1800)
        r = pg.evaluate("""() => ({
          store: document.querySelector('#store').textContent,
          count: document.querySelector('#count').textContent,
          notes: document.querySelectorAll('.note').length,
          marks: new Set([...document.querySelectorAll('mark.hl')].map(x => x.dataset.id)).size,
          boxes: document.querySelectorAll('.fbox').length,
          orphans: [...document.querySelectorAll('.quote.orphan')].map(x => x.textContent.slice(0, 90)),
          suggestionsShown: [...document.querySelectorAll('ins.sugg')].filter(x => getComputedStyle(x).display !== 'none').length,
          figures: document.querySelectorAll('figure').length, tables: document.querySelectorAll('.tbl').length,
          readOnly: document.body.classList.contains('report'),
        })""")
        if a.shot:
            pg.screenshot(path=a.shot)
        b.close()
    for k, v in r.items():
        print(f"{k}: {v}")
    if errs:
        print("JS ERRORS:", errs)
    if errs or r["orphans"]:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
