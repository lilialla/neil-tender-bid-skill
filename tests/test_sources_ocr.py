"""Synthetic full-PDF MinerU intake; no business files or cloud requests."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/neil-tender-bid-skill/scripts"
sys.path.insert(0, str(SCRIPTS))
import sources


class OcrSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / "synthetic_scan.pdf"
        writer = PdfWriter()
        for _ in range(2):
            page = writer.add_blank_page(width=300, height=400)
            drawing = DecodedStreamObject()
            drawing.set_data(b"10 10 100 100 re S\n")
            page[NameObject("/Contents")] = writer._add_object(drawing)
        with self.original.open("wb") as stream:
            writer.write(stream)
        self.input = self.root / "uploaded.pdf"
        shutil.copyfile(self.original, self.input)
        self.result = self.root / "content_list.json"
        self.items = [
            {"type": "header", "text": " 合成采购要求 ", "page_idx": 0},
            {"type": "text", "text": "须提交资格证明。\n限期3日。", "page_idx": 0},
            {"type": "table", "table_caption": ["合成表头"],
             "table_body": "<table><tr><td>不得缺项</td></tr></table>",
             "table_footnote": ["表后注释。"], "page_idx": 0},
            {"type": "image", "img_path": "images/synthetic.jpg", "image_caption": ["原页插图"],
             "image_footnote": ["图下注释。"], "page_idx": 1},
            {"type": "aside_text", "text": "须另附说明。", "page_idx": 1},
            {"type": "page_number", "text": "2", "page_idx": 1}]
        self.write_result()
        self.project = self.root / "project"
        self.initial = sources.initialize(self.project, [self.original])

    def write_result(self, items=None):
        self.result.write_text(json.dumps(self.items if items is None else items, ensure_ascii=False),
                               encoding="utf-8")

    def attach(self):
        return sources.attach_ocr(self.project, self.original, self.input, self.result)

    def prepare_review(self):
        self.attach()
        inventory = sources.read_json(self.project / "sources.json")
        inventory["scope"] = {"status": "confirmed", "basis": "Synthetic complete source set", "missing": []}
        inventory["cross_checks"] = {key: {"status": "不适用", "basis": "Synthetic source checked"}
                                     for key in ("references", "scoring", "forms")}
        record = inventory["sources"][0]
        rows = []
        for page in record["pages"]:
            text = page["ocr"]["text"]
            identifier = f"R{page['number']}"
            page.update(read_status="verified", read_basis="Synthetic original-page review",
                        reviewed_digest=sources.expected_review_digest(record, page),
                        coverage=[{"start_line": 1, "end_line": len(text.splitlines()),
                                   "status": "requirements_found", "checks": ["structure", "meaning", "risk"],
                                   "requirement_ids": [identifier], "note": "Synthetic review only"}])
            row = dict.fromkeys(sources.COLUMNS, "")
            row.update(requirement_id=identifier,
                       source_locations=f"主｜{self.original.name}｜{page['number']}｜合成全文",
                       source_text=text, requirement="按合成原文响应", type_and_consequence="资格和格式",
                       satisfaction_condition="完整响应", required_response_or_proof="证明和说明", status="已确认")
            rows.append(row)
        sources.write_json(self.project / "sources.json", inventory)
        sources.write_requirements(self.project / "requirements.csv", rows)
        return inventory

    def test_attach_preserves_native_text_and_does_not_claim_review(self):
        before = copy.deepcopy(self.initial["sources"][0]["pages"])
        data = self.attach()
        record = data["sources"][0]
        self.assertEqual(record["ocr"]["input_sha256"], sources.sha256(self.original))
        self.assertEqual(record["ocr"]["result_sha256"], sources.sha256(self.result))
        self.assertEqual(record["ocr"]["input_path"], str(self.input.resolve()))
        self.assertEqual(record["ocr"]["result_path"], str(self.result.resolve()))
        expected = [
            " 合成采购要求 \n\n须提交资格证明。\n限期3日。\n\n合成表头\n\n"
            "<table><tr><td>不得缺项</td></tr></table>\n\n表后注释。",
            "原页插图\n\n[原页图像：images/synthetic.jpg]\n\n图下注释。\n\n须另附说明。\n\n2"]
        for original, page, text in zip(before, record["pages"], expected):
            for key in ("text", "text_sha256", "method"):
                self.assertEqual(page[key], original[key])
            self.assertEqual(page["working_text_source"], "ocr")
            self.assertEqual(page["ocr"]["text"], text)
            self.assertEqual(page["ocr"]["page_idx"], page["number"] - 1)
            self.assertEqual(page["ocr"]["text_sha256"], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(page["read_status"], "needs_review")
            self.assertEqual(page["read_basis"], "")
            self.assertEqual(page["coverage"], [])
            self.assertNotIn("reviewed_digest", page)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_reviewed_ocr_drives_quotes_coverage_hints_and_freeze(self):
        self.prepare_review()
        report = sources.check_project(self.project)
        self.assertTrue(report["can_freeze"], report)
        self.assertTrue(any("须提交" in item["text"] for item in report["risk_hints"]))
        sources.freeze(self.project, "Synthetic reviewer", "Synthetic decision only", report["digest"])
        self.assertEqual(sources.check_project(self.project)["freeze_status"], "current")

    def test_native_pdf_keeps_existing_review_and_digest_contract(self):
        native = self.root / "synthetic_native.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=400)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font)})})
        text_stream = DecodedStreamObject()
        text_stream.set_data(b"BT /F1 12 Tf 10 20 Td (Provide certificate.) Tj ET\n")
        page[NameObject("/Contents")] = writer._add_object(text_stream)
        with native.open("wb") as stream:
            writer.write(stream)
        project = self.root / "native_project"
        data = sources.initialize(project, [native])
        data["scope"] = {"status": "confirmed", "basis": "Synthetic complete source", "missing": []}
        data["cross_checks"] = {key: {"status": "不适用", "basis": "Synthetic native source"}
                                for key in ("references", "scoring", "forms")}
        page = data["sources"][0]["pages"][0]
        self.assertIn("Provide certificate.", page["text"])
        page.update(read_status="verified", read_basis="Synthetic native page review",
                    coverage=[{"start_line": 1, "end_line": len(page["text"].splitlines()),
                               "status": "requirements_found", "checks": ["structure", "meaning", "risk"],
                               "requirement_ids": ["R1"]}])
        row = dict.fromkeys(sources.COLUMNS, "")
        row.update(requirement_id="R1", source_locations=f"主｜{native.name}｜1｜body", source_text=page["text"],
                   requirement="Provide certificate", type_and_consequence="Qualification",
                   satisfaction_condition="Certificate", required_response_or_proof="Certificate", status="已确认")
        sources.write_json(project / "sources.json", data)
        sources.write_requirements(project / "requirements.csv", [row])
        report = sources.check_project(project)
        self.assertTrue(report["can_freeze"], report)
        expected_payload = {"inventory": data, "requirements": [row], "live_sources": {native.name: sources.sha256(native)}}
        self.assertEqual(report["digest"], hashlib.sha256(json.dumps(expected_payload, ensure_ascii=False,
                         sort_keys=True).encode()).hexdigest())
        page["text"] = "Fabricated replacement"
        page["text_sha256"] = hashlib.sha256(page["text"].encode()).hexdigest()
        sources.write_json(project / "sources.json", data)
        self.assertFalse(sources.check_project(project)["can_freeze"])

    def test_bad_page_indices_or_body_shapes_leave_inventory_unchanged(self):
        cases = [[], [{"type": "text", "text": "one", "page_idx": 0}],
                 [{"type": "text", "text": "one", "page_idx": True}],
                 [{"type": "text", "text": "one", "page_idx": 2}],
                 [{"type": "text", "text": "one"}],
                 [{"type": "equation", "text": "unknown", "page_idx": 0}]]
        for change in ({"text": ["not a string"]}, {"page_idx": "0"}, {"page_idx": 0.0}):
            candidate = copy.deepcopy(self.items)
            candidate[0].update(change)
            cases.append(candidate)
        for change in ({"table_body": {"html": "unsupported"}}, {"table_caption": "unsupported"},
                       {"table_footnote": [1]}):
            candidate = copy.deepcopy(self.items)
            candidate[2].update(change)
            cases.append(candidate)
        candidate = copy.deepcopy(self.items)
        candidate[3]["img_path"] = ["unsupported"]
        cases.append(candidate)
        before = (self.project / "sources.json").read_bytes()
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.write_result(candidate)
                with self.assertRaises(ValueError):
                    self.attach()
                self.assertEqual((self.project / "sources.json").read_bytes(), before)

    def test_different_uploaded_pdf_or_original_is_rejected(self):
        self.input.write_bytes(self.input.read_bytes() + b"\n% changed input\n")
        with self.assertRaises(ValueError):
            self.attach()
        shutil.copyfile(self.original, self.input)
        self.original.write_bytes(self.original.read_bytes() + b"\n% changed source\n")
        with self.assertRaises(ValueError):
            self.attach()

    def test_duplicate_inventory_page_is_rejected(self):
        data = sources.read_json(self.project / "sources.json")
        data["sources"][0]["pages"][1]["number"] = 1
        sources.write_json(self.project / "sources.json", data)
        with self.assertRaises(ValueError):
            self.attach()

    def test_replacing_native_text_and_its_hash_does_not_pass(self):
        data = self.prepare_review()
        page = data["sources"][0]["pages"][0]
        page["text"] = "Fabricated native text"
        page["text_sha256"] = hashlib.sha256(page["text"].encode()).hexdigest()
        sources.write_json(self.project / "sources.json", data)
        report = sources.check_project(self.project)
        self.assertFalse(report["can_freeze"])
        self.assertTrue(any("原生" in item["evidence"] for item in report["findings"]))

    def test_forged_ocr_text_and_matching_hash_do_not_pass_raw_result_comparison(self):
        data = self.prepare_review()
        record = data["sources"][0]
        page = record["pages"][0]
        page["ocr"]["text"] = "Fabricated OCR text"
        page["ocr"]["text_sha256"] = hashlib.sha256(page["ocr"]["text"].encode()).hexdigest()
        page["reviewed_digest"] = sources.expected_review_digest(record, page)
        sources.write_json(self.project / "sources.json", data)
        report = sources.check_project(self.project)
        self.assertFalse(report["can_freeze"])
        self.assertTrue(any("OCR" in item["evidence"] for item in report["findings"]))

    def test_read_confirmation_must_bind_current_ocr_version(self):
        data = self.prepare_review()
        data["sources"][0]["pages"][0]["reviewed_digest"] = "stale"
        sources.write_json(self.project / "sources.json", data)
        report = sources.check_project(self.project)
        self.assertFalse(report["can_freeze"])
        self.assertTrue(any("读取确认" in item["evidence"] for item in report["findings"]))

    def test_input_or_result_change_invalidates_existing_freeze(self):
        self.prepare_review()
        report = sources.check_project(self.project)
        sources.freeze(self.project, "Synthetic reviewer", "Synthetic decision only", report["digest"])
        original_input, original_result = self.input.read_bytes(), self.result.read_bytes()
        for path in (self.input, self.result):
            with self.subTest(path=path.name):
                path.write_bytes(path.read_bytes() + b"\n ")
                changed = sources.check_project(self.project)
                self.assertFalse(changed["can_freeze"])
                self.assertEqual(changed["freeze_status"], "stale")
                self.input.write_bytes(original_input)
                self.result.write_bytes(original_result)
        self.result.unlink()
        missing = sources.check_project(self.project)
        self.assertFalse(missing["can_freeze"])
        self.assertEqual(missing["freeze_status"], "stale")

    def test_reattach_clears_prior_review_and_coverage(self):
        self.prepare_review()
        data = self.attach()
        for page in data["sources"][0]["pages"]:
            self.assertEqual(page["read_status"], "needs_review")
            self.assertEqual(page["read_basis"], "")
            self.assertEqual(page["coverage"], [])
            self.assertNotIn("reviewed_digest", page)

    def test_literal_correction_preserves_raw_result_and_is_used_for_coverage_and_quotes(self):
        data = self.prepare_review()
        record = data["sources"][0]
        page = record["pages"][0]
        raw_text, raw_hash = page["ocr"]["text"], page["ocr"]["text_sha256"]
        page["ocr"]["corrections"] = [{"before": "<td>不得缺项</td>",
                                       "after": "<td>合成地址甲</td>",
                                       "basis": "合成原PDF第1页地址单元格"}]
        corrected = sources.page_working_text(page)
        self.assertIn("合成地址甲", corrected)
        self.assertEqual(page["ocr"]["text"], raw_text)
        self.assertEqual(page["ocr"]["text_sha256"], raw_hash)
        page["reviewed_digest"] = sources.expected_review_digest(record, page)
        rows = sources.read_requirements(self.project / "requirements.csv")
        rows[0]["source_text"] = corrected
        sources.write_json(self.project / "sources.json", data)
        sources.write_requirements(self.project / "requirements.csv", rows)
        self.assertTrue(sources.check_project(self.project)["can_freeze"])

    def test_corrections_require_a_unique_literal_and_recorded_basis(self):
        data = self.prepare_review()
        valid = {"before": "<td>不得缺项</td>", "after": "<td>合成地址甲</td>", "basis": "合成原页核对"}
        for change in ({"before": ""}, {"before": "not present"}, {"before": "。"},
                       {"after": ["unsupported"]}, {"basis": ""}, {"basis": "  "}):
            with self.subTest(change=change):
                candidate = copy.deepcopy(data)
                candidate["sources"][0]["pages"][0]["ocr"]["corrections"] = [dict(valid, **change)]
                sources.write_json(self.project / "sources.json", candidate)
                report = sources.check_project(self.project)
                self.assertFalse(report["can_freeze"])
                self.assertTrue(any("修正" in item["evidence"] for item in report["findings"]))

    def test_correction_or_its_basis_change_invalidates_old_review_and_freeze(self):
        data = self.prepare_review()
        report = sources.check_project(self.project)
        sources.freeze(self.project, "Synthetic reviewer", "Synthetic decision only", report["digest"])
        record = data["sources"][0]
        page = record["pages"][0]
        page["ocr"]["corrections"] = [{"before": "<td>不得缺项</td>", "after": "<td>合成地址甲</td>",
                                       "basis": "合成原PDF第1页"}]
        sources.write_json(self.project / "sources.json", data)
        changed = sources.check_project(self.project)
        self.assertFalse(changed["can_freeze"])
        self.assertEqual(changed["freeze_status"], "stale")
        self.assertTrue(any("读取确认" in item["evidence"] for item in changed["findings"]))
        first = sources.expected_review_digest(record, page)
        page["ocr"]["corrections"][0]["basis"] = "合成原PDF第1页完整单元格"
        self.assertNotEqual(first, sources.expected_review_digest(record, page))

    def test_cli_attach_accepts_existing_raw_result_and_remains_unreviewed(self):
        completed = subprocess.run([sys.executable, str(SCRIPTS / "tender.py"), "attach-ocr",
                                   "--project", str(self.project), "--source", str(self.original),
                                   "--input", str(self.input), "--result", str(self.result)],
                                  text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["pages"], 2)
        self.assertEqual(sources.read_json(self.project / "sources.json")["sources"][0]["pages"][0]
                         ["read_status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
