# dev-1 / REQ-002 R4 交接

| 项目 | 当前值 |
| --- | --- |
| stage | R4 |
| result | ready |
| next_role | R5 |
| 修订 | v1.2，2026-11-19，R5-FIX-019 已修复，待 R5 复验；016～018 已由 R5 关闭。 |
| work_dir | `D:\Documents\joi-observer\docs\dev-workflow\dev-1` |
| req_dir | `D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-002` |
| 实现依据 | [REQ-002 / AC-201～215、Q-013～014](../requirements.md#req-002-neon-grid-只读-web-看板与同机容器部署) · [计划 v1.0](plan.md) · [R2 v1.5](handoff-r2.md) · [R3 v1.0](handoff-r3.md) · [R5 返修清单 v1.1](handoff-r5.md#r4-修订汇总) |
| 审查对象 | `codex/dev1-web` 的 `947db0a` 加当前工作区，含未跟踪的 Web 源码、部署文件及测试。 |

## 产物

| 任务 | 已交付行为与入口 |
| --- | --- |
| T-001～002 | 同一宿主连接向各页转发经过白名单验证的整帧，信封与原始正文一起更新。各读者的慢写、断连、手动刷新按连接尝试隔离。ASGI 启动时固定三个同版资源，按需打开实时流，停机时等待自身任务与共享连接回收。[IPC 客户端](../../../../src/joi_observer/ipc/client.py) · [订阅桥](../../../../src/joi_observer/web/api.py) · [ASGI 应用](../../../../src/joi_observer/web/app.py) |
| T-003～004 | 页面资源就绪后发起一次同源请求，用完整快照更新硬件、Docker 和三类模型。各页独立管理主题、选择和失联状态。窄屏按完整行裁切列表，调整焦点，模型名称、状态和队列计数在各自的按钮内分行显示。[页面外壳](../../../../src/joi_observer/web/static/index.html) · [页面样式](../../../../src/joi_observer/web/static/dashboard.css) · [数据流与视图](../../../../src/joi_observer/web/static/dashboard.js) |
| T-005 | Web 绘制 `[右缘 − 60 秒, 右缘]` 内的真实观测。新点从右侧进入，已有点按秒整体向左平移，过期点从左侧移出。迟到帧可以让窗口暂时停步。连续段复用原稿的平滑路径，失败处分段，孤点单独绘制。已按用户本轮确认，增补跨完整一分钟的屏幕坐标验证。[曲线黑盒](../../../../tests/browser/dashboard_chart_checks.js) |
| T-006 | 镜像按锁安装 Web extra 和静态资源，使用非 root 单 worker。Compose 通过数值读者 GID 访问唯一的只读 IPC 目录。沿用发布脚本，候选通过检查才切换现行版，失败可按上次有效配置恢复。[Dockerfile](../../../../deploy/Dockerfile.web) · [Compose](../../../../deploy/compose.yaml) · [依赖声明](../../../../pyproject.toml) · [锁文件](../../../../uv.lock) · [发布与恢复入口](../../../../README.md#同机-web-看板) |
| T-007 | 普通三模型原始样本贯通宿主、IPC、ASGI 与真实浏览器，覆盖局部失败、恢复及名称、数值和单位。双页面和 TUI 共享宿主采样，关闭或重建 Web 后宿主继续采集。[宿主与多页](../../../../tests/test_web_pipeline.py) · [同帧对照](../../../../tests/test_web_snapshot_parity.py) · [可见页面](../../../../tests/browser/dashboard_browser.py) |

## R5 返修汇总

### R5-FIX-019 · 中等宽度的指标与列表计数可读性

- 问题依据为 R5 v1.1 的 [019 记录](handoff-r5.md#r4-修订汇总)，关联 AC-201、202、213 和 T-004。
- 原例在 620×900 复现。DECODE 与 TTFT 文本超出各自列宽，模型列表 waiting 标签在按钮右边缘裁切。[本轮修复前结果](evidence/R4/r5-fix-019/before.txt)
- 四个详情指标在布局完成后测量实际列宽与文字范围。能容纳原值时保持原文，超宽时选择能完整显示的舍入小数或带完整指数的科学记数。精确值保存在 title，窗口放大后从原始快照恢复显示精度。[数值呈现](../../../../src/joi_observer/web/static/dashboard.js)
- 模型按钮中的两组计数按可用宽度换行。窄屏单行轨道固定预留八行文字高度，让计数和标签可各占两行，轨道与页面高度独立于当前计数。模型按钮及其后代继续按 id 复用。[列表样式](../../../../src/joi_observer/web/static/dashboard.css)
- R5 的 620×900 原例转绿。另用同一份日常三模型样本，从 1280px 逐步缩至 320px 再放大，核对四项指标及标签的文字范围、完整队列文字与精确值提示。320、360px 仍保留模型列表和详情，恢复 1280px 时读数重新显示全部精度。[几何记录](evidence/R4/r5-fix-019/geometry.txt) · [620px 画面](evidence/R4/r5-fix-019/models-620.png) · [360px 画面](evidence/R4/r5-fix-019/models-360.png)
- 当前状态为 **已修复，待 R5 复验**。

## 验证证据

本轮使用 WSL Ubuntu 24.04.5 x86_64、Python 3.12.3、Node 24.15.0、Chromium 156。IPC 与 ASGI 使用内存端口，浏览器经私有管道打开本地文档，服务器连接保持禁用。[本轮命令](evidence/R4/r5-fix-019/commands.txt)

| 本轮实际执行 | 结果 |
| --- | --- |
| Chromium 页面、原生输入与启动 | **23/23 通过**。包括中等宽度原例、桌面和窄屏、三类模型、容量和焦点、跨帧点击、主题、故障恢复、跨 64 秒左移及迟到帧无回弹。[JUnit](evidence/R4/r5-fix-019/browser.xml) · [输出](evidence/R4/r5-fix-019/browser.txt) |
| Node 数据流与图表时钟 | **31/31 通过**。[输出](evidence/R4/r5-fix-019/node.txt) |
| Web Python、部署与跨层 | **49/49 通过**。[JUnit](evidence/R4/r5-fix-019/web.xml) · [输出](evidence/R4/r5-fix-019/web.txt) |
| 尺寸往返与几何观察 | 同一帧在 1280、850、768、700、640、620、601、600、390、360、320px 下验证，再回到 390、620、1280px。数值保留正确量级，标签和计数在各自范围内，放大恢复完整读数，全程一次数据请求。[脚本](evidence/R4/r5-fix-019/geometry.py) · [结果](evidence/R4/r5-fix-019/geometry.txt) |
| 安装后的正式资源 | 按锁非可编辑安装，逐字节对照本次 HTML、CSS、JS，再用镜像配方中的 Uvicorn 参数加载已安装工厂，完成内存生命周期、首页与两件静态资源请求。[安装记录](evidence/R4/r5-fix-019/installed.txt) |

上述三组 Web 测试共 **103 项通过**。宿主和共享 IPC 的 87 项、65 项日常回归引用 R5 v1.1 的结果。本轮代码改动位于页面 CSS 与 JS，已关闭问题的独立验证见历史摘要。[R5 宿主结果](evidence/R5/review-02/host.xml) · [R5 IPC 结果](evidence/R5/review-02/ipc.xml)

部署脚本的首次发布、失败后恢复、同一提交重试引用既有[发布演练](evidence/R4/deploy-release.txt)。

## 历史摘要

| 原编号 | 问题简述 | 最终状态 | 处理与验证摘要 |
| --- | --- | --- | --- |
| R5-FIX-016 | 旧 IPC 关闭期间刷新误收 503。 | closed | 登记前检查连接状态和期限，并发刷新共享直接后继。R5 原例、期限耗尽和之后恢复均通过。[证据](evidence/R5/review-02/016.xml) |
| R5-FIX-017 | 前台超时后切换标签可继续取数。 | closed | 可见性改变前检查原期限。R5 确认前台失联锁存、健康后台页可按原流追赶。[证据](evidence/R5/review-02/017.txt) |
| R5-FIX-018 | 快照更新打断原生鼠标模型点击。 | closed | 按 id 保留按钮和后代节点。R5 确认跨帧点击、GPU 联动、裁切与焦点回归通过。[证据](evidence/R5/review-02/018.xml) |

## 现场待验

真实 Docker 镜像构建、运行容器的 UID/GID 与宿主 socket 访问权限、内网客户端可达性仍待部署者核对。正式发布需选择包含上述工作区产物的发行提交。站点绑定、端口及恢复命令见 [README](../../../../README.md#同机-web-看板)。

## 下一步

请由用户将本单交回 **R5**，复验 R5-FIX-019 及关联的 AC-201、202、213，并在 R5 交接单中记录该原编号的验收结论。
