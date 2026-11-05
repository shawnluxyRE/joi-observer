# Architecture

- 拟采用 Python 的 src 布局；项目根目录与 Python 包目录分开，以下仅为目录规划：

```text
.
├── src/joi_observer/         # Python 包目录
│   ├── __main__.py           # 启动入口
│   ├── config.yaml           # 采样间隔、服务地址等配置
│   ├── monitor.py            # 调度采集、更新状态、通知刷新
│   ├── data/                 # 数据对象与内存状态，不存放数据文件
│   │   ├── models.py         # 硬件、模型、服务状态的数据对象
│   │   └── state.py          # MonitorState：最新快照、历史与采集状态
│   ├── collectors/
│   │   ├── base.py           # 统一采集器接口
│   │   ├── hardware.py       # GPU、CPU、内存、磁盘、网络
│   │   └── vllm.py           # vLLM 指标；后续按服务增加采集器
│   ├── tui/
│   │   ├── app.py            # 终端布局与键盘交互
│   │   ├── widgets.py        # 指标面板与历史图表
│   │   └── theme.py          # 颜色与样式
│   └── web/                  # 预留：未来只读 Web 看板
├── tests/                    # 采集解析、状态计算与界面测试
├── docs/design/              # UI 设计稿
├── README.md
└── AGENTS.md
```

- 数据流：`Collector → Monitor → MonitorState → TUI / Web`；Monitor 统一写入状态，展示层读取只读快照，不直接采集。
- `data/state.py` 中的 `MonitorState` 是独立内存对象，保存最新数据、上次采样值及时间、最近约 60 秒的有界历史和错误状态；不使用数据库，不持久化监控数据。
- 采集器独立于界面；未来 Web 看板共享同一状态对象，避免重复采集，且仅提供只读接口。

# Info For Skills

- project_root：D:\Documents\joi-observer
- work_id：dev-0
- work_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-0
- req_id：REQ-006
- req_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006
- design_dir：D:\Documents\joi-observer\docs\design
- requirements_path：D:\Documents\joi-observer\docs\dev-workflow\dev-0\requirements.md

# Design

- 设计稿：`docs/design/joi-observer.html`（精简 HTML 片段，作为布局、配色和交互参考；独立预览时按需导出完整 HTML）。
- Ubuntu Terminal TUI：深色、等宽、紧凑分区，全英文；以当前 Neon Grid 总览为准。
- 配色：背景 `#080E18`，正文 `#D4DDEB`，次要信息 `#8A9DB5`，独立未填充轨道track为深灰`#3E4A5B`；冰蓝 `#7DDFFF` 为主色，浅紫 `#C6A7FF` 为辅色；仅 `QUEUED` 和大于 0 的等待数量用琥珀 `#FFA45B`，`WAITING` 标签与 0 使用普通文字色，不加感叹号。
- 顶部：`Joi::Observer`（`Joi` 使用主题辅色，`::` 灰色，`Observer` 使用主题主色），第二行固定显示 `H3C R5300 G6 / Ubuntu发行版本`。启动时按`/etc/os-release`、`/usr/lib/os-release`顺序选首个读取成功文件，仅解析实际字段：优先非空PRETTY_NAME，否则NAME+VERSION_ID；名称/版本缺失或空值分别用Ubuntu/—，显式Linux保留，空文件/读取或编码失败用Ubuntu —。不混合候选、不依赖库默认字段/缓存，不取内核release、不探DMI；右侧保留时间。右上角仅以t键切换 Moonlight（冰蓝 / 浅紫）与 Hologram（`#7B9FFF` / `#E570D0`），两种主题共用琥珀强调规则。每次启动默认 Hologram，仅当前会话保留切换结果。
- 页面纵向分为上下两半：下半区的服务窗口、底部服务切换位及最下方键位提示合计固定占全页高度的一半；顶部品牌、主机信息及上半区硬件等使用剩余高度。奇数页高时下半区向下取整，多出的 1 行留给上半区。
- 上半区：左侧 GPU 列表，右侧依次为 Host Resources、Storage、Docker。GPU 分段条占可用宽度约一半，百分比在条末端，关联填充使用主题主色，未关联填充与显存保持原muted灰色；CPU / RAM 填充使用主题辅色，三种条的未填充段共用独立深灰track，RAM已用量灰色、总量白色。Storage 固定 3 行内容，标题和边框另计，仅采集和显示配置前 3 个挂载点，其余忽略不报错。Docker 配置数量不限、全部采集；面板填充右侧扣除 Host Resources、Storage 及间距后的剩余高度，按配置顺序只显示内容区可容纳的容器，剩余不显示、不作任何提示，不因容器数提高最小终端高度。窗口放大后可显示更多条目；不增加滚动、分页或更多标记，不侵占下半区，内容少时允许留白。
- 下半区：服务窗口与底部切换位、键位提示共同使用半页高度；紫色 `vLLM` 标题；左侧模型列表，选中项冰蓝；右侧运行、排队、吞吐、延迟、KV Cache 与柱状历史图。路由信息浅紫，文案用 `Total`、`Avg queue`。
- 非终端能力或既定半页预算所限时，TUI尽量贴近Neon Grid HTML的排版：GPU显存在型号行右侧、温度/功率最右对齐；CPU/RAM标签与数字同行、条在下一行，RAM保持原布局且不添加百分比文字；Storage数值整体贴内容右缘，仅前3个配置挂载点任一stale时在标题右上角显示一次STALE，内容行不留状态槽。RAM的GiB/TiB及Storage的GiB从原始字节直接ROUND_HALF_UP显示整数，GPU容量、Storage的TiB与公共capacity_text保留1位小数。CPU/Storage已有百分比固定显示1位（如30.0%/0.0%/100.0%），GPU利用率、公共percentage_bar、采样与百分比口径保持。下半模型栏较窄，RUNNING/WAITING为两组标签左/数值右统计块，Total/Avg queue归属各块下方，主要指标为四列标签上/数值下；保留真实单位、状态位和长名称裁切，不复制模拟上限。
- 模型名称复用既有配置`name`，左右列表/详情共用，可配置为`Flash-Next`、`Embedding`、`Reranker`；`served_model_name`独立指定真实服务匹配名称，省略时仍回退`name`，不新增仅左侧别名字段。
- GPU/CPU/RAM利用率条在显示层的填充和未填充轨道都用`▌`，每段仍占1字符格；仅轨道独立为track角色，双主题目标均为`#3E4A5B`，不能改变muted以实现变暗。原条宽、段数、填充色、数字位置及未关联GPU muted保持。公开`percentage_bar`仍返回`█`/`░`并沿用原ROUND_HALF_UP，不增加半格量化，不改vLLM竖向历史柱。Palette末尾track默认(62,74,91)兼容旧构造；精确模式七色槽16～22/六色对1～6、COLOR_PAIRS至少7，固定256色track为239，基础色BLACK|A_BOLD近似深灰，单色0，TERM不变。
- vLLM仅右侧RUNNING/WAITING及历史标题上方四指标的真实数字加粗，含0、科学记数和STALE旧数；`—`/`N/A`/`…`、左栏、标签/单位、caption、状态和历史等不新增粗体。TextCell末尾追加默认False的bold，保持原五个role与旧构造兼容，新增track仅用于硬件轨道；终端按原style叠加A_BOLD，单色也可请求粗体，低色实际字重/亮化依终端，既有Moonlight亮紫近似保持。
- vLLM右详情在模型名、RUNNING/WAITING统计及DECODE HISTORY/RATE HISTORY标题上方各留1行；对应相对空行+1/+5/+11，模型名+2、统计+6、四指标标签/值+9/+10、历史标题+12、图区+13..height−3、轴height−2。左栏完全不变；半页预算及最小16行服务区保持，最小图高1行，不扩大基础终端尺寸、不改历史算法。第三处留白位于历史标题前，原HTML源保持。
- HTML细节：Theme文字主色且贴右，设备标签正文、斜线分隔/发行版本/时钟灰；GPU标题主色，其余标题辅色。GPU功率灰，CPU百分号/RAM共享单位灰，Storage路径及空配置文案正文、容量/中点灰且百分比正文；Docker状态文字统一贴右，新鲜Running主色，其余正文。过宽数值保留指数/单位做有界科学记数，不能裁成较小完整值。原稿中的统一背景/选中标记等适配取舍以 `docs/design/theme.md` 对照表为准。
- 当前TERM=xterm保持不变；低色模式下Moonlight辅色用MAGENTA加A_BOLD近似亮紫，实际RGB由终端基础调色板决定；精确/固定256色保持既有目标色。仅主题变化强制整帧重绘，普通同主题帧维持差分刷新，不自动修改TERM。
- 随包containers提供一条可加载示例，使用前替换实际名称或完整ID；不监控时显式配置空列表，不把示例名称当作已发现部署。
- 保留 vLLM 原柱状历史。UI 目标 60 FPS（1/60秒，约16.7ms），采样默认仍为 1 秒；固定最近 60 秒横轴、稳定时间分箱，纵轴按稳定档位及时升档、延迟降档。点阵和面积图预览不作为正式方案；详细契约见 `docs/design/vllm.md` 与 `docs/design/application-shell.md`。
- 底部仅保留 `vLLM` / `WebUI` 服务切换位（暂不实现切换）；最下方英文键位提示使用冰蓝。设计预览中的模拟标记不属于正式 UI。

# Rules

- 禁止尝试连接任何服务器
- 按当前用户指令，不生成或重建离线安装包，不更新已有GUI启动/回放入口；既有包和回放仍属此前版本，不包含本轮track变更。
- 不清楚服务器内部的部署情况时，可查看 `D:\Documents\llm_server\Ubuntu_Server_03_显卡驱动.md` 和 `D:\Documents\llm_server\Ubuntu_Server_04_服务部署.md`

# Tests

- 产品目标为 Ubuntu Server 24.04 amd64；必需验证在本地 Ubuntu 或 WSL Ubuntu 执行。Windows 工作区通过 WSL 运行测试，目录可用 `~/projects/tmp`。
- 不要求维护原生 Windows 专用测试或执行 Windows 全量回归；通用非终端离线测试继续保留。
