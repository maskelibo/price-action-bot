// Mock data shaped exactly like the FastAPI endpoints in src/price_action/api/server.py
// So Claude Code can swap `MOCK` calls for real fetch('/equity'), /trades, /positions, /signals/pending.

const SYMBOLS_BASE = [
  'BTC','ETH','SOL','BNB','XRP','AVAX','LINK','TON','SUI','APT',
  'INJ','SEI','TIA','ARB','OP','NEAR','DOGE','LTC','ATOM','FIL',
  'RNDR','FET','IMX','LDO','AAVE','UNI','MKR','GMX','PYTH','JTO',
  'WIF','PEPE','BLUR','DYM','STRK','MANTA','ALT','PORTAL','PIXEL','ENA',
  'JUP','W','TAO','ONDO','ETHFI','NOT','IO','ZK','BB','BOME',
  'MEME','FLOKI','BONK','ORDI','SATS','RUNE','TRB','EGLD','ICP','HBAR',
  'XLM','DOT','MATIC','ADA','TRX','ALGO','XTZ','CFX','CKB','NEO',
  'KAS','GALA','SAND','MANA','CHZ','APE','MASK','SUSHI','CRV','COMP',
];

const PATTERNS = [
  { id: 'engulfing_bull', label: 'Bullish Engulfing', dir: 'long' },
  { id: 'engulfing_bear', label: 'Bearish Engulfing', dir: 'short' },
  { id: 'pin_bar_low',    label: 'Pin Bar (rejection low)', dir: 'long' },
  { id: 'pin_bar_high',   label: 'Pin Bar (rejection high)', dir: 'short' },
  { id: 'inside_bar_brk', label: 'Inside Bar Break', dir: 'long' },
  { id: 'morning_star',   label: 'Morning Star', dir: 'long' },
  { id: 'evening_star',   label: 'Evening Star', dir: 'short' },
  { id: 'doji_sr',        label: 'Doji @ S/R', dir: 'long' },
  { id: 'bos_choch',      label: 'BOS / CHoCH', dir: 'long' },
];

// deterministic pseudo-random so screenshots are stable
function mulberry32(a){return function(){let t=a+=0x6D2B79F5;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296}}
const rnd = mulberry32(1337);
const pick = (arr) => arr[Math.floor(rnd()*arr.length)];
const between = (a,b,dec=2) => +(a + rnd()*(b-a)).toFixed(dec);

// ---------------------------------------------------------------- equity curve
function buildEquity(scenario){
  // 90 days of equity points; "exit_ts + equity" — matches /equity response.
  const pts = [];
  let eq = 10000;
  const now = Date.now();
  const day = 86400_000;
  let cum = 0;
  for (let i=90; i>=0; i--){
    const ts = new Date(now - i*day);
    // drift depends on scenario
    let drift;
    if (scenario === 'breaker') drift = i < 8 ? -0.018 - rnd()*0.012 : (rnd()-0.4)*0.02;
    else if (scenario === 'winning') drift = 0.011 + (rnd()-0.45)*0.025;
    else drift = 0.004 + (rnd()-0.5)*0.022;
    eq = eq * (1 + drift);
    cum += eq - 10000;
    pts.push({ ts: ts.toISOString(), equity: +eq.toFixed(2) });
  }
  return pts;
}

// --------------------------------------------------------- open positions list
const POS_TEMPLATES = [
  { symbol: 'BTC/USDT',  side: 'long',  pattern: 'pin_bar_low',    strat: 'classic_pa_v3', confluence: 4.2 },
  { symbol: 'ETH/USDT',  side: 'long',  pattern: 'engulfing_bull', strat: 'classic_pa_v3', confluence: 3.8 },
  { symbol: 'SOL/USDT',  side: 'short', pattern: 'evening_star',   strat: 'momentum_rev',  confluence: 3.5 },
  { symbol: 'AVAX/USDT', side: 'long',  pattern: 'bos_choch',      strat: 'classic_pa_v3', confluence: 4.6 },
  { symbol: 'INJ/USDT',  side: 'long',  pattern: 'inside_bar_brk', strat: 'breakout_v1',   confluence: 3.2 },
  { symbol: 'SUI/USDT',  side: 'long',  pattern: 'pin_bar_low',    strat: 'classic_pa_v3', confluence: 3.9 },
  { symbol: 'TIA/USDT',  side: 'short', pattern: 'pin_bar_high',   strat: 'momentum_rev',  confluence: 3.1 },
  { symbol: 'SEI/USDT',  side: 'long',  pattern: 'morning_star',   strat: 'classic_pa_v3', confluence: 4.0 },
  { symbol: 'RNDR/USDT', side: 'long',  pattern: 'engulfing_bull', strat: 'classic_pa_v3', confluence: 3.6 },
  { symbol: 'PYTH/USDT', side: 'short', pattern: 'evening_star',   strat: 'momentum_rev',  confluence: 3.3 },
];

const PRICE_HINTS = {
  'BTC/USDT': 67800, 'ETH/USDT': 3540, 'SOL/USDT': 162, 'AVAX/USDT': 36.4, 'INJ/USDT': 27.8,
  'SUI/USDT': 1.42, 'TIA/USDT': 9.12, 'SEI/USDT': 0.62, 'RNDR/USDT': 8.30, 'PYTH/USDT': 0.41,
};

function buildPositions(scenario){
  const count = scenario === 'breaker' ? 4 : scenario === 'winning' ? 9 : 7;
  return POS_TEMPLATES.slice(0, count).map((t, i) => {
    const entry = PRICE_HINTS[t.symbol];
    const tilt  = scenario === 'breaker' ? -1 : scenario === 'winning' ? 1.3 : 1;
    const moveBps = (t.side === 'long' ? 1 : -1) * (rnd()*0.05 - 0.018) * tilt;
    const current = +(entry * (1 + moveBps)).toFixed(entry < 2 ? 4 : 2);
    const qty = +(2500 / entry * (0.8 + rnd()*0.6)).toFixed(entry < 2 ? 1 : 4);
    const unrealized = +((current - entry) * qty * (t.side === 'long' ? 1 : -1)).toFixed(2);
    const slDist  = (t.side === 'long' ? -1 : 1) * entry * (0.025 + rnd()*0.02);
    const tpDist  = -slDist * (1.8 + rnd()*1.6);
    const opened = new Date(Date.now() - (3 + Math.floor(rnd()*72)) * 3600_000).toISOString();
    return {
      venue: 'binance',
      symbol: t.symbol,
      side: t.side,
      quantity: qty,
      entry_price: entry,
      current_price: current,
      unrealized_pnl_usdt: unrealized,
      realized_pnl_usdt: 0,
      sl_price: +(entry + slDist).toFixed(entry < 2 ? 4 : 2),
      tp_price: +(entry + tpDist).toFixed(entry < 2 ? 4 : 2),
      opened_at: opened,
      strategy_id: t.strat,
      pattern_id: t.pattern,
      confluence_score: t.confluence,
      leverage: 3,
      notional_usdt: +(qty*current).toFixed(2),
      r_multiple_live: +((current - entry) / Math.abs(slDist) * (t.side === 'long' ? 1 : -1)).toFixed(2),
    };
  });
}

// ------------------------------------------------------------- trade history
function buildTrades(scenario){
  const out = [];
  const winRateBase = scenario === 'winning' ? 0.74 : scenario === 'breaker' ? 0.42 : 0.61;
  for (let i = 0; i < 48; i++){
    const sym = pick(SYMBOLS_BASE.slice(0, 30)) + '/USDT';
    const pattern = pick(PATTERNS);
    const win = rnd() < winRateBase;
    const R = win ? between(0.8, 3.4) : between(-1.05, -0.6);
    const risk = between(80, 220, 1);
    const pnl = +(R * risk).toFixed(2);
    const leverage = pick([2, 2, 3, 3, 3, 4, 5]);
    const notional = +(risk * leverage * between(8, 22, 1)).toFixed(2);
    const exitTs = new Date(Date.now() - (i*0.6 + rnd()*0.8) * 86400_000).toISOString();
    const entryTs = new Date(new Date(exitTs).getTime() - (1 + rnd()*4) * 86400_000).toISOString();
    out.push({
      trade_id: 'T-' + (10000 - i),
      venue: 'binance',
      symbol: sym,
      side: pattern.dir,
      entry_ts: entryTs,
      exit_ts: exitTs,
      entry_price: between(0.4, 200, 4),
      exit_price: between(0.4, 200, 4),
      quantity: between(0.5, 50, 3),
      notional_usdt: notional,
      leverage,
      realized_pnl_usdt: pnl,
      realized_r_multiple: R,
      hold_hours: +((new Date(exitTs).getTime() - new Date(entryTs).getTime()) / 3_600_000).toFixed(1),
      fees_usdt: between(0.4, 3.2, 2),
      slippage_bps: between(0.6, 6.4, 1),
      strategy_id: pick(['classic_pa_v3','momentum_rev','breakout_v1','sr_bounce']),
      pattern_id: pattern.id,
      confluence_score: between(2.2, 4.8),
      mae_pct: between(0.8, 3.4),
      mfe_pct: between(1.1, 5.8),
      classification: win ? null : pick(['wrong_pattern','market_regime_shift','late_entry','sl_too_tight']),
    });
  }
  return out.sort((a,b) => new Date(b.exit_ts) - new Date(a.exit_ts));
}

// ---------------------------------------------------------- pending signals
function buildPendingSignals(scenario){
  const tickers = SYMBOLS_BASE.slice(0, 16);
  return tickers.map((t, i) => {
    const p = pick(PATTERNS);
    const conf = between(2.4, 4.8);
    const ts = new Date(Date.now() - i*420_000).toISOString();
    return {
      ts,
      venue: 'binance',
      symbol: t + '/USDT',
      timeframe: pick(['1d','1d','1d','1w']),
      direction: p.dir,
      pattern_id: p.id,
      pattern_label: p.label,
      confluence_score: conf,
      atr_pct: between(2.4, 6.8),
      suggested_size_atr: between(0.9, 1.6),
      // gate state — what /signals/pending really exposes per RUNBOOK
      gate_state: scenario === 'breaker' ? 'risk_rejected'
                : conf > 3.6 ? 'risk_approved'
                : conf > 3.0 ? 'awaiting_risk'
                : 'signal_only',
      reject_reason: scenario === 'breaker' ? 'daily_dd_breaker' : null,
    };
  });
}

// ----------------------------------------------------- scanner live universe
function buildScanner(scenario){
  // 80 symbols universe scan — like Signals dept output before confluence threshold
  return SYMBOLS_BASE.map((t, i) => {
    const trend = pick(['up','up','up','down','down','flat']);
    const conf  = between(0.4, 4.8);
    const struct= pick(['HH/HL','LH/LL','range','squeeze','expansion']);
    const lastP = PRICE_HINTS[t+'/USDT'] ?? between(0.3, 240, 3);
    const chg24 = between(-7.4, 9.2);
    return {
      symbol: t + '/USDT',
      trend_1w: trend,
      structure: struct,
      atr_pct: between(2.2, 8.4),
      vol_z: between(-2.4, 3.6),
      confluence: conf,
      last_price: lastP,
      change_24h: chg24,
      last_scan_ago_sec: Math.floor(rnd()*55) + 3,
      // tag if very hot
      tag: conf > 4.2 ? 'setup' : conf > 3.4 ? 'watch' : null,
    };
  });
}

// ------------------------------------------------------------ KPIs (computed)
function computeKpis(trades, equity){
  if (!trades.length) return {n_trades:0,win_rate:0,profit_factor:0,sharpe:0,sortino:0,max_drawdown:0,net_pnl_usdt:0,expectancy_r:0,avg_r:0,calmar:0};
  const wins = trades.filter(t => t.realized_pnl_usdt > 0);
  const losses = trades.filter(t => t.realized_pnl_usdt < 0);
  const gross_win = wins.reduce((a,t) => a + t.realized_pnl_usdt, 0);
  const gross_loss = Math.abs(losses.reduce((a,t) => a + t.realized_pnl_usdt, 0));
  const net = trades.reduce((a,t) => a + t.realized_pnl_usdt, 0);
  // synthetic Sharpe from equity returns
  let dd = 0, peak = equity[0]?.equity ?? 10000;
  for (const p of equity){ if (p.equity > peak) peak = p.equity; const cur = (peak - p.equity) / peak; if (cur > dd) dd = cur; }
  const rets = equity.slice(1).map((p,i) => (p.equity - equity[i].equity) / equity[i].equity);
  const mean = rets.reduce((a,b) => a+b, 0) / rets.length;
  const std  = Math.sqrt(rets.reduce((a,b) => a + (b - mean)**2, 0) / rets.length);
  const sharpe = (mean / (std || 1e-9)) * Math.sqrt(365);
  const downside = rets.filter(r => r < 0);
  const dstd = Math.sqrt(downside.reduce((a,b)=>a+b*b,0)/(downside.length||1));
  const sortino = (mean / (dstd || 1e-9)) * Math.sqrt(365);
  const avgR = trades.reduce((a,t) => a + t.realized_r_multiple, 0) / trades.length;
  return {
    n_trades: trades.length,
    win_rate: wins.length / trades.length,
    profit_factor: gross_loss === 0 ? 99 : gross_win / gross_loss,
    sharpe: +sharpe.toFixed(2),
    sortino: +sortino.toFixed(2),
    max_drawdown: +dd.toFixed(4),
    net_pnl_usdt: +net.toFixed(2),
    expectancy_r: +avgR.toFixed(2),
    avg_r: +avgR.toFixed(2),
    calmar: dd ? +((net / 10000) / dd).toFixed(2) : 0,
  };
}

// ------------------------------------------------------------- breaker state
function buildBreakers(scenario){
  return {
    daily:   { limit: 0.05, used: scenario === 'breaker' ? 0.061 : scenario === 'winning' ? -0.034 : 0.012, tripped: scenario === 'breaker' },
    weekly:  { limit: 0.10, used: scenario === 'breaker' ? 0.072 : scenario === 'winning' ? -0.058 : 0.024, tripped: false },
    monthly: { limit: 0.15, used: scenario === 'breaker' ? 0.083 : scenario === 'winning' ? -0.124 : 0.041, tripped: false },
  };
}

// -------------------------------------------------------- departments status
const DEPARTMENTS = [
  { key: 'ceo',         name: 'CEO Office',         pkg: 'agents/ceo',          llm: true,  kpi: 'orkestrasyon',  last: '2 dk',   status: 'ok',   note: 'Günlük direktif yayınlandı' },
  { key: 'data',        name: 'Veri Mühendisliği',  pkg: 'data/',               llm: false, kpi: 'ingest gap',    last: '40 sn',  status: 'ok',   note: 'gap %0.04 < %0.1' },
  { key: 'research',    name: 'Araştırma & Quant',  pkg: 'agents/researcher',   llm: true,  kpi: 'hipotez',       last: '6 sa',   status: 'ok',   note: '3 aday hipotez backtest kuyruğunda' },
  { key: 'signals',     name: 'Sinyal Mühendisliği', pkg: 'signals/',           llm: false, kpi: 'precision',     last: '12 sn',  status: 'ok',   note: '80 sembol tarandı' },
  { key: 'risk',        name: 'Risk Yönetimi',      pkg: 'risk/',               llm: false, kpi: 'DD breaker',    last: '4 sn',   status: 'ok',   note: 'breaker durumu temiz' },
  { key: 'portfolio',   name: 'Portföy',            pkg: 'portfolio/',          llm: false, kpi: 'korelasyon',    last: '8 sn',   status: 'ok',   note: 'ort. ρ = 0.34' },
  { key: 'execution',   name: 'Execution',          pkg: 'execution/',          llm: false, kpi: 'slippage',      last: '1 dk',   status: 'warn', note: 'slippage 8.4 bps — eşiğe yakın' },
  { key: 'analytics',   name: 'Analytics & PM',     pkg: 'agents/analyst',      llm: true,  kpi: 'brief kalite',  last: '9 sa',   status: 'ok',   note: 'günlük brief gönderildi' },
  { key: 'ops',         name: 'Operations / SRE',   pkg: 'agents/ops_engineer', llm: false, kpi: 'çalışma süresi', last: '5 sn',  status: 'ok',   note: 'uptime %99.97' },
  { key: 'lab',         name: 'Geliştirme Lab',     pkg: 'agents/lab_scientist', llm: true, kpi: 'drift',         last: '2 gün',  status: 'ok',   note: 'walk-forward Pazar tamamlanır' },
];

// ---------------------------------------------------------- phase progress
const PHASES = [
  { id: 0, name: 'Repo & İskelet',        gate: 'docker + memory + RAG',                          status: 'done',     value: '✓' },
  { id: 1, name: 'Kalıp Hassasiyeti',     gate: 'etiketli sette precision > %75',                 status: 'done',     value: '%78.3' },
  { id: 2, name: 'Backtest ROI',          gate: 'yıllık net > %70 / Sharpe > 1.5 / DD < %20',     status: 'done',     value: 'Sharpe 1.74' },
  { id: 3, name: 'Risk Katmanı',          gate: 'Sharpe Δ > -%10 / DD < %15',                     status: 'done',     value: 'DD %12.4' },
  { id: 4, name: 'ML Filtresi (ops.)',    gate: 'OOS Sharpe artış > +%15',                        status: 'skipped',  value: '—' },
  { id: 5, name: 'LLM Brief',             gate: '7 gün kesintisiz brief + 1 onay',                status: 'done',     value: '7/7' },
  { id: 6, name: 'Paper Trading',         gate: '4 hafta, P&L sapma < %20',                       status: 'active',   value: '2.4 / 4 hafta' },
  { id: 7, name: 'Mikro Canlı',           gate: 'aylık net pozitif',                              status: 'locked',   value: '—' },
];

// ---------------------------------------------------------- correlation matrix
function buildCorrelations(positions){
  const syms = positions.map(p => p.symbol.split('/')[0]);
  const matrix = syms.map((_, i) => syms.map((__, j) => {
    if (i === j) return 1;
    const seed = (i + 1) * 13 + (j + 1) * 7;
    const r = ((Math.sin(seed) + 1) / 2) * 1.4 - 0.4;
    return +Math.max(-0.4, Math.min(0.92, r)).toFixed(2);
  }));
  return { syms, matrix };
}

// ---------------------------------------------------------- CEO report markdown
const CEO_REPORT_MD = `# CEO Günlük Direktifi — 17 Mayıs 2026

## Piyasa Durumu
BTC haftalık kapanışı 67.800 üzerinde tutundu; 1G yapı **HH/HL**. ETH göreceli güç korunuyor (ETH/BTC oranı +%1.4 haftalık). Altcoin breadth zayıf — yalnızca 18/80 sembol yeni yerel zirve. Volatilite rejimi: **normal** (BTC realize vol %38 yıllık).

## Pozisyon Özeti
Açık 7 pozisyon, net notional **$18.420** (~%18 sermaye). Ortalama korelasyon 0.34 — portföy limiti içinde. Beklenmedik tarafta: TIA short, kalan 6 long.

## Risk
- Günlük DD kullanımı: %1.2 / %5 limit
- Haftalık DD kullanımı: %2.4 / %10 limit
- Yeni emirler açık. Breaker tetiklenmedi.

## Researcher Notu
Ekibin yeni hipotezi (\`weekly_pinbar_after_swfailure\`) walk-forward'da 5 dilimden 3'ünde pozitif Sharpe; **terfi adayı**, kuyrukta. Lab tournament'i Pazar.

## Direktif
1. Mevcut TIA short pozisyonunda kısmi kâr al — fiyat 1R'ye ulaştı.
2. Yeni long pozisyonları confluence ≥ 3.6 ile sınırla; breadth düzelene kadar.
3. Lab'in haftalık sonucu beklenecek; canlıda yeni strateji terfisi yok.

— CEO`;

const ANALYTICS_REPORT_MD = `# Günlük Brief — Analytics

## Performans Özeti
Bugün **3 işlem kapandı**, net **+$284** (R-çarpan toplamı +2.4). 90 günlük kazanma oranı %61.4. Profit factor 2.1. Sharpe 1.78.

## İşlem Post-Mortem
- **SUI long** — pin bar @ S/R, 1.4R kâr (MFE 1.9R). Sınıflandırma: temiz uygulama.
- **AVAX long** — 2.1R, tutma süresi 3 gün, slippage 1.2 bps.
- **ARB long** — SL'ye değdi -1.0R. Sınıflandırma: \`market_regime_shift\`. Kalıp doğruydu fakat BTC 4 saat içinde %1.8 düştü; korelasyon riskini kapatamadık.

## Strateji Performansı (30g)
| Strateji | İşlem | Kazanma | R-toplam |
|---|---:|---:|---:|
| classic_pa_v3 | 32 | %64 | +18.4R |
| momentum_rev  | 14 | %50 | +3.2R |
| breakout_v1   | 8  | %38 | -1.4R |

## Tavsiye
- breakout_v1 son 30 gün marjinal — Lab'a downgrade adayı olarak iletilecek.
- classic_pa_v3 lider; sermaye dağılımında ağırlığı %50 → %60'a çıkarmayı öneriyoruz.

— Analytics`;

// -------------------------------------------------------------- final export
function buildAll(scenario){
  const equity = buildEquity(scenario);
  const trades = buildTrades(scenario);
  const positions = buildPositions(scenario);
  return {
    scenario,
    equity,
    trades,
    positions,
    pending_signals: buildPendingSignals(scenario),
    scanner: buildScanner(scenario),
    kpi: computeKpis(trades, equity),
    breakers: buildBreakers(scenario),
    correlations: buildCorrelations(positions),
    departments: DEPARTMENTS,
    phases: PHASES,
    reports: { ceo: CEO_REPORT_MD, analytics: ANALYTICS_REPORT_MD },
    universe_size: SYMBOLS_BASE.length,
    halted: scenario === 'breaker',
  };
}

window.PA_BUILD = buildAll;
window.PA_PATTERNS = PATTERNS;
