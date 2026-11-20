# joi-observer

面向 Ubuntu Server 24.04 amd64 的宿主机监控工具。常驻服务统一采集 GPU、CPU、内存、磁盘、Docker 和 vLLM；每个 TUI 只读取同一服务的快照。无人查看时采集继续，退出 TUI 不停止服务。正常指标与约 60 秒历史仅保存在内存，受控采集错误日志单独轮转。

同机 Web 容器向内网浏览器提供 dashboard。TUI 与 Web 使用同一份宿主快照，每个页面可独立选择模型和主题。[同机 Web 看板](#同机-web-看板)

## 安装与启动

以下为目标 Ubuntu 主机的部署说明，由管理员执行。

需要 Python 3.12+；GPU 监控需要 NVIDIA 驱动及 `nvidia-smi`，Docker 监控需要 Docker CLI，模型配置填写直接 vLLM 地址。

### 1. 安装系统依赖和 uv

```bash
apt update
apt install -y git curl ca-certificates python3 python3-venv

curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"
uv --version
```

### 2. 安装应用与账户

将项目克隆到所选位置，进入仓库根目录后执行下列命令。

```bash
groupadd --system joi-observer-readers
useradd --system --gid joi-observer-readers --create-home \
  --home-dir /var/lib/joi-observer --shell /usr/sbin/nologin joi-observer
install -d -m 0755 /opt/joi-observer
uv venv --python /usr/bin/python3 /opt/joi-observer/.venv
uv pip install --python /opt/joi-observer/.venv/bin/python .
ln -s /opt/joi-observer/.venv/bin/joi-observer /usr/local/bin/joi-observer
joi-observer --version
```

启用 Docker 容器监控时，以 root 身份执行以下命令：

```bash
usermod -aG docker joi-observer
```

重启服务后，重新打开 TUI、刷新 Web 页面。

`docker` 组具有宿主机管理级权限，仅授予采集服务账户。不要给 `joi-observer-readers` 组 Docker socket、GPU、监控配置或宿主根目录权限。

### 3. 创建服务配置

```bash
install -d -m 0755 /etc/joi-observer
install -o joi-observer -g joi-observer-readers -m 0600 \
  "$(joi-observer --example-config)" /etc/joi-observer/config.yaml
```

编辑配置，仅保留实际要监控的对象。

| 配置项 | 规则 |
| --- | --- |
| `sample_interval` | 默认 1 秒，允许有限数字 1～60 秒及范围内小数。 |
| `collection_timeout` | 默认 3 秒，允许 0.1～60 秒，独立于采样间隔。 |
| `mount_points` | 按顺序仅监控前三项，例如 `["/"]`；空列表关闭挂载项。 |
| `containers` | `id` 是展示名称，`name` 是实际容器名称或完整 ID；空列表表示不监控容器。 |
| `models` | `id` 标识对象，列表显示 `name`，详情显示 `served_model_name`。地址填写直接 vLLM origin，不带 `/v1`、`/metrics` 或网关路径。 |
| `gpu_ids` | 已确认的 GPU 索引字符串或完整 UUID，用于关联高亮。 |
| `logging.directory` | 默认 `/var/lib/joi-observer`，错误日志为该目录下的 `error.log`。 |

`joi-observer service` 查找配置：`--config PATH`、当前目录 `config.yaml`、`/etc/joi-observer/config.yaml`，按此顺序选择。配置仅在服务启动时加载，修改后必须重启。

### 4. 启用常驻服务

```bash
install -m 0644 deploy/systemd/joi-observer.service /etc/systemd/system/joi-observer.service
systemctl daemon-reload
systemctl enable --now joi-observer
systemctl status joi-observer
```

手动运行采用前台方式，由外部管理进程负责常驻；先停止 systemd 服务，使用相同服务账户和已准备的专有运行目录执行：

```bash
joi-observer service --config /etc/joi-observer/config.yaml
```

### 5. 打开 TUI

将查看用户加入读者组，重新登录使组成员资格生效，然后在交互终端运行：

```bash
usermod -aG joi-observer-readers username
joi-observer
```

TUI 运行期间，发往终端标准错误的客户端诊断不会写入全屏画面，也不进入采集服务的 `error.log`。
需要排查时可运行 `joi-observer tui 2>tui-stderr.log`；这会保存实际发出的诊断和退出提示，不会自动启用调试日志。

### 6. 日常管理与升级

```bash
systemctl stop joi-observer
systemctl start joi-observer
systemctl restart joi-observer
journalctl -u joi-observer
```

更改配置后执行 `restart`；升级前先 `stop`，在更新后的源码目录执行 `uv pip install --python /opt/joi-observer/.venv/bin/python .`，再启动服务。终端用户重新运行 TUI。

退出码：正常退出 0，内部错误 1，参数/配置错误 2，非交互终端 3，客户端连接错误 4，服务启动/锁/监听错误 5，SIGINT 130，SIGTERM 143。

## 同机 Web 看板

构建环境须能提供 Dockerfile 指定的 Python 与 uv 镜像、Python 构建依赖和 `uv.lock` 锁定的软件包。

管理员在采集宿主机上准备 rootful Docker Engine、Buildx、Compose v2 和读者组，在仓库根目录运行：

```bash
bash deploy/publish-web.sh
```

脚本从当前 HEAD 提交构建，以该提交的完整 SHA 作为镜像标签。

首次运行会询问宿主内网 IPv4 地址及端口（默认 8090）。脚本把站点设置保存于 `/etc/joi-observer/web/.env`。
成功后在内网浏览器打开 `http://<内网地址>:8090/`，内网访问策略由部署环境负责。

升级时在新发行提交运行同一命令。
如果升级失败，使用上次成功版本的镜像和配置恢复：

```bash
docker compose -p joi-observer -f /etc/joi-observer/web/current/compose.json up -d --pull never --no-build --force-recreate web
```

查看日志可运行 `docker compose -p joi-observer -f /etc/joi-observer/web/current/compose.json logs --tail=100 web`。
首次发布失败时使用脚本输出的候选目录替换 `current`。启停和数据失联排查见[部署说明](docs/design/web-deployment.md#运维操作)。

## 模型导航与键位

↑↓ 按配置顺序选择模型。`q` 退出，`t` 切换主题。

底部显示 `vLLM` 和 `WebUI (disabled)`，暂不切换服务；←→、Enter、p、Tab 无操作。
