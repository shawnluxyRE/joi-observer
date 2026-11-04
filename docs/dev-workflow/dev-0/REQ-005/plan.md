# dev-0 / REQ-005 概要开发计划

- 项目：`D:\Documents\joi-observer`
- 工作目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- 需求目录：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005`
- 分支与基点：`codex/dev0-req005`，`83aad39131895561553d62a359e1f1c52957ed77`；沿用当前工作区及未提交的 R2 产物。
- 修订与状态：v1.0，2026-11-03；R3 ready，可交 R4 实施。导航业务尚未实现。
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-005 / AC-501～504 及共同只读、采样、布局规则；[AGENTS.md](../../../../AGENTS.md)。
- 设计交付：[handoff-r2.md](handoff-r2.md) v1.3；本轮核对与环境证据见 [handoff-r3.md](handoff-r3.md)。

## 设计、接口与测试依据

| 依据 | 本轮使用的接口与测试 |
| --- | --- |
| [navigation.md](../../../design/navigation.md) v1.3，“选择与键盘契约”“默认接线与刷新”“列表、详情与 GPU 关联” | [navigation.py](../../../../src/joi_observer/tui/navigation.py) 的 `SessionViewActions`；[test_navigation.py](../../../../tests/test_navigation.py)、[test_navigation_app.py](../../../../tests/test_navigation_app.py) |
| [application-shell.md](../../../design/application-shell.md) v1.7，“生命周期与异步协作”“可验证的字符容量” | [app.py](../../../../src/joi_observer/tui/app.py) 的 `ViewActions` / `ObserverApp`；[cli.py](../../../../src/joi_observer/cli.py) 的既有装配；[test_navigation_pty.py](../../../../tests/test_navigation_pty.py) 与既有外壳/终端测试 |
| navigation.md 的“服务入口与键位呈现”、R2 v1.1～v1.3 服务归属补充 | [services.py](../../../../src/joi_observer/tui/services.py) 的 `ServicePresentation` / `VLLM_SERVICE` / `footer_text`；[layout.py](../../../../src/joi_observer/tui/layout.py) 的 `compose_frame`；[test_service_footer.py](../../../../tests/test_service_footer.py) |
| [hardware.md](../../../design/hardware.md) v1.3、“硬件显示与模型关联”；[vllm.md](../../../design/vllm.md) v1.4、§10 | 复用 `linked_gpu_ids` / `hardware_cells`、`vllm_cells` 及 `ViewSelection`；既有硬件映射、vLLM 视图/历史、布局测试 |

## 范围与实施起点

REQ-001～004 已合并，采集、状态、三类型详情/历史、GPU 映射、列表可见窗口和终端按键解析均为已有能力。本轮完成模型导航、会话主题标识、默认应用接线以及当前/禁用服务与页脚呈现，覆盖 AC-501～504。

沿用 `Collector → Monitor → MonitorState → TUI`；选择只存在于应用会话。复用既有纯视图和唯一采样链路，不新增配置、持久化偏好、滚动状态、GPU 焦点或服务切换状态机。WebUI 继续禁用，Enter/p/Tab 无操作。主题按后续需求仅由键盘 `t` 切换；精确 RGB 映射与全屏双主题视觉验收留 REQ-006，本轮不以名称或语义角色通过代替完整配色完成。

## 主要任务

| 任务编号与标题 | 交付结果、关联需求与验证依据 | 大致修改范围及设计依据 | 前置依赖 |
| --- | --- | --- | --- |
| T-001 会话选择控制器 | 按配置顺序与 id 选择，初始首项、空列表 None、上下单步首尾停留；不同 id 即使同名/同类型/同端点仍独立。返回不可变选择，会话间隔离，t 保留模型、导航保留主题，无动作键安全且无 I/O。AC-501/502/503；`test_navigation.py` 的控制器及真实视图联动用例。 | `tui/navigation.py`；复用 `ModelConfig`、`ViewSelection` 与既有 `ViewActions` 协议。依据 navigation.md 的选择契约。 | 无新增启动前置；输入与接口已冻结。 |
| T-002 默认应用接线与注入兼容 | 直接构造及正式 CLI 默认获得导航；显式注入对象原样使用，包括 falsey 对象。每帧只读一次选择并用于详情/GPU；刷新、失败、resize 及同实例再次运行保留选择，小窗口仍处理导航/t。全局 q/中断、忽略键和既有刷新/清理规则保持，所有模型继续独立采样。修正 **R2-005-001** 的选择读取与按键分派。AC-501～504；`test_navigation_app.py`、`test_navigation_pty.py`。 | `tui/app.py` 的默认控制器与读键/绘制接合；核对 `cli.py` 现有装配无需第二份选择状态。依据 navigation.md 默认接线及 application-shell.md 生命周期契约。 | 可依现有协议开始；默认导航的贯穿验收需 T-001 完成。 |
| T-003 服务描述与页脚呈现 | 同一当前服务描述驱动服务标题、当前入口和页脚。vLLM 入口为 primary，分隔符及 WebUI (disabled) 为 muted；页脚精确为 `↑↓ Select model    t Theme    q Quit`，仅导航说明来自服务描述，其余全局文字保持。服务切换位/页脚各一行并保持既有半页预算。AC-503/504；`test_service_footer.py` 及应用页脚断言。 | `tui/services.py` 的页脚组合、`tui/layout.py` 的静态描述接线；不引入实际服务切换。依据 navigation.md 服务呈现契约。 | 无新增启动前置，可独立于 T-001/T-002 开发。 |
| T-004 离线联验与交付 | 完成三类型详情/单位/历史/GPU 同帧联动、长列表/尺寸恢复、采样隔离、真实终端与已安装 CLI 验证；现有 44 项失败转绿并保护既有通过行为。更新实现状态、使用说明及 R4 交接，证据对应最终源码和安装产物。覆盖全部 AC-501～504。 | 新增四组测试及受影响接合、README、本需求 `evidence/` 和 `handoff-r4.md`；必要时补足实际集成缺口，不重写既有业务算法。 | 环境/离线包准备可立即开始；最终联验需 T-001～T-003 集成及完整离线构建安装材料。 |

## 开发顺序与并行条件

1. T-001、T-003 可并行；T-002 可按既定协议同步开始，不必等控制器实现才修改接线。T-004 的离线依赖与安装验证准备提前进行，具体执行步骤和 subagents 分工由 R4 确定。
2. T-002 主要涉及 `app.py`，T-003 涉及 `services.py` / `layout.py`；若联动修复需要触及同一文件，先协调写入再集成。保留现有 `vllm.py`、`widgets.py`、Monitor/State 的职责，不把纯视图回归任务扩大成重写。
3. 完成验证先汇合 T-001 + T-002，检查默认应用、注入兼容、三类型/GPU 联动和采样隔离；合入 T-003 后检查真实整帧、页脚及下半页预算，再执行 T-004 的最终全量和安装验证。
4. `R2-005-001` 随 T-002 处理；只修构造不足以关闭问题，读取和分派也必须保留 falsey 注入对象。服务描述与页脚测试的可变输入仅用于证明绑定，不扩展到 WebUI 实现。
5. 各任务先运行对应定向测试；集成后做一次最终 Ubuntu 全量及安装验证。后续只有改动、失败或未解决问题需要时才追加复跑。设计/测试含义冲突交回 R2，规划调整写入 R4 交接的“R3 修订汇总”，不削弱验收断言。

## 验证安排

### 基线与本地环境

已核对 R2 最新 [JUnit](evidence/r2-sync-pytest.xml)、[输出](evidence/r2-sync-pytest.txt) 及 [审计](evidence/r2-sync-audit.json)：**1442 项，1398 passed / 44 failed / 0 errors / 0 skipped**。其中既有 1395 项通过；新增 47 项为 3 通过、44 失败。失败分类为控制器骨架 28、页脚函数骨架 2、默认接线 11、服务呈现 2、falsey 注入缺陷 1。骨架提前失败遮蔽的后续断言仍需 R4 实际执行。

R3 在本地 WSL Ubuntu-24.04（Ubuntu 24.04.5 LTS / x86_64）、Python 3.12.3 完成 `pytest --collect-only -q`：**1442 tests collected，退出码 0**，见 [收集输出](evidence/r3-collect-only.txt)。本轮没有重跑业务断言；不能将收集成功表述为测试通过。实际解释器及已装依赖见 [环境记录](evidence/r3-environment.json)。

R4 在 WSL 中可使用以下入口；另选本地 Ubuntu 环境时记录实际路径和版本：

```bash
cd /mnt/d/Documents/joi-observer
# 新增导航与服务呈现契约
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q \
  tests/test_navigation.py tests/test_navigation_app.py \
  tests/test_navigation_pty.py tests/test_service_footer.py --tb=short
# 集成后的最终全量，包含既有终端与采集回归
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r4-final-pytest.xml
```

保留通用离线测试与 `conftest.py` 的 DNS/connect 防护，PTY 子进程同样隔离外部 I/O。目标平台的 PTY 必须实际执行，不以 skip/xfail 隐藏未实现；不要求 Windows 全量回归。完成标准为验收行为通过及无未解释错误，新增必要用例按实际数量报告。

### 验收与接合检查

| 验证主题 | 完成判定与依据 |
| --- | --- |
| AC-501：选择及联动 | 三类型按配置顺序遍历、首尾停留，合法 id 不因刷新/缺失/STALE/恢复被替换；同一选择驱动详情、类型单位、独立历史与显式 GPU 关联。历史不清空，GPU 集合/顺序/槽位不变，未知映射不猜测。重点复用 `test_navigation_updates_type_units_history_and_gpu_roles_together` 及既有硬件/vLLM 视图断言。T-001/002。 |
| AC-502：容量与恢复 | 0/1 模型、12 模型逐项选择、奇偶页高、最小/过小/恢复尺寸；足够尺寸下选中项可见，过小期间按键仍更新会话，恢复显示最新选择。模型数不抬高最低尺寸，上下半页、Storage 三行、Docker 可见前缀保持。T-001/002。 |
| AC-503/504：服务与有效键位 | 左右不离开 vLLM、不更改模型或上半区、不新增 WebUI 来源；Enter/p/Tab 无详情/暂停/焦点操作。服务标题、当前入口、页脚共用描述，空模型仍用 vLLM 提示，固定文字、语义角色和下半页预算正确。T-002/003。 |
| 会话/注入与采样隔离 | truthy/falsey 注入均保留，每帧一次选择读取；同实例再次运行保持、新实例重置。`test_production_composition_navigates_without_starting_or_rebuilding_sources` 验证装配；`test_real_monitor_sampling_and_histories_are_independent_of_navigation` 在应用仍活跃且处理 Enter/p 后推进全部模型采样，不能只在退出后验证。T-002/004。 |
| 终端与公共回归 | 新 PTY 覆盖真实 curses、CSI/SS3、t、忽略键、q 与 termios/备用屏/光标恢复；既有终端/外壳测试保护首帧、50ms 读键、10Hz 普通绘制、resize 重绘和异常/信号清理。保留硬件、Docker、vLLM、状态和日志回归；双主题精确配色不在本次完成判定内。T-004。 |
| 已安装 CLI | 从最终源码构建 wheel，核对新模块随包及安装来源；隔离 uv 工具环境，离线安装后在新 shell/异目录验证裸命令。通过已安装 CLI 的真实 PTY 验证三类型导航、正常→过小→恢复、主题标识、忽略键、q 和终端恢复；不能用源码 PYTHONPATH 测试代替。T-004。 |

### 离线构建与安装条件

当前测试 venv 已有 HTTPX 0.28.1 及运行依赖，足以加载现有测试；构建后端 setuptools 未安装在该 venv，但本地已有对应 wheel。当前项目 `.pytest_cache/offline_wheels` 只有 9 个 wheel，缺少 HTTPX 及其传递依赖的成套文件。

R3 已按 [REQ-004 离线包清单](../REQ-004/evidence/r4-offline-wheels.json) 只读核对 **17 个来源文件全部存在且 SHA-256 相符**，其中包括 WSL pip 缓存中的缺项，见 [本轮核对](evidence/r3-offline-artifacts.json)。因此当前没有已确认的外部材料阻塞，但 R4 仍需在构建前从这些本地来源整理完整 wheel 集合并准备构建环境；本轮没有安装软件或重建包。安装使用离线、禁止索引及禁止 Python 下载的选项，不连接包服务器。

可参考当前确实存在的 [REQ-004 安装验证脚本](../REQ-004/evidence/r5-retest3-install/verify_uv_install.py)，先适配其中旧 worktree、包和证据路径，并扩展 REQ-005 的导航/缩放场景。已装 CLI 的离线入口应显式加载并验证 I/O 替身与网络防护，再调用已安装业务；只使用虚构域名或假定隐式 sitecustomize 会加载，不足以保证离线。替身限于外部 I/O，不替换控制器、默认应用、布局或采样链路的业务结果。

### 交付与证据边界

R4 更新 README 的导航实现状态、实际键位、当前服务/禁用入口及主题边界；同步修改过的源码中“未实现”阶段注释。必要的接合补测以现有契约为准，不改变需求、指标格式或公开接口含义。

新证据使用 REQ-005 `evidence/` 下的 R4 专用名称，记录命令、平台、源码/包校验信息和实际结果，保留 R2/R3 记录。该目录已被 Git 忽略，跨环境交接须单独携带。禁止尝试连接任何服务器，不运行采证脚本或真实服务联调；离线验收不扩大为部署现场或完整双主题保证。

当前没有需用户改变范围或 R2 先补齐设计的待决事项。完成后更新本需求 `handoff-r4.md` 请求 R5 验收，跨角色推进由用户发起。

## 修订记录

- v1.0（2026-11-03）：基于 R2 v1.3 建立四项交付、启动依赖、并行与集成顺序；纳入 R2-005-001、服务归属、Ubuntu 测试/安装验证及 REQ-006 边界，核对现有离线材料。
