"""PHOENIX bugün/son 30g scan diagnostic.

Her sembol × her strateji için bugün ve geçmiş 30 gün sinyal yoğunluğu.
'Bot bugün hiç sinyal bulamadı mı, normal mi?' sorusunun cevabı.
"""
import os, sys
os.environ['PA_BOT_NAME'] = 'phoenix'
os.environ['PA_LOG_QUIET'] = '1'
sys.path.insert(0, '.'); sys.path.insert(0, 'src')

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import logging
logging.getLogger('price_action').setLevel(logging.ERROR)
import warnings; warnings.filterwarnings('ignore')
from datetime import datetime, timezone, timedelta
import pandas as pd

from scripts.paper_trade_daily import TOP_11, SYMBOLS
from scripts.run_real_backtest import _load_symbol_ohlcv
from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore

print('=' * 80)
print(f'🔥 PHOENIX Scan Diagnostic — {datetime.now(timezone.utc).date()}')
print('=' * 80)
print(f'Pool: {len(TOP_11)} strateji × {len(SYMBOLS)} sembol = {len(TOP_11)*len(SYMBOLS)} hücre')
print(f'Strateji listesi: {[s[0] for s in TOP_11]}')
print()

today = datetime.now(timezone.utc).date()
last_30 = today - timedelta(days=30)

# Her strateji × sembol için engine çalıştır, son 30g sinyal sayısını topla
print('Her strateji × sembol için son 30 gün sinyal yoğunluğu:')
print('(bos hucre = 0 sinyal, sayi = son 30g sinyal sayisi)')
print()
print(f'{"":25s}', end='')
for sym in SYMBOLS:
    short = sym.split('/')[0][:4]
    print(f'{short:>6s}', end='')
print(f'  {"TOPLAM":>7s}')
print('-' * (25 + 6 * len(SYMBOLS) + 9))

grand_total = 0
today_total = 0
sym_totals = {s: 0 for s in SYMBOLS}
for module_name, class_name in TOP_11:
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name, None)
        if cls is None:
            for n in dir(mod):
                if n.endswith('Strategy') and not n.startswith('_'):
                    cls = getattr(mod, n); break
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn or not cls: continue
        s = cls(manifest_fn())
    except Exception as e:
        print(f'{module_name:25s} SKIP ({e})')
        continue

    row = f'{module_name[:25]:25s}'
    strat_total = 0
    for sym in SYMBOLS:
        try:
            df = _load_symbol_ohlcv(sym, tf='1d')
            if df is None or df.empty:
                row += f'{"-":>6s}'; continue
            df = df.sort_values('ts').reset_index(drop=True)
            df['symbol'] = sym; df['venue'] = 'binance'; df['timeframe'] = '1d'
            try:
                df['vol_z_pre'] = volume_zscore(df['volume'], period=20)
            except Exception:
                df['vol_z_pre'] = 0
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(s, [sym], start=df['ts'].iloc[0].to_pydatetime(),
                     end=df['ts'].iloc[-1].to_pydatetime(), timeframe='1d',
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            # Son 30 gün içindeki sinyal sayısı
            if r.trades is not None and len(r.trades) > 0:
                trade_dates = pd.to_datetime(r.trades['entry_ts']).dt.date
                count_30d = sum(1 for d in trade_dates if last_30 <= d <= today)
                count_today = sum(1 for d in trade_dates if d == today - timedelta(days=1))
                strat_total += count_30d
                sym_totals[sym] += count_30d
                today_total += count_today
                if count_30d > 0:
                    marker = f'{count_30d}'
                    if count_today > 0:
                        marker = f'{count_30d}*'  # * = bugün de var
                    row += f'{marker:>6s}'
                else:
                    row += f'{"":>6s}'
            else:
                row += f'{"":>6s}'
        except Exception:
            row += f'{"?":>6s}'
    grand_total += strat_total
    row += f'  {strat_total:>7d}'
    print(row)

print('-' * (25 + 6 * len(SYMBOLS) + 9))
print(f'{"SEMBOL TOPLAMI":25s}', end='')
for sym in SYMBOLS:
    print(f'{sym_totals[sym]:>6d}', end='')
print(f'  {grand_total:>7d}')
print()
print(f'TOPLAM SON 30 GÜN: {grand_total} sinyal')
print(f'BUGÜN (2026-05-14 kapanış): {today_total} sinyal')
print(f'Günlük ortalama: {grand_total/30:.1f} sinyal')
print()
if today_total == 0:
    print(f'❓ BUGÜN HİÇ SİNYAL YOK')
    if grand_total > 0:
        print(f'   Son 30g ortalama: {grand_total/30:.1f}/gün — bugün anomalı değil, doğal varyasyon')
    else:
        print(f'   Son 30g toplam: 0 sinyal — POOL PROBLEMATIK (debug gerek)')
else:
    print(f'✅ Bugün {today_total} sinyal bulundu (* işaretliler)')
