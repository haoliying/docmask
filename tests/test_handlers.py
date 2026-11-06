from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
import zipfile

from docmask.handlers.csv_handler import CsvHandler
from docmask.handlers.docx_handler import DocxHandler
from docmask.handlers.json_handler import JsonHandler
from docmask.handlers.pdf_handler import PdfHandler
from docmask.handlers.pptx_handler import PptxHandler
from docmask.handlers.text_handler import TextHandler
from docmask.handlers.textio import read_text_with_encoding
from docmask.handlers.xls_handler import XlsHandler
from docmask.handlers.xlsx_handler import XlsxHandler
from docmask.masking import Redactor, Restorer, load_mapping
from tests.helpers import make_policy

try:
    import pymupdf
except Exception:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except Exception:
        pymupdf = None  # type: ignore

try:
    from docx import Document
except Exception:  # pragma: no cover
    Document = None  # type: ignore

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.comments import Comment
except Exception:  # pragma: no cover
    Workbook = None  # type: ignore
    load_workbook = None  # type: ignore
    Comment = None  # type: ignore

try:
    import xlrd
    import xlwt
except Exception:  # pragma: no cover
    xlrd = None  # type: ignore
    xlwt = None  # type: ignore

try:
    from pptx import Presentation
    from pptx.util import Inches
except Exception:  # pragma: no cover
    Presentation = None  # type: ignore
    Inches = None  # type: ignore


class TextHandlerTests(unittest.TestCase):
    def test_utf8_and_gb18030_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sample.txt")
            dst = os.path.join(tmp, "out.txt")
            with open(src, "wb") as fh:
                fh.write("手机 13800138000\n邮箱 alice@example.com\n".encode("gb18030"))
            policy = make_policy(strategy="replace")
            warnings = TextHandler().process(src, dst, Redactor(policy).transform, policy)
            self.assertEqual(warnings, [])
            text, encoding = read_text_with_encoding(dst)
            self.assertEqual(encoding, "gb18030")
            self.assertIn("[MOBILE_001]", text)
            self.assertIn("[EMAIL_001]", text)
            self.assertNotIn("13800138000", text)

    def test_utf8_bom_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "bom.txt")
            dst = os.path.join(tmp, "bom_out.txt")
            with open(src, "wb") as fh:
                fh.write("\ufeff手机 13800138000\n".encode("utf-8-sig"))
            policy = make_policy(strategy="replace")
            TextHandler().process(src, dst, Redactor(policy).transform, policy)
            with open(dst, "rb") as fh:
                self.assertTrue(fh.read(3) == b"\xef\xbb\xbf")


class CsvHandlerTests(unittest.TestCase):
    def test_comma_with_quoted_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.csv")
            dst = os.path.join(tmp, "a_out.csv")
            with open(src, "w", encoding="utf-8", newline="") as fh:
                fh.write('姓名,联系方式,备注\n张三,13800138000,"备注,含逗号"\n')
            policy = make_policy(strategy="replace", custom_words={"PERSON": ["张三"]})
            warnings = CsvHandler().process(src, dst, Redactor(policy).transform, policy)
            self.assertEqual(warnings, [])
            with open(dst, "r", encoding="utf-8", newline="") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[1][0], "[NAME_001]")
            self.assertEqual(rows[1][1], "[MOBILE_001]")
            self.assertEqual(rows[1][2], "备注,含逗号")

    def test_semicolon_and_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = make_policy(strategy="replace")
            handler = CsvHandler()
            src = os.path.join(tmp, "b.csv")
            dst = os.path.join(tmp, "b_out.csv")
            with open(src, "w", encoding="utf-8", newline="") as fh:
                fh.write("姓名;手机\n张三;13800138000\n")
            handler.process(src, dst, Redactor(policy).transform, policy)
            text, _ = read_text_with_encoding(dst)
            self.assertIn("[MOBILE_001]", text)
            self.assertIn(";", text)

            tsv_src = os.path.join(tmp, "c.tsv")
            tsv_dst = os.path.join(tmp, "c_out.tsv")
            with open(tsv_src, "w", encoding="utf-8", newline="") as fh:
                fh.write("姓名\t手机\n张三\t13800138000\n")
            handler.process(tsv_src, tsv_dst, Redactor(policy).transform, policy)
            text, _ = read_text_with_encoding(tsv_dst)
            self.assertIn("[MOBILE_001]", text)
            self.assertIn("\t", text)

    def test_single_column_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "d.csv")
            dst = os.path.join(tmp, "d_out.csv")
            with open(src, "w", encoding="utf-8", newline="") as fh:
                fh.write("13800138000\nalice@example.com\n")
            policy = make_policy(strategy="replace")
            CsvHandler().process(src, dst, Redactor(policy).transform, policy)
            text, _ = read_text_with_encoding(dst)
            self.assertIn("[MOBILE_001]", text)
            self.assertIn("[EMAIL_001]", text)


class JsonHandlerTests(unittest.TestCase):
    def test_nested_json_and_keys_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "data.json")
            dst = os.path.join(tmp, "data_out.json")
            payload = {
                "user": {
                    "name": "张三",
                    "phone": "13800138000",
                    "emails": ["alice@example.com"],
                },
                "count": 3,
                "13800138000": "作为键的号码应保留",
            }
            with open(src, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            policy = make_policy(strategy="replace", custom_words={"PERSON": ["张三"]})
            JsonHandler().process(src, dst, Redactor(policy).transform, policy)
            with open(dst, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["user"]["name"], "[NAME_001]")
            self.assertEqual(data["user"]["phone"], "[MOBILE_001]")
            self.assertEqual(data["user"]["emails"][0], "[EMAIL_001]")
            self.assertEqual(data["count"], 3)
            self.assertIn("13800138000", data)

    def test_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "data.jsonl")
            dst = os.path.join(tmp, "data_out.jsonl")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write('{"phone": "13800138000"}\n{"phone": "13900139000"}\n')
            policy = make_policy(strategy="replace")
            JsonHandler().process(src, dst, Redactor(policy).transform, policy)
            with open(dst, "r", encoding="utf-8") as fh:
                lines = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(lines[0]["phone"], "[MOBILE_001]")
            self.assertEqual(lines[1]["phone"], "[MOBILE_002]")

    def test_invalid_json_falls_back_to_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "broken.json")
            dst = os.path.join(tmp, "broken_out.json")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("{ broken 13800138000")
            policy = make_policy(strategy="replace")
            warnings = JsonHandler().process(
                src, dst, Redactor(policy).transform, policy
            )
            text, _ = read_text_with_encoding(dst)
            self.assertTrue(warnings)
            self.assertIn("[MOBILE_001]", text)
            self.assertNotIn("13800138000", text)


@unittest.skipUnless(Document is not None, "需要 python-docx")
class DocxHandlerTests(unittest.TestCase):
    def _create(self, path: str) -> None:
        doc = Document()
        paragraph = doc.add_paragraph()
        for chunk in ("联系人：", "张", "三", "，手机 ", "13800138000"):
            paragraph.add_run(chunk)
        doc.add_paragraph("邮箱：alice@example.com")
        doc.core_properties.author = "张三"
        doc.core_properties.comments = "内部资料"
        doc.save(path)

    def test_cross_run_redaction_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.docx")
            dst = os.path.join(tmp, "a_out.docx")
            self._create(src)
            policy = make_policy(strategy="replace")
            redactor = Redactor(policy)
            warnings = DocxHandler().process(src, dst, redactor.transform, policy)
            self.assertEqual(warnings, [])
            result = Document(dst)
            text = "\n".join(p.text for p in result.paragraphs)
            self.assertIn("[NAME_001]", text)
            self.assertIn("[MOBILE_001]", text)
            self.assertIn("[EMAIL_001]", text)
            self.assertNotIn("张三", text)
            self.assertNotIn("13800138000", text)
            self.assertEqual(result.core_properties.author, "")
            self.assertEqual(result.core_properties.comments, "")
            with zipfile.ZipFile(dst) as zf:
                xml = zf.read("word/document.xml").decode("utf-8")
            self.assertNotIn("13800138000", xml)
            self.assertNotIn("张三", xml)

            with tempfile.TemporaryDirectory() as mtmp:
                mapping_path = os.path.join(mtmp, "mapping.csv")
                redactor.masker.write_mapping(mapping_path)
                restored_dir = os.path.join(mtmp, "restored")
                os.makedirs(restored_dir)
                restored_path = os.path.join(restored_dir, "a.docx")
                restorer = Restorer(load_mapping(mapping_path))
                DocxHandler().process(dst, restored_path, restorer.transform, policy)
                restored = Document(restored_path)
                restored_text = "\n".join(p.text for p in restored.paragraphs)
                self.assertIn("张三", restored_text)
                self.assertIn("13800138000", restored_text)


@unittest.skipUnless(Workbook is not None, "需要 openpyxl")
class XlsxHandlerTests(unittest.TestCase):
    def test_cells_comment_formula_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.xlsx")
            dst = os.path.join(tmp, "a_out.xlsx")
            wb = Workbook()
            ws = wb.active
            ws["A1"] = "姓名"
            ws["B1"] = "张三"
            ws["A2"] = "手机号"
            ws["B2"] = "13800138000"
            ws["C2"] = "alice@example.com"
            ws["D2"] = "=B2"
            ws["B2"].comment = Comment("备用：13900139000", "李四")
            ws.oddHeader.center.text = "联系人：王五"
            wb.properties.creator = "王五"
            wb.save(src)

            policy = make_policy(strategy="replace", custom_words={"PERSON": ["张三"]})
            warnings = XlsxHandler().process(src, dst, Redactor(policy).transform, policy)
            self.assertTrue(any("公式" in item for item in warnings))

            result = load_workbook(dst)
            sheet = result.active
            self.assertEqual(sheet["B1"].value, "[NAME_001]")
            self.assertEqual(sheet["B2"].value, "[MOBILE_001]")
            self.assertEqual(sheet["C2"].value, "[EMAIL_001]")
            self.assertEqual(sheet["D2"].value, "=B2")
            self.assertIn("[MOBILE_002]", sheet["B2"].comment.text)
            self.assertIn("[NAME_002]", sheet.oddHeader.center.text)
            self.assertNotIn("李四", sheet["B2"].comment.text)
            self.assertEqual(sheet["B2"].comment.author, "匿名")
            self.assertFalse(result.properties.creator)
            self.assertIn("[MOBILE_001]", XlsxHandler().extract_text(dst))
            result.close()


    def test_person_column_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "people.xlsx")
            dst = os.path.join(tmp, "people_out.xlsx")
            wb = Workbook()
            ws = wb.active
            ws["A1"] = "姓名"
            ws["B1"] = "手机号"
            ws["A2"] = "张三"
            ws["B2"] = "13800138000"
            ws["A3"] = "李四"
            ws["B3"] = "13900139000"
            wb.save(src)

            policy = make_policy(strategy="replace")
            XlsxHandler().process(src, dst, Redactor(policy).transform, policy)
            result = load_workbook(dst)
            sheet = result.active
            self.assertEqual(sheet["A2"].value, "[NAME_001]")
            self.assertEqual(sheet["A3"].value, "[NAME_002]")
            self.assertEqual(sheet["B2"].value, "[MOBILE_001]")
            self.assertEqual(sheet["B3"].value, "[MOBILE_002]")
            result.close()


@unittest.skipUnless(xlrd is not None and xlwt is not None, "需要 xlrd/xlwt")
class XlsHandlerTests(unittest.TestCase):
    def test_cells_merge_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.xls")
            dst = os.path.join(tmp, "a_out.xls")
            wb = xlwt.Workbook()
            ws = wb.add_sheet("客户")
            ws.write(0, 0, "联系人：张三")
            ws.write(1, 0, "手机号")
            ws.write(1, 1, "13800138000")
            ws.write(2, 0, "邮箱")
            ws.write(2, 1, "alice@example.com")
            ws.write_merge(3, 3, 0, 1, "地址：北京市朝阳区")
            wb.save(src)

            policy = make_policy(
                strategy="replace",
                custom_words={"PERSON": ["张三"], "ADDRESS": ["北京市朝阳区"]},
            )
            warnings = XlsHandler().process(
                src, dst, Redactor(policy).transform, policy
            )
            self.assertTrue(any(".xls" in item for item in warnings))

            result = xlrd.open_workbook(dst)
            sheet = result.sheet_by_index(0)
            self.assertEqual(sheet.name, "客户")
            self.assertEqual(sheet.cell_value(0, 0), "联系人：[NAME_001]")
            self.assertEqual(sheet.cell_value(1, 1), "[MOBILE_001]")
            self.assertEqual(sheet.cell_value(2, 1), "[EMAIL_001]")
            self.assertEqual(sheet.cell_value(3, 0), "地址：[ADDR_001]")
            self.assertIn("[MOBILE_001]", XlsHandler().extract_text(dst))

    def test_person_column_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "people.xls")
            dst = os.path.join(tmp, "people_out.xls")
            wb = xlwt.Workbook()
            ws = wb.add_sheet("名单")
            ws.write(0, 0, "姓名")
            ws.write(0, 1, "手机号")
            ws.write(1, 0, "张三")
            ws.write(1, 1, "13800138000")
            ws.write(2, 0, "李四")
            ws.write(2, 1, "13900139000")
            wb.save(src)

            policy = make_policy(strategy="replace")
            XlsHandler().process(src, dst, Redactor(policy).transform, policy)
            result = xlrd.open_workbook(dst)
            sheet = result.sheet_by_index(0)
            self.assertEqual(sheet.cell_value(1, 0), "[NAME_001]")
            self.assertEqual(sheet.cell_value(2, 0), "[NAME_002]")
            self.assertEqual(sheet.cell_value(1, 1), "[MOBILE_001]")


@unittest.skipUnless(Workbook is not None, "需要 openpyxl")
class FakeXlsHandlerTests(unittest.TestCase):
    def test_xlsx_content_with_xls_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "fake.xls")
            dst = os.path.join(tmp, "fake_out.xlsx")
            wb = Workbook()
            ws = wb.active
            ws["A1"] = "手机号"
            ws["B1"] = "13800138000"
            wb.save(src)

            handler = XlsHandler()
            adjusted = handler.adjust_destination(src, os.path.join(tmp, "fake_out.xls"))
            self.assertEqual(os.path.basename(adjusted), "fake_out.xlsx")

            policy = make_policy(strategy="replace")
            warnings = handler.process(src, dst, Redactor(policy).transform, policy)
            self.assertTrue(any(".xlsx" in item for item in warnings))
            result = load_workbook(dst)
            self.assertEqual(result.active["B1"].value, "[MOBILE_001]")
            result.close()
            self.assertIn("[MOBILE_001]", handler.extract_text(dst))


@unittest.skipUnless(Presentation is not None, "需要 python-pptx")
class PptxHandlerTests(unittest.TestCase):
    def test_text_table_notes_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.pptx")
            dst = os.path.join(tmp, "a_out.pptx")
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
            paragraph = box.text_frame.paragraphs[0]
            paragraph.text = "联系人："
            paragraph.add_run().text = "李"
            paragraph.add_run().text = "四"
            table = slide.shapes.add_table(
                2, 2, Inches(1), Inches(2), Inches(5), Inches(1)
            ).table
            table.cell(0, 0).text = "手机"
            table.cell(0, 1).text = "13800138000"
            slide.notes_slide.notes_text_frame.text = "邮箱 alice@example.com"
            prs.core_properties.author = "王五"
            prs.save(src)

            policy = make_policy(strategy="replace")
            warnings = PptxHandler().process(src, dst, Redactor(policy).transform, policy)
            self.assertEqual(warnings, [])
            text = PptxHandler().extract_text(dst)
            self.assertIn("[NAME_001]", text)
            self.assertIn("[MOBILE_001]", text)
            self.assertIn("[EMAIL_001]", text)
            self.assertNotIn("李四", text)
            self.assertNotIn("13800138000", text)
            result = Presentation(dst)
            self.assertEqual(result.core_properties.author, "")


@unittest.skipUnless(pymupdf is not None, "需要 PyMuPDF")
class PdfHandlerTests(unittest.TestCase):
    def test_text_redaction_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.pdf")
            dst = os.path.join(tmp, "a_out.pdf")
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Phone: 13800138000", fontsize=12)
            page.insert_text((72, 100), "Email: alice@example.com", fontsize=12)
            doc.set_metadata({"title": "Secret", "author": "张三"})
            doc.save(src)
            doc.close()

            policy = make_policy(strategy="replace")
            warnings = PdfHandler().process(src, dst, Redactor(policy).transform, policy)
            self.assertFalse([w for w in warnings if "无法" in w])
            result = pymupdf.open(dst)
            try:
                text = "\n".join(page.get_text("text") for page in result)
                self.assertIn("[MOBILE_001]", text)
                self.assertIn("[EMAIL_001]", text)
                self.assertNotIn("13800138000", text)
                self.assertNotIn("alice@example.com", text)
                self.assertNotEqual(result.metadata.get("title"), "Secret")
            finally:
                result.close()
            self.assertFalse(PdfHandler().can_restore())


if __name__ == "__main__":
    unittest.main()
