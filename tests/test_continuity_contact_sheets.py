import unittest

from tools.extract_continuity_contact_sheets import _select_boundaries


class ContinuityContactSheetSelectionTests(unittest.TestCase):
    def test_fills_representative_sample_when_language_has_no_short_pauses(self) -> None:
        boundaries = [
            {
                "scene_from": index,
                "scene_to": index + 1,
                "available_narration_pause_ms": 280 + index * 10,
                "static_dead_zone_ms": index % 4 * 33,
            }
            for index in range(1, 30)
        ]

        selected = _select_boundaries(boundaries)

        self.assertEqual(len(selected), 13)
        keys = {(item["scene_from"], item["scene_to"]) for _, item in selected}
        self.assertEqual(len(keys), 13)
        self.assertTrue(any(category == "representative" for category, _ in selected))


if __name__ == "__main__":
    unittest.main()
