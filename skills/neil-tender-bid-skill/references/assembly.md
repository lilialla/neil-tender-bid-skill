# PDF 装配、抽页与状态记录

这些命令处理已生成的 PDF，不创建业务承诺、DOCX 模板或 PPT。先完成适用正文与证明核对，再按本项目需要使用。PDF 依赖为 `pypdf==6.12.2`；无现成依赖时可用 `uv run --no-project --with pypdf==6.12.2 python <脚本> ...`，不修改全局环境。

## 装配与抽页

`parts` 是采用页面的 JSON 数组，顺序就是装配顺序。每份来源须填写当前实际哈希，页号从 1 起；明确需要外部重复展示时可重复页面。原件和已有输出均不覆盖。

```json
[
  {"path": "/private-project/chapter.pdf", "sha256": "实际源文件SHA256", "pages": [1, 2]},
  {"path": "/private-project/proof.pdf", "sha256": "实际源文件SHA256", "pages": [1, 3]}
]
```

```bash
python3 "<skill-root>/scripts/tender.py" assemble --parts "<采用页列表JSON>" --out "<新的PDF>" --manifest "<新的装配记录JSON>"
python3 "<skill-root>/scripts/tender.py" derive --master "<母稿装配记录JSON>" --stamp-pages "1,3" --out-dir "<新的内部派生目录>"
```

装配结果含 `path`、`sha256`、`page_count` 和逐页 `page_map`，直接放入现有章节清单的 `files`。页映射记录来源路径、哈希、原页号和输出页号。`derive` 先核对实际母稿页数与记录一致，再生成待用印部分和剩余常规部分；两者均回指同一母稿。全稿都需用印时常规部分为 `null`，不造空 PDF。

原页的视觉内容、固定表式、页眉页脚、目录及内部页码不会因为合并自动正确；需要原生文档工具分页、编目录后重新核对。上述脚本只核对文件和页映射，不提供“排版已经验收”的结论。

## 同一章节清单中的状态

继续在章节清单附 `files`、`checks` 和 `execution`。顶层 `as_of` 记录本次适用时点，`rules_version` 记录本次采用的规则版本；时点、规则、事实和采用材料改变后更新清单。不能把过期证件的旧适用时点沿用到新递交日期。

`files` 仅为本轮当前候选的扁平数组，每项直接含非空 `path` 和实际64位 `sha256`，可另保留用途、页数和页映射。历史文件单列 `reference_files`，供查阅，既不参与当前 `files_digest`，也不自动成为当前候选。把旧版文件组嵌在 `files[].files` 会返回“文件清单结构”阻断；工具不静默展开旧件。采用证明的 `path: null` 如实报告缺失，不推断本地路径。

```bash
python3 "<skill-root>/scripts/tender.py" status --project "<来源与要求项目目录>" --checklist "<章节清单JSON>" --stage signing
```

阶段参数为 `draft`、`signing`、`submission`、`submitted`。命令实时检查采购原件、要求总账、冻结状态及 `requirement_dispositions` 的待核／阻断／无效记录，并比较当前共用事实、采用材料与检查绑定。第一次运行返回当前 `files_digest` 和 `basis_digest`；它们是这组文件及上游依据的身份，不是检查或人工确认。当前文件结构无效时 `files_digest` 为 `null`，不产生有效候选身份。

每项适用检查完成后，由操作者在同一清单记录：

```json
{
  "gate": "G5",
  "item": "固定表式和证明页实际装配",
  "result": "通过",
  "evidence": "实际核对文件、页码和结果；此处不是可直接采用的检查证据",
  "stage": "signing",
  "files_digest": "受检文件集身份",
  "basis_digest": "受检来源与事实身份"
}
```

每个 G1—G6 都需要当前阶段的适用检查或有依据的不适用记录。不得把上例批量填成六个“通过”代替检查。缺项、待核、阻断、旧版本和未冻结要求都会保留问题；PDF 有文件不等于已通过 G5。

`execution.continue_decision` 可以简记真实负责人、具体决定、范围与未满足项。它使提前编制的待签章稿按人的决定被如实表述，不把检查改为通过。要登记人工批准递交，使用 `execution.submission_approval`，含真实 `confirmed_by`、`basis`、当前 `files_digest` 和 `basis_digest`。脚本不能认证这些文字，应来自本次用户或指定负责人的实际决定。

登记实际递交使用 `execution.submission`，含真实 `confirmed_by`、`basis`、所递交文件的 `files_digest`，以及对应凭据 `path`、`sha256`。凭据必须存在并一致，不能由工具创建一份“已递交”文件充数。有些业务只有人员确认时，可先如实记录说明并保持凭据待补，不伪造回执。模拟测试的证据只存在隔离测试中。

已实际发生的递交与检查是否全部通过是两件事，所以有可靠递交记录时可以显示“已递交”并同时保留检查缺口；不会推定采购人接受。签章回传与母稿内容对应核对由人和现有文档工具完成，本模块不鉴定签名、印章或权限。

命令退出码 `0` 表示本次请求的确定性检查无待核/阻断；`1` 表示如实返回了检查问题；`2` 表示输入或执行错误。退出码不是对外执行授权。
