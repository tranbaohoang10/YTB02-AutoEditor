# YTB02 AutoEditor

YTB02 AutoEditor là pipeline dựng video local-first cho Windows. Project nhận script JSON cùng ảnh/video do người dùng cung cấp, hoặc có thể tạo ảnh qua Google GenAI/Nano Banana khi người dùng chủ động cấu hình API. Audio narration luôn là master timeline.

Pipeline:

`script` → Kokoro TTS → punctuation-aware pause compression → đo WAV thật → WhisperX forced alignment → visual retiming → stable phrase subtitle → FFmpeg assemble/SFX mix → `output/FINAL_VIDEO_<số>.mp4`

## Invariant không thay đổi từ V1

- Canonical `scene.text` là source of truth cho narration và subtitle.
- WhisperX chỉ cung cấp timestamp; pipeline không dùng ASR transcript thay script.
- Future word không xuất hiện trước `word.start`; SRT/ASS luôn ceil timestamp.
- Không có proportional character/word fallback. Alignment fail là explicit và có diagnostics trong `work/alignment/`.
- Audio được tạo và nén pause trước khi đo/alignment. Visual scene bám timeline WAV hậu xử lý; cumulative frame quantization không được phép cắt ngắn audio master.
- English mặc định `am_eric`, Vietnamese mặc định `hung_thinh`, speed mặc định `1.0`; trường `speed` trong script vẫn là override rõ ràng.
- Loudness narration mặc định giữ `-18 LUFS`, `-1.5 dBTP`, LRA `7`; source-video audio được mix làm SFX nền ở gain mặc định `-18 dB`.
- Final mặc định 1920×1080, 30fps, H.264/yuv420p + AAC stereo 48 kHz.
- Mỗi build thành công tạo `FINAL_VIDEO_<số>.mp4` mới theo số lớn nhất hiện có + 1; video cũ không bị ghi đè. Tên được giữ trước khi FFmpeg render để giảm nguy cơ collision giữa các build đồng thời.
- Project không sửa hoặc cài dependency vào `H:\KokoroCPU`.

## Workflow ưu tiên — motion graphics layered collage

Đây là mode phù hợp với video documentary paper-collage: một scene được dựng từ background và nhiều ảnh rời có alpha. Từng item xuất hiện theo timeline, giữ nguyên sau entrance, rồi camera có thể drift/push rất nhẹ. Renderer local, deterministic và không generatively sửa nội dung.

Mỗi scene dùng một folder:

```text
input/scenes/scene_01/
  manifest.json
  background.jpg
  map.png
  bank.png
  pound.png
  label.png
  string.png
```

Copy sample có sẵn để bắt đầu:

```powershell
Copy-Item -Recurse input\sample-scenes\scene_01 input\scenes\scene_01
```

Script một scene:

```json
{
  "title": "Layered demo",
  "language": "en",
  "visual": {"mode": "layered_collage"},
  "scenes": [
    {
      "id": 1,
      "assets": "scene_01",
      "text": "This exact text remains the narration and subtitle source."
    }
  ]
}
```

Manifest tối thiểu:

```json
{
  "canvas": {"width": 1920, "height": 1080},
  "background": "background.jpg",
  "items": [
    {
      "id": "map", "file": "map.png",
      "x": 960, "y": 540, "scale": 1.0, "rotation": 0, "z": 1,
      "start": 0.0, "duration": 0.55,
      "enter": "paper_drop", "opacity": 1.0, "anchor": "center",
      "end_state": {"scale": 1.02, "rotation": 1.0}
    }
  ],
  "camera": {"type": "push_in", "start": 0.8, "zoom": 1.035},
  "transition_out": {"type": "paper_wipe", "duration": 0.45}
}
```

`x`/`y` là vị trí anchor trên canvas; `scale=1` là kích thước pixel gốc. `z` thấp được vẽ trước. `start` và `duration` tính bằng giây từ đầu scene. Item chưa tới `start` là invisible, animate trong `duration`, sau đó giữ trạng thái; `end_state` là drift tùy chọn tới cuối scene. Camera mặc định bắt đầu sau khi item cuối dựng xong nếu bỏ `camera.start`.

Entrance presets:

`slide_left_fade`, `slide_right_fade`, `slide_up_fade`, `slide_down_fade`, `pop_in`, `scale_in`, `stamp_in`, `paper_drop`, `slight_rotate_in`, `line_draw`, `string_reveal`, `highlight_flash`.

Transition presets:

`crossfade`, `paper_wipe`, `push_left`, `push_right`, `zoom_fade`, `none`.

Ví dụ bảy scene chỉ cần bảy folder độc lập và giữ đúng thứ tự JSON:

```json
{
  "language": "vi",
  "visual": {"mode": "layered_collage"},
  "scenes": [
    {"id": 1, "assets": "scene_01", "text": "Nội dung chuẩn cảnh một."},
    {"id": 2, "assets": "scene_02", "text": "Nội dung chuẩn cảnh hai."},
    {"id": 3, "assets": "scene_03", "text": "Nội dung chuẩn cảnh ba."},
    {"id": 4, "assets": "scene_04", "text": "Nội dung chuẩn cảnh bốn."},
    {"id": 5, "assets": "scene_05", "text": "Nội dung chuẩn cảnh năm."},
    {"id": 6, "assets": "scene_06", "text": "Nội dung chuẩn cảnh sáu."},
    {"id": 7, "assets": "scene_07", "text": "Nội dung chuẩn cảnh bảy."}
  ]
}
```

Chạy như các mode cũ: `CHECK.bat` validate toàn bộ manifest/asset/canvas trước; `BUILD_VIDEO.bat` hoặc `RUN_ALL.bat` render. Mỗi layered clip và final vẫn là 1920×1080, 30fps, H.264, yuv420p limited/TV range; duration lấy từ WAV narration thật.

## Các workflow tương thích

### Mode A — có ảnh phẳng sẵn

Copy ảnh `.png`, `.jpg`, `.jpeg` hoặc `.webp` vào `input\images`, đặt `visual.image_provider` là `manual`, rồi dùng `scene.image`.

```json
{
  "title": "Demo",
  "language": "en",
  "visual": {
    "image_provider": "manual",
    "style_preset": "newsprint-editorial",
    "motion_mode": "local"
  },
  "scenes": [
    {
      "id": 1,
      "image": "scene_01.png",
      "text": "This exact text becomes narration and subtitles.",
      "motion": {"type": "auto"}
    }
  ]
}
```

Local motion là mặc định được khuyến nghị: deterministic, chạy miễn phí bằng FFmpeg, giữ nội dung ảnh tốt nhất và không phụ thuộc API. Nó chỉ di chuyển camera; không redraw, thêm người, sửa logo/chữ/bản đồ hoặc hallucinate chi tiết.

### Mode B — chỉ có script, tạo ảnh bằng Nano Banana/Gemini

Đặt `image_provider` là `gemini_api`, bỏ `image`, rồi cung cấp `image_prompt`, `visual_hint`, hoặc chỉ narration. Prompt priority là `image_prompt` → `visual_hint` → `scene.text`.

```json
{
  "language": "en",
  "visual": {
    "image_provider": "gemini_api",
    "image_model": "gemini-3.1-flash-image",
    "style_preset": "newsprint-editorial",
    "aspect_ratio": "16:9",
    "image_size": "2K",
    "motion_mode": "local"
  },
  "scenes": [
    {
      "id": 1,
      "text": "Before sunrise London was preparing for a currency crisis.",
      "visual_hint": "Pre-dawn London and the Bank of England, tense documentary mood."
    }
  ]
}
```

Set key trong environment của terminal riêng; không ghi key vào JSON, `.bat`, source code hay file được commit:

```powershell
$env:GEMINI_API_KEY = "paste-key-in-private-terminal-only"
$env:GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image" # optional override
```

Đóng terminal sau build hoặc dùng secret manager/CI secret phù hợp. Ảnh được cache trong `work/generated-images/scene_XXX.png`; sidecar JSON chứa provider/model/prompt/hash/timestamp nhưng không chứa key. Ảnh chỉ tạo lại khi prompt/provider/model đổi hoặc truyền `--force-images`.

### Mode C — ảnh + optional AI image-to-video

AI motion phải opt-in rõ ràng:

```json
"visual": {
  "image_provider": "gemini_api",
  "motion_mode": "ai",
  "motion_provider": "gemini_image_to_video",
  "motion_model": "veo-3.1-generate-preview",
  "ai_fallback_local": true
}
```

Adapter dùng official Google GenAI client và `GEMINI_API_KEY`; `GEMINI_VIDEO_MODEL` có thể override model. AI I2V có thể tốn quota/credit và có thể thay đổi chi tiết ảnh dù prompt yêu cầu motion nhẹ/preserve composition. Nếu `ai_fallback_local=true`, lỗi provider sẽ fallback local; nếu false, lỗi là explicit. `auto` vẫn chọn local, không silently gọi AI.

## Backward compatibility với video input

Script V1 tiếp tục hoạt động:

```json
{
  "language": "vi",
  "voice": "hung_thinh",
  "speed": 1.0,
  "scenes": [
    {"id": 1, "video": "scene_01.mp4", "text": "Nội dung chuẩn từ script."}
  ]
}
```

Copy clip vào `input\videos`. Clip dài hơn narration bị trim; clip ngắn hơn được freeze frame cuối. Video được scale giữ tỷ lệ và pad về canvas. Nếu clip có audio stream, pipeline lấy phần audio trong thời lượng thật của clip, fade in/out nhẹ và mix làm ambient/transition/paper/whoosh SFX; audio không loop khi phần hình bị freeze. Clip không có audio vẫn build bình thường.

Các mặc định audio quan trọng trong `config.json`:

```json
{
  "audio": {
    "sample_rate": 24000,
    "mix_sample_rate": 48000,
    "gap_ms": 0,
    "narration_edge_silence_ms": 50,
    "preserve_source_audio": true,
    "source_audio_gain_db": -18.0,
    "source_audio_fade_ms": 120
  }
}
```

`sample_rate` là chuẩn WAV Kokoro/WhisperX. `mix_sample_rate` là chuẩn final mix. Pipeline chỉ bỏ padding silence ở mép đầu/cuối WAV narration, giữ nguyên pause nằm bên trong; với `gap_ms=0`, boundary hai scene còn khoảng 100–150 ms edge silence theo mặc định.

## Setup và thao tác Windows

Đồng bộ source:

```powershell
git switch main
git pull --ff-only origin main
```

Lần đầu double-click `SETUP.bat`. Script tạo/reuse `.venv`, cài CPU PyTorch, WhisperX, Pillow và official `google-genai`, sau đó chạy `pip check`. Alignment model được cache ở `.cache/alignment`, không nằm trong `work/`.

Mỗi video mới:

1. Copy `input\script.example.json` thành `input\script.json` rồi sửa.
2. Copy ảnh vào `input\images` hoặc video vào `input\videos` nếu dùng manual media.
3. Double-click `CHECK.bat`.
4. Chỉ tạo/resolve ảnh: `GENERATE_IMAGES.bat`.
5. Build: `BUILD_VIDEO.bat`, hoặc một nút generate + build: `RUN_ALL.bat`.
6. Lấy file mới nhất dạng `output\FINAL_VIDEO_<số>.mp4`; console in đường dẫn tuyệt đối dưới nhãn `FINAL VIDEO:` khi build thành công.

`CHECK.bat` kiểm tra Python, FFmpeg/ffprobe, Kokoro EN/VI, WhisperX, alignment config/cache, Pillow, Google GenAI client, script, media paths, provider và credential theo mode. Manual mode không yêu cầu Gemini key. CHECK không tạo ảnh/TTS, không tải model alignment và không render.

## CLI

```powershell
.venv\Scripts\python.exe -m src.pipeline --dry-run
.venv\Scripts\python.exe -m src.pipeline --generate-images
.venv\Scripts\python.exe -m src.pipeline --generate-images --force-images
.venv\Scripts\python.exe -m src.pipeline --build
.venv\Scripts\python.exe -m src.pipeline --run-all
.venv\Scripts\python.exe -m src.pipeline --run-all --motion-mode local
.venv\Scripts\python.exe -m src.pipeline --run-all --motion-mode ai
```

`--dry-run` chỉ parse/validate; không gọi API, không TTS, không download alignment model và không render.

## Schema và validation

Mỗi scene phải có ít nhất một trong:

- `assets`: safe folder name trong `input/scenes`, chứa `manifest.json` và layered assets;
- `video`: safe filename trong `input/videos`;
- `image`: safe filename trong `input/images`;
- `image_prompt` hoặc `visual_hint` để provider tạo ảnh.

Path phải là basename an toàn. Absolute path, `..`, subfolder và image extension khác PNG/JPG/JPEG/WebP đều fail. Scene IDs phải duy nhất, liên tục từ 1; text không rỗng; language chỉ `en`/`vi`.

Local motion presets: `slow_push_in`, `slow_pull_out`, `pan_left`, `pan_right`, `pan_up`, `pan_down`, `drift_subtle`, `static`, `auto`.

`auto` deterministic theo scene ID: push-in, pan-right, pull-out, pan-left, rồi các preset còn lại; rerun không random.

Style presets: `newsprint-editorial`, `photo-collage`, `modern-flat`, `american-retro`, `documentary-paper-collage`. Prompt master giữ consistency và yêu cầu no text vì subtitle được pipeline render sau.

## Folder

```text
input/images/             ảnh manual
input/scenes/             layered scene assets của user
input/sample-scenes/      sample paper-collage được track trong repo
input/videos/             video source V1
input/script.json         source of truth
work/audio/               WAV scene hoặc multi-scene chunk
work/generated-images/    ảnh API + cache metadata
work/motion/              image-motion clips
work/alignment/           word timing diagnostics
.cache/alignment/         model cache lâu dài
output/voice.wav
output/subtitles.srt
output/subtitles.ass
output/FINAL_VIDEO_<số>.mp4
```

Rerun chỉ dọn intermediate build folders trong `work`; không xóa input clips/images/layered assets, generated-image cache hoặc video final cũ. Chỉ file khớp chính xác `FINAL_VIDEO_<integer>.mp4` tham gia cấp số; các tên như `FINAL_VIDEO_backup.mp4` bị bỏ qua.

## Nhịp narration, forced alignment và subtitle

`audio.narration_mode` hỗ trợ `scene` (tương thích one-WAV-per-scene) và `continuous`. Continuous gom nhiều scene ổn định theo `continuous_chunk_scenes`, nối thành một narration master, align một lần với toàn bộ canonical text rồi ánh xạ từng word trở lại đúng scene. Không có word bị mất, trùng ownership hoặc đổi text.

`smart_pause_compression` chỉ cắt phần giữa của silence/near-silence PCM đủ dài. RMS detector có peak guard để bảo vệ consonant nhỏ; 25 ms edge guard mặc định và crossfade 8 ms tránh hard join/click. Pause ngắn giữ nguyên; pause medium/long/very-long được đưa về các target cấu hình. Speech không bị time-stretch. Thứ tự bắt buộc là TTS → pause compression → duration → WhisperX → scene timing/subtitle → video/SFX/final.

Source SFX/mixed final không bao giờ được dùng cho alignment. Model được load một lần cho language/run. Missing/extra/non-monotonic/out-of-duration word đều fail và ghi `work/alignment/scene_XXX.json`; continuous mode còn ghi `continuous_master.json`. Rolling cues chỉ reveal word tại aligned start. Canonical punctuation và Unicode Vietnamese được giữ nguyên.

Phân tích lại voice WAV hoặc final video bằng PCM detector và diagnostics scene:

```powershell
.venv\Scripts\python.exe tools\analyze_narration_pacing.py output\voice.wav --alignment-dir work\alignment --json work\diagnostics\pacing.json
```

## Developer checks

Unit/contract tests không gọi paid API và không tải model:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q src tests
.venv\Scripts\python.exe -m pip check
git diff --check
```

Real forced-alignment smoke vẫn có sẵn:

```powershell
.venv\Scripts\python.exe -m src.alignment_smoke --language en --wav test-en.wav --text "Exact canonical text."
.venv\Scripts\python.exe -m src.alignment_smoke --language vi --wav test-vi.wav --text "Nội dung chuẩn."
```

## Lỗi thường gặp

- `manual image provider cần file`: copy ảnh vào `input/images` và đặt `scene.image`.
- `GEMINI_API_KEY`: chỉ bắt buộc khi image provider hoặc AI motion dùng Gemini.
- `BLOCKED_EXTERNAL`: credential/quota/billing/permission/model/network hoặc provider timeout; pipeline không giả output.
- `Ảnh corrupt/quá nhỏ`: dùng ảnh decode được, tối thiểu 640×360 và aspect hợp lý.
- `Word alignment failed`: xem diagnostics; không có silent fallback.
- `Kokoro Python not found`: sửa `kokoro_python` trong `config.json`; project không sửa `H:\KokoroCPU`.
- `FFmpeg/ffprobe not found`: cài và thêm `bin` vào PATH.

## Security

Project không dùng browser login, cookie scraping, Selenium/Playwright auth, token extraction, account rotation hoặc quota circumvention. Subprocess nhận argument list, không `shell=True`. `.env`, credential folders, keys, input media và work artifacts đều bị ignore. CI chỉ dùng mocks/contract tests, không gọi paid API.
