# YTB02 AutoEditor

YTB02 AutoEditor là công cụ local cho Windows: nhận các video clip đã hoàn thành và một file script JSON, tạo narration bằng Kokoro, căn từng clip theo audio, ghép scene, tạo subtitle rồi xuất `output/FINAL_VIDEO.mp4`.

> Người dùng **tự cung cấp video clips**. Project này **không tạo video AI, không tạo ảnh**, không nghiên cứu nội dung và không publish YouTube.

## 1. Project này làm gì?

Luồng xử lý là:

`script.json + video clips` → Kokoro TTS → đo WAV thật → trim/freeze video → ghép scene và narration → tạo/burn subtitle → `FINAL_VIDEO.mp4`.

Audio narration là **master timeline**. Clip dài hơn audio sẽ bị trim. Clip ngắn hơn audio sẽ giữ nguyên frame cuối bằng FFmpeg, không loop và không thay đổi tốc độ mạnh. Audio gốc của clip bị bỏ trong MVP.

## 2. Cần cài gì?

- Windows 10/11.
- Python 3.12 cho project, nên bật tùy chọn thêm Python vào PATH khi cài.
- FFmpeg và ffprobe có trong PATH.
- Kokoro hiện có thể dùng ở `H:\KokoroCPU\.venv\Scripts\python.exe`.

Nếu Kokoro nằm nơi khác, sửa `kokoro_python` trong `config.json`. Code không phụ thuộc bắt buộc vào ổ H và không sửa thư mục Kokoro.

Để chạy test hoặc phát triển, cài dependency:

```bat
py -3.12 -m pip install -r requirements.txt
```

Pipeline chính dùng gần như toàn bộ standard library. `numpy` và `soundfile` được worker chạy trong môi trường Kokoro sử dụng để ghi WAV.

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
src/                   mã nguồn Python
tests/                 unit tests, không gọi Kokoro thật
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

- phiên bản Python;
- ffmpeg và ffprobe;
- đường dẫn Kokoro Python;
- import Kokoro English và Vietnamese;
- `input/script.json`;
- số clip trong `input/videos`.

Sửa mọi dòng `[FAIL]` trước khi build. Dòng `[WARN] input/script.json is missing` có nghĩa là bạn chưa copy script mẫu.

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
- **input/script.json is missing:** copy `script.example.json` thành `script.json`.
- **Không tìm thấy video:** tên trong script phải khớp chính xác file ở `input/videos`.
- **JSON không hợp lệ:** kiểm tra dấu phẩy, dấu ngoặc kép và vị trí dòng/cột được báo.
- **FFmpeg thất bại:** kiểm tra clip có hỏng hoặc codec đầu vào có được FFmpeg hỗ trợ không.

Lỗi dự kiến được in ngắn gọn, không hiện traceback dài. Pipeline dừng sớm khi input hoặc môi trường không hợp lệ.

## 12. Subtitle sync hoạt động như thế nào?

Subtitle lấy **chính xác từ `scene.text`**, không chạy Whisper hoặc speech-to-text. Mốc bắt đầu/kết thúc mỗi scene lấy từ duration thật của WAV 24 kHz. Nếu text dài, hệ thống chia theo dấu câu và độ dài, giữ nguyên từ và thứ tự; thời lượng các phrase trong scene được phân bổ theo lượng ký tự.

Đây là **phrase-level synchronization**, không phải phoneme/word forced alignment. Vì vậy nội dung đúng tuyệt đối theo script và timeline scene đúng theo audio, nhưng từng từ riêng lẻ không có timestamp cưỡng bức. Subtitle được burn ở bottom-center, trong safe area, chữ trắng viền đen và tối đa khoảng hai dòng với text thông thường.

## Kiểm thử dành cho developer

Không cần internet hoặc Kokoro thật để chạy unit tests:

```bat
py -3.12 -m unittest discover -s tests -v
```

Các test bao phủ JSON hợp lệ/không hợp lệ, ID trùng/không liên tục, video thiếu, timeline cộng dồn, định dạng SRT, bảo toàn nội dung và thứ tự subtitle.
