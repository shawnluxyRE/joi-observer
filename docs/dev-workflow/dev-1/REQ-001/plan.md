# dev-1 / REQ-001 概要开发计划

- 项目：`D:\Documents\joi-observer`
- 工作目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-1`
- 需求目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-001`
- 修订与状态：v1.0，2026-11-16；R3 / ready，交接 R4。
- 需求依据：[requirements.md](../requirements.md) v1.3，**仅 REQ-001 / AC-101～114**；所有 AC 编号均指 dev-1。
- 设计依据：[architecture.md](../../../design/architecture.md) v1.0；[collector-service.md](../../../design/collector-service.md)、[ipc.md](../../../design/ipc.md)、[tui-client.md](../../../design/tui-client.md) v1.2；[configuration.md](../../../design/configuration.md)、[application-shell.md](../../../design/application-shell.md)、[monitor-state.md](../../../design/monitor-state.md) v2.2。硬件、Docker、vLLM、主题、导航、错误日志的复用基线由整体设计索引。
- 接口与测试依据：[handoff-r2.md](handoff-r2.md) v1.2、[本轮设计复查](review-r2-20261116.md)、[测试迁移映射](test-migration.md)；下表链接到当前工作区的接口骨架和黑盒。

本计划交付宿主机常驻采集服务及只读 TUI。REQ-002 仅消费本次形成的共享协议；Web 页面、浏览器 API、容器镜像与 Compose 不在本计划内。具体实现步骤、worker 方案和 subagents 分工由 R4 确定。

## 主要任务

“前置依赖”表示启动该交付或集成所必需的结果；已有冻结接口可支持先行开发的任务不设置串行依赖。各任务均需补齐所改行为的验证，最终集成依赖和共享文件冲突另见下一节。

| 任务编号与标题 | 交付结果、关联需求与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 白名单展示元数据与完整快照协议 | 从生效配置生成完整有序元数据；编解码保留身份、名称回退、端口、GPU 关联、单位、精确整数、未知/N/A、STALE 与历史缺口；拒绝畸形/额外/敏感字段，返回深不可变值。AC-104、107、109、110、113、114；[test_ipc_protocol.py](../../../../tests/test_ipc_protocol.py)。 | [ipc/protocol.py](../../../../src/joi_observer/ipc/protocol.py)；按 IPC 的帧、白名单、整数及时间契约实现，复用现有 StateSnapshot。 | 无；设计和公开类型已具备。 |
| T-002 独立采集运行期与配置边界 | 迁出并复用原采集装配，唯一 State/Monitor/日志在无终端、无客户端时持续运行；提供无 I/O 快照和不丢失的更新通知，显式停止回收全部来源。生产采样独立校验 1～60 秒，collection_timeout 保留 0.1～60 秒。AC-101～104、109、111、113；[test_service_contract.py](../../../../tests/test_service_contract.py) 的 runtime/通知用例及既有配置、采集、调度、状态、日志回归。 | [runtime.py](../../../../src/joi_observer/runtime.py)、[config.py](../../../../src/joi_observer/config.py)、原 cli.ApplicationRuntime 的来源工厂与清理接线，必要的 Monitor 通知接线；设计见常驻服务、配置、状态。 | 无；沿用既有 Collector/Monitor/State 与外部端口。 |
| T-003 只读快照发布与 Unix 监听适配 | 先完成监听就绪屏障，再发布初帧、状态更新和空闲心跳；多读者共享编码，慢读者/上行输入/断开分别隔离；新读者不接收过期缓存。完整帧分批发送，受控编码、待发数量、连接容量和发送期限符合设计。AC-101～103、105、107、109、110、112；[test_service_contract.py](../../../../tests/test_service_contract.py) 的 publisher 用例，补 OS 端口与容量/取消验证。 | [ipc/server.py](../../../../src/joi_observer/ipc/server.py) 及所需 worker 适配；设计见 IPC、常驻服务。Unix 绑定/权限/残留等以 OS 调用替身验证。 | 无新增启动前置；可按既定 source/listener/通知接口开发，协议集成完成条件见后文。 |
| T-004 宿主采集服务生命周期集成 | 单一实例锁下加载一次配置，绑定完成后才开始采样；新启动生成新身份、基线和历史。无效配置、重复实例、绑定失败不留下采样任务；运行中发布故障关闭发布且继续采集，只报告固定安全诊断。配置冻结、日志降级、信号/部分启动失败、幂等清理及预算可验证。AC-101～104、107～113；[test_service_contract.py](../../../../tests/test_service_contract.py) 的完整服务、重启、锁和故障用例。 | [service.py](../../../../src/joi_observer/service.py)、运行期/发布器接线及必要系统端口适配；设计见常驻服务、IPC、配置、错误日志。 | T-001、T-002、T-003 的对应接口可运行，启动/发布/采样的分层验证通过后进入服务集成。 |
| T-005 单次连接与不可变本地缓存 | UnixConnector 与 SnapshotClient 只连接一次；完整收帧和验证后原子替换缓存，同步读取无 I/O。身份/元数据变化、序号/时间/revision 倒退、EOF、期限或协议错误锁存失败；同 revision 心跳仍替换历史。新对象手动恢复，失败/关闭不安装迟到结果。AC-105、107～109、112；[test_ipc_client.py](../../../../tests/test_ipc_client.py)，补解码 worker、Unix 接收适配及取消验证。 | [ipc/client.py](../../../../src/joi_observer/ipc/client.py) 及所需 worker 适配；设计见 IPC、TUI 客户端。 | 无新增启动前置；可按 ReceiveStream/codec 契约开发，协议集成完成条件见后文。 |
| T-006 展示元数据接入既有 TUI 视图 | 生产视图直接接受 DisplayMetadata，不重建含伪 URL 的采集配置。列表显示 name、详情显示已回退的 served_model_name，保留端口差异、同名不同 id、GPU 关联及长名称裁切；布局、主题、导航和扫描历史沿用基线。AC-104～107、114；[test_display_metadata_view.py](../../../../tests/test_display_metadata_view.py)、[test_vllm_view.py](../../../../tests/test_vllm_view.py) 及原硬件/布局/导航/主题/历史回归。 | `tui/{app,layout,widgets,vllm,navigation,history}.py` 的展示类型与字段访问；设计见 TUI 客户端、应用外壳、vLLM、导航。纯视图 AppConfig 测试路径继续有效。 | 无；ModelDisplay/DisplayMetadata 已冻结，可直接构造测试输入。 |
| T-007 正式命令与 TUI 会话集成 | TuiClientSession 首帧成功后才进入全屏；q 只结束本会话，中途失联先恢复终端再诊断。main 正式委派 run_command，默认/显式 tui 仅连接，service 无 TTY 要求；参数迁移、帮助/版本/示例、退出码和信号符合应用外壳。默认客户端从不读配置、启动采集或自动重连。AC-102、103、105、106、108、109、111～114；[test_client_session.py](../../../../tests/test_client_session.py)、[test_client_cli_contract.py](../../../../tests/test_client_cli_contract.py) 及迁移后的旧 CLI/运行期用例。 | [tui/session.py](../../../../src/joi_observer/tui/session.py)、[cli.py](../../../../src/joi_observer/cli.py)、[__main__.py](../../../../src/joi_observer/__main__.py) 的正式接线；设计见应用外壳、TUI 客户端。移除旧组合根作为另一种正式采集入口的可能。 | T-004、T-005、T-006 的对应行为可运行；命令解析与依赖工厂的局部工作可提前。 |
| T-008 Ubuntu 离线整合验证与服务使用说明 | 新旧适用回归全部转绿，完成原始来源到新客户端/Frame 的贯通、双会话隔离、手动恢复、重启及新编排 PTY；补大快照响应性、CPU/内存和退出资源证据。README 与 systemd 模板和实际入口一致，说明安装前置、权限、自启/启停/升级/日志和配置重启生效。AC-101～114，统一以 AC-111 收束；[test_snapshot_pipeline.py](../../../../tests/test_snapshot_pipeline.py)、完整测试集及新增集成检查。 | `tests/`、[README.md](../../../../README.md)、[systemd 模板](../../../../deploy/systemd/joi-observer.service)；结果与限制写入本需求 R4 交接及 evidence。 | T-007 完成正式接线；各任务的局部回归、容量试验和测试迁移持续进行，最终整合在本任务收束。 |

## 开发顺序与并行条件

1. 优先启动 T-001、T-002，并可按冻结接口并行开展 T-003、T-005、T-006。先验证完整协议和独立采样，再组合传输；不要求为了等待另一分支而复制采集状态或引入临时独立采集模式。
2. T-003/T-005 开发可使用既定端口替身；各自转绿与大快照集成须使用 T-001 的真实 codec。T-003 与 T-002 合并时核对真实 Monitor 通知，不能以一秒轮询取代更新驱动发布。元数据视图集成复用 T-001 的真实投影。
3. 尽早联合验证编解码 worker 的执行隔离、取消及大快照下事件循环响应。线程/GIL、迟到结果和退出时池回收都属于必须解决的实现条件；若方案不能满足已有预算，由 R4 调整实现，不能降低样本规模、裁掉历史或放宽期限使测试通过。
4. T-001～003 集成后开展 T-004；T-004、T-005、T-006 可运行后完成 T-007。先形成“来源 → State → 发布 → 客户端 → Frame”的真实离线链路，再以正式 main / python -m 入口和新会话编排完成 T-008。
5. `cli.py` 同时涉及 T-002 的装配迁出和 T-007 的入口切换，是主要修改冲突点；运行期所有权先明确，最终一次切换正式入口。`ipc/protocol.py` 的字段和 codec 契约由 T-001 集中维护；若 worker 有共享适配，T-003/T-005 共同确定接口和关闭责任。T-006 与 T-007 在 `tui/app.py` 的接线合并时复核会话选择和历史尺度的所有权。
6. 每项任务同步迁移对应测试，集成时保留 [test-migration.md](test-migration.md) 的验证意图。旧“q 后关闭采集”拆为“q 后服务/另一客户端继续”和“service stop 后全部采集资源回收”；旧默认加载配置的检查移至 service，同时增加默认客户端零采集检查。实现分工及合并批次由 R4 安排。

## 验证安排

### 已核对的输入基线

R2 的 WSL Ubuntu 24.04 / Python 3.12.3 结果为 **2040 passed、124 failed，共 2164 项**。R3 在本地 WSL 解析其 [JUnit](evidence/r2-skill-update-pytest-20261116.xml)，数量一致；本轮未重新执行产品测试。失败分类引用 [R2 分类摘要](evidence/skill-update-verification-summary-20261116.txt)：116 项待实现入口、4 项元数据视图迁移、3 项采样下限校验、1 项详情标题迁移。它们是开发基线，不是允许保留的最终失败。

独立大快照夹具为 256 模型、每模型 61 个历史点，正文 11,543,589 字节；还保留 `10**5000` / `10**10000` 整数边界。夹具可表达规模不证明新 codec、worker、终端或部署吞吐已经通过。旧 ApplicationRuntime 的回归通过也不能替代新入口验证。

### 分层验证与完成条件

| 验证层 | 执行与判定 |
| --- | --- |
| 协议与配置 | T-001、T-002 使协议黑盒和配置边界转绿；保留脱敏、精确类型、YAML 安全、字段定位、原有大整数和大快照输入。配置不接受低于一秒的生产采样，但内部短周期/可控时钟调度测试继续保留。 |
| 发布/接收与服务 | T-003～005 使服务/客户端黑盒转绿；补未覆盖的 OS 适配、64 连接边界、单帧在途/最新待发、整帧总期限、取消和迟到结果检查。监听失败必须零采样，运行中发布失败必须继续采样；首帧过期缓存、心跳、元数据冻结和实例重启均须验证。 |
| 真实数据贯通 | 三类模型的 [test_snapshot_pipeline.py](../../../../tests/test_snapshot_pipeline.py) 必须完整通过真实 Collector/Monitor/State/codec/SnapshotClient/ObserverApp；保留原始样本的数值、单位、未知、零、N/A、STALE、恢复缺口、Docker id、名称和 GPU 关联断言。另核对关闭一个会话及隐藏对象均不改变采样。 |
| 响应性与资源 | 在 WSL 原生目录对大快照和慢传输使用离线端口，记录 CPU/峰值内存、完整帧耗时、按键/退出响应与 worker/子进程回收。核对 64 KiB 单次 IO、发送两秒总预算、接收与解码五秒总预算、单项 worker 在途及设计规定的清理预算；服务和客户端各自共享一秒清理预算，发布器清理至多 250ms。60 FPS 沿用调度目标，不把 PTY 吞吐表述为所有终端实测帧率。 |
| 正式入口与终端 | T-007/T-008 使用真实新客户端编排、离线传输和 Ubuntu/WSL PTY，验证首连失败不进全屏、中途失败恢复后输出诊断、q/主题/导航、双会话选择及尺度独立、SIGINT/SIGTERM/异常/部分初始化恢复和退出码。检查 main 与 python -m 均走新入口；旧 PTY 结果只能作为基线。 |
| 全量回归与说明 | 在本地 Ubuntu/WSL 原生目录执行迁移后的全部适用测试，例如 `python -m pytest -q --tb=short --junitxml=<本需求 evidence 路径>`；使用已有依赖和离线来源。记录命令、环境、结果、迁移映射及未验证项。未变更功能原有效断言必须通过，禁止删测、skip/xfail、缩小输入或弱化断言掩盖回归。README/示例/正式命令与 systemd 参数同步核对，unit 在原生文件系统做静态检查。 |

整个过程禁止尝试连接任何服务器，包括本地 AF_UNIX listener。协议/完整链路用内存字节流，Unix 绑定、读写、权限与残留用 OS 调用替身；锁用临时文件，终端用本地 PTY。不得以这些结果宣称真实账户/设备权限、实际 AF_UNIX 连通、systemd 开机管理已通过；R4 交接逐项保留未做实机部署验证的边界。R2 的 systemd 静态检查曾因 ExecStart 尚未安装返回 1，也不能写作部署通过。

不生成或重建离线安装包，不更新历史 GUI 启动/回放入口，不将其结果用于本轮验收。T-008 的服务部署说明可交付，安装/启用服务及真实连接不在本次离线执行范围内；REQ-002 容器验证由其后续阶段处理。

## 修订记录

| 修订 | 日期 | 内容 |
| --- | --- | --- |
| v1.0 | 2026-11-16 | 依据 R2 v1.2 建立八项概要任务、必要依赖、并行与冲突条件、测试迁移和离线验证安排；无待决业务或设计问题，交接 R4。 |
