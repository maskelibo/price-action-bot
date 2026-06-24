#!/usr/bin/env pwsh
# =============================================================================
# SEC54.6d Testnet Smoke 7g - Launch Script (Windows PowerShell)
# =============================================================================
# Kullanim:
#   .\scripts\testnet_smoke_15m.ps1
#   .\scripts\testnet_smoke_15m.ps1 -DryRun        # Baglanti test, emir yok
#   .\scripts\testnet_smoke_15m.ps1 -PaperMode      # $1000 paper (smoke PASS sonrasi)
#
# Gereksinimler:
#   .env: BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
#   python: duckdb, ccxt, pandas, pyyaml, prometheus_client
#
# CRITICAL: PA_LIVE_CONFIRM=NO_TESTNET_ONLY - live emir YASAK bu script ile.
# =============================================================================
param(
    [switch]$DryRun,
    [switch]$PaperMode,
    [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $PSScriptRoot

# -- Environment ----------------------------------------------------------------
$env:PA_BOT_NAME          = "phoenix_15m_smoke_sec54_6d"
$env:PA_RUN_MODE          = "paper"
$env:PA_LIVE_CONFIRM      = "NO_TESTNET_ONLY"   # KRITIK: live emir YASAK
$env:PA_LOG_QUIET         = "0"                 # smoke: verbose log

if ($PaperMode) {
    $env:PA_CAPITAL_CAP_USD = "1000"            # paper 1K USD (smoke PASS sonrasi)
    Write-Host "[SMOKE] PAPER MODE: capital_cap=1000 USD" -ForegroundColor Yellow
} else {
    $env:PA_CAPITAL_CAP_USD = "100"             # smoke 100 USD
    Write-Host "[SMOKE] TESTNET MODE: capital_cap=100 USD" -ForegroundColor Cyan
}

Write-Host "=" * 70 -ForegroundColor DarkGray
Write-Host "SEC54.6d Testnet Smoke - 7g monitoring" -ForegroundColor Green
Write-Host "  Bot   : $($env:PA_BOT_NAME)" -ForegroundColor Green
Write-Host "  Mode  : $($env:PA_RUN_MODE) | LIVE_CONFIRM=$($env:PA_LIVE_CONFIRM)" -ForegroundColor Green
Write-Host "  Cap   : `$$($env:PA_CAPITAL_CAP_USD) USD" -ForegroundColor Green
Write-Host "=" * 70 -ForegroundColor DarkGray

# -- Pre-flight checks ----------------------------------------------------------
Write-Host "`n[PREFLIGHT] Checking environment..." -ForegroundColor Yellow

# .env dosyasi
$envPath = Join-Path $ROOT ".env"
if (-not (Test-Path $envPath)) {
    Write-Error "[PREFLIGHT FAIL] .env dosyasi bulunamadi: $envPath"
    exit 1
}

# Python
try {
    $pyver = python --version 2>&1
    Write-Host "  python: $pyver" -ForegroundColor Gray
} catch {
    Write-Error "[PREFLIGHT FAIL] python bulunamadi"
    exit 1
}

# Migration apply (idempotent - zaten uygulanmis olabilir)
Write-Host "`n[MIGRATION] DuckDB pyramid_leg migration apply (idempotent)..." -ForegroundColor Yellow
python -c @"
import duckdb, sys
journals = [
    'data/futures_journal.duckdb',
    'data/futures_journal_phoenix.duckdb',
]
stmts = [
    '''CREATE TABLE IF NOT EXISTS futures_orders (
        order_id VARCHAR PRIMARY KEY, signal_id VARCHAR, ts TIMESTAMP,
        symbol VARCHAR, side VARCHAR, strategy VARCHAR, order_type VARCHAR,
        qty DOUBLE, price DOUBLE, status VARCHAR, exchange_order_id VARCHAR,
        client_order_id VARCHAR, fill_price DOUBLE, fill_qty DOUBLE,
        fee_usdt DOUBLE, slippage_bps DOUBLE, mode VARCHAR, notes VARCHAR
    )''',
    'ALTER TABLE futures_orders ADD COLUMN IF NOT EXISTS parent_position_id VARCHAR',
    'ALTER TABLE futures_orders ADD COLUMN IF NOT EXISTS pyramid_leg_num INTEGER',
]
ok = True
for j in journals:
    try:
        con = duckdb.connect(j)
        for s in stmts:
            con.execute(s)
        con.commit()
        con.close()
        print(f'  OK: {j}')
    except Exception as e:
        print(f'  ERR: {j}: {e}')
        ok = False
sys.exit(0 if ok else 1)
"@
if ($LASTEXITCODE -ne 0) {
    Write-Error "[MIGRATION FAIL] DuckDB migration hatasi. Detay icin log'a bakin."
    exit 1
}
Write-Host "[MIGRATION] OK" -ForegroundColor Green

# Regime features freshness check
Write-Host "`n[REGIME] Features freshness check..." -ForegroundColor Yellow
$featPath = Join-Path $ROOT "data\regime_features_latest.parquet"
if (Test-Path $featPath) {
    $age = (Get-Date) - (Get-Item $featPath).LastWriteTime
    if ($age.TotalHours -gt 24) {
        Write-Host "  [WARN] regime_features_latest.parquet ${([int]$age.TotalHours)}h eskimis - refresh baslatiliyor..." -ForegroundColor Yellow
        python (Join-Path $ROOT "scripts\regime_features_refresh.py") 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [WARN] regime_features_refresh hata verdi - fail-safe ALLOW aktif (smoke devam)" -ForegroundColor Yellow
        } else {
            Write-Host "  [OK] Regime features yenilendi" -ForegroundColor Green
        }
    } else {
        Write-Host "  [OK] regime_features_latest.parquet $([int]$age.TotalMinutes)dk eskimis (24h limitin icinde)" -ForegroundColor Green
    }
} else {
    Write-Host "  [WARN] regime_features_latest.parquet yok - fail-safe ALLOW aktif" -ForegroundColor Yellow
    Write-Host "  Backfill icin: python scripts\regime_features_refresh.py" -ForegroundColor Gray
}

# Kill-switch durumu
$ksPath = Join-Path $ROOT "logs\kill_switch.json"
if (Test-Path $ksPath) {
    $ks = Get-Content $ksPath | ConvertFrom-Json
    if ($ks.halted -eq $true) {
        Write-Host "`n[KILL_SWITCH] AKTIF - reason: $($ks.reason)" -ForegroundColor Red
        Write-Host "Temizlemek icin: Remove-Item '$ksPath' veya icini {halted: false} yap." -ForegroundColor Yellow
        $confirm = Read-Host "Kill-switch'i temizleyip devam etmek istiyor musunuz? (yes/no)"
        if ($confirm -ne "yes") {
            Write-Host "Iptal edildi." -ForegroundColor Red
            exit 1
        }
        '{"halted": false, "reason": ""}' | Set-Content $ksPath -Encoding UTF8
        Write-Host "[KILL_SWITCH] Temizlendi." -ForegroundColor Green
    }
}

# -- DryRun modu ---------------------------------------------------------------
if ($DryRun) {
    Write-Host "`n[DRY-RUN] futures_trade_15m.py --dry-run..." -ForegroundColor Cyan
    python (Join-Path $ROOT "scripts\futures_trade_15m.py") --dry-run
    Write-Host "`n[DRY-RUN] Tamamlandi. Emir gonderilmedi." -ForegroundColor Cyan
    exit 0
}

# -- Cron kurulum bilgisi -------------------------------------------------------
Write-Host "`n[CRON] Windows Task Scheduler kuralum (manuel adimlar):" -ForegroundColor Yellow
Write-Host "  1. Ingest 15m (her 5 dakika):"
Write-Host "     schtasks /Create /SC MINUTE /MO 5 /TN 'PA_ingest_15m' /TR 'python $ROOT\scripts\ingest_15m_live.py' /F"
Write-Host "  2. Regime features refresh (her gun 00:01 UTC):"
Write-Host "     schtasks /Create /SC DAILY /ST 00:01 /TN 'PA_regime_refresh' /TR 'python $ROOT\scripts\regime_features_refresh.py' /F"
Write-Host "  3. Paper gate evaluator (her saat):"
Write-Host "     schtasks /Create /SC HOURLY /TN 'PA_paper_gate' /TR 'python $ROOT\scripts\paper_gate_evaluator.py' /F"
Write-Host "  4. Text dashboard (her 6 saat):"
Write-Host "     schtasks /Create /SC HOURLY /MO 6 /TN 'PA_dashboard' /TR 'python $ROOT\scripts\dashboard_text.py' /F"
Write-Host ""

# -- Daemon launch --------------------------------------------------------------
Write-Host "[LAUNCH] Daemon baslatiliyor..." -ForegroundColor Green
Write-Host "  Komut: python scripts\futures_daemon.py --timeframe 15m" -ForegroundColor Gray
Write-Host "  Durdurmak: Ctrl+C veya echo '{`"halted`": true, `"reason`": `"manual`"}' > logs\kill_switch.json" -ForegroundColor Gray
Write-Host ""

if ($Once) {
    Write-Host "[ONCE] Tek seferlik mod" -ForegroundColor Yellow
    python (Join-Path $ROOT "scripts\futures_daemon.py") --timeframe 15m --once
} else {
    python (Join-Path $ROOT "scripts\futures_daemon.py") --timeframe 15m
}
