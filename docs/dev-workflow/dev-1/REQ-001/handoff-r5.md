# dev-1 / REQ-001 R5 验收交接

- stage：R5
- result：passed
- 修订：v1.17，2026-11-17；按用户要求完成旧问题复验与再次全范围审查，R5-FIX-001～015全部关闭，未确认新增bug。
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-1`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-001`
- 需求依据：[requirements.md](../requirements.md) v1.3，REQ-001 / AC-101～114。
- 验收依据：[plan.md](plan.md) v1.0、[R4交接](handoff-r4.md) v1.9、现行整体/模块设计及[测试迁移映射](test-migration.md)。
- 审查对象：HEAD `0e40fc866f639387e232dc893be81993d1b6a56f` 加全部未提交实现/测试/说明，包含未跟踪文件；169份文件冻结验证。
- 比较基准：前轮R5最终原生副本及[audit8最终SHA](evidence/R5/audit8-final-snapshot.json)、[原 v1.16 交接](evidence/R5/audit9-input-handoff-r5.md)。
- next_role：R0（由用户安排；不向其他独立对话发送消息，不自动推进REQ-002）。

## 统一结论

**passed。旧问题15项全部关闭，当前未解决旧问题0项，本轮确证新bug 0项。**

本轮同时完成旧问题复验和全范围复审，没有仅以R4交接的“已修复”或一次全绿替代检查。原复现、正常对照、异常恢复、相关边界及完整回归均已实际验证；历史问题逐项状态见下方完整表格。未发现需要新增或重开编号的问题。

上轮三项的独立确认：

| 编号 | 修复与复验确认 |
| --- | --- |
| R5-FIX-004 | 硬件清理按spawn Task终态/待完成状态分流。原MemoryError四fd泄漏用例转绿，新MemoryError/RuntimeError/ValueError、同端口恢复、取消/close竞争均通过。本轮再补跨清理等待期限的迟到child/构造失败、并发close及取消close等待者6项，确认writer保留至实际spawn、最终fd/child/Task回收。关闭重开记录。 |
| R5-FIX-015 | 标准库结构化慢回调WARNING单独记录性能信息；其他WARNING、全部ERROR及loop异常仍被拒绝。原背压两函数除末尾诊断调用外AST完整保留；真实默认0.1秒debug阈值的确定性慢回调用例通过。本轮再用实际未取回Task异常与真实慢回调共存验证，确认真实ERROR不会被隐藏。 |
| R5-FIX-014 | 示例正确说明列表name、详情served_model_name及省略时回退name，保留采集身份匹配说明；parsed YAML值与前轮完全相同，运行名称映射回归通过。 |

## 审查范围与产物

主审及三个独立分工覆盖当前全部REQ-001代码、需求/设计契约与相关测试：

| 范围 | 主要核对与记录 |
| --- | --- |
| config、collectors解析、data/models/state/vllm/window、Monitor、协议语义 | 合法输入、YAML安全、身份与精度、采样相位、60秒窗口、原子提交、失败/恢复、完整原样本及快照往返；[语义审查](evidence/R5/audit9-semantics-review.json)。 |
| service/runtime/_shutdown、硬件pipe/spawn、Docker/HTTP生命周期、IPC worker/server、error_log | 固定锁/权限、部分初始化、取消/信号、预算与异常优先级、真实fd/child回收、迟到所有权、背压、发布隔离与日志线程；[资源审查](evidence/R5/audit9-resources-review.json)。 |
| cli/client/session/tui/**、README/unit/example与测试诊断 | 单次连接、完整帧/缓存/失败锁存、终端恢复、导航/主题/历史、Unicode列宽、模型名称/关联及部署一致性；[UI与测试审查](evidence/R5/audit9-ui-summary.json)。 |
| 主审交叉复核 | 全部旧问题状态、真实复现与对照有效性、R4改动范围、原测试断言/YAML语义保留、协议/客户端/worker协作及最终全量。 |

R4本轮交付相对audit8最终版本的差异，已由R5独立核对：

- 产品实现仅 [collectors/_local_io.py](../../../../src/joi_observer/collectors/_local_io.py) 变化；[示例配置](../../../../src/joi_observer/examples/config.yaml)只改注释。
- [test_codec_backpressure_edges.py](../../../../tests/test_codec_backpressure_edges.py)只修改两处末尾诊断调用并增加分类helper/import；旧函数其余AST、实际期限及全部PID/Task/transport/放锁检查保持。
- R4新增 [test_hardware_spawn_failure_edges.py](../../../../tests/test_hardware_spawn_failure_edges.py) 5项和 [test_asyncio_diagnostics.py](../../../../tests/test_asyncio_diagnostics.py) 7项。其他原测试文件逐字节相同，原2587项全部保留通过。

R5本轮只在这两份新测试文件末尾追加 **7项**：迟到spawn所有权6项、真实asyncio混合诊断1项，全部通过。未修改产品、设计、依赖、部署或原断言。全部额外脚本/日志/报告/JUnit/PTY产物位于本需求 `evidence/R5/`。

## 验证证据

实际平台为本地WSL `Ubuntu-24.04`、Python3.12.3、pytest8.4.2，复用已有依赖。独立原生副本为 `/home/shawn/projects/tmp/joi-r5-audit9-20261117/baseline` 和 `/home/shawn/projects/tmp/joi-r5-audit9-20261117/final`；未覆盖前轮副本。

| 本轮实际执行 | 结果与证据 |
| --- | --- |
| R5补测前独立完整基线 | **2599 passed，62.64s，无failed/error/skipped**；含原2587项和R4新增12项；[输出](evidence/R5/audit9-baseline-pytest.txt)、[JUnit](evidence/R5/audit9-baseline-pytest.xml)、[结果](evidence/R5/audit9-baseline-result.json)。 |
| 语义专项 | 原生30文件 **1172 passed**，pytest结尾11.59s；[输出](evidence/R5/audit9-semantics-targeted.txt)、[JUnit](evidence/R5/audit9-semantics-targeted.xml)、[执行/哈希记录](evidence/R5/audit9-semantics-targeted-result.json)。 |
| 资源及生命周期专项 | 两组 **240 passed，23.56s** 和 **116 passed，8.05s**；[资源输出](evidence/R5/audit9-resources-targeted.txt)、[生命周期输出](evidence/R5/audit9-resources-lifecycle.txt)。 |
| 迟到spawn补测及原IO对照 | 两文件 **35 passed，5.34s**，含本轮新增6项；[输出](evidence/R5/audit9-resources-pending.txt)、[JUnit](evidence/R5/audit9-resources-pending.xml)。 |
| CLI/client/TUI/视图/PTY/诊断专项 | 原生36文件 **1011 passed，24.77s**；[输出](evidence/R5/audit9-ui-targeted.txt)、[JUnit](evidence/R5/audit9-ui-targeted.xml)、[AST/YAML/执行核对](evidence/R5/audit9-ui-result.json)、[PTY](evidence/R5/audit9-ui-pty/)。 |
| 真实混合诊断补测及背压/展示对照 | **52 passed**，含新增1项；[输出](evidence/R5/audit9-ui-supplement.txt)、[JUnit](evidence/R5/audit9-ui-supplement.xml)。 |
| 最终原生完整回归 | **2606 passed，64.24s，无failed/error/skipped**；原2599项保留通过、本轮7项新增通过；[输出](evidence/R5/audit9-final-pytest.txt)、[JUnit](evidence/R5/audit9-final-pytest.xml)、[结果](evidence/R5/audit9-final-result.json)、[PTY](evidence/R5/audit9-final-pty/)。 |
| R4修订保留核对 | R5独立 [脚本](evidence/R5/audit9-fix-preservation.py)/[结果](evidence/R5/audit9-fix-preservation.json)：与前轮R5真实冻结版本逐字节/AST比较；除015两处末尾诊断外旧有效断言全部保留，其他原测试字节不变，示例YAML值不变，原2587项及新12项通过。 |
| R5本轮改动与快照一致性 | [可重跑脚本](evidence/R5/audit9_verify.py)、[核对结果](evidence/R5/audit9-verification.json)：169份源码/测试/设计/需求/部署/依赖与最终原生副本SHA一致；R5仅追加两份测试、原AST节点和顺序保留、用例无缺失；产品不变，`git diff --check`通过。 |

专项与全量存在重叠，不能累加为唯一测试总数。015通过有确定性同类日志及真实ERROR负面对照依据，不是靠重复运行到绿，也没有调高slow_callback_duration、全局忽略WARNING或放宽产品期限。

最终完整回归实际命令：

```sh
cd /home/shawn/projects/tmp/joi-r5-audit9-20261117/final
JOI_PTY_EVIDENCE_DIR=/mnt/d/Documents/joi-observer/docs/dev-workflow/dev-1/REQ-001/evidence/R5/audit9-final-pty \
  /home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=/mnt/d/Documents/joi-observer/docs/dev-workflow/dev-1/REQ-001/evidence/R5/audit9-final-pytest.xml
```

## 旧问题与新bug完整清单

本轮确证新bug：**无**。本轮未解决旧问题：**无**。以下是本对话R5系列全部15项旧问题的最终状态，不把历史已关闭问题误写成当前仍存在：

## 历史摘要

| 原编号 | 问题简述 | 最终状态 | 处理与验证摘要 |
| --- | --- | --- | --- |
| R5-FIX-001 | 退出分层重计期限，来源可能晚于放锁结束。 | closed | 共享绝对期限、来源先收束后放锁和独立生命周期回归本轮通过。 |
| R5-FIX-002 | 日志线程创建失败停采或部分启动产生双writer。 | closed | ticket准入、失败恢复及单writer原回归本轮通过。 |
| R5-FIX-003 | stop竞争吞掉服务内部错误，CLI误报成功。 | closed | Monitor/runtime fatal与stop/信号竞争及正式CLI错误优先级本轮通过。 |
| R5-FIX-004 | 资源取得/任务分配失败遗漏回收，含Docker与硬件构造分支。 | closed | 原失败已转绿；终态与迟到spawn、真实四fd/child/Task、取消/并发close及后续采样均复验通过。 |
| R5-FIX-005 | 深层YAML和路径访问异常未统一为ConfigError。 | closed | 深度、stat/lstat权限竞态与安全退出2原回归通过。 |
| R5-FIX-006 | 共享YAML alias图被指数展开。 | closed | 节点/语境复用、懒定位及合法DAG/安全回归通过。 |
| R5-FIX-007 | FAILED后q覆盖连接失败，CLI误退出0。 | closed | 失败结果保存、正常q、局部STALE、双会话和信号对照均通过。 |
| R5-FIX-008 | 默认CLI提前访问失效cwd而崩溃。 | closed | 按需路径读取、信息/非TTY入口及服务安全诊断原回归通过。 |
| R5-FIX-009 | Unicode列宽低估，实际终端越槽。 | closed | 后端宽度、独立ncurses/locale与整页槽位回归通过。 |
| R5-FIX-010 | 缺失/关闭标准流导致TTY探测抛原始异常。 | closed | 真实标准流边界、安全退出3及falsey可用流对照通过。 |
| R5-FIX-011 | 显式falsey工厂被默认工厂替换。 | closed | None-only选择、真实离线采集接线及部分初始化回收原回归通过。 |
| R5-FIX-012 | 主机标签控制/双向字符导致服务零采样退出。 | closed | 本地标签投影前净化、Unicode/locale独立、读取冻结与严格wire校验回归通过。 |
| R5-FIX-013 | stdout背压使worker清理挂起，期限和退出失效。 | closed | 管道先释放再回收；真实首/后帧期限、关闭与服务放锁前回收及正常内容对照通过。 |
| R5-FIX-014 | 示例错误宣称name用于模型详情标题。 | closed | 注释已说明列表name/详情served_model_name及回退；YAML值和实际视图行为保持。 |
| R5-FIX-015 | debug慢回调被误判为资源回收失败。 | closed | 精确分类并记录性能，真实未取回Task ERROR仍失败；原资源/期限断言保留，确定性复验通过。 |

R4交接内部的 R4-FIX-001～004（fork/codec隔离、并发close所有权、启动错误优先、迟到清理异常观察）也在本轮相关原回归与资源审查中保持关闭，不新增或复用R5编号。

## 下一步

接收角色为 **R0/用户**，结论 **passed**。REQ-001当前没有待修复问题或待澄清事项，由用户决定后续安排；不自动推进REQ-002，不向其他独立对话发送消息。

## 验收范围与限制

本轮覆盖REQ-001 / AC-101～114：无TTY常驻/单一采集/退出隔离、原数据语义与60秒窗口、显示与会话独立、完整配套元数据/新实例、STALE与失联区分、只读边界、原回归保留、失败不重连、配置冻结以及模型名称映射，均有现存或补充测试通过。未将已确认的清理自身失败/超时保留资源可重试边界重新认定为新缺陷。

所有验证未连接本地或远程服务器，包括AF_UNIX listener；HTTP/Docker/字节流使用离线端口，真实child/fd/flock/PTY仅本地受控，所建资源已回收。未下载依赖、安装/启用systemd、验证实机账户/设备权限、产品连通或开机管理。README/unit仅静态一致性核对；不将其表述为实机部署通过。

旧额外全字符扫描和独立容量/性能报告仍属原时点；本轮完整回归已包含适用原容量与终端用例，但不声称重跑全部旧探针。未生成安装包、更新历史GUI/回放或实施REQ-002。有限离线检查不能证明任意环境和输入绝无缺陷。
