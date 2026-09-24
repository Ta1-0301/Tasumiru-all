# Ollama・バックエンドAPIサーバー・フロントエンドをまとめて起動する開発用スクリプト
# 使い方: .\start-dev.ps1 [-Model gemma3:4b] [-Port 8000] [-NoFrontend]

param(
    [string]$Model = $(if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "gemma3:4b" }),
    [int]$Port = 8000,
    [switch]$NoFrontend
)

$RepoRoot = $PSScriptRoot
$FrontendDir = Join-Path $RepoRoot "frontend"

# このターミナルが Node.js / uv のインストールより前に開かれていた場合、
# 古い PATH を引き継いでいて 'npm'/'uv' が見つからないことがあるため、
# 既知のインストール先を保険として PATH に足しておく（既にあれば何もしない）。
function Add-PathIfExists([string]$Dir) {
    if ((Test-Path $Dir) -and ($env:Path -notlike "*$Dir*")) {
        $env:Path = "$env:Path;$Dir"
    }
}
Add-PathIfExists "C:\Program Files\nodejs"
Add-PathIfExists "$env:LOCALAPPDATA\Programs\nodejs"
Add-PathIfExists "$env:APPDATA\Python\Python314\Scripts"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Warning "npm が見つかりません。Node.js をインストール直後の場合は、いま開いているターミナルを閉じて新しく開き直してから再実行してください。"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Warning "uv が見つかりません。ターミナルを開き直すか、'pip install --user uv' を実行してください。"
}

$OllamaBaseUrl = "http://127.0.0.1:11434"

function Test-OllamaRunning {
    try {
        Invoke-WebRequest -Uri $OllamaBaseUrl -UseBasicParsing -TimeoutSec 5 | Out-Null
        return $true
    } catch {
        return $false
    }
}

# 1. Ollama サーバーの起動確認
if (Test-OllamaRunning) {
    Write-Host "[ollama] すでに起動しています ($OllamaBaseUrl)"
} else {
    Write-Host "[ollama] 起動していないため 'ollama serve' を開始します..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized

    $retries = 0
    while (-not (Test-OllamaRunning)) {
        Start-Sleep -Seconds 1
        $retries++
        if ($retries -ge 15) {
            Write-Error "[ollama] 起動を確認できませんでした。'ollama serve' を手動で実行してエラー内容を確認してください。"
            exit 1
        }
    }
    Write-Host "[ollama] 起動を確認しました。"
}

# 2. 指定モデルが未取得なら pull する
$installed = & ollama list | Select-String -SimpleMatch $Model
if (-not $installed) {
    Write-Host "[ollama] モデル '$Model' が未取得のため pull します..."
    & ollama pull $Model
} else {
    Write-Host "[ollama] モデル '$Model' は取得済みです。"
}

# 3. フロントエンド（Vite dev server）を別ウィンドウで起動
if (-not $NoFrontend) {
    if (Test-Path (Join-Path $FrontendDir "package.json")) {
        Write-Host "[frontend] npm run dev を別ウィンドウで起動します -> http://localhost:5173"
        Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", "cd '$FrontendDir'; npm run dev"
    } else {
        Write-Host "[frontend] frontend/package.json が見つからないためスキップします。"
    }
}

# 4. バックエンドサーバーの起動（.env の LLM_PROVIDER/OLLAMA_BASE_URL/OLLAMA_MODEL を使用）
$env:OLLAMA_MODEL = $Model
Write-Host "[backend] uvicorn を起動します -> http://localhost:$Port (model=$Model)"
Set-Location $RepoRoot
uv run uvicorn backend.main:app --reload --port $Port
