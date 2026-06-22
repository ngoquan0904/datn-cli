"""datn — CLI che giấu docker compose cho hệ multi-agent assistant."""
from __future__ import annotations

import shutil
import subprocess
import webbrowser

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from . import __version__
from . import compose as cm
from . import config as cfg
from . import doctor as dr
from . import wizard

console = Console()
app = typer.Typer(
    help="datn — one-command distribution (ẩn docker compose).",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Cấu hình lại sau khi đã chạy.", no_args_is_help=False)
app.add_typer(config_app, name="config")


def _image_tag() -> str:
    return cfg.read_lock().get("image_tag", cfg.DEFAULT_IMAGE_TAG)


# ── init ─────────────────────────────────────────────────────────────────────
@app.command()
def init():
    """Wizard cấu hình LLM + embedding → ghi ~/.datn/.env + provider.lock."""
    # Nếu đã cấu hình trước đó (re-init), cần biết volumes có tồn tại không để
    # guard đổi dim hoạt động → đảm bảo Docker chạy. Lần đầu (chưa config) thì
    # bỏ qua, không bắt user bật Docker chỉ để nhập key.
    volumes = False
    if cfg.is_configured():
        if dr.ensure_docker(auto_start=True):
            volumes = cm.volumes_exist()
        else:
            console.print(
                "[yellow]⚠ Docker không chạy — bỏ qua kiểm tra volume. "
                "Nếu đổi embedding dim, hãy chạy `datn reset` thủ công.[/yellow]"
            )
    wizard.run_init(image_tag=cfg.DEFAULT_IMAGE_TAG, volumes_exist=volumes)


# ── up ───────────────────────────────────────────────────────────────────────
@app.command()
def up():
    """Pull images + khởi động toàn bộ stack + chờ healthy."""
    if not cfg.is_configured():
        console.print("[red]Chưa cấu hình. Chạy [bold]datn init[/bold] trước.[/red]")
        raise typer.Exit(1)

    if not dr.run_doctor(require_config=True):
        console.print("[red]✗ doctor phát hiện lỗi blocking. Sửa rồi chạy lại.[/red]")
        raise typer.Exit(1)

    tag = _image_tag()
    cm.render_compose(tag)
    try:
        cm.pull()
        cm.up()
    except subprocess.CalledProcessError as e:
        console.print(
            f"[bold red]✗ docker compose lỗi (exit {e.returncode}).[/bold red]\n"
            f"  Thường gặp: image tag '{tag}' chưa push lên Docker Hub, hoặc mạng lỗi.\n"
            f"  Kiểm tra: docker login / tag trong ~/.datn/provider.lock."
        )
        raise typer.Exit(1)
    if cm.wait_healthy():
        console.print(f"\n[bold green]✓ Hệ thống sẵn sàng![/bold green] → {cfg.WEB_URL}")
        console.print("[dim]Mở bằng: datn open[/dim]")
    else:
        console.print("[red]Một số service chưa healthy. Kiểm tra: datn logs[/red]")
        raise typer.Exit(1)


# ── down / open / logs ───────────────────────────────────────────────────────
@app.command()
def down():
    """Dừng stack (giữ data)."""
    cm.down()
    console.print("[green]✓ Đã dừng (data được giữ).[/green]")


@app.command()
def open():  # noqa: A001 — tên lệnh user-facing
    """Mở web UI trên trình duyệt."""
    console.print(f"→ Mở {cfg.WEB_URL}")
    webbrowser.open(cfg.WEB_URL)


@app.command()
def logs(service: str = typer.Argument(None, help="Tên service (vd agent-api). Bỏ trống = tất cả.")):
    """Xem logs realtime."""
    cm.logs(service)


# ── doctor ───────────────────────────────────────────────────────────────────
@app.command()
def doctor():
    """Kiểm tra môi trường (Docker, ports, config, dim...)."""
    require = cfg.is_configured()
    ok = dr.run_doctor(require_config=require)
    raise typer.Exit(0 if ok else 1)


# ── reset / update / uninstall ───────────────────────────────────────────────
@app.command()
def reset():
    """Xoá toàn bộ data (volumes) — bắt buộc khi đổi embedding dim."""
    if not Confirm.ask(
        "[bold red]Xoá toàn bộ data RAG + chat history?[/bold red]", default=False
    ):
        console.print("Đã huỷ.")
        return
    cm.reset()
    console.print("[green]✓ Đã xoá volumes. Chạy datn init + datn up để bắt đầu lại.[/green]")


@app.command()
def update(tag: str = typer.Option(None, "--tag", help="Image tag mới (vd v0.2.0).")):
    """Đổi image tag → re-render + pull + up lại."""
    lock = cfg.read_lock()
    if tag:
        lock["image_tag"] = tag
        cfg.write_lock(lock)
    new_tag = lock.get("image_tag", cfg.DEFAULT_IMAGE_TAG)
    cm.render_compose(new_tag)
    try:
        cm.pull()
        cm.up()
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]✗ docker compose lỗi (exit {e.returncode}). Tag '{new_tag}' đã push chưa?[/bold red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ Đã cập nhật lên tag '{new_tag}'.[/green]")


@app.command()
def uninstall():
    """down -v + xoá ~/.datn/ (giữ images đã pull)."""
    if not Confirm.ask(
        "[bold red]Gỡ datn: xoá data + cấu hình ~/.datn?[/bold red]", default=False
    ):
        console.print("Đã huỷ.")
        return
    try:
        cm.reset()
    except Exception:
        pass
    shutil.rmtree(cfg.datn_home(), ignore_errors=True)
    console.print("[green]✓ Đã gỡ. (Images Docker vẫn còn — xoá tay nếu muốn.)[/green]")


@app.command()
def version():
    """In version CLI."""
    console.print(f"datn-cli {__version__}")


# ── config sub-app ───────────────────────────────────────────────────────────
def _after_env_change(restart: bool = True):
    if restart and dr.docker_ready():
        cm.restart_backend()


@config_app.callback(invoke_without_command=True)
def config_main(ctx: typer.Context):
    """Không tham số → menu interactive."""
    if ctx.invoked_subcommand is not None:
        return
    if not cfg.is_configured():
        console.print("[red]Chưa có config. Chạy [bold]datn init[/bold].[/red]")
        raise typer.Exit(1)
    choice = Prompt.ask(
        "Sửa mục nào?",
        choices=["llm", "embedding", "tavily", "serpapi"],
        default="llm",
    )
    {"llm": config_llm, "embedding": config_embedding,
     "tavily": config_tavily, "serpapi": config_serpapi}[choice]()


@config_app.command("llm")
def config_llm():
    """Đổi LLM provider/model/key → restart backend."""
    env = cfg.read_env()
    env.update(wizard.prompt_llm())
    cfg.write_env(env)
    lock = cfg.read_lock()
    lock["llm_provider"] = env["LLM_PROVIDER"]
    cfg.write_lock(lock)
    console.print("[green]✓ Đã cập nhật LLM.[/green]")
    _after_env_change()


@config_app.command("embedding")
def config_embedding():
    """Đổi embedding → detect dim; nếu đổi dim + có data → bắt reset."""
    try:
        new = wizard.prompt_embedding()
    except wizard.DimensionDetectError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    lock = cfg.read_lock()
    old_dim = lock.get("embedding_dim")
    new_dim = int(new["EMBEDDING_DIM"])
    if old_dim is not None and old_dim != new_dim and cm.volumes_exist():
        console.print(
            f"[bold red]✗ Đổi dim {old_dim}→{new_dim} sẽ vỡ collection. "
            f"Chạy datn reset trước.[/bold red]"
        )
        raise typer.Exit(1)

    env = cfg.read_env()
    env.update(new)
    cfg.write_env(env)
    lock["embedding_provider"] = new["EMBEDDING_PROVIDER"]
    lock["embedding_dim"] = new_dim
    cfg.write_lock(lock)
    console.print("[green]✓ Đã cập nhật embedding.[/green]")
    _after_env_change()


@config_app.command("tavily")
def config_tavily():
    """Đổi Tavily API key."""
    env = cfg.read_env()
    env["TAVILY_API_KEY"] = Prompt.ask("Tavily API Key", default="", show_default=False)
    cfg.write_env(env)
    console.print("[green]✓ Đã cập nhật Tavily.[/green]")
    _after_env_change()


@config_app.command("serpapi")
def config_serpapi():
    """Đổi SerpApi API key."""
    env = cfg.read_env()
    env["SERPAPI_API_KEY"] = Prompt.ask("SerpApi API Key", default="", show_default=False)
    cfg.write_env(env)
    console.print("[green]✓ Đã cập nhật SerpApi.[/green]")
    _after_env_change()


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)):
    """Sửa nhanh 1 biến .env (cho người rành env)."""
    env = cfg.read_env()
    env[key] = value
    cfg.write_env(env)
    console.print(f"[green]✓ {key} = {value}[/green]")
    _after_env_change()


if __name__ == "__main__":
    app()
