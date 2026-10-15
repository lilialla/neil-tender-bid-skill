#!/usr/bin/env python3
"""Small local command line for the private tender skill."""
import argparse
import json
from pathlib import Path
import sys

import sources


def output(value, path=None):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as file:
            file.write(text)
    else:
        print(text, end="")


def parser():
    root = argparse.ArgumentParser(description="采购来源、九列总账、限定章节与本地文件集；不执行外部发送")
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="读取本地来源，创建新的来源清单与空要求总账")
    init.add_argument("--project", type=Path, required=True)
    init.add_argument("--source", type=Path, action="append", required=True)
    check = sub.add_parser("check", help="核查G1/G2；全页标记不等于语义无遗漏")
    check.add_argument("--project", type=Path, required=True)
    check.add_argument("--full", action="store_true", help="包含源侧风险行提示")
    freeze = sub.add_parser("freeze", help="登记真实人工冻结；不可编造确认")
    freeze.add_argument("--project", type=Path, required=True)
    freeze.add_argument("--reviewer", required=True)
    freeze.add_argument("--decision-reference", required=True)
    freeze.add_argument("--expected-digest", required=True)
    replay = sub.add_parser("replay", help="比较保留的原始候选与复核总账")
    replay.add_argument("--candidate", type=Path, required=True)
    replay.add_argument("--reviewed", type=Path, required=True)
    packet = sub.add_parser("packet", help="只导出本章需要的完整约束与材料引用")
    packet.add_argument("--checklist", type=Path, required=True)
    packet.add_argument("--requirements", type=Path, required=True)
    packet.add_argument("--chapter", required=True)
    packet.add_argument("--out", type=Path, required=True)
    render = sub.add_parser("render", help="填写显式模板，未定值保持空占位与独立缺口")
    render.add_argument("--packet", type=Path, required=True)
    render.add_argument("--out", type=Path, required=True, help="新的结果JSON路径；正文在content字段")
    validate = sub.add_parser("chapters-check", help="核对映射、共用值与材料；返回问题，不代替语义审阅")
    validate.add_argument("--checklist", type=Path, required=True)
    validate.add_argument("--requirements", type=Path, required=True)
    validate.add_argument("--results", type=Path, required=True, help="以chapter ID为键的结果JSON")
    validate.add_argument("--chapter", action="append", help="只检查这些章节（可重复）；不代表全总账映射完整")
    impact = sub.add_parser("impact", help="只定位实际依赖变化的章节")
    for argument in ("before-checklist", "after-checklist", "before-requirements", "after-requirements"):
        impact.add_argument("--" + argument, type=Path, required=True)
    assemble = sub.add_parser("assemble", help="按明确页列表装配PDF，记录来源页到成稿页映射")
    assemble.add_argument("--parts", type=Path, required=True, help="path/sha256/pages数组JSON")
    assemble.add_argument("--out", type=Path, required=True, help="新的PDF路径")
    assemble.add_argument("--manifest", type=Path, required=True, help="新的装配记录JSON路径")
    derive = sub.add_parser("derive", help="从同一母稿派生待用印和常规部分")
    derive.add_argument("--master", type=Path, required=True, help="母稿装配记录JSON")
    derive.add_argument("--stamp-pages", required=True, help="从1起，用半角逗号分隔")
    derive.add_argument("--out-dir", type=Path, required=True)
    assess = sub.add_parser("status", help="区分检查、人工处理、签章与真实递交依据")
    assess.add_argument("--checklist", type=Path, required=True, help="同一章节清单的files/checks/execution部分")
    assess.add_argument("--project", type=Path, required=True, help="当前来源与要求总账所在目录")
    assess.add_argument("--stage", choices=["draft", "signing", "submission", "submitted"], required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            inventory = sources.initialize(args.project, args.source)
            output({"project": str(args.project.resolve()), "sources": len(inventory["sources"]),
                    "status": "工作版，尚未逐范围阅读或人工冻结"})
        elif args.command == "check":
            report = sources.check_project(args.project)
            if not args.full:
                report["risk_hint_count"] = len(report.pop("risk_hints"))
            output(report)
            return 0 if report["can_freeze"] else 1
        elif args.command == "freeze":
            folder = sources.freeze(args.project, args.reviewer, args.decision_reference, args.expected_digest)
            output({"snapshot": str(folder), "status": "已登记人工确认，不证明材料或签章递交完成"})
        elif args.command == "replay":
            output(sources.replay(sources.read_requirements(args.candidate), sources.read_requirements(args.reviewed)))
        elif args.command in {"assemble", "derive", "status"}:
            import assembly
            if args.command == "assemble":
                if args.manifest.exists() or args.manifest.resolve() == args.out.resolve():
                    raise FileExistsError("装配记录输出已存在或与PDF路径相同")
                value = assembly.assemble_pdf(sources.read_json(args.parts), args.out)
                output(value, args.manifest)
            elif args.command == "derive":
                value = assembly.derive_stamp_parts(sources.read_json(args.master),
                    [int(number.strip()) for number in args.stamp_pages.split(",")], args.out_dir)
                output(value, args.out_dir / "page_map.json")
            else:
                value = sources.read_json(args.checklist)
                result = assembly.assess_files(value.get("files", []), value.get("checks", []),
                    value.get("execution", {}), args.stage, source_project=args.project,
                    context={key: value.get(key) for key in ("shared", "materials", "chapters", "global_constraints", "requirement_dispositions",
                                                           "as_of", "rules_version") if key in value})
                output(result)
                return 0 if result["all_checks_passed"] else 1
        else:
            import chapters
            if args.command == "packet":
                value = chapters.prepare_packet(sources.read_json(args.checklist),
                    chapters.read_requirements(args.requirements), args.chapter)
                output(value, args.out)
            elif args.command == "render":
                output(chapters.render_chapter(sources.read_json(args.packet)), args.out)
            elif args.command == "chapters-check":
                value = chapters.validate_chapters(sources.read_json(args.checklist),
                    chapters.read_requirements(args.requirements), sources.read_json(args.results), chapter_ids=args.chapter)
                output(value)
                return 1 if value else 0
            elif args.command == "impact":
                output(chapters.impact(sources.read_json(args.before_checklist), sources.read_json(args.after_checklist),
                    chapters.read_requirements(args.before_requirements), chapters.read_requirements(args.after_requirements)))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError) as error:
        print(json.dumps({"error": str(error), "status": "未完成；读取实际错误后修正，勿据此登记通过"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
