"""Bounded chapter inputs and deterministic checks; no OCR, LLM or external writes."""

import copy
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re


REQUIREMENT_COLUMNS = (
    "requirement_id", "source_locations", "source_text", "requirement",
    "type_and_consequence", "satisfaction_condition", "required_response_or_proof",
    "ambiguity_or_clarification", "status",
)
REQUIREMENT_STATUSES = {"待复核", "已确认", "待澄清", "已被补遗取代"}
PLACEHOLDER = re.compile(r"{{\s*([^{}\s]+)\s*}}")
CHECK_KEYS = ("subject_key", "person_key", "period_start_key", "period_end_key")


def _requirements(rows):
    indexed = {}
    for row in rows:
        if set(row) != set(REQUIREMENT_COLUMNS):
            raise ValueError("requirements must have exactly nine columns")
        if any(not isinstance(row[key], str) for key in REQUIREMENT_COLUMNS):
            raise ValueError("requirement fields must be strings")
        for key in REQUIREMENT_COLUMNS:
            if key != "ambiguity_or_clarification" and not row[key].strip():
                raise ValueError(f"empty requirement field: {key}")
        identifier = row["requirement_id"]
        if identifier != identifier.strip() or identifier in indexed:
            raise ValueError(f"duplicate or untrimmed requirement_id: {identifier}")
        if row["status"] not in REQUIREMENT_STATUSES:
            raise ValueError(f"unknown requirement status: {row['status']}")
        indexed[identifier] = row
    return indexed


def read_requirements(csv_path):
    """Read UTF-8/BOM CSV; reject reordered, extra or missing columns and duplicate IDs."""
    with open(csv_path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != list(REQUIREMENT_COLUMNS):
            raise ValueError("CSV header must be the exact nine columns in the specified order")
        rows = list(reader)
    _requirements(rows)
    return rows


def _ids(values, label):
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"{label} must be a list of nonempty IDs")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return values


def _chapter_index(checklist):
    rows = checklist.get("chapters", [])
    if not isinstance(rows, list):
        raise ValueError("chapters must be a list")
    identifiers = _ids([row.get("id") for row in rows], "chapter IDs")
    return dict(zip(identifiers, rows))


def _fingerprint(packet):
    relevant = {key: value for key, value in packet.items() if key != "input_fingerprint"}
    relevant = copy.deepcopy(relevant)
    relevant["chapter"].pop("decisions", None)
    return hashlib.sha256(json.dumps(relevant, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def prepare_packet(checklist, requirements, chapter_id):
    """Copy only a chapter's full requirements, referenced facts/materials and scoped rules."""
    chapters = _chapter_index(checklist)
    if chapter_id not in chapters:
        raise ValueError(f"unknown chapter: {chapter_id}")
    chapter = chapters[chapter_id]
    ledger = _requirements(requirements)
    shared = checklist.get("shared", {})
    materials = checklist.get("materials", {})
    req_ids = list(_ids(chapter.get("requirement_ids", []), "requirement_ids"))
    shared_keys = list(_ids(chapter.get("shared_keys", []), "shared_keys"))
    material_ids = list(_ids(chapter.get("material_ids", []), "material_ids"))
    template = chapter.get("template")
    if template is not None and not isinstance(template, str):
        raise ValueError("template must be a string or null for a manually generated chapter")
    if template is not None:
        for key in PLACEHOLDER.findall(template):
            if key not in shared_keys:
                shared_keys.append(key)
        if "{{" in PLACEHOLDER.sub("", template) or "}}" in PLACEHOLDER.sub("", template):
            raise ValueError("malformed template placeholder")
    for check in chapter.get("material_checks", []):
        if check.get("material_id") not in material_ids:
            raise ValueError(f"material check has undeclared material: {check.get('material_id')}")
        if check.get("requirement_id") not in req_ids:
            raise ValueError(f"material check has unmapped requirement: {check.get('requirement_id')}")
        for field in CHECK_KEYS:
            if check.get(field) and check[field] not in shared_keys:
                shared_keys.append(check[field])
    constraints = []
    for constraint in checklist.get("global_constraints", []):
        scope = _ids(constraint.get("scope", []), "global constraint scope")
        if not scope or any(identifier != "*" and identifier not in chapters for identifier in scope):
            raise ValueError("unknown or empty global constraint scope")
        ids = _ids(constraint.get("requirement_ids", []), "global constraint requirement_ids")
        if any(identifier not in ledger for identifier in ids):
            raise ValueError("unknown global constraint requirement reference")
        if chapter_id in scope or "*" in scope:
            constraints.append(copy.deepcopy(constraint))
            req_ids.extend(identifier for identifier in ids if identifier not in req_ids)
            constraint_shared = list(_ids(constraint.get("shared_keys", []), "global constraint shared_keys"))
            text = constraint.get("text", "")
            if not isinstance(text, str):
                raise ValueError("global constraint text must be a string")
            constraint_shared.extend(key for key in PLACEHOLDER.findall(text) if key not in constraint_shared)
            shared_keys.extend(key for key in constraint_shared if key not in shared_keys)
            extra_materials = _ids(constraint.get("material_ids", []), "global constraint material_ids")
            material_ids.extend(identifier for identifier in extra_materials if identifier not in material_ids)
    for label, ids, source in (("requirement", req_ids, ledger), ("shared", shared_keys, shared),
                                ("material", material_ids, materials)):
        missing = [identifier for identifier in ids if identifier not in source]
        if missing:
            raise ValueError(f"unknown {label} reference: {', '.join(missing)}")
    if any(ledger[identifier]["status"] == "已被补遗取代" for identifier in req_ids):
        raise ValueError("chapter references a superseded requirement")
    packet = {
        "chapter": {key: copy.deepcopy(chapter[key]) for key in
                    ("id", "path", "template", "output", "material_checks", "decisions",
                     "source_context", "format_skeleton", "output_contract") if key in chapter},
        "requirements": copy.deepcopy([ledger[identifier] for identifier in req_ids]),
        "shared": copy.deepcopy({key: shared[key] for key in shared_keys}),
        "materials": copy.deepcopy({key: materials[key] for key in material_ids}),
        "global_constraints": constraints,
        "dependencies": {"requirement_ids": req_ids, "shared_keys": shared_keys, "material_ids": material_ids},
    }
    packet["input_fingerprint"] = _fingerprint(packet)
    return packet


def _value_gap(fact):
    if fact.get("status") != "confirmed" or not fact.get("source") or fact.get("value") in (None, ""):
        return "fact_pending"
    if fact.get("kind") == "commitment":
        approval = fact.get("approval") or {}
        if approval.get("decision") != "approve" or not approval.get("by"):
            return "unapproved_commitment"
    return None


def _display(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)


def render_chapter(packet):
    """Replace explicit template slots only; gaps stay separate from the document body."""
    template = packet["chapter"].get("template")
    if not isinstance(template, str) or not template.strip():
        raise ValueError("render_chapter requires an explicit nonempty template")
    gaps, used = [], {}

    def replacement(match):
        key = match.group(1)
        fact = packet["shared"][key]
        code = _value_gap(fact)
        if code:
            if not any(gap["shared_key"] == key for gap in gaps):
                gaps.append({"code": code, "shared_key": key, "status": "待核"})
            return "【】"
        used[key] = copy.deepcopy(fact["value"])
        return _display(fact["value"])

    content = PLACEHOLDER.sub(replacement, template)
    return {"content": content, "requirement_ids": packet["dependencies"]["requirement_ids"].copy(),
            "gaps": gaps, "used_values": used, "dependencies": copy.deepcopy(packet["dependencies"]),
            "input_fingerprint": packet["input_fingerprint"]}


def impact(before_checklist, after_checklist, before_requirements, after_requirements):
    """Compare actual bounded inputs. Unknown references are never called unchanged."""
    result = {"affected": [], "unchanged": [], "uncertain": [], "issues": []}
    try:
        before = _chapter_index(before_checklist)
        after = _chapter_index(after_checklist)
        old_ledger = _requirements(before_requirements)
        new_ledger = _requirements(after_requirements)
    except (ValueError, TypeError, AttributeError) as error:
        result["issues"].append(str(error))
        result["uncertain"] = ["*"]
        return result
    mapped = set()
    for identifier in dict.fromkeys([*before, *after]):
        if identifier not in before or identifier not in after:
            try:
                source, rows = ((after_checklist, after_requirements) if identifier in after
                                else (before_checklist, before_requirements))
                packet = prepare_packet(source, rows, identifier)
                mapped.update(packet["dependencies"]["requirement_ids"])
                result["affected"].append(identifier)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                result["uncertain"].append(identifier)
                result["issues"].append(f"{identifier}: {error}")
            continue
        try:
            old = prepare_packet(before_checklist, before_requirements, identifier)
            new = prepare_packet(after_checklist, after_requirements, identifier)
            mapped.update(old["dependencies"]["requirement_ids"])
            mapped.update(new["dependencies"]["requirement_ids"])
            category = "unchanged" if old["input_fingerprint"] == new["input_fingerprint"] else "affected"
            result[category].append(identifier)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            result["uncertain"].append(identifier)
            result["issues"].append(f"{identifier}: {error}")
    unresolved = [identifier for identifier in dict.fromkeys([*old_ledger, *new_ledger])
                  if old_ledger.get(identifier) != new_ledger.get(identifier) and identifier not in mapped]
    if unresolved:
        result["issues"].append("unmapped changed requirements: " + ", ".join(unresolved))
        result["uncertain"].extend(result["unchanged"])
        result["unchanged"] = []
    return result


def validate_chapters(checklist, requirements, results, *, chapter_ids=None):
    """Check all chapters by default, or explicit units without claiming full-ledger coverage."""
    findings = []

    def add(code, chapter=None, status="阻断", **details):
        finding = {"code": code, "status": status, **details}
        if chapter:
            finding["chapter_id"] = chapter["id"]
            if chapter.get("decisions"):
                finding["decisions"] = copy.deepcopy(chapter["decisions"])
        findings.append(finding)

    try:
        ledger = _requirements(requirements)
        chapter_map = _chapter_index(checklist)
        if chapter_ids is not None:
            selected = _ids(chapter_ids, "selected chapter IDs")
            if not selected or any(identifier not in chapter_map for identifier in selected):
                raise ValueError("selected chapter IDs must be nonempty and exist in the checklist")
            chapter_map = {identifier: chapter_map[identifier] for identifier in selected}
    except (ValueError, TypeError, AttributeError) as error:
        add("invalid_input", detail=str(error))
        return findings
    mapped, used_shared = set(), set()
    for chapter in chapter_map.values():
        try:
            packet = prepare_packet(checklist, requirements, chapter["id"])
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            add("unknown_reference", chapter, detail=str(error))
            continue
        mapped.update(packet["dependencies"]["requirement_ids"])
        used_shared.update(packet["dependencies"]["shared_keys"])
        for row in packet["requirements"]:
            if row["status"] != "已确认":
                add("requirement_pending", chapter, status="待核", requirement_id=row["requirement_id"])
        result = results.get(chapter["id"])
        if result is None:
            add("missing_result", chapter)
        else:
            if result.get("input_fingerprint") != packet["input_fingerprint"]:
                add("stale_result", chapter)
            if set(result.get("requirement_ids", [])) != set(packet["dependencies"]["requirement_ids"]):
                add("result_requirement_mismatch", chapter)
            if result.get("dependencies") != packet["dependencies"]:
                add("result_dependency_mismatch", chapter)
            for key, used in result.get("used_values", {}).items():
                fact = packet["shared"].get(key)
                if fact is None or _value_gap(fact) or used != fact.get("value"):
                    add("used_value_mismatch", chapter, shared_key=key)
            if chapter.get("template"):
                expected = render_chapter(packet)
                if result.get("content") != expected["content"]:
                    add("template_content_mismatch", chapter)
                if result.get("gaps") != expected["gaps"]:
                    add("gap_disclosure_mismatch", chapter)
                if result.get("used_values") != expected["used_values"]:
                    if not any(f["code"] == "used_value_mismatch" and f.get("chapter_id") == chapter["id"] for f in findings):
                        add("used_value_mismatch", chapter)
            else:
                add("semantic_review_required", chapter, status="待核",
                    detail="非模板正文须人工核对实质响应、来源及新增承诺。")
        for key, fact in packet["shared"].items():
            code = _value_gap(fact)
            if code:
                add(code, chapter, status="阻断" if code == "unapproved_commitment" else "待核", shared_key=key)
        for identifier, material in packet["materials"].items():
            if material.get("status") != "confirmed":
                add("material_pending", chapter, status="待核", material_id=identifier)
            if not material.get("path") or not re.fullmatch(r"[0-9a-fA-F]{64}", str(material.get("sha256", ""))):
                add("material_provenance_missing", chapter, material_id=identifier)
            pages = material.get("pages")
            if not isinstance(pages, list) or not pages or any(type(page) is not int or page < 1 for page in pages):
                add("material_pages_missing", chapter, material_id=identifier)
        for check in chapter.get("material_checks", []):
            material = packet["materials"][check["material_id"]]
            details = {"material_id": check["material_id"], "requirement_id": check["requirement_id"]}
            for kind in ("subject", "person"):
                key = check.get(f"{kind}_key")
                if key and not _value_gap(packet["shared"][key]) and material.get(kind) != packet["shared"][key]["value"]:
                    add(f"material_{kind}_mismatch", chapter, **details)
            for kind in ("period_start", "period_end"):
                key = check.get(f"{kind}_key")
                if not key or _value_gap(packet["shared"][key]):
                    continue
                try:
                    actual = date.fromisoformat(material[kind])
                    needed = date.fromisoformat(packet["shared"][key]["value"])
                    mismatch = actual > needed if kind == "period_start" else actual < needed
                    if mismatch:
                        add("material_period_mismatch", chapter, field=kind, **details)
                except (KeyError, TypeError, ValueError):
                    add("material_period_unverified", chapter, status="待核", field=kind, **details)
    if chapter_ids is None:
        for identifier, row in ledger.items():
            if row["status"] != "已被补遗取代" and identifier not in mapped:
                add("unmapped_requirement", requirement_id=identifier)
    quotes = {}
    for key, fact in checklist.get("shared", {}).items():
        if chapter_ids is not None and key not in used_shared:
            continue
        if fact.get("kind") != "quote" or _value_gap(fact):
            continue
        if not fact.get("round"):
            add("quote_round_missing", shared_key=key)
            continue
        try:
            amount = _decimal(fact["value"])
        except ValueError:
            add("quote_amount_unverified", status="待核", shared_key=key)
            continue
        group = (fact["round"], fact.get("quote_group", "total"))
        quotes.setdefault(group, []).append((key, amount, fact.get("currency", "CNY")))
    for (round_id, group), entries in quotes.items():
        if len({(amount, currency) for _, amount, currency in entries}) > 1:
            add("quote_round_conflict", round=round_id, quote_group=group, shared_keys=[entry[0] for entry in entries])
    return findings


def _decimal(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("number must be finite")
        return number
    except (InvalidOperation, TypeError) as error:
        raise ValueError("invalid decimal number") from error


def _number_text(number):
    return format(number.normalize(), "f")


def score_performance(candidates, rule):
    """Estimate confirmed per-item scores, count independent IDs and plan one valid backup.

    Candidate order is the user's priority order. This never decides semantic eligibility
    or a reviewer's actual score; status/source record the prior qualification check.
    """
    if rule.get("status") != "confirmed" or not rule.get("source"):
        raise ValueError("scoring rule must be confirmed with a source")
    per_item, maximum = _decimal(rule["points_per_item"]), _decimal(rule["max_points"])
    if per_item <= 0 or maximum < 0:
        raise ValueError("points_per_item must be positive and max_points nonnegative")
    if rule.get("subject_type") not in {"firm", "person"} or not rule.get("subject_id"):
        raise ValueError("scoring rule requires firm/person and subject_id")
    start = date.fromisoformat(rule["start_date"]) if rule.get("start_date") else None
    end = date.fromisoformat(rule["end_date"]) if rule.get("end_date") else None
    if start and end and start > end:
        raise ValueError("invalid scoring date window")
    for limit in ("max_count", "page_limit"):
        if limit in rule and (type(rule[limit]) is not int or rule[limit] < 0):
            raise ValueError(f"{limit} must be a nonnegative integer")
    minimum = int((maximum / per_item).to_integral_value(rounding=ROUND_CEILING))
    target = minimum + 1 if minimum else 0
    limitations = []
    if "max_count" in rule and rule["max_count"] < target:
        target = rule["max_count"]
        limitations.append("submission_count_limit")
    grouped = {}
    for item in candidates:
        if not isinstance(item.get("id"), str) or not item["id"].strip() or item["id"] != item["id"].strip():
            raise ValueError("every candidate requires a trimmed stable independent id")
        grouped.setdefault(item["id"], []).append(item)
    eligible, excluded, duplicates, conflicts = [], [], [], []
    semantic_keys = ("subject_type", "subject_id", "completed_on", "service_type", "status")
    for identifier, copies in grouped.items():
        item = copies[0]
        if len(copies) > 1:
            duplicates.append(identifier)
        if any(any(other.get(key) != item.get(key) for key in semantic_keys) for other in copies[1:]):
            conflicts.append(identifier)
            excluded.append({"id": identifier, "reason": "conflicting_duplicate"})
            continue
        reason = None
        if item.get("status") != "confirmed" or not item.get("source"):
            reason = "qualification_pending"
        elif item.get("subject_type") != rule["subject_type"] or item.get("subject_id") != rule["subject_id"]:
            reason = "subject_mismatch"
        elif rule.get("service_type") and item.get("service_type") != rule["service_type"]:
            reason = "service_type_mismatch"
        elif start or end:
            try:
                actual = date.fromisoformat(item["completed_on"])
                if (start and actual < start) or (end and actual > end):
                    reason = "date_outside_window"
            except (KeyError, TypeError, ValueError):
                reason = "date_unverified"
        if reason:
            excluded.append({"id": identifier, "reason": reason})
        else:
            eligible.append(item)
    selected, pages_used = [], 0
    for item in eligible:
        if len(selected) >= target:
            break
        if "page_limit" in rule:
            pages = item.get("page_count")
            if type(pages) is not int or pages < 1:
                limitations.append(f"page_count_unverified:{item['id']}")
                continue
            if pages_used + pages > rule["page_limit"]:
                limitations.append(f"page_limit:{item['id']}")
                continue
            pages_used += pages
        selected.append(item["id"])
    score = min(maximum, per_item * len(selected))
    return {"minimum_for_full_score": minimum, "target_count": target,
            "eligible_ids": [item["id"] for item in eligible], "selected_ids": selected,
            "backup_count": max(0, len(selected) - minimum), "score": _number_text(score),
            "score_shortfall": _number_text(maximum - score), "excluded": excluded,
            "duplicate_ids": duplicates, "conflicting_ids": conflicts, "limitations": limitations,
            "qualification_shortfall": max(0, target - len(selected)),
            "score_kind": "evidence_supported_estimate"}
