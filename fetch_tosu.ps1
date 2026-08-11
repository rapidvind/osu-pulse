# Downloads the latest Windows build of tosu (https://github.com/tosuapp/tosu)
# into vendor/tosu.exe, ready for PyInstaller to bundle.
#
# tosu is LGPL-3.0 licensed and NOT authored by this project - see
# THIRD_PARTY_NOTICES.md for attribution. We fetch their official release
# asset as-is; nothing here modifies tosu itself.

$ErrorActionPreference = "Stop"

$release = Invoke-RestMethod -Uri "https://api.github.com/repos/tosuapp/tosu/releases/latest"
$asset = $release.assets | Where-Object { $_.name -like "tosu-windows-*.zip" } | Select-Object -First 1

if (-not $asset) {
    Write-Error "Could not find a tosu-windows-*.zip asset in the latest release."
    exit 1
}

Write-Host "Downloading $($asset.name) ($($release.tag_name))..."
$zipPath = Join-Path $env:TEMP $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

$extractDir = Join-Path $env:TEMP "tosu-extract"
if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
Expand-Archive -Path $zipPath -DestinationPath $extractDir

$exe = Get-ChildItem -Path $extractDir -Filter "tosu.exe" -Recurse | Select-Object -First 1
if (-not $exe) {
    Write-Error "tosu.exe not found inside the downloaded archive."
    exit 1
}

New-Item -ItemType Directory -Force -Path "vendor" | Out-Null
Copy-Item $exe.FullName -Destination "vendor\tosu.exe" -Force

Write-Host "vendor\tosu.exe ready ($($release.tag_name))."
