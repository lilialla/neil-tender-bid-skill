# 招投标 Skill 工具

面向律师团队的私有 Codex Skill。目标是减少采购要求遗漏、材料错配和重复返工，并保留人的业务决定权。

## 当前状态

`0.1.5` 为本地辅助试用版。已实现采购来源清单、逐范围覆盖与九列要求总账检查，章节的限定输入、共用值生成和局部变更，以及现有 PDF 的装配、用印抽页和真实状态记录。本版仅修正版本接续、生成契约更新及分页引用的操作规程，不扩张代码能力；自由正文的实质回应和原生页面仍需复核。

真实业务回放与人工冻结在独立私有目录办理，结果不进入本仓库。合成测试和工具安装不代表真实样本已验收，也不代表已签章、递交或被采购人接受。当前工具不会自动从关键词生成采购要求：Codex 必须完整阅读来源、起草候选并处理实质疑点。

## 实施路线

1. Phase 0：完整读取采购来源，形成来源覆盖记录和九列要求总账；G1/G2 与真实人工冻结分开。
2. Phase 1：完成两个关联章节的要求映射、独立上下文执行与局部返工验证；真实阶段验收依赖前阶段冻结。已获授权的内部历史回放可保留明确测试假设继续，不能伪造冻结或把有限测试写成真实验收。
3. Phase 2：用现有文档工具完成单项目所需文件集，再进行 PDF 装配与分阶段检查。尚未实现通用 Word 模板引擎、自动 PPT 生成器或外部递交。

## 使用

Skill 入口：[skills/neil-tender-bid-skill/SKILL.md](skills/neil-tender-bid-skill/SKILL.md)。安装时将该目录复制到独立的 Codex skills 目录；若同名目标已存在，先核对，禁止覆盖。源码始终在本仓库维护。

脚本使用 Python 3.10+；除 PDF 功能需要 `pypdf` 外，核心实现使用标准库。可使用已有环境，或用 `uv` 的隔离运行环境：

```bash
uv run --no-project --with-requirements requirements.txt python skills/neil-tender-bid-skill/scripts/tender.py --help
```

从一个新的私有工作目录开始；命令中的路径须换成本次材料的准确位置：

```bash
python3 skills/neil-tender-bid-skill/scripts/tender.py init --project "<新的私有工作目录>" --source "<采购文件.pdf>"
python3 skills/neil-tender-bid-skill/scripts/tender.py check --project "<私有工作目录>" --full
```

接着按 Skill 逐段读取原文，填写同一 `sources.json` 的覆盖记录和九列 `requirements.csv`。需要的图表原页仍须核对。签章、递交与真实材料云 OCR 依具体授权，不由安装或命令通过推定。

后续操作见 [章节与局部变更](skills/neil-tender-bid-skill/references/chapters.md) 和 [PDF 装配与状态](skills/neil-tender-bid-skill/references/assembly.md)。各命令拒绝覆盖已有候选输出；修订请选择新的版本路径。

局部编制时使用 `chapters-check --chapter <ID>` 只检查正在处理的章节，默认不带该参数仍检查全总账映射。内部测试可保留真实原文的待核状态，使用明确的测试假设验证后续生成；无需为测试伪造一次人工冻结。

## 验证

```bash
uv run --no-project --with-requirements requirements.txt python -m unittest discover -s tests
```

测试只使用合成文字及运行时临时生成的 PDF，覆盖脚注漏处置、跨页引文、损坏来源、补遗替代、冻结后换源、共享事实与全局约束失效、错人错期、重复计分、报价轮次、PDF 页序与用印抽页、人工继续及递交凭据。命令行闭环从合成来源初始化一直运行到候选状态，再变更来源确认原检查失效。

另以两个不继承任务历史的独立执行上下文读取各自合成章节输入，实际生成团队与服务安排正文；主任务核对了人物、时限、复杂事项例外及未引入无关报价。自由正文仍返回语义待核，未把模板或代码验证当作文本自行批准。

这些检查不能证明任意采购文件绝对无漏项、评委认可证明、主观得分或签章真伪。自由正文、表格关系、证明力、模板静态承诺和实际呈现需要适用的语义与原页复核。

本仓库只保存通用源码、说明和合成测试数据；真实采购文件、响应文件、证照、社保、报价资料和会议转录保留在独立的业务目录。

## 参考上游

- [Sigma legal bid workflow](https://github.com/kwf18423059038-pixel/sigma-legal-bid-workflow)
- 评估基线：`v0.2.1`，提交 `9cf05be62d9bd2363261658c4c291a6e572d8cf4`。
- 按需要借鉴业务规则和小工具，不自动引入全部台账或循环引擎。实际复用代码或文档时保留相应许可证、NOTICE 和修改说明。
- 当前版本独立编写，未复制上游源码或实质文档；固定参考与实际复用范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本私有仓库未因此自动采用上游许可证授权其自身全部原创内容。
