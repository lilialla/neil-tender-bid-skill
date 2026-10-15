"""Local source inventory, source-side coverage and a nine-column ledger.

This module does not perform OCR or infer procurement requirements. Codex reads
the original material, drafts candidates and records review dispositions.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

COLUMNS = ["requirement_id", "source_locations", "source_text", "requirement",
           "type_and_consequence", "satisfaction_condition", "required_response_or_proof",
           "ambiguity_or_clarification", "status"]
RISK = re.compile(r"应|须|需|不得|仅限|除外|否则|视为|无效|否决|备注|注[：:]|附件|详见|续表|[0-9０-９]+")
HIGH_RISK = re.compile(r"资格|否决|无效|评分|程序|递交|签章|必需|强制")
STATES = {"待复核", "已确认", "待澄清", "已被补遗取代"}
OCR_PROVIDER = "mineru_content_list_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pdf_texts(path: Path) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF加密，无法读取")
    return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_requirements(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            raise ValueError("要求总账必须恰有规定的9列，且顺序一致")
        rows = list(reader)
    validate_requirements(rows)
    return rows


def validate_requirements(rows: list[dict]) -> dict:
    """One ledger contract for source intake, chapter inputs and CSV output."""
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(COLUMNS):
            raise ValueError("requirements must have exactly nine columns")
        if any(not isinstance(row[key], str) for key in COLUMNS):
            raise ValueError("requirement fields must be strings")
        for key in COLUMNS:
            if key != "ambiguity_or_clarification" and not row[key].strip():
                raise ValueError(f"empty requirement field: {key}")
        identifier = row["requirement_id"]
        if identifier != identifier.strip() or identifier in indexed:
            raise ValueError(f"duplicate or untrimmed requirement_id: {identifier}")
        if row["status"] not in STATES:
            raise ValueError(f"unknown requirement status: {row['status']}")
        indexed[identifier] = row
    return indexed


def write_requirements(path: Path, rows: list[dict]) -> None:
    validate_requirements(rows)
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def inspect_file(path: Path) -> dict:
    path = Path(path).resolve(strict=True)
    record = {"name": path.name, "path": str(path), "sha256": sha256(path),
              "role": "procurement", "required": True, "version": "待核对原文版本",
              "health": "readable", "pages": [], "error": ""}
    if not path.is_file():
        raise ValueError("来源必须为常规文件")
    try:
        with path.open("rb") as stream:
            head = stream.read(4096)
        if not head or not head.strip(b"\0"):
            raise ValueError("空文件或全零文件头，不能作为可用来源")
        if path.suffix.lower() == ".pdf":
            texts = pdf_texts(path)
            method = "native_pdf_layout_text"
        elif path.suffix.lower() in {".txt", ".md"}:
            texts = path.read_text(encoding="utf-8-sig").split("\f")
            method = "provided_text"
        else:
            raise ValueError("此入口只直接读取PDF原生文本或UTF-8分页文本；其他格式先用既有文档工具")
        if not texts:
            raise ValueError("来源没有页面")
        for number, text in enumerate(texts, 1):
            record["pages"].append({"number": number, "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "method": method,
                "read_status": "needs_review" if text.strip() else "unreadable", "read_basis": "",
                "coverage": []})
    except (OSError, UnicodeError, ValueError, ImportError) as error:
        record.update(health="invalid", error=str(error), pages=[])
    except Exception as error:
        # PDF parser errors vary by installed pypdf version; retain the failure.
        record.update(health="invalid", error=f"{type(error).__name__}: {error}", pages=[])
    return record


def initialize(project: Path, paths: list[Path]) -> dict:
    project = Path(project)
    if not paths:
        raise ValueError("至少提供一个当前采购来源")
    if project.exists():
        raise FileExistsError("工作目录已存在；请读取并继续，或选择新的工作目录，不能重新初始化覆盖")
    records = [inspect_file(path) for path in paths]
    if len({record["name"] for record in records}) != len(records):
        raise ValueError("来源同名，需在工作副本中区分后再初始化，避免来源位置歧义")
    project.mkdir(parents=True)
    value = {"schema_version": 1,
        "scope": {"status": "needs_review", "basis": "", "missing": []},
        "sources": records,
        "cross_checks": {name: {"status": "待核", "basis": ""}
                         for name in ("references", "scoring", "forms")}}
    write_json(project / "sources.json", value)
    write_requirements(project / "requirements.csv", [])
    return value


def parse_mineru_content_list(items: list, page_count: int) -> list[str]:
    """Read supported v1 items verbatim; page_idx is zero-based and may repeat."""
    if not isinstance(items, list) or not items or type(page_count) is not int or page_count < 1:
        raise ValueError("OCR结果须为非空MinerU content_list v1数组，且原PDF须有页面")
    fragments = [[] for _ in range(page_count)]
    seen = set()

    def string(value, field):
        if not isinstance(value, str):
            raise ValueError(f"OCR正文结构不支持：{field}须为字符串")
        return value

    def strings(item, field):
        value = item.get(field, [])
        if not isinstance(value, list) or any(not isinstance(part, str) for part in value):
            raise ValueError(f"OCR正文结构不支持：{field}须为字符串数组")
        return value

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("OCR content_list每项须为对象")
        page_idx = item.get("page_idx")
        if type(page_idx) is not int or not 0 <= page_idx < page_count:
            raise ValueError("OCR page_idx须为原PDF范围内从0起算的整数")
        seen.add(page_idx)
        kind = item.get("type")
        if not isinstance(kind, str):
            raise ValueError("OCR正文类型须为字符串")
        if kind in {"text", "header", "page_number", "aside_text"}:
            parts = [string(item.get("text"), "text")]
        elif kind == "table":
            parts = (strings(item, "table_caption") + [string(item.get("table_body"), "table_body")]
                     + strings(item, "table_footnote"))
        elif kind == "image":
            image = string(item.get("img_path"), "img_path")
            if not image.strip():
                raise ValueError("OCR图像须保留非空img_path")
            parts = strings(item, "image_caption") + [f"[原页图像：{image}]"] + strings(item, "image_footnote")
        else:
            raise ValueError(f"OCR正文类型不支持：{kind!r}")
        fragments[page_idx].extend(part for part in parts if part.strip())
    if seen != set(range(page_count)):
        raise ValueError("OCR page_idx未完整覆盖原PDF全本；首版不支持抽页、重排或缺页结果")
    return ["\n\n".join(parts) for parts in fragments]


def page_working_text(page: dict) -> str:
    selected = page.get("working_text_source", "native")
    if selected == "native":
        text = page.get("text", "")
    elif selected == "ocr" and isinstance(page.get("ocr"), dict):
        text = page["ocr"].get("text")
    else:
        raise ValueError("工作文字来源须为native或已关联的ocr")
    if not isinstance(text, str):
        raise ValueError("工作文字须为字符串")
    if selected == "ocr":
        corrections = page["ocr"].get("corrections", [])
        if not isinstance(corrections, list):
            raise ValueError("OCR修正须为逐条记录的数组")
        for correction in corrections:
            if not isinstance(correction, dict) or set(correction) != {"before", "after", "basis"}:
                raise ValueError("OCR修正须恰含before、after、basis")
            before, after, basis = (correction[key] for key in ("before", "after", "basis"))
            if (not isinstance(before, str) or not before or not isinstance(after, str)
                    or not isinstance(basis, str) or not basis.strip()):
                raise ValueError("OCR修正须有非空原字串、字符串替换值及实际原页核对依据")
            first = text.find(before)
            if first < 0 or text.find(before, first + 1) >= 0:
                raise ValueError("OCR修正的before须在当前逐步修正文字中恰好出现1次")
            text = text.replace(before, after, 1)
    return text


def expected_review_digest(record: dict, page: dict) -> str:
    """Version fingerprint only; computing it does not perform or approve review."""
    ocr = record.get("ocr", {})
    page_ocr = page.get("ocr", {})
    if not isinstance(ocr, dict) or not isinstance(page_ocr, dict):
        raise ValueError("OCR来源或页面记录无效")
    payload = {"source_sha256": record.get("sha256"), "page": page.get("number"),
               "working_text_source": page.get("working_text_source", "native"),
               "provider": ocr.get("provider"), "input_sha256": ocr.get("input_sha256"),
               "result_sha256": ocr.get("result_sha256"), "page_idx": page_ocr.get("page_idx"),
               "corrections": page_ocr.get("corrections", []),
               "text_sha256": text_sha256(page_working_text(page))}
    return text_sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def load_ocr_texts(record: dict, current_source_hash: str, page_count: int) -> list[str]:
    ocr = record.get("ocr")
    if not isinstance(ocr, dict) or ocr.get("provider") != OCR_PROVIDER:
        raise ValueError("OCR来源须为已关联的MinerU content_list v1")
    if (current_source_hash != record.get("sha256") or ocr.get("source_sha256") != current_source_hash
            or ocr.get("input_sha256") != current_source_hash):
        raise ValueError("OCR输入必须与登记及当前采购原PDF的全本字节完全相同")
    if type(ocr.get("page_count")) is not int or ocr["page_count"] != page_count:
        raise ValueError("OCR全本页映射与采购原PDF页数不符")
    for field in ("input", "result"):
        path_value = ocr.get(f"{field}_path")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError(f"OCR缺少实际{field}文件路径")
        path = Path(path_value)
        if not path.is_file() or sha256(path) != ocr.get(f"{field}_sha256"):
            raise ValueError(f"OCR实际{field}文件缺失或字节已改变")
    result = Path(ocr["result_path"])
    texts = parse_mineru_content_list(read_json(result), page_count)
    if sha256(result) != ocr["result_sha256"]:
        raise ValueError("OCR结果在读取期间已改变")
    return texts


def attach_ocr(project: Path, source: Path, input_pdf: Path, result: Path) -> dict:
    """Attach an existing full-PDF OCR result without editing native text or claiming review."""
    project = Path(project)
    inventory = read_json(project / "sources.json")
    if inventory.get("schema_version") != 1:
        raise ValueError("来源文件schema_version不支持")
    source, input_pdf, result = (Path(path).resolve(strict=True) for path in (source, input_pdf, result))
    if source.suffix.lower() != ".pdf" or input_pdf.suffix.lower() != ".pdf":
        raise ValueError("OCR接入首版仅支持同一原PDF全本1:1页映射")
    matches = [record for record in inventory.get("sources", [])
               if Path(record.get("path", "")).resolve() == source]
    if len(matches) != 1:
        raise ValueError("须指定清单中唯一已登记的采购原PDF准确路径")
    record = matches[0]
    if record.get("health") != "readable" or record.get("role") != "procurement" or record.get("required") is not True:
        raise ValueError("OCR须关联健康、必要的当前采购来源")
    current = sha256(source)
    if current != record.get("sha256") or sha256(input_pdf) != current:
        raise ValueError("OCR输入必须与登记及当前采购原PDF的全本字节完全相同")
    native = pdf_texts(source)
    pages = record.get("pages", [])
    if (not native or any(type(page.get("number")) is not int for page in pages)
            or [page.get("number") for page in pages] != list(range(1, len(native) + 1))):
        raise ValueError("库存页码须与原PDF页数一致、唯一且连续")
    for page, text in zip(pages, native):
        if (page.get("text") != text or page.get("text_sha256") != text_sha256(text)
                or page.get("method") != "native_pdf_layout_text"):
            raise ValueError("登记的原生文字与原PDF不符；不能用OCR覆盖原生文字")
    result_hash = sha256(result)
    texts = parse_mineru_content_list(read_json(result), len(native))
    if sha256(source) != current or sha256(input_pdf) != current or sha256(result) != result_hash:
        raise ValueError("OCR接入读取期间输入文件已改变")
    record["ocr"] = {"provider": OCR_PROVIDER, "source_sha256": current,
                     "input_path": str(input_pdf), "input_sha256": current,
                     "result_path": str(result), "result_sha256": result_hash, "page_count": len(native)}
    for page, text in zip(pages, texts):
        page.update(working_text_source="ocr", ocr={"page_idx": page["number"] - 1,
                    "text": text, "text_sha256": text_sha256(text)},
                    read_status="needs_review", read_basis="", coverage=[])
        page.pop("reviewed_digest", None)
        page.pop("blank_verified", None)
    write_json(project / "sources.json", inventory)
    return inventory


def parse_locations(value: str) -> list[dict]:
    result = []
    for line in value.splitlines():
        parts = [part.strip() for part in line.split("｜")]
        if len(parts) != 4 or parts[0] not in {"主", "补", "修", "冲突"} or not parts[1] or not parts[3]:
            raise ValueError(f"来源位置应为 角色｜文件名｜页码｜位置：{line}")
        match = re.fullmatch(r"(?:PDF)?第?\s*(\d+)(?:\s*[-—–至]\s*(\d+))?\s*页?", parts[2])
        if not match:
            raise ValueError(f"页码须为连续页或范围：{parts[2]}")
        start, end = int(match[1]), int(match[2] or match[1])
        if start < 1 or end < start:
            raise ValueError("来源页码范围无效")
        result.append({"role": parts[0], "name": parts[1], "start": start, "end": end, "location": parts[3]})
    if not result:
        raise ValueError("缺少来源位置")
    return result


def check_project(project: Path) -> dict:
    project = Path(project)
    inventory = read_json(project / "sources.json")
    rows = read_requirements(project / "requirements.csv")
    findings, hints = [], []

    def issue(gate, key, result, evidence):
        findings.append({"gate": gate, "item": key, "result": result, "evidence": evidence})

    if inventory.get("schema_version") != 1:
        raise ValueError("来源文件schema_version不支持")
    scope = inventory.get("scope", {})
    if scope.get("status") != "confirmed" or not scope.get("basis") or scope.get("missing"):
        issue("G1", "控制来源范围", "待核", "核对所给文件、公告、补遗、附件及缺失项；唯一且明确的来源可按事实直接记录")
    records = inventory.get("sources", [])
    if not records or not any(r.get("role") == "procurement" and r.get("required") is True for r in records):
        issue("G1", "控制来源", "阻断", "至少一个必要采购来源")
    names = [record.get("name") for record in records]
    if len(names) != len(set(names)):
        issue("G1", "来源名称", "阻断", "同名来源不能精确定位")
    lookup, live, live_ocr, working_texts = {}, {}, {}, {}
    for record in records:
        name = record.get("name", "未命名")
        lookup[name] = record
        relevant = record.get("required") is True and record.get("role") == "procurement"
        try:
            current = sha256(Path(record["path"]))
        except (OSError, KeyError):
            current = "missing"
        live[name] = current
        if current != record.get("sha256") and relevant:
            issue("G1", name, "阻断", "来源文件缺失或字节已改变，需重读并更新受影响要求")
        if record.get("health") != "readable" and relevant:
            issue("G1", name, "阻断", record.get("error") or "来源不可读")
        if not relevant:
            if not record.get("exclusion_basis"):
                issue("G1", name, "待核", "非控制或非必要文件须说明用途及排除依据")
            continue
        pages = record.get("pages", [])
        native_texts = None
        if current == record.get("sha256"):
            try:
                actual = Path(record["path"])
                if actual.suffix.lower() == ".pdf":
                    native_texts = pdf_texts(actual)
                    actual_count = len(native_texts)
                else:
                    actual_count = len(actual.read_text(encoding="utf-8-sig").split("\f"))
                if actual_count != len(pages):
                    issue("G1", name, "阻断", "来源清单页数与原文件不符")
            except Exception as error:
                issue("G1", name, "阻断", f"原文件页数核验失败：{error}")
        if (not pages or any(type(page.get("number")) is not int for page in pages)
                or [page.get("number") for page in pages] != list(range(1, len(pages) + 1))):
            issue("G1", name, "阻断", "页码缺失、重复或不连续")
            continue
        ocr_texts = None
        has_ocr = "ocr" in record or any("ocr" in page or page.get("working_text_source") == "ocr" for page in pages)
        if has_ocr:
            metadata = record.get("ocr")
            live_ocr[name] = {}
            for field in ("input", "result"):
                try:
                    live_ocr[name][field] = sha256(Path(metadata[f"{field}_path"]))
                except (OSError, KeyError, TypeError):
                    live_ocr[name][field] = "missing"
            try:
                if Path(record["path"]).suffix.lower() != ".pdf" or native_texts is None:
                    raise ValueError("OCR必须关联当前可读取的采购原PDF")
                ocr_texts = load_ocr_texts(record, current, len(native_texts))
            except (OSError, ValueError, TypeError, KeyError) as error:
                issue("G1", name, "阻断", f"OCR来源核验失败：{error}")
        for page in pages:
            place = f"{name} PDF第{page['number']}页"
            native_raw = page.get("text", "")
            if not isinstance(native_raw, str):
                issue("G1", place, "阻断", "原生文字须为字符串")
                native_raw = ""
            if text_sha256(native_raw) != page.get("text_sha256"):
                issue("G1", place, "阻断", "工作文字被改动，须重新核对原件并更新文字来源记录")
            page_number = page["number"]
            if (native_texts is not None and type(page_number) is int and 1 <= page_number <= len(native_texts)
                    and (native_raw != native_texts[page_number - 1] or page.get("method") != "native_pdf_layout_text")):
                issue("G1", place, "阻断", "登记的原生文字或提取方式与原PDF不符；不得用OCR覆盖原生文字")
            try:
                raw = page_working_text(page)
            except ValueError as error:
                raw = ""
                issue("G1", place, "阻断", str(error))
            if has_ocr:
                page_ocr = page.get("ocr")
                if (page.get("working_text_source") != "ocr" or not isinstance(page_ocr, dict)
                        or type(page_ocr.get("page_idx")) is not int or page_ocr["page_idx"] != page_number - 1
                        or not isinstance(page_ocr.get("text"), str)
                        or page_ocr.get("text_sha256") != text_sha256(page_ocr["text"])):
                    issue("G1", place, "阻断", "OCR逐页文字、哈希或1:1页映射无效")
                elif ocr_texts is not None and (not 1 <= page_number <= len(ocr_texts)
                                               or page_ocr["text"] != ocr_texts[page_number - 1]):
                    issue("G1", place, "阻断", "OCR逐页文字与已锁定的原始结果不一致")
                if page.get("read_status") == "verified":
                    try:
                        reviewed = page.get("reviewed_digest") == expected_review_digest(record, page)
                    except ValueError:
                        reviewed = False
                    if not reviewed:
                        issue("G1", place, "待核", "OCR读取确认未绑定当前原件、输入、结果及本页文字版本")
            working_texts[(name, page_number)] = raw
            if page.get("read_status") != "verified" or not page.get("read_basis"):
                issue("G1", place, "待核", "文本层不证明表格、图片或脚注已可靠读取；需原页核对或经授权的MinerU结果")
            lines = raw.splitlines()
            for number, line in enumerate(lines, 1):
                if RISK.search(line):
                    hints.append({"source": name, "page": page["number"], "line": number, "text": line})
            covered = set()
            for block in page.get("coverage", []):
                start, end = block.get("start_line"), block.get("end_line")
                if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
                    issue("G2", place, "阻断", "覆盖记录超出文字行范围")
                    continue
                span = set(range(start, end + 1))
                if span & covered:
                    issue("G2", place, "阻断", "同页来源范围重叠，需合并处置")
                covered |= span
                state = block.get("status")
                if state not in {"requirements_found", "no_requirement"}:
                    issue("G2", place, "待核", f"来源范围{start}-{end}尚未结案：{state}")
                if not {"structure", "meaning", "risk"}.issubset(block.get("checks", [])):
                    issue("G2", place, "待核", f"来源范围{start}-{end}缺少结构、逐段语义或风险复查")
                linked = block.get("requirement_ids", [])
                if state == "requirements_found" and not linked:
                    issue("G2", place, "阻断", "提取到要求却未给出要求编号")
                if state == "no_requirement" and (linked or not block.get("note")):
                    issue("G2", place, "阻断", "无要求范围须写明理由且不能同时引用要求")
                for req in linked:
                    matching = next((row for row in rows if row["requirement_id"] == req), None)
                    if not matching:
                        issue("G2", place, "阻断", f"未知要求编号{req}")
                    else:
                        try:
                            locations = parse_locations(matching["source_locations"])
                            if not any(loc["name"] == name and loc["start"] <= page["number"] <= loc["end"] for loc in locations):
                                issue("G2", place, "阻断", f"{req}没有回指本页")
                        except ValueError as error:
                            issue("G2", req, "阻断", str(error))
            if covered != set(range(1, len(lines) + 1)):
                missing = sorted(set(range(1, len(lines) + 1)) - covered)
                issue("G2", place, "阻断", f"未处理文字行：{missing}")
            if not lines and not (page.get("blank_verified") is True and page.get("read_basis")):
                issue("G2", place, "待核", "无文字页须核对原页为空白；扫描页不能当作空白")
    if not rows:
        issue("G2", "要求总账", "待核", "没有要求候选，不能据此宣称完整")
    elif not any(row["status"] != "已被补遗取代" for row in rows):
        issue("G2", "要求总账", "待核", "没有现行要求，需重新核对采购是否仍有效")
    for row in rows:
        req = row["requirement_id"]
        if row["status"] not in STATES or row["status"] in {"待复核", "待澄清"}:
            issue("G2", req, "待核", row["ambiguity_or_clarification"] or "解释状态未确认")
        if row["status"] == "已被补遗取代":
            replacement = re.search(r"替代要求[：:]\s*([A-Za-z0-9_-]+)", row["ambiguity_or_clarification"])
            target = next((other for other in rows if replacement and other["requirement_id"] == replacement[1]), None)
            if not target or target["requirement_id"] == req or target["status"] != "已确认":
                issue("G2", req, "待核", "被替代要求须用替代要求：现行ID引用已确认条目；整项取消可在原ID的现行行保留取消原文与修位置")
        for field in COLUMNS[1:7]:
            if not row[field].strip():
                issue("G2", req, "阻断", f"必要字段{field}为空；确实不适用时写明原文依据")
        try:
            locations = parse_locations(row["source_locations"])
        except ValueError as error:
            issue("G2", req, "阻断", str(error))
            continue
        for loc in locations:
            record = lookup.get(loc["name"])
            if record is None or loc["end"] > len(record.get("pages", [])):
                issue("G2", req, "阻断", "引用未知来源或超出实际页数")
            elif record.get("role") != "procurement" or record.get("required") is not True:
                issue("G2", req, "待核", "历史参考材料不能充当当前采购条件")
            else:
                for page in record["pages"][loc["start"] - 1:loc["end"]]:
                    if not any(req in block.get("requirement_ids", []) for block in page.get("coverage", [])):
                        issue("G2", req, "阻断", f"引用页{loc['name']}:{page['number']}未在覆盖记录关联本要求")
            if loc["role"] == "冲突" and not row["ambiguity_or_clarification"].strip():
                issue("G2", req, "待核", "冲突来源需记录负责人的解释和处理，不能由模型静默选择")
        cited_text = "\n".join(working_texts.get((loc["name"], number), "") for loc in locations
                               for number in range(loc["start"], loc["end"] + 1))
        normalize = lambda text: re.sub(r"\s+", "", text)
        if any(normalize(quote) not in normalize(cited_text) for quote in row["source_text"].split("\n---\n")):
            issue("G2", req, "待核", "引文与所引页工作文字不一致，需回读原页；多段原文使用换行---换行分隔")
    for name in ("references", "scoring", "forms"):
        item = inventory.get("cross_checks", {}).get(name, {})
        if item.get("status") not in {"通过", "不适用"} or not item.get("basis"):
            issue("G2", name, "待核", "跨页/附件引用、实际评分规则与固定表式需源侧反查；不适用须依据")
    payload = {"inventory": inventory, "requirements": rows, "live_sources": live}
    if live_ocr:
        payload["live_ocr"] = live_ocr
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    frozen_file = project / "freeze.json"
    frozen = read_json(frozen_file) if frozen_file.exists() else {}
    groups = {gate: ("阻断" if any(f["result"] == "阻断" and f["gate"] == gate for f in findings)
                     else "待核" if any(f["gate"] == gate for f in findings) else "通过") for gate in ("G1", "G2")}
    return {"gates": groups, "findings": findings, "risk_hints": hints, "digest": digest,
            "can_freeze": not findings, "requirement_count": len(rows),
            "source_pages": sum(len(r.get("pages", [])) for r in records if r.get("required") and r.get("role") == "procurement"),
            "freeze_status": "none" if not frozen else "current" if frozen.get("digest") == digest else "stale",
            "limit": "确定性检查不能证明语义无漏项；需逐范围阅读、原页核对与真实人工冻结。"}


def freeze(project: Path, reviewer: str, decision_reference: str, expected_digest: str) -> Path:
    if not reviewer.strip() or not decision_reference.strip():
        raise ValueError("人工冻结须有真实复核人和本次确认依据；不得由模型编造")
    report = check_project(project)
    if report["digest"] != expected_digest:
        raise ValueError("确认后输入已变化，请展示当前版本再确认")
    if not report["can_freeze"]:
        raise ValueError("来源或要求存在未结案项；可继续工作稿，不能把继续决定登记为完整冻结")
    folder = Path(project) / "frozen" / report["digest"]
    folder.mkdir(parents=True, exist_ok=True)
    value = {"digest": report["digest"], "reviewer": reviewer,
             "decision_reference": decision_reference, "recorded_at": datetime.now(timezone.utc).isoformat()}
    for name in ("sources.json", "requirements.csv"):
        destination = folder / name
        if not destination.exists():
            destination.write_bytes((Path(project) / name).read_bytes())
    if not (folder / "freeze.json").exists():
        write_json(folder / "freeze.json", value)
    write_json(Path(project) / "freeze.json", read_json(folder / "freeze.json"))
    return folder


def replay(candidate: list[dict], reviewed: list[dict]) -> dict:
    initial = {row["requirement_id"]: row for row in candidate}
    final = {row["requirement_id"]: row for row in reviewed}
    missed = sorted(final.keys() - initial.keys())
    return {"missed_ids": missed, "removed_ids": sorted(initial.keys() - final.keys()),
            "corrected_ids": sorted(key for key in initial.keys() & final.keys() if initial[key] != final[key]),
            "unchanged_ids": sorted(key for key in initial.keys() & final.keys() if initial[key] == final[key]),
            "high_risk_missed_ids": [key for key in missed if HIGH_RISK.search(final[key]["type_and_consequence"])],
            "basis": "按复核前后稳定要求编号比较；重编号需先人工对齐。候选与人工补正分开，已知样本不是盲测。"}
