from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "sfx"
SAMPLE_RATE = 48_000


def _write_whoosh(path: Path, duration: float, seed: int, brightness: float) -> None:
    rng = random.Random(seed)
    count = round(duration * SAMPLE_RATE)
    low = 0.0
    previous = 0.0
    values: list[float] = []
    for index in range(count):
        progress = index / max(1, count - 1)
        envelope = math.sin(math.pi * progress) ** 1.7
        sweep = 0.72 + 0.28 * math.sin(math.pi * progress)
        noise = rng.uniform(-1.0, 1.0)
        low += brightness * (noise - low)
        paper = low - 0.55 * previous
        previous = low
        accent = math.sin(2 * math.pi * (90 + 220 * progress) * index / SAMPLE_RATE)
        values.append(envelope * sweep * (0.33 * paper + 0.035 * accent))
    peak = max((abs(value) for value in values), default=1.0)
    # Normalize each original procedural asset to -4 dBFS. The production
    # transition gain remains the understandable relative control in config.
    normalization = (10 ** (-4.0 / 20.0)) / max(peak, 1e-9)
    samples = [
        max(-32768, min(32767, round(value * normalization * 32767)))
        for value in values
    ]
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_whoosh(OUTPUT / "paper_swipe_01.wav", 0.30, 2701, 0.16)
    _write_whoosh(OUTPUT / "paper_swipe_02.wav", 0.34, 2702, 0.11)
    _write_whoosh(OUTPUT / "soft_whoosh_01.wav", 0.24, 2703, 0.07)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
