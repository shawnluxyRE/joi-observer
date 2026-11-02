# dev-0 / REQ-003 R4 交接

- stage：R4
- result：ready
- 修订：v1.1，2026-10-30；处理 R5-003-001 返修。
- project_root：`D:\Documents\codex_worktree\dev-req003\joi-observer`
- work_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0\REQ-003`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-003 / AC-301～304 与共同规则。
- 计划依据：[plan.md](plan.md) v1.0；[handoff-r2.md](handoff-r2.md) v1.0、D-003-01～05。
- next_role：R5

## R5 返修回复（v1.1）

接收 [handoff-r5.md](handoff-r5.md) v1.0 的 R5-003-001。R4 已独立复现命令端口 6 项背压回归失败，原 32 项通过，2.40 秒；[输出](evidence/r4-repair-baseline.txt)、[JUnit](evidence/r4-repair-baseline.xml)。返修起始版本见 [r4-repair-start.json](evidence/r4-repair-start.json)。

**R5-003-001 已修复并完成 R4 验证，待 R5 复验关闭。** R5 的原 needs_fix 交接保持不变，不由 R4 代为宣告验收通过。下方 v1.0 产物和 501 项通过属于首次交付历史，本节记录返修后的实际版本。

### 问题确认与修复

- 根因确认：StreamReader 背压暂停管道后，旧实现取消读取任务再 kill/wait，导致管道 EOF/断开不能完成；250 ms 清理超时覆盖了原超限/主动关闭结果，并无条件丢弃资源引用。
- 修改 [docker.py](../../../../src/joi_observer/collectors/docker.py) 的 `LocalDockerCommand`：清理依次取消读任务、终止子进程、关闭 stdout/stderr 读取 transport、等待回收、关闭父 transport、收齐任务，成功后才释放引用。没有继续读取或积累超限输出，每流 65,536 字节上限和 250 ms 清理预算不变。
- Python `Process` 没有关闭读取管道的公开方法，因此将读取 transport 的内部访问集中到 `_close_read_pipes`，并注释该实现依赖。先回收再关闭父 transport，避免 asyncio debug 模式的运行中进程关闭警告；当前 Python 3.12.3 的真实进程与 debug 测试均验证通过。
- 清理故障不覆盖原始 `DockerOutputLimitError` / `CancelledError`，未完成资源继续由命令对象持有；后续并发 close 共享一次清理重试，未清理前不能启动新进程。补充修复内部任务已结束但 run 调用方尚未恢复时的 close 重试窗口，保留其[失败复现](evidence/r4-repair-command-retry-before.txt)。
- [test_docker_command.py](../../../../tests/test_docker_command.py) 新增 5 项：三类触发下保留原语义并重试清理、debug 静默与关闭顺序、已结束任务窗口的重试。原 R5 六项背压回归及其余用例未改预期、未删除或 skip/xfail。生产修改仅限 Docker 命令适配器，公共接口、设计、配置与依赖不变；无需 R2/R3 修订。

主对话和两个 subagents 在改动前核对既定设计/测试与问题可行性，全部确认无阻碍后实施；源码与命令测试由一人修改，独立 agent 验证真实暂停管道，主对话复核最终回归与证据。

### 返修验证证据

沿用本地 WSL Ubuntu-24.04 / Python 3.12.3，在 `/mnt/d/Documents/codex_worktree/dev-req003/joi-observer` 执行。没有服务器连接、真实 Docker、Docker socket 或网络安装；真实进程仅为当前 Python 的固定离线 helper。

```sh
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest \
  tests/test_docker_command.py -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r4-repair-command-final.xml
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r4-repair-final.xml
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-003/evidence/r5-command-flood.py
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-003/evidence/r4-repair-process.py
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-003/evidence/verify_local_process.py
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m compileall -q src tests
git diff --check
```

| 验证 | 返修实际结果 |
| --- | --- |
| R5 六项最小回归 | `pytest tests/test_docker_command.py -q -k backpressured`：**6 passed / 36 deselected**，原样通过；[输出](evidence/r4-repair-command-r5-six.txt)、[JUnit](evidence/r4-repair-command-r5-six.xml)。最终全量也包含这六项。 |
| 命令端口完整回归 | **43 passed**（R5 的 38 项 + 本次 5 项）；[输出](evidence/r4-repair-command-final.txt)、[JUnit](evidence/r4-repair-command-final.xml)。 |
| 最终全量 | **519 passed / 0 failed / 0 errors / 0 skipped，9.57 秒，exit 0**；含原有 364 项、Docker 155 项（101 解析/采集、43 命令、11 集成）及原有 15 项 Unix PTY。R5 新增 13 项全部保留并通过。[输出](evidence/r4-repair-final.txt)、[JUnit](evidence/r4-repair-final.xml)。修复重试窗口前的 518 项通过另存为[中间证据](evidence/r4-repair-intermediate.txt)，不冒充最终版本。 |
| 原 R5 大量输出诊断 | 原脚本未改，stdout/stderr × 65,537 字节 / 1 MiB / 8 MiB 共 **6/6** 均为 `DockerOutputLimitError`、returncode=-9、transport_closed=true；逐项检查结果，不以脚本 exit 0 代替通过。[最终结果](evidence/r4-repair-flood-final.json)，[stderr 为空](evidence/r4-repair-flood-final-stderr.txt)。 |
| 真实暂停管道与复用 | 新增 [r4-repair-process.py](evidence/r4-repair-process.py) 在 OS 创建边界观察真实 paused 状态后触发取消/close/超限，两个流共 **6/6** 通过；原始异常语义正确，触发后清理约 **0.747～1.550 ms**，两管道与父 transport 已关闭、进程回收、无遗留任务；两次同端口后续有效样本均成功。[最终结果](evidence/r4-repair-process-final.json)，[stderr 为空](evidence/r4-repair-process-final-stderr.txt)。诊断保留的 reader paused/buffer 值不是未关闭资源的证据，断言基于实际管道关闭、回收与任务状态，且先于应急 finalizer 执行。 |
| 原有真实本地进程场景 | 原 `verify_local_process.py` 的 **7/7** 场景复跑通过；[最终结果](evidence/r4-repair-local-process-final.json)，[stderr 为空](evidence/r4-repair-local-process-final-stderr.txt)。 |
| 静态与版本 | compileall 与 git diff --check 均 exit 0；最终源码/测试/脚本 SHA-256、JUnit 统计及修改边界见 [r4-repair-version.json](evidence/r4-repair-version.json)。R4 v1.0、R5 和返修前失败证据均保留；证据继续按现有规则被 Git 忽略。 |

验证边界保持不变：以上证明本地离线与真实 Python 子进程场景，不能替代真实 Docker CLI/模板、socket 权限、错误文案和部署中的清理时限验证。本次没有未解决的 R4 修复阻碍。

## 首次交付产物（v1.0）

本轮复用 `codex/dev-req003` worktree，起始 HEAD 为 `a84f9d8b632544f1da005df37d7badc2c530d617`。保留进入 R4 时的所有未提交 R2/R3/用户修改，不写回 AGENTS 元数据中的原仓库。

| 任务 | 状态与范围 |
| --- | --- |
| T-001 / T-003 | 完成；[docker.py](../../../../src/joi_observer/collectors/docker.py) 实现严格 UTF-8/JSON、重复键/字段/生命周期验证、精确名称/完整 ID 匹配、固定错误目录、每次重新查询及全部配置独立装配。[test_docker.py](../../../../tests/test_docker.py) 共 95 项，新增 12 项解析边界。 |
| T-002 | 完成；同一模块实现固定本机 inspect、子进程环境隔离、并发有限双流读取、超时、取消回收和幂等 close。[test_docker_command.py](../../../../tests/test_docker_command.py) 共 32 项，新增 13 项；关闭取消与回收同时完成的竞态已修复并回归。 |
| T-004 | 完成；[cli.py](../../../../src/joi_observer/cli.py) 用全部采集器 spec 注册状态并交给唯一 Monitor，保留 host/vLLM 槽位及组件注入；构造和 prepare_log 不执行命令，空配置不创建端口。 |
| T-005 | 完成；[test_docker_integration.py](../../../../tests/test_docker_integration.py) 共 10 项，新增 7 项，覆盖错误分类/保值/恢复与生产组装边界；[README](../../../../README.md) 更新 Docker 使用和实现状态；全部离线回归通过。 |

本轮新增 32 项测试，未删除、skip、xfail 或放宽 R2 既有断言。未改公共 Monitor/State/Log/布局算法、YAML 结构或依赖。R2/R3 文档保留各自阶段记录，当前实现及验证状态以本单与 README 为准。

## 首次交付验证证据（v1.0）

全部验证未运行真实 Docker、访问 Docker socket 或连接服务器；复用本地 WSL Ubuntu-24.04 与现成虚拟环境，不联网安装依赖。Python 3.12.3；内核 `6.18.33.2-microsoft-standard-WSL2`。命令端口测试替换进程创建边界，集成测试只替换外部命令和终端，保留真实解析/采集/调度/状态/日志。

运行目录：`/mnt/d/Documents/codex_worktree/dev-req003/joi-observer`。

```sh
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r4-baseline.xml
```

实际基线：469 项，366 passed / 103 failed，14.04 秒，exit 1；与 R2 结果一致，失败为待实现业务/接入，无加载错误。输出：[r4-baseline.txt](evidence/r4-baseline.txt)，[r4-baseline.xml](evidence/r4-baseline.xml)。后续实现结果另行记录，不覆盖此基线。

最终在同一目录执行：

```sh
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/r4-final.xml
PYTHONPATH=src ~/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-003/evidence/verify_local_process.py
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m compileall -q src tests
git diff --check
```

| 验证 | 实际结果与证据 |
| --- | --- |
| 最终全量 | **501 passed / 0 failed / 0 errors / 0 skipped，10.02 秒，exit 0**；包含原有 364 项和当前 Docker 137 项，原有 15 项本地 Unix PTY 均通过。[完整输出](evidence/r4-final.txt)、[JUnit](evidence/r4-final.xml)。 |
| 解析/采集及完整链路定向 | `python -m pytest tests/test_docker.py tests/test_docker_integration.py -q`：105 passed；[输出](evidence/r4-parse-tests.txt)。 |
| 命令端口定向 | `python -m pytest tests/test_docker_command.py -q`：32 passed；[输出](evidence/r4-command-final.txt)。包含创建时取消竞争、启动异常后复用、并发 cancel/close、close 自身取消、双流超限与回收。 |
| 生产组合、CLI/外壳定向 | `python -m pytest tests/test_docker_integration.py tests/test_cli.py tests/test_shell_edges.py -q`：43 passed；[输出](evidence/r4-runtime-pytest.txt)。 |
| 真实本机子进程补证 | [verify_local_process.py](evidence/verify_local_process.py) 将唯一 OS 创建边界转为本地 Python helper，**7/7 场景通过**。真实管道/kill/wait 覆盖双流各恰好上限、各自超限、超时、取消、关闭及取消并发双 close；返回后均已回收、无剩余任务。[结果](evidence/r4-local-process.json)。最终取消/关闭耗时约 0.20～0.29 ms，50 ms 超时场景实际 51.71 ms；仅证明当前 WSL helper 场景，不代表 Docker 部署时限。 |
| 语法与差异 | `compileall -q src tests`、`git diff --check` 均 exit 0；无新增依赖、未构建 wheel 或重新安装工具。 |
| 版本与证据归档 | 起始 HEAD 如上；验证时源码、测试、契约及计划 SHA-256 和 Git 状态见 [r4-version.json](evidence/r4-version.json)。所有证据位于本需求 `evidence/`，仍被原 `.gitignore` 忽略；R2 基线保留，不改写为新通过。 |

验收映射：AC-301 的 1/5/6/10 项和更多项保留、精确身份、全量采样由配置/工厂/生产测试验证；AC-302 的 Exited 无错误以及 not_found/unavailable/permission/parse/timeout 完整 STALE/日志链路已覆盖；AC-303 的同名重建、Restarting/Running 恢复、慢项隔离与取消已覆盖；AC-304 的十项持续采样、4→6→3 可见前缀、隐藏故障/恢复、空配置与零容量使用既有布局加新真实采集链路验证。

## 本轮决策

- 主对话组织三个 subagents 完成 T-001～T-005 的开发前检查并汇总跨任务一致性；全部确认可行后才进入实现。没有阻断设计/计划问题。
- `docker.py` 由命令端口与解析/采集任务串行写入；`cli.py` 与不同测试文件可并行修改。保持 R2 公共接口、YAML、Monitor/State/Log 与布局契约。
- 增补测试仅覆盖既定契约中的解析、进程取消与生产组合边界，不降低原验收含义。
- 主对话补充真实本地 Python 子进程证据，并由另一 subagent 只读核对生产组合接缝；未发现未解决的验收阻碍。
- R4-FIX-001：审阅发现 close 调用方取消与内部回收在同一事件循环轮次完成时，使用内部任务 done 状态区分取消来源可能吞掉外部取消。[补测先复现失败](evidence/r4-command-race-before.txt)，随后用当前调用任务的取消请求计数区分，32 项命令测试及最终 501 项均通过；未改变接口或设计。

## R3 / R2 修订结论

无待 R3 调整的计划问题，无待 R2 澄清的设计或既有测试错误。新增解析测试在开发时修正了自身过深嵌套样本：契约未指定 JSON 深度上限，因此不要求合法嵌套必然失败；改用深层未闭合输入验证受控解析失败，未修改原有验收。

## 未验证边界

真实 Docker CLI/模板兼容性、socket 权限与错误文案、目标部署中的进程清理时限仍未验证；本地 Python 子进程结果不能替代这些检查。没有新增服务器联调授权。硬件/vLLM 采集、完整导航/双主题仍在其他需求范围，不以本轮通过宣称其完成。

## 下一步

接收角色 **R5**：请基于当前 worktree、本单 v1.1 与返修最终证据，复验 **R5-003-001** 的六项背压回归、清理错误/取消语义、真实进程释放和全量回归，再在 `handoff-r5.md` 更新问题状态与验收结论。R4 当前为 ready，表示修复可交复验，不表示 R5 已验收。由人工推进下一阶段，本轮未向其他角色聊天发消息、未创建独立聊天、未提交或切换分支。
