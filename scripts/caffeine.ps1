# Caffeine - PC'nin uyku moduna girmesini ve ekranın kapanmasını engeller.
# Kullanım:
#   .\caffeine.ps1                 # Süresiz çalışır (Ctrl+C ile durdur)
#   .\caffeine.ps1 -Minutes 120    # 120 dakika sonra otomatik durur
#   .\caffeine.ps1 -KeepDisplay:$false  # Sadece sistem uyanık kalsın, ekran kapanabilir

[CmdletBinding()]
param(
    [int]$Minutes = 0,
    [switch]$KeepDisplay = $true
)

$signature = @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@

$type = Add-Type -MemberDefinition $signature -Name 'CaffeineUtil' -Namespace 'Win32' -PassThru

$ES_CONTINUOUS       = [uint32]'0x80000000'
$ES_SYSTEM_REQUIRED  = [uint32]'0x00000001'
$ES_DISPLAY_REQUIRED = [uint32]'0x00000002'

$flags = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED
if ($KeepDisplay) { $flags = $flags -bor $ES_DISPLAY_REQUIRED }

$prev = $type::SetThreadExecutionState($flags)
if ($prev -eq 0) {
    Write-Error "SetThreadExecutionState basarisiz oldu."
    exit 1
}

$mode = if ($KeepDisplay) { "sistem + ekran" } else { "sadece sistem" }
$durationText = if ($Minutes -gt 0) { "$Minutes dakika" } else { "sinirsiz (Ctrl+C ile durdur)" }
Write-Host "[caffeine] Aktif. Mod: $mode. Sure: $durationText." -ForegroundColor Green

try {
    if ($Minutes -gt 0) {
        Start-Sleep -Seconds ($Minutes * 60)
    } else {
        while ($true) { Start-Sleep -Seconds 60 }
    }
}
finally {
    [void]$type::SetThreadExecutionState($ES_CONTINUOUS)
    Write-Host "[caffeine] Devre disi. Normal guc politikasina donuldu." -ForegroundColor Yellow
}
