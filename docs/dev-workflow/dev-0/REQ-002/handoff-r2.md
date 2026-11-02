# dev-0 / REQ-002 R2 交接

- stage：R2
- result：ready
- work_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev-req002\joi-observer\docs\dev-workflow\dev-0\REQ-002`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-002 / AC-201～AC-207及共同规则。
- 依赖依据：[REQ-001 R5交接](../REQ-001/handoff-r5.md) v1.4；本轮另实际重跑其全部测试。
- 分支：`codex/dev-req002`；基线提交：`a84f9d8b632544f1da005df37d7badc2c530d617`。
- next_role：R3
- 修订：v1.0，2026-10-30；首次设计，接口骨架、黑盒测试与未实现基线可交接。

本轮完成设计，不代表硬件业务已经实现。保留REQ-001执行逻辑和既有测试，新增业务入口仍为NotImplementedError；CLI及Frame接线仅补契约，实际接线交R4。所有产物在当前worktree，未修改原工作区；既有AGENTS.md修改由用户提供，本轮未改动。

## 产物

| 产物 | 版本/变更 |
| --- | --- |
| [hardware.md](../../../design/hardware.md) | v1.0：数值口径、GPU发现/逐卡隔离、挂载真实性、错误分类、IO与显示契约、UML类图、验收映射 |
| [monitor-state.md](../../../design/monitor-state.md) | v1.6：动态发现入口、UUID/inventory/CPU/RAM/挂载序号身份；State算法不变 |
| [configuration.md](../../../design/configuration.md) | v1.2：现有配置消费、精确GPU映射、前三挂载组装；无新配置字段 |
| [application-shell.md](../../../design/application-shell.md) | v1.3：生产组合根与纯硬件控件接线；保留半页布局和退出预算 |
| [collectors/hardware.py](../../../../src/joi_observer/collectors/hardware.py) | HardwareIO/LocalHardwareIO、CPU/RAM/Storage/GPU采集器、GpuDiscovery、来源工厂骨架 |
| [collectors/base.py](../../../../src/joi_observer/collectors/base.py)、[monitor.py](../../../../src/joi_observer/monitor.py) | DiscoveryResult/Discovery与register_discovery待实现入口；既有Collector和调度运行逻辑保留 |
| [tui/widgets.py](../../../../src/joi_observer/tui/widgets.py) | 分段条、容量格式化、显式GPU关联、硬件内容纯函数骨架 |
| [data/models.py](../../../../src/joi_observer/data/models.py)、[cli.py](../../../../src/joi_observer/cli.py)、[tui/layout.py](../../../../src/joi_observer/tui/layout.py) | 仅补充身份/接线注释，不提前调用新入口 |
| [test_hardware.py](../../../../tests/test_hardware.py) | 99项：原始离线数据→采集公开结果、异常恢复及工厂 |
| [test_hardware_monitor.py](../../../../tests/test_hardware_monitor.py) | 22项：动态注册原子性、周期、故障、真实State/日志与资源回收 |
| [test_hardware_view.py](../../../../tests/test_hardware_view.py) | 81项：格式化/颜色/映射/固定硬件布局及Frame目标接线 |
| [test_hardware_runtime.py](../../../../tests/test_hardware_runtime.py) | 1项：真实ApplicationRuntime到Frame，替换原始IO/终端，五卡最小尺寸及q退出 |
| [test-baseline.json](test-baseline.json) | 本轮可跟踪的验证摘要；详细日志/JUnit/离线材料位于被Git忽略的evidence |

共新增203项黑盒场景，不修改旧测试，不使用xfail/新增skip或“未实现即成功”的断言。测试预期来自需求和公开接口，IO替身提供proc/mountinfo/CSV/原始计数；不以模拟业务计算结果替代采集器验证。

## 验证证据

以下均为本轮实际执行；只使用本机工具、WSL及已有离线依赖，没有连接任何服务器，也没有查询真实GPU负载或挂载容量。nvidia-smi仅执行help命令读取本机帮助。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| Windows全量，Python3.12.10 / pytest8.4.2 / PyYAML6.0.1 | 567项：350 passed、202 failed、15 skipped，0 errors；8.35秒 | [文本](evidence/r2-full-windows.txt)、[JUnit](evidence/r2-full-windows.xml) |
| WSL Ubuntu-24.04全量，Python3.12.3 / pytest8.4.2 / PyYAML6.0.3 | 567项：365 passed、202 failed、0 skipped/errors；11.03秒 | [文本](evidence/r2-full-ubuntu.txt)、[JUnit](evidence/r2-full-ubuntu.xml) |
| 新增203项 | 1项无IO模板构造通过；202项为未实现/未接线基线，两个平台一致 | [结构化统计](evidence/r2-validation.json) |
| 既有REQ-001回归 | Windows349 passed / 15 Unix专用skip；Ubuntu364 passed / 0 skipped，原有失败数0 | 同上 |
| AST保留检查 | 原有函数执行体（忽略docstring）与旧测试AST全部保持；32个Python文件可解析 | [校验脚本](evidence/verify_r2_contracts.py)、[结果与SHA-256](evidence/r2-validation.json) |
| 差异与忽略规则 | git diff --check通过；evidence继续匹配 `.gitignore` 的 `/docs/dev-workflow/**/evidence/` | 本轮本地Git检查 |
| 本机字段材料 | nvidia-smi帮助v596.47，及Ubuntu proc_stat/proc_meminfo/proc_pid_mountinfo手册；未联网 | [CLI帮助](evidence/local-nvidia-smi-help.txt)、[GPU字段帮助](evidence/local-nvidia-query-help.txt)、[Linux手册原文](evidence/local-linux-proc-man.txt) |

202项失败的原因分组：

- 197项直接触达NotImplementedError。
- 2项发现器生命周期测试得到未实现异常后，正确拒绝让NotImplementedError（RuntimeError子类）冒充预期的生命周期拒绝；最终表现为断言失败，同属骨架未实现。
- 2项compose_frame目标行为、1项生产ApplicationRuntime硬件展示为断言失败，属于现有占位尚未接线。

没有导入/收集错误或新发现的REQ-001回归。最初系统Python缺少PyYAML，通过原工作区已有offline_deps解决，未安装或下载依赖；该环境问题不计入业务失败。没有重建wheel或重新执行uv安装验收，不将REQ-001历史安装记录冒充本轮实测。

Windows命令，工作目录为当前worktree根目录：

```powershell
$env:PYTHONPATH = 'D:\Documents\joi-observer\.pytest_cache\offline_deps'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m pytest -p no:cacheprovider -q --tb=no -rN --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r2-full-windows.xml
python -B docs/dev-workflow/dev-0/REQ-002/evidence/verify_r2_contracts.py
git diff --check
```

WSL命令，工作目录为`/mnt/d/Documents/codex_worktree/dev-req002/joi-observer`，使用已有离线uv项目环境的Python，没有同步依赖或访问索引：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -B -m pytest \
  -p no:cacheprovider -q --tb=no -rN \
  --junitxml=docs/dev-workflow/dev-0/REQ-002/evidence/r2-full-ubuntu.xml
```

pytest退出码1是未实现基线，不是验收通过。R4实现后新增测试应全部通过，旧功能回归继续通过。

## 本轮决策

1. GPU以完整UUID保持身份；index仅用于展示/显式映射。inventory独立、不占GPU槽；逐卡失败不扩散到其他卡或Host。
2. CPU/RAM分来源；CPU按累计tick差分，首次/回退/失败或取消后的首样本未知；RAM采用total-available。显存容量在任一实际解析失败时成对保留，避免新旧值混用后出现used>total。
3. Storage以mount-0..2作为短主键，原路径仅用于采集和展示。精确验证挂载点，前后检查挂载身份；不回退根容量、不以第四项补位。堆叠同路径记录保守失败，未宣称原子文件系统快照。
4. Monitor是唯一状态写入者。新增Discovery端口与注册方法，完整校验后才纳入新来源；已有来源相位/历史保持，停止覆盖所有动态资源。
5. 新控件保持GPU3行/Host5行外壳/Storage3行内容和既有半页布局。GPU高亮只读当前选择，不在REQ-002实现完整导航或双主题。
6. 旧通用GPU/host/local/路径Storage快照有明确只读兼容边界，生产只创建新schema；避免REQ-001已有断言与新展示契约冲突。
7. 标准库+本地nvidia-smi，不新增Python依赖。底层IO采用有界可取消本地进程边界；不能用不可取消线程声称满足退出预算。

## 尚未验证的范围

没有等待用户决定的设计问题。目标服务器驱动615.71.09、真实GPU输出/权限、无设备特例和真实挂载状态未现场验证，本机help版本不能替代目标版本证明。单次CLI无卡特殊输出目前仅有离线样本契约。

R4需要补足LocalHardwareIO实际worker、超时/取消/输出上限/进程回收的本地Linux验证，并在接口实现后完成动态调度、Frame和运行期接线。现有R2样本及调度测试不能代替真实OS适配验证。禁止自动连接服务器的约束持续有效。

## 下一步

接收角色为R3。请基于本交接和共享模块设计编写本目录`plan.md`及R3交接，安排采集/动态发现/控件/组合接线/离线验证的实现顺序，明确203项新增测试从未实现基线转为通过及REQ-001回归保持的要求。

本轮未启动R3/R4、未发送跨对话消息；后续阶段由人工指令推进。
