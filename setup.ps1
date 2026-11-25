# Fetch static ffmpeg into bin\ and build the launcher for Povtoritel.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin = Join-Path $root "bin"
$exe = Join-Path $bin "ffmpeg.exe"

if (Test-Path $exe) {
    Write-Host "ffmpeg already present: $exe"
} else {
    New-Item -ItemType Directory -Force $bin | Out-Null
    $ver = "8.1.2"
    $url = "https://github.com/GyanD/codexffmpeg/releases/download/$ver/ffmpeg-$ver-essentials_build.zip"
    $sha = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
    $zip = Join-Path $env:TEMP "ffmpeg-povtoritel.zip"
    $dir = Join-Path $env:TEMP "ffmpeg-povtoritel"

    Write-Host "Downloading static ffmpeg $ver (about 100 MB)..."
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $sha) {
        Remove-Item $zip -Force
        throw "ffmpeg download checksum mismatch: $got"
    }

    Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip -DestinationPath $dir -Force
    $src = Get-ChildItem $dir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    Copy-Item $src.FullName $exe -Force
    Remove-Item $zip, $dir -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "ffmpeg ready: $exe"
}

try {
    & (Join-Path $root "launcher\build.ps1")
} catch {
    Write-Host "Povtoritel.exe not built ($_). The app still runs with pythonw."
}
