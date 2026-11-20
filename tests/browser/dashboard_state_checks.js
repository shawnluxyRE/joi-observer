async function checkCapacities(page) {
  for (const kind of ["gpu", "docker", "model"]) {
    const attr = kind === "docker" ? "container" : kind;
    const selector = `[data-list-body="${kind}"]`;
    const body = page.get(selector);
    const items = visibleRows(body, attr);
    requireThat(items.length >= 4, "tall fixture must show four " + kind + " rows");
    // Use the rendered fourth row as an independent measurement, including
    // any group headers/gaps before it. The body excludes panel chrome.
    const bodyTop = box(body).top;
    const three = box(items[2]).bottom - bodyTop;
    const four = box(items[3]).bottom - bodyTop;
    // These five rows have identical structure and height (including each
    // GPU group's heading). Measure the fourth increment without using a
    // possibly missing fifth DOM row to determine whether it should fit.
    const five = four + (four - three);
    const naturalHeight = box(body).height;
    const naturalCount = naturalHeight >= five ? 5 : 4;
    requireThat(items.length === naturalCount, "largest ordered prefix at natural height for " + kind);
    const style = page.doc.createElement("style");
    page.doc.head.append(style);
    for (const [height, count] of [[three, 3], [four - 1, 3], [four, 4],
                                   [five + 1, 5], [three - 1, 2], [0, 0]]) {
      if (kind === "model" && count === 0) page.get(selector).querySelector("[data-model-id]").focus();
      style.textContent = `${selector}{height:${height}px!important;min-height:${height}px!important;max-height:${height}px!important}`;
      await untilShown(() => Math.abs(box(page.get(selector)).height - height) < 0.1 &&
        ids(page.get(selector), attr).length === count, `${kind}: ${count} complete rows at ${height}px`);
    }
    if (kind === "docker") {
      const label = page.get("#docker").innerText;
      requireThat(label.includes(String(setup.count)) && !label.includes("No containers configured"),
        "configured Docker list can be distinguished at zero capacity");
    }
    if (kind === "model") {
      await untilShown(() => page.doc.activeElement === page.get("#models h2") &&
        ![...page.get("#detail").querySelectorAll("svg,[data-metric]")].some(shown),
        "empty rail transfers model focus to its heading and clears details");
    }
    style.remove();
    await untilShown(() => ids(page.get(selector), attr).length === naturalCount, "natural prefix restored for " + kind);
  }
}

function metric(page, name) {
  return visibleMetricText(page.get(`#detail [data-metric="${name}"]`));
}

async function checkBufferedStream(page) {
  const waiting = () => shown(page.get("#snapshot-wait"));
  const hasCpu = value => page.get("#host").innerText.includes(value);
  await page.send(setup.sample);
  await untilShown(() => shown(page.get("#dashboard")) && hasCpu("12.5"), "initial fresh sample");
  page.win.clockOffset += 9000;
  await page.send(setup.old);
  await untilShown(() => waiting() && /waiting for a fresh snapshot/i.test(page.get("#snapshot-wait").innerText),
    "last good picture explicitly marked waiting for fresh data");
  requireThat(hasCpu("12.5") && !hasCpu("17.5") && !shown(page.get("#error")), "old numbers cannot replace good ones");
  await page.send(setup.fresh);
  await untilShown(() => hasCpu("27.5") && !waiting(), "verified, advancing record clears wait");
  requireThat(page.win.requests.length === 1, "same reader while catching up");
}

async function checkPageLifetime(page) {
  const {win, doc, get} = page;
  await page.send(setup.sample);
  await untilShown(() => shown(get("#dashboard")) && get("#host").innerText.includes("12.5"), "live before leaving");
  if (setup.scene === "bfcache") {
    win.dispatchEvent(new win.PageTransitionEvent("pagehide", {persisted: true}));
    win.dispatchEvent(new win.PageTransitionEvent("pageshow", {persisted: true}));
  } else {
    let hidden = true;
    Object.defineProperty(doc, "hidden", {get: () => hidden});
    Object.defineProperty(doc, "visibilityState", {get: () => hidden ? "hidden" : "visible"});
    doc.dispatchEvent(new win.Event("visibilitychange"));
    // JS was paused, but the original HTTP response may contain a fresh record.
    win.clockOffset += 15000;
    if (setup.scene === "hidden-fresh") win.connection.enqueue(new TextEncoder().encode(setup.fresh));
    if (setup.scene === "hidden-eof") win.connection.close();
    hidden = false;
    doc.dispatchEvent(new win.Event("visibilitychange"));
    requireThat(!shown(get("#dashboard")), "hide stale instruments before processing the original stream");
    if (setup.scene === "hidden-silent") {
      await untilShown(() => shown(get("#snapshot-wait")) && /waiting for a fresh snapshot/i.test(get("#snapshot-wait").innerText),
        "show a visible waiting status while the original stream catches up");
    }
  }
  if (setup.scene === "hidden-fresh") {
    await untilShown(() => shown(get("#dashboard")) && get("#host").innerText.includes("29.5"), "fresh queue resumes");
    requireThat(!shown(get("#error")) && !win.liveSignal.aborted, "healthy response remains open");
  } else {
    await untilShown(() => shown(get("#error")) && !shown(get("#dashboard")) && win.liveSignal.aborted,
      "known failure or silence requires refresh", 3500);
  }
  requireThat(!shown(get("#snapshot-wait")), "the waiting status clears on recovery or failure");
  requireThat(win.requests.length === 1, "visibility or page restoration never fetches again");
}

function checkHardwareAndShell(page, mobile) {
  const {get} = page;
  const meter = (root, label, value) => {
    const found = [...root.querySelectorAll('[role="meter"],meter')].find(node =>
      label.test(node.getAttribute("aria-label") || node.labels?.[0]?.innerText ||
        (node.getAttribute("aria-labelledby") || "").split(/\s+/).map(id =>
          page.doc.getElementById(id)?.textContent || "").join(" ")));
    requireThat(shown(found) && found.checkVisibility({opacityProperty:true}) && box(found).width > box(found).height &&
      Number(found.getAttribute("aria-valuenow") ?? found.value) === value,
      "visible meter reports the sampled " + label);
  };
  const firstGpu = visibleRows(get("#gpu"), "gpu")[0];
  meter(firstGpu, /gpu/i, 50);
  meter(get("#host"), /cpu/i, 12.5);
  meter(get("#host"), /ram|memory/i, 25);
  if (!mobile) {
    const label = get("#gpu").innerText;
    requireThat(/GPU\s+0\s*[–—-]\s*1[\s/|·]*TP\s*2\b/i.test(label), "two assigned GPUs share their TP 2 heading");
    if (visibleRows(get("#gpu"), "gpu").length >= 3) {
      requireThat(/GPU\s+2[\s/|·]*SHARED/i.test(label), "pooling models share the third GPU");
    }
  } else {
    // Every daily model fits on one three-column rail. Read the actual text
    // rectangles: a correctly sized button alone would miss overlapping text.
    const buttons = visibleRows(get("#models"), "model");
    requireThat(buttons.length === 3, "three daily models on the narrow rail");
    for (const button of buttons) {
      const bounds = box(button);
      const walker = page.doc.createTreeWalker(button, page.win.NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        if (!walker.currentNode.textContent.trim()) continue;
        const range = page.doc.createRange();
        range.selectNodeContents(walker.currentNode);
        for (const rect of range.getClientRects()) {
          requireThat(rect.left >= bounds.left - 0.5 && rect.right <= bounds.right + 0.5 &&
            rect.top >= bounds.top - 0.5 && rect.bottom <= bounds.bottom + 0.5,
            "model text stays inside its own narrow button");
        }
      }
      requireThat(/\brunning\b/i.test(button.innerText) && /\bwaiting\b/i.test(button.innerText),
        "both queue counts remain visible on the narrow rail");
    }
  }
  requireThat(shown(get('header [aria-label="Joi::Observer"]')) && shown(get("nav button[disabled]")) &&
    /WebUI/i.test(get("nav button[disabled]").innerText), "visible brand and planned service");
}

function visibleMetricText(el) {
  if (!shown(el)) return undefined;
  const bounds = box(el);
  for (let p = el; p; p = p.parentElement) {
    const style = p.ownerDocument.defaultView.getComputedStyle(p), clip = box(p);
    if (Number(style.opacity) === 0 || style.visibility !== "visible") return undefined;
    if (["hidden","clip"].includes(style.overflowY) &&
        (clip.bottom <= bounds.top || bounds.bottom <= clip.top)) return undefined;
    if (["hidden","clip"].includes(style.overflowX) &&
        (clip.right <= bounds.left || bounds.right <= clip.left)) return undefined;
  }
  return el.innerText.trim();
}

async function checkMediumWidth(page) {
  await page.send(setup.sample);
  await untilShown(() => shown(page.get("#dashboard")), "medium-width live page");
  const textBounds = el => {
    const range = page.doc.createRange();
    range.selectNodeContents(el);
    return range.getBoundingClientRect();
  };
  const problems = [];
  for (const [field, expected] of [
    ["decode_rate", 1234.8671875], ["prefill_rate", 38.5],
    ["ttft_seconds", 0.123456789], ["kv_cache_percent", 62.5],
  ]) {
    const value = page.get(`#detail [data-metric="${field}"]`);
    const visible = value?.innerText.trim();
    const number = Number(visible?.replaceAll(",", ""));
    requireThat(shown(value) && visible && Number.isFinite(number) &&
      Math.abs(number - expected) <= expected * .005, field + " has the expected magnitude");
    const text = textBounds(value), slot = box(value.closest("[data-metric-slot]"));
    if (text.left < slot.left - .5 || text.right > slot.right + .5) problems.push(field + " overruns its slot");
  }
  const row = page.get('[data-model-id="m0"]');
  requireThat(/128\s+run/i.test(row.innerText) && /1024\s+wait/i.test(row.innerText), "queue counts and labels");
  const walker = page.doc.createTreeWalker(row, page.win.NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    if (!/\b(wait|waiting)\b/i.test(walker.currentNode.textContent)) continue;
    const end = textBounds(walker.currentNode).right, boundary = box(row).right;
    if (end > boundary + .5) problems.push("waiting label clipped by the model list");
  }
  requireThat(problems.length === 0, problems.join(", "));
}

function checkVisibleSlots(page, fields) {
  for (const [name, label, unit, expected] of fields) {
    const value = page.get(`#detail [data-metric="${name}"]`);
    const slot = value?.closest("[data-metric-slot]");
    requireThat(shown(slot) && shown(value), "visible metric slot " + name);
    const caption = visibleMetricText(slot.querySelector("[data-metric-label]"));
    const suffix = visibleMetricText(slot.querySelector("[data-metric-unit]"));
    requireThat(caption && label.test(caption) && suffix === unit, "visible label and unit for " + name);
    const actual = metric(page, name);
    requireThat(typeof expected === "number" ? actual && Number(actual) === expected : actual === expected,
      "visible value for " + name);
  }
}

async function checkResizedValues(page) {
  await page.send(setup.sample);
  await untilShown(() => shown(page.get("#dashboard")), "daily values before resize");
  page.get("#theme").click();
  page.get('[data-model-id="m0"]').focus();
  for (const width of [620, 390, 1280]) {
    page.frame.style.width = width + "px";
    await untilShown(() => page.win.innerWidth === width, "viewport reaches requested width");
    await pause();
    for (const [field, expected] of [
      ["decode_rate", 1234.8671875], ["prefill_rate", 38.5],
      ["ttft_seconds", 0.123456789], ["kv_cache_percent", 62.5],
    ]) {
      const node = page.get('[data-metric="' + field + '"]');
      const visible = node.innerText.trim();
      requireThat(visible && Number.isFinite(Number(visible)) &&
        Math.abs(Number(visible) - expected) <= expected * .005, field + " remains readable after resize");
      if (width === 1280) requireThat(visible === String(expected), field + " restores available precision");
      const range = page.doc.createRange();
      range.selectNodeContents(node);
      const boundary = box(node.closest("[data-metric-slot]"));
      requireThat([...range.getClientRects()].every(rect =>
        rect.left >= boundary.left - .5 && rect.right <= boundary.right + .5),
        field + " stays within its resized slot");
    }
    for (const button of visibleRows(page.get("#models"), "model")) {
      const boundary = box(button);
      const range = page.doc.createRange();
      range.selectNodeContents(button.querySelector(".counts"));
      requireThat([...range.getClientRects()].every(rect =>
        rect.left >= boundary.left - .5 && rect.right <= boundary.right + .5 &&
        rect.top >= boundary.top - .5 && rect.bottom <= boundary.bottom + .5),
        "queue values and labels fit after resize");
    }
    requireThat(page.get('[data-model-id="m0"]').getAttribute("aria-pressed") === "true" &&
      page.doc.activeElement.dataset.modelId === "m0" &&
      page.get("#dashboard").dataset.theme === "moonlight", "resize preserves selection, focus and theme");
  }
  requireThat(page.win.requests.length === 1, "resizing uses the original subscription");
}

async function checkFullWindow(page) {
  await page.send(setup.sample);
  await untilShown(() => shown(page.get("#dashboard")), "live five-GPU page");
  const gpuIds = () => ids(page.get("#gpu"), "gpu");
  requireThat(gpuIds().length === 5, "five ordinary GPU cards fit before maximizing");
  for (const [width, height] of [[1280, 710], [1920, 960], [1920, 1080]]) {
    page.frame.style.width = width + "px";
    page.frame.style.height = height + "px";
    await untilShown(() => page.win.innerWidth === width && page.win.innerHeight === height, "window resized");
    await pause();
    const frame = box(page.get("#dashboard"));
    requireThat(frame.left === 0 && frame.top === 0 && Math.abs(frame.width - page.doc.documentElement.clientWidth) < 1 &&
      Math.abs(frame.height - Math.max(height, 876)) < 1, "full viewport without outer whitespace");
    requireThat(gpuIds().length === 5, "maximizing cannot remove GPU 4");
  }
  const widths = () => [...page.get("#gpu").querySelectorAll(".gpu-gauge .meter")].map(node => box(node).width);
  const before = widths();
  await page.send(setup.next);
  requireThat(widths().every((width, i) => Math.abs(width - before[i]) < .1),
    "changing power digits cannot resize any GPU gauge");
  requireThat(page.win.requests.length === 1, "window changes retain one data request");
}

async function checkFieldValues(page) {
  await page.send(setup.sample);
  const expectations = [
    [["decode_rate", /decode/i, "tok/s", 21.5], ["prefill_rate", /prefill/i, "tok/s", 38.5],
     ["ttft_seconds", /ttft/i, "s", 0.5], ["kv_cache_percent", /kv\s*cache/i, "%", 62.5]],
    [["rate", /rate/i, "seq/s", 4.5], ["queue_seconds", /queue/i, "s", 2.5],
     ["latency_seconds", /latency/i, "s", 5.5], ["kv_cache_percent", /kv\s*cache/i, "%", "N/A"]],
    [["rate", /rate/i, "seq/s", 5.5], ["queue_seconds", /queue/i, "s", 3.5],
     ["latency_seconds", /latency/i, "s", 6.5], ["kv_cache_percent", /kv\s*cache/i, "%", "N/A"]],
  ];
  await untilShown(() => shown(page.get("#dashboard")), "three healthy, queued models");
  for (const [index, fields] of expectations.entries()) {
    const row = page.get(`[data-model-id="m${index}"]`);
    row.click();
    await untilShown(() => page.get(`[data-model-id="m${index}"]`)?.getAttribute("aria-pressed") === "true",
      "selected model");
    await untilShown(() => Number(metric(page, "waiting")) === 1 + index, "visible counts for this model");
    requireThat(page.get("#detail").innerText.includes("QUEUED") &&
      Number(metric(page, "running")) === 2 + index && Number(metric(page, "total")) === 3 + 2*index,
      "authoritative queue counts and healthy QUEUED status");
    checkVisibleSlots(page, fields);
    const caption = page.get("#detail").innerText.replace(/\s+/g, " ");
    requireThat(index === 0 ? /Avg queue\s+1\.5(?:0+)?\s*s\b/i.test(caption) : /Unit:\s*seq\b/i.test(caption),
      "queue caption for the selected model");
    checkModelHistory(page, [[19,21.5], [6.5,4.5], [3,5.5]][index], index === 0 ? "tok/s" : "seq/s");
  }
}

async function checkSourceStates(page) {
  await page.send(setup.sample);
  await untilShown(() => shown(page.get("#dashboard")), "a valid unobserved first snapshot is live");
  requireThat(page.get("#models").innerText.includes("双模型") && metric(page, "running") === "—" &&
    !/READY|QUEUED|STALE/.test(page.get("#detail").innerText), "unobserved configured model identity and state");
  const gpu = () => page.get("#gpu");
  requireThat(gpu().innerText.includes("—") && !gpu().innerText.includes("No NVIDIA GPUs"), "unobserved inventory");
  const docker = page.get('[data-container-id="worker-0"]');
  requireThat(docker.innerText.includes("worker-0") && docker.innerText.includes("—"), "unobserved container identity");
  await page.send(setup.known);
  await untilShown(() => ids(gpu(), "gpu").length >= 1, "observed GPU");
  const containers = visibleRows(page.get("#docker"), "container");
  const failed = containers.find(row => row.dataset.containerId === "worker-1");
  const healthy = containers.find(row => row.dataset.containerId === "worker-0");
  requireThat(failed && /\bSTALE\b/.test(failed.innerText) && !/\bRunning\b/.test(failed.innerText) &&
    healthy && /\bRunning\b/.test(healthy.innerText), "stale Docker state replaces its retained Running label");
  const slots = ids(gpu(), "gpu");
  await page.send(setup.removed);
  await untilShown(() => page.get(`[data-gpu-id="${slots[0]}"]`)?.innerText.includes("STALE"),
    "a retained removed device remains visible");
  requireThat(ids(gpu(), "gpu").join() === slots.join() && !gpu().innerText.includes("No NVIDIA GPUs") &&
    !shown(page.get("#error")), "zero inventory with retained GPU slots is a source status");
}

async function checkReferenceFrames(page, lines) {
  const detail = () => page.get("#detail").innerText.replace(/\s+/g, " ");
  const row = id => page.get(`[data-model-id="${id}"]`);
  const aliases = [
    ["chat", "qwen3.8-flash-next", 8000, "decode_rate", "tok/s"],
    ["embedding", "qwen3-embedding-4b", 8001, "rate", "seq/s"],
    ["reranker", "qwen3-reranker-0.6b", 8002, "rate", "seq/s"],
  ];
  await page.send(lines[0]);
  await untilShown(() => shown(page.get("#dashboard")), "real ASGI first snapshot reaches the dashboard");
  requireThat(page.get("#hostline").innerText.includes("Offline Host"), "host metadata");
  const gpu = page.get("[data-gpu-id]").innerText.replace(/\s+/g, " ");
  for (const pattern of [/Offline GPU 0/, /4\.0\s*\/\s*24\.0\s*GiB/, /50\s*%/, /61\s*°C/, /123\.5\s*W/]) {
    requireThat(pattern.test(gpu), "GPU visible sample " + pattern);
  }
  requireThat(/4\s*\/\s*16\s*GiB/.test(page.get("#host").innerText) &&
    /25\s*\/\s*100\s*GiB/.test(page.get("#storage").innerText), "host and storage capacities");
  const docker = page.get('[data-container-id="public-container"]').innerText;
  requireThat(docker.includes("public-container") && docker.includes("Exited") &&
    !page.doc.body.innerText.includes("private-container-target"), "visible Docker identity and lifecycle");
  requireThat(metric(page, "decode_rate") === "—", "initial throughput has no baseline");
  await page.send(lines[1]);
  await untilShown(() => /^0(?:\.0+)?$/.test(metric(page, "decode_rate") || ""), "real observed zero");
  requireThat(/50\.0\s*%/.test(page.get("#host").innerText), "CPU sample after baseline");
  for (const [id, name, port, primary, unit] of aliases) {
    const button = row(id);
    requireThat(button.innerText.includes(id + " alias") && button.innerText.includes(":" + port),
      "configured list alias and explicit port for " + id);
    button.click();
    await untilShown(() => page.get("#detail h2")?.innerText === name, "served identity for " + id);
    requireThat(detail().includes(":" + port) && detail().includes(unit) &&
      /^0(?:\.0+)?$/.test(metric(page, primary) || "") &&
      ["running", "waiting", "total"].every(key => metric(page, key) === "0"), "counts, rate and units for " + id);
    if (id !== "chat") requireThat(metric(page, "kv_cache_percent") === "N/A", "inapplicable pooling KV cache");
  }
  row("embedding").click();
  await page.send(lines[2]);
  await untilShown(() => detail().includes("STALE") && row("embedding").innerText.includes("STALE"),
    "embedding failure wins over retained queue counts");
  requireThat(!/\b(READY|QUEUED)\b/.test(detail()) && !row("chat").innerText.includes("STALE") &&
    !shown(page.get("#error")), "local failure preserves the other sources");
  await page.send(lines[3]);
  await untilShown(() => detail().includes("READY") && !row("embedding").innerText.includes("STALE"),
    "embedding recovery clears the local failure");
}
