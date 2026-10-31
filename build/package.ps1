# Build the portable release zip: the scripts plus the official embeddable Python and the
# requirements, so users do not need to install Python.
# Usage: powershell -ExecutionPolicy Bypass -File build\package.ps1 -Version 1.0.0
# Needs a Python of the same minor version on PATH (used only to run pip).
param(
  [Parameter(Mandatory)] [string]$Version,
  [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# $PSScriptRoot is empty inside param() defaults on Windows PowerShell 5.1, so default here.
if (-not $OutDir) { $OutDir = Join-Path $root "dist" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$pyver = (& python -c "import platform; print(platform.python_version())").Trim()
$tag = ($pyver -split '\.')[0..1] -join ''          # e.g. 313
$name = "eiscp-autopower-$Version-win64"
$stage = Join-Path $OutDir $name
$pydir = Join-Path $stage "python"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $pydir | Out-Null

# 1. Official embeddable Python (signed python.exe / pythonw.exe from python.org)
$url = "https://www.python.org/ftp/python/$pyver/python-$pyver-embed-amd64.zip"
$zip = Join-Path $OutDir "python-$pyver-embed-amd64.zip"
if (-not (Test-Path $zip)) { Invoke-WebRequest -UseBasicParsing $url -OutFile $zip }
Expand-Archive $zip -DestinationPath $pydir -Force
$sig = Get-AuthenticodeSignature (Join-Path $pydir "pythonw.exe")
if ($sig.Status -ne "Valid") { throw "pythonw.exe signature is not valid: $($sig.Status)" }

# 2. Requirements into python\Lib\site-packages, and let the embedded Python see them
$site = Join-Path $pydir "Lib\site-packages"
& python -m pip install --disable-pip-version-check -q --no-compile --target $site -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE) { throw "pip install failed" }
$pth = Join-Path $pydir "python$tag._pth"
Set-Content $pth -Encoding ascii -Value @("python$tag.zip", ".", "Lib\site-packages", "..", "import site")

# 3. The app itself
foreach ($f in "eiscp_autopower.py", "config.example.json", "install.ps1", "uninstall.ps1", "README.md", "LICENSE") {
  Copy-Item (Join-Path $root $f) $stage
}
Copy-Item (Join-Path $pydir "LICENSE.txt") (Join-Path $stage "LICENSE-Python.txt")

# 4. Smoke test with the embedded interpreter
& (Join-Path $pydir "python.exe") -c "import eiscp, pycaw.pycaw, comtypes; import eiscp_autopower; print('ok')"
if ($LASTEXITCODE) { throw "smoke test failed" }
& (Join-Path $pydir "python.exe") (Join-Path $stage "eiscp_autopower.py") --help | Out-Null
if ($LASTEXITCODE) { throw "--help failed" }

# 5. Zip + SHA256
$out = Join-Path $OutDir "$name.zip"
if (Test-Path $out) { Remove-Item $out }
Get-ChildItem $stage -Recurse -Include __pycache__ -Directory | Remove-Item -Recurse -Force
Compress-Archive -Path $stage -DestinationPath $out
$hash = (Get-FileHash $out -Algorithm SHA256).Hash.ToLower()
Set-Content "$out.sha256" -Encoding ascii -Value "$hash  $name.zip"
Write-Host "built $out ($([math]::Round((Get-Item $out).Length/1MB,1)) MB) python $pyver sha256 $hash"
