param(
    [switch]$Record,
    [ValidateSet('EGP-CONTRACT-TEST', 'DGA-TEST')]
    [string]$Service = 'DGA-TEST'
)

$ErrorActionPreference = 'Stop'
$DataPath = Join-Path $PSScriptRoot 'data'
$LogPath = Join-Path $DataPath 'api_requests.jsonl'
$BangkokOffset = [TimeSpan]::FromHours(7)

if ($Record) {
    [System.IO.Directory]::CreateDirectory($DataPath) | Out-Null
    $Entry = @{ at_utc = [DateTimeOffset]::UtcNow.ToString('o'); service = $Service }
    $Line = ($Entry | ConvertTo-Json -Compress) + [Environment]::NewLine
    [System.IO.File]::AppendAllText($LogPath, $Line, [System.Text.UTF8Encoding]::new($false))
    return
}

$Today = [DateTimeOffset]::UtcNow.ToOffset($BangkokOffset).Date
$Count = 0
if (Test-Path -LiteralPath $LogPath) {
    foreach ($Line in Get-Content -LiteralPath $LogPath) {
        try {
            $Entry = $Line | ConvertFrom-Json
            $LocalDate = [DateTimeOffset]::Parse($Entry.at_utc).ToOffset($BangkokOffset).Date
            if ($LocalDate -eq $Today) { $Count++ }
        } catch {
            # Ignore a partial line if the computer stopped while writing.
        }
    }
}
Write-Output ("วันนี้ตามเวลาไทย สคริปต์ในโปรเจ็คพยายามส่งคำขอ $Count ครั้ง")
Write-Output 'ตัวนับในโปรเจ็คไม่มีเพดานและไม่บล็อกการส่งคำขอ; ผู้ให้บริการอาจมีโควตาของตนเอง'
Write-Output 'ตัวนับเริ่มทำงานหลังเพิ่มไฟล์นี้ ไม่รวมคำขอก่อนหน้า จากโปรแกรมอื่น หรือยอดที่ DGA คิดจริง'
