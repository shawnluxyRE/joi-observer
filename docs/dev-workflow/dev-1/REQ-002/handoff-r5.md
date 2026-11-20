# dev-1 / REQ-002 R5 验收交接

| 项目 | 当前记录 |
| --- | --- |
| stage / result / next_role | R5 / **passed** / **R0** |
| 修订 | v1.2，2026-11-19。R5-FIX-016～019 全部关闭，本轮未发现新增验收缺陷。 |
| work_dir | `D:\Documents\joi-observer\docs\dev-workflow\dev-1` |
| req_dir | `D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-002` |
| 需求及验收依据 | [需求 v1.5，AC-201～215、Q-013～014](../requirements.md#req-002-neon-grid-只读-web-看板与同机容器部署) · [计划 T-001～007](plan.md) · [R4 返修 v1.2](handoff-r4.md) · [整体架构](../../../design/architecture.md) · [IPC](../../../design/ipc.md) · [数据通道](../../../design/web.md) · [页面](../../../design/web-dashboard.md) · [部署](../../../design/web-deployment.md) |
| 比较基准与审查对象 | 分支 codex/dev1-web，HEAD 947db0afe44c0fe078cd88575c11559d7220521d 加全部未提交及未跟踪交付。对照上轮 R5 收尾的 197 文件清单，本轮输入仅页面 JS、CSS 及 R4 交接单改变。[上轮输入](evidence/R5/review-02/input.sha256) · [上轮测试增量](evidence/R5/review-02/test-changes.sha256) · [本轮输入](evidence/R5/review-03/input.sha256) · [本轮测试增量](evidence/R5/review-03/test-changes.sha256) |

## 产物

在 R5-FIX-019 原用例通过后，重新审查 REQ-002 的实现与测试逻辑，覆盖日常数据、视口、交互、失联恢复、共享采样及部署。

本轮补充一项尺寸往返测试，使用同一份三模型样本，将窗口从 1280px 缩到 620px、390px，再放大到 1280px。它核对读数的正确量级与实际文字边界、放大后恢复完整精度、队列计数及标签完整，以及模型选择、焦点、主题和单次数据订阅保持。新增用例已通过，原有用例保留。[场景入口](../../../../tests/browser/dashboard_browser.py) · [行为断言](../../../../tests/browser/dashboard_state_checks.js) · [场景分派](../../../../tests/browser/observe_dashboard.js)

本轮重新留存正式页面的桌面、窄屏及 620px 局部截图。[桌面](evidence/R5/review-03/desktop.png) · [窄屏](evidence/R5/review-03/narrow.png) · [019 修复画面](evidence/R5/review-03/models-620.png)

## 验证证据

执行环境为 WSL Ubuntu 24.04.5 x86_64、Python 3.12.3、Node 24.15.0、Chromium 156。IPC 和 HTTP 使用本地内存传输，浏览器通过私有管道打开本地文件。按 Q-014 使用日常三模型与完整行容量边界。[本轮命令](evidence/R5/review-03/commands.txt)

| 本轮实际执行 | 结果 | 证据 |
| --- | --- | --- |
| R5-FIX-019 原失败用例 | 1/1 通过；计入下方 Chromium 全组 | [原例结果](evidence/R5/review-03/019.xml) |
| Web Python，含部署与跨层 | 49/49 通过 | [JUnit](evidence/R5/review-03/web.xml) |
| Node 数据流与时钟 | 31/31 通过 | [输出](evidence/R5/review-03/node.txt) |
| Chromium 页面、原生输入与启动，含新增尺寸往返 | 24/24 通过 | [JUnit](evidence/R5/review-03/browser-final.xml) · [输出](evidence/R5/review-03/browser-final.txt) |
| **本轮 Web 回归合计** | **104/104 通过** | 原交付 103 项全部通过，另补 1 项。 |
| 当前版本按锁非可编辑安装 | 通过。安装包中三件页面资源与本轮源码逐字节一致，以生产 Uvicorn 参数加载工厂，完成生命周期、首页和资源请求。 | [安装结果](evidence/R5/review-03/installed.txt) · [部署复审](evidence/R5/review-03/ops-review.txt) |

宿主与共享 IPC 的实现及相关测试与上轮一致。本轮重新阅读接口和测试逻辑，引用上轮已执行的 87 项宿主/TUI/CLI/PTY/vLLM 回归及 65 项 IPC 回归。87 项组中，按 Q-014 排除的 3 项大报文或声明长度场景及完整命令均见原记录。[宿主结果](evidence/R5/review-02/host.xml) · [IPC 结果](evidence/R5/review-02/ipc.xml) · [原命令](evidence/R5/review-02/commands.txt)

固定资源、共享连接、协议字段及生命周期的本轮复审有独立记录。部署配方、锁、发布脚本和相关测试已做同版哈希确认，沿用上轮实际 Compose 参数展开、发布失败恢复、只读非 root 解码、HTTP/1.1 内存协议栈证据。[通道复审](evidence/R5/review-03/channel-review.txt) · [通道哈希](evidence/R5/review-03/channel-unchanged.sha256) · [部署哈希](evidence/R5/review-03/ops-reused.sha256) · [部署命令](evidence/R5/review-02/ops-commands.txt) · [HTTP/1.1 结果](evidence/R5/review-02/wire-http.txt)

| 验收项 | 本轮结论及依据 |
| --- | --- |
| AC-201 | 通过。核看桌面与窄屏整页，复验两主题、字符品牌、面板、硬件条、底栏及中等宽度可读性。019 的数字重叠和标签裁切已消除。[620px 画面](evidence/R5/review-03/models-620.png) |
| AC-202 | 通过。最新值和历史值来自权威快照，三种模型的速率及单位、硬件容量、Running/Total 计数正确。宽度不足时缩写，放大后恢复原值。[同帧对照](../../../../tests/test_web_snapshot_parity.py) · [尺寸往返](evidence/R5/review-03/resize.xml) |
| AC-203 | 通过。跨帧原生点击、模型详情与 GPU 联动、主题切换、双页隔离和尺寸变化后选择保持均通过。[浏览器结果](evidence/R5/review-03/browser-final.xml) |
| AC-204 | 通过。跨 64 秒左移、迟到帧无回弹、过期点退出、平滑穿点与峰谷、主题渐隐面积通过。[曲线断言](../../../../tests/browser/dashboard_chart_checks.js) |
| AC-205 | 通过。加载、有效零、未知、N/A、局部 STALE 与恢复、历史断口、失联错误可区分。缩写不把未知值或 N/A 变成数字。[页面状态断言](../../../../tests/browser/dashboard_state_checks.js) |
| AC-206 | 通过。GPU、Docker、模型按顺序取完整行前缀，空配置、零容量、焦点转移和溢出不撑高页面均通过。模型计数换行后仍使用实际行高裁切。[容量与状态用例](../../../../tests/browser/dashboard_state_checks.js) |
| AC-207 | 离线通过。关闭页面、停止和重建 Web 应用后宿主继续更新。发布脚本首次发布、失败恢复与同提交重试引用同版演练。[跨层用例](../../../../tests/test_web_pipeline.py) · [发布演练](evidence/R5/review-02/release-rehearsal.txt) |
| AC-208 | 通过。两页共享一次宿主订阅，TUI 消费同一权威状态，浏览器操作不影响宿主采样。首帧前唯一读者离开也释放订阅。[本轮 Web 结果](evidence/R5/review-03/web.xml) |
| AC-209 | 离线通过。核对唯一只读 IPC 目录、数值读者组、非 root、无 GPU 及 Docker 权限。同版程序在只读根和零 capabilities 下成功解码三模型完整历史。[只读验证](evidence/R5/review-02/readonly-worker.txt) |
| AC-210 | 通过。固定路由及方法、字段白名单、完整帧原子交付和实例切换约束通过；响应包含约定展示字段。[HTTP 黑盒](../../../../tests/test_web_api.py) · [协议回归](evidence/R5/review-02/ipc.xml) |
| AC-211 | 离线通过。首页无需登录，站点地址、端口和读者组来自部署参数，流程的网络策略责任写明。保存的 Compose 参数可独立重载。[部署复审](evidence/R5/review-03/ops-review.txt) |
| AC-212 | 离线通过。普通浏览器加载随包资源，缺少 JS/CSS 显示刷新提示。本轮重新核对安装包及生产应用入口，部署说明具备前置服务、权限、端口和恢复步骤。[安装结果](evidence/R5/review-03/installed.txt) |
| AC-213 | 通过约定的本地离线验收。数据链路、用户刷新、共享采样、视觉与交互验证均完成；现场范围见本轮决策。[命令索引](evidence/R5/review-03/commands.txt) |
| AC-214 | 通过。首连失败和中途 EOF 后不自动重连，每个页面分别刷新；旧连接关闭期间刷新、前台超时和健康后台恢复的回归通过。[Web 结果](evidence/R5/review-03/web.xml) · [Node 结果](evidence/R5/review-03/node.txt) |
| AC-215 | 通过。核对列表 name、详情 served_model_name 与缺省回退、同名不同 id、Docker 配置 id，以及无数据和 STALE 时保留身份。[名称与数据用例](../../../../tests/test_web_snapshot_parity.py) · [浏览器结果](evidence/R5/review-03/browser-final.xml) |

## 本轮决策

**REQ-002 在约定的本地离线验收范围内通过，R5-FIX-016～019 全部关闭。** 本轮未发现新的验收缺陷。

真实 Docker 镜像构建和启动、部署宿主的 socket 组权限、内网客户端可达性，沿用计划中的现场核验范围。本轮证据包括安装后的正式资源与应用、部署声明、本地命令演练及只读进程验证。[部署验证边界](../../../design/web-deployment.md#离线验证)

## 历史摘要

| 原编号 | 问题简述 | 最终状态 | 处理与验证摘要 |
| --- | --- | --- | --- |
| R5-FIX-016 | 旧 IPC 关闭期间手动刷新误收 503。 | closed | 登记前检查状态与期限。原例及并发刷新、超时后手动恢复随本轮 Web 全组通过。[证据](evidence/R5/review-03/web.xml) |
| R5-FIX-017 | 前台到期后切换标签可继续使用旧流。 | closed | 改变可见性前兑现原期限。旧例及健康后台追赶随本轮 Node 全组通过。[证据](evidence/R5/review-03/node.txt) |
| R5-FIX-018 | 快照更新打断鼠标模型选择。 | closed | 按 id 复用按钮及后代。跨帧原生点击、焦点与选择回归通过。[证据](evidence/R5/review-03/browser-final.xml) |
| R5-FIX-019 | 中等宽度详情数值重叠，列表标签被裁。 | closed | 按实测列宽缩写、计数换行。原例及尺寸往返通过，放大恢复精度、主题与焦点保持。[证据](evidence/R5/review-03/resize.xml) |

## 下一步

接收角色为 **R0**。请由用户或协调者确认本轮验收结论，并安排后续交付和现场部署核验。
