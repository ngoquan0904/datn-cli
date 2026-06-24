"""Render compose template + bọc các lệnh docker compose."""
from __future__ import annotations

import platform
import subprocess
import time
from importlib import resources

import httpx
from jinja2 import Template
from rich.console import Console

from . import config as cfg

console = Console()

_SYSTEM = platform.system()


# ── Render template ──────────────────────────────────────────────────────────
def _needs_host_gateway() -> bool:
    """Linux + selfhost URL trỏ host.docker.internal → cần extra_hosts."""
    if _SYSTEM != "Linux":
        return False
    env = cfg.read_env()
    urls = (env.get("LLM_BASE_URL", ""), env.get("EMBEDDING_BASE_URL", ""))
    return any("host.docker.internal" in u for u in urls)


def render_compose(image_tag: str) -> None:
    """Render docker-compose.yml vào ~/.datn/ từ template .j2."""
    tpl_text = (
        resources.files("datn_cli.templates")
        .joinpath("docker-compose.dist.yml.j2")
        .read_text(encoding="utf-8")
    )
    rendered = Template(tpl_text).render(
        backend_image=cfg.BACKEND_IMAGE,
        frontend_image=cfg.FRONTEND_IMAGE,
        image_tag=image_tag,
        env_file=str(cfg.env_path()),
        needs_host_gateway=_needs_host_gateway(),
    )
    cfg.compose_path().write_text(rendered, encoding="utf-8")


# ── docker compose wrappers ──────────────────────────────────────────────────
def _compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    # -p datn: pin project name → volume luôn có prefix 'datn_' (deterministic,
    # không phụ thuộc thư mục chứa compose file). volumes_exist() dựa vào điều này.
    cmd = ["docker", "compose", "-p", cfg.PROJECT_NAME, "-f", str(cfg.compose_path()), *args]
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def volumes_exist() -> bool:
    """Có volume của project 'datn' nào đang tồn tại không (để guard đổi dim).

    Vì _compose pin -p datn, volume thực tế có dạng 'datn_datn_<name>'. Lọc theo
    prefix project để không nhầm với volume của dự án khác.
    """
    try:
        r = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=10,
        )
        prefix = f"{cfg.PROJECT_NAME}_"
        return any(v.startswith(prefix) for v in r.stdout.split())
    except Exception:
        return False


def pull() -> None:
    console.print("[cyan]Pulling images from Docker Hub...[/cyan]")
    console.print("[dim]⚠ First run can take a few minutes (~2-4GB).[/dim]")
    _compose("pull")


def up() -> None:
    console.print("[cyan]Starting services...[/cyan]")
    _compose("up", "-d")


def down() -> None:
    _compose("down")


def reset() -> None:
    """down -v — xoá volumes (mất data RAG + chat history)."""
    _compose("down", "-v")


def logs(service: str | None = None) -> None:
    args = ["logs", "-f"]
    if service:
        args.append(service)
    _compose(*args, check=False)


# ── Health polling ───────────────────────────────────────────────────────────
def wait_healthy(timeout: int = 120) -> bool:
    """Poll agent-api `/` + qdrant readiness tới khi healthy hoặc hết giờ."""
    console.print("[cyan]Waiting for services to become healthy...[/cyan]")
    # Poll /health (200) — KHÔNG dùng "/" vì api.py không có route đó (trả 404,
    # sẽ false-positive). /health do api.py expose riêng cho mục đích này.
    api_url = f"http://localhost:{cfg.PORTS['agent-api']}/health"
    qdrant_url = f"http://localhost:{cfg.PORTS['qdrant']}/readyz"

    deadline = time.time() + timeout
    api_ok = qdrant_ok = False
    while time.time() < deadline:
        if not qdrant_ok:
            try:
                qdrant_ok = httpx.get(qdrant_url, timeout=3).status_code == 200
                if qdrant_ok:
                    console.print("[green]✓[/green] qdrant")
            except Exception:
                pass
        if not api_ok:
            try:
                api_ok = httpx.get(api_url, timeout=3).status_code == 200
                if api_ok:
                    console.print("[green]✓[/green] agent-api")
            except Exception:
                pass
        if api_ok and qdrant_ok:
            return True
        time.sleep(3)

    if not qdrant_ok:
        console.print("[red]✗ qdrant is not healthy. See: datn logs qdrant[/red]")
    if not api_ok:
        console.print("[red]✗ agent-api is not healthy. See: datn logs agent-api[/red]")
    return False


def restart_backend() -> None:
    """Restart agent-api + mcp-server để nạp .env mới (không mất data)."""
    console.print("[cyan]Restarting backend to load new config...[/cyan]")
    _compose("up", "-d", "--force-recreate", "agent-api", "mcp-server")
