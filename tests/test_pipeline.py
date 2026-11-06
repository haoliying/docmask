from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest

from docmask.masking import load_mapping
from docmask.pipeline import (
    RedactionJob,
    RestoreJob,
    collect_inputs,
    preview_file,
    write_report,
)
from docmask.models import JobSummary
from tests.helpers import make_policy

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover
    Workbook = None  # type: ignore


def _write(path: str, content: str, encoding: str = "utf-8") -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(content)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class CollectInputsTests(unittest.TestCase):
    def test_recursive_skip_and_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in")
            _write(os.path.join(src, "a.txt"), "phone 13800138000")
            _write(os.path.join(src, "sub", "b.md"), "phone 13800138000")
            _write(os.path.join(src, "c.csv"), "phone\n13800138000\n")
            _write(os.path.join(src, "blob.bin"), "unsupported")
            _write(os.path.join(src, "sub", "ignore.txt"), "ignore")
            files, skipped = collect_inputs(
                [src], recursive=True, exclude_dirs=[os.path.join(src, "sub")]
            )
            self.assertEqual({item.relative for item in files}, {"a.txt", "c.csv"})
            self.assertEqual(skipped, 1)

    def test_non_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "a.txt"), "x")
            _write(os.path.join(tmp, "sub", "b.md"), "x")
            files, _ = collect_inputs([tmp], recursive=False)
            self.assertEqual([item.relative for item in files], ["a.txt"])

    def test_missing_path(self) -> None:
        with self.assertRaises(FileNotFoundError):
            collect_inputs(["/does/not/exist"])


class RedactionJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.src = os.path.join(self.root, "in")
        _write(
            os.path.join(self.src, "a.txt"),
            "手机 13800138000\n联系人：张三\n",
        )
        _write(os.path.join(self.src, "sub", "b.md"), "再次出现 13800138000\n")
        _write(os.path.join(self.src, "c.csv"), "手机\n13800138000\n")
        self.policy = make_policy(
            strategy="replace", custom_words={"PERSON": ["张三"]}
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_batch_mapping_report_and_preview(self) -> None:
        out = os.path.join(self.root, "out")
        report = os.path.join(self.root, "report.json")
        files, skipped = collect_inputs([self.src], recursive=True)
        self.assertEqual(len(files), 3)
        self.assertEqual(skipped, 0)

        job = RedactionJob(self.policy, out, report_path=report)
        summary = job.run(files)
        self.assertEqual(summary.ok_files, 3)
        self.assertEqual(summary.failed_files, 0)
        self.assertEqual(summary.counts.get("CN_MOBILE"), 3)
        self.assertEqual(summary.counts.get("PERSON"), 1)
        self.assertEqual(summary.total_entities, 4)

        a_text = _read(os.path.join(out, "a.txt"))
        b_text = _read(os.path.join(out, "sub", "b.md"))
        c_text = _read(os.path.join(out, "c.csv"))
        self.assertIn("[MOBILE_001]", a_text)
        self.assertIn("[NAME_001]", a_text)
        self.assertIn("[MOBILE_001]", b_text)
        self.assertIn("[MOBILE_001]", c_text)
        self.assertNotIn("13800138000", a_text + b_text + c_text)

        mapping = load_mapping(os.path.join(out, "mapping.csv"))
        self.assertEqual(mapping["[MOBILE_001]"], "13800138000")
        self.assertEqual(mapping["[NAME_001]"], "张三")

        report_text = _read(report)
        self.assertNotIn("13800138000", report_text)
        self.assertNotIn("张三", report_text)
        payload = json.loads(report_text)
        self.assertEqual(payload["summary"]["total_entities"], 4)
        self.assertTrue(payload["mapping_written"])

        preview = preview_file(os.path.join(self.src, "a.txt"), self.policy)
        self.assertEqual(preview.counts.get("CN_MOBILE"), 1)
        self.assertTrue(preview.items)
        for item in preview.items:
            self.assertNotIn("13800138000", item.preview)

    def test_dry_run_writes_nothing(self) -> None:
        out = os.path.join(self.root, "dry")
        report = os.path.join(self.root, "dry_report.json")
        files, _ = collect_inputs([self.src], recursive=True)
        job = RedactionJob(self.policy, out, report_path=report, dry_run=True)
        summary = job.run(files)
        self.assertEqual(summary.total_entities, 4)
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(report))

    def test_same_directory_does_not_overwrite_source(self) -> None:
        files, _ = collect_inputs([self.src], recursive=True)
        job = RedactionJob(self.policy, self.src)
        summary = job.run(files)
        self.assertEqual(summary.ok_files, 3)
        original = _read(os.path.join(self.src, "a.txt"))
        self.assertIn("13800138000", original)
        redacted_path = os.path.join(self.src, "a_redacted.txt")
        self.assertTrue(os.path.exists(redacted_path))
        self.assertIn("[MOBILE_001]", _read(redacted_path))

    def test_restore_roundtrip(self) -> None:
        out = os.path.join(self.root, "out")
        report = os.path.join(self.root, "report.json")
        files, _ = collect_inputs([self.src], recursive=True)
        job = RedactionJob(self.policy, out, report_path=report)
        job.run(files)

        restored = os.path.join(self.root, "restored")
        restore_files, _ = collect_inputs([out], recursive=True)
        restore_job = RestoreJob(
            os.path.join(out, "mapping.csv"),
            restored,
            report_path=os.path.join(self.root, "restore_report.json"),
        )
        restore_summary = restore_job.run(restore_files)
        self.assertEqual(restore_summary.ok_files, 3)
        self.assertEqual(restore_summary.total_entities, 4)
        self.assertEqual(
            _read(os.path.join(restored, "a.txt")),
            _read(os.path.join(self.src, "a.txt")),
        )
        self.assertEqual(
            _read(os.path.join(restored, "sub", "b.md")),
            _read(os.path.join(self.src, "sub", "b.md")),
        )


@unittest.skipUnless(Workbook is not None, "需要 openpyxl")
class FakeXlsPipelineTests(unittest.TestCase):
    def test_output_extension_follows_real_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in")
            os.makedirs(src, exist_ok=True)
            path = os.path.join(src, "fake.xls")
            wb = Workbook()
            wb.active["A1"] = "13800138000"
            wb.save(path)

            files, _ = collect_inputs([src])
            out = os.path.join(tmp, "out")
            summary = RedactionJob(make_policy(strategy="replace"), out).run(files)
            self.assertEqual(summary.ok_files, 1)
            self.assertEqual(summary.files[0].output, "fake.xlsx")
            self.assertTrue(os.path.exists(os.path.join(out, "fake.xlsx")))


class ReportTests(unittest.TestCase):
    def test_csv_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = JobSummary()
            from docmask.models import FileOutcome

            summary.files.append(
                FileOutcome(
                    source="a.txt",
                    output="a_out.txt",
                    status="ok",
                    counts={"CN_MOBILE": 2},
                )
            )
            path = os.path.join(tmp, "report.csv")
            write_report(path, summary, make_policy(), None)
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0][0], "source")
            self.assertEqual(rows[1][0], "a.txt")
            self.assertIn("CN_MOBILE=2", rows[1][3])


if __name__ == "__main__":
    unittest.main()
