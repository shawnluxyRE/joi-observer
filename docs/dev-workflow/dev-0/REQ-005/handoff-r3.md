# dev-0 / REQ-005 R3 交接

- stage：R3
- result：ready
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-005 / AC-501～504 及共同只读、采样、布局规则。
- next_role：R4
- 修订：v1.0，2026-11-03。
- 分支与基点：`codex/dev0-req005`，`83aad39131895561553d62a359e1f1c52957ed77`；复用现有工作区和未提交的 R2 产物。
- 设计依据：[handoff-r2.md](handoff-r2.md) v1.3、[navigation.md](../../../design/navigation.md) v1.3、[application-shell.md](../../../design/application-shell.md) v1.7、[hardware.md](../../../design/hardware.md) v1.3、[vllm.md](../../../design/vllm.md) v1.4。

## 产物与处理结论

已创建 [plan.md](plan.md) v1.0，实际路径为 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005\plan.md`。

计划分为四项可验证交付：T-001 会话选择控制器，T-002 默认应用接线及注入兼容，T-003 服务描述与页脚呈现，T-004 离线联验与交付。明确启动前置、并行条件、集成顺序、AC-501～504 映射及 Ubuntu/WSL 的源码、真实终端和安装包验证；具体实现与 subagents 分工交给 R4。

需求、设计、接口注释和黑盒测试足以支持实施，未发现需要先退回 R2 的冲突。**ready 表示规划可交接，不表示导航已实现或测试已全绿。** 本轮仅新增两份 R3 文档及忽略目录中的核对证据，保留已有工作区修改，没有修改生产代码、测试、需求、R2 设计或依赖。

## 验证证据

| 类别 | 核对或引用结果 | 证据边界 |
| --- | --- | --- |
| 设计与契约审阅 | 对照 AC-501～504、共享设计、导航/服务骨架、默认应用与布局、既有正式装配及四组新测试；两个内部只读审查分别复核契约边界与测试/证据 | 均属于本轮 R3 内部核对，没有推进 R2/R4 聊天。已有采集、列表可见窗口、历史和 GPU 映射按现有能力复用。 |
| 当前实现缺口 | 控制器两入口、页脚函数仍为骨架；默认应用尚未接线；服务行/页脚仍为旧呈现；falsey 注入缺陷已记录 | 分别归入 T-001～T-003，不把已知待实现行为误当成新设计缺陷。 |
| R3 测试加载 | 本地 WSL Ubuntu-24.04，Ubuntu 24.04.5 LTS / x86_64、Python 3.12.3；`pytest --collect-only -q` 得到 **1442 tests collected，退出码 0** | 见 [输出](evidence/r3-collect-only.txt)；只收集，不执行业务断言。工作目录 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。 |
| 引用 R2 最新业务基线 | 已核对 [JUnit](evidence/r2-sync-pytest.xml)、[输出](evidence/r2-sync-pytest.txt) 与 [审计](evidence/r2-sync-audit.json)：**1398 passed / 44 failed / 0 errors / 0 skipped**；审计列出的文件哈希与当前文件一致 | 既有 1395 项通过；新增 47 项为 3 通过、44 失败。本轮未重跑全量、PTY 或安装；骨架遮蔽的后续断言不能算已验证。 |
| 本地测试环境 | 既有 venv 含 pytest 8.4.2、PyYAML 6.0.3、HTTPX 0.28.1 及运行依赖；uv 可执行文件存在。setuptools 未装在该 venv，但本地 wheel 可用 | [环境记录](evidence/r3-environment.json)；只读检查，没有安装/下载。加载成功不等于新包安装已验证。 |
| 离线安装材料 | 当前 wheel 目录只有 9 项；按 [REQ-004 清单](../REQ-004/evidence/r4-offline-wheels.json) 核对 17 个来源文件，全部存在且 SHA-256 相符，包括缺项的 WSL 缓存 | [核对结果](evidence/r3-offline-artifacts.json)。R4 可离线整理完整集合；尚未整理、构建或安装。已有安装验证脚本含旧路径，复用前须适配。 |
| 文档与修改范围 | 两份文档的本地链接、四项任务和交接状态一致；`git diff --check` 与新增文档空白检查通过；写入前记录的 134 个非忽略文件保持不变 | [文档审计](evidence/r3-document-audit.json)；仅证明本轮文档及修改范围，不构成业务验收。 |

最新 44 项失败分别为：控制器骨架 28、页脚函数骨架 2、默认接线 11、服务呈现 2，以及 **R2-005-001 falsey 注入缺陷 1**。R4 应实现后使其转绿，并保留全部既有通过行为；不能以跳过、预置输出或降低断言替代实现。

## 本轮决策

1. 接受 R2 v1.3 的范围与接口；REQ-001～004 已合并的采集、状态、按键解析和纯视图不重复开发。导航只维护会话选择，默认路径不需要新增 MonitorState 字段或第二份采样链路。
2. 默认控制器放在 ObserverApp，显式注入按 None 判断且读取/分派也尊重 falsey 对象。每帧只读取一次选择，同实例再次运行保留、新实例重置。R2-005-001 纳入 T-002，当前仍待 R4 修复。
3. T-001/T-003 可独立并行，T-002 可按协议同步开始；贯穿默认路径需 T-001+T-002，最终整帧和安装验收再汇合 T-003。R4 协调 `app.py` / `layout.py` 的接合修改。
4. 页脚导航说明归当前服务描述所有；同一描述用于标题、当前入口和页脚。全局箭头、间距、t Theme、q Quit 不变，不预造未来服务切换；小窗口沿用现有放大提示。
5. 本需求完成 t 的会话标识/名称及必要语义角色；完整终端 RGB 和全屏双主题属于 REQ-006，不成为本轮前置或交付宣称。
6. 当前无已确认的离线材料阻塞。R4 在安装前按已核对来源整理完整 wheel 集合、准备构建环境；使用已安装 CLI 和显式离线 I/O 防护验证导航，不能用源码 PTY 或虚构地址替代安装与网络隔离证明。

## R2 修订汇总

本轮无新增设计或测试修订请求，无需 R2 重复确认。R2-005-001 保留原编号，作为既有实现缺陷交 T-002 处理；它不要求修改设计含义，R3 未将其标为已修复。

## 待完成验证与执行条件

R4 须完成新旧业务测试、实际本地 PTY 和最终已安装 CLI 的导航、窗口恢复及退出清理。当前 R2 的通过结果及 R3 的收集/材料检查均不能替代这些完成验证。

离线包源已核对可用，但当前 checkout 尚未整理成完整 wheel 集合；安装参考脚本位于 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-004\evidence\r5-retest3-install\verify_uv_install.py`，其中旧 worktree/包路径须更新，并补 REQ-005 场景。证据目录被 Git 忽略，跨环境交接时需单独带走。

没有等待用户改变范围或 R2 补齐契约的事项。遵守禁止尝试连接任何服务器的约束；本轮没有运行采证脚本或现场服务，也没有安装包、提交、切换分支或推送。

## 下一步

接收角色 **R4**：请在用户发起的独立 R4 主对话中，按 [plan.md](plan.md) v1.0 结合 subagents 实施四项交付；先协调接合文件与离线包准备，完成新旧测试和已安装 CLI 验证，更新本需求 `handoff-r4.md` 后请求 R5 验收。

如发现设计/接口/测试矛盾，记录后交回 R2；如需调整规划，在 R4 交接的“R3 修订汇总”保留问题编号、依据与请求，人工交回本对话。跨角色推进由用户发起，本轮未创建或通知其他角色聊天。
