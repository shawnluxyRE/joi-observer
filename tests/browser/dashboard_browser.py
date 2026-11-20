"""Run explicitly with pytest and a local Chromium binary. No HTTP server required."""

import asyncio
from dataclasses import replace
from importlib.resources import files
import json
from pathlib import Path

import pytest

from chromium_document import run_document
from joi_observer.config import ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.ipc.protocol import (
    ContainerDisplay, DisplayMetadata, FRAME_HEADER_BYTES, ModelDisplay, SnapshotEnvelope, encode_envelope,
)

SCROLL_STEPS = (0, 8, 16, 24, 32, 40, 48, 56, 60, 64)


def snapshot(count, *, sequence=1, now=1000, state="sampled", cpu_percent=None):
    """Real wire encoding, using distinct config ids, shared labels and non-demo values."""
    def uuid(index):
        return f"GPU-10000000-0000-0000-0000-{index:012d}"

    models, objects = [], []
    for index in range(count):
        chat = index == 0
        kind = (ModelType.CHAT, ModelType.EMBEDDING, ModelType.RERANKER)[min(index, 2)]
        name = "双模型" if index < 2 else f"Alias {index}"
        gpu_ids = (str(index),)
        if state == "grouped" and index < 3:
            gpu_ids = ("0", "1") if chat else ("2",)
        model = ModelDisplay(f"m{index}", kind, name, "Chat <live>" if chat else name,
                             gpu_ids, None, 443)
        models.append(model)
        history = tuple(HistoryPoint(t, None if value is None else (
            Metric("decode_rate", value, "tok/s"),
        )) for t, value in ((942, 0), (945, 2), (950, None), (954, 0), (963, 4),
                             (969, 4), (975, 2), (984, 7), (990, None), (999, 7))
                             if now - 60 <= t <= now) if chat else ()
        decode_rate = 125.5 if state == "peak" else 7.5
        if chat and state == "peak":
            history += (HistoryPoint(now, (Metric("decode_rate", decode_rate, "tok/s"),)),)
        if chat and state == "scroll":
            # The initial sample can be tracked as an isolated dot across the
            # full minute. Later valid samples form a line entering on the right.
            series = [(1000, 7), (1001, None), (1002, 3), (1003, 2)]
            series.extend((1000 + offset, 4) for offset in SCROLL_STEPS[1:])
            history = tuple(HistoryPoint(t, None if rate is None else (Metric("decode_rate", rate, "tok/s"),))
                            for t, rate in series if now - 60 <= t <= now)
            decode_rate = history[-1].metrics[0].value
        metrics = (
            Metric("running", 0, "seq"), Metric("waiting", None if chat else 2, "seq"),
            Metric("total", 19 if chat else 9007199254740993, "seq"),
            Metric("decode_rate", decode_rate if chat else None, "tok/s", applicable=chat),
            Metric("rate", None if chat else 2.25, "seq/s", applicable=not chat),
            Metric("kv_cache_percent", None, "%", applicable=chat),
        )
        if state in ("distinct", "medium-width"):
            values = [(19, 21.5), (6.5, 4.5), (3, 5.5)][index]
            if chat and state == "medium-width":
                values = (19, 1234.8671875)
            field, unit = ("decode_rate", "tok/s") if chat else ("rate", "seq/s")
            history = tuple(HistoryPoint(now + offset, (Metric(field, value, unit),))
                            for offset, value in zip((-7, -1), values))
            metrics = (
                Metric("running", 2 + index, "seq"), Metric("waiting", 1 + index, "seq"),
                Metric("total", 3 + 2 * index, "seq"),
                Metric("decode_rate", values[-1] if chat else None, "tok/s", applicable=chat),
                Metric("prefill_rate", 38.5 if chat else None, "tok/s", applicable=chat),
                Metric("ttft_seconds", 0.5 if chat else None, "s", applicable=chat),
                Metric("kv_cache_percent", 62.5 if chat else None, "%", applicable=chat),
                Metric("rate", None if chat else 3.5 + index, "seq/s", applicable=not chat),
                Metric("queue_seconds", 1.5 + index, "s"),
                Metric("latency_seconds", None if chat else 4.5 + index, "s", applicable=not chat),
            )
            if chat and state == "medium-width":
                busy = {"running": 128, "waiting": 1024, "total": 1152,
                        "ttft_seconds": 0.123456789, "queue_seconds": 4 / 3}
                metrics = tuple(replace(m, value=busy.get(m.name, m.value)) for m in metrics)
        objects.extend((
            ObjectSnapshot(ObjectKey("vllm", model.id), metrics, index == 1 and state != "distinct", now, history),
            ObjectSnapshot(ObjectKey("docker", f"worker-{index}"), (Metric("state", "Running"),),
                           index == 1, now),
            ObjectSnapshot(ObjectKey("gpu", uuid(index)), (Metric("index", index),
                           Metric("name", f"Accelerator {index}"), Metric("utilization_percent", 50, "%")),
                           sampled_at=now),
        ))
    objects.extend((
        ObjectSnapshot(ObjectKey("gpu_inventory", "local"), (Metric("device_count", count),), sampled_at=now),
        ObjectSnapshot(ObjectKey("host", "cpu"), (
            Metric("cpu_percent", cpu_percent if cpu_percent is not None else (17.5 if sequence == 2 else 12.5), "%"),
        ), sampled_at=now),
        ObjectSnapshot(ObjectKey("host", "ram"), (Metric("ram_percent", 25, "%"),
                       Metric("ram_used_bytes", 4 << 30, "B"), Metric("ram_total_bytes", 16 << 30, "B")),
                       sampled_at=now),
    ))
    mounts = ("/scratch",) if count else ()
    if mounts:
        objects.append(ObjectSnapshot(ObjectKey("storage", "mount-0"), (
            Metric("used_bytes", 3 << 30, "B"), Metric("total_bytes", 10 << 30, "B"),
            Metric("used_percent", 30, "%"),
        ), sampled_at=now))
    if state == "unobserved":
        objects = [
            replace(obj, metrics=tuple(replace(m, value=None) for m in obj.metrics),
                    history=(), sampled_at=None, stale=False)
            for obj in objects if obj.key.collector != "gpu"
        ]
    elif state == "removed":
        objects = [
            replace(obj, metrics=(Metric("device_count", 0),)) if obj.key.collector == "gpu_inventory"
            else replace(obj, stale=True) if obj.key.collector == "gpu" else obj
            for obj in objects
        ]
    metadata = DisplayMetadata("fixture-node", "Fixture Linux", mounts,
                               tuple(ContainerDisplay(f"worker-{i}") for i in range(count)), tuple(models))
    frame = SnapshotEnvelope("boot", "cfg", sequence, now, metadata, StateSnapshot(tuple(objects), sequence))
    return encode_envelope(frame)[FRAME_HEADER_BYTES:].decode("utf-8") + "\n"


@pytest.mark.parametrize(("case", "width", "height"), [
    ("layout", 1280, 900), ("layout", 390, 844), ("selection", 1280, 1400),
    ("capacity", 1280, 1800), ("source-states", 1280, 1200),
    ("field-values", 1280, 1200), ("medium-width", 620, 900),
    ("resize-values", 1280, 900),
    ("buffered-stream", 1280, 900),
    ("chart", 1280, 900), ("scroll-window", 1280, 900),
    ("empty", 390, 844), ("outage", 1280, 900), ("initial-failure", 390, 844),
    ("bfcache", 1280, 900), ("hidden-fresh", 1280, 900), ("hidden-eof", 1280, 900),
    ("hidden-silent", 1280, 900),
])
def test_live_document(tmp_path, case, width, height):
    count = {"empty": 0, "selection": 4, "capacity": 5}.get(case, 3)
    settings = {"scene": case, "width": width, "height": height, "count": count}
    if case == "source-states":
        settings.update(sample=snapshot(count, state="unobserved"), known=snapshot(count, sequence=2),
                        removed=snapshot(count, sequence=3, state="removed"))
    elif case == "field-values":
        settings["sample"] = snapshot(count, state="distinct")
    elif case in ("medium-width", "resize-values"):
        settings["sample"] = snapshot(count, state="medium-width")
    elif case == "layout":
        settings.update(sample=snapshot(count, state="grouped"), larger=snapshot(count + 1, state="grouped"))
    else:
        settings["sample"] = snapshot(count)
    if case == "chart":
        settings["delayed"] = snapshot(count, sequence=2, now=1001, state="peak")
    if case == "scroll-window":
        settings["steps"] = [(offset, snapshot(count, sequence=i, now=1000 + offset, state="scroll"))
                             for i, offset in enumerate(SCROLL_STEPS, start=1)]
    if case == "buffered-stream":
        settings.update(old=snapshot(count, sequence=2, now=1001),
                        fresh=snapshot(count, sequence=3, now=1009, cpu_percent=27.5))
    if case == "hidden-fresh":
        settings["fresh"] = snapshot(count, sequence=2, now=1015, cpu_percent=29.5)
    if case == "outage":
        settings["next"] = snapshot(count, sequence=2, now=1001)
    if case == "selection":
        beat = json.loads(settings["sample"])
        beat.update(sequence=2, published_at=1001)
        settings["heartbeat"] = json.dumps(beat) + "\n"
        settings["next"] = snapshot(count, sequence=3, now=1002, cpu_percent=17.5)
    observe_document(tmp_path, settings)


def test_reference_snapshots_through_http_to_visible_dashboard(tmp_path, monkeypatch):
    # This test is also runnable as an isolated file outside normal pytest discovery.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from test_web_snapshot_parity import browser_reference_response

    headers, lines = asyncio.run(browser_reference_response(tmp_path))
    observe_document(tmp_path, {"scene": "reference", "width": 1280, "height": 1200,
                                "headers": headers, "lines": [line.decode("utf-8") for line in lines]})


def test_full_window_keeps_five_gpus_and_stable_gauges(tmp_path):
    sample = json.loads(snapshot(3))
    objects = sample["snapshot"]["objects"]
    objects[:] = [obj for obj in objects if obj["key"]["collector"] != "gpu"]
    for index in range(5):
        objects.append({
            "key": {"collector": "gpu", "object_id": f"GPU-10000000-0000-0000-0000-{index:012d}"},
            "sampled_at": 1000, "stale": False, "history": [],
            "metrics": [
                {"name": name, "value": value, "unit": unit, "applicable": True}
                for name, value, unit in (
                    ("index", {"integer": str(index)}, ""), ("name", "NVIDIA GeForce RTX 5090", ""),
                    ("utilization_percent", 50, "%"), ("power_w", 9.99, "W"), ("temperature_c", 24, "°C"),
                    ("memory_used_bytes", {"integer": str(24 << 30)}, "B"),
                    ("memory_total_bytes", {"integer": str(32 << 30)}, "B"),
                )
            ],
        })
    inventory = next(obj for obj in objects if obj["key"]["collector"] == "gpu_inventory")
    inventory["metrics"][0]["value"] = {"integer": "5"}
    for index, model in enumerate(sample["metadata"]["models"]):
        model["gpu_ids"] = ["0", "1", "2", "3"] if index == 0 else ["4"]
    updated = json.loads(json.dumps(sample))
    updated.update(sequence=2, published_at=1001)
    for obj in updated["snapshot"]["objects"]:
        if obj["key"]["collector"] == "gpu":
            next(m for m in obj["metrics"] if m["name"] == "power_w")["value"] = 123.45
    observe_document(tmp_path, {"scene": "full-window", "width": 1280, "height": 690,
                                "sample": json.dumps(sample) + "\n", "next": json.dumps(updated) + "\n"})


@pytest.mark.parametrize("gap", [False, True])
def test_history_clips_continuous_observations_at_the_left_window_edge(tmp_path, gap):
    lines = []
    for sequence, published in enumerate((1000.0, 1001.1, 1002.1), start=1):
        sample = json.loads(snapshot(3, sequence=sequence, now=published))
        chat = next(obj for obj in sample["snapshot"]["objects"] if obj["key"] == {
            "collector": "vllm", "object_id": "m0"})
        chat["history"] = [
            {"sampled_at": second + .25, "metrics": None if gap and second == 941 else [
                {"name": "decode_rate", "value": 8 + second % 4 * 4, "unit": "tok/s", "applicable": True}]}
            for second in range(940, 1003) if published - 60 <= second + .25 <= published
        ]
        lines.append(json.dumps(sample) + "\n")
    observe_document(tmp_path, {"scene": "left-boundary", "width": 1280, "height": 900,
                                "gap": gap, "lines": lines})


def test_model_click_survives_an_update_between_press_and_release(tmp_path):
    """Use a trusted browser click while the same visible model receives a new frame."""
    async def click_during_update(command):
        async def evaluate(expression):
            reply = await command("Runtime.evaluate", {
                "expression": expression, "awaitPromise": True, "returnByValue": True,
            })
            assert "exceptionDetails" not in reply, reply.get("exceptionDetails")
            return reply["result"].get("value")

        await evaluate("""window.waitUntil = async predicate => {
            const end = performance.now() + 2500;
            while (!predicate()) {
                if (performance.now() > end) throw Error('page did not reach expected state');
                await new Promise(resolve => setTimeout(resolve, 10));
            }
        }""")
        async def mouse(kind, position):
            await command("Input.dispatchMouseEvent", {"type": kind, "button": "left",
                                                       "clickCount": 1, **position})

        async def deliver(sequence, cpu):
            line = snapshot(3, sequence=sequence, now=999 + sequence)
            await evaluate(f"connection.enqueue(new TextEncoder().encode({json.dumps(line)}))")
            await evaluate(f"waitUntil(() => document.querySelector('#host').innerText.includes('{cpu}'))")

        center = """(() => {
            const button = document.querySelector('[data-model-id="m1"]');
            button.scrollIntoView({block: 'center'});
            const r = button.getBoundingClientRect();
            const x = r.x + r.width / 2, y = r.y + r.height / 2;
            if (!button.contains(document.elementFromPoint(x, y))) throw Error('model button is obscured');
            return {x, y};
        })()"""
        selected = "document.querySelector('#models [aria-pressed=true]').dataset.modelId"
        await evaluate("waitUntil(() => window.connection)")
        await deliver(1, "12.5")
        press = await evaluate(center)
        await mouse("mousePressed", press)
        await mouse("mouseReleased", press)
        assert await evaluate(selected) == "m1", "ordinary click selects this model"
        await evaluate("""document.querySelector('[data-model-id="m0"]').click()""")
        assert await evaluate(selected) == "m0"
        await mouse("mousePressed", press)
        await deliver(2, "17.5")
        assert await evaluate(center) == press, "the clicked model stayed under the pointer"
        await mouse("mouseReleased", press)
        assert await evaluate(selected) == "m1"
        assert await evaluate("document.querySelector('#detail h2').innerText") == "双模型"

    observe_document(tmp_path, {"scene": "native-click"}, interact=click_during_update)


def test_host_gauges_scale_and_native_arrow_focus_keeps_the_theme_color(tmp_path):
    async def inspect(command):
        async def evaluate(expression):
            result = await command("Runtime.evaluate", {
                "expression": expression, "awaitPromise": True, "returnByValue": True})
            assert "exceptionDetails" not in result, result.get("exceptionDetails")
            return result["result"].get("value")

        await evaluate("""new Promise(resolve => {
          function ready() { if (window.connection) resolve(); else setTimeout(ready, 10); }
          ready();
        })""")
        await evaluate(f"connection.enqueue(new TextEncoder().encode({json.dumps(snapshot(3))}))")
        for width, height in ((1280, 900), (390, 844), (1920, 1080)):
            await command("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
            await evaluate("""new Promise(resolve =>
              requestAnimationFrame(() => requestAnimationFrame(resolve)))""")
            host = await evaluate("""(() => {
              const panel = document.querySelector('#host'), style = getComputedStyle(panel);
              return {
                content: panel.getBoundingClientRect().width - parseFloat(style.paddingLeft) -
                  parseFloat(style.paddingRight) - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth),
                bars: [...panel.querySelectorAll('[role=meter]')].map(node => ({
                  width: node.getBoundingClientRect().width, value: Number(node.getAttribute('aria-valuenow'))
                }))
              };
            })()""")
            assert len(host["bars"]) == 2
            assert [bar["value"] for bar in host["bars"]] == [12.5, 25]
            assert all(abs(bar["width"] - host["content"] / 2) < .5 for bar in host["bars"])

        async def key(name, code):
            for event in ("keyDown", "keyUp"):
                await command("Input.dispatchKeyEvent", {
                    "type": event, "key": name, "windowsVirtualKeyCode": code})

        await evaluate("""document.querySelector('[data-model-id="m0"]').focus()""")
        for theme in ("hologram", "moonlight"):
            if theme == "moonlight":
                await key("t", 84)
            for arrow, code, expected in (("ArrowDown", 40, "m1"), ("ArrowUp", 38, "m0")):
                await key(arrow, code)
                selected = await evaluate("""(() => {
                  const node = document.querySelector('#models [aria-pressed=true]'), style = getComputedStyle(node);
                  return {
                    theme: document.querySelector('#dashboard').dataset.theme, id: node.dataset.modelId,
                    focused: node === document.activeElement && node.matches(':focus-visible'),
                    border: style.borderTopColor, outline: style.outlineColor,
                    outlineStyle: style.outlineStyle, outlineWidth: parseFloat(style.outlineWidth),
                    primary: getComputedStyle(document.querySelector('#theme')).color
                  };
                })()""")
                assert (selected["theme"], selected["id"], selected["focused"]) == (theme, expected, True)
                assert selected["outlineStyle"] != "none" and selected["outlineWidth"] > 0
                assert selected["border"] == selected["outline"] == selected["primary"]
            await evaluate("""document.querySelector('[data-model-id="m2"]').focus()""")
            await key("Tab", 9)
            for action in ("tab", "click"):
                if action == "click":
                    point = await evaluate("""(() => {
                      const node = document.querySelector('nav [aria-current="page"]');
                      node.scrollIntoView({block: 'nearest'});
                      const rect = node.getBoundingClientRect();
                      return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                    })()""")
                    for event in ("mousePressed", "mouseReleased"):
                        await command("Input.dispatchMouseEvent", {
                            "type": event, "button": "left", "clickCount": 1, **point})
                service = await evaluate("""(() => {
                  const node = document.querySelector('nav [aria-current="page"]'), style = getComputedStyle(node);
                  return {focused: node === document.activeElement, visible: node.matches(':focus-visible'),
                    border: style.borderBottomColor, outline: style.outlineColor,
                    outlineStyle: style.outlineStyle, primary: getComputedStyle(document.querySelector('#theme')).color};
                })()""")
                assert service["focused"] and service["border"] == service["primary"]
                if action == "tab":
                    assert service["visible"] and service["outlineStyle"] != "none"
                if service["visible"]:
                    assert service["outline"] == service["primary"]
        assert await evaluate("window.requests.length") == 1

    observe_document(tmp_path, {"scene": "host-focus"}, interact=inspect)


def observe_document(tmp_path, settings, *, interact=None):
    assets = files("joi_observer.web").joinpath("static")
    source = assets.joinpath("index.html").read_text(encoding="utf-8")
    # Keep the same scripts/styles and boot order. Resolve /static assets as
    # same-release file:// URLs and replace only the external data source.
    preload = """<script>
    window.requests = [];
    window.fetch = async function (url, options) {
      if (this !== window) throw new TypeError('Invalid receiver for Window.fetch');
      requests.push(String(url));
      window.liveSignal = options.signal;
      if (url !== '/api/live') throw Error('unexpected route');
      if (location.search === '?unavailable') return new Response('Snapshot unavailable.', {status:503});
      const body = new ReadableStream({start(c) { window.connection = c; }});
      return new Response(body, {headers: RESPONSE_HEADERS});
    };
    window.addEventListener('error', e => { window.bootError = e.message; });
    </script>""".replace("RESPONSE_HEADERS", json.dumps(settings.get("headers", {
        "Content-Type": "application/x-ndjson", "Date": "Tue, 17 Nov 2026 03:04:05 GMT",
        "X-Joi-Sent-At": "1000",
    })))
    if settings["scene"] in ("scroll-window", "left-boundary"):
        preload += """<script>window.clockOffset = 0;
          Object.defineProperty(performance, "now", {value: () => window.clockOffset});</script>"""
    elif settings["scene"] == "buffered-stream" or settings["scene"].startswith("hidden-"):
        preload += """<script>
          const elapsed = performance.now.bind(performance); window.clockOffset = 0;
          Object.defineProperty(performance, "now", {value: () => elapsed() + window.clockOffset});
        </script>"""
    if settings["scene"] == "layout":
        # The same document and sample as the automated layout case, for the
        # two visual comparisons with the Neon Grid reference.
        preload += """<script>
          if (location.search === "?visual") {
            const read = window.fetch;
            window.fetch = async (...args) => {
              const response = await read(...args);
              const sample = JSON.parse(SAMPLE), encoder = new TextEncoder();
              let last = performance.now();
              function showSample() {
                window.connection.enqueue(encoder.encode(JSON.stringify(sample) + "\\n"));
              }
              showSample();
              // Keep this reference view available while inspecting either
              // viewport. Only one fixed sample is held; its time axis advances.
              const timer = setInterval(() => {
                const now = performance.now(), step = (now - last) / 1000;
                last = now;
                sample.sequence++;
                sample.snapshot.revision++;
                sample.published_at += step;
                for (const obj of sample.snapshot.objects) {
                  if (obj.sampled_at !== null) obj.sampled_at += step;
                  for (const point of obj.history) point.sampled_at += step;
                }
                showSample();
              }, 1000);
              const stop = () => clearInterval(timer);
              window.liveSignal.addEventListener("abort", stop, {once:true});
              window.addEventListener("pagehide", stop, {once:true});
              return response;
            };
          }
        </script>""".replace("SAMPLE", json.dumps(settings["sample"]).replace("<", "\\u003c"))
    revision = "a" * 64
    source = source.replace("__JOI_RELEASE__", revision).replace("<head>", "<head>" + preload)
    directory = tmp_path / "static" / revision
    directory.mkdir(parents=True)
    for name in ("dashboard.css", "dashboard.js"):
        source = source.replace(f'"/static/{revision}/{name}"', f'"static/{revision}/{name}"')
        (directory / name).write_bytes(assets.joinpath(name).read_bytes())
    (tmp_path / "page.html").write_text(source, encoding="utf-8")
    if interact is not None:
        run_document(tmp_path / "page.html", interact=interact)
        return
    driver = "\n".join(Path(__file__).with_name(name).read_text(encoding="utf-8") for name in (
        "dashboard_chart_checks.js", "dashboard_state_checks.js", "observe_dashboard.js",
    ))
    settings = json.dumps(settings, ensure_ascii=True).replace("<", "\\u003c")
    fixture = tmp_path / "fixture.html"
    fixture.write_text('<!doctype html><meta charset="utf-8"><output id="result">waiting</output>'
                       + f"<script>const setup={settings};\n{driver}</script>", encoding="utf-8")
    run_document(fixture, budget_ms=18000)
