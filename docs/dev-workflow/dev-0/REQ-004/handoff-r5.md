# dev-0 / REQ-004 R5 验收交接

- stage：R5
- result：passed
- work_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0\REQ-004`
- 需求依据：[requirements.md](../requirements.md) v1.12，REQ-004 / AC-401～412、D-001 与共同规则。
- 验收依据：[plan.md](plan.md) v1.0、[handoff-r2.md](handoff-r2.md) v1.3、[handoff-r4.md](handoff-r4.md) v1.2、[vllm.md](../../../design/vllm.md) v1.2、[view-contract.md](view-contract.md)、配置/状态/应用外壳设计与 AGENTS.md。
- 审查对象：分支 `codex/dev0-req004`，比较基点 `2b3643096f193fe9c13d2e78e43924bfc64953ab`；审查覆盖当前 worktree 全部已跟踪及未跟踪的 REQ-004 交付，而非只看已提交 diff。初始路径、Git 状态与逐文件 SHA-256 见 [r5-review-start.json](evidence/r5-review-start.json)。与 R4 manifest 交叉核对一致。
- next_role：R0
- 修订：v1.4，2026-11-03；按用户授权完成提交前全面检查与交付收尾，结论 passed；R5-004-001～004 与测试补漏 R5-TST-003 均已关闭。本轮提交目标为当前 `codex/dev0-req004` 分支，提交标识见 Git 记录；未自动联系或推进其他角色聊天。

## v1.4 提交前全面检查与收尾（2026-11-03）

用户明确要求“再全面检查一下，如果没问题就 commit”。三组独立只读复核覆盖采集/HTTP/运行期、State/数值/视图、文档/打包/提交范围，未发现新的业务实现或测试预期阻碍。业务代码及已有 1365 个测试未改；完成两类提交收尾：

- README 将 REQ-004 状态更新为已通过 R5 离线验收，替换当前仓库不存在的 REQ-001 evidence 辅助脚本命令，改为实际已纳入仓库的终端 pytest 入口。
- 新增 `.gitattributes`：原始 `.prom`、`*-models.json`、`*-version.json` 使用 `-text`，防止 Windows `core.autocrlf=true` 的新 checkout 改变样本字节、导致 provenance SHA-256 失败；`provenance.json` 元数据和 shell 脚本固定 LF。12 份原始 fixture 内容与哈希未修改；不是通过放宽哈希断言处理行尾问题。

将全部暂存文件通过 `git checkout-index --all --prefix=<本需求 evidence/r5-precommit-tree/>` 导出到独立副本，验证提交本身包含所需源码、测试与 fixture；副本没有本工作区原始 evidence 或离线 wheel 缓存。使用既有 Ubuntu 依赖环境，全部采集仍受离线端口和 DNS/connect 防护约束。

| 检查 | 实际命令 / 范围 | 结果与证据 |
| --- | --- | --- |
| 暂存副本全量 | 在 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer/docs/dev-workflow/dev-0/REQ-004/evidence/r5-precommit-tree` 执行 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short --junitxml=../r5-precommit-pytest.xml` | **1365 passed in 27.17s，0 failed / 0 errors / 0 skipped**；[输出](evidence/r5-precommit-pytest.txt)、[JUnit](evidence/r5-precommit-pytest.xml) |
| 最终行尾规则 | 更新导出副本的 `.gitattributes` 与 provenance 后，以同一解释器执行 `-m pytest -q tests/test_vllm_collector.py::test_fixture_hashes_match_provenance --tb=short` | 1 passed；[输出](evidence/r5-precommit-fixtures.txt)。原样本字节保持，provenance 仅行尾正规化 |
| 静态检查 | 同一副本执行 `python -m compileall -q src tests`、`bash -n docs/dev-workflow/dev-0/REQ-004/collect-vllm-evidence.sh` | 均 exit 0；shell 仅语法检查，没有执行采证脚本 |
| 离线依赖 | 原 worktree 执行 `/home/shawn/.local/bin/uv --offline lock --check --python /usr/bin/python3.12 --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels` | exit 0；[输出](evidence/r5-precommit-lock.txt) |
| 更新 README 后的新 wheel / 安装 | 原 worktree 执行 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-004/evidence/r5-precommit-install/verify_uv_install.py --uv /home/shawn/.local/bin/uv` | exit 0，result passed；[报告](evidence/r5-precommit-install/uv-install-results.json)、[执行输出](evidence/r5-precommit-install/run.txt) |
| 暂存空白 / 范围 | `git diff --cached --check`；检查暂存文件清单与最终导出内容 | 通过；[空白检查输出](evidence/r5-precommit-diff-check.txt)、[最终审计](evidence/r5-precommit-audit.json)。忽略的日志、原始采证资料、wheel/缓存没有加入暂存 |

本次新包与安装由 R5 实际执行，复用并逐字节核对 R4 fix2 的显式离线防护脚本（[脚本核对](evidence/r5-precommit-install/script-copy-check.json)）。最新 [wheel](evidence/r5-precommit-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl) SHA-256：**`fe690ec07fa1728a654fd5fa06d09ded66fb522d02e7146728dd0806d7516f28`**。包内 25 份源码/配置及已装包一致、README metadata 对应本轮更新；新 shell 信息命令、三类首模型 TUI 均通过，q 返回 0、termios 恢复、端口全部关闭，network/process attempts 为空，监督器没有遗留进程。先前 wheel 和验证记录继续保留为历史证据。

提交内容为 REQ-004 的设计/交接、实现、相关测试与原始字节 fixture、依赖声明/锁文件及上述收尾。无业务待修订项，沿用 passed 结论并按用户授权提交；实机服务、真实网络/TLS 与 REQ-005/006 的既定限制不变。

## v1.3 第二轮返修复验（历史，2026-11-03）

依据用户“已修复，审查”及 R4 v1.2 交接，独立复核 R5-004-003/004 的修订和相关回归风险。当前比较基点仍为上述 HEAD，审查涵盖未提交交付。相对 v1.2 审查结束时，仅三个业务文件（`collectors/vllm.py`、`data/vllm.py`、`data/vllm_window.py`）、两个测试文件及 R4 交接变化；需求、设计、依赖和其余代码未变。版本快照：[r5-retest2-start.json](evidence/r5-retest2-start.json)，具体业务差异：[r5-retest2-source.diff](evidence/r5-retest2-source.diff)。

主审与两项独立只读复核均确认修复针对根因：HTTPX 的首个实际关闭由独立任务负责，EOF 和上下文退出共用同一任务及截止时间；多引擎延迟直接合计各完整落窗区间的精确 sum/count，最终只转换一次 float。原取消传播、时间预算、懒加载、普通 factory 协议、完整校验、连续性、只读投影及有界窗口行为保持。本次未发现新的明确缺陷，无需再追加测试；R5 未修改业务代码或原测试。

R5 实际运行环境：WSL Ubuntu-24.04 / Ubuntu 24.04.5 LTS x86_64、Python 3.12.3、HTTPX 0.28.1、httpcore 1.0.9；工作目录 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`。

| 验证 | R5 实际命令 | 结果与证据 |
| --- | --- | --- |
| 全量复验，包含四个缺陷复现及 HTTPX、状态、运行期和真实 PTY 回归 | `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-retest2-pytest.xml` | **1365 passed in 24.71s，0 failed / 0 errors / 0 skipped，exit 0**；[输出](evidence/r5-retest2-pytest.txt)、[JUnit](evidence/r5-retest2-pytest.xml) |
| 版本、原测试前缀、用例集合和新 wheel 独立核验 | `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-004/evidence/r5_retest2_audit.py` | exit 0；[报告](evidence/r5-retest2-audit.json)、[输出](evidence/r5-retest2-audit.txt) |
| 空白检查 | Windows 当前 worktree `git diff --check` | exit 0，仅 uv.lock 既有 LF/CRLF 提示，不作为 Windows 产品回归 |

上轮 **1335 项全部保留并通过**，四项失败均转绿，R4 新增 30 项也通过。R5 独立核对两个修改测试文件的旧字节前缀：HTTPX 测试 13850 字节、状态边界测试 13030 字节 SHA-256 与返修起点一致，未改弱旧断言；`test_vllm_window.py` 全文件保持。

最新 [wheel](evidence/r4-fix2-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl) SHA-256：**`138f838d9aaac7cd6e7d60b295ffebaba48b65c3232e0b14bb753972f1cff230`**。R5 独立核实 25 份包内 py/yaml 与当前源码逐字节一致、README metadata 一致，R4 manifest 和构建输入绑定本次快照。隔离 uv 安装、新 shell 裸信息命令及已装 CLI 三类型 TUI 仍明确**引用 R4 执行**的 [fix2 安装报告](evidence/r4-fix2-install/uv-install-results.json)，R5 未重复安装；只读核阅三次退出 0、termios 恢复、端口全关闭、报告 network/process attempts 为空。

本次 R5 使用保留 DNS/connect 防护的离线 pytest 与本地证据，没有尝试连接服务器。关闭修复证明范围为真实 HTTPX 的内存 transport，并未测试真实网络 socket 泄漏数量；生产负载、实机多 engine/隐蔽重启及真实 TLS 握手仍未验证，REQ-005/006 仍不属于本轮。历史失败、前次 R4-VAL-001 偏离及旧 wheel 均保留。

## v1.2 再次代码与测试复查（历史，2026-11-03）

用户在 v1.1 验收后要求复查代码和测试逻辑的错误或遗漏。本次重新核对解析、真实 HTTPX 生命周期、累计计算/窗口、只读 State、服务区、生产接线及测试预期，重点检查替身没有覆盖的真实库行为和数值断言是否能识别伪零；没有只重复原用例或将已知限制扩为新需求。

审查基点仍为 `2b3643096f193fe9c13d2e78e43924bfc64953ab` 的全部未提交交付；本轮起点完整状态和 SHA-256 见 [r5-review2-start.json](evidence/r5-review2-start.json)，与已复验实现相同。发现两个此前漏检的问题：自然 EOF 的响应自动释放被取消打断后不能完成关闭（P2），以及极端次正规延迟在逐 engine 均值提前舍入后全局加权变成零（P3）。另确认一条旧小数值断言的默认绝对容差过宽，已通过新增严格用例补上。

仅在两个既有测试文件末尾追加 **5 项用例**：

| 文件与入口 | 数量 | 结果 |
| --- | ---: | --- |
| [test_vllm_httpx.py](../../../../tests/test_vllm_httpx.py) `test_real_httpx_natural_eof_release_survives_interruption` | 3 | cancel / close / timeout 均失败；R5-004-003 |
| [test_vllm_state_edges.py](../../../../tests/test_vllm_state_edges.py) `test_multi_engine_latency_keeps_a_representable_nonzero_mean_after_weighting` | 1 | 实际 0.0，预期 `math.ulp(0.0)`；R5-004-004 |
| 同文件 `test_tiny_latency_with_huge_count_uses_relative_tolerance_and_stays_nonzero` | 1 | 正值及 `abs=0` 相对容差通过；R5-TST-003 测试补漏 |

R5 实际验证在 WSL Ubuntu-24.04、Python 3.12.3、HTTPX 0.28.1、httpcore 1.0.9 执行；工作目录 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`，下列 `python` 均指 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。pytest 保留 DNS/connect 防护，没有连接服务器或回环地址。

| 范围 | 实际命令 | 结果与证据 |
| --- | --- | --- |
| 真实 HTTPX 内存流 | `python -m pytest -q tests/test_vllm_httpx.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-review2-http.xml` | **15 passed / 3 failed in 0.90s**；[输出](evidence/r5-review2-http.txt)、[JUnit](evidence/r5-review2-http.xml) |
| 窗口、State/Monitor | `python -m pytest -q tests/test_vllm_window.py tests/test_vllm_state.py tests/test_vllm_state_edges.py tests/test_state.py tests/test_state_monitor_edges.py tests/test_monitor.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-review2-state.xml` | **252 passed / 1 failed in 1.33s**；[输出](evidence/r5-review2-state.txt)、[JUnit](evidence/r5-review2-state.xml) |
| 最终全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-review2-pytest.xml` | **1331 passed / 4 failed in 25.39s，0 errors / 0 skipped，exit 1**；[输出](evidence/r5-review2-pytest.txt)、[JUnit](evidence/r5-review2-pytest.xml) |
| 测试容差验证 | `python -c "import pytest; print(0.0 == pytest.approx(1e-92))"` | `True`；[输出](evidence/r5-review2-tolerance.txt) |
| 版本与用例集合审计 | Windows 逐文件 SHA-256、原文件前缀哈希及 JUnit ID 比较；`git diff --check` | [审计报告](evidence/r5-review2-audit.json)：原 1330 项均保留并通过，两个测试原文件字节前缀未变；业务/契约未改。空白检查通过，仅 uv.lock 既有行尾提示 |

还只读检查了本地真实 HTTPX/httpcore 的关闭实现，保存 [源码摘录](evidence/r5-review2-httpx-source.txt)；本地 asyncio 任务在 httpcore `AsyncShieldCancellation` 内仍可被 `Task.cancel()` 打断，保存 [离线验证](evidence/r5-review2-httpcore-shield.txt)。这支撑取消机制判断，不声称执行过真实网络连接泄漏或套接字审计。

解析、固定布局、普通窗口、类型/单位、运行接线及其余测试预期未发现新的可复现问题。HTTPX 内部压缩块的瞬时内存峰值已有明确契约限制，复杂 emoji 的真实终端字宽覆盖有限但无具体验收错误复现，均不作为新增阻碍。真实服务/网络/TLS、生产负载和 REQ-005/006 的既有限制不变。本轮未改源码，不重新构建或安装 wheel；v1.1 的源码/wheel 一致性仍成立，但该 wheel 同样包含本次新发现的实现缺陷。

## v1.1 复验结论与证据（历史，2026-11-03）

收到用户指定的 R4 修复交接后，复核了 v1.1 交接、两个问题对应的代码与测试。相对上次 R5 结束时，只有 `collectors/vllm.py`、`test_vllm_collector_edges.py`、`test_vllm_httpx.py` 和 R4 交接发生变化；需求、设计、依赖及其余实现未变。复验起点的完整 Git 状态和 SHA-256 见 [r5-retest1-start.json](evidence/r5-retest1-start.json)，业务差异见 [r5-retest1-collector.diff](evidence/r5-retest1-collector.diff)。比较基点仍为上述 HEAD，本次包含所有未提交交付。

R5 主审及独立只读复核均确认：忽略分支现在先验证数值词法和约定资源边界，合法独立 series 仍可忽略，业务字段的局部失败与 STOP/bucket 口径未扩大；HTTPX DecodingError 先于通用 HTTPError 分类，非法正文正确归为 `parse/response.invalid`，清理和取消路径未改变。本次无需追加测试，不修改业务代码或原测试。

在 WSL Ubuntu-24.04（Ubuntu 24.04.5 LTS x86_64，Python 3.12.3，HTTPX 0.28.1）实际执行，工作目录为 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`：

| 检查 | R5 实际命令 | 结果与证据 |
| --- | --- | --- |
| 最终全量复验，包含两问题复现、采集/HTTPX、State/Monitor、运行期及真实 PTY 回归 | `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-retest1-pytest.xml` | **1330 passed in 24.44s；0 failed / 0 errors / 0 skipped，exit 0**；[输出](evidence/r5-retest1-pytest.txt)、[JUnit](evidence/r5-retest1-pytest.xml) |
| 版本、测试集合和新 wheel 的独立本地核验 | `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python docs/dev-workflow/dev-0/REQ-004/evidence/r5_retest1_audit.py` | exit 0；[审计报告](evidence/r5-retest1-audit.json)、[输出](evidence/r5-retest1-audit.txt) |
| 改动空白检查 | Windows 当前 worktree `git diff --check` | exit 0，仅 uv.lock 既有 LF/CRLF 提示；不作为 Windows 产品回归 |

JUnit 比较确认上轮 **1309 个用例全部保留且通过**，四项缺陷复现全部转绿；R4 新增 21 项也通过。代码与原断言检查未发现削弱验收预期。重启续办时再次逐文件核对复验快照，未发现变化，因此沿用已完成的全量结果，没有重复运行相同回归。

新交付 [wheel](evidence/r4-fix1-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl) 的 SHA-256 为 **`b20eceedb18a0d6116ad72fa6869eab8adcb7a2fd8aeb722db96c9b734646a7b`**。R5 独立确认 25 份包内 py/yaml 与当前源码逐字节一致、README metadata 一致，R4 最终 manifest 和安装构建输入均对应本次审查快照。新 shell/隔离安装和已装 CLI 的三类型 TUI 仍明确**引用 R4 实际执行**的 [最新安装报告](evidence/r4-fix1-install/uv-install-results.json)，R5 未重复安装；只读核阅三次均退出 0、termios 恢复、端口关闭、报告的 network/process attempts 为空。

本次 R5 测试保留 DNS/connect 防护，仅使用本地资料、字节端口和 HTTPX 内存 transport，未尝试连接服务器。真实目标服务、生产负载、多 engine 实机部署、不可见重启及真实网络/TLS 握手仍未验证；REQ-005 实际方向键导航和 REQ-006 完整双主题仍不属于本轮。旧 R4-VAL-001 偏离和首次失败证据继续保留，不被本次通过覆盖。

## v1.0 产物记录（历史）

仅补充既有测试文件，新增 **25 项参数化用例**；业务实现、依赖、需求、设计及原有测试断言未修改。现有 1284 个用例 ID 全部保留并继续通过。

| 文件 / 新增入口 | 数量 | 验收行为与结果 |
| --- | ---: | --- |
| [test_vllm_collector_edges.py](../../../../tests/test_vllm_collector_edges.py) `test_ignored_series_must_still_be_legal_exposition` | 3 | other-model / bucket / 非 STOP 被过滤行的整体格式校验；均失败，见 R5-004-001 |
| [test_vllm_httpx.py](../../../../tests/test_vllm_httpx.py) `test_real_httpx_invalid_compressed_payload_is_a_response_failure` | 1 | 真实 HTTPX 内存传输中的非法 gzip 载荷归类；失败，见 R5-004-002 |
| [test_vllm_runtime.py](../../../../tests/test_vllm_runtime.py) `test_wrong_reported_identity_stops_reads_breaks_baseline_and_recovers` | 3 | 三类型身份变化停止后续读取、其他模型刷新、故障保值/gap、恢复重建基线、日志限频及恢复后立即再记、端口释放；通过 |
| [test_vllm_state_edges.py](../../../../tests/test_vllm_state_edges.py) 新增三个测试入口 | 6 | 60 秒完整区间边界、只读过期投影、pooling 全失败/局部失败恢复的独立窗口及历史；通过 |
| [test_vllm_view.py](../../../../tests/test_vllm_view.py) 新增三个测试入口 | 12 | gap 分箱峰值不影响缩放、60 秒闭区间与相邻过期/未来点、37/49 行及 30 模型末项选择的固定半页/详情槽；通过 |

本交接与 [r5_verify_artifacts.py](evidence/r5_verify_artifacts.py) 的本地证据核验报告一并保存；`evidence/` 仍受 Git ignore，交接时须保留或另行携带实际文件。

## v1.0 验证证据（历史）

### R5 实际执行

环境：WSL Ubuntu-24.04，Ubuntu 24.04.5 LTS x86_64，Python 3.12.3；HTTPX 0.28.1、httpcore 1.0.9、anyio 4.15.1、PyYAML 6.0.3、pytest 8.4.2。所有 pytest 均在下列工作目录运行，保留 `tests/conftest.py` 的 DNS/连接防护；HTTP 测试只用原始字节端口或 HTTPX MockTransport/内存流，没有连接服务器或回环地址。

```bash
cd /mnt/d/Documents/codex_worktree/dev0-req004/joi-observer
# 以下命令中的 python 均指：
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python
```

| 范围 | 实际命令（以上述解释器代替 python） | 结果与证据 |
| --- | --- | --- |
| 审查起始全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-pytest-baseline.xml` | **1284 passed in 24.29s**；[输出](evidence/r5-pytest-baseline.txt)、[JUnit](evidence/r5-pytest-baseline.xml) |
| 采集及真实 HTTPX | `python -m pytest -q tests/test_vllm_collector.py tests/test_vllm_collector_edges.py tests/test_vllm_engine_samples.py tests/test_vllm_httpx.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-collector-tests.xml` | **163 passed / 4 failed in 3.11s**；[输出](evidence/r5-collector-tests.txt)、[JUnit](evidence/r5-collector-tests.xml) |
| 状态/窗口及公共回归 | `python -m pytest -q tests/test_vllm_window.py tests/test_vllm_state.py tests/test_vllm_state_edges.py tests/test_state.py tests/test_state_monitor_edges.py tests/test_monitor.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-state.xml` | **251 passed in 1.44s**；[输出](evidence/r5-state.txt)、[JUnit](evidence/r5-state.xml) |
| 视图及真实终端 | `python -m pytest -q tests/test_vllm_view.py tests/test_vllm_pty.py tests/test_tui.py tests/test_terminal_pty.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-view.xml` | **144 passed in 5.91s**；[输出](evidence/r5-view.txt)、[JUnit](evidence/r5-view.xml) |
| 身份/恢复运行期接合 | `python -m pytest -q tests/test_vllm_runtime.py --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-runtime.xml` | **8 passed in 0.80s**；[输出](evidence/r5-runtime.txt)、[JUnit](evidence/r5-runtime.xml) |
| 补例后最终全量 | `python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r5-pytest-final.xml` | **1305 passed / 4 failed in 25.24s，0 errors / 0 skipped，退出码 1**；[完整输出](evidence/r5-pytest-final.txt)、[JUnit](evidence/r5-pytest-final.xml) |
| 本地源码/wheel/样本审计 | `python docs/dev-workflow/dev-0/REQ-004/evidence/r5_verify_artifacts.py` | exit 0；[报告](evidence/r5-artifact-audit.json)、[输出](evidence/r5-artifact-audit.txt) |
| 离线锁文件检查 | `/home/shawn/.local/bin/uv --offline lock --check --python /usr/bin/python3.12 --no-python-downloads --no-index --find-links .pytest_cache/offline_wheels` | exit 0，15 packages；[输出](evidence/r5-lock-check.txt) |
| 改动空白检查 | Windows 当前 worktree `git diff --check` | exit 0，仅 uv.lock 既有 LF/CRLF 提示；不是 Windows 产品回归 |

补例过程中，运行期测试初稿将日志码误写为未定义的 `model.mismatch`，产生 3 项失败；依据已有身份未找到契约改为 `object.not_found` 后 8 项通过。该测试编写错误不记为产品缺陷，初稿证据保留为 [r5-runtime-draft.txt](evidence/r5-runtime-draft.txt)、[JUnit](evidence/r5-runtime-draft.xml)。最终两个产品缺陷的预期未更改、未 skip/xfail。

源码审计独立核实了 25 份包内 py/yaml 与当前 wheel 字节一致、README metadata 一致、依赖声明及 R4 安装输入哈希一致、12 份 fixture 的原始来源 SHA-256/摘录行一致。wheel SHA-256 为 `0c62c9f3a6b40737b8aaf57f510d0c95ce7aeb9173fa9af45e306ab4a6ab12bc`。JUnit 比较确认 1284 个原用例均保留且通过；R5 只修改上述五个测试文件。

### 验收覆盖

| 依据 | 本轮核对结果 |
| --- | --- |
| AC-401、408、412 | 三类配置身份、顺序、独立端口、仅约定 origin/路径、同名不合并、未知上限不造值与生产组合通过；新增身份故障全链路通过 |
| AC-402～404、410、411 | 精确计数、实际时间差、逐 engine 连续性、独立加权延迟、首次/零/重置、60 秒完整区间、有限数值与只读过期通过 |
| AC-405、409 | Chat/Pooling 观测分型、KV engine 平均、适用性、局部失败保值及不混合 Total 通过；首次整体响应有效性问题 R5-004-001 已在 v1.1 复验关闭 |
| AC-406、407 | 独立历史、gap、恢复、只读显示、单模型隔离及日志限频通过；首次非法响应漏报/错误归类问题 R5-004-001/002 已在 v1.1 复验关闭 |
| 固定布局与终端接合 | 三类型正常/STALE/恢复、颜色、零/未知/N/A、18 帧既有 ncurses 检查、q/信号/termios、奇数半页和裁切通过 |
| 共享模块回归 | 硬件/Docker 结果子类迁移、普通 State/Monitor、配置、日志和退出流程的原用例继续通过 |

### 引用 R4 结果与未验证项

- 隔离 uv 安装、新 shell/异目录裸信息命令及已装 CLI 的三类型 PTY **引用 R4 实际执行**的 [uv-install-results.json](evidence/r4-install/uv-install-results.json)，R5 未重新执行安装；R5 独立进行了上述产物和源码一致性核对，并只读复核三次退出为 0、termios 恢复、端口全部关闭、记录的 network/process attempts 为空。
- R4 首次安装脚本的离线 hook 未加载，发生 `offline.invalid` 请求尝试；已核阅 [handoff-r4.md](handoff-r4.md) 的 R4-VAL-001 及保留证据。最终成功不覆盖这次偏离；R5 不把 R4 过程描述为全程未尝试网络，也不声称有底层 syscall 审计。
- 真实目标服务、生产负载、实机多 engine/隐蔽重启、真实网络/TLS 握手未验证；遵守禁止连接服务器约束。这些既定限制不通过离线验证扩大为实机保证。
- REQ-005 实际方向键导航和 REQ-006 完整双主题不属于本轮；本轮以注入 ViewSelection 验证模型详情及历史。没有因这些明确留后项新增缺陷。

## 本轮决策

当前结论为 **passed**。REQ-004 / AC-401～412 在已冻结的离线验收范围内通过；第二轮遗漏 R5-004-003/004 已按根因修复并完成独立复验，全部 1365 项测试通过，当前无未关闭的验收阻碍。最新源码、wheel 及安装证据对应同一交付版本。

v1.2 曾因补例暴露原测试漏检而改为 `needs_fix`，其失败与判断保留作历史记录；本次未改变原预期来取得通过。R5-004-001/002、R5-TST-003 继续保持关闭，接收方改为 R0。R5 未修改业务或设计，结论不扩展到既定的真实服务未验证项或 REQ-005/006。

## R4 修订汇总

以下保留首次发现时的行为与代码行号；每项末尾的 R4 回复和 R5 复验为当前状态。

### R5-004-001 [P2] 被过滤的指标行绕过数值语法检查，非法响应被发布为新鲜成功

- 关联需求、验收或任务：AC-407、AC-412、T-001；[vllm.md](../../../design/vllm.md) §6 明确仅忽略合法独立 series，整体 exposition 非法应全对象失败。
- 涉及位置与影响：[collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py) 456–457 行 other-model 分支及 471–472 行 bucket/non-STOP 分支在数值 token 校验前 `continue`。响应含非法数字文本仍产生 `failure=None` 与完整 observation，导致 Monitor 不记录错误、State 不留 gap/TUI 不标 STALE，并继续使用该次采样作为基线。
- 预期与实际行为：合法 fixture 后追加下列任一行，预期 `observation=None` 且 `parse/response.invalid`；实际三种输入均返回健康 observation。只要求整体格式合法，不要求把忽略项计入业务数值，也不改变已有适用字段的局部失败规则。

```text
# Chat fixture
vllm:num_requests_running{engine="0",model_name="unrelated"} PRIVATE
vllm:request_queue_time_seconds_bucket{engine="0",model_name="qwen3.8-flash-next",le="0.123456"} PRIVATE
# Embedding fixture
vllm:request_success_total{engine="0",model_name="qwen3-embedding-4b",finished_reason="other"} PRIVATE
```

- 复现命令：`python -m pytest -q tests/test_vllm_collector_edges.py -k ignored_series --tb=short`；3 failed。完整失败来自 [r5-pytest-final.txt](evidence/r5-pytest-final.txt)，新增用例在测试文件 169 行。
- 处理请求：在过滤 series 前保证 exposition 数值 token 的基础合法性与约定资源上限；继续正确忽略合法 other-model/bucket/non-STOP 行，不累计 bucket、不扩大 STOP 口径；保留适用业务字段局部失败的原测试。
- R4 回复与 R5 复验：**已关闭（2026-11-03）**。R4 v1.1 增加 `_check_ignored_value`（当前 417 行），在 unknown/other-model/bucket/non-STOP 分支（477/482/498 行）过滤前校验词法及资源上限。R5 静态确认合法忽略值和适用字段局部失败语义保留；三项原失败用例、R4 新增 20 项忽略值边界用例及原 parser/真实链路回归均在 [1330 项全量复验](evidence/r5-retest1-pytest.xml) 中通过，无剩余处理请求。

### R5-004-002 [P3] 损坏的 gzip 正文被错误归类为网络不可用

- 关联需求、验收或任务：AC-407、T-002；[vllm.md](../../../design/vllm.md) §9 规定非法载荷为 `parse/response.invalid`，网络/TLS/依赖不可用才为 `source.unavailable`。
- 涉及位置与影响：[collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py) 229–231 行将 HTTPX `DecodingError` 随所有 `HTTPError` 转成 `OSError`，Collector 据此返回 `unavailable/source.unavailable`。仍会正确停止后续请求并标 STALE，但错误种类及 ERROR 日志归类与故障原因不符。
- 预期与实际行为：真实 HTTPX MockTransport 对首个 `/version` 返回 200、`Content-Encoding: gzip`，正文为 `b"PRIVATE invalid gzip body"`；预期 `parse/response.invalid`，实际 `unavailable/source.unavailable`。复现不涉及网络或证书握手。
- 复现命令：`python -m pytest -q tests/test_vllm_httpx.py -k invalid_compressed_payload --tb=short`；1 failed。证据同 [r5-pytest-final.txt](evidence/r5-pytest-final.txt)，新增用例在测试文件 266 行。
- 处理请求：区分内容解码/非法载荷与运输错误并按既定失败分类归一；保留懒加载、替身不导入 HTTPX、异常正文不外泄、单次流请求、取消及清理预算等原契约。
- R4 回复与 R5 复验：**已关闭（2026-11-03）**。R4 v1.1 在当前 229–234 行先识别 DecodingError 并转入既有 `_InvalidResponse` 分类通路。R5 确认 finally 清理、取消传播、懒加载及异常正文隔离保持；原非法 gzip 用例、R4 新增第二路径 gzip 尾部校验损坏用例与全部 HTTPX gzip/超限/TLS/取消回归在 [1330 项全量复验](evidence/r5-retest1-pytest.xml) 中通过，无剩余处理请求。

### R5-004-003 [P2] HTTPX 自然 EOF 自动释放被打断，finally 无法完成底层流关闭

- 关联需求、验收或任务：AC-407/412 的失败隔离、T-002/T-007、[vllm.md](../../../design/vllm.md) §9 及 `HttpPort` 的“超时、取消、close 250ms 内关闭响应流并清理在途任务”。
- 涉及位置：[collectors/vllm.py](../../../../src/joi_observer/collectors/vllm.py) 208 行 `response.aiter_bytes`、239–244 行 finally。HTTPX `Response.aiter_raw` 在正常 EOF 自行调用 `aclose()`；该方法先置 `is_closed=True` 再等待底层流的异步关闭。此时本端口超时、外部取消或 `port.close()` 取消 get，底层关闭可被中断；finally 再退出上下文时因 HTTPX 已标记 closed 而跳过真正释放。
- 预期与实际：真实 HTTPX MockTransport 返回一个已完整读取的内存流，其合作关闭只需 30ms；在其 `aclose()` 已开始时施加 cancel / close / timeout，三种情况都应在 250ms 清理预算内完成底层关闭并传播相应异常。实际异常按预期传播，但 `stream.closed=False`。不是不合作或超出预算的流。
- 影响：端口契约要求的释放没有完成，反复超时/关闭会有资源残留风险；本轮只证明内存 transport 的释放未完成，未建立真实网络连接来断言实际 socket 泄漏数量。
- 测试遗漏：原 HTTPX 测试覆盖读取挂起和显式上下文释放时取消，未覆盖字节迭代器的自然 EOF 自动释放；普通 MemoryStream 的 `aclose()` 无异步等待，不能暴露这段竞态。
- 复现：`python -m pytest -q tests/test_vllm_httpx.py -k natural_eof_release --tb=short`，3 failed。新增测试始于 327 行；[最终失败输出](evidence/r5-review2-pytest.txt)与[本地依赖源码](evidence/r5-review2-httpx-source.txt)互相印证。另验证 httpcore 的 AnyIO shield 并不阻止本程序直接 `asyncio.Task.cancel()`，见 [输出](evidence/r5-review2-httpcore-shield.txt)。
- 处理请求：确保 EOF 自动释放也处于有界且能完成的清理路径，不能仅凭 HTTPX 的 `is_closed` 标志认为底层资源已释放；保留取消传播、250ms 单端口和 1s 总退出预算、单次请求及原所有生命周期断言。
- R4 回复与 R5 复验：**已关闭（2026-11-03）**。R4 v1.2 在当前 103 行增加 `_protect_httpx_response_close`，240 行在迭代前接入；只包装真实 HTTPX Response，EOF 与 context exit 共用首个实际关闭任务和 0.2 秒截止时间，取消等待者后仍完成合作释放再传播取消。R5 独立复核确认不重启关闭/预算、不改变普通 factory 或懒加载。原三项复现及 R4 新增重复取消、Collector 超时、超预算释放、关闭异常/无遗留任务的 6 项测试均在 [1365 项全量复验](evidence/r5-retest2-pytest.xml) 中通过，无剩余处理请求。

### R5-004-004 [P3] 多引擎均值提前舍入使可表示的非零全局延迟变成零

- 关联需求、验收或任务：AC-403/404/411、T-004/T-005、[vllm.md](../../../design/vllm.md) §7 的窗口总时长/自身总观测数及稳定求值契约。
- 涉及位置：[data/vllm.py](../../../../src/joi_observer/data/vllm.py) 211–219 行先取得每个 engine 已舍入成 float 的均值，再以 `Fraction(mean) * observations` 汇总；这无法恢复已经丢失的原始时长。
- 预期与实际：两个 engine 都从零开始，各新增 `math.ulp(0.0)`（约 `5e-324`）秒，观测数分别 2 和 1；三个观测共两个最小正浮点步长，整体结果 `(tiny + tiny) / 3` 可舍入为 `tiny`。实际第一 engine 的均值先舍入为 0，最终全局值也变成 0.0。
- 影响：仅针对极端次正规浮点值的正确性缺陷，不夸大为常规 TTFT/排队时延错误；普通取值和大值避免溢出的既有测试仍通过。
- 复现：`python -m pytest -q tests/test_vllm_state_edges.py -k multi_engine_latency_keeps --tb=short`，1 failed。新增测试 249 行直接通过公开 accumulator 接口提交合法观测，并用独立算术预期精确排除零；[失败输出](evidence/r5-review2-state.txt)。
- 处理请求：在完整落窗区间中按原始时长与精确观测数完成全局加权，最终再转换展示 float；继续保持按引擎连续性、窗口边界、无观测未知及避免中间溢出的既有行为。
- R4 回复与 R5 复验：**已关闭（2026-11-03）**。R4 v1.2 提取 `vllm_window.py:140` 的 `_latency_totals`，保留原完整校验和落窗规则，`vllm.py:203` 直接汇总各 engine 精确时长/观测数后最终舍入一次。R5 独立确认只读、有界及原子路径保持；原非零复现、严格容差补例及 R4 新增六延迟组/顺序/跨区间/过期/大 sum-count 共 24 项均在 [1365 项全量复验](evidence/r5-retest2-pytest.xml) 中通过，无剩余处理请求。

### R5-TST-003 [P3，测试遗漏已补齐] tiny latency 的默认绝对容差允许伪零

- 位置：[test_vllm_state_edges.py](../../../../tests/test_vllm_state_edges.py) 161 行，`test_large_representable_rate_and_tiny_latency_with_huge_count_are_supported` 使用 `pytest.approx(1e-92)`。
- 预期与实际：该例意图验证很小但仍非零的可表示均值；pytest 默认 `abs=1e-12` 会使实际值 0.0 也通过。[离线检查](evidence/r5-review2-tolerance.txt)输出 `True`，说明旧断言不能证明非零性。这不是在断言当前 `weighted_latency` 对该输入计算错误。
- R5 处理：保留原测试，仅在 262 行追加 `test_tiny_latency_with_huge_count_uses_relative_tolerance_and_stays_nonzero`，使用 `mean > 0` 和 `pytest.approx(..., rel=1e-12, abs=0.0)`。新增例通过，测试缺口已补齐；无需 R4 改业务来处理本条，R5-004-004 的独立多引擎缺陷仍待修复。

## 下一步

接收角色 **R0 / 用户**：REQ-004 本轮离线验收通过，请登记验收结果并安排后续需求。四项实现问题及测试补漏均已关闭，无等待 R4 修订或用户澄清的事项。保留本交接、最新 wheel 和 `evidence/` 实际文件；受 Git ignore 的材料不会随普通 diff 传递。下一阶段继续由用户人工推进，本轮未自动联系其他角色聊天。
