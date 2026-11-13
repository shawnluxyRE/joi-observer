# Architecture

- 采用 Python 的 src 布局，拆分为宿主机常驻采集服务、宿主机 TUI 客户端和 Web 容器。以下仅列关键文件与目录，省略辅助模块、缓存及构建产物：

```text
.
├── src/joi_observer/          # Python 包
│   ├── __main__.py            # python -m joi_observer 入口
│   ├── cli.py                 # 命令参数与入口分派；默认启动 TUI 客户端
│   ├── runtime.py             # 采集器、Monitor、State 与日志的组装和清理
│   ├── service.py             # 宿主机常驻采集服务生命周期
│   ├── config.py              # 配置查找、解析与校验
│   ├── monitor.py             # 调度采集，统一写入状态
│   ├── error_log.py           # 采集错误分类、限频与日志轮转
│   ├── examples/config.yaml   # 随包配置示例，不自动作为监控配置加载
│   ├── data/                  # 数据对象与内存状态，不存放数据文件
│   │   ├── models.py          # 指标、采集结果与不可变快照
│   │   └── state.py           # MonitorState：最新数据、历史与采集状态
│   ├── collectors/            # 仅由宿主机采集服务使用
│   │   ├── base.py            # 统一采集器接口
│   │   ├── hardware.py        # GPU、CPU、内存与挂载点磁盘
│   │   ├── docker.py          # 本机容器身份与生命周期采集
│   │   └── vllm.py            # vLLM 服务指标采集
│   ├── ipc/                   # 受限的本机只读数据通道
│   │   ├── protocol.py        # 快照、展示元数据与协议契约
│   │   ├── server.py          # 采集服务的只读数据接口
│   │   └── client.py          # 数据接收、本地快照缓存与连接状态
│   ├── tui/                   # 宿主机终端客户端，含导航、主题及历史图
│   │   ├── app.py             # 终端生命周期、帧调度与输入处理
│   │   ├── layout.py          # 整页布局与帧组装
│   │   ├── widgets.py         # 硬件指标组件
│   │   └── vllm.py            # 模型列表、详情与历史图呈现
│   └── web/                   # 容器内的只读 Web 看板
│       ├── app.py             # Web 应用与数据客户端生命周期
│       ├── api.py             # 浏览器只读数据接口
│       └── static/            # HTML、CSS、JavaScript 等页面资源
├── deploy/
│   ├── systemd/               # 宿主机采集服务配置
│   ├── Dockerfile.web         # Web 容器镜像定义
│   └── compose.yaml           # Web 容器部署配置
├── tests/                     # 既有回归及服务、IPC、TUI、Web 验证
├── docs/
│   ├── design/                # 模块设计与 HTML 视觉参考
│   └── dev-workflow/          # 各工作批次的需求与阶段交接
├── pyproject.toml             # 包元数据、依赖与命令入口
├── uv.lock                    # 开发依赖锁定
├── README.md
└── AGENTS.md
```

- 数据流：`Collector → Monitor → MonitorState → 本机只读数据接口 → TUI / Web`；Web 再向浏览器提供页面与只读数据。采集服务拥有唯一权威状态，客户端通过快照通信，不跨进程直接共享 Python 状态对象。
- `data/state.py` 中的 `MonitorState` 保存最新数据、采样基线及时间、最近约 60 秒的有界历史和采集状态；不使用数据库，不持久化正常监控数据。受控错误日志由 `error_log.py` 单独维护。
- TUI 和 Web 使用统一生效的展示元数据及不可变快照；数据接收与界面绘制解耦，TUI 的同步 `snapshot()` 只读取本地缓存，不执行 I/O。客户端数量、模型选择和主题不影响采样次数或采样周期。
- 监控配置由宿主机采集服务统一读取，修改后重启服务生效。TUI 和 Web 不独立加载另一套监控对象，也不启动采集器。
- 采集服务与客户端独立启停，TUI 退出或 Web 容器停止不影响采集。连接失败后不自动重连：TUI 报错退出，重新运行重试；Web 停留错误页，刷新重试。
- Web 容器只读取白名单快照，不获得 Docker socket、GPU 设备或宿主机文件系统的直接采集权限；仅提供内网只读看板，不实现登录或网络策略管理。

# Info For Skills

- project_root：D:\Documents\joi-observer
- work_id：dev-1
- work_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-1
- req_id：REQ-001
- req_dir：D:\Documents\joi-observer\docs\dev-workflow\dev-1\REQ-001
- design_dir：D:\Documents\joi-observer\docs\design
- requirements_path：D:\Documents\joi-observer\docs\dev-workflow\dev-1\requirements.md

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

[Neon Grid HTML](docs/design/joi-observer.html) 是视觉参考；dev-1 的正式行为和验收以[需求说明](docs/dev-workflow/dev-1/requirements.md)为准，包括 Web 仅展示最近 60 秒、无历史回看，以及 TUI/Web 的模型名称映射。正式 TUI 的布局与主题适配见[主题设计](docs/design/theme.md#原稿与正式终端的逐项对应)。

# Rules

- 禁止尝试连接任何服务器
- 不生成或重建离线安装包，不更新已有 GUI 启动/回放入口；既有包和回放属于历史版本，不作为本轮改动的验证依据。

# Tests

- 产品目标为 Ubuntu Server 24.04 amd64；必需验证在本地 Ubuntu 或 WSL Ubuntu 执行。Windows 工作区通过 WSL 运行测试，目录可用 `~/projects/tmp`。
- 不要求维护原生 Windows 专用测试或执行 Windows 全量回归；通用非终端离线测试继续保留。
- 重构须保留并复用既有有效测试覆盖；未变更功能的原有测试必须通过，不得通过删除、跳过或弱化断言掩盖回归。接口迁移和已确认行为变化可调整相应用例，新增测试作为补充。
