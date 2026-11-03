# dev-0 / REQ-004 R4 交接

- stage：R4
- result：ready
- work_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0\REQ-004`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-004 / AC-401～412。
- 计划依据：[plan.md](plan.md) v1.0；资源边界采用 [handoff-r2.md](handoff-r2.md) v1.4、[vllm.md](../../../design/vllm.md) v1.3，取代旧16标签约定。
- next_role：R5
- 修订：v1.3，2026-11-03；R4-DES-005 已按 R2 确认落实，R5-004-005 已修复，待 R5 复验。R5-004-001～004 与 R5-TST-003 保持关闭。分支 `codex/dev0-req004`，当前基点 `7a4e950ac4f703fa3f68c96bf05834d57b487374`；本轮未提交。

## v1.3 完整响应兼容性返修（2026-11-03）

接收 [handoff-r5.md](handoff-r5.md) v1.5。三类服务的六份已保存完整响应均含 36 标签的正常 `vllm:cache_config_info`，旧统一 16 标签上限将其拒绝。新增完整 fixture 已核对与原始响应字节及 SHA-256 一致。R2 v1.4 明确接受统一64后，R4已实施并完成完整响应、全量及安装验证。此问题是旧资源契约与目标 profile 的冲突，不是用户部署、权限或服务状态问题。

### R2 修订请求 R4-DES-005：已确认并落实统一64上限

- 关联：R5-004-005、T-001/T-008、AC-401/407/409/412、D-001。修订前实现常量、parser 接口注释、`docs/design/vllm.md` §6 与旧测试均限制16；旧“17 标签失败”测试符合旧契约，本轮由R2明确的契约修订取代，没有将其误记为测试自身错误。
- 具体提案：统一 `MAX_LABELS_PER_SERIES = 64`；恰好 64 合法，65 为整体 `response.invalid`。保留在识别/忽略任何 family 之前的标签计数、格式/转义/重复标签和数值校验；不为某条 info 设置特例，不跳过未知行检查。目标业务指标仍只接受既定的精确 2/3 标签集合，2 MiB 正文、64 KiB 单行、50000 样本及数值限制不变。
- 依据：六份完整正文最大标签数均为36，仅该 info 超过16；最大正文64449字节、最大行1054字节、最大样本495，均远低于其他上限。64容纳已证实的正常输出并保留有限余量；单行/正文总字节边界仍约束解析分配。统一上限比按 family 分支更简单，且继续避免 R5-004-001。
- 实际分工：R2同步 `docs/design/vllm.md`、parser契约注释和 `tests/test_vllm_collector.py` 新64/65边界；R4将 `src/joi_observer/collectors/vllm.py` 执行常量改为64并移除临时待实施注释。保留 R5 三个完整响应回归；R4新增完整响应 Collector→Monitor→State、安装TUI验证。R5测试中提及旧16限制的历史docstring已同步为通用边界描述，断言不变。
- 协调记录：三个 subagents 和主对话前检确认技术可行，但未擅自修改冻结资源契约。用户于2026-11-03明确选择先交R2确认，R4按指令发送提案至既有 `REQ-004-R2` 聊天（thread `01a19aec-5839-7fa2-bb24-f5f7ae74d7b0`）。R2 v1.4明确接受64后，用户回交“R2已确认”，R4才恢复实施。
- 起始快照：[r4-fix3-start.json](evidence/r4-fix3-start.json)。独立准备完整链路回归及使用完整正文的离线安装脚本，旧证据和包保留。
- 独立验证准备：新增 [test_vllm_full_response_integration.py](../../../../tests/test_vllm_full_response_integration.py)，完整三响应预读后经真实 Collector→Monitor→State 两轮采样，检查首次未知、二轮有效零、历史、错误日志与三个固定路径。WSL 命令 `python -m pytest -q tests/test_vllm_full_response_integration.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix3-fullchain-baseline.xml` 为 **1 failed**，复现正常响应被标 STALE，无环境/导入错误；[输出](evidence/r4-fix3-fullchain-baseline.txt)、[JUnit](evidence/r4-fix3-fullchain-baseline.xml)。该例没有改旧契约或替换解析业务，保留失败供修复后验证。
- 安装脚本 [r4-fix3-install](evidence/r4-fix3-install/preflight.json) 的HTTP替身使用完整正文并核对每份实际响应SHA-256；已完成新wheel和完整正文TUI验证，结果见下表。旧7a4e950服务器测试包仍含本问题，不作为005修复结果。

### R2 v1.4 回复与 R4 确认

用户已回交“R2 已确认”。R4核实并接受R2 v1.4的统一64上限、64合法/65失败、过滤前校验和目标精确schema不变的完整决定。R2已同步设计、接口注释及黑盒边界，保留执行常量16供R4实施；其188项基线为174通过/14待实现失败，没有环境错误。接收后的文件快照见 [r4-fix3-accepted-start.json](evidence/r4-fix3-accepted-start.json)。此前设计阻碍已解除，不再等待重复授权。

本次仍在计划T-001/T-008范围内，不改变任务边界、依赖或交付条件，无需先调整R3计划。R2文末的后续R3核对按用户另行指令推进，本轮不自动通知R3；先按已确认设计完成实现、完整响应链路、全量与离线安装验证。

### R5-004-005 修复结果与验证

生产运行逻辑的唯一变化是 `MAX_LABELS_PER_SERIES: 16 → 64`；去除文档字符串后，归一该常量的新旧生产AST完全一致。未知family仍先做格式、数量和数值检查，目标业务指标的精确2/3标签schema、其他资源边界、身份、局部失败和历史语义均不变。独立subagent完成代码、R2新边界和完整链路只读复核，无新增问题。

以下命令实际在 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer` 的 WSL Ubuntu-24.04 执行，`python` 为 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`（Python3.12.3、HTTPX0.28.1）。保留DNS/connect防护，没有尝试连接服务器。

| 检查 | 实际命令与结果 | 证据 |
| --- | --- | --- |
| R2边界及完整链路 | `python -m pytest -q tests/test_vllm_collector.py tests/test_vllm_collector_edges.py tests/test_vllm_full_response_integration.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix3-collector.xml`；**188 passed in 2.48s**，R2原14个待实现失败全部转绿 | [输出](evidence/r4-fix3-collector.txt)、[JUnit](evidence/r4-fix3-collector.xml) |
| 六份原始完整正文回放 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix3-full-responses.py`；六份均failure=None，观测与同轮摘录一致，原始SHA未变，network_attempts为空 | [脚本](evidence/r4-fix3-full-responses.py)、[报告](evidence/r4-fix3-full-responses.json)、[输出](evidence/r4-fix3-full-responses.txt) |
| 最终全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix3-pytest-final.xml`；**1395 passed in 26.59s，0 failed / 0 errors / 0 skipped** | [输出](evidence/r4-fix3-pytest-final.txt)、[JUnit](evidence/r4-fix3-pytest-final.xml) |
| 完整正文安装TUI | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix3-install/verify_uv_install.py --uv /home/shawn/.local/bin/uv`；exit0，result=passed | [报告](evidence/r4-fix3-install/uv-install-results.json)、[输出](evidence/r4-fix3-install/run.txt) |
| 交付审计 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix3-audit.py`；exit0，源码/测试/fixture/wheel校验通过；Windows `git diff --check` 通过，仅既有行尾提示 | [脚本](evidence/r4-fix3-audit.py)、[报告](evidence/r4-fix3-audit.json)、[输出](evidence/r4-fix3-audit.txt) |

相对先前1365项，旧单个“17标签失败”用例按R2修订被新的参数化边界替代，其余旧用例保留；总计新增31个用例ID、替代1个，净增30至1395。R2指定188项全部保留通过，不以旧测试数量不变掩盖合法契约修订。构建自动更新被忽略的egg-info元数据，审计将其与生产源码分开记录。

最新 [wheel](evidence/r4-fix3-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl) SHA-256：`20aa98f51dbad08ede22b630f2d1c0f498e4b2ae52f6275480e3444c23870609`。25份包内py/yaml与源码和已装包逐字节一致，README元数据对应本轮状态更新。新shell裸信息命令及三类首模型TUI通过；每次所有模型均使用完整metrics（64449/54707/54664字节）并核对每轮响应哈希，至少两轮采样，q返回0、termios恢复、端口关闭，无网络/外部进程尝试和遗留进程。依旧使用同进程显式离线bootstrap，无隐式hook或真实来源回退。

用户于2026-11-03明确要求“R4阶段不要生成试用包，删除”。本轮服务器试用归档、展开目录及专用生成/验证材料已移入回收站，并清除交接与当前审计对它们的依赖；R4阶段不再生成试用包，该规则已写入AGENTS.md。源码修复、1395项回归证据和内部安装验证产物保留。本次仅清理交付材料与文档，未改业务或测试代码，未重复运行产品回归。

本轮已解决已保存完整0.31.0响应的兼容性问题，等待R5复验。未读取用户当前实时正文，不能声称排除了后续部署变化；真实网络/TLS、生产负载与实机多engine/重启的既定限制保持。内部安装验证产物和evidence被Git忽略，交接时须另行携带，不能仅依赖diff。

## v1.2 第二轮返修（2026-11-03）

接收 [handoff-r5.md](handoff-r5.md) v1.2，已完成 R5-004-003 的 HTTPX 自然 EOF 释放取消竞态及 R5-004-004 的多 engine 次正规延迟舍入修复。R5-TST-003 已由严格容差补例关闭，原断言保持。主对话统筹并独立复核数值修复；collector subagent 负责 HTTP 生命周期，state subagent 负责精确窗口聚合，view subagent 独立复核 HTTP 修复及新 wheel/安装验证。全轮前检确认可行后才开始实现，无 R2 架构/公共接口或 R3 计划修订事项。起点文件哈希：[r4-fix2-start.json](evidence/r4-fix2-start.json)。所有旧产物和证据保留；本节为最新结论。

### R5-004-003 已修复：自然 EOF 的实际释放受取消保护

- 根因确认：HTTPX 在迭代器自然 EOF 内调用 `Response.aclose()`，且 HTTPX/httpcore 在底层释放完成前已设置 closed 标志；此前仅保护最终 context exit，不能补回被打断的首次释放。
- 修订位置：[collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py) 的 `_protect_httpx_response_close`（103 行）及迭代前接入（240 行）。仅对确认属于真实 HTTPX Response 的对象绑定私有关闭包装；首次底层关闭由独立任务拥有，EOF 与 context exit 共用同一任务和首次 0.2 秒截止时间，不根据 is_closed 判断资源已释放，不重启关闭或续发清理预算。
- 响应读取本身仍可取消；完成合作式释放后传播原取消/超时。保留 250ms 单端口、1s 整体退出、单次请求、解压限长、懒加载及错误分类。普通 factory response 不被修改，也不因此要求可写属性或导入 HTTPX。
- R5 的 cancel/close/timeout 三例全部转绿；[test_vllm_httpx.py](../../../../tests/test_vllm_httpx.py) 追加 6 项，覆盖 EOF 重复取消加 close、Collector 总预算超时不读后续路径、三种超预算释放、关闭异常脱敏及无遗留 asyncio 任务。独立复核通过；R4 已修复，待 R5 复验确认。

### R5-004-004 已修复：原始延迟总量全局加权后只舍入一次

- 根因确认：原实现先将每个 engine 均值转 float，再还原 Fraction 加权，无法恢复已因下溢丢失的时长。
- 修订位置：[data/vllm_window.py](../../../../src/joi_observer/data/vllm_window.py) 的私有 `_latency_totals`（140 行）复用既有完整输入校验/完整落窗逻辑，返回 Fraction 总时长和精确整数观测数；公开 `weighted_latency` 签名、返回语义保持。 [data/vllm.py](../../../../src/joi_observer/data/vllm.py) `_window_value`（203 行）逐 engine 取得精确总量，完成全局加权后仅做一次 float 转换。
- 保留各 engine 连续性、独立指标分母、原子校验、无观测 None、有效零、窗口闭区间、只读过期及大值稳定计算。两个 tiny 总时长、三个观测的最终均值正确为 `math.ulp(0.0)`，不再伪零。
- R5 非零复现及严格容差补例通过；[test_vllm_state_edges.py](../../../../tests/test_vllm_state_edges.py) 追加 24 项，覆盖三类型各延迟组、engine 顺序、跨区间舍入、完整窗口边界、只读投影与超 float 总量/巨大 count 的非零均值。主对话独立复核通过；R4 已修复，待 R5 复验确认。

### v1.2 实际验证与交付

本轮仅使用 WSL Ubuntu-24.04、Python 3.12.3、HTTPX 0.28.1、本地字节端口及内存 transport，保留 DNS/connect 防护，没有尝试连接服务器。工作目录为 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`；以下 `python` 为 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。环境、当前源码/测试 SHA-256 与用例集合见本轮审计报告。

| 验证 | 实际命令与结果 | 证据 |
| --- | --- | --- |
| HTTP/采集回归 | `python -m pytest -q tests/test_vllm_collector.py tests/test_vllm_collector_edges.py tests/test_vllm_engine_samples.py tests/test_vllm_httpx.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix2-collector.xml`；197 passed in 3.16s | [输出](evidence/r4-fix2-collector.txt)、[JUnit](evidence/r4-fix2-collector.xml) |
| 数值与状态回归 | `python -m pytest -q tests/test_vllm_window.py tests/test_vllm_state.py tests/test_vllm_state_edges.py tests/test_state.py tests/test_state_monitor_edges.py tests/test_monitor.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix2-state.xml`；277 passed in 1.30s | [输出](evidence/r4-fix2-state.txt)、[JUnit](evidence/r4-fix2-state.xml) |
| 最终全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix2-pytest-final.xml`；**1365 passed in 25.56s，0 failed / 0 errors / 0 skipped** | [输出](evidence/r4-fix2-pytest-final.txt)、[JUnit](evidence/r4-fix2-pytest-final.xml) |
| 新 wheel/离线安装 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix2-install/verify_uv_install.py --uv /home/shawn/.local/bin/uv`；exit 0，result passed | [预检](evidence/r4-fix2-install/preflight.json)、[安装报告](evidence/r4-fix2-install/uv-install-results.json)、[输出](evidence/r4-fix2-install/run.txt) |
| 交付审计 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix2-audit.py`；exit 0，result passed；Windows `git diff --check` 通过，仅既有 uv.lock 行尾提示 | [脚本](evidence/r4-fix2-audit.py)、[报告](evidence/r4-fix2-audit.json)、[输出](evidence/r4-fix2-audit.txt) |

R5 v1.2 的 **1335 项全部保留并通过**，四个失败转绿，本轮新增 30 项；两个已修改测试文件的旧字节前缀完整保留，`test_vllm_window.py` 未改，见 [前缀核对](evidence/r4-fix2-test-prefixes.json)。相对本轮起点，仅修改三个业务文件、两个测试文件和本交接，需求、设计、依赖、R5 交接及其他代码不变。没有通过放宽容差、修改旧断言或 skip/xfail 绕过问题。

最新 wheel：[joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/r4-fix2-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256 **`138f838d9aaac7cd6e7d60b295ffebaba48b65c3232e0b14bb753972f1cff230`**。25 份包内 py/yaml 与 wheel/安装包逐字节一致，README 元数据一致，源码及构建输入前后哈希未变；旧 wheel 和证据继续保留作历史引用。

uv 构建/安装使用 offline、no-index、no-python-downloads 及已有本地 wheelhouse。安装 TUI 由同一解释器进程显式加载并强校验离线 bootstrap 后调用真实已装 CLI，无隐式 hook 或真实来源回退。新 shell 异目录裸信息命令及三类首模型 TUI 通过；每次三个端口至少两轮采样，q 返回0、termios恢复、全部端口关闭，network_attempts/process_attempts 为空，所有监督进程正常回收，无强制/补救回收或遗留进程。

当前无待决设计/实现事项。真实服务、网络/TLS 连接释放、生产负载、实机多 engine/重启仍未验证；本轮证明真实 HTTPX **内存 transport** 的释放完成，不能据此宣称测量了真实 socket 泄漏数量。R4-VAL-001 历史偏离继续保留。

## v1.1 首轮返修记录（历史，2026-11-03）

接收 [handoff-r5.md](handoff-r5.md) v1.0 的 R5-004-001/002，已完成修复。主对话统筹、collector subagent 修复，state subagent 独立核对契约和复核实现，view subagent 刷新隔离安装证据。全轮前检通过后开始实施；无需 R2 修改架构/接口或 R3 调整计划。起始文件哈希保存于 [r4-fix1-start.json](evidence/r4-fix1-start.json)。前一轮证据保留；本节是最新返修结论，后续 v1.0 记录只作历史引用。

### R5-004-001 已修复：过滤行的数值校验

- 原因确认：other-model、bucket、non-STOP 分支在检查数值 token 前退出，导致非法 exposition 被接受为新鲜数据。
- 修订位置：[collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py) 的 `_check_ignored_value`（417 行）及过滤调用（477/482/498 行）。忽略未知指标、其他模型、bucket、非 STOP series 前先验证词法、128 字符、指数绝对值 400 及展开整数 400 位上限。合法负数、小数及 NaN/±Inf 独立 series 继续忽略，不累加 bucket 或改变 STOP 范围。
- 适用业务字段继续由原有组内校验处理；坏计数/直方图仍为局部失败，未把这些字段改成全对象失败。
- 保留 R5 三项失败用例及原断言；[test_vllm_collector_edges.py](../../../../tests/test_vllm_collector_edges.py) 补 16 项资源边界与 4 项合法忽略值用例。修复及独立复核通过，待 R5 复验确认。

### R5-004-002 已修复：非法压缩正文分类

- 原因确认：HTTPX DecodingError 原先进入通用 HTTPError 处理，被归为运输不可用。
- 修订位置：同采集模块 229 行，在通用 HTTPError 前识别 DecodingError，通过既有私有 `_InvalidResponse` 通路转为 `parse/response.invalid`。不增加公共接口，不改变懒加载或注入 factory 时不导入 HTTPX 的约定；超时、网络/TLS 分类及 finally 清理保持。
- 保留 R5 非法 gzip 用例；[test_vllm_httpx.py](../../../../tests/test_vllm_httpx.py) 补第二路径 gzip 尾部校验损坏用例，验证不继续读 `/metrics`、无正文泄漏、响应流/client 关闭。修复及独立复核通过，待 R5 复验确认。

### 本次实际验证与新交付

环境沿用下文 WSL Ubuntu-24.04、Python 3.12.3 与 HTTPX 0.28.1；工作目录为 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`，下列 `python` 为 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。

| 验证 | 实际命令与结果 | 证据 |
| --- | --- | --- |
| 定向回归 | `python -m pytest -q tests/test_vllm_collector.py tests/test_vllm_collector_edges.py tests/test_vllm_engine_samples.py tests/test_vllm_httpx.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix1-collector.xml`；188 passed in 2.37s | [输出](evidence/r4-fix1-collector.txt)、[JUnit](evidence/r4-fix1-collector.xml) |
| 最终全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix1-pytest-final.xml`；**1330 passed in 25.14s，0 failed / 0 errors / 0 skipped** | [输出](evidence/r4-fix1-pytest-final.txt)、[JUnit](evidence/r4-fix1-pytest-final.xml) |
| 新 wheel 与安装 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix1-install/verify_uv_install.py --uv /home/shawn/.local/bin/uv`；exit 0，result passed；uv 构建/安装均使用 offline、no-index、no-python-downloads 和本地 wheelhouse | [预检](evidence/r4-fix1-install/preflight.json)、[报告](evidence/r4-fix1-install/uv-install-results.json)、[输出](evidence/r4-fix1-install/run.txt) |
| 产物核对 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-fix1-audit.py`；exit 0，result passed；Windows `git diff --check` 通过，仅 uv.lock 既有行尾提示 | [审计脚本](evidence/r4-fix1-audit.py)、[报告](evidence/r4-fix1-audit.json)、[输出](evidence/r4-fix1-audit.txt) |

R5 的 **1309 个用例 ID 全部保留并通过**，其中四项缺陷复现转绿；本次只新增 21 项用例。相对返修起点，仅改一个业务模块、上述两个测试文件和本交接单，范围及最终源码/测试 SHA-256 由审计报告记录。独立 subagent 复核确认修复与冻结契约一致；需求、设计、依赖和 R5 交接均未修改。

最新交付 wheel：[joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/r4-fix1-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256 **`b20eceedb18a0d6116ad72fa6869eab8adcb7a2fd8aeb722db96c9b734646a7b`**。25 份包内 py/yaml 与 wheel/已装包逐字节一致，README 元数据及构建输入哈希一致；旧 wheel 与旧验证报告完整保留，仅作历史证据。

本次安装先复核已修正的显式防护脚本，再在同一安装解释器进程加载并校验 DNS/connect/进程和全部来源 factory 防护后调用真实 CLI；无隐式 hook 或裸 TUI 回退。新 shell 异目录裸信息命令通过，三类首模型 TUI 均至少完成两轮采样，q 返回0、termios 恢复、每次三个端口全部关闭，network_attempts/process_attempts 均为空，监督器无强制/补救回收及遗留进程。本次验证未尝试连接服务器；前次 R4-VAL-001 偏离记录继续保留，不因返修成功覆盖。

没有新的待决事项或未解决实现问题。真实目标服务、生产负载、网络/TLS 握手及实机重启仍不在本地离线验证范围，不因本轮通过扩大保证。

## v1.0 产物记录

一个主对话负责配置、生产组合、依赖和最终联验；三个 subagents 分别负责采集 T-001/002/003、窗口状态 T-004/005、服务区 T-006及安装验证。写入范围分离，已有未提交 R2/R3 产物保留；没有改需求、计划或公共接口，没有创建或推进 R2/R3/R5 聊天。

| 任务 | 实现与产物 | 状态 |
| --- | --- | --- |
| T-001 三类型解析 | [collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py)：精确版本/身份、Prometheus 标签与数值上限、Chat/Pooling 分型、STOP 筛选、局部/整体失败 | 完成 |
| T-002 HTTP 与依赖 | 同文件：懒加载 HTTPX、有界解压流、单次请求、取消/清理及错误归一；[pyproject.toml](../../../../pyproject.toml)、[uv.lock](../../../../uv.lock)、完整本地 wheel 集合 | 完成 |
| T-003 配置与采集器 | [config.py](../../../../src/joi_observer/config.py) 的 served_model_name；所有模型独立 factory/端口，三路径共用总预算，失败立即停止 | 完成 |
| T-004 差分与窗口 | [data/vllm_window.py](../../../../src/joi_observer/data/vllm_window.py)：逐 engine 精确整数差分、重置与拓扑判断、完整落窗及按观测数加权 | 完成 |
| T-005 状态与快照 | [data/vllm.py](../../../../src/joi_observer/data/vllm.py)、[state.py](../../../../src/joi_observer/data/state.py)：每模型每组独立基线、有界窗口、原子验证、失败保值/gap、只读过期投影 | 完成 |
| T-006 服务区 | [tui/vllm.py](../../../../src/joi_observer/tui/vllm.py)、[layout.py](../../../../src/joi_observer/tui/layout.py)、[app.py](../../../../src/joi_observer/tui/app.py)：三类型固定槽、状态/单位、时间分箱历史、Unicode 裁切、基础 amber 映射和单调时钟接线 | 完成 |
| T-007 统一运行期 | [cli.py](../../../../src/joi_observer/cli.py)：工厂来源替代手工占位；共享唯一 State/Monitor/ErrorLog；prepare 不采样、注入组件不重建、统一关闭 | 完成 |
| T-008 联验交付 | [README.md](../../../../README.md)、[示例配置](../../../../src/joi_observer/examples/config.yaml)；全量回归、新旧链路及隔离安装复验完成，证据绑定当前源码 | 完成 |

新增测试：`tests/test_vllm_collector_edges.py`、`test_vllm_httpx.py`、`test_vllm_state_edges.py`、`test_vllm_runtime.py`、`test_vllm_pty.py`；`test_vllm_view.py` 补边界。相对 R2 的 1209 个用例 ID 全部保留，新增 75 项，原 315 个待实现失败全部转绿，原 894 项继续通过。

## v1.0 验证证据（历史）

- 开发前检查：三组及主对话已核对需求、设计、接口和黑盒测试，全轮无阻碍；在汇总完成后才启动实现。
- 基线引用 R2：1209 项，894 passed / 315 failed；本轮未重复将未实现业务作为环境故障。
- 本地 WSL 的 pip 缓存发现 HTTPX 0.28.1 与全部传递依赖原始 wheel；只复制原字节，来源及 SHA-256 记录于 [r4-offline-wheels.json](evidence/r4-offline-wheels.json)。恢复脚本：[r4_find_wheels.py](evidence/r4_find_wheels.py)。未下载、未重打包依赖。
- 必需测试使用 WSL Ubuntu-24.04；pytest 保留 DNS/连接防护。安装首轮验证的隔离脚本未加载，意外触发 `offline.invalid` 请求尝试；该偏离及修复单独记录，不能宣称全程无网络尝试。

环境：WSL Ubuntu 24.04 x86_64、Python 3.12.3；解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`；HTTPX 0.28.1、httpcore 1.0.9、anyio 4.15.1、PyYAML 6.0.3、pytest 8.4.2。环境与当前源码/测试/依赖 SHA-256 见 [r4-source-environment.json](evidence/r4-source-environment.json)，绑定本轮未提交工作树；旧 R2/R3 证据保留。

以下实际命令在 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer` 执行；`python` 指上述解释器。

| 检查 | 实际命令 / 结果 | 证据 |
| --- | --- | --- |
| 最终全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-pytest-final.xml`；**1284 passed in 26.74s，0 failed / 0 errors / 0 skipped** | [完整输出](evidence/r4-pytest-final.txt)、[JUnit](evidence/r4-pytest-final.xml) |
| 采集定向 | `python -m pytest -q tests/test_vllm_collector.py tests/test_vllm_collector_edges.py tests/test_vllm_engine_samples.py tests/test_vllm_httpx.py`；163 passed | [r4-collector.txt](evidence/r4-collector.txt) |
| 窗口/状态/公共回归 | `python -m pytest -q tests/test_vllm_window.py tests/test_vllm_state.py tests/test_vllm_state_edges.py tests/test_state.py tests/test_state_monitor_edges.py tests/test_monitor.py`；245 passed | [r4-state.txt](evidence/r4-state.txt) |
| 视图/真实终端 | `python -m pytest -q tests/test_vllm_view.py tests/test_vllm_pty.py tests/test_tui.py tests/test_terminal_pty.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r4-view.xml`；132 passed；18帧三类型×正常/STALE/恢复×36/48行，实际 curses 色对/柱图、q、termios 恢复 | [r4-view.txt](evidence/r4-view.txt)、[JUnit](evidence/r4-view.xml) |
| 运行期联验 | `python -m pytest -q tests/test_vllm_runtime.py tests/test_vllm_integration.py tests/test_integration.py tests/test_shell_edges.py --tb=short`；22 passed；真实 parser→Monitor→State→Frame 三类型局部失败恢复、日志、未选中项持续采样和空/注入装配 | [r4-runtime.txt](evidence/r4-runtime.txt) |
| 硬件终端接合 | `python -m pytest -q tests/test_integration.py tests/test_shell_edges.py tests/test_hardware_pty.py`；20 passed | [r4-view-shell.txt](evidence/r4-view-shell.txt) |
| 静态/依赖 | `python -m compileall -q src tests`、`uv --offline lock --check --python /usr/bin/python3.12 --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels`、Windows `git diff --check` 均通过 | 锁解析 15 packages；Git 只有既有 LF/CRLF 提示，无 diff whitespace 错误 |
| 离线安装最终复验 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r4-install/verify_uv_install.py --uv /home/shawn/.local/bin/uv --wheel docs/dev-workflow/dev-0/REQ-004/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl`；exit 0 / result passed | [最终报告](evidence/r4-install/uv-install-results.json)、[输出](evidence/r4-install/run.txt)、[脚本](evidence/r4-install/verify_uv_install.py) |

交付 wheel 为 [joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256 `0c62c9f3a6b40737b8aaf57f510d0c95ce7aeb9173fa9af45e306ab4a6ab12bc`。初次以 `uv --offline --no-python-downloads build --wheel --python /usr/bin/python3.12 --no-index --find-links <当前worktree>/.pytest_cache/offline_wheels --out-dir <req_dir>/evidence/r4-install/wheels <当前worktree>` 构建，修复验证脚本后复用同一 wheel，没有替换产品版本。

最终安装证据确认所有源码 py/yaml 与 wheel、已装包逐字节一致，README 元数据一致，源码及 README/pyproject/uv.lock 前后哈希未变。隔离 uv 工具 home/bin/cache，`tool update-shell` 后，新 shell 在异目录用真实裸命令验证 `--version`、`--example-config`，无激活环境或 source PYTHONPATH。TUI 用安装解释器同进程显式离线防护 wrapper 调用真实已装 CLI（不宣称这一部分直接用了裸 TUI 命令）；三类分别作为首模型，每次所有三个端口至少两轮采样，READY、单位和历史正确，q 返回0、termios恢复、所有端口关闭。最终三次运行 network_attempts/process_attempts 为空，自有进程监督器无需 forced/reaped 修复，remaining 为空，全部进程已回收。

本需求 evidence/ 和 `.pytest_cache/offline_wheels` 被 Git 忽略，交接时须保留或单独携带实际文件；不能只传 Git diff 并假定日志、wheel 和依赖会随仓库存在。

交付前再次只读核对源码/测试 manifest、最终 wheel 哈希、全部交接链接及三类安装 TUI 报告，结果见 [r4-final-verification.json](evidence/r4-final-verification.json)。必需产品验证均在 Ubuntu 执行；Windows 此处仅核对文件字节和文档链接。

真实 HTTPX 接合使用 AsyncClient/MockTransport/AsyncByteStream，覆盖 gzip 解压后 2 MiB 边界、读中取消、关闭竞态、流与 client 释放、TLS 校验配置和 TLS 异常归一；不把这些结果称为真实网络或证书握手验证。多 engine、计数增量、故障及重启规则为离线构造验证，已有用户样本仅证明单 engine 空闲窗口。生产负载、实机多 engine/重启、真实网络/TLS 握手仍未验证，指标未暴露的隐蔽重启不能保证识别。

## 本轮决策

- 保留冻结架构与结果分型，普通 ObjectSpec 路径不按命名空间猜测 vLLM；模型仅通过 VllmSpec 使用 accumulator。所有速率与窗口在状态层计算，展示只读。
- 计数使用精确整数，窗口采用有界 engine 分片和稳定加权运算；合法大计数造成的派生溢出只使对应速率未知，不终止 Monitor。
- R4 内部复核发现并修复：不可打印 engine 标签穿过 parser 导致 State 异常；get 取消后的流清理被 close/再次取消打断。补充真实链路及真实 HTTPX 内存流回归；不改公共契约。
- REQ-005 方向键导航与 REQ-006 完整双主题未扩入本轮。当前默认首模型；传入 ViewSelection 的三类型详情、历史和布局已验证。没有新增推理负载、服务控制、Web/LiteLLM/WebUI 采集或指标持久化。
- 无需 R3 调整计划或 R2 修改架构/接口。以下两项仅为依据既定契约修正测试自身错误，保留全部验收断言。

## R2 修订汇总

### R4-TST-001 通用集成测试的旧 vLLM 占位字段

- 关联任务与产物：T-006/T-007，`tests/test_integration.py`。
- 问题与依据：旧 OfflineSource 使用 `RUNNING` 占位字段及 `RUNNING: 0` 文本断言；冻结 vLLM 模板字段为 `running`，显示槽分开绘制标签和值。
- 处理与请求：按既定字段契约把测试自身过时的两个 `RUNNING` 输入改为 `running`；原显示断言 `RUNNING: 0` 保留，未削弱首帧、持续刷新、退出和恢复验收含义；完成后附实际验证。向 R2 记录告知，无需变更公共接口。
- R2 回复与 R4 确认：尚无跨对话交接；本问题为 R4 可自行修正的测试错误。

### R4-TST-002 超时测试边界包含 WSL 文件读取抖动

- 关联任务与产物：T-003/T-007，`tests/test_vllm_integration.py::RawHttp`。
- 问题与依据：替身每次 get 同步读取 `/mnt/d` fixture，10ms collector / 20ms Monitor 超时测试出现未阻塞模型 STALE；实测首轮 1 failed / 21 passed。
- 处理与请求：仅在 RawHttp 构造时预读三份 fixture，get 返回已接收的内存字节；保留原超时预算、阻塞控制、业务链路与全部断言。定向复验 22 passed，最终全量 1284 passed。属于测试自身 IO 替身修复，告知 R2，不改变验收含义。
- R2 回复与 R4 确认：本轮无跨对话推进。

## 验证脚本偏离与修复

### R4-VAL-001 首次安装 TUI 的离线 hook 未加载

- 首次构建、源码/wheel 一致性、隔离 uv 安装和新 shell 信息命令通过，但 Ubuntu 优先加载 `/usr/lib/python3.12/sitecustomize.py`，同名临时 hook 未生效。TUI 使用测试配置 `offline.invalid`，出现真实本地 CPU/RAM 数据和模型 STALE，说明隔离失效并触发测试域名请求尝试；未使用部署服务器地址。没有底层 syscall 网络审计，不能据此断言 DNS/connect 的具体执行结果，更不能宣称全程没有尝试连接。
- 已停止重试，由自有进程监督器结束该会话并检查无遗留进程；完整失败证据保留为 [uv-install-first-failure.json](evidence/r4-install/uv-install-first-failure.json)、[run-first-failure.txt](evidence/r4-install/run-first-failure.txt)。
- 修复完成：信息命令保留裸命令验证；TUI 改为同一安装解释器进程显式加载离线 bootstrap、校验所有禁连/进程与硬件/Docker/vLLM 工厂边界及已装 CLI 路径后调用真实 CLI，任何加载/校验错误立即退出，无隐式 hook 回退。主对话与另一 subagent 独立只读复核通过后执行，同一 wheel 三类 TUI 复验通过，最终报告记录所有禁止边界尝试列表为空。
- 首次失败没有保存最终监督器 cleanup report，不能补称已有完整清理日志；补充只读检查确认临时目录已移除，`/proc` 中无该会话路径的进程，见 [first-failure-followup.json](evidence/r4-install/first-failure-followup.json)。首次偏离是 R4 验证脚本错误，已向用户报告并保留证据，不能因最终成功覆盖这段事实。

## 下一步

接收角色 **R5**：请按R2 v1.4 / vLLM设计v1.3复验本交接顶部 **R5-004-005** 的64/65资源边界、完整响应parser与Collector→Monitor→State、1395项回归、完整响应安装TUI，使用 `r4-fix3-*` 证据。R4-DES-005已确认并落实，无待决设计/实现事项；`ready`仅代表R4具备交接条件，不表示已由R5关闭005。原R5-004-001～004与R5-TST-003保持关闭，旧包只作历史引用。

如发现问题，请在 `handoff-r5.md` 的“R4 修订汇总”记录可复现证据并由用户交回 R4。跨角色对话继续由用户人工推进，本轮未自动联系 R5。
