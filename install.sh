#!/usr/bin/env sh
# datn-cli bootstrap installer (macOS / Linux)
#
#   curl -fsSL https://raw.githubusercontent.com/ngoquan0904/datn-cli/main/install.sh | sh
#
# Tự cài: Python 3.9+, pipx, Docker (Linux), rồi `pipx install datn-cli`.
# Idempotent — chạy lại an toàn. Dừng ngay khi gặp lỗi không tự xử lý được.
set -e

DATN_PKG="datn-cli"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { printf "${CYAN}%s${NC}\n" "$1"; }
ok()    { printf "${GREEN}✓ %s${NC}\n" "$1"; }
warn()  { printf "${YELLOW}⚠ %s${NC}\n" "$1"; }
err()   { printf "${RED}✗ %s${NC}\n" "$1"; }

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="mac" ;;
  Linux)  PLATFORM="linux" ;;
  *) err "Hệ điều hành không hỗ trợ: $OS (chỉ macOS/Linux). Windows dùng install.ps1."; exit 1 ;;
esac

has() { command -v "$1" >/dev/null 2>&1; }

# ── 1. Python 3.9+ ───────────────────────────────────────────────────────────
python_ok() {
  has python3 || return 1
  python3 - <<'PY' >/dev/null 2>&1 || return 1
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY
}

install_python() {
  info "[1/4] Cài Python 3..."
  if [ "$PLATFORM" = "mac" ]; then
    if has brew; then
      brew install python
    else
      err "Chưa có Homebrew. Cài Python tay: https://www.python.org/downloads/ rồi chạy lại."
      exit 1
    fi
  else
    # Linux — detect package manager
    if has apt-get; then
      sudo apt-get update -y && sudo apt-get install -y python3 python3-pip python3-venv
    elif has dnf; then
      sudo dnf install -y python3 python3-pip
    elif has yum; then
      sudo yum install -y python3 python3-pip
    elif has pacman; then
      sudo pacman -Sy --noconfirm python python-pip
    elif has zypper; then
      sudo zypper install -y python3 python3-pip
    else
      err "Không nhận diện được package manager. Cài Python 3.9+ thủ công rồi chạy lại."
      exit 1
    fi
  fi
}

if python_ok; then
  ok "Python $(python3 -V 2>&1 | cut -d' ' -f2)"
else
  install_python
  python_ok || { err "Cài Python xong vẫn chưa đạt 3.9+. Kiểm tra thủ công."; exit 1; }
  ok "Python đã cài"
fi

# ── 2. pipx ──────────────────────────────────────────────────────────────────
info "[2/4] Kiểm tra pipx..."
if ! has pipx; then
  python3 -m pip install --user --upgrade pip >/dev/null 2>&1 || true
  python3 -m pip install --user pipx
  python3 -m pipx ensurepath >/dev/null 2>&1 || true
  # Nạp PATH cho phiên hiện tại (pipx thường vào ~/.local/bin)
  export PATH="$HOME/.local/bin:$PATH"
fi
if has pipx; then ok "pipx sẵn sàng"; else
  export PATH="$HOME/.local/bin:$PATH"
  has pipx || { err "pipx chưa vào PATH. Mở terminal mới rồi chạy lại."; exit 1; }
fi

# ── 3. Docker ────────────────────────────────────────────────────────────────
info "[3/4] Kiểm tra Docker..."
if has docker && docker info >/dev/null 2>&1; then
  ok "Docker đang chạy"
elif has docker; then
  warn "Docker đã cài nhưng chưa chạy."
  if [ "$PLATFORM" = "mac" ]; then
    open -a Docker 2>/dev/null || true
    warn "Đã mở Docker Desktop — chờ nó khởi động rồi chạy: datn up"
  else
    sudo systemctl start docker 2>/dev/null || warn "Chạy tay: sudo systemctl start docker"
  fi
else
  if [ "$PLATFORM" = "linux" ]; then
    info "Cài Docker Engine (get.docker.com)..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable --now docker 2>/dev/null || true
    # Thêm user vào nhóm docker để không cần sudo
    if ! id -nG 2>/dev/null | grep -qw docker; then
      sudo usermod -aG docker "$USER" 2>/dev/null || true
      warn "Đã thêm bạn vào nhóm 'docker'. ĐĂNG XUẤT + ĐĂNG NHẬP LẠI rồi chạy: datn up"
    fi
    ok "Docker đã cài"
  else
    err "Docker Desktop cần cài tay trên macOS (file .dmg):"
    printf "   ${CYAN}https://www.docker.com/products/docker-desktop/${NC}\n"
    warn "Cài xong, mở Docker Desktop rồi chạy: datn init && datn up"
  fi
fi

# ── 4. datn-cli ──────────────────────────────────────────────────────────────
info "[4/4] Cài $DATN_PKG..."
pipx install "$DATN_PKG" 2>/dev/null || pipx upgrade "$DATN_PKG"
ok "$DATN_PKG đã cài"

printf "\n${GREEN}════════════════════════════════════════${NC}\n"
ok "Hoàn tất!"
printf "Tiếp theo:\n"
printf "   ${CYAN}datn init${NC}   # nhập API key cho LLM + embedding\n"
printf "   ${CYAN}datn up${NC}     # khởi động hệ thống\n"
printf "   ${CYAN}datn open${NC}   # mở web UI\n"
