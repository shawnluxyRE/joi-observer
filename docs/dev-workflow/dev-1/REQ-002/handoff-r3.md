# dev-1 / REQ-002 R3 交接

| 项目 | 当前值 |
| --- | --- |
| stage | R3 |
| result | ready |
| next_role | R4，由用户安排独立开发对话 |
| 修订 | v1.0，2026-11-19 |
| work_dir | `D:\Documents\joi-observer\docs\dev-workflow\dev-1` |
| req_dir | `D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-002` |
| 需求与输入 | [REQ-002 / AC-201～215、Q-013～014](../requirements.md#req-002-neon-grid-只读-web-看板与同机容器部署)，[R2 交接 v1.5](handoff-r2.md)，[REQ-001 验收](../REQ-001/handoff-r5.md) |

## 产物与结论

[概要开发计划 v1.0](plan.md) 覆盖从宿主快照到普通浏览器的完整链路、Neon Grid 的正式页面和同机容器发布。七项任务均已明确开工条件、集成顺序和验收入口。R2 的接口和黑盒足以支持实施，本轮没有待 R2 修订或待用户裁决的问题。

## 验证证据

R3 在 `947db0a` 加 R2 v1.5 工作区变更上，使用 WSL Ubuntu 24.04.5 x86_64、Python 3.12.3、Node 24.15.0 和 Chromium 156 复跑了以下用例。各组均在隔离网络命名空间执行，浏览器通过私有管道打开本地文件。[命令与结果](evidence/R3/baseline.txt)

| 本轮实际执行 | 结果 | R4 接手时的判定 |
| --- | --- | --- |
| Web Python，39 项 | 2 通过，37 失败 | 首屏静态结构和样例镜像 ID 对照通过。34 项停在 IPC、桥或 ASGI 占位，3 项报告缺少 Compose、Dockerfile 或包内资源声明。 |
| Chromium 与跨层，19 项 | 19 失败 | 15 项到达 DashboardBoot 占位，3 项未显示约定的启动失败提示，1 项在快照进入浏览器之前到达 ASGI 占位。 |
| Node，28 项 | 28 失败 | 26 项到达 LiveFeed.start 占位，2 项到达 HistoryWindowClock.rightEdge 占位。 |
| 既有日常宿主、IPC、TUI，24 项 | 24 通过 | 三模型原始样本、动态 GPU、名称与选择、完整帧原子替换及同 revision 心跳均保有回归起点。 |

R2 已用原稿核过曲线绘制判据，并用临时站点、Git 仓库和 Docker 命令替身演练发布及恢复。R4 仍需取得正式页面的两张整页截图、宿主到可见指标的通过结果，以及镜像与 Compose 的交付证据。实际镜像运行、宿主目录权限和内网端口可达性按现场条件单列。[R2 曲线与发布记录](handoff-r2.md#v15-采纳的两项简化) · [发布演练记录](evidence/R2/v15-deployment-witness.txt)

## 本轮决策

- 保留 R2 的首页加载顺序和三类列表各自的容量规则。复用原稿 `historyCurve(points)` 绘制连续有效段，以真实点位、断口和逐帧屏幕坐标判断曲线是否合格。[页面设计](../../../design/web-dashboard.md)
- 把既有发布脚本作为唯一文档化的发布入口。R4 补齐镜像配方、Compose、可部署的依赖锁与随包资源，更新 README 中的阶段说明，沿用已验证候选才切换 `current` 的规则。[部署设计](../../../design/web-deployment.md) · [README](../../../../README.md#同机-web-看板)
- 按 Q-014 选用日常样本与刚好越界的列表场景。宿主继续拥有唯一采集状态，页面选择、主题及订阅数只影响展示与传输。[需求决定](../requirements.md#已解决)

## 下一步

请由用户将本交接单交给 **R4**。R4 在独立主对话中按[计划](plan.md)组织实现及分工，可先并行推进快照桥、文档单流和容器声明，再将正式页面合入跨层用例。完成后在本需求目录提交 `handoff-r4.md`，列明通过结果、视觉对照与现场待验项。如发现影响任务依赖或验收的差异，请在该交接单的“R3 修订汇总”中注明对应任务和依据。
