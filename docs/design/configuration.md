# Configuration 模块设计

- 关联需求：dev-0 / REQ-001，AC-105、AC-106、AC-107、AC-109、AC-113；为 REQ-002～REQ-005 提供配置载体，并衔接 AC-207、AC-301、AC-304。
- 关联需求补充：dev-1 / REQ-001，AC-107/113/114。
- 修订：v2.3，2026-11-16；在图前集中介绍配置载体、错误类型及配置加载参与者。
- 整体设计：[整体组件与进程边界](architecture.md)。
- 相关代码：`src/joi_observer/config.py`、`src/joi_observer/examples/config.yaml`。
- 关联模块：启动与终端、采样调度、采集错误日志。

本文维护 YAML 字段、输入校验、默认值及配置选择规则。硬件与 Docker 的运行期身份匹配分别由[本机硬件](hardware.md)和 [Docker 设计](docker.md#docker-identity)维护，面板容量与可见性由[应用外壳](application-shell.md#可验证的字符容量)维护。

## 模块职责与范围

只在宿主机采集服务启动时选择并读取用户 YAML，验证字段，返回不可变 AppConfig。读取不访问任何监控目标，不创建日志目录、不修改 YAML、不热重载。运行期间修改或删除文件不影响当前对象与展示元数据；服务重启重新校验并建立新实例，校验失败不得沿用旧实例配置或默认值。安装示例是复制材料，绝不能成为缺少用户配置时的运行回退。TUI/Web 不调用本模块加载监控对象。

dev-1 当前为 R2 设计阶段，现有解析实现复用；服务加载与客户端脱离配置文件的接线由 R4 完成。客户端仅接受连接路径及会话偏好，没有另一套采样参数或名称配置。

`ContainerConfig.id` 是状态身份，也是 TUI Docker 区域的显示名称；`name` 是实际查询目标。解析配置不检查容器存在性，不提供 socket/context 配置；运行期匹配与重建规则见 [Docker 身份契约](docker.md#docker-identity)。

## 类与对象简介

| 图中名称 | 简介 |
| --- | --- |
| `AppConfig` | 不可变启动配置类，汇总采样参数、监控对象和日志设置，供服务实例一次性使用。 |
| `ModelConfig` | 单模型配置类，描述稳定身份、展示名称、采集地址、服务身份和 GPU 关联。 |
| `ContainerConfig` | 单容器配置类，将状态使用的稳定 id 与实际查询目标 name 分开保存。 |
| `LogConfig` | 日志配置类，保存受控错误日志的目录、单文件大小和备份数量。 |
| `ConfigError` | 配置异常类，携带安全的文件、字段和可取得的 YAML 行列定位信息。 |
| `CLI`（service 命令入口） | 时序图中的命令入口角色，选择配置路径、启动 `CollectorService` 并报告安全诊断。 |
| `Config`（`config` 模块） | 时序图中的配置模块角色，查找文件、校验 YAML 和字段并构造冻结配置。 |
| `File`（本地配置文件） | 时序图中的文件角色，提供所选路径的 UTF-8 YAML 内容，不参与监控目标探测。 |
| `CollectorService`（`Service`） | 常驻服务类，在取得实例锁后加载一次配置并拥有该生效配置的运行期。 |

## 简化类图

```mermaid
classDiagram
    class AppConfig {
        +sample_interval: float
        +collection_timeout: float
        +models: tuple
        +containers: tuple
        +logging: LogConfig
    }
    class ModelConfig {
        +id: str
        +name: str
        +served_model_name: str [0..1]
        +gpu_ids: tuple
    }
    class ContainerConfig {
        +id: str
        +name: str
    }
    class LogConfig {
        +directory: Path
        +max_bytes: int
        +backup_count: int
    }
    class ConfigError {
        +path: Path
        +field: str
    }
    AppConfig --> ModelConfig
    AppConfig --> ContainerConfig
    AppConfig --> LogConfig
```

## 关键交互时序图

```mermaid
sequenceDiagram
    participant CLI as service 命令入口
    participant Config as config 模块
    participant File as 本地配置文件
    participant Service as CollectorService
    CLI->>Config: resolve_config_path(显式路径或默认候选)
    Config-->>CLI: 唯一选定路径
    CLI->>Service: run(stop)
    Note over Service: 取得实例锁后加载一次
    Service->>Config: load_config(path)
    Config->>File: 读取 UTF-8 YAML
    File-->>Config: 文件内容
    alt YAML 或字段非法
        Config-->>Service: ConfigError(安全定位信息)
        Service-->>CLI: 退出 2，不装配采集运行期
    else 配置有效
        Config-->>Service: 冻结 AppConfig
        Note over Service: 配置和展示投影在本实例内不再重载
    end
```

## 配置选择与失败处理

仅 `joi-observer service` 按 `--config PATH`、当前目录的 `config.yaml`、系统共享的 `/etc/joi-observer/config.yaml` 的顺序选择。显式相对路径以服务启动目录为基准，`~` 按服务运行用户展开。原用户配置可通过 `joi-observer service --config ~/.joi-observer/config.yaml` 指定。systemd 使用显式 `/etc/joi-observer/config.yaml`，避免工作目录影响生产对象。只选择第一个存在的候选；非法内容、无读取权限、目录或显式路径不存在时直接报错，不改用低优先级文件。

原 `joi-observer --config PATH` 不再启动独立采集；该位置或 `tui` 子命令传 `--config` 时返回参数错误，提示移到 `service`。默认 TUI 即使当前目录有配置也不查找、加载或修改它。参数与退出码见[应用外壳](application-shell.md#命令与启动序列)。

服务未找到默认文件时，报告尝试过的当前目录路径、系统共享路径以及安装包内示例的实际位置。提示写入服务 stderr，不初始化采集、不记录 ERROR、不自动复制文件。读取成功也不证明 GPU、挂载点、容器或 URL 可用。

`ConfigError` 统一提供绝对文件路径、字段路径和可取得的 YAML 行列。错误文本为英文，包含定位及修复原因；不直接回显 YAML 源行或敏感值。字段路径使用零起始数组索引，如 `models[1].id`；YAML 行列从 1 开始。日志目录的可写性失败属于服务启动降级，由日志模块处理，不改写成配置错误或客户端连接错误。

<a id="configuration-fields"></a>

## 字段契约

YAML 顶层须为 mapping；`{}` 有效，空文件、null、标量和列表无效。先检查完整 YAML 文档，再进行应用层字段校验。完整文档须无语法错误、重复 YAML key、不支持的标签、递归别名或无法构造的标准类型标量；这一步覆盖第 4 个及以后的挂载点，不因应用层忽略而跳过。所有实际纳入的字段层次拒绝未知字段及隐式转换字符串/布尔值。

挂载点先取原始列表前 3 项，再校验这 3 项的路径、类型及唯一性。其余合法 YAML 值忽略应用层语义，既不产生超量错误，也不采集、不显示；不能筛选出“前三个有效路径”或用后续项替换前面的非法/采集失败项。例如 `['/', '/data', '/srv', null]` 返回前三项，而 `['/', null, '/srv', '/data']` 必须定位第二项为配置错误；第四项若为 `!!int ""`，仍须报告其 YAML 标量构造错误。初始空列表仍是空态，不自动补足 3 个对象。

容器列表完整校验并保留，不设固定数量上限。第 6、10 等后续项的缺字段、未知字段或重复 ID 均按普通配置错误处理，不能因其当前不可见而忽略。配置模块不读取终端尺寸、不按可见数量裁剪或报错；显示容量由[应用外壳](application-shell.md#可验证的字符容量)决定，不改变有效配置集合。

| 字段 | 默认值 | 有效范围与语义 |
| --- | --- | --- |
| `sample_interval` | `1.0` | 有限数字，1～60 秒，包含端点且允许小数；bool 非数字 |
| `collection_timeout` | `3.0` | 有限数字，0.1～60 秒，包含端点；可大于间隔，同一对象由调度器保证不重叠 |
| `mount_points` | `["/", "/data"]` | 有序、互异的 POSIX 绝对路径，禁止 `..`、控制字符和首尾空白；按上文前三项规则纳入，`[]` 为关闭挂载项 |
| `containers` | `[]` | 按上文规则完整保留有序列表，每项必填 `id`、`name` |
| `models` | `[]` | 有序模型列表；每项必填 `id`、`type`、`name`、`base_url`，可选 `gpu_ids`、`served_model_name` |
| `logging.directory` | `/var/lib/joi-observer` | 自定义目录接受运行平台绝对路径或 `~`、`~/...`。`~` 按采集服务运行用户展开。systemd 为服务准备默认目录；TUI/Web 不创建各自的采集日志。返回 Path，不创建目录，也不展开环境变量或 `~other` |
| `logging.max_bytes` | `10000000` | 整数且至少 1024 字节；十进制 10 MB 默认阈值，保证可容纳一条有界日志 |
| `logging.backup_count` | `3` | 正整数，禁止 0，确保轮转始终有界 |

`id` 长度 1～64，符合 `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`；在所属完整列表内唯一，容器第 6 项及以后也参与重复检查。跨 `containers` / `models` 的同名 ID 不冲突，因为采集器是对象标识的一部分。`name` 是 1～128 个可打印字符，不含控制字符或首尾空白；模型同名不同 ID 保持独立。容器 name 使用真实名称或完整 ID，不从 Compose 项目推断。

模型类型固定为 `chat`、`embedding`、`reranker`。`base_url` 只接受 HTTP/HTTPS origin，允许尾部单个 `/` 并在返回值中去掉；禁止用户凭据、查询、片段以及 `/v1`、`/metrics` 等路径。本模块不进行连通性或服务身份验证；vLLM 的端点与响应身份策略见[vLLM设计](vllm.md#3-配置身份与版本)。URL 本身不能可靠识别 LiteLLM，因此部署说明要求用户填直接 vLLM 地址。

`ModelConfig` 支持可选 `served_model_name: str | None = None`。YAML 省略时使用 `name` 作为期望服务身份；显式给出时必须为 1～128 个可打印字符、无首尾空白或控制字符，不接受 null、空串或非字符串，允许 `/` 且不按本地路径解释。该字段不从 Compose、环境变量或 LiteLLM 自动取得。TUI/Web 列表显示 `name`，详情标题显示 `served_model_name`；省略时详情回退为 `name`。`id` 仍用于状态身份，同名不同 id 独立。服务在构造展示元数据时完成回退，不从成功样本反推名称；该变化不影响采集身份校验、配置顺序和 GPU 关联。

`gpu_ids` 缺省为 `[]`，表示映射未知。各项为 1～128 个非空白可打印字符且不重复；解析器保留原字符串，不查询设备，也不因当前设备不存在而拒绝配置。GPU 索引/UUID 的匹配与未知映射处理见[硬件显示与模型关联](hardware.md#硬件显示与模型关联)。

挂载点是否真实挂载不在加载时探测；来源身份、手工构造 `AppConfig` 的防御边界与本地 IO 的 timeout 传递由[硬件设计](hardware.md#本地-io-与接线)定义。CPU/RAM、GPU 发现无需新增配置。

返回值全部为冻结 dataclass 与 tuple。直接构造 dataclass 只是声明数据，并不代表通过校验；生产组合入口应始终使用 `load_config`。

采样下限的调整只适用于生产配置加载，不把 Monitor 的独立调度数学改成只接受一秒以上。离线测试可直接注入短周期或受控时钟验证同一相位、超时和取消规则。R2 已更新公开契约及配置黑盒，现有 `_Validator.timing` 仍是旧实现；R4 须分别校验采样和采集超时，不能将两者一起收紧或把小于一秒的配置静默抬到一秒。

## 向客户端提供的配置投影

服务调用 `ipc.protocol.build_metadata(config, hostname=..., system=...)` 得到 DisplayMetadata：挂载路径与顺序、容器 id、模型 id/type/name/已回退的 served_model_name/gpu_ids/显式端口/有效端口，以及主机展示信息。URL、容器实际查询目标、采样与超时参数、日志配置和原始错误不进入 IPC；精确字段以[协议设计](ipc.md)为准。端口只用于保留 TUI 的既有显示差异，不能据此构造请求地址。

元数据与快照绑定于同一 `instance_id` 和 `config_revision`；同一连接不能更换生效配置。用户修改 YAML 后要重启服务，再重新运行 TUI；新会话收到匹配的新元数据后才绘制。客户端不保留跨实例的旧模型顺序、名称、关联或历史。

## 示例来源与使用

示例随 wheel 包含于 `joi_observer/examples/config.yaml`。`joi-observer --example-config` 输出示例的绝对路径。管理员可将示例复制到 `/etc/joi-observer/config.yaml` 并编辑，供本机用户共享。用户也可将示例复制为工作目录的 `config.yaml`。示例注释说明挂载点仅前三项、容器全部采集但显示受面板容量限制；containers现提供一条有效YAML示例`id: chat-container`、`name: flash-next-vllm`，须替换为真实容器名称或完整ID；不监控时显式使用`containers: []`。这仅改变示例内容，解析器省略containers的默认值仍为[]。不会自动安装驱动、更改 Docker 权限或创建监控服务。

三个模型名和回环端口来自本地 `D:\Documents\llm_server\Ubuntu_Server_03_显卡驱动.md` 的 8.2、9.3 节；`Ubuntu_Server_04_服务部署.md` 的 3.3 节仅交叉核对路由，不采用 LiteLLM 作为采集入口。上述资料只读查看，未访问 URL、执行部署命令或确认服务在线。容器示例名称用于演示配置结构，不代表自动发现或已确认存在；用户按实际部署替换。

## 接口与验证依据

| 接口或符号 | 代码与注释位置 | 关联验收与黑盒用例 |
| --- | --- | --- |
| `resolve_config_path` | `config.py` 同名函数 | AC-113，显式路径、工作目录及系统共享路径的优先级，缺少文件、目录误配和禁止回退 |
| `load_config` / `ConfigError` | `config.py` 同名函数与异常 | AC-105、AC-106及衔接AC-207/301；挂载点前三项、完整容器列表及重复 ID、重启读取变更、三类模型、非法字段/数值/YAML/URL |
| `ModelConfig.served_model_name` | `config.py`、`tests/test_vllm_config.py` | 省略回退、显式身份校验及展示名与服务身份分离 |
| `LogConfig` | `config.py` 同名数据类 | AC-107、AC-109；默认日志路径、展开、自定义目录和轮转边界、不创建文件 |
| `example_config_path` | `config.py` 同名函数 | AC-113；资源存在，复制后可读取三个模型 |

配置测试可运行 `python -m pytest tests/test_config.py tests/test_config_boundaries.py`。测试使用 pytest 临时目录和本地字符串，替换共享配置路径和 home 以隔离真实文件，并调用 `load_config`。需要本地 PyYAML 和 pytest。REQ-002 工厂测试另外覆盖挂载来源数量和身份。未实现业务失败不能混同环境错误。

`test_config.py` 覆盖挂载点 0～3 项和超量截断、合法 YAML 尾项的应用层忽略、前三项错误不补位，以及容器 0/1/5/6/10 项完整保留、后续项全部参与结构及 ID 检查；保持源文件不变。配置快照只保存前三个挂载点，因此后续采集器不能取得第四项作为失败补位；实际采集范围及 Docker 隐藏项持续更新仍需启动组合根/REQ-002/REQ-003 集成测试验证。

时间边界分别验证 sample_interval 的 1/60 秒、collection_timeout 的 0.1/60 秒；拒绝 0.1、0.5、0.999999 秒采样并保留字段定位和源文件不变断言。1.25 秒采样配 0.1 秒超时仍合法。原有非法类型、非有限值、上界和 YAML 安全矩阵全部保留。

`test_config_boundaries.py` 保留 R5-001 的全部非法标准标量、精确字段/行列、脱敏和完整文档校验场景。原第六容器现在是正常纳入项，仍保留相同输入和断言；另扩展到真正忽略的第四挂载点及其嵌套非法标量，防止先截断 YAML 节点树而绕过历史修复。`_YAML_VALUE_ERRORS` 的异常归一、整文档节点遍历和原有 CLI 安全退出测试不因数量规则变更而削弱。

本模块自动化验证不涵盖真实终端启动、wheel 安装后的资源定位、日志目录权限降级或任何采集行为；由启动/日志契约测试和 R4 的 Ubuntu 离线集成补足。具体运行结果以 REQ-001 的 R2 交接单为准。

## 修订说明

v2.3，2026-11-16：补充配置类和时序对象的集中介绍，标明命令、模块与文件角色；配置字段和校验契约不变。

2026-11-16：按更新后的 R2 图文规范补充核心类图、关键交互时序和整体设计入口；原有接口行为、数值及测试契约不因图面修订改变。

v2.1 按用户确认将生产 sample_interval 改为 1～60 秒，collection_timeout 保留原范围，补齐分离边界黑盒。业务校验实现由 R4 迁移。

v2.0 将配置读取所有权移到常驻服务，并固定客户端参数兼容、启动重读、元数据投影与名称映射。既有 YAML 字段、校验和配置查找函数不改业务语义。

v1.5 将 REQ-004 模型身份扩展并入字段契约，移除运行期匹配与几何规则的副本，保留配置输入校验与来源边界。

v1.4按用户要求补入非空容器示例；示例仍需复制修改，缺配置不能自动启用示例，不更改用户已有配置或解析器默认值。

v1.1 根据需求 v1.12 将挂载点纳入范围固定为前 3 项，将容器改为完整保留及校验，明确配置/采集范围与显示容量分离；保留全部 YAML 安全边界，并把忽略尾项回归扩展到挂载点。公开 API、默认采样/超时、用户配置查找、日志配置及三类模型配置结构均保持不变；现有业务逻辑留待 R4 同步。

v1.2 在REQ-001完成v1.12验收后衔接REQ-002：补充GPU映射的精确匹配、挂载序号身份、前三项组装及timeout传递，不改变配置解析实现或示例目标。
