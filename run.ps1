$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $ProjectPython) {
    $PythonExecutable = $ProjectPython
} elseif ($PythonCommand) {
    $PythonExecutable = $PythonCommand.Source
} else {
    $PythonExecutable = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $PythonExecutable)) {
        throw 'ไม่พบ Python: กรุณาติดตั้ง Python 3.10 ขึ้นไป แล้วเปิด PowerShell ใหม่'
    }
}
Set-Location -LiteralPath $ProjectRoot
& $PythonExecutable -m app.server
