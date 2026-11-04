# dev-0 / REQ-005 R2 交接

- stage：R2
- result：ready
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-005 / AC-501～504 及共同只读、布局、采样约束；[R1 交接](../handoff-r1.md)。
- next_role：R3
- 修订：v1.3，2026-11-03；完成设计、类图、骨架与测试的同步复核并补齐遗漏，最新结果见本节复核记录。
- 设计基点：`83aad39131895561553d62a359e1f1c52957ed77`，REQ-004 已合并；当前分支 `codex/dev0-req005`，使用现有工作区，没有新建 worktree。

## 处理结论

REQ-005 已具备概要开发规划条件。需求范围明确，无需新增用户决定；R2 已提供共享设计、可加载的接口骨架、目标注释和黑盒测试。`ready` 表示设计可交接，**不表示导航已经实现或新业务测试通过**。

已复用 REQ-001 的终端生命周期和按键归一、REQ-002 的 GPU 映射、REQ-004 的分类型详情/历史及列表可见窗口。新的业务入口为 `SessionViewActions` 与 `footer_text(service)`；正式默认接线和服务/页脚呈现仍由 R4 完成。

## v1.3 同步复核与修正

来源为用户要求重新核对全部 R2 产物。本轮逐项对照 AC-501～504、后续服务绑定要求、类图、公开签名、注释与黑盒断言，发现并修正以下遗漏：

- **旧现状说明**：应用外壳与硬件共享文档仍残留 vLLM 占位/执行未接线文字，已更新为 REQ-004 三类来源已合并，避免 R3/R4 重复规划；导航表中的采样隔离测试改为明确指向 `test_navigation_app.py`。
- **被前置失败遮蔽的测试错误**：新导航测试期待 `100 tok/s`、`3 seq/s` 等带空格文字，而现有 `format_metric` 实际为 `100tok/s`、`3seq/s`。已修正新测试期待并单独验证三类纯视图；未修改现有格式化业务或 UI 文字。
- **服务描述覆盖**：补充冻结性断言，同一 Frame 使用测试输入描述的 title 绘制服务标题/当前入口，并使用 navigation_label 绘制页脚；其余全局文字保持不变。
- **会话/采样覆盖**：同端点、同名、同类型的不同 id 仍独立；补充同一应用顺序两次运行保持选择和主题、每帧只读一次选择。真实 Monitor 集成改为应用仍运行且 Enter/p 已处理后推进调度，确认全部模型继续采样，再发送 q；不再只验证应用退出后的采样。

新测试总数为 **47项**：navigation 27、navigation_app 14、navigation_pty 1、service_footer 5。类图中的所有对象和方法均与现有声明或明确的R4目标接线对应；没有遗漏服务描述/页脚接口，也没有把模块框误作新类。`t` 的主题状态/名称切换与 REQ-006 完整配色边界保持一致。

本轮在同一 WSL Ubuntu-24.04 工作目录与解释器执行：

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r2-sync-pytest.xml
python docs/dev-workflow/dev-0/REQ-005/evidence/audit-sync.py
```

| 最新检查 | 实际结果与证据 |
| --- | --- |
| 全量基线 | **1398 passed / 44 failed / 0 errors / 0 skipped，28.19s**；[输出](evidence/r2-sync-pytest.txt)、[JUnit](evidence/r2-sync-pytest.xml) |
| 既有 REQ-001～004 | **1395项全部通过**；既有测试集合保留 |
| 新增 REQ-005 | **3通过、44失败**；28个控制器骨架、2个页脚函数骨架、11个默认接线、2个服务/页脚呈现待实现，以及1个已记录的 R2-005-001 falsey 注入缺陷；没有测试环境或导入异常 |
| 骨架与原实现边界 | 原有24份生产Python去除docstring后AST与基点一致；新增入口仍为声明/未实现骨架，服务描述为冻结数据；[审计](evidence/r2-sync-audit.json)、[脚本](evidence/audit-sync.py) |
| 被骨架遮蔽的纯视图期待 | 直接传入真实不可变ViewSelection，3类指标文字及12模型×4页高共48组可见性均通过；没有替换或实现导航控制器 |
| 文档/类图一致性 | 新设计和本交接的本地链接有效；类图字段、模块函数、常量和标准UML关系静态核对通过，未运行Mermaid渲染器；`git diff --check`通过 |

同步问题已处理，当前未发现剩余设计/图/声明/测试不一致。尚未实现导致的失败继续保留为R4基线；其后续集成断言不能冒充已验证的导航行为。R2保持 `ready`，接收角色仍为R3；本轮未修改业务实现或自动推进其它角色。

## v1.2 类图同步

补齐上一轮遗漏的 `ServicePresentation`、`tui.services` 中的 `VLLM_SERVICE/footer_text`，以及 `tui.layout.compose_frame` 的依赖关系。模块明确标记为 `module`，不引入不存在的实现类；关系使用标准 UML 表示，线上不添加说明文字。图与当前声明、R4待接线契约保持一致，`ViewSelection.theme` 与 REQ-006 配色边界不变。

本次仅修改设计图与交接版本，未修改代码或测试；已核对实际接口及 `git diff --check`，沿用下方验证记录，不重复运行无变化的业务测试。接收角色仍为 R3，按更新后的图与契约规划。

## v1.1 页脚服务归属修订

来源为用户直接补充：页脚 `Select model` 与当前下半区 vLLM 服务绑定；未来切换到其它服务时，上下箭头后的文字可以变化，其它文字不改。

已采纳。新增静态冻结的 `ServicePresentation`，当前 `VLLM_SERVICE` 的导航文字为 `Select model`。外壳使用同一服务描述绘制标题、当前入口和页脚，`footer_text(service)` 仅变化 navigation_label；`↑↓`、四空格间距、`t Theme`、`q Quit` 和其它 UI 文字均保持原约定。没有新增可切换服务、服务状态机或配置字段，控制器签名保持不变。

v1.1 增加 [test_service_footer.py](../../../../tests/test_service_footer.py) 的4项契约测试，当时新增测试总数为44项。WSL 实际运行该文件、已有页脚断言和 `tests/test_tui.py`：**56 passed / 4 failed / 0 errors / 0 skipped，0.82s**。其中既有外壳55项通过，服务元数据1项通过；footer_text骨架2项失败、服务提示接线1项失败、已有页脚目标1项仍失败，均为待R4实现。此处保留历史结果，最新集合以v1.3为准。

命令：`python -m pytest -q tests/test_service_footer.py tests/test_navigation_app.py::test_footer_lists_only_live_keys_and_service_entry_marks_vllm_current tests/test_tui.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r2-footer-pytest.xml`。执行位置和解释器同下文，证据为 [输出](evidence/r2-footer-pytest.txt)、[JUnit](evidence/r2-footer-pytest.xml)。本轮新增元数据与未实现函数声明，未改既有执行体；`git diff --check` 通过。

接收角色仍为 **R3**：规划时将服务描述和页脚组合接线纳入 REQ-005，维持当前 vLLM 页脚可见文字及其它文字；未来服务切换不在本次实现范围。

## 产物

| 产物 | 版本或内容 |
| --- | --- |
| [navigation.md](../../../design/navigation.md) | v1.3：完整 UML 类图、服务描述及全部导航契约；测试映射和单位期待已复核 |
| [application-shell.md](../../../design/application-shell.md) | v1.7：默认控制器、注入兼容、当前服务页脚；REQ-004现状说明已同步 |
| [hardware.md](../../../design/hardware.md) | v1.3：同一 ViewSelection 联动显式 GPU 映射；已清除过期vLLM占位说明 |
| [vllm.md](../../../design/vllm.md) | v1.4：接收导航选择、继续采集全部模型、复用现有滚动/历史；不修改 REQ-004 指标契约 |
| [navigation.py](../../../../src/joi_observer/tui/navigation.py) | `SessionViewActions(models)` 存储结构及 `selection/on_key` 完整契约；两个行为入口保留 NotImplementedError |
| [services.py](../../../../src/joi_observer/tui/services.py) | `ServicePresentation`、`VLLM_SERVICE` 元数据及 `footer_text(service)` 接口骨架；组合行为留R4 |
| [app.py](../../../../src/joi_observer/tui/app.py)、[layout.py](../../../../src/joi_observer/tui/layout.py) | 仅同步 ViewActions、ObserverApp、ViewSelection、compose_frame 的目标注释；既有执行体保留 |
| [test_navigation.py](../../../../tests/test_navigation.py) | 27 项：控制器公开行为、同端点身份、类型/单位/历史/GPU联动、失败与resize、输入不可变 |
| [test_navigation_app.py](../../../../tests/test_navigation_app.py) | 14 项：默认/注入/生产装配、会话重入、每帧一次读取、长列表、小窗口、失败保持、活跃应用采样隔离、页脚与禁用服务 |
| [test_navigation_pty.py](../../../../tests/test_navigation_pty.py) | 1 项：真实本地 PTY/curses、默认应用、CSI/SS3 方向键、主题、忽略键和退出恢复 |
| [test_service_footer.py](../../../../tests/test_service_footer.py) | 5 项：冻结元数据、vLLM归属、不同导航文字输入、固定全局文字、标题/当前入口/页脚共用描述 |
| [README.md](../../../../README.md)、[AGENTS.md](../../../../AGENTS.md) | 标明 R2 状态和新设计入口；当前 req_id/req_dir 指向 REQ-005 |

未修改需求说明、REQ-001～004既有测试断言、采集器、Monitor/State、依赖或锁文件；未编写 R3 的 plan.md，未提前完成 R4 业务。新 evidence 沿用现有 `.gitignore` 规则；先前复制的 REQ-002/003/004 evidence 保留。

## 本轮决策

1. **一个会话控制器，两个已有协议方法。** 仅接收不可变模型元组；按 id 和配置顺序选择，不按显示名、类型或健康状态合并/跳项。初始首模型，空列表 None，上下单步且首尾停留。
2. **默认接线放在 ObserverApp。** `actions is None` 时创建控制器，显式对象原样使用；读取和分派也不能依赖真假值。每个应用实例独立，刷新、失败、resize 不重建控制器。ApplicationRuntime 不再创建第二份选择。
3. **复用渲染和映射。** 不新增滚动偏移、GPU 焦点或服务状态机；同一帧详情与 GPU 共享一次 selection 读取。合法配置 id 的约束避免触发既有纯视图对未知 id 的不同容错规则。
4. **主题边界明确。** t 切换会话主题标识且保留模型，空列表和小窗口亦有效；完整 curses RGB 配色及整体视觉验收留 REQ-006。
5. **服务仍固定 vLLM。** vLLM 用 primary 标明当前，WebUI (disabled) 用 muted；左右不切换。当前 vLLM 页脚为 `↑↓ Select model    t Theme    q Quit`，Select model 由服务描述提供，全局键位文字不变；两行各占既有下半页预算，不新增 Details/Pause/Tab。

## v1.0 全量验证证据（保留历史基线）

本轮实际执行位置：本地 `WSL Ubuntu-24.04`，工作目录 `/mnt/d/Documents/joi-observer`，Python 为 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。测试使用既有离线依赖，不安装软件、不访问服务或运行采证脚本。pytest 的 DNS/connect 防护及 PTY 子进程网络防护均保留。

v1.0 最终全量命令（其中 `python` 为上述解释器；v1.1 的新增4项另见上文）：

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r2-final-pytest.xml
```

| 实际检查 | 结果 | 证据 |
| --- | --- | --- |
| 最终全量，含新增40项 | **1396 passed / 39 failed / 0 errors / 0 skipped，26.79s**，pytest 返回1 | [终端输出](evidence/r2-final-pytest.txt)、[JUnit](evidence/r2-final-pytest.xml) |
| 其中既有测试 | **1395项全部通过**，未调整旧断言 | 同一 JUnit 按测试模块核对；[审计](evidence/r2-audit.json) |
| 其中新增测试 | **1通过、39失败**；truthy 注入兼容已通过，失败分类见下表 | 同上 |
| 本地真实 PTY | 完整按键序列及9次帧确认完成，子进程exit0；termios/备用屏/光标恢复、无网络尝试检查先通过，随后在首个down后仍为CHAT的业务断言失败 | `test_navigation_pty.py` 与最终输出；不声称导航已通过 |
| 设计范围审计 | 已有生产 Python 去除 docstring 后 AST 与 HEAD 相同；新控制器仅字段与未实现入口；新设计链接有效，`git diff --check` 通过 | [审计脚本](evidence/audit-r2.py)、[审计结果](evidence/r2-audit.json) |

初次全量结果为1396通过/38失败；独立审查发现缺少 falsey 注入断言后，新增该参数场景并重跑，以上最终结果取代初次基线。初次 [输出](evidence/r2-pytest.txt) 和 [JUnit](evidence/r2-pytest.xml) 保留供追踪，不作为最终集合。

### 失败分类与现有缺陷

| 类别 | 数量 | 性质及后续处理 |
| --- | --- | --- |
| `SessionViewActions.selection/on_key` 抛 NotImplementedError | 27 | R2 骨架尚未实现；含26项直接契约和1项真实Monitor链路。断言期待正确行为，不把未实现当成功 |
| 默认导航接线未完成 | 10 | 包括正式装配及PTY；当前仍固定首模型/默认主题，待R4接线 |
| 页脚/当前服务呈现 | 1 | 当前仍为旧 `↑↓ Models`，待R4同步目标文字和当前服务角色；后续角色断言尚未到达 |
| **R2-005-001：falsey 注入对象被忽略** | 1 | 现有真实缺陷，单独记录，不归为骨架未实现；见下文 |

**R2-005-001（P2）**：向 ObserverApp 显式传入实现 `ViewActions` 且 `__bool__` 返回 False 的对象，应使用其选择并分派支持的按键。现有 `run()` 使用 `if self.actions`，导致该对象被忽略、退回首模型，`received` 为空。复现入口为 `tests/test_navigation_app.py::test_injected_actions_are_preserved_and_only_supported_keys_are_dispatched[falsey]`，无需网络。R4 默认接线时须一并修正读取和分派判断，保留 truthy 场景。R2 本轮只增加契约与测试，未修改执行体。

所有新增测试均可导入并触达真实公开入口，没有导入或环境错误。骨架提前失败意味着其后续历史、GPU、采样隔离断言尚未全程执行；这些断言是待实现验收条件，不能引用为本轮已证明的导航行为。原有已通过测试仍提供相关纯渲染、采样、映射和终端基础证据。

## 验收映射与遗留验证

| 验收 | 本轮目标覆盖 |
| --- | --- |
| AC-501 | 配置顺序三类型遍历、首尾钳制、详情/单位/不同历史/GPU角色联动、刷新和故障保留、无额外采样及未选中项继续采集 |
| AC-502 | 0/1模型安全、12模型逐项选择、奇偶/最小/过小/放大后选择可见，不抬高最小高度 |
| AC-503 | 左右保持vLLM与模型、无WebUI来源、上半区与既有区域不变、禁用服务文案 |
| AC-504 | Enter/p/Tab无交互；模型采样不因按键暂停；精确可用键位和全局q/t |

R4 需实现后重跑新增与既有全部用例，并验证实际离线安装包经 CLI 进入后的导航、窗口恢复和退出清理。R2 未安装新包，也未完成完整双主题颜色或部署现场验收。没有待用户确认的范围事项；上述验证属于后续实现/验收工作，不阻止 R3 接收本设计。

## 下一步

**接收角色：R3。** 请基于本交接和共享模块设计编写 `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005\plan.md`，规划会话控制器、默认接线、页脚/服务呈现、R2-005-001 修正及离线回归/安装验证，并明确 REQ-006 的完整颜色边界。

本轮止于 R2 交接；没有创建其他角色聊天、自动推进 R3/R4、提交或推送。后续跨角色推进由人工指令发起。
