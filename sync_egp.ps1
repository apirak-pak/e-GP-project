param(
    [ValidateRange(2500, 2700)] [int]$Year = 2568,
    [string]$Keyword = 'จ้างก่อสร้าง',
    [ValidateRange(1, 1000)] [int]$Limit = 20,
    [ValidateRange(0, 2147483647)] [int]$Offset = 0,
    [ValidateRange(0, 1000000000000)] [double]$MinBudget,
    [ValidateRange(0, 1000000000000)] [double]$MaxBudget
)

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

$SyncArgs = @('-m', 'app.sync_egp', '--year', "$Year", '--keyword', $Keyword, '--limit', "$Limit", '--offset', "$Offset")
if ($PSBoundParameters.ContainsKey('MinBudget')) {
    $SyncArgs += @('--min-budget', $MinBudget.ToString([System.Globalization.CultureInfo]::InvariantCulture))
}
if ($PSBoundParameters.ContainsKey('MaxBudget')) {
    $SyncArgs += @('--max-budget', $MaxBudget.ToString([System.Globalization.CultureInfo]::InvariantCulture))
}
Set-Location -LiteralPath $ProjectRoot
& $PythonExecutable @SyncArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
