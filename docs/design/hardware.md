# 本机硬件模块设计

- 关联需求：dev-0 / REQ-002、REQ-006，AC-201～AC-207；共享 AC-101～AC-103、AC-108、AC-110、AC-112、AC-606～AC-608及HTML布局修订。
- 关联需求补充：dev-1 / REQ-001，AC-101～106/111，复用硬件采集与呈现规则。
- 修订：v2.1，2026-11-16；在图前集中说明硬件类、对象职责与时序别名。
- 当前阶段：硬件采集、公共结果、行列、紧凑容量、右对齐和精度均为既有基线；dev-1 的服务/客户端接线仍待 R4。旧交接路径为 `docs/dev-workflow/dev-0/REQ-006/handoff-r4.md`、`handoff-r5.md`，当前工作区未包含，不作为本轮验证证据。
- 整体设计：[组件边界与依赖](architecture.md)。
- 代码：`collectors/hardware.py`、`collectors/base.py`、`monitor.py`、`tui/widgets.py`；生产采集装配迁入 `runtime.py`，客户端呈现继续使用 `tui/layout.py`。
- 关联设计：[Monitor/State](monitor-state.md)、[配置](configuration.md)、[应用外壳](application-shell.md)、[错误日志](error-logging.md)。

## 职责和范围

仅由 Ubuntu 宿主机采集服务使用，只读采集 NVIDIA GPU、整机 CPU/RAM 和配置前三个挂载点。采集结果由 Monitor 提交权威状态，再经只读 IPC 传给 TUI/Web；不增加数据库、采样日志、网络流量指标、磁盘 IO 指标、逐进程指标或服务控制。

REQ-002 负责硬件数据与按当前 `ViewSelection` 计算的 GPU 关联高亮。方向键修改选择由 [REQ-005 导航控制器](navigation.md) 完成，完整主题颜色映射由 REQ-006 完成；本模块提供对应语义颜色角色。Docker 与 vLLM 采集已分别随 REQ-003/004 合并。

保留已合并的配置、状态、调度、日志和半页布局。当前公共 CollectionResult 仅含 key/failure，硬件各 collect 返回携带 metrics 的 MetricCollectionResult；导航不改变结果类型或原业务算法。

## 类与对象简介

| 图中名称 | 简介 |
| --- | --- |
| `HardwareIO` / `IO` | `IO` 是 `HardwareIO` 协议端口的对象别名，负责有界读取本机文件、挂载统计和硬件命令结果。 |
| `LocalHardwareIO` | `LocalHardwareIO` 是硬件读端口的本机实现，负责隔离和回收文件、挂载统计及命令操作使用的外部资源。 |
| `Collector` | `Collector` 是单对象采集协议，约定采集结果与资源关闭接口。 |
| `CpuCollector` | `CpuCollector` 读取整机 CPU 计数并输出采样间隔内的利用率指标。 |
| `MemoryCollector` | `MemoryCollector` 读取整机内存信息并输出 RAM 容量与使用率指标。 |
| `StorageCollector` | `StorageCollector` 按配置挂载点身份输出容量、使用率或采集失败结果。 |
| `GpuCollector` / `GPU` | `GPU` 是 `GpuCollector` 的对象别名，负责按完整 UUID 采集并核对单张 GPU 的指标。 |
| `GpuDiscovery` / `Discovery` | `Discovery` 是 `GpuDiscovery` 的对象别名，负责发现本机 GPU 身份并为 Monitor 声明设备及构造相应采集器。 |
| `Monitor` | `Monitor` 独立调度发现和采集任务，将结果统一提交状态并管理来源资源的关闭。 |
| `MonitorState` / `State` | `State` 是 `MonitorState` 的对象别名，负责保存权威最新指标、采集状态和有界历史并提供不可变快照。 |

## 简化类图

```mermaid
classDiagram
    class HardwareIO {
        <<interface>>
        +read_text(path) str
        +statvfs(path) FileSystemStat
        +run(argv) CommandOutput
        +close()
    }
    class LocalHardwareIO
    class Collector {
        <<interface>>
        +collect() CollectionResult
        +close()
    }
    class CpuCollector
    class MemoryCollector
    class StorageCollector
    class GpuCollector
    class GpuDiscovery {
        +discover() DiscoveryResult
        +create_collector(spec) Collector
    }
    LocalHardwareIO ..|> HardwareIO
    CpuCollector ..|> Collector
    MemoryCollector ..|> Collector
    StorageCollector ..|> Collector
    GpuCollector ..|> Collector
    CpuCollector --> HardwareIO
    MemoryCollector --> HardwareIO
    StorageCollector --> HardwareIO
    GpuCollector --> HardwareIO
    GpuDiscovery --> HardwareIO
    GpuDiscovery ..> GpuCollector
```

## 关键交互时序图

```mermaid
sequenceDiagram
    participant Monitor
    participant Discovery as GpuDiscovery
    participant IO as HardwareIO
    participant State as MonitorState
    participant GPU as GpuCollector
    Monitor->>Discovery: discover()
    Discovery->>IO: run(index, uuid 查询)
    IO-->>Discovery: 原始枚举结果
    Discovery-->>Monitor: inventory 与有序 specs
    opt 完整声明校验通过且存在新 UUID
        Monitor->>Discovery: create_collector(spec)
        Discovery-->>Monitor: 无 I/O 构造的子采集器
        Monitor->>State: register(spec)
    end
    Monitor->>State: accept(inventory, sampled_at)
    opt 本轮创建了新 GPU
        Monitor->>GPU: collect()
        GPU->>IO: run(按 UUID 查询)
        IO-->>GPU: 原始指标
        GPU-->>Monitor: MetricCollectionResult
        Monitor->>State: accept(result, sampled_at)
    end
    Note over Monitor,State: 发现失败只更新 inventory；已知 GPU 不删除，仍按各自周期独立采集
```

发现器报告不可变声明，只有 Monitor 注册对象、创建新来源并提交状态。发现器和每个来源独占一个 IO 端口；关闭一张卡不会关闭其他卡。TUI 只有不可变快照，不持有上述接口。

## 身份、字段与单位

所有模板值初始为 `None`；成功的 `MetricCollectionResult(key, metrics)` 覆盖模板，已知不支持字段显式 `None`。局部失败以 `MetricCollectionResult(key, valid_metrics, failure=...)` 保留成功字段；整体失败使用 `MetricCollectionResult(key, failure=...)`。failure 只能按关键字传入。Collector 协议仍返回公共基类，Monitor 的超时/未知异常可用无载荷 `CollectionResult(key, failure=...)`；成功公共基类不合法。普通硬件 ObjectSpec 只匹配 MetricCollectionResult，不接受 VllmCollectionResult。具体字段以代码目录为准，不让布局根据字段顺序猜含义。

| 对象 key | 字段与存储单位 | 身份与展示规则 |
| --- | --- | --- |
| `host/cpu` | `cpu_percent`，% | 整机，独立采样与失败状态 |
| `host/ram` | `ram_used_bytes`、`ram_total_bytes`，B；`ram_percent`，% | 与 CPU 隔离，Host 标题汇总失败状态 |
| `storage/mount-0`～`mount-2` | `used_bytes`、`total_bytes`，B；`used_percent`，% | 序号按有效配置，界面显示配置原路径；长路径不会突破 ObjectKey 的128字符上限 |
| `gpu_inventory/local` | `device_count`，整数 | 面板级发现状态，不是设备，不计入 GPU 槽与最小高度 |
| `gpu/<完整 UUID>` | `index`、`name`；`utilization_percent`，%；`memory_used_bytes`、`memory_total_bytes`，B；`temperature_c`，°C；`power_w`，W | UUID为会话身份，可靠 index 为显示编号，name 来自采集 |

新 UUID 按发现顺序追加，已有 UUID 不因枚举顺序、模型选择、失败或热移除而重排/删除。新卡可能提高基础最小高度；故障本身不能改变布局。设备数不硬编码为5。使用通用 `Metric`/`ObjectSpec`/`MetricCollectionResult` 和 `MonitorState`，不另建硬件专用可变状态。GPU inventory 的展示结果也由 MetricCollectionResult 承载；DiscoveryResult 的发现声明结构不因本次分型改变。

## 数值口径

### CPU 与 RAM

CPU 从 `/proc/stat` 的整机 `cpu` 行取 `user nice system idle iowait irq softirq steal` 八个累计 tick；不能累加逐核心行，不能把 `guest/guest_nice` 重复计入 total。设 `total` 为八项和，`busy=total-idle-iowait`，两次连续有效样本的 `cpu_percent=100×Δbusy/Δtotal`。无需除以核心数或按计划采样秒数换算。

首次、总 tick 无增长、任一参与计数回退及失败后首个成功样本都没有可比较区间，返回成功的 `None`，不伪造0、不记错误。回退/无增量的当前样本作为新基线；失败清空基线。Monitor超时会取消当前读取，CPU须捕获CancelledError清基线后原样重抛，不能跨超时计算。可比较区间忙 tick 无增长时真值是0。计数回退的处理也覆盖 Linux 文档说明的 iowait 可能下降，不把它误记为驱动故障。必要字段缺失、重复 aggregate 行或非法数字为解析失败。

RAM 使用 `/proc/meminfo` 的 `MemTotal`、`MemAvailable`（kB×1024）。`used=total-available`，`percent=100×used/total`；不采用 `MemFree`，不与显存/KV Cache 混合。`total>0` 且 `0<=available<=total`；缺失/重复必要键、非法单位或数值均失败，不用其他字段估算。CPU 与 RAM 分来源，任何一方失败不阻止另一方刷新。

### 挂载点容量

只创建有效配置的前三项，失败不能用第四项补位；`build_hardware_sources` 对手工构造 AppConfig 也防御性使用 `[:3]`。0项不创建 Storage 采集器，不记错误。

每次读 `/proc/self/mountinfo`，解析 ` - ` 分隔符前第5字段并解码 Linux 路径转义。配置和挂载路径只进行 POSIX 词法规范化，保留配置原文用于显示；不跟随符号链接、不使用父目录/最长前缀匹配。目标必须本身是精确挂载点，普通 `/data` 目录不能因存在或能调用 statvfs 就当成已挂载。

只有精确匹配后才调用 statvfs，再读 mountinfo 检查对应 mount ID、major:minor、root、挂载路径未变化。重复同路径挂载记录视作无法可靠确定目标，返回 `source.unavailable`，不能依赖文本顺序猜顶层挂载；bind mount 的唯一精确挂载记录正常支持。可观察到的卸载/替换导致本轮容量丢弃。前后检查无法证明极短的卸载又恢复（ABA）未发生，R4 可用打开目录的 mount ID 加强绑定；当前不承诺原子文件系统快照。

采用 `f_frsize×f_blocks` 为总容量，`f_frsize×(f_blocks-f_bfree)` 为已用；使用率为已用/总量。保留块包含在总量中，不能把 `f_bavail` 的普通用户可用口径混入百分比分母。`f_frsize>0`、`f_blocks>0`、`0<=f_bfree<=f_blocks`；不支持以0总量冒充有效容量。

### NVIDIA 数据

使用已安装的 `nvidia-smi` 只读查询，无 Python GPU 依赖。固定参数如下；以 argv 调用，不使用 shell：

```text
nvidia-smi --query-gpu=index,uuid --format=csv,noheader,nounits
nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits --id=<完整 UUID>
```

发现查询只枚举身份，逐卡查询通过 UUID 定位。查询字段或可用性随本地驱动存在差异时按下述规则处理，不回退为模拟数据，不按型号猜固定容量。

- GPU 利用率直接使用驱动 `%`，含义是采样周期内有 kernel 执行的时间比例，不能用显存比例代替。`memory.used/total` 按 MiB×1024² 转字节，温度为°C，功率为W。
- `power.draw` 是驱动最近测得的整板功率；较新设备可能是1秒平均，UI只标W，不承诺瞬时值。
- 逐卡查询必须一行、列数正确、UUID精确匹配。身份/结构错误整卡失败；单字段解析失败省略该字段，提交其他有效字段，State保留坏字段旧值并标整卡STALE。显存used/total作为关联容量组：任一容量实际解析失败时两者均省略，不能混合新旧样本产生8/4GiB等无效组合；已知N/A仍可独立返回None。
- `N/A`、`[N/A]`、`[Not Supported]` 是明确不可用标记，字段返回None且不记错误。空字段、`[Unknown Error]`、NaN/Infinity、越界值是解析失败。不能把任何括号文本都当“不支持”。
- index为非负整数；利用率0～100；温度和功率为非负有限数；显存总量>0且0≤已用≤总量。used>total时同时省略两项容量，保留其他有效字段。
- 成功的空CSV代表无卡。针对 CLI 的无设备响应，精确匹配独立的 `No devices were found` 且退出码0或6时也归一成功无卡；不是按所有非零退出码或包含关键字来猜无卡。该特殊输出目前仅有离线契约样本，目标驱动待用户部署后核对。
- 非零返回且不符合无设备特例为整体失败；缺少命令/驱动不可用为 `source.unavailable`。stderr和原始错误文本均不进入State/日志。

## GPU 发现、调度与资源生命周期

`Monitor.register_discovery(discovery)` 在首次 poll/run 前调用，无 IO，注册 inventory 模板；重复key拒绝，调度开始或停止后再注册拒绝。发现器按配置周期独立运行，遵守现有超时、不重入、忙时跳槽规则。

`DiscoveryResult.inventory` 走既有 accept/日志/recovered/通知流程；成功的 specs 是本轮完整枚举声明，失败必须为空。Monitor 先校验整个结果和工厂输出，再注册新卡：重复声明、模板改变、跨发现器/静态来源冲突或错误工厂输出使本轮 inventory 归一 `collector.unexpected`，不得半轮污染状态；已创建但未采用的资源关闭。

只为新UUID调用一次同步、无IO的 `create_collector`。新卡注册后立即发起首采，之后保留自己的周期原点；重复发现不重置历史、状态、采样相位或重新构造来源。已知卡不在最新清单中也不删除，独立UUID查询会标记故障并允许自动恢复。inventory失败只显示面板状态，不批量覆盖每张卡的结果。

服务 stop 须沿用既有 Monitor 的动态资源登记与清理，取消发现任务及所有静态/动态来源，关闭每个已创建资源；迟到发现不得创建来源、注册或提交。整体退出预算仍为 1 秒，不串行叠加每个对象的预算。TUI 退出只关闭本客户端，不调用这条采集清理路径。

## 失败与日志

| 情况 | kind / code | 状态行为 |
| --- | --- | --- |
| IO或调度超时 | timeout / collection.timeout | 当前对象STALE，CPU基线失效 |
| PermissionError | permission / access.denied | 仅受影响对象失败 |
| 未挂载/路径不存在/明确设备不存在 | not_found / object.not_found | 不回退父文件系统、不删除旧卡 |
| 结构、字段、数值非法 | parse / response.invalid | 按整对象/字段失败粒度保值 |
| 缺少命令、驱动不可用、其他受控IO故障、挂载发生变化或歧义 | unavailable / source.unavailable | 保值，后续自动重试 |
| 工厂/发现协议违反或未预期异常 | unexpected / collector.unexpected | 由Monitor隔离，不能泄漏异常 |

复用 REQ-001 已登记错误码和固定日志原因模板，不新建日志体系。首次失败立即ERROR，相同对象/错误60秒限频，恢复不记日志。CPU无基线、GPU已知不支持、成功无卡、未配置挂载点均成功无错误。界面仅固定槽STALE，无时间/原因/错误码；历史失败留缺口。

## 本地 IO 与接线

`HardwareIO` 只返回原始文本、statvfs计数、命令输出；测试替换此边界，不替换被测数值计算。`LocalHardwareIO` 将潜在阻塞的文件/statvfs调用放入可终止本地worker，nvidia-smi使用异步子进程。输出每路≤1 MiB，固定操作白名单、无shell，timeout取配置；取消和close须250ms内终止/回收自己创建的子进程。不能以无限阻塞线程宣称满足取消，也不执行任何网络请求。

不新增运行依赖或更改uv锁文件；生产采样下限现为 1 秒。R4 若发现本地 worker 成本较高，可在维持隔离/取消契约的前提下使用有界常驻 worker，仍不能让慢挂载阻塞其他来源。上述 IO 与资源回收要求沿用原契约，离线短周期测试继续保留。

`build_hardware_sources(config)` 无 I/O 地组装 CPU、RAM、前三挂载及发现器。R4 将旧 `ApplicationRuntime._components` 的采集装配迁入 `CollectorRuntime`，把静态 spec 加入同一 State、静态来源交给 Monitor 后注册发现器；复用动态资源登记与清理。导入、`--help`、缺配置、构造阶段不能执行硬件查询。硬件、Docker 和 vLLM 共用服务内唯一 State/Monitor；旧 RuntimeComponents 测试迁移到新运行期时保留业务断言。

## 硬件显示与模型关联

`widgets.hardware_cells` 已由compose_frame调用，只生成GPU/Host/Storage区域内的文字和状态槽，不重复绘制边框。区域坐标、边框、最小尺寸与面板外壳高度由layout.py负责，完整分配见[应用外壳容量契约](application-shell.md#可验证的字符容量)。下文只定义区域内部的零基字符坐标、字段精度和关联匹配；颜色角色统一见[主题设计](theme.md#color-roles)。

每个区域内容边界记为`L=column+2`、`R=column+width-2`，R为排他边界。右对齐指可见文字末端恰到指定边界，不依赖先前内容长度。Storage 状态只占标题行。

| 区域 | 内容安排 |
| --- | --- |
| GPU 组头与分隔线 | 组头左对齐 GPU 编号范围，右对齐配置标记。从第二个组头起，上方独占一行，使用 `─` 横贯面板内容区 `[L,R)` |
| GPU 设备行 | `[编号] 型号` 从 L 起。显存槽 `[L+12,R−12)`、温度槽 `[R−10,R)` 均右对齐 |
| GPU 利用率行 | 条从 L 起，宽 `floor((width−4)/2)`，空一格后显示百分比。功率在 `[R−10,R)` 右对齐。带组头的布局将设备的 `STALE` 放在百分比和功率之间 |
| Host row+1 | CPU标签靠L，百分比固定1位小数并在`[L+4,R)`右对齐，如30.0% |
| Host row+2 | CPU条从L起，宽`floor((width−4)/2)`，不重复显示比例 |
| Host row+3 | RAM标签靠L，GiB/TiB整数已用/总量组在`[L+4,R)`右对齐；不添加百分比文字 |
| Host row+4 | RAM条与CPU条等宽、同左端；保持既有布局，不添加百分比文字 |
| Storage标题row | 仅当前3个配置挂载点任一对象stale时，在`[R−5,R)`显示一次STALE；其余情况留空 |
| Storage row+2～row+4 | 路径靠L；紧凑容量与固定1位小数的百分比组在`[L+2,R)`右对齐，内容行不预留状态槽 |

每个 GPU 组头下固定留一整行空白，再显示该组第一张卡。每张卡的设备行和利用率行相邻。高度紧张时，先收起同组设备之间的可选留白。若仍需更多行以完整呈现所有组，则依照[应用外壳容量契约](application-shell.md#可验证的字符容量)提高终端最低高度。全部卡都没有可显示的组头时，每卡用三行，前两行放设备和利用率，第三行右端 `[R−5,R)` 留给设备的 `STALE`。两种布局均以方括号标明设备编号，未知编号显示 `[—]`。编号最多占 10 格，后接一格及设备型号。

名字只使用编号之后、显存之前的剩余空间，可以为空。有名字时和相邻内容至少各留一空格，显存与温度之间保留两格。超长Unicode名字或编号在自身槽内裁切，不能覆盖数值组。GPU条及百分比不进入最右温度/功率组。Storage路径只裁数值组左侧剩余空间，至少与数值隔一格；健康、失败与恢复均使用完整内容右缘。120列时GPU的R=69，显存槽14～56、温度/功率槽59～68；Host/Storage的R=118，Host值槽78～117、Storage值槽76～117、Storage标题状态位113～117。

常规数值保持现有精度和文本，温度如`60°C`、功率如`100 W`。超出自身值槽时，先用最多3位有效数字的科学记数压缩，保留指数和单位；例如极大容量仍能辨别已用/总量及GiB/TiB，极大温度/功率仍能辨别°C/W。原始指标与`capacity_text`输出不变，任意精度整数不能先转float溢出。科学记数仍放不下时只在该槽显示明确的`…`，不能截掉指数/单位伪装成较小完整值，也不能用`—`、`0`或`N/A`表示槽位不足。先保留身份/标签/状态，再安排数值，不能向左挤占它们。

CPU和Storage已有百分比文本固定保留1位小数，如`30.0%`、`0.0%`、`100.0%`，未知仍为`—`；这只改变面板文本，不改变CPU累计tick采样或百分比口径。RAM保留容量行与下行条，不添加百分比文字。条的字形、取整与公开`percentage_bar`兼容语义，以及配色和终端降级统一见[硬件分段条、轨道与配色能力](theme.md#hardware-bars)。

容量仍采用GiB/TiB二进制单位，已用和总量使用同一单位（总量≥1TiB切TiB，按原始容量选单位）。GPU及Storage的TiB保留1位小数；RAM的GiB/TiB以及Storage的GiB数值从原始字节直接按ROUND_HALF_UP舍入为整数，不先舍入到1位小数后再次舍入。例如所用单位下1.49显示1、1.5显示2，真实0显示0。不以显示后的整数重新计算RAM或Storage使用率。

GPU、RAM、Storage的容量组合共用一个末尾单位。GPU例如`4.0 / 16.0 GiB`，单边未知为`— / 16.0 GiB`或`4.0 / — GiB`，真实0为`0.0`。RAM与Storage的GiB对应显示`4 / 16 GiB`、`— / 16 GiB`或`4 / — GiB`，真实0为`0`；RAM的TiB同样为整数，例如`1 / 2 TiB`，Storage的TiB仍为`1.0 / 2.0 TiB`。所有组合两边未知均为`— / —`。`capacity_text`公开返回仍是例如`('4.0 GiB', '16.0 GiB')`，其1位小数语义、既有formatter边界和二进制换算不变；RAM/Storage整数只属于对应面板的组合呈现。

Storage完整数值组为`1 / 4 GiB · 25.0%`，TiB例如`1.0 / 4.0 TiB · 25.0%`，未知为`— / — · —`，整体贴内容右缘。各字段及未知片段的颜色语义见[颜色值与显示角色](theme.md#color-roles)。

inventory首次未知显示—，成功0卡且从未有槽显示 `No NVIDIA GPUs`，失败在GPU面板标题状态槽STALE，不能显示成“检测到0卡”。有旧槽时保留所有旧槽。Host的CPU/RAM任一失败在标题预留位STALE；Storage前三个配置挂载点任一失败时仅在Storage标题右上角显示一次STALE，全部恢复后清除。缺少对象或尚未采样本身不视为stale；无配置和第4个起的挂载点不参与标题状态。各挂载仍独立保留已有值、更新和记录错误，标题不新增原因或数量。长路径/名称按终端字符宽度裁切，优先保住指标与状态，不增加行。

`linked_gpu_ids` 只读配置中当前模型的显式gpu_ids；缺省选择第一模型，未知选择或空映射清空高亮。完整UUID精确匹配可用于旧卡；索引只匹配本次已采样且非STALE的唯一index，规范十进制字符串（`4`，非`04`）。出现重复的当前index时不以索引猜映射。UUID前缀、名称、显存和负载均不作为依据。切换只改变编号/填充/百分比的role，不改变GPU顺序、状态、历史或采样次数。

组头读取全部模型的 `gpu_ids`，按设备发现顺序展示。左侧列出实际 GPU 索引，连续编号可以合写为 `GPU 0–3`，组头省略模型名称。右侧的 `TP N` 表示单个模型独占这 N 张卡，且该模型的配置标识都已解析。多个模型共用卡时显示 `SHARED`。它们是配置标记，实际张量并行度以服务启动参数为准。归属或索引不足以确定时，省略相应标记。

例如 Flash-Next 使用 0–3 号卡，Embedding 和 Reranker 共用 4 号卡。第一组标题为左侧 `GPU 0–3`、右侧 `TP 4`。GPU 3 的利用率行下方是横线，横线的下一行同时显示左侧 `GPU 4` 和右侧 `SHARED`，再下一行显示 4 号卡的型号。若某模型使用 GPU 0 和 2，分界不会从该模型的两张卡之间穿过。切换所选模型只改变关联卡的高亮。

REQ-005 默认控制器仅输出合法模型 id（空配置为 None）；同一帧模型详情与硬件关联使用同一选择值。模型服务失败不撤销显式映射，GPU 自身过期索引仍按上面的安全匹配规则处理。不修改本模块的未知 id 兼容行为，不新增 GPU 焦点或滚动。导航贯穿视图的黑盒覆盖见 `tests/test_navigation.py`。

Storage采用序号key。缺少序号对象时兼容读取旧路径key，序号优先。旧host/local仍汇总通用字段和STALE。缺少index字段的旧GPU对象保留通用指标，旧数字槽以方括号显示编号。具有index模板的设备使用硬件专用布局，编号未知时显示 `[—]`。这些兼容路径仅用于展示已有快照。

## 验证依据与边界

| 入口 | 黑盒测试 | 覆盖 |
| --- | --- | --- |
| CPU/RAM/Storage/GPU collect，GPU discover，工厂 | `tests/test_hardware.py` | AC-201～204/207；原始离线文本、IO错误、计数、挂载真实性、字段/单位/恢复 |
| Monitor.register_discovery/poll/stop | `tests/test_hardware_monitor.py` | 动态来源、发现原子性、独立周期/故障、真实State及ErrorLog、关闭 |
| percentage_bar/capacity_text/linked_gpu_ids/hardware_cells/compose_frame | `tests/test_hardware_view.py` | AC-201～207；值与颜色、固定布局、无映射清空、长路径、只读展示 |
| 新行列与右对齐 | `tests/test_html_hardware_layout.py`、`tests/test_hardware_view_edges.py` | 3:2区域、GPU三行分组、Host四内容行、共享容量、右边缘/状态槽/Unicode无覆盖；只读快照与纯控件真实运行 |
| 旧 ApplicationRuntime.prepare_log/run/close 的迁移覆盖 | `tests/test_hardware_runtime.py`、`tests/test_snapshot_pipeline.py` | 保留原始 IO 到 Frame、五卡最小尺寸和前三挂载断言；客户端 q 后采集继续，显式服务 stop 后回收采集资源 |
| 实际curses字符位置 | `tests/test_hardware_pty.py` | 本地PTY真实屏幕的区域与显存/温度/功率列；先完成退出和资源回收，再报告新布局断言差异 |
| 既有Monitor/State/日志/CLI/配置/终端 | 原有全部tests | REQ-001回归、超时/键位响应、错误限频、Storage3行与半页布局 |

测试断言正确业务行为，不以 NotImplementedError 为成功、不使用 xfail 掩盖未实现。历史 R2 路径为 `docs/dev-workflow/dev-0/REQ-002/handoff-r2.md`、`docs/dev-workflow/dev-0/REQ-006/handoff-r2.md`；当前工作区未包含，不作为本轮验证证据。布局断言失败仍按业务问题处理；导入/环境错误独立报告，不包装为采集或启动超时。

以下两段保留REQ-002原设计时点的离线材料与当时待验事项，不表示本轮重新执行硬件命令或需要重写已合并采集器。

REQ-002当时使用本机 `nvidia-smi --help` / `--help-query-gpu`（v596.47）核对字段及index/UUID/功率语义，并读取本地Ubuntu手册 `proc_stat(5)`、`proc_meminfo(5)`、`proc_pid_mountinfo(5)`。原文保存到本需求evidence，属于已安装工具的离线材料，不代表目标服务器驱动615.71.09经过实测。部署文件仅作为已有目标环境背景，不从其GPU数量推定当前设备数。

REQ-002原阶段列有本地Linux适配/worker超时取消/无输出泄漏、Frame呈现和运行期接线验证，后续阶段结果以该需求R4/R5交接为准；最终目标GPU驱动输出、无卡返回码、权限、挂载状态没有现场验证。所有自动化保持离线，禁止连接服务器；未来部署验收须由用户安排。此限制不阻止本设计交接R3。

## 修订说明

v2.1 在图前合并介绍类图和时序图元素，补全对象别名对应关系；原图、接口与业务契约保持不变。

v2.0 按更新后的 R2 模板统一整体设计引用、简化类图和关键交互时序；原业务与测试契约继续保留。

v1.11将v1.9/v1.10的硬件条呈现修订归拢至[主题设计](theme.md#hardware-bars)，本页保留采集、数字和面板内部几何契约；删除重复说明，不改变实现。

v1.8仅按用户反馈调整Storage路径和空配置文字为text；保持数值组右缘、标题STALE、颜色分层和全部精度/数据契约。

v1.7按用户后续修订覆盖v1.6中RAM精度保持不变的约定：RAM的GiB/TiB整数、CPU/Storage固定1位百分比仅属于面板显示。RAM不添加百分比文字，公开`capacity_text`/`percentage_bar`、GPU与采样/计算口径均保持；Storage TiB仍1位小数。

v1.6由用户在REQ-006 R4的实际GUI复核中直接修订，取代旧逐挂载行STALE槽及Storage GiB一位小数的呈现约定。状态对象、日志、采集、公开`capacity_text`与GPU/RAM精度均不改变；实施与复验证据见REQ-006 R4交接。

v1.1 仅同步公共结果分型：硬件具体 collect 及 inventory 状态采用 MetricCollectionResult，公共 Collector/Monitor 接口仍依赖 CollectionResult，failure 仅关键字传参。上述 REQ-002 初次 R2 验证规划保留其历史语境，后续实现与验收记录见原 REQ-002 R4/R5 交接；本次迁移不改写历史交接、不改变硬件算法，也不提前实现 vLLM accumulator 或运行期接线。
