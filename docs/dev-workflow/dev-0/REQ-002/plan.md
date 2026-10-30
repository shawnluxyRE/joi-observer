# dev-0 / REQ-002 概要开发计划

- 项目：`D:\Documents\codex_worktree\dev-req002\joi-observer`
- 工作目录：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0`
- 需求目录：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0\REQ-002`
- 修订与状态：v1.0，2026-10-30；R3 ready，可交 R4 实施。
- 分支与输入：`codex/dev-req002`，HEAD `a84f9d8b632544f1da005df37d7badc2c530d617` 加当前 R2 未提交产物。上述路径沿用本需求 R2 的实际工作目录；根目录 AGENTS.md 中的 `D:\Documents\joi-observer` 是原工作区，不在两处分别维护本计划。
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-002 / AC-201～AC-207 及共同规则；[AGENTS.md](../../../../AGENTS.md)。
- 交接依据：[handoff-r2.md](handoff-r2.md) v1.0；公共基础以 [REQ-001 R5 交接](../REQ-001/handoff-r5.md) v1.4 的需求 v1.12 验收结果为起点。

## 设计、接口与测试依据

下列 D1～D5 仅为本计划的引用简称；T-001～T-007 均限定于 REQ-002，不与 REQ-001 的同号任务混用。

| 引用 | 模块设计 | 接口及主要验证入口 |
| --- | --- | --- |
| D1 | [hardware.md](../../../design/hardware.md) v1.0 | [hardware.py](../../../../src/joi_observer/collectors/hardware.py)；[test_hardware.py](../../../../tests/test_hardware.py) |
| D2 | [monitor-state.md](../../../design/monitor-state.md) v1.6 | [base.py](../../../../src/joi_observer/collectors/base.py)、[monitor.py](../../../../src/joi_observer/monitor.py)、[models.py](../../../../src/joi_observer/data/models.py)、[state.py](../../../../src/joi_observer/data/state.py)；[test_hardware_monitor.py](../../../../tests/test_hardware_monitor.py) 及既有状态/调度测试 |
| D3 | [configuration.md](../../../design/configuration.md) v1.2 | [config.py](../../../../src/joi_observer/config.py) 与既有配置测试；本轮只消费现有配置，不增加字段 |
| D4 | [application-shell.md](../../../design/application-shell.md) v1.3、D1 的硬件显示契约 | [widgets.py](../../../../src/joi_observer/tui/widgets.py)、[layout.py](../../../../src/joi_observer/tui/layout.py)、[app.py](../../../../src/joi_observer/tui/app.py)、[cli.py](../../../../src/joi_observer/cli.py)；[test_hardware_view.py](../../../../tests/test_hardware_view.py)、[test_hardware_runtime.py](../../../../tests/test_hardware_runtime.py) 及既有外壳/PTY 测试 |
| D5 | [error-logging.md](../../../design/error-logging.md) v1.1 的既定契约 | [error_log.py](../../../../src/joi_observer/error_log.py) 及既有日志测试；实际实现状态以 REQ-001 R5 v1.4 为准，不采用旧文档中“仍为骨架”的阶段描述 |

[Neon Grid 参考稿](../../../design/joi-observer.html) 仅用于理解外观，不能把模拟数据或旧交互当作本轮实现要求。工程继续使用现有 [pyproject.toml](../../../../pyproject.toml)、[uv.lock](../../../../uv.lock) 和标准库，不因硬件接入新增依赖。

## 范围与完成边界

本轮实现本机 NVIDIA GPU、CPU、RAM、前三挂载点的采集、动态 GPU 来源管理、只读硬件显示及生产组合根接线。沿用 `Collector → Monitor → MonitorState → TUI`；状态、日志、配置和终端基础复用已验收实现，不重建一套硬件状态或错误体系。

影响交付判定的条件如下，详细数值口径与错误分类引用 D1：

- GPU 使用完整 UUID 保持身份；inventory 独立于设备槽，新卡追加、旧卡暂失保槽，单卡/字段失败不覆盖其他来源。成功无卡与发现失败必须可区分。
- CPU/RAM 分来源，CPU 失败或取消后重新建立差分基线；RAM、显存和挂载容量各按约定口径处理，不混用。挂载点必须精确验证，前后身份变化时丢弃容量，不能回退父文件系统或用第四项补位。
- 硬件显示复用现有 8 区与全页半分。GPU 每卡 3 行、Host 外壳 5 行、Storage 内容 3 行/外壳 6 行；inventory 不抬高最小高度。0～4 卡最低 120×36，5 卡最低 120×37，更多 GPU 沿用现有容量公式。Docker 数量不改变最低高度或侵占下半区。
- AC-205/206 在本轮验证给定 `ViewSelection` 时的显式映射、高亮清空及只读性；方向键更新选择由 REQ-005 完成，完整双主题由 REQ-006 完成，最终交互需后续联验。本轮不把这些交互声明为已交付。
- 不实现 Docker/vLLM 采集、网络流量、磁盘 IO、GPU 详情或 Web；保留 Docker/vLLM 占位及既有注入接口。全程离线，禁止尝试连接任何服务器。

## 主要任务

任务按可验证结果划分；具体函数拆分、实现步骤和 subagents 分工由 R4 决定。现有公开接口足以支持前五项并行开工，不能把真实 IO 尚未完成当作原始样本测试的前置阻断。

| 任务编号与标题 | 交付结果、关联需求与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 可取消的本地 IO | 原始文件、文件系统计数和 NVIDIA 命令通过有限输出、可取消的本地进程边界读取；独占资源、超时、幂等关闭及回收有本地 Linux 实证。支持 AC-201～204、共享响应/退出要求；补足 R2 明确未覆盖的真实 OS 验证。 | `collectors/hardware.py` 的 `LocalHardwareIO`，必要的包内 worker 与对应测试；D1 的 IO/生命周期契约。 | 无新增任务依赖；最终 OS 验证需本地 Ubuntu/WSL。 |
| T-002 Host 与挂载点采集 | CPU/RAM 独立更新；初始未知、真 0、计数回退、失败/取消与恢复正确；前三挂载按序、精确匹配、容量一致、无回退或补位。AC-202/203/204/207；`test_hardware.py` 的 CPU/RAM/Storage 场景。 | `CpuCollector`、`MemoryCollector`、`StorageCollector`；D1/D3，复用现有结果与失败类型。 | 无；用原始 IO 替身验证。 |
| T-003 GPU 查询与发现 | UUID 定位逐卡采集，字段/单位/不可用与部分失败正确；显存关联容量成对保值；发现清单与无卡状态可靠，创建独占 IO 的子来源。AC-201/204，支持 AC-205/206 的可靠身份；`test_hardware.py` 的 GPU/Discovery 场景。 | `GpuCollector`、`GpuDiscovery` 及其工厂；D1/D2。 | 无；用原始 CSV 与受控 IO 错误验证。 |
| T-004 动态来源调度与收尾 | inventory 和新来源仅由 Monitor 注册/提交；完整校验后纳入，协议或工厂错误不产生半轮状态；首采即时、后续保持各自周期，重复发现不重建，迟到结果不生效。关闭覆盖发现器、静态/动态来源及未采用资源，保持总退出预算。AC-201/204 及共享隔离/历史/日志规则；`test_hardware_monitor.py` 和既有调度/状态/日志回归。 | `monitor.py`，按需接合 `collectors/base.py`；D1/D2/D5。现有 State 与日志算法原则上复用。 | 无；基于公开 Discovery/Collector 离线端口实现。 |
| T-005 硬件控件与 Frame | 数字、容量与条格一致；正常 0、未知、STALE 各有正确显示；按当前选择只读计算关联色，未知清空；长文本、固定状态槽和新旧快照兼容正确，替换占位后无重复绘制或越界。AC-201～207 的显示部分；`test_hardware_view.py` 及既有 TUI/外壳测试。 | `tui/widgets.py`、`tui/layout.py`，必要时核对 `app.py` 的 GPU 槽；D1/D4，沿用几何与语义颜色。 | 无；可直接使用不可变快照。 |
| T-006 生产组合根联通 | `build_hardware_sources` 无 IO 组装 CPU/RAM/前三挂载与发现器；同一 State/Monitor 启动后到真实 Frame 可见，所有 IO 继承超时且退出释放。移除生产 `host/local` 占位，保留外部注入路径；导入、构造、help、缺配置不启动采集。AC-201～207 的链路验证；工厂测试及 `test_hardware_runtime.py`。 | 硬件来源总工厂、`cli.py` 与必要接合修复；D1～D4。 | T-001～T-005 的最小可运行链路；装配审阅和测试场景可提前准备。 |
| T-007 离线验收与交付 | 新增业务测试全部通过且公共基础无回归；真实 OS 取消/回收、PTY 和最终安装包证据齐备，README 反映实际范围，形成 R4 交接及未验证清单。AC-201～207 的本轮范围、共享生命周期与安装回归。 | 相关 `tests/`、本需求 `evidence/`、README、`handoff-r4.md`；复用既有离线安装/PTY 工具。 | T-006 完整联通后执行最终验收；脚本和环境准备可提前。 |

## 开发顺序与并行条件

1. 先核对当前 R2 输入与基线，保留用户及 R2 未提交改动。REQ-001 的 v1.12 已验收；其旧计划中的 43 项实现差异是历史，不能再列为本轮待修任务。
2. 尽早验证 T-001 的超时/取消与真实进程回收边界。T-002/T-003 使用原始材料替身，T-004 使用发现端口，T-005 使用快照，可与 T-001 并行。真实 IO 策略若不能满足既定预算，应先处理该风险，不能等到最终接线才发现。
3. `hardware.py` 同时承载 IO、采集器与工厂，是主要修改冲突点；R4 安排统一集成或明确修改边界。`monitor.py` 的动态资源管理集中集成；`widgets.py` 与 `layout.py` 的相互引用需避免导入循环。私有组织方式不在本计划固定。
4. 各任务先通过对应定向测试，再集成 T-006。先确认静态来源和 inventory 归入同一状态，再核对发现→逐卡采集→Frame、失败恢复及 q 退出。不能仅用直接构造的快照代替生产组合根验证，也不能仅以原始 IO 替身证明 T-001 已完成。
5. 完整链路稳定后执行 T-007。Windows 回归与本地 Ubuntu/PTY 验证可并行；最终 wheel/安装验证须对应同一交付源码。没有依赖变化时保留锁文件，所需离线材料从已有本地目录复用，不访问包索引。

## 验证安排

### 已核对基线

- R2 [test-baseline.json](test-baseline.json)：新增 203 项中 1 passed / 202 failed；全量 Windows 350 passed / 202 failed / 15 skipped，Ubuntu 365 passed / 202 failed / 0 skipped，均无收集错误。失败是 197 项直接未实现、2 项生命周期断言拒绝未实现异常、2 项 Frame 未接线、1 项运行期未接线。
- R3 于 2026-10-30 实际复跑 Windows 全量，结果仍为 **350 passed / 202 failed / 15 skipped，0 errors**，9.05 秒；旧 REQ-001 为 349 passed / 15 Unix PTY skipped、0 failed。见 [本轮报告](evidence/r3-full-windows.txt)、[JUnit](evidence/r3-full-windows.xml)、[校核摘要](evidence/r3-validation.json)。退出码 1 表示当前未实现基线，不是验收通过。
- R3 对 R2 记录的 37 个设计/源码/测试文件逐项核对 SHA-256，全部一致。Ubuntu 数字引用 R2 实测，R3 未重复执行；已有证据不能代替 R4 实现后的验证。

### 定向与联合完成条件

| 验证组 | 必须成立的结果 |
| --- | --- |
| 采集数值与恢复 | 四类采集器从原始 proc/mountinfo/statvfs/CSV 生成正确结果；CPU 不跨失败或取消区间计算；RAM 使用 available；挂载精确身份与容量一致；GPU 字段不可用不误报，解析失败保留正确字段/容量组。无卡、无挂载、无 CPU 基线均不伪造 0 或 ERROR。 |
| 动态发现与隔离 | 重复/冲突声明、模板变化、错误或抛异常工厂均不能污染部分状态，已建而未采用资源释放；重复发现不重建或重置相位；发现慢/失败不阻塞已知卡与 Host；消失保槽、恢复复用；stop 后没有新建源或迟到提交。 |
| 状态、日志与显示 | 用真实 State/ErrorLog 验证部分失败保值、历史缺口、首次/持续/恢复后失败日志规则；TUI 只有固定槽 STALE，不能显示原因、时间或原始错误。旧通用 GPU、host/local、路径 Storage 的只读兼容继续通过。 |
| 高亮与布局 | 给定 A/B/未知选择时，高亮只改变编号、条填充和百分比的语义 role；UUID 精确匹配，索引只用当前有效唯一值，无猜测、重排或额外采集。保持五卡 120×37、奇偶半页、Storage 三行及 Docker 余高；缩放和失败恢复不产生越界或状态引起的几何变化。 |
| 生产链路 | 保留 `test_production_runtime_collects_local_hardware_and_closes_every_io_on_q`：原始 IO/终端替身之外使用真实运行链路，五卡可见、inventory 不算第六卡、只采前三挂载、q 恢复终端且 IO 全关、无网络尝试或输出泄漏。再结合真实配置加载验证来源范围与无 IO 启动边界。 |

现有四份新增测试分别为 99/22/81/1 项。R4 可针对真实风险补充用例，优先使用相关已有测试文件；不得删改有效业务断言、永久 skip/xfail 或以 NotImplementedError 代表成功。完成判定是业务行为和回归全部满足，不是维持测试总数不变。

### 本地 OS、终端与安装验证

- 在本地 Ubuntu/WSL 实际验证 LocalHardwareIO：固定操作与 argv、无 shell、文件/命令输出上限（两路各不超过 1 MiB）、IO 错误、超时、取消、重复 close、进程终止与回收、无控制台泄漏。使用受控本地临时材料/辅助进程制造慢操作和异常；不替换被验证的父进程取消/回收路径。只通过 RawIO 测试不足以交付。
- 将多个静态/动态来源与发现器一起纳入关闭验证，核对每端口 250ms 清理及应用整体 1 秒退出预算，不能串行累加预算。检查慢来源不拖住其他采样、键盘及 q，0.1 秒配置下仍遵守不重入、忙时跳槽规则。进程组织方式由 R4 决定，不另设无依据的吞吐指标。
- 实现后在 Windows 与本地 Ubuntu 执行完整 pytest。Windows 可保留既有 15 项 Unix 平台跳过，Ubuntu 必须实际执行；补充 Linux 专用 OS 测试时记录平台原因及真实执行结果。定向/全量输出、环境、源码版本和未验证事项保存到本需求的新证据文件，不覆盖 R2 历史。
- 在本地真实 PTY 复验硬件接线后的 q、信号退出、缩放、慢采集期间输入响应及终端恢复，保留既有 Esc/部分转义序列保护。布局探针只能证明 Frame，不能冒充真实终端绘制证据。
- 用已有离线工具重建并检查最终 wheel，在隔离安装环境、新 shell 和异目录验证裸命令、无配置/help 不采集、硬件入口及 worker 能从安装包运行。复用既有脚本时核对其旧占位断言；运行场景仅用本地资源或明确的原始 IO 替身，不能启动任何服务器采集。`uv run` 不能代替工具安装验收。
- 当前 worktree 没有 `.pytest_cache/offline_wheels`；原工作区 `D:\Documents\joi-observer\.pytest_cache\offline_wheels` 已存在，Windows 原始离线依赖为同目录下的 `offline_deps`。R4 在 worktree 或隔离目录准备所需离线包并核对锁文件相对路径，不修改原工作区实现、不联网重新解析依赖。Ubuntu 可先复用 R2 记录的 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。

### 交付判定与后续衔接

T-001～T-007 的交付条件具备后，R4 可交 R5 验收 REQ-002 本轮范围。README 应说明硬件已接入、操作系统和本地依赖要求、Docker/vLLM/完整导航与主题的当前边界；移除与交付状态不符的“全部采集器未接入”等旧描述。

本地 Linux worker 验证属于本轮必要证据。目标服务器驱动、实际 GPU/权限、无设备返回特例和真实挂载状况仍未现场验证；继续沿用 [R2 尚未验证范围](handoff-r2.md#尚未验证的范围)，不因开发或验收自动连接服务器。后续 REQ-005/006 联验完整按键、高亮及主题；本计划不预先宣称这些需求完成。

## 修订记录

- v1.0（2026-10-30）：依据需求 v1.12、REQ-002 R2 v1.0 及已验收 REQ-001 建立七项交付任务，明确并行/集成顺序、真实 IO 验证、黑盒基线与后续交互边界；未发现阻断开工的设计问题。
