# dev-0 / REQ-006 R2 交接

- stage：R2
- result：ready（v1.4逐项HTML审查完成，遗漏及错误断言已同步修正；业务未实现基线保留）
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006`
- 需求依据：[requirements.md](../requirements.md) v1.16，REQ-006 / AC-601～616；用户确认默认Hologram、原柱状图＋30 FPS，并要求终端能力允许时尽量贴近HTML排版。
- next_role：R3
- 修订：v1.4，2026-11-04；按用户要求再次全面对照HTML，补齐细节契约并完成最终WSL复验。
- 设计基点：`0a42646b43df67832d6cfe9088e9eaf8c9c8f8af`，REQ-005 已合并；当前分支为用户指定的 `codex/dev0-req006`，从 `codex/dev0` 新建，复用现有工作区；全部未提交改动已随分支切换保留，没有新建worktree。用户先前对 AGENTS.md 的 REQ-006 路径调整保留。

## 处理结论

已将 Hologram 默认启动、t → Moonlight → Hologram、仅会话内保留且不保存偏好写入需求 v1.13、项目约定和相关设计。REQ-005 的导航及服务页脚沿用，不新增主题配置字段或第二套会话状态。

本阶段只提供设计、结构声明、完整目标注释和黑盒契约；现有默认 Moonlight 与固定 curses 色执行体保留给 R4。Frame 追加 theme 元数据是结构准备，尚未将 view.theme 传入正常和小窗口返回。v1.0曾ready，v1.1仅修订文档时为draft；本次v1.2已补齐新增类型、接口、目标注释和黑盒并重新验证，恢复ready。它表示R2产物可交接，不表示主题、帧时钟或尺度已实现。

## v1.4 全面对照复核与最终证据

本轮分别复核Neon Grid的硬件、服务、外壳三条路径，再交叉检查文档、目标注释和黑盒。不是只确认前次结论：确实发现了遗漏与被前置失败遮住的错误期待，已逐项纠正。当前采用/适配/排除关系统一见[主题设计的逐项对照表](../../../design/theme.md#原稿与正式终端的逐项对应)，不能将其他HTML概念稿当作正式范围。

### 审查发现与处理

| 项目 | 已落实的修订 |
| --- | --- |
| 外壳右边缘与角色 | 两主题名称文字均贴C右缘且primary；主机名text、系统/时钟muted，真实本地aware时间不转UTC。GPU标题primary，其余标题secondary；Docker所有状态文字在14格槽内右齐，fresh Running primary，其余text |
| 硬件细分角色与单位 | 功率muted且W前空格；CPU数字text/%muted；RAM总量数字text/共享单位muted；Storage路径/容量/中点muted、比例text；补0、未知、多位数及状态组合 |
| 下半分隔与文字层次 | 横线+3/+6、竖线+4/+5均muted；四指标标签muted/值text；Total与Avg queue或Unit分别位于两统计组的caption行且muted |
| 模型栏计数 | 固定左12格与右11格，中间一空格；正常‘3 running’左齐、‘7 waiting’右齐；数字与标签独立角色，未知和0不混淆 |
| 状态文字真正右齐 | 右标题与左模型状态都保留原6格槽，但READY/STALE/—的文字也在槽内右齐；不能仅把一个左齐槽放在右边就视为与HTML一致 |
| 大数值不伪装 | 硬件数值组明确左右边界；最新计数/指标及容量过宽时保留指数/单位、用最多3有效数字科学记数，rail必要时缩run/wait，再不够使用明确…；不改变原始Metric、公共formatter或历史尺度算法 |
| 错误观察边界 | 修复test_navigation四指标收集将右边框│混入；修复theme_view路由只允许http开头、与新箭头契约冲突的选择器。角色断言只约束可见glyph，避免要求空白一定由某个TextCell绘制 |
| PTY前置遮蔽 | 导航布局、主题名称、实际RGB拆为独立验证分支，vLLM布局与颜色也分开；均在完整交互/退出/恢复后断言，颜色现在可独立触达 |
| 文档现状与差异 | 清除导航仍要求100tok/s同行格式、‘只调整默认主题’和主题‘不重写布局’等当前口径；REQ-002/003原阶段记录明确标历史。逐项记录统一背景/边框role/选中›、不复制模拟元数据和不重复NOW值的保留取舍 |

### 产物与覆盖

- [theme.md](../../../design/theme.md) v1.4新增逐项HTML元素映射表及明确取舍；[requirements.md](../requirements.md) v1.16新增AC-616，并同步AGENTS/README。
- [application-shell.md](../../../design/application-shell.md) v1.12、[docker.md](../../../design/docker.md) v1.2及layout目标注释冻结外壳细节；新增[test_html_shell_layout.py](../../../../tests/test_html_shell_layout.py) **32项**，并增强真实Docker采集到Frame的断言。
- [hardware.md](../../../design/hardware.md) v1.5及widgets注释同步逐片段角色与有界数值；[test_html_hardware_layout.py](../../../../tests/test_html_hardware_layout.py)增至**41项**，相关view/edges/runtime/PTY同步。
- [view-contract.md](../REQ-004/view-contract.md)、[vllm.md](../../../design/vllm.md) v1.8、[navigation.md](../../../design/navigation.md) v1.8及vllm注释同步计数、caption、分隔、状态右缘和数值裁切；[test_vllm_view.py](../../../../tests/test_vllm_view.py)增至**154项**。导航及两个PTY的观察范围/分支同步，未替换被测渲染结果。
- 原HTML未改写以迎合TUI测试；只读参考稿中的Neon Grid。没有使用实际服务器或推理负载验证布局。

### 最终运行记录

运行位置：本地WSL Ubuntu-24.04，`/mnt/d/Documents/joi-observer`；使用既有Python 3.12解释器`/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`，无安装、无服务器连接。

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r2-parity-final-pytest.xml
python docs/dev-workflow/dev-0/REQ-006/evidence/audit-r2-sync.py
git diff --check
```

| 验证 | 实际结果与边界 |
| --- | --- |
| 最终全量 | **1827项：1368 passed / 459 failed / 0 errors / 0 skipped，43.45s**；pytest退出1。[输出](evidence/r2-parity-final-pytest.txt)、[JUnit](evidence/r2-parity-final-pytest.xml)、[明细](evidence/r2-parity-final-summary.json) |
| 初次全量 | 1823项：1368通过/455失败，43.55s；随后补齐两处状态槽内文字右齐的4项覆盖并修正相应旧断言，重新全量。以上最终结果取代初次结果，不混用计数 |
| 独立交叉复核 | 硬件左右边界/角色、rail子槽、数值极值和指数、四列宽度、W88历史位置、caption归属及可见glyph断言均已核对；新科学记数不改变公共format_metric、capacity_text |
| 实际RGB独立触达 | 旧curses主色实测[0,680,680]与Hologram目标[482,624,1000]不符，作为普通业务失败报告；不再以先前布局失败掩盖后续颜色断言。终端退出/恢复先执行 |
| R2边界与静态检查 | 原有26份生产Python执行体与基点一致，9个新增业务入口仍为骨架；[审计](evidence/r2-parity-audit.json)。文档本地链接和git diff --check通过；Mermaid仅静态核对，没有声称已视觉渲染验收 |

459项失败是已有未实现主题/帧时钟/历史/新布局及其新增细节的目标基线；R2-006-001仍为已单列的既有终端重入缺陷。没有导入或环境错误，没有以xfail/skip隐藏未实现，也没有把语法/可加载/静态核对等同于真实界面通过。

**当前结论**：在本次明确范围和保留取舍内，未发现剩余文档—目标注释—黑盒不一致或未登记的HTML元素。业务逻辑仍留R4，真实Ubuntu/WSL GUI终端、字体、颜色能力和整体观感须在实现后逐区截图对照；不能从R2 ready或失败数量推出当前TUI已与HTML一致。接收角色仍为R3。

## v1.3 HTML对应排版修订与验证（历史）

来源：用户指出GPU/CPU/RAM/Storage数字靠右与下半统计/指标结构差异，明确要求“如果不是终端能力限制，那就尽量做到和html设计的排版布局一致”。已纳入正式契约，不以原来只统一主题和刷新作为完整视觉交付。

- 上半横向接近HTML的3:2，GPU外宽`floor((C−1)*3/5)`，间隔1列后Host/Storage/Docker共用余宽。Host扩为6行（CPU/RAM各标签/值＋条两行），消耗原Host/Storage间的一行留白；Storage仍row8/6行、内容10～12，Docker仍row15/余高。原最小高度、半页公式和Docker容量不变。
- GPU显存改到型号行中间区右对齐，温度/功率在最右10字符区上下对齐，第三行留STALE；RAM与Storage容量使用共享单位。CPU/RAM数值和Storage数值组固定右对齐，长名称/路径不能挤占值或状态。
- 模型栏内容固定24列，首行MODELS标题，条目名称/状态、类型/明确端口、运行/等待三层，项间留白；容量`(service.height−2)//4`，最低服务高度16可显示3模型。保留每模型6字符状态槽，不能为窄栏丢弃未选中模型健康状态。
- 服务分隔在c+27，详情从c+30起；右侧RUNNING/WAITING为两统计块，标签左、数值组内右，Total和Avg queue/单位在下一行；四指标列标签/单位在上、纯数值在下。可靠路由含箭头，不复制模拟TP/EP/容量分母；pooling KV槽为N/A。历史标题/图/轴的行位不变，120列时图区宽由76变为88，相关桶坐标期待同步。
- 仅采用字符终端和既定高度预算必要的适配：统一字号、字符边框、状态预留位、长名称裁切和选中指示。字段分组/对齐能够实现的部分均进入黑盒；HTML原稿继续作为参考，不修改采集口径或用模拟字段填充未知。

### 本轮产物

| 文件 | 修订 |
| --- | --- |
| [requirements.md](../requirements.md)、[AGENTS.md](../../../../AGENTS.md) | v1.15及项目布局规则，新增AC-613～615，保留已确认30FPS/主题/原柱图 |
| [application-shell.md](../../../design/application-shell.md) v1.11 | 3:2横向、Host6/既有半页预算、服务固定分隔及目标接线 |
| [hardware.md](../../../design/hardware.md) v1.4 | GPU/CPU/RAM/Storage固定右边缘、共享容量、状态槽和legacy兼容 |
| [view-contract.md](../REQ-004/view-contract.md) v1.1、[vllm.md](../../../design/vllm.md) v1.7 | 24列三层模型栏、双统计和四指标、真实字段/单位、固定历史行位 |
| [theme.md](../../../design/theme.md) v1.3、[navigation.md](../../../design/navigation.md) v1.7 | HTML与TUI逐项对应及真实终端视觉复核；新可见容量/保持选择 |
| [layout.py](../../../../src/joi_observer/tui/layout.py)、[widgets.py](../../../../src/joi_observer/tui/widgets.py)、[vllm.py](../../../../src/joi_observer/tui/vllm.py) | 仅补齐目标注释，公开签名继续复用；既有执行体保留给R4 |
| [test_html_hardware_layout.py](../../../../tests/test_html_hardware_layout.py) | 新增24项，覆盖右边缘、分行、未知/0/单位、Unicode和状态保护；含legacy兼容 |
| [test_tui.py](../../../../tests/test_tui.py)、[test_vllm_view.py](../../../../tests/test_vllm_view.py) | 新增6项外壳几何/分隔及9项服务布局/显式端口场景，修订原几何与数值行列期待 |
| 硬件view/edges/runtime/PTY，navigation/app/PTY，theme_view | 同步新几何及标签/数值分行，保留来源隔离、不可变数据、异常/恢复与完整退出；其余采集/计算用例不改 |

### 本轮验证与边界

运行于本地WSL Ubuntu-24.04，目录`/mnt/d/Documents/joi-observer`，解释器仍为`/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。网络与部署连接禁用，复用已有依赖，无安装或远程联调。

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r2-layout-pytest.xml
python -m pytest -q --tb=short \
  tests/test_tui.py::test_storage_ignores_fourth_mount_without_replacing_failed_first_item \
  tests/test_theme_view.py::test_resize_keeps_half_page_storage_three_rows_and_docker_visible_prefix \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r2-layout-followup.xml
python docs/dev-workflow/dev-0/REQ-006/evidence/audit-r2-sync.py
git diff --check
```

| 检查 | 实际结果 |
| --- | --- |
| 全量新基线 | **1740项：1358 passed / 382 failed / 0 errors / 0 skipped，38.25s**，pytest退出1；[输出](evidence/r2-layout-pytest.txt)、[JUnit](evidence/r2-layout-pytest.xml)、[模块与失败明细](evidence/r2-layout-summary.json) |
| Storage分块兼容复验 | 全量后审查修正两处旧“路径必须和容量在同一TextCell”的假设，允许独立路径cell；**3 passed，0.54s**，[输出](evidence/r2-layout-followup.txt)、[JUnit](evidence/r2-layout-followup.xml)。未改用例数量或业务结果期待，未重跑无变化的全量 |
| 硬件域专项 | 新布局view/edges/runtime/PTY及新增几何集合130项，77通过/53失败；来源/恢复完整，失败发生在呈现差异断言 |
| 真实终端 | 硬件PTY的6个主场景、导航PTY、vLLM PTY均先完成退出/termios与子进程回收，再报告布局或主题/历史差异；没有将新视觉期待作为启动ready门槛 |
| R2边界与一致性 | 原有26份生产Python的执行体与基点一致，9个新增行为入口仍为骨架；[审计](evidence/r2-layout-audit.json)。新右边缘、模型容量、四列宽度与历史桶坐标经独立复核；本地文档链接及git diff --check通过 |

新增与修订失败属于旧布局/旧主题/旧帧时钟/旧历史算法尚未对齐目标；R2-006-001终端重入旧属性仍是已单列的既有缺陷。各模块数量详见JSON，不将所有失败统称为NotImplementedError；部分断言只能在R4实现后继续触达。没有以实现业务或模拟结果让R2基线转绿。

本轮完成设计、注释与黑盒同步，**没有实际实现HTML排版、30FPS或完整主题**，也未进行真实GUI终端截图对照或新安装包验收。这些是R4/R5必做的视觉/运行验证，不能以本轮静态图面和测试数量替代。R2维持ready，后续接收角色仍为R3。

## v1.2 同步结果与验证（历史）

本轮按用户“继续同步其它所有文件”完成前次遗留：

- 新增`history.py`：纯`bucket_history`、冻结`HistoryScale`、独立`HistoryScaleTracker`；模型＋指标尺度、五秒计时、全部模型更新、任意精度上限和原子校验均具备公开契约。新增行为方法仍抛NotImplementedError。
- 新增`timing.py`：固定30FPS元数据及`FrameSchedule(start)`的due/timeout/advance骨架；首次、慢帧跳槽、重复推进、resize保持原节拍和参数校验已冻结。
- `compose_frame`与`vllm_cells`追加兼容的可选关键字`history_scales`；声明纯调用默认即时nice尺度、显式匹配/错误拒绝、标签布局与极值处理。`ObserverApp`补齐同一快照/时钟、全部模型、小窗口、跨run和帧截止点目标注释；现有执行体未改。
- 新增三个测试文件，并同步旧短轴、共享桶、峰值铺满、10Hz时序以及主题/PTY断言。原有采样隔离、数据不可变、缺口、真实退出与终端恢复断言保留；不以xfail/skip掩盖新业务。
- 同步应用外壳v1.10、vLLMv1.6、主题v1.2、导航v1.6、REQ-004视图契约、README及当前分支记录。原HTML已保留Hologram和柱状参考，本轮未把静态设计预览改成30FPS应用或换图型。

| 本轮新增 / 同步文件 | 范围 |
| --- | --- |
| [history.py](../../../../src/joi_observer/tui/history.py) | 分桶、尺度数据、会话接口骨架及完整行为注释 |
| [timing.py](../../../../src/joi_observer/tui/timing.py) | 30FPS常量和无I/O帧时钟骨架 |
| [test_history_presentation.py](../../../../tests/test_history_presentation.py) | 89项：窗口/分桶/缺口、尺度/5秒/未知/隔离/原子性与极值 |
| [test_frame_timing.py](../../../../tests/test_frame_timing.py) | 39项：35个帧时钟契约及4个真实应用调度边界 |
| [test_history_app.py](../../../../tests/test_history_app.py) | 3项：默认接线、未选中尺度、主题/resize/小窗口和跨run/新实例 |
| [test_vllm_view.py](../../../../tests/test_vllm_view.py) | 110项：沿用指标契约，同步固定轴并新增尺度/边界/标签/极值；纯调用与显式尺度均覆盖 |
| 导航、主题视图及vLLM PTY | 同步30Hz、固定轴、显式尺度与真实RGB期待；PTY仍在完成交互及恢复后报告业务差异 |

验证位置仍为本地WSL Ubuntu-24.04，`/mnt/d/Documents/joi-observer`；使用既有 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`，无安装或服务器连接。命令：

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r2-sync-pytest.xml
python docs/dev-workflow/dev-0/REQ-006/evidence/audit-r2-sync.py
git diff --check
```

| 验证 | 实际结果 / 证据 |
| --- | --- |
| 完整集合 | **1701项：1429 passed / 272 failed / 0 errors / 0 skipped，34.67s**；pytest退出1。[输出](evidence/r2-sync-pytest.txt)、[JUnit](evidence/r2-sync-pytest.xml)、[模块与失败明细](evidence/r2-sync-summary.json) |
| 新增历史/时钟/应用三文件 | **131项：1通过、130失败**；数据冻结性通过，其余为未实现接口或缺失默认接线，未出现导入/环境错误 |
| 所有受影响模块 | 上表及主题/导航共371项，99通过、272失败；其余测试模块**1330项全部通过** |
| R2边界 | 原有26份生产Python去除docstring、允许Frame.theme字段/HistoryScale类型导入/新增history_scales形参后，AST与基点一致；9个新增行为入口均为未实现骨架。[审计脚本](evidence/audit-r2-sync.py)、[审计结果](evidence/r2-sync-audit.json) |
| 静态复核 | 模块图、接口、文档本地链接及git diff --check通过；Mermaid为静态核对，未用渲染器。未运行新安装包或真实GUI终端帧率/观感验收 |

失败按公开入口归类（数量互不重叠）：

| 模块 | 失败数 | 性质 |
| --- | --- | --- |
| history_presentation | 88 | 分桶/尺度业务入口未实现，含合法及异常场景；后续断言未全程执行 |
| frame_timing | 39 | 28个方法骨架、7个构造校验、4个实际应用仍10Hz的调度契约 |
| history_app | 3 | 默认应用未创建/传递尺度，没有Scale标签；后续五秒和隔离断言待实现后执行 |
| vllm_view | 52 | 原短轴/重铺/按峰值拉满算法及未接显式尺度/错误验证/标签；新增极值期待不能由旧算法证明 |
| navigation / navigation_app / navigation_pty | 25 / 9 / 1 | 默认主题未改、固定轴/尺度缺失及30Hz接线未完成；显式注入测试继续通过 |
| theme_palette / theme_terminal / theme_view | 11 / 35 / 8 | 原配色骨架/背景接线、Frame主题元数据、显式尺度传递；包含已记录的R2-006-001终端重入旧属性缺陷 |
| vllm_pty | 1 | 真正完成18帧及q/termios恢复后失败于固定60秒轴，后续目标尺度/RGB断言仍被前置失败遮蔽 |

独立复核修正了history测试中三处一秒桶列号错误（70秒为第30列、80.2秒为第40列），并补充`sys.float_info.max`对应任意精度上限及最小正float非零柱，避免骨架提前失败隐藏错误断言。没有为了得到绿色结果实现被测业务或替换预期输出。既有R2-006-001继续单独作为真实缺陷交R4，其余本轮失败为目标行为尚未实现；历史v1.0数量不得作为本次集合结果。

## v1.1 柱状图与刷新方案修订（历史，遗留已由v1.2同步）

来源：用户看过点阵/面积图预览后明确要求“还是用原本的柱状图，用之前的优化方案，更新设计文档”。本轮仅改文档，未修改HTML、生产代码、接口注释或测试；不自动进入R3/R4。

- UI目标30 FPS；按下一帧截止点限制读键等待，慢绘制跳过过期帧，不补帧积压。采样默认仍为1秒，不新增60FPS模式或帧率配置。
- 原竖柱、1/8字符顶部、有效0基线点及失败缺口保留。横轴固定最近60秒；以图区宽度W、Δ=60/(W−1)建立绝对时间桶，同桶不移、跨桶统一左移，短历史左侧留白。当前桶即时接收真实新点，旧点离窗不触发全图重排。
- 纵轴用1/2/5×10^n上限，升档立即，目标连续低于当前档满5秒再降档；无有效观测保持尺度并清零计时，真实全0可降到最小1。按模型＋指标维护只读快照派生的UI会话状态，不写MonitorState或配置。
- 历史标题现有空余位置显示尺度上限，采用muted，不增加行数。纯compose_frame/vllm_cells消费显式不可变尺度值；新增具体类型/接口声明与黑盒待后续R2同步，不能通过隐式全局状态破坏纯渲染。
- 需求v1.14新增AC-609～612；[应用外壳](../../../design/application-shell.md) v1.9维护帧调度，[vLLM设计](../../../design/vllm.md#101-稳定柱状历史与显示尺度) v1.5维护图表公式，[REQ-004视图契约](../REQ-004/view-contract.md)改为引用新口径。主题v1.1、导航v1.5、AGENTS与README同步，原HTML柱图仍是视觉参考。

**尚未执行的接口与测试同步**：30FPS调度/超预算跳帧、固定短历史留白/端点/同桶/缺口、纵轴5秒迟降与不同模型尺度隔离、尺度标题布局、终端无变化帧输出。tests/test_navigation_app.py中10Hz时序以及tests/test_vllm_view.py/test_vllm_pty.py的短轴和自动拉满高度断言须更新；不是现在已经通过的新验收。本轮不修改它们以保持用户指定的文档范围。

**本轮文档核验**：在本地WSL Ubuntu-24.04，使用既有Python 3.12解释器，以Fraction精确运算核对W=2/3/60/76/120/251的126组合法端点/窗口样例；全部落入0..W−1，旧点过期不重排其余点、推进一桶恰左移一列的示例通过。更新文档的本地链接检查与git diff --check通过；没有重跑应用测试，也没有测得真实终端30FPS。此核对验证文档公式，不替代后续生产代码的浮点边界/帧调度/尺度状态测试。

## 产物

| 产物 | 内容 |
| --- | --- |
| [theme.md](../../../design/theme.md) | v1.2：30 FPS/柱状接口与黑盒同步；UML 类图、颜色角色、会话/帧/终端协作、颜色能力降级、整屏背景、资源恢复、布局复用与验收映射 |
| [application-shell.md](../../../design/application-shell.md) | v1.10：帧时钟/尺度协作类图、接口与黑盒；30 FPS截止点、跳帧和无变化帧输出；Frame.theme 与 TerminalPort/CursesTerminal 目标接线，更新 REQ-005 已合并现状 |
| [navigation.md](../../../design/navigation.md) | v1.6：同步30 FPS黑盒；启动默认 Hologram，保留会话/注入/导航规则与历史交接 |
| [theme.py](../../../../src/joi_observer/tui/theme.py) | DEFAULT_THEME、冻结 Palette、palette_for 与 CursesTheme 的可加载骨架；行为入口抛 NotImplementedError |
| [layout.py](../../../../src/joi_observer/tui/layout.py)、[navigation.py](../../../../src/joi_observer/tui/navigation.py)、[app.py](../../../../src/joi_observer/tui/app.py) | Frame.theme 结构声明与目标注释；已有函数执行体不改 |
| [test_theme_palette.py](../../../../tests/test_theme_palette.py) | 默认元数据、精确 RGB、冻结性、非法主题 |
| [test_theme_view.py](../../../../tests/test_theme_view.py) | 主题默认与传递、全屏语义角色、琥珀、三类型和各来源失败/恢复、半页/Storage/Docker/长名称 |
| [test_theme_terminal.py](../../../../tests/test_theme_terminal.py) | 配色公开接口及真实 CursesTerminal 配合终端边界替身，颜色能力、背景、切换、失败及恢复 |
| [test_navigation.py](../../../../tests/test_navigation.py)、[test_navigation_app.py](../../../../tests/test_navigation_app.py)、[test_navigation_pty.py](../../../../tests/test_navigation_pty.py) | 按 v1.13 修订默认及切换顺序；保留显式注入 Hologram，补两次 t、鼠标无动作与真实 PTY 配色观察 |
| [test_vllm_pty.py](../../../../tests/test_vllm_pty.py) | 三类型/状态/resize 既有流程，改以真实 RGB 和空白背景代替基础白/黄色号 |
| [requirements.md](../requirements.md)、[AGENTS.md](../../../../AGENTS.md)、[README.md](../../../../README.md)、[joi-observer.html](../../../design/joi-observer.html) | 用户默认主题修订、R2 状态/入口及 Hologram 初始设计预览 |

未改采集器、Monitor/State、配置解析、依赖或锁文件；没有 R3 plan、R4 实现、Git 提交或推送。证据沿用 `.gitignore` 中 `/docs/dev-workflow/**/evidence/` 规则。

## v1.0 历史验证证据

验证位置为本地 WSL Ubuntu-24.04，目录 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`（Python 3.12.3）。仅复用已有离线依赖；pytest 阻断 DNS/connect，PTY 子进程同样禁用网络，不连接部署服务器、不发推理请求。

本轮实际执行（`python` 指上述 WSL 解释器）：

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r2-pytest.xml
python docs/dev-workflow/dev-0/REQ-006/evidence/audit-r2.py
git diff --check
```

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 全量离线基线 | **1530 项：1444 passed / 86 failed / 0 errors / 0 skipped，31.50s** | [输出](evidence/r2-pytest.txt)、[JUnit](evidence/r2-pytest.xml)、[分类](evidence/r2-summary.json) |
| 新增主题三个文件 | **78 项：27通过、51失败**；palette 1/11、view 26/5、terminal 0/35（通过/失败） | 同上 |
| 修订导航三文件 | **48 项：14通过、34失败**；含新增2个鼠标无动作参数，显式注入 Hologram 两场景通过 | 同上 |
| 修订 vLLM PTY | 1 项失败于真实 RGB 仍为旧基础色；完整运行与 termios 恢复先于业务断言完成 | 同上 |
| 其余原有测试 | **1403 项全部通过**，没有修改这些测试 | 同一全量结果 |
| R2 执行体审计 | 原有26份生产Python去除docstring、忽略新增Frame.theme声明后，与HEAD的AST一致；4个新增业务入口仍为NotImplementedError骨架 | [审计](evidence/r2-audit.json)、[脚本](evidence/audit-r2.py) |
| 一致性复核 | 新设计/交接本地链接有效；图中类型/字段/关系与目标接口一致，固定256色索引及PTY RGB独立核算；git diff --check通过 | 审计同上；Mermaid只作静态核对，未运行渲染器 |

这里的通过数与REQ-005原1450项不直接比较：本轮新增78项并增加2个导航参数，同时按已修订需求修改默认主题及旧基础颜色期待。已通过项不能证明尚未触达的后续断言；没有将骨架失败改成skip/xfail。

### 失败分类与 R4 输入

| 分类 | 数量 | 结论 |
| --- | --- | --- |
| palette_for / CursesTheme 骨架 | 43 | 11个纯palette和32个配色器用例尚未实现；包含异常传播用例先遇到NotImplementedError，未证明目标异常路径 |
| 默认主题仍为 Moonlight | 37 | 导航34项及主题视图3项；按需求v1.13更改默认值即可进入后续断言，不应回改测试 |
| Frame 未传递显式主题 | 2 | 正常与too_small返回都遗漏view.theme，目前字段固定使用新声明默认值 |
| 后端配色接线未完成 | 3 | 全窗口背景、颜色恢复接线以及真实vLLM RGB；颜色恢复用例当前尚未产生私有色槽，因此未验证其后续失败处理 |
| **R2-006-001：终端重入残留属性** | 1 | 原有缺陷，不能仅归为新增骨架；见下文 |

**R2-006-001（P2）**：复用一个CursesTerminal，先在有色终端enter/render/restore，再在无色终端enter/render。现有_styles未清理，第二轮仍给Observer属性256，目标是0。公开复现为`test_theme_terminal.py::test_terminal_reentry_reprobes_monochrome_without_old_color_attributes`，只替换curses/termios边界。R4按每次enter独立CursesTheme和restore清缓存契约一并修复；R2不改旧执行体。

真实导航PTY已完成10帧与两次t、完整按键、q、光标/备用屏/termios恢复，再失败于首帧默认主题；实际主/辅/次要色与空白背景已采集，但后续目标RGB断言被首个业务失败遮蔽，不能记为通过。真实vLLM PTY的18帧全部完成，正文实测[680,680,680]，目标[831,867,922]。没有环境错误或服务器连接。

尚未运行安装包验收、真实GUI终端的最终观感复核；没有实际实现颜色恢复，因此不声称终端色表恢复已通过。以上为v1.0时点列出的实现后验证；v1.1另需先补齐上节R2接口/黑盒，不能据此认为新增范围已具备完整交接条件。

## 本轮决策

1. 默认主题按用户明确指令改为 Hologram，不重新申请确认；旧 R1/REQ-005 交接保留历史时点结果，当前以需求 v1.14 和本交接为准，v1.13记录保留历史依据。
2. 复用 ViewSelection 与 SessionViewActions；唯一默认元数据在 theme.DEFAULT_THEME，R4 改 ViewSelection 默认值即可衔接控制器。Frame.theme 独立于标题文字，覆盖小窗口。
3. 颜色归 Palette、语义归已有控件、终端能力与资源归 CursesTheme。精确模式不叠加 dim，五个角色共用背景；仅在基础色降级时使用白色加 dim。
4. 精确模式只改编号 ≥16 的私有色槽并保存还原；固定256色按明确最近色，基础色/无色仍可操作。能力异常不写采集 ERROR、不新增 UI 诊断；程序异常不被伪装为能力不足。
5. 保持半页、Storage 三行、Docker 余高与隐藏前缀、全部模型继续采集的已合并行为。HTML 仍为设计预览，其鼠标和状态保存不代表正式 TUI 交互。
6. 旧测试按用户已确认的默认主题/实际RGB、30Hz、固定时间轴及尺度契约同步，保留显式注入、采样隔离和生命周期断言；不xfail，不将骨架未实现视为通过。

## 待完成的实现与验收

R4 完成 palette_for/CursesTheme、ViewSelection默认值、FrameSchedule、bucket_history/HistoryScaleTracker、compose_frame/vllm_cells尺度与主题传递、ObserverApp默认接线及CursesTerminal配色，并修复R2-006-001。按本交接重新执行全量及离线安装包验证；补齐实际终端颜色恢复、字体与最终观感复核。没有待用户决定的范围问题，现场服务器验证不属于此任务。

## 下一步

本轮HTML排版以及先前尺度输入/状态边界、30FPS目标注释和黑盒均已同步，WSL基线明确，result为ready。接收角色为 **R3**，依据本交接与共享主题/历史/外壳设计，在 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006\plan.md` 编写概要开发计划，覆盖HTML对应的上下区排版/裁切/对齐、默认/帧传递、配色资源、30FPS调度、稳定时间桶/尺度、后端接线、失败与恢复及离线全量/安装/视觉对照验证。由用户另行发起 R3；本轮不自动创建或推进其他角色聊天。
