# dev-1 / REQ-002 R2 交接

| 项目 | 当前值 |
| --- | --- |
| stage / result | R2 / ready（v1.5 两项简化已可交接） |
| next_role | R3，由用户安排独立对话 |
| 修订 | v1.5，2026-11-19 |
| 范围 | [REQ-002 / AC-201～215、Q-013～014](../requirements.md#req-002-neon-grid-只读-web-看板与同机容器部署)，依赖 [REQ-001 R5](../REQ-001/handoff-r5.md) |
| 基线 | `codex/dev1-web`，`947db0a` 加本轮工作区变更 |

## 实现依据

[整体设计 v1.7](../../../design/architecture.md)、[IPC v1.4](../../../design/ipc.md)、[Web 数据通道 v1.4](../../../design/web.md)、[Neon Grid 页面 v1.5](../../../design/web-dashboard.md)和[部署 v1.5](../../../design/web-deployment.md)为现行设计。R2 交付接口骨架、浏览器默认接线、设计及离线验收。宿主采集服务和 TUI 继续使用既有采样与 IPC 线格式。

同一看板可以在多个文档中独立打开。各文档持有自己的选择、主题和一条同源数据流，Web 桥共享同一宿主连接的已验证正文。采集故障按来源显示 STALE，连接错误由各页锁存，用户刷新后可以恢复。历史窗只显示最近 60 秒，按秒向前步进，连续有效样本平滑穿点，失败处留白。

## v1.5 采纳的两项简化

本轮按用户确认保留 v1.4 的首页加载和列表容量设计。首页先加载 HTML，再加载同版 CSS、JS，然后连接 `/api/live`。GPU、Docker、模型分别沿用各自的容量计算和溢出处理。

| 项目 | R3 / R4 的实施依据 |
| --- | --- |
| 历史曲线 | 正式页面在 R4 接入[原稿](../../../design/joi-observer.html)中的纯路径函数 `historyCurve(points)`，按所选模型的真实采样时间投影坐标，仅对连续有效段绘制，单点画圆，缺口处分段。代表场景验一次几何、渐隐面积与断口，换主题看实际描边与填充颜色，切换模型看点值与单位。继续按屏幕坐标逐帧验收一秒步进时无回弹。[曲线设计](../../../design/web-dashboard.md#近-60-秒曲线) · [浏览器验收](../../../../tests/browser/dashboard_chart_checks.js) |
| Web 发布 | 从选定发行版运行 `bash deploy/publish-web.sh` 完成一次发布。脚本承接已有候选构建、站点参数解析、镜像和应用核对，成功后切换 `current`。失败时可用保留的配置和镜像执行一条人工恢复命令。脚本可离线演练，正式发布还需 R4 交付 Web 镜像配方、Compose 和可运行应用。[发布脚本](../../../../deploy/publish-web.sh) · [README 操作入口](../../../../README.md#同机-web-看板) |

本轮在本地 WSL Ubuntu 24.04 离线验证了以下结果。

- **曲线。** 用 Chromium 156 对照原稿路径与日常样本，正确的几何及两种主题绘制通过，折线、旧主题渐变色和斜向渐变均被识别。正式入口的曲线和三模型切换用例仍停在 R2 的 `DashboardBoot.start` 占位，由 R4 接入绘制后完成端到端验收。[正式入口结果](evidence/R2/v15-chart-scenes.xml)
- **发布。** 在临时站点和本地 Git 仓库直接运行发布脚本，用命令替身代替 Docker。首次发布采用默认端口，候选启动或成品检查失败后均能用 README 的命令恢复上一版，同一提交重试成功后才切换现行版。[脚本演练记录](evidence/R2/v15-deployment-witness.txt)
- **范围核对。** 对照 v1.4 快照核对了首页加载、版本化资源、列表容量设计及原有容量判据。既有首屏结构和发行镜像 ID 核对两项通过。此次沿用现有场景，上一版的全量运行记录见下文。[普通回归结果](evidence/R2/v15-shell-and-release.xml)

## v1.4 已完成的 12 项修订

编号对应 [v1.3 整体复查](evidence/R2/design-reaudit-v13.md)。[v1.2 复查](evidence/R2/design-reaudit-v12.md)、[v1.1 复查](evidence/R2/design-reaudit-v11.md)和[首次复查](evidence/R2/design-review-20261118.md)保留各版复查时的判据。

| 项 | v1.4 的处理和验收位置 |
| --- | --- |
| 1 · 浏览器原生方法 | 默认 fetch、setTimeout、clearTimeout 绑定浏览器全局对象，通过流实例调用时保留原生接收者。离线端口照常注入。[LiveFeed](../../../../src/joi_observer/web/static/dashboard.js) |
| 2 · 屏幕样式 | 正式模板继续异步加载同版 CSS，加载成功即启用屏幕媒体样式。启动器等 DOM、脚本和屏幕样式就绪才交接，原生加载失败提示仍可独立显示。[页面外壳](../../../../src/joi_observer/web/static/index.html) |
| 3 · 等待提示 | 可见等待区放在仪表外。已显示过数据的健康标签从后台回来、原期限已过时，收起旧指标、显示等待，并在原读取器上最多等 2 秒。静默、追上与 EOF 复用已有恢复场景。[页面状态检查](../../../../tests/browser/dashboard_state_checks.js) |
| 4 · 发布失败恢复 | 每次构建都有自己的候选目录和本地镜像标签。同一个提交再次构建也使用新的候选。候选启动并通过核对后才切换 `current`。失败时按 `current/compose.json` 重建上次成功的版本。首次安装尚无成功版本时重新发布。[运维与恢复命令](../../../design/web-deployment.md#运维操作) |
| 5 · 站点参数 | 发布时读一次站点 `.env`，清除旧 shell 中的同名覆盖。省略端口取 8080，启动、成品核对和恢复共用展开后的 Compose 配置。[部署配置与探针](../../../../tests/web_image_artifact.py) |
| 6 · 停机边界 | Web 撤销订阅、结束自己的任务，等待 `SnapshotClient.close()` 有界返回。底层传输关闭超时或异常沿用现有客户端行为。原停机用例让请求退出和 lifespan 共用一次清理，验证 Web 对自己拥有的工作负责。[桥关闭接口](../../../../src/joi_observer/web/api.py) · [ASGI 生命周期](../../../../src/joi_observer/web/app.py) |
| 7 · 绘制驱动 | 现有 Chromium 用例通过私有管道加载本地文件，等待真实绘制和页面的 DOM 结果。尺寸通知及逐帧回调可在测试期间实际执行。[浏览器驱动](../../../../tests/browser/chromium_document.py) |
| 8 · 曲线无回弹 | 同一视口下图的时间轴保持稳定。原迟到帧场景用一个普通峰值使纵轴标签变宽，直接观察同一个存留采样点的屏幕横坐标，保留原有平滑穿点和断口验收。[曲线检查](../../../../tests/browser/dashboard_chart_checks.js) |
| 9 · 失联期限 | 原用例在第 4 秒发同发布时间的新状态，确认两个读者都看到更新。第 8 秒再送新鲜帧，此时两条旧响应必须均已结束。错误续期至第 11 秒的实现无法通过。[桥时序用例](../../../../tests/test_web_bridge_edges.py) |
| 10 · 按锁安装 | 复用依赖验收读取交付 Dockerfile 的实际安装指令，核对 `uv sync --locked` 和 `web` extra。只用 pip 安装或只在注释写 locked 的配方都会被拒绝。R4 发布时同步可部署的锁文件和随包资源。[部署验收](../../../../tests/test_web_deployment.py) |
| 11 · Docker 状态 | 原日常样本中，一个容器失败但保留了上次 Running。页面检查读取这一行的可见状态，要求显示 STALE，并核对相邻健康容器仍显示 Running。[状态检查](../../../../tests/browser/dashboard_state_checks.js) |
| 12 · 页面偏好 | 原双页用例先给第一页选非默认模型和主题，送入心跳及后续更新，再打开第二页。核对第一页保留选择、新页使用默认值，后续操作继续彼此独立。[双页选择](../../../../tests/browser/observe_dashboard.js) |

## 视觉对照

[桌面原稿（1280×900 视口）](evidence/R2/v13-reference-desktop.png)和[窄屏原稿（390×844 视口）](evidence/R2/v13-reference-narrow.png)作为 R4 成品的两份视觉参照。正式页面可绘制后，按[页面设计的整页对照步骤](../../../design/web-dashboard.md#黑盒入口与验证边界)，核对品牌、面板、GPU 与主机分段条、选中关联、主题及服务入口。数值和曲线取日常样本，Running/Total、键位和名称映射按现行需求。

## v1.4 的验证基线

v1.4 在 WSL Ubuntu 24.04 amd64 的原生目录 `/home/shawn/projects/tmp/joi-r2-v14-fgBWNVHo` 运行，使用 Python 3.12、Node 24 和 Chromium 156。常设 Web 用例共 **86 项**。当时的正式入口结果为 **2 项通过、84 项等待 R4 实现**，无收集错误、跳过或浏览器驱动超时。另有 **24 项既有宿主、IPC、TUI 日常回归全部通过**。

| 实际执行 | 本轮结果 |
| --- | --- |
| Web Python，39 项 | 首屏结构与运行镜像 ID 对照通过。34 项到达 Web、桥或 IPC 新接口的实现占位，3 项到达 R4 的 Compose、Dockerfile 或包内资源声明缺件。[输出](evidence/R2/v14-web.txt) · [JUnit](evidence/R2/v14-web.xml) |
| Chromium 与跨层，19 项 | 15 项到达启动器占位，3 项得到等待实现的启动行为，1 项在真实输入链路到达 ASGI 占位。全部通过私有管道执行。[输出](evidence/R2/v14-browser.txt) · [JUnit](evidence/R2/v14-browser.xml) |
| Node，28 项 | 26 项到达 LiveFeed.start，2 项到达 HistoryWindowClock.rightEdge，占位均明确报错。[输出](evidence/R2/v14-node.txt) |
| 日常宿主回归，24 项 | 普通三模型原始样本、动态 GPU、TUI 名称与选择、IPC 原子读取和心跳替换全部通过。[JUnit](evidence/R2/v14-host.xml) |

针对原反例还做了以下离线复核：

- **页面接线与绘制。** 在实际 Chromium 中通过流实例调用默认 fetch（本地 data URI）及原生计时器，检查正式模板的 CSS 在屏幕生效、仪表收起时状态文字仍可见。两个普通 iframe 将宽度从 100 改到 150、200，均得到对应的逐帧回调和尺寸通知。对同一个绘图判据，稳定曲线通过，持续约 60 毫秒的 9.2 CSS 像素右移被拒绝。
- **数据时限与停机。** 用 asyncio 定时器及现有响应读取助手验证，原 7 秒期限可通过，等时间戳错误续期会被拒绝。真实 SnapshotClient 在内存传输的关闭操作抛错时有界返回 CLOSED，验证 Web 采用的公开关闭边界。
- **部署与按锁安装。** 在本地 Git 小仓库和临时站点目录执行文档中的 Bash，Docker 使用命令替身。首次发布取默认 8080 并忽略旧 shell 值，启动失败和成品检查失败均能恢复原镜像与配置，同一提交重试成功后才切换现行版。交付配方的检查接受带换行和构建缓存挂载的按锁安装指令，拒绝仅执行 pip 且只在注释中出现 locked 的配方。[部署演练记录](evidence/R2/v14-deployment-witness.txt)

语法检查覆盖 Python、JavaScript 和部署 Bash。正式看板的整页绘制、运行镜像及现场挂载仍由 R4 按本交接验证。项目内验证均使用日常配置和本地文件或内存传输。

## 离线复跑

从工作区或相同内容的 Ubuntu 目录执行。以下命令使用本轮已有的解释器和 Chromium。

```bash
PY=/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python
BR=/home/shawn/projects/tmp/joi-req002-browser.uWlUJy
unshare -Urn "$PY" -B -m pytest -p no:cacheprovider -q tests/test_web_*.py
unshare -Urn "$BR/node" --test tests/browser/live_feed.test.cjs
unshare -Urn env CHROMIUM="$BR/chromium/chromium" LD_LIBRARY_PATH="$BR/lib" \
  DBUS_SESSION_BUS_ADDRESS=disabled: DBUS_SYSTEM_BUS_ADDRESS=disabled: \
  "$PY" -B -m pytest -p no:cacheprovider -q tests/browser/dashboard_browser.py tests/browser/dashboard_boot.py
unshare -Urn "$PY" -B -m pytest -p no:cacheprovider -q \
  tests/test_snapshot_pipeline.py::test_raw_sources_through_snapshot_transport_keep_original_values_and_frame_contracts \
  tests/test_snapshot_pipeline.py::test_dynamic_gpu_discovery_partial_failure_and_recovery_share_one_snapshot_connection \
  tests/test_display_metadata_view.py \
  tests/test_ipc_client.py::test_complete_first_frame_and_sync_cache_have_no_transport_io \
  tests/test_ipc_client.py::test_fragmented_wire_is_installed_atomically_and_old_value_stays_immutable \
  tests/test_ipc_client.py::test_same_revision_heartbeat_replaces_cache_when_history_expires
```

## v1.5 整体设计复查

2026-11-19 对照 [AC-201～215](../requirements.md#req-002-neon-grid-只读-web-看板与同机容器部署)核对了现行模块设计、REQ-001 的接口约定和已有验收入口。结论为 R2 / ready，未发现需要在 R3 规划前修订的明显设计错误或需求遗漏。

| 验收范围 | 核对结论 |
| --- | --- |
| 页面与指标（AC-201～203、206、215） | 单页加载顺序、桌面与窄屏布局、三类列表的容量规则、模型及 Docker 的名称映射、数值单位、主题和选择的会话隔离均有明确约定。 |
| 历史与故障（AC-204、205、214） | 曲线按所选模型的真实采样时间分段，60 秒窗口按秒前进，连续观测平滑穿点，失效观测留缺口。页面区分零值、未知、不适用、局部失败和整体断流。整体连接失败后由各页独立刷新。 |
| 采集与权限（AC-207～211） | 采集和状态归宿主服务，Web 共享只读快照订阅。增加页面、关闭页面或重建 Web 均不触发采样。容器的读者组、专用目录挂载、内网端口和部署者的网络责任一致。 |
| 普通浏览器、部署和集成（AC-212、213） | 页面资源随包交付。安装、发布、启停、升级、恢复和排错有对应入口。已有离线链路与发布演练明确了验证方法。正式页面的视觉对照、实时数据端到端运行与真实镜像仍需在实现后验收。 |

本次为设计复查，引用既有验证记录，未重跑产品测试。

## 下一步

接收角色为 **R3**。由用户安排独立对话，在本需求目录编写 `plan.md`，按 v1.5 的曲线接入方式和发布脚本入口安排 R4 实现。正式页面与原稿的视觉对照、Web 全链路及实际镜像部署仍由后续阶段验证。
