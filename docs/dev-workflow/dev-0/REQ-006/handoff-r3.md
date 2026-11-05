# dev-0 / REQ-006 R3 交接

- stage：R3
- result：ready
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006`
- 需求依据：[requirements.md](../requirements.md) v1.16，REQ-006 / AC-601～616及共同约束。
- next_role：R4
- 修订：v1.0，2026-11-04。
- 分支与基点：`codex/dev0-req006`，`0a42646b43df67832d6cfe9088e9eaf8c9c8f8af`；保留当前未提交的R2产物与用户修改。
- 设计依据：[handoff-r2.md](handoff-r2.md) v1.4、theme v1.4、application-shell v1.12、hardware v1.5、docker v1.2、vllm v1.8、navigation v1.8及REQ-004视图契约v1.1；实际链接集中见计划。

## 产物与处理结论

已创建[plan.md](plan.md) v1.0，实际路径为 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006\plan.md`。

计划分为六项可验证交付：T-001双主题与终端恢复、T-002外壳/上半区排版、T-003服务区排版、T-004稳定柱状历史与尺度、T-005 30 FPS应用接线、T-006离线联验和视觉交付。已列出启动条件、共享文件冲突、集成顺序、AC-601～616映射及Ubuntu/WSL源码、PTY、安装包和实际GUI终端验证。

需求、设计、接口注释与黑盒足以支持实施，未发现必须先交回R2的契约冲突。**ready只表示规划可以交接，主题、布局、帧时钟和历史目标仍待R4实现。** 具体实现步骤与subagents分工留给R4。本轮只新增两份R3文档及忽略目录中的核对证据，未修改生产代码、测试、需求、共享设计或R2记录。

## 验证证据

| 类别 | 实际核对或引用结果 | 证据与边界 |
| --- | --- | --- |
| 设计、接口与黑盒审阅 | 对照需求v1.16、R2 v1.4、Neon Grid映射、主题/上下布局/历史/时序接口及相关测试；两个内部只读复核分别检查主题布局和历史时序，无阻塞矛盾 | 属于当前R3内部审阅，没有创建或推进R2/R4聊天。采用最新范围，不以REQ-005旧主题/10Hz/旧布局要求约束本轮。 |
| R3实际测试加载 | WSL Ubuntu-24.04，Ubuntu 24.04.5 LTS / x86_64，Python 3.12.3；**1827 tests collected，退出码0，1.41s** | [输出](evidence/r3-collect-only.txt)、[结果](evidence/r3-collection-result.json)、[核对脚本](evidence/r3-check-inputs.py)。运行 `pytest --collect-only -q -p no:cacheprovider`，收集前阻断DNS/connect；未执行业务断言。 |
| 引用R2最新业务基线 | JUnit、summary和模块计数一致：**1827项，1368 passed / 459 failed / 0 errors / 0 skipped** | [本轮核对](evidence/r3-r2-evidence-check.json)；原始[R2最终JUnit](evidence/r2-parity-final-pytest.xml)、[输出](evidence/r2-parity-final-pytest.txt)、[分类](evidence/r2-parity-final-summary.json)。不是R3重跑结果，旧版计数仅保留历史。 |
| R3实际执行体审计 | 在WSL复跑现有只读审计，退出0；原有26份生产Python排除约定注释/结构变化后与基点一致，9个新增行为入口仍为骨架，链接无缺失 | [本轮审计结果](evidence/r3-source-audit.json)、[审计脚本](evidence/audit-r2-sync.py)。只证明设计交付的执行体边界，不证明业务或最终界面正确。 |
| 测试/构建工具 | 既有venv含pytest 8.4.2、PyYAML 6.0.3、HTTPX 0.28.1；uv 0.13.6及系统Python 3.12可用；venv未装setuptools，但本地wheel可用 | [环境记录](evidence/r3-environment.json)。目录 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。本轮无安装或下载。 |
| 离线安装材料 | REQ-005清单中的17个目的wheel全部存在且SHA-256相符，现成wheelhouse已完整；REQ-005的4份安装验证/辅助脚本存在 | [材料核对](evidence/r3-offline-artifacts.json)、[原清单](../REQ-005/evidence/r4-offline-wheels.json)。旧包和旧安装passed只作历史参考；本需求须从最终源码构建新包并适配验证。 |
| 文档与修改范围 | 两份文档本地链接、六项任务、验收编号和交接状态一致；空白检查通过；写入前记录的151个非忽略文件保持不变 | [输入快照](evidence/r3-input-manifest.json)、[文档审计](evidence/r3-document-audit.json)。仅新增计划、交接和忽略证据，不能作为产品验收。 |

459项失败包含未实现骨架及旧行为与新目标的差异，不全部属于环境错误或NotImplementedError；R2-006-001是单列的既有实现缺陷。前置失败遮蔽的后续断言未验证，R4须实际实现并执行，不能以skip/xfail、预置业务结果或降低断言转绿。

## 本轮决策

1. 接受R2 v1.4的范围与保留取舍，完整交付HTML字段分组、相对位置、对齐和角色；不是只统一主题/刷新。实际采用、适配与排除以[theme.md](../../../design/theme.md)的逐项表为准，不新增模拟字段或视觉豁免。
2. T-001～T-005可按已冻结接口开始，文件共享是集成协调事项。`layout.py`承接默认/帧/几何/尺度，`vllm.py`承接排版/历史，`app.py`承接终端/调度；默认贯穿验证需相关任务汇合。
3. 保持既有半页与最低尺寸，120列的历史宽度按新布局为88；Docker全部采集但仅显示可见前缀，Storage始终三内容行。不要沿用旧76列图区或由容器数抬高终端高度。
4. 选择和尺度属于应用实例，帧节拍属于每次run，配色资源属于每次enter。小窗口和未选中模型继续推进尺度；同一帧使用一次快照/选择及同域单调时间，MonitorState不新增展示状态。
5. 不变帧可省略实际写入，但不是强制缓存方案；30FPS为调度目标，不能增加采样或伪造历史。实际PTY耗时和GUI观感各自记录，不能由单元或PTY通过推导任意终端可见30FPS。
6. 当前测试加载和离线依赖无已确认阻塞。17个wheel已经齐备，R4只需按最终实现准备构建/安装验证；最终wheel、双主题RGB、背景/色表恢复及实际GUI截图均必须新验，不能复用旧REQ-005通过结论。

## R2 修订汇总

本轮无新增设计或测试修订请求，无需R2重复确认。

**R2-006-001：终端重入残留属性**保留原编号，纳入T-001。公开复现为 `tests/test_theme_terminal.py::test_terminal_reentry_reprobes_monochrome_without_old_color_attributes`：同一终端对象先有色进入/绘制/退出，再无色进入，不能继续携带上轮颜色属性。按每次enter独立配色和restore清缓存的既定契约修复，不改变设计含义；本轮未将问题标为已关闭。

## 待完成验证与执行条件

R4仍须完成适用业务测试、真实本地PTY、最终新wheel的隔离离线安装与实际Ubuntu/WSL GUI终端逐区截图对照。参考脚本为 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005\evidence\r5-install\verify_uv_install.py` 及同目录3份辅助脚本；旧Moonlight默认、同行数值和布局/历史期待须按REQ-006适配。网络防护必须显式生效，仅替换外部I/O，不替换业务结果。

没有等待用户改变范围或R2补齐契约的事项。全部工作保持离线，不尝试连接任何服务器。`evidence/` 被Git忽略，跨环境交接需单独携带。本轮未运行全量业务、PTY、安装或GUI验收，未提交、切换分支或推送。

## 下一步

接收角色 **R4**：请在用户发起的独立R4主对话中，按[plan.md](plan.md) v1.0结合subagents实施六项交付，协调共享文件，完成验证后更新本需求 `handoff-r4.md` 并请求R5验收。

如发现设计/接口/测试矛盾，记录后交回R2；如需调整计划，在R4交接的“R3 修订汇总”保留问题编号、依据和请求，人工交回本对话。跨角色推进由用户发起，本轮未创建或通知其他角色聊天。
