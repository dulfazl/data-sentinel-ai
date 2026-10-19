"""End-to-end test of the unpacked extension in Playwright's Chromium against the real scan API.

Serves a local page with a file input, a detached file input (like Google Drive), a drop zone
and a textarea. Everything is local (127.0.0.1); no real website is opened.
Skipped automatically if Playwright or its Chromium build is not installed.
"""
import functools
import itertools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import PAYROLL, ROOT

sync_api = pytest.importorskip("playwright.sync_api")

from data_sentinel.browser_api import ScanAPI  # noqa: E402
from data_sentinel.db import Database  # noqa: E402
from data_sentinel.engine import Engine  # noqa: E402

EXT = os.path.join(ROOT, "extension")
TOKEN = "ext-test-token"
_users = itertools.count(1)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>DLP test page</title></head><body>
<input type="file" id="file" multiple>
<button id="detached">Upload like Google Drive</button>
<div id="drop" style="width:300px;height:120px;border:2px dashed #888">Drop files here</div>
<textarea id="text" rows="4" cols="60"></textarea>
<script>
  window.log = [];
  const names = (fl) => Array.from(fl).map((f) => f.name).join(",");
  document.getElementById("file").addEventListener("change", (e) => log.push("change:" + names(e.target.files)));
  document.getElementById("detached").addEventListener("click", () => {
    const inp = document.createElement("input");           // never attached to the page
    inp.type = "file";
    inp.addEventListener("change", () => log.push("detached:" + names(inp.files)));
    inp.click();
  });
  const drop = document.getElementById("drop");
  drop.addEventListener("dragover", (e) => e.preventDefault());
  drop.addEventListener("drop", (e) => { e.preventDefault(); log.push("drop:" + names(e.dataTransfer.files)); });
  document.getElementById("text").addEventListener("paste", (e) =>
    log.push("paste:" + e.clipboardData.getData("text/plain").length));
  window.dropFile = (name, text) => {
    const dt = new DataTransfer();
    dt.items.add(new File([text], name, { type: "text/plain" }));
    drop.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  };
  window.pasteText = (text) => {
    const ta = document.getElementById("text");
    ta.focus();
    const dt = new DataTransfer();
    dt.setData("text/plain", text);
    ta.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  };
</script></body></html>"""


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("ext_files")
    (d / "index.html").write_text(PAGE)
    (d / "public_notice.txt").write_text("Join us for the annual picnic on Friday!")
    (d / "internal_memo.txt").write_text("Internal use only. Sprint planning notes for next week.")
    (d / "customer_payroll_confidential.csv").write_text(PAYROLL)
    with open(d / "customer_data_export.csv", "wb") as fh:          # 21 MB: sent as name + size only
        fh.write(b"id,value\n" + b"1,2\n" * (21 * 1024 * 1024 // 4))
    return d


@pytest.fixture(scope="module")
def site(files):
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(files))
    handler.log_message = lambda *a: None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://localhost:{httpd.server_address[1]}/index.html"
    httpd.shutdown()


@pytest.fixture(scope="module")
def api():
    db = Database(url="", sqlite_path=":memory:")
    db.init_schema()
    server = ScanAPI(Engine(db, use_saved_model=False), "alice", token=TOKEN, port=0)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def browser(api, tmp_path_factory):
    profile = tmp_path_factory.mktemp("chromium_profile")
    with sync_api.sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(profile), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        except Exception as exc:
            pytest.skip(f"Chromium for Playwright not available: {exc}")
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        settings = {"agentUrl": f"http://127.0.0.1:{api.port}", "token": TOKEN, "blockWhenOffline": False,
                    "skipSites": "localhost:8501"}
        sw.evaluate("s => chrome.storage.local.set(s)", settings)
        yield ctx, sw, settings
        ctx.close()


@pytest.fixture
def page(browser, site, api):
    api.user = f"tester{next(_users)}"          # fresh user: no history, deterministic scores
    ctx, _, _ = browser
    pg = ctx.new_page()
    pg.goto(site)
    pg.wait_for_function("window.log !== undefined")
    yield pg
    pg.close()


def banner(pg, kind):
    pg.wait_for_selector(f"data-sentinel-banner[data-kind={kind}]", state="attached", timeout=15000)
    return pg.eval_on_selector("data-sentinel-banner", "b => b.dataset.message")


def wait_log(pg, prefix):
    pg.wait_for_function(f"window.log.some(x => x.startsWith({prefix!r}))", timeout=15000)


def test_harmless_upload_reaches_the_page(page, files):
    page.set_input_files("#file", str(files / "public_notice.txt"))
    wait_log(page, "change:public_notice.txt")
    assert page.eval_on_selector("#file", "i => i.files.length") == 1


def test_restricted_upload_is_dropped_with_red_banner(page, files):
    page.set_input_files("#file", str(files / "customer_payroll_confidential.csv"))
    msg = banner(page, "block")
    assert msg.startswith("Blocked by Data Sentinel: customer_payroll_confidential.csv (Restricted)")
    page.wait_for_timeout(300)
    assert page.evaluate("window.log") == []
    assert page.eval_on_selector("#file", "i => i.files.length") == 0


def test_warn_replays_upload_with_amber_banner(page, files):
    page.set_input_files("#file", str(files / "internal_memo.txt"))
    wait_log(page, "change:internal_memo.txt")
    assert "Data Sentinel warning" in banner(page, "warn")


def test_detached_input_like_google_drive(page, files):
    with page.expect_file_chooser() as fc:
        page.click("#detached")
    fc.value.set_files(str(files / "customer_payroll_confidential.csv"))
    banner(page, "block")
    page.wait_for_timeout(300)
    assert not any(x.startswith("detached:") for x in page.evaluate("window.log"))
    with page.expect_file_chooser() as fc:
        page.click("#detached")
    fc.value.set_files(str(files / "public_notice.txt"))
    wait_log(page, "detached:public_notice.txt")


def test_drag_and_drop(page):
    page.evaluate("dropFile('payroll.csv', " + repr(PAYROLL) + ")")
    banner(page, "block")
    page.wait_for_timeout(300)
    assert page.evaluate("window.log") == []
    page.evaluate("dropFile('notice.txt', 'Join us for the annual picnic on Friday!')")
    wait_log(page, "drop:notice.txt")


def test_paste_of_api_key_blocked_and_harmless_paste_inserted(page):
    page.evaluate("pasteText('api_key = sk_live_51HxTestKeyOnly')")
    assert "pasted text (Restricted)" in banner(page, "block")
    page.wait_for_timeout(300)
    assert page.evaluate("window.log") == [] and page.input_value("#text") == ""
    harmless = "Please review the agenda for tomorrow's meeting."
    page.evaluate(f"pasteText({harmless!r})")
    wait_log(page, "paste:")
    page.wait_for_function(f"document.getElementById('text').value === {harmless!r}")


def test_short_paste_is_not_held(page):
    page.evaluate("pasteText('hello')")
    assert page.evaluate("window.log") == ["paste:5"]                 # delivered synchronously


def test_large_file_sent_as_name_and_size(page, files, api):
    page.set_input_files("#file", str(files / "customer_data_export.csv"))
    banner(page, "block")
    row = api.engine.db.one("SELECT f.inspected, f.size_bytes FROM files f JOIN transfer_events e ON e.file_id = f.id "
                            "WHERE f.name = 'customer_data_export.csv' ORDER BY e.id DESC LIMIT 1")
    assert row["inspected"] == 0 and row["size_bytes"] > 20 * 1024 * 1024


def test_offline_agent_follows_the_toggle(browser, page, files):
    ctx, sw, settings = browser
    try:
        sw.evaluate("s => chrome.storage.local.set(s)", dict(settings, agentUrl="http://127.0.0.1:9", blockWhenOffline=True))
        page.set_input_files("#file", str(files / "public_notice.txt"))
        assert "agent is offline" in banner(page, "block")
        assert page.evaluate("window.log") == []
        sw.evaluate("s => chrome.storage.local.set(s)", dict(settings, agentUrl="http://127.0.0.1:9", blockWhenOffline=False))
        page.set_input_files("#file", str(files / "public_notice.txt"))
        wait_log(page, "change:public_notice.txt")
        assert "NOT checked" in banner(page, "warn")
    finally:
        sw.evaluate("s => chrome.storage.local.set(s)", settings)
