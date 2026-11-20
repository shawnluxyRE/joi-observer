/* Inspect the production document through its visible DOM, computed styling and layout. */
const pause = () => new Promise(resolve => setTimeout(resolve, 75));
const requireThat = (ok, reason) => { if (!ok) throw Error(reason); };
const box = el => el.getBoundingClientRect();
const shown = el => !!el && box(el).width > 0 && box(el).height > 0 &&
  el.ownerDocument.defaultView.getComputedStyle(el).visibility === "visible";
function visibleRows(root, kind) {
  const track = root.matches("[data-list-body]") ? root : root.querySelector("[data-list-body]");
  const boundary = box(track);
  return [...track.querySelectorAll(`[data-${kind}-id]`)].filter(el => {
    const row = box(el);
    return shown(el) && boundary.height > 0 && row.top < boundary.bottom && row.bottom > boundary.top;
  });
}
const ids = (root, kind) => visibleRows(root, kind).map(el => el.getAttribute(`data-${kind}-id`));

async function untilShown(predicate, description, timeout = 1800) {
  const end = performance.now() + timeout;
  while (!predicate()) {
    requireThat(performance.now() < end, description);
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}

async function openPage(failAtOpen = false) {
  const frame = document.createElement("iframe");
  frame.style.cssText = `width:${setup.width}px;height:${setup.height}px;border:0`;
  const loaded = new Promise(resolve => frame.onload = resolve);
  frame.src = failAtOpen ? "page.html?unavailable" : "page.html";
  document.body.append(frame);
  await loaded;
  const win = frame.contentWindow, doc = frame.contentDocument;
  await untilShown(() => win.bootError || win.requests.length || shown(doc.querySelector("#error")),
    "boot must either issue the data request or report a resource error");
  requireThat(!win.bootError, win.bootError || "boot");
  requireThat(win.requests.join() === "/api/live", "one same-origin data request at startup");
  requireThat(!shown(doc.querySelector("#dashboard")), "metrics hidden before first complete record");
  if (!failAtOpen) requireThat(shown(doc.querySelector("#loading")), "loading");
  let firstEnqueue;
  const send = async line => {
    if (firstEnqueue === undefined) firstEnqueue = win.performance.now();
    const bytes = new TextEncoder().encode(line);
    // The real ASGI records may reach the browser in independent transport chunks.
    if (setup.scene === "reference") {
      for (let offset = 0; offset < bytes.length; offset += 1024) {
        win.connection.enqueue(bytes.subarray(offset, offset + 1024));
      }
    } else {
      win.connection.enqueue(bytes);
    }
    await pause();
  };
  return {frame, win, doc, send, get firstEnqueue() { return firstEnqueue; },
    get: selector => doc.querySelector(selector)};
}

async function observe() {
  if (setup.scene === "initial-failure") {
    const failed = await openPage(true);
    const error = failed.get("#error");
    await untilShown(() => shown(error) && /refresh/i.test(error.innerText) && !shown(failed.get("#loading")),
      "initial 503 must leave an explicit refresh-only error page");
    const other = await openPage();
    await other.send(setup.sample);
    await untilShown(() => shown(other.get("#dashboard")) && shown(error) && !shown(failed.get("#dashboard"))
      && failed.win.requests.length === 1, "another successful open cannot unlock an initial error");
    return;
  }
  const a = await openPage();
  if (setup.scene === "full-window") return checkFullWindow(a);
  if (setup.scene === "left-boundary") return checkLeftBoundary(a);
  if (setup.scene === "scroll-window") return checkScrollingWindow(a);
  if (setup.scene === "chart-lifecycle") return checkChartLifetime(a);
  if (setup.scene === "buffered-chart") return checkBufferedHistory(a);
  if (setup.scene === "source-states") return checkSourceStates(a);
  if (setup.scene === "reference") return checkReferenceFrames(a, setup.lines);
  if (setup.scene === "field-values") return checkFieldValues(a);
  if (setup.scene === "medium-width") return checkMediumWidth(a);
  if (setup.scene === "resize-values") return checkResizedValues(a);
  if (setup.scene === "buffered-stream") return checkBufferedStream(a);
  if (setup.scene === "bfcache" || setup.scene.startsWith("hidden-")) return checkPageLifetime(a);
  await a.send(setup.sample);
  const {get, doc, win} = a;
  const text = selector => get(selector).innerText.replace(/\s+/g, " ");
  const section = get("#dashboard");
  await untilShown(() => shown(get("#dashboard")) && !shown(get("#loading")) && !shown(get("#error")), "live page");
  const clock = text("#hostline");
  requireThat(clock.includes("fixture-node") && clock.includes("Fixture Linux")
    && /03:04:0[56] UTC/.test(clock), "collector host and UTC clock");
  const descriptions = [get("#hostline"), ...get("#hostline").querySelectorAll("[title], [aria-label]")]
    .flatMap(el => [el.title, el.getAttribute("aria-label")]).join(" ");
  requireThat(/estimated host UTC at connection/i.test(descriptions), "UTC clock identifies its estimate");

  if (setup.scene === "empty") {
    for (const [selector, label] of [["#gpu", "No NVIDIA GPUs"], ["#models", "No models configured"],
      ["#docker", "No containers configured"], ["#storage", "No mount points configured"]]) {
      requireThat(text(selector).includes(label), label);
    }
    requireThat(!get("#detail svg") && !get("[data-model-id]"), "no invented model or plot");
    return;
  }

  requireThat(text("#host").includes("12.5") && /4\s*\/\s*16\s*GiB/.test(text("#host")), "CPU/RAM");
  requireThat(text("#storage").includes("/scratch") && text("#storage").includes("30.0%"), "mount");
  requireThat(text("#models").includes("双模型") && text("#models").includes("STALE"), "model rail");
  requireThat(text("#detail h2") === "Chat <live>", "server-provided detail title as literal text");
  requireThat(/RUNNING\s*0\b/i.test(text("#detail")) && /Total\s+19\b/.test(text("#detail"))
    && !/(RUNNING\s*0|Total\s+19)\s*\//i.test(text("#detail")), "authoritative counts without denominators");
  requireThat(text("#detail").includes("—") && text("#detail").includes("tok/s"), "unknown and chat units");
  const rows = () => ids(get("#models"), "model");
  const selected = () => get('#models [aria-pressed="true"]')?.dataset.modelId;
  const clickModel = id => get(`[data-model-id="${id}"]`).click();
  const key = k => doc.activeElement.dispatchEvent(new win.KeyboardEvent("keydown", {key: k, bubbles: true}));
  if (setup.scene === "capacity") return checkCapacities(a);
  if (setup.scene === "chart") return checkHistory(a);
  if (setup.scene === "layout") {
    const body = box(section), host = box(get("#host")), gpuBox = box(get("#gpu"));
    requireThat(Math.abs(body.left) < .5 && Math.abs(body.top) < .5 &&
      Math.abs(body.width - doc.documentElement.clientWidth) < 1 && body.height >= win.innerHeight,
      "dashboard fills the viewport without external margins");
    requireThat(box(get("#storage")).top >= host.bottom - 1 && box(get("#docker")).top >= box(get("#storage")).bottom - 1,
      "host stack ordering");
    const mobile = setup.width <= 600;
    checkHardwareAndShell(a, mobile);
    requireThat(mobile ? host.top >= gpuBox.bottom - 1 : host.left >= gpuBox.right - 1,
      "responsive GPU/host panels");
    const info = box(get("#detail"));
    requireThat(mobile ? info.top >= box(get("#models")).bottom - 1 : info.left >= box(get("#models")).right - 1,
      "responsive model rail");
    requireThat(!doc.querySelector('input[type="range"], [data-history-pan]') &&
      !/PAN HISTORY|q\s+Quit|180s|Amber Relay|Vector Matrix/i.test(section.innerText), "formal page controls");
    requireThat(win.getComputedStyle(section).fontFamily.toLowerCase().includes("mono"), "system mono stack");
    requireThat(win.getComputedStyle(section).backgroundColor === "rgb(8, 14, 24)", "terminal background");
    const panelIds = [["#gpu","gpu"], ["#docker","container"], ["#models","model"]];
    for (const [selector, kind] of panelIds) {
      const panel = get(selector), visible = ids(panel, kind);
      requireThat(visible.length > 0 && visible.length <= setup.count, "visible " + kind + " rows");
      const prefix = kind === "container" ? "worker-" : "m";
      requireThat(visible.every((name, index) => kind === "gpu" ?
        name.endsWith(String(index).padStart(12, "0")) : name === prefix + index), "source order");
      requireThat(!["auto", "scroll"].includes(win.getComputedStyle(panel).overflowY), "no panel scroll");
      const bounds = box(panel.querySelector("[data-list-body]"));
      for (const row of visibleRows(panel, kind)) {
        requireThat(box(row).bottom <= bounds.bottom + 1, "no partial rows");
      }
    }
    const second = await openPage();
    await second.send(setup.larger);
    await untilShown(() => shown(second.get("#dashboard")), "overflow comparison page is live");
    for (const [selector, kind] of panelIds) {
      const firstPanel = get(selector), secondPanel = second.get(selector);
      requireThat(Math.abs(box(firstPanel).height - box(secondPanel).height) < 1,
        "adding an object does not grow " + kind);
      // A full-size panel may fit all four fixture rows. Limit the list tracks
      // to the same measured prefix so just one extra object exercises overflow.
      const firstRows = visibleRows(firstPanel, kind);
      const prefix = firstRows.slice(0, 3);
      const expected = ids(firstPanel, kind).slice(0, prefix.length);
      const firstTrack = firstPanel.querySelector("[data-list-body]");
      const height = box(prefix.at(-1)).bottom - box(firstTrack).top;
      for (const panel of [firstPanel, secondPanel]) {
        panel.querySelector("[data-list-body]").style.setProperty("max-height", height + "px", "important");
      }
      await untilShown(() => [firstPanel, secondPanel].every(panel =>
        ids(panel, kind).join() === expected.join()), "both pages show only the complete prefix of " + kind);
      requireThat(Math.abs(box(firstPanel).height - box(secondPanel).height) < 1, "overflow does not grow " + kind);
    }
    requireThat(section.scrollWidth <= section.clientWidth + 1, "no horizontal page overflow");
    return;
  }
  if (setup.scene === "selection") {
    requireThat(selected() === "m0" && get('[data-gpu-id$="000000000000"]').dataset.linked === "true", "first model GPU");
    get('[data-model-id="m0"]').focus();
    key("ArrowDown");
    await untilShown(() => selected() === "m1" && text("#detail h2") === "双模型" && text("#detail").includes("STALE")
      && text("#detail").includes("N/A") && text("#detail").includes("seq/s"), "failed pooling model remains selectable");
    const allCounts = [text("#detail"), ...[...get("#detail").querySelectorAll("[title], [aria-label]")].map(
      el => (el.title || "") + (el.getAttribute("aria-label") || ""))].join(" ");
    requireThat(allCounts.includes("9007199254740993"), "exact total remains available when visually abbreviated");
    requireThat(get('[data-gpu-id$="000000000001"]').dataset.linked === "true", "mapped second GPU");
    const linked = visibleRows(get("#gpu"), "gpu").filter(row => row.dataset.linked === "true");
    requireThat(linked.length === 1 && linked[0].dataset.gpuId.endsWith("000000000001"), "old GPU highlight cleared");
    const firstRow = get('[data-gpu-id$="000000000000"]');
    const secondRow = get('[data-gpu-id$="000000000001"]');
    const paints = el => [el, ...el.querySelectorAll("*")].filter(shown).flatMap(node => {
      const style = win.getComputedStyle(node);
      return [style.color, style.backgroundColor];
    });
    const accent = "rgb(123, 159, 255)";
    requireThat(paints(secondRow).includes(accent) && !paints(firstRow).includes(accent),
      "actual selected GPU paint differs from the unrelated GPU");
    get("#theme").click();
    await untilShown(() => get("#dashboard").dataset.theme === "moonlight", "first page changes theme");
    await a.send(setup.heartbeat);
    await a.send(setup.next);
    await untilShown(() => text("#host").includes("17.5"), "first page consumes the heartbeat and the next update");
    requireThat(get("#dashboard").dataset.theme === "moonlight" && selected() === "m1" &&
      text("#detail h2") === "双模型", "new publications preserve the page's theme and selection");
    requireThat(paints(get('[data-gpu-id$="000000000001"]')).includes("rgb(125, 223, 255)"), "Moonlight GPU paint");
    const second = await openPage();
    await second.send(setup.sample);
    await untilShown(() => shown(second.get("#dashboard")) && second.get("#dashboard").dataset.theme === "hologram" &&
      second.get('[data-model-id="m0"]')?.getAttribute("aria-pressed") === "true" &&
      second.get("#detail h2").innerText === "Chat <live>", "a later document opens with its own defaults");
    requireThat(get("#dashboard").dataset.theme === "moonlight" && selected() === "m1",
      "opening another document preserves the first one");
    key("t");
    await untilShown(() => get("#dashboard").dataset.theme === "hologram", "theme key");
    second.get("#theme").click();
    await untilShown(() => second.get("#dashboard").dataset.theme === "moonlight", "second page changes theme");
    const old = rows().at(-1);
    clickModel(old);
    await untilShown(() => selected() === old, "last visible model selected");
    requireThat(get("#dashboard").dataset.theme === "hologram" && second.get("#detail h2").innerText === "Chat <live>",
      "each document handles later theme and model changes independently");
    get(`[data-model-id="${old}"]`).focus();
    a.frame.style.width = "390px";
    a.frame.style.height = "844px";
    await untilShown(() => rows().length === 3 && !rows().includes(old) && selected() === "m0" &&
      doc.activeElement.dataset.modelId === "m0", "shrink selects and focuses the first visible model");
    key("ArrowUp");
    get("#theme").focus();
    a.frame.style.width = "1280px";
    a.frame.style.height = "1400px";
    await untilShown(() => rows().includes(old), "model rail expands again");
    requireThat(doc.activeElement === get("#theme"), "resize leaves existing focus outside the list alone");
    requireThat(selected() === "m0" && win.requests.length === 1, "bounded input never opens a connection");
    return;
  }
  win.connection.close();
  await untilShown(() => shown(get("#error")) && !shown(section), "lost stream hides all live metrics");
  const second = await openPage();
  await second.send(setup.next);
  await untilShown(() => shown(second.get("#dashboard")) && shown(get("#error")) && win.requests.length === 1,
    "another page reopening cannot revive a failed document");
  const reloaded = new Promise(resolve => a.frame.addEventListener("load", resolve, {once: true}));
  a.frame.contentWindow.location.reload();
  await reloaded;
  const fresh = a.frame.contentWindow;
  await untilShown(() => fresh.requests?.length === 1, "refreshed page starts fetching");
  requireThat(fresh.requests.join() === "/api/live", "reload starts one new document request");
  fresh.connection.enqueue(new TextEncoder().encode(setup.next));
  await untilShown(() => shown(fresh.document.querySelector("#dashboard")), "fresh document recovers");
}

window.addEventListener("load", async () => {
  try {
    await observe();
    document.getElementById("result").textContent = "passed";
  } catch (error) {
    document.getElementById("result").textContent = error.message;
  }
}, {once: true});
