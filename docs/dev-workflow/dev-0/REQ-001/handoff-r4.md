# dev-0 / REQ-001 R4 交接

- stage：R4
- result：ready
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-001 / AC-101～AC-114 及共同规则。
- 计划依据：[plan.md](plan.md) v1.1；R2 交接 v1.5，R2-112-01～03。
- next_role：R5
- 修订：v1.4，2026-10-30；完成 v1.12 增量实现与本地验证，交 R5 验收。

v1.12 增量实现已完成：**Ubuntu 359 passed / 0 skipped；Windows 344 passed / 15 Unix PTY skipped**。原新契约基线的 43 个失败均消除，全部 327 项原用例保持逻辑和预期，另在已有测试文件中追加 32 项。当前 `ready` 表示可交 R5 审查，不表示 R5 已验收新需求。原 v1.9 公共基础和 R5-001/002 已由 [handoff-r5.md](handoff-r5.md) v1.3 验收通过，旧证据与结论保留为历史。

## v1.12 增量产物与处理结论

全部开发前检查完成后才开始实现，三个 subagents 分别负责配置/CLI 接合、布局、核心回归/离线集成；主对话负责集成、真实终端、安装、README 和交接。无需要退回 R2/R3 的接口或计划问题，全程未连接服务器。

| 任务 | 本轮结果 |
| --- | --- |
| T-001 / R2-112-01 | [config.py](../../../../src/joi_observer/config.py) 先检查整份 YAML，再只校验/保留原前三挂载点；所有容器完整校验、去重并按序保留。末轮复核补齐忽略挂载尾项中合法非字符串映射键的处理，尾项的重复键、标签、递归、非法标量仍拒绝，实际纳入字段仍要求字符串键。 |
| T-002～T-004 / R2-112-03 | 复用现有状态、日志、调度，生产代码未改；隐藏容器照常更新当前值、历史和实际失败日志。核心及联合定向两平台各 101 项通过。 |
| T-005 / R2-112-02 | [layout.py](../../../../src/joi_observer/tui/layout.py) 实现全页奇偶平分、8 区、独立 `service_switch`、Storage 总高 6 行/内容 3 行、Docker 剩余高度与可见前缀。零容量不画条目/空态，不补位、不提示溢出；绘制约束在各自区域，模型列表随服务区高度伸展。 |
| T-006 | `cli.py` 原有全量容器建槽与只读装配直接复用，无生产修改；新增真实 YAML 重启、非法配置在全屏前退出，以及小窗仍有十个容器状态槽的验证。 |
| T-007 | [test_integration.py](../../../../tests/test_integration.py) 增加真实 YAML→3 个挂载/10 个容器离线来源→Monitor/State/ErrorLog→ObserverApp 联合场景。每源 4 次采样、52 次状态提交，隐藏项有持续历史；高度 44→48→42→48 对应显示 4→6→3→6，不额外采样、不重建来源。隐藏第 6 容器失败与恢复、第 10 容器 Exited 均按原日志规则处理。 |
| T-008 | 更新 [源码 PTY](evidence/verify_pty.py) 和 [安装验证](evidence/verify_uv_install.py) 的旧尺寸预期，覆盖 0/5 GPU、35/36/37 边界、42/44/45/48 奇偶半页与可见条目；最终 wheel、非 editable 安装、新交互 shell 和异目录裸命令通过。README 已更新；依赖未变，`uv.lock` 未修改。 |

修改的生产文件只有 `config.py`、`tui/layout.py`；状态、调度、日志、CLI 和 `tui/app.py` 均保持本轮开始时的文件哈希，R5 两项修复完整保留。新增测试只加入 `test_cli.py`（5）、`test_config_boundaries.py`（19）、`test_tui.py`（7）、`test_integration.py`（1），没有新增测试文件或改动已有断言。

本轮仍不接入真实硬件/Docker/vLLM 采集器，不增加生产演示来源，也不宣称完成导航、GPU 联动、双主题或最终模型面板；对应 REQ-002～006 的后续集成边界不变。

## v1.12 验证证据

汇总与最终源码/测试/wheel 哈希见 [r4-v112-results.json](evidence/r4-v112-results.json)；修改前保护文件哈希及测试语法树见 [r4-v112-before.json](evidence/r4-v112-before.json)。旧 R2/R3/R5 交接、需求、设计、旧 JSON 和锁文件均未覆盖。

| 实际验证 | 结果 | 新证据 |
| --- | --- | --- |
| 配置/CLI，两平台 | 最终各 183 passed，含忽略尾项键的完整安全边界 | [初次接合](evidence/r4-v112-config-results.json)、[补齐尾项](evidence/r4-v112-config-tail-results.json) |
| 布局/外壳，Ubuntu | 60 passed；既有 53 项加 7 项边界回归 | [布局结果](evidence/r4-v112-layout-results.json) |
| 状态/调度/日志/联合，两平台 | 各 101 passed；生产核心未改 | [核心与集成](evidence/r4-v112-core-integration-results.json) |
| Windows 最终全量 | 344 passed、15 skipped、0 failed/errors，5.98 秒 | [文本](evidence/r4-v112-full-windows.txt)、[JUnit](evidence/r4-v112-full-windows.xml) |
| WSL uv 最终全量 | 359 passed、0 skipped/failed/errors，7.99 秒；全部 Unix PTY 输入用例实际执行 | [文本](evidence/r4-v112-full-ubuntu.txt)、[JUnit](evidence/r4-v112-full-ubuntu.xml) |
| 最终源码真实 PTY | 12 场景通过；含五个离线 GPU 来源、0/5 GPU 最小边界、奇偶半页、固定 Storage、Docker 可见前缀/零容量及缩放；termios/光标/原屏幕均恢复 | [源码 PTY 结果及实际帧区域](evidence/r4-v112-pty-results.json) |
| 最终离线 uv 工具安装 | 6 个缺配置/生命周期场景通过；安装包自身的 14 个几何检查通过。新 shell 初始无工具 PATH、无激活环境、异目录裸命令可用；代码/示例和 README 元数据匹配最终版本，临时安装已清理 | [安装结果](evidence/r4-v112-uv-install-results.json)、[输出](evidence/r4-v112-uv-install.txt) |
| 最终 wheel 重建 | uv 离线构建通过，所有 Python 文件/示例逐字节与最终源码一致 | [构建日志](evidence/r4-v112-wheel-build.txt)、[哈希汇总](evidence/r4-v112-results.json) |
| 静态与保留检查 | 语法检查、文档链接、`git diff --check` 通过；既有测试 AST/保护文件哈希不变，独立只读复核无遗留问题 | [汇总](evidence/r4-v112-results.json) |

环境沿用本地 Python 3.12.10 / PyYAML 6.0.1 / pytest 8.4.2（Windows）与 Python 3.12.3 / PyYAML 6.0.3 / pytest 8.4.2 / uv 0.13.6（Ubuntu-24.04 WSL），只使用已有离线 wheel。最终全量与系统复验命令：

```powershell
$env:PYTHONPATH = "$PWD\.pytest_cache\offline_deps"
$env:PYTHONPYCACHEPREFIX = "$PWD\.pytest_cache\r4-v112-pycache"
python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r4-v112-full-windows.xml
```

```bash
PYTHONPYCACHEPREFIX=/home/shawn/projects/tmp/joi-observer-v112-pycache \
UV_PROJECT_ENVIRONMENT=/home/shawn/projects/tmp/joi-observer-dev-0-venv \
  /home/shawn/.local/bin/uv --offline run --locked --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels \
  --extra test pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r4-v112-full-ubuntu.xml
python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py
python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --output docs/dev-workflow/dev-0/REQ-001/evidence/r4-v112-uv-install-results.json
/home/shawn/.local/bin/uv --offline build --wheel --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels
```

源码 PTY 在真实 `render` 调用处记录 Frame 区域与可见名称；五 GPU 场景只替换外部来源为离线 Collector，仍使用真实 Monitor/State/UI。安装验证的几何检查调用安装包的真实配置/布局函数，和裸命令的真实 PTY 生命周期证据分开记录，不把几何探针称作屏幕截图。窗口容量不会裁剪生产配置或来源集合。

日志实现及降级路径未变，按计划引用 [R5 实际权限验证](evidence/r5-permissions.json)，本轮不重复 chmod 场景。离线锁仍要求 `.pytest_cache/offline_wheels` 中的相同 wheel 包，已验证二进制平台范围仍为 CPython 3.12 / Linux x86_64 和 Windows amd64；没有连接目标服务器或验证其他平台。

本轮未产生需 R2 修改契约或 R3 改计划的问题。末轮发现的挂载尾项非字符串键误拒绝属于 R4 实现遗漏，已按原“合法 YAML 尾项忽略应用语义”的契约修复，并补重复键/非法标签/别名/构造错误回归；没有通过削弱测试绕过问题。

## v1.9 已完成返修（历史记录）

已依据 [handoff-r5.md](handoff-r5.md) v1.1 修复两项 P2 缺陷：R5-001 非法 YAML 构造异常未归一、R5-002 Esc 序列同步阻塞输入。最新全量结果为 **Ubuntu 269 passed / 0 skipped，Windows 254 passed / 15 skipped**；Windows 跳过的全部 Unix PTY 用例均已在 Ubuntu 执行通过。旧 R5 交接和历史证据原样保留；`ready` 表示本次返修可供 R5 复验，不代替 R5 关闭问题或作最终验收。

## R5 返修处理

### R5-001 非法 YAML 构造异常与 CLI 诊断

- R4 状态：**已修复，待 R5 复验**。开发前定向复现 R5 的 7 个失败；问题可在既有接口内处理，无需 R2/R3 变更。
- 修改 [config.py](../../../../src/joi_observer/config.py)：统一私有 YAML 构造异常集合，使用 `LookupError` 覆盖 `IndexError`/`KeyError`，补充 `AttributeError`。在具体标量 `construct_object` 调用处转换为 ConfigError，保留原字段及行列；外层文档构造使用同一集合，已定位的 ConfigError 原样传播。未通过修改 CLI 的内部错误处理掩盖配置问题。
- 保留 R5 的配置/CLI 测试逻辑与预期；在 [test_config_boundaries.py](../../../../tests/test_config_boundaries.py) 追加 5 项嵌套忽略尾项的非法标量定位测试，在 [test_cli.py](../../../../tests/test_cli.py) 追加 3 项真实 `python -m joi_observer` 子进程验证：退出码 2、无堆栈/原始值、无终端转义序列、未创建日志目录。
- Windows PyYAML 6.0.1、Ubuntu PyYAML 6.0.3 的配置/CLI 定向回归均为 **120 passed**。基线与分项结果见 [r4-fix-config-results.json](evidence/r4-fix-config-results.json)。

### R5-002 Esc 序列阻塞事件循环

- R4 状态：**已修复，待 R5 复验**。真实 WSL PTY 复现原 5 项中 2 失败，Esc/不完整序列导致约 1.011 秒阻塞；修复不改变 TerminalPort 公开接口。
- 修改 [tui/app.py](../../../../src/joi_observer/tui/app.py)：关闭 ncurses 的同步 keypad 序列判别，以非阻塞 `getch()` 读取字节，在私有有界状态中解析 terminfo、CSI 和 SS3 按键。前缀从首字节起最多保留 50ms，跨短轮询保持但不续期；每次调用遵守自身 deadline，等待及连续输入处理让出 asyncio 事件循环。未知或过期前缀不吞掉后续 q/t，保留 resize、Enter、Ctrl+C 和终端恢复。
- R5 原有 5 个 PTY 用例保持不变；在 [test_terminal_pty.py](../../../../tests/test_terminal_pty.py) 追加 10 项，覆盖四方向分片输入、3ms 调用预算、前缀到期不续期、未知/不完整 UTF-8 后的 q/t、取消等待和实际终端恢复。没有新增测试文件。
- 真实 PTY 15 项与既有 TUI/外壳回归合计 **50 passed**。该次定向实测中，50ms 轮询最长约 51.39ms（含调度抖动），事件循环心跳最大间隔约 10.46ms，不再出现原约 1 秒冻结；详见 [r4-fix-terminal-results.json](evidence/r4-fix-terminal-results.json)。

两项分工均在全部开发前检查确认可行后实施。另由独立 subagent 只读复核实现与测试，未发现遗留问题；主对话随后完成下述全量、真实终端与最终安装验证。所有新增测试位于已有相关文件，未改 R2/R5 的架构、公共契约或既有验收预期。

## 初次交付产物（历史）

| 任务 | 状态与实现 | 验证依据 |
| --- | --- | --- |
| T-001 配置 | 完成 `src/joi_observer/config.py`；优先级、完整 YAML 校验、字段定位、不可变配置与包内示例定位 | 原有 70 项及新增 18 项配置边界测试通过 |
| T-002 状态 | 完成 `src/joi_observer/data/state.py`；原子提交、未知/0/N/A/STALE、失败保值、有界历史及冻结快照 | 原有 State 测试及状态边界测试通过 |
| T-003 日志 | 完成 `src/joi_observer/error_log.py`；受控 JSONL、本地发生时间、限频/恢复轮次、守护写线程、有界队列、追加轮转及有界关闭 | 原有 22 项及新增 13 项日志边界测试通过；真实权限验证通过 |
| T-004 调度 | 完成 `src/joi_observer/monitor.py`；每对象独立固定周期、忙槽跳过、完成瞬间时间、超时与异常隔离、停止后无迟到提交 | State/Monitor 原有 30 项及新增 17 项边界测试通过 |
| T-005 外壳 | 完成 `src/joi_observer/tui/layout.py`、`app.py`；容量、只读绘制、稳定 GPU 槽、显示宽度截断、键位分派、真实 curses 及恢复 | TUI 黑盒/边界测试；真实 PTY 10 场景通过 |
| T-006 生命周期 | 完成 `src/joi_observer/cli.py`；参数/配置/TTY/日志顺序、唯一运行期、信号退出码、先恢复终端后共享 1 秒清理预算 | CLI/TUI 原有 45 项及新增 7 项边界测试通过 |
| T-007 联合验证 | 新增 `tests/test_integration.py` 4 项；实际配置、Monitor、State、ErrorLog、ObserverApp 与屏幕生成联合运行 | 61 次失败仍持续采样/刷新而仅记录 0/60 秒；恢复、新错误、队满、慢 IO、写失败及键位响应通过 |
| T-008 本地交付 | uv 真实生成 `uv.lock`、独立项目环境全量回归、离线构建和非 editable 工具安装通过；新 shell PATH/异目录裸命令、安装后真实 PTY、源码 PTY 和普通用户权限验证通过；README 更新 | 补验证据见 [uv-project-results.json](evidence/uv-project-results.json)、[uv-install-results.json](evidence/uv-install-results.json)；锁文件依赖本地 wheel 目录，平台范围见下文 |

新增测试文件：`tests/test_config_boundaries.py`、`test_state_monitor_edges.py`、`test_error_log_boundaries.py`、`test_shell_edges.py`、`test_integration.py`。原有六份黑盒测试未改验收预期，没有新增 skip/xfail。

交付代码仍遵循 `Collector → Monitor → MonitorState → TUI`；生产没有具体采集器或演示来源。默认外壳绘制真实配置对应的未知槽/空态，模型导航和主题端口等待 REQ-005/006 接入，不能将本轮解释为完整监控产品。

## 初次开发前检查（历史）

2026-10-28 已读取需求、计划、四份模块设计、公开接口和六份黑盒测试。全部任务确认可在既定契约内实现，没有需先交回 R2/R3 的架构、接口或计划冲突。保留工作区原有未提交文件；不连接任何服务器，不运行具体监控采集。

状态/调度实测基线：30 failed / 0 errors；日志实测基线：1 passed / 21 failed，均源于未实现骨架。配置采用 PyYAML；Windows 系统 Python 3.12.10 和 pytest 8.4.2 可用但缺 PyYAML；WSL Ubuntu 24.04 的 Python 3.12.3 已有 PyYAML 6.0.1。已将 WSL 自带纯 Python yaml 包复制到被 Git 忽略的 `.pytest_cache/offline_deps` 供 Windows 测试，未联网安装。

## 验证证据

### 本次 R5 返修验证（2026-10-29）

本次结果与最终源码/测试/wheel 哈希见 [r4-fix-results.json](evidence/r4-fix-results.json)，修复前文件哈希见 [r4-fix-before.json](evidence/r4-fix-before.json)。R5 整理后全量的 251 项全部保留，本次追加 18 项，共 269 项。原 9 个失败用例均已通过。

| 实际检查 | 结果 | 证据 |
| --- | --- | --- |
| Windows 全量 pytest，Python 3.12.10 / PyYAML 6.0.1 / pytest 8.4.2 | 254 passed、15 skipped、0 failed、0 errors，6.04 秒 | [文本](evidence/r4-fix-full-windows.txt)、[JUnit](evidence/r4-fix-full-windows.xml) |
| WSL uv 项目环境全量，Python 3.12.3 / PyYAML 6.0.3 / pytest 8.4.2 | 269 passed、0 skipped、0 failed、0 errors，8.52 秒；包含全部 15 项真实 PTY 输入测试 | [文本](evidence/r4-fix-full-ubuntu.txt)、[JUnit](evidence/r4-fix-full-ubuntu.xml) |
| 原有真实源码 PTY 生命周期脚本 | q、小窗、缩放、Ctrl+C、SIGINT/SIGTERM、部分 enter/render/read 失败及日志不可写，共 10 场景通过 | [r4-fix-pty-results.json](evidence/r4-fix-pty-results.json) |
| 最终源码 uv 离线非 editable 安装 | 新 shell / 异目录裸命令、安装示例、缺配置及 5 个全屏/信号场景通过；安装代码和示例与修复后源码逐字节一致，临时安装已清理 | [r4-fix-uv-install-results.json](evidence/r4-fix-uv-install-results.json)、[文本](evidence/r4-fix-uv-install.txt) |
| 最终 wheel 离线重建与逐文件校核 | uv 构建成功，wheel 中 `.py`/示例与最终源码一致；未把旧安装产物用作修复证据 | [构建日志](evidence/r4-fix-wheel-build.txt)、[哈希汇总](evidence/r4-fix-results.json) |
| 语法、差异、文档与保留文件检查 | `compileall`、`git diff --check`、本地文档链接通过；R5 交接、计划、R2/R3 交接、需求、README、依赖声明与锁文件未改 | [r4-fix-results.json](evidence/r4-fix-results.json) |

全量复现命令（项目根目录）：

```powershell
$env:PYTHONPATH = "$PWD\.pytest_cache\offline_deps"
$env:PYTHONPYCACHEPREFIX = "$PWD\.pytest_cache\r4-fix-windows-pycache"
python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r4-fix-full-windows.xml
```

```bash
PYTHONPYCACHEPREFIX=/home/shawn/projects/tmp/joi-observer-r4-fix-pycache \
UV_PROJECT_ENVIRONMENT=/home/shawn/projects/tmp/joi-observer-dev-0-venv \
  /home/shawn/.local/bin/uv --offline run --locked --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels \
  --extra test pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r4-fix-full-ubuntu.xml

python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py
python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --output docs/dev-workflow/dev-0/REQ-001/evidence/r4-fix-uv-install-results.json
/home/shawn/.local/bin/uv --offline build --wheel --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels
```

没有连接服务器。独立日志权限脚本本次未重复执行，日志业务未改；其既有真实文件权限证据以及 R5 复验结果仍为历史引用。Windows 跳过项为 Unix PTY 平台限制，不代表 Ubuntu 有未执行用例。具体采集器与完整导航/主题的后续需求边界不变。

### 初次交付验证（历史）

结构化结果和本轮源码 SHA-256 见 [validation-results.json](evidence/validation-results.json)。Windows、Ubuntu 系统测试环境及新增的 Ubuntu uv 项目环境分别执行同一组 **226 项**，均为 **226 passed、0 failed、0 errors、0 skipped**（原有 167 项＋新增 59 项）。没有连接服务器或执行真实硬件/Docker/vLLM 采集。

2026-10-29 按用户要求将 R4 的 4 个脚本与 7 份 JSON 结果集中到 `evidence/`。下表脚本命令已更新为整理后的复现路径；既有 JSON 原样保留，执行时间和构建哈希仍对应当时的验证版本，本次目录整理不代表重新执行完整验收。

工作目录为 `D:\Documents\joi-observer`；WSL 对应 `/mnt/d/Documents/joi-observer`。

| 实际命令/检查 | 结果与边界 |
| --- | --- |
| Windows：先 `$env:PYTHONPATH = "$PWD\.pytest_cache\offline_deps"`；`python -m pytest -q --tb=short --junitxml=.pytest_cache/r4-windows.xml` | 226 passed，4.04 秒；Python 3.12.10 / pytest 8.4.2 / 本地复制的 PyYAML 6.0.1 |
| WSL：`PYTHONPATH=/mnt/c/Users/Xinyi_Lu/AppData/Local/Programs/Python/Python312/Lib/site-packages python3 -m pytest -q --tb=short --junitxml=.pytest_cache/r4-ubuntu.xml` | 226 passed，2.91 秒；Ubuntu 24.04 / Python 3.12.3 / 系统 PyYAML 6.0.1 / 本地 pytest 8.4.2 |
| WSL：`uv --offline lock --python /usr/bin/python3 --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels` | uv 0.13.6 真实解析 8 包并生成 `uv.lock`；未手工编辑锁内容 |
| WSL：`UV_PROJECT_ENVIRONMENT=/home/shawn/projects/tmp/joi-observer-dev-0-venv uv --offline run --locked --python /usr/bin/python3 --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels --extra test pytest -q --tb=short --junitxml=.pytest_cache/r4-uv-ubuntu.xml` | 226 passed，2.97 秒；独立 uv 环境 / Python 3.12.3 / PyYAML 6.0.3 / pytest 8.4.2 |
| `python -m compileall -q src tests` | 通过 |
| `git diff --check` | 通过；Git 仅提示原有 requirements.md 的 LF/CRLF 工作区转换规则 |
| WSL：`python3 /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py` | 10 场景通过；见 [脚本](evidence/verify_pty.py)、[结果](evidence/pty-results.json) |
| WSL：`python3 /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-001/evidence/verify_permissions.py` | 2 场景通过；见 [脚本](evidence/verify_permissions.py)、[结果](evidence/permissions-results.json) |
| WSL：`uv --offline build --wheel --python /usr/bin/python3 --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels` | setuptools 84.0.0，离线构建 `dist/joi_observer-0.1.0.dev0-py3-none-any.whl`；20 个条目，源码/示例逐文件与最终版本字节一致，包含示例和 `joi-observer = joi_observer.cli:main` |
| WSL：`python3 docs/dev-workflow/dev-0/REQ-001/evidence/verify_uv_install.py --uv /home/shawn/.local/bin/uv` | 离线非 editable 安装、新 shell、异目录裸命令、安装示例、缺配置退出及安装后真实 PTY 通过；见 [脚本](evidence/verify_uv_install.py)、[结果](evidence/uv-install-results.json) |

本节 uv 命令实际通过 `/home/shawn/.local/bin/uv` 执行。wheel SHA-256 保存于结构化结果；构建产物和详细 JUnit XML 位于已忽略的 `dist/`、`.pytest_cache/`，可按上述命令重新生成。初版使用 bundled setuptools 的构建已由最终 uv 构建补验替代。

安装验收使用临时 HOME、UV_TOOL_DIR、UV_TOOL_BIN_DIR 与独立 cache，先在 PATH 不含工具 bin 时执行真实 `uv tool update-shell`，再启动新的交互 Bash，通过生成的 `.bashrc` 取得命令。新 shell 清除 VIRTUAL_ENV、PYTHONPATH 等环境，不手工加入工具 bin，工作目录不在源码中。验证 --version、--example-config 指向安装环境、缺配置退出 2、复制修改安装示例后全屏启动，以及 q/resize/Ctrl+C/SIGINT/SIGTERM 的退出码和终端恢复。没有更改真实用户 shell 配置或留下测试工具安装。

依赖通过 [restore_offline_wheels.py](evidence/restore_offline_wheels.py) 从两端 pip HTTP 缓存中的原始 wheel 恢复；读取 METADATA/WHEEL 还原标准文件名，不修改或重打包库内容，原文件哈希见 [offline-wheels-manifest.json](evidence/offline-wheels-manifest.json)。当前 `uv.lock` 是 uv 实际生成的离线锁，registry 引用 `.pytest_cache/offline_wheels`；该目录被 Git 忽略，换机时须复制相同 wheel 包或从已有缓存恢复。二进制 wheel 目前覆盖 CPython 3.12 / Linux x86_64 和 Windows amd64，不能据此声称锁文件支持其他 Python 版本/平台。源码元数据仍声明 Python >=3.12，未为这次环境验证收窄公共兼容性要求。

真实 PTY 使用 WSL uid 1000、xterm-256color 和 ncurses。覆盖 q、119×38 小窗退出、120×38 → 119×38 → 120×37 → 120×38 缩放、Ctrl+C、SIGINT、SIGTERM、部分 enter 失败、render/read 异常及启动日志不可写。每例验证完整 termios 与进入前一致、光标重新显示、alternate screen 退出；异常原文和堆栈不泄漏，固定内部错误提示发生在恢复后。日志不可写提示只出现一次且位于进入全屏之前。

真实权限验证使用 Linux 临时目录及普通用户 chmod：目录 `0500 → 0700`，文件 `0400 → 0600`；实际追加得到 PermissionError。恢复后下一错误立即记录，不补写丢失事件，采样/通知/键位继续，错误不进入帧或 stdout/stderr。该场景使用内存终端以核对状态和键位；真实终端恢复由独立 PTY 证据覆盖。慢写和队满是可释放 IO 边界注入，未将其表述为实际磁盘故障。

### 验收映射与界限

| 验收 | 本轮实际验证 | 未纳入通过结论 |
| --- | --- | --- |
| AC-101 | 命令全屏、主机/当前时间、未知值、STALE 固定槽 | 后续具体采集器和最终字段面板 |
| AC-102 | 默认/自定义采样、完成提交、持续刷新、61 次故障采样 | 真实部署采样 |
| AC-103 | 慢/失败来源隔离、超时、键位分派与 q 响应 | 完整导航、GPU 关联及主题效果 |
| AC-104 | q、Ctrl+C、SIGINT/SIGTERM、部分初始化与运行异常恢复；共用清理预算 | SIGKILL/断电及违反取消契约的后续适配器 |
| AC-105 | 配置重读、三类模型/顺序/前五容器、非法配置启动前定位 | 后续具体来源接入后的对象配置复验 |
| AC-106 | 容量公式、120×38 主场景、小窗、缩放恢复、稳定槽位 | 最终 REQ-006 外观验收 |
| AC-107～109 | 默认/自定义日志目录、仅 ERROR、限频、追加轮转、阈值与备份边界 | 真实来源错误归类需随适配器复验 |
| AC-110～112 | 静默、受控原因、权限降级/恢复、慢 IO、队满、0/60 秒和恢复新轮次 | 未验证目标服务器文件系统或服务权限 |
| AC-113 | 缺配置/非法配置退出、示例定位与复制后加载；uv 安装后示例资源定位及准备用户配置通过 | 目标服务器部署未验证 |
| AC-114 | uv 离线非 editable 安装、首次 PATH 配置、新交互 shell、异目录裸命令及全屏启停通过 | 仅本机 Ubuntu；依赖 wheel 目录与平台范围按上文准备 |

## 本轮决策

1. 保留既有 R2 架构和公开接口。三个 subagents 在全部开发前检查通过后才开始实现；同文件修改串行协调。
2. 避免配置挂载路径的合法长度被内部 ObjectKey 上限误限：没有具体 storage 采集器时，由 `compose_frame` 按配置直接绘制未知值槽。已补合法长路径/宽字符名称的生产组合根回归；后续 REQ-002 必须明确稳定挂载身份，不能把任意长路径直接当成最长 128 字符的 ObjectKey。
3. 配置独立审查发现并修复标准 YAML 标签非法标量漏转 ConfigError、反斜线/非法主机 URL 被接受的实现问题。新增定位/脱敏/忽略尾项回归；属于 R4 实现修复，没有变更配置契约。
4. 保持历史基线不变，新增测试独立存放；未覆盖或重置原有 AGENTS、需求及设计稿修改，没有创建提交或自动推进其他角色对话。

## R3 修订汇总

### R4-ENV-001 uv 环境漏检与离线依赖补验（已关闭）

- 关联：T-008 / AC-114，原计划要求真实 uv 生成锁文件并安装工具，在新 shell 和异目录验收裸命令。
- 更正：初版环境检查不充分，不能据非交互 PATH 中未找到 uv 推断 WSL 未安装。用户补充「WSL中uv应该安装了」后，实际确认绝对路径及版本 0.13.6。
- 处理：第一次 `uv --offline lock` 因 uv cache 没有 PyYAML 而失败；随后从已有 Windows/WSL pip 缓存恢复真实 wheel 包，未联网。uv 离线生成锁文件、项目全量测试、wheel 构建、工具安装和 AC-114 验证均通过。
- 状态：缺项关闭，不改变安装方式、公开接口或验收含义；本地 wheel 目录依赖和已验证平台明确记录。无需 R3 修改任务范围。

## R2 修订汇总

没有需要 R2 处理的接口变更、设计阻碍或测试自身错误。既有黑盒预期未修改。真实采集器/部署及 vLLM 指标核对仍引用 [R2 的范围与未验证事项](handoff-r2.md#范围与未验证事项)，不在本轮推断这些事实。

## 下一步

接收角色为 **R5**。请依据需求 v1.12、R2 v1.5、plan v1.1 与本交接 v1.4 验收本轮增量，重点核对前三挂载点/完整容器配置、全页奇偶平分与八区边界、Docker 可见数量与采集数量分离，以及最终安装产物。新证据统一为 `evidence/r4-v112-*`；原 `r4-fix-*` 与 R5-001/002 属于已验收历史，回归保护继续保留。请在 R5 交接中记录新需求的验收结论或反馈具体缺陷；真实采集器和完整监控产品仍不属于本轮已验证范围。

本轮没有创建或通知 R5 对话；跨对话推进由用户发起。
