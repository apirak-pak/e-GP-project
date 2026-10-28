param(
    [ValidateRange(2500, 2700)]
    [int]$Year = 2568,

    [ValidateRange(1, 10)]
    [int]$Limit = 1
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $ProjectRoot '.env'
if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw 'ไม่พบไฟล์ .env ในโฟลเดอร์โปรเจ็ค'
}

$KeyLines = @(Get-Content -LiteralPath $EnvPath | Where-Object { $_ -match '^\s*DGA_API_KEY\s*=' })
if ($KeyLines.Count -ne 1) {
    throw 'ไฟล์ .env ต้องมี DGA_API_KEY=... เพียงหนึ่งบรรทัด'
}
$PlainKey = ($KeyLines[0] -replace '^\s*DGA_API_KEY\s*=\s*', '').Trim()
if ($PlainKey.Length -ge 2 -and (($PlainKey.StartsWith('"') -and $PlainKey.EndsWith('"')) -or ($PlainKey.StartsWith("'") -and $PlainKey.EndsWith("'")))) {
    $PlainKey = $PlainKey.Substring(1, $PlainKey.Length - 2)
}
if (-not $PlainKey -or $PlainKey -eq 'PASTE_YOUR_KEY_HERE') {
    throw 'ยังไม่ได้ใส่ DGA_API_KEY จริงในไฟล์ .env'
}

# The current EGP-CONTRACT documentation requires api-key in the query string.
# Build the URL only in memory and never print it or the raw exception message.
$EncodedKey = [System.Uri]::EscapeDataString($PlainKey)
$RequestUri = "https://opend.data.go.th/govspending/service/egp-contract?api-key=$EncodedKey&year=$Year&keyword=%E0%B8%88%E0%B9%89%E0%B8%B2%E0%B8%87%E0%B8%81%E0%B9%88%E0%B8%AD%E0%B8%AA%E0%B8%A3%E0%B9%89%E0%B8%B2%E0%B8%87&limit=$Limit"
try {
    & (Join-Path $ProjectRoot 'api_usage.ps1') -Record -Service 'EGP-CONTRACT-TEST'
    $Result = Invoke-RestMethod -Uri $RequestUri -Method GET -MaximumRedirection 0 -TimeoutSec 30 -ErrorAction Stop
    Write-Output ('SUCCESS=' + $Result.success)
    Write-Output ('CODE=' + $Result.code)
    Write-Output ('TOTAL=' + $Result.total)
    Write-Output ('RETURNED=' + @($Result.data).Count)
    if ($Result.data -and @($Result.data).Count -gt 0) {
        Write-Output ('FIELDS=' + ($Result.data[0].PSObject.Properties.Name -join ','))
        $Project = $Result.data[0]
        Write-Output ('SAMPLE_PROVINCE=' + $Project.province)
        Write-Output ('SAMPLE_DISTRICT=' + $Project.district)
        Write-Output ('SAMPLE_LOCATION=' + ($Project.project_location | ConvertTo-Json -Compress -Depth 3))
        Write-Output ('SAMPLE_TYPE=' + $Project.project_type_name)
        Write-Output ('SAMPLE_STATUS=' + $Project.project_status)
        Write-Output ('SAMPLE_ANNOUNCED=' + $Project.announce_date)
        Write-Output ('SAMPLE_TRANSACTION=' + $Project.transaction_date)
        Write-Output ('SAMPLE_CONTRACT_COUNT=' + @($Project.contract).Count)
        if ($Project.contract -and @($Project.contract).Count -gt 0) {
            Write-Output ('CONTRACT_FIELDS=' + ($Project.contract[0].PSObject.Properties.Name -join ','))
            Write-Output ('SAMPLE_CONTRACT_DATE=' + $Project.contract[0].contract_date)
        }
        Write-Output ('PROJECT_STATUSES=' + ((@($Result.data) | ForEach-Object { $_.project_status } | Sort-Object -Unique) -join ','))
        Write-Output ('CONTRACT_STATUSES=' + ((@($Result.data) | ForEach-Object { @($_.contract) | ForEach-Object { $_.status } } | Sort-Object -Unique) -join ','))
    }
} catch {
    $Status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'none' }
    Write-Error "เรียก EGP-CONTRACT ไม่สำเร็จ (HTTP $Status; $($_.Exception.GetType().Name))"
} finally {
    Remove-Variable PlainKey, EncodedKey, RequestUri, KeyLines -ErrorAction SilentlyContinue
}
