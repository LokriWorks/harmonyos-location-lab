$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$version = [regex]::Match((Get-Content app_version.py -Raw), 'VERSION = "([^"]+)"').Groups[1].Value
$exe = (Resolve-Path "dist/HarmonyOSLocationLab-v$version-win-x64.exe").Path
$result = Join-Path (Get-Location) 'build/exe-self-test.json'
if (Test-Path $result) { Remove-Item -LiteralPath $result }
$savedPath, $savedPython, $savedTcl, $savedTk = $env:PATH, $env:PYTHONPATH, $env:TCL_LIBRARY, $env:TK_LIBRARY
try {
    $env:PATH = "$env:SystemRoot/System32;$env:SystemRoot"
    $env:PYTHONPATH = $null
    $env:TCL_LIBRARY = $null
    $env:TK_LIBRARY = $null
    $process = Start-Process -FilePath $exe -ArgumentList @('--self-test', ('"' + $result + '"')) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        Stop-Process -Id $process.Id -Force
        throw 'Offline EXE test timed out'
    }
    if ($process.ExitCode -ne 0 -or -not (Test-Path $result)) { throw 'EXE failed to start or produce a result' }
    $data = Get-Content $result -Raw | ConvertFrom-Json
    if (-not ($data.ok -and $data.frozen -and $data.offline -and $data.cancelled -and $data.chinese_ok -and $data.sample_points -gt 0)) { throw 'EXE self-test failed' }
    Get-Content $result -Raw
} finally {
    $env:PATH, $env:PYTHONPATH, $env:TCL_LIBRARY, $env:TK_LIBRARY = $savedPath, $savedPython, $savedTcl, $savedTk
}
