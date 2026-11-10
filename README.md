# joi-observer

一个面向 Ubuntu Server 的终端监控工具，通过 TUI 实时展示服务器硬件状态与LLM服务负载。

- **硬件监控**：GPU 利用率、显存、温度与功耗，以及 CPU、内存、磁盘。
- **vLLM 监控**：Chat、Embedding、Reranker 的运行与排队序列数，以及分类型吞吐、延迟和 Chat KV Cache 使用率。
- **服务扩展**：后续可接入 Open WebUI 等其它服务。

## 安装与启动

首次在被监控的 **Ubuntu Server 24.04 amd64** 服务器上安装时，按第 1 到 4 节操作。以 root 身份执行安装和配置，所有本机用户均可使用已安装的命令。

GPU 监控需要可用的 NVIDIA 驱动和 `nvidia-smi`。Docker 监控需要 Docker CLI，vLLM 监控需要已部署的服务。

### 1. 安装系统依赖和 uv

```bash
apt update
apt install -y git curl ca-certificates python3 python3-venv

curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"
uv --version
```

### 2. 为所有用户安装 Joi::Observer

将项目克隆到所选位置，进入仓库根目录后执行下列命令。

```bash
umask 022
install -d -m 0755 /opt/joi-observer-tool
UV_TOOL_DIR=/opt/joi-observer-tool \
UV_TOOL_BIN_DIR=/usr/local/bin \
uv tool install --python /usr/bin/python3 --link-mode copy .
joi-observer --version
```

### 3. 创建共享配置

复制随包示例，让所有本机用户都能读取配置。

```bash
install -d -m 0755 /etc/joi-observer
install -m 0644 "$(/usr/local/bin/joi-observer --example-config)" /etc/joi-observer/config.yaml
```

编辑 `/etc/joi-observer/config.yaml`，按服务器实际部署填写以下项目。

| 配置项 | 如何填写 |
| --- | --- |
| `mount_points` | 填实际存在的挂载点，例如 `["/"]`。最多监控配置的前三项。 |
| `containers` | 填真实容器名称或完整 ID；不监控容器时设为 `[]`。 |
| `models` | 只保留需要监控的模型，填写对应类型、展示名、真实服务名及直接 vLLM 地址；地址不带 `/v1` 或 `/metrics`，不填网关地址。 |
| `gpu_ids` | 为模型填写已确认的 GPU 索引字符串或完整 UUID，用于关联高亮。 |
| `logging.directory` | 填当前用户可写的目录，默认 `~/.joi-observer`。 |

### 4. 启动和日常使用

在服务器的交互式终端中启动

```bash
joi-observer
```

配置按 `--config` 指定的文件、当前目录的 `config.yaml`、系统默认的 `/etc/joi-observer/config.yaml` 的顺序查找。

### 5. 更新已安装版本

退出正在运行的 Joi::Observer。以 root 身份进入此前克隆的仓库根目录，拉取更新并重新安装。

```bash
. "$HOME/.local/bin/env"
umask 022
git pull --ff-only &&
  UV_TOOL_DIR=/opt/joi-observer-tool \
  UV_TOOL_BIN_DIR=/usr/local/bin \
  uv tool install --force --refresh-package joi-observer \
    --python /usr/bin/python3 --link-mode copy . &&
  joi-observer --version
```

更新完成后，各用户重新运行 `joi-observer` 即可。

## 模型导航与键位

↑↓ 按配置顺序选择模型，到首尾停留，长列表随选择滚动。刷新、采集失败和窗口缩放保留选择；切换模型不清空历史或暂停其他来源。

底部显示 `vLLM` 和 `WebUI (disabled)`，暂不切换服务；←→、Enter、p、Tab 无操作。`q` 退出，`t` 切换主题。
