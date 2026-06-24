// Main screens: Overview, Positions, Scanner, Signals

// ============================================================ OVERVIEW
const Overview = ({data, lang, actions}) => {
  const t = STRINGS[lang];
  const k = data.kpi;
  const totalOpen = data.positions.reduce((a,p) => a + p.unrealized_pnl_usdt, 0);
  const totalNotional = data.positions.reduce((a,p) => a + p.notional_usdt, 0);
  const todayTrades = data.trades.filter(x => Date.now() - new Date(x.exit_ts).getTime() < 86400_000);
  const todayPnl = todayTrades.reduce((a,x) => a + x.realized_pnl_usdt, 0);

  return (
    <div className="stack" style={{gap:18}}>

      {data.halted && <HaltBanner lang={lang}/>}

      <Card padded={false}>
        <div className="kpi-strip">
          <KpiTile label={t.label.net_pnl} value={F.usd(k.net_pnl_usdt, {compact:true})} tone={pnlTone(k.net_pnl_usdt)} sub="90 günlük realize" big/>
          <KpiTile label={t.label.today} value={F.usd(todayPnl)} tone={pnlTone(todayPnl)} sub={todayTrades.length + ' işlem'}/>
          <KpiTile label={t.label.upnl} value={F.usd(totalOpen)} tone={pnlTone(totalOpen)} sub={data.positions.length + ' açık'}/>
          <KpiTile label={t.label.sharpe} value={F.num(k.sharpe)} tone={k.sharpe > 1.5 ? 'profit' : 'warn'} sub={'Sortino ' + F.num(k.sortino)}/>
          <KpiTile label={t.label.pf} value={F.num(k.profit_factor)} sub={'beklenti ' + F.r(k.expectancy_r)}/>
          <KpiTile label={t.label.win} value={F.pct(k.win_rate)} sub={k.n_trades + ' işlem'}/>
          <KpiTile label={t.label.dd} value={F.pct(k.max_drawdown,1)} tone={k.max_drawdown > 0.15 ? 'loss' : 'warn'} sub={'Calmar ' + F.num(k.calmar)}/>
          <KpiTile label={t.label.exposure} value={F.usd(totalNotional, {compact:true})} sub={(totalNotional/100).toFixed(0) + '% sermaye'}/>
        </div>
      </Card>

      <div className="grid-eq-pos">
        <Card
          title={t.section.equity}
          subtitle="USDT · son 90 gün · paper"
          action={<div className="seg"><div className="seg-btn">7G</div><div className="seg-btn">30G</div><div className="seg-btn active">90G</div><div className="seg-btn">TÜMÜ</div></div>}
        >
          <AreaChart points={data.equity}/>
        </Card>

        <Card title={t.section.risk_state} subtitle="DD breaker · risk departmanı">
          <div className="stack" style={{gap:14}}>
            <BreakerCompact b={data.breakers.daily}   name={t.label.daily} lang={lang}/>
            <BreakerCompact b={data.breakers.weekly}  name={t.label.weekly} lang={lang}/>
            <BreakerCompact b={data.breakers.monthly} name={t.label.monthly} lang={lang}/>
            <div style={{display:'flex', gap:8, paddingTop:8, borderTop:'1px solid var(--border-soft)'}}>
              <Pill tone="info" icon={<I.Cog/>}>{t.label.risk_per_trade} 2%</Pill>
              <Pill tone="info" icon={<I.Cog/>}>{t.label.max_lev} 3×</Pill>
            </div>
          </div>
        </Card>
      </div>

      <Card title={t.section.live_pos} subtitle={data.positions.length + ' açık · binance'} padded={false}
            action={<button className="btn-soft" onClick={() => window.__navTo?.('positions')}>{t.misc.view_all} <I.ArrowRight/></button>}>
        <PositionsTable rows={data.positions.slice(0,6)} lang={lang} compact actions={actions}/>
      </Card>

      <div className="grid-overview-bottom">
        <Card title={t.section.scan_activity} subtitle={data.scanner.length + ' ' + t.chip.symbols}
              action={<Pill tone="accent" icon={<I.Pulse/>}>{t.label.live}</Pill>}>
          <ScanActivityList rows={data.scanner.slice().sort((a,b)=>b.confluence-a.confluence).slice(0,10)} lang={lang}/>
        </Card>

        <Card title={t.section.phases} subtitle="gate-bazlı ilerleme">
          <div className="phase-track">
            {data.phases.map(p => <PhaseRow key={p.id} p={p}/>)}
          </div>
        </Card>
      </div>
    </div>
  );
};

const BreakerCompact = ({b, name, lang}) => {
  const t = STRINGS[lang];
  const tone = b.tripped ? 'loss' : Math.abs(b.used) > b.limit*0.7 ? 'warn' : 'profit';
  return (
    <ProgressBar
      value={Math.abs(b.used)}
      max={b.limit}
      tone={tone === 'profit' ? 'accent' : tone}
      label={<span>{name} <span style={{color:'var(--text-muted)', fontFamily:'var(--font-mono)', fontSize:11, marginLeft:6}}>{b.tripped ? t.label.tripped : F.pctSigned(b.used, 2)}</span></span>}
      secondary={F.pct(b.limit, 0) + ' ' + t.label.limit}
    />
  );
};

const PhaseRow = ({p}) => (
  <div className="phase-row">
    <div className={'phase-bullet ' + p.status}>
      {p.status === 'done' ? <I.Check/> : p.status === 'active' ? <I.Pulse/> : p.status === 'locked' ? <I.Lock/> : <I.Slash/>}
    </div>
    <div>
      <div className="phase-name">{p.id}. {p.name}</div>
    </div>
    <div className="phase-gate">{p.gate}</div>
    <div className="phase-value">{p.value}</div>
  </div>
);

const ScanActivityList = ({rows, lang}) => {
  const t = STRINGS[lang];
  return (
    <div className="stack" style={{gap:0}}>
      {rows.map(r => (
        <div key={r.symbol} style={{display:'grid', gridTemplateColumns:'1fr 70px 80px 70px', alignItems:'center', gap:10, padding:'8px 0', borderBottom:'1px dashed var(--border-soft)'}}>
          <div className="sym">
            <span className="sym-tag">{symTag(r.symbol)}</span>
            <div className="sym-meta">
              <span className="pair">{r.symbol}</span>
              <span className="vendor">{r.structure} · {r.tag ? t.scan[r.tag] : '—'}</span>
            </div>
          </div>
          <div className="mono" style={{fontSize:12, color:'var(--text-secondary)'}}>${F.num(r.last_price, r.last_price < 2 ? 4 : 2)}</div>
          <div className="mono" style={{fontSize:12, color: r.change_24h>0?'var(--profit)':'var(--loss)'}}>{F.pctSigned(r.change_24h/100, 2)}</div>
          <div style={{textAlign:'right'}}>
            <Pill tone={r.confluence > 4 ? 'accent' : r.confluence > 3.2 ? 'info' : 'neutral'}>{F.num(r.confluence,1)}</Pill>
          </div>
        </div>
      ))}
    </div>
  );
};

// ============================================================ POSITIONS
const PositionsTable = ({rows, lang, compact=false, actions}) => {
  const t = STRINGS[lang];
  if (!rows.length) return <div className="empty">{STRINGS[lang].misc.empty}</div>;
  return (
    <div className="tbl-wrap">
    <table className="tbl">
      <thead>
        <tr>
          <th>{t.label.symbol}</th>
          <th>{t.label.side}</th>
          <th className="num">{t.label.entry}</th>
          <th className="num">{t.label.current}</th>
          <th className="num">{t.label.sl}</th>
          <th className="num">{t.label.tp}</th>
          <th>{t.label.pattern}</th>
          {!compact && <th className="num">{t.label.confluence}</th>}
          {!compact && <th className="num">{t.label.leverage}</th>}
          <th className="num">{t.label.upnl}</th>
          <th className="num">{t.label.rmul}</th>
          {!compact && <th className="num">{t.label.age}</th>}
          {actions && <th></th>}
        </tr>
      </thead>
      <tbody>
        {rows.map(p => (
          <tr key={p.symbol}>
            <td>
              <div className="sym">
                <span className="sym-tag">{symTag(p.symbol)}</span>
                <div className="sym-meta">
                  <span className="pair">{p.symbol}</span>
                  <span className="vendor">{p.strategy_id}</span>
                </div>
              </div>
            </td>
            <td><Pill tone={sideTone(p.side)} icon={p.side==='long'?<I.Long/>:<I.Short/>}>{t.label[p.side]}</Pill></td>
            <td className="num">{F.num(p.entry_price, p.entry_price < 2 ? 4 : 2)}</td>
            <td className="num"><span className={p.current_price >= p.entry_price ? 'tone--profit' : 'tone--loss'}>{F.num(p.current_price, p.current_price < 2 ? 4 : 2)}</span></td>
            <td className="num tone--loss">{F.num(p.sl_price, p.sl_price < 2 ? 4 : 2)}</td>
            <td className="num tone--profit">{F.num(p.tp_price, p.tp_price < 2 ? 4 : 2)}</td>
            <td><span className="mono" style={{fontSize:12, color:'var(--text-secondary)'}}>{(window.PA_PATTERNS.find(pp=>pp.id===p.pattern_id)?.label) || p.pattern_id}</span></td>
            {!compact && <td className="num"><Pill tone={p.confluence_score > 3.8 ? 'accent' : 'neutral'}>{F.num(p.confluence_score,1)}</Pill></td>}
            {!compact && <td className="num mono">{p.leverage}×</td>}
            <td className={'num tone--' + pnlTone(p.unrealized_pnl_usdt)}>{F.usd(p.unrealized_pnl_usdt)}</td>
            <td className={'num tone--' + pnlTone(p.r_multiple_live)}>{F.r(p.r_multiple_live)}</td>
            {!compact && <td className="num muted">{F.ageHours(p.opened_at)}</td>}
            {actions && (
              <td style={{textAlign:'right'}}>
                <Button tone="danger-outline" size="xs" icon={<I.Halt/>} onClick={() => actions.closePosition(p)} title={t.action.close_pos}>{t.action.close_pos}</Button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
};

const Positions = ({data, lang, actions}) => {
  const t = STRINGS[lang];
  const [side, setSide] = React.useState('all');
  const [query, setQuery] = React.useState('');
  let rows = data.positions;
  if (side !== 'all') rows = rows.filter(r => r.side === side);
  if (query) rows = rows.filter(r => r.symbol.toLowerCase().includes(query.toLowerCase()) || r.pattern_id.includes(query.toLowerCase()));

  const totalUpnl = data.positions.reduce((a,p) => a + p.unrealized_pnl_usdt, 0);
  const totalNotional = data.positions.reduce((a,p) => a + p.notional_usdt, 0);
  const longs = data.positions.filter(p => p.side === 'long').length;
  const shorts = data.positions.filter(p => p.side === 'short').length;

  return (
    <div className="stack" style={{gap:18}}>
      <Card padded={false}>
        <div className="kpi-strip" style={{gridTemplateColumns:'repeat(5,1fr)'}}>
          <KpiTile label={t.label.open} value={data.positions.length} sub={longs + ' L · ' + shorts + ' S'}/>
          <KpiTile label={t.label.upnl} value={F.usd(totalUpnl)} tone={pnlTone(totalUpnl)} sub="tüm pozisyonlar"/>
          <KpiTile label={t.label.notional} value={F.usd(totalNotional, {compact:true})} sub="riske edilen"/>
          <KpiTile label={t.label.avg_confluence} value={F.num(data.positions.reduce((a,p)=>a+p.confluence_score,0)/data.positions.length, 2)}/>
          <KpiTile label={t.label.avg_lev} value={(data.positions.reduce((a,p)=>a+p.leverage,0)/data.positions.length).toFixed(1) + '×'}/>
        </div>
      </Card>

      <Card
        title={t.section.live_pos}
        subtitle="paper · binance testnet · 4 sn yenileme"
        padded={false}
        action={
          <div className="row">
            <input className="search-input" placeholder={t.misc.search} value={query} onChange={e => setQuery(e.target.value)}/>
            <div className="seg">
              <div className={'seg-btn ' + (side==='all'?'active':'')} onClick={()=>setSide('all')}>{t.misc.all}</div>
              <div className={'seg-btn ' + (side==='long'?'active':'')} onClick={()=>setSide('long')}>{t.misc.longs}</div>
              <div className={'seg-btn ' + (side==='short'?'active':'')} onClick={()=>setSide('short')}>{t.misc.shorts}</div>
            </div>
          </div>
        }
      >
        <PositionsTable rows={rows} lang={lang} actions={actions}/>
      </Card>
    </div>
  );
};

// ============================================================ SCANNER
const Scanner = ({data, lang}) => {
  const t = STRINGS[lang];
  const [filter, setFilter] = React.useState('all');
  const [query, setQuery] = React.useState('');
  let rows = data.scanner;
  if (filter === 'setup') rows = rows.filter(r => r.tag === 'setup');
  else if (filter === 'watch') rows = rows.filter(r => r.tag === 'watch' || r.tag === 'setup');
  if (query) rows = rows.filter(r => r.symbol.toLowerCase().includes(query.toLowerCase()));
  rows = rows.slice().sort((a,b) => b.confluence - a.confluence);

  const setupCount = data.scanner.filter(r => r.tag === 'setup').length;
  const watchCount = data.scanner.filter(r => r.tag === 'watch').length;

  return (
    <div className="stack" style={{gap:18}}>
      <Card padded={false}>
        <div className="kpi-strip" style={{gridTemplateColumns:'repeat(5,1fr)'}}>
          <KpiTile label={t.label.universe_size} value={data.scanner.length} sub={t.chip.symbols}/>
          <KpiTile label={t.label.setups} value={setupCount} tone="accent" sub="confluence > 4.2"/>
          <KpiTile label={t.label.watch} value={watchCount} tone="info" sub="confluence > 3.4"/>
          <KpiTile label={t.label.avg_atr} value={F.num(data.scanner.reduce((a,r)=>a+r.atr_pct,0)/data.scanner.length, 1)+'%'}/>
          <KpiTile label={t.label.last_scan} value="12 sn önce" sub="sinyal departmanı"/>
        </div>
      </Card>

      <Card
        title={t.section.universe}
        subtitle={data.scanner.length + ' sembol · 1G kapanış · vektörize'}
        padded={false}
        action={
          <div className="row">
            <input className="search-input" placeholder={t.misc.search} value={query} onChange={e => setQuery(e.target.value)}/>
            <div className="seg">
              <div className={'seg-btn ' + (filter==='all'?'active':'')} onClick={()=>setFilter('all')}>{t.misc.all}</div>
              <div className={'seg-btn ' + (filter==='watch'?'active':'')} onClick={()=>setFilter('watch')}>{t.label.watch}+</div>
              <div className={'seg-btn ' + (filter==='setup'?'active':'')} onClick={()=>setFilter('setup')}>{t.label.setups}</div>
            </div>
          </div>
        }
      >
        <div className="scan-grid">
          {rows.map(r => (
            <div key={r.symbol} className={'scan-cell ' + (r.tag || '')}>
              <div className="scan-head">
                <span className="scan-symbol">{r.symbol}</span>
                <span className="scan-change" style={{color: r.change_24h>0?'var(--profit)':'var(--loss)'}}>{F.pctSigned(r.change_24h/100, 1)}</span>
              </div>
              <div className="scan-meta">
                <span>${F.num(r.last_price, r.last_price < 2 ? 4 : 2)}</span>
                <span>{r.structure}</span>
              </div>
              <div className="scan-meta">
                <span>ATR {r.atr_pct.toFixed(1)}%</span>
                <span style={{color: r.trend_1w==='up'?'var(--profit)':r.trend_1w==='down'?'var(--loss)':'var(--text-muted)'}}>1H {t.scan[r.trend_1w]}</span>
              </div>
              <div className="scan-conf-bar">
                <div className="scan-conf-fill" style={{width: Math.min(100, r.confluence/5*100) + '%', background: r.confluence > 4 ? 'var(--accent)' : r.confluence > 3 ? 'var(--info)' : 'var(--text-muted)'}}/>
              </div>
              <div className="scan-meta">
                <span style={{color:'var(--text-muted)'}}>conf {F.num(r.confluence, 1)}</span>
                {r.tag && <Pill tone={r.tag === 'setup' ? 'accent' : 'info'}>{t.scan[r.tag]}</Pill>}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

// ============================================================ SIGNALS
const SignalQueue = ({data, lang, actions}) => {
  const t = STRINGS[lang];
  const states = ['risk_approved','awaiting_risk','signal_only','risk_rejected'];
  const stateMeta = {
    risk_approved: { tone: 'profit', label: t.label.approved, icon: <I.Check/> },
    awaiting_risk: { tone: 'warn',   label: t.label.awaiting, icon: <I.Clock/> },
    signal_only:   { tone: 'info',   label: t.label.signal_only, icon: <I.Pulse/> },
    risk_rejected: { tone: 'loss',   label: t.label.rejected, icon: <I.Halt/> },
  };
  const grouped = states.map(s => ({state: s, rows: data.pending_signals.filter(x => x.gate_state === s)}));
  const counts = Object.fromEntries(states.map(s => [s, data.pending_signals.filter(x => x.gate_state === s).length]));

  return (
    <div className="stack" style={{gap:18}}>

      <Card title={t.section.signal_flow}
            subtitle={t.pipeline.auto_note}
            action={<Pill tone="accent" icon={<I.Pulse/>}>{t.label.automated}</Pill>}>
        <div className="pipeline">
          <PipelineStage idx={1} title={t.pipeline.stage_scanner} sub={`${data.scanner.length} ${t.label.symbols}`} icon={<I.Scanner/>} tone="info"/>
          <PipelineArrow/>
          <PipelineStage idx={2} title={t.pipeline.stage_signal} sub={`confluence > 3.0`} icon={<I.Signals/>} tone="info" count={counts.signal_only + counts.awaiting_risk + counts.risk_approved + counts.risk_rejected}/>
          <PipelineArrow/>
          <PipelineStage idx={3} title={t.pipeline.stage_risk} sub="breaker + boyutlandırma" icon={<I.Risk/>} tone="warn" count={counts.awaiting_risk}/>
          <PipelineArrow/>
          <PipelineStage idx={4} title={t.pipeline.stage_portfolio} sub="korelasyon + tahsis" icon={<I.Departments/>} tone="info" count={counts.risk_approved}/>
          <PipelineArrow/>
          <PipelineStage idx={5} title={t.pipeline.stage_exec} sub="ccxt · binance" icon={<I.Pulse/>} tone="accent" count={counts.risk_approved}/>
        </div>
      </Card>

      <Card padded={false}>
        <div className="kpi-strip" style={{gridTemplateColumns:'repeat(4,1fr)'}}>
          {states.map(s => (
            <KpiTile key={s}
              label={stateMeta[s].label}
              value={counts[s]}
              tone={stateMeta[s].tone}/>
          ))}
        </div>
      </Card>

      <Card title={t.section.signal_queue} subtitle="sinyal → risk → portföy → execution · otomatik · audit" padded={false}>
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>{t.label.status}</th>
              <th>{t.label.symbol}</th>
              <th>{t.label.timeframe}</th>
              <th>{t.label.direction}</th>
              <th>{t.label.pattern}</th>
              <th className="num">{t.label.confluence}</th>
              <th className="num">{t.label.atr}</th>
              <th className="num">{t.label.age}</th>
              <th>{t.label.note}</th>
            </tr>
          </thead>
          <tbody>
            {grouped.flatMap(g => g.rows).map((s, i) => {
              const m = stateMeta[s.gate_state];
              return (
                <tr key={i}>
                  <td><Pill tone={m.tone} icon={m.icon}>{m.label}</Pill></td>
                  <td><div className="sym"><span className="sym-tag">{symTag(s.symbol)}</span><div className="sym-meta"><span className="pair">{s.symbol}</span><span className="vendor">binance</span></div></div></td>
                  <td><Pill>{s.timeframe.toUpperCase()}</Pill></td>
                  <td><Pill tone={sideTone(s.direction)} icon={s.direction==='long'?<I.Long/>:<I.Short/>}>{t.label[s.direction]}</Pill></td>
                  <td><span className="mono" style={{fontSize:12, color:'var(--text-secondary)'}}>{s.pattern_label}</span></td>
                  <td className="num"><Pill tone={s.confluence_score > 3.8 ? 'accent' : 'neutral'}>{F.num(s.confluence_score,1)}</Pill></td>
                  <td className="num mono">{s.atr_pct.toFixed(1)}%</td>
                  <td className="num muted">{F.ageHours(s.ts)}</td>
                  <td><span style={{color:'var(--text-muted)', fontSize:12}}>{s.reject_reason || (s.gate_state === 'risk_approved' ? t.notes.queued : s.gate_state === 'awaiting_risk' ? t.notes.risk_review : t.notes.below_thr)}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      </Card>
    </div>
  );
};

window.Overview = Overview;
window.Positions = Positions;
window.Scanner = Scanner;
window.SignalQueue = SignalQueue;

// pipeline stage diagram --------------------------------------------------
const PipelineStage = ({idx, title, sub, icon, tone='info', count}) => (
  <div className={`pipe-stage pipe-stage--${tone}`}>
    <div className="pipe-stage-head">
      <span className="pipe-stage-idx">{idx}</span>
      <span className="pipe-stage-icon">{icon}</span>
      {count != null && <span className="pipe-stage-count">{count}</span>}
    </div>
    <div className="pipe-stage-title">{title}</div>
    <div className="pipe-stage-sub">{sub}</div>
  </div>
);

const PipelineArrow = () => (
  <div className="pipe-arrow">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14M14 6l6 6-6 6"/>
    </svg>
  </div>
);

window.PipelineStage = PipelineStage;
window.PipelineArrow = PipelineArrow;
