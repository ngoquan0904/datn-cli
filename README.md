# datn-cli

Cài hệ trợ lý đa tác tử **datn** bằng 1 lệnh — CLI ẩn docker compose. Không cần source code.

## Cài đặt (1 lệnh)

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/ngoquan0904/datn-cli/main/install.sh | sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/ngoquan0904/datn-cli/main/install.ps1 | iex
```

Script tự cài: Python 3.9+, pipx, Docker (Linux) / WSL2+Docker Desktop (Windows), rồi `datn-cli`.

## Chạy

```bash
datn init     # nhập API key cho LLM + embedding (chọn provider)
datn up       # pull images + khởi động + chờ healthy (lần đầu mất vài phút)
datn open     # mở http://localhost:5173
```

Trong `datn init` bạn chỉ cần **nhập API key**. Embedding dimension tự dò.
Gmail/Calendar cấu hình sau trong **Settings** của web UI (upload `client_secret.json`).

## Lệnh hay dùng

| Lệnh | Việc |
|---|---|
| `datn doctor` | Kiểm tra Docker, ports, cấu hình |
| `datn logs agent-api` | Xem log 1 service |
| `datn down` | Dừng (giữ data) |
| `datn config llm` | Đổi LLM provider/model/key |
| `datn config embedding` | Đổi embedding (đổi dim → cần `datn reset`) |
| `datn update --tag vX.Y.Z` | Cập nhật phiên bản image |
| `datn reset` | Xoá data (RAG + chat history) |
| `datn uninstall` | Gỡ data + cấu hình |

## Self-host LLM/Embedding

Chọn provider `selfhost` trong `datn init`, nhập `base_url` (OpenAI-compatible, vd vLLM/llama.cpp/Ollama).
`localhost`/`127.0.0.1` tự đổi sang `host.docker.internal` để container gọi được host.

## Troubleshooting

| Triệu chứng | Cách xử lý |
|---|---|
| **Docker chưa cài** (macOS) | Tải Docker Desktop: https://www.docker.com/products/docker-desktop/ — script không tự cài được file .dmg |
| **`permission denied` Docker (Linux)** | Đăng xuất + đăng nhập lại 1 lần (đã thêm bạn vào nhóm `docker`). Kiểm tra: `datn doctor` |
| **WSL2 chưa có (Windows)** | Chạy lại `install.ps1` sau khi **khởi động lại máy** (script đã chạy `wsl --install`) |
| **Port bận** (5000/8000/5173/5432/6333/9000) | `datn doctor` báo port + tiến trình. Đóng app chiếm port hoặc dừng stack cũ |
| **Đĩa đầy khi pull** | Cần ~5GB trống cho images. Dọn ổ rồi `datn up` lại |
| **Đổi embedding → lỗi dim** | `datn reset` (xoá data) → `datn init` → `datn up`. Đổi dim làm vỡ Qdrant collection |
| **News/Travel báo "chưa cấu hình"** | Thiếu Tavily/SerpApi key — chạy `datn config tavily` / `datn config serpapi` (optional) |
| **Image pull lỗi / tag không tồn tại** | Kiểm tra tag trong `~/.datn/provider.lock`; thử `datn update --tag latest` |

## Yêu cầu hệ thống
- RAM ≥ 4GB (Qdrant + Postgres + backend).
- Đĩa trống ≥ 5GB (images ~2-4GB).
- Kết nối Internet (pull images + gọi LLM API).
