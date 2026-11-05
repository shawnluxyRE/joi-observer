# dev-0 / REQ-006 R4 交接

- stage：R4
- result：ready
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006`
- 需求依据：[requirements.md](../requirements.md) v1.24，REQ-006统一半块分段与独立深灰轨道、右侧三处留白、数字强调及R5-006-003页眉回退契约。
- 计划依据：[plan.md](plan.md) v1.0及用户GUI反馈执行补充、[handoff-r2.md](handoff-r2.md) v1.4（被用户直接修订的Storage规则见当前设计）。
- next_role：R5
- 修订：v1.10，2026-11-05，GPU/CPU/RAM分段统一▌，未填充段采用独立深灰track；按用户要求不生成离线包。

## 产物

沿用 `codex/dev0-req006` 当前工作区，保留已有R2/R3/R5未提交产物。本轮按用户明确修订将GPU/CPU/RAM两段都画为▌，未填充段独立深灰，未关联GPU填充仍为原muted灰。用户要求不再生成离线包，因此本轮仅修改源码、文档和执行本地测试，旧wheel/已安装CLI/Frame回放不含本轮变化。前轮vLLM三处留白、数值加粗及页眉修复保持。001/002保持关闭，003为R4已修复待R5复验；当前GUI观感仍未验。下文保留历史轮次，当前结论以页首状态及“统一半块与深灰轨道”节为准。没有提交、切分支、推送或连接服务器。

| 任务 | 完成情况与产物 |
| --- | --- |
| T-001 双主题与终端 | [theme.py](../../../../src/joi_observer/tui/theme.py) 实现冻结 Palette、精确RGB/固定256色/基础色/单色及异常降级；[app.py](../../../../src/joi_observer/tui/app.py) 每次enter独立资源、逐帧背景、退出归还私有色槽；[layout.py](../../../../src/joi_observer/tui/layout.py) 默认Hologram与正常/小窗口Frame元数据一致。R2-006-001已修复。 |
| T-002 外壳/硬件 | [layout.py](../../../../src/joi_observer/tui/layout.py)、[widgets.py](../../../../src/joi_observer/tui/widgets.py)：3:2上区、Host四内容行、Storage三行、Docker余高；页眉及各数值/状态右齐、角色与共享单位分色、长Unicode优先裁名称、过宽数字保留科学记数/单位。公共format_metric/capacity_text未改语义。 |
| T-003 服务 | [vllm.py](../../../../src/joi_observer/tui/vllm.py)：24列三层模型栏、选中可见窗口、双统计/caption、四列标签与数值；三类型适用性与真实单位、六字符状态槽、路由、GPU联动和既有导航保持。 |
| T-004 历史 | [history.py](../../../../src/joi_observer/tui/history.py)：闭60秒窗口、绝对时间桶、桶内缺口优先、有效0、任意精度1/2/5档；模型/指标独立五秒迟降、原子校验；vllm/layout消费冻结尺度。正极小值保留八分之一柱，极大有限值无溢出/裁峰。 |
| T-005 调度 | [timing.py](../../../../src/joi_observer/tui/timing.py)、app.py：当前固定起点60Hz，截止点内读键、resize即时绘制、慢帧跳过旧槽、ready输入主动让出；每帧一次快照/选择，全部模型同一now推进尺度；小窗口保留图区宽度，同实例跨run保留选择/尺度、重启帧节拍。 |
| T-006 联验与交付 | 最终1835项通过、最终wheel隔离uv安装与真实CLI通过；[README](../../../../README.md)更新实际能力；[23场景预览](evidence/r4-visual/index.html)、[Frame数据](evidence/r4-visual/frames.json)、PNG与[对照表](evidence/r4-visual/comparison.html)已生成。实际GUI工具策略阻碍详见待决事项。 |

首次新增 [test_frame_timing_edges.py](../../../../tests/test_frame_timing_edges.py) 8项有效补测；初次测试变更限下列R2观察器修正。相对R3输入，首次生产仅改7份TUI文件、未改采集/数据/配置解析/日志/公共运行依赖，首次SHA与差异见[audit](evidence/r4-audit.json)。GUI返修另更新随包示例YAML并新增Storage展示边界测试，详见下文。

## 统一半块与深灰轨道（当前交付）

主对话与三个subagent先核对语义角色、颜色资源/恢复、基础色降级、硬件比例与测试观察器，汇总无阻塞后实施。此用户修订明确覆盖旧▌/▏双字形和轨道muted规则；单独调整硬件轨道，不改变其他灰色文字。需求及设计同步；用户“不生成离线包”优先于原T-006每轮重建安排。

- [widgets.py](../../../../src/joi_observer/tui/widgets.py)按原filled/empty长度绘制两段▌，empty改用track；填充角色、段数、条宽/行高、百分比和数字位置保持。公开percentage_bar仍返回█/░，算法与容量/GPU关联规则不变。
- [theme.py](../../../../src/joi_observer/tui/theme.py)新增track目标色`#3E4A5B`，原五色值和色对编号保持。Palette末尾默认track兼容旧构造；精确模式用7私有槽16..22和6非零色对1..6，色对能力阈值为7；固定256选择239。基础8～255色用BLACK+A_BOLD近似深灰，muted仍WHITE+A_DIM，实际明暗由终端ANSI及bold/dim处理决定；单色颜色属性为0，不承诺无色终端的颜色区分。不改TERM、基础调色板、全局背景或原Moonlight辅色。
- 硬件测试改为按固定列与原填充数量分别检查两段角色，不能再凭同一字形判断比例；真实PTY用已有公开宽字符接口观察实际字形、RGB和背景。主题验证覆盖新增资源边界与恢复，并保留原数字bold/主题重绘行为。vLLM、布局、调度、历史和采样源码保持。

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| Palette/主题后端/双TERM真实PTY | **68 passed，1.21s**；精确/固定256/基础色/单色、旧构造兼容、7槽/6非零色对边界与故障回滚/恢复，xterm实际SGR验证track亮黑和muted dim白分离且属性不泄漏；[输出](evidence/r4-track-gray-theme.txt)、[JUnit](evidence/r4-track-gray-theme.xml) |
| 硬件/布局/导航/真实PTY | **296 passed，6.91s**；两段同▌、原填充分界/0/未知/100%、未关联GPU分色、原RGB/背景与数字列；[输出](evidence/r4-track-gray-hardware.txt)、[JUnit](evidence/r4-track-gray-hardware.xml) |
| **最终WSL全量** | **1946 passed / 0 failed / 0 errors / 0 skipped，31.43s**；[输出](evidence/r4-track-gray-final-pytest.txt)、[JUnit](evidence/r4-track-gray-final-pytest.xml) |
| 源码及范围审计 | 生产仅theme.py/widgets.py变化；公开percentage_bar/capacity_text/linked_gpu_ids的AST保持，其他源码不变，R5交接未改。旧wheel、两GUI脚本及23Frame文件hash完全保持；[脚本](evidence/r4-track-gray-audit.py)、[结果](evidence/r4-track-gray-audit.json)。git diff --check通过 |

实际命令（本地WSL Ubuntu，项目根目录）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-track-gray-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-track-gray-audit.py
```

**交付范围：不构建、不安装、不重新生成Frame/HTML/PNG。** 旧`r4-install`及`r4-visual`入口保持三处留白版本，仅作为历史材料；使用旧入口看到▏不代表当前源码未修改。本轮GUI观感仍未验证。[人工清单](manual-gui-checklist.md)页首已明确版本范围。

后续用户另行请求预览图：在独立目录生成一张[当前源码Hologram静态图](evidence/r4-track-gray-preview/hologram-chat-dark-track-120x48.png)，使用现有离线样本及真实compose_frame输出，重点可见GPU4的muted填充与track轨道；[Frame](evidence/r4-track-gray-preview/frames.json)和[源码hash](evidence/r4-track-gray-preview/manifest.json)留存。此静态预览不代表实际终端截图/低色效果，不构建或安装包，不覆盖上述旧23Frame/GUI入口。

## vLLM右侧三处留白（上一轮交付）

主对话与三个subagent核对行位、最小图高、既有测试及证据消费后实施。需求v1.23、theme v1.11、vLLM v1.12、shell v1.19、REQ-004 view-contract v1.3和AGENTS/README同步；这是用户明确的显示修订，覆盖旧固定行位及“图区高度不变”的相应描述。原HTML设计片段不修改。

生产仅改[vllm.py](../../../../src/joi_observer/tui/vllm.py)的右侧相对行位：+1留白，+2模型/状态，+3路由，+4横线，+5留白，+6统计/+7caption，+8横线，+9指标标签/+10数字，+11留白，+12历史标题，+13..height-3柱图；横轴仍height-2。Pooling同样在RATE HISTORY前留空。最小service高度16仍有1行图；左栏、外框、半页、最低终端尺寸、全部字段/配色/数值加粗保持。历史图按减少3行后的实际高度重算柱高，时间分桶、尺度、数据、60Hz和采样不变。

测试只适配上述行位及新图高，保留原模型/字段/色彩/历史边界含义，在既有三类型/尺寸与PTY用例中检查三处右侧空白。半尺度检查改按新高度精确校验八分之一格数量及半块，不把最小1行图误要求为原4行图；无新增重复测试。

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| 视图/导航/主题/集成/真实PTY | **248 passed，4.41s**；[输出](evidence/r4-vllm-spacing-view.txt)、[JUnit](evidence/r4-vllm-spacing-view.xml) |
| **最终WSL全量** | **1937 passed / 0 failed / 0 errors / 0 skipped，32.64s**；[输出](evidence/r4-vllm-spacing-final-pytest.txt)、[JUnit](evidence/r4-vllm-spacing-final-pytest.xml) |
| wheel/已安装CLI | 源码/YAML/README逐字节匹配；实际屏幕检查三空行、模型识别及数字bold新行位；[安装结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-vllm-spacing-install-summary.json) |
| CLI节拍/采样 | 253帧，119间隔中位16.826ms；三模型各5轮采样、中位约1.00730秒；颜色/termios/端口关闭通过，无网络/外部进程尝试。这是本地PTY测量，不保证GUI可见FPS |
| 回放与预览 | [基础色PTY](evidence/r4-visual/r4-vllm-spacing-frame-pty-basic-smoke.json)、[256色PTY](evidence/r4-visual/r4-vllm-spacing-frame-pty-256-smoke.json)均通过；23份HTML/PNG刷新并查看三空行及剩余图高，用户入口继承TERM |
| 最终审计 | 生产仅vllm.py变化，其他源码保持；23场景输入/区域/上半/左栏/外框/页脚完全相同，右侧只按既定映射移行且文字/role/bold保持；时间轴、正柱所在列、0与缺口保持，图高按新预算缩减。包/README/预览hash匹配、R5交接未改；[脚本](evidence/r4-vllm-spacing-audit.py)、[结果](evidence/r4-vllm-spacing-audit.json)。git diff --check通过 |

实际命令（本地WSL Ubuntu，项目根目录）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-vllm-spacing-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-vllm-spacing-audit.py
```

此轮wheel仍保留于`evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256 `2b0da25252bd051a5c1bb950818406a8e1a7dff2defc21c31b6b11963b3128ff`，历史环境`/tmp/joi-req006-install-_0p99m6u`。前版13份安装文件备份于`evidence/r4-install-before-vllm-spacing/`且SHA匹配。两条离线GUI启动脚本保留该环境，不含后续统一半块/深灰轨道源码修改；旧GUI确认亦不替代新观感。

## vLLM数字加粗（上一轮交付）

主对话与subagents先核对六个数值槽、颜色role、公共TextCell及终端/预览消费边界，确认可行后实施。用户明确的字重修订同步到需求v1.22、theme v1.10、vLLM v1.11、shell v1.18、REQ-004 view-contract v1.2及AGENTS/README；采集、调度和运行依赖保持。

- [layout.py](../../../../src/joi_observer/tui/layout.py)在TextCell末尾新增`bold: bool = False`，兼容旧三/四参数构造，颜色role保持独立。
- [vllm.py](../../../../src/joi_observer/tui/vllm.py)只标记右侧RUNNING/WAITING数字及历史标题上方四指标的数字；包括0、科学记数、STALE保留旧数。占位`—`/`N/A`/`…`、左栏计数、标签/单位、caption、状态与历史均不新增粗体。Pooling等价指标行沿用相同规则，KV N/A不加粗。
- [app.py](../../../../src/joi_observer/tui/app.py)仅在指定TextCell的原主题属性上叠加A_BOLD。原主题色对、背景及已有Moonlight基础色字重保留；低色终端可能把bold呈现为更亮，实际字体/亮度待用户GUI观感。ObserverApp调度AST未变。

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| 终端后端 | 45 passed；覆盖颜色/单色下独立A_BOLD及原色对/背景/恢复；[输出](evidence/r4-vllm-bold-terminal.txt)、[JUnit](evidence/r4-vllm-bold-terminal.xml) |
| 服务视图/真实PTY/导航 | 239 passed；验证指定数字加粗、占位/左栏/标签不新增粗体及RGB保持；[输出](evidence/r4-vllm-bold-view.txt)、[JUnit](evidence/r4-vllm-bold-view.xml) |
| **最终WSL全量** | **1937 passed / 0 failed / 0 errors / 0 skipped，29.97s**；[输出](evidence/r4-vllm-bold-final-pytest.txt)、[JUnit](evidence/r4-vllm-bold-final-pytest.xml) |
| wheel/已安装CLI | 源码/YAML/README逐字节一致；真实颜色属性验证`actual_A_BOLD = declared_bold OR theme_bold`；[安装结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-vllm-bold-install-summary.json) |
| 真实CLI节拍/采样 | 254帧，119间隔中位16.559ms；三模型各5轮采样、中位约1.00597秒；退出/termios恢复通过，网络/外部进程尝试为空。这是本地PTY证据，不推导GUI可见FPS |
| 双色能力回放 | [基础色PTY](evidence/r4-visual/r4-vllm-bold-frame-pty-basic-smoke.json)、[256色PTY](evidence/r4-visual/r4-vllm-bold-frame-pty-256-smoke.json)均通过，六个Chat数字实际A_BOLD、颜色及现有Moonlight亮紫属性正确；用户入口继承TERM |
| 预览与最终审计 | 23份完整场景仅新增cell.bold，移除字段后与前版Frame/输入/历史完全相等；HTML/PNG已更新并检查。源码仅app/layout/vllm变更、调度AST保持，包/README/预览hash一致，R5交接未改；[审计脚本](evidence/r4-vllm-bold-audit.py)、[结果](evidence/r4-vllm-bold-audit.json) |

实际命令（本地WSL Ubuntu，项目根目录）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-vllm-bold-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-vllm-bold-audit.py
```

此轮wheel已归档为`evidence/r4-install-before-vllm-spacing/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256 `330a6c1dd46939f69e610aabbde86d88ffd2d1785727700787e8fb2df03b7cb3`；历史环境`/tmp/joi-req006-install-crju6mls`。更早安装完整备份于`evidence/r4-install-before-vllm-bold/`，13文件SHA匹配。两个GUI入口路径保持。当前新MobaXterm观感仍未验证，旧GUI确认不用于关闭新范围；人工重点见[清单](manual-gui-checklist.md)。

## 硬件分格与页眉回退（上一轮交付）

主对话与subagents先核对用户分格目标、R5 v1.3及真实os-release复现、公共格式接口/硬件几何和离线安装边界，汇总可行后实施。需求v1.21、hardware v1.9、theme v1.9、shell v1.17、AGENTS/README同步；无公共接口、采集、调度或运行依赖变更。

### 硬件条半格空隙

仅[widgets.py](../../../../src/joi_observer/tui/widgets.py)的私有bar呈现把已有filled/empty数量分别映射到`▌`/`▏`，每个字形仍占一个字符格；填充左半块自带半格留白，轨道较细，使未关联GPU在同灰色下仍可辨识比例。主对话已向用户说明这一推荐选择，未伪称收到额外字形确认。

公开`percentage_bar`仍返回█/░，原ROUND_HALF_UP、数量、颜色角色、GPU关联、条宽/行高/百分比列保持；CPU/RAM数值行和所有其他字段保持。vLLM竖向历史柱、60FPS、1秒采样、分桶/尺度均未修改。23份真实Frame反向映射硬件glyph后与前版完整Frame/输入/历史逐项相等，见审计。

### R5-006-003：R4已修复，待R5复验

- 修复前实际复跑3个R5原文本样本均失败：缺PRETTY_NAME、空文件、空PRETTY_NAME且缺NAME被库默认Linux遮蔽。原报告保留，不改变预期为Linux。
- [cli.py](../../../../src/joi_observer/cli.py)改为私有本地reader，一次读取首个成功候选（/etc/os-release优先于/usr/lib/os-release），只解析实际提供的PRETTY_NAME/NAME/VERSION_ID。保留经本地标准库核对的赋值/引号/五类转义规则，不注入Linux默认字段、不依赖私有stdlib API或缓存、不执行shell。
- 优先非空PRETTY_NAME，否则NAME+VERSION_ID，缺失/空值分别Ubuntu/—；显式PRETTY_NAME=Linux或NAME=Linux正常保留。空可读首文件不与后续文件合并；open/read OSError可尝试下一候选，UTF-8错误丢弃部分字段直接未知。固定设备标签及无内核/DMI/网络探测边界保持。
- R5原3个样本、测试名、最终期望及真实生产ApplicationRuntime组装保留；只将文件位置替身从stdlib私有候选/缓存改到本模块候选路径，仍读取真实文件，不替换解析结果。原3个字典替身场景也改为原始文件IO，避免再次掩盖解析行为。新增14个真实文本边界覆盖显式Linux、引号/转义/不展开shell、重复字段、候选优先/不混合、缺文件、编码失败/丢弃部分结果和一次读取。

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| 修复前R5复现 | 3 failed；[输出](evidence/r4-segments-hostfix-baseline.txt)、[JUnit](evidence/r4-segments-hostfix-baseline.xml) |
| CLI真实文本/装配 | 45 passed；[输出](evidence/r4-segments-hostfix-cli.txt)、[JUnit](evidence/r4-segments-hostfix-cli.xml) |
| 硬件视图/集成/真实PTY | 296 passed；包括条槽全部▌/▏、宽字符颜色/背景和数字位置；[输出](evidence/r4-segments-hostfix-bars.txt)、[JUnit](evidence/r4-segments-hostfix-bars.xml) |
| **最终WSL全量** | **1934 passed / 0 failed / 0 errors / 0 skipped，30.74s**；[输出](evidence/r4-segments-hostfix-final-pytest.txt)、[JUnit](evidence/r4-segments-hostfix-final-pytest.xml)，含R5新增主题重绘重试及原001/002回归 |
| 新wheel/已安装CLI | passed，源码/YAML/README逐字节一致；已安装版本另外读取真实临时os-release文本验证3个缺字段和2个显式Linux案例；[安装结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-segments-hostfix-install-summary.json) |
| 真实CLI/PTY与采样 | 254帧，119间隔中位16.658ms；三模型各5轮，采样中位约1.00031秒；颜色/termios/端口清理通过，无DNS/connect/外部进程尝试。是本地PTY证据，不推导MobaXterm可见FPS |
| 手动回放入口 | 自有[基础色PTY](evidence/r4-visual/r4-segments-hostfix-frame-pty-basic-smoke.json)和[256色PTY](evidence/r4-visual/r4-segments-hostfix-frame-pty-256-smoke.json)通过，上半真实屏幕含▌/▏、不含原█/░；原GUI入口路径保持并继承TERM |
| 最终审计 | 生产仅cli.py/widgets.py变化；公共percentage/capacity/GPU映射函数执行AST及App/采样/历史/vLLM源码保持；23Frame只变硬件glyph、其他字段完全相等；新包/README/预览hash一致，R5交接原样保留；[脚本](evidence/r4-segments-hostfix-audit.py)、[结果](evidence/r4-segments-hostfix-audit.json)。git diff --check通过 |

实际命令（本地WSL Ubuntu，项目根目录）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q tests/test_cli.py --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-segments-hostfix-cli.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-segments-hostfix-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-segments-hostfix-audit.py
```

此轮wheel已归档为`evidence/r4-install-before-vllm-bold/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`；SHA-256 `4a2b138666e3f3d5f655dbff5327fb8a861e5b5a57cf24369ff0030fe7e065fc`，历史环境`/tmp/joi-req006-install-nrc5jgne`。更早完整备份于`evidence/r4-install-before-segments-hostfix/`，13文件SHA校验一致。R4代码与本地验证完成；R5-006-003的最终关闭交R5复验。GUI-006-002继续保留当前新MobaXterm观感未验，不用旧GUI-006-001或静态PNG顶替，也不为此连接服务器。

## 2026-11-05 60FPS调整（上一轮交付）

用户明确将柱图/界面刷新目标从30提高为60FPS。主对话与subagents先核对帧调度、既有公平性测试、历史/采样约束及安装验证，再实施。生产执行体仅将[FRAME_RATE](../../../../src/joi_observer/tui/timing.py)改为60，FRAME_INTERVAL自动为1/60；同步app/timing注释。固定起点相位、两个方向的公平性、缩放、跳过过期槽、终端恢复算法保持，未新增帧率配置或开关。

默认采样仍1秒，最近60秒历史、真实观测点/缺口、时间分桶和5秒尺度迟降均不变，不插值、不按60FPS制造新观测。需求v1.20、shell v1.16、vLLM v1.10、navigation v1.9、theme v1.8及AGENTS/README当前目标同步；历史30Hz记录不改写。

现有时序测试按新契约重算：0.205秒应13帧；慢帧/resize截止点重新核算；输入burst在首16.7ms内；周期输入用60次t及第61次q保留超过1秒的验证，混合相位组保持原墙钟跨度、6相位与快慢/缩放组合。R5两类公平性语义和断言强度保留，无新增重复测试，GiB指数/历史任意时刻等无关30数值未修改。

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| 帧时钟/公平性/导航/历史应用 | 86 passed；[输出](evidence/r4-60fps-timing.txt)、[JUnit](evidence/r4-60fps-timing.xml) |
| **最终WSL全量** | **1916 passed / 0 failed / 0 errors / 0 skipped，30.64s**；[输出](evidence/r4-60fps-final-pytest.txt)、[JUnit](evidence/r4-60fps-final-pytest.xml) |
| 新wheel及已安装常量 | passed，明确验证已安装FRAME_RATE=60、FRAME_INTERVAL=1/60，源码/YAML/README逐字节对应；[安装结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-60fps-install-summary.json) |
| 已安装真实CLI/PTY帧调度 | 253帧，119个普通间隔中位**16.618ms**、范围12.560～20.700ms；render平均0.154ms/最大1.151ms，q124.59ms。色彩/termios/端口关闭通过，网络/外部进程尝试为空；仅本地PTY测量，不保证所有GUI终端实际可见60FPS |
| 采样独立性 | 三模型各5轮采样，原始HTTP每三次GET为一轮，轮间隔中位约**0.99844秒**、范围0.98632～1.01963秒；返回响应字节保持，未因60Hz提高采集次数 |
| 颜色回放/预览 | [基础色](evidence/r4-visual/r4-60fps-frame-pty-basic-smoke.json)、[256色](evidence/r4-visual/r4-60fps-frame-pty-256-smoke.json)独立自有PTY均通过；两个GUI入口继承TERM。23个Frame及其输入/历史与升级前逐项相等，仅源hash更新 |
| 最终审计 | 排除注释及FRAME_RATE值后，app/timing可执行AST不变；其余生产源/配置/采集/数据/历史字节未变，安装与预览hash一致；[脚本](evidence/r4-60fps-audit.py)、[结果](evidence/r4-60fps-audit.json)；git diff --check通过 |

本轮命令（项目根目录，本地WSL Ubuntu）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-60fps-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-60fps-audit.py
```

此轮wheel已归档为`evidence/r4-install-before-segments-hostfix/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256 `bd9154f716e8fa2f9bf461a9bd9b01ef4b84e29af2ef1aabf1c4d52aa3f19843`，对应历史环境`/tmp/joi-req006-install-lpnou31h`。更早30FPS安装保留在`evidence/r4-install-before-60fps/`，最后一条非执行注释清理前的中间成功构建留`evidence/r4-60fps-pre-comment-install/`，均不替代当前最终结果。

## 2026-11-05显示调整（上一轮交付）

用户要求容器示例、Moonlight紫色、Storage左侧文字及页眉更新，并明确确认：设备标签固定`H3C R5300 G6`，Ubuntu发行版本自动读取；在提供`TERM=xterm`、COLORTERM/TMUX为空后，用户进一步要求**不修改TERM，选可显示的近似紫色**。最后这一指令覆盖先前的256色操作建议。主对话/subagents已先核对接口、布局和本地颜色能力，再按用户明确修订实施；需求v1.19及相关设计/README/AGENTS同步。

| 修改 | 结果 |
| --- | --- |
| 随包容器示例 | [config.yaml](../../../../src/joi_observer/examples/config.yaml)的containers包含`id: chat-container` / `name: flash-next-vllm`，注释要求替换实际名称/完整ID，`[]`可关闭。只更改示例，不修改用户配置，不启动Docker。 |
| 低色Moonlight | [theme.py](../../../../src/joi_observer/tui/theme.py)只在8～255色基础模式给Moonlight secondary使用MAGENTA+A_BOLD，作为终端亮紫近似；实际亮度/RGB由终端调色板和粗体处理决定，不宣称等于#C6A7FF。Hologram、精确/固定256目标色保持，不设置TERM。 |
| 主题重绘 | [app.py](../../../../src/joi_observer/tui/app.py)的CursesTerminal在主题变化时clearok(True)强制物理重绘，成功refresh后才记主题，enter/restore清缓存；同主题保留差分。原输出缺口为改调色板后未重写已有字形，现有curses内存颜色断言不能证明模拟器重着色；本轮已补真实PTY输出验证。ObserverApp调度AST与前版完全相同。 |
| Storage左侧文字 | [widgets.py](../../../../src/joi_observer/tui/widgets.py)的挂载路径和空配置文字改为正文text；容量/中点继续muted、百分比text，状态汇总、精度及布局保持。Neon Grid HTML对应路径同步正文色。 |
| 页眉第二行 | [cli.py](../../../../src/joi_observer/cli.py)仅在组合根启动装配时读取本机os-release，优先PRETTY_NAME，缺失退NAME+VERSION_ID，不可读/编码错误时Ubuntu —；固定设备标签是用户指定展示文字，不是DMI探测。[layout.py](../../../../src/joi_observer/tui/layout.py)用`设备 / 发行版`，保留右时钟与分色；不再取hostname/Linux内核号，不新增配置字段。 |
| 手动验证入口 | 两条原GUI脚本及其生成逻辑移除强制TERM赋值，继承调用者环境。专用测试PTY分别模拟xterm与256色，仅作用于测试子进程，不修改用户会话。 |

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| 配置示例/身份 | 105 passed；[输出](evidence/r4-ui-polish-config.txt)、[JUnit](evidence/r4-ui-polish-config.xml) |
| 布局/硬件/真实PTY | 325 passed；[输出](evidence/r4-ui-polish-layout.txt)、[JUnit](evidence/r4-ui-polish-layout.xml) |
| 主机信息/CLI/生命周期 | 35 passed；真实组合根覆盖完整发行版本、NAME+VERSION_ID、读取失败回退，禁止调用kernel release；[输出](evidence/r4-ui-polish-host.txt)、[JUnit](evidence/r4-ui-polish-host.xml) |
| 配色/主题切换/真实PTY | 58 passed；[输出](evidence/r4-ui-polish-theme-final.txt)、[JUnit](evidence/r4-ui-polish-theme-final.xml)；原重绘缺口[失败输出](evidence/r4-ui-polish-theme-before.txt)保留 |
| 实际颜色能力与输出 | [探针](evidence/r4-ui-polish-theme-probe.py)/[结果](evidence/r4-ui-polish-theme-probe.json)：xterm为8色，Moonlight secondary索引5且bold=true，切换重写字形；同主题重复帧0输出。256色仍原精确映射、不加bold。模拟器最终像素RGB/服务器GUI未现场验证 |
| **最终WSL全量** | **1916 passed / 0 failed / 0 errors / 0 skipped，31.03s**；[输出](evidence/r4-ui-polish-final-pytest.txt)、[JUnit](evidence/r4-ui-polish-final-pytest.xml) |
| 新wheel/真实CLI/已安装示例 | passed；源码/YAML/README逐字节一致，实际页眉为`H3C R5300 G6 / Ubuntu 24.04.5 LTS`并与本地os-release一致；已安装示例含容器条目，验证运行仍使用独立空容器配置；[安装结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-ui-polish-install-summary.json) |
| 继承TERM与回放 | 两GUI脚本无TERM赋值；自有PTY分别以xterm与256色运行同一回放器，提示、n/p、缩放、Moonlight、q、恢复均通过：[基础色](evidence/r4-visual/r4-ui-polish-frame-pty-basic-smoke.json)、[256色](evidence/r4-visual/r4-ui-polish-frame-pty-256-smoke.json) |
| 预览与最终审计 | 23份Frame/PNG/HTML参考刷新，真实路径角色/固定设备标题核对；源码及预览哈希一致、ObserverApp调度AST未改变、两GUI脚本继承TERM；[审计脚本](evidence/r4-ui-polish-audit.py)、[结果](evidence/r4-ui-polish-audit.json)，git diff --check通过 |

最终命令（本地WSL Ubuntu，项目根目录）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-ui-polish-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-ui-polish-audit.py
```

此轮30FPS wheel已归档为`evidence/r4-install-before-60fps/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256：`e4f0ea80e26c3d7bf75fb7d0def42d09ebdf2d436ac986335ba2e384f0d8d0c3`，对应历史环境`/tmp/joi-req006-install-zbrmoq8_`。更早R5已通过的安装证据保留于`evidence/r4-install-before-ui-polish-20261105/`，[清单](evidence/r4-install-before-ui-polish-20261105/backup-manifest.json)逐文件SHA一致。没有修改服务器环境。

## R5返修第二轮：R5-006-002（历史交付，R5已通过）

- 依据：[handoff-r5.md](handoff-r5.md) v1.1、AC-603/609/612、T-005。主对话与subagents先核对新失败、上一轮修复和两个方向的公平性，确认不需公共接口或计划范围变更后再实现。
- **R5 v1.2已复验通过并关闭002。** 以下保留当时修复证据：复现1.5/2.5/3.5μs相位，2.5μs曾失败、31次输入超过1秒却只画初始帧；邻近相位通过。根因是上一轮补丁没有区分“本轮是否已绘制”，把尚未画出的到期槽也advance掉。
- 生产仅改[app.py](../../../../src/joi_observer/tui/app.py)：每轮重置`drew_frame=False`，成功render后置True。读键前发现timeout<=0时，**未绘制**则保留deadline、让出并进入下一轮绘制，不能advance；**已绘制**才沿用001修复，用同一个read_now推进并获得正超时读键。未绘制到期分支最多经过一次即进入绘制；已绘制跨点分支必服务输入，从而同时保住到期显示和输入机会。
- 不改FrameSchedule、原30Hz相位、公共TerminalPort、采集频率、每帧一次快照/选择或finally恢复。application-shell同步这两个分支的实现说明，README本轮未改。
- R5两个问题的原用例及所有原断言完整保留。新增一组12项回归：6相位（截止前/恰好/之后，含2.5μs）×快速/混合慢绘制，穿插放大→小窗口→恢复、主题与模型切换，检查每阶段持续出帧、最大绘制/输入间隔、每帧状态一致、一次快照、正输入预算和原始相位。新增测试自身对resize帧速率的观察修正见R4-006-T07。

| 本轮实际验证 | 结果与证据 |
| --- | --- |
| 修复前原用例 | 1 failed / 2 passed，2.5μs只绘制初始帧；[输出](evidence/r4-r5-fix2-baseline.txt)、[JUnit](evidence/r4-r5-fix2-baseline.xml) |
| 修复后时序/历史应用/导航 | 86 passed，含两个R5问题及新增12组合；[输出](evidence/r4-r5-fix2-timing.txt)、[JUnit](evidence/r4-r5-fix2-timing.xml) |
| **当前最终WSL全量** | **1908 passed / 0 failed / 0 errors / 0 skipped，32.95s**；[输出](evidence/r4-r5-fix2-final-pytest.txt)、[JUnit](evidence/r4-r5-fix2-final-pytest.xml) |
| 当前wheel/隔离安装/真实CLI | passed，源码/YAML/README逐字节一致；常规主题/导航/缩放/退出及颜色/termios/IO关闭通过，网络/外部进程尝试为空；[安装结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-r5-fix2-install-summary.json) |
| 已安装真实PTY | 131帧，普通间隔中位33.425ms，render平均0.222ms/最大2.094ms，q响应203.01ms；常规PTY结果不代替001/002的确定性相位回归 |
| 回放/预览 | 新环境[回放冒烟](evidence/r4-visual/r4-r5-fix2-frame-pty-smoke.json)通过；23份Frame/PNG/HTML参考及manifest源hash刷新，原GUI入口路径保持并指向最新包 |
| 最终审计 | 相对R5复验的生产源码只有app.py改变；去掉本轮新增测试后可恢复R5测试文件**完全相同SHA-256**，证明原用例/断言未动；R5交接原样保留。测试、安装、源码/README和预览哈希一致；[脚本](evidence/r4-r5-fix2-audit.py)、[结果](evidence/r4-r5-fix2-audit.json)；git diff --check通过 |

实际命令（本地WSL Ubuntu-24.04，项目根目录，保留离线防护）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_frame_timing_edges.py tests/test_frame_timing.py tests/test_history_app.py tests/test_navigation_app.py \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-r5-fix2-timing.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-r5-fix2-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-r5-fix2-audit.py
```

此轮wheel已归档为`evidence/r4-install-before-ui-polish-20261105/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256：`159e48ddd1365fc0cb54408518a0922fd8eb46c41d013cee4a2878f01d322fb8`，对应历史环境`/tmp/joi-req006-install-pt8r3o12`。更早13份安装文件保留在`evidence/r4-install-before-r5-fix2/`并逐项校验，[备份清单](evidence/r4-install-before-r5-fix2/backup-manifest.json)。R5随后已复验关闭002，本段保留历史证据。

## R5返修第一轮：R5-006-001（历史交付，原问题已关闭）

- 接收依据：[handoff-r5.md](handoff-r5.md) v1.0，AC-609 / T-005。主对话与subagents先核对失败用例、FrameSchedule/TerminalPort契约、文档与安装条件，全部确认可行后才实现；不需要架构、公共接口或任务范围调整。
- **当前结论：R5已复验关闭R5-006-001。** 以下为初轮修复记录；该修复另引入R5-006-002，不能由原问题关闭推导整轮验收通过。在WSL复跑原用例，曾确认30次近截止慢帧中read_key为0；失败报告保留。根因是绘制结束后所选截止点在下一次读时钟时已过，原`continue`绕过了唯一输入读取。
- 修改仅位于生产[app.py](../../../../src/joi_observer/tui/app.py)的ObserverApp循环：读键前取一次`read_now`；若timeout非正，按该时刻跳过过期帧槽，再以同一时刻取得严格正timeout并调用read_key。原始`start+n/30`相位、跳帧、每帧一次快照/选择/尺度推进、独立采样及finally恢复保持；ready输入仍在处理后主动让出事件循环。
- 保留R5原`test_near_deadline_draws_do_not_starve_a_pending_quit`及断言，新增两个黑盒回归：慢帧下down/t在下一正常帧呈现；连续无输入后q仍能被读取，同时校验输入预算落原节拍、无补画、快照次数和兄弟任务运行机会。R5新增的主题失败/显示身份测试未改。
- R5非阻塞文档建议已处理：theme/application-shell/hardware当前阶段不再写成未实现骨架；历史设计/失败记录明确保留当时时点，不改公共契约或宣称R5已通过。README本轮未改。
- GUI-006-001按[R5用户确认](evidence/r5-user-gui-confirmation.json)关闭；手动清单改为复验参考，不再阻碍本轮交付，不推导新的截图、字体信息或GUI实测帧率。

| 本次实际验证 | 结果与证据 |
| --- | --- |
| 修复前复现 | 1 failed，30帧没有读取ready q；[输出](evidence/r4-r5-fix-baseline.txt)、[JUnit](evidence/r4-r5-fix-baseline.xml) |
| 修复后时序/历史应用/导航定向 | 71 passed，含R5原用例和2个新增回归；[输出](evidence/r4-r5-fix-timing.txt)、[JUnit](evidence/r4-r5-fix-timing.xml) |
| **最终WSL全量** | **1893 passed / 0 failed / 0 errors / 0 skipped，30.67s**；[输出](evidence/r4-r5-fix-final-pytest.txt)、[JUnit](evidence/r4-r5-fix-final-pytest.xml) |
| 最终源码wheel/离线uv安装/真实CLI | passed，全部源码Python/YAML/README逐字节一致；新shell异目录裸命令、三模型、两主题、缩放、q、颜色/termios/IO关闭均通过，DNS/connect/外部进程尝试为空；[结果](evidence/r4-install/uv-install-results.json)、[摘要](evidence/r4-r5-fix-install-summary.json) |
| 已安装PTY实测 | 130帧，59间隔中位33.457ms，render平均0.199ms/最大1.299ms，q响应73.09ms；仅本地PTY性能，精确跨截止点缺陷由受控时钟回归验证 |
| 回放/参考资产 | 新环境[回放冒烟](evidence/r4-visual/r4-r5-fix-frame-pty-smoke.json)通过；23个Frame/PNG及HTML参考重新生成，包含两处0s及当前源哈希，两个原GUI入口更新到新安装环境 |
| 最终审计 | 相对R5审查源码只有app.py改变；R5交接和另外两份新增测试文件未改；测试全绿、源码/README/wheel及预览哈希一致；[审计脚本](evidence/r4-r5-fix-audit.py)、[结果](evidence/r4-r5-fix-audit.json)。git diff --check通过 |

实际命令（仓库根目录、本地WSL Ubuntu-24.04，保留离线防护）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_frame_timing_edges.py tests/test_frame_timing.py tests/test_history_app.py tests/test_navigation_app.py \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-r5-fix-timing.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-r5-fix-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-r5-fix-audit.py
```

第一轮修复wheel已归档为`evidence/r4-install-before-r5-fix2/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256：`2f1d98c360cda8be71bdca3a746c502e451f0290a8eab9d995c2e1908cb8b273`，对应历史环境`/tmp/joi-req006-install-kd006op9`。更早的13份安装文件保留于`evidence/r4-install-before-r5-fix/`，见[哈希清单](evidence/r4-install-before-r5-fix/backup-manifest.json)。R5随后已关闭001并提交002；本段原ready结论只表示当时具备复验条件，不是R5验收通过。

## 开发前检查（首次实现记录）

主对话与三个 subagent 已分别检查全部任务的需求、设计、接口及黑盒；2026-11-04 汇总确认可行后才开始修改实现。未发现阻碍开发的设计/计划问题。

| 范围 | 责任与文件边界 | 检查结论 |
| --- | --- | --- |
| T-001 配色、T-004 分桶/尺度 | theme_history：`tui/theme.py`、`tui/history.py` | 公开契约齐全；私有即时档位算法供纯渲染复用。 |
| T-002 外壳/硬件及布局接线 | shell_hardware：`tui/layout.py`、`tui/widgets.py` | 3:2、Host6、24列模型栏及88列历史几何一致。 |
| T-003 服务、T-004 历史呈现 | service_view：`tui/vllm.py` | 三层列表、统计/四指标、固定行位及尺度输入可独立实现。 |
| T-001 终端、T-005 调度、T-006 集成 | 主对话：`tui/app.py`、`tui/timing.py`、交接与证据 | 选择/尺度按应用实例、帧节拍按run、配色按enter分别管理。 |

## 验证证据

实际执行平台为本地 WSL `Ubuntu-24.04` / Python 3.12.3，工作目录 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。禁止服务器连接，保留测试 DNS/connect 防护。

以下表格保留**用户GUI反馈前首次交付**的实际执行结果，不借用R2/R3历史通过结论；当前修订验证见后续“用户GUI反馈返修”。测试及安装子进程显式阻断DNS/connect，未连接部署服务器或发送推理请求。

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| 主题/历史定向 | 136 passed，含终端重入与颜色恢复 | [输出](evidence/r4-theme-history-pytest.txt)、[JUnit](evidence/r4-theme-history-pytest.xml) |
| 外壳/硬件定向 | 243 passed | [输出](evidence/r4-shell-pytest.txt)、[JUnit](evidence/r4-shell-pytest.xml) |
| 服务/导航定向 | 183 passed | [输出](evidence/r4-service-view.txt)、[JUnit](evidence/r4-service-view.xml) |
| 应用/时序/生命周期 | 102 passed | [输出](evidence/r4-app-pytest.txt)、[JUnit](evidence/r4-app-pytest.xml) |
| 首轮全量 | 1816 passed / 11 failed；均已定位并按下节修正测试观察器。保留失败报告，不覆盖 | [输出](evidence/r4-integration-pytest.txt)、[JUnit](evidence/r4-integration-pytest.xml) |
| 修复后定向 | 硬件/极大时刻67 passed；主题历史123 passed；集成/真实vLLM PTY 8 passed | [硬件](evidence/r4-shell-integration-pytest.txt)、[主题历史](evidence/r4-service-history-theme-fixed.txt)、[集成PTY](evidence/r4-service-integration-pty-fixed.txt) |
| **首次Ubuntu全量** | **1835 passed / 0 failed / 0 errors / 0 skipped，33.33s**；包括硬件/vLLM/导航/生命周期真实PTY | [输出](evidence/r4-final-pytest.txt)、[JUnit](evidence/r4-final-pytest.xml) |
| 首次wheel与uv安装 | passed；异目录新shell裸命令、无激活/源码PYTHONPATH、示例入口、全部源码Python/YAML/README逐字节对应、3新增模块打包 | [安装脚本](evidence/r4-install-before-gui-feedback/verify_uv_install.py)、[结果](evidence/r4-install-before-gui-feedback/uv-install-results.json)、[首次复核](evidence/r4-audit.json) |
| 已安装真实CLI/PTY | 130帧；双主题实际RGB/ASCII文字与空白背景、三类型/导航/60秒轴/尺度、缩小/恢复、q/备用屏/光标/termios和6私有色恢复通过；DNS/connect/Popen尝试均为空 | 同一安装结果；只替换硬件与原始HTTP边界，CLI/配置/解析/Collector/Monitor/State/App/curses均真实 |
| PTY时序实测 | 最后59间隔中位33.300ms，范围31.085～35.062ms；平均render0.207ms、最大1.450ms；q退出82.95ms；采样仍配置1秒 | 同一安装结果；只证明本机PTY时序，不推导GUI可见30FPS |
| 视觉材料 | 23个真实Frame，双主题/三类型/120×40和48/160×48/STALE/长Unicode/0/未知/过小/恢复；逐帧边界与半页检查通过。离线Consolas 14px栅格图已抽查正常、pooling、STALE、长名、0、未知、小窗口 | [场景清单](evidence/r4-visual/manifest.json)、[生成脚本](evidence/r4-visual/generate_preview.py)、[PNG渲染脚本](evidence/r4-visual/render_frames.ps1)、[视觉边界记录](evidence/r4-visual/verification.json)。**这些不是终端截图** |
| 差异与交付检查 | git diff --check退出0（只有既有CRLF提示）；最终源码/README与安装wheel哈希一致 | [核对脚本](evidence/r4-audit.py)、[核对结果](evidence/r4-audit.json) |

首次验证命令（从仓库根目录、WSL Ubuntu运行；当前重验见下文）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-audit.py
```

首次wheel归档：`evidence/r4-install-before-gui-feedback/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256：`7240100e7d7e27d3603f87858c6c37a99e33d1b6da7cfdd2bb40d9b33898323c`。17份本地依赖wheel继续复用，构建/安装均`--offline --no-index --no-python-downloads`；不新增运行依赖。`evidence/`与依赖wheel被Git忽略，交接时须单独携带。

AC-601～608/613～616对应主题、导航、HTML布局/硬件、Docker、vLLM及状态回归；AC-609～612对应帧调度、历史纯函数/应用、真实PTY与已安装CLI。自动化断言全部通过；GUI字体和最终观感是额外独立验收项，尚未以自动化结果替代。

## 第一轮用户 GUI 反馈返修（名称与 Storage）

用户提供Windows Terminal实际截图并明确要求两项调整；属于对既定显示细节的直接修订，无需再交R2申请相同决定。需求v1.17、hardware v1.6、theme v1.5、application-shell v1.13、configuration v1.3、vllm v1.9、AGENTS与README已同步。

1. **展示名称**：确认`models[].name`同时控制列表和详情标题，省略`served_model_name`时会用name匹配服务。随包[示例配置](../../../../src/joi_observer/examples/config.yaml)与离线验证配置现使用Flash-Next、Embedding、Reranker，并显式保留对应qwen实际服务身份；未新增字段、硬编码列表标签或修改用户生产配置。示例解析/采集身份测试保持真实匹配。
2. **Storage**：`widgets.py`将前3个配置挂载点任一stale汇总为标题右上角一个STALE；第四项和未配置对象不参与。内容行不再占状态槽，容量/百分比组贴R右缘。仅Storage GiB从原始字节精确ROUND_HALF_UP到整数（1.49→1、1.5→2），TiB/GPU/RAM与公共capacity_text保留原格式；未知/0和三行固定预算不变。新增[test_storage_presentation.py](../../../../tests/test_storage_presentation.py)20项边界测试，原测试期待按用户新规则同步。

| 当前验证 | 实际结果与证据 |
| --- | --- |
| Storage定向/真实硬件PTY | 285 passed；[输出](evidence/r4-gui-feedback-hardware.txt)、[JUnit](evidence/r4-gui-feedback-hardware.xml) |
| 配置/示例/CLI/采集解析 | 277 passed；[输出](evidence/r4-gui-feedback-config.txt)、[JUnit](evidence/r4-gui-feedback-config.xml) |
| 返修首轮全量 | 1854 passed / 1 failed；定位为已有PTY观察器混用旧Frame与新物理尺寸，非产品绘制回归；[原报告](evidence/r4-gui-feedback-first-pytest.xml)、[输出](evidence/r4-gui-feedback-first-pytest.txt)，下节R4-006-T06记录修正 |
| PTY观察器修复定向 | 9 passed，含新增2项确定性resize竞态测试；[输出](evidence/r4-hardware-resize-observer-pytest.txt)、[JUnit](evidence/r4-hardware-resize-observer-pytest.xml) |
| **第一轮返修WSL全量** | **1857 passed / 0 failed / 0 errors / 0 skipped，30.72s**；[输出](evidence/r4-gui-feedback-final-pytest.txt)、[JUnit](evidence/r4-gui-feedback-final-pytest.xml) |
| 第一轮返修wheel/隔离安装/真实CLI | passed，源码/YAML/README逐字节一致，短名不影响真实served身份；[安装结果归档](evidence/r4-install-before-precision-feedback/uv-install-results.json)、[摘要](evidence/r4-gui-feedback-install-summary.json) |
| 当前安装PTY时序 | 130帧，最后59间隔中位33.316ms，render均值0.198ms/最大1.813ms，q退出72.44ms；恢复通过，DNS/connect/外部进程尝试为空。此时序仍不代表GUI可见FPS |
| Frame预览及手动入口 | 23场景HTML/JSON/PNG已按当前源码重生，已检查正常/STALE图；回放PTY小窗口/n/p/恢复/q复验通过，两条原启动脚本路径保持不变、改指当前安装环境 |
| 最终一致性 | [核对](evidence/r4-gui-feedback-audit.json)确认当前源码与安装wheel一致、Frame生成哈希一致、Storage仅标题STALE、短名与真实身份分离；git diff --check通过 |

本轮实际命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-gui-feedback-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-gui-feedback-audit.py
```

第一轮返修wheel归档：`evidence/r4-install-before-precision-feedback/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`；SHA-256 `f70590cc9520669a087b0e7c175ad69c8b5b54b5950135b52beeaada80daf138`，对应历史安装环境`/tmp/joi-req006-install-u_7weg7g`。更早的首次安装证据完整复制至`evidence/r4-install-before-gui-feedback/`且[备份清单](evidence/r4-install-before-gui-feedback/backup-manifest.json)逐文件哈希一致。

已收到的两张人工截图与初始会话报告摘要见[人工输入记录](evidence/manual-gui/user-initial-summary.json)，可确认Hologram实际字形、五GPU/STALE回放与正式CLI的pooling零历史；未推导用户已接受全部项目。当前Windows Terminal版本由appshot为1.24.12741.0，字体/字号尚未提供。更新后的正常与STALE布局仍需按[检查清单](manual-gui-checklist.md)复验，因此result继续blocked。

## 第二轮 GUI 反馈返修（精度，历史验证）

用户要求RAM容量也显示整数，并将CPU/Storage已有百分比固定为一位小数；经明确询问，用户确认RAM保持现有布局、不添加百分比文字。需求v1.18、hardware v1.7、theme v1.6、application-shell v1.14、AGENTS与README已同步，覆盖上一轮RAM保持一位小数的旧约定。

- RAM的GiB/TiB容量均从原始字节直接ROUND_HALF_UP至整数，未知和0独立保留，不用已舍入的一位小数再取整；巨大整数以精确Decimal字符串处理，不触发int转字符串长度限制。
- CPU/Storage百分比在既有舍入结果上固定显示一位，例如`30.0%`、`0.0%`、`100.0%`；不改变CPU采样/原始比例/条格口径。CPU数字text、百分号muted，Storage百分比仍text。
- GPU容量/利用率、Storage TiB一位小数、公共`capacity_text`与`percentage_bar`契约保持；RAM没有新增百分比字段或布局行。
- 新增[test_hardware_precision.py](../../../../tests/test_hardware_precision.py)29项边界覆盖：GiB/TiB半值、避免二次舍入、未知/0、大整数、负零、百分比角色及原数据/公共helper不变；受影响HTML/硬件/运行期/主题/PTY期待按用户明确精度规则同步。

| 当前验证 | 实际结果与证据 |
| --- | --- |
| 硬件精度定向 | 316 passed，包含真实PTY；[输出](evidence/r4-precision-feedback-hardware.txt)、[JUnit](evidence/r4-precision-feedback-hardware.xml) |
| **精度返修WSL全量** | **1886 passed / 0 failed / 0 errors / 0 skipped，31.47s**；[输出](evidence/r4-precision-feedback-final-pytest.txt)、[JUnit](evidence/r4-precision-feedback-final-pytest.xml) |
| 当前源码/安装/预览一致性 | 结果见[安装摘要](evidence/r4-precision-feedback-install-summary.json)、[一致性核对](evidence/r4-precision-feedback-audit.json)；两条GUI入口路径保持，使用最新隔离安装环境 |
| 当前已安装CLI及回放PTY | passed，真实CLI130帧，间隔中位33.450ms，render平均0.237ms、最大1.431ms，q93.40ms；颜色/termios/IO关闭通过，网络/外部进程尝试为空。新的回放[冒烟报告](evidence/r4-visual/r4-precision-feedback-frame-pty-smoke.json)单独保留，未覆盖前轮报告 |

本轮复验命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r4-precision-feedback-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --keep-environment
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r4-precision-feedback-audit.py
```

上一轮13份安装文件已完整备份到`evidence/r4-install-before-precision-feedback/`并逐项校验SHA-256，见[备份清单](evidence/r4-install-before-precision-feedback/backup-manifest.json)。本轮不修改监控数据、配置接口或运行依赖；当前精度仍待用户GUI复验，不自动关闭GUI-006-001。

精度返修wheel归档为`evidence/r4-install-before-r5-fix/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`，SHA-256：`96dbfd37477d9674ea33278ede0c6bd2c9b097d35aa701168f7cb9be5e3b552e`，对应历史环境`/tmp/joi-req006-install-5w0arxlf`。该轮23份真实Frame和PNG已刷新，正常/0样本检查确认RAM无新增百分比、CPU/Storage保留尾零，GPU和Storage TiB保持原精度。静态预览仍不代替GUI截图。

## 本轮决策

1. 公共架构、签名和跨模块契约保持；仅以私有`history._scale_upper`复用同一精确档位算法。
2. 极大有限起点/跨度超出浮点帧分辨率时，FrameSchedule用Fraction保留原始1/30节拍；普通时刻保留既定浮点截止点语义。该实现修复避免溢出和逐tick无穷追赶，不改变时钟输入契约。
3. 终端每帧按完整Frame提交给curses差异输出，未引入额外写入缓存；读键/尺度计时不省略，采样独立。
4. 所有测试观察修订有明确已定布局依据，未降低业务期待、移除故障恢复断言、添加skip/xfail或更换预置业务结果。

## R2 修订汇总

### R2-006-001 终端重入残留属性

- 关联任务与产物：T-001，`tui/app.py` / `tui/theme.py`；`test_theme_terminal.py::test_terminal_reentry_reprobes_monochrome_without_old_color_attributes`。
- 问题与依据：有色会话结束后复用终端进入无色会话，不应保留旧属性。
- 处理与请求：每次 enter 独立 CursesTheme、restore 清空资源；主题定向与最终全量及已安装真实PTY颜色恢复均通过。**已关闭**。
- R2 回复与 R4 确认：原 R2 已明确按现有契约修复，无需修改公共接口。

### R4-006-T01 主题历史观察器包含外框

- 关联：T-004，`tests/test_theme_view.py::plot`，三类型参数。
- 原因：只限制左界，把c+width-1的muted外框当作primary历史柱，违反已定图区`[c+30,c+width-2)`。
- 修正：补排他右界，不改柱图/尺度/角色期待；123项定向及最终全量通过。已自行修正，向R2备案，无需变更验收含义。

### R4-006-T02 硬件边界测试仍观察旧行位/旧caption

- 关联：T-002，`tests/test_hardware_integration_edges.py`四项。
- 原因：温度仍查旧row5；巨大RAM仍要求已由新契约移除的百分比caption。
- 修正：温度查已定型号行row3并加右缘/角色；巨大RAM保留精确字节/原始100%检查，新增满条及TiB科学记数观察。67项定向及最终全量通过。已自行修正，向R2备案。

### R4-006-T03 运行期文字观察器人为插空格

- 关联：T-002，`tests/test_hardware_runtime.py::region_text`，两项联合运行期用例。
- 原因：以空格拼接TextCell使已拆分色角色的`34.2`/`%`变成`34.2 %`，容量也不再表示真实屏幕。
- 修正：按字符坐标重建屏幕文字；采集/失败隔离/清理断言均保留。67项定向及最终全量通过。已自行修正，向R2备案。

### R4-006-T04 日志联验仍要求旧RUNNING字符串

- 关联：T-003，`tests/test_integration.py::test_61_failed_samples_keep_updating_ui_while_real_log_records_only_0_and_60`。
- 原因：旧`RUNNING: 0`与新双统计块已定布局不符。
- 修正：检查固定统计槽内RUNNING/0及text角色，61次失败采样和0/60秒日志限频断言完整保留；8项定向及最终全量通过。已自行修正，向R2备案。

### R4-006-T05 PTY所谓空白探针落在新边框

- 关联：T-001/T-002，`tests/test_vllm_pty.py`。
- 原因：旧(7,118)已是Host横边框，窄字符`inch`把Unicode字形位混入属性导致伪色对；实际空白背景正确。
- 修正：改(0,20)真实ASCII空白，并新增字形为空格断言；完整RGB/背景/退出恢复保留。真实探针[脚本](evidence/r4-service-color-probe.py)与[报告](evidence/r4-service-color-probe/report.json)保留；8项定向及最终全量通过。已自行修正，向R2备案。

### R4-006-T06 硬件 PTY 缩放观察混用两个时刻

- 关联：T-006，`tests/test_hardware_pty.py`。本次返修全量触发，生产代码未因此更改。
- 原因与证据：[原始失败帧](evidence/r4-hardware-resize-race-original-report.json)中，Frame按120×45生成，render/refresh期间终端已变120×48，观察器用新物理尺寸给旧Frame标记；随后一帧正确恢复。resize等待还可能命中此前相同尺寸的历史帧。
- 修正：真实compose入口的只读wrapper记录每帧输入size，调用及返回不变；保留输入size、render前后与读屏后物理size。所有帧几何仍按真实输入size断言，不按预期几何筛选；只在尺寸一致时检查实际字形。每次resize仅等待本次新增且输入/物理尺寸均匹配的帧，保留最后120×44恢复断言。
- 验证：新增2项确定性用例覆盖render前/中resize，9项定向与1857项最终全量通过。已自行修正并向R2备案，不改变半页验收含义。

### R4-006-T07 新增混合相位回归的普通帧速率观察

- 关联：R5-006-002返修中R4新增的12组合测试，不涉及R5原用例。
- 原因：新增测试最初把resize即时帧与其后原网格普通帧的间隔也按普通30Hz限制检查，5.5μs相位的2项因此假阳性；例如0.7999975秒resize帧紧邻0.8秒普通tick，属于既定允许行为。
- 修正：仅从普通帧速率序列中排除由外部尺寸变化触发的那一帧，继续比较两侧普通帧；所有帧仍受最大进展间隔/内容/选择一致性约束，输入延迟与原始相位断言保留。未改生产相位，也未改R5任何断言。
- 证据：[新增测试初轮输出](evidence/r4-r5-fix2-timing-observer-first.txt)保留；修正后86项定向和1908项最终全量通过。已自行修正并在本交接向R2备案。

### R4-006-T08 发行版本测试的文件IO接缝更新

- R5-006-003原失败样本/期望没有错误；修复改为保留实际字段的reader后，真实文件位置接缝从platform私有候选/缓存转为cli候选常量。
- 仅适配文件位置，不替换解析结果或生产Runtime；3条R5原期望完整保留。原预制字典装配用例同步为真实文本/缺文件，并增加14项边界。45项CLI及1934项全量通过。记录供R2/R5审阅，不将此描述为原R5预期错误。

### R4-006-T09 半块PTY颜色观察的窄字符位混叠

- 新增硬件条取色观察最初用narrow inch读▌/▏，Unicode高位混入色对，导致伪黑色；与此前T05同类观察边界问题，不是产品颜色变化。[初轮输出](evidence/r4-segments-hostfix-bars-narrow-probe.txt)保留。
- 只在Ubuntu真实PTY测试用已有libncursesw.so.6的公开stdscr、mvwin_wch/getcchar读取宽字符及色对；opaque缓冲，不访问Python WINDOW私有结构，不安装系统包或新增产品依赖。发生resize时仍按既有稳定输入/物理尺寸边界观察。
- 正确宽字符观察验证实际▌/▏、颜色和背景；6个PTY场景以及296项定向/1934项全量通过，生产只改字形不改颜色。记录供R2/R5备案。

## 待决事项

### GUI-006-001 实际 GUI 终端观感与截图未完成

- **当前状态：CLOSED，用户确认。** R5已询问最新RAM/百分比精度版本，用户明确答复“已复验，整体显示符合预期”，见[R5交接](handoff-r5.md)与[确认记录](evidence/r5-user-gui-confirmation.json)。以下为历史阻碍及准备过程，不再要求重复确认，不推导新增截图、特定字体或GUI实测30FPS。

- 影响：T-006要求实际Ubuntu/WSL GUI终端、字体、双主题、三类型、缩放/恢复与退出的截图对照。代码/全量/PTY/安装已通过，不能因此将该项标为通过。
- 环境：本地有WSLg但无Linux GUI终端及截图工具；Windows Terminal已安装。用户已明确授权覆盖computer-use技能的终端自动化限制，仅操作本次离线WSL验证会话。
- 实际尝试：普通启动与显式可见启动能运行隔离安装CLI，但自动化窗口清单均不暴露目标；随后`cua.computer.launch_app(wt.exe)`明确返回 **`product policy blocks this app`**。用户授权不能解除工具产品策略；没有绕过该拒绝。两次任务自有WSL验证进程已按精确解释器/环境匹配发送SIGTERM，确认无残留，未关闭用户其他终端。
- 本地HTML预览也被浏览器工具协议策略拒绝（只允许HTTP/HTTPS）。没有启动本地服务器或绕过策略；使用独立离线Frame JSON→PNG栅格化检查补充静态可审阅材料，不冒充浏览器或终端截图。
- 历史已安装CLI的[离线GUI脚本](evidence/r4-install/installed-offline-gui.sh)保留三处留白/数字加粗/细轨道/页眉修复环境`/tmp/joi-req006-install-_0p99m6u`，脚本继承调用者TERM。本轮遵照用户要求不重建，故下述入口不包含统一半块/深灰轨道，不作为当前版本验证命令。若临时环境被系统清理，不使用失效路径，也不自行恢复构建流程。

```bash
bash /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/installed-offline-gui.sh
```

该脚本显式阻断DNS/connect/外部子进程，仅使用本地录制vLLM完整响应；实际配置采样1秒。额外五GPU/硬件同样本Frame对照与23场景PNG见`evidence/r4-visual/`；静态PNG所用Consolas不是实际GUI字体检测结果。

### 人工验证启动材料补充（2026-11-04）

用户请求自行完成剩余GUI验证。已复核保留安装环境存在，并提供[人工检查清单](manual-gui-checklist.md)：

- 正式CLI入口仍为上述`installed-offline-gui.sh`，用于真实应用的t/方向键/缩放/退出。该配置无硬件/磁盘/容器、静态累计指标差分后吞吐为0，不能独立完成全部视觉检查。
- 新增[完整Frame回放入口](evidence/r4-visual/manual-frame-gui.sh)及[脚本](evidence/r4-visual/manual_frame_gui.py)，用已安装CursesTerminal绘制23份既有Frame，n/p只用于回放场景选择，q退出，支持`--scene`和`--list`。固定逻辑画布不代表动态采集或正式应用导航；正常Frame未加入验证提示。
- 本地WSL真实PTY冒烟实际通过：小窗口、n/p、放大恢复、q、termios恢复、零DNS/connect/外部进程尝试，见[结果](evidence/r4-visual/manual-frame-pty-smoke.json)与[原始报告](evidence/r4-visual/manual-frame-pty-report.json)。这是新增证据脚本验证，不计入产品1835项，不代替人工GUI验收。
- 回放报告默认写`evidence/r4-visual/manual-frame-gui-report.json`，人工观感字段固定为`not recorded`，必须结合用户反馈与截图核实。当前result继续blocked，GUI-006-001尚未关闭。

## 下一步

接收角色为 **R5**：R4当前result=ready，请由用户发起源码/本地离线复核，重点核对两段同▌但轨道独立深灰、未关联GPU的muted填充保持、颜色资源边界/回滚/恢复、原比例/布局/其他颜色不变。前轮vLLM留白、数字字重和真实os-release回退继续保留，并确认003关闭结论。本轮用户不要求离线包，勿用旧安装包替代当前源码证据，也不自行重启构建流程。001/002保持关闭；GUI观感按用户安排另行反馈。本对话不自动创建或推进其他角色聊天。
