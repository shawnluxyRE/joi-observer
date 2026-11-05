# REQ-006 人工 GUI 验证清单

**当前入口版本说明（2026-11-05）：** 用户已要求停止生成离线包。本轮源码已将GPU/CPU/RAM填充与轨道统一为`▌`，轨道使用独立深灰track；以下旧wheel/已安装CLI/Frame回放没有重建，仍是上一轮三处留白、细轨道`▏`版本，不能用它们验证本轮深灰轨道。下文旧入口和检查记录保留供历史参考，当前源码1946项全量通过，证据见[R4交接](handoff-r4.md)。

状态：旧版GUI-006-001已据[用户确认](evidence/r5-user-gui-confirmation.json)关闭；当前GUI-006-002的新MobaXterm观感仍未验证。用户在[R5范围记录](evidence/r5-ui60-user-scope.json)中要求先做代码与离线复验，因此以下是后续人工复验参考，不能用旧确认替代新版配色、分格条或实际FPS结果。

2026-11-05新增显示调整：两条启动脚本继承当前`TERM`，不会切换到256色。当前`TERM=xterm`下Moonlight使用终端亮紫近似，颜色受终端ANSI调色板控制；主题变化会强制重绘以更新旧文字。Storage左侧路径为正文色；页眉固定`H3C R5300 G6 /`，正式CLI后接本机Ubuntu发行版本。原GUI整体确认针对上一版，本说明记录本次新增行为，不将旧确认冒充新增截图。

同日用户将刷新目标提高为60FPS（约16.7ms），默认采样仍1秒、柱图窗口仍60秒。可观察刷新/按键响应，不能将回放静态画面或肉眼观感等同于实测60FPS；柱图不会为每帧生成新的采样。

本轮硬件条改为填充`▌`/细轨道`▏`的分格外观，原字符宽度、填充数量、颜色、行高和数值列保持，vLLM历史竖柱不变。页眉缺字段回退同时修复，显式Linux值保留。R5已记录用户对新MobaXterm显示的答复为“尚未检查；先做代码与离线复验”，见[范围记录](evidence/r5-ui60-user-scope.json)；因此新版观感仍未验，原GUI-006-001已关闭的结论不覆盖这些新变化。

后续数字强调仅作用于vLLM右侧RUNNING/WAITING数值和历史标题上方四指标的真实数字。0、科学记数、STALE保留数值也加粗；—/N/A/…、左侧模型计数、标签/单位、caption、状态和历史不新增粗体。颜色role/色对与位置保持；低色终端可能将bold同时表现为更亮，这是终端字重处理。

最新留白调整：右侧模型名、RUNNING/WAITING、DECODE HISTORY（pooling为RATE HISTORY）上方各空一行；第三处是历史标题上方，不是DECODE指标标签上方。左栏、外框和下半页高度不变，柱图区相应少3行，最小支持尺寸仍保留1行图，横轴仍在原底部。数值加粗和颜色规则保持。

2026-11-04用户GUI反馈后的当前复验重点：模型展示名为Flash-Next/Embedding/Reranker；Storage的STALE只在面板右上角汇总一次，行内百分比贴内容右缘。Storage GiB与RAM容量（GiB/TiB）都显示整数；CPU/Storage现有百分比固定一位，如30.0%。RAM保持原布局，不新增百分比文字；GPU与Storage TiB精度保持。退出旧验证会话后重新运行下面入口，以使用修订后的安装包和场景。

已确认保留的离线安装环境仍可用。使用 Windows Terminal 的 PowerShell 标签执行以下命令，无需切换目录或激活虚拟环境。两个入口都仅使用本地样本并阻断 DNS/connect；不要直接用项目的生产配置启动。

## 1. 正式 CLI：交互、缩放与退出

```powershell
wsl -d Ubuntu-24.04 -- bash /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-install/installed-offline-gui.sh
```

初始窗口至少120列×36行，建议放大至120列×48行或以上。此场景故意不提供硬件、挂载点与容器；其空态/未知值正常。三模型使用相同的本地录制响应，吞吐在建立基线后为0属于预期，不必等待非零负载。

- [ ] 初始主题为 Hologram；按两次 `t` 后依次 Moonlight、Hologram。名称和品牌/选中项/标题/页脚颜色同步，空白背景统一，无旧色残留。只点击Theme文字不会切主题。
- [ ] 用 `↑` / `↓` 选择 Chat、Embedding、Reranker，选择项始终可见，到首尾停止。Chat使用tok/s，pooling使用seq/s且KV为N/A。服务仍固定vLLM，WebUI禁用；`←` / `→`、Enter、p、Tab不激活其他功能。
- [ ] 放大、缩小到低于最低尺寸，再放大。小窗口显示英文放大提示；小窗口内按t和方向键后，恢复时保留最新主题/选择，无旧文字、旧柱或边框残影。
- [ ] 正常布局服务窗口、底部服务位和键位共同占下半页；改变窗口高度时保持半页规则（奇数高度上半多1行）。三类型切换不使图表行位跳动。
- [ ] 右侧模型名、RUNNING/WAITING和历史标题上方各有完整一行留白；四指标标签与其数值仍紧邻，左栏条目位置不变。缩小至最低支持高度时，历史仍有一行可绘区且时间轴完整。
- [ ] 时间会更新，持续刷新时输入响应正常，无明显闪烁、撕裂、乱码或残影。人工只评价观感，不要求凭肉眼证明精确60FPS。
- [ ] 按 `q` 返回原shell，原屏幕、光标、输入回显和颜色恢复正常。可输入不含敏感信息的几字符后退格，确认回显；无需执行额外命令。

建议保留：Hologram Chat、Moonlight pooling、过小窗口、恢复后的正常窗口、退出后shell截图。

## 2. 完整样本：硬件、长名称与状态观感

```powershell
wsl -d Ubuntu-24.04 -- bash /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-visual/manual-frame-gui.sh
```

这是将保存的真实 Frame 交给**已安装的 CursesTerminal**绘制的离线回放器，不启动采集，也不模拟正式应用导航。仅在这个回放器中：`n`下一场景、`p`上一场景、`q`退出；t/方向键的产品行为在第1部分检查。

回放内容的逻辑画布固定为场景名称所标的120×40、120×48或160×48；更大的终端会留额外空白，不应将该空白视为产品半页分配错误。实际窗口过小时会提示放大，仍可n/p/q。回放是冻结画面，不用于判断动画帧率或尺度计时。

指定场景示例（可在q退出后换场景重启）：

```powershell
wsl -d Ubuntu-24.04 -- bash /mnt/d/Documents/joi-observer/docs/dev-workflow/dev-0/REQ-006/evidence/r4-visual/manual-frame-gui.sh --scene hologram-chat-stale-120x48
```

建议检查以下场景；其余可以用n/p浏览：

| 场景ID | 检查重点 |
| --- | --- |
| `hologram-chat-120x40` | 5GPU、型号/显存/温度/功率、CPU/RAM两行、Storage固定三槽、Docker只显示可见前缀、双统计与四列指标。 |
| `hologram-chat-120x48` | 同样本增加高度，Docker显示更多条目，Storage仍三槽；正吞吐柱图有左侧留白、固定-60s/0s、有效0和缺口。 |
| `moonlight-embed-120x48` | Moonlight配色、关联GPU4高亮、未关联GPU灰色、pooling seq/s及KV N/A。 |
| `hologram-rank-120x48` | Reranker指标/单位/选中项、等待数大于0的琥珀规则。 |
| `hologram-chat-stale-120x48` | 与正常同尺寸比较：Storage只在标题右上角显示一个STALE，挂载点各行百分比位置保持；其他对象状态仍占原固定位置，不新增诊断行，不挤压指标/历史；旧正等待值不用琥珀。 |
| `health-restored-120x48` | 与STALE帧对照，恢复后的字段/边框无错位或残留。 |
| `hologram-chat-long-unicode-120x48` | 长中文/Unicode名称先裁切，不覆盖数值、单位、状态或边框，字形无乱码。 |
| `moonlight-long-unicode-160x48` | 有条件时检查宽版长名称；窗口至少160列×48行。 |
| `hologram-chat-zero-120x48` / `hologram-chat-unknown-120x48` | 0与未知—可辨、0等待不用琥珀；这两份冻结样本无历史，历史空态—属于预期。 |

共同观察：Theme/时钟/Docker状态右缘整齐；CPU百分号、RAM共享单位、Storage中点的分色正确；原柱图、分段条、边框和箭头字形完整。记录实际终端字体和字号，不把静态PNG使用的Consolas当成实际字体。

## 3. 提交结果

截图可直接附在当前对话，或保存至：

```text
D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-006\evidence\manual-gui\
```

至少提供一张完整5GPU正常布局、一张另一主题pooling、一张STALE、一张长Unicode，以及正式CLI的缩小/恢复记录。退出恢复可用文字确认。若失败，保留失败场景和复现操作，不必继续强行完成全部检查。

反馈模板：

```text
终端：Windows Terminal（版本如方便提供）
字体 / 字号：
正式CLI：主题 / 三模型导航 / 缩小恢复 / q退出（通过或问题）
完整样本：硬件 / 双主题 / 三类型 / STALE恢复 / 长Unicode / 0与未知（通过或问题）
刷新观感：
截图：已附 / 保存路径
问题及复现步骤：无 / ...
```

GUI-006-001及R5-006-001/002保持已关闭。R4当前完成右侧三处留白，指定vLLM数字加粗、硬件分格与R5-006-003页眉回退修复保持，1937项全量验证通过；最终证据与R5交接状态见[交接记录](handoff-r4.md)。新版GUI-006-002由用户按安排检查后反馈，不重复要求旧版本的整体确认。
