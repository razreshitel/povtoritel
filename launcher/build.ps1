# Build Povtoritel.exe (native launcher with icon and name).
param([string]$Python = "py")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$build = Join-Path $here "build"
$exe = Join-Path $root "Povtoritel.exe"

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "Visual Studio Build Tools (C++) not found" }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "MSVC x64 tools not found" }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"

$info = & $Python -c "import sys; v=sys.version_info; print(f'{v[0]}.{v[1]}|python{v[0]}{v[1]}.dll|{sys.base_prefix}')"
if ($LASTEXITCODE -ne 0 -or -not $info) { throw "Python not found: $Python" }
$ver, $dll, $home_ = $info.Trim().Split("|")

New-Item -ItemType Directory -Force $build | Out-Null
$esc = $home_.Replace("\", "\\")
@"
#define PY_VER L"$ver"
#define PY_DLL L"$dll"
#define PY_HOME L"$esc"
"@ | Set-Content -Encoding ascii (Join-Path $build "pyconf.h")

$bat = Join-Path $build "build.bat"
@"
@echo off
call "$vcvars" >nul 2>nul || exit /b 1
cd /d "$here"
rc /nologo /fo build\povtoritel.res povtoritel.rc || exit /b 1
cl /nologo /O1 /MT /W3 /DUNICODE /D_UNICODE /Ibuild povtoritel.c build\povtoritel.res /Fobuild\ /Fe"$exe" /link /SUBSYSTEM:WINDOWS /MANIFEST:NO user32.lib advapi32.lib shell32.lib || exit /b 1
"@ | Set-Content -Encoding ascii $bat

& cmd /c "`"$bat`""
if ($LASTEXITCODE -ne 0) { throw "build failed (is Povtoritel.exe running?)" }
Write-Host "built $exe for Python $ver"
