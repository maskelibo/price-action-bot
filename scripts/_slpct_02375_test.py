import os, sys
os.environ["PA_LOG_QUIET"]="1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
from pathlib import Path
ROOT=Path("/Users/peyman/price-action-bot")
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"src"))
from scripts import researcher_slpct_threshold_sweep as sw

POOL = ROOT/"data"/"sec53_15m_pool_v11.pkl"
YAML = ROOT/"configs"/"risk_phoenix_scalp_15m_c2v5_final.yaml"
GRID = [0.022, 0.02375, 0.025]   # marjinal taban / ÖNERİ / mevcut
DD = dict(daily_dd=0.02, weekly_dd=0.05)

for bps in (55.0, 100.0):
    print("\n"+"#"*90)
    print(f"# 0.02375 TEST — honest +{int(bps)}bps taker  (gate: mon_mean>0 + DD>=-25 + shuffle_p<0.05)")
    print("#"*90)
    sw.sweep(f"15m@{int(bps)}bps", POOL, YAML, sl_grid=GRID, risk_pct=0.005,
             dd_kwargs=DD, extra_bps=bps, n_shuffle=20)
