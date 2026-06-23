"""Đường dẫn + đọc/ghi ~/.datn/.env và provider.lock."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

# Image tag mặc định — phải khớp tag đã push lên Docker Hub (xem notes.md mục C/F).
DEFAULT_IMAGE_TAG = "latest"

# Compose project name — pin để volume naming deterministic (xem compose.py).
PROJECT_NAME = "datn"

# Docker Hub images
BACKEND_IMAGE = "ngoquan0904/datn-backend"
FRONTEND_IMAGE = "ngoquan0904/datn-frontend"

# Cổng dùng trên host (để doctor kiểm tra + in URL)
PORTS = {
    "frontend": 5173,
    "agent-api": 5000,
    "mcp-server": 8000,
    "postgres": 5432,
    "qdrant": 6333,
    "minio": 9000,
    "minio-console": 9001,
}

WEB_URL = f"http://localhost:{PORTS['frontend']}"

# Field bắt buộc trong .env để hệ thống chạy
REQUIRED_ENV_FIELDS = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
]


def datn_home() -> Path:
    """Thư mục cấu hình ~/.datn (tạo nếu chưa có)."""
    home = Path(os.path.expanduser("~")) / ".datn"
    home.mkdir(parents=True, exist_ok=True)
    return home


def env_path() -> Path:
    return datn_home() / ".env"


def lock_path() -> Path:
    return datn_home() / "provider.lock"


def compose_path() -> Path:
    return datn_home() / "docker-compose.yml"


# ── .env IO ─────────────────────────────────────────────────────────────────
def read_env() -> dict[str, str]:
    """Đọc .env thành dict (bỏ qua comment/dòng trống)."""
    path = env_path()
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        data[key.strip()] = val.strip()
    return data


def write_env(data: dict[str, str]) -> None:
    """Ghi .env theo thứ tự khối + chmod 600 (chỉ owner đọc — không lộ key)."""
    order = [
        ("# === LLM ===", None),
        (None, "LLM_PROVIDER"),
        (None, "LLM_API_KEY"),
        (None, "LLM_MODEL"),
        (None, "LLM_BASE_URL"),
        (None, "LLM_DISABLE_THINKING"),
        ("# === EMBEDDING ===", None),
        (None, "EMBEDDING_PROVIDER"),
        (None, "EMBEDDING_API_KEY"),
        (None, "EMBEDDING_MODEL"),
        (None, "EMBEDDING_BASE_URL"),
        (None, "EMBEDDING_DIM"),
        ("# === Sub-agents (optional) ===", None),
        (None, "TAVILY_API_KEY"),
        (None, "SERPAPI_API_KEY"),
    ]
    lines: list[str] = []
    written: set[str] = set()
    for comment, key in order:
        if comment:
            if lines:
                lines.append("")
            lines.append(comment)
        elif key is not None:
            lines.append(f"{key}={data.get(key, '')}")
            written.add(key)
    # Giữ lại field lạ (nếu user thêm tay) ở cuối
    extra = [k for k in data if k not in written]
    if extra:
        lines.append("")
        lines.append("# === Extra ===")
        for k in extra:
            lines.append(f"{k}={data[k]}")

    path = env_path()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass  # Windows có thể không hỗ trợ chmod đầy đủ — bỏ qua


# ── provider.lock IO ─────────────────────────────────────────────────────────
def read_lock() -> dict:
    path = lock_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_lock(data: dict) -> None:
    lock_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_configured() -> bool:
    return env_path().exists()
