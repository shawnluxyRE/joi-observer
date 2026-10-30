# dev-0 / REQ-002 R3 交接

- stage：R3
- result：ready
- work_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0\REQ-002`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-002 / AC-201～AC-207 及共同规则。
- 设计依据：[handoff-r2.md](handoff-r2.md) v1.0；hardware v1.0、monitor-state v1.6、configuration v1.2、application-shell v1.3，复用 error-logging v1.1 契约及 REQ-001 已验收实现。
- 分支与输入：`codex/dev-req002`，HEAD `a84f9d8b632544f1da005df37d7badc2c530d617` 加当前 R2 未提交产物。
- next_role：R4
- 修订：v1.0，2026-10-30；概要规划完成，无等待确认的开工事项。

## 产物

| 产物 | 版本与内容 |
| --- | --- |
| [plan.md](plan.md) | v1.0：七项任务覆盖本地 IO、Host/Storage、GPU、动态调度、纯控件/Frame、生产组合与离线交付；明确必要依赖、并行条件、共享文件集成和验证安排。 |
| 本交接 | v1.0：处理结论、核对与实测证据、R4 接收要求。 |
| [r3-validation.json](evidence/r3-validation.json) | Windows 本轮测试统计及 R2 的 37 个输入文件哈希复核；详细日志/JUnit 存本需求 evidence，沿用既有 Git 忽略规则。 |

本轮只新增计划、交接和本地验证证据，未修改需求、设计、业务源码、测试预期、用户 AGENTS.md 或原工作区，也未创建提交。

## 验证证据

| 类型 | 核对/执行结果 | 依据 |
| --- | --- | --- |
| R3 静态核对 | 需求、四份硬件测试、公开接口注释和共享设计一致，未发现需先交回 R2 的阻断问题；原始 IO 适配验证已明确纳入 R4。 | 计划 D1～D5、[R2 交接](handoff-r2.md)；两项并行只读复核分别检查设计依赖与测试契约。 |
| R3 输入版本复核 | R2 记录的 37 个设计/源码/测试 SHA-256 全部匹配，当前源码与测试未发生后续漂移。 | [r3-validation.json](evidence/r3-validation.json)、[R2 哈希](evidence/r2-validation.json)。 |
| R3 Windows 实际全量 | Python 3.12.10；567 项：350 passed / 202 failed / 15 Unix PTY skipped / 0 errors，9.05 秒。新增 203 项为 1 passed / 202 failed；原有 364 项为 349 passed / 15 skipped，无回归失败。 | [文本](evidence/r3-full-windows.txt)、[JUnit](evidence/r3-full-windows.xml)。 |
| 引用 R2 Ubuntu 结果 | 365 passed / 202 failed / 0 skipped/errors；R3 未重跑，不标为本轮实测。 | [test-baseline.json](test-baseline.json)、[R2 Ubuntu 报告](evidence/r2-full-ubuntu.txt)。 |
| 已验收依赖 | REQ-001 的需求 v1.12 公共基础已通过 R5 v1.4，不重开旧计划的 43 项历史差异。 | [REQ-001 R5 交接](../REQ-001/handoff-r5.md)。 |

Windows 实际命令（当前 worktree 根目录，使用已有本地依赖，无安装或联网）：

```powershell
$env:PYTHONPATH = 'D:\Documents\joi-observer\.pytest_cache\offline_deps'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m pytest -p no:cacheprovider -q --tb=no -rN --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r3-full-windows.xml
```

pytest 退出码 1 符合未实现基线，不代表业务验收通过。202 项失败仍对应 R2 的 197 项直接 NotImplementedError、2 项生命周期异常断言和 3 项 Frame/Runtime 未接线。真实 worker、进程回收、实现后的 Linux 全量/PTY/最终安装包均须由 R4 取得新证据，不能用本轮基线替代。

## 本轮决策

1. 在当前 worktree 的 REQ-002 目录维护产物，沿用 R2 的实际路径；不按 AGENTS.md 的原工作区路径另建一份计划。
2. 将本地 IO 取消与资源回收列为 T-001，建议尽早验证；采集业务、动态调度和纯控件可基于已声明端口并行，不必串行等待实际 IO。
3. 复用已验收 State、日志、配置和终端行为。动态来源的完整校验与全部资源清理是 Monitor 的必要增量；新旧 schema 的只读兼容继续保留，不能为新硬件接线删除旧断言。
4. 本轮 AC-205/206 覆盖给定选择后的正确高亮、未知清空与只读性；完整导航和双主题依设计留给 REQ-005/006，后续再做交互联验。
5. `hardware.py`、`monitor.py` 和 `widgets.py`/`layout.py` 的修改冲突及集成顺序写入计划；具体实现步骤与 subagents 分工留给 R4。
6. 目标驱动与部署现场尚未验证不阻止离线实现；本地 Linux 的真实 IO 生命周期验证则是本轮交付条件。全程禁止尝试连接服务器。

## R2 修订汇总

本轮无修订请求。现有设计、公开接口和黑盒测试足以支持七项任务开工；未发现需改变需求范围或验收含义的事项。R2 已披露的真实 LocalHardwareIO 验证缺口作为 T-001/T-007 的实施与验证工作处理，无需先退回补设计。

## 下一步

接收角色：**R4**。请人工在独立 R4 对话交付本文件及 [plan.md](plan.md) v1.0，按当前 worktree 和分支继续实现；保留现有 R2/用户改动，先核对离线环境并推进主要任务。实现后使新增业务测试全部通过、公共基础回归保持，通过本地 Linux IO/PTY/安装验证，在本目录更新 `handoff-r4.md` 后交 R5。

当前没有等待用户或 R2 确认的事项。R4 如发现影响任务范围、依赖或完成判定的问题，在其交接单“R3 修订汇总”记录原问题编号、证据和建议，再由人工交回 R3；具体编码组织由 R4 自行决定。本轮未自动启动其他角色对话或发送跨对话消息。
