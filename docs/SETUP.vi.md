# SETUP (Tiếng Việt) — clone sạch → chạy → build

*Ngôn ngữ: **Tiếng Việt** · [English](SETUP.md)*

Đây là tài liệu tham chiếu để đưa một **bản clone sạch** vào hoạt động mà **không phụ
thuộc** vào trạng thái sẵn có của máy (venv cũ, thư mục rác, Python toàn cục). Mọi thứ
được điều khiển bằng các script trong [`scripts/`](../scripts).

macOS Apple Silicon là nền tảng **chính, đã được kiểm chứng**. Trạng thái Windows/Linux ở
cuối tài liệu.

---

## A. Cài đặt nhanh cho bản clone sạch (macOS)

```bash
git clone https://github.com/imtoiteu/SpeechProcessingDesktop.git
cd SpeechProcessingDesktop
./scripts/diagnose_env.sh          # (tuỳ chọn) báo cáo môi trường
./scripts/bootstrap_macos.sh       # STT venv + TTS venv + dependency desktop
./scripts/setup_chunkformer.sh     # (tuỳ chọn) bật Batch + ChunkFormer (tiếng Việt)
./scripts/build_desktop_macos.sh   # build STTLive.app
./scripts/open_desktop_macos.sh    # mở ứng dụng
```

`bootstrap_macos.sh` chạy lại nhiều lần được (idempotent). Nó:

1. Kiểm tra OS + công cụ cần thiết (`uv`, `ffmpeg`, `node`/`npm`, `cargo`) và in gợi ý cài
   đặt nếu thiếu.
2. Tạo **`.venv` gốc** (STT): cài `whisperlivekit` (editable) + `mlx-whisper`, và kiểm tra
   `.venv/bin/whisperlivekit-server` tồn tại.
3. Thiết lập **`VieNeu-TTS/.venv`** (TTS): `uv sync`, rồi cài lại wheel Metal
   `llama-cpp-python==0.3.16` + `trafilatura`, và kiểm tra `import vieneu`,
   `import llama_cpp`, `import trafilatura`.
4. Cài dependency desktop (`npm install`) và tạo icon (`npm run icon`).

Không tải model nặng (chúng tự tải khi dùng lần đầu). Để tải trước model TTS:

```bash
./scripts/bootstrap_macos.sh --warm-tts     # chạy scripts/download_tts_model.sh
```

> **Vì sao wheel TTS được cài lại mỗi lần chạy:** một lệnh `uv sync` trơn trong
> `VieNeu-TTS` cài phần lõi (không torch) nhưng có thể **gỡ mất** `llama-cpp-python` (nó
> nằm trong nhóm tuỳ chọn nặng). Bootstrap cài lại wheel Metal mỗi lần để backbone GGUF
> luôn hoạt động.

**`setup_chunkformer.sh` — bắt buộc cho ChunkFormer, có thể bỏ qua:** cần chạy **nếu** bạn
muốn dùng model **Batch + ChunkFormer (tiếng Việt)** trong UI. Nó tạo venv cô lập
`.venv-chunkformer` (ChunkFormer kéo theo torch/torchaudio riêng, xung đột với venv STT/TTS
nên phải tách riêng). Nếu không cần ChunkFormer, **bỏ qua bước này** — streaming, batch
Whisper và TTS vẫn chạy bình thường.

## B. Sử dụng hằng ngày

```bash
./scripts/open_desktop_macos.sh
```

Nếu chưa build ứng dụng, lệnh này sẽ in: *"Please run ./scripts/build_desktop_macos.sh first."*

Ở **Local Managed Mode**, ứng dụng tự khởi động STT nếu `:8000` chưa chạy, và TTS khởi
động trễ khi mở tab Text→Speech. Bạn **không cần** tự chạy server.

## C. Chạy thủ công / gỡ lỗi (chạy trực tiếp server, không cần ứng dụng)

```bash
./scripts/run_stt_server.sh     # STT: streaming (/asr) + batch (/v1/audio/transcriptions) → :8000
./scripts/run_tts_server.sh     # sidecar TTS → :8011 (health: /tts/health)
./scripts/run_web_macos.sh      # giao diện web + API STT → http://localhost:8000 (bí danh của run_stt_server.sh)
./scripts/dev_desktop_macos.sh  # chế độ dev Tauri (hot-reload)
```

Biến môi trường ghi đè cho `run_stt_server.sh` (mặc định giữ nguyên lệnh macOS đã kiểm chứng):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `STTLIVE_STT_MODEL` | `large-v3-turbo` | Kích thước model streaming |
| `STTLIVE_STT_LANGUAGE` | `auto` | Ngôn ngữ (`auto` = tự phát hiện) |
| `STTLIVE_STT_HOST` | `localhost` | Host lắng nghe |
| `STTLIVE_STT_PORT` | `8000` | Cổng lắng nghe |

(Các tên cũ `STT_MODEL` / `STT_LANGUAGE` / `STT_HOST` / `STT_PORT` vẫn dùng được như
phương án dự phòng. Backend/policy giữ nguyên `mlx-whisper` / `simulstreaming`.)

## D. Mô hình hai môi trường (venv)

| Môi trường | Hệ con | File thực thi quan trọng |
|---|---|---|
| **`.venv`** (gốc) | STT — WhisperLiveKit + mlx-whisper | `.venv/bin/whisperlivekit-server` |
| **`VieNeu-TTS/.venv`** | TTS — vieneu + llama-cpp-python + trafilatura | `VieNeu-TTS/.venv/bin/vieneu-stream` |

Venv thứ ba (tuỳ chọn):

| Môi trường | Hệ con | Tạo bằng |
|---|---|---|
| **`.venv-chunkformer`** | Chỉ dùng cho **Batch ChunkFormer (tiếng Việt)** | `./scripts/setup_chunkformer.sh` |

`.venv-stage0` và `.venv-tts` là **cũ/thử nghiệm** — không tính năng UI hiện tại nào dùng.
`./scripts/diagnose_env.sh` cho biết venv nào tồn tại và các import quan trọng có chạy
không, để phân biệt cái đang dùng với cái cũ.

> **Không sao chép thư mục `.venv` giữa các máy.** Venv chứa đường dẫn tuyệt đối và các
> gói nhị phân theo nền tảng (mlx-whisper, bản Metal của llama-cpp-python, torch). Luôn tạo
> lại trên từng máy bằng `./scripts/bootstrap_macos.sh` (và `./scripts/setup_chunkformer.sh`
> nếu cần). Mọi thư mục `.venv*` đều đã bị git bỏ qua vì lý do này.

## E. Bản đồ tính năng UI → backend

| Tính năng UI | Endpoint / backend |
|---|---|
| **Micro streaming** | WebSocket `ws://<stt>/asr` — MLX-Whisper `large-v3-turbo` (singleton trong tiến trình) trên macOS Apple Silicon |
| **Phát lại bản ghi micro** | bản ghi trong WebView được chuyển sang **WAV/PCM** để phát lại ổn định (Safari/WKWebView không phát lại được blob MediaRecorder thô) |
| **Tải file / batch** | `POST <stt>/v1/audio/transcriptions` |
| **Batch + ChunkFormer (tiếng Việt)** | cùng endpoint → định tuyến sang tiến trình con ChunkFormer (`.venv-chunkformer`) |
| **Batch + tiny/base/small/medium/large-v3-turbo** | cùng endpoint → MLX-Whisper theo từng model |
| **TTS** | `http://<tts>/tts/*` trên `:8011` (hoặc TTS URL đã cấu hình); health `GET /tts/health`; model `q4` / `q8` / `ngochuyen` + danh sách giọng |
| **Cài đặt desktop** | chọn **Local Managed** / **Remote Server**, STT URL, TTS URL, tự khởi động STT, tự khởi động TTS, timeout |

Server ghi log quyết định định tuyến cho mỗi yêu cầu batch (model yêu cầu, backend được
chọn, ChunkFormer/mlx-whisper/fallback, thời gian xử lý) và ghi log backend/model một lần
mỗi phiên `/asr` — để bạn xác nhận engine nào đã chạy.

> **Khởi động (warm-up) ChunkFormer:** lần chạy batch ChunkFormer **đầu tiên** chậm hơn vì
> model nạp/khởi động theo yêu cầu; các lần **sau** nhanh hơn miễn là tiến trình server STT
> còn sống (nó giữ model đã nạp trong bộ nhớ).

## F. Local Managed Mode

- STT và TTS chạy trên **cùng máy** với ứng dụng.
- Ứng dụng có thể **tự khởi động STT** trên `:8000` nếu chưa chạy.
- **TTS khởi động trễ** trên `:8011` khi mở tab Text→Speech / bấm *Start TTS Server*.
- Khi thoát, ứng dụng chỉ dừng **những tiến trình do chính nó khởi động** (không đụng tới
  tiến trình bên ngoài).

## G. Remote Server Mode

- Ứng dụng **không** khởi động server cục bộ nào.
- Bạn nhập **URL theo IP hoặc tên miền** của STT/TTS (ví dụ `http://192.168.1.20:8000`).
- Dành cho triển khai LAN/công ty và các client Windows/Linux trỏ tới một máy backend đã
  được kiểm chứng (ví dụ macOS).

Đổi chế độ bất cứ lúc nào qua nút **⚙ Settings** trên thanh trên cùng của ứng dụng.

## H. Đường dẫn file cấu hình

Lần mở đầu (nếu chưa có cấu hình) hiện hộp thoại thiết lập; sau đó bỏ qua và dùng lại cấu
hình đã lưu. Cấu hình nằm **ngoài repo**:

| Hệ điều hành | Đường dẫn |
|---|---|
| macOS | `~/Library/Application Support/STTLive/config.json` |
| Windows | `%APPDATA%\STTLive\config.json` |
| Linux | `~/.config/STTLive/config.json` |

Các trường: `mode` (`local`/`remote`), `stt_url`, `tts_url`, `auto_start_stt`,
`auto_start_tts`, `timeout_seconds`.

## I. Đặt lại cấu hình

```bash
# macOS
rm -f "$HOME/Library/Application Support/STTLive/config.json"

# Linux
rm -f "$HOME/.config/STTLive/config.json"

# Windows (PowerShell)
Remove-Item "$env:APPDATA\STTLive\config.json"
```

Lần mở tiếp theo sẽ hiện lại hộp thoại thiết lập lần đầu.

## J. Trạng thái & giới hạn Windows / Linux

**Ứng dụng desktop (client) build và chạy được trên cả ba hệ điều hành.** Phần *backend
cục bộ* thì khác:

- **Không có MLX/Metal** ngoài macOS — STT `mlx-whisper` và wheel Metal `llama-cpp-python`
  của TTS là **riêng cho macOS**.
- **STT cục bộ trên Windows/Linux** dùng `faster-whisper` (`run_stt_windows.ps1` /
  `run_stt_linux.sh`), backend đa nền tảng của upstream (CPU, hoặc CUDA nếu cài bản
  ctranslate2 GPU). Đường này **chưa được dự án kiểm chứng** — hãy tự xác minh trên phần
  cứng thật trước khi dựa vào nó.
- **TTS cục bộ trên Windows/Linux** cần wheel `llama-cpp-python` bản **CPU hoặc CUDA**
  (KHÔNG phải wheel Metal của macOS). Cũng chưa kiểm chứng ở đây.
- **ChunkFormer** trên Windows/Linux có thể chạy CPU/CUDA qua `.venv-chunkformer`, nhưng
  chỉ đường macOS (MPS/CPU) đã được chạy thử.
- **Khuyến nghị trên Windows/Linux:** chạy ứng dụng ở **Remote Server Mode** trỏ tới một
  máy STT/TTS đã kiểm chứng (ví dụ máy Mac) trong mạng LAN.

Script bootstrap/build/run:

```bash
# Linux
./scripts/bootstrap_linux.sh            # dependency client desktop (thêm --with-stt để tạo venv faster-whisper cục bộ)
./scripts/build_desktop_linux.sh
./scripts/open_desktop_linux.sh

# Windows (PowerShell, từ thư mục gốc repo)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_windows.ps1   # thêm -WithStt để tạo venv cục bộ
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_desktop_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_desktop_windows.ps1
```

Tauri không biên dịch chéo: mỗi bộ cài được tạo trên chính hệ điều hành của nó. Linux còn
cần thư viện hệ thống (`webkit2gtk`, `libsoup`, …); Windows cần MSVC C++ Build Tools + môi
trường chạy WebView2. Xem [`DESKTOP_APP.md`](DESKTOP_APP.md) cho danh sách yêu cầu đầy đủ.

---

## Chẩn đoán

```bash
./scripts/diagnose_env.sh
```

In OS/kiến trúc, phiên bản Python/uv/ffmpeg/node/cargo, sự tồn tại của từng venv và file
thực thi chính, các import quan trọng của TTS (`vieneu`, `llama_cpp`, `trafilatura`), sự
hiện diện của file Silero VAD bắt buộc, cấu hình desktop, và đường dẫn file cấu hình.

### Tài nguyên bắt buộc khi chạy: Silero VAD

STT nạp `WhisperLiveKit/whisperlivekit/silero_vad_models/silero_vad.onnx` (~2.3 MB,
opset-16) khi khởi động. File này **đã được commit** trong repo (một ngoại lệ trong
`.gitignore` so với quy tắc chung `*.onnx`), nên bản clone sạch luôn có sẵn. Nếu bị thiếu,
`bootstrap_macos.sh` và `run_stt_server.sh` sẽ **tự tải lại** từ đúng phiên bản upstream đã
ghim trước khi STT khởi động, và `run_stt_server.sh` sẽ báo lỗi rõ ràng nếu không tải được.
