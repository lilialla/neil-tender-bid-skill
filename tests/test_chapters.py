"""Phase 1 behavior checks. All names, prices and documents are synthetic."""

import copy
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills/neil-tender-bid-skill/scripts/chapters.py"
SPEC = importlib.util.spec_from_file_location("chapters", SCRIPT)
chapters = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chapters)


def requirement(identifier):
    return dict(zip(chapters.REQUIREMENT_COLUMNS, [
        identifier, "synthetic.pdf p1 段1", "应提供指定人员的服务证明。",
        "提供证明", "证明缺失待补", "人员及期间一致", "服务证明", "", "已确认",
    ]))


def fixture():
    ledger = [requirement("R1"), requirement("R2"), requirement("R3")]
    checklist = {
        "shared": {
            "lawyer": {"value": "合成人员甲", "status": "confirmed", "source": "合成选择记录"},
            "response_hours": {"value": "2小时", "status": "confirmed", "source": "合成决定",
                               "kind": "commitment", "approval": {"by": "测试负责人", "decision": "approve"}},
            "start": {"value": "2026-01-01", "status": "confirmed", "source": "合成服务计划"},
            "end": {"value": "2026-12-31", "status": "confirmed", "source": "合成服务计划"},
            "unused": {"value": "不能进入章节的无关信息", "status": "confirmed", "source": "合成资料"},
        },
        "materials": {
            "M1": {"path": "synthetic-proof.pdf", "sha256": "a" * 64, "pages": [1],
                   "person": "合成人员甲", "period_start": "2026-01-01", "period_end": "2026-12-31",
                   "status": "confirmed"},
            "M2": {"path": "unrelated.pdf", "sha256": "b" * 64, "pages": [1]},
        },
        "chapters": [
            {"id": "team", "path": "商务/团队", "requirement_ids": ["R1"],
             "shared_keys": ["lawyer", "start", "end"], "material_ids": ["M1"],
             "template": "人员：{{lawyer}}；服务期：{{start}}至{{end}}。", "output": "team.md",
             "material_checks": [{"material_id": "M1", "requirement_id": "R1", "person_key": "lawyer",
                                  "period_start_key": "start", "period_end_key": "end"}]},
            {"id": "service", "path": "技术/服务", "requirement_ids": ["R2"],
             "shared_keys": ["lawyer", "response_hours"], "material_ids": [],
             "template": "{{lawyer}}负责响应；时限：{{response_hours}}。", "output": "service.md"},
            {"id": "other", "path": "其他", "requirement_ids": ["R3"], "shared_keys": [],
             "material_ids": [], "template": "合成固定内容。", "output": "other.md"},
        ],
        "global_constraints": [{"scope": ["team", "service"], "requirement_ids": ["R2"], "text": "不得改变已批准时限。"}],
    }
    return checklist, ledger


def results_for(checklist, ledger):
    return {c["id"]: chapters.render_chapter(chapters.prepare_packet(checklist, ledger, c["id"]))
            for c in checklist["chapters"]}


class ChaptersTests(unittest.TestCase):
    def test_scoped_check_does_not_report_other_unbuilt_chapters_as_missing(self):
        checklist, ledger = fixture()
        results = results_for(checklist, ledger)
        scoped = chapters.validate_chapters(checklist, ledger + [requirement("R4")],
                                            {"team": results["team"]}, chapter_ids=["team"])
        self.assertEqual(scoped, [])
        whole = chapters.validate_chapters(checklist, ledger + [requirement("R4")], results)
        self.assertTrue(any(x["code"] == "unmapped_requirement" and x["requirement_id"] == "R4" for x in whole))
        invalid = chapters.validate_chapters(checklist, ledger, results, chapter_ids=["unknown"])
        self.assertTrue(any(x["code"] == "invalid_input" for x in invalid))
        tampered = dict(results["team"], used_values={"lawyer": "wrong person"})
        self.assertTrue(chapters.validate_chapters(checklist, ledger, {"team": tampered}, chapter_ids=["team"]))

    def test_exact_nine_columns_csv_and_duplicate_id_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=chapters.REQUIREMENT_COLUMNS)
                writer.writeheader()
                writer.writerow(requirement("R1"))
            self.assertEqual(chapters.read_requirements(path)[0]["requirement_id"], "R1")
            with path.open("a", encoding="utf-8", newline="") as file:
                csv.DictWriter(file, fieldnames=chapters.REQUIREMENT_COLUMNS).writerow(requirement("R1"))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                chapters.read_requirements(path)
            path.write_text("requirement_id,status\nR1,已确认\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nine|9"):
                chapters.read_requirements(path)

    def test_packet_contains_only_selected_and_complete_sources(self):
        checklist, ledger = fixture()
        packet = chapters.prepare_packet(checklist, ledger, "team")
        self.assertEqual(set(packet["shared"]), {"lawyer", "start", "end"})
        self.assertEqual(set(packet["materials"]), {"M1"})
        self.assertEqual(packet["requirements"], ledger[:2])
        self.assertNotIn("unused", str(packet))
        packet["shared"]["lawyer"]["value"] = "修改隔离副本"
        self.assertEqual(checklist["shared"]["lawyer"]["value"], "合成人员甲")

    def test_pending_fact_and_unapproved_commitment_render_empty_with_internal_gaps(self):
        checklist, ledger = fixture()
        checklist["shared"]["lawyer"]["status"] = "pending"
        checklist["shared"]["response_hours"].pop("approval")
        result = chapters.render_chapter(chapters.prepare_packet(checklist, ledger, "service"))
        self.assertEqual(result["content"], "【】负责响应；时限：【】。")
        self.assertEqual(result["used_values"], {})
        self.assertEqual(len(result["gaps"]), 2)
        self.assertNotIn("合成人员甲", result["content"])

    def test_missing_reference_is_visible_and_never_unchanged(self):
        checklist, ledger = fixture()
        after = copy.deepcopy(checklist)
        after["chapters"][0]["template"] += "{{unknown}}"
        with self.assertRaisesRegex(ValueError, "unknown"):
            chapters.prepare_packet(after, ledger, "team")
        change = chapters.impact(checklist, after, ledger, ledger)
        self.assertIn("team", change["uncertain"])
        self.assertNotIn("team", change["unchanged"])
        self.assertTrue(change["issues"])

    def test_change_shared_lawyer_affects_both_references_only(self):
        checklist, ledger = fixture()
        after = copy.deepcopy(checklist)
        after["shared"]["lawyer"]["value"] = "合成人员乙"
        change = chapters.impact(checklist, after, ledger, ledger)
        self.assertEqual(change["affected"], ["team", "service"])
        self.assertEqual(change["unchanged"], ["other"])
        self.assertEqual(change["uncertain"], [])

    def test_new_unmapped_requirement_is_unknown_impact_not_no_impact(self):
        checklist, ledger = fixture()
        after_ledger = ledger + [requirement("R4")]
        change = chapters.impact(checklist, checklist, ledger, after_ledger)
        self.assertEqual(change["unchanged"], [])
        self.assertEqual(set(change["uncertain"]), {"team", "service", "other"})
        self.assertIn("R4", str(change["issues"]))

    def test_global_constraint_fact_and_material_are_real_dependencies(self):
        checklist, ledger = fixture()
        rule = checklist["global_constraints"][0]
        rule.update(shared_keys=["response_hours"], material_ids=["M1"], text="不得改变{{response_hours}}响应时限。")
        packet = chapters.prepare_packet(checklist, ledger, "team")
        self.assertIn("response_hours", packet["shared"])
        after = copy.deepcopy(checklist)
        after["shared"]["response_hours"]["value"] = "1小时"
        changed = chapters.impact(checklist, after, ledger, ledger)
        self.assertEqual(changed["affected"], ["team", "service"])
        self.assertIn("M1", chapters.prepare_packet(checklist, ledger, "service")["materials"])
        rule["material_ids"] = ["missing-material"]
        with self.assertRaises(ValueError):
            chapters.prepare_packet(checklist, ledger, "team")

    def test_material_requirement_template_and_global_changes_have_local_effect(self):
        checklist, ledger = fixture()
        after = copy.deepcopy(checklist)
        after["materials"]["M1"]["sha256"] = "c" * 64
        self.assertEqual(chapters.impact(checklist, after, ledger, ledger)["affected"], ["team"])
        later = copy.deepcopy(ledger)
        later[1]["source_text"] = "补遗后的完整时限要求。"
        self.assertEqual(chapters.impact(checklist, checklist, ledger, later)["affected"], ["team", "service"])
        after = copy.deepcopy(checklist)
        after["chapters"][2]["template"] = "新的固定内容。"
        self.assertEqual(chapters.impact(checklist, after, ledger, ledger)["affected"], ["other"])
        after = copy.deepcopy(checklist)
        after["shared"]["unused"]["value"] = "无关变化"
        self.assertEqual(chapters.impact(checklist, after, ledger, ledger)["affected"], [])

    def test_valid_two_chapters_are_consistent(self):
        checklist, ledger = fixture()
        self.assertEqual(chapters.validate_chapters(checklist, ledger, results_for(checklist, ledger)), [])

    def test_wrong_person_wrong_period_preserve_findings_with_continue_decision(self):
        checklist, ledger = fixture()
        checklist["materials"]["M1"].update(person="其他人员", period_end="2026-06-30")
        checklist["chapters"][0]["decisions"] = [{"by": "测试负责人", "action": "continue", "reason": "先生成工作稿"}]
        findings = chapters.validate_chapters(checklist, ledger, results_for(checklist, ledger))
        codes = {finding["code"] for finding in findings}
        self.assertTrue({"material_person_mismatch", "material_period_mismatch"} <= codes)
        self.assertTrue(all(f["status"] == "阻断" for f in findings))
        self.assertEqual(findings[0]["decisions"][0]["action"], "continue")

    def test_missing_mapping_and_tampered_used_values_are_reported(self):
        checklist, ledger = fixture()
        results = results_for(checklist, ledger)
        results["team"]["used_values"]["lawyer"] = "串用人员"
        ledger.append(requirement("R4"))
        findings = chapters.validate_chapters(checklist, ledger, results)
        self.assertIn("unmapped_requirement", {f["code"] for f in findings})
        self.assertIn("used_value_mismatch", {f["code"] for f in findings})

    def test_all_required_response_locations_are_checked(self):
        checklist, ledger = fixture()
        results = results_for(checklist, ledger)
        del results["service"]
        findings = chapters.validate_chapters(checklist, ledger, results)
        self.assertIn("missing_result", {f["code"] for f in findings})

    def test_quote_round_conflicts_not_different_rounds(self):
        checklist, ledger = fixture()
        checklist["shared"].update({
            "quote_a": {"kind": "quote", "round": "round-1", "value": "100000", "status": "confirmed", "source": "合成报价决定"},
            "quote_b": {"kind": "quote", "round": "round-1", "value": "96600", "status": "confirmed", "source": "合成报价决定"},
        })
        findings = chapters.validate_chapters(checklist, ledger, results_for(checklist, ledger))
        self.assertIn("quote_round_conflict", {f["code"] for f in findings})
        checklist["shared"]["quote_b"]["round"] = "round-2"
        self.assertNotIn("quote_round_conflict", {f["code"] for f in chapters.validate_chapters(checklist, ledger, results_for(checklist, ledger))})

    def test_body_tampering_and_stale_material_dependency_are_visible(self):
        checklist, ledger = fixture()
        results = results_for(checklist, ledger)
        results["team"]["content"] += "未经批准的新承诺。"
        self.assertIn("template_content_mismatch", {f["code"] for f in chapters.validate_chapters(checklist, ledger, results)})
        results = results_for(checklist, ledger)
        checklist["materials"]["M1"]["sha256"] = "d" * 64
        self.assertIn("stale_result", {f["code"] for f in chapters.validate_chapters(checklist, ledger, results)})

    def test_unconfirmed_requirement_and_hidden_gap_do_not_pass(self):
        checklist, ledger = fixture()
        ledger[0]["status"] = "待澄清"
        checklist["shared"]["lawyer"]["status"] = "pending"
        results = results_for(checklist, ledger)
        results["team"]["gaps"] = []
        codes = {f["code"] for f in chapters.validate_chapters(checklist, ledger, results)}
        self.assertIn("requirement_pending", codes)
        self.assertIn("gap_disclosure_mismatch", codes)

    def test_global_unknown_scope_is_visible_and_manual_result_needs_review(self):
        checklist, ledger = fixture()
        checklist["global_constraints"][0]["scope"] = ["typo"]
        with self.assertRaisesRegex(ValueError, "scope"):
            chapters.prepare_packet(checklist, ledger, "team")
        checklist, ledger = fixture()
        results = results_for(checklist, ledger)
        checklist["chapters"][0].pop("template")
        codes = {f["code"] for f in chapters.validate_chapters(checklist, ledger, results)}
        self.assertIn("semantic_review_required", codes)

    def test_csv_row_length_and_malformed_placeholder_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text(",".join(chapters.REQUIREMENT_COLUMNS) + "\nR1,missing\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                chapters.read_requirements(path)
        checklist, ledger = fixture()
        checklist["chapters"][0]["template"] = "{{lawyer"
        with self.assertRaisesRegex(ValueError, "malformed"):
            chapters.prepare_packet(checklist, ledger, "team")


class PerformanceTests(unittest.TestCase):
    def test_whitespace_variant_cannot_count_as_an_independent_record(self):
        rule = {"status": "confirmed", "source": "synthetic", "points_per_item": "2", "max_points": "4",
                "subject_type": "firm", "subject_id": "synthetic-firm"}
        record = {"id": "contract-1", "status": "confirmed", "source": "synthetic", "subject_type": "firm",
                  "subject_id": "synthetic-firm"}
        with self.assertRaises(ValueError):
            chapters.score_performance([record, dict(record, id="contract-1 ")], rule)

    def setUp(self):
        self.rule = {"points_per_item": "1.5", "max_points": "4", "subject_type": "person",
                     "subject_id": "person-a", "start_date": "2024-01-01", "end_date": "2026-09-01",
                     "status": "confirmed", "source": "合成评分原文 R1"}
        self.candidates = [{"id": f"contract-{i}", "subject_type": "person", "subject_id": "person-a",
                            "completed_on": "2025-01-01", "status": "confirmed", "source": "合成合同关键页",
                            "page_count": 2} for i in range(1, 5)]

    def test_ceiling_minimum_plus_one_backup_and_score_cap(self):
        result = chapters.score_performance(self.candidates, self.rule)
        self.assertEqual(result["minimum_for_full_score"], 3)
        self.assertEqual(result["target_count"], 4)
        self.assertEqual(result["score"], "4")
        self.assertEqual(result["backup_count"], 1)

    def test_copies_dont_score_wrong_subject_and_date_are_excluded(self):
        candidates = self.candidates[:1] + [copy.deepcopy(self.candidates[0])]
        candidates += [dict(self.candidates[1], subject_id="person-b"),
                       dict(self.candidates[2], subject_type="firm"),
                       dict(self.candidates[3], completed_on="2023-01-01")]
        result = chapters.score_performance(candidates, self.rule)
        self.assertEqual(result["eligible_ids"], ["contract-1"])
        self.assertEqual(result["score"], "1.5")
        self.assertEqual(len(result["excluded"]), 3)
        self.assertEqual(result["duplicate_ids"], ["contract-1"])

    def test_submission_and_page_limits_reduce_backup_without_fake_full_score(self):
        result = chapters.score_performance(self.candidates, dict(self.rule, max_count=3))
        self.assertEqual(result["target_count"], 3)
        self.assertEqual(result["backup_count"], 0)
        self.assertEqual(result["score"], "4")
        result = chapters.score_performance(self.candidates, dict(self.rule, page_limit=4))
        self.assertEqual(len(result["selected_ids"]), 2)
        self.assertEqual(result["score"], "3")
        self.assertTrue(result["limitations"])

    def test_conflicting_duplicates_are_not_arbitrarily_counted(self):
        candidates = [self.candidates[0], dict(self.candidates[0], subject_id="person-b")]
        result = chapters.score_performance(candidates, self.rule)
        self.assertEqual(result["score"], "0")
        self.assertEqual(result["conflicting_ids"], ["contract-1"])

    def test_unconfirmed_scoring_rule_is_not_calculated(self):
        with self.assertRaisesRegex(ValueError, "confirmed"):
            chapters.score_performance(self.candidates, dict(self.rule, status="pending"))


if __name__ == "__main__":
    unittest.main()
