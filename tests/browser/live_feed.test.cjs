/* Run with node --test. fetch, time, and every byte of the stream are local. */
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");

const source = readFileSync(path.join(__dirname, "../../src/joi_observer/web/static/dashboard.js"), "utf8");
const {LiveFeed, HistoryWindowClock} = vm.runInNewContext(source + "\n({LiveFeed, HistoryWindowClock})", {
  document: {addEventListener() {}}, performance, setTimeout, clearTimeout,
  TextDecoder, TextDecoderStream, AbortController, AbortSignal, ReadableStream, Response, URL, console,
});
const encoder = new TextEncoder();
const nextTurn = () => new Promise(resolve => setImmediate(resolve));
const date = "Tue, 17 Nov 2026 03:04:05 GMT";

function frame(sequence, published = 99) {
  const data = {
    protocol_version: 1, instance_id: "instance", config_revision: "cfg", sequence: 1,
    published_at: published, metadata: {hostname: "风扇", system: "Ubuntu", mount_points: [],
      containers: [], models: []}, snapshot: {revision: 4, objects: [{
        key: {collector: "host", object_id: "cpu"}, metrics: [{
          name: "cpu_percent", unit: "%", applicable: true, value: {integer: "0"},
        }], sampled_at: 99, stale: false, history: [],
      }]},
  };
  return JSON.stringify(data).replace('"sequence":1', '"sequence":' + sequence) + "\n";
}

function rig({status = 200, headers = {Date: date}, holdHeaders = false, sentAt = "99",
              redirected = false} = {}) {
  let time = 200;
  let writer;
  let cancelled = false;
  let releaseHeaders;
  const held = new Promise(resolve => { releaseHeaders = resolve; });
  const timers = new Map();
  const stream = new ReadableStream({
    start(controller) { writer = controller; },
    cancel() { cancelled = true; },
  });
  const requests = [], frames = [], failures = [], waiting = [];
  const feed = new LiveFeed({
    fetcher: async (url, options) => {
      requests.push([url, options]);
      if (holdHeaders) await held;
      if (redirected && options.redirect === "error") throw new TypeError("redirect rejected");
      const responseHeaders = {"Content-Type": "application/x-ndjson", ...headers};
      if (sentAt !== null) responseHeaders["X-Joi-Sent-At"] = sentAt;
      return new Response(stream, {status, headers: responseHeaders});
    },
    now: () => time,
    schedule(cb, ms) { const token = {}; timers.set(token, {at: time + ms, cb}); return token; },
    cancel(token) { timers.delete(token); },
  });
  function advance(ms, dispatchTimers = true) {
    time += ms;
    if (!dispatchTimers) return;
    for (const [key, {at, cb}] of [...timers]) {
      if (at <= time && timers.delete(key)) cb();
    }
  }
  feed.start((envelope, received, utc) => frames.push({envelope, received, utc}),
             () => failures.push(time), visible => waiting.push(visible));
  return {feed, requests, frames, failures, writer, advance, releaseHeaders,
    timers, stream, waiting, cancelled: () => cancelled};
}

test("UTF-8 fragments and coalesced frames preserve integer tags, duplicates in JS Number and UTC", async () => {
  const r = rig();
  await nextTurn();
  const line = encoder.encode(frame("9007199254740992"));
  const split = line.indexOf(0xe9) + 1; // first byte of 风
  r.writer.enqueue(line.slice(0, split));
  await nextTurn();
  assert.equal(r.frames.length, 0);
  r.advance(230);
  const second = encoder.encode(frame("9007199254740993"));
  r.writer.enqueue(new Uint8Array([...line.slice(split), ...second]));
  await nextTurn();
  assert.equal(r.frames.length, 2);
  for (const {envelope, received, utc} of r.frames) {
    assert.equal(envelope.metadata.hostname, "风扇");
    assert.equal(envelope.snapshot.objects[0].metrics[0].value.integer, "0");
    assert.equal(received, 430);
    assert.equal(utc, Date.parse(date) + 230);
  }
  assert.deepEqual(r.requests.map(([url]) => url), ["/api/live"]);
  r.writer.close();
  await nextTurn();
  r.advance(30000);
  assert.equal(r.failures.length, 1);
  assert.equal(r.requests.length, 1);
});

test("a redirect fails the single same-origin fetch before following its destination", async () => {
  const r = rig({redirected: true});
  await nextTurn();
  assert.equal(r.requests.length, 1);
  assert.equal(r.requests[0][0], "/api/live");
  assert.equal(r.requests[0][1].mode, "same-origin");
  assert.equal(r.requests[0][1].redirect, "error");
  assert.equal(r.failures.length, 1);
  assert.equal(r.frames.length, 0);
});

for (const sentAt of [null, "NaN", "-1", "17, 18"]) {
  test(`missing or invalid monotonic header (${sentAt}) terminates the response`, async () => {
    const r = rig({sentAt});
    await nextTurn();
    assert.equal(r.failures.length, 1);
    assert.equal(r.frames.length, 0);
  });
}

for (const recover of [false, true]) {
  test(`progressively delayed records cannot renew the last fresh deadline (catch-up=${recover})`, async () => {
    const r = rig();
    const deliver = async (seq, published) => {
      r.writer.enqueue(encoder.encode(frame(seq, published)));
      await nextTurn();
    };
    await nextTurn();
    await deliver(1, 99);
    // Fresh at 4 s lag, stale at almost 6 s lag; bytes keep arriving.
    r.advance(6000);
    await deliver(2, 101);
    r.advance(4000);
    await deliver(3, 103);
    assert.deepEqual(r.frames.map(f => f.envelope.published_at), [99, 101]);
    assert.equal(r.failures.length, 0);
    assert.deepEqual(r.waiting, [true]);
    r.advance(6000);
    await deliver(4, recover ? 115 : 106);
    r.advance(2000);
    assert.deepEqual(r.frames.map(f => f.envelope.published_at), recover ? [99,101,115] : [99,101]);
    assert.equal(r.failures.length, Number(!recover));
    assert.deepEqual(r.waiting, recover ? [true,false] : [true]);
    assert.equal(r.requests.length, 1);
    r.feed.close();
  });
}

test("an old first record cannot paint or reset the fetch deadline; a fresh record can join in time", async () => {
  const r = rig({sentAt: "105"});
  await nextTurn();
  r.writer.enqueue(encoder.encode(frame(1, 99)));
  await nextTurn();
  assert.equal(r.frames.length, 0);
  r.advance(1000);
  r.writer.enqueue(encoder.encode(frame(2, 106)));
  await nextTurn();
  assert.deepEqual(r.frames.map(f => f.envelope.published_at), [106]);
  assert.equal(r.failures.length, 0);
  assert.equal(r.requests.length, 1);
  r.feed.close();
});

test("equal publication times do not keep the stream alive; unchanged metrics can still be fresh", async () => {
  const r = rig();
  await nextTurn();
  r.writer.enqueue(encoder.encode(frame(1)));
  await nextTurn();
  r.advance(1000);
  r.writer.enqueue(encoder.encode(frame(2, 100)));
  await nextTurn();
  assert.equal(r.frames.at(-1).envelope.published_at, 100);
  r.advance(1000);
  const update = JSON.parse(frame(3, 100));
  update.snapshot.revision++;
  update.snapshot.objects[0].metrics[0].value = {integer:"25"};
  r.writer.enqueue(encoder.encode(JSON.stringify(update) + "\n"));
  await nextTurn();
  assert.equal(r.frames.at(-1).envelope.snapshot.objects[0].metrics[0].value.integer, "25");
  r.advance(11000);
  assert.equal(r.failures.length, 1);
});

test("hiding a foreground page after its absolute deadline cannot revive the stream", async () => {
  const r = rig();
  await nextTurn();
  r.writer.enqueue(encoder.encode(frame(1)));
  await nextTurn();
  r.advance(12001, false); // The foreground timeout callback is still queued.
  r.feed.setVisible(false);
  r.feed.setVisible(true);
  if (!r.cancelled()) {
    r.writer.enqueue(encoder.encode(frame(2, 111)));
    await nextTurn();
  }
  assert.deepEqual(r.frames.map(f => f.envelope.published_at), [99]);
  assert.equal(r.failures.length, 1);
  assert.equal(r.requests.length, 1);
  assert.equal(r.cancelled(), true);
});

for (const localInterval of [1250, 750]) {
  test(`clock rate differences do not accumulate into the window (local interval ${localInterval} ms)`, () => {
    // Exaggerate the rate difference over six normal publications instead of running for days.
    const clock = new HistoryWindowClock(100.25, 0);
    let last = clock.rightEdge(0);
    for (let n = 1; n <= 6; n++) {
      const at = n * localInterval;
      const before = clock.rightEdge(at - 1);
      assert.ok(before >= last);
      clock.publish(100.25 + n, at);
      last = clock.rightEdge(at);
      assert.ok(last >= before);
      assert.equal(last, 100.25 + n);
    }
    const late = new HistoryWindowClock(100, 0);
    assert.equal(late.rightEdge(4000), 104);
    late.publish(101, 4000);
    assert.equal(late.rightEdge(4000), 104);
    assert.equal(late.rightEdge(5500), 104);
    assert.equal(late.rightEdge(8100), 105);
  });
}

for (const afterFirst of [false, true]) {
  test(`incomplete bytes never extend the ${afterFirst ? "next" : "first"} complete-record deadline`, async () => {
    const r = rig({headers: {}});
    await nextTurn();
    if (afterFirst) {
      r.advance(1000);
      r.writer.enqueue(encoder.encode(frame("1")));
      await nextTurn();
      assert.equal(r.frames.length, 1);
      assert.equal(r.frames[0].utc, null);
    }
    r.advance(11999);
    r.writer.enqueue(encoder.encode('{"protocol_version":'));
    await nextTurn();
    assert.equal(r.failures.length, 0);
    r.advance(1);
    await nextTurn();
    assert.equal(r.failures.length, 1);
    r.advance(36000);
    assert.equal(r.requests.length, 1);
    assert.equal(r.frames.length, Number(afterFirst));
    r.feed.close();
    r.feed.close();
    assert.equal(r.failures.length, 1);
  });
}

test("no response headers within the first deadline ends the request irrevocably", async () => {
  const r = rig({holdHeaders: true});
  await nextTurn();
  r.advance(12000);
  await nextTurn();
  assert.equal(r.failures.length, 1);
  r.writer.enqueue(encoder.encode(frame("1")));
  r.releaseHeaders();
  await nextTurn();
  assert.equal(r.frames.length, 0);
  assert.equal(r.requests.length, 1);
});

for (const kind of ["503", "wrong MIME", "partial EOF", "invalid JSON", "invalid UTF-8",
                    "incompatible version", "missing snapshot"]) {
  test(`${kind} latches a single failure without opening a replacement stream`, async () => {
    const r = rig({status: kind === "503" ? 503 : 200,
                   headers: kind === "wrong MIME" ? {"Content-Type": "text/html"} : {}});
    await nextTurn();
    if (kind === "partial EOF") {
      r.writer.enqueue(encoder.encode(frame("1").trimEnd()));
      r.writer.close();
    } else if (kind === "invalid JSON") {
      r.writer.enqueue(encoder.encode("{broken}\n"));
    } else if (kind === "invalid UTF-8") {
      const bytes = encoder.encode(frame("1"));
      bytes[bytes.indexOf(0xe9)] = 255;
      r.writer.enqueue(bytes);
    } else if (kind === "incompatible version" || kind === "missing snapshot") {
      const invalid = JSON.parse(frame("1"));
      if (kind === "incompatible version") invalid.protocol_version = 2;
      else delete invalid.snapshot;
      r.writer.enqueue(encoder.encode(JSON.stringify(invalid) + "\n"));
    }
    await nextTurn();
    assert.equal(r.failures.length, 1, "response/record errors terminate before the timeout");
    r.advance(36000);
    assert.equal(r.frames.length, 0);
    assert.equal(r.failures.length, 1);
    assert.equal(r.requests.length, 1);
  });
}

for (const arrival of ["headers", "first frame", "next frame"]) {
  test(`in the foreground an expired deadline wins over late ${arrival}`, async () => {
    const r = rig({holdHeaders: arrival === "headers"});
    await nextTurn();
    if (arrival === "next frame") {
      r.writer.enqueue(encoder.encode(frame("1")));
      await nextTurn();
    }
    const installed = r.frames.length;
    r.advance(13000, false);
    if (arrival === "headers") r.releaseHeaders();
    else r.writer.enqueue(encoder.encode(frame("2")));
    await nextTurn();
    assert.equal(r.frames.length, installed);
    assert.equal(r.failures.length, 1);
    assert.equal(r.requests[0][1].signal.aborted, true);
    assert.equal(r.timers.size, 0);
    if (arrival !== "headers") {
      assert.equal(r.stream.locked, false);
      assert.equal(r.cancelled(), true);
    }
    r.advance(30000);
    assert.equal(r.requests.length, 1);
  });
}

for (const holdHeaders of [true, false]) {
  test(`explicit close releases the single ${holdHeaders ? "pending request" : "active reader"}`, async () => {
    const r = rig({holdHeaders});
    await nextTurn();
    r.feed.close();
    r.feed.close();
    r.releaseHeaders();
    await nextTurn();
    assert.equal(r.requests[0][1].signal.aborted, true);
    assert.equal(r.timers.size, 0);
    assert.equal(r.stream.locked, false);
    if (!holdHeaders) assert.equal(r.cancelled(), true);
    r.advance(13000);
    assert.deepEqual([r.requests.length, r.frames.length, r.failures.length], [1, 0, 0]);
  });
}

test("the clock uses header-receipt time and rejects an invalid Date", async () => {
  const r = rig({holdHeaders: true});
  r.advance(4000);
  r.releaseHeaders();
  await nextTurn();
  r.advance(250);
  r.writer.enqueue(encoder.encode(frame("1")));
  await nextTurn();
  assert.equal(r.frames[0].utc, Date.parse(date) + 250);
  r.feed.close();

  const invalid = rig({headers: {Date: "unavailable"}});
  await nextTurn();
  invalid.writer.enqueue(encoder.encode(frame("1")));
  await nextTurn();
  assert.equal(invalid.frames[0].utc, null);
  invalid.feed.close();
});

test("returning to a paused page gives the original reader one catch-up deadline", async () => {
  const r = rig();
  await nextTurn();
  r.writer.enqueue(encoder.encode(frame(1)));
  await nextTurn();
  r.feed.setVisible(false);
  r.advance(15000);
  assert.equal(r.failures.length, 0);
  assert.equal(r.feed.setVisible(true), true);
  r.advance(1500);
  r.feed.setVisible(false);
  r.feed.setVisible(true);
  r.advance(500);
  await nextTurn();
  assert.equal(r.requests.length, 1);
  assert.equal(r.failures.length, 1);
  assert.equal(r.stream.locked, false);
});

test("headers rejected before the first read also release the response body", async () => {
  const r = rig({headers: {"Content-Type": "text/plain"}});
  await nextTurn();
  assert.equal(r.failures.length, 1);
  assert.equal(r.requests[0][1].signal.aborted, true);
  assert.equal(r.cancelled(), true);
  assert.equal(r.stream.locked, false);
});
