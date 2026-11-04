# dev-0 / REQ-005 R5 验收交接

- stage：R5
- result：passed
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-005`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-005 / AC-501～504，以及共同只读、采样、布局约束。
- 验收依据：[plan.md](plan.md) v1.0、[handoff-r2.md](handoff-r2.md) v1.3、[handoff-r4.md](handoff-r4.md) v1.0；[导航设计](../../../design/navigation.md) v1.3、[应用外壳](../../../design/application-shell.md) v1.7、[硬件](../../../design/hardware.md) v1.3、[vLLM](../../../design/vllm.md) v1.4 及根目录 AGENTS.md。
- 审查对象：分支 `codex/dev0-req005`，比较基准 `83aad39131895561553d62a359e1f1c52957ed77`；覆盖当前未提交的实现、设计、README 和四组 REQ-005 测试，不只审查已提交版本。审查开始时 137 个非忽略文件的 SHA-256 和完整状态见 [开始快照](evidence/r5-review-start.json)，已跟踪交付差异见 [patch](evidence/r5-delivery-tracked.patch)。
- next_role：R0
- 修订：v1.1，2026-11-03；完成用户要求的代码与测试逻辑复查，补齐三类测试遗漏；最新全量 1450 passed。首轮记录保留，复查详情见下文。

## 产物

首轮仅在 [tests/test_navigation_app.py](../../../../tests/test_navigation_app.py) 补充两个用例，原有用例完整保留：

| 新增用例 | 补齐的风险 |
| --- | --- |
| `test_fixed_size_key_burst_updates_next_normal_frame_without_extra_redraws` | 固定终端尺寸下连续按键全部生效，在下一普通绘制周期显示最后选择与主题；不借 resize 触发绘制，不因导航突破 10Hz 上限；全局退出正常恢复终端。仅替换外部时钟。 |
| `test_default_app_keeps_model_and_gpu_selection_consistent_during_discovery_and_failure` | 默认应用同帧显示模型详情及对应 GPU 角色；发现新卡只追加显示槽位，快照顺序变化不重排；STALE 索引不猜测，显式 UUID 关联仍有效，模型/GPU 恢复不改变选择。仅提供只读样本。 |

另新增本交接及本目录 `evidence/r5-*` 证据。没有修改业务代码、需求或设计契约，没有删除、跳过或削弱原有测试。[修改范围审计](evidence/r5-audit.json) 核对去掉两个新增函数后的测试文件与开始快照一致，其他原有非忽略文件保持原样。最终 GPU 用例按屏幕坐标核对角色，不依赖 TextCell 返回顺序。

## 验证证据

本节保留 v1.0 首轮记录；v1.1 的新增测试、最新全量和修改范围见“代码与测试逻辑复查”。

本轮实际环境：本地 WSL `Ubuntu-24.04`，Ubuntu 24.04.5 LTS / x86_64，Python 3.12.3；工作目录 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。所有验证使用离线端口，保留 DNS/connect 防护；未尝试连接服务器。

| R5 实际执行 | 结果 | 证据 |
| --- | --- | --- |
| 审查开始时四组 REQ-005 契约测试 | 47 passed，2.02s | [输出](evidence/r5-baseline-pytest.txt)、[JUnit](evidence/r5-baseline-pytest.xml) |
| 默认应用 GPU 联动补测后定向验证 | 15 passed，0.58s | [输出](evidence/r5-gpu-navigation-pytest.txt)、[JUnit](evidence/r5-gpu-navigation-pytest.xml) |
| 两个新增用例及原应用测试 | 16 passed，0.56s | [输出](evidence/r5-added-tests-pytest.txt)、[JUnit](evidence/r5-added-tests-pytest.xml) |
| 最终全量，包括真实 curses/PTY 与新增用例 | **1444 passed / 0 failed / 0 errors / 0 skipped，26.53s**；既有 1395 + REQ-005 原 47 + R5 新增 2 | [输出](evidence/r5-final-pytest.txt)、[JUnit](evidence/r5-final-pytest.xml) |
| 已安装 CLI 独立离线复验 | **passed**；19 检查点、21 帧、2.221s、退出码 0；三模型各 63 次 fixture 请求，全部端口关闭；网络/外部进程尝试为 0；termios、备用屏、光标恢复，无强杀或遗留进程 | [安装结果](evidence/r5-install/uv-install-results.json)、[输出](evidence/r5-install/run-output.txt)、[验证脚本](evidence/r5-install/verify_uv_install.py) |
| 源码、安装包及修改边界 | R4 产品源码哈希无差异；wheel 一致；复用的 4 份安装验证脚本字节一致；仅新增测试和本轮交接/证据；`git diff --check` 通过 | [审计](evidence/r5-audit.json) |

第一次全量也是 1444 passed，26.49s，保留于 [初次输出](evidence/r5-initial-full-pytest.txt) 和 [JUnit](evidence/r5-initial-full-pytest.xml)。随后仅将新 GPU 用例的返回顺序断言改为屏幕坐标断言，重跑上述最终全量；以最终结果为准。

验收覆盖核对：

| 标准 | 独立核对与实际验证 |
| --- | --- |
| AC-501 | 配置顺序遍历三类型、首尾停留；详情/指标适用性/单位/历史切换；新鲜索引、UUID、未知映射及 GPU 高亮；刷新、STALE、恢复与普通绘制周期保留选择。控制器、真实纯视图、默认应用、Monitor 集成及真实 PTY 共同覆盖。 |
| AC-502 | 0/1 模型安全，空态仍可 t/q；长列表选择始终可见；最小尺寸、奇偶页高、缩小及恢复保持选择。 |
| AC-503 | 当前 vLLM 与禁用 WebUI 明确呈现；左右键不改变服务/模型/硬件，不增加采样来源；所有模型持续由唯一 Monitor 采集。 |
| AC-504 | Enter/p/Tab 无额外交互，活跃应用中 Enter/p 后采样仍继续；页脚精确为 `↑↓ Select model    t Theme    q Quit`；服务描述绑定正确。 |
| 共同约束与回归 | falsey 注入原样保留、每帧一次读取选择、实例隔离与同实例重入、固定半页预算、Storage/Docker 可见容量、采集/状态/日志/退出与资源回收均由全量保护。R2-005-001 已由实际测试复验关闭。 |

测试命令（`python` 为上述 WSL 解释器；输出同时用 `tee` 保存）：

```bash
python -m pytest -q tests/test_navigation.py tests/test_navigation_app.py \
  tests/test_navigation_pty.py tests/test_service_footer.py --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r5-baseline-pytest.xml
python -m pytest -q tests/test_navigation_app.py --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r5-added-tests-pytest.xml
python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r5-final-pytest.xml
python docs/dev-workflow/dev-0/REQ-005/evidence/r5-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv --python /usr/bin/python3.12 \
  --wheel docs/dev-workflow/dev-0/REQ-005/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl
```

安装复验复制 R4 的四份已审阅验证脚本到同层 `r5-install`，不覆盖 R4 记录，使用同一个最终 wheel，没有重建产品包。wheel SHA-256 为 `42d45db20e999013e14bda98fd8d076d8094ad12b6ac82acd6bbc9c964be92fc`；27 个 Python/YAML 源文件及 README、pyproject.toml、uv.lock 与原安装证据一致。工具安装为独立 HOME/uv 环境，`uv --offline --no-python-downloads tool install --no-index --find-links ...`；新 shell、异目录裸命令验证通过。实际 TUI 执行未修改的已安装 console script，保留真实 CLI、配置、采集器、Monitor、State、默认应用、控制器、布局与 curses；仅外部 I/O 被替换。

独立复核确认：按键 ACK 等待输入消费后的首个绘制帧，再断言结果，不等待“正确选择”出现；覆盖 CSI/SS3、三类型及首尾停留、忽略键、120×40 → 80×24 → 120×41，小窗口内 down/t 后恢复到最新选择。R4 早先两次观测脚本失败及修正说明已审阅，不是本轮产品缺陷。R4 的 1442 passed 和原安装结果只作为交付历史引用；上述 R5 测试和安装结果均为本轮实际执行。

## 本轮决策

**REQ-005 在选定范围内验收通过。** 未发现需要 R4 修复的验收缺陷；AC-501～504 与相关设计契约满足，必要 Ubuntu 验证完成，新增测试及全量均通过，无待关闭问题。

限制：使用本地离线样本，没有验证部署服务器、现场 NVIDIA 驱动/容器、真实 HTTP/TLS。GPU 联动由真实视图和默认应用的只读样本测试验证，安装场景没有真实 GPU。精确 Moonlight/Hologram RGB 及全屏双主题外观属于 REQ-006，本结论仅覆盖主题会话状态和名称，不将其视作完整视觉验收。证据及 wheel 目录被 Git 忽略，跨环境交接需另行携带。

## 代码与测试逻辑复查（v1.1）

用户要求再次检查代码和测试是否存在错误或遗漏。复查没有沿用全绿结果作为充分依据，重新核对导航实现、默认与注入控制器、模型身份、GPU 联动、普通刷新、长列表、真实终端解码、采样隔离和安装验证的 ACK 逻辑。审查范围仍为 REQ-005 及其依赖接合，基准提交未变；本次开始时 138 个文件的状态与 SHA-256 见 [复查快照](evidence/r5-recheck-start.json)。[v1.0 原交接](evidence/r5-handoff-v1.0.md) 另存供追溯。

**结论：没有复现业务代码缺陷；确认三类测试覆盖遗漏，已由 R5 补齐，验收仍为 passed。**

| 确认的遗漏 | 补充验证与处理结果 |
| --- | --- |
| 同类型、同名、同端点的不同模型 id，只在控制器层区分；原贯穿测试的值/历史不足以识别按类型错误取首项 | 新增 `test_default_app_uses_id_for_same_type_name_and_endpoint_samples`。使用反序快照、不同吞吐/STALE/历史，默认应用 down/up 三帧验证选中行与数据，并切回原帧；显式检查帧数，当前吞吐与最新历史保持一致。 |
| `selection_reads == len(frames)` 仅验证总数，不能排除不同帧多读/漏读相互抵消 | 新增 `test_each_frame_reads_selection_once_for_model_details_and_gpu_highlight`。计数装饰器保留真实 SessionViewActions；每次 render 当场核对本帧恰好一次读取，同时验证模型详情、GPU 高亮与主题；selection 本身不推进状态。 |
| 原残缺输入测试只保留最后一次读取结果，且 expected=None 分支不检查返回键，可能漏掉短暂误发动作；残缺前缀后接完整方向键的恢复组合未覆盖 | 在 [test_terminal_pty.py](../../../../tests/test_terminal_pty.py) 新增参数化用例 `test_incomplete_prefixes_never_emit_actions_or_consume_following_arrows`，共 4 节点：单独 ESC、残缺 CSI 全过程无键，以及 malformed/expired 前缀后 CSI/SS3 方向键和 q 的完整精确序列。复用真实 PTY 和终端恢复检查，不修改原 helper 或原测试。 |

新增共 **6 个测试节点**（应用 2 个、PTY 4 个），没有改动任何既有测试函数、业务实现或设计契约。[复查审计](evidence/r5-recheck-audit.json) 核对删除本次新增函数后的两个测试文件可还原到复查开始快照，源码与契约哈希保持不变。

为验证身份遗漏确实存在，执行 [内存错误注入脚本](evidence/r5-recheck-mutation-type-alias.py)：仅在独立 Python 进程中临时将 `vllm_cells` 的两个按 id 取对象位置改为“取同类型第一项”，不写产品文件。

- 补测前，选定的导航、应用、页脚和 vLLM 纯视图 **121 项仍全部通过**，证实原测试会漏掉这类数据串用：[原测试输出](evidence/r5-recheck-mutation-type-alias-before.txt)。没有据此声称整个测试仓库对该错误都不敏感。
- 补测后，新增身份用例在错误注入下明确失败，吞吐断言识别错取数据：[最终错误注入输出](evidence/r5-recheck-mutation-type-alias-after-final.txt)。这是预期检出测试错误版本，**不是实际产品测试失败**；脚本核实产品源码 SHA-256 未变。
- 相同新增用例在真实产品实现下通过：[最终定向输出](evidence/r5-recheck-identity-pytest-final.txt)、[JUnit](evidence/r5-recheck-identity-pytest-final.xml)。

本次实际验证仍在同一 WSL Ubuntu 24.04 / Python 3.12.3 环境执行，保留离线保护：

| R5 复查实际执行 | 结果 | 证据 |
| --- | --- | --- |
| 逐帧选择补测与原 truthy/falsey 注入用例 | 3 passed，14 deselected，0.50s | [输出](evidence/r5-recheck-selection-pytest.txt)、[JUnit](evidence/r5-recheck-selection-pytest.xml) |
| 终端与导航真实 PTY，含 4 个新增输入节点 | 20 passed，0 skipped，7.27s | [输出](evidence/r5-recheck-input-pytest.txt)、[JUnit](evidence/r5-recheck-input-pytest.xml) |
| 最终身份补测 | 1 passed，0.41s | 上述最终定向输出与 JUnit |
| 最终全量 | **1450 passed / 0 failed / 0 errors / 0 skipped，27.10s** | [输出](evidence/r5-recheck-final-pytest.txt)、[JUnit](evidence/r5-recheck-final-pytest.xml) |
| 原测试、产品源码、契约及交接链接核对 | 原测试完整保留；业务与契约未改；`git diff --check` 通过 | [审计](evidence/r5-recheck-audit.json) |

全量最终命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-005/evidence/r5-recheck-final-pytest.xml
```

较早一次复查全量亦为 1450 passed，26.75s，见 [初次输出](evidence/r5-recheck-initial-full-pytest.txt) 和 [JUnit](evidence/r5-recheck-initial-full-pytest.xml)。随后仅校正新增身份用例的样本一致性并补显式三帧断言，重新执行上述最终全量；所有结论以最终版本为准。

现有实现按模型 id 正确读取数据；默认控制器、falsey 注入、无状态列表窗口与 GPU 追加槽位逻辑未发现错误。真实按键和安装脚本均在输入消费后的首个绘制帧断言，未发现等待“正确结果”而掩盖中间错误的逻辑。采样隔离用例使用真实 Monitor/State/Collector；其手工推进调度的边界由首轮已安装 CLI 的真实并发运行证据补足。

产品及构建输入未变，本次没有重复安装，沿用并重新审阅首轮 19 检查点的已安装 CLI 证据；不将其写成第二次重新安装。未验证真实服务器/驱动/容器/网络与 REQ-006 完整 RGB，限制不变。三类遗漏均已在测试层处理，不需要 R4 修订业务实现。

## 下一步

**接收角色：R0（协调者/用户）。** 请据本交接确认 REQ-005 阶段完成，并由人工决定后续需求或提交安排。无需退回 R4；本轮不自动推进其他角色聊天，也不修改 README 中保留的 R4 交付时状态说明。
