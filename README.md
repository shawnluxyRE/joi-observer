# joi-observer

一个面向 Ubuntu Server 的终端监控工具，通过 TUI 实时展示服务器硬件状态与LLM服务负载。

- **硬件监控**：GPU 利用率、显存、温度与功耗，以及 CPU、内存、磁盘。
- **vLLM 监控**：Chat、Embedding、Reranker 的运行与排队序列数，以及分类型吞吐、延迟和 Chat KV Cache 使用率。
- **服务扩展**：后续可接入 Open WebUI 等其它服务。

## 安装与启动

以下步骤在被监控的 **Ubuntu Server 24.04 amd64** 服务器上执行，安装过程需要联网访问 Ubuntu 软件源、GitHub、uv 下载站及 Python 包源。

GPU 监控需要服务器已有可用的 NVIDIA 驱动和 `nvidia-smi`；Docker 监控需要 Docker CLI 及当前用户访问本机 Docker socket 的权限；vLLM 服务需提前部署。
Joi::Observer 不负责安装或启动这些服务。建议将终端放大到至少 120 列 × 40 行，GPU 较多时按界面提示继续放大。

### 1. 安装系统依赖和 uv

```bash
sudo apt update
sudo apt install -y git curl ca-certificates python3 python3-venv vim

curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"
uv --version
```

uv 按[官方安装方式](https://docs.astral.sh/uv/getting-started/installation/)安装到当前用户目录；加载环境脚本后，当前终端即可使用。

### 2. 安装工具

将项目克隆到所选位置，然后进入仓库根目录（包含 `pyproject.toml` 的目录）执行：

```bash
uv tool install --python /usr/bin/python3 .
uv tool update-shell
export PATH="$(uv tool dir --bin):$PATH"
joi-observer --version
```

`uv tool install` 会为工具创建独立环境，并联网下载所需依赖；不需要另外准备离线 wheel 包。安装完成后，命令可直接使用，无需激活虚拟环境或进入源码目录。工具安装和命令路径说明见[uv 官方文档](https://docs.astral.sh/uv/guides/tools/#installing-tools)。

### 3. 创建并修改监控配置

首次使用先复制随包示例，再按服务器实际部署修改：

```bash
mkdir -p ~/.joi-observer
cp "$(joi-observer --example-config)" ~/.joi-observer/config.yaml
vim ~/.joi-observer/config.yaml
```

启动前检查以下项目：

| 配置项 | 如何填写 |
| --- | --- |
| `mount_points` | 填实际存在的挂载点，例如 `["/"]`。最多监控配置的前三项。 |
| `containers` | 填真实容器名称或完整 ID；不监控容器时设为 `[]`。 |
| `models` | 只保留需要监控的模型，填写对应类型、展示名、真实服务名及直接 vLLM 地址；地址不带 `/v1` 或 `/metrics`，不填网关地址。 |
| `gpu_ids` | 为模型填写已确认的 GPU 索引字符串或完整 UUID，用于关联高亮。 |
| `logging.directory` | 填当前用户可写的目录，默认 `~/.joi-observer`。 |

默认每秒采样一次，每个对象超时 3 秒。

### 4. 启动和日常使用

在服务器的交互式终端中启动

```bash
joi-observer
```

默认先查找当前目录的 `config.yaml`，再查找 `~/.joi-observer/config.yaml`；若需要固定使用某份配置，继续带上 `--config`。

↑↓ 选择模型，`t` 切换主题，`q` 退出。终端过小时按提示放大。某个对象显示 STALE 时，可查看 `~/.joi-observer/error.log` 中的采集错误。

### 5. 更新已安装版本

退出正在运行的 Joi::Observer，进入此前克隆的仓库根目录，拉取更新并重新安装：

```bash
git pull --ff-only
uv tool install --force --python /usr/bin/python3 .
joi-observer --version
```

更新后重新启动即可；`~/.joi-observer/config.yaml` 会保留，不需要重新复制示例。

## 模型导航与键位

↑↓ 按配置顺序选择模型，到首尾停留，长列表随选择滚动。刷新、采集失败和窗口缩放保留选择；切换模型不清空历史或暂停其他来源。

底部显示 `vLLM` 和 `WebUI (disabled)`，暂不切换服务；←→、Enter、p、Tab 无操作。`q` 退出，`t` 切换主题。
