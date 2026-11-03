"""vLLM 0.31.0 的只读、有界采集与原始语义解析。

模块导入及构造不加载 HTTPX 或执行网络，也不执行包内采证代码。HTTPX 依赖采用
>=0.28.1,<0.29，并仅在未注入 client_factory 的首次 get 中懒加载。
Collector 返回原始语义观测，由 MonitorState 计算速率、窗口和历史。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
import re
from typing import Protocol
from urllib.parse import urlsplit

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import ObjectKey
from joi_observer.data.vllm import (
    ChatEngineSample, CounterSample, LatencySample, PoolingEngineSample,
    VllmCollectionResult, VllmObservation, make_vllm_spec,
)
from joi_observer.error_log import ErrorKind, Failure


SUPPORTED_VERSION = "0.31.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_SAMPLE_LINES = 50_000
MAX_LABELS_PER_SERIES = 16
MAX_NUMBER_CHARACTERS = 128
MAX_DECIMAL_EXPONENT = 400
MAX_INTEGER_DIGITS = 400
MAX_HTTP_CHUNK_BYTES = 64 * 1024
METRICS_PATHS = ("/version", "/v1/models", "/metrics")
_FAILURES = {
    ErrorKind.PARSE: ("response.invalid", "Invalid collection response."),
    ErrorKind.NOT_FOUND: ("object.not_found", "Configured object was not found."),
    ErrorKind.PERMISSION: ("access.denied", "Permission denied."),
    ErrorKind.UNAVAILABLE: ("source.unavailable", "Data source is unavailable."),
    ErrorKind.TIMEOUT: ("collection.timeout", "Collection timed out."),
}


def _failure(kind: ErrorKind) -> Failure:
    return Failure(kind, *_FAILURES[kind])


def _failed(config: ModelConfig, kind: ErrorKind) -> VllmCollectionResult:
    return VllmCollectionResult(ObjectKey("vllm", config.id), failure=_failure(kind))


def _positive_time(value: object) -> bool:
    try:
        return type(value) in (int, float) and value > 0 and math.isfinite(value)
    except OverflowError:
        return False


async def _cleanup(awaitable: object, timeout: float = 0.2) -> None:
    """Finish bounded teardown before propagating an owner's repeated cancel.

    Stream cleanup owns a separate task: cancellation of the reading task must
    not interrupt a response after its socket/stream release has already begun.
    The last slice of the budget is reserved for cancelling overdue cleanup.
    """
    task = asyncio.ensure_future(awaitable)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    cancel_at = deadline - min(0.01, timeout / 4)
    cancellation = False
    cleanup_cancelled = False
    while not task.done():
        now = loop.time()
        if now >= deadline:
            break
        if now >= cancel_at and not cleanup_cancelled:
            task.cancel()
            cleanup_cancelled = True
        try:
            await asyncio.wait((task,), timeout=(deadline if cleanup_cancelled else cancel_at) - now)
        except asyncio.CancelledError:
            cancellation = True

    def consume(completed):
        try:
            completed.result()
        except (asyncio.CancelledError, Exception):
            pass

    if task.done():
        consume(task)
    else:
        task.cancel()
        task.add_done_callback(consume)
    if cancellation:
        raise asyncio.CancelledError()


def _protect_httpx_response_close(response: object) -> None:
    """Own the *first* HTTPX release, including its automatic EOF close.

    HTTPX marks a Response closed before awaiting the underlying stream release.
    Retrying aclose after cancellation would consequently do nothing. Install a
    per-response close owner before iteration so EOF and context-manager exit
    both await the same bounded task. Only release is protected; body reads stay
    cancellable. No HTTPX import or extra protocol method is needed for injected
    clients, whose ordinary context-manager cleanup remains handled by get.
    """
    if not any(cls.__name__ == "Response" and cls.__module__ == "httpx"
               for cls in type(response).__mro__):
        return
    original_close = response.aclose
    close_task: asyncio.Task | None = None
    deadline = 0.0

    async def protected_close() -> None:
        nonlocal close_task, deadline
        loop = asyncio.get_running_loop()
        if close_task is None:
            deadline = loop.time() + 0.2
            close_task = asyncio.create_task(original_close())
        # All callers share the first release's deadline; a repeated close must
        # neither restart the operation nor grant it another cleanup budget.
        await _cleanup(close_task, max(0.001, deadline - loop.time()))
        if not close_task.done() or close_task.cancelled():
            raise TimeoutError("HTTP response cleanup timed out.")
        close_task.result()

    response.aclose = protected_close


@dataclass(frozen=True)
class HttpResponse:
    """一次请求的状态码和有界响应字节；构造不做业务校验。

    body 不进入快照/日志；3xx 不跟随，交给 Collector 分类。成功要求
    status=200，且非 bool。HTTP 端口与解析入口分别校验各自字节上限。
    """

    status: int
    body: bytes


class HttpBodyTooLargeError(Exception):
    """解压后的任一响应超过上限；不携带正文，Collector 归为 response.invalid。"""


class HttpPort(Protocol):
    """每个模型独占的异步 HTTP 端口；替身只提供字节/错误，不替换业务。

    构造无 IO，get 不重试、不跟随重定向、不发送推理请求。不打印或记日志。
    timeout 为本次剩余总预算，必须有限正数且拒 bool；max_bytes 为正整数。
    """

    async def get(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        """只读固定路径，返回状态码与字节。

        超时抛 TimeoutError，网络/TLS/依赖不可用归为 OSError，响应超限抛
        HttpBodyTooLargeError。取消传播 CancelledError。异常不含响应正文。
        超时、取消、close 250ms 内关闭响应流并清理在途任务，不留后台请求。
        """
        ...

    async def close(self) -> None:
        """幂等关闭自身 client 和流；在途 get 收到 CancelledError，250ms 内完成。"""
        ...


class AsyncHttpClient:
    """HTTPX 异步适配器接口；可注入完全离线 client factory。

    构造只保存 factory。首次 get 才创建 client，参数必须包含
    follow_redirects=False、trust_env=False、verify=True。默认 factory 懒加载
    httpx.AsyncClient；测试注入 factory 时不加载 HTTPX，也不解析 DNS。

    factory(**options) 返回具有 stream(method, url, *, timeout) 和 aclose()
    的对象。stream 返回异步上下文管理器，其 response 提供 status_code、
    headers、aiter_bytes(chunk_size=...)、aclose()。一次 get 只调用一次stream("GET",...)，
    不自行重试。即便无 Content-Length 也须按解压后的流式字节累计限长，
    恰好 max_bytes 合法，超出即中止并关闭流；不能读完无限正文才检查。
    读取时明确传递不超过MAX_HTTP_CHUNK_BYTES的chunk_size；解压累计上限
    不等同于HTTPX内部瞬时内存上限，真实后端的Content-Encoding/解压边界
    仍须在实现验证中覆盖，不能仅凭fake端口测试宣称已验证。

    url 只允许 http/https 的明确 origin 加 METRICS_PATHS 之一，拒绝凭据、
    query、fragment 和其他路径。非法参数在创建 client/请求前抛 ValueError。
    单实例不可重入 get；close 后 get 抛 RuntimeError，close 本身幂等。
    底层连接/读取和整体 get 都受传入 timeout 约束；清理预算250ms。
    只有 get 会创建 client 和请求；close 不会为未使用的端口创建 client。
    """

    def __init__(self, client_factory: Callable[..., object] | None = None) -> None:
        self._client_factory = client_factory
        self._client: object | None = None
        self._closed = False
        self._active: asyncio.Task | None = None

    async def get(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        """通过有界可取消流读取唯一请求；解压后的累计字节不能超过上限。"""
        if self._closed:
            raise RuntimeError("HTTP port is closed.")
        if self._active is not None:
            raise RuntimeError("HTTP port is already reading.")
        if not _positive_time(timeout) or type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("Invalid HTTP limits.")
        try:
            target = urlsplit(url)
            valid = (isinstance(url, str) and target.scheme in ("http", "https")
                     and target.hostname and target.path in METRICS_PATHS
                     and target.username is None and target.password is None
                     and not target.query and not target.fragment
                     and "?" not in url and "#" not in url
                     and not any(c.isspace() or ord(c) < 32 for c in url))
            target.port  # Invalid ports must fail before constructing a client.
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ValueError("Invalid read-only HTTP target.")
        self._active = asyncio.current_task()
        context = None
        entered = False
        try:
            async with asyncio.timeout(timeout):
                if self._client is None:
                    factory = self._client_factory
                    if factory is None:
                        try:
                            from httpx import AsyncClient
                        except ImportError:
                            raise OSError("HTTP dependency unavailable.") from None
                        factory = AsyncClient
                    self._client = factory(follow_redirects=False, trust_env=False, verify=True)
                context = self._client.stream("GET", url, timeout=timeout)
                response = await context.__aenter__()
                entered = True
                _protect_httpx_response_close(response)
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=MAX_HTTP_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise OSError("Invalid HTTP byte stream.")
                    if len(body) + len(chunk) > max_bytes:
                        raise HttpBodyTooLargeError()
                    body.extend(chunk)
                return HttpResponse(response.status_code, bytes(body))
        except TimeoutError:
            raise TimeoutError("HTTP request timed out.") from None
        except OSError:
            raise OSError("HTTP transport unavailable.") from None
        except HttpBodyTooLargeError:
            raise
        except Exception as error:
            # Injected clients remain independent of the optional HTTPX import.
            # Inspecting the exception hierarchy also handles real HTTPX clients
            # supplied through the factory without importing their module here.
            hierarchy = type(error).__mro__
            if any(cls.__module__.startswith("httpx") and cls.__name__ == "TimeoutException"
                   for cls in hierarchy):
                raise TimeoutError("HTTP request timed out.") from None
            if any(cls.__module__.startswith("httpx") and cls.__name__ == "DecodingError"
                   for cls in hierarchy):
                # The transport delivered a response, but its encoded body is
                # invalid. Preserve the payload/transport distinction without
                # importing HTTPX for an injected client or exposing its text.
                raise _InvalidResponse() from None
            if any(cls.__module__.startswith("httpx") and cls.__name__ == "HTTPError"
                   for cls in hierarchy):
                raise OSError("HTTP transport unavailable.") from None
            raise
        finally:
            try:
                if entered:
                    await _cleanup(context.__aexit__(None, None, None))
            finally:
                self._active = None

    async def close(self) -> None:
        """幂等关闭响应、在途任务和 client，清理共享 250ms 预算。"""
        if self._closed:
            return
        self._closed = True
        deadline = asyncio.get_running_loop().time() + 0.24
        active = self._active
        if active is not None and active is not asyncio.current_task():
            if not active.cancelling():
                active.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(active), timeout=0.21)
            except (asyncio.CancelledError, Exception):
                pass
        if self._client is not None:
            await _cleanup(self._client.aclose(), max(0.001, deadline - asyncio.get_running_loop().time()))


class _InvalidResponse(ValueError):
    pass


class _MissingIdentity(ValueError):
    pass


def _decode(body: bytes) -> str:
    if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BYTES:
        raise _InvalidResponse()
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise _InvalidResponse() from None


def _json_object(body: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _InvalidResponse()
            result[key] = value
        return result

    def invalid_constant(value):
        raise _InvalidResponse()

    try:
        value = json.loads(_decode(body), object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise _InvalidResponse() from None
    if not isinstance(value, dict):
        raise _InvalidResponse()
    return value


def _check_version(body: bytes) -> None:
    if _json_object(body).get("version") != SUPPORTED_VERSION:
        raise _InvalidResponse()


def _check_models(body: bytes, identity: str) -> None:
    catalog = _json_object(body).get("data")
    if not isinstance(catalog, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
        for entry in catalog
    ):
        raise _InvalidResponse()
    if not any(entry["id"] == identity for entry in catalog):
        raise _MissingIdentity()


_NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
_LABEL = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE]([+-]?[0-9]+))?\Z")


def _sample(line: str) -> tuple[str, dict[str, str], str]:
    """Scan quoted Prometheus labels before separating the value token."""
    match = _NAME.match(line)
    if match is None:
        raise _InvalidResponse()
    name = match.group()
    position = match.end()
    labels: dict[str, str] = {}
    if position < len(line) and line[position] == "{":
        position += 1
        while True:
            while position < len(line) and line[position].isspace():
                position += 1
            if position < len(line) and line[position] == "}":
                position += 1
                break
            match = _LABEL.match(line, position)
            if match is None:
                raise _InvalidResponse()
            label = match.group()
            position = match.end()
            while position < len(line) and line[position].isspace():
                position += 1
            if position >= len(line) or line[position] != "=":
                raise _InvalidResponse()
            position += 1
            while position < len(line) and line[position].isspace():
                position += 1
            if position >= len(line) or line[position] != '"':
                raise _InvalidResponse()
            position += 1
            value = []
            while position < len(line) and line[position] != '"':
                character = line[position]
                position += 1
                if character == "\\":
                    if position >= len(line) or line[position] not in ('n', '"', "\\"):
                        raise _InvalidResponse()
                    character = {"n": "\n", '"': '"', "\\": "\\"}[line[position]]
                    position += 1
                value.append(character)
            if position >= len(line) or label in labels:
                raise _InvalidResponse()
            labels[label] = "".join(value)
            if len(labels) > MAX_LABELS_PER_SERIES:
                raise _InvalidResponse()
            position += 1
            while position < len(line) and line[position].isspace():
                position += 1
            if position >= len(line) or line[position] not in (",", "}"):
                raise _InvalidResponse()
            if line[position] == "}":
                position += 1
                break
            position += 1
    if position >= len(line) or not line[position].isspace():
        raise _InvalidResponse()
    tokens = line[position:].split()
    if len(tokens) not in (1, 2):
        raise _InvalidResponse()
    if len(tokens) == 2 and not re.fullmatch(r"[+-]?[0-9]+", tokens[1]):
        raise _InvalidResponse()
    return name, labels, tokens[0]


def _decimal(token: str) -> Decimal:
    if len(token) > MAX_NUMBER_CHARACTERS:
        raise ValueError()
    match = _NUMBER.fullmatch(token)
    if match is None or (match[1] is not None and abs(int(match[1])) > MAX_DECIMAL_EXPONENT):
        raise ValueError()
    try:
        number = Decimal(token)
    except InvalidOperation:
        raise ValueError() from None
    if not number.is_finite() or number < 0:
        raise ValueError()
    return number


def _integer(token: str) -> int:
    number = _decimal(token)
    if (number != 0 and number.adjusted() >= MAX_INTEGER_DIGITS) or number != number.to_integral_value():
        raise ValueError()
    return int(number)


def _real(token: str) -> float:
    number = float(_decimal(token))
    if not math.isfinite(number):
        raise ValueError()
    return number


def _check_ignored_value(token: str) -> None:
    """Validate discarded exposition without applying business-field semantics.

    Negative/fractional values and the Prometheus nonfinite spellings remain
    legal for independent series. Resource limits still apply, even though no
    business value will be built from the token. Required target fields keep
    their separate group-local validation and failure behavior.
    """
    if len(token) > MAX_NUMBER_CHARACTERS:
        raise _InvalidResponse()
    if token in ("NaN", "+Inf", "-Inf", "Inf"):
        return
    match = _NUMBER.fullmatch(token)
    if match is None or (match[1] is not None and abs(int(match[1])) > MAX_DECIMAL_EXPONENT):
        raise _InvalidResponse()
    number = Decimal(token)
    if (number != 0 and number == number.to_integral_value()
            and number.adjusted() >= MAX_INTEGER_DIGITS):
        raise _InvalidResponse()


def _raw_observation(config: ModelConfig, metrics: bytes) -> tuple[VllmObservation, bool]:
    identity = config.served_model_name or config.name
    chat = config.type is ModelType.CHAT
    gauges = {"vllm:num_requests_running", "vllm:num_requests_waiting"}
    counters = {"vllm:prompt_tokens", "vllm:generation_tokens"} if chat else {"vllm:request_success"}
    histograms = {"vllm:request_queue_time_seconds", (
        "vllm:time_to_first_token_seconds" if chat else "vllm:e2e_request_latency_seconds")}
    if chat:
        gauges.add("vllm:kv_cache_usage_perc")
    targets = set(gauges)
    for base in counters:
        targets.update((base + "_total", base + "_created"))
    for base in histograms:
        targets.update(base + suffix for suffix in ("_sum", "_count", "_created", "_bucket"))
    series: dict[str, dict[str, str]] = {}
    seen = set()
    process_started_at = None
    process_seen = False
    sample_count = 0
    for raw_line in _decode(metrics).split("\n"):
        if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
            raise _InvalidResponse()
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sample_count += 1
        if sample_count > MAX_SAMPLE_LINES:
            raise _InvalidResponse()
        name, labels, value = _sample(line)
        if name == "process_start_time_seconds":
            if process_seen or labels:
                raise _InvalidResponse()
            process_seen = True
            try:
                process_started_at = _real(value)
            except ValueError:
                raise _InvalidResponse() from None
            continue
        if name not in targets:
            _check_ignored_value(value)
            continue
        if "model_name" not in labels:
            raise _InvalidResponse()
        if labels["model_name"] != identity:
            _check_ignored_value(value)
            continue
        expected = {"model_name", "engine"}
        if name.endswith("_bucket"):
            expected.add("le")
        if name in {"vllm:request_success_total", "vllm:request_success_created"}:
            expected.add("finished_reason")
        if (set(labels) != expected or not labels.get("engine")
                or not labels["engine"].isprintable()):
            raise _InvalidResponse()
        key = (name, tuple(sorted(labels.items())))
        if key in seen:
            raise _InvalidResponse()
        seen.add(key)
        fields = series.setdefault(labels["engine"], {})
        if name.endswith("_bucket") or labels.get("finished_reason", "stop") != "stop":
            _check_ignored_value(value)
            continue
        fields[name] = value
    if not series:
        raise _MissingIdentity()
    partial = False
    engines = []
    for engine_id, fields in series.items():
        def group(read):
            nonlocal partial
            try:
                return read()
            except (KeyError, ValueError):
                partial = True
                return None

        def created(base):
            token = fields.get(base + "_created")
            return None if token is None else _real(token)

        def counter(base):
            return CounterSample(_integer(fields[base + "_total"]), created(base))

        def latency(base):
            seconds = _real(fields[base + "_sum"])
            count = _integer(fields[base + "_count"])
            if count == 0 and seconds != 0:
                raise ValueError()
            return LatencySample(seconds, count, created(base))

        def kv():
            value = _real(fields["vllm:kv_cache_usage_perc"])
            if value > 1:
                raise ValueError()
            return value

        common = dict(
            engine_id=engine_id,
            running=group(lambda: _integer(fields["vllm:num_requests_running"])),
            waiting=group(lambda: _integer(fields["vllm:num_requests_waiting"])),
            queue=group(lambda: latency("vllm:request_queue_time_seconds")),
        )
        if chat:
            engines.append(ChatEngineSample(
                **common, kv_cache_fraction=group(kv),
                prompt_tokens=group(lambda: counter("vllm:prompt_tokens")),
                generation_tokens=group(lambda: counter("vllm:generation_tokens")),
                ttft=group(lambda: latency("vllm:time_to_first_token_seconds")),
            ))
        else:
            engines.append(PoolingEngineSample(
                **common, completed_sequences=group(lambda: counter("vllm:request_success")),
                latency=group(lambda: latency("vllm:e2e_request_latency_seconds")),
            ))
    return VllmObservation(config.type, identity, tuple(engines), process_started_at), partial


def parse_scrape(
    config: ModelConfig,
    *,
    version: bytes,
    models: bytes,
    metrics: bytes,
) -> VllmCollectionResult:
    """纯解析三份字节，返回 config.id 的不可变 vLLM 语义观测。

    版本必须精确为0.31.0；期望身份为 config.served_model_name or config.name，
    必须在 /v1/models 的 data[].id 与所用metrics的model_name中精确匹配。
    身份不匹配使用 not_found/object.not_found；非法版本/JSON/UTF-8/整体
    exposition结构使用 parse/response.invalid。整对象失败返回同一结果子类，
    observation=None并携带Failure；结果无metrics或vllm字段。
    JSON拒重复key，不把原始正文/任意异常/URL放入Failure或打印。

    每份输入最多2MiB；metrics单行最多64KiB、样本行最多50000、单series
    标签最多16。超限为整体response.invalid。只匹配精确指标名，规范化label
    顺序后重复目标series、缺少model_name/engine或额外目标标签为整体结构
    失败，不将重复导出累加。合法未知指标/其他model的独立series可忽略。
    Prometheus标签须正确处理转义，不能按逗号/正则随意拆引号内容。

    引擎观测按engine标识保留，不汇总、不推断GPU/TP个数。Chat正常及局部失败
    均构造ChatEngineSample，Embedding/Reranker均构造PoolingEngineSample；
    engines为非空同型tuple，与config.type对应，不返回裸EngineSample或混合tuple。
    两子类只保留各自适用字段，不以None占位另一类型的专属字段。核心目标字段：
    所有类型的 num_requests_running/num_requests_waiting；Chat的
    prompt_tokens_total、generation_tokens_total、time_to_first_token_seconds
    的sum/count、request_queue_time_seconds的sum/count、kv_cache_usage_perc。
    pooling的request_success_total仅finished_reason="stop"进入completed_sequences，
    queue同上，latency为e2e_request_latency_seconds的sum/count；其他完成reason
    不进入RATE。pooling不要求prompt/generation/TTFT/KV来源，载荷不含这些属性；
    Chat不要求completed_sequences或latency来源，载荷也不含这两个属性。
    单位由profile固定为token/seq/秒。

    本应支持字段缺失/坏值为局部response.invalid，observation保留对应子类及其余
    有效字段，坏字段None；延迟sum/count原子成组，不能混用新旧值。running/waiting是非负
    整数；KV为[0,1]有限ratio；sum非负有限，count非负整数，count=0时sum=0。
    数值token长度<=128，十进制指数绝对值<=400，展开整数<=400位，拒NaN/Inf、
    负数和非整数计数。计数经精确Decimal语义解析，不能先float后int。

    process_start_time_seconds及对应_created可选，缺失不失败；出现则验证为
    非负有限时间。非法process marker是整体结构失败，非法_created使对应字段
    组局部失败。_created不是计数，bucket不相加，le="+Inf"仅是标签。
    成功返回VllmCollectionResult(observation=VllmObservation, failure=None)，
    不计算rate/mean/Total，也不携带展示metrics。
    输入只在本函数及其纯解析辅助函数内存在。
    """
    try:
        _check_version(version)
        _check_models(models, config.served_model_name or config.name)
        observation, partial = _raw_observation(config, metrics)
    except _MissingIdentity:
        return _failed(config, ErrorKind.NOT_FOUND)
    except _InvalidResponse:
        return _failed(config, ErrorKind.PARSE)
    return VllmCollectionResult(ObjectKey("vllm", config.id), observation,
                                failure=_failure(ErrorKind.PARSE) if partial else None)


class VllmCollector:
    """每配置模型一个Collector，独占HttpPort；构造只保存依赖与静态spec。

    每次collect严格按 /version → /v1/models → /metrics 顺序GET，使用同一
    timeout总预算，后续请求只获得剩余预算；不各自重新获得完整timeout。
    三次响应每份最多MAX_RESPONSE_BYTES。每轮重新校验版本和身份，不能因
    之前成功永久缓存身份。所有端点来自config.base_url，不访问其他地址。

    HTTP401/403映射permission/access.denied，404映射not_found/object.not_found；
    其余非200（含3xx）映射unavailable/source.unavailable。状态类型/格式错误
    归parse/response.invalid。异常TimeoutError映射collection.timeout，OSError
    映射source.unavailable，HttpBodyTooLargeError映射response.invalid。版本和
    models身份在取得对应响应后即校验，失败不继续后续端点；不重试。取消须传播，
    不能变成VllmCollectionResult失败。
    未知异常交Monitor统一处理。close幂等委托端口，取消在途collect并清理。
    """

    def __init__(self, config: ModelConfig, http: HttpPort, timeout: float = 3.0) -> None:
        if not _positive_time(timeout):
            raise ValueError("Invalid collection timeout.")
        self.config = config
        self.http = http
        self.timeout = timeout
        self.spec = make_vllm_spec(config)
        self._closed = False
        self._active: asyncio.Task | None = None

    async def collect(self) -> VllmCollectionResult:
        """执行单预算三次只读请求，逐步核对身份后调用纯 parser。"""
        if self._closed:
            raise RuntimeError("Collector is closed.")
        if self._active is not None:
            raise RuntimeError("Collector is already sampling.")
        self._active = asyncio.current_task()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        bodies = []
        try:
            async with asyncio.timeout(self.timeout):
                for path in METRICS_PATHS:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError()
                    response = await self.http.get(self.config.base_url.rstrip("/") + path,
                                                   timeout=remaining, max_bytes=MAX_RESPONSE_BYTES)
                    if (not isinstance(response, HttpResponse) or type(response.status) is not int
                            or not 100 <= response.status <= 599):
                        return _failed(self.config, ErrorKind.PARSE)
                    if response.status != 200:
                        kind = {401: ErrorKind.PERMISSION, 403: ErrorKind.PERMISSION,
                                404: ErrorKind.NOT_FOUND}.get(response.status, ErrorKind.UNAVAILABLE)
                        return _failed(self.config, kind)
                    # Check transport substitutes too, before subsequent requests.
                    _decode(response.body)
                    if path == "/version":
                        _check_version(response.body)
                    elif path == "/v1/models":
                        _check_models(response.body, self.config.served_model_name or self.config.name)
                    bodies.append(response.body)
                return parse_scrape(self.config, version=bodies[0], models=bodies[1], metrics=bodies[2])
        except TimeoutError:
            return _failed(self.config, ErrorKind.TIMEOUT)
        except OSError:
            return _failed(self.config, ErrorKind.UNAVAILABLE)
        except (HttpBodyTooLargeError, _InvalidResponse):
            return _failed(self.config, ErrorKind.PARSE)
        except _MissingIdentity:
            return _failed(self.config, ErrorKind.NOT_FOUND)
        finally:
            self._active = None

    async def close(self) -> None:
        """幂等取消采样并关闭独占端口，清理共享 250ms 预算。"""
        if self._closed:
            return
        self._closed = True
        deadline = asyncio.get_running_loop().time() + 0.24
        active = self._active
        if active is not None and active is not asyncio.current_task():
            if not active.cancelling():
                active.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(active), timeout=0.21)
            except (asyncio.CancelledError, Exception):
                pass
        await _cleanup(self.http.close(), max(0.001, deadline - asyncio.get_running_loop().time()))


def build_vllm_collectors(
    config: AppConfig,
    *,
    http_factory: Callable[[], HttpPort] | None = None,
) -> tuple[VllmCollector, ...]:
    """为全部config.models按顺序创建采集器，不按选择/屏幕容量裁剪。

    每个模型只调用factory一次并独占返回端口，无模型时不调用factory。
    默认每项独立AsyncHttpClient，无请求/导入HTTPX；同名/同origin不同id不合并。
    使用config.collection_timeout，不更改配置、创建日志或执行采集。
    工厂与每个端口的构造均不执行网络 IO。
    """
    factory = http_factory or AsyncHttpClient
    return tuple(VllmCollector(model, factory(), timeout=config.collection_timeout)
                 for model in config.models)
