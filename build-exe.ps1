param(
  [string]$Name = "FinalTrade",
  [string]$IconPath = "",
  [switch]$Clean
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$backendVenv = Join-Path $backendDir ".venv"
$backendPython = Join-Path $backendVenv "Scripts\python.exe"
$frontendDist = Join-Path $frontendDir "dist"
$backendDist = Join-Path $backendDir "dist"
$backendBuild = Join-Path $backendDir "build"
$repoDist = Join-Path $repoRoot "dist"
$backendSpec = Join-Path $backendDir ("{0}.spec" -f $Name)
$resolvedIconPath = ""
$defaultIconPath = Join-Path $repoRoot "assets\\finaltrade.ico"

if ($IconPath -and $IconPath.Trim().Length -gt 0) {
  if (-not (Test-Path $IconPath)) {
    throw "Icon file not found: $IconPath"
  }
  $resolvedIconPath = (Resolve-Path $IconPath).Path
}
elseif (Test-Path $defaultIconPath) {
  $resolvedIconPath = (Resolve-Path $defaultIconPath).Path
}

if (-not (Test-Path $backendPython)) {
  Write-Host "Creating backend virtual environment..."
  python -m venv $backendVenv
}

Write-Host "Installing backend dependencies..."
& $backendPython -m pip install --upgrade pip
& $backendPython -m pip install -r (Join-Path $backendDir "requirements.txt")
& $backendPython -m pip install pyinstaller

Write-Host "Building frontend..."
Push-Location $frontendDir
try {
  if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    npm install
  }
  npm run build
}
finally {
  Pop-Location
}

if (-not (Test-Path (Join-Path $frontendDist "index.html"))) {
  throw "Frontend build failed: index.html not found in $frontendDist"
}

if ($Clean) {
  Remove-Item $backendDist -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item $backendBuild -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item $backendSpec -Force -ErrorAction SilentlyContinue
  Remove-Item $repoDist -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Packaging exe with PyInstaller..."
$addData = "{0};frontend_dist" -f $frontendDist
$pyiArgs = @(
  "--noconfirm",
  "--clean",
  "--onefile",
  "--name", $Name,
  "--add-data", $addData,
  "--hidden-import", "uvicorn.loops.asyncio",
  "--hidden-import", "uvicorn.protocols.http.h11_impl",
  "--hidden-import", "uvicorn.lifespan.on",
  "desktop_launcher.py"
)

if ($resolvedIconPath) {
  $pyiArgs += @("--icon", $resolvedIconPath)
}

Push-Location $backendDir
try {
  & $backendPython -m PyInstaller @pyiArgs
}
finally {
  Pop-Location
}

New-Item -ItemType Directory -Path $repoDist -Force | Out-Null
$exePath = Join-Path $backendDist ("{0}.exe" -f $Name)
if (-not (Test-Path $exePath)) {
  throw "Packaging failed: $exePath not found"
}

$targetPath = Join-Path $repoDist ("{0}.exe" -f $Name)
Copy-Item -Path $exePath -Destination $targetPath -Force

Write-Host ""
Write-Host "Build complete."
Write-Host "Output: $targetPath"
