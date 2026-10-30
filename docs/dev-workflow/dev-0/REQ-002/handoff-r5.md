# dev-0 / REQ-002 R5 验收交接

- stage：R5
- result：passed
- work_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0\REQ-002`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-002 / AC-201～AC-207 及共同规则。
- 验收依据：[plan.md](plan.md) v1.0、[handoff-r4.md](handoff-r4.md) v1.2 续修、[handoff-r2.md](handoff-r2.md) v1.0；hardware v1.0、monitor-state v1.6、configuration v1.2、application-shell v1.3、error-logging v1.1 及公开接口注释。
- 审查对象：分支 `codex/dev-req002`，基线 HEAD `a84f9d8b632544f1da005df37d7badc2c530d617` 加当前全部未提交的 R2/R3/R4/R5 产物。本轮输入快照见 [r5-retest2-before.json](evidence/r5-retest2-before.json)，最终绑定与范围保持见 [r5-retest2-validation.json](evidence/r5-retest2-validation.json)。此前各版快照保留为历史证据。
- next_role：R0
- 修订：v1.3，2026-10-30；收到 R4 v1.2 后独立复验，关闭 R5-002-003-A/B，REQ-002 本轮验收通过。

**REQ-002 本轮验收通过，所有验收问题已关闭。** R5-002-001、R5-002-002 保持关闭，R5-002-003-A/B 本轮复验通过。独立重跑 7 组所有权/成功判定保护、3 项失败清理、7 个安装场景和 14 项布局检查均通过；16 份正常安装清理报告没有强杀、补回收或残留。产品和永久测试未变化，上轮独立全量 Ubuntu 688 passed、Windows 633 passed / 55 skipped 的结果继续适用，本轮未重复运行产品全量。

## R4 v1.2 安装工具续修复验（当前有效）

本轮只复验剩余安装工具 A/B。53 个产品、永久测试、README、依赖及旧脚本保护输入与 R4 清单完全匹配；其中 46 个产品/永久测试等输入也与上轮 R5 独立全量所验证的版本一致。新 5 份脚本在执行前后均匹配 R4 最终哈希。本轮没有修改业务、测试或设计，仅保存复验材料并维护本交接。

为保留 R4 及上轮失败证据，5 份新脚本逐字节复制到 `evidence/r5-retest2-install/` 后运行，目录层级保持一致；交付 wheel 原样复用，SHA-256 为 `5efb61936735e20eb05dd0a053d5568b9d2a0268e16f7096d2b5429ed5374fa9`，没有重新构建。

| 本轮 R5 实际验证 | 结果与依据 | 新证据 |
| --- | --- | --- |
| A：独立 supervisor 所有权 | 无关 sentinel 及其孤儿后代在 guard 期间和结束后仍存活，未被认领/发信号/回收；三轮快速 double-fork、setsid、空环境 exec 的自有后代先确认存活、再实际回收 | [7 组保护探针结果](evidence/r5-retest2-install/owned-edges-results.json)、[输出](evidence/r5-retest2-install/owned-edges-run.txt) |
| B：正常成功判定 | 直接执行两处真实 AST 成功断言；exit 0 但漏 wait 的命令产生非空 reaped，两处均拒绝；正常自行 wait 通过；forced/reaped/remaining 三字段单独挑战均被拒绝 | 同上结果；[探针脚本](evidence/r5-retest2-install/verify_owned_edges.py) |
| 失败清理 | PTY 观察失败、独立会话持管道超时、创建失败共 3 项通过；只清理本次目标树，supervisor 自身回收、调用方 subreaper 状态保持 | [结果](evidence/r5-retest2-install/cleanup-results.json)、[输出](evidence/r5-retest2-install/cleanup-run.txt) |
| 现有 wheel 安装及运行 | 7 个新 shell/异目录命令与 PTY 场景、14 项安装版布局检查通过；真实 proc/statvfs/UUID/Storage 验证通过；16 份正常报告 forced/reaped/remaining 均为空，supervisor 全部回收，临时安装移除 | [结果](evidence/r5-retest2-install/results.json)、[输出](evidence/r5-retest2-install/run.txt)，同目录实际 ANSI 输出 |
| 版本、语法与残留 | 53 个保护文件和 5 份新脚本执行前后无漂移；新脚本编译检查及 git diff --check 通过；无相关测试/helper 进程、当前用户僵尸进程或临时 uv 安装 | [输入](evidence/r5-retest2-before.json)、[最终汇总](evidence/r5-retest2-validation.json)、[Windows](evidence/r5-retest2-windows-processes.json)、[Ubuntu](evidence/r5-retest2-linux-processes.json) |

两项并行只读审查分别核对隔离 supervisor/PID 所有权，以及真实成功断言/探针/PTY proxy 语义。另由 R5 审查执行两个自有进程实验：错误启动时刻的 SIGKILL 请求被拒绝，sentinel 存活；真实终止自有 supervisor 后，调用方报缺少清理报告的 RuntimeError，未将失败判为通过。该实验目标由外层 finally 回收，不宣称 SIGKILL 后 helper 本身还能完成清理。

实际入口均在当前 worktree，由 `wsl -d Ubuntu-24.04 -- bash -lc` 执行，使用既有 venv 和 `PYTHONDONTWRITEBYTECODE=1`：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B docs/dev-workflow/dev-0/REQ-002/evidence/r5-retest2-install/verify_owned_edges.py
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B docs/dev-workflow/dev-0/REQ-002/evidence/r5-retest2-install/verify_cleanup.py
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B docs/dev-workflow/dev-0/REQ-002/evidence/r5-retest2-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12 \
  --wheelhouse /mnt/d/Documents/joi-observer/.pytest_cache/offline_wheels \
  --wheel /mnt/d/Documents/codex_worktree/dev-req002/joi-observer/docs/dev-workflow/dev-0/REQ-002/evidence/r4-fix-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl \
  --output /mnt/d/Documents/codex_worktree/dev-req002/joi-observer/docs/dev-workflow/dev-0/REQ-002/evidence/r5-retest2-install/results.json \
  --out-dir /mnt/d/Documents/codex_worktree/dev-req002/joi-observer/docs/dev-workflow/dev-0/REQ-002/evidence/r5-retest2-install/wheels
```

本轮没有重新执行产品全量 pytest；引用上轮 R5 实测结果，并以源码/永久测试哈希不变证明适用性，不将引用写作本轮新执行。所有新建临时目录和自有实验进程均回收，旧清理清单未执行。继续保持离线验证、没有连接服务器；网络证据仍不是系统级动态审计。目标服务器环境、后续导航和完整双主题等剩余范围不变。

## R4 v1.1 修复复验（v1.2 历史，产品结论沿用）

本轮输入为 R4 v1.1 的当前未提交工作树。独立核对 R4 记录的 46 个源码/测试等文件哈希全部匹配，并保存 55 个输入文件的快照：[r5-retest-before.json](evidence/r5-retest-before.json)。复验结束这些输入均未被 R5 改动，返修前 1263 条 assert AST 仍全部保留，当前 1310 条 assert 也未改变；汇总见 [r5-retest-validation.json](evidence/r5-retest-validation.json)。

| R5 实际执行 | 结果 | 证据 |
| --- | --- | --- |
| Windows / Python 3.12.10 全量 | **633 passed / 55 skipped / 0 failed/errors**，10.46s | [文本](evidence/r5-retest-final-windows.txt)、[JUnit](evidence/r5-retest-final-windows.xml)、[命令与临时目录回收](evidence/r5-retest-final-windows-run.json) |
| WSL Ubuntu-24.04 / Python 3.12.3 全量 | **688 passed / 0 skipped / 0 failed/errors**，31.22s；包含原三项失败、五种管道关闭路径和真实 PTY | [文本](evidence/r5-retest-final-ubuntu.txt)、[JUnit](evidence/r5-retest-final-ubuntu.xml)、[命令与临时目录回收](evidence/r5-retest-final-ubuntu-run.json) |
| 大整数独立探针 | 原两项失败及 5001 位 GPU 索引 Frame/映射通过；1043 组容量与高精度 Decimal 参考一致，格式化及非法百分比检查通过 | [独立结果](evidence/r5-retest-numeric-independent.json) |
| 新 wheel 的标准安装复验 | 7 个安装/PTY 场景、14 项安装版布局探针通过；16 份正常清理报告均无 forced/reaped/remaining PID；临时安装已移除 | [安装结果](evidence/r5-retest-install/results.json)、[输出](evidence/r5-retest-install/run.txt) |
| R4 新 harness 原有失败自测 | PTY 观察失败、脱离会话持管道超时、创建失败，共 3 项通过；基线 sentinel 存活、subreaper 恢复 | [结果](evidence/r5-retest-install/cleanup-results.json)、[输出](evidence/r5-retest-install/cleanup-run.txt) |
| 新增 harness 所有权/证据探针 | **2 项问题复现**，独立脚本退出码 1；不是产品 pytest 失败 | [脚本](evidence/r5-retest-install/verify_owned_edges.py)、[结果](evidence/r5-retest-install/owned-edges-results.json) |
| 最终语法/差异/残留检查 | 42 个 Python 文件语法、git diff --check 通过；无相关测试进程、当前用户僵尸进程或临时 uv 安装 | [汇总](evidence/r5-retest-validation.json)、[Windows](evidence/r5-retest-windows-processes.json)、[Ubuntu](evidence/r5-retest-linux-processes.json) |

全量执行沿用独立 TemporaryDirectory，设置 `--basetemp`、隔离 pycache、`-B -p no:cacheprovider` 和 `PYTHONDONTWRITEBYTECODE=1`；本轮新建目录在成功/失败后自动回收，未处理旧清理清单。实际命令均在同名 `-run.json`，只用既有本地 offline_deps/venv，无服务器连接。

安装复验使用 R4 新三份脚本的逐字节副本，置于本轮 `r5-retest-install/` 以保留 R4 历史证据；`--wheel` 指向 R4 新包，未重新构建。wheel SHA-256 为 `5efb61936735e20eb05dd0a053d5568b9d2a0268e16f7096d2b5429ed5374fa9`，源码→wheel→安装文件匹配。实际标准场景的 reaped/forced 均为零，因此新探针发现的问题不推翻这些已完成的成功安装证据。

### 迟到 spawn 初步判断的纠正

初步探针在真实 `create_subprocess_exec` 已返回 Process 后额外 sleep(0.5)，却未给该包装器提供取消清理，从而人为制造所有权空档。核对本机 Python 3.12.3 POSIX 和 3.12.10 Windows 源码后，确认标准库在创建取消时会 close/wait/rethrow，成功获取 transport 到返回 Process 之间没有新 await。保留同一取消契约的修正探针在事件循环退出后已回收直接子进程。

因此，先前 commentary 中的迟到创建产品泄漏判断已撤回，不作为新缺陷，也没有添加错误的永久失败用例。调查记录：[r5-reverify-io-late-spawn-assessment.json](evidence/r5-reverify-io-late-spawn-assessment.json)、[修正探针](evidence/r5-reverify-io-late-spawn-cancellation-contract.txt)。原管道问题的关闭依据是修复代码、五路径回归、原生 Windows IO 与本轮双平台全量。

## 二次复查范围与证据（v1.1 历史）

输入与首次审查最终哈希一致，见 [r5-recheck-before.json](evidence/r5-recheck-before.json)。本次交换分项审查范围，独立复核动态调度/IO、数值解析/状态边界以及 PTY/安装证据的实际断言与失败兜底。

本次新增 4 个用例：大整数跨采集、调度、状态的 2 个参数场景；独立会话后代持有管道的 1 个场景；PTY 观察断言失败后的进程清理 1 个场景。保留前轮 11 项补充用例和原业务断言。修改均限于测试，PTY 原用例只增加所有权记录与 finally 清理。

- 数值问题：[r5-recheck-numeric-windows.txt](evidence/r5-recheck-numeric-windows.txt) 及同名 XML，2 failed。预期不替设计规定数值上限：允许完整准确支持大整数，或在无法表示时按对象级解析失败隔离；无论哪种都须保证其他来源继续更新和下一轮恢复。
- IO 问题：[r5-recheck-io-all.txt](evidence/r5-recheck-io-all.txt) 及同名 XML，新增回归失败，原有本地 IO 用例保持通过。独立探针通过 subreaper 管理实验子进程，失败记录后执行回收。
- PTY 失败清理：[r5-recheck-pty-review.json](evidence/r5-recheck-pty-review.json)、[r5-recheck-pty-ubuntu.txt](evidence/r5-recheck-pty-ubuntu.txt) 及同名 XML；修改前强制观察失败确实留下慢命令，修改后 7 个 PTY 场景通过。

### 二次复查最终回归

| 环境 | 当前实际结果 | 证据 |
| --- | --- | --- |
| Windows / Python 3.12.10 | **612 passed / 2 failed / 51 skipped**，11.25s；失败为两项大整数场景，Linux/PTY 项在 Ubuntu 执行 | [文本](evidence/r5-recheck-final-windows.txt)、[JUnit](evidence/r5-recheck-final-windows.xml)、[实际命令与临时目录清理](evidence/r5-recheck-final-windows-run.json) |
| WSL Ubuntu-24.04 / Python 3.12.3 | **662 passed / 3 failed / 0 skipped**，29.01s；仅两项大整数及继承管道预算用例失败 | [文本](evidence/r5-recheck-final-ubuntu.txt)、[JUnit](evidence/r5-recheck-final-ubuntu.xml)、[实际命令与临时目录清理](evidence/r5-recheck-final-ubuntu-run.json) |

全部 665 项测试已验证；原有业务用例及 PTY 清理修补通过。新增失败保留，未 skip/xfail。完整回归用独立 TemporaryDirectory 作为 `--basetemp` 和 pycache 路径，`-B -p no:cacheprovider` 且设置 `PYTHONDONTWRITEBYTECODE=1`；退出码为 1 时也由 finally 回收这些新建临时目录。复用既有 Windows offline_deps 和 Ubuntu venv，无下载、安装或服务连接。

IO 新用例的第一次冷启动运行暴露测试前置竞态：0.1 秒预算可能早于 Python 替身写 PID 标记，失败未到目标断言。已将该新用例的命令 timeout 调整为 1 秒并在标记后观察 1.5 秒，**清理要求仍为 250ms**；最终确实失败于清理预算断言。原失败尝试保留为 [r5-recheck-cold-start-ubuntu.txt](evidence/r5-recheck-cold-start-ubuntu.txt)，冷启动定向复验见 [r5-recheck-io-detached-pipe-cold.txt](evidence/r5-recheck-io-detached-pipe-cold.txt)。探针外层超时、缺 marker 和 close 异常三种兜底均验证无自有残留进程并恢复 subreaper 状态，见 [r5-recheck-io-probe-cleanup-check.txt](evidence/r5-recheck-io-probe-cleanup-check.txt)。

最终 [r5-recheck-validation.json](evidence/r5-recheck-validation.json) 绑定当前源码/测试哈希：本轮仅 3 个测试文件变化；原始测试中的 **1183 条 assert AST 全部保留**。唯一修改的原测试函数仅增加 PTY finally 清理；业务、设计、依赖和原断言不变。42 个 Python 文件语法检查、git diff --check 均通过。

## R4 修订汇总

### R5-002-001 [P2] 大整数字段在状态提交时引发未隔离异常

- 关联：AC-201/202/204、共同故障隔离规则、T-002/T-003/T-006。
- 位置：`collectors/_hardware_parsing.py:41,80,146` 接受整数；`data/state.py:57` 的 `math.isfinite(value)` 隐式转 float 并溢出；`monitor.py:291` 的状态提交将异常传播出 poll。
- 实际：GPU index 为 `10**309` 或 RAM MemTotal 为 `10**309 kB` 时，采集返回成功，随后抛 OverflowError，整条监控循环退出。其他正常来源不能继续本轮提交。这是罕见异常/极端输入，不宣称真实设备已产生该值。
- 预期：整数支持范围须一致；可准确支持时正常提交，无法表示时受影响对象独立失败并可恢复，不能让数值校验异常终止全部监控。现有设计没有规定 float 上界，本测试不引入未经约定的容量/索引上限。
- 复现：`python -m pytest tests/test_hardware_integration_edges.py -k large_raw_integer -q --tb=short`；两参数均失败于相同 OverflowError。
- 处理请求：R4 修复采集→状态的数值契约衔接及异常隔离，复验健康来源继续采样、原值/历史和日志语义、下一轮恢复；同时避免格式化环节再次做不可承受的 float 转换。
- R4 回复与 R5 复验：R4 v1.1 对整数保留精确值，仅对 float 验证有限性；显示和容量格式化也避免隐式转 float/超长 int 字符串限制。原回归、额外大整数端到端和独立参考比较均通过。
- 状态：**v1.2 已关闭**。

### R5-002-002 [P2] 清理等待后代关闭管道，可能突破超时与退出预算

- 关联：hardware.md/monitor-state.md 的取消/close 250ms、应用总体 1 秒关闭契约；T-001/T-004/T-007。
- 位置：`collectors/_local_io.py:84-99` 的 `_reap`；关键行 99 无截止等待 stdout/stderr EOF，`_execute:148/150` shield 等待该清理。
- 实际：受控本地 NVIDIA 命令 fork 后代，后代 setsid 并继承输出管道。killpg 只终止原进程组，后代继续持有管道；端口 timeout=0.1 秒后，等待超过 0.5 秒仍未返回。显式终止后代释放管道才完成超时处理。现有 inherited-pipes 用例只覆盖同组后代，因此未暴露此分支。
- 预期：终止并回收自己拥有的直接子进程，输出管道或外部后代不能使清理无限等待；不要求无授权地查杀不属于本端口的系统进程。
- 复现：`python -m pytest tests/test_local_hardware_io_edges.py -k descendant_keeps_pipes -q --tb=short`。
- 处理请求：R4 为真实资源清理设置有效截止并处理继承管道，保留输出限制、正常采集和取消回收行为；复验单端口、并行端口及整体退出。
- R4 回复与 R5 复验：R4 v1.1 将父端读 transport 与 Process.wait 解耦，主动关闭读端并在同一截止内回收直接子进程；timeout/cancel/close/parallel/runtime 五路径通过，外部会话后代由 fixture 自行管理。原有回归断言保留。
- 状态：**v1.2 已关闭**；迟到 spawn 初步探针不符合标准库取消语义，已排除，见本交接纠正记录。

### R5-002-003 PTY 测试失败兜底遗漏独立会话子进程（测试侧已修补）

- 位置：原 `tests/test_hardware_pty.py` finally 只执行 child.kill()/wait()；应用的 IO 子进程使用独立会话。
- 复现：强制观察函数无法提供预期 Frame，slow_quit 用例在 5 秒后断言失败；测试 finally 完成时慢 NVIDIA 子进程仍存活。实验外层随后显式终止并回收全部自有进程。
- 修补：记录 fixture 内子进程 PID 与启动时刻；先请求应用正常退出并有界等待，再按实时身份仅清理仍属于本测试的独立会话。新增故障注入用例验证失败后没有活子进程，保留正常 q/信号/终端恢复断言。
- 状态：**当前测试已修补并定向通过**。历史 `evidence/verify_r4_uv_install.py:92-95` 也有只杀主进程的兜底，本轮未改历史证据脚本；R4 再复用前应在新版本验证脚本补充失败清理。
- 证据口径修正：安装脚本的 `network_used=False` 是预设说明，不能单独视作动态网络审计；安装 resize 用例主要断言缩小提示，逐尺寸真实绘制覆盖来自源码 PTY，安装版另有纯布局探针。首次成功安装证据仍有效，但不能扩大这些断言所证明的范围。

#### R5-002-003-A [P2] 新 harness 误认领无关进程的孤儿化后代

- 位置：`evidence/r4-fix-install/owned_processes.py:62-64` 的 `OwnedProcess.observe`。
- 预期：只管理当前启动的 root 及其后代；既有无关进程及其后代不能因 subreaper 接管而变成本次所有物。
- 实际：guard 运行期间，把新出现的全部直接子进程认领为自有。受控实验先创建无关 sentinel，再让其孙进程孤儿化；sentinel 自身仍存活，但其孙进程被认领并 SIGKILL。原 sentinel 自测只验证 sentinel 本身，不能覆盖该情况。
- 复现：在本需求根目录通过 WSL Python 运行 `evidence/r5-retest-install/verify_owned_edges.py`（完整位置见上表）；结果中的 `R5-002-003-A` 为 reproduced，`descendant_was_claimed` 和 `descendant_was_force_killed` 均为 true。
- 处理请求：R4 在测试工具中建立可归属到本次 root 的可靠证明，不能仅凭“新直接子进程”判定所有权；加入无关既有进程后代的保护用例。信号的 pidfd/启动时刻保护需保留。
- R4 v1.2 回复与 R5 复验：每次启动独立 supervisor，只有它设置 subreaper 并创建本次唯一 root；外层无关进程的后代不会进入该 supervisor 的祖先树。原 A 触发时序、真实存活/未认领断言及快速 fork 三轮均独立通过。
- 状态：**v1.3 已关闭**。

#### R5-002-003-B [P2] 正常成功断言未拒绝 harness 补做 waitpid

- 位置：`evidence/r4-fix-install/verify_uv_install.py:116,175` 只检查 `forced_pids`；harness 的补回收记录在 `owned_processes.py:112-118`。
- 预期：正常成功路径应证明被测进程自行完成资源回收；harness 兜底补做 waitpid 不能被当作产品已回收的证据。
- 实际：受控命令 exit 0 前遗漏回收其已退出子进程。harness 补做 waitpid 后得到 `forced_pids=[]`、`reaped_pids=[PID]`，脚本两处正常成功断言仍通过。探针直接提取并执行被审脚本的真实 AST 断言，没有手抄另一套成功条件。
- 复现：同一 `verify_owned_edges.py`，`R5-002-003-B` 为 reproduced，`harness_reaping_was_masked=true`。
- 处理请求：R4 正常路径同时拒绝兜底强杀、补回收及残留；失败路径仍执行安全回收。补充正常退出但漏 wait 的场景。
- R4 v1.2 回复与 R5 复验：两处真实成功断言均要求 forced/reaped/remaining 为空；独立探针确认 exit 0 但漏 wait 被拒绝，自行 wait 通过，三字段逐一挑战也被拒绝。本轮标准安装 16 份报告均无需兜底修补。
- 状态：**v1.3 已关闭**。

两个探针均只操纵自己创建的实验进程；最终 `remaining_direct_children=[]`、`temporary_directory_removed=true`、`subreaper_restored=true`。原 PTY finally 漏清理问题已修补；v1.3 的 A/B 复验完成，**R5-002-003 整体关闭**。

## 历史环境残留核查与清理限制（v1.1；本轮未执行删除）

只读扫描未发现遗留 Joi 采集 worker、NVIDIA 测试替身或临时安装进程；现有 WSL 系统/用户服务不属于测试垃圾。独立复现实验均检查自有子进程回收。

已识别当前工作树构建副本、egg-info、Python/pytest 缓存，以及原工作区和 WSL 中同项目历史 pycache；pytest 默认保留的近期临时目录也列入清单。最终仍在的候选文件合计 **82,672,800 字节（约 78.84 MiB）**，详见 [r5-recheck-cleanup-inventory.json](evidence/r5-recheck-cleanup-inventory.json)。离线依赖/wheelhouse、复用虚拟环境、交接证据和交付 wheel 保留；含其他 worktree Docker 测试的目录及活动/归属不明目录不清理。最终进程检查见 [Windows](evidence/r5-recheck-windows-processes.json)、[Ubuntu](evidence/r5-recheck-linux-processes.json)，相关进程均为 0。

**本次未执行这些目录的删除。** 自动审批对 `.pytest_cache/r5-recheck-numeric-temp` 的 Remove-Item 返回 `blocked by policy`，未给更具体理由；已核验的构建目录删除在派发前中止。没有换机制绕过，也没有删除源码或证据。清单供用户明确安排后续清理。

## 首次审查产物（历史）

优先在已有测试文件追加 7 个测试函数，对应 11 个用例；没有新增带角色词缀的测试文件，没有删除、跳过或削弱原有断言。

| 文件 | 新增用例 | 补漏内容 |
| --- | ---: | --- |
| [test_hardware_collectors_edges.py](../../../../tests/test_hardware_collectors_edges.py) | 5 | 唯一 bind mount 的容量读取不受无关挂载记录重排影响；已支持字段转为三种明确不支持标记时清空旧值并解除 STALE；显存换算溢出时两项容量成对保值，独立字段继续更新。 |
| [test_hardware_integration_edges.py](../../../../tests/test_hardware_integration_edges.py) | 3 | 原始 GPU 响应→Collector→State→Frame；部分失败和设备索引变化时，旧索引、新索引、完整 UUID 的高亮分别符合契约，恢复与未知选择清空正确，重复渲染不额外采集。 |
| [test_hardware_monitor_edges.py](../../../../tests/test_hardware_monitor_edges.py) | 1 | 发现工厂错误返回已经注册的来源时，拒绝本轮声明且不得误关闭该来源；下一轮正确发现可恢复。 |
| [test_local_hardware_io_edges.py](../../../../tests/test_local_hardware_io_edges.py) | 1 | 取消某个 close 等待方后，本地 IO 仍完成真实 Linux 子进程回收，重复 close 可等待清理完成，满足 250ms 预算。 |
| [test_hardware_runtime.py](../../../../tests/test_hardware_runtime.py) | 1 | 生产调度、状态、日志和 UI 链路中，CPU 与 inventory 失败不阻止 RAM/Storage；恢复为空 inventory 后撤销 STALE、保持几何；失败不显示正常 0，原始错误不泄漏，日志限频与退出释放正确。 |

本交接、输入快照、JUnit、日志和安装复验结果统一保存在本需求目录。`evidence/` 沿用仓库 Git 忽略规则，后续交接须同时提供本地证据，不能只传 Git diff。

## 首次审查验证证据（历史）

### 审查范围与版本保留

采用 R2/R3/R4 已明确的当前 worktree 路径，不在 AGENTS.md 所列原工作区重复维护交接。原工作区只用于读取既有离线依赖。全程未尝试连接服务器。

开始时记录 57 个源码、测试、配置、需求、计划和设计输入的 SHA-256；R4 交付记录中的 45 个文件哈希全部匹配。结束时仅上述 5 个测试文件发生变化，原有 367 个顶层测试函数/辅助函数/类的 AST 全部保留。业务、设计、README、AGENTS.md、依赖和锁文件哈希不变；未创建提交。

| 验收范围 | 独立核对与实际验证 |
| --- | --- |
| AC-201：多 GPU 数值与字段可用性 | 核对完整 UUID 定位、CSV 结构、百分比/显存/温度/功耗单位、明确不支持标记与实际字段失败的区别；显存关联容量成对保值。原始样本及 Collector→State→Frame 用例通过。 |
| AC-202：CPU/RAM | 核对八项 CPU tick 差分、guest 不重复计入、无基线/回退/失败/取消的处理、真实闲置 0；RAM 使用 MemAvailable，数字、比例及条格一致。Host 来源隔离与恢复通过。 |
| AC-203、AC-207：Storage | 前三项采集与固定 3 内容行、失败不补位；精确挂载匹配、词法规范化、bind mount、前后身份变化/歧义、f_bfree 容量口径和无父目录回退通过；真实本地 `/` 容量正常。 |
| AC-204：无卡、失败及隔离 | 发现失败与成功无卡区分；单卡/字段失败只影响约定范围；保留旧值、STALE 固定槽、ERROR 限频/恢复和无原始诊断泄漏通过。生产链路故障恢复新增用例通过。 |
| AC-205、AC-206：本轮高亮范围 | 给定 ViewSelection 时，模型 A/B/未知的映射、完整 UUID、仅新鲜唯一 index、部分失败及恢复正确；保持全部 GPU 顺序/几何/历史，显示不触发采集。实际方向键与完整双主题按计划留给 REQ-005/006。 |
| T-001、T-004：调度与资源 | 动态发现整轮校验、首次立即采样、重复发现不重建、慢源不阻塞其他来源、迟到结果丢弃、错误工厂的资源归属和并行关闭通过。本地 Linux 真实进程覆盖超时、取消、有限输出、回收与继承输出管道。 |
| T-006、T-007：运行及交付 | 真实生产组合根、启动无采集边界、硬件 worker 包装、只读状态、全页半分、真实 curses/PTY 绘制、缩放、q/信号退出和终端恢复通过；安装包与当前源码匹配。 |

### R5 实际执行

以下为本轮实际执行结果；没有把 R4 的历史测试报告计作 R5 运行结果。

| 验证 | 结果 | 新证据 |
| --- | --- | --- |
| 补漏前 Windows 全量 | 602 passed / 48 skipped，7.59s，0 failed/errors | [文本](evidence/r5-baseline-windows.txt)、[JUnit](evidence/r5-baseline-windows.xml) |
| 补漏后 Windows 全量 | 612 passed / 49 skipped，9.95s，0 failed/errors；Python 3.12.10 | [文本](evidence/r5-final-windows.txt)、[JUnit](evidence/r5-final-windows.xml) |
| 补漏后 WSL Ubuntu-24.04 全量 | 661 passed / 0 skipped，24.74s，0 failed/errors；Python 3.12.3；包含全部真实 Linux IO 和 Unix PTY 测试 | [文本](evidence/r5-final-ubuntu.txt)、[JUnit](evidence/r5-final-ubuntu.xml) |
| 采集器定向 | 137 passed | [文本](evidence/r5-collectors-windows.txt) |
| 展示与集成定向 | 99 passed | [文本](evidence/r5-view-windows.txt) |
| 调度/IO 定向 | Windows 33 passed / 28 skipped；Ubuntu 61 passed / 0 skipped | [Windows](evidence/r5-monitor-io-windows.txt)、[Ubuntu](evidence/r5-monitor-io-ubuntu.txt)，同名 XML |
| 生产运行期定向 | 2 passed | [文本](evidence/r5-runtime-windows.txt)、[JUnit](evidence/r5-runtime-windows.xml) |
| 交付 wheel 离线安装独立复验 | 7 场景通过（缺配置、help、q、resize、Ctrl-C、SIGINT、SIGTERM）；14 项安装包几何检查通过；真实 proc/statvfs、受控 NVIDIA UUID 查询和 worker 回收通过，临时安装已清理 | [结果](evidence/r5-install/results.json)、[执行输出](evidence/r5-install/run.txt)，该子目录另含实际 PTY ANSI 输出 |
| 语法、差异及保留检查 | 42 个 Python 文件编译检查通过；git diff --check 通过；原测试 AST 与非测试输入哈希保留 | [汇总](evidence/r5-validation.json)、[差异检查](evidence/r5-diff-check.txt) |

Windows 全量命令在当前 worktree 执行，复用原目录本地依赖；关闭 pytest 缓存及字节码写入，并隔离字节码读取路径：

```powershell
$env:PYTHONPATH='D:\Documents\joi-observer\.pytest_cache\offline_deps'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPYCACHEPREFIX='D:\Documents\codex_worktree\dev-req002\joi-observer\.pytest_cache\r5-windows-pycache'
python -B -m pytest -p no:cacheprovider -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r5-final-windows.xml
git diff --check
```

Ubuntu 全量命令通过 `wsl -d Ubuntu-24.04 -- bash -lc` 执行：

```bash
cd /mnt/d/Documents/codex_worktree/dev-req002/joi-observer
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/home/shawn/projects/tmp/joi-observer-r5-pycache /home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B -m pytest -p no:cacheprovider -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r5-final-ubuntu.xml
```

安装复验先审阅并复用 [verify_r4_uv_install.py](evidence/verify_r4_uv_install.py)，使用 `--wheel` 指向已经交付的包；本轮未重新构建 wheel。脚本内部的 `uv --offline --no-python-downloads`、`--no-index --find-links`、全新临时安装/用户目录、新交互 shell 与异目录裸命令均实际执行，完整 argv 在安装结果的 commands 字段。输出放入独立 `r5-install/`，保留原 R4 证据。

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-002/evidence/verify_r4_uv_install.py \
  --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12 \
  --wheelhouse /mnt/d/Documents/joi-observer/.pytest_cache/offline_wheels \
  --wheel /mnt/d/Documents/codex_worktree/dev-req002/joi-observer/docs/dev-workflow/dev-0/REQ-002/evidence/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl \
  --output /mnt/d/Documents/codex_worktree/dev-req002/joi-observer/docs/dev-workflow/dev-0/REQ-002/evidence/r5-install/results.json \
  --out-dir /mnt/d/Documents/codex_worktree/dev-req002/joi-observer/docs/dev-workflow/dev-0/REQ-002/evidence/r5-install/wheels
```

wheel SHA-256：`ee77eb300a072d8639f963b05d6298c29ccf082ee99ac4afc7af680a0600b002`，与 R4 记录一致。包内 Python/YAML、安装文件、worker 与当前源码逐文件匹配；安装包 README 元数据一致。R4 的构建记录与目标环境声明仅作为交付来源引用，不宣称本轮重新构建或连接目标主机。

## 首次审查决策（已被二次复查取代）

本轮 AC-201～AC-207 的计划内范围、T-001～T-007 交付条件及必要回归满足，结果为 `passed`；无待 R4 修复的问题、无阻断验收的待澄清项。三项并行只读审查覆盖采集器/解析、调度/本地 IO、展示/状态链路，主审查覆盖生产接线、版本和安装证据；所有代码修改仅为补充测试。

剩余限制沿用已确定的设计和范围，不扩张为本轮完成声明：

- 未连接目标服务器；实际 NVIDIA 驱动/权限/输出、无卡返回码和真实部署挂载未现场核验。本地受控 NVIDIA 命令只证明离线协议、接线及生命周期。
- AC-205/206 本轮验收给定选择的显式关联高亮；实际方向键模型导航、完整双主题需 REQ-005/006 后续联验。Docker/vLLM 采集仍属于 REQ-003/004。
- mountinfo 前后身份核对不能保证观察到极短卸载恢复的 ABA 变化，仍采用设计已披露的非原子快照边界。

## 下一步

接收角色：**R0 / 用户**。请按 `stage=R5`、`result=passed` 接收 REQ-002 本轮交付及新 wheel/验证证据，由人工安排后续需求和部署环境验收。R5-002-001、R5-002-002、R5-002-003 均已关闭，无待 R4 回复事项。未自动推进其他角色对话、未提交代码、未连接服务器；旧清理清单未执行。
