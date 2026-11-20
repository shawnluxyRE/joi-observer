# dev-1 / REQ-001 R4 交接

- stage：R4
- result：ready
- 修订：v1.9，2026-11-17；统一修复 R5-FIX-004 硬件构造失败分支、015 测试误判和014示例说明，待 R5 独立复验。
- work_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-1
- req_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-001
- 需求依据：[requirements.md](../requirements.md) v1.3，REQ-001 / AC-101～114；本轮直接关联 AC-101、104、111、114。
- 计划依据：[plan.md](plan.md) v1.0 / T-002、T-004、T-008。
- 审查输入：[R5 交接](handoff-r5.md) v1.16；冻结前的 [R4 输入](evidence/R4/fix004-014-015-input-handoff-r4.md)及 [R5 输入](evidence/R4/fix004-014-015-input-handoff-r5.md)。
- next_role：R5

## 产物

本轮处理004重开的新分支及015、014。主对话与三个 subagents 分别预检硬件资源回收、测试诊断/示例说明、独立补测及复审；汇总确认无设计、公共接口或计划阻碍后实施。R5 v1.16 已关闭的其他问题保持关闭；ready 不代表已通过本轮 R5 验收。

| 问题 / 文件 | 本轮改动 |
| --- | --- |
| 004 / [collectors/_local_io.py](../../../../src/joi_observer/collectors/_local_io.py) | 清理再次等待 spawn 发生异常后，按 Task 是否结束分流。终态构造异常仍继续关闭已取得的 writer/读 transport；成功竞争则取回实际 child；仍待完成的 spawn 保留登记的迟到 owner 和 writer，直至真实创建结束。原始异常、取消、回收期限和同端口后续采样保持。不添加 MemoryError 特例。 |
| 015 / [test_codec_backpressure_edges.py](../../../../tests/test_codec_backpressure_edges.py) | 两处最终诊断断言改为同一私有 helper；只将标准 base_events._run_once 的结构化慢回调 WARNING 单独记录为 JUnit 性能信息，其余 asyncio WARNING 和所有 ERROR 仍使检查失败。原两测试函数除最后一次诊断调用外 AST 完整保留，所有期限、PID、Task、transport 和 loop_errors 断言不变。无全局日志过滤或阈值调整。 |
| 014 / [examples/config.yaml](../../../../src/joi_observer/examples/config.yaml) | 注释明确列表使用 name，详情使用 served_model_name，省略时回退 name；保留采集身份须匹配的说明。YAML 数据值完全不变。 |
| 004 / [test_hardware_spawn_failure_edges.py](../../../../tests/test_hardware_spawn_failure_edges.py) | 新增 5 项：真实 Popen 的 MemoryError/RuntimeError/ValueError、同端口失败后恢复、取消/close 与稍后构造失败竞争。断言原错或取消结果、四个真实 fd/transport 回收、Task 收束及幂等关闭。 |
| 015 / [test_asyncio_diagnostics.py](../../../../tests/test_asyncio_diagnostics.py) | 新增 7 项：真实默认 debug loop 的 0.11s callback 确定性生成旧规则会误判的慢回调；验证其被记录为性能信息，并验证资源/未观察异常/相似文本及慢回调混合错误仍被拒绝。 |

本轮修改一份运行实现、一份示例注释及一份既有测试，新增两份测试共12项。除015按R5明确请求修正的两处诊断检查外，所有其他既有测试逐字节保留，包含R5本轮新增13项及原失败参数。未改需求、设计、依赖、部署、公共契约、采集计算或产品期限。额外产物均位于 [evidence/R4](evidence/R4/)。

## 验证证据

实际平台为本地 WSL Ubuntu-24.04、Python3.12.3、pytest8.4.2，复用既有依赖。主对话原生副本为 /home/shawn/projects/tmp/joi-r4-fix004-014-015-20261117/baseline 与 /home/shawn/projects/tmp/joi-r4-fix004-014-015-20261117/final，不覆盖前轮副本。

[可重跑脚本](evidence/R4/fix004-014-015-verify.py)记录冻结、实际命令、结果、性能提取和保留核对；[基线清单](evidence/R4/fix004-014-015-baseline-snapshot.json)为167份文件，[最终清单](evidence/R4/fix004-014-015-final-snapshot.json)为169份，覆盖源码、测试、设计、部署、入口和依赖，排除缓存、egg-info和evidence。

| 实际执行 | 结果与证据 |
| --- | --- |
| 主对话修改前原样全量 | **2586 passed、1 failed，61.25s，无error/skipped**。唯一失败为R5硬件Popen MemoryError参数的四fd泄漏；本次未再出现015偶发误判，不据此撤销R5已观察结果。[输出](evidence/R4/fix004-014-015-baseline-full.txt)、[JUnit](evidence/R4/fix004-014-015-baseline-full.xml)、[结果](evidence/R4/fix004-014-015-baseline-full-result.json)。 |
| 004 新5项加R5原三参数红→绿 | subagent独立原生副本：旧产品 **6 failed、2 passed，0.31s**；修复后 **8 passed，0.24s**。失败断言在救援前检查真实fd，正常/EAGAIN对照保留。[脚本](evidence/R4/fix004-014-015-hardware-tests-verify.py)、[红输出](evidence/R4/fix004-014-015-hardware-before.txt)、[红JUnit](evidence/R4/fix004-014-015-hardware-before.xml)、[红命令/SHA](evidence/R4/fix004-014-015-hardware-before-result.json)、[绿输出](evidence/R4/fix004-014-015-hardware-after.txt)、[绿JUnit](evidence/R4/fix004-014-015-hardware-after.xml)、[绿命令/SHA](evidence/R4/fix004-014-015-hardware-after-result.json)。 |
| 004 原硬件IO/分配失败专项 | 实现subagent实跑 **38 passed，5.96s**，含原R5三参数、取消与原资源回归。[输出](evidence/R4/fix004-014-015-hardware-targeted.txt)、[JUnit](evidence/R4/fix004-014-015-hardware-targeted.xml)。 |
| 015 确定性诊断及相关专项 | subagent原生副本实跑新增7项、原背压7项及展示元数据回归，**51 passed，3.92s**。真实默认0.1s阈值下callback观测0.110505s，旧全拒规则必会误判，新检查记录性能且仍拒绝其他warning/error；不是靠原样重复全量直到绿。[脚本](evidence/R4/fix004-014-015-diagnostics-verify.py)、[输出](evidence/R4/fix004-014-015-diagnostics.txt)、[JUnit](evidence/R4/fix004-014-015-diagnostics.xml)、[命令/AST/YAML/SHA核对](evidence/R4/fix004-014-015-diagnostics-result.json)。 |
| 主对话最终11文件整合专项 | 硬件、分配失败、诊断/背压、运行期/服务关闭、元数据展示及客户端失败结果 **158 passed，15.93s**。[输出](evidence/R4/fix004-014-015-targeted.txt)、[JUnit](evidence/R4/fix004-014-015-targeted.xml)、[完整命令/结果](evidence/R4/fix004-014-015-targeted-result.json)。 |
| 主对话最终全量 | **2599 passed，63.36s，无failed/error/skipped**。原2587项全部保留并通过，新增12项全部通过。[输出](evidence/R4/fix004-014-015-final-full.txt)、[JUnit](evidence/R4/fix004-014-015-final-full.xml)、[结果](evidence/R4/fix004-014-015-final-full-result.json)、[PTY证据](evidence/R4/fix004-014-015-final-full-pty/)。 |
| 最终性能信息与资源期限分开核对 | 确定性callback为0.110334s；原背压7场景的性能记录单独保留，本次无其他慢回调。主动client.close约0.0037/0.0040s，service三种退出约0.0143～0.0164s；首/后帧从背压出现后到失败约0.3672/0.3845s（其完整帧构造预算仍0.5s）。[提取与评估](evidence/R4/fix004-014-015-diagnostics-observations.json)。没有将启动debug阈值当作产品期限，也不据此承诺任意环境性能。 |
| 源码、原断言及示例保留核对 | 除两处最终诊断调用外原背压测试AST/顺序完整保留，其他原测试逐字节一致；原用例无缺失；示例parsed YAML值不变。最终169文件SHA与工作区一致，基线未覆盖，git diff --check通过。[核对JSON](evidence/R4/fix004-014-015-verification.json)。 |
| 独立R4复审 | 核对spawn终态/待完成分流、原错/迟到所有权、诊断精确分类、原有效断言和示例语义，无剩余阻碍；8项硬件测试为复审者实际执行，51项诊断为明确引用。[复审JSON](evidence/R4/fix004-014-015-review.json)、[复审核对脚本](evidence/R4/fix004-014-015-review-verify.py)。 |

专项有重叠，不与全量相加。最终全量实际命令：

~~~sh
cd /home/shawn/projects/tmp/joi-r4-fix004-014-015-20261117/final
JOI_PTY_EVIDENCE_DIR=/mnt/d/Documents/joi-observer/docs/dev-workflow/dev-1/REQ-001/evidence/R4/fix004-014-015-final-full-pty \
  /home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=/mnt/d/Documents/joi-observer/docs/dev-workflow/dev-1/REQ-001/evidence/R4/fix004-014-015-final-full.xml
~~~

[交接静态检查](evidence/R4/fix004-014-015-handoff-check.json)核对链接、历史编号与摘要长度、产品AST及最终源码SHA。

## 本轮决策与验证边界

004沿用重开的原编号，014/015沿用R5编号，本轮不新增问题编号。各修复符合既定资源所有权、名称映射和测试验证含义，无需改R2公共契约或R3任务边界。

004按实际spawn状态处理，不根据某一种异常名称决定是否回收；没有真实child的构造失败仍关闭已取得管道，而尚在创建中的child保留迟到owner，不提前关闭其引用的writer。原清理自身失败后保持资源可达、允许后续close重试的边界不变。

015仅区分标准库慢回调性能消息与回收故障诊断。未知WARNING、所有ERROR、loop异常、真实fd/PID/Task/transport和原退出预算仍受断言约束。默认slow_callback_duration和产品期限均未提高，日志未全局屏蔽。014只纠正文案，不声称原显示运行行为有故障，也未新增固定注释文本单元测试。

全部验证未连接任何本地或远程服务器，包括AF_UNIX listener；HTTP/Docker/传输为离线端口，真实pipe/fd、子进程、flock及PTY仅本地受控执行，红基线救援在失败观测后清理所建资源。未下载依赖、安装/启用systemd、验证真实账户/设备权限、产品服务连通或开机管理。原容量/终端适用测试纳入全量；旧额外全字符扫描、独立容量/性能报告不冒称本轮重新执行。未生成安装包、更新历史GUI/回放或实施REQ-002；不承诺有限离线检查涵盖任意资源或环境故障。

## R5 返修汇总

### R5-FIX-004 [P2] 重开：子进程构造分配失败绕过硬件管道回收

- 问题依据：[R5 v1.16](handoff-r5.md)，AC-101、104、111，T-002/T-004/T-008；spawn Task内实际Popen构造失败后二次等待只捕获OS/取消异常，跳过writer/读transport回收。
- 处理与验证：按spawn Task终态与待完成状态统一分流；构造任意受支持异常后先释放既有管道，原错继续传播，成功竞争可取回child，迟到spawn仍被登记持有。原R5三参数及新增5项全部通过，MemoryError/RuntimeError/ValueError失败后同端口恢复、cancel/close竞争均回收四个真实fd；原相关38项和最终2599项全量通过。
- R5复验与状态：**已修复，待R5独立复验确认**；不自行将重开问题标记closed。004其他历史修复及原回归保持通过。

### R5-FIX-015 [P2] 测试将普通debug慢回调误判为资源回收失败

- 问题依据：[R5 v1.16](handoff-r5.md)原生基线的0.101s启动慢回调，实际回收仅0.012s；AC-111、T-008。本轮原样基线未再次偶发，但有确定性同类日志验证。
- 处理与验证：两处末尾全拒WARNING断言改为精确结构化分类并记录JUnit性能信息，其余原资源/期限/异常检查AST不变；新7项验证真实默认debug loop慢回调、其他资源/未观察异常/相似日志及混合错误。51项专项、158项整合和2599项全量通过，原7场景资源结果与性能信息分开记录。
- R5复验与状态：**已纠正测试检查，待R5独立复验确认**；不是调高阈值、全局忽略WARNING或削弱真实资源断言。

### R5-FIX-014 [P3] 随包示例错误说明name会用于模型详情标题

- 问题依据：[R5 v1.16](handoff-r5.md)，共同约束14、AC-114、T-008；原示例注释与已正确实现的列表/详情字段用途不一致。
- 处理与验证：说明列表name、详情served_model_name以及缺省name回退，保留精确采集身份说明；YAML值语义比较不变，既有元数据/实际视图回归及完整全量通过。
- R5复验与状态：**已修正文案，待R5独立复验确认**；不改变运行行为，不新增注释字符串测试。

## R2 修订汇总

R5-FIX-015为R4自编测试的检查错误，已按既定契约及R5明确请求自行纠正；完整原因、修改和证据见上文同号“R5返修汇总”。本条向R2同步知悉测试验证方式的纠正，不请求改变设计或验收含义，无需等待新决定，也不阻塞交R5复验。本轮未通过工具向其他独立对话发送消息。

## 历史摘要

| 原编号 | 问题简述 | 最终状态 | 处理与验证摘要 |
| --- | --- | --- | --- |
| R4-FIX-001 | 日志线程后fork编解码存在多线程风险。 | closed | 独立解释器与有界私有管道，响应及回收原回归本轮通过。 |
| R4-FIX-002 | 首连关闭与并发close没有统一收束点。 | closed | 首连及关闭owner统一，分配失败原回归本轮通过。 |
| R4-FIX-003 | 监听清理次生错误覆盖原始启动异常。 | closed | 原始异常保留，同族二次故障原回归本轮通过。 |
| R4-FIX-004 | 迟到清理异常未被观察。 | closed | 已有任务收束并观察结果，相关原回归本轮通过。 |
| R5-FIX-001 | 分层重计期限，来源可能晚于放锁结束。 | closed | R5已复验，共享期限及来源先收束后放锁原回归通过。 |
| R5-FIX-002 | 日志线程资源失败及部分启动导致停采或双writer。 | closed | R5已复验，ticket准入和恢复原回归本轮通过。 |
| R5-FIX-003 | stop竞争吞掉服务内部错误，CLI误退出0。 | closed | R5已复验，真实fatal及信号优先原回归本轮通过。 |
| R5-FIX-005 | 深层YAML和路径访问错误未归一ConfigError。 | closed | R5已复验，stat/lstat及深度错误退出2原回归本轮通过。 |
| R5-FIX-006 | 合法共享alias图被指数展开。 | closed | R5已复验，节点/语境复用、懒定位及合法DAG原回归通过。 |
| R5-FIX-007 | 客户端FAILED后q覆盖失败，CLI误退出0。 | closed | R5已复验，结果保存、原失败及双会话隔离回归通过。 |
| R5-FIX-008 | 默认CLI提前访问失效cwd，信息及非TTY入口崩溃。 | closed | R5已复验，路径按需读取和安全退出原回归通过。 |
| R5-FIX-009 | Unicode列宽低估，同源测试遗漏越槽。 | closed | R5已复验，后端宽度及真实ncurses/locale独立控制原回归通过。 |
| R5-FIX-010 | 缺失或关闭标准流使TTY检查抛原始异常。 | closed | R5已复验，安全探测与连接前退出3原回归通过。 |
| R5-FIX-011 | 显式falsey Callable被默认工厂替换。 | closed | R5已复验，None-only工厂选择及离线接线原回归通过。 |
| R5-FIX-012 | 主机展示控制/双向字符进入协议校验，导致零采样退出。 | closed | R5 v1.16确认服务投影前净化与原读取/严格协议保留；本轮原回归通过。 |
| R5-FIX-013 | stdout背压使worker清理挂起，帧期限与退出无法完成。 | closed | R5 v1.16确认先释放读管道再回收；本轮原真实背压/失败/退出回归通过。 |

## 下一步

接收角色 **R5**，本轮结论 **ready**。请统一独立复验004重开的硬件分支、015确定性诊断分类及014随包说明：保留原三参数与全部R5十三项补测，核对新十二项、真实fd/后续采样/取消/迟到所有权、原有效断言和期限保留、示例语义及完整回归，再决定是否关闭问题并通过验收。

由用户安排R5独立复验；本轮不自动向独立对话发送消息，不连接产品服务或推进REQ-002。
