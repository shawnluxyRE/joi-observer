# dev-0 / REQ-001 R3 交接

- stage：R3
- result：ready
- next_role：R4
- 修订：v1.1，2026-10-30
- project_root：`D:\Documents\joi-observer`
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001`
- 需求依据：[requirements.md](../requirements.md) 与 [handoff-r1.md](../handoff-r1.md) v1.12，REQ-001 / AC-101～AC-114 及共同规则。
- 设计交付依据：[handoff-r2.md](handoff-r2.md) v1.5，R2-112-01～03；模块引用及验证安排见 [plan.md](plan.md) v1.1。
- 实施起点：[handoff-r4.md](handoff-r4.md) v1.3、[handoff-r5.md](handoff-r5.md) v1.3 对需求 v1.9 的已完成实现与验收。

## 产物与处理结论

已修订 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001\plan.md` 至 v1.1。保留 T-001～T-008 编号，重点更新配置、半页布局、数量分离集成和本地交付复验；状态、日志、调度及既有终端输入修复作为已完成成果复用。

核对需求、设计、目标接口注释和黑盒预期后，未发现必须先交回 R2 的冲突，也没有待用户决定的规划事项。当前 43 项失败属于旧实现尚未同步新契约，不是骨架未实现。`ready` 表示本轮增量计划可交 R4，不代表新数量/布局规则已经实现或验收；不推翻 R5 对旧 v1.9 的通过结论。

本轮修改范围仅为 `plan.md` 和本交接单，保留需求、R2/R4/R5 交接、实现代码、测试、锁文件及历史证据。

## 验证证据

| 类别 | 核对内容或结果 | 证据边界 |
| --- | --- | --- |
| 本轮材料核对 | 需求/R1 v1.12、AGENTS、R2 v1.5；configuration v1.1、monitor-state v1.5、application-shell v1.2、error-logging v1.1；当前实现、目标注释、相关测试及 R4/R5 交接 | 配置与布局的旧执行逻辑和新注释/断言差异已确认，不将它们误判为设计冲突。 |
| 本轮测试加载 | 2026-10-30，在项目根目录使用既有 `.pytest_cache/offline_deps`：`python -m pytest --collect-only -q`，退出码 0，327 tests collected | 只运行收集，未执行断言；本轮未重复全量测试、PTY 或安装。 |
| 本轮文档与范围校验 | 任务编号及 R3 ready / R4 状态核对；本地链接与格式检查、`git diff --check` 通过；除计划和本交接外，133 个源码、测试、设计、角色记录及证据文件的 SHA-256 均未变化 | 仅文档修订，不将静态检查表述为业务验收。 |
| 引用新 R2 基线 | [r2-v112-validation.json](evidence/r2-v112-validation.json)：2026-10-29 Windows 327 项，269 passed / 43 failed / 15 skipped / 0 errors；配置差异 15、布局及关联集成差异 28 | 引用 R2 实测，不是本轮重跑；15 项跳过是 Unix PTY 平台条件。43 项不得永久 skip/xfail。 |
| 引用旧版本通过 | [r5-recheck-results.json](evidence/r5-recheck-results.json)：Ubuntu 269 passed，Windows 254 passed / 15 skipped；R5 v1.3 再审沿用 v1.2 结果，R5-001/002 均已关闭 | 对应需求 v1.9，证明原公共基础与修复已完成，不代表 v1.12 已通过。 |
| 引用已有交付环境 | [r4-fix-uv-install-results.json](evidence/r4-fix-uv-install-results.json)、[r5-permissions.json](evidence/r5-permissions.json)；已有 `uv.lock`、离线依赖及 WSL uv 环境记录 | 本轮未重建安装；新布局与最终 wheel 由 T-008 重新验证，未改日志的独立权限结果可按范围引用。 |

两项只读并行审阅分别核对运行期/布局与配置/已有验收。最终复核已校正 T-006 的挂载表述：仅核对有效配置与展示槽，正式采集身份继续留给 REQ-002；并修复一处历史基线链接。没有需退回 R2 的契约矛盾，未通过这些子任务推进其他角色对话；全程未连接任何服务器。

## 本轮决策

1. 本轮是需求升级引起的增量工作。T-001/T-005 同步新契约，T-006 核验装配，T-007/T-008 补足新版本证据；T-002～T-004 及终端生命周期主要回归，不重复从零实现或重建锁文件。
2. 配置保留全部容器，显示只取容量内前缀；挂载仅纳入原前三项。前项失败不补位，缩放不改变来源或历史。具体采集器仍属 REQ-002～REQ-004，本轮用离线源验证。
3. 半页预算和新最低尺寸采用 D4；新增独立 `service_switch`，逐区域限制内容。Docker 超量隐藏和基础布局不足分开处理，零容量不画条目/空态，不增加更多标记或滚动功能。
4. 保留 R5-001 的整文档 YAML 构造与安全定位，覆盖真正忽略的第四挂载；保留 R5-002 的非阻塞输入及全部 15 项 PTY 用例。旧问题仍为已关闭，不重新编号或回退修复。
5. T-001 与 T-005 可并行；组合根审阅和验证脚本准备可提前。当前十容器联合用例直接构造 AppConfig，R4 还需结合真实加载/装配证据检查端到端对象集合。
6. 旧 PTY/安装脚本依赖容器数推导的尺寸预期必须更新；新报告标注 v1.12 和源码/产物版本，保留旧 JSON。无依赖变化不重新生成锁；换机离线依赖限制继续披露。

## R2 修订汇总

以下沿用 R2 已给出的编号，表示规划采纳情况；没有新增退回 R2 的请求。完整设计变更记录维护于 [handoff-r2.md 的 v1.5 修订](handoff-r2.md#v15-需求v112修订与当前验证)。

| 原编号 | R3 核对与处理 | 对应任务与状态 |
| --- | --- | --- |
| R2-112-01 | D1、config 注释与配置/安全边界预期一致。采纳前三挂载、完整容器校验和整文档 YAML 检查；现有解析循环需 R4 同步。 | T-001、T-006、T-007；规划已采纳，实现及验证待 R4。 |
| R2-112-02 | D4、Frame/容量目标注释及 TUI 用例一致。采纳半页、8 区、固定 Storage、Docker 余高/零容量和新最小尺寸。 | T-005、T-007、T-008；规划已采纳，实现及本地复验待 R4。 |
| R2-112-03 | D2 和十容器联合测试明确显示与来源分离。复用现有 Monitor/State/日志，核验隐藏对象采样、错误记录及扩大后最新快照。 | T-002～T-004 回归，T-006/T-007 接合；无需重设调度接口。 |

R4 旧交接没有需本轮处理的 R3 规划反馈；R5-001/R5-002 的修复与关闭结论分别由原 R4/R5 交接维护。部署/指标待核对事项继续引用 [R2 的范围与未验证事项](handoff-r2.md#范围与未验证事项)，不重复建立记录。

## 历史规划记录

v1.0（2026-10-28）依据需求 v1.9、R2 v1.4 形成八项任务并交 R4。该轮实际收集 167 项测试；引用的 R2 初版 [test-baseline.json](test-baseline.json) 为 2 passed / 165 failed，日志时间 [test-log-time-baseline.json](test-log-time-baseline.json) 为 1 passed / 21 failed，均属当时未实现骨架，不能继续用作当前基线。该轮两份文档 38 个本地链接、任务编号、状态及空白检查通过，`git diff --check` 通过。

v1.0 确定的公共基础范围、按现有接口并行、真实日志联合验证、终端先恢复和共享退出预算、uv 工具安装独立验收仍有效；这些工作后来由 R4/R5 完成。旧容器前五项、固定服务高度、Storage 吸收余高和 Docker 按条数贴合的安排已被需求 v1.12 与本版取代，不再作为实施依据。

## 下一步

接收角色为 **R4**。请按 [plan.md](plan.md) v1.1，在已有验收通过的实现上完成 R2-112-01～03，优先同步配置与布局，再执行加载/装配/全量采样的离线联合回归和新版本 PTY、uv 安装验证。交接时区分新证据、引用的旧证据及仍属后续需求的功能，不覆盖旧验收记录。

如发现接口/测试冲突，保留原问题编号，通过本需求 `handoff-r4.md` 的“R3 修订汇总”反馈。当前无等待确认事项；跨对话推进仍由用户发起，本轮未创建或通知 R4/R2 对话。
