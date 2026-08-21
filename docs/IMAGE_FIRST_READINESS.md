# Image-first pipeline readiness

Ngày verification: 2026-08-21

Issue: #13

Branch: `feat/13-image-first-pipeline`

Baseline main: `b8037bd6509b6bdc7b731a8b3c60a43a44fd9297`

## Baseline

- Unit tests: 45/45 PASS.
- `compileall`: PASS.
- `pip check`: PASS.
- `git diff --check`: PASS.
- Existing seven-scene video-only script dry-run: PASS.

## Architecture delivered

- Backward-compatible `Scene` schema: video, manual image, or provider-generated image.
- Safe basename validation and PNG/JPG/JPEG/WebP allowlist.
- Manual and official Google GenAI image-provider abstraction.
- Deterministic master style prompt, five presets, scene prompt priority and retry prompt.
- SHA-256 prompt/provider/model cache with secret-free JSON sidecars.
- Image decode/resolution/aspect QC and ffprobe video QC.
- Local FFmpeg motion with eight deterministic presets plus scene-ID-based `auto`.
- Local motion uses measured narration duration and produces 1920×1080, 30fps, H.264/yuv420p.
- Optional official Google GenAI/Veo image-to-video adapter, explicit opt-in, warning, normalization and configured local fallback.
- CLI actions: dry-run, generate images, force images, build, run-all and motion-mode override.
- Windows UX: mode-aware CHECK plus `GENERATE_IMAGES.bat` and `RUN_ALL.bat`.

## Final regression gate

- Tests: 84/84 PASS, including opt-in real FFmpeg image-motion smoke.
- `compileall`: PASS.
- `pip check`: PASS.
- `git diff --check`: PASS.
- Security contracts: PASS; no `shell=True`, `os.system`, committed Google key literal or credential metadata.
- Updated CHECK in manual mode: PASS, including Kokoro EN/VI imports and dry-run.

## Real local acceptance

### Manual image E2E

PASS:

- manual PNG → local `slow_push_in` → real Kokoro English `am_eric` at 1.08;
- measured WAV 4.600s → WhisperX 14/14 canonical words;
- rolling SRT/ASS with real no-future-word and ceil timestamp verification;
- loudnorm measured `-18.4 LUFS`, true peak `-3.3 dBFS`;
- final: 1920×1080, 30/1 fps, H.264, yuv420p, AAC, 4.600s;
- final duration exactly follows the 4.600s audio master.

### Legacy video-only E2E

PASS:

- unchanged V1 scene schema;
- source clip 4.000s froze to narration target 4.600s;
- final: 1920×1080, 30/1 fps, H.264, yuv420p, AAC, 4.600s;
- Kokoro, WhisperX, rolling subtitle, loudness and atomic replacement remained active.

## External smoke status

- Real Gemini/Nano Banana image generation: `BLOCKED_EXTERNAL_REAL_API` — `GEMINI_API_KEY` absent. Official adapter signature was verified against installed `google-genai 1.75.0`; mocked provider/cache/retry/QC tests PASS.
- Real Gemini/Veo image-to-video: `BLOCKED_EXTERNAL_REAL_I2V` — provider credential absent. Official adapter signature was verified locally; mocked success/failure/fallback/normalization tests PASS.
- Missing-key dry-runs return explicit `BLOCKED_EXTERNAL` without making an API call.

## Acceptance summary

- AC-01 through AC-25 non-external requirements: PASS.
- No internal P0/P1 blocker remains.
- Paid/external smoke tests remain accurately blocked by absent credentials; local/manual workflow is fully operational without them.
