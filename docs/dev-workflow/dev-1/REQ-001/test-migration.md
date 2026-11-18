# REQ-001 测试保留与迁移映射

- 修订：v1.0，2026-11-13。
- 依据：用户明确保持原有业务逻辑和测试验证意图；允许修改接口装配和已确认变化对应的预期。
- 当前阶段：R2 固定黑盒契约，R4 实现并使测试通过；R4 补适配器、真实终端接线及资源回收验证。

## 保留原则

迁移不是要求测试源码不变。配置、原始采集解析、身份、单位、数值精度、窗口、未知/N/A、失败缺口、布局、主题、导航、历史和日志的有效断言继续保留；接口调用和测试装配按新所有权调整。不得删除、skip、xfail、减小输入或放宽断言掩盖回归。生产采样间隔改为 1～60 秒后，解析配置边界用例须同步新范围；内部调度测试的受控时钟或较短等待仅用于离线加速，不改变生产配置契约。

## 迁移矩阵

| 既有测试入口 | 迁移内容 | 必须保留的验证意图 |
| --- | --- | --- |
| `tests/test_config.py`、`test_config_boundaries.py`、`test_vllm_config.py` | 样本间隔边界改为 1～60 秒；采集超时独立保持既有范围；服务持有配置加载 | YAML 安全校验、字段/行列定位、优先级、无非法回退、冻结配置、完整对象顺序和名称回退 |
| `tests/test_cli.py` | 默认入口配置加载场景移到 `service`；默认/TUI 测试改为只连接；新的参数/安全错误码由新分派验证 | 帮助不构造运行期、无副作用、配置错误脱敏、不泄漏异常、信号退出与清理 |
| `tests/test_hardware_runtime.py`、`test_docker_integration.py`、`test_vllm_runtime.py`、`test_vllm_integration.py` | 旧 ApplicationRuntime 装配改为 CollectorRuntime/CollectorService 与客户端接线 | 原始 IO 到真实采集/State/Frame 的数值和单位、失败隔离、隐藏对象仍采集、端口关闭 |
| `tests/test_local_hardware_io_edges.py`、`test_shell_edges.py`、`test_tui.py` | 拆分采集与 UI 生命周期；原 q 后关闭采集 IO 的场景改为服务 stop 后验证 | 部分初始化失败也清理、取消不记采集失败、时限、终端先恢复、幂等关闭及所有子资源回收 |
| `tests/test_navigation_app.py`、`test_navigation.py`、历史/主题/帧调度测试 | 注入 DisplayMetadata 和本地缓存；采集配置仍只在服务 | 模型按稳定 id 选择、每会话独立主题/尺度、同帧选择一致、60 FPS、公平输入、60 秒扫描和迟降 |
| `tests/test_vllm_view.py` 的双标题用例 | 列表仍 `name`，详情预期改为 `served_model_name or name`，与 AC-114 对齐 | 稳定 id 匹配、13/17/Total 30、QUEUED、忽略同名错误身份、输入不可变和标题槽位 |
| 其余纯硬件/Docker/vLLM 视图用例 | 可继续直接传 AppConfig，生产用 DisplayMetadata；两种输入采用相同正式展示规则 | 数字强调、精度、超长/Unicode 裁切、状态槽、0/未知/N/A、极大整数、不覆盖邻槽 |
| `tests/test_hardware_pty.py`、`test_terminal_pty.py`、`test_vllm_pty.py`、`test_navigation_pty.py`、`test_theme_pty.py` | 包装入口迁到离线服务/客户端；保持本地 Ubuntu/WSL PTY | 真实 curses 进入/退出、尺寸、主题、方向键/退出响应、异常及信号恢复、子进程回收 |

旧组合根中“按 q 关闭全部采集器”的原断言不能简单删掉：新测试分别验证“客户端 q 后服务与另一客户端继续”和“服务 stop 后全部采集 IO、日志及发布资源释放”。

## R2 补齐的新链路黑盒

`tests/test_snapshot_pipeline.py` 复用既有 `test_hardware.RawIO/gpu_row`、`test_docker_integration.RawCommand` 及 `test_vllm_full_response_integration` 的完整捕获响应端口。它们只替换原始文件、命令、HTTP、日志文件、字节流和终端边界；真实链路为：

`Collector → Monitor → MonitorState → build_metadata/encode_envelope → 内存字节流 → SnapshotClient → ObserverApp → Frame`。

三个参数场景分别选择 Chat、Embedding、Reranker；每个场景用受控同域单调时钟推进四次一秒采样，覆盖首样本未知、有效零、一次 503 局部失败与恢复。校验 CPU/RAM/磁盘/GPU 精确值和单位、Docker 配置 id、同一完整快照往返相等、元数据/GPU 关联、模型名称、N/A、STALE 及历史缺口。模型切换不重采，连接只创建一次；分批字节读取后才有完整缓存。

协议的独立 fixture 测试继续覆盖大快照和 `10**5000` / `10**10000` 整数保真；它们不能被小整数替换以规避原回归。原采集解析、窗口算法和视图的详细边界测试继续作为补充，不以一组贯通测试替代它们。

## 验证状态与分工

R2 新入口尚未实现时，测试失败应明确归因于实际业务入口的 NotImplementedError；测试仍期待正确结果，不把骨架失败当成功。完整链路测试的原始样本准备和基线断言位于待实现调用之前，能发现夹具或已有采集/状态链路的真实错误。

R4 实现编解码、客户端/发布状态机和新命令后，需要记录新链路全部转绿及既有适用回归结果。旧 main/ApplicationRuntime 留存期间的通过结果，只能证明旧实现未受当前骨架修改破坏，不能当作迁移完成的证据。禁止连接任何本地或远程服务器，所有传输验证使用离线端口；真实部署权限、systemd 和容器结果另行如实记录。
