"""启动配置的本地查找、严格 YAML 校验与不可变配置载体。

本模块只负责本地文件查找、YAML 解码及结构校验，不探测 GPU、挂载点、
Docker 或服务地址，不创建日志目录，不修改源配置。配置解析成功才允许
进入全屏及创建采集任务。配置错误不属于采集失败，不写 error.log。

完整 YAML 安全检查先于应用层校验：挂载点仅纳入原列表前 3 项，
容器全部校验并按配置顺序纳入，均不受终端显示容量影响。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import ipaddress
import math
import re
from urllib.parse import urlsplit

import yaml


# SafeLoader's standard scalar constructors use native exceptions for malformed
# input: empty/sign-only numbers can raise IndexError, and an unmatched timestamp
# can raise AttributeError. Keep the node and document boundaries in agreement.
_YAML_VALUE_ERRORS = (ValueError, TypeError, LookupError, AttributeError, OverflowError)


class ConfigError(ValueError):
    """可在全屏前展示的本地配置错误。

    ``path`` 是绝对配置路径，``field`` 是字段路径（例如
    ``models[1].id``；列表下标从 0 开始），文件错误使用 ``<file>``。
    YAML 语法/重复键错误的 ``line`` / ``column`` 是 1 起始位置；无法定位
    时为 None。str(error) 必须包含 path、field 和英文修复原因，不回显
    原始 YAML 行、URL 凭据、任意配置值或原始异常堆栈。

    缺文件、无读取权限、UTF-8/YAML 错误、重复键、未知字段和字段非法都
    归入此异常；日志目录的实际可写性不是配置校验内容。
    """

    path: Path
    field: str
    line: int | None
    column: int | None

    def __init__(self, path: Path, field: str, reason: str, *,
                 line: int | None = None, column: int | None = None) -> None:
        self.path = path.absolute()
        self.field = field
        self.line = line
        self.column = column
        location = f"{self.path}: {field}"
        if line is not None:
            location += f" (line {line}, column {column})"
        super().__init__(f"{location}: {reason}")


class ModelType(str, Enum):
    """三个支持的模型类型；YAML 使用精确的小写值，不推断模型类型。"""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANKER = "reranker"


@dataclass(frozen=True)
class ContainerConfig:
    """一项显式容器配置。

    id 是应用内稳定标识，符合 [A-Za-z0-9][A-Za-z0-9_.-]{0,63}，在实际
    完整 containers 列表中唯一。name 是真实 Docker 名称或完整容器 ID，1～128
    个可打印字符，不含控制字符/首尾空白；不能把 Compose 项目名当成
    真实容器名。匹配及生命周期采集交由 REQ-003，读取配置不访问 Docker。
    """

    id: str
    name: str


@dataclass(frozen=True)
class ModelConfig:
    """一项 vLLM 监控配置；列表次序即展示次序。

    id 规则同 ContainerConfig，在 models 内唯一；不同 id 可以使用相同
    name，不能据此合并。name 是 1～128 个可打印字符的展示名称，禁止
    首尾空白和控制字符。type 为 ModelType；base_url 为绝对 http/https
    origin（主机名及可选有效端口），允许一个结尾 / 并在加载时移除，
    禁止 userinfo、查询、片段和 /v1 等其他路径。它指向直接 vLLM 服务，
    不是 LiteLLM 网关或推理 API；服务身份是否正确不能离线验证。

    gpu_ids 为显式 GPU 索引字符串或 GPU UUID 字符串的不可变序列，
    每项 1～128 个非空白可打印字符，不重复。空 tuple 表示映射未知，
    展示层不猜测；不检查当前设备是否存在，也不从地址/名称推断映射。
    """

    id: str
    type: ModelType
    name: str
    base_url: str
    gpu_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogConfig:
    """采集 ERROR 文件设置；载体本身不执行 I/O 或校验。

    directory 的 YAML 值只能是运行平台绝对路径或 ~ / ~/... 形式，
    load_config 按运行用户 Path.home() 展开；不展开 $ENV、%ENV% 或 ~other。
    默认目录 ~/.joi-observer，与 XDG 配置无关。返回的有效配置中它是绝对
    Path；不存在/不可写由日志初始化处理，不在此创建或检查。

    max_bytes 为整数且 >=1024，默认 10,000,000 字节（十进制 10 MB），
    backup_count 为整数且 >=1，默认 3；bool 不视为整数。文件名固定
    error.log，不允许配置文件名。最小阈值用于容纳单条有界诊断记录。
    """

    directory: Path = Path("~/.joi-observer")
    max_bytes: int = 10_000_000
    backup_count: int = 3


@dataclass(frozen=True)
class AppConfig:
    """启动后不可变的配置快照；不支持热重载。

    sample_interval、collection_timeout 单位均为秒，是有限实数且位于
    [0.1, 60.0]，不接受 bool、字符串、NaN/Infinity。timeout 可超过
    interval；调度器负责同对象不重叠和跳过错过的周期，不积压请求。

    mount_points 是有序、无重复的 POSIX 绝对挂载点，禁止 ..、控制字符、
    首尾空白；保持原字符串，不静默改变路径。缺省为 / 和 /data，显式
    空列表关闭挂载项。完整 YAML 校验后只校验并纳入原始 mount_points
    列表的前 3 项，尾项不作路径/类型/重复项等应用层校验；不能跳过前
    3 项中的错误并以后续项补位，采集失败时也不重新选择目标。

    containers/models 缺省或 [] 表示相应空态；null 不等价于空列表。
    containers 不设固定数量上限，全部逐项校验并按配置顺序返回，所有
    纳入对象均采集；仅展示层按可用行数隐藏后续容器，不改变此快照。

    dataclass 仅声明载体；生产代码须使用 load_config 返回的有效配置。
    直接构造实例不会自动验证任何字段，也不会展开 LogConfig 默认路径。
    """

    sample_interval: float = 1.0
    collection_timeout: float = 3.0
    mount_points: tuple[str, ...] = ("/", "/data")
    containers: tuple[ContainerConfig, ...] = ()
    models: tuple[ModelConfig, ...] = ()
    logging: LogConfig = field(default_factory=LogConfig)


def resolve_config_path(
    explicit: str | Path | None, *, cwd: Path, home: Path
) -> Path:
    """选择本地用户配置，绝不将包内示例作为默认目标。

    Args:
        explicit: --config 的原始路径；None 表示使用默认查找。相对路径
            相对 cwd，~/... 相对给定 home；空字符串非法，不展开环境变量。
        cwd: 绝对当前目录，由 CLI 获取；无副作用，不更改进程工作目录。
        home: 绝对用户主目录，由 CLI 获取，便于离线测试隔离用户文件。

    Returns:
        绝对配置路径。优先级为 explicit > cwd/config.yaml >
        home/.joi-observer/config.yaml。存在的高优先级候选即被选中，
        即使不可读/非法也不回退；文件内容由 load_config 解析。

    Raises:
        ConfigError: 显式路径不存在、候选是目录、无候选或路径无效。
            无默认文件时 path 指向 home/.joi-observer/config.yaml，消息
            需列出 cwd 候选、期望路径及 example_config_path() 的位置，
            使 CLI 可提示复制示例。explicit 缺失只报告该指定路径，不回退。

    本函数仅查找文件，不读配置内容、不写文件、不联网、不采集。
    """
    expected = home / ".joi-observer" / "config.yaml"
    if explicit is not None:
        raw = str(explicit)
        if not raw or any(not c.isprintable() for c in raw):
            raise ConfigError(expected, "<file>", "Specify a valid configuration path.")
        if raw == "~" or raw.startswith("~/") or raw.startswith("~\\"):
            candidate = home / raw[2:] if len(raw) > 1 else home
        else:
            candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidates = (candidate,)
    else:
        candidates = (cwd / "config.yaml", expected)
    for candidate in candidates:
        candidate = candidate.absolute()
        try:
            # stat detects inaccessible paths; they must not trigger fallback.
            candidate.stat()
        except FileNotFoundError:
            if explicit is not None or candidate.is_symlink():
                raise ConfigError(candidate, "<file>", "Configuration file does not exist.") from None
            continue
        except (OSError, ValueError):
            raise ConfigError(candidate, "<file>", "Cannot access configuration file.") from None
        if not candidate.is_file():
            raise ConfigError(candidate, "<file>", "Configuration path must be a regular file.")
        return candidate
    raise ConfigError(expected, "<file>",
                      f"No configuration found. Checked {cwd / 'config.yaml'} and {expected}. "
                      f"Copy and edit the example at {example_config_path()}.")


def load_config(path: Path) -> AppConfig:
    """读取 UTF-8 YAML 并返回一次性、不可变的有效启动配置。

    Args:
        path: 已选择的绝对配置路径；本函数也必须独立处理文件消失、
            无读取权限等 TOCTOU 情况，不要求调用方先检查存在。

    Returns:
        AppConfig。仅空 mapping ``{}`` 允许采用字段默认值；空文档、null、
        顶层序列/标量非法。字段与 dataclass 同名；models 每项必填 id、
        type、name、base_url，containers 每项必填 id、name；logging
        内各项可省略。数值转为 float，序列转为 tuple，日志目录展开为
        Path。完整 YAML 校验后，挂载点先取原始列表前 3 项再验证其
        路径/类型/唯一性，后续项不作应用层校验、不采集、不补位。
        容器不截断，整个列表逐项验证字段及 ID 唯一性并保持原顺序；
        显示容量不参与配置解析。无论保留或忽略多少项，都不写回源文件。

    Raises:
        ConfigError: 文件/解码/YAML/字段错误；错误携带 path、field 及
            可取得的行列。整个 YAML 文档拒绝重复 key、不支持的标签、
            递归别名及无法构造的标准类型标量，包含忽略的挂载点尾项；
            这些错误仍提供安全的字段/行列定位，不能泄漏原始值或堆栈。
            所有实际纳入的字段层次拒绝未知 key 和隐式类型转换；第四个
            挂载点起的合法 YAML 值不作应用层校验。不得捕获错误后静默
            使用默认监控目标，也不得用尾项替换前三项中的非法配置。

    Side effects:
        只读取 path。不修改文件、不创建目录、不读环境凭据、不访问任何
        监控对象；仅为 ~ 展开读取运行用户 home。成功校验不证明目标
        已存在/可达，后续真实失败由采集器报告。配置错误只由 CLI 在
        全屏前展示，不写采集 ERROR 文件。
    """
    path = path.absolute()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        raise ConfigError(path, "<file>", "Cannot read a UTF-8 configuration file.") from None
    try:
        loader = _ConfigLoader(source)
        try:
            root = loader.get_single_node()
            # Inspect every node, including structurally ignored mount tails.
            # Store marks separately so field errors never echo source lines.
            marks: dict[str, tuple[int, int]] = {}
            _inspect_yaml(root, "", marks, set(), path, loader)
            data = loader.construct_document(root) if root is not None else None
        finally:
            loader.dispose()
    except ConfigError:
        raise
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise ConfigError(path, "<file>", "Invalid YAML syntax, key, or tag.",
                          line=mark.line + 1 if mark else None,
                          column=mark.column + 1 if mark else None) from None
    except _YAML_VALUE_ERRORS:
        raise ConfigError(path, "<file>", "Invalid YAML value for its declared type.") from None
    validator = _Validator(path, marks)
    data = validator.mapping(data, "", {"sample_interval", "collection_timeout", "mount_points", "containers", "models", "logging"})
    interval = validator.timing(data.get("sample_interval", 1.0), "sample_interval")
    timeout = validator.timing(data.get("collection_timeout", 3.0), "collection_timeout")
    mounts = validator.sequence(data.get("mount_points", ["/", "/data"]), "mount_points")
    mount_values: list[str] = []
    for i, value in enumerate(mounts[:3]):
        key = f"mount_points[{i}]"
        if (not isinstance(value, str) or not value.startswith("/") or
                value.strip() != value or not value.isprintable() or ".." in value.split("/")):
            validator.fail(key, "Use a POSIX absolute path without parent traversal or control characters.")
        if value in mount_values:
            validator.fail(key, "Mount points must be unique.")
        mount_values.append(value)
    containers: list[ContainerConfig] = []
    container_ids: set[str] = set()
    for i, value in enumerate(validator.sequence(data.get("containers", []), "containers")):
        key = f"containers[{i}]"
        item = validator.mapping(value, key, {"id", "name"}, {"id", "name"})
        identity = validator.identity(item["id"], key + ".id", container_ids)
        containers.append(ContainerConfig(identity, validator.name(item["name"], key + ".name")))
    models: list[ModelConfig] = []
    model_ids: set[str] = set()
    for i, value in enumerate(validator.sequence(data.get("models", []), "models")):
        key = f"models[{i}]"
        item = validator.mapping(value, key, {"id", "type", "name", "base_url", "gpu_ids"}, {"id", "type", "name", "base_url"})
        identity = validator.identity(item["id"], key + ".id", model_ids)
        if not isinstance(item["type"], str) or item["type"] not in {t.value for t in ModelType}:
            validator.fail(key + ".type", "Use chat, embedding, or reranker.")
        gpu_ids: list[str] = []
        for j, gpu in enumerate(validator.sequence(item.get("gpu_ids", []), key + ".gpu_ids")):
            field_path = f"{key}.gpu_ids[{j}]"
            gpu = validator.name(gpu, field_path)
            if any(c.isspace() for c in gpu) or gpu in gpu_ids:
                validator.fail(field_path, "GPU identifiers must be unique and contain no whitespace.")
            gpu_ids.append(gpu)
        models.append(ModelConfig(identity, ModelType(item["type"]),
                                  validator.name(item["name"], key + ".name"),
                                  validator.origin(item["base_url"], key + ".base_url"), tuple(gpu_ids)))
    log = validator.mapping(data.get("logging", {}), "logging", {"directory", "max_bytes", "backup_count"})
    directory = log.get("directory", "~/.joi-observer")
    if not isinstance(directory, str) or not directory or not directory.isprintable() or directory != directory.strip():
        validator.fail("logging.directory", "Use an absolute path or ~/path.")
    if directory == "~" or directory.startswith("~/"):
        directory_path = Path.home() / directory[2:] if len(directory) > 1 else Path.home()
    else:
        directory_path = Path(directory)
        if not directory_path.is_absolute():
            validator.fail("logging.directory", "Use an absolute path or ~/path.")
    max_bytes = validator.integer(log.get("max_bytes", 10_000_000), "logging.max_bytes", 1024)
    backup_count = validator.integer(log.get("backup_count", 3), "logging.backup_count", 1)
    return AppConfig(interval, timeout, tuple(mount_values), tuple(containers), tuple(models),
                     LogConfig(directory_path, max_bytes, backup_count))


def example_config_path() -> Path:
    """返回安装包内 examples/config.yaml 的绝对可读路径。

    标准 wheel/editable 安装须包含该资源；资源仅供用户复制修改。
    不复制、不解析、不回退加载，调用本函数不得启动任何采集。
    """
    return Path(__file__).resolve().parent / "examples" / "config.yaml"


class _ConfigLoader(yaml.SafeLoader):
    """SafeLoader with validation performed on its complete composed node tree."""


def _inspect_yaml(node, field, marks, active, path, loader, *, ignored_mount_tail=False):
    if node is None:
        return
    mark = node.start_mark
    marks[field or "<file>"] = (mark.line + 1, mark.column + 1)
    if id(node) in active:
        raise ConfigError(path, field or "<file>", "Recursive YAML aliases are not supported.",
                          line=mark.line + 1, column=mark.column + 1)
    if node.tag not in yaml.SafeLoader.yaml_constructors:
        raise ConfigError(path, field or "<file>", "Unsupported YAML tag.",
                          line=mark.line + 1, column=mark.column + 1)
    active.add(id(node))
    try:
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key, value in node.value:
                string_key = isinstance(key, yaml.ScalarNode) and key.tag == "tag:yaml.org,2002:str"
                if not string_key and not ignored_mount_tail:
                    raise ConfigError(path, field or "<file>", "Mapping keys must be strings.",
                                      line=key.start_mark.line + 1, column=key.start_mark.column + 1)
                # Unknown keys are safe field labels only if they look like identifiers.
                label = key.value if string_key and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.value) else "<key>"
                child = f"{field}.{label}" if field else label
                identity = key.value
                if ignored_mount_tail:
                    # Ignored YAML mappings may use any SafeLoader-compatible
                    # key. Still validate keys as data, including tags, aliases
                    # and native scalar-construction failures before hashing.
                    _inspect_yaml(key, child, marks, active, path, loader, ignored_mount_tail=True)
                    try:
                        identity = loader.construct_object(key, deep=True)
                        hash(identity)
                    except _YAML_VALUE_ERRORS:
                        raise ConfigError(path, child, "Invalid YAML mapping key.",
                                          line=key.start_mark.line + 1,
                                          column=key.start_mark.column + 1) from None
                if identity in seen:
                    raise ConfigError(path, child, "Duplicate YAML key.",
                                      line=key.start_mark.line + 1, column=key.start_mark.column + 1)
                seen.add(identity)
                _inspect_yaml(value, child, marks, active, path, loader,
                              ignored_mount_tail=ignored_mount_tail)
        elif isinstance(node, yaml.SequenceNode):
            for i, value in enumerate(node.value):
                _inspect_yaml(value, f"{field}[{i}]", marks, active, path, loader,
                              ignored_mount_tail=ignored_mount_tail or field == "mount_points" and i >= 3)
        else:
            # Normalize at the scalar's own mark, including ignored mount
            # tails, without exposing the constructor's exception or source text.
            try:
                loader.construct_object(node)
            except _YAML_VALUE_ERRORS:
                raise ConfigError(path, field or "<file>", "Invalid YAML value for its declared type.",
                                  line=mark.line + 1, column=mark.column + 1) from None
    finally:
        active.remove(id(node))


class _Validator:
    def __init__(self, path, marks):
        self.path, self.marks = path, marks

    def fail(self, field, reason):
        location = field or "<file>"
        while location not in self.marks and location != "<file>":
            parent = re.sub(r"(?:\.[^.\[]+|\[\d+\])$", "", location)
            location = parent if parent and parent != location else "<file>"
        line, column = self.marks.get(location, (None, None))
        raise ConfigError(self.path, field or "<file>", reason, line=line, column=column)

    def mapping(self, value, field, allowed, required=frozenset()):
        if not isinstance(value, dict):
            self.fail(field, "Expected a mapping.")
        for key in value:
            if key not in allowed:
                label = key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else "<key>"
                self.fail(f"{field}.{label}" if field else label, "Unknown field.")
        for key in sorted(required - value.keys()):
            self.fail(f"{field}.{key}", "Required field is missing.")
        return value

    def sequence(self, value, field):
        if not isinstance(value, list):
            self.fail(field, "Expected a list.")
        return value

    def timing(self, value, field):
        if type(value) not in (int, float) or not 0.1 <= value <= 60 or not math.isfinite(value):
            self.fail(field, "Use a finite number from 0.1 through 60 seconds.")
        return float(value)

    def integer(self, value, field, minimum):
        if type(value) is not int or value < minimum:
            self.fail(field, f"Use an integer of at least {minimum}.")
        return value

    def name(self, value, field):
        if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.isprintable() or value.strip() != value:
            self.fail(field, "Use 1 to 128 printable characters without surrounding whitespace.")
        return value

    def identity(self, value, field, seen):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            self.fail(field, "Use a 1 to 64 character stable identifier (letters, digits, _, ., -).")
        if value in seen:
            self.fail(field, "Identifiers must be unique within the list.")
        seen.add(value)
        return value

    def origin(self, value, field):
        valid = (isinstance(value, str) and value and "\\" not in value
                 and all(c.isprintable() and not c.isspace() for c in value))
        try:
            parts = urlsplit(value) if valid else None
            valid = (valid and parts.scheme in ("http", "https") and parts.hostname
                     and parts.username is None and parts.password is None
                     and parts.path in ("", "/") and "?" not in value and "#" not in value
                     and parts.port != 0 and not parts.netloc.endswith(":"))
            if valid:
                host = parts.hostname
                if ":" in host:
                    ipaddress.IPv6Address(host)
                else:
                    hostname = host.encode("idna").decode("ascii").removesuffix(".")
                    valid = len(hostname) <= 253 and all(
                        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                        for label in hostname.split("."))
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            self.fail(field, "Use an HTTP/HTTPS origin with a valid host and port, without credentials, query, fragment, or path.")
        return value[:-1] if value.endswith("/") else value
