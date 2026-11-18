"""TUI connection lifetime, separate from the host collector lifetime."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from datetime import datetime

from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient
from joi_observer._shutdown import spawn, run_cleanup, await_owner, join_tasks, cancel_once
from joi_observer.tui.app import ObserverApp, TerminalPort
from joi_observer.tui.layout import HostInfo


class TuiClientSession:
    """Run the real ObserverApp using metadata and a local snapshot cache.

    Await client.connect before terminal.enter. Construct a fresh ObserverApp,
    SessionViewActions and HistoryScaleTracker from that envelope's metadata;
    never load AppConfig, build collectors, read host release or prepare logs.
    Race UI execution against client.wait_failed. Failure cancels the UI and
    awaits its terminal restoration before propagating ConnectionFailure.
    q closes only this client. Source STALE does not end the session. The
    existing app's layout, frame scheduler, input and cleanup remain in use.
    """

    def __init__(self, client: SnapshotClient, terminal: TerminalPort, *,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> None:
        """Store dependencies; wall_clock returns timezone-aware local time.

        Each session owns its selection and theme; construction reads no clock.
        """
        self.client = client
        self.terminal = terminal
        self.wall_clock = wall_clock
        self._tasks = []
        self._close_task = None
        self._deadline = None
        self._connection_failed = False

    async def run(self) -> None:
        """Connect once, run UI and receive concurrently, finally close client.

        Failure before first frame never enters fullscreen. In-session failure
        restores before escaping; no diagnostic is printed by this layer.
        Slow reads never block keys. Cancellation/SIGINT follows the same
        cleanup path. No reconnection, local sampling or fallback configuration.
        A known connection failure survives a normal UI return and the client's
        transition to CLOSED; existing UI errors and cancellation keep priority.
        """
        original = None
        try:
            connecting = spawn(self.client.connect())
            self._tasks = [connecting]
            envelope = await connecting
            self._tasks = []  # The completed handshake must not win the UI race.
            metadata = envelope.metadata
            app = ObserverApp(metadata, self.client, self.terminal,
                              host=HostInfo(metadata.hostname, metadata.system),
                              wall_clock=self.wall_clock)
            ui = spawn(app.run())
            self._tasks.append(ui)
            failure = spawn(self.client.wait_failed())
            self._tasks.append(failure)
            done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
            if ui in done:
                await ui
                if failure.done() and not failure.cancelled():
                    error = failure.exception()
                    if isinstance(error, ConnectionFailure):
                        raise error
            else:
                await failure
        except BaseException as error:
            original = error
            raise
        finally:
            try:
                await self.close()
            except BaseException as error:
                if original is None:
                    if self._connection_failed and not isinstance(error, asyncio.CancelledError):
                        raise ConnectionFailure("Snapshot connection failed.") from None
                    raise
            if original is None and self._connection_failed:
                raise ConnectionFailure("Snapshot connection failed.") from None

    async def close(self) -> None:
        """Idempotently cancel session work, restore UI, and close this client.

        Share a one-second cleanup budget; do not wait for a stalled read.
        """
        if self._close_task is None:
            self._deadline = asyncio.get_running_loop().time() + 1.0
            await run_cleanup(self._cleanup, publish=lambda task: setattr(self, "_close_task", task))
        else:
            await await_owner(self._close_task)

    async def _cleanup(self):
        for task in self._tasks:
            cancel_once(task)
        try:
            async with asyncio.timeout_at(self._deadline):
                await join_tasks(self._tasks)
        except TimeoutError:
            pass
        finally:
            original = sys.exc_info()[1]
            # UI work has settled and restored the terminal. Capture failure
            # immediately before close synchronously replaces FAILED with
            # CLOSED, so delayed stream teardown cannot turn it into success.
            if self.client.state is ConnectionState.FAILED:
                self._connection_failed = True
            try:
                await self.client.close()
            except BaseException:
                if original is None:
                    raise
