# dev-0 / REQ-003 概要开发计划

- 项目：`D:\Documents\codex_worktree\dev-req003\joi-observer`
- 工作目录：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0`
- 需求目录：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0\REQ-003`
- 分支：`codex/dev-req003`；复用当前 worktree 及未提交的 R2 产物。
- 修订与状态：v1.0，2026-10-30；R3 ready，可交 R4 实施。
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-003 / AC-301～304 及共同规则；[AGENTS.md](../../../../AGENTS.md)。
- 设计交付：[handoff-r2.md](handoff-r2.md) v1.0，D-003-01～05；规划核对结论见 [handoff-r3.md](handoff-r3.md)。

## 设计、接口与测试依据

| 依据 | 主要接口及验证入口 |
| --- | --- |
| [docker.md](../../../design/docker.md) v1.0 | [collectors/docker.py](../../../../src/joi_observer/collectors/docker.py) 的解析、命令、采集器与工厂；[test_docker.py](../../../../tests/test_docker.py)、[test_docker_command.py](../../../../tests/test_docker_command.py)、[test_docker_integration.py](../../../../tests/test_docker_integration.py) |
| [configuration.md](../../../design/configuration.md) v1.2 | [ContainerConfig](../../../../src/joi_observer/config.py)；配置全量保留、稳定 id 与精确目标；配置及 CLI 测试 |
| [monitor-state.md](../../../design/monitor-state.md) v1.6、[error-logging.md](../../../design/error-logging.md) v1.1 | [Collector](../../../../src/joi_observer/collectors/base.py)、[Monitor](../../../../src/joi_observer/monitor.py)、[MonitorState](../../../../src/joi_observer/data/state.py)、[ErrorLog](../../../../src/joi_observer/error_log.py)；现有调度、状态、日志和联合测试 |
| [application-shell.md](../../../design/application-shell.md) v1.3 | [ApplicationRuntime](../../../../src/joi_observer/cli.py)、[compose_frame](../../../../src/joi_observer/tui/layout.py)；生产组合、可见前缀、半页布局与退出回归 |

## 范围与实施起点

本轮完成显式配置的本机 Docker 容器生命周期采集及生产接入，仅依赖已具备的 REQ-001 公共基础；REQ-002、REQ-004 以及完整导航/主题不构成前置任务。配置全量保留、可见前缀、空态、STALE、日志限频和状态历史已有实现，应复用这些行为。

待实现入口集中在 `collectors/docker.py`。`ApplicationRuntime` 已保存 `docker_command_factory`，但仍使用空来源 `Monitor(())`；R4 必须完成实际组装。根目录 README 的“Docker 尚未接入”描述应随完成状态更新。AGENTS 路径元数据沿用原仓库，本计划全部产物以当前 worktree 为准，保留已有修改。

本期不增加远端 Docker/context、rootless 自动发现、sudo、容器管理、健康检查展示或资源统计；不扩展 YAML 结构，不重做布局，不以 Docker 来源数量提高最小终端高度。禁止尝试连接任何服务器；开发及自动化验证使用离线端口和样本，不执行实际 Docker 命令或访问 Docker socket。

## 主要任务

前置依赖只记录启动所需条件；完成后的集成关系见下一节。各任务实现步骤和主对话/subagents 分工由 R4 确定。

| 任务编号与标题 | 交付结果、关联需求与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 生命周期与身份解析 | 原始命令响应产生正确 state 或受控 Failure；七种生命周期、名称/完整 ID、重建、误匹配及异常边界符合契约，原文不泄漏。对应 AC-301～303；通过 test_docker 的解析/错误用例。 | `collectors/docker.py::parse_inspect`；Docker 设计的身份、结果及失败约定，D-003-02/03。 | 无新增任务前置，现有值对象与错误目录已具备。 |
| T-002 有界本机命令执行 | 固定只读 inspect 与本机 socket、环境隔离、双流上限、超时、取消及幂等关闭可用；在途 run 按约定取消并完成回收，不干扰终端或其他来源。对应 AC-302/303 及共同隔离/退出规则；通过 test_docker_command。 | `LocalDockerCommand` 及必要内部结构；Docker 设计的读取边界与清理预算，D-003-01/05。 | 无新增任务前置，DockerCommandPort/CommandOutput 契约已具备。 |
| T-003 单对象采集与全量装配 | 每次采样查询当前目标，正确转换 IO 失败并传播取消；工厂保留全部配置顺序、不同 id 的同名目标和独立端口所有权，空列表不创建端口。对应 AC-301～304；通过 test_docker 的 collector/factory 用例。 | `DockerCollector`、`build_docker_collectors`；现有 Collector 协议、Docker 设计，D-003-04/05。 | 现有解析和命令接口契约已具备，可用离线端口开始开发。 |
| T-004 生产运行期接入 | 默认运行期注册全部 Docker spec 并实际调度全部采集器，共享唯一 State/Monitor/Log；构造及 prepare_log 不执行命令，注入 RuntimeComponents 时不另建采集器，退出清理完整。对应 AC-301～304；通过生产组合与首帧测试。 | `cli.py::ApplicationRuntime` 及相关接合测试；应用外壳与 Docker 生产组装设计。配置解析、布局、状态和日志以复用为主。 | 现有工厂与 RuntimeComponents 接口已具备，可先准备接入；无需等待其他需求。 |
| T-005 离线联验与交付说明 | 验证完整采集链路、隐藏项、失败恢复、响应性和回归；形成当前版本证据，更新 Docker 使用边界和实现状态，并完成 R4 交接。对应全部 AC-301～304；新旧测试均满足正确业务预期。 | `tests/test_docker*.py`、相关公共测试、README、本需求 evidence 与 handoff-r4；按已有契约补必要接合用例，不重定义验收。 | 最终联验需 T-001～T-004 已完成并集成；证据/文档准备可提前。 |

## 开发顺序与并行条件

1. 建议先开展 T-001 与 T-002；解析依赖原始字节，命令端口只负责 IO，两者可独立验证。T-003 可依既定接口并行开展；T-004 可提前核对生产装配和准备离线验证。
2. T-001～T-003 都修改 `collectors/docker.py`，逻辑可并行不等于可无协调地同时写入；R4 主对话应确定修改边界、集成顺序或串行写入。T-004 主要修改 cli.py，但与其他需求接入相同组合根存在冲突，集成时保留已有非 Docker 来源/槽位及共享对象。
3. T-003 的完成验证必须真实串联 T-001，命令行为由 T-002 的 OS 边界测试支撑；T-004 的采样与关闭验证须消费完成的 T-003。不能用预设 CollectionResult 或只注册未知模板替代生产采集。
4. 各部分定向验证通过后，进行 T-005 的生产链路、全量回归及交付核对。若出现设计/测试含义冲突，R4 记录问题交回相应角色，不为迁就实现降低断言。无需为本计划另建分支或 worktree。

## 验证安排

### 基线及运行位置

引用 [R2 完整输出](evidence/pytest-full.txt) 与 [JUnit 结果](evidence/pytest.xml)：469 项中 366 passed / 103 failed / 0 errors / 0 skipped；原有 364 项全通过，新增 105 项中 2 项声明测试通过。失败为待实现入口或生产接入缺失，不能永久 skip/xfail。本轮 R3 仅复核证据并执行收集：469 tests collected，退出码 0；没有重跑业务断言。

已可用的离线环境为本地 WSL Ubuntu-24.04，工作目录 `/mnt/d/Documents/codex_worktree/dev-req003/joi-observer`，Python 为 `~/projects/tmp/joi-observer-dev-0-venv/bin/python`。Windows 系统 Python 在 R2 阶段缺少 PyYAML，不能用该环境的 collection error 代表业务失败；优先复用已验证环境，不联网安装依赖。

```sh
# 定向验证
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest \
  tests/test_docker.py tests/test_docker_command.py tests/test_docker_integration.py
# 完成集成后的公共回归，包含本地 Unix PTY
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest
```

### 主要验收与接合检查

| 验证主题 | 完成判定及依据 |
| --- | --- |
| AC-301 全量与身份 | 1/5/6/10 项全部保留并采样，空项与较多项无固定截断；稳定 id、精确名称/完整 ID、同名重建与同目标不同 id 均按设计。工厂/解析用例加配置回归；生产组合验证所有来源确有更新。 |
| AC-302 状态与错误 | Exited/Dead 等合法状态成功且不记 ERROR；不存在、不可用、权限及解析/超时错误使用对应目录，行内仅 STALE、值/历史遵循公共契约。通过解析测试和真实 Monitor/State/Frame/Log 联验；对尚未覆盖的错误类别接合场景可按已有契约补测试。 |
| AC-303 恢复与隔离 | 失败后重新采样、Restarting/Running 恢复及名称重建无需重启 TUI；慢项不阻塞其他来源，取消不成为错误样本，资源关闭不影响同级采集器。保留底层双流/超限/取消和公共不重叠/退出预算测试。 |
| AC-304 可见性 | 十项在 4→6→3 行容量下只改变可见前缀，隐藏对象仍采样和记录真实失败；扩大后读取当前状态，失败不补位，无更多/分页标记。复用空配置、零容量、奇偶半页及区域稳定测试，不能只验证静态截图。 |
| 生产装配边界 | 命令工厂实际被使用、超时传递一致、构造/prepare_log 无采样；空配置不创建端口，注入组件不创建第二套来源。运行真实 ApplicationRuntime，替身仅隔离命令和终端；保留既有首帧 pending IO 测试，按需补上述未覆盖边界。 |
| 既有能力 | 全量回归配置/状态/调度/日志/CLI/TUI 与 15 项本地 PTY；保护原有 364 项行为和单一数据流。无关模块不重做；若更改公共关闭或日志路径，则定向核验受影响预算和静默规则。 |

命令端口测试仅替换 OS 创建端口；集成测试替换原始命令 IO，保留被测解析、采集、Monitor、State 与日志。继续保留真实进程/连接防护。若补充 OS 级进程清理证据，应使用可隔离的本地离线替身；不得调用实际 Docker 或示例服务地址。

### 交付判定与未验证边界

R4 交付应消除当前 103 项业务缺失失败、保留既有通过行为，并记录合理新增用例的实际数量，不以恢复固定总数代替验收。README 更新已接入能力、实际容器名称/完整 ID 的配置含义、固定本机 socket 和 Running 不代表健康；保持现有 YAML 格式。若构建安装产物，核对新 Docker 模块被打包且可离线导入，不因本轮增加不必要依赖。

新证据保存本需求 `evidence/`，使用可区分 R4 的文件名，记录源码/产物版本、环境、命令及实际结果，保留 R2 基线且继续 Git 忽略；更新 `handoff-r4.md` 后交 R5。真实 Docker CLI/模板兼容性、socket 权限/错误文案与真实部署中的清理时限仍未验证，须如实记录；本计划不自动安排服务器联调，也不把这些外部验证作为离线开发启动条件。

## 修订记录

- v1.0（2026-10-30）：采纳 R2 D-003-01～05，建立五项交付任务及集成顺序；明确全量采集/可见性分离、生产接入、离线验证和既有功能回归。当前无阻断开发的设计修订或待用户决定事项。
