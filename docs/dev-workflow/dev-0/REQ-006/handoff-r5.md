# dev-0 / REQ-006 R5 验收交接

- stage：R5
- result：passed
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006`
- 需求依据：[requirements.md](../requirements.md) v1.24，REQ-006 / AC-601～616，及页眉变更关联的 REQ-001 / AC-101、AGENTS.md 的离线、WSL、修改边界与本轮不构建安装包约定。
- 验收依据：[plan.md](plan.md) v1.0 及用户页眉/60FPS/分段/粗体/留白/track补充、[handoff-r4.md](handoff-r4.md) v1.10、application-shell v1.20、theme v1.12、vllm v1.12，以及当前 hardware/navigation/configuration/docker 与 REQ-004 view-contract。旧版本依据和结果保留于各历史节。
- 审查对象：分支 `codex/dev0-req006`；比较基准 `0a42646b43df67832d6cfe9088e9eaf8c9c8f8af`；2026-11-04 当前工作区的全部 REQ-006 已跟踪及未跟踪交付，不限于已提交内容。输入时 158 份文件的哈希、Git 状态及差异分别见 [输入快照](evidence/r5-input-snapshot.json)、[输入差异](evidence/r5-input.diff)。输入源码与测试哈希均与 R4 当前精度版本 audit 一致。
- next_role：R0
- 修订：v1.5，2026-11-05；用户最新明确要求重建安装包，已完成当前验收源码构建、同版本覆盖安装及完整服务器离线包验证。此前1948项源码验收结论保持；[v1.4归档](evidence/r5-handoff-v1.4.md)保留当时不构建的范围。更早记录分别保存于 [v1.0](evidence/r5-handoff-v1.0.md)、[v1.1](evidence/r5-handoff-v1.1.md)、[v1.2](evidence/r5-handoff-v1.2.md)、[v1.3](evidence/r5-handoff-v1.3.md)。

## 当前安装包重建交付（v1.5）

用户最新指令“你需要重建安装包”覆盖此前本轮不构建的限制，见[请求与构建输入](evidence/r5-track-build-input.json)。已按R5 v1.4通过的源码完成本地离线构建，业务源码/版本号/依赖声明/测试未改，仅将README中已过时的不构建说明同步为本次交付。未连接服务器，也未修改既有GUI启动或回放入口。

| 交付与实际验证 | 结果/证据 |
| --- | --- |
| 当前wheel | [joi_observer-0.1.0.dev0-py3-none-any.whl](evidence/r5-track-build/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl)，SHA-256 `198ca82b7cd74e727bf9281799f388cb179e828a9807b7f79697554231392d06`；全部Python/YAML与通过1948项的源码一致，安装metadata中的README与当前文档一致 |
| 完整服务器离线包 | [joi-observer-server-test-20261105-track.tar.gz](evidence/server-test/joi-observer-server-test-20261105-track.tar.gz)，1,501,416字节，含应用及8个运行依赖wheel、配置示例、升级说明、manifest和SHA256SUMS；目标Ubuntu 24.04 amd64 / CPython 3.12 / 已有uv |
| 同版本真实更新 | 先安装并逐文件核对旧三处留白wheel，再用`--force --reinstall`安装新包；新旧都为0.1.0.dev0，新安装源码逐字节对应当前版本，已证明同版本替换；[完整安装结果](evidence/r5-track-build/uv-install-results.json)、[摘要](evidence/r5-track-build-summary.json) |
| 已安装真实CLI/PTY | 通过新shell裸命令、三类型/双主题/缩放/q、bold、track精确色与6色对、7私有色槽16..22恢复及termios/端口清理；253帧，119间隔中位16.658ms，采样仍约1秒。网络与外部进程尝试为空；这是本地PTY测量，不推导GUI可见FPS |
| 离线包独立安装 | 从tar实际解压，校验12个文件哈希，在全新工具目录与空缓存中仅使用包内wheel安装；安装源码与R5审查一致，已安装60FPS、track=(62,74,91)正确；[验证结果](evidence/r5-track-bundle-verification.json) |

安装验证使用独立的[脚本副本](evidence/r5-track-build/verify_uv_install.py)，补齐track角色和7色槽观察；没有改旧R4安装证据。继承原网络防护、源码一致性、60Hz与采样检查，另外覆盖同版本更新。其CLI场景不采集硬件，已安装硬件字形通过wheel全源码对应与已执行的源码硬件真实PTY证据关联，不声称此次安装场景自行产生了硬件采样。

归档SHA-256：`24dfb21d28664d91bfd85af59278f71997facb4ffa6433badd2dd21faf995a27`，另附[校验文件](evidence/server-test/joi-observer-server-test-20261105-track.tar.gz.sha256)。解压后按包内TESTING.txt更新，保留用户现有`server-test.yaml`；不覆盖服务器配置。原有旧包与GUI入口仍保存为历史，不自动指向新包。

实际构建/升级验证命令（本地WSL，项目根目录）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r5-track-build/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --previous-wheel /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl
```

## 页眉修复与显示调整复验（v1.4，源码通过记录）

**本轮源码复验通过，未发现新的验收缺陷。** 比较基线为R5 v1.3 / [审计](evidence/r5-ui60-audit.json)，受审对象为R4 v1.10当前未提交工作区；HEAD仍为`0a42646b43df67832d6cfe9088e9eaf8c9c8f8af`。本次6份生产变化为cli.py、app.py、layout.py、theme.py、vllm.py、widgets.py；输入文件/历史产物哈希见[本轮快照](evidence/r5-track-input.json)，完整生产差异见[源差异](evidence/r5-track-source.diff)。源码与R4当前track审计对应。

用户明确“已修复并改了一些其它的，继续复验，预览效果已确认”，已保存[确认记录](evidence/r5-track-preview-confirmation.json)，当前静态预览manifest的源码哈希与受审源码一致。本轮遵循AGENTS/计划中的“不生成或重建离线安装包、不更新已有GUI启动/回放入口”；这些历史产物保持原字节，不被当作当前track安装验证。

| 本次 R5 实际验证 | 结果 | 证据 |
| --- | --- | --- |
| **WSL完整回归，含R5补测** | **1948 passed / 0 failed / 0 errors / 0 skipped，31.07s**；包括原003三样本、60Hz与001/002、真实硬件/模型/导航/主题PTY及生命周期 | [输出](evidence/r5-track-final-pytest.txt)、[JUnit](evidence/r5-track-final-pytest.xml) |
| CLI真实文本/生产组装定向 | 47 passed；新增同Runtime只读一次、新Runtime重新读取，以及部分read失败切候选不混入字段两项 | [输出](evidence/r5-track-host-pytest.txt)、[JUnit](evidence/r5-track-host-pytest.xml) |
| 主题终端定向 | 53 passed；现有精确模式测试补充track不含A_BOLD/A_DIM断言，原RGB/属性/恢复断言保留 | [输出](evidence/r5-track-theme-pytest.txt)、[JUnit](evidence/r5-track-theme-pytest.xml) |
| 预览确认 | 用户已确认预览效果；记录不扩大为新MobaXterm像素、字体或可见FPS测量 | [用户确认](evidence/r5-track-preview-confirmation.json)、[当前预览manifest](evidence/r4-track-gray-preview/manifest.json) |
| 差异与范围核对 | R5仅补2项CLI测试和1条主题断言、交接/证据；业务/设计不改。现存wheel、两GUI入口及旧Frame哈希保持，未构建/安装/更新回放。Windows Git diff --check通过 | [审计](evidence/r5-track-audit.json)、[差异检查](evidence/r5-track-diff-check.txt) |

实际执行环境为本地WSL Ubuntu-24.04 / x86_64 / Python 3.12.3，保留测试DNS/connect禁用；没有连接任何服务器。关键命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-track-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_cli.py --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-track-host-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_theme_terminal.py --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-track-theme-pytest.xml
```

修复及附带变化的审查结论：

- **发行版回退**：私有reader只解析文件实际字段，正确保留显式Linux，候选优先、不合并、读取失败和编码失败行为符合v1.24。原3项R5样本、预期和真实生产Runtime路径保持；改动只是将文件路径替身从旧stdlib候选改到当前reader，未模拟预定解析结果。R5-006-003关闭。
- **track与分段**：填充/未填充统一▌，沿用原段数/宽度和公共percentage_bar比例。仅未填充段用独立track，原muted/关联填充不变。Palette末尾默认值和原色对1～5兼容；第7私有色槽/第6非零色对及阈值、固定256索引239、基础色近似、单色和失败恢复均有覆盖。
- **数字加粗**：TextCell.bold独立于颜色role，默认False兼容旧构造。仅六个右侧真实数字槽加粗，零/科学记数/STALE旧数与占位区分；单色和既有Moonlight基础属性组合正确。实际PTY观察字形、RGB/背景和bold，而非仅检查Frame元数据。
- **三处留白与历史图**：右侧+1/+5/+11留空，模型/统计/历史标题移至约定行，左栏与服务半页预算保持。最小16行服务区保留1行图，轴仍height−2；柱高按新实际高度计算。现有三类型、缩放、零/缺口/峰值及真实PTY断言适配符合新契约。
- **相关回归**：采样、状态、60秒时间分箱/尺度、60Hz调度均未改变；001/002双向公平性回归保持通过。未因新轨道或粗体改变采样、原始指标、模型匹配或导航。

剩余边界：当前通过结论针对本次授权的源码、离线/PTY及已确认预览。旧wheel/已安装CLI/旧GUI回放仍为三处留白版本，未包含最后的统一半块与深灰track；其SHA-256 `2b0da25252bd051a5c1bb950818406a8e1a7dff2defc21c31b6b11963b3128ff` 仅作历史识别。本次不声称完成最新源码的已安装包验证或具体终端最终RGB/可见FPS测量，这些不构成本轮已明确排除的交付工作。

## 显示调整与60FPS复验（v1.3 历史）

用户再次明确调用 R5，要求审查最新改动。本轮以最近通过的 R5 v1.2 / [审计](evidence/r5-retest2-audit.json) 为比较基线，旧通过 wheel SHA-256 为 `159e48ddd1365fc0cb54408518a0922fd8eb46c41d013cee4a2878f01d322fb8`，位于 `evidence/r4-install-before-ui-polish-20261105/wheels/`。当前仍为 `codex/dev0-req006`、HEAD `0a42646b43df67832d6cfe9088e9eaf8c9c8f8af` 的未提交工作区；不能仅以 HEAD 判断交付版本。160份输入文件哈希见[本轮快照](evidence/r5-ui60-input.json)，7份生产文件的逐行差异见[源差异](evidence/r5-ui60-source.diff)。

审查覆盖两轮未再经 R5 验收的变化：固定设备标签与真实 os-release 发行版本；Storage路径/空态正文色；随包容器示例；低色Moonlight亮紫近似与主题变化物理重绘；60FPS调度及测试重算。当前源码与 R4 60FPS 审计匹配。用户已答复“尚未检查；先做代码与离线复验”，本轮据此完成代码与离线范围，新MobaXterm观感单独保留待验证，见[范围确认](evidence/r5-ui60-user-scope.json)。

**结论：needs_fix。** 发现一项 P2：真实 `platform.freedesktop_os_release()` 会为缺失的 `PRETTY_NAME` / `NAME` 填入 `Linux`，当前页眉代码据此错误跳过需求要求的回退，见 R5-006-003。其余本轮变化未发现确定验收缺陷；原001/002在60Hz下保持通过。

| 本次 R5 实际验证 | 结果 | 证据 |
| --- | --- | --- |
| **WSL 完整回归，含本次补测** | **1917 passed / 3 failed / 0 errors / 0 skipped，33.35s**；3项失败均为同一个发行版本回退缺陷 | [输出](evidence/r5-ui60-final-pytest.txt)、[JUnit](evidence/r5-ui60-final-pytest.xml) |
| 真实os-release文本与生产装配定向 | 28 passed / 3 failed；保留真实标准库解析器，覆盖缺PRETTY_NAME、空文件、空PRETTY_NAME且缺NAME | [输出](evidence/r5-ui60-host-fallback.txt)、[JUnit](evidence/r5-ui60-host-fallback.xml) |
| 主题重绘/异常恢复定向 | 43 passed，包含本次新增的resize中断重绘重试用例 | [输出](evidence/r5-ui60-theme-retry.txt)、[JUnit](evidence/r5-ui60-theme-retry.xml) |
| 当前wheel独立隔离安装及真实CLI/PTY | passed；已安装FRAME_RATE=60、FRAME_INTERVAL=1/60，源码Python/YAML/README一致；253帧、119个普通间隔中位16.683ms，q响应135.14ms；颜色/termios与进程清理通过，网络/外部进程尝试为空 | [完整结果](evidence/r5-ui60-install/uv-install-results.json)、[摘要](evidence/r5-ui60-install-summary.json) |
| 采样与历史独立性 | 已安装CLI三模型各5轮，轮间隔中位约1.00013秒，范围约0.98722～1.01320秒；采集、Monitor、State/窗口、历史分箱/尺度源码与旧通过版本字节一致 | 同一[安装摘要](evidence/r5-ui60-install-summary.json)、[审查审计](evidence/r5-ui60-audit.json) |
| 修改边界与差异 | R5仅在两份已有测试文件新增2个函数（参数化后4项）及交接/证据；原测试内容保留、业务/设计不改；Windows Git diff --check通过 | [审计](evidence/r5-ui60-audit.json)、[差异检查](evidence/r5-ui60-diff-check.txt) |

新增测试位置：

- [test_cli.py](../../../../tests/test_cli.py)：`test_real_runtime_os_release_text_fallback_uses_distribution_fields`。用临时os-release文本及真实stdlib解析，通过真实 `ApplicationRuntime.prepare_log()` 取得生产 `ObserverApp.host`；不直接模拟解析后的字典。三个失败预期完整保留。
- [test_theme_terminal.py](../../../../tests/test_theme_terminal.py)：`test_resize_aborted_theme_switch_keeps_physical_redraw_pending`。已显示Hologram后切Moonlight，addstr因resize提前返回，恢复后同目标主题仍须clearok，refresh成功后下一同主题帧才恢复差分；退出清理继续成立。

合理性与回归核对：

- **60Hz**：相对旧通过版本，ObserverApp调度执行AST未改变，FrameSchedule执行变化仅FRAME_RATE 30→60；截止点、Fraction大时刻、双向公平性、resize及采样隔离保留。现有用例按新节拍重算，周期输入仍覆盖超过1秒、混合组墙钟跨度保持，原断言语义未削弱。
- **主题**：仅基础色Moonlight辅色加A_BOLD，精确/固定256色保持；应用与两GUI入口不设置TERM。现有新PTY测试按帧检查重新发送实际字形、颜色指令顺序、后续角色不继承bold及同主题差分，能够补足旧“只查curses内存色表”的盲点。
- **页眉/Storage/示例**：固定设备标签、斜线分隔与时钟右缘、Storage左侧角色、可加载容器示例均按新契约落实。发现的缺陷局限于发行版本回退，不影响正常含PRETTY_NAME的os-release路径；不据此猜测服务器现场文件情况。
- **非阻塞文档建议**：application-shell“刷新提高不使1秒采样变成30次新观测”仍有旧数字，可改为60或省略次数；不影响采样实现，不作为验收阻碍。

全部实际执行仍在本地 WSL Ubuntu-24.04 / Python 3.12.3，保留DNS/connect禁用与uv离线安装。关键命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-ui60-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_cli.py --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-ui60-host-fallback.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r5-ui60-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --wheel /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl
```

当前受审wheel SHA-256为 `bd9154f716e8fa2f9bf461a9bd9b01ef4b84e29af2ef1aabf1c4d52aa3f19843`。上述为R5本次实际结果；R4的1916项通过仅作输入交付记录。新字体/颜色/刷新观感尚未人工复验，PTY数据不等于MobaXterm可见60FPS；没有连接任何服务器。

## 第二轮修复复验（v1.2 历史，2026-11-05）

**修复方法合理，本轮验收通过；在已审查和实际验证的范围内未发现新回归。** 用户明确要求继续复验合理性与回归风险。本次以前一轮 [r5-retest-audit.json](evidence/r5-retest-audit.json) 为比较基线，审查 R4 v1.4 的当前工作区及未提交交付；生产源码仍仅 `app.py` 改变。当前源码与测试均匹配 R4 fix2 审计，见[本轮输入快照](evidence/r5-retest2-input.json)、[修复差异](evidence/r5-retest2-source.diff)。

修复采用每轮重置的 `drew_frame`，成功 render 后才置 True，正确区分以下两种情况：

1. **本轮未绘制，读键前才到期**：保留 deadline，只让出事件循环，不调用 advance。由于时钟单调且 deadline 未变，下一轮必然到期并绘制；这一分支不会连续跳过画面。
2. **本轮已绘制，读键前再次到期**：沿用 R5-006-001 的修复，以同一个 `read_now` 推进到未来原始节拍并得到正 timeout，然后读取按键。不会回到连续绘图而不服务输入的旧行为。

因此，在终端操作可返回、时钟满足既定单调契约的条件下，未绘制到期分支最多多经过一轮；完成绘制后仍有读键机会。FrameSchedule、`start+n/30` 相位、采样调度、每帧一次快照/选择及尺度推进保持。resize 的即时帧也算一次已完成绘制；新让出点仍在原 try/finally 内，取消、绘制/读键异常、终端恢复与同实例再次 run 的边界未改变。

| 本次 R5 实际验证 | 结果 | 证据 |
| --- | --- | --- |
| **WSL 完整回归** | **1908 passed / 0 failed / 0 errors / 0 skipped，30.26s**；含两个 R5 原回归、R4 新增 12 相位/快慢绘制/缩放组合，以及取消/异常恢复、导航、历史与真实 PTY | [输出](evidence/r5-retest2-final-pytest.txt)、[JUnit](evidence/r5-retest2-final-pytest.xml) |
| 当前 wheel 独立隔离安装/真实 CLI/PTY | passed；源码 Python/YAML/README 一致，新 shell 异目录命令、双主题/三类型/缩放/q 及终端恢复通过；130 帧，普通间隔中位33.226ms、q响应82.50ms；网络/外部进程尝试为空，任务自有进程均清理 | [完整结果](evidence/r5-retest2-install/uv-install-results.json)、[摘要](evidence/r5-retest2-install-summary.json) |
| 原测试与修改边界 | 移除 R4 本轮新增的一个参数化函数后，可恢复前轮测试文件完全相同的 SHA-256；原 R5 测试及断言没有削弱。本次 R5 没有新增或修改测试、业务代码或设计，只更新交接与证据 | [复验审计](evidence/r5-retest2-audit.json) |
| 差异检查 | Windows Git `git diff --check` 退出0 | [输出](evidence/r5-retest2-diff-check.txt) |

R4-006-T07 的观察修订合理：仅将实际尺寸变化产生的即时帧排除出普通帧速率计算，仍比较其前后普通帧的间隔；所有帧继续接受内容、进展和输入延迟检查。没有把失败产品结果改写为测试预期。现有回归已覆盖本次变化，未发现必须新增的测试缺口。

实际执行环境仍为本地 WSL Ubuntu-24.04 / x86_64 / Python 3.12.3，保留原 DNS/connect 禁用和离线安装措施。关键命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-retest2-final-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r5-retest2-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --wheel /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl
```

当前 wheel SHA-256：`159e48ddd1365fc0cb54408518a0922fd8eb46c41d013cee4a2878f01d322fb8`。本次实际执行结果与 R4 的1908项报告分别记录，不用对方结论代替独立复验。GUI 继续采用用户已确认的整体观感；没有连接部署服务器，也没有新增 GUI 字体/截图/可见FPS结论。此前失败记录继续保留，当前状态以本节和页首为准。

## 第一轮修复复验（v1.1 历史）

用户已明确要求检查修复方法。比较对象为初审 [r5-review-audit.json](evidence/r5-review-audit.json) 与 R4 v1.3 交付；相对初审，生产源码只有 `src/joi_observer/tui/app.py` 改变。当前源码/测试输入与 R4 返修审计哈希一致，见[复验输入快照](evidence/r5-retest-input.json)、[生产修复差异](evidence/r5-retest-source.diff)。文档阶段说明调整不改变本轮验收依据。

**修复方向合理，但当前实现仍不满足验收。** 以同一个 `read_now` 推进已逝节拍并取得正超时，解决了刚完成慢绘制后反复跳过输入的问题；原 R5 失败测试和 R4 新增的导航/主题、连续无输入回归均通过。问题在于该分支没有区分本轮是否已绘制：未绘制时也会直接推进到下一槽，造成到期画面可以被持续跳过。原问题 R5-006-001 关闭，新回归 R5-006-002 保持 OPEN，`result=needs_fix` / `next_role=R4`。

本次 R5 仅在现有 `test_frame_timing_edges.py` 新增一个参数化测试（3 个相邻输入相位），没有改业务代码、设计或原测试断言。输入事件按预定时间到达，端口等待事件或完整超时、主动让出事件循环；不是任意提前返回 None，也没有回拨时钟。

| 本次 R5 实际验证 | 结果 | 证据 |
| --- | --- | --- |
| R4 修复交付的完整回归（新增相位测试前） | **1893 passed，30.50s**，包含原 R5-006-001 及 R4 两项新增回归 | [输出](evidence/r5-retest-final-pytest.txt)、[JUnit](evidence/r5-retest-final-pytest.xml) |
| 帧边界文件，含本次补测 | **13 passed / 1 failed**；1.5μs 与 3.5μs 相位通过，2.5μs 相位只画初始帧 | [输出](evidence/r5-retest-input-phase.txt)、[JUnit](evidence/r5-retest-input-phase.xml) |
| **最终完整回归，含本次补测** | **1895 passed / 1 failed / 0 errors / 0 skipped，32.29s**；唯一失败为新 R5-006-002 | [输出](evidence/r5-retest-with-input-phase-pytest.txt)、[JUnit](evidence/r5-retest-with-input-phase-pytest.xml) |
| 修复后 wheel 独立隔离安装/真实 CLI/PTY | passed；源码 Python/YAML/README 一致；131 帧、普通间隔中位33.449ms、q响应83.88ms；网络与外部进程尝试为空。常规PTY通过不替代确定性相位缺陷的验证 | [安装结果](evidence/r5-retest-install/uv-install-results.json)、[摘要](evidence/r5-retest-install-summary.json) |
| 修改边界与差异检查 | 业务/设计未被 R5 改动；仅补相位测试和本交接/证据，原有测试完整保留 | [复验审计](evidence/r5-retest-audit.json) |

以上在本地 WSL Ubuntu-24.04、Python 3.12.3 执行，沿用本交接原有离线防护。实际关键命令：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-retest-with-input-phase-pytest.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_frame_timing_edges.py \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-retest-input-phase.xml
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r5-retest-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --wheel /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl
```

当轮 wheel SHA-256：`2f1d98c360cda8be71bdca3a746c502e451f0290a8eab9d995c2e1908cb8b273`，现归档于 `evidence/r4-install-before-r5-fix2/wheels/`。用户已有 GUI 确认继续有效，没有重复索取；当轮复验只针对调度修复和相关回归，不将常规终端通过描述为所有时序边界已正确。以下初审证据保留当时结果，不覆盖原失败报告。

## 初审产物（v1.0 历史）

本轮只补充测试及 R5 交接/验证证据，没有修改业务代码、设计契约、既有测试预期，也没有提交、推送或连接服务器。

| 产物 | 新增覆盖 |
| --- | --- |
| [test_frame_timing_edges.py](../../../../tests/test_frame_timing_edges.py) | 1 项：慢帧完成后的调度操作跨过下一截止点时，已就绪的 q 必须有机会被读取；当前失败，保留原约定。 |
| [test_theme_terminal.py](../../../../tests/test_theme_terminal.py) | 3 项：先成功呈现 Hologram，再切 Moonlight 时 init_color/init_pair/color_pair 中途异常，整帧旧属性和背景清除、单色锁定、颜色与终端恢复。 |
| [test_vllm_view.py](../../../../tests/test_vllm_view.py) | 1 项：name、id、served_model_name 各不相同，左右标题共用 name、指标仅按 id 取值；同名干扰快照不改变选择。 |
| [R5 最终核对](evidence/r5-review-audit.json) | 输入/输出文件哈希、业务及设计未变、最终测试统计、当前包一致性。 |

## 初审验证证据（v1.0 历史）

全部实际执行在本地 WSL `Ubuntu-24.04` / x86_64 / Python 3.12.3，仓库 `/mnt/d/Documents/joi-observer`，解释器 `/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python`。pytest 保留 DNS/connect 禁用；安装使用本地 wheel、uv offline/no-index/no-python-downloads，真实 CLI 子进程保留 DNS/connect/Popen 防护。

### 本轮实际执行

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| **完整回归，含新增用例** | **1890 passed / 1 failed / 0 errors / 0 skipped，30.80s**；唯一失败为 R5-006-001。原有 1886 项及其余 4 项新增测试通过。 | [输出](evidence/r5-final-pytest.txt)、[JUnit](evidence/r5-final-pytest.xml) |
| 帧截止点边界文件 | 8 passed / 1 failed；30 帧期间 read_key 调用为 0。 | [输出](evidence/r5-frame-deadline-pytest.txt)、[JUnit](evidence/r5-frame-deadline-pytest.xml) |
| 主题终端定向 | 38 passed，含新增 3 项切换中途故障。 | [输出](evidence/r5-theme-switch-pytest.txt)、[JUnit](evidence/r5-theme-switch-pytest.xml) |
| 历史/尺度/应用/服务视图定向 | 286 passed；执行于名称补测加入前，包含于最终全量。 | [输出](evidence/r5-history-scope-pytest.txt)、[JUnit](evidence/r5-history-scope-pytest.xml) |
| 服务视图定向 | 155 passed，含名称/内部身份区分补测。 | [输出](evidence/r5-model-display-pytest.txt)、[JUnit](evidence/r5-model-display-pytest.xml) |
| 布局探索矩阵 | 1323 组合通过：非零原点、连续宽高、三类型、不同选择、长名称及极端数字；检查内容不越界、不相互覆盖。这是探索验证，不计入 pytest 数量。 | [脚本](evidence/r5-layout-boundaries.py)、[结果](evidence/r5-layout-boundaries.json) |
| 当前 wheel 独立隔离安装与真实 CLI/PTY | passed；新 shell 异目录裸命令、示例入口、全部源码 Python/YAML/README 对应、双主题/三类型/缩放/退出恢复通过。130 帧，普通帧间隔中位 33.345ms，q 响应 84.14ms；网络/外部进程尝试为空，任务自有进程均清理。 | [安装结果](evidence/r5-install/uv-install-results.json)、[摘要](evidence/r5-install-summary.json)、[实际复用脚本](evidence/r5-install/verify_uv_install.py) |
| 最新实际终端观感 | 用户在本次 R5 对话明确答复“已复验，整体显示符合预期”；原 GUI-006-001 的人工观感待确认项据此关闭。 | [原问题与答复记录](evidence/r5-user-gui-confirmation.json) |
| 差异检查 | `git diff --check` 通过；R5 期间业务/设计哈希未变，只新增 3 个测试函数（参数化后 5 项）及本交接与 evidence。 | [最终核对](evidence/r5-review-audit.json) |

关键命令（从仓库根目录在 WSL 执行；日志通过 `tee` 保存并启用 `set -o pipefail`）：

```bash
/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-final-pytest.xml

/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short \
  tests/test_frame_timing_edges.py \
  --junitxml=docs/dev-workflow/dev-0/REQ-006/evidence/r5-frame-deadline-pytest.xml

/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r5-install/verify_uv_install.py \
  --uv /home/shawn/.local/bin/uv \
  --wheel /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/wheels/joi_observer-0.1.0.dev0-py3-none-any.whl

/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python \
  docs/dev-workflow/dev-0/REQ-006/evidence/r5-layout-boundaries.py
```

### 覆盖与证据边界

- AC-601～604：默认主题、两次 t、颜色角色、琥珀范围、鼠标不启用、选择和快照保持、能力降级及恢复，由主题/导航/PTY 和安装验证覆盖；未发现确定缺陷。
- AC-605～608、613～616：GPU/Host/Storage/Docker 分区、奇偶半页、可见容器前缀、长 Unicode、固定状态槽、三模型布局、直接字节 HALF_UP、固定一位百分比、数值上界、名称与服务身份分离均有当前用例；未发现确定缺陷。
- AC-610～612：固定 60 秒分箱、有效 0 与缺口、模型/指标独立尺度、即时升档与 5 秒迟降、主题/缩放保持、原样本不改及终端残留清除通过；未发现确定缺陷。
- **AC-609 未满足**：普通节拍、慢帧跳槽及常规输入已通过，但新增的连续截止点跨越场景暴露输入饥饿，见下节。
- 初审使用 R4 当时 wheel，SHA-256 为 `96dbfd37477d9674ea33278ede0c6bd2c9b097d35aa701168f7cb9be5e3b552e`，现归档于 `evidence/r4-install-before-r5-fix/wheels/`；R5 未改变源码，不重复构建同源 wheel。安装验证脚本复用 R4 已审查脚本副本，**结果为 R5 初审时实际执行**，未覆盖或冒用 R4 旧结果。
- R4 的 1886 passed、原安装、23 场景 Frame/PNG 与历史 GUI 截图只作为交付背景引用。静态 PNG 不作实际终端截图；本次没有新增截图或字体/字号报告。用户的整体观感确认独立记录，不推导 GUI 实测 30 FPS 或逐项交互报告。
- 未连接或验证部署服务器，不给出服务器 GPU、Docker、vLLM 运行状态的结论；此次仅验收批准的本地离线范围。`evidence/` 被 Git 忽略，交接应携带实际文件。

## 本轮决策

**当前源码与重建安装交付通过，result=passed，接收角色R0／用户。** R5-006-001、002、003均已复验关闭，1948项源码验证及用户预览确认保持。用户随后明确要求重建包，本次新增构建、同版本更新、实际CLI/PTY及完整离线包安装验证已完成；旧GUI入口继续保留历史版本。各历史节的失败与等待状态仅代表当时交付。

核对 R4-006-T01～T06 的测试观察修订：图区外框过滤、硬件新行位、TextCell 按坐标组合、双统计块、真实空白颜色探针与 compose/物理 resize 时刻分离，均有当前契约依据；没有据此恢复旧布局或把旧预期作为新需求。完整回归保留业务状态、失败恢复、采样隔离及真实 PTY 断言。

初审的非阻塞文档建议已由 R4 v1.3 处理：theme/application-shell/hardware 补充了当前实现阶段说明；不是验收阻碍。R5 未修改这些设计文档。

## R4 修订汇总

### R5-006-001 [P2] 慢帧完成后的截止点跨越可持续饿死按键

- 状态：**CLOSED，R4 修复后 R5 复验通过**。下列触发与失败描述为初审版本，原失败证据继续保留。
- 关联需求、验收或任务：REQ-006 / AC-609；T-005；application-shell“帧截止点与终端写入”及 ObserverApp 关于慢帧跳过旧节拍、保持退出/导航/主题响应的约定。
- 涉及位置与影响：[app.py](../../../../src/joi_observer/tui/app.py) 第 379～384 行；尤其 `timeout <= 0` 分支先让出事件循环再 `continue`，绕过应用唯一的 `read_key`。q、t、方向键共用该路径；让出事件循环可以运行采样协程，但不会读取终端输入。
- 触发条件：慢终端每次刷新完成于下一 30 Hz 边界前；`schedule.advance(loop.time())` 尚选中该未来槽，而随后 `schedule.timeout(loop.time())` 已跨过该槽。若持续出现此情形，下一循环继续绘制，重复绕过读取。
- 预期与实际行为：预期允许跳帧但仍有有界的输入服务机会，已就绪的 q 能退出。实际确定性复现中，统一单调时钟每次观察间经过 1 微秒，终端刷新完成在下一边界前 0.5 微秒；连续 30 帧约 0.97 秒，`read_key` 调用 **0 次**。第 30 帧看门狗结束测试，终端 restore 正常执行。该时钟不按调用者或第几次读取制造特殊返回值，真实 App、FrameSchedule、快照/布局均保留。
- 复现或验证依据：[test_frame_timing_edges.py](../../../../tests/test_frame_timing_edges.py) 的 `test_near_deadline_draws_do_not_starve_a_pending_quit`（第 105 行）；[定向失败](evidence/r5-frame-deadline-pytest.txt)与[全量失败](evidence/r5-final-pytest.txt)一致。
- 最短复现命令：`/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q tests/test_frame_timing_edges.py::test_near_deadline_draws_do_not_starve_a_pending_quit`。
- 处理请求：修复截止点跨越时的调度/输入公平性，确保连续慢绘制仍能处理已就绪按键；保留 read_key 的正超时、原始 30 Hz 相位、跳过过期帧、不额外采样和终端恢复契约。不要删除/跳过新增测试或把 0 次读取改为成功预期。
- R4 回复与 R5 复验：R4 v1.3 改为读取一次 `read_now`，超时非正则 `advance(read_now)` 后以同一时刻重算超时并读取输入。R5 实际复跑原用例及完整回归，原问题通过；同一时刻保证正超时、原始 30Hz 相位保持，源码/wheel一致。此修复曾引入 R5-006-002，随后 R4 v1.4 区分已绘制/未绘制；2026-11-05完整回归再次确认001保持通过，002亦已关闭。

### R5-006-002 [P2] 未绘制的到期帧也被推进，周期输入可使画面持续不刷新

- 状态：**CLOSED，2026-11-05 R5 独立复验通过**。下列触发及失败描述为 R4 v1.3 的历史行为，原失败证据继续保留。
- 关联需求、验收或任务：REQ-006 / AC-603、AC-609、AC-612；T-005；application-shell 约定“快照/按键变化在下一个普通绘制机会呈现”“主机时间至少每秒更新”，跳过旧槽仅用于已完成慢绘制后的过期节拍，不能持续丢弃尚未呈现的到期画面。
- 涉及位置与影响：[app.py](../../../../src/joi_observer/tui/app.py) 第 383～389 行，尤其第 388 行无条件 `schedule.advance(read_now)`。本轮若 `schedule.due(now)` 尚为 false，没有执行 render，而下一次 `read_now` 刚好跨过 deadline，也会执行该分支；尚未绘制的槽直接被消耗。
- 预期与实际行为：快速离线终端与持续按键下，普通帧仍应持续绘制、主题状态可见，按键不应饿死画面。实际固定 30Hz 输入相位可使上述窗口反复发生：31 次输入、超过 1 秒，只有初始 1 帧；q 仍可退出，但期间 t 的变化没有任何新帧呈现。这与允许慢终端丢帧不同，复现的 render 无耗时。
- 复现方法：本次新增 [test_frame_timing_edges.py](../../../../tests/test_frame_timing_edges.py) 第 284 行 `test_periodic_input_before_deadlines_cannot_starve_normal_frames`。独立事件队列在 `n/30 - phase` 到达，前30次 t、第31次 q；每次时钟观察统一经过1μs；read_key 等待事件或完整正超时，并 await sleep(0)。相位 1.5μs/3.5μs 作为相邻对照通过，2.5μs 稳定失败。没有按调用点伪造时钟，没有提前超时或回拨时间。
- 最短复现命令：`/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q 'tests/test_frame_timing_edges.py::test_periodic_input_before_deadlines_cannot_starve_normal_frames[2.5]'`。
- 验证证据：[定向失败](evidence/r5-retest-input-phase.txt)与[全量失败](evidence/r5-retest-with-input-phase-pytest.txt)一致；原 R5-006-001 与 R4 两项新增用例均通过。端口只替换时钟/终端外部边界，真实 App、FrameSchedule、SessionViewActions 与 compose_frame 均保留。
- 处理请求：区分“本轮已绘制后跨截止点”与“本轮未绘制但已经到期”，保证读键和到期绘制各有有界的处理机会。避免在后者直接 advance 丢弃待绘制帧；同时保留对原输入饥饿的修复、正超时、原始相位、不额外采样和 finally 清理。不要仅回退原补丁，也不要删除或弱化本次测试。
- R4 回复与 R5 复验：R4 v1.4 增加每轮 `drew_frame`；未绘制且读键前到期时不推进deadline，下一轮先完成绘制；已绘制才沿用001的推进并读键。R5核对其活性、原始相位、resize和finally边界，实际执行1908项完整回归全部通过，包含原三个相位与新增12组合；源码与最终wheel一致。修复合理，未发现新回归，本编号关闭，见[本轮报告](evidence/r5-retest2-final-pytest.xml)与[审计](evidence/r5-retest2-audit.json)。

### GUI-006-001 最新实际终端观感待确认

- 状态：**CLOSED，用户确认**。
- 本次 R5 已针对最新 RAM/百分比精度版本询问，用户明确答复“已复验，整体显示符合预期”。以[本次人工答复](evidence/r5-user-gui-confirmation.json)解除原 R4 的观感待确认事项，不把旧静态预览或自动化通过冒充新截图。
- R4 v1.3 已同步该关闭状态；无需再次请求同一整体观感确认。

### R5-006-003 [P2] 标准库默认Linux遮蔽了os-release字段缺失，页眉回退失效

- 状态：**CLOSED，2026-11-05 R5复验通过**。以下复现描述对应v1.3旧代码，失败证据保留。
- 关联需求、验收或任务：REQ-006页眉修订、T-002/T-006，及REQ-001 / AC-101、requirements v1.20共同决定、application-shell“HTML对齐的字符适配”约定：优先PRETTY_NAME，缺失退NAME+VERSION_ID，缺NAME/版本分别用Ubuntu/—。
- 涉及位置与影响：[cli.py](../../../../src/joi_observer/cli.py) 第104～110行 `_local_host_info()`。Python 3.12真实 `platform.freedesktop_os_release()` 的解析器预填 `NAME=Linux`、`PRETTY_NAME=Linux`。该返回字典无法直接代表原文件是否提供字段；代码的 `.get(..., "")` / `if not system` 因而在实际缺字段时不会按约定回退。
- 预期与实际行为：原始文件仅 `NAME="Ubuntu"` 与 `VERSION_ID="24.04"` 时应显示 `Ubuntu 24.04`，实际 `Linux`；空文件应 `Ubuntu —`，实际 `Linux`；显式空PRETTY_NAME且只有VERSION_ID时应 `Ubuntu 24.04`，实际 `Linux 24.04`。固定设备标签本身正确。普通Ubuntu完整PRETTY_NAME路径通过，缺陷不代表现场所有启动均错误。
- 复现与验证：新增 `tests/test_cli.py::test_real_runtime_os_release_text_fallback_uses_distribution_fields`，3个参数均失败；通过临时文件调整标准库读取候选并清理缓存，真实标准库解析与生产组装保持，不开启采样或服务连接。现有测试直接返回预制release字典，未覆盖标准库注入的默认字段。见[定向输出](evidence/r5-ui60-host-fallback.txt)、[全量输出](evidence/r5-ui60-final-pytest.txt)。
- 最短复现命令：`/home/shawn/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q tests/test_cli.py::test_real_runtime_os_release_text_fallback_uses_distribution_fields`。
- 处理请求：正确区分实际文件提供的字段与库补入的默认值，落实优先级和缺失回退；保留显式PRETTY_NAME优先、读取/编码失败回退、启动时读取、无内核/DMI/网络探测的边界。不要把新增失败预期改成Linux，也不要简单把真实文件中明确提供的字面值Linux一律视为缺失。
- R4回复与R5复验：R4已采用私有实际字段reader，不再依赖stdlib补入的默认字段或全局缓存；R5核对候选优先、显式Linux、引号转义、空值、OSError/UnicodeError及一次读取契约，原3个失败样本全部通过。本次另补两项Runtime/部分读取失败测试并通过；完整回归1948项通过。原测试仅调整文件位置IO接缝，样本、预期与真实生产装配未削弱。本编号关闭；按当前不构建安装包约定，不追加新wheel验收。

## 预览确认与范围记录

### GUI-006-002 新显示预览确认

- **当前状态：CLOSED，就本轮预览确认范围。** 上轮“尚未检查；先做代码与离线复验”保留于[旧范围记录](evidence/r5-ui60-user-scope.json)；当前用户明确“预览效果已确认”，见[新确认](evidence/r5-track-preview-confirmation.json)，不再索取同一确认。旧GUI-006-001也保持关闭。
- 本次接受的是用户对当前预览的确认。没有操作MobaXterm或连接服务器，没有把静态图、PTY时序或该回复扩大为实际终端像素RGB、字体/字号或可见60FPS实测。基础色最终明暗仍受终端调色板和bold/dim处理影响；如后续另行实机验证，可在同需求目录增补证据。

## 下一步

接收角色为 **R0／用户**：当前安装包已重建并验证，可将页首链接的`20261105-track`离线包上传服务器，按包内说明以`--force --reinstall`更新同版本工具并沿用现有配置。本轮不连接服务器、不更新旧GUI入口、不提交或推送；`evidence/`被Git忽略，移交时应携带实际文件。
