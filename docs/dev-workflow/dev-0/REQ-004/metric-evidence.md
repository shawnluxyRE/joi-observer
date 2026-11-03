# REQ-004 指标证据与 D-001 核对

- 修订：v1.0，2026-11-02。
- 结论：当前三类部署的核心指标均得到用户提供的原始样本及同容器安装源码支持，D-001 指标核对已完成。完整 R2 阶段状态由 `handoff-r2.md` 汇总，不由本文件单独宣告。
- 证据边界：用户在服务器执行只读采证后提供压缩包；本轮只读分析已解包资料，不联网，不执行包内源码，不向服务发送推理请求。以下明确区分实采事实、源码定义和 Observer 的设计选择。

## 1. 来源、版本与完整性

本地证据根目录为本需求目录下：

```text
evidence/server-9UwOpl9Q/joi-vllm-evidence.9UwOpl9Q/
```

下文 `E/` 代表该根目录；`S/` 代表 `E/containers/qwen3-embedding-vllm/sources/vllm/`。三个容器的 44 个源码文件路径和内容 SHA-256 完全一致，因此 `S/` 的源码行号同时适用于 Chat、Embedding、Reranker。文件行号对应原始文件，不经过格式化或代码执行。

原始采证压缩包的导入 SHA-256 记录为 `69a51042dcbf641e59db5d0f3479376cb53133b911bfff5d37903f8a2aeeb408`，同时保存于 `tests/fixtures/vllm/0.31.0/provenance.json`。下表的正文及解包源码哈希已在本地逐项重新核对。

| 项目 | 实采事实与证据 |
| --- | --- |
| 采证时间 | `E/run.json:3` 为 `2026-11-02T07:06:23.904727+00:00`，即北京时间 2026-11-02 15:06；逐请求 UTC 起止时间另存 sidecar |
| 服务版本 | 三个 `E/http/<port>/version/body.json:1` 及 `E/containers/<container>/package.json:1` 都报告 `0.31.0` |
| 包路径 | 三个 `package.json:1` 均为 `/usr/local/lib/python3.12/dist-packages/vllm` |
| 镜像引用 | 三个 `inspect.json:1` 均报告 `vllm/vllm-openai:v0.31.0@sha256:c1c9f6fd5c109ba7f0546a59f5b2f15fb87f64c77782e90a27b648b42a8e67c3` |
| 模型身份 | 三个 `models/body.json:1` 分别报告 `qwen3.8-flash-next`、`qwen3-embedding-4b`、`qwen3-reranker-0.6b`；与各端点指标的 `model_name` 一致 |
| HTTP 完整性 | 6 份 metrics 的 `http_status.txt` 均为 200、`curl_exit_code.txt` 均为 0，原始正文与错误/时间分离；这证明采证请求成功，不代替载荷语义核对 |
| 源码导出完整性 | 三个 `sources_exit_code.txt` 均为 0；每个 `sources/source-manifest.json` 为 44 文件、697596 字节、`complete_within_allowlist=true`，实际逐文件 SHA-256 与 manifest 全部相符 |
| 完整性的含义 | 完整指采证脚本的源码白名单，不是整个 vLLM 仓库。版本及镜像信息与部署文档一致，但本次未联网逐字比对官方 release；SHA 只保证本地证据内容一致性，不构成官方签名认证 |

源码归档 SHA-256：

| 容器 | `sources.tar.gz` SHA-256 |
| --- | --- |
| `flash-next-vllm` | `4f23ffdeef1c1d5e12f3b1bb6f3ebc254d17461869957622d84624af140c89d9` |
| `qwen3-embedding-vllm` | `4f23ffdeef1c1d5e12f3b1bb6f3ebc254d17461869957622d84624af140c89d9` |
| `qwen3-reranker-vllm` | `f5fbfc073d1e6e5b82993be8ae6fb26a3bf18d33004a3cd00e2a9e5b0d54e847` |

Reranker 归档字节哈希不同，但解包后 44 个源码文件内容哈希一致；不能把 gzip 包字节差异直接解释为源码差异。

原始指标正文 SHA-256：

| 端口 / 轮次 | `E/http/<port>/metrics-<round>/body.prom` SHA-256 |
| --- | --- |
| 8000 / 1 | `81c66a2a9aa2bf5ff37198cf8c6602f16ab767337e58d58465aff90865d6ada7` |
| 8000 / 2 | `24a41bc3532a01683a7e1c5d467e6b899bf5558a34a6b2d7b9c3f01b03766693` |
| 8001 / 1 | `555d3ebf05a93f4a43692559ea158432bdf2a0af9f40b61693b938fc91209e20` |
| 8001 / 2 | `70a36781807a04a535f0c2c169d8b7f3cda6e21acb9e57214bceaf63ed5769a3` |
| 8002 / 1 | `3a3ee9ba7258cd5553d93c9aca2a19e5a0b27dbd31ce78f52c97d49e1041ccf2` |
| 8002 / 2 | `1b58c0612f901e334682785f038e78e954d9016ba3ff5804f437b29ac4369ff6` |

所有 metrics 正文的 `HELP`、`TYPE`、标签和累计值均保留。两轮全文哈希不同不意味着业务计数有增量，Python/HTTP 自身统计可能变化；业务比较必须按字段进行。

## 2. 冻结的三类型映射

精确筛选 `model_name == expected_model_name`，按 `engine` 区分独立序列。三个实采服务均只有 `engine="0"`；多引擎行为来自源码结构和离线构造验证，不声称本次完成多引擎实机验证。

| 展示项 | 类型 | 精确来源 | 单位与算法 | 原始样本行号 |
| --- | --- | --- | --- | --- |
| RUNNING | 全部 | `vllm:num_requests_running` | 同模型所有 engine 的当前内部请求/序列数量求和，单位 `seq` | Chat `body.prom:81–83`；pooling `:55–57` |
| WAITING | 全部 | `vllm:num_requests_waiting` | 同模型所有 engine 求和，单位 `seq` | Chat `:84–86`；pooling `:58–60` |
| Total | 全部 | 同一次有效 RUNNING + WAITING | 单位 `seq`；任一未知时不得合成新总数 | Observer 派生契约 |
| PREFILL | Chat | `vllm:prompt_tokens_total` | 逐 engine 的输入 Token 增量 / 实际采样时间差，`tok/s` | 8000 `:141–143` |
| DECODE | Chat | `vllm:generation_tokens_total` | 逐 engine 的生成 Token 增量 / 实际采样时间差，`tok/s` | 8000 `:163–165` |
| RATE | Embedding / Reranker | `vllm:request_success_total{finished_reason="stop"}` | 逐 engine 正常完成序列增量 / 实际采样时间差，`seq/s` | 8001、8002 `:143–149` |
| TTFT | Chat | `vllm:time_to_first_token_seconds_sum` 与 `_count` | 有效窗口的总时长增量 / 自身观测数增量，秒 | 8000 `:342–343` |
| Avg queue | 全部 | `vllm:request_queue_time_seconds_sum` 与 `_count` | 有效窗口按自身观测数加权，秒 | 8000 `:454–455`；8001、8002 `:404–405` |
| Avg latency | Embedding / Reranker | `vllm:e2e_request_latency_seconds_sum` 与 `_count` | 有效窗口按自身观测数加权，秒 | 8001、8002 `:375–376` |
| KV CACHE | Chat | `vllm:kv_cache_usage_perc` | engine 比例的算术平均 ×100，百分比 | 8000 `:96–98` |

表中 `body.prom` 行号同时适用于对应端点两轮样本。TTFT、生成吞吐及 KV Cache 即使在 pooling 端点出现，也不改变产品按类型规定的不适用性；pooling 不展示这些 Chat 指标的伪造零值。

累计 Token、完成量和 histogram count 从 Prometheus 十进制原文精确解析为非负整数，允许整数值的科学记数法，不经二进制 float 再转 int；例如 Chat 实采 `4.694991e+06` 精确等于 `4694991`。原文非有限、负数、非整数或超资源限制均不能被四舍五入成计数。sum、时间及比例要求有限并满足各自取值约束。

## 3. 单位及 pooling 正常完成依据

### 内部序列不等于 HTTP 请求

- `S/entrypoints/pooling/base/io_processor.py:136–169` 把单次 Embedding 调用的多条输入拆成多个 render request。
- `S/entrypoints/pooling/scoring/io_processor.py:452–489` 为各 query/document 对创建独立 render request。
- `S/entrypoints/pooling/base/serving.py:167–190` 对每个 `engine_input` 调用一次 `engine_client.encode`，并产生独立请求标识；`:204–214` 随后合并这批结果。
- `S/v1/core/sched/scheduler.py:2549–2551` 的 RUNNING/WAITING 来自 scheduler 内部请求集合；`:2887–2892` 形成 `SchedulerStats`。因此三类型负载计数均采用 `seq`，包括 Chat；它不承诺等于 HTTP 并发。
- Embedding 还存在内部拆分路径，见 `S/entrypoints/pooling/embed/io_processor.py:127–167`。Observer 始终沿用实际内部完成计数，不按输入项、候选数、top_n 或配置并发上限换算。

### RATE 只选择 STOP

`S/v1/core/sched/scheduler.py:2111–2114` 对存在 pooling 输出的请求直接设置 `FINISHED_STOPPED`；`S/v1/request.py:404–409` 将其映射为 STOP。正常 pooling 输出未发现走 LENGTH 的路径：LENGTH 对应长度截断或被忽略请求，`:401–403` 说明超长输入被忽略的情形；生成 Token 的 stop 检查属于另一分支，见 scheduler `:2107–2110,2434–2451`。

因此 pooling RATE 固定选择 `finished_reason="stop"`，排除 `length/abort/error/repetition`。这表示正常成功完成的内部序列速率，不是所有终止量。不能因为指标名为 `request_success` 就汇总全部 reason：`S/v1/metrics/loggers.py:1153–1156` 实际按所有已记录 finish reason 增加相应 counter。

## 4. 延迟计时范围与分母

`S/v1/metrics/loggers.py:851–868` 声明 e2e/queue 直方图；`:1153–1162` 在已记录的内部请求终止时写入观测。直方图没有 `finished_reason` 标签，不能筛选出仅 STOP 的延迟，也不能使用 RATE 的 STOP count 作为分母。TTFT、queue、e2e 各自使用自己的 `_sum/_count`。

- **TTFT**：`S/v1/metrics/stats.py:469–475` 在首次 prefill 输出时记录来源内部请求 `arrival_time` 到该输出处理批次时刻的耗时。本期仅 Chat 展示 TTFT。
- **Avg queue**：stats `:520–526,542–545` 为来源 QUEUED 到首次 SCHEDULED 事件时间差；重调度不覆盖首次 SCHEDULED。scheduler `:2582–2583` 记录新增请求 QUEUED，`:1296–1299` 记录 SCHEDULED。它不是当前仍在等待队列的任务已等时长。
- **Avg latency**：stats `:433,453–455,542` 为输出处理批次的 `time.time()` 减来源内部请求 `arrival_time`。`S/v1/engine/output_processor.py:681–684,750–768,882–900` 把完成输出传入统计。
- `S/entrypoints/pooling/base/serving.py:72–82,100–105` 表明之后还要进行整批结果收集、后处理及 HTTP 响应构建。因此 Avg latency 不是完整 HTTP 响应、LiteLLM 网关或客户端耗时。
- Reranker 的 `arrival_time` 在每条内部序列 render 开始时记录，先于模板/编码，见 `S/entrypoints/pooling/scoring/io_processor.py:550–568,596`。故不应把 e2e 称为纯模型执行耗时。
- Embedding 通过 renderer 生成输入，见 `S/entrypoints/pooling/base/io_processor.py:264–271`。本契约只采用已证实的“来源内部请求 arrival_time 至输出处理”定义，不承诺 tokenization/render 是否被完整包含；无需为设计冻结进一步向用户索取材料。

窗口只用两次连续成功观测之间可比较的增量，不使用启动以来总 sum/count 代替最近 60 秒均值。各指标自己的观测集合可能不同：Chat 实采 TTFT count 为 270，而 queue/e2e count 为 269（8000 `body.prom:342,425,454`），直接证明不能复用分母。

## 5. 多引擎与 KV Cache 聚合

- `S/v1/metrics/loggers.py:480–485` 标签为 `model_name,engine`；`S/v1/metrics/utils.py:11–19` 为每个 engine 创建独立 metric child。engine 是统计分片标识，不是 GPU 索引；实采 pooling GPU 配置为同一个 UUID，但指标仍是 `engine="0"`。
- `loggers.py:1035–1048` 更新 per-engine RUNNING/WAITING，WAITING 已包括普通等待和 deferred 部分。不得再叠加 `num_requests_waiting_by_reason`，否则重复计数。
- `loggers.py:508–522` 对 gauge 使用 `multiprocess_mode="mostrecent"`。Observer 对一个 `(model_name,engine,metric)` 只接受一个值；不把 API worker 重复样本叠加。
- Observer 对同模型的各 engine gauge 求和；对累计计数先逐 engine 比较、检查重置，再汇总增量；对延迟先逐 engine 取得合法 sum/count 增量，再按总时长/总观测数计算，不平均各 engine 均值。
- `loggers.py:576–583` 明确 KV 值 `1` 为 100%，`:1050` 来自 scheduler KV 使用率。其聚合日志 `:384–399` 对 engine 使用率做算术平均；Observer 采用相同的 engine 等权平均 ×100。它不是按 cache 容量加权的总占用率，更不是 GPU 显存利用率。
- 聚合所需的 engine 集合不完整时，不把残缺子集当完整总数。集合增删、任一成员重置等使相应差分组失去可比性，当前样本仅用于建立下一段基线。

本次没有多个 engine 的真实样本、故障或重启演练；上述语义由安装源码支持，边界通过离线构造样本验证。没有为补证据制造负载或更改服务部署。

## 6. 空闲、无观测、不适用及失败

两轮均成功取得数据且业务计数未变：

| 实采字段 | Chat | Embedding | Reranker |
| --- | --- | --- | --- |
| RUNNING / WAITING | 0 / 0 | 0 / 0 | 0 / 0 |
| 正常完成 STOP 累计量 | 269 | 365 | 84 |
| 生成 Token 累计量 | 253067 | 本期不适用 | 本期不适用 |
| 输入 Token 累计量 | 4694991 | 本期不展示 | 本期不展示 |
| queue count | 269 | 365 | 84 |
| e2e count | 269，本期不展示 | 365 | 84 |

样本位置见第 2 节。成功且有可比较基线的第二轮吞吐应为有效 `0`；首轮无基线为 `—`。该区间没有新延迟观测，窗口 Avg queue/TTFT/Avg latency 为 `—`，不能借用累计历史均值。正常空闲不是异常，也不代表字段不支持。

三类核心字段在此 profile 的样本和源码中均有依据；缺失本应存在的系列、重复身份、非有限或非法值属于实际字段失败，不可按“pooling 不支持”吞掉。类型不适用字段由配置 profile 决定并正常省略/N/A，不因上游恰好暴露了同名指标而启用。字段缺失仅使相关指标组不可用，其余有效字段保留；实际错误仍按对象标记 STALE。

## 7. 重启识别局限

三个端点的 `body.prom:25–27` 暴露 `process_start_time_seconds`，两轮值稳定；受监控 counter 还带有 `_created` 系列。适配器可以利用已取得的连续性标记变化、逐 engine 计数回退和标签集合变化打断基线。

这些事实不证明已提供每个 engine 的独立生命周期 ID。API 进程未重启、engine 内部重启后计数又超过旧值的情形，可能无法仅凭该采样识别。不能用 model API 的 `created` 字段作为 engine 启动时间，也不能承诺检测不可见重启。`S/v1/metrics/prometheus.py:21–35` 还提示多进程目录若跨运行遗留可导致不准确指标；Observer 不读取或清理该目录，不自动修复服务。

全对象失败后全部差分组断开；局部失败至少断开受影响组；恢复首个有效样本只建立新基线。这样避免跨已知故障、重置或身份变化产生负速率或假峰值，但不把能力局限隐藏为“始终可靠的重启检测”。

## 8. 对设计和测试的约束

正式设计见 [`docs/design/vllm.md`](../../../design/vllm.md)。实采样本证明三种类型的可用字段及安装版本；窗口边界、负载增量、不同 engine、异常字段、失败/恢复等用明确标注的合成离线输入验证，不能声称是实机观测。

完整采证包、完整 metrics 正文和安装源码保留在默认忽略的 `evidence/` 中；本文件保留路径、哈希、行号及结论供交接复核。可提交的 parser fixture 位于 `tests/fixtures/vllm/0.31.0/`：version/models 为原样字节，metrics 为保留标签和值的必要行摘录；`provenance.json` 记录原文件哈希、保留行号及 fixture 哈希。测试另外生成的边界变体明确视为合成输入，不冒充新实采事实。

R2 可基于上述契约冻结 D-001；若后续版本、运行模式或实采事实发生变化，应重新核对对应 profile，而不把本次结论外推到所有历史/未来 vLLM 版本。
