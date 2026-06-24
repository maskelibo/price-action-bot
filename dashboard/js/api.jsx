// PA_FETCH — live data adapter.
// Maps FastAPI endpoints (/equity, /trades, /positions, /signals/pending,
// /health, /reports/ceo/latest, /reports/analytics/latest) to the shape
// the UI screens expect (same as window.PA_BUILD mock output).
//
// For endpoints not yet wired (scanner, breakers, correlations, departments)
// the mock fallback is used so the UI stays responsive. Those become real
// in Phase 3 of the dashboard migration.

const _safe = async (url, parser, fallback) => {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url} → ${res.status}`);
    return await parser(res);
  } catch (e) {
    console.warn(`PA_FETCH: ${url} failed (${e.message}) — using fallback`);
    return fallback;
  }
};

const _json = (r) => r.json();
const _text = (r) => r.text();

// pin SL/TP keys to mock shape; trades/positions live shape uses different field names.
function _normPosition(p) {
  const entry = p.entry_price ?? p.entryPrice ?? 0;
  const mark = p.current_price ?? p.markPrice ?? p.mark_price ?? entry;
  const qty = p.quantity ?? p.qty ?? p.contracts ?? 0;
  return {
    venue: p.venue ?? 'binance',
    symbol: p.symbol ?? p.sym ?? '?',
    side: (p.side ?? 'long').toLowerCase(),
    quantity: qty,
    entry_price: entry,
    current_price: mark,
    unrealized_pnl_usdt: p.unrealized_pnl_usdt ?? p.unrealizedPnl ?? 0,
    realized_pnl_usdt: p.realized_pnl_usdt ?? 0,
    sl_price: p.sl_price ?? p.stop_loss ?? null,
    tp_price: p.tp_price ?? p.take_profit ?? null,
    opened_at: p.opened_at ?? p.entry_ts ?? null,
    // Phase 3 contract fields — default until backend fills them
    strategy_id: p.strategy_id ?? p.strategy ?? 'unknown',
    pattern_id: p.pattern_id ?? p.pattern ?? null,
    confluence_score: p.confluence_score ?? null,
    leverage: p.leverage ?? 1,
    notional_usdt: p.notional_usdt ?? +(qty * mark).toFixed(2),
    r_multiple_live: p.r_multiple_live ?? null,
  };
}

function _normTrade(t) {
  return {
    trade_id: t.trade_id ?? t.id ?? null,
    venue: t.venue ?? 'binance',
    symbol: t.symbol ?? '?',
    side: (t.side ?? 'long').toLowerCase(),
    entry_ts: t.entry_ts ?? null,
    exit_ts: t.exit_ts ?? t.ts ?? null,
    entry_price: t.entry_price ?? 0,
    exit_price: t.exit_price ?? 0,
    quantity: t.quantity ?? t.qty ?? 0,
    notional_usdt: t.notional_usdt ?? null,
    leverage: t.leverage ?? 1,
    realized_pnl_usdt: t.realized_pnl_usdt ?? 0,
    realized_r_multiple: t.realized_r_multiple ?? t.realized_r ?? 0,
    hold_hours: t.hold_hours ?? null,
    fees_usdt: t.fees_usdt ?? null,
    slippage_bps: t.slippage_bps ?? null,
    strategy_id: t.strategy_id ?? t.strategy ?? 'unknown',
    pattern_id: t.pattern_id ?? t.pattern ?? null,
    confluence_score: t.confluence_score ?? null,
    mae_pct: t.mae_pct ?? null,
    mfe_pct: t.mfe_pct ?? null,
    classification: t.classification ?? null,
  };
}

function _normSignal(s) {
  return {
    ts: s.ts ?? null,
    venue: s.venue ?? 'binance',
    symbol: s.symbol ?? '?',
    timeframe: s.timeframe ?? '1d',
    direction: (s.direction ?? s.side ?? 'long').toLowerCase(),
    pattern_id: s.pattern_id ?? s.pattern ?? null,
    pattern_label: s.pattern_label ?? null,
    confluence_score: s.confluence_score ?? s.confluence ?? 0,
    atr_pct: s.atr_pct ?? null,
    suggested_size_atr: s.suggested_size_atr ?? null,
    gate_state: s.gate_state ?? 'signal_only',
    reject_reason: s.reject_reason ?? null,
  };
}

// recompute KPI from real trades + equity, same formula as mock-data.jsx
function _computeKpi(trades, equityPts) {
  if (!trades.length) return { n_trades: 0, win_rate: 0, profit_factor: 0, sharpe: 0, sortino: 0, max_drawdown: 0, net_pnl_usdt: 0, expectancy_r: 0, avg_r: 0, calmar: 0 };
  const wins = trades.filter(t => t.realized_pnl_usdt > 0);
  const losses = trades.filter(t => t.realized_pnl_usdt < 0);
  const gross_win = wins.reduce((a, t) => a + t.realized_pnl_usdt, 0);
  const gross_loss = Math.abs(losses.reduce((a, t) => a + t.realized_pnl_usdt, 0));
  const net = trades.reduce((a, t) => a + t.realized_pnl_usdt, 0);
  let dd = 0, peak = equityPts[0]?.equity ?? 10000;
  for (const p of equityPts) { if (p.equity > peak) peak = p.equity; const cur = (peak - p.equity) / peak; if (cur > dd) dd = cur; }
  const rets = equityPts.slice(1).map((p, i) => (p.equity - equityPts[i].equity) / equityPts[i].equity);
  const mean = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : 0;
  const std = rets.length ? Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length) : 1e-9;
  const sharpe = (mean / (std || 1e-9)) * Math.sqrt(365);
  const downside = rets.filter(r => r < 0);
  const dstd = Math.sqrt(downside.reduce((a, b) => a + b * b, 0) / (downside.length || 1));
  const sortino = (mean / (dstd || 1e-9)) * Math.sqrt(365);
  const avgR = trades.reduce((a, t) => a + (t.realized_r_multiple || 0), 0) / trades.length;
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

async function PA_FETCH(scenario) {
  // mock provides Phase-3-only sections (scanner, breakers, correlations, departments, phases, universe_size)
  const mock = window.PA_BUILD(scenario);

  const [equity, trades, positions, signals, health, ceoMd, analyticsMd] = await Promise.all([
    _safe('/equity?days=90', _json, { points: [] }),
    _safe('/trades?limit=200', _json, { trades: [] }),
    _safe('/positions', _json, { positions: [] }),
    _safe('/signals/pending?limit=80', _json, { signals: [] }),
    _safe('/health', _json, { halted: false }),
    _safe('/reports/ceo/latest', _text, mock.reports.ceo),
    _safe('/reports/analytics/latest', _text, mock.reports.analytics),
  ]);

  const equityPts = equity.points ?? [];
  const tradesNorm = (trades.trades ?? []).map(_normTrade);
  const positionsNorm = (positions.positions ?? []).map(_normPosition);
  const signalsNorm = (signals.signals ?? []).map(_normSignal);

  return {
    scenario,
    equity: equityPts,
    trades: tradesNorm,
    positions: positionsNorm,
    pending_signals: signalsNorm,
    // Phase 3 — endpoints not wired yet, fall back to mock so UI doesn't blank
    scanner: mock.scanner,
    breakers: mock.breakers,
    correlations: positionsNorm.length
      ? { syms: positionsNorm.map(p => p.symbol.split('/')[0]), matrix: _identityMatrix(positionsNorm.length) }
      : mock.correlations,
    departments: mock.departments,
    phases: mock.phases,
    universe_size: mock.universe_size,
    // KPI from live data, falls back to mock if both empty
    kpi: (tradesNorm.length || equityPts.length)
      ? _computeKpi(tradesNorm, equityPts)
      : mock.kpi,
    reports: { ceo: ceoMd, analytics: analyticsMd },
    halted: !!health.halted,
  };
}

function _identityMatrix(n) {
  return Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => (i === j ? 1 : 0))
  );
}

window.PA_FETCH = PA_FETCH;
