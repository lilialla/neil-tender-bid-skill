# neil-tender-bid-skill

中文招标、采购、询价、磋商的本地辅助。完整读取采购原件，拆成可以回读的要求总账，按要求和材料制作响应章节，定位一次局部返工，并核对文件集和用印派生。

Codex 逐段理解来源并生成候选。脚本核对文件、覆盖、引用和版本。资格缺口、解释疑点和评分取舍由人决定。脚本检查通过，不证明拆标完整、证据会被认可，或投标成功。

当前版本 `0.1.10`。

## 能做的事

- 登记采购正文、附件、补遗和有效澄清，核对哈希、页数和逐段覆盖。
- 把原子要求写入固定的九列 UTF-8 CSV。同一项的条件、证明、后果和补遗留在同一行。
- 导出单章所需的原文、格式骨架和输出契约，供模板替换或按原文起草。
- 一次变更只更新实际引用到的章节、装配、目录和抽页。
- 装配已经生成的 PDF，从同一母稿抽出用印页，并分开记录工作稿、待签章、批准递交和已递交。
- 关联已经下载的 MinerU `content_list` v1。这里不上传，也不重跑 OCR。

## 不做的事

- 不从关键词自动生成采购要求。原文要逐段读完。
- 不生成 DOCX 或 PPT，也没有通用 Word 模板引擎。正式文书用当前环境里已有的文档工具。
- 不签章、不递交、不外发。这些要另有明确授权。
- 不把真实采购文件、响应文件、人员材料、证照、报价或会议转录放进本仓库。

## 三份数据

业务目录放在本仓库之外。

| 文件 | 内容 |
|---|---|
| `sources.json` | 来源身份、哈希、页读取和覆盖 |
| `requirements.csv` | 九列要求总账 |
| `chapters.json` | 共用事实、材料、章节、逐项处置和当前文件 |

`chapters.json` 从制作章节时开始用，并且是当前章节清单的固定入口。带日期的旧清单只作历史来源。材料、签章和递交状态不写入九列表。

## 三段工作

1. **Phase 0。** 读完当前控制来源，写成九列总账。G1/G2 达到后，等人冻结一次。没有确认就保持工作版，不把工作版写成已验收。
2. **Phase 1。** 用已冻结总账做两章响应，并回放一次标明的局部变更。两章通过只说明这个范围可用。
3. **Phase 2。** 补齐本项目需要的主文件、独立报价和 PPT 等，再做 PDF 装配、抽页和执行状态核对。

真实报价、签章和尚未补上的事实留在业务目录。工具测试结束，不等于一份标书已经做完。

## 安装

把 `skills/neil-tender-bid-skill` 复制到本机 skills 目录。Codex 使用 `~/.codex/skills/neil-tender-bid-skill`。目标目录已存在时先核对差异，不要直接覆盖。

需要 Python 3.10+。来源、总账和章节检查使用标准库。PDF 装配需要 `pypdf==6.12.2`，见 [requirements.txt](requirements.txt)。

```bash
uv run --no-project --with-requirements requirements.txt \
  python skills/neil-tender-bid-skill/scripts/tender.py --help
```

入口说明是 [skills/neil-tender-bid-skill/SKILL.md](skills/neil-tender-bid-skill/SKILL.md)。运行子命令前先看该子命令的 `--help`，不要按名称猜参数。

## 从一份采购文件开始

下面的路径换成这次材料的实际位置。`init` 拒绝覆盖已有工作目录。它只建立待核来源和空总账，不提取要求。

```bash
python3 skills/neil-tender-bid-skill/scripts/tender.py init \
  --project "<新的私有工作目录>" \
  --source "<采购文件.pdf>"

python3 skills/neil-tender-bid-skill/scripts/tender.py check \
  --project "<私有工作目录>" \
  --full
```

扫描件已经有与原 PDF 字节相同的 MinerU 全本结果时，初始化后再关联：

```bash
python3 skills/neil-tender-bid-skill/scripts/tender.py attach-ocr \
  --project "<私有工作目录>" \
  --source "<已登记采购原PDF>" \
  --input "<实际提交OCR的全本PDF>" \
  --result "<content_list.json>"
```

只接受与登记原件字节相同的全本，一页对一页。关联后各页仍待对照原页核对。修正字段和行号规则见 [扫描 PDF 的既有 OCR 结果](skills/neil-tender-bid-skill/references/workflow.md#扫描pdf的既有ocr结果)。

然后按 Skill 逐段阅读，填写 `sources.json` 的覆盖记录和九列 `requirements.csv`。图表原页仍要看。各命令拒绝覆盖已有输出；修订时另选新路径。

操作细节：

- [来源、总账和阶段约定](skills/neil-tender-bid-skill/references/workflow.md)
- [两章生成与局部变更](skills/neil-tender-bid-skill/references/chapters.md)
- [PDF 装配、抽页与状态](skills/neil-tender-bid-skill/references/assembly.md)

## 命令

| 命令 | 作用 |
|---|---|
| `init` | 登记本地来源，建立空要求总账 |
| `attach-ocr` | 关联既有 MinerU 全本结果 |
| `check` | 查 G1/G2。全页标记不等于没有漏项 |
| `freeze` | 登记一次真实的人工冻结 |
| `replay` | 按稳定编号比较首次候选和复核总账 |
| `packet` | 导出本章需要的原文、约束和材料 |
| `render` | 只替换模板中的 `{{key}}`，未定值留空 |
| `chapters-check` | 查映射、共用值和材料，不代替通读正文 |
| `impact` | 标出依赖发生变化的章节 |
| `assemble` | 按页列表合并 PDF，并记录页从哪一页来 |
| `derive` | 从同一母稿拆出用印页和常规页 |
| `status` | 按阶段核对文件、检查记录和递交依据 |

`chapters-check --chapter <章节ID>` 只查正在做的章节，可重复指定。不带该参数时查整本映射。局部通过不能当成全本完成。

## 检查通过是什么意思

| 检查 | 看什么 |
|---|---|
| G1 | 控制来源、版本、能否读取 |
| G2 | 要求能否从原文反查，含跨页、脚注、勾选和附件 |
| G3 | 必需回应和证明是否出现，对象、时间和形式是否对 |
| G4 | 主体、人员、期限、承诺、同轮报价是否一致 |
| G5 | 目录、页序、表式、附件和版式能否阅读 |
| G6 | 受检文件是不是当前这套，旧件有没有处置 |

退出码 `0` 表示这次确定性检查没有待核或阻断。`1` 表示如实报出问题。`2` 表示输入或执行错误。退出码不是递交许可。

文件名里的“定稿”、检查通过，或一份模拟回执，都不等于已经签章、已经递交，或采购人已经接受。

## 测试

```bash
uv run --no-project --with-requirements requirements.txt python -m unittest discover -s tests
```

测试只用合成文字和运行时生成的 PDF。`0.1.10` 记录的结果是 81 项通过，覆盖来源覆盖、补遗替代、冻结后换源、共享事实、错人错期、计分去重、报价轮次、PDF 页序、用印抽页，以及 OCR 全本关联。自由撰写的正文仍要人工看。这组测试不证明一份新的采购文件没有漏项。

## 许可与上游

本仓库的代码和说明是独立编写的，目前没有选择开源许可证。仓库公开，只表示源码可以查看。

方法上参考 [Sigma Legal Bid Workflow](https://github.com/kwf18423059038-pixel/sigma-legal-bid-workflow) 的 `v0.2.1`（`9cf05be62d9bd2363261658c4c291a6e572d8cf4`）。没有复制上游代码或文档正文，也不自动跟随上游更新。参考范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
