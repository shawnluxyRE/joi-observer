# REQ-004 服务窗口展示契约

- 修订：v1.3，2026-11-05；REQ-006按用户要求在右侧模型名、RUNNING/WAITING及DECODE HISTORY/RATE HISTORY标题上方各留1行；左栏、半页预算及最小120×16服务区保持，最小图区为1行，既有数字粗体/字段/颜色/历史算法不变。
- 代码：`src/joi_observer/tui/vllm.py`，公开入口 `vllm_cells`。
- 测试：`tests/test_vllm_view.py`；仅使用冻结快照和配置，无 HTTP、Docker 或 GPU。
- 上级设计：[vLLM 模块](../../../design/vllm.md)。

## 职责与输入

`vllm_cells(snapshot, config, region, view, *, now, history_scales=None)` 返回服务区内容 `tuple[TextCell,...]`。只读取 `(collector="vllm", object_id=config.id)`，不持有采集器、Monitor 或状态写接口，不计算计数差分、延迟窗口或跨采样 Total。选择、主题和调用次数不会影响采集、历史或快照 revision。

`now` 是与历史点同域的有限非负单调秒数，不能从页眉的 datetime 墙钟转换。`compose_frame` 新增可选关键字 `monotonic_now: float | None = None`，显式值用于离线时钟，缺省生产路径取 `time.monotonic()`，再传给本函数。既有单调时钟接线保留；本轮只修订布局及 `history_scales` 目标契约，R4 负责在保留半页区域计算的前提下替换旧执行体。

## 固定槽位

输入 `Region("service", row, column, width, height)` 包含外边框，至少 `120×16`；半页分界和最小终端高度不变。本函数只写内部，外框和 `column+27` 的栏间分隔由外层绘制。

左模型栏内容固定为 `[column+2, column+26)`，共24列，不随窗口宽度增加。右详情从 `L=column+30` 到 `R=column+width-2`（不含）；120列窗口对应88列图区。所有区间按终端字符宽度裁切，长名称不能跨栏、覆盖状态或单位。

| 区域 / 相对行 | 内容 |
| --- | --- |
| 左 `+1` | `MODELS / n`，muted；n为配置模型总数 |
| 左第i个可见项 `+2+4i` | `column+2`处为选中`›`，名称从`column+4`开始；选中名称primary，其他text。名称末端不超过`column+19`，状态槽固定从`column+20`起占6列，文字在槽内右对齐到`column+26` |
| 左名称下一行 | 大写类型和URL显式端口，如`CHAT / :8000`，muted；未写端口则只显示类型，不猜80/443 |
| 左名称后两行 | 左槽`[column+2,column+14)`的`3 running`左齐；空1格；右槽`[column+15,column+26)`的`7 waiting`右齐。数字独立着色，标签muted；running数字text，waiting仅新鲜正数amber，其余text |
| 左名称后三行 | 分隔留白；不增加独立行框或把三行合为一行 |
| 右 `+1`、`+5`、`+11` | `[L,R)`保持空行，分别位于模型名、RUNNING/WAITING统计及历史标题上方；左栏行位不变 |
| 右 `+2` | 模型名左，状态槽从`R-6`起固定6列，文字右对齐到R（READY/STALE/—不留下尾空格）；不再重复`[type]`，类型已在左栏 |
| 右 `+3` | `↳ `加配置的真实直接服务URL，secondary |
| 右 `+4`、`+8` | `[L,R)`横向分隔线，muted，保留右侧固定空行 |
| 右 `+6` | RUNNING / WAITING 两个等分统计组，text标签组内左对齐，至少留1空格后纯数值组内右对齐；真实数字bold=True，running为text、waiting按新鲜正值规则。占位普通，无大数字/ASCII艺术、分母或Total第三组 |
| 右 `+7` | 左从L起`Total {state.total} seq`；右从`S+2`起Chat的`Avg queue {seconds}s`或pooling的`Unit: seq`。两边caption均muted，限于各自统计组 |
| 右 `+9` | 四列muted指标标签，单位包含在标签中，见下表 |
| 右 `+10` | 与标签对应的text纯数值设bold=True；`—`、`N/A`及`…`不加粗，不重复单位、不越列 |
| 右 `+12` | Chat为`DECODE HISTORY / tok/s`，pooling为`RATE HISTORY / seq/s`；同一行右端muted尺度标签 |
| 右 `+13 ... height-3` | 竖柱图区；height16时1行，窗口增高后扩充此区 |
| 右 `height-2` | 固定`−60s / 0s`相对时间轴 |

两统计组中间分隔为 `S=L+(R-L)//2`；左组`[L,S-1)`，右组`[S+2,R)`，分隔线位于S列，仅覆盖相对`+6/+7`两行，角色muted；数值不得跨过各自右缘。120列时L=30、S=74、右组起76、R=118。

四指标列可用宽为`R-L-3`；前三列宽`q=(R-L-3)//4`，每列之间一空格，最后一列接收余数。列起点为`L+i*(q+1)`；120列对应30、52、74、96。标题和数值各自只占固定一行。

粗体由追加在TextCell末尾的`bold: bool=False`表示，原row/column/text/role构造及原五个role保持兼容；新增track仅供硬件轨道使用，不改变本服务角色。仅上表右`+6`、`+10`六个数值槽中的真实数字加粗，包括0、科学记数和STALE保留值；非适用、未知或有界省略不设置bold。三种模型类型共用规则，pooling的KV N/A保持普通。左栏数字、标签/单位、caption、标题/路由/状态、历史柱/尺度及其他面板均不新增粗体。角色、单位、数字格式与槽宽不变，终端以原颜色属性叠加A_BOLD，不通过更换role模拟字重；低色终端可能同时亮化，实际外观由终端决定。

新增留白只占右详情的三行预算，服务外矩形、轴行、左栏容量与条目位置保持。图区从旧`+10`下移到`+13`，可用高度为`height-15`，最低height=16时仍有1行柱图；不以增加终端最低高度或侵占上半区来补回这3行。第三处空行位于DECODE HISTORY/RATE HISTORY标题上方，四指标标签仍直接跟随其上方分隔线。

| 类型 | 第一列 | 第二列 | 第三列 | 第四列 |
| --- | --- | --- | --- | --- |
| Chat | `DECODE / tok/s` | `PREFILL / tok/s` | `TTFT / s` | `KV CACHE / %` |
| Embedding / Reranker | `RATE / seq/s` | `Avg queue / s` | `Avg latency / s` | `KV CACHE / %`，值固定N/A |

左栏容量为`(height-2)//4`，按配置顺序保留含选中项的连续窗口；列表溢出不提高最小高度。未知选中id或None回退首模型。无配置只显示一次`No models configured`，不绘制伪造指标或历史。每个模型首行保留状态槽是终端适配：不能为了窄栏隐藏未选中模型的STALE；名称可裁短，右侧详情保留更多名称空间。方向键和WebUI禁用由REQ-005负责，本函数只消费ViewSelection。

## 指标和状态

字段名固定为 `running`、`waiting`、`total`、`decode_rate`、`prefill_rate`、`rate`、`ttft_seconds`、`queue_seconds`、`latency_seconds`、`kv_cache_percent`。Chat三项负载为seq、吞吐为tok/s；pooling RATE为seq/s。显示标签与字段名分离，不能输出原始字段名或任意附加 Metric。

None为`—`，有效0正常显示0；不适用为N/A。仅模型已采样、非stale、RUNNING/WAITING均有效时显示READY/QUEUED。等待>0显示QUEUED，否则READY。只有QUEUED标签和新鲜正等待值采用amber；WAITING标签、0、STALE期间保留的旧等待值都为普通text。两主题规则一致，不增加感叹号。缺少队列值时状态为`—`，不默认READY；任何实际失败以STALE覆盖状态。

数值超宽时先改用最多3有效数字的科学记数，保留完整指数；不得直接截断十进制前缀而显示成貌似更小的值。左栏数值加标签仍放不下时，可将`running/waiting`缩成`run/wait`；仍不足则数值用明确`…`，标签和邻槽不被覆盖。正常、0与未知值保持原文案，无值为`—`而不是0；未知queue caption为`Avg queue —`，不追加虚假的秒数或单位后缀。该规则适用于最新统计/指标与caption的有界数值，不能修改原始metrics或改变公共`format_metric`。

Total必须取状态层同采样计算的字段；不能把保留的RUNNING与更新后的WAITING重新相加。未配置并发/总请求上限时不显示分母；不推断TP、并发量等参数。样本时间、错误原因、故障持续时间和最后成功时间不进入服务窗口。

## 历史绘图

REQ-006 已按用户最终决定保留原柱状图，并修订历史显示为固定最近60秒横轴、稳定时间桶和纵轴迟降。当前完整契约统一维护在[vLLM设计 §10.1](../../../design/vllm.md#101-稳定柱状历史与显示尺度)，不在本文件维护第二套公式。

横轴固定−60s/0s；短历史靠右、无样本区留白，替代原“最早点到now铺满横轴”的规则。同桶最大值与缺口优先、有效0基线点、未来/过期过滤仍保留；只改变显示，不修改吞吐、延迟或HistoryPoint。当前桶立即接收最新点，旧点在桶推进时统一左移；标题现有行显示尺度上限，不增加图区高度。

REQ-006已同步新参数、尺度骨架与黑盒；旧测试结果是REQ-004当时契约的历史证据，不能证明新的时间轴/分箱/迟降行为。新执行接线留R4；固定服务区沿用既有高度，模型类型槽位按本文的新HTML映射执行。

所有文字按终端单元宽度裁切，控制字符变为空白，不能跨内部分区、外边框或服务区域。服务类型、错误、恢复和空字段变化均不改变外部Region或槽位。

## 验证覆盖

| 契约 | 黑盒入口覆盖 |
| --- | --- |
| AC-401/408 | 模型身份/同名独立、RUNNING/WAITING/Total、未知Total不重算、未知上限不造分母、路由 |
| AC-404/405/409/410/411 | 空值/零值、Chat指标、pooling seq/s与两类延迟、类型不适用槽、非KV显存替代 |
| AC-406 | 主历史类型/单位、固定60秒轴及短历史留白（新期待已同步，执行体待实现）、过期/未来点、零/缺口区分、切换后保留历史与不可变快照 |
| AC-407 | STALE覆盖QUEUED、旧等待无amber、无诊断信息、状态恢复/类型槽位稳定 |
| 共同展示约束 | 初始unknown不READY、两主题amber规则、Unicode裁切、配置顺序/滚动、只读无外部I/O、上下半页接线 |

测试断言正确业务输出，不将NotImplementedError当成功，也不使用xfail。`test_vllm_pty.py`和`test_navigation_pty.py`通过本地Ubuntu/WSL真实PTY记录字形、颜色与交互；完成q退出和模式恢复后才进行业务断言。PTY仅在非POSIX环境按平台条件跳过，不以业务未实现为跳过理由。当前测试不调用真实服务。

以下2026-11-02记录是旧REQ-004阶段证据，不代表本轮HTML布局/固定88列图区已实现；新基线汇入REQ-006交接。

2026-11-02 在 WSL `Ubuntu-24.04`、当前 worktree 的 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer` 执行：

```bash
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_vllm_view.py \
  --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/pytest-view.xml
```

结果为53 failed，0 errors / 0 skipped：52项触达`vllm_cells`的NotImplementedError，1项触达现有`compose_frame`并因尚未接入类型指标和历史展示而断言失败。均为尚待实现的行为基线，无导入或环境问题。输出见 [evidence/pytest-view.txt](evidence/pytest-view.txt)、[evidence/pytest-view.xml](evidence/pytest-view.xml)。
