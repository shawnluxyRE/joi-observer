# dev-0 / REQ-003 R3 交接

- stage：R3
- result：ready
- next_role：R4
- 修订：v1.0，2026-10-30
- project_root：`D:\Documents\codex_worktree\dev-req003\joi-observer`
- work_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0\REQ-003`
- 当前分支：`codex/dev-req003`，沿用用户指定的当前 worktree。
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-003 / AC-301～304 与共同规则。
- 设计依据：[handoff-r2.md](handoff-r2.md) v1.0、D-003-01～05；[Docker 设计](../../../design/docker.md) v1.0 及计划列明的公共模块契约。

## 产物与处理结论

已创建 `D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0\REQ-003\plan.md` v1.0，将开发划分为生命周期解析、本机命令、采集器/工厂、生产组合和离线验证交付五项任务，并明确并行修改冲突及最终集成条件。

核对需求、设计、接口注释及测试后，没有必须先退回 R2 的矛盾，也没有需用户决定的规划事项。REQ-003 只依赖已有 REQ-001，不等待其他具体采集器。ready 表示计划可交 R4，尚未实现的 Docker 功能和基线失败仍由 R4 处理。

本轮仅新增 [plan.md](plan.md) 与本交接单，不修改需求、R2 设计/骨架、源码、测试、依赖、AGENTS 或历史证据；保留当前未提交内容，不提交或切换分支。

## 验证证据

| 类别 | 本轮核对或引用结果 | 证据边界 |
| --- | --- | --- |
| 本轮材料审阅 | requirements v1.12；R2 v1.0；Docker v1.0、configuration v1.2、application-shell v1.3、monitor-state v1.6、错误日志契约；具体接口、生产空来源装配、三组新测试和公共复用点 | 当前业务缺口与目标契约可区分；旧文档阶段描述不代替当前源码/测试状态。 |
| 本轮独立只读审阅 | 对照身份、失败、关闭/取消、全量采集、可见前缀及生产组装，未发现阻断 R4 的设计冲突 | 只作为当前 R3 的审阅子任务，没有推进或联系其他角色聊天。 |
| 本轮测试加载 | 2026-10-30，本地 WSL Ubuntu-24.04，在 `/mnt/d/Documents/codex_worktree/dev-req003/joi-observer` 执行 `~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest --collect-only -q`；469 tests collected，退出码 0 | 只收集/加载，不执行业务断言；没有重跑全量、PTY、安装或实际 Docker。 |
| 引用 R2 基线 | 已读取 [pytest.xml](evidence/pytest.xml)，469 项，366 passed / 103 failed / 0 errors / 0 skipped；完整输出见 [pytest-full.txt](evidence/pytest-full.txt) | 原有 364 项通过；新增 105 项中 2 项通过、103 项为未实现入口/生产接入导致的失败。不是本轮重跑，不代表实际 Docker 已验证。 |
| 本轮文档检查 | 两份文档的 29 个本地文件链接、五项任务编号、状态及 `git diff --check` 通过；写入前已有的 53 个非忽略文件 SHA-256 全部未变 | 仅新增两份 R3 文档；文档检查不构成业务验收。 |

全程未尝试连接任何服务器、执行实际 Docker 命令或访问 Docker socket；未联网安装依赖。验证产物继续引用本地被忽略的 R2 evidence，没有改写该目录基线。

## 本轮决策

1. 采纳 R2 D-003-01～05，不改变本机 CLI、严格身份、生命周期/失败、端口所有权或清理预算。具体局部算法与执行分工由 R4 决定。
2. T-001/T-002 可独立并行，T-003/T-004 可依接口提前开发；三项任务同改 docker.py，需协调写入。最终链路按解析/命令、采集器、生产组合顺序集成验证，而不是把建议顺序都当作启动前置。
3. 不把当前 Docker 静态模板误认为完成采集。T-004 必须向唯一 Monitor 提供全部来源，保持唯一 State/Log、只读展示与全部对象的关闭生命周期。
4. 配置/布局/状态/调度/日志复用已有实现；通过新旧离线用例保护全量采集、隐藏失败、缩放恢复和退出行为。需要补的接合测试沿用已明确的契约，不更改验收含义。
5. R4 完成后同步 README 和本需求交接，保留 R2 原始失败基线。实际部署兼容性仍按 R2 的未验证事项记录，本轮不增加实机连接或联调授权。

## R2 修订汇总

本轮无新增修订请求。D-003-01～05 已纳入计划：01/05 对应 T-002，02/03 对应 T-001，04/05 对应 T-003，生产接入与验证对应 T-004/T-005。没有改变设计或黑盒预期，不要求 R2 重复确认既定结论。

## 下一步

接收角色 **R4**：请按 [plan.md](plan.md) v1.0，在当前 worktree 由一个主对话结合 subagents 安排实施，完成五项交付及离线验证，更新本需求 `handoff-r4.md` 后交 R5。优先明确同文件修改边界；保留现有 364 项行为，消除 103 项待实现失败，并核验生产实际采样与完整关闭。

如遇设计/接口/测试矛盾，向 R2 记录问题；如需调整任务依赖、范围或验证安排，通过 `handoff-r4.md` 的“R3 修订汇总”回交本对话。当前无等待确认事项；跨对话推进仍由用户指令发起，本轮未创建或通知 R4/R2 聊天。
