"""Run the installed-style entrypoint across one entirely synthetic closed loop."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/neil-tender-bid-skill/scripts"
sys.path.insert(0, str(SCRIPTS))
import assembly
import sources


class CliTests(unittest.TestCase):
    def test_synthetic_source_to_two_chapters_and_candidate_status(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "synthetic.txt"
            raw.write_text("拟派人员负责服务响应。\n响应时限为2小时。", encoding="utf-8")
            project = root / "project"

            def cli(*args, code=0):
                process = subprocess.run([sys.executable, str(SCRIPTS / "tender.py"), *map(str, args)],
                                         text=True, capture_output=True, check=False)
                self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                return json.loads(process.stdout) if process.stdout else None

            cli("init", "--project", project, "--source", raw)
            first = cli("check", "--project", project, code=1)
            self.assertEqual(first["freeze_status"], "none")
            data = sources.read_json(project / "sources.json")
            data["scope"] = {"status": "confirmed", "basis": "Synthetic complete source set", "missing": []}
            page = data["sources"][0]["pages"][0]
            page.update(read_status="verified", read_basis="Synthetic text reviewed",
                        coverage=[{"start_line": 1, "end_line": 2, "status": "requirements_found",
                                   "requirement_ids": ["R1"], "checks": ["structure", "meaning", "risk"]}])
            data["cross_checks"] = {key: {"status": "不适用", "basis": "Synthetic source has no such structures"}
                                    for key in ("references", "scoring", "forms")}
            sources.write_json(project / "sources.json", data)
            row = dict.fromkeys(sources.COLUMNS, "")
            row.update(requirement_id="R1", source_locations="主｜synthetic.txt｜1｜两条合成关联响应",
                       source_text=raw.read_text(), requirement="指定人员及时响应", type_and_consequence="服务要求",
                       satisfaction_condition="2小时", required_response_or_proof="团队及服务安排", status="已确认")
            sources.write_requirements(project / "requirements.csv", [row])
            checked = cli("check", "--project", project)
            cli("freeze", "--project", project, "--reviewer", "Synthetic reviewer", "--decision-reference",
                "TEST ONLY: synthetic authorized freeze", "--expected-digest", checked["digest"])
            checklist = {"shared": {"lawyer": {"value": "合成人员甲", "status": "confirmed", "source": "合成决定"}},
                         "materials": {}, "global_constraints": [], "chapters": [
                             {"id": identifier, "path": identifier, "requirement_ids": ["R1"], "shared_keys": ["lawyer"],
                              "material_ids": [], "template": "{{lawyer}}负责2小时内响应。"} for identifier in ("team", "service")]}
            checklist_path = root / "checklist.json"
            sources.write_json(checklist_path, checklist)
            results = {}
            for identifier in ("team", "service"):
                packet, result = root / f"{identifier}-packet.json", root / f"{identifier}-result.json"
                cli("packet", "--checklist", checklist_path, "--requirements", project / "requirements.csv",
                    "--chapter", identifier, "--out", packet)
                cli("render", "--packet", packet, "--out", result)
                results[identifier] = sources.read_json(result)
                self.assertIn("合成人员甲", results[identifier]["content"])
            result_path = root / "results.json"
            sources.write_json(result_path, results)
            self.assertEqual(cli("chapters-check", "--checklist", checklist_path, "--requirements",
                                 project / "requirements.csv", "--results", result_path), [])
            pdf = root / "synthetic.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=200)
            with pdf.open("wb") as stream:
                writer.write(stream)
            parts_path = root / "parts.json"
            sources.write_json(parts_path, [{"path": str(pdf), "sha256": sources.sha256(pdf), "pages": [1]}])
            master_path = root / "master.json"
            cli("assemble", "--parts", parts_path, "--out", root / "assembled.pdf", "--manifest", master_path)
            cli("derive", "--master", master_path, "--stamp-pages", "1", "--out-dir", root / "derived")
            checklist["files"] = [sources.read_json(master_path)]
            sources.write_json(checklist_path, checklist)
            status = cli("status", "--project", project, "--checklist", checklist_path, "--stage", "signing", code=1)
            self.assertEqual(status["state"], "工作稿")
            checklist["checks"] = [{"gate": gate, "stage": "signing", "result": "通过", "evidence": "Synthetic check only",
                                    "files_digest": status["files_digest"], "basis_digest": status["basis_digest"]}
                                   for gate in ("G1", "G2", "G3", "G4", "G5", "G6")]
            sources.write_json(checklist_path, checklist)
            ready = cli("status", "--project", project, "--checklist", checklist_path, "--stage", "signing")
            self.assertEqual(ready["state"], "待签章／待执行候选版")
            raw.write_text("合成补遗改变来源。", encoding="utf-8")
            stale = cli("status", "--project", project, "--checklist", checklist_path, "--stage", "signing", code=1)
            self.assertFalse(stale["all_checks_passed"])


if __name__ == "__main__":
    unittest.main()
