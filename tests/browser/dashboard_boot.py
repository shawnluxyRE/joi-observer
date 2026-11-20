"""The HTML shell can report a failed or retired boot without a data connection."""

from importlib.resources import files
import json
import re

import pytest

from chromium_document import run_document


@pytest.mark.parametrize("case", ["missing stylesheet", "missing script", "late readiness", "left during boot"])
def test_boot_stops_before_live_fetch(tmp_path, case):
    assets = files("joi_observer.web").joinpath("static")
    html = assets.joinpath("index.html").read_text(encoding="utf-8")
    release = "a" * 64
    html = html.replace("__JOI_RELEASE__", release).replace('"/static/', '"static/')
    directory = tmp_path / "static" / release
    directory.mkdir(parents=True)
    missing_asset = {"missing stylesheet": "dashboard.css", "missing script": "dashboard.js"}.get(case)
    for name in ("dashboard.js", "dashboard.css"):
        if name == missing_asset:
            continue
        (directory / name).write_bytes(assets.joinpath(name).read_bytes())
    if missing_asset is None:
        # Switch only the shell's readiness and clock ports. Drive the real boot
        # synchronously across pagehide or timeout before releasing its resources.
        entry = """<script id="dashboard-boot-entry">
          let now = 0;
          const ready = new Promise(resolve => {
            window.finishAssets = () => { if (EXPIRED) now = 8100; resolve(); };
          });
          new DashboardBoot(document, {now: () => now, whenAssetsReady: () => ready}).start();
        </script>""".replace("EXPIRED", json.dumps(case == "late readiness"))
        html, replaced = re.subn(r'<script\b[^>]*\bid="dashboard-boot-entry"[^>]*>.*?</script>',
                                 entry, html, count=1, flags=re.S)
        assert replaced == 1
    fetch = "<script>window.calls=0;window.fetch=()=>{window.calls++;throw Error('unexpected fetch')}</script>"
    (tmp_path / "page.html").write_text(html.replace("<head>", "<head>" + fetch), encoding="utf-8")
    fixture = tmp_path / "fixture.html"
    fixture.write_text("""<!doctype html><output id="result">waiting</output>
      <iframe src="page.html"></iframe><script>
      window.addEventListener("load", () => {
        const w = document.querySelector("iframe").contentWindow, doc = w.document;
        const left = CASE === "left during boot";
        if (left) {
          w.dispatchEvent(new w.PageTransitionEvent("pagehide", {persisted:true}));
          w.dispatchEvent(new w.PageTransitionEvent("pageshow", {persisted:true}));
        }
        if (!CASE.startsWith("missing ")) w.finishAssets();
        const until = performance.now() + (CASE.startsWith("missing ") ? 9000 : 1000);
        function inspect() {
          const error = doc.getElementById(left ? "error" : "asset-error");
          const visible = el => el.getClientRects().length > 0;
          if (visible(error) && /refresh/i.test(error.innerText) && !visible(doc.getElementById("loading"))
              && !visible(doc.getElementById("dashboard")) && !w.calls) {
            document.getElementById("result").textContent = "passed";
          } else if (performance.now() >= until || w.calls) {
            document.getElementById("result").textContent = "boot failed to stop with a refresh prompt";
          } else setTimeout(inspect, 100);
        }
        // Let the resolved readiness promise run before observing retired boot.
        setTimeout(inspect, 0);
      });
      </script>""".replace("CASE", json.dumps(case)), encoding="utf-8")
    run_document(fixture, budget_ms=10000)
