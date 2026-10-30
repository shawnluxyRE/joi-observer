# dev-0 / REQ-001 概要开发计划

- 项目：`D:\Documents\joi-observer`
- 工作目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- 需求目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001`
- 修订与状态：v1.1，2026-10-30；R3 ready，可交 R4 实施本轮增量修订。
- 需求依据：[requirements.md](../requirements.md) v1.12、[handoff-r1.md](../handoff-r1.md) v1.12，REQ-001 / AC-101～AC-114 及共同规则；根目录 [AGENTS.md](../../../../AGENTS.md)。
- 本轮设计依据：[handoff-r2.md](handoff-r2.md) v1.5，R2-112-01～R2-112-03；处理结论见 [handoff-r3.md](handoff-r3.md)。
- 已有实现与验收：[handoff-r4.md](handoff-r4.md) v1.3、[handoff-r5.md](handoff-r5.md) v1.3，对应需求 v1.9；作为增量开发起点，不能代替 v1.12 验收。

## 设计、接口与测试依据

D1～D4 仅为本计划的引用简称，不替代需求中的 D-001 等待决事项编号。

| 引用 | 当前模块设计 | 主要接口与注释 | 验证入口 |
| --- | --- | --- | --- |
| D1 | [configuration.md](../../../design/configuration.md) v1.1 | [config.py](../../../../src/joi_observer/config.py)、[示例配置](../../../../src/joi_observer/examples/config.yaml) | [test_config.py](../../../../tests/test_config.py)、[test_config_boundaries.py](../../../../tests/test_config_boundaries.py)、[test_cli.py](../../../../tests/test_cli.py) |
| D2 | [monitor-state.md](../../../design/monitor-state.md) v1.5 | [models.py](../../../../src/joi_observer/data/models.py)、[state.py](../../../../src/joi_observer/data/state.py)、[monitor.py](../../../../src/joi_observer/monitor.py)、[Collector](../../../../src/joi_observer/collectors/base.py) | [test_state.py](../../../../tests/test_state.py)、[test_monitor.py](../../../../tests/test_monitor.py)、[test_state_monitor_edges.py](../../../../tests/test_state_monitor_edges.py)、[test_integration.py](../../../../tests/test_integration.py) |
| D3 | [error-logging.md](../../../design/error-logging.md) v1.1，契约不变 | [error_log.py](../../../../src/joi_observer/error_log.py) | [test_error_log.py](../../../../tests/test_error_log.py)、[test_error_log_boundaries.py](../../../../tests/test_error_log_boundaries.py)、联合测试 |
| D4 | [application-shell.md](../../../design/application-shell.md) v1.2 | [cli.py](../../../../src/joi_observer/cli.py)、[模块入口](../../../../src/joi_observer/__main__.py)、[app.py](../../../../src/joi_observer/tui/app.py)、[layout.py](../../../../src/joi_observer/tui/layout.py) | [test_tui.py](../../../../tests/test_tui.py)、[test_shell_edges.py](../../../../tests/test_shell_edges.py)、[test_terminal_pty.py](../../../../tests/test_terminal_pty.py)、CLI/联合测试 |

工程依据为现有 [pyproject.toml](../../../../pyproject.toml)、[uv.lock](../../../../uv.lock) 和 [README.md](../../../../README.md)。[Neon Grid 参考稿](../../../design/joi-observer.html) 用于布局理解；字符容量、分区和对象数量采用更新后的需求与 D1/D4，不沿用旧稿的尺寸或展示数量。

## 本轮范围与既有成果

v1.0 计划中的公共基础已实现并经 R5 验收；本轮在原实现上同步 v1.12 的配置和布局契约。保留 T-001～T-008 编号，区分本轮修改、接合验证和既有成果回归，不重新开发状态、日志、调度及终端输入。已关闭的 R5-001（YAML 安全诊断）和 R5-002（Esc 输入阻塞）修复继续保留。

本轮完成判定采用以下变化，详细接口和区域坐标引用 D1/D4：

- **R2-112-01**：先完成整份 YAML 安全检查，挂载点只校验并纳入原列表前 3 项，尾项忽略应用语义；前项非法或采集失败不以第四项补位。容器全部校验、去重并按序保留，不设固定数量上限，也不按终端容量截断配置。
- **R2-112-02**：以全页绘制高度 H 平分，下半区为 `H//2`，奇数多出一行归上半；页眉、边框、间距、服务切换位和键位均包含在两半预算内。Frame 增加独立 `service_switch`，共 8 区。Storage 固定 3 行内容、总高 6 行；Docker 使用右侧余高，允许留白，只展示可容纳的配置前缀，无隐藏提示、补位、滚动或分页。零容量不画条目或空态文字。基础布局不足才提示放大。
- **R2-112-03**：可见容量只作用于 Frame。全部配置容器仍保有采样、当前值、历史与实际失败日志；隐藏本身不是失败。缩放只改变可见前缀，不重建来源、丢弃状态或触发额外采集，重新可见时读取最新快照。

最低列数仍为 120；按 D4 的新公式，0～4 / 5 / 6 / 10 GPU 槽对应最低 36 / 37 / 43 / 67 行，挂载点与容器计数不抬高最低行数。主场景 120×37 仅承诺基础布局可用，不承诺显示所有容器；H=44/48/42 的 Docker 容量为 4/6/3，H=36 且 GPU 不超过 4 时容量为 0。

具体硬件、Docker、vLLM 采集器仍属 REQ-002～REQ-004；完整导航、GPU 联动、双主题和最终模型指标排版仍属 REQ-005～REQ-006。本轮用离线端口验证公共链路并调整现有服务内容的区域边界，不增加真实采集器或生产演示数据。AC-207/301/304/605/607/608 仅作为共享规则的衔接引用，不表示本计划接管这些需求的全部验收。

## 主要任务

前置依赖只记录开始工作所必需的条件；既有公开契约与可执行基础已具备。任务编号延续 v1.0，修改范围限于实现新契约所需内容。

| 任务编号与标题 | 本轮交付结果、关联验收与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 配置数量规则修订 | 完整 YAML 检查后仅返回前三挂载点；所有容器完整校验、去重、保序；保持源文件不变、可定位安全错误及示例加载。AC-105/113，衔接 AC-207/301；D1 的配置/边界/CLI 测试。 | `config.py`，核对已更新示例与使用说明；D1、R2-112-01。 | 无新增任务依赖，复用现有解析及 R5-001 修复。 |
| T-002 只读状态与有界历史回归 | 复用已验收状态；隐藏容器仍在完整快照与历史中，未知/0/N/A/STALE、失败缺口和冻结视图保持正确。AC-101/102/110；状态及联合测试。 | `data/` 原则上无需改动；若接合发现回归，仅作必要修复；D2。 | 无新增任务依赖。 |
| T-003 采集错误日志回归 | 复用已验收日志；隐藏对象的真实失败照常记录，单纯隐藏不记录；原限频、轮转、本地时间、静默降级及有界关闭保持通过。AC-107～112；日志及联合测试。 | `error_log.py` 原则上无需改动；D3、R2-112-03。 | 无新增任务依赖。 |
| T-004 独立采样回归 | 复用现有 Monitor；十个离线容器全部持续采样，缩放不减源、重建任务或额外采集；超时隔离和通知不变。AC-102/103/108/112；调度及联合测试。 | `monitor.py`、采集端口原则上无需改动；D2、R2-112-03。 | 无新增任务依赖；现有调度可直接接入离线源。 |
| T-005 半页布局与容量修订 | 实现新最低尺寸、奇偶半页、8 区、Storage 固定高度、Docker 可见前缀和逐区域绘制边界；零容量、空态、失败/恢复及缩放无越界、补位或提示。AC-101/106/110，衔接共享布局 AC；TUI/外壳测试。 | 主要为 `tui/layout.py`；按需接合 `app.py`，保留稳定 GPU 槽、即时缩放重绘及 R5-002 输入修复；D4、R2-112-02。 | 无新增任务依赖，可用直接构造的配置/快照与 T-001 并行。 |
| T-006 CLI 与组合根接合核验 | 新配置重启后仅前三挂载进入有效配置与展示槽，全部容器建状态槽；运行期不按显示容量裁剪来源。配置错误在全屏前退出，既有 TTY、日志提示、信号及共享退出预算不回退。AC-104/105/110/111/113；CLI/外壳/集成测试。 | 核对 `cli.py` 装配路径，现有容器全量建槽逻辑可复用；挂载采集身份仍由 REQ-002 定义；D1/D2/D4。 | 可立即审阅；基于新解析结果的联合验证需 T-001 可用。 |
| T-007 新契约离线集成与全量回归 | 打通“用户配置→对象集合→采样/状态/日志→可见前缀”；通过当前新增黑盒预期与旧功能回归，消除 R2 43 项实现差异。AC-101～113 的公共范围。 | 相关已有 `tests/`、必要的接合修复及本需求新证据；D1～D4、R2-112-01～03。 | 正式联合验收需 T-001/T-005 新行为可用；可提前准备场景，复用 T-002～T-004。 |
| T-008 新布局 PTY 与安装交付复验 | 更新本地 PTY/安装脚本旧尺寸预期，重建并核对最终 wheel，在新 shell、异目录裸命令和真实终端中验证新布局、缩放与恢复；更新说明和 R4 交接。AC-104/106/113/114。 | README、现有 `evidence/verify_pty.py` / `verify_uv_install.py` 及新报告；复用已存在的 `uv.lock` 和离线依赖；D4。 | 脚本准备可提前；最终验证需 T-001/T-005/T-006 对应路径可用，以及本地 Ubuntu/WSL 环境。 |

## 开发顺序与并行条件

1. 先核对需求 v1.12、R2 v1.5 与 R4/R5 已验收版本，保留现有未提交改动、两项 R5 修复、锁文件及历史证据。确认离线 wheel、Windows YAML 依赖和 WSL uv 环境可复用；缺失时记录具体环境缺项，不把已完成安装基础写成尚未建立。
2. T-001 与 T-005 可并行；T-006 的组合根审阅、T-008 的脚本边界核对也可提前。T-002～T-004 作为现成功能和回归依据，不要求重写，也不作为配置/布局开工阻断项。具体实现步骤及 subagents 分工由 R4 决定。
3. 先分别通过配置和布局定向用例，再联通 T-006/T-007：从真实 YAML 加载结果核对前三挂载的有效配置/展示槽，并建立完整容器的状态与离线来源集合。现有十容器联合用例直接构造 AppConfig，需结合加载和装配证据覆盖配置到来源的衔接，不能仅验证屏幕前缀；不为本轮新增生产挂载身份或采集器。
4. `layout.py`、`test_tui.py` 的几何与绘制变更统一集成；`test_shell_edges.py` 涉及生命周期保护，`test_integration.py` 涉及数量和日志协作，应协调修改。维持公开签名，避免为了新布局改动已修好的终端输入或删改 R5 安全断言。
5. 新行为可用后，T-007 全量回归与 T-008 本地 PTY/安装验证可并行。最终安装产物须对应同一交付版本；无依赖变化不重新解析或生成 `uv.lock`。README 应反映实际实现状态，旧 R2/R4/R5 JSON 和交接结论保留为历史，不覆盖成新通过记录。

## 验证安排

### 当前基线与历史证据

- 新契约基线引用 [r2-v112-validation.json](evidence/r2-v112-validation.json)：2026-10-29 Windows 共 327 项，269 passed / 43 failed / 15 Unix PTY skipped / 0 errors；15 项配置差异、28 项布局及关联集成差异。失败是旧可执行逻辑未同步新契约，不是 NotImplementedError，不得永久 skip/xfail。
- 旧需求 v1.9 的 R5 验收仍有效证明当时公共基础已完成：Ubuntu 269 passed，Windows 254 passed / 15 平台跳过，见 [r5-recheck-results.json](evidence/r5-recheck-results.json) 及 R5 交接。旧 wheel、尺寸和安装报告不能证明本轮新行为通过。
- 初版 167 项骨架基线及日志时间基线只作历史：见 [test-baseline.json](test-baseline.json)、[test-log-time-baseline.json](test-log-time-baseline.json)。当前任务完成判定采用新基线和新增实际证据。

### 定向与联合验证

| 验证组 | 完成条件与主要依据 |
| --- | --- |
| 配置纳入范围 | 挂载 0/1/2/3/4/6 项只纳入原前三项；合法 YAML 尾项不做路径/类型/去重语义校验，前三项非法不补位。容器 0/1/5/6/10 项全部保留，后续项缺字段、未知字段及重复 ID 均定位报错，源文件不变。`test_config.py`。 |
| YAML/CLI 安全保护 | 仍检查整份 YAML 的语法、重复键、标签、递归别名及标准标量构造；覆盖第 4 挂载及嵌套非法标量，保留原第 6 容器输入和 R5-001 场景。CLI 返回 2、有字段/行列定位，无原值、堆栈、半初始化 TUI 或日志。`test_config_boundaries.py`、`test_cli.py`。 |
| 几何与显示边界 | 按 D4 核对新最低尺寸、奇偶半页及独立切换行；Storage 固定高度且仅前三项；Docker 在 H=44→48→42 时显示配置前 4→6→3 项，H=36 零容量不画空态；容器增多不触发放大提示，不覆盖下半页。保留 Unicode 宽度和极小窗口检查。`test_tui.py`、`test_shell_edges.py`。 |
| 状态稳定与缩放 | 同一尺寸下失败/恢复不改变区域或对象前缀，不以尾项替换失败项；GPU 槽不因暂失而缩短容量。ObserverApp 缩放即时重绘且 q/t/方向键端口响应，不重入终端或启动采集。TUI/外壳用例。 |
| 采集与可见数量分离 | 真实加载后的前三挂载及完整容器进入公共链路；十个离线容器在隐藏时仍采样、更新快照/历史，隐藏失败仍写 ERROR，扩大后显示最新 STALE；缩放不改变来源数量/调用次数，不修改配置或状态。`test_integration.py` 的十容器用例及必要的加载/装配接合验证。 |
| 既有公共能力回归 | 保留并通过状态、调度、日志、安全诊断及终端用例；包括持续失败限频、恢复、新错误、旧轮次写失败回调、轮转边界、慢 IO/队满、静默与共享 1 秒退出预算。保留全部 15 项真实 PTY 输入用例，保护 R5-002。 |

R4 先执行相关文件的定向测试，再在 Windows 和本地 Ubuntu/WSL 执行全量；Windows 仅 Unix PTY 的平台跳过可按原条件保留，Ubuntu 应实际执行这些用例。复用 R4/R5 交接中的离线依赖和 uv `--offline --locked` 流程，不联网解析依赖。测试替身仅隔离外部采集、终端、时钟及文件故障，不替换被测配置、布局或调度结果。

### 真实终端与安装

- 调整 [verify_pty.py](evidence/verify_pty.py) 和 [verify_uv_install.py](evidence/verify_uv_install.py) 中按五容器推导旧最低高度的场景。无 GPU 的生产外壳新最小为 120×36，5 GPU 离线场景为 120×37；覆盖相邻边界、奇偶页高、Docker 零容量及扩大/缩小，并记录分区和可见条目。`test_terminal_pty.py` 的输入时限断言继续保留，不因布局变化降低预期。
- 真实 PTY 复验 q、Ctrl+C/SIGINT、SIGTERM、部分进入/绘制/读键异常、缩放和终端属性恢复，核对 termios、光标与原屏幕；安装后的布局须来自最终代码。已有生命周期场景可以复用，使用新的尺寸预期和新输出路径。
- 用既有离线环境重建 wheel，逐文件核对 Python 代码和示例；在新交互 shell、未激活环境、异目录下验证裸命令、示例定位、缺配置退出和全屏启停。`uv run` 不能替代工具安装验收。锁文件依赖本地 `.pytest_cache/offline_wheels` 的已披露限制继续记录，不推断其他 Python/平台已验证。
- 日志实现未变时，可引用 [r5-permissions.json](evidence/r5-permissions.json) 的真实权限证据，结合当前全量及安装启停回归，不无理由重做独立 chmod 场景；若日志或降级路径改变则定向复验。其余历史安装证据仅说明原版本已通过。
- 全程禁止尝试连接任何服务器，包括示例地址。实际来源均使用离线端口；不扩大为目标主机或 Docker 实采验收。

### 交付判定与后续衔接

T-001/T-005 新行为、T-006 接合、T-007 回归及 T-008 最终产物/终端证据齐备后，R4 可交 R5 验收本轮增量。43 项差异应消除且无新失败；新增合理用例时按实际数量记录，不以恢复旧测试总数为目标。新证据存于本需求目录，标明需求 v1.12、源码/产物版本、环境、命令、结果和未验证事项；不覆盖历史 JSON。

后续 REQ-002/003 接入真实采集器时复验前三挂载和完整容器来源；REQ-005/006 继承半页与 8 区边界，复验完整导航、GPU 高亮、主题及模型内容。部署与指标待核对事项继续引用 [R2 交接的范围与未验证事项](handoff-r2.md#范围与未验证事项)，不重复建立记录。

## 修订记录

- v1.1（2026-10-30）：采纳 R2-112-01～03，按需求 v1.12 改为增量规划；保留八项任务编号和已验收成果，更新配置/布局、全量与可见数量分离、新尺寸及 PTY/安装证据要求；当前无阻断实施的设计问题。
- v1.0（2026-10-28，历史）：依据需求 v1.9 建立八项公共基础任务，明确并行、离线集成、uv/PTY 和后续需求边界；后来已由 R4 实现并经 R5 验收。本版不再采用其容器前五项、Docker 贴合内容、Storage 吸收余高和旧尺寸安排。
