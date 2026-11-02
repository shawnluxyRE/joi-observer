# dev-0 / REQ-003 R5 验收交接

- stage：R5
- result：passed
- 修订：v1.1，2026-10-30；复验关闭 R5-003-001，并完整复查 REQ-003 的代码与测试逻辑。
- project_root：`D:\Documents\codex_worktree\dev-req003\joi-observer`
- work_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0\REQ-003`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-003 / AC-301～304 与共同规则。
- 验收依据：[plan.md](plan.md) v1.0、[handoff-r2.md](handoff-r2.md) 的 D-003-01～05、[handoff-r4.md](handoff-r4.md) v1.1；[Docker 设计](../../../design/docker.md) v1.0，以及配置、Monitor/State、日志和应用外壳契约。
- 审查对象：`codex/dev-req003`，HEAD `a84f9d8b632544f1da005df37d7badc2c530d617` 加本轮全部未提交交付（含 untracked 文件），不是只审查 HEAD。
- next_role：R0

## 复验与完整复查（v1.1，当前结论）

**REQ-003 本轮离线验收通过，R5-003-001 已关闭。** 先独立确认原六项背压回归及真实本地子进程验证通过，再按用户要求复读整个 REQ-003 的实现与测试逻辑；未发现新的确定验收缺陷。此结论取代下文 v1.0 的 needs_fix，原失败证据和问题过程继续保留。

### 审查对象与修改边界

- HEAD 仍为 `a84f9d8b632544f1da005df37d7badc2c530d617`，分支仍为 `codex/dev-req003`；以当前完整未提交交付为对象。
- [r5-retest-start.json](evidence/r5-retest-start.json) 保存本次起始 SHA-256；与上轮 R5 最终快照比较，返修涉及 `collectors/docker.py`、`test_docker_command.py`、`handoff-r4.md`：[比较结果](evidence/r5-retest-repair-files.json)。R4 的 519 passed 属于引用证据，以下均为 R5 本轮实际执行。
- R5 本轮仅在 [test_docker_command.py](../../../../tests/test_docker_command.py) 末尾补充 `test_completed_failure_cleanup_allows_next_sample_on_same_command` 的 3 项参数化用例，验证同端口在超时、超限、调用方取消后完成清理并再次成功采样；同时更新本单。未改业务代码、设计、原有测试或其他交接单。
- 最终版本、JUnit 统计和文件修改范围见 [r5-retest-final-version.json](evidence/r5-retest-final-version.json)。原六项失败测试以及 R4 新增五项均保留，没有删除、跳过或削弱预期。

### 完整代码与测试逻辑复查

| 范围 | 复查结论 |
| --- | --- |
| 解析与身份，AC-301/302/303 | 全量复读 `parse_inspect`、`DockerCollector`、工厂及 101 项测试：严格单对象 JSON、身份精确匹配、七种生命周期、同名重建、完整 ID 改名/拒绝改绑、错误优先级与净化均符合契约。构造无 IO、每次重新查询、空配置和全量保序成立。[详细记录](evidence/r5-rereview-parse-review.txt)。 |
| 命令与清理，T-002 / D-003-05 | 复读整个适配器与 46 项命令测试；固定本机 argv、环境隔离、并发有界双流、超时、取消、close 和资源所有权均核对。修复关闭暂停管道后回收进程，再关闭父 transport；原始超限/取消语义保留。同端口恢复补测通过。 |
| 生产组合与配置，AC-301 | 核对 YAML 全量容器校验/保序、全部工厂项注册并实际采样、唯一 Monitor/State/Log、只读 reader、注入组件不重复创建、prepare 不采样。配置/CLI 测试的首帧替身只证明首帧，另有真实生产采样链路补足。 |
| 状态、日志、显示，AC-302～304 | 核对停止状态成功、受控 STALE/日志原因、失败保值与历史缺口、恢复清除 stale、日志限频、隐藏项持续采样、4→6→3 可见前缀、零容量/空配置、半页与顺序稳定。真实定时超时、同级隔离、q 退出与终端恢复覆盖完整。 |
| 测试逻辑与证据质量 | Docker 单元测试替身只提供原始响应/OS 行为，集成测试保留真实解析、采集、Monitor/State/Frame/Log；未用预设 CollectionResult 替代 REQ-003 被测业务。背压替身另有真实 Python 管道交叉验证，断言先于应急 finalizer，不能以测试清理制造成功。未发现用例削弱、错误预期或需要继续补漏的已确认风险。 |

检查过“清理本身发生额外故障后，Collector 是否再次转发 close”的候选：目前只有人工端口故障可触发，正常生产关闭只组织一次，真实背压/取消验证均已完整释放资源；既定契约未要求上层自动重试该额外故障，因此未将其扩大为验收阻碍，也未添加缺少明确契约依据的失败测试。

### R5 实际执行与证据

环境和运行目录与首轮相同：本地 WSL Ubuntu-24.04 / Python 3.12.3，`/mnt/d/Documents/codex_worktree/dev-req003/joi-observer`，现有虚拟环境 `~/projects/tmp/joi-observer-dev-0-venv/bin/python`。所有验证禁止真实 Docker/socket/服务器连接；真实进程仅为固定本地 Python helper。

```sh
# 修复复验：包含原六项背压回归及 R4 新增五项
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest tests/test_docker_command.py \
  -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-retest-command.xml
# 完整复查及新增 3 项恢复用例后的最终全量
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-retest-final.xml
# 真实暂停管道、旧故障诊断和原有本地进程场景，均逐项检查
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-003/evidence/r4-repair-process.py
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-003/evidence/r5-command-flood.py
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-003/evidence/verify_local_process.py
```

| 验证 | 本次结果 |
| --- | --- |
| 修复初验命令端口 | **43 passed，0.44 秒，exit 0**；原六项背压测试原样通过。[输出](evidence/r5-retest-command.txt)、[JUnit](evidence/r5-retest-command.xml)。 |
| 命令完整复查及补测 | **46 passed，0.44 秒，exit 0**。[输出](evidence/r5-rereview-command-tests.txt)、[JUnit](evidence/r5-rereview-command-tests.xml)。 |
| 解析/采集/工厂 | **101 passed，0.32 秒，exit 0**。[输出](evidence/r5-rereview-parse-tests.txt)、[JUnit](evidence/r5-rereview-parse-tests.xml)。 |
| 集成及相关配置/状态/日志/CLI/TUI 回归 | **360 passed，4.93 秒，exit 0**；相关模块清单可由 JUnit testcase classname 核对。[输出](evidence/r5-rereview-integration.txt)、[JUnit](evidence/r5-rereview-integration.xml)。 |
| 最终全量 | **522 passed / 0 failed / 0 errors / 0 skipped，9.23 秒，exit 0**；原 R4 519 项加本次 3 项，包含原有 15 项 Unix PTY。[输出](evidence/r5-retest-final.txt)、[JUnit](evidence/r5-retest-final.xml)。定向结果与全量重叠，不相加作为额外测试数量。 |
| 真实暂停管道 | stdout/stderr × 取消/close/超限后复用 **6/6 通过**；触发后释放约 0.635～1.117 ms，原始异常语义正确、两条管道与父 transport 关闭、进程已回收、无遗留任务，两个复用样本成功。[结果](evidence/r5-retest-process.json)、[空 stderr](evidence/r5-retest-process-stderr.txt)。 |
| 原大量输出诊断 | stdout/stderr × 65,537 字节 / 1 MiB / 8 MiB **6/6** 均为 DockerOutputLimitError、returncode=-9、transport_closed=true；逐项检查 JSON，不以脚本 exit 0 单独判定。[结果](evidence/r5-retest-flood.json)、[空 stderr](evidence/r5-retest-flood-stderr.txt)。已关闭 transport 中残余的 reader buffer/paused 属性不代表 OS 管道未关闭。 |
| 原有真实本地进程 | **7/7 通过**；恰好上限、超限、超时、取消和关闭均回归。[结果](evidence/r5-retest-local-process.json)、[空 stderr](evidence/r5-retest-local-process-stderr.txt)。 |
| 静态与修改边界 | compileall、git diff --check 及源码/契约未变核验见 [r5-retest-static-checks.txt](evidence/r5-retest-static-checks.txt)、[最终快照](evidence/r5-retest-final-version.json)。 |

当前无未关闭验收问题。限制保持为真实 Docker CLI/模板兼容性、socket 权限/错误文案及目标部署中的清理时限尚未实机验证；Python 3.12.3 的本地进程验证不扩展为其他运行时或部署环境的承诺。

## 首轮审查产物（v1.0，历史记录）

沿用 R2～R4 指定的当前 worktree，未写回 AGENTS 路径元数据中的原仓库。保留进入审查时的全部修改；业务代码、设计契约、原有测试预期均未修改，没有删除、skip 或 xfail 失败用例。

| 产物 | 本轮新增内容 |
| --- | --- |
| [test_docker.py](../../../../tests/test_docker.py) | 6 项：完整 ID 目标允许同 ID 改名但拒绝改绑到同名重建的新 ID；五类预期 IO 异常后继续采样并恢复。 |
| [test_docker_integration.py](../../../../tests/test_docker_integration.py) | 1 项：真实生产组合中的 Monitor 定时超时、单对象 STALE/日志、同级采样、自动恢复、再次在途时 q 退出和终端先恢复。 |
| [test_docker_command.py](../../../../tests/test_docker_command.py) | 6 项：stdout/stderr 背压下分别触发输出超限、调用方取消、close，要求保留错误/取消语义并完整释放管道与进程等待任务。全部保留为失败回归。 |
| 本交接单及 [evidence/](evidence/) | 验收映射、R4 修订请求、独立执行日志/JUnit、真实本地 Python 子进程诊断和版本快照。 |

合计新增 13 项测试。新增命令测试只替换 OS 进程端口，使用真实 asyncio StreamReader 的暂停/恢复阈值，并模拟子进程退出与管道断开的关系；测试 finally 主动释放替身资源，不以清理测试环境代替被测实现的清理断言。

## 首轮验证证据（v1.0，历史记录）

运行环境：本地 WSL `Ubuntu-24.04`，Python 3.12.3，内核 `6.18.33.2-microsoft-standard-WSL2`；复用 `~/projects/tmp/joi-observer-dev-0-venv/bin/python`。运行目录：`/mnt/d/Documents/codex_worktree/dev-req003/joi-observer`。

所有验证均为本轮 R5 实际执行，未连接服务器、执行真实 Docker 或访问 Docker socket，未联网安装依赖。真实子进程补证的唯一启动目标是当前虚拟环境 Python 和固定 helper；Docker argv 仅用于校验被测调用后替换 OS 边界。

### 比较基准与版本

- [r5-review-start.json](evidence/r5-review-start.json)：进入审查时 HEAD、分支、Git 状态及已跟踪/未跟踪交付文件 SHA-256。
- [r5-r4-snapshot-comparison.json](evidence/r5-r4-snapshot-comparison.json)：R4 归档的 47 个文件与 R5 起始快照全部相符；R4 的 501 passed 是引用基准，下表另列 R5 独立复跑。
- [r5-review-final.json](evidence/r5-review-final.json)：最终文件哈希、实际测试结果及相对起始快照的修改范围。R5 对已有文件的修改仅为上述三个测试文件。

### 实际运行与结果

```sh
# R5 起始独立回归（增补用例前）
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-baseline.xml

# 最终全量，包含本轮 13 项补测；失败用例不排除
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-final.xml

# 命令清理问题的最小回归范围
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest \
  tests/test_docker_command.py -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-command-tests.xml

# 已有 7 项本地进程场景与新增大量输出诊断
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-003/evidence/verify_local_process.py
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-003/evidence/r5-command-flood.py
```

| 验证 | R5 实际结果与证据 |
| --- | --- |
| 起始全量 | **501 passed，0 failed / errors / skipped，9.60 秒，exit 0**。[输出](evidence/r5-baseline.txt)、[JUnit](evidence/r5-baseline.xml)。 |
| 最终全量 | **508 passed / 6 failed / 0 errors / 0 skipped，11.88 秒，exit 1**。原有 501 项全部通过；新增 7 项通过、6 项命令背压测试失败，均归属同一问题 R5-003-001。包含原有 15 项 Unix PTY 测试。[输出](evidence/r5-final.txt)、[JUnit](evidence/r5-final.xml)。 |
| 解析、身份与采集器 | `python -m pytest tests/test_docker.py -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-parse-tests.xml`：101 passed，0.56 秒，exit 0。[输出](evidence/r5-parse-tests.txt)、[JUnit](evidence/r5-parse-tests.xml)。 |
| 生产集成 | `python -m pytest tests/test_docker_integration.py -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r5-integration.xml`：11 passed，0.80 秒，exit 0。[输出](evidence/r5-integration.txt)、[JUnit](evidence/r5-integration.xml)。新增定时用例为排查时序不确定性独立复跑 5 次，均通过：[记录](evidence/r5-integration-timing.txt)。 |
| 命令端口 | 32 passed / 6 failed，2.29 秒，exit 1；原 32 项全通过。[输出](evidence/r5-command-tests.txt)、[JUnit](evidence/r5-command-tests.xml)。 |
| 原有真实本地进程补证 | 复跑 R4 的 `verify_local_process.py`，7/7 场景通过；包括双流恰好上限、超限 1 字节、超时、取消、关闭。[R5 运行结果](evidence/r5-local-process.json)。这些通过不能证明大量输出的背压场景正确。 |
| 大量输出独立诊断 | [r5-command-flood.py](evidence/r5-command-flood.py) 以本地 Python 分别向 stdout/stderr 写 65,537 字节、1 MiB、8 MiB。[首次结果](evidence/r5-command-flood.json)及[主审独立复跑](evidence/r5-command-flood-independent.json)均复现背压下的 TimeoutError 和未关闭 transport。该脚本汇总结果后 exit 0，**不是验收通过信号**；具体失败断言见上述 6 项 pytest。 |
| 静态与修改边界 | `python -m compileall -q src tests`、`git diff --check` 结果见 [r5-static-checks.txt](evidence/r5-static-checks.txt)；源码/契约未改，详情见最终快照。 |

### 验收覆盖

| 范围 | 核对结果 |
| --- | --- |
| AC-301 | 配置/工厂的 1、5、6、10 项和更大列表完整保留；全部来源进入唯一 Monitor；精确名称/完整 ID、七种状态、同名重建和独立身份已覆盖。未发现缺陷。 |
| AC-302 | Exited/Dead 成功且不记错，受控 not_found/permission/unavailable/parse/timeout 经 State/Frame/Log 的原位 STALE、保值与净化行为已覆盖；但底层大量输出可能被错分为 timeout，见 R5-003-001。 |
| AC-303 | 名称重建、失败后恢复、真实 Monitor 超时后恢复及同级隔离均通过；背压下的底层关闭/取消资源回收不满足 D-003-05，见同一问题。 |
| AC-304 | 十项持续采样、4→6→3 可见前缀、隐藏失败与当前状态恢复、零配置/零容量、顺序与半页布局均通过。 |
| 共同规则/生产组合 | 唯一 State/Monitor/Log、注入组件不重复创建、构造/prepare 无采样、终端恢复、日志限频及原有回归通过；管道背压清理例外尚未修复。 |

## 首轮决策（v1.0，历史记录）

**首次验收未通过，v1.0 result=needs_fix；当前已由上文 v1.1 复验结论取代。** 当时发现一项已复现的 P2 验收缺陷 R5-003-001；6 个失败用例为同一根因的不同流/触发方式，不拆成多个问题。不以原有 501 项通过替代新增风险验证，也不改变用例预期隐藏失败。

代码修改仅限补充测试。R5 未修改业务代码或设计、未提交 Git、未切换分支、未向其他角色聊天发送消息或自动推进阶段。

## R4 修订汇总

### R5-003-001 [P2] 管道背压下清理超时、丢失管道资源并改变错误/取消语义

- 状态：**已关闭，2026-10-30 R5 复验通过**。以下保留首次缺陷的触发条件与旧实现行为，当前修复结果见本项末尾及上文 v1.1。
- 关联需求、验收或任务：REQ-003 的 AC-302/303；共同隔离/退出规则；T-002/T-005；Docker 设计“读取边界与实现取舍”“失败、恢复与取消”及 D-003-05（每流超限须终止并回收，取消/close 清理 250 ms，close 的 run 调用方收到 CancelledError）。
- 涉及位置：[docker.py](../../../../src/joi_observer/collectors/docker.py) `LocalDockerCommand._cleanup`，首轮旧版本第 245～258 行；回归入口为 [test_docker_command.py](../../../../tests/test_docker_command.py) 第 427 行开始的 `test_backpressured_pipe_is_released_before_command_cleanup_returns`。
- 触发条件：stdout 或 stderr 持续输出，asyncio StreamReader 缓冲区因背压暂停底层管道；此时触发输出超限、调用方取消或主动 close。真实本地 helper 已复现，是否触发取决于管道/子进程退出调度时序，不能按某一固定输出大小是否偶然通过判断修复。
- 预期行为：在清理预算内终止并回收进程，释放两条管道和读取/等待任务；超限仍抛 DockerOutputLimitError（采集失败分类为 parse/response.invalid），调用方取消或 close 仍向 run 调用方传播 CancelledError；后续 close 不依赖已丢失的资源引用。
- 实际行为：先取消全部 `_read_tasks`，再 kill 并 await `process.wait()`。管道已暂停且无人继续排空/关闭，子进程虽已终止，管道断开仍无法完成，等待被 250 ms 清理超时打断。finally 无条件清空 `_process/_spawn/_read_tasks`。超限和 close 场景的 run 改为 TimeoutError；显式取消虽保留 CancelledError，但回收/管道关闭未完成。
- 真实进程证据：失败样本返回 `returncode=-9`，但相应 reader 仍 paused、残余 buffer 196,607 字节、`transport_closed=false`，调用耗时约 268～271 ms。这里是**管道/transport 未完整释放**，不宣称子进程仍在运行；诊断 finally 显式关闭 transport，避免验证自身留下资源。
- 影响：超限被误记为 collection.timeout，主动关闭丢失约定取消语义，长时间运行或重复异常输出可能累积未释放的管道资源。此为既定适配契约的缺陷，不是界面或编码风格建议。
- 复现方法：运行上文命令端口 pytest，stdout/stderr × output_limit/cancel/close 六项全部失败；最终全量亦相同。真实 helper 诊断用于交叉证明替身所模拟的背压条件能在本地 OS 管道发生。
- 处理请求：在有界清理中同时处理子进程与暂停管道的生命周期，保留原始超限/取消语义；完整回收前不要无条件丢弃资源所有权。修复不得通过取消限量、无界读取、忽略失败或放宽原测试实现。请保持固定本机命令、环境隔离与其他采集器独立性。
- R4 回复与 R5 复验：已读取 handoff-r4.md v1.1。确认修复关闭暂停的读管道、等待回收后关闭父 transport，并在异常清理时保留原始超限/取消语义和资源所有权。R5 独立重跑原六项、完整命令测试、真实暂停管道/旧故障脚本，并完成全需求复查；最终 522 项全部通过，未发现新验收缺陷。**问题关闭**，原失败证据不覆盖。

## 待决事项

没有新增需求歧义或需要用户决策的范围问题。仍沿用已声明的验证限制：真实 Docker CLI/模板、socket 权限/错误文案、目标部署中的清理时限未验证；本地 Python 进程结果不能替代这些检查。禁止连接服务器的约束继续有效，这些外部验证不因交接自动获授权。

硬件/vLLM 采集、完整模型导航与双主题属于其他需求，不在本轮验收完成声明内。

## 下一步

接收角色 **R0 / 用户**：REQ-003 本轮离线验收通过，R5-003-001 已关闭，完整代码与测试逻辑复查完成。请据此协调后续阶段；本对话不自动发送跨角色消息、提交或合并代码。真实部署验证仍需另行授权，不能从本次通过结论推定已完成。
