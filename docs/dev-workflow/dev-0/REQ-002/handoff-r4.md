# dev-0 / REQ-002 R4 交接

- stage：R4
- result：ready
- work_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0\REQ-002`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-002 / AC-201～AC-207 及共同规则。
- 计划依据：[plan.md](plan.md) v1.0；R2 [handoff-r2.md](handoff-r2.md) v1.0。
- next_role：R5
- 修订：v1.2，2026-10-30，续修 R5 v1.2 的安装验证工具 A/B 问题；当前工作树保留用户 AGENTS.md 和全部 R2/R3/R5 未提交产物，不修改原工作区。

## 本轮返修状态

接收 [R5 交接](handoff-r5.md) v1.2。**R5-002-001、R5-002-002 已被 R5 独立复验关闭，本轮 R5-002-003-A/B 的安装验证工具修订也已完成，`result=ready`，交 R5 复验。** 产品代码、永久测试、README、依赖和旧脚本等 53 个保护输入全部保持，交付 wheel 原样复用；输入/最终哈希见 [r4-fix2-before.json](evidence/r4-fix2-before.json) 与 [r4-fix2-validation.json](evidence/r4-fix2-validation.json)。下方 v1.0/v1.1 内容均为历史记录，当前 A/B 结论以下面 v1.2 验证为准；R4 ready 不代表 R5 已关闭 A/B。

原工作树/原工作区的历史缓存和构建目录清理不属于本轮产品缺陷修复；不执行 R5 清单中曾被自动审批阻止的删除。新测试使用独立临时目录，完成后回收本轮新建临时目录及自有测试进程。

## R5-002-003 A/B 续修（v1.2）

- A：共享 subreaper 仅凭新出现的直接子进程认领所有权，会误认无关 sentinel 的孤儿后代。已改为每次启动一个独立 supervisor，由该进程设置 subreaper 且只启动本次目标 root；调用方 subreaper 状态不变、无关孤儿不会进入 supervisor 的祖先树。快速 double-fork、setsid、exec 清空环境仍由这条隔离边界证明归属，不依赖恰好观察到中间父链或继承环境标记。PID 启动时刻与 pidfd 信号保护保留，helper 关闭无关继承 FD，并将实际目标 PID/退出码/信号交互交给窄 Popen-like proxy。
- supervisor 会记录补做 waitpid 的 PID；正常回收直接 root 与 supervisor 本身不计作产品补回收。缺少完整清理报告、helper 异常退出或未回收不能默认为成功。核心实现：[owned_processes.py](evidence/r4-fix2-install/owned_processes.py)、[_owned_supervisor.py](evidence/r4-fix2-install/_owned_supervisor.py)。
- B：新 [verify_uv_install.py](evidence/r4-fix2-install/verify_uv_install.py) 两处真实成功断言均显式要求 `forced_pids`、`reaped_pids`、`remaining` 为空。独立探针直接提取并执行这两处 AST：exit 0 但遗漏 wait 的实际命令产生非空 `reaped_pids` 时，两处均拒绝；自行 wait 的命令通过。
- 新脚本和结果集中放在 `evidence/r4-fix2-install/`，历史 `r4-fix-install/` 和 `r5-retest-install/` 完整保留。仅复验现有 wheel SHA-256 `5efb61936735e20eb05dd0a053d5568b9d2a0268e16f7096d2b5429ed5374fa9`，不重新构建。

### 本轮实际验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 独立所有权与成功判定保护回归 | **7 组通过**：A 的无关 sentinel/孤儿后代在 guard 运行期间被外层接管，guard 结束后均实际存活，且未被认领/发信号/回收；B 的 exit 0 漏 wait 被真实两处成功断言拒绝；3 轮快速 double-fork/setsid/空环境 exec 后代在关闭前确认 PID/启动身份存在，关闭后实际消失；正常自行 wait 通过；强杀/补回收/残留字段逐一拒绝 | [脚本](evidence/r4-fix2-install/verify_owned_edges.py)、[最终结果与实际命令](evidence/r4-fix2-install/owned-edges-results.json) |
| 失败清理回归 | **3 项通过**：PTY 观察失败、独立会话持管道超时、创建失败；只清理本次目标树，既有 sentinel 不受影响，supervisor 自身已回收，调用方 subreaper 状态保持 | [脚本](evidence/r4-fix2-install/verify_cleanup.py)、[结果](evidence/r4-fix2-install/cleanup-results.json)、[输出](evidence/r4-fix2-install/cleanup-run.txt) |
| 现有 wheel 标准安装复验 | **7 场景、14 项纯布局探针通过**；真实 proc/statvfs/UUID/Storage 验证通过；16 份正常报告的 forced/reaped/remaining 均为零，supervisor 全部回收，未依赖兜底强杀或补 waitpid；临时安装已移除 | [结果](evidence/r4-fix2-install/results.json)、[输出](evidence/r4-fix2-install/run.txt)、同目录 ANSI 记录 |
| 产物与范围保持 | 产品、永久测试及旧脚本等 **53 个保护输入完全不变**；原 wheel SHA-256 不变；最终 5 份验证脚本语法及 `git diff --check` 通过，探针/安装证据绑定最终脚本哈希，执行前后无漂移 | [校核汇总](evidence/r4-fix2-validation.json)、[安装前脚本哈希](evidence/r4-fix2-install/final-scripts-before-install.json) |

快速 fork 保护探针首次使 root 立即退出，supervisor 合法清理过快导致 leaf 尚未写好观察标记；该前置失败保留在 [owned-edges-results-initial.json](evidence/r4-fix2-install/owned-edges-results-initial.json)。随后为 root 加入 ready/release 握手，让外层先证明 leaf 实际存活，再释放 root；中间父链快速消失、setsid 和空环境 exec 不变，未要求实现延迟本来正确的清理。独立审查同时修正了 helper 对 PID 新身份的记录更新及清理循环使用当前记录的问题，最终结果绑定修正后的脚本。

本轮只改新证据目录中的验证工具和本交接，不重复执行产品全量 pytest；引用 R5 v1.2 已独立完成的 **Ubuntu 688 passed、Windows 633 passed / 55 skipped**，并用产品/永久测试哈希不变证明适用范围，不能把引用记录写作本轮新执行。网络证据仍限定为离线命令配置与本地受控实验，不宣称做了系统级动态网络审计；安装 resize 提示/恢复与纯布局探针、源码真实 PTY 几何验证继续分开表述。

实际执行入口均在本地 WSL Ubuntu-24.04，使用既有 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B`：新目录的 `verify_owned_edges.py`、`verify_cleanup.py`、`verify_uv_install.py --wheel <现有 wheel> --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12 --wheelhouse /mnt/d/Documents/joi-observer/.pytest_cache/offline_wheels --output <新目录>/results.json`。完整参数保存在探针/安装 JSON，安装始终显式 `--offline --no-index --no-python-downloads`。最后在当前工作树执行 `python -B docs/dev-workflow/dev-0/REQ-002/evidence/summarize_r4_fix2.py` 核对保护输入、最终脚本和原 wheel。

## 上轮 R5 修订回复（v1.1 历史）

### R5-002-001 大整数导致状态提交及显示异常

- 已复现 R5 两项回归。Python 整数本身有限，原 `math.isfinite(int)` 将其隐式转为 float，导致 OverflowError。
- 修复：`data/state.py` 对整数指标保留精确值，仅检查 float 的有限性；时间/窗口参数无法表示时仍返回契约规定的 ValueError。`tui/layout.py` 和 `widgets.py` 的通用格式化、GPU 索引文本及容量显示不再依赖 float 或超长 int 的直接 str 转换；容量使用整数商余数完成原 ROUND_HALF_UP 口径。
- 无新增整数上限、无公共签名或对象结构变更，无需修改采集器/Monitor。新增 16 个参数场景，包含 GPU/RAM/Storage→Monitor→State→Frame、大数正常→解析失败保值/历史缺口/日志→恢复，以及 RAM 字节换算超过 Python 整数字符串限制的场景。
- Windows 与 Ubuntu 同一定向集均 **345 passed**，见 [Windows](evidence/r4-fix-numeric-windows-v2.xml)、[Ubuntu](evidence/r4-fix-numeric-ubuntu.xml) 及同名前缀 `-run.json`。新建临时目录已清理。
- 新增测试初次使用 pytest 自动参数 ID，pytest 自身尝试转换 5001 位整数时收集失败；仅为新增参数指定显式 ID 后通过，未修改任何既有业务断言。首次报告保留为 `r4-fix-numeric-windows.*`，无 R2 契约修订请求。
- R4 结论：**已修复，待 R5 复验**。

### R5-002-002 脱离会话的后代持有管道使 IO 清理超时

- 已在本地 Ubuntu 复现 R5 失败用例，见 [基线](evidence/r4-fix-io-baseline.xml)。
- 修复：`_local_io.py` 显式持有 stdout/stderr 的父端读 transport；Linux 使用独立 pipe，Windows 使用 overlapped pipe。输出读取仍各限 1 MiB，`Process.wait()` 不再与输出管道 EOF 绑定。取消/关闭时只终止自有进程组和直接子进程，最多留出 25ms 管道收尾时间，随后主动关闭读端，并在同一个 250ms 截止内等待直接子进程回收。
- 重复取消不打断共享清理任务；创建过程被取消时保留进程/文件描述符所有权。无需修改 Monitor、公开接口、采样周期或依赖；不扫描或查杀端口外部会话中的后代。
- 原 R5 detached 用例保留全部断言并扩展为 timeout/cancel/close/parallel/runtime 五路径，增加直接子进程已回收、外部后代仍存活、单/并行端口 250ms 和 ApplicationRuntime 整体 1 秒预算的断言。外部后代仅由测试 fixture 自己回收。
- Linux IO/Monitor/Runtime/真实 PTY 定向集 **78 passed**；Windows IO **4 passed / 33 Linux 专用项 skipped**，包含原生双路输出、取消、close。见 [Ubuntu](evidence/r4-fix-io-ubuntu.xml)、[Windows](evidence/r4-fix-io-windows.xml)、[五路径](evidence/r4-fix-io-detached.xml)。所有对应 runner 临时目录均已回收。
- 另有独立只读审阅及 Windows 8 端口进程层探针，见 [记录](evidence/r4-fix-io-windows-probe.json)。该探针调用私有 `_execute` 验证本地进程层，不能作为 NVIDIA 白名单或驱动验证。
- 首轮返修全量出现一项新 fixture 竞态：并行 writer 截断共用 PID 标记，reader 可能在文件内容写完前观察到路径。已将 PID 记录改为唯一临时文件写完后原子替换，并只统计已发布记录；未调整 timeout、250ms/1s 预算或任何原有回收断言。失败报告保留为 [r4-fix-final-ubuntu-marker-race.xml](evidence/r4-fix-final-ubuntu-marker-race.xml)，修复后重复并行/runtime 定向验证通过。本问题是新增测试协议错误，无 R2 契约修订。
- R4 结论：**已修复，最终双平台全量通过，交 R5 复验**。

### R5-002-003 安装验证失败清理与证据范围

- 保留 R5 对 `tests/test_hardware_pty.py` 的所有权记录及故障注入回归。新建 [verify_uv_install.py](evidence/r4-fix-install/verify_uv_install.py) 与 [owned_processes.py](evidence/r4-fix-install/owned_processes.py)，不修改历史安装脚本和证据。
- 新 harness 临时启用 Linux subreaper，通过本次启动的父子关系、PID 启动时刻及 pidfd 定位自有进程；给应用有界正常退出时间后，仅清理本次后代并 waitpid 回收，最后恢复原 subreaper 状态。
- 三项真实失败自测通过：PTY 观察断言失败、命令超时且脱离会话持管道、创建进程失败；独立预置的无关 sentinel 保持存活，所有本轮子进程和临时目录已回收。见 [cleanup-results.json](evidence/r4-fix-install/cleanup-results.json)。
- 新安装报告明确 `dynamic_system_network_audit=false`，不以预设 `network_used=False` 冒充动态系统审计；安装 resize 证据限定为实际提示输出/终端恢复，纯 Frame 几何探针和源码真实 PTY 断言单独说明。
- 最终新 harness 构建与安装已通过，见 [results.json](evidence/r4-fix-install/results.json)：7 个新 shell/异目录命令及 PTY 场景、14 项纯布局探针、真实 proc/statvfs/UUID/Storage 读取；源码→wheel→安装逐文件一致。17 份正常清理报告均为 0 强杀、0 残留，subreaper 全部恢复，本轮临时安装已移除。正常成功路径如需要 harness 强杀即判失败，不能靠清理兜底掩盖产品泄漏。
- 新包：[joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/r4-fix-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256 `5efb61936735e20eb05dd0a053d5568b9d2a0268e16f7096d2b5429ed5374fa9`。旧 wheel 和验证记录完整保留。
- R4 结论：**已修补并验证，待 R5 复验**。

## 返修最终验证（v1.1）

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| Windows / Python 3.12.10 全量 | **633 passed / 55 skipped / 0 failed / 0 errors**，10.13s；跳过项为 Linux IO/Unix PTY，在 Ubuntu 实际执行 | [文本](evidence/r4-fix-final-windows.txt)、[JUnit](evidence/r4-fix-final-windows.xml)、[命令与临时目录回收](evidence/r4-fix-final-windows-run.json) |
| WSL Ubuntu-24.04 / Python 3.12.3 全量 | **688 passed / 0 skipped / 0 failed / 0 errors**，29.69s；包含 R5 原三项失败、数值补测、五种 detached 管道关闭路径、真实 PTY 及测试失败清理 | [文本](evidence/r4-fix-final-ubuntu.txt)、[JUnit](evidence/r4-fix-final-ubuntu.xml)、[命令与临时目录回收](evidence/r4-fix-final-ubuntu-run.json) |
| 新 wheel、安装与 harness 失败自测 | 与当前产品源码逐文件一致；7 安装场景、14 纯布局探针、真实 IO 及 3 清理故障自测通过；正常路径不依赖兜底强杀，全部自有进程及临时安装清理完成 | [安装](evidence/r4-fix-install/results.json)、[失败自测](evidence/r4-fix-install/cleanup-results.json) |
| 语法、差异及断言保留 | 42 个 Python 文件编译检查、`git diff --check` 通过；返修前 **1263 条 assert AST 全部保留**。仅 4 个产品文件及 4 个测试文件变化，公共接口、README、依赖和锁文件不变 | [汇总与当前哈希](evidence/r4-fix-validation.json) |

本轮比 R5 的 665 项增加 23 个参数场景，总计 688 项。最终源码、测试哈希与 wheel/source/install 绑定见汇总；未创建提交。证据目录仍按仓库规则忽略，交付时需同时提供本地报告与新 wheel。

实际最终命令在当前工作树执行；runner 为每次运行建立独立 TemporaryDirectory，用作 pytest `--basetemp` 和 pycache 路径，使用 `-B -p no:cacheprovider`、`PYTHONDONTWRITEBYTECODE=1`，在成功和失败时均回收该目录。Windows 复用原工作区 offline_deps，Ubuntu 复用既有 venv，无依赖下载。

```powershell
python -B docs/dev-workflow/dev-0/REQ-002/evidence/run_r4_fix_checks.py --name r4-fix-final-windows
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/Documents/codex_worktree/dev-req002/joi-observer && /home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B docs/dev-workflow/dev-0/REQ-002/evidence/run_r4_fix_checks.py --name r4-fix-final-ubuntu'
python -B docs/dev-workflow/dev-0/REQ-002/evidence/summarize_r4_fix.py
```

最终安装使用新的 `evidence/r4-fix-install/verify_uv_install.py`，`--output` 为该目录 `results.json`，`--out-dir` 为该目录 `wheels/`；实际 uv 构建/安装 argv 保存在安装结果的 commands 字段。离线依赖目录继续使用 `/mnt/d/Documents/joi-observer/.pytest_cache/offline_wheels`，显式使用 `--offline --no-index --no-python-downloads`。源码真实 PTY 的逐尺寸绘制断言与安装版提示/恢复验证分别报告，不混淆证据能力。

## 首次交付产物（v1.0 历史）

| 任务 | 状态 | 实现与验证入口 |
| --- | --- | --- |
| T-001 可取消的本地 IO | 完成 | `collectors/_local_io.py`、`_hardware_worker.py` 与 `LocalHardwareIO`；固定 argv/操作白名单、双路各 1 MiB、文件/statvfs 进程隔离、超时/取消/幂等关闭。`test_local_hardware_io.py`、`test_local_hardware_io_edges.py`。 |
| T-002 Host 与挂载点采集 | 完成 | `CpuCollector`、`MemoryCollector`、`StorageCollector` 与 `_hardware_parsing.py`；CPU 失败/取消重置基线、RAM available 口径、挂载前后唯一身份校验。 |
| T-003 GPU 查询与发现 | 完成 | `GpuCollector`、`GpuDiscovery`；完整 UUID 身份、字段失败隔离、显存成对保值、独占 IO 和成功无卡区分。`test_hardware.py`、`test_hardware_collectors_edges.py`。 |
| T-004 动态来源调度与收尾 | 完成 | `monitor.py`；先校验整轮声明/工厂结果再注册，失败不产生半轮状态，独立周期与首采，废弃资源和所有动态来源并行关闭。`test_hardware_monitor.py`、`test_hardware_monitor_edges.py`。 |
| T-005 硬件控件与 Frame | 完成 | `tui/widgets.py`、`tui/layout.py`；数值/条格一致、固定 STALE 槽、显式映射高亮及旧快照兼容，保持半页/Storage/Docker 几何。`test_hardware_view.py`、`test_hardware_view_edges.py`。 |
| T-006 生产组合根 | 完成 | `build_hardware_sources`、`cli.py`；CPU/RAM/前三挂载和独立 inventory 进入同一 State/Monitor，保留 Docker/vLLM 占位及注入通道，组装不采集。`test_hardware_runtime.py`。 |
| T-007 离线验收与交付 | 完成 | 全量双平台、真实 Linux IO、真实 PTY 与最终 wheel/隔离 uv 安装全部通过；README 已更新实际硬件范围。 |

产品代码均位于 `src/joi_observer/`，测试位于 `tests/`。未新增运行依赖，`pyproject.toml` 与 `uv.lock` 未改。只读状态、错误码与日志体系均复用 REQ-001。

## 首次交付验证证据（v1.0 历史）

### 开发前检查与环境

主对话检查 T-001/T-006/T-007，三个 subagents 分别检查 T-002/T-003、T-004、T-005；全部确认可行后才开始实现，无 R2/R3 阻碍。

Windows 系统 Python 缺 PyYAML，首次收集报环境错误；复用原工作区已有 `.pytest_cache/offline_deps` 后收集正常，没有安装或下载依赖。WSL 发行版为 `Ubuntu-24.04`，使用既有 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。两平台均只运行本地离线测试。

- Windows 基线：`$env:PYTHONPATH='D:\Documents\joi-observer\.pytest_cache\offline_deps'; python -m pytest -q --tb=no`，**350 passed / 202 failed / 15 skipped**，与 R2/R3 业务未实现基线一致。证据：[r4-baseline-windows.txt](evidence/r4-baseline-windows.txt)。
- 原有 R2 新增业务测试共 203 项，接线后全通过；未删改其断言、未添加 xfail。
- 本轮新增 83 项风险/边界回归，全部测试共 650 项；既有 R2 与 REQ-001 测试预期保持。

### 最终验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| Windows Python 3.12.10 全量 | **602 passed / 48 skipped / 0 failed / 0 errors**，8.36s；跳过项全部为本地 Linux IO 或 Unix PTY，在 Ubuntu 实际执行 | [文本](evidence/r4-final-windows.txt)、[JUnit](evidence/r4-final-windows.xml) |
| WSL Ubuntu-24.04 / Python 3.12.3 全量 | **650 passed / 0 skipped / 0 failed / 0 errors**，15.57s | [文本](evidence/r4-final-ubuntu.txt)、[JUnit](evidence/r4-final-ubuntu.xml) |
| 语法与差异 | `python -m compileall -q src tests`、`git diff --check` 均通过 | [汇总](evidence/r4-validation.json) |
| 最终 wheel 与离线 uv 安装 | 同一 wheel 安装到临时隔离工具环境；源码→wheel→安装文件、worker 与 README 元数据逐一匹配；新 shell/异目录裸命令、help/缺配置无采集、真实 Host/Storage 和固定 UUID 查询、q/信号/resize 均通过；临时安装已清理 | [脚本](evidence/verify_r4_uv_install.py)、[结果和实际 argv](evidence/r4-uv-install-results.json)、`r4-installed-pty-*.ansi` |
| 版本绑定 | 分支 `codex/dev-req002`，基线 HEAD `a84f9d8b632544f1da005df37d7badc2c530d617` 加当前未提交工作树；记录产品、测试、README、锁文件 SHA-256，并与安装证据交叉核验 | [r4-validation.json](evidence/r4-validation.json) |

最终包：[joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256 `ee77eb300a072d8639f963b05d6298c29ccf082ee99ac4afc7af680a0600b002`。未创建提交；证据目录按仓库现有 `.gitignore` 规则保留于本地，交接时需要一并提供，不能仅依靠 Git diff 传递这些报告。

实际最终命令（均在当前 worktree 中执行；Linux 命令通过 `wsl -d Ubuntu-24.04 -- bash -lc` 调用）：

```powershell
$env:PYTHONPATH='D:\Documents\joi-observer\.pytest_cache\offline_deps'
$env:PYTHONPYCACHEPREFIX='D:\Documents\codex_worktree\dev-req002\joi-observer\.pytest_cache\r4-final-windows-pycache'
python -m compileall -q src tests
python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r4-final-windows.xml
git diff --check
python docs/dev-workflow/dev-0/REQ-002/evidence/summarize_r4_validation.py
```

```bash
cd /mnt/d/Documents/codex_worktree/dev-req002/joi-observer
PYTHONPYCACHEPREFIX=/home/shawn/projects/tmp/joi-observer-req002-final-pycache /home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r4-final-ubuntu.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-002/evidence/verify_r4_uv_install.py --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12 --wheelhouse /mnt/d/Documents/joi-observer/.pytest_cache/offline_wheels --output docs/dev-workflow/dev-0/REQ-002/evidence/r4-uv-install-results.json
```

安装脚本显式使用 `uv --offline --no-python-downloads` 与 `--no-index --find-links` 构建/安装，复用本地原始 wheel，未访问包索引。实际重建和复验参数以安装 JSON 的 commands 字段为准。

### 实际 OS 与终端

- [r4-local-io-ubuntu.xml](evidence/r4-local-io-ubuntu.xml)、[r4-local-io-review-ubuntu.xml](evidence/r4-local-io-review-ubuntu.xml)：27 项真实 Linux IO 测试通过。包括真实 proc/statvfs、errno、FIFO 阻塞、命令 stdout/stderr 上限、spawn/取消竞争、8 端口并行关闭、慢来源隔离、继承输出管道；直接子进程均终止并回收，8 端口合计关闭低于 250ms。
- [r4-hardware-pty-summary.json](evidence/r4-hardware-pty-summary.json)、[r4-hardware-pty-tests.xml](evidence/r4-hardware-pty-tests.xml)：6 项真实生产链路 PTY 测试通过。临时本地 NVIDIA 命令提供五卡或慢命令，文件/容量读取和父进程生命周期不替换；验证五卡数据绘制、缩放、q/SIGINT/SIGTERM、慢采集响应、termios/光标/备用屏幕恢复、无网络尝试与原始输出泄漏。
- [r4-frame-check.json](evidence/r4-frame-check.json) 及 `r4-frame-*.txt`：给定选择 A/B/未知的纯 Frame 布局和高亮证据，明确不替代真实 PTY。
- [r4-monitor-windows.xml](evidence/r4-monitor-windows.xml)、[r4-monitor-ubuntu.xml](evidence/r4-monitor-ubuntu.xml)：126 项调度、状态、日志定向回归通过。

## 首次交付决策（v1.0 历史）

- 工作目录采用 R2/R3 已明确的当前 worktree，不在 AGENTS.md 指向的原工作区重复维护产物；只复用原目录现有离线依赖。
- 多个任务涉及 `hardware.py`，按类划分修改范围；解析、本地进程管理与 worker 使用包内私有模块。公共接口和跨模块契约未改变。
- 每次文件/statvfs 读取启动可终止 worker；Linux 独立进程组便于清理继承管道，Windows 子进程无可见控制台。真实测试证明满足本轮取消/关闭预算；没有引入无依据的吞吐指标。
- 集成审查发现并修复 GPU 名称错误标记显示、显存总量小于一字节导致 Frame 异常、Storage 身份校验和 statvfs 路径不一致三个实现缺陷；补采集→State→Frame 与原始 IO 回归，未调整验收含义。
- 最终安装发现本机合法 nsfs mountinfo 记录的 root 为 `net:[4026532238]` 等不透明身份，而非绝对路径；旧解析误拒绝这些无关记录，使 `/` 容量失败。已保留 root 身份原文，只对被查询的 mountpoint 规范化，并增加 net/mnt 样本及真实 Host/Storage 成功回归。首次失败留存 [r4-uv-install-nsfs-failure.json](evidence/r4-uv-install-nsfs-failure.json)；修复后重新跑完整双平台测试、重新构建 wheel 和验证安装，无残留失败。

## R3 修订汇总

无计划边界或依赖调整。子代理分工与私有模块组织属于 R4 执行安排。

## R2 修订汇总

无公共接口、架构或测试契约变更，未修改有效黑盒预期。新增边界问题均为 R4 实现缺陷，按既定契约修复。

v1.1 测试侧修正供 R2 备案：新增巨大整数参数的 pytest 自动 ID 改为显式 ID；新增并发 PID 标记改为写完后原子发布。二者均为测试基础设施问题，原失败证据、全部预算和业务断言保留，修正后验证通过；没有待 R2 澄清或更改的验收含义。

## 未验证与后续范围

- 禁止连接服务器的约束始终保留。目标服务器 NVIDIA 驱动版本/权限、真实 GPU 输出、无卡返回码以及挂载实际部署未现场核验；本地模拟 NVIDIA 命令不代表目标驱动验证。
- 挂载前后身份核对不能保证检测极短 ABA 变化，沿用 R2 已说明边界。
- AC-205/206 本轮只验证给定 `ViewSelection` 的显式映射、清空和只读行为；方向键模型选择待 REQ-005，完整双主题待 REQ-006。Docker/vLLM 采集待 REQ-003/004。
- `ready` 仅表示 R4 可交接，不表示 R5 验收通过。不会自动创建或推进 R5 对话。

## 下一步

本轮 R5-002-003-A/B 已完成修订和验证，`stage=R4`、`result=ready`、`next_role=R5`。请人工将本交接 **v1.2** 与 `r4-fix2-*` 新证据交给 **R5 复验并关闭剩余安装工具问题**；R5-002-001/002 已关闭，产品和原交付 wheel 未变。未自动推进其他对话，未连接目标服务器。
