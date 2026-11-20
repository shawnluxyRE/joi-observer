"""Acceptance of the shipped Web configuration, installed resources and independent lifecycle."""

import asyncio
from configparser import ConfigParser
from pathlib import Path
import re
import shlex
import tomllib

from packaging.requirements import Requirement
import pytest
import yaml

from web_image_artifact import check_deployment, exercise_application


ROOT = Path(__file__).resolve().parents[1]


def required_text(path):
    assert path.is_file(), f"Missing Web deployment artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_shipped_compose_publishes_web_on_the_selected_interface_and_ipc_directory():
    document = yaml.safe_load(required_text(ROOT / "deploy" / "compose.yaml"))
    assert set(document["services"]) == {"web"}
    web = document["services"]["web"]
    assert re.fullmatch(r"\$\{JOI_WEB_IMAGE:\?[^}]*\}", web["image"]) and not web.get("build")
    port, = web["ports"]
    assert port["target"] == 8080 and port.get("protocol", "tcp") == "tcp"
    assert re.fullmatch(r"\$\{JOI_WEB_BIND:\?[^}]*\}", port["host_ip"])
    assert port["published"] == "${JOI_WEB_PORT:-8090}"
    mount, = web["volumes"]
    assert mount["source"] == mount["target"] == "/run/joi-observer"
    assert mount["type"] == "bind" and mount["read_only"] and not mount["bind"]["create_host_path"]
    assert any(re.fullmatch(r"\$\{JOI_READERS_GID:\?[^}]*\}", str(group)) for group in web["group_add"])
    assert web["read_only"] and not web.get("privileged") and "ALL" in web["cap_drop"]
    assert web.get("runtime") == "runc"
    assert not web.get("devices") and not web.get("gpus") and not web.get("use_api_socket")
    assert "/api/live" not in str(web.get("healthcheck", {}))


def test_collector_restart_keeps_the_web_mount_on_the_published_socket_directory():
    from joi_observer.ipc.client import DEFAULT_ENDPOINT as reader_socket
    from joi_observer.service import DEFAULT_ENDPOINT as publisher_socket

    unit = ConfigParser(interpolation=None)
    unit.read_string(required_text(ROOT / "deploy" / "systemd" / "joi-observer.service"))
    host_service = unit["Service"]
    compose = yaml.safe_load(required_text(ROOT / "deploy" / "compose.yaml"))
    mount, = compose["services"]["web"]["volumes"]

    # Keeping the directory inode lets the existing bind see a replacement socket
    # after a stop/start just as it does after a single systemctl restart.
    assert host_service.getboolean("RuntimeDirectoryPreserve")
    assert Path(mount["source"]) == Path("/run") / host_service["RuntimeDirectory"]
    assert publisher_socket.parent == Path(mount["source"])
    assert Path(mount["target"]) / publisher_socket.name == reader_socket


def test_running_deployment_is_compared_with_the_selected_build():
    directory = "/run/joi-observer"
    current = {"Image": "sha256:current", "State": {"Running": True}, "Config": {"User": "65532:65532"},
               "HostConfig": {"Privileged": False, "ReadonlyRootfs": True, "CapDrop": ["ALL"],
                              "Runtime": "runc", "GroupAdd": ["704"]},
               "Mounts": [{"Type": "bind", "RW": False, "Source": directory, "Destination": directory}],
               "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "192.0.2.14", "HostPort": "8088"}]}}}
    service = {"ports": [{"target": 8080, "published": "8088", "host_ip": "192.0.2.14"}],
               "group_add": ["704"]}
    check_deployment(current, "sha256:current", service)
    with pytest.raises(AssertionError, match="different release image"):
        check_deployment(current, "sha256:next", service)


def test_web_installation_declares_and_locks_its_runtime_dependencies():
    recipe = required_text(ROOT / "deploy" / "Dockerfile.web").replace("\\\n", " ")
    # Read the executable install step, allowing a build cache mount and option reordering.
    # The actual versioned build and installed application are checked during deployment.
    installs = re.findall(
        r"(?im)^\s*RUN[ \t]+(?:--\S+[ \t]+)*uv[ \t]+sync[ \t]+([^\n#;&|]+)", recipe
    )
    assert any({"--locked", "--no-dev", "--no-editable"} <= set(options)
               and ("--extra=web" in options or ("--extra", "web") in zip(options, options[1:]))
               for options in map(shlex.split, installs)), "Install the web extra from uv.lock using uv sync --locked"
    project = tomllib.loads(required_text(ROOT / "pyproject.toml"))["project"]
    web = project.get("optional-dependencies", {}).get("web", [])
    runners = [Requirement(item) for item in web]
    assert any(req.name.lower() == "uvicorn" and (req.marker is None or req.marker.evaluate({"extra": "web"}))
               for req in runners), "Declare Uvicorn in the web extra"
    lock = tomllib.loads(required_text(ROOT / "uv.lock"))["package"]
    locked_project = next(p for p in lock if p["name"] == project["name"])
    assert "uvicorn" in {item["name"] for item in locked_project["optional-dependencies"]["web"]}
    direct = {Requirement(item).name.lower() for item in [*web, *project["dependencies"]]}
    locked = {p["name"].lower(): p for p in lock}
    for name in direct:
        assert name in locked
        assert ".pytest_cache" not in locked[name]["source"].get("registry", ""), "Web build depends on a test cache"


def test_product_runtime_probe_drives_the_real_factory_through_static_http():
    from importlib.resources import files
    from joi_observer.web.app import create_app
    from test_web_api import Attempts

    port = Attempts()
    asyncio.run(exercise_application(create_app(connector=port), files("joi_observer.web").joinpath("static")))
    assert not port.endpoints


def test_installed_web_package_declares_its_dashboard_resources():
    config = tomllib.loads(required_text(ROOT / "pyproject.toml"))["tool"]["setuptools"]
    roots = [ROOT / "src" / "joi_observer", ROOT / "src" / "joi_observer" / "web"]

    def declared(key):
        paths = set()
        for root in roots:
            package = ".".join(root.relative_to(ROOT / "src").parts)
            patterns = config.get(key, {})
            for pattern in [*patterns.get("*", []), *patterns.get(package, [])]:
                paths.update(root.glob(pattern))
        return paths

    resources = {roots[-1] / "static" / name for name in ("index.html", "dashboard.css", "dashboard.js")}
    assert all(path.is_file() for path in resources)
    included = declared("package-data") - declared("exclude-package-data")
    missing = sorted(path.name for path in resources - included)
    assert not missing, f"Web resources absent from setuptools package-data: {missing}"


def test_missing_packaged_assets_fail_lifespan_startup_without_ipc(tmp_path):
    from joi_observer.web.app import create_app
    from test_web_api import Attempts, _AsgiExchange

    async def scenario():
        port = Attempts()
        app = create_app(connector=port, asset_root=tmp_path)
        worker = _AsgiExchange(app, {"type": "lifespan", "asgi": {"version": "3.0"}})
        worker.incoming.put_nowait({"type": "lifespan.startup"})
        await worker.start()
        try:
            assert (await worker.event())["type"] == "lifespan.startup.failed"
            await asyncio.wait_for(worker.task, 2)
            assert not port.endpoints
        finally:
            if not worker.task.done():
                worker.task.cancel()
                await asyncio.gather(worker.task, return_exceptions=True)

    asyncio.run(scenario())


def test_cancelled_http_and_lifespan_shutdown_join_the_same_ipc_cleanup():
    from joi_observer.web.app import create_app
    from test_ipc_client import MemoryStream
    from test_ipc_protocol import payload, wire
    from test_web_api import Attempts, HttpRequest, _AsgiExchange

    class HeldClose(MemoryStream):
        def __init__(self):
            super().__init__(wire(payload()))
            self.close_count = 0
            self.closing = asyncio.Event()
            self.release = asyncio.Event()
            self.close_attempt_finished = False

        async def close(self):
            self.close_count += 1
            self.closing.set()
            try:
                await self.release.wait()
                # SnapshotClient handles transport close errors within its bounded close().
                raise OSError("transport no longer available")
            finally:
                self.close_attempt_finished = True

    class LifespanExchange(_AsgiExchange):
        async def send(self, message):
            if message["type"] == "lifespan.shutdown.complete":
                assert self.stream.close_attempt_finished, "Shutdown acknowledged while IPC close was pending"
            await super().send(message)

    async def scenario():
        stream = HeldClose()
        port = Attempts(stream)
        app = create_app(connector=port, clock=lambda: 60.0)
        worker = LifespanExchange(app, {"type": "lifespan", "asgi": {"version": "3.0"}})
        worker.stream = stream
        worker.incoming.put_nowait({"type": "lifespan.startup"})
        await worker.start()
        tasks = [worker.task]
        try:
            assert (await worker.event())["type"] == "lifespan.startup.complete"
            page = HttpRequest(app)
            await page.__aenter__()
            tasks.append(page.task)
            assert (await page.response())[0] == 200
            assert await page.frame() == payload()
            page.task.cancel()
            # The server enters lifespan shutdown without joining cancelled
            # HTTP tasks. Hold the real client's transport close across both.
            await asyncio.wait_for(stream.closing.wait(), 2)
            worker.incoming.put_nowait({"type": "lifespan.shutdown"})
            while not worker.incoming.empty():
                await asyncio.sleep(0)
            stream.release.set()
            assert (await worker.event())["type"] == "lifespan.shutdown.complete"
            await worker.task
            result, = await asyncio.gather(page.task, return_exceptions=True)
            assert result is None or isinstance(result, asyncio.CancelledError)
            assert stream.close_count == 1 and len(port.endpoints) == 1
        finally:
            stream.release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
