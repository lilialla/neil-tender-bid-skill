"""PDF fixtures are generated from scratch in an isolated temporary folder."""
from pathlib import Path
import sys
import tempfile
import unittest
from pypdf import PdfReader, PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/neil-tender-bid-skill/scripts"))
import assembly
from sources import sha256


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / "synthetic.pdf"
        writer = PdfWriter()
        for width in (100, 200, 300):
            writer.add_blank_page(width=width, height=400)
        with self.original.open("wb") as stream:
            writer.write(stream)

    def part(self, pages):
        return {"path": str(self.original), "sha256": sha256(self.original), "pages": pages}

    def test_selected_pages_and_repeated_external_display(self):
        report = assembly.assemble_pdf([self.part([3, 1]), self.part([1])], self.root / "assembled.pdf")
        self.assertEqual([p["source_page"] for p in report["page_map"]], [3, 1, 1])
        self.assertEqual([int(p.mediabox.width) for p in PdfReader(report["path"]).pages], [300, 100, 100])

    def test_stamp_and_regular_parts_are_from_same_master(self):
        output = assembly.assemble_pdf([self.part([1, 2, 3])], self.root / "master.pdf")
        result = assembly.derive_stamp_parts(output, [2], self.root / "derived")
        self.assertEqual(result["stamp"]["page_map"][0]["source_page"], 2)
        self.assertEqual([p["source_page"] for p in result["regular"]["page_map"]], [1, 3])
        self.assertEqual(result["source_sha256"], output["sha256"])

    def test_changed_input_and_invalid_page_are_rejected_before_write(self):
        bad = dict(self.part([1]), sha256="0" * 64)
        target = self.root / "bad.pdf"
        with self.assertRaises(ValueError):
            assembly.assemble_pdf([bad], target)
        self.assertFalse(target.exists())
        with self.assertRaises(ValueError):
            assembly.assemble_pdf([self.part([4])], target)
        self.assertFalse(target.exists())

    def test_output_never_overwrites_original(self):
        before = sha256(self.original)
        with self.assertRaises(FileExistsError):
            assembly.assemble_pdf([self.part([1])], self.original)
        self.assertEqual(sha256(self.original), before)

    def test_wrong_master_page_count_never_omits_tail(self):
        master = assembly.assemble_pdf([self.part([1, 2, 3])], self.root / "master.pdf")
        master["page_count"] = 2
        with self.assertRaises(ValueError):
            assembly.derive_stamp_parts(master, [1], self.root / "derived")
        self.assertFalse((self.root / "derived").exists())

    def test_basis_changes_invalidate_previous_checks(self):
        import sources
        procurement = self.root / "采购.txt"
        procurement.write_text("提供响应。", encoding="utf-8")
        project = self.root / "项目"
        sources.initialize(project, [procurement])
        item = assembly.assemble_pdf([self.part([1])], self.root / "candidate.pdf")
        old = assembly.assess_files([item], [], {}, "signing", source_project=project, context={"shared": {}})
        checks = [{"gate": gate, "stage": "signing", "result": "通过", "evidence": "合成核对",
                   "files_digest": old["files_digest"], "basis_digest": old["basis_digest"]}
                  for gate in ("G1", "G2", "G3", "G4", "G5", "G6")]
        procurement.write_text("补遗后的响应要求。", encoding="utf-8")
        changed = assembly.assess_files([item], checks, {}, "signing", source_project=project, context={"shared": {}})
        self.assertNotEqual(old["basis_digest"], changed["basis_digest"])
        self.assertFalse(changed["all_checks_passed"])
        fact_change = assembly.assess_files([item], checks, {}, "signing", source_project=project,
                                              context={"shared": {"lawyer": "合成乙"}})
        self.assertNotEqual(changed["basis_digest"], fact_change["basis_digest"])

    def test_empty_parts_and_zero_pdf_are_rejected(self):
        with self.assertRaises(ValueError):
            assembly.assemble_pdf([], self.root / "empty.pdf")
        self.original.write_bytes(b"\0" * 200)
        with self.assertRaises(ValueError):
            assembly.assemble_pdf([self.part([1])], self.root / "bad.pdf")

    def test_changed_candidate_invalidates_checks_and_approval(self):
        item = assembly.assemble_pdf([self.part([1])], self.root / "candidate.pdf")
        value = assembly.assess_files([item], [], {}, "signing")
        self.assertEqual(value["state"], "工作稿")
        Path(item["path"]).write_bytes(b"replacement")
        value = assembly.assess_files([item], [], {"continue_decision": "合成负责人决定继续"}, "signing")
        self.assertFalse(value["all_checks_passed"])
        self.assertTrue(any(x["item"] == "文件版本" for x in value["findings"]))

    def test_human_continue_does_not_clear_gap_or_create_submission(self):
        item = assembly.assemble_pdf([self.part([1])], self.root / "candidate.pdf")
        value = assembly.assess_files([item], [], {"continue_decision": "合成测试决定继续编制"}, "signing")
        self.assertEqual(value["state"], "待签章稿（按人工决定编制，检查缺口保留）")
        self.assertFalse(value["all_checks_passed"])
        self.assertFalse(value["submitted"])

    def test_submission_requires_actual_confirmation_and_receipt_binding(self):
        item = assembly.assemble_pdf([self.part([1])], self.root / "candidate.pdf")
        missing = assembly.assess_files([item], [], {"submitted": True}, "submitted")
        self.assertFalse(missing["submitted"])
        receipt = self.root / "synthetic-receipt.txt"
        receipt.write_text("Synthetic receipt only", encoding="utf-8")
        evidence = {"confirmed_by": "Synthetic operator", "basis": "test-only execution attestation",
                    "files_digest": assembly.files_digest([item]), "path": str(receipt), "sha256": sha256(receipt)}
        actual = assembly.assess_files([item], [], {"submission": evidence}, "submitted")
        self.assertTrue(actual["submitted"])
        self.assertFalse(actual["all_checks_passed"])
        self.assertIn("不等于采购人接受", actual["state"])


if __name__ == "__main__":
    unittest.main()
