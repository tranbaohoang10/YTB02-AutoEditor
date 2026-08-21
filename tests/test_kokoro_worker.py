import unittest

from src.kokoro_worker import _english_generator, _vietnamese_audio


class KokoroWorkerRegressionTests(unittest.TestCase):
    def test_english_adapter_preserves_voice_and_speed(self) -> None:
        calls = []
        def engine(text, *, voice, speed):
            calls.append((text, voice, speed))
            return ["audio-piece"]
        pieces = list(_english_generator(engine, "Hello", "am_eric", 1.08))
        self.assertEqual(calls, [("Hello", "am_eric", 1.08)])
        self.assertEqual(len(pieces), 1)

    def test_vietnamese_adapter_preserves_speed_and_audio_tuple_order(self) -> None:
        class Engine:
            def synthesize(self, text, *, speed):
                self.call = (text, speed)
                return [0.1, 0.2], "phonemes"
        engine = Engine()
        raw = _vietnamese_audio(engine, "Xin chào", "hung_thinh", 1.08)
        self.assertEqual(engine.call, ("Xin chào", 1.08))
        self.assertEqual(raw, ([0.1, 0.2], "phonemes"))
