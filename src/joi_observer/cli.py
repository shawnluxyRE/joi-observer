"""REQ-001 CLI与运行期组合根，导入模块不触发环境检查或采集。"""

import argparse
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import platform
import signal
import sys
from typing import Protocol, TextIO

from joi_observer import __version__
from joi_observer.config import AppConfig, ConfigError, example_config_path, load_config, resolve_config_path
from joi_observer.data.models import Metric, ObjectKey, ObjectSpec, StateSnapshot
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.monitor import Monitor
from joi_observer.tui.app import CursesTerminal, ObserverApp
from joi_observer.tui.layout import HostInfo


class RuntimePort(Protocol):
    """已验证配置后的运行期边界，供CLI隔离终端/驱动/采集进程。"""

    def prepare_log(self) -> bool:
        """全屏前调用一次ErrorLog.prepare；可写返回True，失败返回False。

        不自行打印。False不阻断启动；其后日志仍可按错误事件尝试恢复写入。
        """
        ...

    async def run(self) -> None:
        """并发运行采样和UI，q返回；可处理终止确保终端恢复后才返回/抛错。"""
        ...

    async def close(self) -> None:
        """幂等结束worker/日志；总体退出预算1秒，不补打日志到控制台。"""
        ...


class RuntimeLog(Protocol):
    """组合根只管理日志生命周期；采集record/recovered由Monitor使用。"""

    def prepare(self) -> bool:
        """同ErrorLog.prepare：全屏前检查文件，失败返回False但不打印。"""
        ...

    async def close(self, *, timeout: float = 1.0) -> bool:
        """同ErrorLog.close：在剩余预算内排空，绝不阻挡终端先恢复。"""
        ...


@dataclass(frozen=True)
class RuntimeComponents:
    """已组装的运行期依赖；用于验证真实Monitor/UI的协作而非替换编排。

    monitor与app必须共享同一个MonitorState，error_log与monitor使用的日志
    实例相同。注入组件只替换外部端口/装配，不允许替换采样或UI业务结果。
    生产可由组合根创建；测试注入的组件也由组合根run/close拥有其生命周期。
    """

    monitor: Monitor
    app: ObserverApp
    error_log: RuntimeLog


@dataclass(frozen=True)
class CliDependencies:
    """CLI外部环境快照，不用于替换配置解析业务或CLI本身。

    runtime_factory只在配置验证及交互检查通过后调用，参数为解析后的AppConfig。
    stdout/stderr只用于全屏前CLI输出，运行期间采集错误禁止输出。
    term来自TERM；空字符串或dumb视为不可交互终端。测试使用StringIO和离线runtime。
    """

    cwd: Path
    home: Path
    stdin_isatty: bool
    stdout_isatty: bool
    term: str
    stdout: TextIO
    stderr: TextIO
    runtime_factory: Callable[[AppConfig], RuntimePort]


class ApplicationRuntime:
    """生产组合根，负责创建本次会话唯一的State、Monitor、ErrorLog与UI。

    构造只保存config，无I/O。prepare_log准备日志；run中按配置装配采集器，
    具体硬件/Docker/vLLM适配分别由REQ-002/003/004提供，不创建伪造数据。
    UI只接收SnapshotReader。所有正常监控数据保存在内存，不写数据库/文件。
    """

    def __init__(self, config: AppConfig, *, components: RuntimeComponents | None = None) -> None:
        self.config = config
        self.components = components
        self._stop_event: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self._deadline: float | None = None
        self._closed = False
        self._running = False
        self._close_task: asyncio.Task | None = None

    def prepare_log(self) -> bool:
        """构建/使用components的唯一ErrorLog并prepare，失败False且不输出。

        不启动采样。注入组件的测试可自行准备Log端口后直接调用run；生产main
        总是在run前调用本方法，避免遗漏唯一的全屏前可写性提示。
        """
        return self._components().error_log.prepare()

    async def run(self) -> None:
        """先确保UI可绘制初始快照，再同时运行Monitor.run(stop_event)与UI.run。

        UI退出/异常则设置stop_event并取消或等待Monitor；Monitor内部异常则
        取消UI，使其finally恢复终端。采集失败是数据结果，不终止运行期。
        本方法保留原异常供main映射退出码，绝不打印采集错误或traceback。
        退出总体清理预算1秒（含Monitor.stop和ErrorLog.close）；所有采集器须
        合作取消，同步外部调用需有底层超时，不能靠无限等待线程退出收尾。
        Python可处理的SIGINT/SIGTERM走相同清理路径；SIGKILL/断电无法保证恢复。
        """
        if self._running or self._closed:
            raise RuntimeError("Runtime is already running or closed")
        components = self._components()
        self._running = True
        self._stop_event = asyncio.Event()

        async def capture(operation):
            # KeyboardInterrupt must not escape a child Task and abort the loop
            # before the sibling UI has restored the real terminal.
            try:
                await operation
                return None
            except BaseException as error:
                return error

        ui_task = asyncio.create_task(capture(components.app.run()), name="observer-ui")
        monitor_task = asyncio.create_task(capture(components.monitor.run(self._stop_event)), name="observer-monitor")
        self._tasks = [ui_task, monitor_task]
        try:
            done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
            # Preserve a genuine failure even if the other task also completed.
            for task in (ui_task, monitor_task):
                if task in done and task.result() is not None:
                    raise task.result()
        finally:
            self._start_budget()
            self._stop_event.set()
            # The UI's finally is allowed to restore the terminal before any
            # potentially slow source or log cleanup begins.
            if not ui_task.done():
                ui_task.cancel()
                await self._wait_with_budget({ui_task})
            if not monitor_task.done():
                monitor_task.cancel()
            try:
                await self.close()
            finally:
                self._running = False

    async def close(self) -> None:
        """幂等清理部分构造资源；run失败和prepare后失败也能调用。

        与run共享1秒退出预算，关闭日志不向控制台补发积压采集错误。
        清理失败不掩盖已有异常。没有待写错误时不产生任何日志记录。
        """
        if self._closed:
            return
        self._start_budget()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._cleanup(), name="observer-cleanup")
        await self._wait_with_budget({self._close_task})

    def _components(self) -> RuntimeComponents:
        if self.components is None:
            # Static unknown templates are presentation slots, not collectors.
            # REQ-002--004 will supply the actual sources using the same state.
            specs = [ObjectSpec(ObjectKey("host", "local"),
                                (Metric("CPU", None, "%"), Metric("RAM", None, "GiB")))]
            # Mounts have no collector identity yet (REQ-002); the layout uses
            # config directly for their unknown slots, including long paths.
            specs.extend(ObjectSpec(ObjectKey("docker", item.id), (Metric("state", None),))
                         for item in self.config.containers)
            specs.extend(ObjectSpec(ObjectKey("vllm", item.id),
                                    (Metric("RUNNING", None), Metric("WAITING", None)))
                         for item in self.config.models)
            state = MonitorState(tuple(specs))
            log = ErrorLog(self.config.logging)
            monitor = Monitor((), state, log, interval=self.config.sample_interval,
                              timeout=self.config.collection_timeout)
            app = ObserverApp(self.config, _ReadOnlyState(state), CursesTerminal(),
                              host=HostInfo(platform.node(), f"{platform.system()} {platform.release()}"),
                              wall_clock=lambda: datetime.now().astimezone())
            self.components = RuntimeComponents(monitor, app, log)
        return self.components

    def _start_budget(self) -> None:
        if self._deadline is None:
            self._deadline = asyncio.get_running_loop().time() + 1.0

    def _remaining(self) -> float:
        return max(0.0, self._deadline - asyncio.get_running_loop().time())

    async def _wait_with_budget(self, tasks: set[asyncio.Task]) -> None:
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self._remaining())
            for task in pending:
                task.cancel()
            for task in tasks - pending:
                # Cleanup errors are deliberately isolated from the original
                # operation's result, including cancellation during shutdown.
                try:
                    task.result()
                except BaseException:
                    pass

    async def _cleanup(self) -> None:
        try:
            if self.components is None:
                return
            if self._stop_event is not None:
                self._stop_event.set()
            if self._tasks:
                ui_task = self._tasks[0]
                if not ui_task.done():
                    ui_task.cancel()
                    await self._wait_with_budget({ui_task})
            for task in self._tasks[1:]:
                if not task.done():
                    task.cancel()
            stop_task = asyncio.create_task(self.components.monitor.stop())
            pending = {stop_task, *self._tasks[1:]}
            remaining = self._remaining()
            if remaining > 0:
                log_task = asyncio.create_task(self.components.error_log.close(timeout=remaining))
                pending.add(log_task)
            await self._wait_with_budget(pending)
        finally:
            self._closed = True


class _ReadOnlyState:
    """Narrow the production UI dependency to the snapshot capability only."""

    def __init__(self, state: MonitorState) -> None:
        self.__state = state

    def snapshot(self) -> StateSnapshot:
        return self.__state.snapshot()


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("Invalid command arguments. Use --help for usage.")


class _SignalExit(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def main(argv: Sequence[str] | None = None, *, dependencies: CliDependencies | None = None) -> int:
    """命令入口，返回退出码；不直接调用sys.exit，便于离线黑盒验证。

    argv=None读取sys.argv[1:]，否则使用传入序列。支持--config PATH、--help、
    --version、--example-config（只打印随包示例绝对路径）。后三项无需配置或
    TTY，不构建runtime。未知参数返回2。默认依赖在调用时读取本地环境，
    runtime_factory=ApplicationRuntime；导入不产生副作用。

    普通启动顺序：解析参数→resolve_config_path→load_config→检查stdin/stdout
    均为TTY且TERM不为空/dumb→构建runtime→prepare_log→async运行并finally close。
    非TTY返回3并提示需要交互终端，不进入全屏/采集/写日志。配置失败返回2，
    输出路径、字段/行列；缺配置同时提示期望路径和示例路径，不使用示例启动，
    不写error.log。日志准备失败只在stderr输出一次固定英文提示
    'Error log unavailable; monitoring will continue.'，然后正常进入UI。

    q返回0；SIGINT/KeyboardInterrupt返回130；SIGTERM返回143；内部运行错误
    完成终端恢复后返回1，只能打印固定 'Observer stopped unexpectedly.'，
    不打印异常内容或堆栈。采集失败应被Monitor隔离，永不因此改变CLI退出码。
    生产退出时恢复终端先于任何CLI诊断；close再次被调用须安全。
    """
    if dependencies is None:
        dependencies = CliDependencies(
            cwd=Path.cwd(), home=Path.home(), stdin_isatty=sys.stdin.isatty(),
            stdout_isatty=sys.stdout.isatty(), term=os.environ.get("TERM", ""),
            stdout=sys.stdout, stderr=sys.stderr, runtime_factory=ApplicationRuntime)
    deps = dependencies
    parser = _ArgumentParser(prog="joi-observer", description="Read-only terminal observer", add_help=False)
    parser.add_argument("--config", metavar="PATH", help="Read this user configuration")
    parser.add_argument("--help", "-h", action="store_true", help="Show this help")
    parser.add_argument("--version", action="store_true", help="Show the package version")
    parser.add_argument("--example-config", action="store_true", help="Print the example configuration path")
    try:
        arguments = parser.parse_args(argv)
    except ValueError as error:
        print(str(error), file=deps.stderr)
        return 2
    if arguments.help:
        parser.print_help(deps.stdout)
        return 0
    if arguments.version:
        print(f"joi-observer {__version__}", file=deps.stdout)
        return 0
    if arguments.example_config:
        print(example_config_path(), file=deps.stdout)
        return 0
    try:
        path = resolve_config_path(arguments.config, cwd=deps.cwd, home=deps.home)
        config = load_config(path)
    except ConfigError as error:
        print(str(error), file=deps.stderr)
        return 2
    if not deps.stdin_isatty or not deps.stdout_isatty or not deps.term.strip() or deps.term.lower() == "dumb":
        print("An interactive terminal is required.", file=deps.stderr)
        return 3

    async def session(runtime: RuntimePort) -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        received: list[int] = []
        previous_handlers = {}

        def stop_for_signal(signum, frame):
            if not received:
                received.append(signum)
                loop.call_soon_threadsafe(task.cancel)

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                previous = signal.signal(signum, stop_for_signal)
            except (ValueError, OSError):
                continue  # main may also be embedded in a non-main thread.
            previous_handlers[signum] = previous
        try:
            try:
                if not runtime.prepare_log():
                    print("Error log unavailable; monitoring will continue.", file=deps.stderr)
                await runtime.run()
            finally:
                original_error = sys.exc_info()[0]
                try:
                    await runtime.close()
                except BaseException:
                    if original_error is None:
                        raise
        except asyncio.CancelledError:
            if received:
                raise _SignalExit(received[0]) from None
            raise
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
        if received:
            raise _SignalExit(received[0])

    try:
        runtime = deps.runtime_factory(config)
        asyncio.run(session(runtime))
        return 0
    except _SignalExit as error:
        return 128 + error.signum
    except KeyboardInterrupt:
        return 130
    except (Exception, asyncio.CancelledError):
        print("Observer stopped unexpectedly.", file=deps.stderr)
        return 1
