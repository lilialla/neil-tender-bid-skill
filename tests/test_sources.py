"""Synthetic source-side regression tests; no business documents."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/neil-tender-bid-skill/scripts"))
import sources
import chapters


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / "采购.txt"
        self.original.write_text("第一章\n参与人提供资格证明。\n注：证明须含有效期。\f第二章\n每项1.5分，最高4分。", encoding="utf-8")
        self.project = self.root / "回放"
        sources.initialize(self.project, [self.original])

    def prepare(self):
        record = sources.read_json(self.project / "sources.json")
        record["scope"] = {"status": "confirmed", "basis": "合成案例完整输入", "missing": []}
        for page in record["sources"][0]["pages"]:
            page["read_status"] = "verified"
            page["read_basis"] = "合成纯文本逐行核对"
            page["coverage"] = [{"start_line": 1, "end_line": len(page["text"].splitlines()),
                "status": "requirements_found", "requirement_ids": [f"R{page['number']}"],
                "checks": ["structure", "meaning", "risk"], "note": "逐行处理正文与备注"}]
        record["cross_checks"] = {
            name: {"status": "通过", "basis": "合成原文检查"}
            for name in ("references", "scoring", "forms")}
        sources.write_json(self.project / "sources.json", record)
        rows = []
        for number, text in [(1, "参与人提供资格证明。\n注：证明须含有效期。"), (2, "每项1.5分，最高4分。")]:
            row = dict.fromkeys(sources.COLUMNS, "")
            row.update(requirement_id=f"R{number}", source_locations=f"主｜采购.txt｜{number}｜正文及注释",
                source_text=text, requirement="按原文提供证明或计分", type_and_consequence="资格" if number == 1 else "评分",
                satisfaction_condition="完整原文标准", required_response_or_proof="证明材料", status="已确认")
            rows.append(row)
        sources.write_requirements(self.project / "requirements.csv", rows)
        return record

    def test_initial_inventory_is_not_review_or_freeze(self):
        report = sources.check_project(self.project)
        self.assertFalse(report["can_freeze"])
        self.assertTrue(report["risk_hints"])
        self.assertEqual(len(sources.read_requirements(self.project / "requirements.csv")), 0)

    def test_source_and_chapter_readers_reject_the_same_invalid_ledger(self):
        self.prepare()
        valid = sources.read_requirements(self.project / "requirements.csv")
        for field, value in (("requirement_id", "R1 "), ("requirement_id", " R1"),
                             ("requirement", ""), ("status", "unknown")):
            with self.subTest(field=field, value=value):
                rows = [dict(valid[0], **{field: value}), valid[1]]
                with (self.project / "requirements.csv").open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=sources.COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows)
                for reader in (sources.read_requirements, chapters.read_requirements):
                    with self.assertRaises(ValueError):
                        reader(self.project / "requirements.csv")
                with self.assertRaises(ValueError):
                    sources.write_requirements(self.root / "invalid.csv", rows)

    def test_full_source_coverage_and_frozen_version(self):
        self.prepare()
        report = sources.check_project(self.project)
        self.assertTrue(report["can_freeze"], report)
        frozen = sources.freeze(self.project, "合成复核人", "test-only decision", report["digest"])
        self.assertTrue(frozen.exists())
        self.assertEqual(sources.check_project(self.project)["freeze_status"], "current")

    def test_unprocessed_footnote_prevents_freeze(self):
        data = self.prepare()
        data["sources"][0]["pages"][0]["coverage"][0]["end_line"] = 2
        sources.write_json(self.project / "sources.json", data)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_false_no_requirement_with_link_is_rejected(self):
        data = self.prepare()
        data["sources"][0]["pages"][0]["coverage"][0]["status"] = "no_requirement"
        sources.write_json(self.project / "sources.json", data)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_cross_page_condition_requires_both_pages(self):
        self.prepare()
        rows = sources.read_requirements(self.project / "requirements.csv")
        rows[1]["source_locations"] = "主｜采购.txt｜2-3｜跨页评分条件"
        sources.write_requirements(self.project / "requirements.csv", rows)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_changed_source_invalidates_check_and_freeze(self):
        self.prepare()
        report = sources.check_project(self.project)
        sources.freeze(self.project, "合成复核人", "test-only", report["digest"])
        self.original.write_text("补遗更换后的来源", encoding="utf-8")
        report = sources.check_project(self.project)
        self.assertFalse(report["can_freeze"])
        self.assertEqual(report["freeze_status"], "stale")

    def test_csv_content_change_invalidates_human_digest(self):
        self.prepare()
        report = sources.check_project(self.project)
        rows = sources.read_requirements(self.project / "requirements.csv")
        rows[0]["requirement"] = "修改后的要求"
        sources.write_requirements(self.project / "requirements.csv", rows)
        with self.assertRaises(ValueError):
            sources.freeze(self.project, "合成复核人", "test-only", report["digest"])

    def test_unreadable_page_cannot_be_declared_empty(self):
        data = self.prepare()
        data["sources"][0]["pages"][1]["read_status"] = "unreadable"
        sources.write_json(self.project / "sources.json", data)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_conflicting_location_remains_reviewable(self):
        self.prepare()
        rows = sources.read_requirements(self.project / "requirements.csv")
        rows[0]["source_locations"] += "\n冲突｜采购.txt｜2｜说明"
        rows[0]["status"] = "待澄清"
        rows[0]["ambiguity_or_clarification"] = "待负责人解释"
        sources.write_requirements(self.project / "requirements.csv", rows)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_zero_pdf_is_not_healthy(self):
        bad = self.root / "坏件.pdf"
        bad.write_bytes(b"\0" * 100)
        record = sources.inspect_file(bad)
        self.assertEqual(record["health"], "invalid")
        self.assertEqual(record["pages"], [])

    def test_candidate_replay_separates_missed_and_corrected(self):
        self.prepare()
        rows = sources.read_requirements(self.project / "requirements.csv")
        candidate = [dict(rows[0], satisfaction_condition="不完整")]
        result = sources.replay(candidate, rows)
        self.assertEqual(result["missed_ids"], ["R2"])
        self.assertEqual(result["corrected_ids"], ["R1"])
        self.assertEqual(result["high_risk_missed_ids"], ["R2"])

    def test_initialization_never_overwrites(self):
        with self.assertRaises(FileExistsError):
            sources.initialize(self.project, [self.original])

    def test_dangling_replacement_cannot_freeze(self):
        self.prepare()
        rows = sources.read_requirements(self.project / "requirements.csv")
        for row in rows:
            row.update(status="已被补遗取代", ambiguity_or_clarification="替代要求：R999")
        sources.write_requirements(self.project / "requirements.csv", rows)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])

    def test_fabricated_quote_and_inventory_page_count_fail(self):
        data = self.prepare()
        data["sources"][0]["pages"].pop()
        sources.write_json(self.project / "sources.json", data)
        rows = sources.read_requirements(self.project / "requirements.csv")
        rows[0]["source_text"] = "这句话不存在于采购原文。"
        sources.write_requirements(self.project / "requirements.csv", rows)
        report = sources.check_project(self.project)
        self.assertFalse(report["can_freeze"])
        self.assertTrue(any("页数" in item["evidence"] for item in report["findings"]))
        self.assertTrue(any("引文" in item["evidence"] for item in report["findings"]))

    def test_empty_cancellation_reason_cannot_bypass_replacement(self):
        self.prepare()
        rows = sources.read_requirements(self.project / "requirements.csv")
        rows[0].update(status="已被补遗取代", ambiguity_or_clarification="撤销依据：",
                       source_locations="修｜采购.txt｜1｜正文及注释")
        sources.write_requirements(self.project / "requirements.csv", rows)
        self.assertFalse(sources.check_project(self.project)["can_freeze"])


if __name__ == "__main__":
    unittest.main()
