import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DependencyContractTests(unittest.TestCase):
    def test_whisperx_and_numpy_requirements_are_pinned_compatibly(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("whisperx==3.8.6", requirements)
        self.assertIn("numpy>=2.1,<3", requirements)

    def test_setup_pins_cpu_torch_family_and_runs_runtime_checks(self) -> None:
        setup = (ROOT / "SETUP.bat").read_text(encoding="utf-8")
        self.assertIn("torch==2.8.0", setup)
        self.assertIn("torchaudio==2.8.0", setup)
        self.assertIn("torchvision==0.23.0", setup)
        self.assertIn("https://download.pytorch.org/whl/cpu", setup)
        self.assertIn("-m pip check", setup)
        self.assertIn("import whisperx; import torch; import torchaudio", setup)


if __name__ == "__main__":
    unittest.main()
