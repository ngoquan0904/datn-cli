"""Xác định embedding dimension.

- Provider có model phổ biến (openai/gemini/openrouter) → tra bảng tĩnh.
- selfhost → gửi 1 test embed call (OpenAI schema) đo len vector thực tế.

KHÔNG import backend code (CLI là package độc lập). Bảng dim được nhân bản
từ infrastructure/model.py:get_embedding_dimension — giữ đồng bộ thủ công.
"""
from __future__ import annotations

import httpx

# Mirror của infrastructure/model.py — cập nhật cùng lúc nếu backend đổi.
_DIMENSION_MAP = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "google/gemini-embedding-001": 3072,
    "embedding-001": 3072,
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
    "openai/text-embedding-ada-002": 1536,
}


class DimensionDetectError(RuntimeError):
    """Không xác định được dim (endpoint sai / key sai / schema lạ)."""


def known_dimension(model: str) -> int | None:
    """Tra dim từ bảng tĩnh. None nếu không biết (vd model selfhost lạ)."""
    if model in _DIMENSION_MAP:
        return _DIMENSION_MAP[model]
    for key, dim in _DIMENSION_MAP.items():
        if key in model:
            return dim
    return None


def detect_selfhost_dimension(base_url: str, model: str, api_key: str = "") -> int:
    """Gửi test embed call tới endpoint OpenAI-compatible, đo dim.

    Raise DimensionDetectError với thông điệp rõ ràng nếu thất bại.
    """
    url = base_url.rstrip("/") + "/embeddings"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.post(
            url,
            headers=headers,
            json={"model": model, "input": "test"},
            timeout=30.0,
        )
    except httpx.ConnectError as e:
        raise DimensionDetectError(
            f"Không kết nối được tới {url}. Kiểm tra base_url + endpoint đang chạy.\n  ({e})"
        )
    except httpx.TimeoutException:
        raise DimensionDetectError(f"Timeout khi gọi {url} (30s). Endpoint phản hồi quá chậm?")

    if resp.status_code == 401:
        raise DimensionDetectError(f"401 Unauthorized — sai API key cho {url}.")
    if resp.status_code == 404:
        raise DimensionDetectError(
            f"404 Not Found — {url} không tồn tại. base_url có đúng dạng "
            f"'http://host:port/v1' không?"
        )
    if resp.status_code >= 400:
        raise DimensionDetectError(
            f"HTTP {resp.status_code} từ {url}: {resp.text[:200]}"
        )

    try:
        data = resp.json()
        embedding = data["data"][0]["embedding"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise DimensionDetectError(
            f"Response không đúng OpenAI schema (cần data[0].embedding). "
            f"Nhận: {resp.text[:200]}"
        )

    if not isinstance(embedding, list) or not embedding:
        raise DimensionDetectError("embedding rỗng hoặc không phải list.")

    return len(embedding)
