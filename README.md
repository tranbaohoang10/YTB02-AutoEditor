# YTB02 AutoEditor

YTB02 AutoEditor là công cụ local cho Windows: nhận các video clip đã hoàn thành và một file script JSON, tạo narration bằng Kokoro, căn từng clip theo audio, ghép scene, tạo subtitle rồi xuất `output/FINAL_VIDEO.mp4`.

> Người dùng **tự cung cấp video clips**. Project này **không tạo video AI, không tạo ảnh**, không nghiên cứu nội dung và không publish YouTube.

## 1. Project này làm gì?

Luồng xử lý là:

`script.json + video clips` → Kokoro TTS → đo WAV thật → WhisperX forced alignment → rolling word subtitle → trim/freeze/ghép video → burn subtitle → `FINAL_VIDEO.mp4`.

Audio narration là **master timeline**. Clip dài hơn audio sẽ bị trim. Clip ngắn hơn audio sẽ giữ nguyên frame cuối bằng FFmpeg, không loop và không thay đổi tốc độ mạnh. Audio gốc của clip bị bỏ trong MVP.

## 2. Cần cài gì?

- Windows 10/11.
- Python 3.12 cho project, nên bật tùy chọn thêm Python vào PATH khi cài.
- FFmpeg và ffprobe có trong PATH.
- Kokoro hiện có thể dùng ở `H:\KokoroCPU\.venv\Scripts\python.exe`.
- Project virtual environment riêng tại `.venv` cho WhisperX/PyTorch CPU.

Nếu Kokoro nằm nơi khác, sửa `kokoro_python` trong `config.json`. Code không phụ thuộc bắt buộc vào ổ H và không sửa thư mục Kokoro.

Lần đầu tiên, double-click:

```bat
SETUP.bat
```

`SETUP.bat` tạo `.venv`, cài PyTorch bản CPU và WhisperX cho riêng project này. Nó không cài gì vào `H:\KokoroCPU`. Model forced-alignment chỉ tải ở lần build đầu tiên rồi được reuse từ `.cache/alignment`.

## 3. Cấu trúc folder

```text
input/
  videos/              video clip do bạn cung cấp
  script.example.json  script mẫu
  script.json          script thật của lần chạy (tự tạo)
output/
  voice.wav            narration đã ghép
  subtitles.srt        subtitle chuẩn, UTF-8
  subtitles.ass        subtitle có style để burn
  FINAL_VIDEO.mp4      kết quả cuối
work/                  WAV từng scene và media trung gian
  alignment/           diagnostics word timing từng scene
.cache/alignment/      model/NLTK cache, không bị xóa khi rerun
src/                   mã nguồn Python
tests/                 unit tests dùng mock aligner, không tải model
```

## 4. Bỏ video vào input/videos

Copy mọi clip vào `input\videos\`. Tên file không bắt buộc theo `scene_01.mp4`; tên trong trường `video` của script mới là authority. Ví dụ `my_custom_clip.mp4` hoạt động bình thường.

Clip nên đọc được bằng FFmpeg. Mọi clip sẽ được normalize về 1920×1080, 30 fps, H.264 và `yuv420p`. Hình được scale giữ đúng tỷ lệ rồi pad đen, không bị kéo méo.

## 5. Sửa script.json

Copy file mẫu trước:

```bat
copy input\script.example.json input\script.json
```

Sau đó sửa `input\script.json` bằng editor hỗ trợ UTF-8:

```json
{
  "title": "Demo",
  "language": "en",
  "voice": "am_eric",
  "speed": 1.0,
  "scenes": [
    {
      "id": 1,
      "video": "my_custom_clip.mp4",
      "text": "This exact text becomes narration and subtitles."
    }
  ]
}
```

Quy tắc quan trọng:

- `language` chỉ là `en` hoặc `vi`.
- ID bắt đầu từ 1, liên tục và không trùng.
- Thứ tự scene lấy theo ID, không theo thứ tự file trong folder.
- `video` là tên file trong `input/videos`, không phải command hay đường dẫn tùy ý.
- `text` không được rỗng.
- Hỗ trợ từ 1 đến N scene, không giới hạn cứng 30 scene.

## 6. English voice

Dùng `"language": "en"`. Voice mặc định là `am_eric`. Kokoro English được khởi tạo với American English (`lang_code="a"`) và CPU.

## 7. Vietnamese voice

Dùng `"language": "vi"`. Voice mặc định là `hung_thinh`. File JSON, SRT và ASS đều được ghi Unicode để giữ dấu tiếng Việt.

## 8. Chạy CHECK.bat

Double click `CHECK.bat`. Script chỉ kiểm tra, không render:

- project `.venv` và Python;
- ffmpeg và ffprobe;
- WhisperX, PyTorch, alignment engine/device/config;
- trạng thái alignment model cache (không tự tải model);
- đường dẫn Kokoro Python;
- import Kokoro English và Vietnamese;
- `input/script.json`;
- số clip trong `input/videos`.

Sửa mọi dòng `[FAIL]` trước khi build. Nếu `.venv` thiếu, chạy `SETUP.bat`. Dòng cảnh báo model chưa cache là bình thường trước lần build đầu; CHECK không tải model lớn.

## 9. Chạy BUILD_VIDEO.bat

Sau khi CHECK không còn lỗi và script/video đã sẵn sàng, double click `BUILD_VIDEO.bat`. Khi thành công, cửa sổ hiển thị:

```text
================================
VIDEO BUILD COMPLETE
output\FINAL_VIDEO.mp4
================================
```

Có thể chạy bằng terminal:

```bat
python -m src.pipeline
python -m src.pipeline --script input\script.json
python -m src.pipeline --script input\script.json --dry-run
```

`--dry-run` chỉ parse script, validate clip và liệt kê scene; nó không cần chạy TTS và không render video.

## 10. File final nằm ở đâu?

Video cuối nằm tại `output\FINAL_VIDEO.mp4`. Narration và subtitle riêng nằm tại `output\voice.wav`, `output\subtitles.srt` và `output\subtitles.ass`.

Khi rerun, file trung gian trong `work/` được dựng lại an toàn. Clip đầu vào không bị xóa. `FINAL_VIDEO.mp4` cũ chỉ bị thay sau khi FFmpeg tạo xong bản mới.

## 11. Các lỗi thường gặp

- **Python 3.12 not found:** cài Python 3.12 hoặc sửa PATH.
- **ffmpeg/ffprobe not found:** cài FFmpeg và thêm folder `bin` vào PATH, sau đó mở lại terminal.
- **Kokoro Python not found:** sửa `kokoro_python` trong `config.json`.
- **Kokoro import failed:** kiểm tra package `kokoro`, `kokoro_vietnamese`, `numpy`, `soundfile` trong chính môi trường Kokoro.
- **WhisperX import failed:** chạy lại `SETUP.bat`; không cài WhisperX vào Kokoro environment.
- **Alignment model download failed:** kiểm tra internet ở lần build đầu; cache được giữ tại `.cache/alignment`.
- **Word alignment failed:** xem file `work/alignment/scene_XXX.json`; pipeline không fallback âm thầm.
- **input/script.json is missing:** copy `script.example.json` thành `script.json`.
- **Không tìm thấy video:** tên trong script phải khớp chính xác file ở `input/videos`.
- **JSON không hợp lệ:** kiểm tra dấu phẩy, dấu ngoặc kép và vị trí dòng/cột được báo.
- **FFmpeg thất bại:** kiểm tra clip có hỏng hoặc codec đầu vào có được FFmpeg hỗ trợ không.

Lỗi dự kiến được in ngắn gọn, không hiện traceback dài. Pipeline dừng sớm khi input hoặc môi trường không hợp lệ.

## 12. Subtitle sync hoạt động như thế nào?

Narration được Kokoro tạo trước thành WAV riêng cho từng scene. WhisperX sau đó chạy **forced word alignment** giữa WAV thật và transcript đã biết từ `scene.text`. Project không chạy Whisper transcription/ASR để đoán hoặc thay nội dung. Script vẫn là canonical source of truth; aligner chỉ cung cấp timestamp.

Subtitle dùng rolling word reveal: một canonical word chỉ xuất hiện khi playback đạt `word.start` đã align. Future words không được hiển thị sớm. Khi caption dài, project mở window mới, giữ bottom-center, safe area, chữ trắng viền đen và tối đa hai dòng. Cả English và Vietnamese dùng model mapping mặc định của WhisperX, có thể override trong `config.json`.

Đây là forced alignment có validation, không được quảng cáo là đồng bộ hoàn hảo trong mọi audio. Nếu thiếu/thừa word, sai thứ tự, thiếu timestamp hoặc vượt duration, pipeline dừng và ghi chi tiết tại `work/alignment/scene_XXX.json`. Không có silent fallback về cách chia duration theo số chữ/ký tự; `allow_approximate_fallback` mặc định là `false`.

Lần đầu build có thể chậm và cần internet để tải alignment model. Các lần sau reuse `.cache/alignment`. CPU được hỗ trợ và là mode bắt buộc hiện tại; không cần NVIDIA/CUDA.

## Kiểm thử dành cho developer

Không cần internet hoặc Kokoro thật để chạy unit tests:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Các test không tải model thật. Chúng bao phủ validation script/timeline, canonical word mapping, punctuation/Unicode Vietnamese, missing/extra words, diagnostics, global offsets, rolling windows, SRT/ASS ordering và invariant không hiển thị future word.
