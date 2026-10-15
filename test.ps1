$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($PythonCommand) {
    $PythonExecutable = $PythonCommand.Source
} else {
    $PythonExecutable = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $PythonExecutable)) {
        throw 'ไม่พบ Python: กรุณาติดตั้ง Python 3.10 ขึ้นไป แล้วเปิด PowerShell ใหม่'
    }
}
Set-Location -LiteralPath $ProjectRoot
& $PythonExecutable -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
