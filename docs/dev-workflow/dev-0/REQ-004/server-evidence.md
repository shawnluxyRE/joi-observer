# REQ-004 服务器只读采证

本轮采证已由用户完成并回传 `joi-vllm-evidence.9UwOpl9Q.tar.gz`，核对结论见 [metric-evidence.md](metric-evidence.md)。以下保留原采证方法与执行前假设，不表示仍等待用户重复采集。

此步骤由用户手动在真实 Ubuntu 服务器执行。Codex 不执行脚本、不连接服务器；WSL 的语法检查或离线测试不构成真实 vLLM 验证。脚本只获取已有服务的资料，不发送推理请求，也不启停、重启、更新或修改服务。

## 当前事实与待核对项

本地部署文档记载如下配置，尚未以本轮实机采证确认：

| 类型 | 容器名 | served-model-name | 宿主机回环端口 | 运行方式 |
| --- | --- | --- | --- | --- |
| Chat | `flash-next-vllm` | `qwen3.8-flash-next` | 8000 | 生成，TP=4、EP |
| Embedding | `qwen3-embedding-vllm` | `qwen3-embedding-4b` | 8001 | pooling，TP=1，embed |
| Reranker | `qwen3-reranker-vllm` | `qwen3-reranker-0.6b` | 8002 | pooling，TP=1，classify |

- 三者使用 `vllm/vllm-openai:v0.31.0@sha256:c1c9f6fd5c109ba7f0546a59f5b2f15fb87f64c77782e90a27b648b42a8e67c3`；release 提交为 `db9527a46873454610df6dbedf79a36d6bf1a7f6`。
- Chat 文档绑定 GPU 索引 0–3；另外两个容器共用 `GPU-4cc0dd71-92d4-9393-40d5-53066cdbab95`。本脚本仅读取 Docker 已配置的设备请求，不运行 `nvidia-smi`、CUDA 或其他 GPU 探测。
- 文档称三个回环服务当前未设置 API Key；脚本不读取 `.env`、密钥、容器环境变量、完整启动命令或服务日志。401/403 作为实际结果保留，不尝试补认证。
- 文档没有 Prometheus 指标、样本或统计实现证据。核心指标名、标签、处理单位、延迟计时范围、多引擎汇总、pooling 可用性及重启识别均待下面的输出核对。

依据：`D:/Documents/llm_server/Ubuntu_Server_03_显卡驱动.md` 第 6.2、8.2、9.1、9.3 节，以及 `D:/Documents/llm_server/Ubuntu_Server_04_服务部署.md` 第 3.3 节。这些是本地文档事实，不代表运行实例仍与其一致。

## 手动执行

把同目录的 `collect-vllm-evidence.sh` 手动传到服务器上的任意工作目录。依赖：Bash、curl、Docker CLI、宿主机 Python 3，以及 Ubuntu 通常已有的 `mktemp`、`timeout`、`date`、`sleep`、`mkdir`、`mv`（GNU coreutils）；三个运行容器内需要 Python 3 及已安装的 vLLM distribution 元数据。打包使用 Python 标准库，不要求安装 tar、第三方 Python 包或 vLLM 到宿主机。

普通用户已具有 Docker 访问权限时：

```bash
bash ./collect-vllm-evidence.sh
```

需要 sudo 访问 Docker 时：

```bash
sudo -v && bash ./collect-vllm-evidence.sh --sudo
```

`--sudo` 只对 Docker 命令使用 `sudo -n`，不会让整个脚本以 root 运行，也不会读取密码。Docker CLI 显式指定 `--host unix:///var/run/docker.sock`，只访问本机 Docker socket，不采用环境变量或 context 中配置的远端地址；如果使用其他本机 socket，先回报该差异。如果容器名与上表不同，先修改脚本顶部 `containers=(...)` 数组。HTTP 目标固定为 `127.0.0.1:8000`、`:8001`、`:8002`；地址不匹配时先回报部署差异，不改为 LiteLLM、WebUI 或其他网关。

脚本使用 `umask 077` 和 `mktemp -d` 建立私有采证目录，最后输出目录及同名 `.tar.gz` 路径。目录和压缩包都保留，不自动删除。把输出的 `.tar.gz` 交回当前 REQ-004 设计对话；无需提供环境配置、密钥或模型输入输出。

## 采集范围与失败标识

1. HTTP 只发 GET：每个端点各一次 `/version`、`/v1/models`，再进行两轮 `/metrics`，轮次之间至少暂停 2 秒。请求顺序执行，实际间隔以每次请求的 UTC 起止时间为准，不把名义 2 秒当计算分母。没有专门制造负载，空闲样本也是有效证据。
2. curl 忽略用户 `.curlrc`，禁用代理（含 `--noproxy '*'`），不跟随重定向；连接超时 2 秒、单请求总超时 8 秒、响应上限 2 MiB、不重试。HTTP 状态、curl 退出码、错误及 UTC 时间全部写旁路文件，不混入指标正文。只有 HTTP 200 且 curl 成功的正文命名为 `body.prom`/`body.json`；这些仍是待核对的原始载荷，不保证内容格式或语义有效。其他正文保留为 `response.partial`，不能作为正常业务样本。
3. Docker 仅读取容器名、配置镜像引用、镜像 ID、生命周期状态、启动时间、设备请求及端口映射；另使用 `importlib.metadata` 读取已安装 vLLM 版本与包目录。不导入 `vllm`，不调用 GPU，不读取完整 inspect、环境或日志。每项退出码和 stderr 独立保存；失败的 inspect/package 文件不能作为成功证据。
4. 每个容器均以 `python3 -B` 只读导出安装包内下列源码：`v1/metrics/` 和 `entrypoints/pooling/` 下全部可读取的 `.py`，以及 `v1/request.py`、`v1/engine/core.py`、`v1/engine/output_processor.py`、`v1/core/sched/scheduler.py`。不复制整个安装包，不包含字节码、模型权重或挂载配置。拒绝符号链接，每文件最多 2 MiB、每容器源码合计最多 20 MiB，目录枚举最多 4096 项、深度最多 16 层。源码读取和打包均在内存中完成，标准输出传回宿主机；不会在容器内写文件。
5. 源码归档内的 `source-manifest.json` 记录版本、源路径、文件大小、SHA-256 和缺失/被跳过原因。部分源码缺失时归档可以成功生成，但 `complete_within_allowlist=false`；不得据此声称语义已经核实。没有任何允许的源码可读、命令超时或其他导出失败时保留 `sources.partial` 与错误，不命名为成功的 `sources.tar.gz`。Docker 元数据读取限时 15 秒，源码读取限时 45 秒；超时后最多再等 2 秒强制结束对应采证命令。

## 输出的使用边界

指标的 `HELP`、`TYPE`、全部标签及 `_sum`/`_count` 必须完整保留，不能只抄指标名或截图。两次样本用于核对暴露结构及可比较区间；若空闲期间无计数变化，不为采证额外调用推理。

指标名中的 `request` 不足以证明其计量单位是完整 HTTP 请求。需要结合安装版本及源码核对内部序列、请求拆分、完成计数、延迟记录时点和引擎标签；不能按 Embedding 输入批大小、Reranker 候选数或 `top_n` 自行换算。如果白名单源码仍不足，后续只补明确缺失的代码路径；不会把缺失项默认为支持。

回交前可以检查压缩包是否包含预期的三个端点与三个容器目录。采证失败、404、鉴权拒绝、找不到容器、源文件缺失都应保留原样并说明，不用模拟值替换。只有证据核对完成后，R2 才可确认三类模型的指标契约；核心能力不满足需求时按 `requirements.md` 的 D-001 记录差异并返回 R1。
