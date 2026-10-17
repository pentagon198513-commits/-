"""Exercise the documented CLI as a separate process."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "matching.json"


class CliTests(unittest.TestCase):
    def run_cli(self, content: str, *, encoding: str = "utf-8"):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text(content, encoding=encoding)
            original = path.read_bytes()
            result = subprocess.run(
                [sys.executable, "-m", "supply_assistant", str(path)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                timeout=10,
            )
            self.assertEqual(path.read_bytes(), original, "Input must not be modified")
            return result

    def test_documented_example_reports_one_match_and_three_review_cases(self):
        result = self.run_cli(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(output["summary"], {"matched": 1, "needs_review": 3})
        self.assertEqual(
            [row["reason"] for row in output["results"]],
            ["exact_match", "not_found", "ambiguous_match", "scope_mismatch"],
        )
        self.assertEqual(output["results"][0]["product"]["article"], "00123")
        self.assertEqual(output["results"][3]["cabinet_id"], "demo-other-cabinet")
        self.assertIsNone(output["results"][3]["product"])

    def test_utf8_bom_file_with_matching_line_returns_success(self):
        request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        request["lines"] = request["lines"][:1]
        request["lines"][0]["barcode"] = "4600000000001"
        result = self.run_cli(json.dumps(request, ensure_ascii=False), encoding="utf-8-sig")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["summary"], {"matched": 1, "needs_review": 0})
        self.assertEqual(output["results"][0]["product"]["product_id"], "demo-item-1")
        self.assertEqual(output["results"][0]["order_id"], "demo-order-1")

    def test_numeric_article_rejects_whole_request_without_partial_results(self):
        request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        request["lines"][1]["article"] = 123
        result = self.run_cli(json.dumps(request))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("article", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_order_line_is_rejected(self):
        request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        request["lines"].append(dict(request["lines"][0]))
        result = self.run_cli(json.dumps(request))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("повтор", result.stderr)

    def test_malformed_json_has_no_traceback_or_partial_output(self):
        result = self.run_cli('{"catalog":')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Ошибка входных данных", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
