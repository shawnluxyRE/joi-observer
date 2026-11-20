"""Offline inspection of a deployed Web container and its installed ASGI application."""

import argparse
import asyncio
from contextlib import ExitStack
from html.parser import HTMLParser
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch


def check_deployment(container, expected_image, service):
    """Compare a running container with the selected build and its resolved Compose service."""
    assert container["Image"] == expected_image, "The running Web container uses a different release image"
    assert container["State"]["Running"], "The selected Web container is stopped"
    host = container["HostConfig"]
    assert not host["Privileged"] and host["ReadonlyRootfs"]
    assert "ALL" in host["CapDrop"] and not host.get("CapAdd")
    assert host["Runtime"] == "runc" and not host.get("Devices") and not host.get("DeviceRequests")
    reader_gid, = service["group_add"]
    assert str(reader_gid) in host["GroupAdd"]
    assert container["Config"]["User"] == "65532:65532"
    mount, = container["Mounts"]
    assert mount["Type"] == "bind" and not mount["RW"]
    assert mount["Source"] == mount["Destination"] == "/run/joi-observer"
    bindings = container["NetworkSettings"]["Ports"]
    port, = service["ports"]
    assert {key: entries for key, entries in bindings.items() if entries} == {
        "8080/tcp": [{"HostIp": port["host_ip"], "HostPort": str(port["published"])}],
    }


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "src" in attrs:
            self.urls.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.urls.append(attrs["href"])


async def http_get(app, path, state):
    incoming = asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    messages = []

    async def send(event):
        messages.append(event)

    await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
               "method": "GET", "path": path, "raw_path": path.encode(), "http_version": "1.1",
               "scheme": "http", "root_path": "", "query_string": b"", "headers": [],
               "state": state.copy()}, incoming.get, send)
    first, *body = messages
    assert first["type"] == "http.response.start" and first["status"] == 200, f"Cannot load {path}"
    assert body and all(part["type"] == "http.response.body" for part in body)
    assert all(part.get("more_body", False) for part in body[:-1]) and not body[-1].get("more_body", False)
    return b"".join(part.get("body", b"") for part in body)


async def exercise_application(app, asset_dir):
    """Use actual lifespan/HTTP entry points and compare bytes with the installed package."""
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    state = {}

    async def lifespan():
        try:
            await app({"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"},
                       "state": state}, incoming.get, outgoing.put)
        finally:
            outgoing.put_nowait(None)

    task = asyncio.create_task(lifespan())

    async def expect(event):
        message = await outgoing.get()
        if message is None:
            await task  # Report the original startup/shutdown exception.
            raise AssertionError(f"Web lifespan ended before {event}")
        assert message["type"] == event, f"Expected {event}, received {message['type']}"

    try:
        async with asyncio.timeout(15):
            incoming.put_nowait({"type": "lifespan.startup"})
            await expect("lifespan.startup.complete")
            document = await http_get(app, "/", state)
            links = AssetLinks()
            links.feed(document.decode("utf-8"))
            assert len(links.urls) == 2
            releases, names = set(), set()
            for url in links.urls:
                match = re.fullmatch(r"/static/([^/?#]+)/(dashboard\.(?:js|css))", url)
                assert match, "Unexpected dashboard asset URL"
                release, name = match.groups()
                releases.add(release)
                names.add(name)
                expected = asset_dir.joinpath(name).read_bytes()
                assert expected and await http_get(app, url, state) == expected, f"Incorrect response: {name}"
            assert len(releases) == 1 and names == {"dashboard.js", "dashboard.css"}
            assert asset_dir.joinpath("index.html").read_bytes().replace(
                b"__JOI_RELEASE__", releases.pop().encode()) == document
            incoming.put_nowait({"type": "lifespan.shutdown"})
            await expect("lifespan.shutdown.complete")
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def check_runtime():
    """Use PID 1's real Uvicorn options, without opening a network listener."""
    import uvicorn
    from uvicorn.main import main as uvicorn_cli

    argv = [os.fsdecode(arg) for arg in Path("/proc/1/cmdline").read_bytes().split(b"\0") if arg]
    assert argv[1:3] == ["-m", "uvicorn"], "PID 1 must run the Web server"
    assert (os.getuid(), os.getgid()) == (65532, 65532)
    assert not Path("/var/run/docker.sock").exists()
    assert not any(Path("/dev").glob("nvidia*"))
    with ExitStack() as stack:
        for owner, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"), (socket.socket, "bind"),
                            (socket, "getaddrinfo")):
            stack.enter_context(patch.object(owner, name, side_effect=AssertionError("Unexpected network access")))
        with patch("uvicorn.main.run") as runner:
            uvicorn_cli.main(args=argv[3:], standalone_mode=False)
        runner.assert_called_once()
        args, kwargs = runner.call_args
        app_dir = kwargs.pop("app_dir", None)
        if app_dir is not None:
            sys.path.insert(0, app_dir)
        server = uvicorn.Config(*args, **kwargs)
        assert server.app == "joi_observer.web.app:create_app" and server.factory and server.lifespan == "on"
        assert server.workers == 1 and not server.reload and not server.date_header
        assert server.host == "0.0.0.0" and server.port == 8080 and not server.uds and server.fd is None
        server.load()
        asyncio.run(exercise_application(server.loaded_app, files("joi_observer.web").joinpath("static")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    deployment = commands.add_parser("deployment", help="Read one Docker container inspection from stdin")
    deployment.add_argument("expected_image", help="Image ID recorded from the selected release build")
    deployment.add_argument("compose", type=Path, help="Resolved Compose JSON used to launch this release")
    commands.add_parser("runtime", help="Run inside the deployed Web container")
    options = parser.parse_args()
    if options.mode == "deployment":
        container, = json.load(sys.stdin)
        service = json.loads(options.compose.read_text(encoding="utf-8"))["services"]["web"]
        check_deployment(container, options.expected_image, service)
    else:
        check_runtime()
