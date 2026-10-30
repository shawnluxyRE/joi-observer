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
- req_id：REQ-003
- req_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-003
- design_dir：D:\Documents\joi-observer\docs\design
- requirements_path：D:\Documents\joi-observer\docs\dev-workflow\dev-0\requirements.md

# Design

- 设计稿：`docs/design/joi-observer.html`（精简 HTML 片段，作为布局、配色和交互参考；独立预览时按需导出完整 HTML）。
- Ubuntu Terminal TUI：深色、等宽、紧凑分区，全英文；以当前 Neon Grid 总览为准。
- 配色：背景 `#080E18`，正文 `#D4DDEB`，次要信息 `#8A9DB5`；冰蓝 `#7DDFFF` 为主色，浅紫 `#C6A7FF` 为辅色；仅 `QUEUED` 和大于 0 的等待数量用琥珀 `#FFA45B`，`WAITING` 标签与 0 使用普通文字色，不加感叹号。
- 顶部：`Joi::Observer`（`Joi` 使用主题辅色，`::` 灰色，`Observer` 使用主题主色），主机信息右侧显示时间；右上角按钮切换 Moonlight（冰蓝 / 浅紫）与 Hologram（`#7B9FFF` / `#E570D0`），两种主题共用琥珀强调规则。
- 页面纵向分为上下两半：下半区的服务窗口、底部服务切换位及最下方键位提示合计固定占全页高度的一半；顶部品牌、主机信息及上半区硬件等使用剩余高度。奇数页高时下半区向下取整，多出的 1 行留给上半区。
- 上半区：左侧 GPU 列表，右侧依次为 Host Resources、Storage、Docker。GPU 分段条占可用宽度约一半，百分比在条末端，使用主题主色，显存灰色；CPU / RAM 条使用主题辅色，未填充段与 GPU 同灰色，RAM 已用量灰色、总量白色。Storage 固定 3 行内容，标题和边框另计，仅采集和显示配置前 3 个挂载点，其余忽略不报错。Docker 配置数量不限、全部采集；面板填充右侧扣除 Host Resources、Storage 及间距后的剩余高度，按配置顺序只显示内容区可容纳的容器，剩余不显示、不作任何提示，不因容器数提高最小终端高度。窗口放大后可显示更多条目；不增加滚动、分页或更多标记，不侵占下半区，内容少时允许留白。
- 下半区：服务窗口与底部切换位、键位提示共同使用半页高度；紫色 `vLLM` 标题；左侧模型列表，选中项冰蓝；右侧运行、排队、吞吐、延迟、KV Cache 与柱状历史图。路由信息浅紫，文案用 `Total`、`Avg queue`。
- 底部仅保留 `vLLM` / `WebUI` 服务切换位（暂不实现切换）；最下方英文键位提示使用冰蓝。设计预览中的模拟标记不属于正式 UI。

# Rules

- 禁止尝试连接任何服务器
- 不清楚服务器内部的部署情况时，可查看 `D:\Documents\llm_server\Ubuntu_Server_03_显卡驱动.md` 和 `D:\Documents\llm_server\Ubuntu_Server_04_服务部署.md`

# Tests

- 必要时可以使用WSL的Ubuntu系统，目录可用`~/projects/tmp`。
