param(
    [Parameter(Mandatory = $true)]
    [string]$Uri,

    [ValidateSet('GET', 'POST')]
    [string]$Method = 'GET',

    [string]$JsonBody = ''
)

$ErrorActionPreference = 'Stop'

try {
    $ParsedUri = [System.Uri]::new($Uri)
} catch {
    throw 'URL ไม่ถูกต้อง กรุณาคัดลอกจากคู่มือ API ของชุดข้อมูล'
}

if ($ParsedUri.Scheme -ne 'https' -or $ParsedUri.Host -notin @('opend.data.go.th', 'api.data.go.th', 'govspending.data.go.th')) {
    throw 'สคริปต์นี้รับเฉพาะ HTTPS ของ data.go.th หรือ govspending.data.go.th'
}
if ($ParsedUri.Query -match '(?i)(api[-_]?key|token|secret)=') {
    throw 'URL มี Key อยู่ใน query string กรุณาใช้ URL ที่ไม่มี Key แล้วให้สคริปต์ส่ง Key ทาง header'
}
if ($Method -eq 'POST' -and -not $JsonBody) {
    throw 'คำขอ POST ต้องระบุ -JsonBody ตามคู่มือของ API ชุดนั้น'
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $ProjectRoot '.env'
if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw 'ไม่พบไฟล์ .env ให้คัดลอก .env.example เป็น .env แล้วใส่ DGA_API_KEY ในไฟล์นั้น'
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
try {
    $Request = @{
        Uri = $Uri
        Method = $Method
        Headers = @{ 'api-key' = $PlainKey }
        TimeoutSec = 30
        MaximumRedirection = 0
        ErrorAction = 'Stop'
    }
    if ($Method -eq 'POST') {
        $Request.ContentType = 'application/json'
        $Request.Body = $JsonBody
    }
    & (Join-Path $ProjectRoot 'api_usage.ps1') -Record -Service 'DGA-TEST'
    $Result = Invoke-RestMethod @Request
    Write-Host 'เชื่อมต่อสำเร็จ' -ForegroundColor Green
    Write-Output "ฟิลด์หลัก: $($Result.PSObject.Properties.Name -join ', ')"
    if ($Result.result -and $Result.result.records) {
        Write-Output "จำนวนรายการในคำตอบ: $($Result.result.records.Count)"
        Write-Output "ฟิลด์ของรายการแรก: $($Result.result.records[0].PSObject.Properties.Name -join ', ')"
    }
} catch {
    $Status = $_.Exception.Response.StatusCode
    if ($Status) {
        if ([int]$Status -in @(301, 302, 307, 308)) {
            $Location = $_.Exception.Response.Headers.Location
            if ($Location) {
                $RedirectUri = [System.Uri]::new($ParsedUri, $Location)
                Write-Error "API เปลี่ยนปลายทาง (HTTP $([int]$Status)) ไปยัง $($RedirectUri.Scheme)://$($RedirectUri.Host)$($RedirectUri.AbsolutePath)"
            } else {
                Write-Error "API เปลี่ยนปลายทาง (HTTP $([int]$Status)) แต่ไม่แจ้ง URL ใหม่"
            }
        } else {
            Write-Error "เรียก API ไม่สำเร็จ (HTTP $([int]$Status)) ตรวจ URL วิธี GET/POST และสิทธิของ Key"
        }
    } else {
        Write-Error "เรียก API ไม่สำเร็จ ($($_.Exception.GetType().Name)) ตรวจการเชื่อมต่อและรูปแบบคำขอ"
    }
} finally {
    Remove-Variable PlainKey, Request, KeyLines -ErrorAction SilentlyContinue
}
