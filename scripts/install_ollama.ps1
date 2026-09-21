# scripts/install_ollama.ps1 — install the local inference runtime on Windows.
#
# Ollama is what runs a model on this machine. Without it the local leg of the
# model chain cannot answer, and ai/local_model.py refuses to start rather than
# pretending otherwise.
#
# winget first, deliberately: it resolves a signed package from the Microsoft
# package repository, which is a materially better supply-chain story than
# downloading and executing an installer this script chose. The direct download
# is the fallback for a machine without winget, and it verifies what it got
# before running it.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install_ollama.ps1

$ErrorActionPreference = 'Stop'

function Test-OllamaPresent {
    $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)
}

if (Test-OllamaPresent) {
    Write-Host "ollama: already installed at $((Get-Command ollama).Source)"
    try { & ollama --version } catch { }
    exit 0
}

Write-Host "ollama: not present — installing"

$installed = $false

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "ollama: installing via winget (signed package)"
    try {
        & winget install --id Ollama.Ollama --exact --silent `
            --accept-package-agreements --accept-source-agreements
        $installed = $true
    } catch {
        Write-Warning "ollama: winget install failed ($($_.Exception.Message)); falling back to the direct download"
    }
} else {
    Write-Host "ollama: winget is not available on this machine"
}

if (-not $installed) {
    $url = $env:OLLAMA_INSTALL_URL
    if (-not $url) { $url = 'https://ollama.com/download/OllamaSetup.exe' }
    $target = Join-Path $env:TEMP 'OllamaSetup.exe'

    Write-Host "ollama: downloading $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing -TimeoutSec 300
    } catch {
        Write-Error "ollama: could not download the installer ($($_.Exception.Message)). Install manually: https://ollama.com/download"
        exit 1
    }

    if (-not (Test-Path $target) -or (Get-Item $target).Length -eq 0) {
        Write-Error "ollama: the downloaded installer is empty — refusing to run it"
        exit 1
    }

    $sha = (Get-FileHash -Path $target -Algorithm SHA256).Hash.ToLower()
    Write-Host "ollama: installer sha256 $sha"
    $expected = $env:OLLAMA_INSTALL_SHA256
    if ($expected) {
        if ($sha -ne $expected.ToLower()) {
            Write-Error "ollama: checksum mismatch — refusing to run it. expected $expected, actual $sha"
            exit 1
        }
        Write-Host "ollama: checksum matches the pin"
    } else {
        Write-Host "ollama: no OLLAMA_INSTALL_SHA256 pin set — running an unpinned installer."
        Write-Host "        Pin it with the sha256 above once you have reviewed the file."
    }

    # An Authenticode signature is what distinguishes the vendor's installer
    # from anything else that answered the request. A missing or invalid one is
    # not a warning to scroll past.
    $signature = Get-AuthenticodeSignature -FilePath $target
    Write-Host "ollama: signature status $($signature.Status)"
    if ($signature.Status -ne 'Valid') {
        Write-Error "ollama: the installer is not validly signed ($($signature.Status)) — refusing to run it"
        exit 1
    }

    Write-Host "ollama: running the installer"
    Start-Process -FilePath $target -ArgumentList '/VERYSILENT','/NORESTART' -Wait
    # A fresh install lands in PATH only for new processes; refresh this one so
    # the check below measures the install rather than a stale environment.
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
}

if (-not (Test-OllamaPresent)) {
    Write-Error "ollama: the installer finished but ollama is still not on PATH. This is a failed install reporting success. See https://ollama.com/download"
    exit 1
}

Write-Host "ollama: installed at $((Get-Command ollama).Source)"
try { & ollama --version } catch { }
