# STTLive — Nhận dạng giọng nói tiếng Việt (STT) + Chuyển văn bản thành giọng nói (TTS), chạy cục bộ

*Ngôn ngữ: **Tiếng Việt** · [English](README.md)*

Bộ công cụ **STT + TTS** tiếng Việt chạy hoàn toàn trên máy (local-first), tối ưu cho
Apple Silicon. Dựa trên [WhisperLiveKit](WhisperLiveKit/) (nhận dạng streaming/batch) và
sidecar [VieNeu-TTS](VieNeu-TTS/). Mọi thứ chạy trên thiết bị; không gửi dữ liệu lên cloud.

> Tài liệu chi tiết bằng tiếng Việt: [docs/SETUP.vi.md](docs/SETUP.vi.md).
> Detailed English reference: [docs/SETUP.md](docs/SETUP.md).

---

## 1. Cài đặt nhanh cho bản clone sạch (macOS Apple Silicon)

```bash
git clone https://github.com/imtoiteu/SpeechProcessingDesktop.git
cd SpeechProcessingDesktop
./scripts/diagnose_env.sh          # (tuỳ chọn) kiểm tra môi trường trước khi cài
./scripts/bootstrap_macos.sh       # tạo môi trường STT + TTS chính (không tải model nặng)
./scripts/setup_chunkformer.sh     # (tuỳ chọn) bật "Batch + ChunkFormer (tiếng Việt)"
./scripts/build_desktop_macos.sh   # build ứng dụng desktop (Tauri) → STTLive.app
./scripts/open_desktop_macos.sh    # mở ứng dụng đã build
```

Giải thích từng bước:

- **`diagnose_env.sh`** — in báo cáo môi trường (OS, Python, uv, ffmpeg, node, cargo, các
  venv, và file VAD bắt buộc). Chỉ đọc, không cài gì.
- **`bootstrap_macos.sh`** — thiết lập **hai môi trường chính**: `.venv` (STT) và
  `VieNeu-TTS/.venv` (TTS), rồi cài dependency cho desktop. Chạy lại nhiều lần được
  (idempotent). Không tải model nặng theo mặc định (thêm `--warm-tts` để tải trước model TTS).
- **`setup_chunkformer.sh`** — **bắt buộc nếu** bạn muốn dùng **Batch + ChunkFormer
  (tiếng Việt)**. Có thể **bỏ qua** nếu không cần ChunkFormer; các tính năng còn lại
  (streaming, batch Whisper, TTS) vẫn hoạt động bình thường.
- **`build_desktop_macos.sh`** — build ứng dụng Tauri thành `STTLive.app`.
- **`open_desktop_macos.sh`** — mở `STTLive.app` đã build.

## 2. Sử dụng hằng ngày

```bash
./scripts/open_desktop_macos.sh
```

- Ở **Chế độ Local Managed** (mặc định), ứng dụng **tự khởi động STT** trên `:8000` nếu
  chưa chạy.
- **TTS khởi động trễ (lazy-start)** khi bạn mở tab *Text → Speech* / bấm *Start TTS Server*.
- **Không cần** tự tay chạy server cho việc dùng desktop thông thường.

## 3. Chạy thủ công / gỡ lỗi (không cần ứng dụng desktop)

```bash
./scripts/run_stt_server.sh     # STT (WhisperLiveKit)  → http://localhost:8000
./scripts/run_tts_server.sh     # TTS (VieNeu-TTS)       → http://localhost:8011
./scripts/run_web_macos.sh      # giao diện web STT (chế độ web/debug) → http://localhost:8000
./scripts/dev_desktop_macos.sh  # chạy ứng dụng Tauri ở chế độ dev (hot-reload)
```

- **`run_stt_server.sh`** — khởi động WhisperLiveKit trên `http://localhost:8000`
  (streaming `/asr` + batch `/v1/audio/transcriptions`).
- **`run_tts_server.sh`** — khởi động VieNeu-TTS trên `http://localhost:8011`
  (health: `/tts/health`).
- **`run_web_macos.sh`** — dùng cho chế độ web/gỡ lỗi (chính là server STT ở trên).
- **`dev_desktop_macos.sh`** — chế độ phát triển Tauri.

## 4. Mô hình hai môi trường (venv)

| Môi trường | Nhiệm vụ | File thực thi quan trọng |
|---|---|---|
| **`.venv`** (gốc) | STT — WhisperLiveKit + mlx-whisper | `.venv/bin/whisperlivekit-server` |
| **`VieNeu-TTS/.venv`** | TTS — vieneu + llama-cpp-python + trafilatura | `VieNeu-TTS/.venv/bin/vieneu-stream` |
| **`.venv-chunkformer`** (tuỳ chọn) | Chỉ dùng cho **Batch + ChunkFormer** | tạo bằng `./scripts/setup_chunkformer.sh` |

> **Không sao chép thư mục `.venv` giữa các máy.** Venv chứa đường dẫn tuyệt đối và các
> gói nhị phân theo nền tảng (mlx-whisper, bản Metal của llama-cpp-python, torch). Luôn
> tạo lại trên từng máy bằng `./scripts/bootstrap_macos.sh`. `.venv-stage0` / `.venv-tts`
> là cũ/thử nghiệm, không tính năng nào đang dùng.

## 5. Bản đồ tính năng UI → backend

- **Micro streaming** → WebSocket `/asr`, dùng **mlx-whisper / large-v3-turbo** trên
  macOS Apple Silicon.
- **Phát lại bản ghi micro** → bản ghi trong WebView được chuyển sang **WAV/PCM** để phát
  lại ổn định trong ứng dụng.
- **Tải file / batch** → `POST /v1/audio/transcriptions`.
- **Batch + ChunkFormer** → dùng backend ChunkFormer; **lần chạy đầu chậm hơn** do model
  cần nạp/khởi động, các lần sau nhanh hơn nếu tiến trình server vẫn sống.
- **Text-to-Speech** → server TTS `http://localhost:8011`, health `/tts/health`, chọn
  model `q4` / `q8` / `ngochuyen` và giọng đọc từ danh sách.
- **Cài đặt (Settings)** → Local Managed / Remote Server, STT URL, TTS URL, tự khởi động
  STT, tự khởi động TTS, timeout.

## 6. Đường dẫn file cấu hình (lưu ngoài repo)

| Hệ điều hành | Đường dẫn |
|---|---|
| macOS | `~/Library/Application Support/STTLive/config.json` |
| Windows | `%APPDATA%\STTLive\config.json` |
| Linux | `~/.config/STTLive/config.json` |

Đặt lại cấu hình trên macOS (lần mở sau sẽ hiện lại hộp thoại thiết lập lần đầu):

```bash
rm -f "$HOME/Library/Application Support/STTLive/config.json"
```

## 7. Local Managed vs Remote Server

**Local Managed:**
- Server chạy trên **cùng máy** với ứng dụng.
- Ứng dụng có thể **tự khởi động STT**.
- **TTS khởi động trễ** khi cần.
- Phù hợp nhất cho dùng cục bộ trên MacBook Apple Silicon.

**Remote Server:**
- Ứng dụng **không** khởi động server cục bộ.
- Người dùng nhập **IP hoặc tên miền** của STT/TTS.
- Phù hợp cho triển khai LAN/công ty.
- **Khuyến nghị cho máy Windows/Linux**, trừ khi backend cục bộ đã được kiểm chứng.

## 8. Giới hạn Windows / Linux

- **Ứng dụng desktop (client)** build và chạy được trên cả ba hệ điều hành (xem
  [docs/DESKTOP_APP.md](docs/DESKTOP_APP.md)).
- **MLX/Metal chỉ có trên macOS.** Backend `mlx-whisper` (STT) và bản Metal của
  `llama-cpp-python` (TTS) là **riêng cho macOS**.
- **STT cục bộ trên Windows/Linux** dùng `faster-whisper` (CPU/CUDA) — **chưa được dự án
  kiểm chứng**; hãy tự xác minh trước khi dùng.
- **TTS cục bộ trên Windows/Linux** cần bản `llama-cpp-python` CPU/CUDA (không phải bản
  Metal của macOS) — cũng chưa kiểm chứng.
- **Khuyến nghị dùng Remote Server Mode** trên Windows/Linux, trỏ tới một máy backend đã
  được kiểm chứng (ví dụ máy Mac) trong cùng mạng LAN.

## 9. File tài nguyên bắt buộc: Silero VAD

STT nạp `WhisperLiveKit/whisperlivekit/silero_vad_models/silero_vad.onnx` (~2.3 MB) khi
khởi động. File này **đã được commit sẵn** trong repo nên bản clone sạch luôn có. Nếu vì
lý do nào đó bị thiếu, `bootstrap_macos.sh` và `run_stt_server.sh` sẽ **tự tải lại** từ
đúng phiên bản upstream đã ghim; `diagnose_env.sh` cũng kiểm tra file này.

---

Xem [docs/SETUP.vi.md](docs/SETUP.vi.md) để có hướng dẫn chi tiết bằng tiếng Việt, hoặc
[docs/SETUP.md](docs/SETUP.md) / [docs/DESKTOP_APP.md](docs/DESKTOP_APP.md) cho tài liệu
tiếng Anh.
