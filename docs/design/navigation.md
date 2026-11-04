# 模型导航与服务入口设计

- 关联需求：dev-0 / REQ-005，`requirements.md` v1.12，AC-501～504；依赖 REQ-001、REQ-002、REQ-004。
- 修订：v1.3，2026-11-03；完成设计、类图、骨架及黑盒契约同步复核，修正测试映射与单位期待，补齐会话和服务描述覆盖。
- 代码：`src/joi_observer/tui/navigation.py`、`tui/services.py`；复用 `tui/app.py`、`tui/layout.py`、`tui/vllm.py`、`tui/widgets.py`。
- 关联模块：[应用外壳](application-shell.md)、[硬件](hardware.md)、[vLLM](vllm.md)、[配置](configuration.md)、[Monitor / State](monitor-state.md)。
- 阶段：R2。新增接口骨架、目标注释与黑盒测试；已有执行逻辑保留，导航及默认接线由 R4 实现。实际验证见 [R2 交接](../dev-workflow/dev-0/REQ-005/handoff-r2.md)。

## 职责与已有基础

导航只维护当前应用实例的模型选择和主题标识，不参与采集、历史计算、健康判断或 GPU 发现。数据流继续为 `Collector → Monitor → MonitorState → TUI`；所有模型无论是否可见或选中均由同一个 Monitor 持续采集。控制器不接收 Monitor、State、SnapshotReader、终端或 HTTP 端口。

设计基线是已合并 REQ-004 的 `83aad39`。以下能力已经存在，本轮复用其公开行为：

| 已有能力 | 所在入口 | 本轮使用方式 |
| --- | --- | --- |
| 不可变选择值、纯布局与半页分区 | `ViewSelection`、`compose_frame` | 每帧将同一个选择值传给模型和 GPU 绘制 |
| 键名归一、全局退出、异步读键与缩放 | `CursesTerminal`、`ObserverApp` | 不重写输入解析器和生命周期 |
| 分类型详情、历史、空态、随选择可见的模型列表 | `vllm_cells` | 不增加第二套滚动状态或指标适配 |
| 显式 GPU 关联映射与稳定硬件槽位 | `linked_gpu_ids`、`hardware_cells` | 选择只改变语义高亮，不改变设备集合 |
| 可注入的会话操作协议 | `ViewActions` | 新增具体的 `SessionViewActions` |

当前正式构造未提供 actions，`ObserverApp` 每帧使用首模型占位，方向键没有选择效果。R4 要补齐默认控制器，并调整当前服务样式和页脚文字；不通过修改 MonitorState 保存 UI 选择。

## 核心接口与协作

```mermaid
classDiagram
    class ModelConfig {
        +id str
        +gpu_ids tuple
    }
    class ViewSelection {
        +model_id str_or_None
        +theme str
    }
    class ViewActions {
        <<interface>>
        +selection() ViewSelection
        +on_key(key) None
    }
    class SessionViewActions {
        +__init__(models)
        +selection() ViewSelection
        +on_key(key) None
    }
    class SnapshotReader {
        <<interface>>
        +snapshot() StateSnapshot
    }
    class TerminalPort {
        <<interface>>
        +size() TerminalSize
        +read_key(timeout) str_or_None
        +render(frame) None
    }
    class ObserverApp {
        +run() None
    }
    class ServicePresentation {
        +service_id str
        +title str
        +navigation_label str
    }
    class Layout["tui.layout"] {
        <<module>>
        +compose_frame(snapshot, config, size, host, now) Frame
    }
    class Services["tui.services"] {
        <<module>>
        +VLLM_SERVICE ServicePresentation
        +footer_text(service) str
    }
    SessionViewActions ..|> ViewActions
    SessionViewActions ..> ModelConfig
    SessionViewActions --> ViewSelection
    ObserverApp o-- ViewActions
    ObserverApp --> SnapshotReader
    ObserverApp --> TerminalPort
    ObserverApp ..> ViewSelection
    ObserverApp ..> Layout
    Layout ..> ViewSelection
    Layout ..> ServicePresentation
    Layout ..> Services
    Services --> ServicePresentation
```

图中 `module` 框表示实际 Python 模块，列出模块级函数和常量，不代表新增类。`VLLM_SERVICE` 是 `ServicePresentation("vllm", "vLLM", "Select model")`；布局使用同一描述的 title 绘制当前服务，并传给 `footer_text(service)` 生成导航提示。图示为目标接口协作，服务描述与骨架已声明，布局接线仍待 R4。主题状态仍由 `ViewSelection.theme` 承载，完整配色映射留 REQ-006。

`SessionViewActions(models: tuple[ModelConfig, ...])` 结构化满足既有协议，不继承应用类。输入是配置解析后顺序固定、id 唯一的模型元组；复用配置校验，不在此层重新校验 URL、探测端点或增加新的配置字段。同名、同类型、同地址但 id 不同的项仍可分别选择。

`selection() -> ViewSelection` 只读，`on_key(key: str) -> None` 仅更新会话。存储形式由 R4 决定；骨架声明模型序列和选择字段，不公开游标、滚动偏移或可变容器。没有修改配置集合、选择服务、持久化偏好和按健康自动选项的接口。

## 选择与键盘契约

非空配置初始选择第一项，空配置返回 `model_id=None`；每个新应用实例从 `theme="moonlight"` 开始。非空配置的控制器始终输出合法 id，不向视图输出未知 id。连续读取的值相等，后续操作不能改变已返回的冻结值；不同控制器实例互不影响。

| 归一化输入 | 会话行为 | 应用处理 |
| --- | --- | --- |
| `up` / `down` | 按配置顺序前/后一项；在首/尾停留，不循环；保持主题 | 分派至控制器 |
| `t` | moonlight ↔ hologram，保留模型 | 全局有效，空列表、小窗口、失败时也可操作 |
| `left` / `right` | 无动作 | 不离开 vLLM，不改变模型或硬件，不发起新来源 |
| `enter` / `p` / `tab` / 其他键 | 无动作 | 不开详情、不暂停、不转移面板焦点 |
| `q` | 控制器直接收到时无动作 | 应用全局正常退出，沿用运行期清理 |
| `interrupt` | 控制器直接收到时无动作 | 应用沿用中断和终端恢复路径 |

控制器只识别表中的小写规范键名，不自行解码原始转义序列，也不将 `T`、`Down` 等作为别名。终端已有 CSI、SS3 和 terminfo 方向键支持；残缺输入的有界处理与取消预算不变。

零模型时所有方向键安全、主题可切换；单模型时上下始终停留。选中项首次未采集、STALE、恢复或暂时不在快照中时保持 id；这些状态只影响已有视图的指标和状态槽。模型列表来自配置，不从成功采样对象反推列表。不热加载配置，不增加运行时删除模型的迁移规则。

本需求完成主题标识的会话操作；终端精确 Moonlight/Hologram RGB 映射及全屏颜色验收仍属于 REQ-006。不得把主题名称变化或语义角色通过视为完整双主题已实现。

## 默认接线与刷新

R4 在 `ObserverApp.__init__` 中以 `actions is None` 判断默认路径，创建一个 `SessionViewActions(config.models)`；显式注入的 actions 原样保留，包括真假值为 false 的对象。控制器在构造时只做内存初始化，不读快照、不进入终端。选择放在应用内，是为了让正式 CLI 和直接实例化应用获得相同默认行为，避免仅在某个入口接线。

运行期读取选择和分派按键同样不能通过 `if actions` 跳过 falsey 实例；构造完成后默认或注入的控制器均应正常参与。对应 truthy/falsey 两种注入均有黑盒断言。

`ApplicationRuntime` 继续原样创建 ObserverApp，自动使用其默认控制器；不再额外创建第二份选择状态。注入完整 RuntimeComponents 时仍不创建额外来源或替换已注入的应用。单个应用实例重复顺序运行保留该实例选择；只有新建实例才重置，重复并发运行仍按既有契约拒绝。

首次绘制发生在第一个按键前。每次绘制读取一次 `selection()`，将该值传给整帧；不分别读取模型详情与 GPU 高亮的选择。处理按键后在下一普通绘制周期显示，沿用最多 10Hz 绘制与最长 50ms 读键，不为导航提高采样或绘制频率。尺寸变化仍在下一次读键前立即重绘。

刷新、主题、采集失败与 resize 不重建控制器。不足基础尺寸时仍处理方向键和 t，恢复足够尺寸后显示最新选择；此时屏幕继续只显示既有放大提示和 `q Quit`，不为小窗口增加完整页脚。新发现 GPU 仍按既有顺序追加槽位，导航不增删或重排槽位。

## 列表、详情与 GPU 关联

模型列表继续每项两行。service 高度为 `H // 2 - 2`，其内容可见容量为 `(service.height - 2) // 2`；最低可用区域高度 16 时可见 7 项。纯绘制按已有规则，窗口首项为 `max(0, selected_index - capacity + 1)`，末端不超过模型总数。这不是带记忆的滚动窗口：选择靠前时可能显示较多后续项，选择靠后时可能留下余白，不新增分页、循环、更多标记或滚动条。任何可用尺寸下当前选择都在可见窗口内；模型数量不提高最低终端高度。

右侧详情、单位、历史取 `ObjectKey("vllm", model.id)`。Chat 的 DECODE/PREFILL、TTFT、KV Cache 和 pooling 的 RATE/Avg latency 继续使用 [vLLM 契约](vllm.md)，不复制计算逻辑。切走再切回不清空历史，不把旧样本当新样本，不替换选中故障模型。

GPU 映射继续只读模型的 `gpu_ids`。完整 UUID 精确匹配；规范十进制索引只匹配当前已采样、非 STALE 且索引唯一的 GPU。空映射、未知标识、重复或过期索引不猜测；明确 UUID 关联可用于保留的旧卡。切换改变编号、填充条和百分比的 `primary/muted`，不改变 GPU 槽位、值、状态或顺序。模型服务本身 STALE 不使显式配置映射失效。

既有纯视图对外部未知 id 的容错保持：vLLM 回退首项，硬件清空关联。默认控制器从不产生这种输入，无需为本需求统一或扩大兼容规则。

## 服务入口与键位呈现

下半区仍包含 service、service_switch 和 footer，共占 `H // 2` 行；奇数页高余行留给上半区。沿用八个 Region、120 列下限、Storage 三行和 Docker 可见前缀规则。

正常帧在 `service_switch` 同一行保留可见文字 `vLLM  /  WebUI (disabled)`，将 `vLLM` 单独绘为 `primary` 表示当前服务，分隔符和 `WebUI (disabled)` 为 `muted`。不引入可变 service_id、焦点状态、WebUI 页面或鼠标流程。

当前 vLLM 页脚仍精确为 `↑↓ Select model    t Theme    q Quit`，角色 `primary`。其中 **Select model 由 vLLM 服务提供**，不是所有服务的固定文案；`↑↓`、四空格间距、`t Theme` 和 `q Quit` 保持全局固定，其余 UI 文字不改。不声称左右可切换，不显示 Details/Pause/Tab 操作。

`tui/services.py` 定义不可变 `ServicePresentation(service_id, title, navigation_label)`；当前唯一启用描述是 `VLLM_SERVICE = ("vllm", "vLLM", "Select model")`。这只是静态呈现元数据，不增加服务状态机、配置字段或启用 WebUI。描述由服务定义提供，不从模型数量、模型类型、快照内容或当前文案反推服务身份；空模型时仍使用 vLLM 的提示。

R4 在 `compose_frame` 内取得一次 `services.VLLM_SERVICE`，用其 title 绘制服务标题和当前服务项，并将**同一描述**交给 `footer_text(service)`。该纯函数只组合 `↑↓ {navigation_label}    t Theme    q Quit`。以后支持其它服务切换时，切换的是当前描述，页脚同步使用对应 navigation_label；本轮不定义未来服务的具体文案或按键行为。`ViewSelection`、`ViewActions` 和模型导航签名不变。

R2 新增元数据声明、footer_text 骨架与黑盒契约；页脚组合和 compose_frame 接线继续留 R4。测试可替换当前服务的静态导航文字输入来验证绑定，不模拟页脚输出，不据此宣称服务切换已实现。

## 接口与验证依据

| 公开入口 | 黑盒测试 / 复用 | 验收依据 |
| --- | --- | --- |
| `SessionViewActions` | `tests/test_navigation.py`：默认、顺序、边界、0/1模型、同名身份、主题、无动作键、值不可变、实例隔离 | AC-501～503、共同只读约束 |
| 控制器 → 真实纯视图 | 同文件：类型/单位/历史/GPU 联动、长列表与尺寸变化、输入快照保持 | AC-501、502；复用 AC-205/206、401/406/409 |
| 默认 `ObserverApp` / 注入操作 | `tests/test_navigation_app.py`：真实应用循环、同实例再次运行/新实例重置、每帧一次选择读取、刷新/失败/缩放保留、全局操作、禁用入口和页脚 | AC-501～504 |
| `ServicePresentation` / `footer_text` / `compose_frame` | `tests/test_service_footer.py`：冻结描述、vLLM归属、标题/当前入口/导航文案共用描述、全局文字保持、实际Frame接线 | AC-504；用户本轮补充 |
| 控制器与采样隔离 | `tests/test_navigation_app.py`：真实 Monitor/State/VllmCollector 与离线 HTTP 字节端口；按键本身不额外采样，应用运行中 Enter/p 后全部模型仍按调度更新 | AC-501、503、504；共同采样约束 |
| 真实按键 → 默认应用 → Frame | `tests/test_navigation_pty.py`：本地 PTY、curses、箭头/主题/忽略键、q 与终端恢复 | AC-501、503、504 |
| 既有终端适配器 / 固定布局 / 映射边界 | `test_terminal_pty.py`、`test_tui.py`、`test_shell_edges.py`、`test_hardware_view*.py`、`test_vllm_view.py` | 不重复实现已覆盖的解析器、映射和布局算法 |

测试只隔离外部终端、时钟、只读样本或 HTTP 字节来源，不替换控制器的预期结果或 Frame 生成。默认应用测试不手工注入一个假控制器来掩盖接线缺失。PTY 子进程也封锁网络；不运行任何采证脚本，不连接部署服务。

指标文字沿用既有 `format_metric` 的值与单位直接拼接规则，例如 `100tok/s`、`3seq/s`、`0.25s`；导航不调整这类文字的格式。历史标题 `DECODE HISTORY / tok/s` 等保持原样。新测试必须分别核对指标值与标题的既有格式，不能因骨架提前失败而保留尚未触达的错误期待。

在本地 Ubuntu/WSL 运行 `python -m pytest -q tests/test_navigation.py tests/test_navigation_app.py tests/test_navigation_pty.py tests/test_service_footer.py --tb=short`，并在实现后运行既有全量回归。断言期待真实业务行为，不以 skip/xfail 隐藏业务未实现，也不把 NotImplementedError 当通过；PTY 仅沿用非 POSIX 环境保护，本地 Ubuntu 必须实际执行。骨架未实现、默认接线和旧文字导致的失败单独记录；falsey 注入已有缺陷另列，导入错误、环境问题或既有业务回归不得归为预期业务失败。

R4 完成实现后应重跑全部用例，并从实际离线安装包验证 CLI 的箭头导航、正常/过小/恢复尺寸、q 和终端恢复。R2 的内存帧与本地 PTY 不能替代已安装包或完整双主题视觉验收；这些边界不要求服务器联调。

## 设计决定

- 新增一个控制器，复用现有两个方法和冻结选择值；不增设展示状态库或更改 MonitorState。
- 默认接线放在 ObserverApp，保证直接构造与 CLI 一致；保留显式依赖注入。
- 沿用无状态可见窗口，避免选择与 resize 各维护一份滚动偏移。
- 本需求只定义服务入口的当前/禁用状态，不为未来 WebUI 预造切换状态机。
- 上下箭头后的文字属于当前服务描述；vLLM 是 Select model，全局主题/退出文字不变。静态描述与服务启用、可切换状态分开。
- 无需新的用户范围决定。REQ-006 的颜色、部署环境验证和 R3 开发计划均不在本轮交付中。
