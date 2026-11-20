"""Observe a local file's result in a normally rendering Chromium page."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile


RESULT = """new Promise(resolve => {
    const read = () => {
        const value = document.getElementById("result")?.textContent;
        if (value && value !== "waiting") {
            observer.disconnect();
            resolve(value);
        }
    };
    const observer = new MutationObserver(read);
    observer.observe(document, {subtree: true, childList: true, characterData: true});
    read();
})"""


async def _observe(path: Path, profile: str, log, budget_ms: int, interact=None) -> str:
    # Chromium's DevTools pipe reads FD 3 and writes FD 4. The POSIX shell
    # maps our stdin/stdout to those FDs and immediately execs the browser.
    process = await asyncio.create_subprocess_exec(
        "sh", "-c", 'exec "$@" 3<&0 4>&1 </dev/null >/dev/null', "sh",
        os.environ.get("CHROMIUM", "chromium"), "--headless", "--no-sandbox", "--disable-gpu",
        "--allow-file-access-from-files", "--disable-background-networking", "--disable-component-update",
        "--disable-sync", "--no-first-run", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND",
        "--remote-debugging-pipe", f"--user-data-dir={profile}", "about:blank",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log,
    )
    request_id = 0

    async def command(method, params, session=None):
        nonlocal request_id
        request_id += 1
        request = {"id": request_id, "method": method, "params": params}
        if session:
            request["sessionId"] = session
        process.stdin.write(json.dumps(request).encode() + b"\0")
        await process.stdin.drain()
        while True:
            packet = await process.stdout.readuntil(b"\0")
            reply = json.loads(packet[:-1])
            if reply.get("id") == request_id:
                if "error" in reply:
                    raise RuntimeError(f"{method} failed: {reply['error']}")
                return reply["result"]

    try:
        async with asyncio.timeout(10):
            page = await command("Target.createTarget", {"url": "about:blank"})
            attached = await command("Target.attachToTarget", {"targetId": page["targetId"], "flatten": True})
            session = attached["sessionId"]
            await command("Page.bringToFront", {}, session)
            navigation = await command("Page.navigate", {"url": path.resolve().as_uri()}, session)
            if navigation.get("errorText"):
                raise RuntimeError(f"Cannot load {path}: {navigation['errorText']}")
        async with asyncio.timeout(budget_ms / 1000):
            if interact is not None:
                await interact(lambda method, params: command(method, params, session))
                return "passed"
            result = await command("Runtime.evaluate", {
                "expression": RESULT, "awaitPromise": True, "returnByValue": True,
            }, session)
        if "exceptionDetails" in result:
            raise RuntimeError(f"Reading {path} failed: {result['exceptionDetails']}")
        return result["result"]["value"]
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            process.kill()
            await process.wait()


def run_document(path: Path, *, budget_ms: int = 8000, interact=None) -> None:
    with TemporaryDirectory() as profile, TemporaryFile() as log:
        try:
            observation = asyncio.run(_observe(path, profile, log, budget_ms, interact))
        except (TimeoutError, OSError, EOFError) as exc:
            log.seek(0)
            details = log.read().decode(errors="replace")[-1000:]
            raise AssertionError(f"{path}: Chromium did not return #result ({type(exc).__name__}). {details}") from exc
    assert observation == "passed", observation
