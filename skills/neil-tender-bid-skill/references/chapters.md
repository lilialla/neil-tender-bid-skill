# 两章生成与局部变更

`scripts/chapters.py` 是可直接导入的标准库模块。它负责选择有限输入、确定性模板替换、引用变更定位和结构化检查；采购理解、证据证明力、技术方案充分性及静态模板中的实质承诺仍须复核。没有外部请求、OCR 或自动提交。

## 一份章节清单

继续使用九列要求 CSV；不要把材料、人工决定、签章或递交状态塞入该 CSV。JSON 章节清单最少包含 `shared`、`materials`、`chapters`、`global_constraints`。以下均为合成示例：

```json
{
  "shared": {
    "lawyer": {"value": "合成人员甲", "status": "confirmed", "source": "合成选人决定"},
    "response_hours": {
      "value": "2小时", "status": "confirmed", "source": "合成时限决定",
      "kind": "commitment", "approval": {"by": "测试负责人", "decision": "approve"}
    }
  },
  "materials": {
    "proof-a": {
      "path": "synthetic-proof.pdf", "sha256": "填写实际SHA256",
      "pages": [1, 2], "status": "confirmed", "person": "合成人员甲"
    }
  },
  "chapters": [
    {
      "id": "team", "path": "商务/团队", "output": "team.md",
      "requirement_ids": ["R1"], "shared_keys": ["lawyer"], "material_ids": ["proof-a"],
      "template": "拟派人员：{{lawyer}}。",
      "material_checks": [{"material_id": "proof-a", "requirement_id": "R1", "person_key": "lawyer"}]
    },
    {
      "id": "service", "path": "技术/服务安排", "output": "service.md",
      "requirement_ids": ["R2"], "shared_keys": ["lawyer", "response_hours"], "material_ids": [],
      "template": "{{lawyer}}负责服务响应，时限为{{response_hours}}。"
    }
  ],
  "global_constraints": [
    {"scope": ["service"], "requirement_ids": ["R2"], "text": "保留原文的完整限制条件。"}
  ]
}
```

示例 SHA256 是说明占位符，运行前须替换为实际材料哈希；校验器不会将它当作有效来源。

- `status: confirmed` 与非空 `source` 表示当前采用且有依据的确定值；其他状态、空值或无来源的值保持待核。人员决定和证据实际上是否取得分别记录。
- `kind: commitment` 还需 `approval.by` 及 `approval.decision: approve`；批准继续制作不等于批准具体承诺。未批准承诺只生成 `【】`，问题写入内部 `gaps`。
- 报价使用 `kind: quote`、明确 `round`、数值 `value`，可补 `currency`（默认 `CNY`）和 `quote_group`（默认 `total`）。相同轮次、同组报价金额或币种冲突会报错；不同轮次可以并存。当前章节仍须明确引用采用值。同一轮已被替代的候选用非 `confirmed` 状态保留，不能同时标成当前采用值。
- `pages` 是实际采用的原材料页号列表。材料 `status: confirmed` 应来自已完成的原件核对；本模块检查引用与元数据，不重新打开或鉴定原文件。G1 及装配时须另验文件、实际页码和哈希。
- `material_checks` 可用 `subject_key`、`person_key` 指向已确认共用值，核对材料的 `subject`、`person`。`period_start_key`、`period_end_key` 指向 `YYYY-MM-DD` 日期，核对材料的证明期间是否覆盖所需期间。不能用合同标题相似代替这些核对；有其他证据条件时仍需原页审查。
- `global_constraints.scope` 使用章节 ID 列表，确实全局适用时用 `["*"]`；适用原文由 `requirement_ids` 一起完整带入。错误章节 ID 或要求引用会明确报错，不能默认该约束没有影响。
- 共同约束涉及批准时限、人员或材料时，用该约束的 `shared_keys`、`material_ids` 明确引用；`text` 中的 `{{key}}` 也会带入对应共用值。这样修改时限会使受该约束的全部章节失效。自由文字中的隐含依赖仍须由操作者识别，脚本不猜测。
- 证件有效性、执业年限和滚动业绩期间等时间敏感章节，通过已有 `shared_keys` 明确引用适用时点及必要规则版本，并给这些共享值记录来源。顶层 `as_of`、`rules_version` 会使文件集检查失效，但不会自动成为每章的生成输入；章节依赖变化按实际声明识别。
- 章节 `decisions` 可记录 `[{"by":"负责人","action":"continue","reason":"先生成工作稿"}]`。检查问题保留该决定；不会把问题改为通过，也不会把未取得证明写成已取得。

### 逐项处置与完整映射

同一清单可用 `requirement_dispositions` 数组登记不单独生成章节的要求，补充默认完整映射；不另建台账。每个现行要求最多一条，保留旧文字字段不妨碍增加以下固定字段：

```json
{
  "requirement_id": "R4",
  "type": "execution",
  "status": "pending",
  "location": "执行清单第1项",
  "basis": "采购原文要求现场出示原件；尚待经办人确认执行"
}
```

- `type` 限 `response`（正文）、`proof`（证明）、`execution`（执行事项）、`rule`（适用规则）、`not_applicable`（不适用）。
- `status` 限 `verified`、`pending`、`blocked`、`not_applicable`。`basis` 始终须有实际依据；`location` 须为字符串，待核或阻断时可空。
- `verified` 须为适用类型且有实际响应、证明、执行事项或规则的位置；它记录操作者已核的处置，不证明未来执行已经发生。`not_applicable` 状态须用同名类型并写明原文依据，可无响应位置。单纯登记编号、总括接受或无依据结论不能记为通过。
- 未知、被补遗取代、重复或带首尾空格的要求编号，未知类型／状态，缺依据及已核却无位置，均报 `invalid_disposition`。`pending`、`blocked` 和要求解释未确认继续返回真实问题。

完整 `chapters-check` 合并章节映射与有效逐项处置检查全量覆盖；已经映射到章节的要求仍检查该章节实际结果，处置不掩盖 `missing_result`、过期、事实或材料问题。`--chapter` 仅核所选章节，不将其他处置的待办混入局部结论。`status` 另行核对处置问题并绑定其版本，人工 G1—G6 通过记录不能抹去待核、阻断或无效处置。

## 模块接口

命令行与同一份数据对应，输出路径须为新文件：

```bash
python3 "<skill-root>/scripts/tender.py" packet --checklist "<章节清单JSON>" --requirements "<九列总账CSV>" --chapter team --out "<本章输入JSON>"
python3 "<skill-root>/scripts/tender.py" render --packet "<本章输入JSON>" --out "<本章结果JSON>"
python3 "<skill-root>/scripts/tender.py" chapters-check --checklist "<章节清单JSON>" --requirements "<九列总账CSV>" --results "<按章节ID索引的结果JSON>"
python3 "<skill-root>/scripts/tender.py" impact --before-checklist "<原清单>" --after-checklist "<新清单>" --before-requirements "<原总账>" --after-requirements "<新总账>"
```

`render` 结果的 `content` 是正文，可另存为本章 Markdown 再交现有文档工具；`gaps` 等字段只留内部。模型自由起草使用同一 packet 而不必调用模板渲染。

只核对正在制作的章节时，给 `chapters-check` 增加 `--chapter team --chapter service`；它仍检查这些章节的全部适用约束、共用值及证明，但不把其他尚未编制的章节报成遗漏。未给 `--chapter` 时保留完整总账映射检查。局部检查不能用于宣称全本响应完整，整合前仍应运行默认完整检查；不另复制一份精简总账。

| 函数 | 输出与用途 |
|---|---|
| `read_requirements(csv_path)` | UTF-8/BOM CSV 转列表；表头必须按规划的固定九列顺序，ID 唯一，必需值非空，要求状态使用规划中的四种中文状态。 |
| `prepare_packet(checklist, requirements, chapter_id)` | 深复制本章及适用全局规则的完整要求、来源、必要材料和共用值。未知引用抛出 `ValueError`。 |
| `render_chapter(packet)` | 返回 `content`、`requirement_ids`、内部 `gaps`、`used_values`、`dependencies`、`input_fingerprint`；正文只作 `{{key}}` 替换，不调用模型。 |
| `impact(before_checklist, after_checklist, before_requirements, after_requirements)` | 返回 `affected`、`unchanged`、`uncertain`、`issues`；比较实际选中输入，未知引用放入待核范围。 |
| `validate_chapters(checklist, requirements, results, chapter_ids=None)` | `results` 按章节 ID 索引；可显式限定检查单元，默认检查全总账映射。返回问题列表，不作递交放行决定。 |
| `score_performance(candidates, rule)` | 根据已确认的按项计分规则，按独立 ID 去重，计算有材料支持的预估分及默认一项备选。 |

`prepare_packet` 也会识别模板直接引用及材料核对所需的共用字段，避免人工漏写依赖导致错误声称无影响。它不会带入其他章节正文或无关材料。输入指纹用于识别使用旧输入的结果，不证明来源或人工批准的真实性。

模板首次采用时，先复核其中静态事实和承诺；变化后复核变化部分。将重要事实、报价、时限及实质承诺写成有来源的共用字段，避免把这些内容硬编码在模板中。任意长正文可由 Codex 使用 packet 另行生成：章节不设 `template`，保留相同结果字段，`validate_chapters` 会返回语义复核待核项，不把任意文本当作已验证模板。不得用已有的 `input_fingerprint` 掩盖真实输入变化。

若检查列表为空，只表示已提供结构化条件下没有发现本模块覆盖的问题；它不等于 G1—G6 全部通过，更不证明证明附件已装配、签章或递交。正文缺口、未映射要求、待澄清要求、错人错期、过期结果和同轮报价冲突均需如实进入现有清单。

只生成 packet 并不自动建立独立模型上下文；确需隔离时，单独调用只提供 packet 的执行上下文。继承整段任务历史的子任务不能称为隔离测试。

### 独立生成的实际输入与输出

模型自由起草时，可在所属章节增加三个字段，`packet` 会深复制并纳入输入指纹；其变化只使实际接收该字段的章节过期：

- `source_context`：本章所需的完整原文范围，含来源名称、哈希、页码、续页、表头及注释。总账行不足以保留语义时在这里补全；不要把整本来源无差别塞入。
- `format_skeleton`：原编号、小标题、空白正文槽位或表头，以及必要的版式限制。不得夹带已经写好的章节答案；需要旧稿作局部修改时明确记为修改测试。区分整节／整封文书生成与既有正文槽回填；回填时逐槽说明由装配端保留的标题、抬头、编号、签章及落款，输出仅含槽内内容。装配前核对实际槽位边界，六字段有效不代表可直接回填。
- `output_contract`：正文输出形态、要求回应位置、证明使用、共享值、未核项及自主拟订承诺的返回约定。每个要求区分本节直接回应、共同背景、他节依赖或待核；只有实际核见的他节响应才能记为已满足。

这三个字段保存操作者选定的生成内容，不会自动解析隐含的共享值或材料依赖。人员、时限等仍由 `shared_keys`、`material_ids` 和适用共同约束声明；契约、骨架说明及活动共同约束按共享字段名说明角色及取值来源，不另写一套固定人名，骨架不硬编码未知事实。共享值变化时，操作者须重建适用的 `output_contract`，核对旧正文及跨节限制与新值是否冲突；上一轮 `prior_output`、旧变更方向或“某槽位不得修改”等一次性约束，仅在本轮仍适用时保留。脚本的影响定位和指纹不能识别或消除这些语义冲突。保存输入文件后才启动不继承历史正文的生成上下文；记录实际输入哈希及独立输出，再按采购原文核对后装入原格式。人工补充了 packet 的内容就须更新章节清单并重新导出，不能沿用原指纹掩盖变化。

`output_contract` 是供生成者与操作者执行的契约，本模块不自动验证这些自定义字段或自由正文的语义。原生页面复核、证据是否足够和真实批准状态仍需分别记录，不以新鲜度检查通过替代。

生成前，将接入 `chapters-check` 的六个固定结果字段及类型明确写入实际 `output_contract`：`content` 字符串、`requirement_ids` 字符串数组、`gaps` 数组、`used_values` 对象、`dependencies` 对象及 `input_fingerprint` 字符串。后两项使用实际输入中的值，`used_values` 按共享字段名映射到实际采用值，不返回对象数组。`results` 顶层须为章节ID到结果的对象。字段缺失或错型报 `invalid_result` 并标出 `field`，不自动转换或补猜；选中结果无效时，仍继续报告其采购、共享事实和材料问题。此检查不验证 `gaps` 元素或自定义正文槽位，正常自由正文仍报 `semantic_review_required`。

契约应明确正文与内部记录的边界：测试口径、待批准、待核资历和他节尚未检查等编制说明放入 `gaps`，不塞入供应商响应正文；正文仅写有依据的事实和拟执行安排。未定的关键必填事实使用空白占位，不用编制提示代替响应。复核时保留原文的义务组合，例如“并出具”不能改成可择一的“或出具”；自主设计的工作流程与已确认事实分别记录。

### 履约条款的多个落点

同一义务既出现在承诺摘要又出现在执行方案时，可由一个有界单元统一生成两个落点。摘要保留实质承诺，执行段明确职责及记录方式；共同采用相同要求和事实，不因章节分别制作而产生互相矛盾的例外。

在现有逐项回应中，针对会改变履约结果的差异核对“对象、触发点、动作、例外”。完成一项服务、服务期届满、提前终止以及人员内部交接是不同节点；不能统称“项目结束”。可留存、可披露等例外须保留原文条件，不能由“按约定处理”替代具体限制，也不能自行补充年限、上限或许可。

先判断采购要求的是本次附入的证明、拟用表样，还是未来履约形成的台账、签收及处置记录。只要求未来形成的成果时，可先写责任和流程，将未发生的执行状态留在内部记录；不编造已取得的成果，也不把它机械列成本次缺失附件。采购确实要求投标时提供的表样或既有证明仍须准备。

本轮发现、处理规则、实际复测证据和是否采纳进Skill写在同一章节清单；结论只汇总有结果的事项。通用修正注明源码落点及验证范围，项目特有事实、尚未验证的建议留在业务记录，不把每个样本问题都升级为全局规则。

字数预算只是排版预估。原生导出新增页面时，先定位哪段溢出及目录、PPT、报价和抽页引用的影响；可用准确的完整条款引用替代重复范围列举，但不能省略不同触发点、实质动作或例外来凑原页数。仍需增页时接受合理分页，核对引用的起点、终点和完整范围，即使章节起点未变也要核对终点；分页稳定后一次更新受影响引用。比较页面正文时按各页真实纸张尺寸及页脚位置处理，不能用统一 A4 高度裁切后判断一致。输入契约或正文被改后重新绑定版本；拿原输出作收敛修改应记为修改测试，保留首次结果及原生分页证据。

## 计分输入

```json
{
  "rule": {
    "status": "confirmed", "source": "合成评分原文R3",
    "points_per_item": "1.5", "max_points": "4",
    "subject_type": "person", "subject_id": "person-a",
    "start_date": "2024-01-01", "end_date": "2026-09-01"
  },
  "candidates": [
    {
      "id": "contract-1", "subject_type": "person", "subject_id": "person-a",
      "completed_on": "2025-01-01", "status": "confirmed",
      "source": "合成合同关键页", "page_count": 2
    }
  ]
}
```

`subject_type` 限于 `firm` 或 `person`，且 `subject_id` 必须匹配。独立 ID 由原件核对确定；同一合同的不同扫描件或副本使用同一 ID，重复展示不增加计分。同一 ID 的主体、期间、类别或确认状态互相矛盾时，整项保持待核，不任意取第一份计分。

当前公式仅处理每项固定分及该项上限：`ceil(max_points / points_per_item)` 是满分最低数量，默认另准备一项合格备选。合格性是既有人工／原页判断的输入；程序进一步核对结构化主体、`service_type`（规则规定时）和完成日期窗口，不能推断合同性质或人员是否实际参与。

`start_date` / `end_date` 在此函数中核对的是 `completed_on`，含首尾日。规则按签订日、服务期间或其他口径计分时，先采用相应原文口径核对，不把完成日期模型用于不同规则。复杂公式、主观分和未知竞争报价不由本函数猜测。

规则可补 `max_count` 和 `page_limit`。按输入候选顺序选取，遇到数量、页面不明或页数限制时列明限制；不会为凑满分突破上限。输入顺序由实际采用策略确定，模块不优化证明组合或自动增加保密材料。输出包括实际选择、备选数、预计失分、排除原因和限制；`score` 永远是有材料支持的估计，不是评委给分。保密、新承诺和工作量例外由人在现有清单简记决定。

## 合成验证

仓库根目录运行：

```sh
python3 -m unittest discover -s tests -p test_chapters.py -v
```

测试覆盖两个共享人员章节及一个无关章节、一次局部变更、待定值占位、错人错期、缺映射、多份合同去重、报价轮次、未批准承诺和限制后的实际计分。它们证明所列机制的合成行为，不等于真实样本验收。
