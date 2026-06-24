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
    help="datn — one-command distribution (hides docker compose).",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Reconfigure after install.", no_args_is_help=False)
app.add_typer(config_app, name="config")


def _image_tag() -> str:
    return cfg.read_lock().get("image_tag", cfg.DEFAULT_IMAGE_TAG)


# ── init ─────────────────────────────────────────────────────────────────────
@app.command()
def init():
    """Wizard: configure LLM + embedding → write ~/.datn/.env + provider.lock."""
    # Nếu đã cấu hình trước đó (re-init), cần biết volumes có tồn tại không để
    # guard đổi dim hoạt động → đảm bảo Docker chạy. Lần đầu (chưa config) thì
    # bỏ qua, không bắt user bật Docker chỉ để nhập key.
    volumes = False
    if cfg.is_configured():
        if dr.ensure_docker(auto_start=True):
            volumes = cm.volumes_exist()
        else:
            console.print(
                "[yellow]⚠ Docker is not running — skipping volume check. "
                "If you change the embedding dim, run `datn reset` manually.[/yellow]"
            )
    wizard.run_init(image_tag=cfg.DEFAULT_IMAGE_TAG, volumes_exist=volumes)


# ── up ───────────────────────────────────────────────────────────────────────
@app.command()
def up():
    """Pull images + start the whole stack + wait until healthy."""
    if not cfg.is_configured():
        console.print("[red]Not configured yet. Run [bold]datn init[/bold] first.[/red]")
        raise typer.Exit(1)

    if not dr.run_doctor(require_config=True):
        console.print("[red]✗ doctor found a blocking issue. Fix it and try again.[/red]")
        raise typer.Exit(1)

    tag = _image_tag()
    cm.render_compose(tag)
    try:
        cm.pull()
        cm.up()
    except subprocess.CalledProcessError as e:
        console.print(
            f"[bold red]✗ docker compose failed (exit {e.returncode}).[/bold red]\n"
            f"  See the docker error above. Common causes:\n"
            f"    • Port in use (port is already allocated) → stop the app/stack using it; run [cyan]datn doctor[/cyan]\n"
            f"    • Image tag '{tag}' not on Docker Hub / network issue → check [cyan]docker pull {cfg.BACKEND_IMAGE}:{tag}[/cyan]\n"
            f"    • Container crashed → see [cyan]datn logs[/cyan]"
        )
        raise typer.Exit(1)
    if cm.wait_healthy():
        console.print(f"\n[bold green]✓ System is ready![/bold green] → {cfg.WEB_URL}")
        console.print("[dim]Open it with: datn open[/dim]")
    else:
        console.print("[red]Some services are not healthy. Check: datn logs[/red]")
        raise typer.Exit(1)


# ── down / open / logs ───────────────────────────────────────────────────────
@app.command()
def down():
    """Stop the stack (data is kept)."""
    cm.down()
    console.print("[green]✓ Stopped (data preserved).[/green]")


@app.command()
def open():  # noqa: A001 — tên lệnh user-facing
    """Open the web UI in your browser."""
    console.print(f"→ Opening {cfg.WEB_URL}")
    webbrowser.open(cfg.WEB_URL)


@app.command()
def logs(service: str = typer.Argument(None, help="Service name (e.g. agent-api). Empty = all.")):
    """Stream logs in realtime."""
    cm.logs(service)


# ── doctor ───────────────────────────────────────────────────────────────────
@app.command()
def doctor():
    """Check the environment (Docker, ports, config, dim...)."""
    require = cfg.is_configured()
    ok = dr.run_doctor(require_config=require)
    raise typer.Exit(0 if ok else 1)


# ── reset / update / uninstall ───────────────────────────────────────────────
@app.command()
def reset():
    """Delete all data (volumes) — required when the embedding dim changes."""
    if not Confirm.ask(
        "[bold red]Delete all RAG data + chat history?[/bold red]", default=False
    ):
        console.print("Cancelled.")
        return
    cm.reset()
    console.print("[green]✓ Volumes deleted. Run datn init + datn up to start over.[/green]")


@app.command()
def update(tag: str = typer.Option(None, "--tag", help="New image tag (e.g. v0.2.0).")):
    """Change image tag → re-render + pull + up again."""
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
        console.print(f"[bold red]✗ docker compose failed (exit {e.returncode}). Is tag '{new_tag}' pushed?[/bold red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ Updated to tag '{new_tag}'.[/green]")


@app.command()
def uninstall():
    """down -v + remove ~/.datn/ (pulled images are kept)."""
    if not Confirm.ask(
        "[bold red]Uninstall datn: delete data + config in ~/.datn?[/bold red]", default=False
    ):
        console.print("Cancelled.")
        return
    try:
        cm.reset()
    except Exception:
        pass
    shutil.rmtree(cfg.datn_home(), ignore_errors=True)
    console.print("[green]✓ Uninstalled. (Docker images remain — remove them manually if you want.)[/green]")


@app.command()
def version():
    """Print the CLI version."""
    console.print(f"datn-cli {__version__}")


# ── config sub-app ───────────────────────────────────────────────────────────
def _after_env_change(restart: bool = True):
    if restart and dr.docker_ready():
        cm.restart_backend()


@config_app.callback(invoke_without_command=True)
def config_main(ctx: typer.Context):
    """No argument → interactive menu."""
    if ctx.invoked_subcommand is not None:
        return
    if not cfg.is_configured():
        console.print("[red]No config yet. Run [bold]datn init[/bold].[/red]")
        raise typer.Exit(1)
    choice = Prompt.ask(
        "What do you want to change?",
        choices=["llm", "embedding", "tavily", "serpapi"],
        default="llm",
    )
    {"llm": config_llm, "embedding": config_embedding,
     "tavily": config_tavily, "serpapi": config_serpapi}[choice]()


@config_app.command("llm")
def config_llm():
    """Change LLM provider/model/key → restart backend."""
    env = cfg.read_env()
    env.update(wizard.prompt_llm())
    cfg.write_env(env)
    lock = cfg.read_lock()
    lock["llm_provider"] = env["LLM_PROVIDER"]
    cfg.write_lock(lock)
    console.print("[green]✓ LLM updated.[/green]")
    _after_env_change()


@config_app.command("embedding")
def config_embedding():
    """Change embedding → detect dim; if dim changes with existing data → require reset."""
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
            f"[bold red]✗ Changing dim {old_dim}→{new_dim} will break the collection. "
            f"Run datn reset first.[/bold red]"
        )
        raise typer.Exit(1)

    env = cfg.read_env()
    env.update(new)
    cfg.write_env(env)
    lock["embedding_provider"] = new["EMBEDDING_PROVIDER"]
    lock["embedding_dim"] = new_dim
    cfg.write_lock(lock)
    console.print("[green]✓ Embedding updated.[/green]")
    _after_env_change()


@config_app.command("tavily")
def config_tavily():
    """Change the Tavily API key."""
    env = cfg.read_env()
    env["TAVILY_API_KEY"] = Prompt.ask("Tavily API Key", default="", show_default=False)
    cfg.write_env(env)
    console.print("[green]✓ Tavily updated.[/green]")
    _after_env_change()


@config_app.command("serpapi")
def config_serpapi():
    """Change the SerpApi API key."""
    env = cfg.read_env()
    env["SERPAPI_API_KEY"] = Prompt.ask("SerpApi API Key", default="", show_default=False)
    cfg.write_env(env)
    console.print("[green]✓ SerpApi updated.[/green]")
    _after_env_change()


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)):
    """Quickly set one .env variable (for advanced users)."""
    env = cfg.read_env()
    env[key] = value
    cfg.write_env(env)
    console.print(f"[green]✓ {key} = {value}[/green]")
    _after_env_change()


if __name__ == "__main__":
    app()
