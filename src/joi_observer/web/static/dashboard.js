"use strict";

/** Receive a single document's stream. The host bridge has already validated
 * the IPC whitelist. Check the envelope shape used by this JS consumer before
 * handing a complete record to the view. Metric integers stay in decimal form.
 */
function readPublication(line) {
  const frame = JSON.parse(line);
  const meta = frame?.metadata;
  const snapshot = frame?.snapshot;
  const text = value => typeof value === "string";
  const time = value => Number.isFinite(value) && value >= 0;
  function validMetric(metric) {
    if (!text(metric?.name) || !text(metric.unit) || typeof metric.applicable !== "boolean") return false;
    const value = metric.value;
    return value === null || text(value) || Number.isFinite(value) ||
      (text(value?.integer) && /^-?(0|[1-9]\d*)$/.test(value.integer));
  }
  const metrics = items => Array.isArray(items) && items.every(validMetric);
  function validObject(obj) {
    return text(obj?.key?.collector) && text(obj.key.object_id) && typeof obj.stale === "boolean" &&
      (obj.sampled_at === null || time(obj.sampled_at)) && metrics(obj.metrics) &&
      Array.isArray(obj.history) && obj.history.every(point => time(point?.sampled_at) &&
        (point.metrics === null || metrics(point.metrics)));
  }
  function validModel(model) {
    return text(model?.id) && text(model.name) && text(model.served_model_name) &&
      ["chat", "embedding", "reranker"].includes(model.type) &&
      Array.isArray(model.gpu_ids) && model.gpu_ids.every(text) &&
      Number.isInteger(model.effective_port) &&
      (model.explicit_port === null || Number.isInteger(model.explicit_port));
  }
  if (frame?.protocol_version !== 1 || !text(frame.instance_id) || !text(frame.config_revision) ||
      typeof frame.sequence !== "number" || frame.sequence < 1 || !time(frame.published_at) ||
      !text(meta?.hostname) || !text(meta.system) ||
      !Array.isArray(meta.mount_points) || !meta.mount_points.every(text) ||
      !Array.isArray(meta.containers) || !meta.containers.every(item => text(item?.id)) ||
      !Array.isArray(meta.models) || !meta.models.every(validModel) ||
      typeof snapshot?.revision !== "number" || snapshot.revision < 0 ||
      !Array.isArray(snapshot.objects) || !snapshot.objects.every(validObject)) {
    throw new Error("Invalid snapshot");
  }
  return frame;
}

/** Read one same-origin response. All times used for deadlines are local
 * monotonic milliseconds; publication ages are measured in host seconds.
 */
class LiveFeed {
  constructor({fetcher = globalThis.fetch.bind(globalThis), now = () => performance.now(),
               schedule = globalThis.setTimeout.bind(globalThis),
               cancel = globalThis.clearTimeout.bind(globalThis)} = {}) {
    this.fetcher = fetcher;
    this.now = now;
    this.schedule = schedule;
    this.cancel = cancel;
    this.state = "new";
    this.timer = null;
    this.reader = null;
    this.visible = true;
    this.waiting = false;
    this.resuming = false;
    this.lastPublication = null;
  }

  start(accept, fail, waiting = () => {}) {
    if (this.state !== "new") return;
    this.state = "active";
    this.accept = accept;
    this.onFailure = fail;
    this.onWaiting = waiting;
    this.abort = new AbortController();
    this.deadline = this.now() + 12000;
    this.armTimer();
    this.readResponse().catch(() => this.fail());
  }

  // A hidden, healthy page continues reading; the original reader can catch
  // up on return. First connection and an existing wait keep their deadlines.
  get mayDefer() {
    return !this.visible && this.lastPublication !== null && !this.waiting;
  }

  armTimer() {
    if (this.timer !== null) this.cancel(this.timer);
    this.timer = null;
    if (this.state !== "active" || this.mayDefer) return;
    this.timer = this.schedule(() => {
      if (this.state !== "active" || this.mayDefer) return;
      if (this.now() >= this.deadline) this.fail();
      else this.armTimer();
    }, Math.max(0, this.deadline - this.now()));
  }

  inTime() {
    if (this.state !== "active") return false;
    if (!this.mayDefer && this.now() >= this.deadline) this.fail();
    return this.state === "active";
  }

  setWaiting(value) {
    if (this.waiting === value) return;
    this.waiting = value;
    this.onWaiting(value);
  }

  setVisible(visible) {
    // Settle the deadline under the previous visibility. An already expired
    // foreground reader cannot defer its timeout by entering the background.
    if (this.state === "active" && !this.inTime()) return false;
    if (visible === this.visible) return this.resuming;
    const wasDeferred = this.mayDefer;
    this.visible = visible;
    if (this.state !== "active") return false;
    if (visible && wasDeferred && this.now() >= this.deadline) {
      this.resuming = true;
      this.deadline = this.now() + 2000;
      this.setWaiting(true);
    }
    this.armTimer();
    return this.resuming;
  }

  async readResponse() {
    const response = await this.fetcher("/api/live", {
      mode: "same-origin", redirect: "error", signal: this.abort.signal,
    });
    if (!this.inTime()) {
      if (response.body) await response.body.cancel();
      return;
    }
    const received = this.now();
    // The response body is ours as soon as fetch resolves, including when its
    // headers are rejected. close() cancels it through the same reader.
    const reader = response.body?.getReader();
    this.reader = reader;
    const mime = response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase();
    const rawTime = response.headers.get("X-Joi-Sent-At");
    if (response.status !== 200 || mime !== "application/x-ndjson" || !reader ||
        !/^\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(rawTime) || !Number.isFinite(Number(rawTime))) {
      throw new Error("Invalid live response");
    }
    this.hostFloor = Number(rawTime);
    this.floorAt = received;
    this.headerAt = received;
    const headerDate = response.headers.get("Date");
    const utc = Date.parse(headerDate);
    this.utc = Number.isFinite(utc) && new Date(utc).toUTCString() === headerDate ? utc : null;
    const decoder = new TextDecoder("utf-8", {fatal: true, ignoreBOM: true});
    const pieces = [];
    while (this.state === "active") {
      const {value, done} = await reader.read();
      if (!this.inTime()) return;
      if (done) throw new Error("Live stream ended");
      // Decode each complete line independently, including lines which span
      // several transport chunks or share a chunk with a subsequent bad line.
      let start = 0;
      while (start < value.length && this.state === "active") {
        const end = value.indexOf(10, start);
        if (end === -1) {
          pieces.push(decoder.decode(value.subarray(start), {stream: true}));
          break;
        }
        pieces.push(decoder.decode(value.subarray(start, end)));
        const frame = readPublication(pieces.join(""));
        pieces.length = 0;
        if (!this.inTime()) return;
        this.install(frame);
        start = end + 1;
      }
    }
  }

  install(frame) {
    const at = this.now();
    const published = frame.published_at;
    this.hostFloor = Math.max(published, this.hostFloor + 0.999 * (at - this.floorAt) / 1000);
    this.floorAt = at;
    if (this.hostFloor - published > 5) {
      if (this.lastPublication !== null && !this.waiting) {
        this.setWaiting(true);
        this.armTimer();
      }
      return;
    }
    if (this.lastPublication === null || published > this.lastPublication) {
      this.lastPublication = published;
      this.resuming = false;
      this.deadline = at + 12000;
      this.setWaiting(false);
      this.armTimer();
    } else if (this.resuming) {
      return;
    }
    this.accept(frame, at, this.utc === null ? null : this.utc + at - this.headerAt);
  }

  fail() {
    if (this.state !== "active") return;
    this.close();
    this.onFailure();
  }

  close() {
    if (this.state === "closed") return;
    this.state = "closed";
    this.resuming = false;
    if (this.timer !== null) this.cancel(this.timer);
    this.timer = null;
    this.abort?.abort();
    if (this.reader) {
      this.reader.cancel().catch(() => {});
      this.reader.releaseLock();
      this.reader = null;
    }
  }
}

const HISTORY_DELAY_SECONDS = 1;

/** Play the chart one second behind trusted host time; numeric panels stay live. */
class HistoryWindowClock {
  /** Install the first publication and its local monotonic receipt in milliseconds. */
  constructor(publishedAt, receivedAtMs) {
    this.publishedAt = publishedAt;
    this.receivedAtMs = receivedAtMs;
    this.lastEdge = publishedAt - HISTORY_DELAY_SECONDS;
  }

  /** Reanchor on the latest strictly advancing fresh publication; retain the last drawn edge. */
  publish(publishedAt, receivedAtMs) {
    if (publishedAt > this.publishedAt) {
      this.publishedAt = publishedAt;
      this.receivedAtMs = receivedAtMs;
    }
  }

  /** Preserve fractional seconds and never move already displayed observations backwards. */
  rightEdge(nowMs) {
    const elapsed = (nowMs - this.receivedAtMs) / 1000;
    this.lastEdge = Math.max(this.lastEdge, this.publishedAt + elapsed - HISTORY_DELAY_SECONDS);
    return this.lastEdge;
  }
}

// All publication text goes through DOM text nodes, including names and paths.
function element(tag, className, ...children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children);
  return node;
}

const missing = "—";
const tenths = new Intl.NumberFormat("en-US", {useGrouping: false, minimumFractionDigits: 1, maximumFractionDigits: 1});
const scientificFormats = [3, 2, 1].map(precision =>
  new Intl.NumberFormat("en-US", {notation: "scientific", maximumSignificantDigits: precision}));

function getMetric(source, name) {
  return source?.metrics?.find(metric => metric.name === name);
}

function valueOfMetric(metric) {
  const value = metric?.value;
  if (value === undefined || value === null || !metric.applicable) return null;
  return typeof value === "object" ? BigInt(value.integer) : value;
}

function valueOf(source, name) {
  return valueOfMetric(getMetric(source, name));
}

function numberText(value) {
  return value === null ? missing : String(value);
}

function metricSlot(source, name, applicable = true) {
  const metric = getMetric(source, name);
  const value = valueOfMetric(metric);
  const exact = !applicable || metric?.applicable === false ? "N/A" : numberText(value);
  const slot = element("strong", value === null ? "missing" : "");
  slot.dataset.metric = name;
  slot.title = exact;
  slot.textContent = exact;
  return slot;
}

// Queue counters have intrinsic width. The four detail slots below have
// independent grid widths and are fitted only after the grid is laid out.
function queueCounter(source, name) {
  const node = metricSlot(source, name);
  if (node.title.length > 12) node.textContent = scientificFormats[0].format(valueOf(source, name)).replace("E", "e");
  return node;
}

function fitMetricValue(node, value) {
  if (value === null) return;
  const range = document.createRange();
  range.selectNodeContents(node);
  const width = node.getBoundingClientRect().width;
  const inkWidth = () => range.getBoundingClientRect().width;
  const exactWidth = inkWidth();
  if (exactWidth <= width) return;

  // Use the monospaced glyph width to skip candidates that cannot fit, and
  // confirm the chosen number against the actual rendered text rectangle.
  const characters = Math.floor(node.title.length * width / exactWidth);
  if (typeof value === "number" && !Number.isInteger(value)) {
    for (let digits = Math.min(17, characters); digits >= 3; digits--) {
      const rounded = value.toPrecision(digits).replace("e+", "e");
      if (rounded.length > characters || rounded.includes("e")) continue;
      node.firstChild.data = rounded;
      if (inkWidth() <= width) return;
    }
  }
  for (const format of scientificFormats) {
    node.firstChild.data = format.format(value).replace("E", "e");
    if (inkWidth() <= width) return;
  }
  // At extremely small widths retain every digit of the exponent.
  node.style.overflowWrap = "anywhere";
}

function capacityLabel(used, total, kind) {
  const tib = (total ?? used) >= 2n ** 40n;
  const divisor = 2n ** (tib ? 40n : 30n);
  const showTenths = kind === "gpu" || (kind === "storage" && tib);
  function rounded(value) {
    if (value === null) return missing;
    const units = (BigInt(value) * (showTenths ? 10n : 1n) + divisor / 2n) / divisor;
    return showTenths ? String(units / 10n) + "." + String(units % 10n) : String(units);
  }
  const unit = used === null && total === null ? "" : tib ? " TiB" : " GiB";
  return element("span", "", element("span", "dim", rounded(used) + " / "), rounded(total), element("span", "dim", unit));
}

function meter(label, percent, segments) {
  const bar = element("span", "meter");
  bar.setAttribute("role", "meter");
  bar.setAttribute("aria-label", label);
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  if (percent === null) bar.setAttribute("aria-valuetext", "Unknown");
  else bar.setAttribute("aria-valuenow", String(percent));
  const filled = percent === null ? 0 : Math.round(Number(percent) * segments / 100);
  for (let i = 0; i < segments; i++) bar.append(element("i", i < filled ? "filled" : ""));
  return bar;
}

function modelStatus(source) {
  if (source?.stale) return "STALE";
  const waiting = valueOf(source, "waiting");
  if (source?.sampled_at == null || valueOf(source, "running") === null || waiting === null) return missing;
  return waiting > 0 ? "QUEUED" : "READY";
}

function statusClass(status) {
  return "model-state " + (["STALE", "QUEUED"].includes(status) ? "warn" : "dim");
}

function statusNode(status) {
  return element("span", statusClass(status), status);
}

function gpuRange(indices) {
  const sorted = indices.map(BigInt).sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
  const runs = [];
  for (const index of sorted) {
    const last = runs.at(-1);
    if (last && last.end + 1n === index) last.end = index;
    else runs.push({start: index, end: index});
  }
  return "GPU " + runs.map(({start, end}) => start === end ? String(start) : start + "–" + end).join(", ");
}

// Resolve against the entire inventory before clipping it. Missing aliases
// remain unresolved, so a partial match cannot advertise a tensor-parallel size.
function gpuAssignments(cards, models) {
  const positions = new Map(), aliases = new Map(), counts = new Map();
  cards.forEach((card, i) => {
    const id = card.key.object_id, index = valueOf(card, "index");
    positions.set(id, i);
    aliases.set(id, id);
    if (index !== null) {
      const key = String(index);
      counts.set(key, (counts.get(key) || 0) + 1);
      if (!card.stale && card.sampled_at !== null) aliases.set(key, aliases.has(key) ? null : id);
    }
  });
  const byModel = new Map(), owners = new Map(), spans = new Map();
  for (const model of models) {
    const members = new Set(model.gpu_ids.map(ref => aliases.get(ref)));
    byModel.set(model.id, members);
    let first = cards.length, last = -1;
    for (const id of members) {
      if (!positions.has(id)) continue;
      owners.set(id, (owners.get(id) || 0) + 1);
      const i = positions.get(id);
      first = Math.min(first, i);
      last = Math.max(last, i);
    }
    if (last >= 0) spans.set(first, Math.max(spans.get(first) ?? first, last));
  }
  const headers = new Map();
  for (let start = 0; start < cards.length;) {
    let end = start;
    for (let i = start; i <= end; i++) end = Math.max(end, spans.get(i) ?? i);
    const group = cards.slice(start, end + 1);
    const ids = group.map(card => card.key.object_id);
    const indices = group.map(card => valueOf(card, "index"));
    if (ids.every(id => owners.has(id)) && indices.every(i => i !== null && counts.get(String(i)) === 1)) {
      const shared = ids.some(id => owners.get(id) > 1);
      const complete = Array.from(byModel.values()).some(set => set.size === ids.length && ids.every(id => set.has(id)));
      headers.set(start, [gpuRange(indices), shared ? "SHARED" : complete ? "TP " + ids.length : ""]);
    }
    start = end + 1;
  }
  return {byModel, headers};
}

function gpuRow(card, linked) {
  const id = card.key.object_id, index = numberText(valueOf(card, "index"));
  const name = numberText(valueOf(card, "name"));
  const usage = valueOf(card, "utilization_percent");
  const memory = capacityLabel(valueOf(card, "memory_used_bytes"), valueOf(card, "memory_total_bytes"), "gpu");
  const nameLabel = element("span", "ellipsis", name);
  nameLabel.title = name;
  const title = element("div", "gpu-name", nameLabel, element("span", "gpu-memory", memory));
  const gauge = element("div", "gpu-gauge", meter("GPU " + index + " utilization", usage, 16),
    element("span", "", usage === null ? missing : numberText(usage) + "%"));
  const temperature = valueOf(card, "temperature_c"), power = valueOf(card, "power_w");
  const health = element("div", "gpu-health", temperature === null ? missing : numberText(temperature) + "°C",
    element("small", "", power === null ? missing : numberText(power) + " W"));
  if (card.stale) health.append(statusNode("STALE"));
  const row = element("div", "gpu-row", element("span", "gpu-index", "[" + index + "]"),
    element("div", "", title, gauge), health);
  row.dataset.gpuId = id;
  row.dataset.linked = String(linked?.has(id) === true);
  return row;
}

function modelButton(model) {
  const name = element("span", "model-name ellipsis", model.name);
  name.title = model.name;
  const heading = element("span", "model-name-line", name, statusNode(missing));
  const type = element("span", "model-type ellipsis", model.type.toUpperCase());
  if (model.explicit_port !== null) type.append(element("span", "model-port", " / :" + model.explicit_port));
  const counts = element("span", "counts", element("span", "", ""), element("span", "", ""));
  const button = element("button", "model-button", heading, type, counts);
  button.type = "button";
  button.dataset.modelId = model.id;
  return button;
}

function updateModelButton(button, source) {
  const status = modelStatus(source);
  const label = button.querySelector(".model-state");
  label.className = statusClass(status);
  label.firstChild.data = status;
  const [running, waiting] = button.querySelector(".counts").children;
  running.firstChild.data = numberText(valueOf(source, "running")) + " running";
  waiting.firstChild.data = numberText(valueOf(source, "waiting")) + " waiting";
}

// Measure the actual laid-out rows, including group headers, gaps and
// fractional pixels. Remove the incomplete suffix from layout and tab order.
function fitRows(track, entries) {
  const content = document.createDocumentFragment();
  for (const entry of entries) content.append(...entry);
  track.replaceChildren(content);
  return trimRows(track, entries);
}

function trimRows(track, entries) {
  const bottom = track.getBoundingClientRect().bottom;
  const firstHidden = entries.findIndex(nodes => nodes.at(-1).getBoundingClientRect().bottom > bottom);
  if (firstHidden < 0) return entries.length;
  for (const nodes of entries.slice(firstHidden)) for (const node of nodes) node.remove();
  return firstHidden;
}

// Pure path calculation from the Neon Grid reference. Work in screen
// coordinates so the derivative at a shared observation agrees on both sides.
function historyCurve(points) {
  const deltas = points.slice(1).map((point, i) => (point.y - points[i].y) / (point.x - points[i].x));
  const slopes = points.map((_, i) => {
    if (i === 0) return deltas[0];
    if (i === points.length - 1) return deltas[i - 1];
    if (deltas[i - 1] * deltas[i] <= 0) return 0;
    return 2 * deltas[i - 1] * deltas[i] / (deltas[i - 1] + deltas[i]);
  });
  const pair = (x, y) => x.toFixed(2) + " " + y.toFixed(2);
  let path = "M " + pair(points[0].x, points[0].y);
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1], step = (b.x - a.x) / 3;
    path += " C " + pair(a.x + step, a.y + step * slopes[i]) + " " +
      pair(b.x - step, b.y - step * slopes[i + 1]) + " " + pair(b.x, b.y);
  }
  return path;
}

function svgElement(tag, attrs, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  node.append(...children);
  return node;
}

// Metric integers can exceed double range. Scale mantissas, then use the
// resulting bounded ratios for screen coordinates.
function scientificParts(value) {
  if (typeof value === "bigint") {
    const text = String(value);
    return {mantissa: Number(text[0] + "." + text.slice(1, 17)), exponent: text.length - 1};
  }
  const [mantissa, exponent] = value.toExponential().split("e");
  return {mantissa: Number(mantissa), exponent: Number(exponent)};
}

// Retain the one-second playback buffer and two earlier observations for
// the left-edge tangents. Empty or disjoint snapshots start afresh.
function historyWithBoundary(previous, current, publishedAt) {
  if (!current.length) return current;
  const overlap = previous.findIndex(point => point.sampled_at === current[0].sampled_at);
  if (overlap < 0) return current;
  const first = previous.findIndex(point => point.sampled_at >= publishedAt - HISTORY_DELAY_SECONDS - 60);
  const boundary = first < 0 ? overlap : Math.min(first, overlap);
  return previous.slice(Math.max(0, boundary - 2), overlap).concat(current);
}

function drawHistory(svg, history, field, rightEdge, title) {
  const bounds = svg.getBoundingClientRect();
  const width = bounds.width, height = bounds.height;
  if (width < 80 || height < 40) return;
  // Fixed plot edges also protect the visible x of existing observations when
  // a higher peak calls for wider labels on the vertical axis.
  const left = 48, right = width - 15, top = 12, bottom = height - 21;
  const since = rightEdge - 60;
  const x = time => left + (time - since) / 60 * (right - left);
  const runs = [];
  let run = null, maximum = null;
  const first = history.findIndex(point => point.sampled_at >= since);
  const context = first < 0 ? [] : history.slice(Math.max(0, first - 2));
  for (const point of context) {
    // Already received samples just ahead of playback provide the right-edge
    // interpolation. The fixed window clips them without shifting their times.
    const value = valueOf(point, field);
    if (value === null || value < 0) {
      run = null;
      continue;
    }
    if (!run) {
      run = [];
      runs.push(run);
    }
    const parts = scientificParts(value);
    if (parts.mantissa > 0 && (!maximum || parts.exponent > maximum.exponent ||
        (parts.exponent === maximum.exponent && parts.mantissa > maximum.mantissa))) maximum = parts;
    run.push({time: point.sampled_at, ...parts});
  }
  const exponent = maximum?.exponent ?? 0;
  const ceiling = [1, 2, 5, 10].find(n => n >= (maximum?.mantissa ?? 1));
  function tickLabel(fraction) {
    if (fraction === 0) return "0";
    const scaled = ceiling * fraction;
    if (exponent >= -2 && exponent <= 3) return String(Number((scaled * 10 ** exponent).toPrecision(6)));
    const [coefficient, shift] = scaled.toExponential().split("e");
    return coefficient + "e" + (exponent + Number(shift));
  }
  const gradient = svgElement("linearGradient", {id: "history-fill", x1: "0%", y1: "0%", x2: "0%", y2: "100%"});
  for (const [offset, opacity] of [["0%", .46], ["56%", .21], ["100%", .025]]) {
    gradient.append(svgElement("stop", {offset, "stop-opacity": opacity}));
  }
  const content = document.createDocumentFragment();
  const clip = svgElement("clipPath", {id: "history-window"},
    svgElement("rect", {x: left, y: 0, width: right - left, height}));
  content.append(svgElement("title", {}, title), svgElement("defs", {}, gradient, clip));
  for (let i = 0; i <= 4; i++) {
    const y = bottom - i / 4 * (bottom - top);
    content.append(svgElement("g", {"data-value-tick": ""},
      svgElement("line", {x1: left, x2: right, y1: y, y2: y}),
      svgElement("text", {x: left - 6, y: y + 3, "text-anchor": "end"}, tickLabel(i / 4))));
  }
  for (const time of (right - left < 340 ? [-60, -30, 0] : [-60, -45, -30, -15, 0])) {
    content.append(svgElement("g", {"data-time-tick": ""},
      svgElement("text", {x: x(time + rightEdge), y: height - 3, "text-anchor": "middle"},
        (time < 0 ? "−" + -time : "0") + "s")));
  }
  // Move only the series between observations entering/leaving the window.
  // The clipping rectangle, axes and gradient stay fixed in screen space.
  const plot = svgElement("g", {});
  for (const segment of runs) {
    if (segment.at(-1).time < since || segment[0].time > rightEdge) continue;
    const points = segment.map(point => ({
      x: x(point.time),
      y: point.mantissa === 0 ? bottom :
        bottom - (bottom - top) * (point.mantissa / ceiling) * 10 ** (point.exponent - exponent),
    }));
    if (points.length === 1) {
      plot.append(svgElement("circle", {"data-point": "", cx: points[0].x, cy: points[0].y, r: 3}));
    } else {
      const d = historyCurve(points);
      const area = d + " L " + points.at(-1).x.toFixed(2) + " " + bottom + " L " + points[0].x.toFixed(2) + " " + bottom + " Z";
      plot.append(svgElement("path", {"data-area": "", d: area, fill: "url(#history-fill)"}),
        svgElement("path", {"data-curve": "", d}));
    }
  }
  content.append(svgElement("g", {"clip-path": "url(#history-window)"}, plot));
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  svg.replaceChildren(content);
  return {plot, rightEdge, pixelsPerSecond: (right - left) / 60,
    expiresAt: first < 0 ? Infinity : history[first].sampled_at + 60,
    revealsAt: history.find(point => point.sampled_at > rightEdge)?.sampled_at ?? Infinity};
}

/** Own the selected model id, theme and current complete frame of one page. */
class Dashboard {
  constructor(page, feed) {
    this.page = page;
    this.win = page.defaultView;
    this.feed = feed;
    this.dashboard = page.getElementById("dashboard");
    this.selected = null;
    this.visibleModels = [];
    this.frame = null;
    this.clock = null;
    this.histories = new Map();
    this.animation = null;
    this.closed = false;
  }

  /** Takes over from the boot loader and binds one subscription, selection
   * and theme to this document. Leaving or losing the stream retires the view.
   */
  start() {
    if (this.events) return;
    this.events = new AbortController();
    const options = {signal: this.events.signal};
    this.tracks = Object.fromEntries(Array.from(this.dashboard.querySelectorAll("[data-list-body]"),
      node => [node.dataset.listBody, node]));
    this.win.addEventListener("pagehide", () => this.end(), options);
    this.page.addEventListener("visibilitychange", () => {
      if (this.feed.setVisible(!this.page.hidden)) {
        this.dashboard.hidden = true;
        this.byId("snapshot-wait").hidden = false;
      }
      if (!this.closed && this.frame && !this.page.hidden && !this.dashboard.hidden) {
        this.updateTime();
        this.updateHistory();
      }
      this.scheduleAnimation();
    }, options);
    this.byId("theme").addEventListener("click", () => this.toggleTheme(), options);
    this.tracks.model.addEventListener("click", event => {
      const button = event.target.closest("[data-model-id]");
      if (button) this.select(button.dataset.modelId);
    }, options);
    this.page.addEventListener("keydown", event => this.handleKey(event), options);
    this.observer = new ResizeObserver(() => {
      if (this.frame && !this.dashboard.hidden) this.render();
    });
    for (const track of Object.values(this.tracks)) this.observer.observe(track);
    this.observer.observe(this.byId("detail"));
    this.feed.start((frame, at, utc) => this.install(frame, at, utc), () => this.end(),
      waiting => { this.byId("snapshot-wait").hidden = !waiting; });
    this.feed.setVisible(!this.page.hidden);
  }

  byId(id) { return this.page.getElementById(id); }

  install(frame, at, utc) {
    if (this.closed) return;
    this.frame = frame;
    this.utcAt = utc;
    this.receivedAt = at;
    if (!this.clock) this.clock = new HistoryWindowClock(frame.published_at, at);
    else this.clock.publish(frame.published_at, at);
    this.objects = new Map();
    const histories = new Map();
    for (const obj of frame.snapshot.objects) {
      this.objects.set(obj.key.collector + "/" + obj.key.object_id, obj);
      if (obj.key.collector === "vllm") {
        histories.set(obj.key.object_id,
          historyWithBoundary(this.histories.get(obj.key.object_id) ?? [], obj.history, frame.published_at));
      }
    }
    this.histories = histories;
    this.cards = frame.snapshot.objects.filter(obj => obj.key.collector === "gpu");
    this.gpus = gpuAssignments(this.cards, frame.metadata.models);
    this.dashboard.hidden = false;
    this.byId("loading").hidden = true;
    this.render();
    if (this.timer === undefined) {
      this.timer = this.win.setInterval(() => {
        if (!this.page.hidden && !this.dashboard.hidden) this.updateTime();
      }, 1000);
    }
  }

  end() {
    if (this.closed) return;
    this.closed = true;
    this.scheduleAnimation();
    this.histories.clear();
    this.graph = null;
    this.feed.close();
    this.events.abort();
    this.observer.disconnect();
    this.win.clearInterval(this.timer);
    this.byId("snapshot-wait").hidden = true;
    this.byId("loading").hidden = true;
    this.dashboard.hidden = true;
    this.byId("error").hidden = false;
  }

  handleKey(event) {
    if (this.dashboard.hidden || event.defaultPrevented || event.altKey || event.shiftKey ||
        event.metaKey || event.ctrlKey || event.target.isContentEditable ||
        event.target.closest?.("input, textarea, select")) return;
    if (event.key === "t") {
      event.preventDefault();
      this.toggleTheme();
    } else if (["ArrowDown", "ArrowUp"].includes(event.key) && this.visibleModels.length) {
      event.preventDefault();
      const next = this.visibleModels.indexOf(this.selected) + (event.key === "ArrowDown" ? 1 : -1);
      if (this.visibleModels[next] !== undefined) this.select(this.visibleModels[next], true);
    }
  }

  select(id, keyboard = false) {
    if (id === this.selected || !this.visibleModels.includes(id)) return;
    this.selected = id;
    this.render(keyboard);
  }

  toggleTheme() {
    const hologram = this.dashboard.dataset.theme === "moonlight";
    this.dashboard.dataset.theme = hologram ? "hologram" : "moonlight";
    const label = "Theme: " + (hologram ? "Hologram" : "Moonlight");
    const button = this.byId("theme");
    button.textContent = label + " ↔";
    button.setAttribute("aria-label", label + ". Switch to " + (hologram ? "Moonlight" : "Hologram"));
    button.setAttribute("aria-pressed", String(hologram));
  }

  render(focusSelected = false) {
    const focused = this.page.activeElement?.dataset.modelId;
    const {metadata} = this.frame;
    const host = element("span", "ellipsis", metadata.hostname, element("span", "dim", " / " + metadata.system));
    host.title = metadata.hostname + " / " + metadata.system;
    this.time = element("time", "dim");
    this.time.title = "Estimated host UTC at connection";
    this.byId("hostline").replaceChildren(host, this.time);
    this.renderHost();
    this.renderStorage(metadata.mount_points);
    this.renderDocker(metadata.containers);
    this.renderModels(metadata.models, focused, focusSelected);
    this.renderGpus();
    this.renderDetail(metadata.models.find(model => model.id === this.selected));
    this.updateTime();
    this.updateHistory();
    this.scheduleAnimation();
  }

  renderHost() {
    const panel = this.byId("host");
    const content = [panel.querySelector("legend")];
    for (const key of ["cpu", "ram"]) {
      const source = this.objects.get("host/" + key);
      const usage = valueOf(source, key + "_percent");
      const name = key.toUpperCase();
      const label = element("span", "", name);
      if (source?.stale) label.append(" ", statusNode("STALE"));
      const amount = key === "cpu" ? (usage === null ? missing : element("span", "", tenths.format(usage), element("span", "dim", " %"))) :
        capacityLabel(valueOf(source, "ram_used_bytes"), valueOf(source, "ram_total_bytes"), "ram");
      content.push(element("div", "resource", element("div", "pair", label, element("strong", "", amount)),
        meter(name + " utilization", usage, 20)));
    }
    panel.replaceChildren(...content);
  }

  renderStorage(mounts) {
    const panel = this.byId("storage");
    const content = [panel.querySelector("legend")];
    if (!mounts.length) content.push(element("span", "dim", "No mount points configured"));
    mounts.forEach((mount, i) => {
      const source = this.objects.get("storage/mount-" + i);
      const path = element("span", "ellipsis", mount);
      path.title = mount;
      const usage = valueOf(source, "used_percent");
      const capacity = capacityLabel(valueOf(source, "used_bytes"), valueOf(source, "total_bytes"), "storage");
      const amount = element("span", "dim", capacity, " · ",
        element("strong", "storage-percent", usage === null ? missing : tenths.format(usage) + "%"));
      if (source?.stale) amount.append(" ", statusNode("STALE"));
      content.push(element("div", "pair", path, amount));
    });
    panel.replaceChildren(...content);
  }

  renderDocker(containers) {
    const track = this.tracks.docker;
    const entries = containers.map(({id}) => {
      const source = this.objects.get("docker/" + id);
      const state = source?.stale ? "STALE" : numberText(valueOf(source, "state"));
      const label = element("span", "ellipsis", id);
      label.title = id;
      const status = element("span", "docker-state " + (state === "Running" ? "accent" : state === "STALE" ? "warn" : ""), state);
      const row = element("div", "docker-row", label, status);
      row.dataset.containerId = id;
      return [row];
    });
    const visible = fitRows(track, entries);
    const legend = this.byId("docker").querySelector("legend");
    legend.textContent = visible === entries.length ? "DOCKER" : "DOCKER / " + entries.length;
    if (!entries.length) track.append(element("span", "dim", "No containers configured"));
  }

  renderModels(models, focused, focusSelected) {
    const track = this.tracks.model;
    const heading = this.byId("models").querySelector("h2");
    heading.textContent = "MODELS / " + models.length;
    const candidates = this.win.matchMedia("(max-width: 600px)").matches ? models.slice(0, 3) : models;
    // A native click can span a publication. Keep the same connected button
    // and its hit-tested descendants for every model still in the visible prefix.
    const existing = new Map(Array.from(track.children, node => [node.dataset.modelId, node]));
    const entries = candidates.map((model, index) => {
      const button = existing.get(model.id) ?? modelButton(model);
      updateModelButton(button, this.objects.get("vllm/" + model.id));
      const current = track.children[index] ?? null;
      if (button !== current) track.insertBefore(button, current);
      return [button];
    });
    while (track.children.length > entries.length) track.lastElementChild.remove();
    const count = trimRows(track, entries);
    this.visibleModels = candidates.slice(0, count).map(model => model.id);
    if (!this.visibleModels.includes(this.selected)) this.selected = this.visibleModels[0] ?? null;
    if (!models.length) track.append(element("span", "dim", "No models configured"));
    for (const [button] of entries.slice(0, count)) {
      button.setAttribute("aria-pressed", String(button.dataset.modelId === this.selected));
    }
    if (focused !== undefined || focusSelected) {
      const target = !focusSelected && this.visibleModels.includes(focused) ? focused : this.selected;
      (entries.find(([node]) => node.dataset.modelId === target)?.[0] ?? heading).focus({preventScroll: true});
    }
  }

  renderGpus() {
    const track = this.tracks.gpu;
    const inventory = this.objects.get("gpu_inventory/local");
    const count = valueOf(inventory, "device_count");
    const legend = this.byId("gpu").querySelector("legend");
    legend.replaceChildren("GPU FABRIC ", element("span", "dim", "/ " + numberText(count) + " DEVICES"));
    if (inventory?.stale) legend.append(" ", statusNode("STALE"));
    const linked = this.gpus.byModel.get(this.selected);
    const entries = this.cards.map((card, i) => {
      const row = gpuRow(card, linked);
      const header = this.gpus.headers.get(i);
      if (!header) return [row];
      return [element("div", "group-label", element("span", "", header[0]),
        element("span", "secondary", header[1])), row];
    });
    fitRows(track, entries);
    if (!entries.length) {
      const empty = !inventory?.stale && inventory?.sampled_at != null && count !== null && Number(count) === 0;
      track.append(element("span", "dim", empty ? "No NVIDIA GPUs" : missing));
    }
  }

  renderDetail(model) {
    const detail = this.byId("detail");
    this.graph = null;
    if (!model) {
      detail.replaceChildren();
      return;
    }
    const source = this.objects.get("vllm/" + model.id);
    const chat = model.type === "chat";
    const name = element("h2", "ellipsis", model.served_model_name);
    name.title = model.served_model_name;
    const status = modelStatus(source);
    const title = element("div", "pair", name, statusNode(status));
    const running = element("div", "queue", element("span", "queue-label", "RUNNING"), queueCounter(source, "running"),
      element("span", "queue-caption", "Total ", queueCounter(source, "total")));
    const queue = valueOf(source, "queue_seconds");
    const waitingValue = queueCounter(source, "waiting");
    if (status === "QUEUED") waitingValue.classList.add("warn");
    const waiting = element("div", "queue", element("span", "queue-label", "WAITING"), waitingValue,
      element("span", "queue-caption", chat ? "Avg queue " + (queue === null ? missing : numberText(queue) + " s") : "Unit: seq"));
    const fields = chat ? [["decode_rate", "DECODE", "tok/s"], ["prefill_rate", "PREFILL", "tok/s"], ["ttft_seconds", "TTFT", "s"]] :
      [["rate", "RATE", "seq/s"], ["queue_seconds", "AVG QUEUE", "s"], ["latency_seconds", "AVG LATENCY", "s"]];
    fields.push(["kv_cache_percent", "KV CACHE", "%"]);
    const grid = element("div", "metric-grid");
    for (const [field, label, unit] of fields) {
      const caption = element("span", "", label), suffix = element("span", "", unit);
      caption.dataset.metricLabel = "";
      suffix.dataset.metricUnit = "";
      const value = metricSlot(source, field, field !== "kv_cache_percent" || chat);
      value.classList.add("metric-value");
      const slot = element("div", "", element("span", "metric-heading", caption, " / ", suffix), value);
      slot.dataset.metricSlot = "";
      grid.append(slot);
    }
    const [field, label, unit] = fields[0];
    const latest = valueOf(source, field);
    const heading = label + " HISTORY | " + unit;
    const latestText = latest === null ? missing : numberText(latest) + " " + unit;
    const svg = svgElement("svg", {class: "history-svg", role: "img"});
    this.graph = {svg, history: this.histories.get(model.id) ?? [], field,
      title: model.name + " · " + heading + " · " + latestText};
    detail.replaceChildren(title, element("div", "detail-route", ":" + model.effective_port), element("div", "queues", running, waiting),
      grid, element("div", "history-block", element("div", "history-heading", heading, element("strong", "", latestText)), svg));
    for (const number of grid.querySelectorAll("[data-metric]")) {
      fitMetricValue(number, valueOf(source, number.dataset.metric));
    }
  }

  updateTime() {
    const now = this.win.performance.now();
    const utc = this.utcAt === null ? null : new Date(this.utcAt + now - this.receivedAt);
    this.time.textContent = utc ? utc.toISOString().slice(11, 19) + " UTC" : missing;
  }

  scheduleAnimation() {
    if (this.closed || this.page.hidden || this.dashboard.hidden || !this.graph) {
      if (this.animation !== null) this.win.cancelAnimationFrame(this.animation);
      this.animation = null;
      return;
    }
    if (this.animation !== null) return;
    this.animation = this.win.requestAnimationFrame(() => {
      this.animation = null;
      if (!this.closed && !this.page.hidden && !this.dashboard.hidden) this.updateHistory();
      this.scheduleAnimation();
    });
  }

  updateHistory() {
    const now = this.win.performance.now();
    const edge = this.clock.rightEdge(now);
    if (this.graph) {
      const {svg, history, field, title} = this.graph;
      const drawing = this.graph.drawing;
      if (!drawing || edge > drawing.expiresAt || edge >= drawing.revealsAt) {
        this.graph.drawing = drawHistory(svg, history, field, edge, title);
      } else {
        const offset = (drawing.rightEdge - edge) * drawing.pixelsPerSecond;
        drawing.plot.setAttribute("transform", "translate(" + offset + " 0)");
      }
    }
  }
}
