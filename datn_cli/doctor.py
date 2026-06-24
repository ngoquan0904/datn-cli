"""`datn doctor` — kiểm tra môi trường trước khi `up`.

Thứ tự: dừng ở lỗi blocking, tiếp tục với warning. Tự khởi động Docker nếu
daemon chưa chạy (Mac/Linux/Windows).
"""
from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import time

from rich.console import Console

from . import config as cfg

console = Console()

_SYSTEM = platform.system()  # "Linux" | "Darwin" | "Windows"


# ── Docker daemon ────────────────────────────────────────────────────────────
def docker_ready() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_installed() -> bool:
    return shutil.which("docker") is not None


def _start_docker_daemon() -> None:
    """Khởi động Docker theo platform (không chờ — caller poll riêng)."""
    try:
        if _SYSTEM == "Darwin":
            subprocess.Popen(["open", "-a", "Docker"])
        elif _SYSTEM == "Linux":
            # sudo -n: non-interactive. Nếu cần password mà không có TTY → fail ngay
            # thay vì treo 30s. Khi đó in hướng dẫn thủ công.
            r = subprocess.run(
                ["sudo", "-n", "systemctl", "start", "docker"],
                capture_output=True, timeout=15,
            )
            if r.returncode != 0:
                console.print(
                    "  [yellow]Could not auto-start (needs privileges). Run manually:[/yellow] "
                    "[cyan]sudo systemctl start docker[/cyan]"
                )
        elif _SYSTEM == "Windows":
            subprocess.Popen(
                ['C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'],
                shell=True,
            )
    except Exception:
        pass


def ensure_docker(auto_start: bool = True) -> bool:
    """Đảm bảo Docker chạy. Tự start + chờ tối đa 60s nếu cần."""
    if docker_ready():
        return True
    if not docker_installed():
        console.print("[bold red]✗ Docker is not installed.[/bold red]")
        if _SYSTEM == "Linux":
            console.print("  Install: [cyan]curl -fsSL https://get.docker.com | sh[/cyan]")
        else:
            console.print("  Download Docker Desktop: [cyan]https://www.docker.com/products/docker-desktop/[/cyan]")
        return False
    if not auto_start:
        console.print("[red]✗ Docker is not running.[/red]")
        return False

    console.print("[yellow]⚠ Docker is not running — starting it...[/yellow]")
    _start_docker_daemon()
    for _ in range(30):  # 30 × 2s = 60s
        if docker_ready():
            console.print("[green]✓ Docker is ready[/green]")
            return True
        time.sleep(2)
    console.print("[red]✗ Docker didn't start within 60s. Open Docker Desktop manually.[/red]")
    return False


# ── Linux docker group ───────────────────────────────────────────────────────
def _check_docker_group() -> tuple[bool, str]:
    if _SYSTEM != "Linux":
        return True, ""
    try:
        groups = subprocess.run(["id", "-nG"], capture_output=True, text=True, timeout=5).stdout
        if "docker" in groups.split():
            return True, ""
        return False, (
            "User is not in the 'docker' group. Run:\n"
            "    [cyan]sudo usermod -aG docker $USER[/cyan]\n"
            "  then [bold]log out and back in[/bold] (for the new group to take effect)."
        )
    except Exception:
        return True, ""


# ── Disk / RAM ───────────────────────────────────────────────────────────────
def _check_disk() -> tuple[bool, str]:
    try:
        free_gb = shutil.disk_usage("/").free / (1024 ** 3)
        if free_gb < 5:
            return False, f"Only {free_gb:.1f}GB free (need ~5GB for images)."
        return True, ""
    except Exception:
        return True, ""


def _check_ram() -> tuple[bool, str]:
    # Đọc /proc/meminfo trên Linux; bỏ qua trên Mac/Windows (không có psutil dep).
    if _SYSTEM != "Linux":
        return True, ""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    gb = kb / (1024 ** 2)
                    if gb < 2:
                        return False, f"Available RAM {gb:.1f}GB (<2GB) — Qdrant+Postgres may be heavy."
                    return True, ""
    except Exception:
        pass
    return True, ""


# ── Ports ────────────────────────────────────────────────────────────────────
def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _check_ports() -> tuple[bool, str]:
    busy = [name + f":{p}" for name, p in cfg.PORTS.items() if _port_in_use(p)]
    if busy:
        return False, "Ports in use: " + ", ".join(busy) + " (stop the app using them, or change ports)."
    return True, ""


# ── .env / dim ───────────────────────────────────────────────────────────────
def _check_env() -> tuple[bool, str]:
    if not cfg.env_path().exists():
        return False, "No ~/.datn/.env yet. Run [bold]datn init[/bold] first."
    data = cfg.read_env()
    missing = [k for k in cfg.REQUIRED_ENV_FIELDS if not data.get(k)]
    if missing:
        return False, "Missing required fields: " + ", ".join(missing) + ". Run [bold]datn init[/bold]."
    return True, ""


def _check_dim_lock() -> tuple[bool, str]:
    data = cfg.read_env()
    lock = cfg.read_lock()
    env_dim = data.get("EMBEDDING_DIM")
    lock_dim = lock.get("embedding_dim")
    if env_dim and lock_dim is not None and str(lock_dim) != str(env_dim):
        return False, (
            f"embedding_dim mismatch: .env={env_dim} vs lock={lock_dim}. "
            "Run [bold]datn reset[/bold] then [bold]datn init[/bold]."
        )
    return True, ""


def _check_wsl() -> tuple[bool, str]:
    if _SYSTEM != "Windows":
        return True, ""
    try:
        r = subprocess.run(["wsl", "--status"], capture_output=True, timeout=10)
        if r.returncode != 0:
            return False, "WSL2 is not ready. Run [cyan]wsl --install[/cyan] (needs a reboot)."
        return True, ""
    except Exception:
        return False, "Could not check WSL. Docker Desktop requires WSL2."


# ── Orchestration ────────────────────────────────────────────────────────────
def run_doctor(require_config: bool = True, auto_start_docker: bool = True) -> bool:
    """Chạy toàn bộ check. Trả True nếu không có lỗi blocking."""
    console.print("[bold]=== datn doctor ===[/bold]")
    ok = True

    # 1. Docker (blocking, có auto-start)
    if ensure_docker(auto_start=auto_start_docker):
        console.print("[green]✓[/green] Docker daemon")
    else:
        return False  # không có Docker thì các check sau vô nghĩa

    # 2-N: warning/blocking checks
    checks = [
        ("docker group", _check_docker_group(), True),
        ("disk space", _check_disk(), False),
        ("RAM", _check_ram(), False),
        ("ports", _check_ports(), False),
        ("WSL2", _check_wsl(), True),
    ]
    if require_config:
        checks += [
            ("config (.env)", _check_env(), True),
            ("embedding dim lock", _check_dim_lock(), True),
        ]

    for name, (passed, msg), blocking in checks:
        if passed:
            console.print(f"[green]✓[/green] {name}")
        elif blocking:
            console.print(f"[bold red]✗[/bold red] {name}: {msg}")
            ok = False
        else:
            console.print(f"[yellow]⚠[/yellow] {name}: {msg}")

    return ok
