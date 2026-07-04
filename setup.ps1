# Fetch static ffmpeg into bin\ for Povtoritel.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin = Join-Path $root "bin"
$exe = Join-Path $bin "ffmpeg.exe"

if (Test-Path $exe) {
    Write-Host "ffmpeg already present: $exe"
    exit 0
}

New-Item -ItemType Directory -Force $bin | Out-Null
$url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zip = Join-Path $env:TEMP "ffmpeg-povtoritel.zip"
$dir = Join-Path $env:TEMP "ffmpeg-povtoritel"

Write-Host "Downloading static ffmpeg (about 100 MB)..."
$ProgressPreference = "SilentlyContinue"
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $dir -Force
$src = Get-ChildItem $dir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
Copy-Item $src.FullName $exe -Force
Remove-Item $zip, $dir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "ffmpeg ready: $exe"
