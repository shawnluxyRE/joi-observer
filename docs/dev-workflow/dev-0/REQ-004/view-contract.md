# REQ-004 服务窗口展示契约

- 修订：v1.0，2026-11-02；R2 接口骨架与黑盒契约，不包含业务实现。
- 代码：`src/joi_observer/tui/vllm.py`，公开入口 `vllm_cells`。
- 测试：`tests/test_vllm_view.py`；仅使用冻结快照和配置，无 HTTP、Docker 或 GPU。
- 上级设计：[vLLM 模块](../../../design/vllm.md)。

## 职责与输入

`vllm_cells(snapshot, config, region, view, *, now)` 返回服务区内容 `tuple[TextCell,...]`。只读取 `(collector="vllm", object_id=config.id)`，不持有采集器、Monitor 或状态写接口，不计算计数差分、延迟窗口或跨采样 Total。选择、主题和调用次数不会影响采集、历史或快照 revision。

`now` 是与历史点同域的有限非负单调秒数，不能从页眉的 datetime 墙钟转换。`compose_frame` 新增可选关键字 `monotonic_now: float | None = None`，显式值用于离线时钟，缺省生产路径取 `time.monotonic()`，再传给本函数。当前只声明参数，尚未接入本函数；R4 负责在保留半页区域计算的前提下替换原指标逐行占位输出。

## 固定槽位

输入 `Region("service", row, column, width, height)` 包含外边框，至少 `120×16`；外边框由 `compose_frame` 绘制，本函数只写内部。左栏为区域宽度的前三分之一，右栏从 `column + width//3 + 2` 开始，右侧保留到 `column + width - 3`。名称、类型、状态应分别占可裁切的单行槽，不允许名称挤掉状态。

| 区域 / 相对行 | 内容 |
| --- | --- |
| 左栏 `+1,+2` 起每项两行 | 第一行：展示名、英文类型、状态；第二行：RUNNING/WAITING 与 seq 单位 |
| 右栏 `+1` | 选中模型名、类型、状态；状态预留6字符以同时容纳 QUEUED/STALE/READY/— |
| 右栏 `+2` | 配置的直接服务地址，secondary 色 |
| 右栏 `+4` | RUNNING、WAITING、Total，单位 seq；直接使用 State 的三个字段 |
| 右栏 `+6` 两列 | Chat：DECODE/PREFILL；pooling：RATE/N/A |
| 右栏 `+7` 两列 | Chat：TTFT/Avg queue；pooling：Avg queue/Avg latency |
| 右栏 `+8` | Chat：KV CACHE；pooling：N/A，不显示 Chat KV 标签 |
| 右栏 `+9` | Chat：DECODE HISTORY / tok/s；pooling：RATE HISTORY / seq/s |
| 右栏 `+10 ... height-3` | 竖柱图区；最小高度16时为4行，窗口增高后只扩充此区及左栏容量 |
| 右栏 `height-2` | 相对时间轴；固定保留一行 |

左栏容量为 `(height-2)//2`，按配置顺序保留包含选择项的连续窗口；列表溢出不提高整个界面最小高度。未知选中id或None回退首模型。无配置时仅在内部显示一次 `No models configured`，不绘制无对象指标和历史。选中名使用 primary，其他模型名为 text。方向键事件及 WebUI 禁用交互仍由 REQ-005负责，完整主题映射由 REQ-006负责；本函数只消费 ViewSelection。

## 指标和状态

字段名固定为 `running`、`waiting`、`total`、`decode_rate`、`prefill_rate`、`rate`、`ttft_seconds`、`queue_seconds`、`latency_seconds`、`kv_cache_percent`。Chat三项负载为seq、吞吐为tok/s；pooling RATE为seq/s。显示标签与字段名分离，不能输出原始字段名或任意附加 Metric。

None为`—`，有效0正常显示0；不适用为N/A。仅模型已采样、非stale、RUNNING/WAITING均有效时显示READY/QUEUED。等待>0显示QUEUED，否则READY。只有QUEUED标签和新鲜正等待值采用amber；WAITING标签、0、STALE期间保留的旧等待值都为普通text。两主题规则一致，不增加感叹号。缺少队列值时状态为`—`，不默认READY；任何实际失败以STALE覆盖状态。

Total必须取状态层同采样计算的字段；不能把保留的RUNNING与更新后的WAITING重新相加。未配置并发/总请求上限时不显示分母；不推断TP、并发量等参数。样本时间、错误原因、故障持续时间和最后成功时间不进入服务窗口。

## 历史绘图

只使用选中模型的主吞吐字段及其自身单位，保留`[now-60,now]`的点。横轴从最早保留点到now，显示实际相对范围；只有2秒历史时标`-2s`到`0s`，不冒充60秒。单点零跨度只标0s。未来及过期点不参与缩放或绘图。没有任何点时图区显示`—`。

正值用竖柱，合法零值在基线画`·`，`HistoryPoint.metrics=None`或主要字段None为留白缺口。按采样时间分箱，保留实际间隔；同箱可比有效值取最大值，若含失败/未知点则整箱留白以优先保留缺口。不插值，不把旧值补成新柱，不把缺口绘成0。显示聚合只影响柱状图，不修改最新吞吐或原始历史。

所有文字按终端单元宽度裁切，控制字符变为空白，不能跨内部分区、外边框或服务区域。服务类型、错误、恢复和空字段变化均不改变外部Region或槽位。

## 验证覆盖

| 契约 | 黑盒入口覆盖 |
| --- | --- |
| AC-401/408 | 模型身份/同名独立、RUNNING/WAITING/Total、未知Total不重算、未知上限不造分母、路由 |
| AC-404/405/409/410/411 | 空值/零值、Chat指标、pooling seq/s与两类延迟、类型不适用槽、非KV显存替代 |
| AC-406 | 主历史类型/单位、短窗口轴、过期/未来点、零/缺口区分、切换后保留历史与不可变快照 |
| AC-407 | STALE覆盖QUEUED、旧等待无amber、无诊断信息、状态恢复/类型槽位稳定 |
| 共同展示约束 | 初始unknown不READY、两主题amber规则、Unicode裁切、配置顺序/滚动、只读无外部I/O、上下半页接线 |

测试断言正确业务输出，不将NotImplementedError当成功，也不使用skip/xfail。真实终端颜色、字形和完整交互留给后续Ubuntu/WSL离线PTY与主题验收。当前测试不调用真实服务。

2026-11-02 在 WSL `Ubuntu-24.04`、当前 worktree 的 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer` 执行：

```bash
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_vllm_view.py \
  --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/pytest-view.xml
```

结果为53 failed，0 errors / 0 skipped：52项触达`vllm_cells`的NotImplementedError，1项触达现有`compose_frame`并因尚未接入类型指标和历史展示而断言失败。均为尚待实现的行为基线，无导入或环境问题。输出见 [evidence/pytest-view.txt](evidence/pytest-view.txt)、[evidence/pytest-view.xml](evidence/pytest-view.xml)。
