# Docker 容器采集模块设计

- 关联需求：dev-0 / REQ-003，requirements.md v1.12，AC-301～304；依赖 REQ-001 的配置、调度、状态、日志与布局。
- 修订：v1.0，2026-10-30，R2 首次设计。
- 相关代码：`src/joi_observer/collectors/docker.py`、`config.py::ContainerConfig`、`cli.py::ApplicationRuntime`。
- 关联模块：[配置](configuration.md)、[Monitor / State](monitor-state.md)、[错误日志](error-logging.md)、[应用外壳](application-shell.md)。

## 职责与范围

每个显式配置项独立读取一个本机容器的生命周期，输出现有 `CollectionResult`。全量配置参与采集，显示层自行取可见前缀。模块不依赖终端，不写状态或日志，不发现其他容器，不读取资源统计、容器日志或业务负载，不执行启停、重启或权限修改。

REQ-001 的数量、布局与错误链路已有实现；本次新增实际采集接口和黑盒契约，业务入口保持 `NotImplementedError`。组合根仅增加命令端口注入声明，真实接入留给 R4。不能把现有静态 Docker 槽位当成已经采集成功。

## 类图

```mermaid
classDiagram
    class ApplicationRuntime {
        -_docker_command_factory
        +run() None
        +close() None
    }
    class Collector {
        <<interface>>
        +spec ObjectSpec
        +collect() CollectionResult
        +close() None
    }
    class DockerCollector {
        +spec ObjectSpec
        +collect() CollectionResult
        +close() None
    }
    class DockerCommandPort {
        <<interface>>
        +run(argv, timeout) CommandOutput
        +close() None
    }
    class LocalDockerCommand
    class CommandOutput {
        +returncode int
        +stdout bytes
        +stderr bytes
    }
    class Monitor
    class MonitorState
    class CollectionResult
    Collector <|.. DockerCollector
    DockerCommandPort <|.. LocalDockerCommand
    DockerCollector *-- "1" DockerCommandPort
    DockerCollector ..> CollectionResult
    DockerCommandPort ..> CommandOutput
    ApplicationRuntime ..> DockerCollector
    Monitor --> "0..*" Collector
    Monitor --> "1" MonitorState
```

图为目标依赖结构，接口实现使用 Python 结构化 Protocol。每个采集器独占一个命令端口，避免关闭一项影响其他项。原始命令输出仅在采集模块内解析，不进入快照或日志。

## 读取边界与实现取舍

采用本机 Docker CLI 的单对象 inspect，不增加 Python Docker SDK 依赖，不解析面向人的 `docker ps` 表格。CLI 可返回停止容器，格式模板只输出身份与生命周期。命令使用参数数组，不经 shell：

```text
docker --host unix:///var/run/docker.sock container inspect --format <template> -- <config.name>
```

模板固定为代码中的 `DOCKER_INSPECT_TEMPLATE`：

```text
{"Id":{{json .Id}},"Name":{{json .Name}},"State":{"Status":{{json .State.Status}}}}
```

`LocalDockerCommand.run` 只接受上述形状、模板和非空目标，其他操作或远端 host 在创建子进程前拒绝。子进程环境复制当前环境后删除所有 `DOCKER_*`，设置 `LC_ALL=C`、`LANG=C`，不改变父环境；这样配置 context、host、TLS 或 API 版本变量不改变本机目标。stdin 为 DEVNULL，stdout/stderr 为 PIPE，禁止继承终端输出。即便目标字符串含 shell 元字符，也只是 `--` 后的单个参数，不拼接执行。

本期固定常规本机 `/var/run/docker.sock`，不自动查找 rootless socket、不回退到 context、不执行 sudo。无 CLI、无 socket、权限不足均通过采集失败链路报告，不能阻断其他来源。CLI、模板与权限在真实部署中尚未验证；这是一项待 R4 完成的本地适配契约，不是已经读取过实际 Docker 的证据。

每次 collect 只发起一次命令，不重试、不缓存永久失败、不持久缓存解析后的 ID。标准输出和错误输出分别最多 65,536 字节；两条流须并发限量读取。恰好上限可接受，超过即终止、回收进程并抛 `DockerOutputLimitError`，不能依赖无界 `communicate()` 收完才检查。CLI 格式本身避免输出环境变量、挂载、healthcheck 结果等不需要的内容。

## 身份与结果契约

`ContainerConfig.id` 是应用内身份；状态 key 恒为 `ObjectKey("docker", id)`。`name` 是 Docker 查询目标，同时沿用配置文字作为行名称。配置层继续允许其原有可打印字符范围，不在加载阶段访问 Docker或收紧为部署存在性校验。不同配置 id 指向同一目标时分别保留、分别采集。

成功输出必须是严格 UTF-8 的单个 JSON 对象，允许前后空白；拒绝数组、多个对象、重复 JSON key、缺失/类型错误字段及无效状态。`Id` 必须是 64 位小写十六进制；`Name` 必须只有一个前导 `/`，后面为非空、无空白/控制字符且不再包含 `/` 的可打印名称。

- 配置目标是 64 位小写十六进制时，按完整 ID 比较，只能匹配响应 `Id`，不能被同名但不同 ID 的容器替代。
- 其他目标按名称与响应 `Name` 去掉唯一前导 `/` 后精确比较，不做大小写折叠、子串或 Compose 名推断。
- Docker 接受短 ID 前缀不代表本工具接受；只有响应名称确实等于该短字符串时才算名称匹配。配置带前导 `/` 不自动归一化。
- 名称目标每次重新查询，因此可以跟随同名重建的新 ID；完整 ID 目标不能跟随重建改绑。合法响应不匹配配置身份，按对象未找到处理。

`State.Status` 仅接受下列精确小写值，成功结果只有一个 `Metric("state", value)`，无单位；初始 spec 为相同字段且值 `None`。

| 原始值 | 展示值 |
| --- | --- |
| created | Created |
| running | Running |
| paused | Paused |
| restarting | Restarting |
| removing | Removing |
| exited | Exited |
| dead | Dead |

`Exited`、`Dead` 等生命周期均可成功，不因退出码或健康状态生成错误。`Running` 不表示应用健康。额外 JSON 字段忽略；`Health`、`State.Error`、环境内容不影响生命周期，也不能透传。未知状态或状态缺失属于解析失败，不能伪造 `Running`、0 或把任意文字写进 TUI。

## 失败、恢复与取消

所有预期失败返回原 key、空 metrics 和既有目录内的 `Failure`；固定受控 reason 不含原始 stdout/stderr/异常。保留最后有效值和历史缺口由 MonitorState 实现，TUI 复用状态栏位置显示 `STALE`。成功后正常清除 STALE，由 Monitor 通知日志模块结束故障轮次。

| 输入或事件 | kind / code |
| --- | --- |
| CLI 非零且 stderr 含 `permission denied`；或 PermissionError | permission / access.denied |
| CLI 非零且 stderr 含 `no such container` 或 `no such object`；或响应身份不符 | not_found / object.not_found |
| 非零的其他 CLI 错误；FileNotFoundError / 其他 OSError | unavailable / source.unavailable |
| 成功输出格式/字段/状态非法；任一流超限 | parse / response.invalid |
| 底层 TimeoutError；Monitor 超时 | timeout / collection.timeout |
| 未预料的程序异常 | 交给 Monitor 归一为 unexpected / collector.unexpected |

先检查输出上限。非零退出不解析 stdout；stderr 按 ASCII 不区分大小写的上述固定短语分类，权限规则优先于不存在，未识别错误保守归为 unavailable。成功退出时 stderr 不改变合法 stdout 结果。错误分类不使用动态消息作为 code，不扩充日志目录；原文不写入 Failure.reason。离线样本是构造的契约样本，未知 CLI 版本/文案的精细分类仍需之后获授权验证。

每个来源独立受 `collection_timeout` 约束，默认 3 秒；底层端口也收到该有限正超时值（int/float，拒绝 bool）。Monitor 的超时到达后取消仍应传播，不能包装成权限或不可用。底层超时、取消、流超限和 close 必须停止并 await 回收在途进程，取消/close 清理预算 250 ms；不使用无限阻塞线程，清理不打印、不追加采集错误。close 主动取消在途 run，其调用方收到 CancelledError，close 返回前完成进程和读取任务清理，不返回终止退出码作为新采样。close 幂等，关闭后 run 拒绝；Monitor 保证同一采集器无重叠调用，端口无需支持多个同时命令。

## 生产组装与展示复用

`build_docker_collectors(containers, timeout=..., command_factory=...)` 按完整配置顺序创建独立采集器，空配置返回空 tuple 且不创建端口。默认工厂创建 LocalDockerCommand；工厂、采集器构造与 prepare_log 都不执行命令。

R4 在 `ApplicationRuntime._components()` 调用该工厂：用其全部 spec 替换现有 Docker 静态模板，并把全部采集器交给同一个 Monitor；保留 host/vLLM 槽位、唯一 State/Log 和只读 reader。传入 RuntimeComponents 时沿用注入组件，不创建额外采集器。新增 `docker_command_factory` 只隔离外部命令，不能替换采集结果或另建一套状态。

`compose_frame` 已按内容容量显示配置前缀，每项一行，失败不补位。未配置时仅在有内容行的区域显示 `No containers configured`；容量为 0 时不绘制条目或空态。配置 10 项、容量 4→6→3 时仅改变可见项，不影响采集、对象顺序、最小终端尺寸或下半区高度。隐藏项真实失败仍按既有 ERROR 规则记录；单纯隐藏不记错。无需新增滚动、分页、更多提示或展示类。

## 接口与验证依据

| 接口/边界 | 黑盒入口 | 覆盖 |
| --- | --- | --- |
| parse_inspect | `tests/test_docker.py` | 七种状态、名称/完整 ID、重建、误匹配、JSON/字段边界、失败目录、输出净化 |
| DockerCollector / build_docker_collectors | 同上 | 固定单次只读命令、全量顺序、重复目标不同 id、无 IO 构造、失败恢复、取消、关闭 |
| LocalDockerCommand | `tests/test_docker_command.py` | 仅替换 asyncio 子进程创建端口；参数/环境、原始字节、并发排空、两流上限、超时/取消/close 回收 |
| Collector→Monitor→State→Frame/Log | `tests/test_docker_integration.py` | 真实采集业务入口与离线命令样本；隐藏项采样/日志、容量变化、恢复及错误净化 |
| ApplicationRuntime | 同上 | 用 fake 命令与终端运行真实生产组装，要求全部容器实际采样，揭示当前只有静态槽位的缺口 |
| 配置与容量 | `tests/test_config.py`、`test_config_boundaries.py`、`test_tui.py`、`test_integration.py` | 复用 REQ-001 的 1/5/6/10 项完整保留、空态、0 容量、半页、配置不修改等测试 |

运行入口：`python -m pytest tests/test_docker.py tests/test_docker_command.py tests/test_docker_integration.py`，以及全量 `python -m pytest`。所有 Docker IO 使用离线替身；不运行实际 docker、不访问 Unix socket 或网络。现有两个生产首帧测试增加 pending command 工厂，保持首次采样前的断言，并为 R4 接入后继续隔离真实 IO。

测试不以 NotImplementedError 为成功条件，不使用 xfail 隐藏骨架；纯业务入口失败是 R2 基线。生产组装尚未接入导致的行为断言失败单独记录，不能当作导入/环境错误。实际命令、数量和结果见 [REQ-003 R2 交接](../dev-workflow/dev-0/REQ-003/handoff-r2.md)。

后续集成待验证：真实 Docker CLI 与模板、Unix socket 权限和错误文案、真实进程取消的时限。当前仅验证离线协议和本地公共 TUI；不得将样本结果表述为实机验证，也不因交接自动获得服务器连接授权。
