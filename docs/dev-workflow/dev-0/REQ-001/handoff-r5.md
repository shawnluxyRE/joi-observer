# dev-0 / REQ-001 R5 验收交接

- stage：R5
- result：passed
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-001 / AC-101～AC-114 及共同规则；衔接 Storage、Docker 与半页布局的共享验收条件。
- 验收依据：[plan.md](plan.md) v1.1、[handoff-r4.md](handoff-r4.md) v1.4、R2 交接 v1.5，以及 configuration v1.1、monitor-state v1.5、error-logging v1.1、application-shell v1.2、公开接口注释和最新 AGENTS.md。
- 审查对象：HEAD `ebda572d2ac7eab378e79617247ab876622af5bc` 加全部未提交实现；本轮输入快照见 [r5-v112-before.json](evidence/r5-v112-before.json)，最终源码/测试/wheel 哈希及保留校验见 [r5-v112-results.json](evidence/r5-v112-results.json)。前轮 v1.9 的快照和复验结果保留为历史，不能代替本轮验证。
- next_role：R0
- 修订：v1.4，2026-10-30；独立验收需求 v1.12 增量，补充 5 项测试，配置/半页布局/隐藏对象回归与本地终端、安装验证通过。

**需求 v1.12 的 REQ-001 公共基础增量验收通过。** 本轮未发现新的验收缺陷，原 R5-001、R5-002 保持关闭。最终独立运行结果：Ubuntu **364 passed / 0 skipped**；Windows **349 passed / 15 Unix PTY skipped**，15 项终端专用用例均已在 Ubuntu 执行通过。范围仍以计划中的公共基础为限，不表示后续具体采集器、完整导航、双主题或最终模型面板已经验收。

## v1.12 本轮产物与验证证据

### 范围和结论

| 本轮验收范围 | 独立核对结果 |
| --- | --- |
| R2-112-01 / T-001、T-006：挂载点与容器配置 | 完整 YAML 安全检查后，仅原前三挂载项参与应用校验和有效配置；第四项起不补位。所有容器完整校验、去重并按序保留，后续项错误仍在进入全屏前定位退出；CLI 不按可见容量裁剪状态槽。 |
| R2-112-02 / T-005：半页及区域容量 | 全页直接平分，奇数多出一行归上半；服务窗口、独立切换位和键位合计占下半。8 区及逐区域裁切正确，Storage 固定 3 内容行/6 总行，Docker 使用右侧余高并仅显示配置前缀，无溢出提示或补位。 |
| 容量与稳定性 / AC-101、AC-106 | 0～4／5／6／10 GPU 最低高度为 36／37／43／67，最低宽度 120。Docker 总数不增加最小高度；零容量不画条目或空态。失败/恢复不改变区域或顺序；长名称、宽字符、模型列表及所有 GPU 槽保持在各自区域。 |
| R2-112-03 / T-002～T-004、T-007：隐藏不停止采集 | 真实加载的 3 个挂载和 10 个容器进入离线来源链路；13 源各 4 次采样、52 次状态提交。隐藏第 6 个容器失败/恢复仍更新历史及 ERROR，第 10 项 Exited 不记错误；窗口 44→48→42→48 行只改变可见 4→6→3→6 项，不增加采样、不改配置或重建状态。 |
| 原公共基础回归 | 状态、调度、日志、CLI、输入及清理行为保持通过。原 R5-001 的安全 YAML/CLI 诊断和 R5-002 的 Esc/方向键时限全部保留且通过。 |

### 补充测试与保留检查

本轮仅在两个已有测试文件补充 **5 项用例**，没有新增测试文件或角色词缀，没有修改业务实现、需求、设计及原有用例逻辑：

| 补充位置 | 数量 | 补漏内容 |
| --- | ---: | --- |
| [test_config_boundaries.py](../../../../tests/test_config_boundaries.py) | 3 | 合法非递归别名被忽略时不改变实际纳入值；忽略尾项的非字符串映射键通过别名进入 containers/logging 时仍按实际字段严格拒绝。 |
| [test_tui.py](../../../../tests/test_tui.py) | 2 | 6／10 GPU 在最低高度、低一行和相邻偶数高度时，容量判定与实际名称/指标/STALE 绘制一致，不静默隐藏 GPU，也不侵入下半区。 |

R2 的 327 项、R4 交付的 359 项均保留；本轮开始时的 **158 个测试函数 AST 全部保持**，新增 3 个参数化测试函数对应 5 项。完整输入快照覆盖 41 个源码、测试、配置、需求及设计文件；R5 仅改变上述两个测试文件，最终保留校验见 [结果汇总](evidence/r5-v112-results.json)。分项只读审查及补漏证据见 [配置](evidence/r5-v112-config-review.json)、[布局](evidence/r5-v112-layout-review.json)、[核心与集成](evidence/r5-v112-integration-review.json)。

### 本轮实际执行

工作目录为 `D:\Documents\joi-observer`，WSL 对应 `/mnt/d/Documents/joi-observer`，发行版 `Ubuntu-24.04`、普通用户 uid 1000。所有验证只使用本地离线来源/依赖，没有连接任何服务器。

| 实际检查 | 结果 | 新证据 |
| --- | --- | --- |
| 补漏前 Windows 全量 | 344 passed / 15 skipped，6.76 秒，确认 R4 交付基线 | [文本](evidence/r5-v112-baseline-windows.txt)、[JUnit](evidence/r5-v112-baseline-windows.xml) |
| 最终 Windows 全量 | 349 passed / 15 skipped，7.73 秒，0 failed / errors；Python 3.12.10、PyYAML 6.0.1、pytest 8.4.2 | [文本](evidence/r5-v112-full-windows.txt)、[JUnit](evidence/r5-v112-full-windows.xml) |
| 最终 WSL uv 项目全量 | 364 passed / 0 skipped，12.88 秒，0 failed / errors；Python 3.12.3、PyYAML 6.0.3、pytest 8.4.2、uv 0.13.6 | [文本](evidence/r5-v112-full-ubuntu.txt)、[JUnit](evidence/r5-v112-full-ubuntu.xml) |
| 真实源码 PTY，独立重跑更新后的脚本 | 12 场景通过，含 0／5 GPU、35／36／37 边界、42／44／45／48 页高、Docker 零容量/可见前缀、固定 Storage、q/信号/异常与终端恢复 | [PTY 实际区域记录](evidence/r5-v112-pty-results.json) |
| 离线 uv 工具安装，独立重跑更新后的脚本 | 6 个缺配置/生命周期场景和 14 个安装包几何检查通过；首次 PATH 配置、新交互 shell、异目录裸命令、安装示例、代码及 README 元数据均验证通过；临时安装已清理 | [安装结果](evidence/r5-v112-uv-install-results.json)、[输出](evidence/r5-v112-uv-install.txt) |
| 当前 wheel 独立逐文件核对 | 14 个 Python 文件和示例与本轮源码字节一致；README 元数据相符，SHA-256 与 R4 最终 wheel 一致 | [结果汇总](evidence/r5-v112-results.json) |
| 差异及引用核对 | 原测试 AST 保留；业务、设计与锁文件未被 R5 修改；`git diff --check` 通过，仅既有 LF/CRLF 提示 | [输入快照](evidence/r5-v112-before.json)、[结果汇总](evidence/r5-v112-results.json) |

全量 pytest 命令主体如下；实际由临时目录包装执行，`<temp>` 为该次新建的 `TemporaryDirectory`，结束后自动删除，未另外留下专用 pycache。使用 `PYTHONDONTWRITEBYTECODE=1`，并将 `PYTHONPYCACHEPREFIX` 指向同一临时目录，避免跨 Windows/WSL 复用旧字节码。pytest 缓存插件已关闭；日志与 JUnit 只写入本需求 `evidence/`。

```powershell
# Windows：PYTHONPATH 指向已有 .pytest_cache/offline_deps。
python -B -m pytest -p no:cacheprovider --basetemp <temp>/pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r5-v112-full-windows.xml
```

```bash
# WSL：UV_PROJECT_ENVIRONMENT=/home/shawn/projects/tmp/joi-observer-dev-0-venv。
/home/shawn/.local/bin/uv --offline run --locked --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels \
  --extra test pytest -p no:cacheprovider --basetemp <temp>/pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r5-v112-full-ubuntu.xml
PYTHONDONTWRITEBYTECODE=1 python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py
PYTHONDONTWRITEBYTECODE=1 python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --output docs/dev-workflow/dev-0/REQ-001/evidence/r5-v112-uv-install-results.json
```

本轮确实重跑了源码 PTY 与安装脚本，没有把 R4 的通过报告当作 R5 实测。最终 wheel 的离线构建由 R4 执行，R5 实际检查其哈希及包内容；安装脚本则另行从当前源码完成非 editable 构建/安装。区域探针是 Frame 数据核对，不称作屏幕截图。日志实现及降级路径未变，独立 chmod 场景按计划引用以前实际执行的 [r5-permissions.json](evidence/r5-permissions.json)，没有重复运行或改写旧结果。

### 本轮决策与剩余边界

- `result=passed`、`next_role=R0`。本轮没有新的 R4 修订请求，R5-001、R5-002 保持关闭。
- 当前验收覆盖计划定义的公共配置、半页布局、完整容器集合与隐藏显示分离、运行期及离线安装。AC-207/301/304/605/607/608 仅核对这些共享规则，不宣称相关后续需求整体完成。
- 真实硬件/Docker/vLLM 采集器、完整导航/GPU 联动、双主题和最终模型指标面板仍按 REQ-002～006 接入后验收；未验证目标服务器部署。
- 离线安装仍依赖被 Git 忽略的 `.pytest_cache/offline_wheels`，保留既有 CPython 3.12 / Linux x86_64 与 Windows amd64 的平台限制。

## v1.9 产物（历史）

| 补充位置 | 用例数 | 验收补漏 |
| --- | ---: | --- |
| [test_config_boundaries.py](../../../../tests/test_config_boundaries.py) | 6 | 非法标准 YAML 标量、容器忽略尾项的完整 YAML 校验；原 6 项失败现已通过 |
| [test_cli.py](../../../../tests/test_cli.py) | 1 | CLI 安全定位和退出码；原 1 项失败现已通过 |
| [test_state_monitor_edges.py](../../../../tests/test_state_monitor_edges.py) | 4 | 真实 run 循环中超时恢复、快源继续、合作取消、关闭隔离、多对象历史裁剪；全部通过 |
| [test_error_log_boundaries.py](../../../../tests/test_error_log_boundaries.py) | 9 | 六类受控原因、归一后限频、恢复隔离、真实目录阻断后静默重建和不补写；全部通过 |
| [test_terminal_pty.py](../../../../tests/test_terminal_pty.py)（初次验收新增文件） | 5 | 实际 ncurses 的 q/up/left、Esc 和不完整转义序列；原 2 项失败现已通过 |

上表为 R5 初次补充的 25 项。本次返修中 R4 在已有文件内再补充 18 项（配置 5、真实 CLI 3、PTY 10），全量合计 269 项；R5 已审查这些用例和实现，本次未再添加重复用例，没有修改业务代码、测试预期或设计契约。

测试以外只维护本交接及 `evidence/` 验证资料。初次验收的结构化结果和当时的文件哈希见 [r5-validation-results.json](evidence/r5-validation-results.json)；该历史报告中的 38 个文件不变结论对应整理前版本。整理后的文件、迁移映射、语法树校核和实际回归结果见 [test-reorganization-results.json](evidence/test-reorganization-results.json)。没有创建提交、修改旧角色交接结论或覆盖历史证据。

### v1.1 测试整理

遵循更新后的技能：“优先在相关的已有测试文件中添加，必要时再新建。新文件不添加角色词缀。”配置、CLI、状态/调度和日志用例已并入上表四个已有文件；真实终端输入测试依赖 Unix PTY，保留独立文件 `test_terminal_pty.py`。旧的四个 `test_r5_*.py` 文件已移除，状态测试函数名也去掉了 `r5_`。

为避免覆盖已有辅助对象，只对移入代码作语义命名调整：状态测试的 `Source` 改为 `CooperativeSource`；日志测试的 `NOW`、`emit` 改为 `FAILURE_TIME`、`emit_failure`。业务输入、参数化、断言、超时和跳过条件保持不变。

旧证据保留执行时的文件名、用例名和哈希，不改写历史；其当前对应位置以上表及整理结果 JSON 为准。整理前快照为 [test-reorganization-before.json](evidence/test-reorganization-before.json)。

## v1.9 验证证据（历史）

### 再次代码审查与残留盘点（v1.3）

按用户要求再次只读审查配置、CLI、终端、状态/调度、日志及对应测试，未发现新的确认缺陷或错误测试预期。测试替身用于外部采集、时钟、IO 故障等边界，实际业务链路和真实 PTY 均由原用例运行；任务、日志线程、子进程和终端句柄有关闭/回收路径。

当前源码和测试 SHA-256 与上次通过的复验版本完全一致，因此本次引用 v1.2 的 Ubuntu 269 passed、Windows 254 passed / 15 平台跳过结果，没有重复运行全量。详见 [代码、测试与清理复查](evidence/code-test-cleanup-review.json)。

盘点确认 24 处可再生缓存、构建中间文件和本项目 pytest 临时目录，共 56,802,181 字节（约 54.17 MiB），另有一个指向已盘点 pytest 目录的 `pytest-current` 符号链接。详细路径、大小及边界检查见 [Windows 清单](evidence/cleanup-candidates-windows.json)、[WSL 清单](evidence/cleanup-candidates-wsl.json)。未发现本项目临时 uv 安装或 PTY 脚本目录残留，也未发现仍在运行的本项目测试进程。

保留离线依赖源码、`uv.lock` 依赖的 wheel 目录、有效 WSL uv 测试环境、最终 wheel、Git/源码/测试和全部历史验收证据。`.pytest_cache` 同时存有必要离线依赖及历史结果，不能整目录删除。

**清理未执行**：自动审批拦截了批量删除命令，仅返回 `blocked by policy`，没有提供更具体原因；没有通过其他方式重试删除。此限制不影响已经通过的产品验收，待用户明确后续清理请求。

### R4 返修后的 R5 独立复验（v1.2）

本次审查确认实际改动为 `config.py`、`tui/app.py`、3 个测试文件和 R4 交接；其他业务文件、需求和设计未变。对原测试及辅助对象作 AST 核对，既有逻辑、原 R5 新增用例的断言和参数化均保留；此前 251 项用例全部仍在，新增加 18 项。完整文件哈希与逐项验证见 [r5-recheck-results.json](evidence/r5-recheck-results.json)。

| 本次实际执行 | 结果 | 新证据 |
| --- | --- | --- |
| Windows 全量，Python 3.12.10 / PyYAML 6.0.1 / pytest 8.4.2 | 254 passed / 15 skipped，6.29 秒；0 failed / 0 errors | [文本](evidence/r5-recheck-windows.txt)、[JUnit](evidence/r5-recheck-windows.xml) |
| WSL Ubuntu-24.04 uv 项目全量，Python 3.12.3 / PyYAML 6.0.3 / pytest 8.4.2 | 269 passed / 0 skipped，8.11 秒；包含 15 项真实 PTY 输入用例 | [文本](evidence/r5-recheck-ubuntu.txt)、[JUnit](evidence/r5-recheck-ubuntu.xml) |
| 真实终端生命周期脚本重新执行 | q、小窗、缩放、Ctrl+C、SIGINT/SIGTERM、部分 enter/render/read 失败、启动日志不可写，共 10 场景通过；termios、光标和原屏幕恢复 | [r5-recheck-lifecycle.json](evidence/r5-recheck-lifecycle.json) |
| 原失败用例逐项核对 | Ubuntu 的原 9 项失败、Windows 的原 7 项失败全部通过；没有删除、跳过或改低预期 | [复验结果](evidence/r5-recheck-results.json) |
| 当前 wheel 逐文件核对 | 14 个 Python 文件及 1 份 YAML 示例与当前源码字节一致；命令入口存在，wheel SHA-256 与 R4 最终构建报告相符 | [复验结果](evidence/r5-recheck-results.json) |
| 源码、测试及差异检查 | 复验对象与 R4 v1.3 哈希记录一致；原测试逻辑保留；`git diff --check` 通过（仅既有行尾提示） | [复验结果](evidence/r5-recheck-results.json) |

Windows 的 15 项跳过全部是 Unix PTY 平台条件，Ubuntu 已执行这 15 项且无跳过。本次没有新建角色命名测试文件，也没有连接任何服务器。

实际命令（项目根目录）：

```powershell
$env:PYTHONPATH = "$PWD\.pytest_cache\offline_deps"
$env:PYTHONPYCACHEPREFIX = "$PWD\.pytest_cache\r5-recheck-windows-pycache"
python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r5-recheck-windows.xml
```

```bash
PYTHONPYCACHEPREFIX=/home/shawn/projects/tmp/joi-observer-r5-recheck-pycache \
UV_PROJECT_ENVIRONMENT=/home/shawn/projects/tmp/joi-observer-dev-0-venv \
  /home/shawn/.local/bin/uv --offline run --locked --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels \
  --extra test pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r5-recheck-ubuntu.xml
python3 -B docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py
```

本次未重复安装工具或运行独立 chmod 权限脚本：安装结果引用 R4 修复后的 [uv 安装证据](evidence/r4-fix-uv-install-results.json)，并由 R5 实际核对当前 wheel 的全部代码/示例与修复后源码一致；日志代码未改，权限行为引用此前 R5 实际执行的 [权限证据](evidence/r5-permissions.json)。这些引用与上表本次实测明确区分。

### 初次验收与测试整理（历史）

工作目录：Windows `D:\Documents\joi-observer`；WSL `/mnt/d/Documents/joi-observer`。实际发行版为 `Ubuntu-24.04`，普通用户 uid 1000；初次尝试名称 `Ubuntu` 只返回发行版不存在，随后确认正确名称继续验证，不是环境阻碍。全程没有连接任何服务器，依赖仅使用已有缓存及离线 wheel。

| 检查 | 实际结果 | 本轮证据 |
| --- | --- | --- |
| 修改测试前 Windows 全量 | 226 passed，4.77 秒 | [文本](evidence/r5-baseline-windows.txt)、[JUnit](evidence/r5-baseline-windows.xml) |
| 整理前 Windows 全量 | 239 passed / 7 failed / 5 skipped，4.91 秒；Python 3.12.10、pytest 8.4.2、离线 PyYAML 6.0.1 | [文本](evidence/r5-final-windows.txt)、[JUnit](evidence/r5-final-windows.xml) |
| 整理前 WSL uv 项目全量 | 242 passed / 9 failed / 0 skipped，6.95 秒；Python 3.12.3、pytest 8.4.2、PyYAML 6.0.3、uv 0.13.6 | [文本](evidence/r5-final-ubuntu.txt)、[JUnit](evidence/r5-final-ubuntu.xml) |
| 整理后 Windows 全量 | 239 passed / 7 failed / 5 skipped；用例数和失败行为不变 | [文本](evidence/test-reorganization-windows.txt)、[JUnit](evidence/test-reorganization-windows.xml) |
| 整理后 WSL uv 项目全量 | 242 passed / 9 failed / 0 skipped；用例数和失败行为不变 | [文本](evidence/test-reorganization-ubuntu.txt)、[JUnit](evidence/test-reorganization-ubuntu.xml) |
| 真实源码 PTY，重新执行 R4 脚本 | 10 场景通过：q、小窗、缩放、Ctrl+C、SIGINT、SIGTERM、部分初始化失败、绘制失败、读键失败、日志不可写 | [r5-existing-pty.json](evidence/r5-existing-pty.json) |
| 本地 Linux 真实权限，重新执行 R4 脚本 | 启动目录 0500→0700、运行文件 0400→0600 两场景通过；采样、按键、静默和恢复正常 | [r5-permissions.json](evidence/r5-permissions.json) |
| uv 离线工具安装，重新执行 R4 脚本 | 非 editable 安装、首次 PATH 配置、新交互 shell、异目录裸命令、安装示例、缺配置退出及安装后 PTY 通过 | [r5-config-uv-install.json](evidence/r5-config-uv-install.json) |
| 编译及差异检查 | `python -m compileall -q src tests`、`git diff --check` 通过；仅有既有 requirements.md 行尾转换提示 | [文件不变和结果汇总](evidence/r5-validation-results.json) |

Windows 的 5 个跳过仅是本次新增 Unix PTY 用例的平台条件；同一组用例已在 Ubuntu 全部执行，没有跳过或削弱任何原有测试。两个平台最终回归均包含原有 226 项，全部通过。状态/日志分项结果另见 [state/monitor](evidence/r5-state-monitor-review.json)、[error log](evidence/r5-log-review.json)，配置分项和实际 CLI 子进程见 [configuration](evidence/r5-config-review.json)、[CLI 错误证据](evidence/r5-config-cli-malformed.json)。

初次验收整理后的历史复现命令：

```powershell
# Windows PowerShell，项目根目录；离线依赖目录为既有 R4 准备内容。
$env:PYTHONPATH = "$PWD\.pytest_cache\offline_deps"
$env:PYTHONPYCACHEPREFIX = "$PWD\.pytest_cache\reorganization-windows-pycache"
python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/test-reorganization-windows.xml
```

```bash
# 本地 WSL Ubuntu-24.04，项目根目录。
PYTHONPYCACHEPREFIX=/home/shawn/projects/tmp/joi-observer-reorganization-pycache \
UV_PROJECT_ENVIRONMENT=/home/shawn/projects/tmp/joi-observer-dev-0-venv \
  /home/shawn/.local/bin/uv --offline run --locked --python /usr/bin/python3 \
  --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels \
  --extra test pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/test-reorganization-ubuntu.xml

python3 docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py
python3 docs/dev-workflow/dev-0/REQ-001/evidence/verify_permissions.py \
  --output docs/dev-workflow/dev-0/REQ-001/evidence/r5-permissions.json
python3 docs/dev-workflow/dev-0/REQ-001/evidence/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --output docs/dev-workflow/dev-0/REQ-001/evidence/r5-config-uv-install.json
```

本轮复用了 R4 的 PTY、权限和安装脚本，但确实重新执行并保存了新的 R5 结果；没有把旧报告当作本轮实测。旧 wheel 构建哈希和缓存恢复来源仍属于引用的 R4 证据，本轮安装脚本重新构建并安装源码。安装/权限脚本中的 IO 故障使用真实本地文件权限；权限场景的 UI 仍是内存终端，终端恢复由另行执行的真实 PTY 证据支持。

### 用例自身校核

初次并行全量结果保留于 [Windows](evidence/r5-full-windows.txt) 和 [Ubuntu](evidence/r5-full-ubuntu.txt)。Windows 曾在新增状态测试中出现一次 `fast.calls == 1`：慢源超时提交时，不能假定快源第二次提交也已完成。已将**本次新增用例**改为恢复慢源前有界等待快源第二次成功提交，再断言其值及非 STALE，保留原验收要求。校正记录在 [分项报告](evidence/r5-state-monitor-review.json)，最终两平台均通过此项，不将测试时序竞争报成产品缺陷。

Esc 用例也经独立复核：公开契约允许忽略未知键，用例不要求 Esc 必须返回某个字符，而是在有界观察内核对每次读取耗时及事件循环心跳。q/up/left 仍校验正确键值。两个 Esc 场景在初次验收时失败，早期证据保留于 [r5-terminal-pty.txt](evidence/r5-terminal-pty.txt) 和 `r5-final-ubuntu.*`；本次修复后已通过，当前结论以上述 v1.2 复验为准。

### 验收映射与边界

| 验收 | R5 核对结果 |
| --- | --- |
| AC-101 | 公共标题、主机/当前时间、未知值、首次失败固定 STALE 槽通过；具体来源和最终面板仍留后续需求 |
| AC-102～103 | 独立采样、超时隔离、恢复及展示键位端口通过；真实终端输入、分片方向键、短轮询和取消复验通过，R5-002 已关闭 |
| AC-104 | q、可捕获信号、部分初始化/运行异常的真实终端恢复通过；SIGKILL/断电不在保证范围 |
| AC-105 | 常规有效/非法配置、顺序、重读和容器前五项通过；非法 YAML 构造异常的定位、脱敏与退出码复验通过，R5-001 已关闭 |
| AC-106 | 容量公式、小窗、缩放恢复、稳定区域和 Docker 行数通过；最终主题视觉属于 REQ-006 |
| AC-107～112 | 目录、ERROR 内容与脱敏、轮转、限频、恢复、队列、慢 IO 隔离及真实权限降级通过；真实采集器分类后续复验 |
| AC-113～114 | 示例资源、缺配置、修改示例后加载、uv 安装及新 shell 裸命令通过；换机依赖准备限制保留 |

## v1.9 验收决策（历史）

1. 当前结论为 `passed`，R5-001、R5-002 均经独立源码审查和实际复验关闭，没有发现新的验收阻碍。初次 `needs_fix` 的失败证据继续保留，不能将历史失败当作当前状态。
2. 范围沿用计划：本轮没有具体硬件、Docker、vLLM 采集器，也没有完整模型导航/GPU 联动/双主题，不据此另报实现遗漏；真实部署、完整 UI 和后续适配器仍须各需求集成验收。
3. 离线锁引用被 Git 忽略的 `.pytest_cache/offline_wheels`；README 和 R4 已披露换机需准备相同依赖及目前 CPython 3.12 平台覆盖。该已披露限制本轮不另列新缺陷，不推断其他 Python 版本已经验证。
4. 本次仅更新交接和新增复验证据，没有修改业务代码、契约或现有用例；原失败测试已全部通过。没有通知或启动其他角色对话。

## R4 修订汇总

### R5-001 [P2] 非法标准 YAML 标量绕过 ConfigError，CLI 泄漏堆栈

- 状态：**已关闭，2026-10-29 R5 复验通过**。
- 关联：REQ-001 / AC-105，T-001、T-006；[configuration.md](../../../design/configuration.md) 的完整 YAML 校验、可定位安全 ConfigError，以及 [application-shell.md](../../../design/application-shell.md) 的配置错误退出码 2。
- 修复前位置：[config.py](../../../../src/joi_observer/config.py) 第 350～351 行调用标量构造器和异常归一边界，外层第 246 行；[cli.py](../../../../src/joi_observer/cli.py) 第 312～315 行配置加载边界。
- 预期：非法标量在进入 TUI、组装采集器或创建日志前，转成带路径/字段/行列的 ConfigError；CLI 输出安全配置诊断并返回 2，不显示堆栈或原始值。即使该标量位于第六个容器，仍遵循全文件 YAML 合法性检查。
- 修复前实际：`sample_interval: !!int ""`、`sample_interval: !!float ""` 抛 `IndexError`；`sample_interval: !!timestamp PRIVATE` 抛 `AttributeError`。这些异常不在原捕获集合内。真实 `python -m joi_observer --config <临时配置>` 返回 1，stderr 包含 Python traceback，没有约定的字段定位诊断。第六个容器位置同样复现。
- 影响：用户提供非法配置时启动错误行为不符合契约，诊断无法正确指向配置位置；本问题发生在进入全屏前，未观察到采集启动或错误日志创建。
- 修复前复现：`python -m pytest tests/test_config_boundaries.py tests/test_cli.py -k 'standard_scalar_constructor_failures or malformed_timestamp_cli' -q --tb=short`，当时 7 项失败；Windows PyYAML 6.0.1 和 Ubuntu PyYAML 6.0.3 均复现。原始证据见 [真实 CLI](evidence/r5-config-cli-malformed.json)、[Windows 分项](evidence/r5-config-windows.txt)、[Ubuntu 分项](evidence/r5-config-ubuntu.txt)；整理后、修复前的失败证据见历史全量结果。
- 处理请求：在 YAML 输入边界将这些构造异常归一为安全、可定位的 ConfigError；保留尾项全文件检查及脱敏，不仅用 CLI 的笼统内部错误提示掩盖问题。保留并通过新增 7 项用例及原有配置/CLI 回归。
- R4 回复：v1.3 在 `config.py` 统一 `_YAML_VALUE_ERRORS`，用 `LookupError` 覆盖 `IndexError`/`KeyError` 并补充 `AttributeError`；在原标量节点转换为安全 ConfigError，外层透传已定位错误，没有修改 CLI 掩盖异常。
- R5 复验：源码审查及两个平台全量通过；原 7 个失败用例全部通过，追加的 5 个嵌套尾项和 3 个真实 CLI 子进程用例也通过。实际确认退出 2、路径/字段/行列定位、无堆栈/原始值、未进入终端或创建日志；本问题关闭。证据见 `r5-recheck-windows.*`、`r5-recheck-ubuntu.*` 和 [汇总](evidence/r5-recheck-results.json)。

### R5-002 [P2] Esc 序列等待同步阻塞 curses 输入与 asyncio 事件循环

- 状态：**已关闭，2026-10-29 R5 复验通过**。
- 关联：REQ-001 / AC-102～103，T-005；[application-shell.md](../../../design/application-shell.md) 要求键盘等待上限 50ms，`TerminalPort.read_key(timeout)` 明确不得阻塞事件循环或采样任务。
- 修复前位置：[tui/app.py](../../../../src/joi_observer/tui/app.py) 第 106～107 行 `keypad(True)` / `nodelay(True)`，第 184～188 行在事件循环中同步调用 `get_wch()`。
- 预期：输入 Esc 或不完整转义序列时，按约定轮询上限返回/继续等待，事件循环和采样仍可运行；q 与方向键保持正确解析。未知 Esc 可被忽略，不要求暴露特定字符。
- 修复前实际：真实 WSL PTY、`TERM=xterm-256color`、固定测试环境 `ESCDELAY=1000` 下，写入 `b'\x1b'` 或 `b'\x1b['` 后，`read_key(0.05)` 分别耗时约 1.0112 / 1.0116 秒，同期 10ms 心跳也暂停约 1.011 秒。`nodelay` 没有消除已收到 Esc 后的序列判别等待，函数内 deadline 只能在同步调用返回后检查。
- 影响：未知按键或不完整终端输入能冻结 UI 刷新和同一个事件循环上的所有采样约 1 秒；连续发生时破坏采样节奏。正常 q/up/left 三场景通过，因此问题不是没有成功进入终端。
- 修复前复现：在本地 WSL 运行 `python -m pytest tests/test_terminal_pty.py -q --tb=short`；当时 2 failed / 3 passed。环境值在测试中显式固定，不声称已测得所有终端的默认 Esc 等待值。用例容许 0.20 秒调度抖动，仍远低于当时实测阻塞。见 [整理后 Ubuntu 历史全量](evidence/test-reorganization-ubuntu.txt) 与 [JUnit](evidence/test-reorganization-ubuntu.xml)。
- 处理请求：使真实 curses 的序列解析等待也受输入预算约束，不得仅在 `get_wch()` 返回后检查超时；保持方向键解析和终端恢复。保留 5 个 PTY 用例，通过 50ms 契约的实现验证及原有 PTY/集成回归。
- R4 回复：v1.3 关闭同步 keypad 判别，改为非阻塞 `getch()` 与有界异步前缀解析；单次调用受自身 deadline 限制，前缀从首字节起 50ms 到期，不因后续片段或跨调用而续期；保留方向键、q/t、Enter、Ctrl+C、resize 和恢复。
- R5 复验：独立源码审查无遗留问题；原 5 个实际 PTY 用例及 R4 新增 10 项全部通过。短轮询、分片方向键、前缀到期、UTF-8/未知输入后的 q/t、取消等待与恢复均通过；原 10 场景终端生命周期脚本也重新执行通过。原两个失败场景不再出现约 1 秒阻塞，本问题关闭。证据见 [Ubuntu 全量](evidence/r5-recheck-ubuntu.xml)、[生命周期](evidence/r5-recheck-lifecycle.json)。

## 下一步

接收角色为 **R0／用户**。需求 v1.12 的 REQ-001 公共基础增量验收通过，本轮无新增缺陷，原两项修订保持关闭，可据此协调后续需求。REQ-002～REQ-006 接入具体采集器、完整导航/GPU 联动及主题时，继续复验相应集成行为；本结论不代表目标服务器或完整监控产品已经验收。

跨对话推进由用户发起。本轮没有向其他聊天发送消息。
