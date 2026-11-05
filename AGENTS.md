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

| 文档 | 维护内容 |
| --- | --- |
| [应用外壳](docs/design/application-shell.md) | 启动与退出、整页布局和最低尺寸、页眉、UI 帧调度 |
| [主题](docs/design/theme.md) | 颜色角色、硬件条字形与轨道、终端配色降级及恢复 |
| [硬件](docs/design/hardware.md) | 硬件采集、数值口径与精度、面板内部布局、GPU 关联 |
| [Docker](docs/design/docker.md) | 容器采集与身份、生命周期、条目名称及状态槽 |
| [vLLM](docs/design/vllm.md) | 服务指标与窗口、模型列表和详情坐标、数字强调、历史图 |
| [导航](docs/design/navigation.md) | 会话选择、按键、服务入口与页脚 |
| [配置](docs/design/configuration.md) | 配置查找、字段校验、默认值与示例 |
| [状态](docs/design/monitor-state.md) | 调度、公共结果类型、只读快照与状态更新 |
| [错误日志](docs/design/error-logging.md) | 采集错误分类、限频、文件格式与轮转 |

[Neon Grid HTML](docs/design/joi-observer.html) 是视觉参考；正式 TUI 的采用与适配范围见[主题设计](docs/design/theme.md#原稿与正式终端的逐项对应)。

# Rules

- 禁止尝试连接任何服务器
- 按当前用户指令，不生成或重建离线安装包，不更新已有GUI启动/回放入口；既有包和回放仍属此前版本，不包含本轮track变更。

# Tests

- 产品目标为 Ubuntu Server 24.04 amd64；必需验证在本地 Ubuntu 或 WSL Ubuntu 执行。Windows 工作区通过 WSL 运行测试，目录可用 `~/projects/tmp`。
- 不要求维护原生 Windows 专用测试或执行 Windows 全量回归；通用非终端离线测试继续保留。
