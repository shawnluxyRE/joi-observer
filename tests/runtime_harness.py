"""Offline migration fixture for independently owned collection and TUI tasks.

This is test scaffolding, never an executable product mode. CollectorRuntime
performs production source assembly; the real ObserverApp reads its snapshot
port. IPC itself is covered by the dedicated service/client/pipeline tests.
Leaving the UI does not stop collection. Tests explicitly call close() to stop
the service side and retain their original source cleanup assertions there.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime

from joi_observer._host import local_host_info
from joi_observer.ipc.protocol import build_metadata
from joi_observer.runtime import CollectorComponents, CollectorRuntime
from joi_observer.tui.app import CursesTerminal, ObserverApp


@dataclass(frozen=True)
class RuntimeComponents:
    monitor: object
    app: object
    error_log: object


class ApplicationRuntime:
    """Keep existing offline assertions while splitting q from service stop."""

    def __init__(self, config, *, components=None, docker_command_factory=None,
                 vllm_http_factory=None):
        self.config = config
        self.components = components
        self.collector = CollectorRuntime(
            config, docker_command_factory=docker_command_factory,
            vllm_http_factory=vllm_http_factory,
        )
        if components is not None:
            updates = asyncio.Event()
            # Migrated fixtures retain their real Monitor and State; only the
            # ownership and lightweight update notification are wired here.
            components.monitor._on_update = updates.set
            self.collector.components = CollectorComponents(
                components.monitor._state, components.monitor, components.error_log, updates,
            )
        self.stop = None
        self.sampling = None
        self._ui = None

    def prepare_log(self):
        result = self.collector.prepare_log()
        self._components()
        return result

    def _components(self):
        if self.components is None:
            owned = self.collector._components()
            host = local_host_info()
            # Legacy factory tests deliberately hand-build more than three
            # mounts. Keep that full input at CollectorRuntime, while the
            # presentation projection receives load_config's effective range.
            effective = replace(self.config, mount_points=self.config.mount_points[:3])
            metadata = build_metadata(effective, hostname=host.hostname, system=host.system)
            app = ObserverApp(metadata, self.collector, CursesTerminal(), host=host,
                              wall_clock=lambda: datetime.now().astimezone())
            self.components = RuntimeComponents(owned.monitor, app, owned.error_log)
        return self.components

    async def run(self):
        components = self._components()
        if self.sampling is not None:
            raise RuntimeError("Migration harness cannot run twice.")
        self.stop = asyncio.Event()
        self.sampling = asyncio.create_task(self.collector.run(self.stop))

        async def capture_ui():
            try:
                await components.app.run()
            except BaseException as error:
                return error
            return None

        self._ui = asyncio.create_task(capture_ui())
        try:
            done, _ = await asyncio.wait((self._ui, self.sampling),
                                         return_when=asyncio.FIRST_COMPLETED)
            if self.sampling in done:
                await self.sampling
            if self._ui in done:
                error = self._ui.result()
                if error is not None:
                    raise error
        finally:
            if self._ui is not None and not self._ui.done():
                self._ui.cancel()
                await asyncio.gather(self._ui, return_exceptions=True)

    async def close(self):
        # Unlike q, this explicitly stops the independently owned service.
        if self.stop is not None:
            self.stop.set()
        if self._ui is not None and not self._ui.done():
            self._ui.cancel()
            await asyncio.gather(self._ui, return_exceptions=True)
        await self.collector.close()
        if self.sampling is not None:
            await asyncio.gather(self.sampling, return_exceptions=True)
