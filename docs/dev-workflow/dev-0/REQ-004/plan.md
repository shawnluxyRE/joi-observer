# dev-0 / REQ-004 概要开发计划

- 项目：`D:\Documents\codex_worktree\dev0-req004\joi-observer`
- 工作目录：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0`
- 需求目录：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0\REQ-004`
- 分支：`codex/dev0-req004`；沿用当前 worktree 及未提交的 R2 产物。
- 修订与状态：v1.0，2026-11-02；R3 ready，可交 R4 实施。业务尚未实现。
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-004 / AC-401～412、D-001 及共同规则；[AGENTS.md](../../../../AGENTS.md)。
- 设计交付：[handoff-r2.md](handoff-r2.md) v1.3；规划核对及环境条件见 [handoff-r3.md](handoff-r3.md)。AGENTS 中原仓库路径仅为沿用的元数据，本轮产物以当前 worktree 为准。

## 设计、接口与测试依据

| 依据 | 接口与验证入口 |
| --- | --- |
| [vllm.md](../../../design/vllm.md) v1.2、[metric-evidence.md](metric-evidence.md) v1.0 | [collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py)、[data/vllm.py](../../../../src/joi_observer/data/vllm.py)；[test_vllm_collector.py](../../../../tests/test_vllm_collector.py)、[test_vllm_engine_samples.py](../../../../tests/test_vllm_engine_samples.py) |
| [vllm.md](../../../design/vllm.md) §5～8、[monitor-state.md](../../../design/monitor-state.md) 的 REQ-004 契约 | [vllm_window.py](../../../../src/joi_observer/data/vllm_window.py)、[state.py](../../../../src/joi_observer/data/state.py)；[test_vllm_window.py](../../../../tests/test_vllm_window.py)、[test_vllm_state.py](../../../../tests/test_vllm_state.py)、现有 State/Monitor 测试 |
| [configuration.md](../../../design/configuration.md) 的“REQ-004 服务身份扩展”、[application-shell.md](../../../design/application-shell.md) v1.4 | [config.py](../../../../src/joi_observer/config.py)、[cli.py](../../../../src/joi_observer/cli.py)；[test_vllm_config.py](../../../../tests/test_vllm_config.py)、[test_vllm_integration.py](../../../../tests/test_vllm_integration.py) |
| [view-contract.md](view-contract.md) v1.0、应用外壳的半页布局 | [tui/vllm.py](../../../../src/joi_observer/tui/vllm.py)、[layout.py](../../../../src/joi_observer/tui/layout.py)、[app.py](../../../../src/joi_observer/tui/app.py)；[test_vllm_view.py](../../../../tests/test_vllm_view.py)、既有布局与 PTY 测试 |
| [error-logging.md](../../../design/error-logging.md)、既有硬件/Docker 设计及测试 | 复用统一调度、失败隔离、日志限频和关闭生命周期；保护已经通过的普通指标结果路径 |

共享设计文档部分仍保留前序需求的修订日期，REQ-004 增量以上表指定章节和 R2 v1.3 为准，不把旧阶段说明视为当前实现状态。

## 范围与实施起点

完成三个配置类型 Chat、Embedding、Reranker 的直接 vLLM 采集、分类型指标、独立历史和服务区展示，覆盖全部 AC-401～412。REQ-001 公共基础及 REQ-002/003 已在当前分支，保留唯一的 `Collector → Monitor → MonitorState → TUI` 数据流。

D-001 已由 R2 基于用户提供的样本和安装源码核对，本计划不重新要求采证。兼容范围为已冻结的 vLLM `0.31.0` profile。结果基类/兄弟子类迁移、Chat/Pooling 观测分型及静态模板已提供，直接复用；HTTP、解析、窗口、accumulator、State 专支、配置新字段、组合根及服务绘制仍待实现。不得把现有手工 vLLM 占位 spec 或可导入骨架算作完成。

REQ-004 消费 `ViewSelection`，验证不同模型选择下的详情、单位和历史；实际方向键行为及完整主题分别留给 REQ-005/006。本轮只补服务区所需颜色角色和基础 amber 映射，保持上下各半、Storage 三行、Docker 可见前缀及原最小尺寸规则。不增加 LiteLLM/WebUI 采集、推理负载、服务控制、Web 接口或监控数据持久化。

禁止尝试连接任何服务器，包含回环地址；测试保留 [conftest.py](../../../../tests/conftest.py) 的 DNS/连接防护。只使用本地资料、原始字节端口和内存传输替身，不执行采证脚本、不启动真实 vLLM、不访问 Docker socket，也不为依赖准备自行联网。

## 主要任务

前置依赖仅表示启动所必需的条件；已冻结的接口允许相关任务先使用边界替身开发。实现步骤、私有结构和主对话/subagents 分工由 R4 决定，完成时的集成顺序见下一节。

| 任务编号与标题 | 交付结果、关联需求与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 三类型原始观测解析 | 原始三份响应产生匹配模型类型的不可变观测；精确身份/版本、STOP 筛选、整数精度、字段分组与局部/整体失败符合契约，不提前计算展示值。AC-401、405、409～412；collector 解析测试及 engine_samples 结构测试。 | `collectors/vllm.py::parse_scrape`；vLLM §4～6、metric-evidence；复用既有 Chat/Pooling 数据类。 | 无新增任务前置，映射及原始样本已具备。 |
| T-002 有界 HTTP 端口与真实依赖 | 懒加载 HTTPX、单次流读取、解压后限长、超时/取消/关闭和错误归一可用；禁代理、禁重定向、启用证书校验。同步声明、锁文件和离线依赖，并以真实 HTTPX 库完成离线适配验证。AC-407、412 及隔离/退出规则；collector 的 client 测试与必要真实库接合验证。 | `AsyncHttpClient`、`pyproject.toml`、`uv.lock`、离线 wheel 集合；vLLM §9。固定版本范围 `HTTPX>=0.28.1,<0.29`。 | 接口实现可立即开始；真实库与安装验证需本地具备 HTTPX 及传递依赖，见“依赖准备条件”。 |
| T-003 配置身份与模型采集器 | 接入 `served_model_name`，省略回退展示名，显式值严格校验且兼容旧配置；全部模型按顺序独立建端口、不合并同名/同 origin 项。每轮按三路径顺序共用总预算，失败立即停止后续读取，取消传播。AC-401、407、408、412；config 及 collector/factory 用例。 | `config.py`、`VllmCollector`、`build_vllm_collectors`；配置扩展和 vLLM §9。 | 无新增任务启动前置；现有 parser、HttpPort 和配置契约已具备。 |
| T-004 差分与加权窗口 | 使用实际采样时间、逐 engine 判断连续性后求速率；首次/重置/拓扑变化返回未知，有效零正确；延迟只取完整落窗区间、按观测数加权，数值边界受控。AC-402～404、406、410、411；window 全组测试。 | `data/vllm_window.py`；vLLM §7。 | 无新增任务前置，纯输入输出契约已具备。 |
| T-005 独立模型状态与只读快照 | 每模型每组基线、窗口和历史有界；类型/身份/数值先原子校验；同次 Total、KV 平均、部分失败保值、恢复断基线、整点历史 gap 和只读过期投影正确。合法大计数溢出仅隔离该速率，不终止 Monitor。AC-401～407、409～411；state 及通用 State/Monitor 测试。 | `VllmAccumulator`、`MonitorState` 的 VllmSpec 专支；vLLM §5、7、8 及 monitor-state。 | 可依现有窗口接口开始；无需等待 HTTP 或界面。 |
| T-006 固定服务区与历史展示 | 模型列表、类型、状态和详情符合冻结槽位；三类单位、未知/零/N/A、STALE/amber、裁切、历史时间分箱及缺口正确；只读调用不重置历史。AC-401、404～411；view 全组测试及整页/终端接合。 | `tui/vllm.py`、`compose_frame` 的 `monotonic_now` 接线、`CursesTerminal` 基础 amber 映射；view-contract 和应用外壳。 | 无新增任务前置，冻结快照与 ViewSelection 已具备。 |
| T-007 统一运行期接入 | 用工厂产生的 VllmSpec 替换手工占位，全部模型与硬件/Docker 共用唯一 State/Monitor/Log；构造及日志预检查无采集，注入完整组件不再创建来源；退出关闭全部端口。AC-401、406～408、412；integration、首帧及运行期用例。 | `cli.py::ApplicationRuntime` 及必要接合点；应用外壳、vLLM §9、现有运行生命周期。 | 可依现有工厂/Spec 接口开始，不等待 REQ-005/006。 |
| T-008 离线联验与交付 | 全链路、真实依赖、Ubuntu 终端及离线安装验证完成；现有待实现失败转绿且保留既有行为；更新使用说明、实现状态和 R4 交接，证据绑定交付版本。全部 AC-401～412。 | 必要接合测试、README、随包示例说明、本需求 `evidence/` 与 `handoff-r4.md`。 | 最终联验需 T-001～T-007 完成集成且离线依赖齐备；材料准备可提前。 |

## 开发顺序与并行条件

1. 优先并行开展 T-001、T-004、T-006，并提前检查 T-002 的离线依赖。T-002/T-003/T-005/T-007 可按既定接口开始，建议顺序不等于启动阻塞。
2. T-001/T-002/T-003 都涉及 `collectors/vllm.py`，需协调写入或串行集成；T-005 涉及共享 `state.py`，必须保留普通 ObjectSpec 路径。T-006/T-007 分别触及页面与组合根，合入时保护现有硬件/Docker 接线，不重建第二套状态或调度。
3. 完成验证依次串联：T-001 + T-002 → T-003；T-004 → T-005；T-003 + T-005 → T-007；T-006 与 T-007 汇合后进入 T-008。T-003 必须调用真实 parser，T-005 必须调用真实窗口计算，联合测试不得以预先计算的结果替代这些业务。
4. T-006 可独立消费冻结快照开发；集成时用同一单调时钟域投影 State 和历史图，墙钟仅用于页眉。通过传入选择切换验证类型和历史，不借此扩大到方向键实现。
5. 定向验证通过后进行一次最终 Ubuntu 全量回归、受影响终端接合与安装验证；只有新改动、失败或未解决风险才追加复跑。出现设计/测试含义冲突时记录并交回 R2；规划调整记录到 R4 交接的“R3 修订汇总”，不通过削弱断言改变验收。

## 验证安排

### 基线及运行环境

已核对 R2 的 [完整输出](evidence/pytest-consolidated.txt) 和 [JUnit 汇总](evidence/pytest-consolidated.xml)：**1209 项，894 passed / 315 failed，0 errors / 0 skipped**。通用及既有非 vLLM 专项 862 项通过；vLLM 专项 347 项中 32 项通过、315 项待实现失败。R2 将其分为 299 项直接 NotImplementedError 和 16 项配置/状态/组合/绘制缺失，不包含导入或环境错误。

R3 本轮在本地 WSL Ubuntu-24.04、Python 3.12.3 执行 `pytest --collect-only -q`，**1209 tests collected，退出码 0**；只验证加载，没有重跑业务断言。工作目录为 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`，已有解释器为 `~/projects/tmp/joi-observer-dev-0-venv/bin/python`。不安排 Windows 全量回归。

```bash
cd /mnt/d/Documents/codex_worktree/dev0-req004/joi-observer
# 各任务按自身范围选择执行；集成后覆盖全部 vLLM 契约
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q tests/test_vllm_*.py
# 最终公共回归，包含本地 Unix PTY
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q
```

R4 须记录实际使用的环境和依赖版本；若另建离线环境，替换上述解释器路径并写入证据。完成标准是正确业务行为全部通过、无未解释错误，而非凑回固定测试总数；不能 skip/xfail 现有失败来宣告完成。

### 依赖准备条件

R3 只读检查的 venv 和 `D:\Documents\joi-observer\.pytest_cache\offline_wheels` 均没有 HTTPX 及所需传递依赖。现有 venv 足以加载当前测试，不能据此宣称已具备真实 HTTPX 或新 wheel 安装验证条件。WSL 已有 `/home/shawn/.local/bin/uv`，无需依赖 venv 中的 pip。

R4 应先盘点可用本地包/缓存，准备满足冻结版本范围的完整依赖集合，再成套更新声明与锁文件并验证离线安装；如本地材料仍缺，记录明确缺项并请求提供离线材料，不自行连接包索引或任何服务器。这只限制 T-002 的真实库验证及 T-008 最终交付，其余实现和端口契约测试可继续；材料不足时不得把对应验证标为完成。

### 验收与接合检查

| 验证主题 | 完成判定与对应任务 |
| --- | --- |
| AC-401、408、412：身份、全量与来源 | 三类实际采样、配置顺序和 id 独立；name/served_model_name 分离；仅三个配置 origin 的约定路径，无 LiteLLM/推理/额外探测；未知路由参数或并发上限不造值。T-001/003/006/007。 |
| AC-402～404、410、411：计数与窗口 | 200/2=100 tok/s、1000/2=500 tok/s、6/2=3 seq/s；(4+5)/(2+1)=3s，queue 使用自身分母。保留首次、有效零、字段独立重置、marker 可用性变化、拓扑变化、完整落窗和不可表示速率边界。T-004/005。 |
| AC-405、409：适用性与局部失败 | Chat/Pooling 原始字段分型、最终 N/A 模板、KV engine 等权平均与 GPU 显存独立；缺少适用字段不破坏有效组，失败值保留且不能拼成新 Total。T-001/005/006。 |
| AC-406、407：历史、失败恢复和隔离 | 未选中项持续采样，切换选择仍保留自身历史；任何 failure 写整点 gap，恢复首点不跨故障差分；慢模型不阻塞其他来源/按键。实际 Monitor/State/日志/Frame 接合验证 STALE 原位、错误只进日志、自动恢复、约 60 秒窗口与内存有界。T-003/005/006/007。 |
| HTTP 与资源生命周期 | 三次 GET 共用总预算；失败不请求后续路径；单响应解压后 2 MiB 上限，无 Content-Length 也受限；不重试/跳转/环境代理；取消不变业务错误；单端口清理 250ms，整体退出沿用 1s，无迟到提交。T-002/003/007。 |
| 真实 HTTPX 接合 | 使用真实库的 client/stream/response 和解压逻辑，网络边界使用内存 transport/字节流；补足压缩后超限、读取中取消、流/client 关闭、TLS 校验启用及 TLS 异常归一。保留无 DNS/连接防护；区分配置/离线错误路径证据与未执行的真实证书握手。当前 fake client 用例不能独自满足本项。T-002/008。 |
| 页面与终端 | 固定尺寸下三类型及正常→失败→恢复均不改变槽位；真实时间分箱、零点/缺口、Unicode 裁切、基础 amber 和只读性正确。按既有 PTY 方式补受影响服务区的离线终端接合，保留 q/信号恢复、首帧和 resize 回归；不以此宣告完整主题/方向键已完成。T-006/008。 |
| 生产组合与公共回归 | prepare_log 不采样、空模型不建端口、完整 components 注入不重复组装；全部端口由同一生命周期关闭。保留硬件/Docker、配置、普通结果/公共失败、日志限频及终端能力；必要接合缺口按原契约补测。T-005/007/008。 |
| 打包与安装 | 新源码、HTTPX 声明/锁/离线包匹配；最终 wheel 含新模块与示例。用隔离 uv 工具环境、离线依赖、新 shell/异目录验证裸命令及资源，TUI 验证接入离线 IO，不运行示例地址。记录源码→wheel→安装版本一致性并清理自有验证资源。T-002/008。 |

真实依赖、压缩边界、生产组合和终端接合属于已有契约的完成验证；可按需要补测试，不要求为已覆盖的数据类声明或文档编写重复测试。测试替身仅位于外部 IO/时钟/终端边界，不能替换被测解析、差分、调度、状态或绘图结果。

### 交付判定与证据边界

R4 应消除当前 315 项待实现失败并保护已有 894 项通过行为；新增必要用例按实际数量报告。更新 README 的实现状态、配置身份字段、seq/STOP 计数、延迟计时范围和不可见重启限制，保持示例监控目标与现有配置兼容。

新证据保存本需求 `evidence/`，采用 R4 专用文件名，记录命令、环境、源码/产物版本、实际结果和未验证项，保留 R2 基线。该目录已被 Git 忽略，交接时不能只依赖 diff 传递证据。前序 REQ-002 的安装说明可参考其交接文档，但旧 evidence 工具未随 Git 进入当前 worktree，复用前须确认实际存在路径并适配新依赖，不能直接引用不存在的脚本。

实采只证明单 engine 空闲窗口；多 engine、增量、故障恢复依赖源码口径与离线构造验证，指标未暴露的重启无法保证识别。真实服务负载、多 engine 部署、网络/TLS 握手和真实网络取消仍未实机演练，不能以离线通过扩大这些结论，也不作为再次连接服务器的授权。

当前没有需 R2 先修订或用户改变需求口径的事项。完成上述交付后，R4 更新本需求 `handoff-r4.md` 请求 R5 验收；跨对话推进由用户发起。

## 修订记录

- v1.0（2026-11-02）：采纳 R2 v1.3 与已核对 D-001，建立八项交付、并行条件和集成顺序；明确真实 HTTPX 离线依赖条件、公共状态迁移保护、只读固定服务区及 Ubuntu 验证，保留 REQ-005/006 边界。
