#!/usr/bin/env pwsh
# =============================================================================
# SEC54.6d Smoke Rollback - 5 dakikada YOL-B baseline'a don
# =============================================================================
# Kullanim: .\scripts\smoke_rollback.ps1
# Tetikleyici: Smoke fail → G-01..G-08 herhangi biri FAIL
#
# Adimlar:
#   1. Kill-switch aktiflestir (daemon durur)
#   2. Acik testnet emirleri iptal (ccxt cancel_all)
#   3. _pyramid_positions temizle (in-process - restart ile zaten temizlenir)
#   4. Log rollback anini
# =============================================================================
param(
    [string]$Reason = "smoke_fail_manual_rollback"
)

$ROOT = Split-Path -Parent $PSScriptRoot

Write-Host "=" * 60 -ForegroundColor Red
Write-Host "SMOKE ROLLBACK BASLATILIYOR" -ForegroundColor Red
Write-Host "  Reason: $Reason" -ForegroundColor Red
Write-Host "=" * 60 -ForegroundColor Red

# Step 1: Kill switch aktiflestir
$ksPath = Join-Path $ROOT "logs\kill_switch.json"
$ks = @{ halted = $true; reason = $Reason; ts = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ") } | ConvertTo-Json
$ks | Set-Content $ksPath -Encoding UTF8
Write-Host "[1/4] Kill-switch aktiflestirildi: $ksPath" -ForegroundColor Yellow

# Step 2: Binance testnet emirleri iptal
Write-Host "[2/4] Testnet acik emirler iptal ediliyor..." -ForegroundColor Yellow
python -c @"
import os, sys
sys.path.insert(0, '.')
sys.path.insert(0, 'src')
from dotenv import load_dotenv
load_dotenv('.env', override=False)
try:
    import ccxt
    ex = ccxt.binance({
        'apiKey': os.environ.get('BINANCE_TESTNET_API_KEY',''),
        'secret': os.environ.get('BINANCE_TESTNET_SECRET',''),
        'enableRateLimit': True,
        'options': {'defaultType': 'future'},
        'urls': {'api': {'public': 'https://testnet.binancefuture.com',
                         'private': 'https://testnet.binancefuture.com'}},
    })
    syms = ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','ADA/USDT',
            'AVAX/USDT','LINK/USDT','DOT/USDT','DOGE/USDT','XRP/USDT']
    total = 0
    for s in syms:
        try:
            result = ex.cancel_all_orders(s)
            n = len(result) if isinstance(result, list) else 0
            if n: print(f'  Cancelled {n} orders for {s}')
            total += n
        except Exception as e:
            print(f'  {s}: {e}')
    print(f'[2/4] Toplam {total} emir iptal edildi')
except Exception as e:
    print(f'[2/4] Exchange baglantisi basarisiz: {e}')
    print('[2/4] Manuel iptal gerekebilir (Binance testnet UI)')
"@

# Step 3: State dosyalarini temizle
Write-Host "[3/4] State dosyalari temizleniyor..." -ForegroundColor Yellow
$stateFiles = @(
    "logs\state\futures_last_scan_phoenix.txt",
    "logs\risk\futures_breaker_state_15m_phoenix.json"
)
foreach ($f in $stateFiles) {
    $fp = Join-Path $ROOT $f
    if (Test-Path $fp) {
        Remove-Item $fp -Force
        Write-Host "  Silindi: $f" -ForegroundColor Gray
    }
}

# Step 4: Log
$logPath = Join-Path $ROOT "logs\smoke_rollback.log"
$logLine = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss UTC') ROLLBACK reason=$Reason"
Add-Content $logPath $logLine
Write-Host "[4/4] Rollback logu: $logPath" -ForegroundColor Gray

Write-Host ""
Write-Host "ROLLBACK TAMAMLANDI" -ForegroundColor Green
Write-Host "  - Kill-switch aktif (daemon dur)" -ForegroundColor Green
Write-Host "  - Testnet emirler iptal" -ForegroundColor Green
Write-Host "  - State dosyalari temizlendi" -ForegroundColor Green
Write-Host ""
Write-Host "Sonraki adimlar:" -ForegroundColor Yellow
Write-Host "  1. Smoke fail sebebini incele: logs\futures_daemon_phoenix.log" -ForegroundColor Yellow
Write-Host "  2. YOL-B YAML degisiklik gerektiriyorsa: configs\risk_phoenix_scalp_15m_c2v5_final.yaml" -ForegroundColor Yellow
Write-Host "  3. Duzeltme sonrasi kill-switch'i temizle ve smoke'u yeniden baslat" -ForegroundColor Yellow
