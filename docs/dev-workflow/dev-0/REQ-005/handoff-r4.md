# dev-0 / REQ-005 R4 交接

- stage：R4
- result：ready
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-005 / AC-501～504 及共同布局、只读和采样规则。
- 计划依据：[plan.md](plan.md) v1.0；[handoff-r2.md](handoff-r2.md) v1.3。
- next_role：R5
- 修订：v1.0，2026-11-03；实现、全量与已安装 CLI 验证完成，可交 R5 审查。
- 工作区：沿用 `codex/dev0-req005` 及现有未提交 R2/R3 产物，不新建 worktree。

## 产物

| 任务 | 开发前检查 | 当前状态 |
| --- | --- | --- |
| T-001 会话选择控制器 | 模型 id、冻结选择、顺序与键盘契约一致，无新增 I/O 或跨模块接口 | 完成，[navigation.py](../../../../src/joi_observer/tui/navigation.py)：私有配置序号，首项/空 None，首尾停留，t 保持模型，其他键无动作 |
| T-002 默认应用接线 | 默认控制器可在构造接入；CLI 已复用 ObserverApp；falsey 注入须贯穿读取/分派 | 完成，[app.py](../../../../src/joi_observer/tui/app.py)：按 None 默认化，原样保留注入；每帧一次读取，重绘/重入不重建；CLI 无需改动 |
| T-003 服务与页脚 | 静态描述可统一标题、当前入口和页脚；区域预算无需变更 | 完成，[services.py](../../../../src/joi_observer/tui/services.py)、[layout.py](../../../../src/joi_observer/tui/layout.py)：同一描述绘制标题/当前项/页脚；当前项 primary，禁用项 muted，半页预算不变 |
| T-004 离线联验与交付 | WSL Ubuntu 24.04 / Python 3.12 环境及本地离线依赖来源可用 | 完成；全量及已安装 CLI 均通过，[README](../../../../README.md) 已更新，17 个本地 wheel 已核验，证据及包校验已归档 |

主对话汇总所有任务检查并确认跨任务契约一致后，已安排三个子任务并行实现。未发现设计或计划阻碍；同文件修改范围互不重叠。

## 验证证据

实际环境：本地 WSL `Ubuntu-24.04`（Ubuntu 24.04.5 LTS / x86_64），Python 3.12.3，工作目录 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。未尝试连接服务器，保留 DNS/connect 防护及 PTY 子进程防护。

开发前实际执行：

```bash
python -m pytest -q tests/test_navigation.py tests/test_navigation_app.py \
  tests/test_navigation_pty.py tests/test_service_footer.py --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r4-baseline-pytest.xml
```

结果：**3 passed / 44 failed / 0 errors / 0 skipped，2.85s**。失败与 R2/R3 基线一致，包含未实现控制器/页脚、默认接线及已记录的 falsey 注入缺陷，无导入或环境失败。[JUnit](evidence/r4-baseline-pytest.xml)。该记录是开发前基线，最终结果以下表为准。

| 实际检查 | 结果 | 证据 |
| --- | --- | --- |
| T-001 定向控制器与真实视图联动 | 27 passed，0.32s | [输出](evidence/r4-t001-pytest.txt)、[JUnit](evidence/r4-t001-pytest.xml) |
| T-002 应用、导航 PTY、外壳和布局 | 77 passed，2.94s；truthy/falsey 单独复核 2 passed | [输出](evidence/r4-t002-pytest.txt)、[JUnit](evidence/r4-t002-pytest.xml)、[注入验证](evidence/r4-t002-injected.txt) |
| T-003 页脚、服务描述及布局 | 61 passed，0.58s | [输出](evidence/r4-t003-pytest.txt)、[JUnit](evidence/r4-t003-pytest.xml) |
| 集成后全量 | **1442 passed / 0 failed / 0 errors / 0 skipped，25.57s**；既有 1395 + REQ-005 新增 47 均通过 | [输出](evidence/r4-final-pytest.txt)、[JUnit](evidence/r4-final-pytest.xml) |
| 本地离线材料 | 17 个 wheel 按原清单逐一 SHA-256 核验并复制到 `.pytest_cache/offline_wheels`，无下载 | [清单](evidence/r4-offline-wheels.json)、[脚本](evidence/prepare_offline_wheels.py) |
| 最终 wheel 与独立工具安装 | wheel 内全部 Python/YAML 与源码字节一致；新 navigation/services 均随包；安装后的包和 README 一致；新 shell、异目录裸命令成功，无虚拟环境激活或源码 PYTHONPATH | [安装结果](evidence/r4-install/uv-install-results.json)、[最终输出](evidence/r4-install/run-output.txt) |
| 已安装 CLI 真实 PTY | 19 个检查点通过，21 个真实帧，2.206s，退出 0；3 模型各 63 次 fixture 请求且端口全部关闭，网络/外部命令尝试为 0；终端与所属进程正常清理 | 同上；[验证脚本](evidence/r4-install/verify_uv_install.py)、[显式离线入口](evidence/r4-install/offline_sitecustomize.py) |
| 实现审查与范围审计 | 内部独立只读审查未发现实质缺陷；既有已跟踪测试未改，公开接口含义未变；`git diff --check` 通过 | [审计](evidence/r4-audit.json)、[脚本](evidence/audit_r4.py) |

最终全量与审计的实际命令（python 为上述 WSL 解释器）：

```bash
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r4-final-pytest.xml
python docs/dev-workflow/dev-0/REQ-005/evidence/prepare_offline_wheels.py
python docs/dev-workflow/dev-0/REQ-005/evidence/audit_r4.py
```

安装验证使用 uv 0.13.6 和 `/usr/bin/python3.12`；验证脚本在独立 HOME/uv tool/cache 下离线构建 wheel，执行 `uv --offline --no-python-downloads tool install --no-index --find-links ...` 与 `tool update-shell`，然后从无源码路径的异目录、新交互 shell 验证 `joi-observer --version` / `--example-config`。脚本外层实际命令如下，完整命令与证据对应见 [命令汇总](evidence/r4-install/command-summary.json)：

```bash
python docs/dev-workflow/dev-0/REQ-005/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12
# 观测脚本修正后复用同一个 wheel，不更改或重建产品代码：
python docs/dev-workflow/dev-0/REQ-005/evidence/r4-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12 \
  --wheel docs/dev-workflow/dev-0/REQ-005/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl
```

安装包：[joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256：`42d45db20e999013e14bda98fd8d076d8094ad12b6ac82acd6bbc9c964be92fc`。验证前后源码、README、pyproject 和锁文件哈希保持一致。

已安装 CLI 在同一已安装解释器中先显式加载并检查网络/进程封锁和外部 I/O 替身，再执行未修改的 console script。实际使用安装包的 CLI、配置、采集器、Monitor、State、默认 ObserverApp、控制器、布局和 curses；未用源码 PYTHONPATH 或假选择结果。19 个检查点覆盖 CSI/SS3、三类型及首尾停留、t 保持模型、左右/Enter/p/Tab 无动作、忽略键后全部模型继续采样、120×40 → 80×24 → 120×41，以及小窗口内 down/t 后恢复到最新模型和主题。q 后 termios、备用屏和光标恢复；监督器记录没有强杀、补回收或剩余进程，所有所属进程正常结束且 subreaper 恢复。

全量包含真实 curses/PTY 的 CSI/SS3 输入、退出/信号和终端恢复回归。新增测试已实际触达此前被骨架失败遮蔽的详情/单位/历史/GPU 联动、长列表、0/1 模型、STALE/恢复、过小窗口导航及恢复、应用重入、falsey 注入和活跃应用采样隔离断言。T-001～T-003 复用了现有 47 项契约测试，未新增重复实现的镜像测试，也未削弱验收断言。

审计脚本初次读取 Windows 检出目录时，WSL Git 默认换行设置把 CRLF 误计为改动；改为仅本次命令传入 `-c core.autocrlf=true` 后核对通过。未更改 Git 配置或测试内容。该问题属于证据脚本适配，不是业务或 R2 测试失败。

安装观测工具的两次失败及审查修正亦独立保留：第一次误用完整模型名匹配已有截断列表，第二次误等终端本来不产生的归一化 Tab 键；分别修为名称前缀结合同一行类型、被动记录真实 Tab 字节消费。内部审查还将按键 ACK 改为只等待按键消费后的首个绘制帧，然后立即断言业务结果，避免等待预期结果掩盖中间错误；每帧按序号独立原子记录。修正仅在 evidence 脚本内，真实解码器原参数/返回值保持，未修改产品或 R2 测试。详见 [修正说明](evidence/r4-install/verification-notes.json)、[第一次记录](evidence/r4-install/run-01-harness-failure.json)、[第二次记录](evidence/r4-install/run-02-harness-failure.json)。最终脚本再次经独立只读复核确认，复验结果为 passed。

证据目录被 Git 忽略，跨环境交接须单独携带。未验证部署服务器、真实网络/TLS、现场驱动/容器或 REQ-006 精确 RGB/全屏双主题外观；这些不是本轮完成判定。

## 本轮决策

- 复用同一采样与纯视图链路，仅增加会话内导航和静态服务呈现，不扩大 REQ-006 的完整配色范围。
- 构造默认化后直接使用控制器，避免 falsey 注入对象在读取或分派时再次被忽略。
- 本轮无新增验收含义或公开接口修改；不自动推进 R5 对话。

## R2 修订汇总

### R2-005-001 falsey 注入被忽略

- 关联任务与产物：T-002，`tui/app.py` 和 `tests/test_navigation_app.py`。
- 问题与依据：显式传入的 falsey ViewActions 被旧 `if self.actions` 跳过；R2 已明确要求保留所有显式对象。
- 处理与请求：构造采用 `actions is None`，后续读取和分派直接使用已确定的控制器；truthy/falsey 两种注入场景及全量均通过，问题关闭。
- R2 回复与 R4 确认：采用 R2 v1.3 既定处理意见，无设计改动或待澄清契约；R4 已核实并完成修复。无需要 R2 修正的测试错误，无 R3 计划修订请求。

## 下一步

**接收角色：R5。处理结论：REQ-005 / T-001～T-004 已完成，R4 ready，无阻碍验收的待决事项。** 请以本交接、R2 v1.3 设计和 R3 v1.0 计划审查 AC-501～504、测试完整性及最终安装证据，输出本需求的 `handoff-r5.md`。需要复现安装验证时携带被 Git 忽略的 evidence 和离线 wheel 集合。跨角色推进由用户发起；R4 ready 不表示已经通过 R5 验收。
