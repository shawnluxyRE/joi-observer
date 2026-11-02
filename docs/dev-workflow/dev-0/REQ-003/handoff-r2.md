# dev-0 / REQ-003 R2 交接

- stage：R2
- result：ready
- next_role：R3
- 修订：v1.0，2026-10-30
- 来源：用户指定 REQ-003 首次设计；无 R3/R4 修订单。
- 当前分支：`codex/dev-req003`；起点 `codex/dev0` / `a84f9d8b632544f1da005df37d7badc2c530d617`，本轮产物尚未提交。
- 实际 project_root：`D:\Documents\codex_worktree\dev-req003\joi-observer`
- 实际 work_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0`
- 实际 req_dir：`D:\Documents\codex_worktree\dev-req003\joi-observer\docs\dev-workflow\dev-0\REQ-003`
- 需求依据：当前 worktree 的 `docs/dev-workflow/dev-0/requirements.md` v1.12，REQ-003 / AC-301～304 与共同规则；依赖 REQ-001。

AGENTS 的路径元数据沿用原仓库。本轮按用户已创建并切换到的 worktree 保存对应相对路径产物，没有写回 `D:\Documents\joi-observer`。开始时 AGENTS.md 已有用户将 REQ-001 改为 REQ-003 的修改，本轮未编辑该文件。

## 产物

以下路径均相对上述实际 project_root；模块文档跨需求原位维护。

| 产物 | 版本/变化 |
| --- | --- |
| `docs/design/docker.md` | v1.0；单容器职责、UML 类图、本机命令/响应、身份与失败、取消清理、生产组装和测试映射 |
| `docs/design/configuration.md` | v1.2；保留现有 YAML 结构，补充精确容器身份引用，更新已实现状态说明 |
| `docs/design/application-shell.md` | v1.3；Docker 命令端口注入与全量采集器接入约定 |
| `docs/design/monitor-state.md` | v1.6；固定 Docker state 字段及复用关系，不修改 Monitor/State 算法 |
| `src/joi_observer/collectors/docker.py` | CommandOutput / DockerCommandPort / LocalDockerCommand / DockerCollector / parse_inspect / build_docker_collectors 声明与完整注释；业务方法均为 NotImplementedError |
| `src/joi_observer/config.py` | 仅补 ContainerConfig 注释，解析行为不变 |
| `src/joi_observer/cli.py` | 可选 docker_command_factory 参数和依赖保存、R4 接入注释；当前生产仍只注册 Docker 模板，未调用新工厂 |
| `tests/test_docker.py` | 83 项；生命周期、身份、错误、限量输出、真实采集入口和工厂契约 |
| `tests/test_docker_command.py` | 19 项；替换 OS 创建端口，验证本机命令、环境、双流、超时/取消/close 回收 |
| `tests/test_docker_integration.py` | 3 项；真实采集器到 Monitor/State/Frame/Log；隐藏失败恢复、慢项隔离、生产组装 |
| `tests/conftest.py`、`tests/test_cli.py`、`tests/test_shell_edges.py` | 新增离线 IO 防护与 pending command 工厂；两个既有生产首帧测试隔离未来 Docker IO，原断言保留 |

本轮只有设计、结构、注释和测试，没有实现 Docker 读取、解析、调度或显示业务。已有公共实现保留；没有修改 requirements.md、依赖清单或 .gitignore。

## 本轮决策

| 编号 | 决策与依据 |
| --- | --- |
| D-003-01 | 采用本机 Docker CLI、固定 `unix:///var/run/docker.sock`、参数数组与最小 JSON 模板；无需新增 SDK，避免 ps 表格和全量 inspect 输出。删除子进程 DOCKER_* 环境，不跟随远端 context，不自动探测 rootless 或 sudo。 |
| D-003-02 | 配置 id 是状态 key；查询目标必须精确匹配名称或完整 64 位小写 hex ID。完整 ID 优先按 ID 解释，不接受其同名替代；短 ID 仅前缀命中不算匹配，名称监控允许同名重建。 |
| D-003-03 | 七种生命周期统一首字母大写，包含 Removing；Exited/Dead 不记错，Health/State.Error 忽略。失败复用现有六类 Failure，stderr 只参与固定分类，原文不透传。 |
| D-003-04 | 每配置项独占一个命令端口，全部接入唯一 Monitor；容量裁剪只在已有 Frame 中发生。无配置时不创建端口，不把失败项换成后续项，不新增面板/分页。 |
| D-003-05 | 每流 65536 字节上限并发读取，底层 timeout 与 Monitor timeout 双重约束；取消/close 在 250ms 内终止及回收，close 取消在途 run 并向其调用方传播 CancelledError。 |

独立审查已核对并同步 close 的取消语义、timeout 排除 bool、响应 Name 内部禁止 `/`。测试对进程/连接端口默认拒绝真实 IO；双流替身支持 StreamReader 的常规读取方法，避免把特定读取算法写成验收条件。

## 验证证据

运行日期 2026-10-30。全部为本地离线验证，未尝试服务器连接，未执行实际 docker 命令、访问 Docker socket 或下载安装依赖。样本为契约构造的原始 JSON/错误文本，不是部署实采数据。

环境：Windows 工作区，WSL `Ubuntu-24.04`；复用现成虚拟环境 `~/projects/tmp/joi-observer-dev-0-venv/bin/python`。最初使用 Windows `python -m pytest -q` 时缺 PyYAML，出现 11 个 collection errors；该环境问题通过切换现成本地 WSL 环境解决，不能归类为业务基线失败。

实际运行位置：`/mnt/d/Documents/codex_worktree/dev-req003/joi-observer`。

```sh
# 新增设计产物前的既有基线
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q
# 364 passed

# 完成产物、审查修订后的全量验证
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-003/evidence/pytest.xml
# 103 failed, 366 passed；exit code 1
```

| 范围 | 实际结果 | 分类 |
| --- | --- | --- |
| 原有 364 项（包含 15 项本地 Unix PTY） | 364 passed | 既有功能无回归；首帧测试增加命令 IO 注入后仍通过 |
| test_docker.py，83 项 | 2 passed / 81 failed | 结构声明可用；业务入口未实现，其中 1 项因 NotImplementedError 不符合预期未知异常消息而断言失败 |
| test_docker_command.py，19 项 | 19 failed | 全部触达 LocalDockerCommand.run 的 NotImplementedError |
| test_docker_integration.py，3 项 | 3 failed | 2 项为采集骨架未调用命令导致计数断言失败；1 项为生产组合尚未接入采集器，等待期限内没有采样 |

合计 469 项均可收集、加载并触达入口；无最终导入/环境错误、无 skip/xfail。103 项失败中 99 项直接为 NotImplementedError，另 4 项是上述业务缺失导致的行为断言失败。没有将“尚未实现”当作通过条件，不要求 R2 阶段把业务测试变绿。

- 完整输出：[evidence/pytest-full.txt](evidence/pytest-full.txt)
- 机器可读结果：[evidence/pytest.xml](evidence/pytest.xml)
- `git diff --check` 通过。
- `git check-ignore -v -- docs/dev-workflow/dev-0/REQ-003/evidence/pytest.xml` 命中原有 `.gitignore` 的 `/docs/dev-workflow/**/evidence/`；验证产物仅本地保留。

## 遗留与下一步

当前没有阻止 R3 规划的待决输入。ready 表示设计、骨架和验证基线可交接，不表示 Docker 功能已经实现。

接收角色 **R3**：请读取本交接与 `docs/design/docker.md`，在本需求目录编写 `plan.md` 及 `handoff-r3.md`，规划解析、受限异步命令、采集器/工厂、生产组合接入和离线用例转绿；保留现有配置/布局/状态/日志实现。R3 如发现契约问题，以本需求目录的修订汇总回交 R2。

R4 后续需执行这些待实现入口并让黑盒测试验证正确业务行为，不能删除失败用例或用预设 CollectionResult 替换被测逻辑。真实 Docker 版本、模板兼容性、权限/错误文案和真实子进程清理时限尚未验证；只能在之后获得相应授权的环境验证，当前限制持续有效。

本交接未向其他聊天发消息或自动推进阶段；按用户手动指令交给 R3。
