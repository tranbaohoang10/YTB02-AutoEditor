# YTB02 AutoEditor V1 readiness

Ngày audit: 2026-08-20

Baseline code đã merge và final-verified: `9fed9a7439ee78b0b02aad71ce3d13cdce3ad539`

Trạng thái tổng: **PASS — V1 READY**

Quy ước:

- `PASS`: code/test/real verification hiện tại đủ chứng minh yêu cầu.
- `NEEDS_WORK`: còn thay đổi cụ thể cần hoàn thành.
- `BLOCKED_EXTERNAL`: cần dữ liệu, quyền hoặc hệ thống ngoài project.

## A. Installation

| Mục | Trạng thái | Evidence |
|---|---|---|
| A1 | PASS | `SETUP.bat` đã chạy thật trên Windows với Python 3.12.10. |
| A2 | PASS | Setup tạo và reuse project-local `.venv`. |
| A3 | PASS | Alignment dependencies chỉ cài trong project `.venv`; `H:\KokoroCPU` chỉ được invoke. |
| A4 | PASS | Real `pip check`: `No broken requirements found.` |
| A5 | PASS | Real imports WhisperX 3.8.6, Torch 2.8 CPU và Torchaudio 2.8 PASS. |
| A6 | PASS | Real rerun `SETUP.bat` reuse `.venv` và exit 0. |
| A7 | PASS | English/Vietnamese model được tải một lần vào `.cache/alignment` và reuse ở lần smoke sau. |
| A8 | PASS | `.venv/`, `.cache/` và `work/*` được ignore; `git check-ignore` đã xác nhận. |

## B. Environment check

| Mục | Trạng thái | Evidence |
|---|---|---|
| B1 | PASS | CHECK kiểm tra dependency/config/import, yêu cầu script + ít nhất một clip và chạy pipeline `--dry-run` để validate JSON/video references mà không render. |
| B2 | PASS | CHECK chỉ import package/đọc cache, không gọi load model hoặc download. |
| B3 | PASS | Missing script/clip và dry-run failure đều có `[FAIL]` cùng hướng khắc phục; CHECK chỉ báo ready khi không còn lỗi. |

## C. Script validation

| Mục | Trạng thái | Evidence |
|---|---|---|
| C1 | PASS | Loader chỉ chấp nhận `en`/`vi`. |
| C2 | PASS | Loader bắt buộc IDs liên tục `1..N`. |
| C3 | PASS | Duplicate ID fail; có unit test. |
| C4 | PASS | Missing video fail; có unit test. |
| C5 | PASS | Narration phải là chuỗi và `strip()` không được rỗng. |
| C6 | PASS | Invalid JSON báo dòng/cột; có unit test lỗi JSON. |
| C7 | PASS | `video` chỉ được là filename, từ chối absolute path và path traversal. |
| C8 | PASS | Đọc `utf-8-sig`; real Vietnamese TTS/alignment và unit Unicode đều PASS. |

## D. TTS

| Mục | Trạng thái | Evidence |
|---|---|---|
| D1 | PASS | Real English Kokoro `am_eric` tạo WAV 3.925 giây. |
| D2 | PASS | Real Vietnamese Kokoro `hung_thinh` tạo WAV 3.150 giây. |
| D3 | PASS | Worker khởi tạo một engine trước loop scene. |
| D4 | PASS | Worker ghi `scene_XXX.wav` riêng cho từng scene. |
| D5 | PASS | Text truyền qua manifest JSON UTF-8, không đưa trực tiếp vào shell. |
| D6 | PASS | `subprocess.run` dùng argument list, không dùng `shell=True`. |
| D7 | PASS | Worker và bridge đều fail nếu audio/WAV rỗng. |

## E. Audio master timeline

| Mục | Trạng thái | Evidence |
|---|---|---|
| E1 | PASS | Timeline dùng duration WAV từ real ffprobe. |
| E2 | PASS | Không có estimate theo word/character count. |
| E3 | PASS | Cumulative offsets có unit test và real scene-2 offset 4.247 giây PASS. |
| E4 | PASS | `gap_ms` được dùng trong timeline, video target và audio silence concat; unit test xác nhận cumulative gap. |
| E5 | PASS | Real `voice.wav` và final render cùng audio-master duration 6.500 giây. |

## F. Forced alignment

| Mục | Trạng thái | Evidence |
|---|---|---|
| F1 | PASS | Real English WhisperX alignment 10/10 canonical words. |
| F2 | PASS | Real Vietnamese WhisperX alignment 12/12 canonical words. |
| F3 | PASS | Pipeline chỉ gọi alignment với `scene.text`; không chạy Whisper ASR. |
| F4 | PASS | Missing canonical word fail; unit test. |
| F5 | PASS | Extra aligned word fail; unit test. |
| F6 | PASS | Non-monotonic timestamp fail; unit và real timestamps PASS. |
| F7 | PASS | Punctuation được map về canonical display text. |
| F8 | PASS | Standalone dash/ellipsis/arrow gắn deterministic vào spoken token, không tạo fake timestamp. |
| F9 | PASS | Mỗi scene ghi `work/alignment/scene_XXX.json`. |
| F10 | PASS | Failure nêu scene, aligned/canonical count, reason và diagnostics path. |
| F11 | PASS | Approximate fallback mặc định false và bị từ chối rõ nếu bật. |

## G. Subtitle

| Mục | Trạng thái | Evidence |
|---|---|---|
| G1 | PASS | Rolling cue được tạo theo từng `word.start`. |
| G2 | PASS | Unit invariant và real English/Vietnamese/E2E no-future-word checks PASS. |
| G3 | PASS | SRT millisecond và ASS centisecond đều ceil; unit serialization PASS. |
| G4 | PASS | ASS style alignment `2` (bottom-center), real burn PASS. |
| G5 | PASS | Config/ASS dùng bottom margin 70. |
| G6 | PASS | ASS chữ trắng, outline đen. |
| G7 | PASS | Window fitting và real ASS đều tối đa hai dòng. |
| G8 | PASS | Caption dài rollover sang window mới; unit test. |
| G9 | PASS | Real English rolling subtitle PASS. |
| G10 | PASS | Real Vietnamese Unicode alignment và rolling cue PASS. |
| G11 | PASS | Final FFmpeg render burn file ASS thật. |
| G12 | PASS | `output/subtitles.srt` được tạo trong real pipeline. |

## H. Video processing

| Mục | Trạng thái | Evidence |
|---|---|---|
| H1 | PASS | Filter normalize không giả định resolution đầu vào; synthetic 640x360 đã render thành 1920x1080. |
| H2 | PASS | `force_original_aspect_ratio=decrease`. |
| H3 | PASS | Pad đen tới canvas target. |
| H4 | PASS | Real prepared/final streams: 1920x1080, 30fps, H.264, yuv420p. |
| H5 | PASS | Prepared scene map video-only và dùng `-an`. |
| H6 | PASS | Real 8.000 giây clip trim còn 2.567 giây cho target 2.575. |
| H7 | PASS | Real 2.000 giây clip freeze thành 3.933 giây cho target 3.925. |
| H8 | PASS | Real two-scene concat PASS. |
| H9 | PASS | Pipeline chỉ đọc `input/videos`; cleanup chỉ tác động ignored `work` artifacts. |

## I. Final render

| Mục | Trạng thái | Evidence |
|---|---|---|
| I1 | PASS | Real `output/FINAL_VIDEO_<số>.mp4` được tạo. |
| I2 | PASS | Real file size 1,133,901 bytes. |
| I3 | PASS | ffprobe xác nhận video stream. |
| I4 | PASS | ffprobe xác nhận audio stream. |
| I5 | PASS | ffprobe: 1920x1080. |
| I6 | PASS | ffprobe: `30/1` fps. |
| I7 | PASS | ffprobe: H.264. |
| I8 | PASS | ffprobe: AAC. |
| I9 | PASS | FFmpeg ASS filter hoàn tất và artifact verifier PASS. |
| I10 | PASS | Final 6.500 giây khớp narration timeline trong frame tolerance. |
| I11 | PASS | Render vào file `.building.mp4` theo số đã giữ, chỉ `os.replace` reservation sau khi build thành công. |

## J. Error handling

| Mục | Trạng thái | Evidence |
|---|---|---|
| J1 | PASS | CLI catch `AutoEditorError`, in message ngắn và không traceback. |
| J2 | PASS | Validation/TTS/alignment/media errors có context người dùng. |
| J3 | PASS | FFmpeg failure giữ 3000 ký tự cuối stderr/stdout. |
| J4 | PASS | Alignment failure nêu exact scene ID và diagnostics. |
| J5 | PASS | Batch files và README chỉ cách sửa dependency thiếu. |
| J6 | PASS | Pipeline/smoke catch `KeyboardInterrupt`, trả exit code 130; final cũ chỉ replace khi thành công. |
| J7 | PASS | Source media không nằm trong cleanup/delete paths. |

## K. Testing

| Mục | Trạng thái | Evidence |
|---|---|---|
| K1 | PASS | 45/45 unit tests PASS, gồm CHECK, speed default và loudnorm command contracts. |
| K2 | PASS | Bugs punctuation/alignment review đã có regression tests. |
| K3 | PASS | Main CI run cho `9fed9a7` SUCCESS. |
| K4 | PASS | Python compileall PASS. |
| K5 | PASS | `git diff --check` PASS. |
| K6 | PASS | Real English alignment smoke PASS. |
| K7 | PASS | Real Vietnamese alignment smoke PASS. |
| K8 | PASS | Real two-scene synthetic end-to-end render PASS. |
| K9 | PASS | Real no-future-word English, Vietnamese và E2E PASS. |
| K10 | PASS | Real FFmpeg trim/freeze durations trong one-frame tolerance. |

## L. Documentation

| Mục | Trạng thái | Evidence |
|---|---|---|
| L | PASS | README mô tả scope/non-scope, setup/check/input/script, EN/VI, forced alignment, first download, build/output và common errors; nói rõ không quảng cáo alignment hoàn hảo. |

## M. Git/GitHub

| Mục | Trạng thái | Evidence |
|---|---|---|
| M | PASS | AGENTS quy định Issue → branch → tests → commit → push → PR → CI → squash merge; PR #4 đã theo workflow, không force push/direct commit main. |

## Gap cần xử lý

Không còn gap code P0/P1/P2 sau Issue #7, không có `BLOCKED_EXTERNAL`, không có Issue/PR code mở và chưa có lý do tạo thêm feature ngoài scope.

## Final acceptance trên Windows

Final acceptance được chạy lại từ đầu trên `main` commit `9fed9a7` ngày 2026-08-20:

- 40/40 unit tests, compileall và `pip check`: PASS.
- `CHECK.bat` với two-scene input hợp lệ: PASS, exit 0, dry-run validate script/video references.
- Kokoro English `am_eric`: tạo WAV thật 3.925 giây.
- English forced alignment: 10/10 canonical words; real no-future-word: PASS.
- Kokoro Vietnamese `hung_thinh`: tạo WAV thật 3.150 giây.
- Vietnamese forced alignment: 12/12 canonical words; Unicode/no-future-word: PASS.
- `BUILD_VIDEO.bat` two-scene end-to-end: PASS, exit 0.
- Freeze: clip 2.000 giây → prepared 3.933 giây, target narration 3.925 giây.
- Trim: clip 8.000 giây → prepared 2.567 giây, target narration 2.575 giây.
- ASS bottom-center, max hai dòng, timestamps/global offset/no-future-word E2E: PASS.
- Final ffprobe: 1920x1080, 30/1 fps, H.264, yuv420p, AAC, 6.500 giây, file non-empty.
- `git diff --check`: PASS; smoke copies đã được dọn khỏi `input`, không sửa `H:\KokoroCPU`.

## Giới hạn không blocking

- FFmpeg/ffprobe và Kokoro environment vẫn là prerequisite local theo README.
- Lần alignment đầu cần internet để tải model; các lần sau reuse `.cache/alignment`.
- Forced alignment có validation nhưng không được coi là hoàn hảo với mọi audio; failure luôn explicit và không có proportional fallback.

## Post-V1: narration audio tuning

Issue #11 giữ nguyên toàn bộ V1 invariants và bổ sung:

- Default narration speed `1.08`; explicit `1.0`, `1.15` hoặc giá trị hợp lệ khác vẫn được tôn trọng.
- `voice.wav` được FFmpeg loudnorm sau concat với target khoảng `-18 LUFS`, `-1.5 dBTP`, LRA `7 LU`; scene WAV gốc vẫn là nguồn duration/alignment.
- Real speed smoke cùng text/voice: 1.00 = 3.925 giây, 1.08 = 3.800 giây.
- Real single-scene loudness: `-24.77` → `-18.33 LUFS`; true peak sau normalize `-3.58 dBTP`; duration giữ 3.800 giây.
- Isolated two-scene E2E: `voice.wav -17.70 LUFS / -2.53 dBTP`, final AAC `-17.72 LUFS / -2.54 dBTP`, duration 6.250 giây.
- Forced alignment, rolling subtitle, real no-future-word, ASS, trim/freeze và final ffprobe đều PASS sau normalization.
