"""Wizard `datn init` + reconfigure `datn config`.

Ghi ~/.datn/.env (chmod 600) + provider.lock. Embedding dim tự detect — KHÔNG
hỏi user nhập tay. localhost trong selfhost URL được auto-replace để dùng được
từ trong container.
"""
from __future__ import annotations

import re

from rich.console import Console
from rich.prompt import Confirm, Prompt

from . import config as cfg
from .embed_detect import (
    DimensionDetectError,
    detect_selfhost_dimension,
    known_dimension,
)

console = Console()

LLM_PROVIDERS = ["openai", "openrouter", "gemini", "selfhost"]
EMBEDDING_PROVIDERS = ["openai", "gemini", "openrouter", "selfhost"]

# Gợi ý model mặc định theo provider
_LLM_DEFAULTS = {
    "openai": "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "selfhost": "",
}
_EMBEDDING_DEFAULTS = {
    "openai": "text-embedding-3-small",
    "gemini": "google/gemini-embedding-001",
    "openrouter": "google/gemini-embedding-001",
    "selfhost": "",
}


def _fix_localhost(url: str) -> str:
    """localhost/127.0.0.1 → host.docker.internal (để container gọi được host)."""
    if not url:
        return url
    new = re.sub(r"\b(localhost|127\.0\.0\.1)\b", "host.docker.internal", url)
    if new != url:
        console.print(
            f"  [yellow]↪ Đổi '{url}' → '{new}' (để chạy được từ trong container)[/yellow]"
        )
    return new


# ── LLM section ──────────────────────────────────────────────────────────────
def prompt_llm() -> dict[str, str]:
    console.print("\n[bold cyan]── LLM Provider ──[/bold cyan]")
    provider = Prompt.ask("  Provider", choices=LLM_PROVIDERS, default="openai")

    if provider == "selfhost":
        base_url = ""
        while not base_url:
            base_url = _fix_localhost(Prompt.ask("  Base URL (vd http://host:8000/v1)").strip())
            if not base_url:
                console.print("  [red]Base URL bắt buộc cho selfhost.[/red]")
        api_key = Prompt.ask("  API Key (Enter nếu không cần)", default="", show_default=False)
        model = ""
        while not model:
            model = Prompt.ask("  Model").strip()
        # Model reasoning (Qwen/VNPT/DeepSeek-distill) cần tắt thinking để xuất
        # đúng XML structured — nếu không, chuỗi suy luận rò vào output làm hỏng flow.
        disable_thinking = Confirm.ask(
            "  Model dạng reasoning (Qwen/VNPT...) — tắt chế độ thinking?", default=False
        )
    else:
        base_url = ""
        api_key = Prompt.ask("  API Key", password=True)
        model = Prompt.ask("  Model", default=_LLM_DEFAULTS[provider])
        disable_thinking = False

    return {
        "LLM_PROVIDER": provider,
        "LLM_API_KEY": api_key,
        "LLM_MODEL": model,
        "LLM_BASE_URL": base_url,
        "LLM_DISABLE_THINKING": "true" if disable_thinking else "",
    }


# ── Embedding section (dim auto-detect) ──────────────────────────────────────
def prompt_embedding() -> dict[str, str]:
    console.print("\n[bold cyan]── Embedding Provider ──[/bold cyan]")
    provider = Prompt.ask("  Provider", choices=EMBEDDING_PROVIDERS, default="openai")

    if provider == "selfhost":
        base_url = _fix_localhost(Prompt.ask("  Base URL (vd http://host:8080/v1)"))
        api_key = Prompt.ask("  API Key (Enter nếu không cần)", default="", show_default=False)
        model = Prompt.ask("  Model")
        console.print("  [dim]→ Đang kiểm tra endpoint + đo dimension...[/dim]")
        dim = detect_selfhost_dimension(base_url, model, api_key)  # raise nếu lỗi
        console.print(f"  [green]✓ Kết nối OK — dim = {dim}[/green]")
    else:
        base_url = ""
        api_key = Prompt.ask("  API Key", password=True)
        model = Prompt.ask("  Model", default=_EMBEDDING_DEFAULTS[provider])
        dim = known_dimension(model)
        if dim is None:
            console.print(
                f"  [yellow]⚠ Không rõ dim của '{model}', mặc định 1536. "
                f"Nếu sai, embedding sẽ vỡ collection.[/yellow]"
            )
            dim = 1536
        else:
            console.print(f"  [green]✓ dim = {dim}[/green]")

    return {
        "EMBEDDING_PROVIDER": provider,
        "EMBEDDING_API_KEY": api_key,
        "EMBEDDING_MODEL": model,
        "EMBEDDING_BASE_URL": base_url,
        "EMBEDDING_DIM": str(dim),
    }


# ── Optional sub-agents ──────────────────────────────────────────────────────
def prompt_optional() -> dict[str, str]:
    console.print("\n[bold cyan]── Optional (Enter để bỏ qua) ──[/bold cyan]")
    tavily = Prompt.ask("  Tavily API Key (News agent)", default="", show_default=False)
    serpapi = Prompt.ask("  SerpApi API Key (Travel agent)", default="", show_default=False)
    unsplash = Prompt.ask("  Unsplash Access Key (ảnh cho slide)", default="", show_default=False)
    return {
        "TAVILY_API_KEY": tavily,
        "SERPAPI_API_KEY": serpapi,
        "UNSPLASH_ACCESS_KEY": unsplash,
    }


# ── Orchestration ────────────────────────────────────────────────────────────
def run_init(image_tag: str, volumes_exist: bool) -> bool:
    """Chạy wizard đầy đủ. Trả False nếu user huỷ / bị guard chặn."""
    console.print("[bold]=== datn init ===[/bold]")

    if cfg.is_configured():
        if not Confirm.ask(
            "[yellow]Config đã tồn tại (~/.datn/.env). Ghi đè?[/yellow]", default=False
        ):
            console.print("Đã huỷ.")
            return False

    old_lock = cfg.read_lock()

    try:
        llm = prompt_llm()
        embedding = prompt_embedding()
    except DimensionDetectError as e:
        console.print(f"\n[bold red]✗ Lỗi cấu hình embedding:[/bold red]\n  {e}")
        console.print("[red]Không ghi .env. Sửa lại endpoint/key rồi chạy `datn init` lại.[/red]")
        return False

    optional = prompt_optional()

    new_dim = int(embedding["EMBEDDING_DIM"])
    old_dim = old_lock.get("embedding_dim")

    # Guard đổi dim: dim mới ≠ dim cũ VÀ volumes đã có data → chặn, bắt reset
    if old_dim is not None and old_dim != new_dim and volumes_exist:
        console.print(
            f"\n[bold red]✗ Đổi embedding dimension {old_dim} → {new_dim} "
            f"sẽ vỡ Qdrant collection![/bold red]"
        )
        console.print(
            "[red]Data RAG hiện tại dùng dim cũ. Chạy [bold]datn reset[/bold] "
            "(xoá data) trước, rồi [bold]datn init[/bold] lại.[/red]"
        )
        return False

    env_data = {**llm, **embedding, **optional}
    cfg.write_env(env_data)
    cfg.write_lock({
        "llm_provider": llm["LLM_PROVIDER"],
        "embedding_provider": embedding["EMBEDDING_PROVIDER"],
        "embedding_dim": new_dim,
        "image_tag": image_tag,
    })

    console.print(f"\n[green]✓ Đã ghi {cfg.env_path()} (chmod 600)[/green]")
    console.print(f"[green]✓ Đã ghi {cfg.lock_path()}[/green]")
    console.print(
        "\n[dim]💡 Gmail/Calendar: cấu hình trong Settings sau khi `datn up` "
        "(upload client_secret.json + Authorize).[/dim]"
    )
    console.print("\n[bold]Tiếp theo:[/bold] datn up")
    return True
