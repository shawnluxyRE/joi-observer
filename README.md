# joi-observer

一个面向 Ubuntu Server 的终端监控工具，通过 TUI 实时展示服务器硬件状态与LLM服务负载。

- **硬件监控**：GPU 利用率、显存、温度与功耗，以及 CPU、内存、磁盘。
- **vLLM 监控**：各模型的运行与排队请求数、Token 吞吐、延迟和 KV Cache 使用率。
- **服务扩展**：后续可接入 Open WebUI 等服务。

## 当前阶段

REQ-001 的公共运行基础已实现：严格 YAML 配置、独立异步调度、只读内存快照、有界历史、异步 ERROR 日志、全屏外壳及终端恢复。REQ-003 已接入显式配置的本机 Docker 容器生命周期采集。硬件与 vLLM 采集器、完整模型导航及双主题仍属于后续需求，对应槽位目前显示未知值或空态。

需求 v1.12 的配置与布局已同步：仅纳入原配置前三个挂载点，全部容器保序保留，显示数量随上半区空间变化；下半区连同服务切换位、键位提示固定占半页。此前 R5 通过结论对应 v1.9，本轮增量的验证和交接结果另见 R4 交接单。

设计入口：[运行架构与内存状态](docs/design/monitor-state.md)、[配置](docs/design/configuration.md)、[启动与终端](docs/design/application-shell.md)、[采集错误日志](docs/design/error-logging.md)、[Docker](docs/design/docker.md)。实现范围与实际验证结果见 [REQ-001 R4 交接](docs/dev-workflow/dev-0/REQ-001/handoff-r4.md) 和 [REQ-003 R4 交接](docs/dev-workflow/dev-0/REQ-003/handoff-r4.md)。

## 安装与启动约定

目标环境为 Ubuntu Server 24.04 amd64、Python 3.12+，使用 **uv** 管理安装与开发环境，终端后端使用标准库 curses。工程采用 src 布局，`pyproject.toml` 注册 `joi-observer` 命令。正式依赖为 PyYAML，测试依赖为 pytest。

日常使用通过 `uv tool install` 安装，uv 为工具维护独立环境。以下步骤假定 uv、Python 3.12 和离线 wheel 包已在本地准备好；使用 `--offline` 避免访问服务器：

```bash
uv --offline tool install --python 3.12 --no-python-downloads --no-index \
  --find-links /path/to/joi-observer/.pytest_cache/offline_wheels /path/to/joi-observer
uv tool update-shell
```

首次执行 `uv tool update-shell` 后重新打开终端，使工具命令目录进入 PATH。随后准备配置：

```bash
mkdir -p ~/.joi-observer
cp "$(joi-observer --example-config)" ~/.joi-observer/config.yaml
# 先编辑 ~/.joi-observer/config.yaml，核对实际监控对象和服务地址。
joi-observer
```

完成一次安装、PATH 配置和用户配置后，以后新开终端直接输入 `joi-observer`，无需手动激活虚拟环境，也无需进入源码目录。工具入口会使用 uv 管理的对应 Python 环境。[uv 工具说明](https://docs.astral.sh/uv/concepts/tools/)

开发时在项目目录通过 `uv run` 使用项目环境，同样无需手动激活：

```bash
cd /path/to/joi-observer
uv --offline run --locked --python 3.12 --no-python-downloads --no-index \
  --find-links .pytest_cache/offline_wheels joi-observer
uv --offline run --locked --python 3.12 --no-python-downloads --no-index \
  --find-links .pytest_cache/offline_wheels --extra test pytest
```

开发环境与已安装工具的环境独立；修改源码后，`uv run` 使用项目源码，已安装的工具需要重新安装更新。`uv run` 会准备项目环境，`--locked` 要求当前依赖与 `uv.lock` 一致。[uv 项目运行说明](https://docs.astral.sh/uv/concepts/projects/run/)

WSL 中的 uv 位于 `/home/shawn/.local/bin/uv`，实测版本为 0.13.6。使用原有 pip 缓存中的原始 wheel 包生成的 `uv.lock` 继续复用；项目环境与工具安装均采用离线依赖，最新测试结果记录在 R4 交接单。锁文件引用仓库相对目录 `.pytest_cache/offline_wheels`，该目录被 Git 忽略，换机器时须一并准备对应 wheel 包；当前二进制包覆盖 CPython 3.12 的 Linux x86_64 / Windows amd64，不能假定覆盖其他 Python 版本或平台。

可用 [restore_offline_wheels.py](docs/dev-workflow/dev-0/REQ-001/evidence/restore_offline_wheels.py) 从本机现有 pip 缓存原样恢复 wheel 目录，使用 `--help` 查看缓存位置参数；它只读取本地档案并校验 SHA-256，不下载或重打包依赖。没有本地缓存时需先离线准备这些包。本轮源码、wheel、真实 PTY、文件权限及工具安装验证的具体证据统一记录在 R4 交接单。

配置优先级：`joi-observer --config /absolute/path/config.yaml` → 当前目录 `config.yaml` → `~/.joi-observer/config.yaml`。指定配置缺失/非法时退出，不回退。随包示例位于 [examples/config.yaml](src/joi_observer/examples/config.yaml)，包含本地部署材料记载的三个模型；这些地址未验证，示例不会自动用于采集。容器列表初始为空，用户填写真实名称；GPU 关联也由用户显式配置。

默认每秒采样、每对象超时 3 秒，约 60 秒历史只保存在内存。默认错误日志为 `~/.joi-observer/error.log`，10,000,000 字节轮转、3 份备份，仅记录采集失败 ERROR；`time` 使用服务器本地 `YYYY-MM-DD HH:MM:SS`，不附带时区信息。相同对象相同错误连续发生最多每 60 秒记录一次。日志不可写时启动前提示一次并继续监控。

布局按全页高度平分：下半区包含服务窗口、服务切换及键位提示，奇数高度时多出的一行留给上半区。无 GPU 或不超过 4 个 GPU 槽时最低为 120×36；5 GPU 场景最低为 120×37，GPU 更多时按设计公式增高，容器数量不提高最低高度。Storage 固定 3 行内容，只纳入原配置前三个挂载点，前项失败不以尾项补位；整个 YAML 仍执行安全校验。Docker 全部配置项持续采集，只显示区域可容纳的前若干项，隐藏不丢失状态或改变采样。页高 44/48/42 行时分别显示前 4/6/3 个容器，36 行时容量可为零；溢出不提示、不滚动、不占用下半区，内容不足时保留空白。低于基础尺寸时显示英文放大提示，`q` 仍可退出。具体分配见[终端设计](docs/design/application-shell.md)。

## Docker 容器配置与边界

在现有 YAML 的 `containers` 中填写稳定的应用内 `id`，以及实际容器名称或完整的 64 位小写十六进制 ID：

```yaml
containers:
  - id: webui
    name: actual-webui-container
  - id: inference
    name: actual-inference-container
```

`name` 精确匹配，不使用 Compose 项目名推断、名称子串或短 ID 前缀，也不自动去掉前导 `/`。按名称监控会在后续采样中跟随同名重建的容器；按完整 ID 监控不会自动改绑。不同 `id` 可以指向同一目标，仍独立采样。

采集使用本机 `docker` CLI 的只读 `container inspect`，固定访问 `unix:///var/run/docker.sock`。运行用户需要已安装 Docker CLI 且具备该 socket 的读取权限；工具不会执行 sudo 或调整权限。命令不使用 shell，子进程移除 `DOCKER_*` 环境变量，不跟随远端 context，也不自动发现 rootless socket。

状态包括 Created、Running、Paused、Restarting、Removing、Exited、Dead。Running 仅表示容器生命周期，不代表应用健康；Exited/Dead 属于成功采集，不产生错误日志。对象不存在、权限不足、命令不可用、超时或响应异常时原位显示 STALE，原因仅写 ERROR 日志，后续成功采样自动恢复。每个容器独立执行、超时和清理；stdout/stderr 各限制为 65,536 字节，原始输出不进入快照或日志。

当前验证使用离线命令样本及本地进程替身，真实 Docker CLI/模板兼容性、socket 权限、错误文案与部署中的清理时限尚未实机验证。

## 离线开发验证

在已有 Python 3.12+、PyYAML 和 pytest 的本地环境中运行，不必安装本包或访问服务：

```text
python -m compileall -q src tests
python -m pytest --collect-only -q
python -m pytest -q --tb=short
```

pytest 从 `pyproject.toml` 将 `src` 加入导入路径。黑盒和集成用例使用临时文件、内存终端与离线采集端口，实际运行配置解析、调度、状态、日志和屏幕生成。新增边界测试未修改既有黑盒预期，R2 的历史失败基线保留供追溯。

本地 Ubuntu 普通用户可进一步运行真实终端与文件权限验证（仅本机 PTY/临时文件）：

```bash
PYTHONPATH=src python3 docs/dev-workflow/dev-0/REQ-001/evidence/verify_pty.py
PYTHONPATH=src python3 docs/dev-workflow/dev-0/REQ-001/evidence/verify_permissions.py
```

这些验证不代表目标服务器或后续具体采集器已验收，不能据此连接部署服务器。
