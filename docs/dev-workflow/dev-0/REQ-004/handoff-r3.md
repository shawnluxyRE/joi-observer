# dev-0 / REQ-004 R3 交接

- stage：R3
- result：ready
- next_role：R4
- 修订：v1.0，2026-11-02
- project_root：`D:\Documents\codex_worktree\dev0-req004\joi-observer`
- work_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0\REQ-004`
- 分支：`codex/dev0-req004`；复用当前 worktree 和未提交的 R2 交付。
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-004 / AC-401～412、D-001 及共同规则。
- 设计依据：[handoff-r2.md](handoff-r2.md) v1.3、[vllm.md](../../../design/vllm.md) v1.2、[metric-evidence.md](metric-evidence.md) 与 [view-contract.md](view-contract.md) v1.0，以及计划列明的共享模块契约。

## 产物与处理结论

已创建 [plan.md](plan.md) v1.0，实际路径为 `D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0\REQ-004\plan.md`。

计划分为八项：三类型解析、有界 HTTP 与依赖、配置/采集器、窗口数学、模型状态、服务区展示、统一运行期接入、离线联验交付。列明启动条件、同文件写入冲突、真实链路集成顺序及 AC-401～412 验证安排；局部实现与 subagents 分工交给 R4。

需求、设计、公共接口注释与黑盒测试足以支持实施，未发现必须先退回 R2 的冲突。D-001 已有依据，不需要重新采证或改变三类型指标范围。ready 仅表示 R3 规划可交接，不表示业务实现完成或测试全绿。

本轮只新增两份 R3 文档，保留已有未提交修改；没有修改需求、R2 产物、源码、测试、依赖或 AGENTS，没有创建提交或切换分支。

## 验证证据

| 类别 | 本轮核对或引用结果 | 证据边界 |
| --- | --- | --- |
| 材料审阅 | 核对需求共同规则与 REQ-004、R2 交接、指标证据/视图契约、相关共享设计、接口和七组 vLLM 测试 | 三个并行只读审阅子任务分别复核采集/配置、状态/展示、生产接入/验证条件；均属本轮 R3，没有推进其他角色聊天。 |
| 当前实现缺口 | parser/HTTP/collector/factory、window/accumulator/view 为未实现入口；配置新字段、State 派生专支、生产组合和整页绘制缺少接线 | 与 R2 失败分类一致，纳入 T-001～T-007，不当作 R2 设计缺陷。 |
| R3 测试加载 | 本地 WSL Ubuntu-24.04，Python 3.12.3；当前 worktree 执行 `~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest --collect-only -q`，1209 tests collected，退出码 0 | 只加载/收集，不执行业务断言；不把此结果当作 1209 项通过。 |
| 引用 R2 全量结果 | 已读 [pytest-consolidated.xml](evidence/pytest-consolidated.xml)：1209 项，894 passed / 315 failed，0 errors / 0 skipped；[完整输出](evidence/pytest-consolidated.txt) 与 R2 v1.3 提供分类 | 862 项通用/既有非 vLLM 专项通过；vLLM 32 通过、315 待实现失败。这是 R2 的执行结果，本轮未重跑全量、PTY 或安装。 |
| 本地依赖盘点 | `/home/shawn/projects/tmp/joi-observer-dev-0-venv/lib/python3.12/site-packages` 和 `D:\Documents\joi-observer\.pytest_cache\offline_wheels` 未见 HTTPX/httpcore/anyio/certifi/idna/h11；WSL `/home/shawn/.local/bin/uv` 可用 | 只读目录检查，未安装/联网；仅说明所检查环境与目录，不断言其他本地缓存也不存在。真实后端及安装验证需先补齐依赖。 |
| 文档与改动范围检查 | 两份文档 40 个本地链接均有效，八项任务及交接状态一致；`git diff --check` 通过；写入前记录的 111 个非忽略文件 SHA-256 全部保持 | 只新增 plan.md 和 handoff-r3.md；文档检查不构成业务验收。 |

全程没有尝试连接任何服务器，没有运行采证脚本、真实 Docker/vLLM 或安装包；采证事实与源码定义继续引用 R2，未重新执行归档源码。R3 不宣称完成真实 HTTPX、TLS 握手、服务负载、多 engine 或重启演练。

## 本轮决策

1. 沿用当前 worktree 的真实路径；AGENTS 中原仓库路径不作为写入第二份计划的目标。保留公共结果兄弟子类和 Chat/Pooling 观测分型，不另行重构已确认接口。
2. T-001/T-004/T-006 可独立开发，其余任务可依既定接口提前开始。解析、HTTP、采集器共用 `collectors/vllm.py`，需 R4 协调写入；最终按 parser/端口→collector、window→accumulator/State→运行期→整页联合验证。
3. State 依据 spec/结果类型分派，公共无载荷失败保留通用语义；独立业务组基线不能被对象级标志替代。任何实际 failure 记整点历史 gap，合法大计数的派生溢出仅隔离对应速率。T-005 必须保护硬件/Docker 普通路径。
4. T-006 只读消费选中模型及冻结快照，完成当前服务区必要状态/颜色和历史显示；方向键、完整主题仍属 REQ-005/006，不成为本轮前置或交付宣称。
5. 当前真实 HTTPX 离线材料缺项属于 T-002/T-008 的验证准备条件，不是需 R2 改设计的问题。R4 可以继续其余任务；真实库检查与最终安装尚不能标完成。依赖声明、锁文件和完整离线 wheel 集合必须成套更新。
6. 保留禁止所有服务器连接的约束。真实 HTTPX 接合使用内存传输边界，区分可验证的解压/取消/关闭、TLS 配置/错误归一与尚未执行的真实网络握手；不把 fake client 用例当作完整后端证据。

## R2 修订汇总

本轮无新增修订请求，无需 R2 重复确认。D-001 的固定 profile、seq 单位、STOP 完成量、独立延迟分母与不可见重启边界已纳入 T-001/004/005/008；服务窗口契约纳入 T-006。现有待实现失败应由 R4 实现后验证，不通过改写需求或降低测试断言处理。

## 执行条件与未验证事项

唯一已发现的环境准备缺项是 HTTPX 及其传递依赖未在所检查离线环境中备齐。R4 先盘点其他本地包/缓存；仍缺时记录具体缺项，请求提供离线材料，期间继续不依赖这些材料的工作。不得自行联网获取，也不得省略真实库/安装验证后宣告整个 REQ-004 完成。

前序安装工具位于其他 worktree 的忽略目录，当前 worktree 没有对应旧脚本。已确认可供参考的修订版实际位于 `D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0\REQ-002\evidence\r4-fix2-install\verify_uv_install.py`，同目录有 `_owned_supervisor.py`；复用时需适配本次源码、依赖与新证据目录。旧验收结果不代替本轮验证。

当前没有等待用户改变范围、指标口径或 R2 补齐契约的事项；上述材料准备只约束相关任务完成点，不阻塞计划交接。

## 下一步

接收角色 **R4**：请按 [plan.md](plan.md) v1.0，在当前 worktree 由一个主对话结合 subagents 实施八项交付；优先确认离线依赖条件和同文件修改边界，保留现有通过行为，完成新旧测试、真实库及 Ubuntu 离线接合验证。更新本需求 `handoff-r4.md` 后请求 R5 验收。

如发现设计/接口/测试矛盾，记录问题交回 R2；如需调整规划，在 R4 交接的“R3 修订汇总”保留问题编号、证据及调整请求，人工交回本对话。跨对话推进由用户发起，本轮未创建或通知 R4/R2 聊天。
