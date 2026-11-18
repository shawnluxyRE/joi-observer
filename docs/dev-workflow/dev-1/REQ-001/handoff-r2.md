# dev-1 / REQ-001 R2 交接

- stage：R2
- result：ready
- 修订：v1.3，2026-11-16；按最新 R2 技能补充图前类/对象简介、合并别名并核对职责。
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-1`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-001`
- 需求依据：[requirements.md](../requirements.md) v1.3，REQ-001 / AC-101～114；R1 分析历史见 [handoff-r1.md](../handoff-r1.md)。
- 问题来源：用户直接复查及确认，以及 2026-11-16 要求按更新技能修订；不是 R3/R4 修订。
- next_role：R3

R2-REV-001～006 已落实到整体/模块设计和黑盒，本轮仅补充说明性简介，不改变接口、业务契约或验收预期。ready 表示设计文档可引用；REQ-001 已有 R3 规划并进入 R4 实施，当前实现与验证进展见 [R4 交接](handoff-r4.md)。本文保留的业务测试数字是先前 R2 交接时点的引用，不代表当前代码仍为骨架或仍有相同失败。

## 本轮处理结论

本次按新技能在 13 份模块文档首图前集中介绍类图和时序图的全部类/对象，一项一句职责；对象别名与本类合并，模块、函数、文件、线程及字节流明确标为角色。整体设计按用户要求恢复组件图后的“组件职责与模块索引”，不增加逐个类或对象介绍。13 份模块文档共 91 项介绍，未新增业务决定。

新增 [整体设计](../../../design/architecture.md)，集中说明组件/进程边界和模块依赖；13 份模块文档各有简化核心类图和关键时序图，均引用整体设计。具体接口、协议、时间及故障规则由模块文档维护，避免在交接中重复展开。

此前确认的完整快照分批字节流、取消 8 MiB 总量限制、状态驱动发布/空闲心跳、生产采样 1～60 秒、整数保真和原测试验证意图均保留。本轮复查新增三项处理：

- R2-REV-004：补 SnapshotPublisher.start()，绑定成功后才启动 Monitor；启动入口与直接 run 的监听所有权明确，避免双绑定和失败前采样。
- R2-REV-005：新读者不能将超过现有五秒发布年龄的缓存当首帧；等待下一正常发布包含在原首帧预算，不追加 source/采样，也不重连。
- R2-REV-006：补 state revision/published_at 倒退失败及同 revision 心跳仍替换过期历史的黑盒。

本轮 [设计复查记录](review-r2-20261116.md) 给出发现、处理及验证边界；原 [首版复查](review-r2.md) 保留原问题编号和用户确认背景。本轮未发现新的阻塞设计问题；业务、worker 容量/取消和系统适配验证仍由 R4 完成。

## 产物

| 产物 | 当前内容 |
| --- | --- |
| [整体设计](../../../design/architecture.md) v1.2 | 组件图、进程边界、模块索引及实现/验证边界 |
| [IPC](../../../design/ipc.md) v1.3 | 完整字节流、分批 IO、整数 tag、更新/心跳、时间及故障隔离 |
| [常驻服务](../../../design/collector-service.md) v1.3 | 通知接线、运行期所有权、锁/权限、发布失败后继续采样、取消及 systemd 模板 |
| [TUI 客户端](../../../design/tui-client.md) v1.3 | 缓存原子替换、受控解码、终端恢复、无重连与黑盒分工 |
| [配置](../../../design/configuration.md)、[应用外壳](../../../design/application-shell.md)、[状态](../../../design/monitor-state.md) v2.3 | 补图前类/对象简介，保留配置/状态/呈现契约 |
| [硬件](../../../design/hardware.md)、[导航](../../../design/navigation.md)、[vLLM](../../../design/vllm.md)、[错误日志](../../../design/error-logging.md) | 沿用原业务设计；更新所有权/名称及采样说明 |
| [Web 边界](../../../design/web.md) v0.3 | 仅固定 REQ-001 共享输入；REQ-002 页面/容器仍需独立设计 |
| `src/joi_observer/ipc/{protocol,client,server}.py` | 冻结值、流协议/worker/接收发布端口及待实现入口 |
| `src/joi_observer/{runtime,service}.py` | CollectorComponents 含更新事件；CollectorRuntime.wait_updated；服务故障隔离与实例锁骨架 |
| `src/joi_observer/tui/session.py`、`cli.py` | 客户端编排和 run_command 分派骨架；原入口仍待迁移 |
| `config.py`、`monitor.py`、`data/state.py`、`examples/config.yaml` | 同步公开契约/注释和示例。R2 没有实施采样下限解析逻辑；R4 必须分别校验两个时间字段 |
| `deploy/systemd/joi-observer.service`、`AGENTS.md` | 声明性部署模板及模块索引，未安装启动 |
| [本轮复查](review-r2-20261116.md)、[先前复查](review-r2.md)、[测试迁移](test-migration.md) | 保留问题编号、处理结论、验证边界和原测试验证意图映射 |

## 黑盒与验收覆盖

| 测试入口 | 覆盖 |
| --- | --- |
| `test_ipc_protocol.py`（58 项） | 独立 wire fixture、脱敏/身份/顺序/GPU 关联、单位/未知/N/A/缺口、畸形帧、整数 tag、极大整数、超过原 8 MiB 的完整快照；AC-104/107/109/110/113/114 |
| `test_ipc_client.py`（17 项） | 首帧、分批接收后原子替换、缓存无 IO、不可变旧值、期限、EOF、身份变化、无重连、手动新对象恢复、大长度不预分配、时间/revision 倒退及同 revision 心跳；AC-105/107/108/109/112 |
| `test_service_contract.py`（22 项） | 无客户端采集、多读者、拒绝命令、慢读隔离、状态通知/心跳、分批写大快照、发布故障仍采样、配置冻结、重启、锁与日志降级、监听启动屏障及过期首帧缓存；AC-101/102/103/107/108/110/111/113 |
| `test_client_session.py`（4 项）、`test_client_cli_contract.py`（12 项） | 终端恢复、q/主题响应、会话隔离、默认客户端不读配置、参数迁移及安全错误；AC-102/103/105/106/112 |
| `test_display_metadata_view.py`（5 项） | 列表/详情、回退、长标题、同名独立 id 与真实整页入口；AC-106/114 |
| `test_snapshot_pipeline.py`（3 项） | 原始硬件/Docker/vLLM 样本经真实 Collector/Monitor/State/codec/SnapshotClient/ObserverApp，比较原值、单位、零/未知/N/A、STALE/恢复、缺口及 GPU 关联；AC-104/105/107/109/114 |
| 原配置与 vLLM 视图测试迁移 | 分离采样/超时端点；新增采样下限拒绝矩阵；双标题预期按 AC-114 改动，13/17/Total 30、QUEUED、id 与不可变断言仍保留 |
| 其他原有适用回归 | 配置安全、采集解析、调度/State、日志、硬件/vLLM/Docker、布局/导航/主题/历史/本地 PTY 继续保留；AC-111 |

R2 提供完整链路黑盒，R4 实现并使其通过，另补 OS 适配器和新编排的 PTY 集成。旧 CLI/runtime 测试须迁移入口：配置断言移到 service，客户端 q 后采集继续，原采集 IO 清理断言移到显式 service stop；不得删掉或弱化原覆盖。详见 test-migration.md。

## 业务基线引用与本轮文档验证

本轮仅作介绍文字与组织结构调整，未重跑业务测试；以下全量测试是先前 R2 设计交接时点的实际结果引用，当前实现测试结果以 R4 记录为准。

执行平台为本地 WSL `Ubuntu-24.04` / Ubuntu 24.04.5 LTS x86_64，Python 3.12.3、pytest 8.4.2。复用本地现成环境，未下载依赖、未连接任何本地或远程服务器。

源码/测试复制到 WSL 原生目录 `/home/shawn/projects/tmp/joi-r2-skill-update-20261116`，在其中执行：

```sh
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=/mnt/d/Documents/joi-observer/docs/dev-workflow/dev-1/REQ-001/evidence/r2-skill-update-pytest-20261116.xml
```

该次 R2 基线结果：**2040 passed，124 failed，24.50s**。无导入/收集/环境错误。完整链路三个参数场景已先通过四轮真实原始采集及 State 基线断言，再触达 build_metadata 的待实现入口。

| 分类 | 实际原因 |
| --- | --- |
| 116 失败 | NotImplementedError：触达 R2 预留业务入口 |
| 4 失败 | 真实视图仍读取旧 base_url，DisplayMetadata 适配待 R4 |
| 3 失败 | sample_interval 的 0.1/0.5/0.999999 拒绝预期已更新，旧解析实现尚未收紧 |
| 1 失败 | 原双标题测试已按新名称规则迁移，旧视图仍显示 name |
| 2040 通过 | 既有适用功能及新增可执行判断；其中原测试文件 2039 通过，新契约文件 1 通过 |

这四类失败均为明确待实现/待迁移行为，不用 skip/xfail 处理。其余未变更功能的原适用回归通过。原有测试源码并非全部不变：仅配置范围与标题对应的预期作已确认迁移，其他核心断言保留。

原始证据：[pytest 输出](evidence/r2-skill-update-pytest-20261116.txt)、[JUnit](evidence/r2-skill-update-pytest-20261116.xml)、[分类摘要](evidence/skill-update-verification-summary-20261116.txt)。evidence 已由既有 `.gitignore` 忽略。历史基线 2037 passed、首版 R2 的 2038 passed/90 failed，以及 2026-11-13 修订后的 2040 passed/118 failed 保留在各自原日志，不替代本轮结果或新架构完成验收。

大快照独立夹具采用 256 模型、每模型 61 个一秒采样历史点，JSON 正文为 **11543589 字节**，用于证明大于旧限制的合法输入；不代表待实现 codec 或实际部署吞吐已经通过。静态 diff 检查通过，当前设计与交接本地链接已核对；[图与引用静态检查](evidence/design-static-check-20261116.json)覆盖 14 份设计、27 张图。环境无可用 Mermaid parser/renderer，未下载或实际渲染图形，只报告静态结构一致性。

systemd 模板沿用首版静态检查事实：WSL 原生 0644 副本的 `systemd-analyze verify` 返回 1，仅因目标 ExecStart 尚未安装；未部署或启动服务，不能称部署通过。没有生成离线安装包或更新历史 GUI/回放。

本轮文档检查在本地 WSL 执行，覆盖图前位置、两图元素、别名唯一性、一句职责及本地引用，结果为 **13 份模块 / 91 项介绍全部通过**，另核对整体设计已恢复组件职责与模块索引，见 [简介覆盖检查](evidence/class-object-intro-check-20261116.json)。`git diff --check` 无格式错误。本轮未编辑产品代码、测试、需求或部署文件，未执行任何服务器连接；工作区并行 R4 修改不回退或归入本轮文档验证。

## R4 实现检查项（原设计交接）

- 实现协议、受控编解码、客户端/发布状态机、配置采样下限校验和默认 CLI 接线，使上述失败转绿。
- 复用原 ApplicationRuntime 的采集装配和资源回收；最终 main 委派新 run_command，旧组合根不保留为另一种正式采集模式。
- 按迁移映射保持原测试意图和有效断言，补新编排本地 PTY 的信号/异常恢复、worker 退出预算和大快照下按键响应/容量验证。
- 在不连接服务器的约束内，用 OS 调用替身验证 Unix 权限/残留/分批 IO；真实账户权限、systemd 管理及 REQ-002 容器挂载仍未部署验证。
- README 的正式新命令随实现更新，避免将骨架命令写成已经可用；REQ-002 另行设计浏览器时间映射、整数表示、刷新恢复和只读容器。

## 下一步

本轮说明性文档更新供 **R3 核对引用，并供当前 R4 实现查阅**；不改变已有 plan.md 的业务范围、依赖或验收要求，不重置 R3/R4 阶段。实现问题仍按既有 R4 → R2 修订流程反馈。本对话不自动推进其他角色。
