$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCommand) {
    throw 'ไม่พบ Python: กรุณาติดตั้ง Python 3.10 ขึ้นไป แล้วเปิด PowerShell ใหม่'
}
Set-Location -LiteralPath $ProjectRoot
& $PythonCommand.Source -m egp_live.server
