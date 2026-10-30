# dev-0 / REQ-001 R2 交接

- stage：R2
- result：ready
- next_role：R3
- 修订：v1.5，2026-10-29
- project_root：`D:\Documents\joi-observer`
- work_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0`
- req_dir：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001`
- 需求依据：`D:\Documents\joi-observer\docs\dev-workflow\dev-0\requirements.md`及`handoff-r1.md` v1.12；REQ-001 AC-105/106及跨需求共同布局规则，衔接AC-207/301/304/607/608。
- 来源：用户要求核对更新需求对REQ-001的影响。已有R3计划v1.0和R4/R5对v1.9的实现/验收记录，本次为新需求引起的R2修订，不属于R4缺陷回交。

## 处理结论与产物

REQ-001需要修订：配置层改为仅纳入前3个挂载点、完整保留所有容器；布局按全页上下各半，Storage固定3行内容，Docker仅显示剩余空间可容纳的前缀。设计、目标接口注释、示例及黑盒预期已同步，`ready`表示新契约可交给R3更新规划。

v1.9公共运行基础已由R4实现并经R5验收，本次保留其可执行业务逻辑。Windows新基线为327项：269通过、43项新契约尚未实现而失败、15项Unix PTY跳过、0导入/收集错误。43项不是骨架NotImplementedError；配置和布局需后续R4同步。uv安装、日志本地时间、限频、只读状态和退出恢复等既有约定不变。

根目录采用 src 布局，保留用户架构方向，区分配置解析代码与随包示例。未改动用户已有 `AGENTS.md` 修改或 HTML 设计稿；v1.1 按用户指示同步需求文档中的 uv 安装约定，没有生成 R3 的 plan.md 或开展具体采集实现。

| 产物 | 实际路径 |
| --- | --- |
| 调度、状态与总体架构设计 | `D:\Documents\joi-observer\docs\design\monitor-state.md` |
| 配置设计 | `D:\Documents\joi-observer\docs\design\configuration.md` |
| CLI、全屏与容量设计 | `D:\Documents\joi-observer\docs\design\application-shell.md` |
| 采集错误日志设计 | `D:\Documents\joi-observer\docs\design\error-logging.md` |
| 配置接口与示例 | `D:\Documents\joi-observer\src\joi_observer\config.py`；`src\joi_observer\examples\config.yaml` |
| 单对象采集端口与调度 | `D:\Documents\joi-observer\src\joi_observer\collectors\base.py`；`src\joi_observer\monitor.py` |
| 数据对象与状态 | `D:\Documents\joi-observer\src\joi_observer\data\models.py`；`src\joi_observer\data\state.py` |
| 日志接口与文件后端骨架 | `D:\Documents\joi-observer\src\joi_observer\error_log.py` |
| CLI/组合根/终端骨架 | `D:\Documents\joi-observer\src\joi_observer\cli.py`、`__main__.py`、`tui\app.py`、`tui\layout.py` |
| 黑盒测试 | `D:\Documents\joi-observer\tests\test_config.py`、`test_cli.py`、`test_state.py`、`test_monitor.py`、`test_error_log.py`、`test_tui.py` |
| 工程与使用说明 | `D:\Documents\joi-observer\pyproject.toml`、`.gitignore`、`README.md`，以及各包 `__init__.py` |
| 实测基线摘要 | `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001\test-baseline.json` |
| 日志时间修订的定向基线 | `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001\test-log-time-baseline.json` |
| v1.12修订验证 | `D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001\evidence\r2-v112-validation.json`；同目录`r2-v112-windows.xml`、`r2-v112-windows.txt`、`r2-v112-before.json` |

表内未写绝对前缀的同组文件相对该组首个文件的目录；`src/` 开头的简写相对项目根目录。代码/文档内的交叉链接保持仓库可迁移。包目录 `data/` 只放 Python 声明，不存放监控数据。

## 本轮设计决策

1. Python 3.12+、标准库 asyncio/curses；curses 延迟导入，Windows 可加载骨架。安装与开发使用 uv：正式使用 `uv tool install --python 3.12 /path/to/joi-observer`，首次通过 `uv tool update-shell` 配置 PATH；开发使用 `uv run --python 3.12 joi-observer`，测试使用 `uv run --python 3.12 --extra test pytest`。不要求每次手动激活环境。YAML 依赖 PyYAML，uv 不作为应用运行依赖；版本范围为设计选择，未下载依赖。R4 使用 uv 生成并维护项目锁文件。
2. 安装后的 `joi-observer` 可在新终端直接进入 TUI，无需进入源码目录；模块入口可在项目环境用 `uv run python -m joi_observer` 调用。配置优先级为 `--config` → 当前目录 → `~/.joi-observer/config.yaml`。缺文件/非法配置不回退到示例，启动前定位并退出。`--example-config` 只报告示例路径。
3. 采样默认 1 秒、独立超时 3 秒，均允许 0.1～60 秒。每对象单任务，忙时跳过周期、不追赶、不重叠；慢源不拖住其他来源及 UI。状态由 Monitor 唯一写入，展示只读冻结快照。
4. 有界历史默认 60 秒且最多 602 点/对象；有效0、未知None、不适用、失败保值与历史缺口相互区分。失败详情不进入快照，采样时间仅供内部计算。
5. 挂载点只校验/返回原列表前3项，第4项起忽略应用字段语义，不补位；完整YAML语法/标签/标量安全校验仍覆盖整份文件。容器不设固定数量上限，全部逐项校验、去重并保留顺序；只有展示层隐藏超出容量的尾项。模型配置与示例来源保持不变，不探测服务。
6. 日志目录默认 `~/.joi-observer`，文件固定 `error.log`，10,000,000字节、3份备份；阈值最小1024字节。time记录服务器本地发生时间，固定 `YYYY-MM-DD HH:MM:SS`，不附带时区信息、不转换成UTC。稳定 `(collector, object_id, kind, code)` 分类，不受动态reason或墙钟变更影响；0～59秒抑制，60秒允许，恢复清除故障轮次。输出受控原因模板，不记录任意异常正文、凭据或模型内容。
7. 日志预检查失败仅在全屏前提示一次后继续；运行期专用单写者与256条有界队列，IO失败静默，后续错误可重试。队满丢弃新事件，不改变采样/STALE；失败写入撤销限频预占，不重放旧记录。相同目录不支持多个进程同时轮转。
8. 下半页为`H//2`、上半页为`H-H//2`，页眉/服务切换/键位均包含在对应预算内。最低列数120；最低行数`max(36, 2*(2+max(3*max(GPU,1)+2,16))-1)`，5GPU为37，6GPU为43，容器数量不影响尺寸。Storage固定6行（3内容+3标题/边框），Docker占右侧余高，容量`max(0, upper_rows-18)`；隐藏无提示、不滚动，零容量不画条目/空态。仅基础窗口不足时提示放大。
9. 全屏生命周期覆盖部分进入失败、q、取消、异常和可处理信号；先恢复终端，再在总体1秒预算内协调采集/日志关闭。不可取消的底层调用不能靠无限等待线程收尾。t/方向键为后续展示模块预留端口，不触发采集。
10. 类图只表示静态结构，以一张图展示Monitor、Collector、MonitorState、ErrorLog、CollectionResult、StateSnapshot、ObjectSnapshot七个核心类型。关联从持有者指向被引用对象，参数/返回类型使用依赖；连线不带文字标签，仅保留必要多重性。图中省略非关键成员和细节类型，完整接口与私有结构仍保留在代码注释中。

这些决定已同步到模块文档、接口注释和黑盒测试；没有尚待人工决定的 REQ-001 设计问题。

## 验收与黑盒覆盖

| 验收条件 | 主要公开行为测试 | 仍需后续验证 |
| --- | --- | --- |
| AC-101 | state 首次None/首次失败；tui 标题、主机、当前时间、—、固定STALE槽 | 真实终端绘制与后续采集器字段 |
| AC-102 | monitor 即时/默认/自定义周期、状态通知；Runtime联合入口 | 完成实现后观察刷新周期 |
| AC-103 | 慢源隔离、超时、独立快源；UI按键分派；真实Monitor/UI的慢源退出组合测试 | REQ-005/006 的完整导航/主题及真实终端响应 |
| AC-104 | q、部分enter失败、绘制/键盘异常、取消、运行中stop；恢复先于日志close | Ubuntu PTY的termios、光标、alternate screen、SIGINT/SIGTERM |
| AC-105 | 前3挂载点、完整容器列表及后续项校验、完整YAML安全回归、重启重读 | R4同步新解析逻辑；REQ-002/003实采接入 |
| AC-106 | 全页奇偶半高、120列和新GPU容量公式、固定Storage、Docker4→6→3/零容量/不补位/不提示、小窗q | R4同步布局，REQ-006视觉排版及本地PTY新边界 |
| AC-107 | 默认home展开、自定义目录、不改配置；真实临时文件创建/追加 | 目标OS文件权限组合 |
| AC-108 | 四类对象首次ERROR；Monitor对0/None/N/A/Exited无日志 | 具体适配器失败分类 |
| AC-109 | 默认参数、真实临时文件轮转与最旧淘汰 | 多种真实文件系统IO故障 |
| AC-110 | 日志字段/受控原因/静默；快照无原因；CLI内部异常不泄漏 | curses全屏绘制期间输出隔离 |
| AC-111 | prepare失败继续、运行写失败恢复、慢磁盘/队满、有界close | 本地Ubuntu不可写目录及长期阻塞IO |
| AC-112 | 0/1～59/60、新对象/错误、A→B→A、恢复重记；61次失败仍61次采样/STALE更新 | 实现后的跨模块集成 |
| AC-113 | 未配置退出、路径和示例提示、示例复制后加载三类型 | wheel资源安装定位 |
| AC-114 | application-shell.md 的 uv 本地安装验证场景：首次配置PATH后，新shell中不激活环境、不进入源码目录，直接解析命令及示例资源并离线启停TUI | 新增安装验收待R4执行；现有CLI单测不能替代工具安装验证 |

测试隔离外部采集、文件故障和终端边界，不替换被测配置解析、状态、调度、限频或屏幕生成结果。联合用例真实调用 ApplicationRuntime、Monitor、MonitorState、ObserverApp 的入口。首轮尚未实现时通常在第一个待实现入口失败，因此收集成功不等于后续断言已执行或行为已验证。

## v1.1 文档修订

采纳用户在本对话中的补充：需求说明升至 v1.8，REQ-001 简明记录 uv 安装和新终端直接启动，新增 AC-114；应用外壳设计与运行架构升至 v1.1，README 改为 uv 使用流程。详细命令、工具环境/项目环境区别和离线安装验收放在设计文档，需求文档只保留约束与可观察结果。

本次仅修改文档，没有改变 Python 接口、业务代码或测试断言，没有执行 uv 安装、依赖解析或监控启动。通过文档一致性检查与 `git diff --check`；以下167项测试结果引用初版实际执行基线，本次没有重新运行业务测试。AC-114 的安装行为明确列为未验证，不计入既有通过项。

## v1.2 日志时间修订与验证

采纳用户要求：日志time使用服务器本地 `YYYY-MM-DD HH:MM:SS`，不附带时区名、偏移或Z后缀，也不转换成UTC。需求说明升至v1.9，日志设计升至v1.1、运行架构升至v1.2；同步README、ErrorLog/Monitor接口注释与既有日志测试。内部datetime可保留时区信息，序列化只输出本地年月日时分秒，60秒限频仍使用单调时钟。

在 `D:\Documents\joi-observer` 实际执行：

- `python -m compileall -q src/joi_observer/error_log.py src/joi_observer/monitor.py tests/test_error_log.py`：通过。
- `python -m pytest tests/test_error_log.py -q --tb=no -o addopts= --junitxml=.pytest_cache/r2-log-time.xml`：22项，1 passed、21 failed、0 errors；失败均为ErrorLog.prepare的NotImplementedError，尚未执行到时间字符串断言，不能宣称输出格式已实现或通过。
- `git diff --check`：通过；已检查并替换旧时间格式约定，原约定仅在历史修订说明中保留。

本次未新增用例、未实现日志业务、未连接服务器；定向结果保存于test-log-time-baseline.json，以下全量结果仍为初版历史基线。交接保持 `stage=R2`、`result=ready`、`next_role=R3`；R3按新时间契约规划，R4实现后重跑日志测试。

## v1.3 UML 类图修订与验证

采纳用户指出的两项问题：原类图把Collector返回结果的数据方向误作类关系，且Monitor/MonitorState仅列操作、缺少主要持有对象和内部状态。`monitor-state.md`升至v1.3，拆为调度协作、内存状态/快照两张UML类图；补齐可见性、参数及返回类型、关联多重性，标明Collector接口、不可变数据类型与ErrorKind枚举。StateSnapshot与ObjectSnapshot不再画组合。

同步`monitor.py`和`data/state.py`的骨架：新增私有`_CollectorSlot`（来源、周期原点、下次到期、任务、实际完成时刻）和`_ObjectState`（声明、当前值、最近结果/时间、前次成功/时间、基线有效性、STALE、历史），以及Monitor的slot表/运行标记和MonitorState的entry表/revision。仅声明类型、空容器及初始标记；调度、合并和历史裁剪仍待R4，不改变公开方法签名或既有测试断言。业务需求未变，requirements.md保持v1.9。

实际在`D:\Documents\joi-observer`执行源码AST与类图属性静态比对：14个相关类型的全部属性名称一致；组合仅有上述两处。独立审查确认关联方向、依赖、多重性及可空字段一致；枚举使用类型依赖。`python -m compileall -q src tests`通过，`python -m pytest --collect-only -q`成功收集167项，`git diff --check`通过。没有新增结构镜像测试，也未重跑业务测试；历史执行结果见下文。

Mermaid记法依据其官方类图说明核对，本地没有可用Mermaid解析/渲染器，因此本次未完成图形渲染验证，不将静态核对表述为渲染通过。未执行采集或连接监控服务器。交接保持R2 ready，接收角色R3；规划时采用更新后的UML图和骨架结构。

## v1.4 类图精简

按用户反馈将两张详细类图合并为一张核心类图，去掉全部连线文字、时钟/超时/运行标记等非关键成员，以及调度记录、状态条目、枚举等细节类的展开；保留Monitor的三个持有对象、MonitorState状态表、主要操作，以及采集结果/只读快照的关键成员。关联与依赖继续采用UML定义，快照之间使用普通关联。

本次只修改`monitor-state.md`及本交接单，需求、代码骨架和测试不变。已静态核对单张类图、七个核心类型、无连线文字和成员对应关系，并通过`git diff --check`；未重跑业务测试或进行Mermaid渲染。交接保持R2 ready，R3按精简视图及既有接口契约规划。

## v1.5 需求v1.12修订与当前验证

| 编号 | 旧契约与影响 | 本次R2处理及后续实现位置 |
| --- | --- | --- |
| R2-112-01 | config仍纳入全部挂载点、截断容器前5项 | configuration v1.1、config.py注释、示例与配置黑盒已修订；R4修改现有解析循环，保留R5-001完整YAML检查及安全定位 |
| R2-112-02 | 固定16行服务区、旧最低高度、Storage吸收余高、Docker按条数贴合 | application-shell v1.2、layout.py目标注释及TUI测试已修订；Frame新增`service_switch`区域，总计8区；R4按区域边界限制绘制，不能让尾项越界覆盖下半页 |
| R2-112-03 | 显示数量与采集数量原来同为最多5项 | monitor-state v1.5、Monitor注释及真实Monitor/State/日志/Frame联合用例明确全部容器持续采集，隐藏失败仍记录、缩放只改变可见前缀 |

本次实际修改的测试为`test_config.py`、`test_config_boundaries.py`、`test_tui.py`、`test_shell_edges.py`及`test_integration.py`。保留原R5 YAML安全场景，增加第4挂载点完整YAML校验；PTY输入修复用例未改。源码剥除docstring后的AST校验确认可执行逻辑完全未变，未将既有实现改回骨架。AGENTS、需求、R1交接、R3计划及交接、R4/R5交接和uv.lock的SHA-256均与修订前一致。

运行目录`D:\Documents\joi-observer`，Windows Python3.12.10/pytest8.4.2，复用`.pytest_cache/offline_deps`中的PyYAML6.0.1，没有安装依赖或连接服务器：

```powershell
$env:PYTHONPATH = "$PWD\.pytest_cache\offline_deps"
python -m pytest -q --tb=short --junitxml=docs/dev-workflow/dev-0/REQ-001/evidence/r2-v112-windows.xml
```

实测327项，269 passed、43 failed、15 skipped、0 errors，退出码1。失败分类：配置15项、TUI26项、稳定GPU槽位边界1项、Docker完整采集与可见容量联合用例1项，均为旧实现与新契约的差异；无NotImplementedError或导入/环境失败。联合用例已完成十个来源的首次采样，但旧layout在容器数量检查处拒绝继续，后续隐藏/缩放断言尚不能宣称验证通过。15个Unix PTY用例在Windows按平台跳过，本次未重跑WSL或工具安装。

`python -m compileall -q src tests`、`git diff --check`及源码/保护文件比对通过。结构化结果见[evidence/r2-v112-validation.json](evidence/r2-v112-validation.json)，完整输出及JUnit分别见[evidence/r2-v112-windows.txt](evidence/r2-v112-windows.txt)、[evidence/r2-v112-windows.xml](evidence/r2-v112-windows.xml)，保护基线见[evidence/r2-v112-before.json](evidence/r2-v112-before.json)。这些是新契约交接基线，不得永久skip/xfail，也不推翻R5对旧v1.9的历史验收。

R3需要更新现有plan.md中T-001配置、T-005终端布局及相关集成/安装验收项，再交R4实施。既有`verify_pty.py`、`verify_uv_install.py`使用的旧尺寸边界应在实现新契约后重新核对；原JSON证据保持历史值。REQ-002/003/005/006后续设计继承前三挂载点、完整容器采集和半页预算，当前不扩展为这些需求的业务实现。

## 初版验证证据

运行目录均为 `D:\Documents\joi-observer`。本次实际使用 Windows、Python 3.12.10、pytest 8.4.2；未使用 WSL、真实终端、GPU、Docker或服务。没有连接任何服务器。

| 已执行命令 | 实际结果 |
| --- | --- |
| `python -m compileall -q src tests` | 通过，源码与测试语法可编译 |
| `python -m pytest --collect-only -q` | 最终167项成功收集，退出码0 |
| `python -m pytest -q --tb=short --junitxml=.pytest_cache/r2-baseline.xml` | 167项：2 passed、165 failed、0 errors、0 skipped；pytest退出码1，运行约3.29秒 |
| 解析上述JUnit结果并逐项归类 | 162项直接NotImplementedError；3项因期待具体RuntimeError文案却收到NotImplementedError，产生断言失败；均由业务未实现导致，没有独立导入/环境故障 |
| `git diff --check` | 通过；工作区原有AGENTS.md修改保留 |

分模块：CLI 17失败；配置1通过/69失败；日志1通过/21失败；Monitor 14失败；State 16失败；TUI及组合根28失败。2项通过仅证明冻结配置载体和日志构造无文件副作用，不能解释为任何核心业务已实现。完整分类及基线命令保存于 test-baseline.json，JUnit详细临时报告留在已忽略的 `.pytest_cache/`。

当前环境未安装 PyYAML、setuptools/build，尚未运行 wheel构建、安装或真实YAML解析；骨架延迟业务依赖，因此测试可以加载。这是明确未执行的实现/打包验证，不把缺依赖作为业务失败或通过条件。R4 实现时须准备依赖并重新执行断言；不应将165个失败永久标为预期、skip或xfail。

## 范围与未验证事项

- D-002：REQ-001 已确定字符容量及小窗口策略；REQ-002/006 继承并完成具体绘制验证。
- D-003：已处理配置、超时和日志部分。容器实际匹配、CPU/RAM/磁盘口径、vLLM指标仍属于REQ-002～004设计。
- D-001：目标vLLM生成/pooling指标、计数单位、延迟计时范围尚未核对；属于REQ-004，不把HTML样例当依据，也未自行缩小业务范围。
- D-004：真实容器名、版本、权限和设备映射未验证。禁止连接服务器的限制持续有效。
- 本轮只提供REQ-001公共外壳；完整运行的硬件/模型面板及主题导航依赖后续需求，不宣称已完成REQ-002～006。

## 下一步请求

接收角色为 **R3**。请基于本交接v1.5及更新的模块设计，修订 **REQ-001** 已有的
`D:\Documents\joi-observer\docs\dev-workflow\dev-0\REQ-001\plan.md` v1.0，纳入R2-112-01～03、43项新基线差异及本地布局/安装复验，然后交R4同步实现。若发现接口/测试冲突，保留问题编号交回R2；没有需等待的人工确认。本轮未改R3～R5阶段记录，也未自动推进其他对话。

规划应纳入用户最新确认的 uv 安装流程及 AC-114 本地验收，保持禁止连接服务器的限制。
