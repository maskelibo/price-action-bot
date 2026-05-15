"""Trading Bot Dashboard — Streamlit UI (v2.0 — Futures + UI overhaul)

Sayfalar:
  Genel Bakış · İşlemler · Pozisyonlar · Equity · Strateji · Spot Testnet · Futures · Backtest

Çalıştır:
    streamlit run scripts/dashboard.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

PAPER_JOURNAL = ROOT / "data" / "paper_journal.duckdb"
TESTNET_JOURNAL = ROOT / "data" / "testnet_journal.duckdb"
FUTURES_JOURNAL = ROOT / "data" / "futures_journal.duckdb"
PAPER_STATE = ROOT / "logs" / "execution" / "paper_state.json"

# ============================================================
# Page config
# ============================================================
st.set_page_config(
    page_title="Price Action Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Compact dark CSS
st.markdown("""
<style>
/* Compact main padding */
.block-container { padding-top: 1.2rem !important; padding-bottom: 1rem !important; max-width: 100% !important; }

/* Sidebar tighter */
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%); }
section[data-testid="stSidebar"] * { color: #e2e8f0; }
section[data-testid="stSidebar"] .stRadio label { padding: 4px 8px; border-radius: 6px; }
section[data-testid="stSidebar"] hr { margin: 0.5rem 0 !important; border-color: #334155; }
section[data-testid="stSidebar"] [data-testid="stMetricValue"] { color: #f1f5f9 !important; font-size: 1.15rem !important; }
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { color: #94a3b8 !important; }

/* Metric cards — compact, modern */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 12px 16px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
[data-testid="stMetricValue"] { font-size: 1.5rem !important; font-weight: 700; color: #f1f5f9; }
[data-testid="stMetricLabel"] { font-size: 0.78rem !important; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }

/* Title / subheader compact */
h1 { font-size: 1.6rem !important; margin-bottom: 0.5rem !important; padding-bottom: 0 !important; color: #f1f5f9 !important; }
h2 { font-size: 1.25rem !important; margin-top: 1rem !important; margin-bottom: 0.4rem !important; color: #e2e8f0 !important; border-bottom: 2px solid #334155; padding-bottom: 4px; }
h3 { font-size: 1.05rem !important; margin-top: 0.5rem !important; color: #cbd5e1 !important; }

/* Dataframe style */
.stDataFrame { border: 1px solid #334155 !important; border-radius: 8px !important; }
.stDataFrame [data-testid="stDataFrameResizable"] { background: #0f172a !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap: 4px; background: transparent; }
.stTabs [data-baseweb="tab"] { background: #1e293b; border-radius: 6px 6px 0 0; padding: 8px 16px; font-weight: 500; }
.stTabs [aria-selected="true"] { background: #2563eb !important; color: white !important; }

/* Divider tighter */
hr { margin: 0.6rem 0 !important; }

/* Status pill */
.pill { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; margin-left: 6px; }
.pill-live { background: #16a34a; color: white; }
.pill-stop { background: #dc2626; color: white; }
.pill-warn { background: #ca8a04; color: white; }
.pill-info { background: #2563eb; color: white; }

/* Reduce top whitespace from header */
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
.stDeployButton { display: none; }

/* Plotly chart container */
.js-plotly-plot { border-radius: 8px; overflow: hidden; }

/* Info/success/warning compact */
[data-testid="stAlert"] { padding: 10px 14px !important; border-radius: 8px !important; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# Auto-refresh + cache
# ============================================================
import time as _time
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = _time.time()
if _time.time() - st.session_state.last_refresh > 5:
    st.session_state.last_refresh = _time.time()
    st.cache_data.clear()


# ============================================================
# Data loaders
# ============================================================
@st.cache_data(ttl=5)
def load_paper_state():
    if not PAPER_STATE.exists():
        return None
    return json.loads(PAPER_STATE.read_text(encoding='utf-8'))


@st.cache_data(ttl=5)
def _query(db: Path, sql: str) -> pd.DataFrame:
    if not db.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(db), read_only=True)
    try:
        df = con.execute(sql).fetchdf()
    except Exception:
        df = pd.DataFrame()
    con.close()
    return df


def load_paper_signals(): return _query(PAPER_JOURNAL, "SELECT * FROM paper_signals ORDER BY ts DESC")
def load_paper_events():  return _query(PAPER_JOURNAL, "SELECT * FROM paper_position_events ORDER BY ts DESC")
def load_paper_equity():  return _query(PAPER_JOURNAL, "SELECT * FROM paper_equity_snapshots ORDER BY ts")
def load_testnet_signals(): return _query(TESTNET_JOURNAL, "SELECT * FROM testnet_signals ORDER BY ts DESC")
def load_testnet_oco(): return _query(TESTNET_JOURNAL, "SELECT * FROM testnet_oco_orders ORDER BY ts DESC")
def load_testnet_equity(): return _query(TESTNET_JOURNAL, "SELECT * FROM testnet_equity_snapshots ORDER BY ts")
def load_futures_signals(): return _query(FUTURES_JOURNAL, "SELECT * FROM futures_signals ORDER BY ts DESC")
def load_futures_protection(): return _query(FUTURES_JOURNAL, "SELECT * FROM futures_protection_orders ORDER BY ts DESC")
def load_futures_equity(): return _query(FUTURES_JOURNAL, "SELECT * FROM futures_equity_snapshots ORDER BY ts")


@st.cache_data(ttl=20)
def fetch_spot_balance():
    try:
        import ccxt
        ex = ccxt.binance({
            'apiKey': os.getenv('BINANCE_TESTNET_API_KEY'),
            'secret': os.getenv('BINANCE_TESTNET_API_SECRET'),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot', 'warnOnFetchOpenOrdersWithoutSymbol': False},
        })
        ex.set_sandbox_mode(True)
        bal = ex.fetch_balance()
        return {k: v for k, v in bal['total'].items() if v > 0.0001}
    except Exception as e:
        return {"_error": str(e)}


@st.cache_data(ttl=15)
def fetch_futures_state_cached():
    try:
        from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state
        ex = get_futures_exchange()
        return fetch_futures_state(ex)
    except Exception as e:
        return {"_error": str(e)}


# ============================================================
# Helpers
# ============================================================
def daemon_status(log_path: Path, max_age_seconds: int = 180) -> str:
    """Log dosyasının son değişiklik zamanına göre status."""
    if not log_path.exists():
        return "stop"
    age = _time.time() - log_path.stat().st_mtime
    if age < max_age_seconds:
        return "live"
    elif age < max_age_seconds * 3:
        return "warn"
    return "stop"


def status_pill(label: str, status: str) -> str:
    cls = {"live": "pill-live", "warn": "pill-warn", "stop": "pill-stop", "info": "pill-info"}.get(status, "pill-info")
    text = {"live": "LIVE", "warn": "STALE", "stop": "OFF", "info": "INFO"}.get(status, status.upper())
    return f'<span class="pill {cls}">{label}: {text}</span>'


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.markdown("### ⚡ Price Action Bot")
    st.caption("v2.0.4 · Production")

    page = st.radio(
        "Sayfa",
        ["📊 Genel Bakış", "🚀 Futures (Live)", "🔌 Spot Testnet", "📜 İşlemler",
         "📍 Pozisyonlar", "📈 Equity", "🎯 Strateji", "🧪 Backtest"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    # Daemon status
    spot_log = ROOT / "logs" / "testnet_daemon.log"
    fut_log = ROOT / "logs" / "futures_daemon.log"
    spot_st = daemon_status(spot_log)
    fut_st = daemon_status(fut_log)

    st.markdown("**Daemon**")
    st.markdown(status_pill("Spot", spot_st) + "<br>" + status_pill("Futures", fut_st), unsafe_allow_html=True)

    st.markdown("---")

    # Quick balance summary
    st.markdown("**Bakiye (Live)**")
    fut_state = fetch_futures_state_cached()
    if "_error" not in fut_state:
        st.metric("🚀 Futures", f"${fut_state['wallet_balance']:,.0f}",
                  delta=f"{fut_state['unrealized_pnl']:+.2f}")
        st.metric("📍 Pozisyon", f"{fut_state['n_positions']}",
                  delta=f"{fut_state['n_algo_orders']} TP/SL")

    spot_bal = fetch_spot_balance()
    if "_error" not in spot_bal:
        usdt = spot_bal.get('USDT', 0)
        st.metric("🔌 Spot USDT", f"${usdt:,.0f}")

    st.markdown("---")
    if st.button("🔄 Yenile", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"⏱ {datetime.now().strftime('%H:%M:%S')}")


# ============================================================
# Page 1: Genel Bakış
# ============================================================
if page == "📊 Genel Bakış":
    st.title("📊 Genel Bakış")

    fut_state = fetch_futures_state_cached()
    spot_bal = fetch_spot_balance()
    spot_usdt = spot_bal.get('USDT', 0) if "_error" not in spot_bal else 0

    # Top metrics — 5 kart bir satır
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        if "_error" not in fut_state:
            wallet = fut_state['wallet_balance']
            st.metric("🚀 Futures Wallet", f"${wallet:,.2f}",
                      delta=f"${wallet-5000:+,.0f} vs $5k")
        else:
            st.metric("🚀 Futures", "N/A")
    with c2:
        if "_error" not in fut_state:
            st.metric("📊 Unrealized PnL", f"${fut_state['unrealized_pnl']:+,.2f}",
                      delta=f"{fut_state['n_positions']} açık poz")
    with c3:
        st.metric("🔌 Spot USDT", f"${spot_usdt:,.2f}",
                  delta=f"${spot_usdt-10000:+,.0f} vs $10k")
    with c4:
        if "_error" not in fut_state:
            st.metric("🎯 Algo Orders", f"{fut_state['n_algo_orders']}",
                      delta="TP+SL koruma", delta_color="off")
    with c5:
        sigs = load_futures_signals()
        n_filled = len(sigs[sigs['status'] == 'filled']) if not sigs.empty else 0
        st.metric("📜 Futures Trade", f"{n_filled}",
                  delta=f"{len(sigs)} toplam sinyal", delta_color="off")

    # Equity Curves
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🚀 Futures Equity")
        eq_f = load_futures_equity()
        if not eq_f.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=eq_f['ts'], y=eq_f['wallet_balance'],
                mode='lines', name='Wallet',
                line=dict(color='#22c55e', width=2),
                fill='tozeroy', fillcolor='rgba(34,197,94,0.1)',
            ))
            fig.add_hline(y=5000, line_dash="dash", line_color="gray", annotation_text="$5k başlangıç")
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=20),
                              hovermode='x unified', plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                              font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
                              yaxis=dict(gridcolor='#1e293b', tickformat='$,.0f'))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Henüz equity snapshot yok (ilk 5dk sonra)")

    with col2:
        st.subheader("🔌 Spot Equity")
        eq_s = load_testnet_equity()
        if not eq_s.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=eq_s['ts'], y=eq_s['total_value_usdt'],
                mode='lines', name='Total',
                line=dict(color='#3b82f6', width=2),
                fill='tozeroy', fillcolor='rgba(59,130,246,0.1)',
            ))
            fig.add_hline(y=10000, line_dash="dash", line_color="gray", annotation_text="$10k başlangıç")
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=20),
                              hovermode='x unified', plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                              font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
                              yaxis=dict(gridcolor='#1e293b', tickformat='$,.0f'))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Henüz equity snapshot yok")

    # Latest activity
    st.subheader("⚡ Son Aktivite")
    fut_sigs = load_futures_signals()
    if not fut_sigs.empty:
        recent = fut_sigs.head(8).copy()
        recent['ts'] = pd.to_datetime(recent['ts']).dt.strftime('%m-%d %H:%M')
        cols_show = ['ts', 'symbol', 'strategy', 'side', 'leverage', 'fill_price', 'notional_usdt', 'status']
        cols_avail = [c for c in cols_show if c in recent.columns]
        st.dataframe(recent[cols_avail], use_container_width=True, hide_index=True, height=300)
    else:
        st.info("Henüz futures trade yok")


# ============================================================
# Page 2: Futures (Live)
# ============================================================
elif page == "🚀 Futures (Live)":
    st.title("🚀 Futures Testnet Live")
    st.caption("Binance USDM Futures Testnet · long+short+lev 3x · TP/SL Binance tarafında")

    fut_state = fetch_futures_state_cached()
    if "_error" in fut_state:
        st.error(f"Bağlantı hatası: {fut_state['_error']}")
        st.stop()

    # Üst metrik bar
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 Wallet", f"${fut_state['wallet_balance']:,.2f}",
              delta=f"${fut_state['wallet_balance']-5000:+,.2f}")
    c2.metric("💵 Available", f"${fut_state['available_balance']:,.2f}")
    c3.metric("📊 Unrealized PnL", f"${fut_state['unrealized_pnl']:+,.2f}")
    c4.metric("📍 Pozisyon", fut_state['n_positions'])
    c5.metric("🎯 Algo Orders", fut_state['n_algo_orders'], delta="TP+SL", delta_color="off")

    # Pozisyonlar
    st.subheader("📍 Açık Pozisyonlar")
    if fut_state['positions']:
        pos_data = []
        for p in fut_state['positions']:
            sym = p.get('symbol', '?').replace('/USDT:USDT', '').replace('/USDT', '')
            qty = abs(float(p.get('contracts', 0)))
            entry = float(p.get('entryPrice', 0))
            mark = float(p.get('markPrice', 0))
            pnl = float(p.get('unrealizedPnl', 0))
            pnl_pct = (pnl / (entry * qty / 3) * 100) if entry > 0 else 0  # leverage 3x
            notional = qty * mark
            pos_data.append({
                'Sembol': sym,
                'Yön': '🔻 SHORT' if p.get('side') == 'short' else '🔺 LONG',
                'Qty': f"{qty:.4f}",
                'Entry': f"${entry:,.4f}",
                'Mark': f"${mark:,.4f}",
                'Notional': f"${notional:,.2f}",
                'PnL $': f"${pnl:+,.2f}",
                'PnL %': f"{pnl_pct:+.2f}%",
            })
        df_pos = pd.DataFrame(pos_data)
        st.dataframe(df_pos, use_container_width=True, hide_index=True)
    else:
        st.info("Açık pozisyon yok")

    # Algo (TP/SL) orders
    st.subheader("🎯 Algo Orders (TP+SL)")
    if fut_state['algo_orders']:
        algo_data = []
        for o in fut_state['algo_orders']:
            algo_data.append({
                'Sembol': o.get('symbol', '?'),
                'Tip': '🎯 TP' if o.get('orderType') == 'TAKE_PROFIT_MARKET' else '🛡️ SL',
                'Yön': o.get('side', '?'),
                'Qty': float(o.get('quantity', 0)),
                'Trigger': f"${float(o.get('triggerPrice', 0)):,.4f}",
                'Status': o.get('algoStatus', '?'),
            })
        df_algo = pd.DataFrame(algo_data).sort_values(['Sembol', 'Tip'])
        st.dataframe(df_algo, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("Algo order yok")

    # Equity Curve
    st.subheader("📈 Wallet Curve")
    eq_f = load_futures_equity()
    if not eq_f.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq_f['ts'], y=eq_f['wallet_balance'],
            mode='lines+markers', name='Wallet',
            line=dict(color='#22c55e', width=2.5),
            marker=dict(size=4),
            fill='tozeroy', fillcolor='rgba(34,197,94,0.08)',
        ))
        fig.add_hline(y=5000, line_dash="dash", line_color="#475569", annotation_text="$5k başlangıç")
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=20),
                          hovermode='x unified', plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                          font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
                          yaxis=dict(gridcolor='#1e293b', tickformat='$,.0f'))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Equity snapshot daha yok (5dk içinde gelir)")

    # Trade history
    st.subheader("📜 Trade Geçmişi")
    sigs = load_futures_signals()
    if not sigs.empty:
        sigs_show = sigs.copy()
        sigs_show['ts'] = pd.to_datetime(sigs_show['ts']).dt.strftime('%m-%d %H:%M')
        cols = ['ts', 'symbol', 'strategy', 'side', 'leverage', 'fill_price',
                'fill_qty', 'notional_usdt', 'margin_usdt', 'status']
        cols_avail = [c for c in cols if c in sigs_show.columns]
        st.dataframe(sigs_show[cols_avail].head(50), use_container_width=True,
                     hide_index=True, height=400)
    else:
        st.info("Henüz trade yok")


# ============================================================
# Page 3: Spot Testnet
# ============================================================
elif page == "🔌 Spot Testnet":
    st.title("🔌 Spot Testnet")
    st.caption("Binance Spot Testnet · sadece long · OCO TP+SL")

    bal = fetch_spot_balance()
    if "_error" in bal:
        st.error(f"Bağlantı: {bal['_error']}")
        st.stop()

    # Top metrics
    usdt = bal.get('USDT', 0)
    n_currency = len([k for k in bal.keys() if k != 'USDT'])

    c1, c2, c3 = st.columns(3)
    c1.metric("💵 USDT Bakiye", f"${usdt:,.2f}", delta=f"${usdt-10000:+,.0f}")
    c2.metric("🪙 Coin Tutuyor", n_currency)
    c3.metric("📊 Toplam Currency", len(bal))

    # Bakiye + güncel değer
    st.subheader("💰 Bakiye Detay")
    if bal:
        df_bal = pd.DataFrame([
            {'Currency': k, 'Amount': v} for k, v in bal.items() if v > 0.0001
        ]).sort_values('Amount', ascending=False).head(20)
        st.dataframe(df_bal, use_container_width=True, hide_index=True)

    # OCO orders
    st.subheader("🎯 Aktif OCO Orderları")
    oco = load_testnet_oco()
    if not oco.empty:
        active = oco[oco['status'] == 'placed'].copy()
        if not active.empty:
            active['ts'] = pd.to_datetime(active['ts']).dt.strftime('%m-%d %H:%M')
            st.dataframe(
                active[['ts', 'symbol', 'qty', 'tp_price', 'sl_trigger', 'sl_limit']].rename(columns={
                    'ts': 'Açılış', 'symbol': 'Sembol', 'qty': 'Qty',
                    'tp_price': 'TP', 'sl_trigger': 'SL Trigger', 'sl_limit': 'SL Limit'
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Aktif OCO yok")
    else:
        st.info("OCO geçmişi yok")

    # Trade history
    st.subheader("📜 Spot Trade Geçmişi")
    tn_sig = load_testnet_signals()
    if not tn_sig.empty:
        tn_sig['ts'] = pd.to_datetime(tn_sig['ts']).dt.strftime('%m-%d %H:%M')
        st.dataframe(
            tn_sig[['ts', 'symbol', 'strategy', 'side', 'status', 'fill_price', 'fill_qty', 'cost_usdt']].head(50),
            use_container_width=True, hide_index=True, height=400,
        )


# ============================================================
# Page 4: İşlemler
# ============================================================
elif page == "📜 İşlemler":
    st.title("📜 Tüm İşlemler")

    tab1, tab2, tab3 = st.tabs(["🚀 Futures", "🔌 Spot", "📦 Paper Sim"])

    with tab1:
        sigs = load_futures_signals()
        if sigs.empty:
            st.info("Henüz futures trade yok")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                st_f = ['Hepsi'] + sorted(sigs['status'].unique().tolist())
                f_status = st.selectbox("Status", st_f, key='fst')
            with c2:
                sym_f = ['Hepsi'] + sorted(sigs['symbol'].unique().tolist())
                f_sym = st.selectbox("Sembol", sym_f, key='fsy')
            with c3:
                str_f = ['Hepsi'] + sorted(sigs['strategy'].unique().tolist())
                f_str = st.selectbox("Strateji", str_f, key='fsr')

            f = sigs.copy()
            if f_status != 'Hepsi': f = f[f['status'] == f_status]
            if f_sym != 'Hepsi': f = f[f['symbol'] == f_sym]
            if f_str != 'Hepsi': f = f[f['strategy'] == f_str]

            st.write(f"**{len(f)}** sinyal · {len(sigs)} toplam")
            f['ts'] = pd.to_datetime(f['ts']).dt.strftime('%Y-%m-%d %H:%M')
            cols = ['ts', 'symbol', 'strategy', 'side', 'leverage', 'fill_price',
                    'sl_price', 'tp_price', 'notional_usdt', 'status', 'notes']
            cols_avail = [c for c in cols if c in f.columns]
            st.dataframe(f[cols_avail], use_container_width=True, hide_index=True, height=550)

    with tab2:
        tn = load_testnet_signals()
        if tn.empty:
            st.info("Henüz spot trade yok")
        else:
            c1, c2 = st.columns(2)
            f_st = c1.selectbox("Status", ['Hepsi'] + sorted(tn['status'].unique().tolist()), key='tnst')
            f_sym = c2.selectbox("Sembol", ['Hepsi'] + sorted(tn['symbol'].unique().tolist()), key='tnsy')
            f = tn.copy()
            if f_st != 'Hepsi': f = f[f['status'] == f_st]
            if f_sym != 'Hepsi': f = f[f['symbol'] == f_sym]
            st.write(f"**{len(f)}** sinyal")
            f['ts'] = pd.to_datetime(f['ts']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(f, use_container_width=True, hide_index=True, height=500)

    with tab3:
        events = load_paper_events()
        if events.empty:
            st.info("Paper sim event yok")
        else:
            ev_types = ['Hepsi'] + sorted(events['event_type'].unique().tolist())
            ev_filter = st.selectbox("Event Type", ev_types, key='pev')
            f = events if ev_filter == 'Hepsi' else events[events['event_type'] == ev_filter]
            st.write(f"**{len(f)}** event")
            st.dataframe(f, use_container_width=True, hide_index=True, height=500)


# ============================================================
# Page 5: Pozisyonlar
# ============================================================
elif page == "📍 Pozisyonlar":
    st.title("📍 Aktif Pozisyonlar")

    tab1, tab2 = st.tabs(["🚀 Futures", "🔌 Spot"])

    with tab1:
        fut_state = fetch_futures_state_cached()
        if "_error" in fut_state:
            st.error(fut_state['_error'])
        elif fut_state['positions']:
            data = []
            total_pnl = 0
            total_notional = 0
            for p in fut_state['positions']:
                sym = p.get('symbol', '?').replace('/USDT:USDT', '').replace('/USDT', '')
                qty = abs(float(p.get('contracts', 0)))
                entry = float(p.get('entryPrice', 0))
                mark = float(p.get('markPrice', 0))
                pnl = float(p.get('unrealizedPnl', 0))
                notional = qty * mark
                total_pnl += pnl
                total_notional += notional
                data.append({
                    'Sembol': sym,
                    'Yön': p.get('side', '?').upper(),
                    'Qty': f"{qty:.4f}",
                    'Entry': f"${entry:,.4f}",
                    'Mark': f"${mark:,.4f}",
                    'Notional': f"${notional:,.2f}",
                    'PnL': f"${pnl:+.2f}",
                    'Margin': f"${notional/3:.2f}",
                })
            c1, c2, c3 = st.columns(3)
            c1.metric("📍 Pozisyon", len(data))
            c2.metric("💼 Toplam Notional", f"${total_notional:,.0f}")
            c3.metric("📊 Toplam PnL", f"${total_pnl:+,.2f}")
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.info("Açık pozisyon yok")

    with tab2:
        bal = fetch_spot_balance()
        if "_error" not in bal:
            data = []
            for ccy, amt in sorted(bal.items(), key=lambda x: -x[1]):
                if amt > 0.0001 and ccy != 'USDT':
                    data.append({'Currency': ccy, 'Amount': amt})
            if data:
                st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
            else:
                st.info("Sadece USDT bakiye, açık coin yok")


# ============================================================
# Page 6: Equity
# ============================================================
elif page == "📈 Equity":
    st.title("📈 Equity Curves")

    eq_f = load_futures_equity()
    eq_s = load_testnet_equity()

    fig = go.Figure()
    if not eq_f.empty:
        fig.add_trace(go.Scatter(
            x=eq_f['ts'], y=eq_f['wallet_balance'],
            mode='lines', name='🚀 Futures Wallet',
            line=dict(color='#22c55e', width=2.5),
        ))
    if not eq_s.empty:
        fig.add_trace(go.Scatter(
            x=eq_s['ts'], y=eq_s['total_value_usdt'],
            mode='lines', name='🔌 Spot Total',
            line=dict(color='#3b82f6', width=2.5),
        ))
    fig.update_layout(
        height=450, margin=dict(l=10, r=10, t=30, b=20),
        hovermode='x unified', plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
        font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
        yaxis=dict(gridcolor='#1e293b', tickformat='$,.0f'),
        legend=dict(bgcolor='#1e293b', bordercolor='#334155', borderwidth=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    if not eq_f.empty:
        st.subheader("🚀 Futures Snapshot Tablosu")
        eq_f_show = eq_f.copy().tail(30).iloc[::-1]
        eq_f_show['ts'] = pd.to_datetime(eq_f_show['ts']).dt.strftime('%m-%d %H:%M')
        st.dataframe(eq_f_show, use_container_width=True, hide_index=True, height=300)


# ============================================================
# Page 7: Strateji
# ============================================================
elif page == "🎯 Strateji":
    st.title("🎯 Strateji Performansı")

    sigs = load_futures_signals()
    if sigs.empty:
        st.info("Henüz futures sinyal yok")
    else:
        st.subheader("📊 Strateji Bazında Sinyal Dağılımı")
        by_strat = sigs.groupby('strategy').agg(
            n_signal=('signal_id', 'count'),
            n_filled=('status', lambda x: (x == 'filled').sum()),
            avg_notional=('notional_usdt', 'mean'),
        ).sort_values('n_signal', ascending=False)
        st.dataframe(by_strat, use_container_width=True)

        # Side dağılımı
        st.subheader("⚖️ Long vs Short")
        side_counts = sigs[sigs['status'] == 'filled'].groupby('side').size().reset_index(name='count')
        if not side_counts.empty:
            fig = px.pie(side_counts, values='count', names='side',
                         color='side', color_discrete_map={'long': '#22c55e', 'short': '#ef4444'},
                         hole=0.5)
            fig.update_layout(height=350, plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                              font_color='#e2e8f0')
            st.plotly_chart(fig, use_container_width=True)

        # Sembol dağılımı
        st.subheader("🪙 Sembol Bazında")
        by_sym = sigs[sigs['status'] == 'filled'].groupby('symbol').size().reset_index(name='trade')
        if not by_sym.empty:
            fig = px.bar(by_sym.sort_values('trade', ascending=True), x='trade', y='symbol',
                         orientation='h', color='trade', color_continuous_scale='viridis')
            fig.update_layout(height=400, plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                              font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
                              yaxis=dict(gridcolor='#1e293b'))
            st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Page 8: Backtest
# ============================================================
elif page == "🧪 Backtest":
    st.title("🧪 Backtest Beklenti vs Live Gerçek")

    fut_state = fetch_futures_state_cached()
    fut_eq = fut_state.get('wallet_balance', 5000) if "_error" not in fut_state else 5000
    fut_ret = (fut_eq / 5000 - 1) * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Backtest Yıllık", "+%239.5", delta="v2.0.3 production")
    c2.metric("Futures Şu An", f"{fut_ret:+.2f}%", delta=f"${fut_eq-5000:+.0f}")
    c3.metric("Hedef Yıllık", "+%150-200", delta="60-90 gün")
    c4.metric("Sürüm", "v2.0.4", delta="futures live")

    st.subheader("📊 Sürüm Yolculuğu")
    history = pd.DataFrame([
        {"v": "v0.9.7", "yıllık": 33.6, "DD": -32.6, "açıklama": "Production lock başlangıç"},
        {"v": "v1.1.0", "yıllık": 37.5, "DD": -31.8, "açıklama": "monthly_dd 15→8"},
        {"v": "v1.2.0", "yıllık": 51.2, "DD": -34.2, "açıklama": "tp2_R 2→1.5 + FVG"},
        {"v": "v1.3.0", "yıllık": 60.2, "DD": -33.4, "açıklama": "mdd 8→6 + halt 21g"},
        {"v": "v1.4.0", "yıllık": 67.8, "DD": -34.8, "açıklama": "max_concurrent 8→12"},
        {"v": "v1.5.0", "yıllık": 116.3, "DD": -34.9, "açıklama": "side-cond + force-exit"},
        {"v": "v1.5.1", "yıllık": 136.2, "DD": -38.6, "açıklama": "PURE side-cond"},
        {"v": "v2.0.3", "yıllık": 239.5, "DD": -38.7, "açıklama": "Pyramid + SEC16 fix"},
        {"v": "v2.0.4", "yıllık": 239.5, "DD": -38.7, "açıklama": "Futures live deploy"},
    ])
    fig = go.Figure()
    fig.add_trace(go.Bar(x=history['v'], y=history['yıllık'],
                         marker_color='#3b82f6', name='Yıllık %',
                         text=history['yıllık'].apply(lambda x: f"%{x:.1f}"),
                         textposition='outside'))
    fig.update_layout(height=380, plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                      font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
                      yaxis=dict(gridcolor='#1e293b'),
                      margin=dict(l=10, r=10, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(history, use_container_width=True, hide_index=True)

    st.subheader("📉 Drawdown Karşılaştırma")
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=history['v'], y=history['DD'].abs(),
                          marker_color='#ef4444', text=history['DD'].apply(lambda x: f"%{x:.1f}"),
                          textposition='outside'))
    fig2.update_layout(height=300, plot_bgcolor='#0f172a', paper_bgcolor='#0f172a',
                       font_color='#e2e8f0', xaxis=dict(gridcolor='#1e293b'),
                       yaxis=dict(gridcolor='#1e293b'),
                       margin=dict(l=10, r=10, t=20, b=20))
    st.plotly_chart(fig2, use_container_width=True)
