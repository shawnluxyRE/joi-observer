# joi-observer

面向 Ubuntu Server 24.04 amd64 的宿主机监控工具。常驻服务统一采集 GPU、CPU、内存、磁盘、Docker 和 vLLM；每个 TUI 只读取同一服务的快照。无人查看时采集继续，退出 TUI 不停止服务。正常指标与约 60 秒历史仅保存在内存，受控采集错误日志单独轮转。

本轮交付宿主服务和 TUI；Web 页面及容器属于后续 REQ-002。

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

服务账户所需 Docker/设备权限依部署环境设置；不要给 `joi-observer-readers` 组 Docker socket、GPU、监控配置或宿主根目录权限。

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

## 模型导航与键位

↑↓ 按配置顺序选择模型，到首尾停留，长列表随选择滚动。刷新、采集失败和窗口缩放保留选择；切换模型不清空历史或暂停其他来源。

底部显示 `vLLM` 和 `WebUI (disabled)`，暂不切换服务；←→、Enter、p、Tab 无操作。`q` 退出，`t` 切换主题。
