# joi-observer

一个面向 Ubuntu Server 的终端监控工具，通过 TUI 实时展示服务器硬件状态与LLM服务负载。

- **硬件监控**：GPU 利用率、显存、温度与功耗，以及 CPU、内存、磁盘。
- **vLLM 监控**：Chat、Embedding、Reranker 的运行与排队序列数，以及分类型吞吐、延迟和 Chat KV Cache 使用率。
- **服务扩展**：后续可接入 Open WebUI 等服务。

## 当前阶段

REQ-001 公共运行基础、REQ-002 本机硬件、REQ-003 Docker 生命周期、REQ-004 三类型 vLLM 采集与显示，以及 REQ-005 模型导航与服务入口已实现。公共能力包括严格 YAML 配置、独立异步调度、只读内存快照、有界历史、异步 ERROR 日志、全屏终端与终端恢复。默认选择首个配置模型，↑↓ 切换详情、单位、历史和关联 GPU 高亮，所有模型持续采集。REQ-006 已实现双主题、Neon Grid 字符排版、60 FPS 调度与稳定柱状历史；本轮验证和待验收项见 [REQ-006 R4 交接](docs/dev-workflow/dev-0/REQ-006/handoff-r4.md)。REQ-004 已按 R2 确认将统一标签上限修订为 64，以兼容完整响应中的正常服务元数据，并通过 R5 完整响应复验；旧 7a4e950 测试包不包含此修复。REQ-004 结果见 [R4 交接单](docs/dev-workflow/dev-0/REQ-004/handoff-r4.md) 和 [R5 交接单](docs/dev-workflow/dev-0/REQ-004/handoff-r5.md)。

需求 v1.12 的配置与布局已同步：仅纳入原配置前三个挂载点，全部容器保序保留，显示数量随上半区空间变化；下半区连同服务切换位、键位提示固定占半页。REQ-001、REQ-002 和 REQ-003 均已通过各自范围的 R5 离线验收。

深灰轨道源码审查阶段曾按用户要求暂不构建安装包；随后用户明确要求重建。当前源码的安装交付以 [重建验证记录](docs/dev-workflow/dev-0/REQ-006/evidence/r5-track-build/uv-install-results.json) 及对应服务器安装包为准，包含统一半块与深灰track。既有GUI启动与回放入口未随此次打包更新，仍属此前版本，不能作为当前安装包内容的依据。

REQ-005 的会话控制器、默认应用接线及服务页脚已完成；直接构造应用与正式 CLI 使用相同的默认导航。已通过 R5 离线验收及代码、测试逻辑复查，WSL Ubuntu 全量 1450 项通过；验收范围与证据见 [REQ-005 R5 交接](docs/dev-workflow/dev-0/REQ-005/handoff-r5.md)，实现记录见 [R4 交接](docs/dev-workflow/dev-0/REQ-005/handoff-r4.md)，契约见 [模型导航设计](docs/design/navigation.md)。

设计入口：[本机硬件](docs/design/hardware.md)、[Docker](docs/design/docker.md)、[vLLM](docs/design/vllm.md)、[模型导航](docs/design/navigation.md)、[运行架构与内存状态](docs/design/monitor-state.md)、[配置](docs/design/configuration.md)、[启动与终端](docs/design/application-shell.md)、[采集错误日志](docs/design/error-logging.md)。各需求的实现范围与验证记录见 [REQ-001](docs/dev-workflow/dev-0/REQ-001/handoff-r4.md)、[REQ-002](docs/dev-workflow/dev-0/REQ-002/handoff-r4.md)、[REQ-003](docs/dev-workflow/dev-0/REQ-003/handoff-r4.md)、[REQ-004](docs/dev-workflow/dev-0/REQ-004/handoff-r4.md) 和 [REQ-005](docs/dev-workflow/dev-0/REQ-005/handoff-r4.md) 的 R4 交接。

硬件采集在运行工具的 Ubuntu 主机本地执行。GPU 需要已安装并可查询的 `nvidia-smi`，按完整 UUID 保持设备身份；新卡追加，暂时消失的卡保留原位置并显示 STALE。发现器失败不阻断已知卡和 Host 采样；成功无卡显示 `No NVIDIA GPUs`。不会安装驱动或修改硬件。按当前选中模型计算显式 GPU 关联色，索引只使用新鲜且唯一的采样值，未知映射不猜测；导航不改变 GPU 集合、顺序或采样。

CPU 使用 `/proc/stat` 的整机累计 tick 差分，首次及失败恢复后的第一轮显示 `—`。RAM 使用 `MemTotal - MemAvailable`，不以 MemFree 或 GPU 显存替代。Storage 精确验证挂载点，并在容量读取前后核对挂载身份；未挂载不回退到父文件系统，也不以第四项补位。容量使用 `f_frsize × f_blocks` 与 `f_frsize × (f_blocks - f_bfree)`，包含保留块；界面统一显示 GiB/TiB。RAM 的 GiB/TiB 和 Storage 的 GiB 直接由原始字节四舍五入为整数（ROUND_HALF_UP），Storage 的 TiB 和 GPU 显存保留一位小数。CPU/Storage已有百分比固定显示一位小数，如 `30.0%`、`0.0%`、`100.0%`；RAM保持容量行与下行条，不添加百分比文字。显示精度不改变采样、原始比例或GPU利用率。Storage 左侧路径和空配置文字使用正文色，容量与中点分隔保持灰色、百分比保持正文色。前三个配置挂载点任一失败时，仅在 Storage 标题右上角显示一次 STALE；内容行容量和百分比仍贴右，全部恢复后清除标题状态。GPU 显存按驱动 MiB 换算，功率是驱动最近测得的板卡功率，可能为一秒平均。失败原因仅写 ERROR 日志。

文件及 statvfs 读取放在可终止的包内 worker 中，NVIDIA 查询使用固定 argv 的本地子进程；两路输出各限 1 MiB。每个采集器与发现器独占 IO，超时/取消会终止并回收本端口进程。上述硬件采集不建立网络连接。目标服务器的驱动、权限、挂载及无卡输出尚未现场验证，本地离线测试不能替代部署验收。

## 安装与启动约定

目标环境为 Ubuntu Server 24.04 amd64、Python 3.12+，使用 **uv** 管理安装与开发环境，终端后端使用标准库 curses。工程采用 src 布局，`pyproject.toml` 注册 `joi-observer` 命令。正式依赖为 PyYAML 与 HTTPX（`>=0.28.1,<0.29`），测试依赖为 pytest。

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

当前工作区的完整离线 wheel 集合包含 HTTPX 及其传递依赖，来源与 SHA-256 见 [REQ-005 离线包清单](docs/dev-workflow/dev-0/REQ-005/evidence/r4-offline-wheels.json)。这些包按既有清单从本地文件及 pip 缓存原样恢复，没有下载或重打包。证据与 wheel 目录均被 Git 忽略，克隆仓库时不会自动获得；须从已有交付材料另行准备。源码、wheel、真实 PTY 和工具安装验证记录在 R4 交接单。

配置优先级：`joi-observer --config /absolute/path/config.yaml` → 当前目录 `config.yaml` → `~/.joi-observer/config.yaml`。指定配置缺失/非法时退出，不回退。随包示例位于 [examples/config.yaml](src/joi_observer/examples/config.yaml)，包含本地部署材料记载的三个模型；地址仅供部署参考，使用时须核对实际目标，示例不会自动用于采集。随包容器示例为 `id: chat-container`、`name: flash-next-vllm`，复制后须替换为实际容器名称或完整 ID；不监控容器时设为 `containers: []`。示例名称不代表已探测到该容器；GPU 关联也由用户显式配置。

默认每秒采样、每对象超时 3 秒，约 60 秒历史只保存在内存。界面按固定60 Hz节拍（每1/60秒，约16.7ms）调度，慢终端跳过过期帧，显示刷新不会增加采集频率，不新增帧率切换或配置项。原柱状历史采用固定最近60秒轴与稳定时间桶；没有样本和失败区间留白，有效0显示点标记。纵轴采用1/2/5十进制档位，超出即升档，连续低于当前档5秒后降档；每个模型独立保留尺度，切换主题/模型和缩放不清空。默认错误日志为 `~/.joi-observer/error.log`，10,000,000 字节轮转、3 份备份，仅记录采集失败 ERROR；`time` 使用服务器本地 `YYYY-MM-DD HH:MM:SS`，不附带时区信息。相同对象相同错误连续发生最多每 60 秒记录一次。日志不可写时启动前提示一次并继续监控。

布局按全页高度平分：下半区包含服务窗口、服务切换及键位提示，奇数高度时多出的一行留给上半区。无 GPU 或不超过 4 个 GPU 槽时最低为 120×36；5 GPU 场景最低为 120×37，GPU 更多时按设计公式增高，容器数量不提高最低高度。Storage 固定 3 行内容，只纳入原配置前三个挂载点，前项失败不以尾项补位；整个 YAML 仍执行安全校验。Docker 全部配置项持续采集，只显示区域可容纳的前若干项，隐藏不丢失状态或改变采样。页高 44/48/42 行时分别显示前 4/6/3 个容器，36 行时容量可为零；溢出不提示、不滚动、不占用下半区，内容不足时保留空白。低于基础尺寸时显示英文放大提示，仍处理 ↑↓、t 和 q；放大后显示最新选择。具体分配见[终端设计](docs/design/application-shell.md)。

页眉第二行固定使用设备标签 `H3C R5300 G6`，后接 ` / ` 和本地 Ubuntu 发行版本，右侧仍显示时间。启动时按 `/etc/os-release`、`/usr/lib/os-release` 顺序读取，使用首个读取成功文件实际提供的字段：优先非空 `PRETTY_NAME`，否则组合 `NAME` 与 `VERSION_ID`，缺失或空值分别用 `Ubuntu`、`—`。显式名称 `Linux` 正常保留；空文件、读取或编码失败显示 `Ubuntu —`，不拼接低优先级文件、不读取内核版本或探测设备型号。

GPU、CPU、RAM的利用率条中，填充和未填充轨道都显示为`▌`，每段仍占原来一个字符格。轨道独立使用双主题相同的深灰track色`#3E4A5B`；关联GPU填充仍为主色，未关联GPU填充仍为原muted灰色，CPU/RAM填充仍为辅色。分段数、条宽、数字位置和百分比计算保持，不改变其他灰色文字或vLLM竖向历史柱。

## 模型导航与键位

↑↓ 按配置顺序单步选择模型，到首尾停留。同名、同类型或同端点但 id 不同的模型仍独立；模型列表较长时选中项保持可见。空配置显示英文空态，零或一个模型时方向键安全。刷新、采集失败和窗口缩放保留选择，切换模型不清空历史或暂停其他来源。

底部固定显示当前 `vLLM` 和 `WebUI (disabled)`；←→ 不切换服务。Enter、p、Tab 无操作。正常尺寸下页脚为 `↑↓ Select model    t Theme    q Quit`，其中 `Select model` 来自当前服务描述。q 全局退出，t 按 Hologram → Moonlight → Hologram 切换，保持模型和历史。每个新应用默认 Hologram，不保存偏好；同一个应用实例再次运行保留其选择和历史尺度。

两主题同步更新文字、指标条和空白背景；仅新鲜正等待数与QUEUED使用琥珀色。支持改色的256色终端使用精确RGB，退出时恢复全部七个私有色槽；六个前景色对共用背景，需要COLOR_PAIRS至少7。固定256色终端使用最近颜色，track对应标准索引239；低色终端使用基础色，无色或颜色资源不足时保留单色操作。主题变化时整帧重绘一次，普通同主题帧仍采用差分刷新。右上角Theme仅作状态展示，不启用鼠标。硬件数值右对齐、固定24列模型栏、双统计块和四列指标保持；过宽数值保留指数/单位，无法容纳时用明确省略符。具体规则见[主题设计](docs/design/theme.md)。

当前`TERM=xterm`会话保持原终端设置。基础色模式下，Moonlight辅色使用MAGENTA加A_BOLD近似亮紫，track使用BLACK加A_BOLD近似深灰；muted仍为WHITE加A_DIM。实际亮度、RGB和字重由终端ANSI调色板及bold处理决定，不保证等于精确目标色。精确RGB和固定256色模式保留各自策略；程序不修改TERM，也不要求切换终端类型。

vLLM 右侧 RUNNING/WAITING 数值及历史图上方四项指标的真实数字使用粗体，包括 0、科学记数和 STALE 保留数字；`—`、`N/A`、`…`、左栏计数及标签等保持原样。颜色角色不变；终端可能将粗体同时显示为更亮的颜色，具体效果取决于终端设置。

右侧模型名、RUNNING/WAITING 统计和 DECODE HISTORY/RATE HISTORY 标题上方各留一行空白。左侧模型栏及半页布局保持，历史图区在原服务预算内减少三行；最小尺寸下仍保留一行柱图，放大窗口可增加图高。

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

## vLLM 配置与指标口径

兼容范围固定为 vLLM **0.31.0**，三类映射已基于用户提供的采样和安装源码核对。[模块设计](docs/design/vllm.md)和[指标证据](docs/dev-workflow/dev-0/REQ-004/metric-evidence.md)记录精确映射。每个模型独立顺序读取其直接 origin 的 `/version`、`/v1/models`、`/metrics`，三次 GET 共用本轮超时，每份解压后响应最多 2 MiB。启用 HTTPS 证书验证，禁用环境代理、重定向和自动重试；不访问 LiteLLM、WebUI 或推理接口。

`id` 用于独立状态身份，`name` 同时用于左侧模型列表和右侧详情标题，可配置为 `Flash-Next`、`Embedding`、`Reranker` 等短名称；不另设仅左侧的别名字段。可选 `served_model_name` 精确指定服务报告的模型名，省略时回退 `name`，所以使用短展示名时应显式保留真实服务名。显式值须为 1～128 个可打印字符，无首尾空白或控制字符，不能为 null。同名或同地址的不同 id 不合并。例如：

```yaml
models:
  - id: chat
    type: chat
    name: Flash-Next
    served_model_name: qwen3.8-flash-next
    base_url: http://127.0.0.1:8000
    gpu_ids: []
  - id: embedding
    type: embedding
    name: Embedding
    served_model_name: qwen3-embedding-4b
    base_url: http://127.0.0.1:8001
    gpu_ids: []
  - id: reranker
    type: reranker
    name: Reranker
    served_model_name: qwen3-reranker-0.6b
    base_url: http://127.0.0.1:8002
    gpu_ids: []
```

- RUNNING/WAITING/Total表示vLLM内部请求或序列数量，不是HTTP请求数，也不包含LiteLLM尚未进入vLLM的队列。
- Chat DECODE/PREFILL采用生成/输入Token累计差分；输入统计沿用来源，包含缓存等来源计入的Token，不表示纯计算吞吐。
- Embedding/Reranker RATE为正常STOP完成的内部序列率`seq/s`，不按HTTP批大小、候选数量或top_n换算。abort/error/length/repetition不计入这个完成速率。
- TTFT与Avg latency从来源记录的内部序列arrival_time计至相关输出处理阶段；Avg latency不包括之后整批后处理、完整HTTP发送、网关或客户端耗时，也不承诺Embedding的tokenization是否计入。Avg queue是来源记录的首次入队至首次调度时间，在结束统计时写入，不是等待中任务目前等了多久。
- 每种延迟按最近60秒可比较区间的增量总秒数/自身增量观测数计算；直方图可能包含来源记录的非成功终止，不能共用RATE分母。首次无基线或无新观测为`—`，可比较无吞吐增量才为0。
- Chat KV CACHE为各engine报告使用率的算术平均，不等于GPU显存占比；pooling不展示生成吞吐、TTFT和KV指标。engine不是GPU编号，不按TP或显卡数重复汇总。

历史、基线及正常指标仅驻内存。模型失败原位显示 STALE，原因仅进入 ERROR 日志，其他模型继续更新；部分字段失败保留旧值，有效组独立更新，Total 不混用新旧负载数。任何失败点在历史中留空，恢复首点对断开的组重新建基线。延迟窗口只纳入完整落在最近 60 秒内的可比较区间，按各指标自身观测数加权。

计数回退、引擎集合变化、process/created 标记变化或可用性变化会打断相应基线；若重启未暴露标记且新计数已赶超旧值，无法保证识别，不推断不存在的重启信号。当前验证覆盖原始样本、离线变形、多 engine 算法与真实 HTTPX 内存传输；未连接目标服务，也未执行真实网络/TLS 握手、生产负载或实机重启演练。

## 离线开发验证

产品目标为 Ubuntu Server 24.04 amd64；必需验证在已有 Python 3.12+、PyYAML、HTTPX 和 pytest 的本地 Ubuntu 或 WSL Ubuntu 环境中运行。Windows 工作区通过 WSL 执行以下命令，不必安装本包或访问服务；不要求维护原生 Windows 专用测试或执行 Windows 全量回归，历史验证记录保留：

```text
python -m compileall -q src tests
python -m pytest --collect-only -q
python -m pytest -q --tb=short
```

pytest 从 `pyproject.toml` 将 `src` 加入导入路径。黑盒和集成用例使用临时文件、内存终端与离线采集端口，实际运行配置解析、调度、状态、日志和屏幕生成。REQ-006按需求v1.24同步默认主题、60FPS、固定历史轴/尺度、HTML对应排版，以及用户GUI复核后的Storage标题状态、RAM/Storage容量精度、CPU/Storage固定一位百分比与可配置模型展示名，以及固定设备标签、本地发行版本、Storage路径正文色、非空容器示例、低色Moonlight近似、硬件同字形分段及独立深灰track、os-release实际字段回退、右侧关键数字粗体和三处留白；RAM不新增百分比文字，其他采集/计算契约保持。R2各版历史失败基线保留供追溯，最新同步结果见REQ-006交接。

真实终端用例已包含在全量测试中，也可由本地 Ubuntu 普通用户单独运行（仅本机 PTY）：

```bash
python -m pytest -q tests/test_terminal_pty.py tests/test_hardware_pty.py tests/test_vllm_pty.py tests/test_navigation_pty.py
```

这些验证不代表目标服务器或后续具体采集器已验收，不能据此连接部署服务器。
