"""Assemble existing PDFs and keep exact page provenance; never sign or submit."""
import hashlib
import json
from pathlib import Path

from sources import sha256, check_project


def assemble_pdf(parts, destination):
    """Parts are explicit path/hash/one-based page lists. Repeated pages are allowed."""
    from pypdf import PdfReader, PdfWriter
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("输出已存在，不能覆盖原件或已有候选")
    if not parts:
        raise ValueError("未指定装配来源")
    writer, mapping, opened = PdfWriter(), [], []
    for part in parts:
        path = Path(part["path"])
        if sha256(path) != part.get("sha256"):
            raise ValueError(f"装配来源变化：{path.name}")
        try:
            reader = PdfReader(path)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("来源加密无法读取")
            pages = part.get("pages")
            if not isinstance(pages, list) or not pages or any(type(p) is not int or p < 1 or p > len(reader.pages) for p in pages):
                raise ValueError("必须提供有效且非空的逐页列表")
        except Exception as error:
            raise ValueError(f"无法装配{path.name}：{error}") from error
        opened.append(reader)
        for page in pages:
            writer.add_page(reader.pages[page - 1])
            mapping.append({"output_page": len(mapping) + 1, "source_path": str(path.resolve()),
                            "source_sha256": part["sha256"], "source_page": page})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        writer.write(stream)
    return {"path": str(destination.resolve()), "sha256": sha256(destination),
            "page_count": len(mapping), "page_map": mapping,
            "state": "工作稿", "visual_review": "待核"}


def derive_stamp_parts(master, stamp_pages, output_directory):
    """Derive stamp and regular pages from exactly one unchanged master."""
    output_directory = Path(output_directory)
    if output_directory.exists():
        raise FileExistsError("派生目录已存在，不能混入旧件")
    from pypdf import PdfReader
    if len(PdfReader(master["path"]).pages) != master["page_count"]:
        raise ValueError("母稿记录页数与实际PDF不一致，不能派生")
    if not isinstance(stamp_pages, list) or not stamp_pages or len(set(stamp_pages)) != len(stamp_pages):
        raise ValueError("用印页列表为空或重复")
    if any(type(p) is not int or p < 1 or p > master["page_count"] for p in stamp_pages):
        raise ValueError("用印页超出母稿")
    source = {"path": master["path"], "sha256": master["sha256"]}
    if sha256(Path(source["path"])) != source["sha256"]:
        raise ValueError("母稿已变化，旧抽页方案失效")
    stem = Path(master["path"]).stem
    stamp = assemble_pdf([dict(source, pages=stamp_pages)], output_directory / f"{stem}_待用印部分.pdf")
    regular_pages = [p for p in range(1, master["page_count"] + 1) if p not in stamp_pages]
    regular = assemble_pdf([dict(source, pages=regular_pages)], output_directory / f"{stem}_常规部分.pdf") if regular_pages else None
    return {"source_sha256": master["sha256"], "stamp": stamp, "regular": regular,
            "state": "待用印抽页已生成；尚未签章"}


def files_digest(files):
    selected = [{key: item[key] for key in ("path", "sha256")} for item in files]
    return hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def assess_files(files, checks, execution, stage="draft", *, source_project=None, context=None):
    """Separate check results, human handling decisions and observed execution.

    Evidence is supplied by the supervising operator; this is a local record,
    not authentication of signatures, authority, platform acceptance or receipt.
    """
    if stage not in {"draft", "signing", "submission", "submitted"}:
        raise ValueError("未知检查阶段")
    digest = files_digest(files)
    findings = []
    source_digest = None
    if source_project is None or context is None:
        findings.append({"gate": "G1", "item": "检查依据", "result": "待核", "evidence": "需绑定采购项目与当前共用事实/规则时点"})
    else:
        report = check_project(Path(source_project))
        source_digest = report["digest"]
        findings.extend(report["findings"])
        if report["freeze_status"] != "current":
            findings.append({"gate": "G2", "item": "要求冻结", "result": "待核", "evidence": "尚无对应当前来源与要求的真实人工冻结"})
    live_materials = {}
    if context:
        selected = {identifier for chapter in context.get("chapters", []) for identifier in chapter.get("material_ids", [])}
        chapter_ids = {chapter["id"] for chapter in context.get("chapters", [])}
        for constraint in context.get("global_constraints", []):
            if "*" in constraint.get("scope", []) or chapter_ids.intersection(constraint.get("scope", [])):
                selected.update(constraint.get("material_ids", []))
        for identifier in selected:
            material = context.get("materials", {}).get(identifier, {})
            try:
                current = sha256(Path(material["path"]))
            except (OSError, KeyError):
                current = "missing"
            live_materials[identifier] = current
            if current != material.get("sha256"):
                findings.append({"gate": "G3", "item": "采用证明版本", "result": "阻断", "evidence": identifier})
    basis_digest = hashlib.sha256(json.dumps({"source": source_digest, "context": context,
        "live_materials": live_materials, "checker": sha256(Path(__file__))}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if not files:
        findings.append({"gate": "G5", "item": "文件清单", "result": "阻断", "evidence": "没有文件"})
    files_current = bool(files)
    for item in files:
        try:
            valid = sha256(Path(item["path"])) == item["sha256"]
        except OSError:
            valid = False
        if not valid:
            files_current = False
            findings.append({"gate": "G6", "item": "文件版本", "result": "阻断", "evidence": item["path"]})
    # Every applicable gate needs explicit evidence bound to this file set and stage.
    for gate in ("G1", "G2", "G3", "G4", "G5", "G6"):
        entries = [entry for entry in checks if entry.get("gate") == gate]
        if not entries:
            findings.append({"gate": gate, "item": "尚未检查", "result": "待核", "evidence": "缺少本阶段检查依据"})
        for entry in entries:
            if (entry.get("files_digest") != digest or entry.get("basis_digest") != basis_digest
                    or entry.get("stage") != stage or not entry.get("evidence")
                    or entry.get("result") not in {"通过", "不适用"}):
                findings.append({"gate": gate, "item": entry.get("item", "检查未通过或已失效"),
                                 "result": entry.get("result") if entry.get("result") in {"阻断", "待核"} else "待核",
                                 "evidence": entry.get("evidence", "缺少当前依据")})

    def evidence_ok(value, receipt=False):
        if not isinstance(value, dict) or not value.get("confirmed_by") or not value.get("basis") or value.get("files_digest") != digest:
            return False
        if receipt:
            try:
                return sha256(Path(value["path"])) == value["sha256"]
            except (KeyError, OSError):
                return False
        return value.get("basis_digest") == basis_digest

    passed = not findings
    state = "工作稿"
    if stage == "signing" and files_current:
        if passed:
            state = "待签章／待执行候选版"
        elif execution.get("continue_decision"):
            state = "待签章稿（按人工决定编制，检查缺口保留）"
    approved = files_current and evidence_ok(execution.get("submission_approval"))
    if stage in {"submission", "submitted"} and approved:
        state = "人工批准可递交" if passed else "人工决定递交（检查缺口保留）"
    submitted = files_current and evidence_ok(execution.get("submission"), receipt=True)
    if stage == "submitted" and submitted:
        state = "已递交（依据人员确认与对应凭据，不等于采购人接受）"
    return {"files_digest": digest, "basis_digest": basis_digest, "stage": stage, "state": state, "all_checks_passed": passed,
            "findings": findings, "human_decision": execution.get("continue_decision"),
            "submission_approved": approved, "submitted": submitted,
            "limit": "文件生成、可见签章、人员确认、递交及采购人接受分别记录；本工具不能鉴定真实性。"}
