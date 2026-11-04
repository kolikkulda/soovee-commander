$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = Join-Path (Get-Location) "src"
$version = python -c "from soovee_commander import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw "Cannot determine application version" }
if (-not $env:LIBARCHIVE -or -not (Test-Path $env:LIBARCHIVE)) {
    throw "Set LIBARCHIVE to archive.dll from vcpkg install libarchive:x64-windows. The DLL and dependencies will be bundled."
}
$archiveBin = Split-Path -Parent $env:LIBARCHIVE
python scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw "License inventory failed" }
python -m PyInstaller --noconfirm --windowed --name SooveeCommander --collect-submodules zeroconf --add-data "src/soovee_commander/licenses;soovee_commander/licenses" --icon packaging/SooveeCommander.ico --add-data "src/soovee_commander/assets;soovee_commander/assets" --paths src --add-data "src/soovee_commander/locales;soovee_commander/locales" --add-binary "$archiveBin\*.dll;archive_bin" launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$portable = "dist/SooveeCommander-$version-windows-x86_64-portable.zip"
Compress-Archive -Path dist/SooveeCommander/* -DestinationPath $portable -Force
$compiler = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $compiler) { $compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $compiler)) { throw "Install Inno Setup 6 to build the Windows installer" }
& $compiler "/DAppVersion=$version" packaging/windows.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
if (Test-Path .release/update-private.pem) {
    python scripts/release.py package --artifact "dist/SooveeCommander-$version-windows-x86_64-setup.exe" --target windows-x86_64 --output "dist/SooveeCommander-$version-windows-x86_64.stereoupdate"
    if ($LASTEXITCODE -ne 0) { throw "Update signing failed" }
}
