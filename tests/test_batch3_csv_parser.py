from pathlib import Path
import tempfile
import unittest

from short_video_foundation.qianchuan_script_acquisition.csv_parser import (
    FIELD_DELIMITER,
    RpaCsvError,
    parse_diagnosis_csv,
)


FIXTURES = Path(__file__).parent / "fixtures"


class Batch3CsvParserTests(unittest.TestCase):
    def test_unit_separator_csv_preserves_script_text(self):
        rows = parse_diagnosis_csv(FIXTURES / "qianchuan-script-diagnosis-v1.csv")
        script = next(row for row in rows if row.record_type == "script_analysis")
        self.assertEqual(script.script_info["text"], "原始参考脚本")
        self.assertEqual(script.material_id, "m1")
        self.assertEqual(script.duration_sec, 12.5)

    def test_malformed_script_info_is_machine_readable_failure(self):
        path = Path(tempfile.mkstemp(suffix=".csv")[1])
        try:
            path.write_text(
                "recordType\x01materialId\x01scriptInfo\n"
                "\x02script_analysis\x01m1\x01not-a-structure\n",
                encoding="utf-8",
            )
            row = parse_diagnosis_csv(path)[0]
            self.assertEqual(row.parse_status, "failed")
            self.assertEqual(row.script_info, {})
            self.assertIn("structured", row.parse_error)
        finally:
            path.unlink(missing_ok=True)

    def test_parser_rejects_non_unit_delimiter_and_non_finite_numbers(self):
        path = Path(tempfile.mkstemp(suffix=".csv")[1])
        try:
            path.write_text("recordType,materialId\nscript_analysis,m1\n", encoding="utf-8")
            with self.assertRaisesRegex(RpaCsvError, "delimiter"):
                parse_diagnosis_csv(path)
            path.write_text("recordType\x01materialId\x01metricValue\nscript_analysis\x01m1\x01NaN\n", encoding="utf-8")
            with self.assertRaisesRegex(RpaCsvError, "finite"):
                parse_diagnosis_csv(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
