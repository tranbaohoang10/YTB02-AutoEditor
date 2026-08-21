import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CheckContractTests(unittest.TestCase):
    def test_check_requires_script_and_runs_mode_aware_dry_validation(self) -> None:
        content = (ROOT / "CHECK.bat").read_text(encoding="utf-8").lower()
        self.assertIn("[fail] input\\script.json is missing", content)
        self.assertIn("set \"check_failed=1\"", content)
        self.assertIn(
            "-m src.pipeline --script input\\script.json --config config.json --dry-run",
            content,
        )
        self.assertIn("script json and referenced visual sources are valid", content)
        self.assertIn("manual image mode does not require gemini_api_key", content)
        self.assertIn("gemini_api_key is required for gemini_api mode", content)
        self.assertIn("value is hidden", content)

    def test_check_does_not_load_or_download_alignment_models(self) -> None:
        content = (ROOT / "CHECK.bat").read_text(encoding="utf-8").lower()
        self.assertNotIn("load_align_model", content)
        self.assertNotIn("alignment_smoke", content)
        self.assertNotIn("huggingface", content)


if __name__ == "__main__":
    unittest.main()
