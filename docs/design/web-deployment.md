# Web 容器部署契约

dev-1 / REQ-002，v1.5，2026-11-19。Web 独立运行在采集宿主机上的容器中。组件依赖见[整体设计](architecture.md)，订阅、响应和文档生命周期见 [Web 接口](web.md)，宿主运行目录的所有权见[常驻采集服务](collector-service.md)。

## 进程与部署参数

目标为 Ubuntu Server 24.04 amd64。宿主准备 rootful Docker Engine、Buildx 和 Compose v2。宿主运维脚本使用基础安装已经提供的 `python3`。镜像安装项目的 `web` extra 和随包的 HTML、CSS、JS。页面使用本地等宽字体。

| 项目 | 生效值和职责 |
| --- | --- |
| Web 进程 | 以非 root 用户 `65532:65532` 启动一个 Uvicorn worker。PID 1 的入口为 `python -m uvicorn joi_observer.web.app:create_app --factory --host 0.0.0.0 --port 8080 --workers 1 --lifespan on --no-date-header --timeout-graceful-shutdown 3`。允许常规日志等运维选项。成功的实时响应由应用在发头时给出 UTC Date 和宿主单调时间 X-Joi-Sent-At。 |
| 内网地址 | Compose 唯一服务为 `web`，由必填 `JOI_WEB_IMAGE` 指向本次构建的本地镜像，发布步骤将实际镜像 ID 写入展开后的配置。长格式端口的 `host_ip` 取必填 `JOI_WEB_BIND`，发布到 `JOI_WEB_PORT`（默认 8090）并映射至容器 8080/TCP。使用普通 bridge 网络。 |
| 读者身份 | 容器附加组取必填的宿主读者组数值 `JOI_READERS_GID`。运行 UID 与采集服务所有者不同。设备按标准 `runc` 与 `NVIDIA_VISIBLE_DEVICES=void` 启动，不授予 Docker API、GPU 或采集权限。 |
| 挂载 | 唯一宿主 bind 将 `/run/joi-observer` 挂载到容器同一路径，`read_only: true`、`bind.create_host_path: false`。容器根文件系统只读，移除所有 capabilities。宿主监控配置、日志及根目录不进入容器。 |

宿主 systemd unit 创建 `0750` 的专用目录和 `0660` 的 socket。读者组可进入目录并建立 Unix 流连接，只读挂载保护目录项，只有采集服务拥有实例锁和监听端。目录挂载配合 `RuntimeDirectoryPreserve=yes`，宿主服务重启后用户刷新即可接入新建的 socket。需要在宿主服务首次启动前展示错误页时，可先执行 `install -d -o joi-observer -g joi-observer-readers -m 0750 /run/joi-observer`。

默认部署让宿主与容器的 UID/GID 直接对应。rootless 或 userns-remap 需要单独规划组号映射，本版部署说明采用直接映射。部署者负责核对内网路由、端口发布和防火墙。绑定目标接口不能替代来源授权，Docker 发布的端口可能绕过既有 UFW 过滤。

Web 启动时加载静态资源，即使采集服务暂时不可用也能提供页面。资源初始化失败由 lifespan.startup.failed 报告。SIGTERM 后 Web 停止接纳请求，取消数据订阅并回收连接。请求撤销和应用关闭可重叠。Web 停止自己的订阅和任务，并等待 IPC 客户端的 `close()` 有界返回。底层传输释放遵循客户端原有契约。Uvicorn 的请求停机宽限与 Docker 的外层停止宽限留出完成回收的时间。其他 TUI 和宿主采集继续运行。可采用日志、重启策略或只读取静态首页的健康检查。后台探活不得打开实时数据流。

## 构建输入与镜像内容

构建从选定的 Git 提交导出一次。输入仅含 Python 源文件、公开配置示例、三个 Web 资源、`README.md`、`pyproject.toml`、`uv.lock` 和 Web 配方。部署参数、用户配置、工作树的未提交文件和证据目录均在归档外。公开输入直接通过标准输入交给构建器，镜像也不需要访问主机的工作目录。

在镜像构建阶段以 Python 3.12+ 使用独立安装步骤 `RUN uv sync --locked --no-dev --extra web --no-editable`，将安装得到的虚拟环境保留为运行环境，并将其 bin 目录置于 PATH 首位。所选提交中的锁须包含 Uvicorn 及其依赖，过期的锁应使构建失败。当前宿主开发锁中的 registry 指向 `.pytest_cache/offline_wheels`。R4 在同步 Web extra 时须将部署依赖改为构建环境可提供的锁定来源，不将开发测试缓存复制进镜像。构建依赖由部署环境提供。随包资源继续由 setuptools package-data 声明，运行时通过已安装包读取。

## 运维操作

管理员在提供 REQ-002 成品的发行提交中运行[发布脚本](../../deploy/publish-web.sh)。首次发布录入内网 IPv4、端口和由宿主组查得的读者 GID，保存在 `/etc/joi-observer/web/.env`。以后使用同一命令升级。首次配置、发布及人工恢复命令见 [README](../../README.md#同机-web-看板)。

脚本为每次构建创建独立候选目录，从当前 HEAD 提交导出公开构建输入，镜像标签为 `joi-observer-web:<完整Git提交SHA>`。Compose 读取站点参数一次，并在 `compose.json` 中固定实际构建的镜像 ID。候选启动、权限核对和人工恢复共用该配置；同一提交重建后，历史发布仍能按原镜像 ID 恢复。运行容器的 ASGI 工厂及首页和两件静态资源均通过冒烟后，才将 `current` 指向该候选版本。

现场依次执行发布或恢复。替换容器期间看板会短暂中断。升级失败时 `current` 仍指向上次通过核对的版本。首次发布失败可从脚本输出找到候选目录，排错后重新发布。保留现行版和上一版的目录，以及各目录 `image.id` 对应的本地镜像。修改站点 `.env` 后重新发布以采用新参数。

| 日常动作 | 操作 |
| --- | --- |
| 停止、启动 Web | `docker compose -p joi-observer -f /etc/joi-observer/web/current/compose.json stop web`、`docker compose -p joi-observer -f /etc/joi-observer/web/current/compose.json start web`。宿主采集继续，用户刷新已报错的页面恢复。 |
| 页面不可达 | 查看 Compose 的 `ps`、`logs --tail=100 web`，核对发布端口和内网访问策略。首次发布失败时，使用脚本输出的候选目录中的 `compose.json`。 |
| 页面可达、数据失联 | 查看 `systemctl status joi-observer`、`journalctl -u joi-observer`，比对现行 `compose.json` 的读者组与 `stat -c '%A %u:%g %n' /run/joi-observer /run/joi-observer/snapshot.sock`。修复后刷新页面。更新宿主监控配置时重启 `joi-observer`，各页手动刷新以取得新实例与元数据。 |

浏览器打开 `http://<内网地址>:<发布端口>/`。每个标签占一条长 HTTP 响应，HTTP/1.1 同源连接池由浏览器限制，常见实现约六条。同来源的标签占满后新请求可能排队，关闭空闲标签并刷新即可重新尝试。Web 运行诊断写入容器标准输出或标准错误，正常监控数据只在内存中。

## 离线验证

| 范围 | 依据 |
| --- | --- |
| 部署声明与独立启停 | 核对 Compose 的端口和只读挂载、镜像配方的按锁安装步骤、项目 Web extra、锁定来源及随包资源。在内存用空资源目录验证启动失败，用一个订阅验证停机期间只回收一次连接。实际成品使用本次构建的镜像 ID 及同一份已展开的 Compose 参数核对。[部署用例](../../tests/test_web_deployment.py) · [成品探针](../../tests/web_image_artifact.py) |
| 宿主到浏览器 | 普通 CPU 样本沿真实采集、状态、发布、IPC 客户端与 ASGI 链路更新，同时打开两页及停掉 Web 后采样周期不变。宿主重启后新页面获取新身份。[跨层用例](../../tests/test_web_pipeline.py) |
| 协议与会话 | 日常三模型样本核对名称、单位、失败与恢复，HTTP 端使用内存消息，离线链路不连接 HTTP 或 AF_UNIX 监听器。本批次执行范围以 Q-014 为准。[多来源用例](../../tests/test_web_snapshot_parity.py) · [需求决定](../dev-workflow/dev-1/requirements.md#已解决) |

在本地 Ubuntu 或 WSL 的项目环境运行 `python3 -m pytest -q tests/test_web_deployment.py tests/test_web_pipeline.py tests/test_web_snapshot_parity.py`。实际运行容器、宿主挂载、内网可达性在部署现场核对。各阶段运行记录见 [R2 交接](../dev-workflow/dev-1/REQ-002/handoff-r2.md)。
