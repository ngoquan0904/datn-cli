# datn-cli bootstrap installer (Windows)
#
#   irm https://raw.githubusercontent.com/ngoquan0904/datn-cli/main/install.ps1 | iex
#
# Tự cài: WSL2, Python 3.9+, pipx, Docker Desktop, rồi `pipx install datn-cli`.
# Idempotent. Một số bước cần Admin + reboot (WSL2) — script báo rõ.

$ErrorActionPreference = "Stop"
$Pkg = "datn-cli"

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)   { Write-Host "OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "!   $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "X   $m" -ForegroundColor Red }

function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# ── 0. Execution policy ──────────────────────────────────────────────────────
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq "Restricted" -or $policy -eq "AllSigned") {
    Warn "Execution policy = $policy. Cho phép chạy script user-scope:"
    Write-Host "    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Cyan
    Warn "Chạy lệnh trên rồi chạy lại installer."
    exit 1
}

# ── 0b. winget có sẵn? ───────────────────────────────────────────────────────
if (-not (Has "winget")) {
    Err "Không có winget (App Installer). Cài từ Microsoft Store: 'App Installer', rồi chạy lại."
    exit 1
}

# ── 1. WSL2 (Docker Desktop bắt buộc) ────────────────────────────────────────
Info "[1/5] Kiem tra WSL2..."
$wslOk = $false
try { wsl --status *>$null; if ($LASTEXITCODE -eq 0) { $wslOk = $true } } catch {}
if (-not $wslOk) {
    Warn "WSL2 chua san sang. Dang cai (can quyen Admin)..."
    try {
        Start-Process -FilePath "wsl" -ArgumentList "--install" -Verb RunAs -Wait
    } catch {
        Err "Khong tu cai WSL2 duoc. Chay PowerShell (Admin): wsl --install"
        exit 1
    }
    Warn "WSL2 da cai — KHOI DONG LAI MAY, roi chay lai installer nay."
    exit 0
}
Ok "WSL2 san sang"

# ── 2. Python 3.9+ ───────────────────────────────────────────────────────────
Info "[2/5] Kiem tra Python..."
function Python-Ok {
    if (-not (Has "python")) { return $false }
    try {
        $v = (python -c "import sys; print(1 if sys.version_info>=(3,9) else 0)") 2>$null
        return ($v.Trim() -eq "1")
    } catch { return $false }
}
if (Python-Ok) {
    Ok ("Python " + (python -V 2>&1))
} else {
    Info "Cai Python 3.11 qua winget..."
    winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Python-Ok)) {
        Err "Cai Python xong nhung chua nhan trong PATH. Mo terminal moi roi chay lai."
        exit 1
    }
    Ok "Python da cai"
}

# ── 3. pipx ──────────────────────────────────────────────────────────────────
Info "[3/5] Kiem tra pipx..."
if (-not (Has "pipx")) {
    python -m pip install --user --upgrade pip *>$null
    python -m pip install --user pipx
    python -m pipx ensurepath *>$null
    Refresh-Path
}
if (-not (Has "pipx")) {
    # pipx co the o %USERPROFILE%\.local\bin
    $env:Path += ";$env:USERPROFILE\.local\bin"
    if (-not (Has "pipx")) { Err "pipx chua vao PATH. Mo terminal moi roi chay lai."; exit 1 }
}
Ok "pipx san sang"

# ── 4. Docker Desktop ────────────────────────────────────────────────────────
Info "[4/5] Kiem tra Docker..."
$dockerRunning = $false
if (Has "docker") { try { docker info *>$null; if ($LASTEXITCODE -eq 0) { $dockerRunning = $true } } catch {} }

if ($dockerRunning) {
    Ok "Docker dang chay"
} elseif (Has "docker") {
    Warn "Docker da cai nhung chua chay — dang mo Docker Desktop..."
    $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Start-Process $dd }
    Warn "Cho Docker Desktop khoi dong roi chay: datn up"
} else {
    Info "Cai Docker Desktop qua winget (can vai phut)..."
    winget install -e --id Docker.DockerDesktop --silent --accept-package-agreements --accept-source-agreements
    Warn "Docker Desktop da cai — co the can KHOI DONG LAI. Mo Docker Desktop roi chay: datn up"
}

# ── 5. datn-cli ──────────────────────────────────────────────────────────────
Info "[5/5] Cai $Pkg..."
try { pipx install $Pkg } catch { pipx upgrade $Pkg }
Ok "$Pkg da cai"

Write-Host ""
Ok "Hoan tat!"
Write-Host "Tiep theo:" -ForegroundColor Cyan
Write-Host "    datn init   # nhap API key cho LLM + embedding"
Write-Host "    datn up     # khoi dong he thong"
Write-Host "    datn open   # mo web UI"
