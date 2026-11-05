# dev-0 / REQ-006 概要开发计划

- 项目：`D:\Documents\joi-observer`
- 工作目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- 需求目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006`
- 分支与基点：`codex/dev0-req006`，`0a42646b43df67832d6cfe9088e9eaf8c9c8f8af`；沿用当前工作区及未提交的 R2 产物。
- 修订与状态：v1.0，2026-11-04；R3 ready，可交 R4 实施。ready 表示计划具备执行条件，不表示目标 UI 已实现。
- 需求依据：[requirements.md](../requirements.md) v1.16，REQ-006 / AC-601～616 及共同只读、采样、状态和布局规则；[AGENTS.md](../../../../AGENTS.md)。
- 设计交付：[handoff-r2.md](handoff-r2.md) v1.4；采用其最终证据，前几版验证保留为历史。

### 用户 GUI 反馈执行补充（2026-11-04，R4登记）

下列用户直接修订覆盖v1.0中相应显示细节，归属既有T-002/T-003/T-006，不改变任务依赖、公共配置字段或采集范围；当前需求依据为requirements v1.17。此记录不改写原R3交接的历史结论。

- Storage只在面板标题右上角汇总STALE：前3个配置挂载点任一失败即显示，逐行不再预留STALE；容量与百分比组右对齐至内容右缘。Storage的GiB数值按原始字节直接ROUND_HALF_UP到整数，TiB、GPU/RAM与公共capacity_text语义保持。
- 随包示例和离线GUI样本使用既有`name`字段显示Flash-Next、Embedding、Reranker，显式`served_model_name`保留真实服务身份。左右标题共用展示名，不增加独立短名字段。
- 重跑受影响测试、最终WSL回归并刷新最终wheel/离线安装/Frame回放环境。旧通过报告与wheel在`evidence/r4-install-before-gui-feedback/`等原证据中保留，修订后GUI仍待用户复验。

2026-11-04后续精度补充（当前需求v1.18）：用户要求RAM容量也显示整数（GiB/TiB均从原始字节直接ROUND_HALF_UP），CPU和Storage现有百分比固定保留1位小数（含30.0%、0.0%、100.0%）；用户已进一步确认RAM保持原布局、不新增百分比文字。GPU显示、CPU采样/舍入口径、Storage TiB及公共格式化接口保持。归属既有T-002/T-006；上一轮安装证据另保留于`evidence/r4-install-before-precision-feedback/`。

2026-11-05用户追加显示修订（当前需求v1.19）：随包containers使用可修改的实际YAML示例；Storage路径及空配置文字改正文色；页眉固定设备展示标签`H3C R5300 G6`，由本机os-release自动读取发行版本，以`设备 / 系统`显示，不读取内核号或探测服务器。用户提供`TERM=xterm`并明确不修改TERM，Moonlight在基础色模式使用终端亮紫近似（magenta + bold），精确/固定256配色保持；主题切换强制整帧重绘，普通同主题帧保持差分。原GUI脚本也继承调用者TERM，专用自动化PTY独立模拟不同颜色能力。归属既有T-001/T-002/T-006，不新增配置字段或运行依赖；此前R5 v1.2已通过的结论保留为该版本历史，不自动覆盖本轮变更。

2026-11-05用户后续明确提高刷新目标（当前需求v1.20）：T-005改为固定60Hz、`start+n/60`、约16.7ms绘制机会；同步原帧时钟/导航/两向公平性及缩放验证，保留读键正超时、跳过已逝槽和终端恢复。不改变默认1秒采样、60秒历史、分桶或5秒尺度迟降，不生成插值样本、不新增帧率配置或切换。T-006按新源码构建安装包，核验约16.7ms的真实PTY调度与采样仍独立；旧30Hz验证事实不改写。以下v1.0表格的30Hz条目由本条覆盖，任务边界与依赖保持。

同日用户要求GPU/CPU/RAM硬件条使用半格空隙的分格外观（当前需求v1.21）：T-002保留原条宽/行高/颜色/数量与数值位置，显示层推荐填充▌、细轨道▏以保留未关联灰GPU比例可辨；不改变percentage_bar公共返回、原取整算法或vLLM历史柱。同时处理R5-006-003：本地os-release必须从首个读取成功文件的实际字段计算页眉，不能把标准库补入的Linux默认值当作文件值，也不能丢弃显式Linux；测试保持真实文件文本与生产装配。T-006按新源重建离线包并验证；新MobaXterm观感按用户“先代码与离线复验”的范围保留未验，旧GUI确认不替代当前显示确认。

同日用户要求仅将vLLM详情RUNNING/WAITING右侧数值和历史标题上方四列指标的数字加粗（当前需求v1.22）：T-003用独立的TextCell.bold默认False呈现标记，保留旧构造、五色role和坐标；T-001后端逐单元与A_BOLD组合。只加粗可见的真实数值（含0/科学记数/STALE旧数），—/N/A/…与左栏/标签/caption/状态/历史不新增加粗，三类型对应槽一致。T-006更新真实PTY、预览及包验证；不改变采样、60Hz、布局、内容或既有Moonlight基础色字重。

同日用户追加右侧三处留白，并明确第三处为DECODE HISTORY标题上方（不是DECODE指标标签）：T-003在模型名、RUNNING/WAITING、历史标题前各留一行。右详情相对service改为模型/状态+2、路由+3、横线+4、统计+6/caption+7、横线+8、指标标签+9/值+10、历史标题+12、柱图+13..height-3，+1/+5/+11为右侧空白，横轴仍height-2。服务半页、最小高度16、左栏与原颜色/加粗/字段保持，图区高度减少3行且最小仍有1行；不改变时间分桶、尺度、采样与60Hz。T-006适配行位观察并重建原离线验证入口；此明确用户修订覆盖旧行位契约，不扩大到其他区域或HTML原稿。

同日用户进一步要求GPU/CPU/RAM的填充与未填充段统一使用`▌`，取消细轨道，未填充段采用更深灰以区分未关联GPU的原muted填充。T-001/T-002增加独立track角色，不改原五个角色、背景、数量算法、位置或vLLM；T-006验证源码/真实本地PTY，并适配原来依赖字形区分两段的测试观察器。用户明确“不要生成离线包”：本轮不构建wheel、不重装、不生成离线预览包、不更新旧GUI入口；旧包仅是上一轮三处留白版本，不能作为本轮显示证据。

## 设计、接口与测试依据

| 领域 | 当前依据与公开接合点 |
| --- | --- |
| 主题与终端 | [theme.md](../../../design/theme.md) v1.4，含 Neon Grid 逐项采用/适配/排除表；[theme.py](../../../../src/joi_observer/tui/theme.py) 的 Palette、palette_for、CursesTheme；ViewSelection、Frame.theme 与 CursesTerminal 生命周期 |
| 外壳与硬件 | [application-shell.md](../../../design/application-shell.md) v1.12、[hardware.md](../../../design/hardware.md) v1.5、[docker.md](../../../design/docker.md) v1.2；[layout.py](../../../../src/joi_observer/tui/layout.py) 的 compose_frame/required_size、[widgets.py](../../../../src/joi_observer/tui/widgets.py) 的 hardware_cells |
| 服务与导航 | [vllm.md](../../../design/vllm.md) v1.8、[view-contract.md](../REQ-004/view-contract.md) v1.1、[navigation.md](../../../design/navigation.md) v1.8；[vllm.py](../../../../src/joi_observer/tui/vllm.py) 的 vllm_cells 与既有 SessionViewActions/服务页脚 |
| 历史与刷新 | vllm.md §10.1、application-shell.md 的帧截止点和尺度接线；[history.py](../../../../src/joi_observer/tui/history.py) 的 bucket_history/HistoryScale/HistoryScaleTracker、[timing.py](../../../../src/joi_observer/tui/timing.py) 的 FrameSchedule、[app.py](../../../../src/joi_observer/tui/app.py) 的 ObserverApp |
| 视觉参考 | [joi-observer.html](../../../design/joi-observer.html) 中 Neon Grid；以 theme.md 对照表和正式字符契约限定采用范围，不引入其他概念稿或模拟字段 |

REQ-001～005 已合并的采集、内存状态、指标计算、导航及退出能力继续复用。本次只调整 REQ-006 的呈现与 UI 调度；不新增配置字段、运行依赖、持久化、采样来源、图表类型或服务管理功能。既有公共 `format_metric`、`capacity_text` 和真实 Metric/单位语义保持，有界数字格式属于布局呈现。

## 主要任务

表中前置依赖只记录启动所必需的条件；跨任务完成验证和共享文件冲突另见下一节。具体实现步骤、私有函数及 subagents 分工由 R4 决定。

| 任务编号与标题 | 交付结果、关联需求与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 双主题与终端恢复闭环 | 新应用默认 Hologram，两次 t 正确切换；正常/小窗口的名称、帧元数据、实际配色及空白背景一致。精确 RGB、固定256色、基础色、单色及异常降级遵守契约；退出、部分失败和重入恢复颜色与终端。修复 **R2-006-001** 有色→无色重入残留属性。AC-601～604、612；`test_theme_palette.py`、`test_theme_terminal.py`、`test_theme_view.py`、导航及真实 PTY。 | `tui/theme.py`、`layout.py` 的默认/Frame 传递、`app.py` 的 CursesTerminal；核对既有 `navigation.py` 会话复用。依据 theme.md、application-shell.md 配色衔接。 | 无新增启动前置；已有角色、会话及终端协议可直接使用。 |
| T-002 外壳与上半区 HTML 排版 | 交付3:2横向、Host四内容行、Storage三内容行和Docker余高；页眉、Theme/时钟、硬件数值及Docker状态固定右缘，细分角色/共享单位正确。长Unicode名称、未知、0、极长数值及STALE不相互覆盖；保持半页、GPU槽位、Docker配置前缀和最低尺寸。AC-605～608、613、615、616；`test_html_shell_layout.py`、`test_html_hardware_layout.py`、TUI/硬件/Docker回归。 | `tui/layout.py`、`widgets.py`；依据 application-shell.md 字符容量、hardware.md 显示契约、docker.md 呈现规则。 | 无新增启动前置；可按现有语义角色独立验证，不等待配色后端。 |
| T-003 服务区 HTML 排版与数值边界 | 固定24列模型栏、三层条目和选中可见窗口；双统计块、caption归属、四列标签/数值、路由、分隔与槽内状态右齐符合契约。三类型、失败恢复、长名称和科学记数保留真实单位/适用性，不改变历史行位；保留原导航和GPU联动。AC-604～607、614～616；`test_vllm_view.py`、`test_navigation.py`、`test_theme_view.py` 及相关应用/PTY。 | `tui/vllm.py` 与 `layout.py` 栏间分隔；依据 view-contract.md、vllm.md §10、navigation.md。 | 无新增启动前置；排版可以先验证，完整历史验收与 T-004 集成。 |
| T-004 稳定柱状历史与显示尺度 | 固定最近60秒、绝对时间桶、端点/缺口/有效0行为正确；模型＋指标独立尺度即时升档、连续低档满5秒才降，非法输入原子失败。纯视图消费冻结尺度并保留默认即时档位语义，尺度标签不增行；极大值不溢出、不裁峰，正极小值不伪装成0。不改原始历史或采样计算。AC-610～612；`test_history_presentation.py`、`test_vllm_view.py`、主题视图及vLLM PTY。 | `tui/history.py`、`vllm.py` 的历史呈现、`layout.py` 的显式尺度传递；依据 vllm.md §10.1 及两个渲染入口的完整注释。 | 无新增启动前置；公开类型和参数已声明。 |
| T-005 30 FPS 与应用会话接线 | 普通帧按固定起点30Hz调度，读键等待不越截止点，慢帧跳过旧槽；首次/resize及时绘制且不重置原节拍。每帧一次快照/选择、同一单调时刻推进全部模型尺度；主题、选择、resize、小窗口、同实例再run保持尺度，新实例独立，每次run重建帧节拍。键盘/采样持续响应，旧文字和柱无残留。AC-601～603、609～612；`test_frame_timing.py`、`test_history_app.py`、`test_navigation_app.py` 及生命周期/采样隔离回归。 | `tui/timing.py`、`app.py` 的 ObserverApp，与 `layout.py` 当前图区宽度接合；依据 application-shell.md、history/timing接口。 | 可按现有协议立即开始；默认应用的贯穿验证需 T-004 及 T-002/T-003 布局集成。 |
| T-006 离线联验、视觉对照与交付 | AC-601～616 全部有对应结果；新旧业务测试、真实本地PTY、最终源码构建的已安装CLI及实际GUI终端逐区截图对照完成。更新实现状态与使用说明、R4交接和源码/包对应证据；关闭R2-006-001并保留既有通过行为。 | 现有测试及必要接合补测、README、已实现源码的阶段注释、本需求 `evidence/` 和 `handoff-r4.md`。 | 证据/离线安装/视觉场景准备可立即开始；最终验收需 T-001～T-005 集成及最终wheel。 |

## 开发顺序与并行条件

1. T-001～T-005 的公开契约已齐备，均可开始；建议先落实主题值/终端能力、分桶/尺度、帧时钟这些可独立验证的能力，同时推进上下区排版。T-006 的离线材料和同样本视觉场景准备提前进行，不等实现全部结束。
2. `layout.py` 同时承接主题元数据、上下区几何和尺度传递；`vllm.py` 同时承接服务排版及历史；`app.py` 同时承接终端资源和应用调度。R4须协调这些共享文件的修改与集成，不把文件冲突误写为所有任务串行的业务依赖。
3. 先让各交付对应的定向测试通过；汇合 T-002/T-003 时统一实际图区宽度和槽位，120列窗口的历史宽度为88，不能继续使用旧76。T-004据真实几何验证分桶/尺度标签，再与T-005贯穿默认应用；T-001的真实颜色也要在整帧中验证，不能只看主题名称。
4. 同一应用再次run保留选择和尺度，但每次run重启帧时钟，每次终端enter重新探测配色资源；三种生命周期不能混用。小窗口仍推进全部模型尺度，采用最近正常图区宽度，尚无正常帧则使用最小正常布局宽度。R2-006-001随T-001关闭。
5. 无变化帧省略实际写入是允许的优化，不是新前置条件或指定缓存方案。采用时不能省略读键、尺度计时或必要的残留清除；不得生成插值样本、提高采样频率或把纯渲染改为隐式有状态。
6. 汇合后完成一次最终Ubuntu全量，再用最终源码wheel验证安装路径和真实终端观感；后续只因改动、失败或未解决问题追加复验。若设计/测试含义冲突，交回R2；若需调整规划，在R4交接的“R3 修订汇总”记录依据和请求。不得削弱断言、跳过目标PTY或用预置结果替代实现。

## 验证安排

### 基线与执行环境

当前引用 [R2最终JUnit](evidence/r2-parity-final-pytest.xml)、[输出](evidence/r2-parity-final-pytest.txt) 和 [分类](evidence/r2-parity-final-summary.json)：**1827项，1368 passed / 459 failed / 0 errors / 0 skipped**。这些失败包括新骨架、旧主题/调度/历史/排版与目标不符，以及R2-006-001；不全部归为NotImplementedError。前置失败遮蔽的后续断言仍须实现后执行。

R3在本地WSL复跑只读[R2执行体审计](evidence/r3-source-audit.json)：原有26份生产Python在排除约定结构/注释变化后与基点一致，9个新增行为入口仍为骨架，无缺失链接。另完成 `pytest --collect-only -q -p no:cacheprovider`：**1827 tests collected，退出码0**，见[收集输出](evidence/r3-collect-only.txt)和[结果](evidence/r3-collection-result.json)。本轮没有执行业务断言、PTY或安装；静态审计和加载成功均不代替R4测试。

必须在本地Ubuntu或WSL Ubuntu运行；当前入口为WSL `Ubuntu-24.04`，工作目录 `/mnt/d/Documents/joi-observer`，既有解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。保持pytest及PTY子进程的DNS/connect防护，仅替换外部I/O、时钟或终端边界；不连接任何服务器，不发推理请求。无需原生Windows全量回归。

### 验收映射与完成条件

| 验证主题 | 完成判定及主要测试入口 |
| --- | --- |
| AC-601～604：主题和输入 | `test_theme_palette.py`、`test_theme_terminal.py`、`test_theme_view.py`、导航系列：默认/两次t/不启用鼠标、全部角色和背景同步；仅新鲜正等待与QUEUED为amber；0、未知、STALE旧正数保持非amber。保留显式truthy/falsey注入、当前模型/GPU/历史及同实例会话。T-001/006。 |
| AC-605～608：几何和状态稳定 | `test_tui.py`、主题/硬件view与edges、`test_docker_integration.py`：奇偶半页、0～4 GPU最小120×36、5 GPU最小120×37及放大/过小/恢复；前三挂载、Docker全部采集但仅可见前缀，溢出无提示。逐来源正常→失败→恢复不移位或增诊断。T-002/003/006。 |
| AC-613、615、616：上半与外壳细节 | `test_html_hardware_layout.py`、`test_html_shell_layout.py` 及硬件runtime/PTY：页眉本地aware时钟、固定右缘、标签/单位/百分号/中点分色，GPU显存/温度/功率、CPU/RAM两行、Storage和Docker状态保护。覆盖0/未知/多位数/长Unicode/极长数字，有界科学记数不能截成较小完整值。T-002/006。 |
| AC-614～616：服务细节 | `test_vllm_view.py`、导航/主题视图与应用：24列三层条目、名称和状态槽、计数左右子槽、双统计及caption、四指标、分隔、可靠URL/明确端口。Chat与pooling保留tok/s、seq/s、真实延迟和N/A，不复制模拟上限；当前选择可见且图位不变。T-003/006。 |
| AC-610～612：分桶、尺度与纯渲染 | `test_history_presentation.py`、`test_vllm_view.py`：短历史留白、闭端点及相邻外点、同桶不动/跨桶左移、缺口优先/0/空图、五秒迟降与清零条件、模型指标隔离、时间回退原子性、任意精度上限及极小正数。显式尺度错误拒绝和纯调用即时档位分别验证。T-004。 |
| AC-609、611、612：默认应用与采样 | `test_frame_timing.py`、`test_history_app.py`、`test_navigation_app.py`：可控时钟30Hz、截止点读键、连续输入、慢帧跳槽、resize不漂移、一次快照/选择、未选中模型迟降、小窗口和跨run保持/隔离。真实Monitor继续按配置采样，未将1秒变成30次新观测。T-005/006。 |
| 真正终端与恢复 | `test_terminal_pty.py`、`test_navigation_pty.py`、`test_vllm_pty.py`、`test_hardware_pty.py` 及主题终端边界：布局与RGB分别观察，完整交互后检查q、取消/异常/信号、光标/回显/备用屏/termios和配色色槽恢复；有色→无色重入属性不残留。记录本地PTY绘制耗时、帧间隔及退出响应，不把PTY吞吐视作GUI可见30FPS保证。T-001/005/006。 |
| 已安装CLI与视觉对照 | 从最终源码构建并离线安装新wheel，验证三个新增模块随包、裸命令与异目录运行；同样本/同尺寸下对照Neon Grid逐区截图，覆盖双主题、主要三类型、正常/过小/恢复、长名称、状态变化、原柱图和退出恢复。实际本地Ubuntu/WSL GUI终端字体/颜色能力/观感须有记录；单元/PTY绿不能替代。T-006。 |

各任务按上表运行定向测试；最终全量入口如下（相对路径从项目根目录执行）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-final-pytest.xml
```

成功条件是全部适用验收通过、既有采集/状态/日志/导航和生命周期行为无回归，且没有未解释错误或目标平台跳过。最终测试数量按实际报告，不把R2的1827项当作不可增加的上限。只收集、编译、静态检查或骨架可导入均不能算实现通过。

### 离线安装与交付证据

R3按[REQ-005离线清单](../REQ-005/evidence/r4-offline-wheels.json)核对 `.pytest_cache/offline_wheels` 的17个目的wheel，全部存在且SHA-256相符，见[本轮核对](evidence/r3-offline-artifacts.json)。既有测试venv未装setuptools，但本地wheelhouse有构建后端；uv及系统Python可用，详见[环境记录](evidence/r3-environment.json)。当前没有已确认的离线材料阻塞，不能沿用REQ-005旧计划“仅9个wheel、待整理”的历史说法。

R4仍需准备构建环境，从最终源码重建wheel，使用离线、禁索引、禁止Python下载的安装选项。旧REQ-005包及其通过记录只能作参考，材料存在不能证明新版本安装通过。

可参考[REQ-005安装验证脚本](../REQ-005/evidence/r5-install/verify_uv_install.py)及其同目录辅助脚本，适配本需求的路径、Hologram默认、两次t的实际RGB/背景、30Hz、固定60秒轴/尺度、最新布局和恢复观察。运行已安装的真实CLI/配置/采集器/Monitor/State/默认应用/布局/curses，仅替换外部I/O；显式加载并验证网络防护，不能只靠虚构域名或源码PYTHONPATH。

T-006更新README和已实现接口的阶段注释，记录截图所用终端/字体/尺寸/样本、颜色能力、调度测量及实际结果。沿用theme.md对照表的既定取舍；若发现实现与契约存在差异，先修复或按流程反馈，不将其默认为新的视觉豁免。

新证据使用本需求 `evidence/r4-*`，保留R2/R3原记录；记录命令、平台、源码/包校验和结果。`evidence/` 已被Git忽略，跨环境交接需单独携带。完成后写本需求 `handoff-r4.md` 请求R5验收；跨角色推进由用户发起。

## 修订记录

- v1.0（2026-11-04）：基于R2 v1.4与需求v1.16建立六项交付、并行/集成条件及AC-601～616验证安排；纳入R2-006-001、实际HTML排版、稳定原柱图、30FPS、离线安装和GUI视觉对照。未改变需求或设计含义；当前无须先交回R2的阻塞项。
