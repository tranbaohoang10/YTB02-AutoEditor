import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SecurityContractTests(unittest.TestCase):
    def test_subprocesses_do_not_use_shell_true_or_os_system(self) -> None:
        source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py"))
        self.assertNotRegex(source, r"shell\s*=\s*True")
        self.assertNotIn("os.system(", source)

    def test_gitignore_protects_local_credentials_and_media(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", "secrets/", "credentials/", "input/images/*", "input/videos/*"):
            self.assertIn(pattern, ignore)

    def test_repository_sources_contain_no_google_api_key_literal(self) -> None:
        paths = [*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").glob("test_*.py")]
        content = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertIsNone(re.search(r"AIza[0-9A-Za-z_-]{20,}", content))
