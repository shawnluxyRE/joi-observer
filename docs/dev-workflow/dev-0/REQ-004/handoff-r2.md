# dev-0 / REQ-004 R2 交接

- stage：R2
- result：ready
- next_role：R4（先确认并实施资源边界修订；不自动推进其他角色聊天）
- 修订：v1.4，2026-11-03
- 来源：用户在R4明确选择先交R2确认；审阅R4 v1.3的R4-DES-005及R5 v1.5的R5-004-005。
- 分支：`codex/dev0-req004`；本轮审查HEAD `7a4e950ac4f703fa3f68c96bf05834d57b487374`。R4/R5已有未提交完整fixture、回归和交接记录，本轮保留；R2未提交。
- 实际 project_root：`D:\Documents\codex_worktree\dev0-req004\joi-observer`
- 实际 work_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0`
- 实际 req_dir：`D:\Documents\codex_worktree\dev0-req004\joi-observer\docs\dev-workflow\dev-0\REQ-004`
- 需求依据：当前worktree `docs/dev-workflow/dev-0/requirements.md` v1.12，REQ-004 / AC-401～412、D-001及共同规则。

## v1.4 决定：接受R4-DES-005统一64标签上限

**结论：接受64，不采用family豁免或跳过未知行的替代方案。** R4-DES-005的设计结论已明确，`result=ready`表示可以回交R4，不表示R5-004-005已经修复或验收通过。当前运行常量仍为16；需要R4落实并回验。

### 已确认契约

1. `MAX_LABELS_PER_SERIES`的统一目标值为 **64**。单条series恰好64个标签合法，65及以上为整对象`parse/response.invalid`，不得保留一部分观测当作成功。
2. 标签语法、引号/转义、重复标签、数量，以及数值词法和资源边界继续在对应过滤分支丢弃数据前检查；适用于未知family、其他模型、bucket及非STOP序列。不得对`vllm:cache_config_info`特判，不得直接忽略未知行来绕过限制。
3. 全局资源上限与目标schema分开：目标普通业务指标仍精确要求`model_name/engine`两个标签；bucket增加`le`、完成计数增加`finished_reason`，共三个。超过既定目标标签集合仍为整体失败，不能因全局放宽到64而接受任意业务标签。
4. 2MiB正文、64KiB单行、50000样本、128字符数字token、指数绝对值400及展开整数400位限制均不变。身份校验、目标数值约束、局部失败、STOP筛选和现有被忽略合法Prometheus数值规则不变。
5. 将三类完整响应纳入parser和Collector→Monitor→State回归；摘录fixture继续用于精确字段和异常变形测试，但不能独自证明完整exposition兼容。R5完整fixture及R4完整链路用例原样保留。

### 依据与责任边界

R2独立读取六份已保存完整响应并用识别引号/转义的计数器核对，未执行包内代码或连接服务：

| 模型（每项两轮） | 正文字节 | 样本数 | 最大行字节（不含换行） | 最大标签数 |
| --- | ---: | ---: | ---: | ---: |
| Chat | 64449 | 495 | 1054 | 36 |
| Embedding | 54707 | 431 | 1034 | 36 |
| Reranker | 54664 | 431 | 1034 | 36 |

六份中唯一超过旧16上限的series均是正常`vllm:cache_config_info`（Chat第588行，另两类第532行）。三份新完整fixture与各自原始第一轮响应逐字节一致，长度及SHA-256均匹配`full-response-provenance.json`；[本轮独立核验](evidence/r2-des005-full-fixture-audit.json)。R5的源码依据与单因素排除结果见其v1.5交接，本轮未覆盖或改写该证据。

原16阈值缺少完整正常响应的兼容验证，R2接受这是设计资源边界的遗漏，不归因于用户部署或R4没有遵循原契约。D-001的核心指标映射核对不能替代全响应兼容检查。64覆盖已确认36标签并留有有界余量；现有单行/正文总量继续限制内存分配，目标schema仍只有2/3标签。本轮不扩大版本兼容范围，也不承诺未来任意metadata宽度均被支持。

### 本轮同步产物

- `docs/design/vllm.md` → v1.3，修订§6、依据及修订记录。
- `src/joi_observer/collectors/vllm.py`仅更新公开契约注释并标明实施待办；**未修改执行常量16或解析逻辑**。去除docstring后的生产AST与起点一致，其他生产源码哈希未变。
- `tests/test_vllm_collector.py`将旧“17标签失败”用例按新契约修订，覆盖unknown/info/other-model的17、36、64合法值，65整体失败，边界处重复标签/非法转义/非法数值/数值超限，以及三标签业务schema多出第四项仍拒绝；增加公开常量须为64的断言。旧预期是被明确的R2契约修订取代，不是测试自行放宽。
- 未修改R4/R5交接、`test_vllm_collector_edges.py`、`test_vllm_full_response_integration.py`或任何fixture。保护文件哈希均与起点一致，见[起始快照](evidence/r2-des005-start.json)与[范围审计](evidence/r2-des005-audit.json)。没有构建、安装或替换wheel/服务器测试包。

### 实际验证

本地WSL Ubuntu-24.04、Python3.12.3、已有`~/projects/tmp/joi-observer-dev-0-venv/bin/python`；工作目录`/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`，保留pytest的DNS/connect防护。

```bash
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q \
  tests/test_vllm_collector.py tests/test_vllm_collector_edges.py \
  tests/test_vllm_full_response_integration.py --tb=short -rN \
  --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/r2-des005-contract.xml
```

实际 **188项：174 passed / 14 failed，0 errors / 0 skipped，exit1**；[输出](evidence/r2-des005-contract.txt)、[JUnit](evidence/r2-des005-contract.xml)。其中collector为136通过/10失败（公开常量16≠64，以及三类被过滤series×17/36/64共9项合法输入被旧限制拒绝）；R5完整parser回归38通过/3失败；R4完整链路1失败。14项均与当前仍执行16上限一致，不是导入/环境问题。负向边界在旧的更严格限制下通过，不能单独作为新64实现正确的证明；R4改动后必须连同正向边界重新运行。

本轮没有重复无关全量/安装测试。`git diff --check`通过；生产AST、常量与保护文件范围核对通过。该结果是设计修订后的待实现基线，旧7a4e950包仍含问题，不能据此宣称R5-004-005已关闭。

### 回交与待确认事项

接收角色 **R4**：请确认接受本决定，统一落实执行常量64并移除临时待实施注释，保留过滤前校验与目标精确schema；运行上述188项及必要全量回归，验证完整fixture、真实Collector→Monitor→State和使用完整正文的离线安装TUI链路，再构建并核验新wheel/测试包。R5回归中提到旧16标签测试的历史说明由后续维护时同步，原断言和完整样本不应删减。

R4实施/确认状态：**待回交**。R5-004-005仍待R4修复后由R5复验关闭。R4确认后，按人工指令再交R3核对计划；本轮不自动创建或通知其他角色聊天，也不修改他们的交接文件。

## v1.0～v1.3 首次设计与修订记录（历史，2026-11-02）

AGENTS路径元数据沿用原仓库，本轮所有产物写在已创建的worktree。开始时AGENTS.md已有用户将REQ-003改为REQ-004的修改，予以保留，未代改。没有修改需求范围、没有连接任何服务器、没有执行包内源码。

### 结论与采证

用户回传 `C:\Users\Xinyi_Lu\Downloads\joi-vllm-evidence.9UwOpl9Q.tar.gz`，SHA-256为 `69a51042dcbf641e59db5d0f3479376cb53133b911bfff5d37903f8a2aeeb408`。安全解包后保存到本需求的 `evidence/server-9UwOpl9Q/joi-vllm-evidence.9UwOpl9Q/`，完整材料被既有.gitignore忽略；未将归档内内容当作指令执行。

三个端点的12次HTTP读取均为200/curl退出0，版本与容器distribution均为0.31.0，模型身份一致。三个容器每份44个白名单源码文件全部通过manifest哈希校验，内容逐文件相同，没有白名单遗漏。具体样本、哈希、源码行号与推导边界见 [metric-evidence.md](metric-evidence.md)。

三类核心指标均有源码和样本依据，D-001无需因指标缺失退回R1。实采是单engine空闲窗口；多engine、增量、故障、恢复和重启规则依据源码定义设计离线用例，不宣称完成实机演练。Embedding是否包含完整tokenization不额外承诺，延迟精确限定为来源内部arrival_time到输出处理的范围。

### 产物

下列路径相对实际project_root；共享模块原位维护。

| 产物 | 内容与当前状态 |
| --- | --- |
| `docs/design/vllm.md` | v1.2模块设计、UML、精确映射引用、公共结果继承、Chat/Pooling引擎观测分型及HTTP/状态/窗口/显示接线契约 |
| `docs/dev-workflow/dev-0/REQ-004/metric-evidence.md` | 样本与源码证据、单位、STOP筛选、计时、多engine、重启局限 |
| 同目录 `view-contract.md` | 固定服务窗口槽位、列表、状态/颜色、历史时间分箱和边界 |
| 同目录 `collect-vllm-evidence.sh`、`server-evidence.md` | 已完成采证的方法留档；脚本由用户运行，代理仅作离线检查 |
| `src/joi_observer/collectors/vllm.py` | HttpResponse/HttpPort/AsyncHttpClient、parse_scrape、VllmCollector与工厂；解析/采集协变返回VllmCollectionResult，业务入口仍NotImplementedError |
| `src/joi_observer/data/vllm.py` | 不可变计数/延迟、EngineSample公共字段及ChatEngineSample/PoolingEngineSample专用载荷、同型引擎tuple、VllmCollectionResult、原有VllmSpec/模板及Accumulator骨架 |
| `src/joi_observer/data/vllm_window.py` | 差分和加权窗口接口，业务入口NotImplementedError |
| `src/joi_observer/data/models.py`、`data/state.py` | CollectionResult仅含key/failure，MetricCollectionResult携metrics；State完成普通指标子类、公共整失败与错误类型配对适配，vLLM派生计算专支尚未实现 |
| `src/joi_observer/collectors/hardware.py`、`collectors/docker.py`及8个既有测试文件 | 指标结果构造与返回类型迁移到MetricCollectionResult；failure改为关键字，既有业务算法及验收含义不变 |
| `tests/test_state.py`、`tests/test_monitor.py` | 分别27项/16项；公共结果构造、冻结、失败和分派用例已归入对应模块，重复行为并入既有场景 |
| `src/joi_observer/config.py`、`cli.py` | 新配置字段声明与HTTP工厂注入参数；配置解析和生产组合仍待实现 |
| `src/joi_observer/tui/vllm.py`、`tui/layout.py`、`tui/app.py` | 纯vllm_cells骨架、monotonic_now注入参数及amber基础映射契约；绘制/接线仍待实现 |
| `tests/test_vllm_collector.py` | 120项：真实样本/变形解析、HTTP状态与限制、取消、工厂、采集契约 |
| `tests/test_vllm_engine_samples.py` | 15项：公共字段、专用字段不存在、非法构造参数、冻结及部分缺失时保留子类 |
| `tests/test_vllm_state.py` | 65项：vLLM结果结构/构造、兄弟类型分离、State结果配对、模板、独立基线、窗口、重置、部分失败、原子性及引擎分型 |
| `tests/test_vllm_window.py` | 79项：计数差分、精度、加权均值、完整落窗、不可比较区间与数值边界 |
| `tests/test_vllm_config.py` | 11项：服务身份与展示名分离、旧配置兼容、有效/非法字段 |
| `tests/test_vllm_integration.py` | 4项：真实collector经Monitor/State、三模型独立采样、超时恢复、极大计数隔离、生产组合根 |
| `tests/test_vllm_view.py` | 53项：类型/单位/状态、固定槽、长名称分区、只读、历史与整页接线 |
| `tests/fixtures/vllm/0.31.0/` | 12份实采字节样本及README/provenance，保存原始来源行号和两级SHA；合成异常样本由测试构造并明确区分 |
| `tests/conftest.py`、`tests/test_shell_edges.py` | 默认禁止DNS/网络连接；首帧测试注入pending HTTP端口，保留原断言 |
| `docs/design/configuration.md`、`monitor-state.md`、`application-shell.md`、`hardware.md`、`docker.md`、`README.md` | 同步配置、类型继承、结果配对、组合根及面向使用者的计数/延迟含义；标明业务待实现 |

本轮提供结构、声明、注释、静态模板及黑盒测试，并完成公共结果类型迁移所需的构造/分派适配；未实现HTTP/Prometheus解析、差分窗口、vLLM State专支或显示业务。已有硬件/Docker采集算法及调度、保值、历史行为保留。HTTPX选择已在设计冻结；为保持既有离线安装锁一致，本轮不修改pyproject.toml/uv.lock、不安装依赖。

### 关键设计决定

1. 三类型负载数量均使用内部序列语义seq；pooling RATE仅取 `request_success_total{finished_reason="stop"}` 的差分，单位seq/s，排除abort/error/length/repetition。TTFT、queue和e2e各用自身sum/count，不能共用RATE分母。
2. Chat输入/生成Token使用独立累计量差分；输入沿用来源计数，包括其记录的缓存等Token。KV为各engine ratio算术平均×100，沿用官方聚合日志口径，不声称容量加权或GPU显存占用。
3. 延迟从来源内部arrival_time计至输出处理，排队是首次QUEUED到SCHEDULED；不声称客户端/网关/完整HTTP耗时。三类指标固定映射已足够设计，不需要制造业务负载或重启服务。
4. 公共CollectionResult仅有key/failure；MetricCollectionResult与VllmCollectionResult是兄弟子类，分别只持metrics和observation，不再有载荷互斥调用约束。普通ObjectSpec接受指标子类，VllmSpec接受vLLM子类；公共基类仅表示无载荷整失败，可用于任意spec。所有failure均为仅限关键字参数。State统一持有每模型、每指标组基线；成功观测不得缺少类型必需字段，局部失败保留旧失败值、独立有效组继续计算。任何failure保守写整点历史gap。
5. 首次、拓扑/epoch变化或计数回退不跨区间差分；过去已验证延迟区间仍自然过期。窗口只纳入完整落在最近60秒的区间，不作比例分摊或每秒均值等权平均。snapshot过期投影只读且不改revision。
6. 数字解析有字符/指数/展开位数上限。合法大整数造成派生float不可表示时，仅该速率为None，当前计数留作新基线；不能让数学入口的溢出异常终止Monitor，不伪造0或ERROR。
7. 每模型每轮依次GET直接origin的/version、/v1/models、/metrics，共享整轮timeout，不重试/跳转/用环境代理。HTTPX首次调用懒加载，可完全注入离线client；单响应2MiB，取消/关闭预算250ms。
8. name只作展示；可选served_model_name精确校验服务身份，省略回退name。固定服务布局与已有半页分区相容，不把真实方向键和完整主题实现混入本需求。
9. 保留用户明确的类图偏好：省略Monitor/MonitorState到CollectionResult的依赖线；使用标准UML关系，不在线上加解释标签。
10. EngineSample只含engine_id/running/waiting/queue；ChatEngineSample增加KV、输入/生成Token、TTFT，PoolingEngineSample增加完成序列数和完成延迟，Embedding/Reranker共用后者。不适用原始字段不再存在，None仅表示适用字段本次未取得；最终Metric的N/A模板保持不变。VllmObservation的engines必须同型、非空并匹配model_type，部分失败也不能携带裸基类、混合或错误的引擎子类。

### 验证证据

环境：本地WSL Ubuntu-24.04，Python3.12.3、pytest8.4.2，使用已有 `~/projects/tmp/joi-observer-dev-0-venv/bin/python`。运行目录为 `/mnt/d/Documents/codex_worktree/dev0-req004/joi-observer`。没有下载/安装包、没有启动vLLM、没有发送服务器请求；HTTP/DNS连接默认被测试防护拒绝，外部依赖只用原始字节端口替身。

```bash
~/projects/tmp/joi-observer-dev-0-venv/bin/python -m pytest -q --tb=short -rN \
  --junitxml=docs/dev-workflow/dev-0/REQ-004/evidence/pytest-consolidated.xml
```

最终全量实际结果：**1209项，894 passed / 315 failed，0 errors / 0 skipped**，exit1。输出见 [evidence/pytest-consolidated.txt](evidence/pytest-consolidated.txt)、[evidence/pytest-consolidated.xml](evidence/pytest-consolidated.xml)。与上次全量比较，失败用例ID集合完全相同，没有新增或删除失败用例；数量减少5项来自通过用例的重复合并。

| 范围 | 通过 | 失败 | 分类 |
| --- | ---: | ---: | --- |
| 通用及既有非vLLM专项测试（含并入用例） | 862 | 0 | 硬件、Docker、配置、状态/调度、日志、TUI和本地PTY无回归；State27项、Monitor16项均通过 |
| vLLM collector | 4 | 116 | 结构与provenance通过；116个业务入口NotImplementedError |
| vLLM引擎载荷分型 | 15 | 0 | 公共及专用字段、非法跨类型参数、冻结和部分缺失的结构契约通过 |
| vLLM config | 1 | 10 | 旧配置兼容通过；新键尚未加入解析器导致有效新字段/特定校验断言失败 |
| vLLM integration | 0 | 4 | Collector未实现及生产组合根尚未接入，触达真实Monitor/State后行为断言失败 |
| vLLM state | 10 | 55 | 静态模板、结果结构/构造及State类型配对通过；54个accumulator入口未实现，1个State派生计算专支尚未接入；引擎类型/部分失败用例均保留 |
| vLLM view | 0 | 53 | 52个纯view入口未实现，1个compose_frame接线断言失败 |
| vLLM window | 2 | 77 | 冻结载体通过；77个计算入口未实现 |

相对最初849项基线，REQ-004现净增加360项，净增45通过/315失败；失败中299项直接NotImplementedError，另外16项为配置/State/组合根/显示缺少新行为。均已分类为明确的待实现基线，不将NotImplementedError作为成功断言，不使用skip/xfail；没有导入错误、环境错误或既有功能失败。测试没有用预先算好的业务结果替换被测解析、差分、调度或显示；Monitor分派用例只在提交边界使用记录替身，单独验证通用调度不访问专用载荷。

早期窗口与单模块结果作为历史证据保留；最终全量结果优先。WSL `python -m compileall -q src tests`通过。采证工具的bash语法及9项离线源码导出检查通过（[source-export-validation.json](evidence/source-export-validation.json)）；只在合成文件树执行导出片段，未执行HTTP/Docker采证。既有.gitignore覆盖整个需求evidence目录。git diff --check通过。

### 限制与下一步

此前v1.1按用户确认将v1.0的可选vllm载荷方案替换为公共基类和两个兄弟子类。旧指标构造点已显式迁移为`MetricCollectionResult(key, metrics, failure=...)`，vLLM使用`VllmCollectionResult(key, observation, failure=...)`；未保留旧字段别名或会混淆参数顺序的兼容构造。当时独立的24项公共类型/分派测试已在本次按职责归并。

此前v1.2仅按用户“先改EngineSample”的授权拆分引擎载荷及同步必要引用、测试、接口注释和设计图。状态测试分别构造Chat与Pooling样本，不再同时填充两类专用字段；新增15项结构检查和20项待实现的消费边界/部分失败行为用例。VllmSpec默认字段、模板、Monitor声明核验、RuntimeComponents、Failure及其他审查建议均未调整。接口、类图语义仍以v1.2为准，最新测试组织及全量基线以本交接v1.3为准。

本次仅整理测试和引用说明，未改生产代码。已删除原独立公共结果测试文件：通用构造/状态规则并入test_state，vLLM专用结构和State配对并入test_vllm_state，Monitor转交并入test_monitor。重复合并映射：部分失败保值/gap并入既有部分失败场景（注入确定时钟）；公共/指标整失败并入已有失败恢复场景的参数化；vLLM结果被普通Spec拒绝并入已有原子拒绝场景；timeout/unexpected的无载荷基类断言并入已有真实状态链路测试。以上净减少5个重复case，外来载荷拒绝、failure关键字、冻结/replace、完整指标误配VllmSpec和首次公共失败等独立覆盖均保留。

当前无阻止R3规划的待决输入，ready仅表示R2设计、骨架与测试基线具备交接条件，不表示REQ-004业务已经实现或测试全绿。

接收角色 **R3**：请读取本交接、模块设计、metric-evidence及view-contract，在本需求目录编写 `plan.md` 与 `handoff-r3.md`，规划解析/HTTP、状态与窗口、配置/组合根、服务展示及离线用例转绿。R4实现真实HTTPX后端时需成套更新pyproject.toml、uv.lock和离线wheel集合，验证真实依赖的流式解压、取消、证书校验及关闭行为；本轮factory替身不能证明这些后端集成已经完成。

实采仅含单engine无新完成量的窗口；真实多engine负载、不可见重启和HTTP传输取消未演练。指标创建时间和process_start不是完整engine epoch，指标未暴露的重启不能保证检测；不得在实现或验收中把此局限扩大成“所有重启已覆盖”。这些边界已有确定设计，不需要当前再连接服务器。

本轮未向其他聊天发消息，也未自动推进R3/R4；由用户手动交给下一角色。
