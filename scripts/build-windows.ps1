param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$version = [regex]::Match((Get-Content app_version.py -Raw), 'VERSION = "([^"]+)"').Groups[1].Value
if (-not $version) { throw 'Missing version' }
$name = "HarmonyOSLocationLab-v$version-win-x64"
$noticeDir = Join-Path (Get-Location) 'build/notices'
New-Item -ItemType Directory -Force $noticeDir | Out-Null
Copy-Item LICENSE "$noticeDir/PROJECT-LICENSE.txt"
Copy-Item THIRD-PARTY-NOTICES.md "$noticeDir/README.md"
Copy-Item licenses/* $noticeDir
$prefix = (& $Python -c 'import sys; print(sys.base_prefix)').Trim()
Copy-Item "$prefix/LICENSE.txt" "$noticeDir/PYTHON-LICENSE.txt"
$pyinstallerLicense = (& $Python -c 'from importlib.metadata import distribution; d=distribution("pyinstaller"); print(next(d.locate_file(f) for f in d.files if str(f).endswith("COPYING.txt")))').Trim()
Copy-Item $pyinstallerLicense "$noticeDir/PYINSTALLER-COPYING.txt"
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name $name --add-data 'examples;examples' --add-data "$noticeDir;licenses" gui.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
Compress-Archive -Path "$noticeDir/*" -DestinationPath "dist/HarmonyOSLocationLab-v$version-licenses.zip" -Force
Write-Host "Built dist/$name.exe"
