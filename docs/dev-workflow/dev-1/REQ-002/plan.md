# dev-1 / REQ-002 概要开发计划

- 项目 `D:\Documents\joi-observer`
- 工作目录 `D:\Documents\joi-observer\docs\dev-workflow\dev-1`
- 需求目录 `D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-002`
- v1.0，2026-11-19，R3 / ready，接收角色 R4。
- 范围为 dev-1 的 REQ-002、AC-201～215。Q-013 确定历史窗口与曲线行为，Q-014 确定日常验证规模。宿主服务、快照协议 v1 和 TUI 已由 REQ-001 交付。[需求说明 v1.5](../requirements.md#req-002-neon-grid-只读-web-看板与同机容器部署) · [REQ-001 R5 验收](../REQ-001/handoff-r5.md)
- 实施起点为 `codex/dev1-web` 的 `947db0a` 加 R2 v1.5 工作区交付。整体设计 v1.7、IPC v1.4、Web 数据通道 v1.4、页面及部署 v1.5 共同约定以下接口与黑盒。[R2 交接](handoff-r2.md) · [整体设计](../../../design/architecture.md) · [IPC](../../../design/ipc.md) · [Web 数据通道](../../../design/web.md) · [Neon Grid 页面](../../../design/web-dashboard.md) · [Web 部署](../../../design/web-deployment.md)

## 主要任务

| 任务编号与标题 | 交付结果与验收依据 | 大致修改范围 | 开工所需前置 |
| --- | --- | --- | --- |
| T-001 多个页面共享已验证的宿主快照 | Web 原子取得同一发布的信封与原始正文，保留精确整数、转义及局部 STALE。并发页面共享一次 IPC 尝试，慢读者写完整行后取最新帧。相同发布时间的新序号可更新数据，只有新鲜且时间前进的后续帧才续期。失败通知本次全部读者，末页退出释放连接。AC-205、207、208、210、214。[接口黑盒](../../../../tests/test_web_api.py) · [共享桥边界](../../../../tests/test_web_bridge_edges.py) | 在 [IPC 客户端](../../../../src/joi_observer/ipc/client.py) 完成可选的 `retain_body` / `wire_publication()`，在 [Web 订阅桥](../../../../src/joi_observer/web/api.py) 实现逐请求订阅。默认 TUI 路径继续只缓存解码结果。 | 已具备的 REQ-001 客户端、协议校验与 R2 读者接口。 |
| T-002 普通浏览器取得同版首页、资源与只读数据流 | 采集服务离线时首页仍可加载。启动时固定同版 HTML/CSS/JS 并按版本提供资源。仅合规的 `GET /api/live` 订阅，首行前失败给 503，已发 200 后失联则结束流。首行写前复检、分块写入期限、取消与停机按契约隔离单页。AC-207、208、210～214。[HTTP 黑盒](../../../../tests/test_web_api.py) · [慢页与首行](../../../../tests/test_web_bridge_edges.py) · [应用生命周期](../../../../tests/test_web_deployment.py) | [ASGI 工厂与应用](../../../../src/joi_observer/web/app.py)，包括静态资源、实时响应时间头及 lifespan，沿用 T-001 的订阅接口。 | R2 已给出 `LineSubscription`、工厂和资源模板，可先实现路由。 |
| T-003 每个文档独立打开、等待、失联与刷新 | HTML 先显示加载态，DOM、同版脚本及屏幕样式就绪后只取一次同源数据流。完整 UTF-8 行原子更新，心跳与普通帧均可用。区分加载资源失败、连接失败与健康标签恢复后的短暂等待。失败页收起旧仪表，只有该页刷新才可恢复。AC-205、208、210、212～214。[首屏](../../../../tests/test_web_dashboard.py) · [流与时钟](../../../../tests/browser/live_feed.test.cjs) · [文档启动](../../../../tests/browser/dashboard_boot.py) | [正式模板](../../../../src/joi_observer/web/static/index.html) 的 DashboardBoot 和[随包脚本](../../../../src/joi_observer/web/static/dashboard.js) 的 LiveFeed、文档生命周期。 | R2 的启动与流接口、内存响应和可控时钟已具备。 |
| T-004 Neon Grid 指标、选择与响应式布局 | 同一帧驱动品牌与主机行、硬件、存储、Docker、三类模型详情及服务入口。列表取 `name`，详情取已回退的 `served_model_name`，容器取配置 id。Running/Total 仅显示真实计数。零、未知、N/A、空配置及局部 STALE 各有可见表现。GPU、Docker、模型分别取可完整容纳的有序前缀，裁切时调整选择与焦点。两页各自保留主题、模型和 GPU 高亮。AC-201～203、205、206、212、215。[页面设计](../../../design/web-dashboard.md) · [浏览器场景](../../../../tests/browser/dashboard_browser.py) | [页面资源](../../../../src/joi_observer/web/static)，复用同帧元数据和指标口径。桌面与窄屏以 [Neon Grid 原稿第一屏](../../../design/joi-observer.html)为视觉依据。 | 已有白名单帧和三模型离线样本可用于绘制。 |
| T-005 所选模型的 60 秒实时曲线 | 以真实采样时间绘制，窗口逐秒前移，迟到帧及纵轴变宽时，同一存留点在相同视口内不会向右回弹。连续有效段平滑穿点，断口留白，单点画圆，填充随主题主色渐隐。切换模型同步更新曲线、点值及 tok/s 或 seq/s。AC-202～205、Q-013。[曲线设计](../../../design/web-dashboard.md#近-60-秒曲线) · [曲线黑盒](../../../../tests/browser/dashboard_chart_checks.js) | 在 [dashboard.js](../../../../src/joi_observer/web/static/dashboard.js) 接入 HistoryWindowClock，将[原稿](../../../design/joi-observer.html)的纯路径函数 `historyCurve(points)` 用于每个连续段，窗口只展示最近 60 秒。 | 原稿路径函数、图表时钟契约及正常/迟到/缺口样本已具备。 |
| T-006 可发布和恢复的同机 Web 容器 | 交付 `deploy/Dockerfile.web`、`deploy/compose.yaml`、Web extra、可用于部署的锁和三件随包资源。镜像按锁安装，以非 root 单 Uvicorn worker 运行。Compose 绑定指定内网地址和端口，以读者 GID 访问唯一只读挂载 `/run/joi-observer`。沿用一次发布命令、成功后切换 `current` 和失败后的人工恢复。AC-207、209～213。[部署用例](../../../../tests/test_web_deployment.py) · [成品核对脚本](../../../../tests/web_image_artifact.py) | 上述两个部署文件、[pyproject.toml](../../../../pyproject.toml)、[uv.lock](../../../../uv.lock) 与 [README 运维入口](../../../../README.md#同机-web-看板)。用部署环境可提供的锁定来源替换当下的测试缓存来源，复用[发布脚本](../../../../deploy/publish-web.sh)。 | 配方与 Compose 可按既定工厂、资源路径和站点参数开工。 |
| T-007 宿主、TUI 与正式页面联合验证 | 用同一采集来源核对双页与 TUI 的业务值及采样次数，验证关页、Web 停止/重建、宿主重启及手动刷新。完成两种视口的整页对照，记录可部署产物、离线验证结果与现场待验项。以 AC-213 贯通 AC-201～215。[双页与宿主生命周期](../../../../tests/test_web_pipeline.py) · [同快照数值对照](../../../../tests/test_web_snapshot_parity.py) · [正式页面入口](../../../../tests/browser/dashboard_browser.py) | 正式入口、现有黑盒、两张成品截图和 R4 交接。沿用既有宿主采集、状态和 TUI。 | 全链路需 T-001～005 的正式入口可运行，部署验收汇总需 T-006。分层检查随各任务进行。 |

## 开发顺序与并行条件

1. 先在后端贯通一条日常快照。T-001 让原子读取与双订阅用例通过，再与 T-002 合验从发头到结束流的行为。宿主恢复后，旧订阅仍然终止，只有新的页面数据请求可以发起下一次 IPC 尝试。T-002 的静态路由、T-003 的单次 fetch、T-004 的面板、T-005 的图表与 T-006 的部署声明均可按现有契约并行准备。
2. T-003～005 共用 `dashboard.js`，T-003 与 T-004 也共用 HTML 的状态区。合入时让同一文档的启动器移交给唯一的 Dashboard，由它把同一完整帧和所选模型交给面板与曲线。随后用正式资源验两页选择、收起旧仪表、终态停止绘图，以及刷新后取得新实例。
3. T-006 与应用约定相同的工厂、三个静态资源和单 worker 参数。打通 T-001～005 后，先用内存 ASGI 及浏览器 file 文档合验。正式发布取包含应用、资源、锁、配方、Compose 和成品核对脚本的同一发行提交，工作树改动须进入该提交才是构建输入。

## 验证安排

R3 在本地 WSL Ubuntu 24.04 amd64 对当前 R2 v1.5 工作区执行了 86 项 Web 黑盒，2 项通过、84 项失败，24 项宿主日常回归全部通过。失败落在尚待实现的正式入口、部署文件与包资源声明。R4 以本版用例全部通过并完成下表各项作为离线交付依据。[R3 命令与结果](evidence/R3/baseline.txt) · [R2 已有证据与复跑入口](handoff-r2.md#离线复跑)

| 验证面 | R4 执行与判定 |
| --- | --- |
| IPC、ASGI 与页面失联 | 运行 `tests/test_web_*.py`。核对原始白名单正文、相同发布时间的新序号、读者退出/换代、慢读者与停机。桥按 5 秒新鲜度及 7 秒进展期限判断，200 头和首行共用一次 5 秒写期限。Node 另显式执行 `node --test tests/browser/live_feed.test.cjs`，核对浏览器 12 秒整行进展、健康页从后台恢复时原流最多 2 秒追赶，以及 EOF 后的页级错误。 |
| 正式页面与视觉 | 显式将 `tests/browser/dashboard_boot.py` 和 `tests/browser/dashboard_browser.py` 传给 pytest。Chromium 经私有管道打开本地文件，检查真实盒尺寸、两主题、分段条、GPU 关联、键位、容量与焦点。按页面设计的 `layout` / `page.html?visual` 入口，在 100% 缩放下各保留一张 1280×900 和 390×844 全页截图，窄屏包含折叠线以下内容。与[桌面原稿](evidence/R2/v13-reference-desktop.png)及[窄屏原稿](evidence/R2/v13-reference-narrow.png)比对。 |
| 曲线与多来源贯通 | 代表性 Chat 场景验一次采样点、峰谷、断口与面积边界，换主题查实际描边和填充，切换三模型查各自点值与单位，迟到帧逐帧查屏幕横坐标。再用 `test_reference_snapshots_through_http_to_visible_dashboard` 将与 TUI 共用的样本经正式 ASGI 送入 Chromium。 |
| 宿主回归与规模 | 复跑 [24 项日常宿主、IPC、TUI 用例](evidence/R3/baseline.txt)，并运行改动涉及的既有日常功能回归，保留原断言。Q-014 以 Chat、Embedding、Reranker 为常规样本，溢出只增加刚好越界的条目。用正常历史和可控写端测试分块、超时和恢复。 |
| 部署与运维 | 在本地用部署测试检查端口、读者组、只读根及专用目录、移除 capabilities、常规 runc 和包内资源。依部署设计核对实际 `uv sync --locked --no-dev --extra web --no-editable` 安装步骤。以本地 Git 和 Docker 命令替身离线演练选定发行版的 `bash deploy/publish-web.sh`、首次发布、升级失败和按上一版配置恢复。成品运行时的镜像 ID、权限和资源由既有脚本核对后再晋升候选。[发布与恢复设计](../../../design/web-deployment.md#运维操作) |

本轮验证遵守仓库的服务器连接禁令。宿主链路使用离线来源及内存传输，浏览器使用本地资源。实际运行镜像、宿主挂载权限及内网可达性由部署者在现场核对，R4 交接分别标明已取得与待取得的证据。
