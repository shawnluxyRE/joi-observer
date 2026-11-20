/* Observe geometry in CSS pixels, allowing the renderer to transform its SVG groups. */
function curveReader(path) {
  const length = path.getTotalLength();
  const matrix = path.getScreenCTM(), point = distance => path.getPointAtLength(distance).matrixTransform(matrix);
  const start = point(0), end = point(length);
  const forwards = start.x < end.x;
  const low = forwards ? start : end, high = forwards ? end : start;
  function at(fraction) {
    const x = low.x + fraction * (high.x - low.x);
    let left = 0, right = length;
    for (let i = 0; i < 18; i++) {
      const middle = (left + right) / 2;
      if (point(forwards ? middle : length - middle).x < x) left = middle;
      else right = middle;
    }
    const distance = (left + right) / 2;
    return point(forwards ? distance : length - distance);
  }
  return {low, high, at};
}

function timeTickX(svg, seconds) {
  const label = [...svg.querySelectorAll("[data-time-tick] text")].find(el =>
    Number(el.textContent.trim().replace("−", "-").replace(/\s*s$/, "")) === seconds);
  requireThat(shown(label), "visible labelled time tick " + seconds);
  const origin = label.getStartPositionOfChar(0);
  const anchor = new label.ownerDocument.defaultView.DOMPoint(origin.x, origin.y);
  const align = label.ownerDocument.defaultView.getComputedStyle(label).textAnchor;
  if (align === "middle") anchor.x += label.getComputedTextLength() / 2;
  if (align === "end") anchor.x += label.getComputedTextLength();
  return anchor.matrixTransform(label.getScreenCTM()).x;
}

function sampleRuler(page, maximum) {
  const svg = page.get("#detail svg");
  const left = timeTickX(svg, -60), right = timeTickX(svg, 0);
  const ticks = [...svg.querySelectorAll("[data-value-tick]")].map(group => {
    const label = group.querySelector("text"), grid = group.querySelector("line");
    requireThat(shown(label) && grid, "labelled throughput gridline");
    const value = Number(label.textContent.trim());
    const y = grid.getPointAtLength(0).matrixTransform(grid.getScreenCTM()).y;
    requireThat(Number.isFinite(value) && Math.abs(box(label).top + box(label).height/2 - y) <= box(label).height,
      "throughput label is displayed beside its gridline");
    return {value, y};
  }).sort((a,b) => a.value - b.value);
  const zero = ticks[0], top = ticks.at(-1);
  requireThat(ticks.length >= 2 && zero.value === 0 && top.value >= maximum && top.y < zero.y && right > left,
    "axes cover the input's time and throughput ranges");
  // Receipt falls between enqueue and the first live paint. Both clocks below
  // belong to this iframe, bounding the continuous motion since receipt.
  const elapsed = Math.max(0, page.win.performance.now() - page.firstEnqueue);
  return function measured(point, time, value) {
    const x0 = left + (time - 939) / 60 * (right-left);
    const y = zero.y + value / top.value * (top.y-zero.y);
    requireThat(point.x >= x0 - elapsed/1000*(right-left)/60 - 1 && point.x <= x0 + 1 &&
      Math.abs(point.y - y) <= 1.25, "measured point aligns with independent axis labels");
  };
}

function checkModelHistory(page, values, unit) {
  const svg = page.get("#detail svg");
  const curves = svg?.querySelectorAll("[data-curve]");
  requireThat(curves?.length === 1 && visiblyPainted(page, curves[0], "stroke"), "selected model history is drawn");
  const heading = page.get("#detail").innerText.replace(/\s+/g, " ").match(/HISTORY\s*\|\s*(tok\/s|seq\/s)/i);
  requireThat(heading?.[1] === unit, "selected model history uses " + unit);
  const ruler = sampleRuler(page, Math.max(...values));
  const line = curveReader(curves[0]);
  ruler(line.low, 993, values[0]);
  ruler(line.high, 999, values[1]);
}

function checkSampleCoordinates(page, curves) {
  const svg = page.get("#detail svg");
  const measured = sampleRuler(page, 7);
  for (const [i, samples] of [[[942,0],[945,2]], [[954,0],[963,4],[969,4],[975,2],[984,7]]].entries()) {
    for (const [time, value] of samples) {
      const fraction = (time-samples[0][0]) / (samples.at(-1)[0]-samples[0][0]);
      measured(curves[i].at(fraction), time, value);
    }
  }
  const dot = svg.querySelector("[data-point]");
  measured({x:box(dot).left+box(dot).width/2, y:box(dot).top+box(dot).height/2}, 999, 7);
}

function visiblyPainted(page, el, paint) {
  const style = page.win.getComputedStyle(el);
  if (style[paint] === "none" || style[paint] === "transparent" || /^rgba\(.*,\s*0\)$/.test(style[paint]) ||
      Number(style[paint + "Opacity"]) <= 0) return false;
  if (paint === "stroke" && parseFloat(style.strokeWidth) <= 0) return false;
  for (let parent = el; parent; parent = parent.parentElement) {
    const ancestor = page.win.getComputedStyle(parent);
    if (ancestor.display === "none" || ancestor.visibility !== "visible" || Number(ancestor.opacity) <= 0) return false;
  }
  return true;
}

function checkSmoothSamples(curve) {
  // (954,0), (963,4), (969,4), (975,2), (984,7).
  // The measured endpoints fix the two linear axes without prescribing a plot size.
  const {low, high, at} = curve;
  requireThat(high.x > low.x && high.y < low.y, "increasing time and throughput axes");
  const valueAt = time => (low.y - at((time - 954) / 30).y) * 7 / (low.y - high.y);
  const samples = [[954,0], [963,4], [969,4], [975,2], [984,7]];
  for (const [time, value] of samples) {
    requireThat(Math.abs(valueAt(time) - value) < 0.05, "curve passes through every measured point");
  }
  for (let i = 1; i < samples.length; i++) {
    const [t0, v0] = samples[i-1], [t1, v1] = samples[i];
    let previous = v0;
    for (let step = 1; step < 12; step++) {
      const y = valueAt(t0 + (t1 - t0) * step / 12);
      requireThat(y >= Math.min(v0, v1) - 0.04 && y <= Math.max(v0, v1) + 0.04 &&
        (y - previous) * Math.sign(v1 - v0) >= -0.04,
        "no overshoot at an extremum or along a plateau");
      previous = y;
    }
  }
  // At a smooth minimum both tangents become horizontal. Try successively
  // smaller neighborhoods so different shape-preserving splines qualify.
  // A polyline retains 100% of its two incident chord slopes at every scale.
  const bottom = valueAt(975);
  requireThat([0.1, 0.05, 0.025, 0.0125].some(f =>
    (valueAt(975 - 6*f) - bottom) / (2*f) < 0.75 &&
    (valueAt(975 + 9*f) - bottom) / (5*f) < 0.75), "rounded turn through the minimum");
}

function checkChartPaint(page, hue) {
  const svg = page.get("#detail svg[role=img]");
  const strokes = svg.querySelectorAll("[data-curve]");
  const areas = svg.querySelectorAll("[data-area]");
  requireThat(strokes.length > 0 && areas.length > 0, "the theme paints the curve and its area");
  for (const stroke of strokes) {
    requireThat(visiblyPainted(page, stroke, "stroke") && page.win.getComputedStyle(stroke).stroke === hue,
      "the visible line follows the theme");
  }
  for (const area of areas) {
    const style = page.win.getComputedStyle(area), paint = /url\(["']?[^#]*#([^"')]+)["']?\)/.exec(style.fill);
    const gradient = paint && page.doc.getElementById(paint[1]);
    requireThat(gradient?.localName === "linearGradient" && Number(style.opacity) > 0 &&
      Number(style.fillOpacity) > 0, "visible area uses its gradient");
    // Only the effective paint direction matters, including transforms made
    // by the gradient, its object bounding box, and the owning SVG group.
    let transform = area.getScreenCTM();
    if (gradient.gradientUnits.baseVal === 2) {
      const bounds = area.getBBox();
      transform = transform.scale(bounds.width, bounds.height);
    }
    const transforms = gradient.gradientTransform.baseVal;
    for (let j = 0; j < transforms.numberOfItems; j++) transform = transform.multiply(transforms.getItem(j).matrix);
    const direction = new page.win.DOMPoint(gradient.x2.baseVal.value - gradient.x1.baseVal.value,
      gradient.y2.baseVal.value - gradient.y1.baseVal.value, 0, 0).matrixTransform(transform);
    requireThat(direction.y > 0 && Math.abs(direction.x) < 0.001 * direction.y, "gradient runs vertically down");
    const stops = [...gradient.querySelectorAll("stop")].map(s => page.win.getComputedStyle(s));
    requireThat(stops.length >= 2 && stops.every((s, j) => s.stopColor === hue &&
      (!j || Number(s.stopOpacity) < Number(stops[j-1].stopOpacity))), "single-hue fading area");
  }
}

function checkChartGeometry(page) {
  const svg = page.get("#detail svg[role=img]");
  const byPosition = (a, b) => box(a).left - box(b).left;
  const curves = [...svg.querySelectorAll("[data-curve]")].sort(byPosition).map(curveReader);
  const areas = [...svg.querySelectorAll("[data-area]")].sort(byPosition);
  const dots = svg.querySelectorAll("[data-point]");
  requireThat(curves.length === 2 && areas.length === 2 && dots.length === 1 &&
    shown(dots[0]) && visiblyPainted(page, dots[0], "fill"), "two runs and one visible isolated point");
  checkSampleCoordinates(page, curves);
  checkSmoothSamples(curves[1]);
  requireThat(curves[0].high.x < curves[1].low.x, "open gap between measured runs");
  const zero = curves[0].low.y;
  for (const [i, area] of areas.entries()) {
    const curve = curves[i];
    const fillBounds = box(area);
    requireThat(Math.abs(fillBounds.left - curve.low.x) < 1 &&
      Math.abs(fillBounds.right - curve.high.x) < 1 && Math.abs(fillBounds.bottom - zero) < 1,
      "fill spans only its run, down to zero");
    const inverse = area.getScreenCTM().inverse();
    const filled = (x,y) => area.isPointInFill(new page.win.DOMPoint(x,y).matrixTransform(inverse));
    for (const fraction of [0.2, 0.45, 0.75]) {
      const boundary = curve.at(fraction);
      const dy = Math.min(1, (zero - boundary.y) / 3);
      requireThat(dy > 0 && filled(boundary.x, boundary.y + dy) && !filled(boundary.x, boundary.y - dy) &&
        filled(boundary.x, zero - dy), "painted area follows the actual curve and closes at zero");
    }
  }
}

async function checkHistory(page) {
  const svg = () => page.get("#detail svg[role=img]");
  const paths = () => svg().querySelectorAll("[data-curve]");
  const points = () => svg().querySelectorAll("[data-point]");
  const theme = page.get("#theme");
  checkChartPaint(page, "rgb(123, 159, 255)");
  checkChartGeometry(page);
  theme.click();
  await untilShown(() => page.win.getComputedStyle(paths()[0]).stroke === "rgb(125, 223, 255)", "Moonlight chart");
  checkChartPaint(page, "rgb(125, 223, 255)");
  requireThat(svg().textContent.includes("60") && !page.get("#detail button"), "read-only 60 s axis");

  // Sample 942 leaves the window when its right edge passes 1002. Its
  // continuous segment is then clipped at the boundary on an animation frame.
  await untilShown(() => curveReader(paths()[0]).low.x < timeTickX(svg(), -60),
    "oldest point moves outside the clipped window", 4500);
  // The longest continuous segment starts at 954 throughout the scene.
  // Compare its screen pixel even if the axes move.
  const survivingX = () => Array.from(paths(), curveReader)
    .sort((a, b) => (b.high.x - b.low.x) - (a.high.x - a.low.x))[0].low.x;
  const originalPaths = [...paths()], axes = [...svg().querySelectorAll("[data-time-tick], [data-value-tick]")];
  const speed = (timeTickX(svg(), 0) - timeTickX(svg(), -60)) / 60 / 1000;
  const positions = [];
  await new Promise(resolve => {
    function measure() {
      positions.push({x: survivingX(), at: page.win.performance.now()});
      if (positions.at(-1).at - positions[0].at < 450) page.win.requestAnimationFrame(measure);
      else resolve();
    }
    page.win.requestAnimationFrame(measure);
  });
  requireThat(positions.length >= 5, "continuous motion is observed across multiple browser paints");
  for (let i = 1; i < positions.length; i++) {
    const elapsed = positions[i].at - positions[i-1].at;
    const distance = positions[i-1].x - positions[i].x;
    requireThat(distance > 0 && Math.abs(distance - elapsed * speed) < .35,
      "each animation frame moves left at the elapsed-time rate without one-second jumps");
  }
  requireThat(originalPaths.every((path, i) => path === paths()[i]) && axes.every(node => node.isConnected),
    "ordinary animation reuses the painted paths and fixed axes");
  let minimumX = survivingX(), maxRightward = 0, observedFrames = 0, nextPaint;
  function observeMotion() {
    const x = survivingX();
    maxRightward = Math.max(maxRightward, x - minimumX);
    minimumX = Math.min(minimumX, x);
    observedFrames++;
    nextPaint = page.win.requestAnimationFrame(observeMotion);
  }
  // The late sample at 1001 joins the old dot at 999 and needs a wider value
  // label. The same frame still contains the already expired sample at 942.
  nextPaint = page.win.requestAnimationFrame(observeMotion);
  try {
    await page.send(setup.delayed);
    await untilShown(() => page.get("#host").innerText.includes("17.5") && paths().length >= 2,
      "late frame installs its new peak in the second curve");
    await new Promise(resolve => setTimeout(resolve, 1150)); // observe the late anchor over another second
  } finally {
    page.win.cancelAnimationFrame(nextPaint);
  }
  const clip = svg().querySelector("clipPath rect");
  requireThat(clip && Math.abs(new page.win.DOMPoint(clip.x.baseVal.value, 0)
    .matrixTransform(svg().getScreenCTM()).x - timeTickX(svg(), -60)) < 1 && points().length <= 1,
    "expired context stays clipped outside the window");
  requireThat(observedFrames > 1 && maxRightward <= 0.5, "the surviving sample cannot move right on screen");
}

async function checkBufferedHistory(page) {
  await page.send(setup.lines[0]);
  page.get("#detail svg").scrollIntoView({block: "center"});
  const paints = point => {
    const hit = page.doc.elementFromPoint(point.x, point.y + 1);
    return !!hit?.matches("[data-curve], [data-area]");
  };
  for (let publication = 1; publication <= 2; publication++) {
    page.win.clockOffset = publication * 1000;
    await page.send(setup.lines[publication]);
    const svg = page.get("#detail svg"), path = svg.querySelector("[data-curve]");
    const right = timeTickX(svg, 0), left = timeTickX(svg, -60), speed = (right - left) / 60;
    const latest = 1000 + publication;
    requireThat(page.get('[data-metric="decode_rate"]').textContent === (publication === 1 ? "7" : "5"),
      "the latest numeric metric updates immediately while the chart plays one second behind");
    let previousY;
    for (const elapsed of [0, 200, 400, 600, 800, 1000]) {
      page.win.clockOffset = publication * 1000 + elapsed;
      await new Promise(resolve => page.win.requestAnimationFrame(() => page.win.requestAnimationFrame(resolve)));
      const currentPath = page.get("#detail svg [data-curve]");
      const curve = curveReader(currentPath);
      const atTime = time => curve.at((time - 997) / (latest - 997));
      const playback = latest - 1 + elapsed / 1000;
      const tip = atTime(playback);
      requireThat(Math.abs(tip.x - right) < .1 && paints(atTime(playback - .08)),
        "the buffered curve and area reach the fixed right edge with no missing strip");
      requireThat(Math.abs(curve.low.x - (right - (playback - 997) * speed)) < .1,
        "all historical samples use the same one-second delayed time axis");
      requireThat(!paints({x: right + 2, y: tip.y}), "the fixed window clips the received lookahead samples");
      if (previousY !== undefined) requireThat((tip.y - previousY) * (publication === 1 ? -1 : 1) > 0,
        "the right-edge value changes continuously between the real samples");
      previousY = tip.y;
      if (elapsed < 1000) requireThat(path === currentPath, "ordinary playback reuses its SVG path");
    }
  }
  const svg = page.get("#detail svg"), right = timeTickX(svg, 0);
  const displayed = curveReader(svg.querySelector("[data-curve]")).high.x;
  page.get('[data-model-id="m1"]').click();
  page.get('[data-model-id="m0"]').click();
  requireThat(Math.abs(curveReader(page.get("#detail svg [data-curve]")).high.x - displayed) < .1,
    "switching models preserves the shared playback time");
  page.win.clockOffset = 4000;
  await new Promise(resolve => page.win.requestAnimationFrame(() => page.win.requestAnimationFrame(resolve)));
  const tip = curveReader(page.get("#detail svg [data-curve]")).high;
  requireThat(tip.x < right - 2 && !paints({x: right - 1, y: tip.y}),
    "missing new observations remain empty instead of being extrapolated");
  requireThat(page.win.requests.length === 1, "buffered playback uses the original data stream");
}

async function checkChartLifetime(page) {
  const {win, doc, get} = page;
  requireThat(win.pendingPaints.size === 0, "no animation before the first snapshot");
  await page.send(setup.sample);
  requireThat(win.pendingPaints.size === 1, "one animation loop for the live chart");
  await page.send(setup.next);
  get("#theme").click();
  requireThat(win.pendingPaints.size === 1, "publications and theme changes do not multiply animation loops");
  let hidden = true;
  Object.defineProperty(doc, "hidden", {get: () => hidden});
  doc.dispatchEvent(new win.Event("visibilitychange"));
  requireThat(win.pendingPaints.size === 0, "hidden documents cancel their pending animation");
  const plot = get("#detail svg");
  const frozen = plot.innerHTML;
  await new Promise(resolve => setTimeout(resolve, 150));
  requireThat(plot.innerHTML === frozen, "the hidden chart does not animate");
  hidden = false;
  doc.dispatchEvent(new win.Event("visibilitychange"));
  await pause();
  requireThat(win.pendingPaints.size === 1 && plot.innerHTML !== frozen,
    "returning to a healthy document resumes its existing chart");
  win.connection.close();
  await untilShown(() => shown(get("#error")), "EOF closes the animated chart");
  requireThat(win.pendingPaints.size === 0, "failure cancels the pending animation");
  doc.dispatchEvent(new win.Event("visibilitychange"));
  await pause();
  requireThat(win.pendingPaints.size === 0 && win.requests.length === 1 && !shown(get("#dashboard")),
    "visibility cannot restart a failed chart or open a second stream");
}

async function checkLeftBoundary(page) {
  let previousY;
  for (const [index, line] of setup.lines.entries()) {
    page.win.clockOffset = index * 1000;
    await page.send(line);
    const svg = page.get("#detail svg");
    const curves = [...svg.querySelectorAll("[data-curve]")].map(curveReader);
    const main = curves.sort((a, b) => (b.high.x - b.low.x) - (a.high.x - a.low.x))[0];
    const left = timeTickX(svg, -60), right = timeTickX(svg, 0);
    const at = left + (942.5 - (JSON.parse(line).published_at - 61)) / 60 * (right - left);
    const y = main.at((at - main.low.x) / (main.high.x - main.low.x)).y;
    if (previousY !== undefined) requireThat(Math.abs(y - previousY) < .1,
      "a retained curve segment keeps its shape as older points leave");
    previousY = y;
    if (!index) continue;
    if (setup.gap) {
      requireThat(main.low.x > left, "the missing observation at the boundary remains a gap");
    } else {
      requireThat(main.low.x < left, "a real earlier observation supports the boundary interpolation");
    }
    const path = svg.querySelector("[data-curve]");
    const reference = /#([^)]*)/.exec(path.closest("[clip-path]").getAttribute("clip-path"));
    const clip = reference && page.doc.getElementById(reference[1])?.querySelector("rect");
    requireThat(clip, "the curve has an active clipping rectangle");
    const matrix = svg.getScreenCTM(), start = clip.x.baseVal.value;
    requireThat(Math.abs(new page.win.DOMPoint(start, 0).matrixTransform(matrix).x - left) < 1 &&
      Math.abs(new page.win.DOMPoint(start + clip.width.baseVal.value, 0).matrixTransform(matrix).x - right) < 1,
      "visible curve is clipped to exactly sixty seconds");
  }
  requireThat(page.win.requests.length === 1, "boundary rendering retains the one stream");
}

// Follow one real SVG dot for a whole minute, including a host timestamp
// divisible by 60. A cycling cursor would leave it in place or wrap it.
async function checkScrollingWindow(page) {
  let previousX = null;
  for (const [seconds, publication] of setup.steps) {
    page.win.clockOffset = 1000 * seconds;
    await page.send(publication);
    if (!seconds) {
      requireThat(!page.get("#detail [data-point]"), "the first new observation waits for the playback buffer");
      page.win.clockOffset = 1000;
      await new Promise(resolve => page.win.requestAnimationFrame(() => page.win.requestAnimationFrame(resolve)));
    }
    const svg = page.get("#detail svg");
    requireThat(shown(svg), "the chart stays live on one document");
    const left = timeTickX(svg, -60), right = timeTickX(svg, 0);
    const dot = svg.querySelector("[data-point]");
    const playbackSeconds = seconds ? seconds - 1 : 0;
    if (playbackSeconds <= 60) {
      requireThat(shown(dot), "the original observation remains visible for the full window");
      const x = box(dot).left + box(dot).width / 2;
      requireThat(Math.abs(x - (right - playbackSeconds / 60 * (right - left))) <= 1.25,
        "a retained observation moves from the right edge toward the left by elapsed time");
      if (previousX !== null) requireThat(x < previousX, "the same observation moves left on each step");
      previousX = x;
    } else {
      requireThat(!dot, "the expired observation has left the plot");
    }
    if (seconds > 0) {
      const curve = svg.querySelector("[data-curve]");
      requireThat(curve && Math.abs(curveReader(curve).high.x - (right + (right - left) / 60)) <= 1.25,
        "the newest received sample stays one second ahead of playback, behind the window clip");
    }
  }
  requireThat(page.win.requests.length === 1, "scrolling uses only the original stream");
}
