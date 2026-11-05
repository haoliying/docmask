"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

from . import __version__
from .config import (
    build_policy,
    load_rules_file,
    load_words_file,
    sample_rules,
)
from .entities import ENTITY_DEFS, label_of
from .pipeline import (
    RedactionJob,
    RestoreJob,
    collect_inputs,
    preview_file,
    supported_formats_text,
)
from .handlers import load_builtin_handlers


def _supports_color() -> bool:
    stream = sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")


_COLOR = _supports_color()


def _paint(text: str, code: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _ok(text: str) -> str:
    return _paint(text, "32")


def _warn(text: str) -> str:
    return _paint(text, "33")


def _error(text: str) -> str:
    return _paint(text, "31")


def _dim(text: str) -> str:
    return _paint(text, "2")


def _policy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy",
        choices=["mask", "partial", "replace", "hash"],
        help="脱敏策略：mask 全掩码 / partial 部分保留 / replace 占位符 / hash 哈希",
    )
    parser.add_argument("--enable", nargs="+", metavar="TYPE", help="仅启用这些实体类型")
    parser.add_argument("--disable", nargs="+", metavar="TYPE", help="禁用这些实体类型")
    parser.add_argument("--rules", metavar="FILE", help="自定义规则 JSON 文件")
    parser.add_argument("--custom-words", metavar="FILE", help="自定义词表文件")
    parser.add_argument("--mask-char", help="掩码字符，默认 *")
    parser.add_argument(
        "--keep-length", action="store_true", default=None, help="全掩码时保留原文字符数"
    )
    parser.add_argument(
        "--keep-metadata",
        action="store_true",
        default=None,
        help="保留文档作者等元数据（默认清理）",
    )
    parser.add_argument(
        "--pdf-mode",
        choices=["text", "box"],
        help="PDF 输出：text 写入掩码文本 / box 仅覆盖色块",
    )
    parser.add_argument("--salt", help="hash 策略使用的盐（也可用环境变量 DOCMASK_SALT）")


def _build_policy_from_args(args):
    rules = load_rules_file(args.rules) if getattr(args, "rules", None) else {}
    words = (
        load_words_file(args.custom_words)
        if getattr(args, "custom_words", None)
        else None
    )
    strip_metadata = False if getattr(args, "keep_metadata", None) else None
    return build_policy(
        rules=rules,
        enabled=args.enable,
        disabled=args.disable,
        strategy=args.strategy,
        mask_char=args.mask_char,
        keep_length=args.keep_length,
        strip_metadata=strip_metadata,
        pdf_mode=args.pdf_mode,
        salt=args.salt or os.environ.get("DOCMASK_SALT"),
        custom_words=words,
    )


def _print_summary(summary, out_dir: Optional[str], report: Optional[str], mapping: Optional[str], dry_run: bool) -> None:
    print()
    print(
        f"{_ok('完成')}  文件 {len(summary.files)} 个 · 成功 {summary.ok_files} · "
        f"失败 {summary.failed_files} · 命中 {summary.total_entities} 处"
    )
    if summary.counts:
        for etype, count in summary.counts.items():
            print(f"  {label_of(etype):<12} {count:>6}")
    if dry_run:
        print(_warn("演练模式：未写入任何文件"))
    elif out_dir:
        print(f"输出目录  {out_dir}")
    if mapping and not dry_run:
        print(f"映射文件  {mapping}  {_warn('（含敏感原文，请妥善保管）')}")
    if report and not dry_run:
        print(f"审计报告  {report}")


def _print_file_line(item) -> None:
    if item.status == "error":
        print(f"  {_error('失败')}  {item.source}  {item.error}")
    elif item.status == "skipped":
        print(f"  {_warn('跳过')}  {item.source}  {item.error}")
    else:
        print(
            f"  {_ok('OK')}    {item.source}  "
            f"{item.total} 处  {_dim(str(item.elapsed_ms) + 'ms')}"
        )
    for warning in item.warnings:
        print(f"        {_warn('!')} {warning}")


def cmd_run(args: argparse.Namespace) -> int:
    policy = _build_policy_from_args(args)
    out_dir = os.path.abspath(os.path.expanduser(args.output))
    exclude = [out_dir]
    files, skipped = collect_inputs(args.inputs, not args.non_recursive, exclude)
    if not files:
        print(_error("没有找到可处理的文件。支持格式: " + supported_formats_text()))
        return 2
    report_path = args.report
    if not report_path and not args.dry_run:
        report_path = os.path.join(out_dir, "redaction_report.json")
    job = RedactionJob(
        policy,
        out_dir,
        mapping_path=args.mapping,
        report_path=report_path,
        dry_run=args.dry_run,
    )
    if not args.quiet:
        print(
            f"docmask {__version__}  ·  策略 {policy.strategy}  ·  "
            f"{len(files)} 个文件"
            + (f"  ·  跳过 {skipped} 个不支持的文件" if skipped else "")
        )
    summary = job.run(files)
    if not args.quiet:
        for item in summary.files:
            _print_file_line(item)
    mapping_path = job.mapping_path
    if args.json:
        payload = {
            "version": __version__,
            "strategy": policy.strategy,
            "dry_run": args.dry_run,
            "summary": {
                "files": len(summary.files),
                "ok": summary.ok_files,
                "failed": summary.failed_files,
                "counts": summary.counts,
                "total": summary.total_entities,
            },
            "output": None if args.dry_run else out_dir,
            "report": None if args.dry_run else report_path,
            "mapping": None if args.dry_run else mapping_path,
            "files": [
                {
                    "source": item.source,
                    "status": item.status,
                    "counts": item.counts,
                    "warnings": item.warnings,
                    "error": item.error,
                }
                for item in summary.files
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_summary(
            summary,
            out_dir,
            report_path,
            mapping_path,
            args.dry_run,
        )
    return 2 if summary.failed_files else 0


def cmd_preview(args: argparse.Namespace) -> int:
    policy = _build_policy_from_args(args)
    files, _ = collect_inputs(args.inputs, not args.non_recursive, [])
    if not files:
        print(_error("没有找到可处理的文件。支持格式: " + supported_formats_text()))
        return 2
    payload = []
    for item in files:
        preview = preview_file(item.source, policy, max_items=args.limit)
        payload.append(
            {
                "source": item.relative,
                "total": preview.total,
                "counts": preview.counts,
                "items": [
                    {
                        "type": entry.type,
                        "label": entry.label,
                        "preview": entry.preview,
                        "confidence": entry.confidence,
                    }
                    for entry in preview.items
                ],
                "error": preview.error,
            }
        )
        if not args.json:
            print()
            print(f"{_paint(item.relative, '1')}  {preview.total} 处")
            if preview.error:
                print(f"  {_error('错误')}  {preview.error}")
                continue
            if not preview.counts:
                print("  未发现敏感信息")
            for etype, count in sorted(preview.counts.items(), key=lambda kv: -kv[1]):
                print(f"  {label_of(etype):<12} {count:>5}")
            for entry in preview.items:
                print(f"  - {entry.label}: {entry.preview}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    out_dir = os.path.abspath(os.path.expanduser(args.output))
    files, skipped = collect_inputs(args.inputs, not args.non_recursive, [out_dir])
    if not files:
        print(_error("没有找到可处理的文件"))
        return 2
    job = RestoreJob(args.mapping, out_dir, report_path=args.report)
    summary = job.run(files)
    for item in summary.files:
        _print_file_line(item)
    print()
    print(
        f"{_ok('完成')}  文件 {len(summary.files)} 个 · 成功 {summary.ok_files} · "
        f"失败 {summary.failed_files} · 还原 {summary.total_entities} 处"
        + (f" · 跳过 {skipped} 个不支持的文件" if skipped else "")
    )
    print(f"输出目录  {out_dir}")
    if args.report:
        print(f"审计报告  {args.report}")
    return 2 if summary.failed_files else 0


def cmd_entities(args: argparse.Namespace) -> int:
    print(f"{'类型':<22}{'名称':<14}{'默认':<6}说明")
    print("-" * 90)
    for key, item in ENTITY_DEFS.items():
        print(
            f"{key:<22}{str(item['label']):<14}"
            f"{('是' if item['default'] else '否'):<6}{item['description']}"
        )
    return 0


def cmd_rules_init(args: argparse.Namespace) -> int:
    target = os.path.abspath(os.path.expanduser(args.output))
    if os.path.exists(target) and not args.force:
        print(_error(f"文件已存在: {target}（使用 --force 覆盖）"))
        return 2
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(sample_rules(), fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"已生成示例规则文件: {target}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .web.server import serve

    try:
        serve(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docmask",
        description="离线文档脱敏工具：在本地批量识别并遮盖敏感信息。",
    )
    parser.add_argument("--version", action="version", version=f"docmask {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="批量脱敏文件或目录")
    run.add_argument("inputs", nargs="+", help="文件或目录")
    run.add_argument("-o", "--output", default="./redacted_output", help="输出目录")
    run.add_argument("--mapping", help="映射文件输出路径（replace 策略默认写入输出目录）")
    run.add_argument("--report", help="审计报告路径（.json 或 .csv）")
    run.add_argument("--dry-run", action="store_true", help="只分析，不写入文件")
    run.add_argument("--non-recursive", action="store_true", help="不递归子目录")
    run.add_argument("--quiet", action="store_true", help="只输出最终汇总")
    run.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    _policy_args(run)
    run.set_defaults(func=cmd_run)

    preview = sub.add_parser("preview", help="预览识别结果（不写入文件）")
    preview.add_argument("inputs", nargs="+", help="文件或目录")
    preview.add_argument("--limit", type=int, default=8, help="每个文件展示的样例数")
    preview.add_argument("--non-recursive", action="store_true", help="不递归子目录")
    preview.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    _policy_args(preview)
    preview.set_defaults(func=cmd_preview)

    restore = sub.add_parser("restore", help="根据映射文件还原占位符")
    restore.add_argument("inputs", nargs="+", help="文件或目录")
    restore.add_argument("-o", "--output", default="./restored_output", help="输出目录")
    restore.add_argument("--mapping", required=True, help="脱敏时生成的 mapping.csv")
    restore.add_argument("--report", help="还原报告路径")
    restore.add_argument("--non-recursive", action="store_true", help="不递归子目录")
    restore.set_defaults(func=cmd_restore)

    entities = sub.add_parser("entities", help="查看支持的实体类型")
    entities.set_defaults(func=cmd_entities)

    rules = sub.add_parser("rules", help="规则文件工具")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_init = rules_sub.add_parser("init", help="生成示例规则文件")
    rules_init.add_argument("-o", "--output", default="./docmask_rules.json")
    rules_init.add_argument("--force", action="store_true", help="覆盖已有文件")
    rules_init.set_defaults(func=cmd_rules_init)

    ui = sub.add_parser("ui", help="启动本地 Web 界面")
    ui.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    ui.add_argument("--port", type=int, default=8765, help="监听端口")
    ui.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ui.set_defaults(func=cmd_ui)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    load_builtin_handlers()
    if argv is None:
        argv = sys.argv[1:]
    # 双击 Windows 单文件 EXE 时没有参数，直接打开本地 Web 界面；
    # 命令行用法保持不变。
    if not argv and getattr(sys, "frozen", False):
        argv = ["ui"]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(_error(f"错误: {exc}"))
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
