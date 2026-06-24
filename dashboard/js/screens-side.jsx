// Secondary screens: Journal, Risk, Departments, Reports

// ============================================================ JOURNAL
const Journal = ({data, lang}) => {
  const t = STRINGS[lang];
  const [filter, setFilter] = React.useState('all');
  const [query, setQuery] = React.useState('');

  let rows = data.trades;
  if (filter === 'wins') rows = rows.filter(x => x.realized_pnl_usdt > 0);
  else if (filter === 'losses') rows = rows.filter(x => x.realized_pnl_usdt < 0);
  if (query) rows = rows.filter(r => r.symbol.toLowerCase().includes(query.toLowerCase()) || r.pattern_id.includes(query.toLowerCase()) || r.strategy_id.includes(query.toLowerCase()));

  // strategy aggregation
  const stratAgg = {};
  data.trades.forEach(t => {
    if (!stratAgg[t.strategy_id]) stratAgg[t.strategy_id] = { n:0, wins:0, R:0, pnl:0 };
    const s = stratAgg[t.strategy_id];
    s.n++; if (t.realized_pnl_usdt > 0) s.wins++; s.R += t.realized_r_multiple; s.pnl += t.realized_pnl_usdt;
  });
  const stratRows = Object.entries(stratAgg).sort((a,b) => b[1].pnl - a[1].pnl);
  const maxAbs = Math.max(...stratRows.map(([,v]) => Math.abs(v.pnl)), 1);

  // symbol aggregation — coin başına özet
  const symAgg = {};
  data.trades.forEach(tr => {
    if (!symAgg[tr.symbol]) symAgg[tr.symbol] = { n:0, wins:0, pnl:0, R:0, notional:0, levSum:0, levs:new Set() };
    const s = symAgg[tr.symbol];
    s.n++;
    if (tr.realized_pnl_usdt > 0) s.wins++;
    s.pnl += tr.realized_pnl_usdt;
    s.R += tr.realized_r_multiple;
    s.notional += tr.notional_usdt || 0;
    s.levSum += tr.leverage || 0;
    if (tr.leverage) s.levs.add(tr.leverage);
  });
  const symRows = Object.entries(symAgg)
    .map(([sym, s]) => ({
      symbol: sym,
      n: s.n,
      win_rate: s.n ? s.wins/s.n : 0,
      pnl: s.pnl,
      R: s.R,
      notional: s.notional,
      avg_lev: s.n ? s.levSum/s.n : 0,
      lev_range: [...s.levs].sort((a,b)=>a-b),
    }))
    .sort((a,b) => b.pnl - a.pnl);
  const symMaxPnl = Math.max(...symRows.map(r => Math.abs(r.pnl)), 1);

  const wins = data.trades.filter(x => x.realized_pnl_usdt > 0);
  const losses = data.trades.filter(x => x.realized_pnl_usdt < 0);
  const grossWin = wins.reduce((a,x)=>a+x.realized_pnl_usdt, 0);
  const grossLoss = Math.abs(losses.reduce((a,x)=>a+x.realized_pnl_usdt, 0));
  const avgWin = wins.length ? grossWin/wins.length : 0;
  const avgLoss = losses.length ? grossLoss/losses.length : 0;
  const totalNotional = data.trades.reduce((a,x) => a + (x.notional_usdt || 0), 0);

  return (
    <div className="stack" style={{gap:18}}>
      <Card padded={false}>
        <div className="kpi-strip" style={{gridTemplateColumns:'repeat(6,1fr)'}}>
          <KpiTile label={t.label.trades} value={data.trades.length} sub="son 90 gün"/>
          <KpiTile label={t.label.win} value={F.pct(wins.length/data.trades.length)} tone="profit" sub={wins.length + 'K ' + losses.length + 'Z'}/>
          <KpiTile label={t.label.total_notional} value={F.usd(totalNotional, {compact:true})} sub="işlem hacmi"/>
          <KpiTile label={t.label.net_pnl} value={F.usd(data.kpi.net_pnl_usdt)} tone={pnlTone(data.kpi.net_pnl_usdt)} sub={(data.kpi.net_pnl_usdt/totalNotional*100).toFixed(2) + '% ROI'}/>
          <KpiTile label={t.label.avg_win + ' / ' + t.label.avg_loss} value={F.usd(avgWin)} tone="profit" sub={t.label.avg_loss + ' ' + F.usd(-avgLoss)}/>
          <KpiTile label={t.label.expectancy} value={F.r(data.kpi.expectancy_r)} sub="işlem başına"/>
        </div>
      </Card>

      <Card title={t.section.by_symbol}
            subtitle={`${symRows.length} sembol · 90 gün · kaç işlem · ne kadar girilmiş · ne getirmiş · hangi kaldıraç`}
            padded={false}>
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>{t.label.symbol}</th>
              <th className="num">{t.label.n_trades}</th>
              <th className="num">{t.label.win_lbl}</th>
              <th className="num">{t.label.total_notional}</th>
              <th className="num">Lev (ort · aralık)</th>
              <th className="num">R toplam</th>
              <th className="num">PnL</th>
              <th>{t.label.dist}</th>
            </tr>
          </thead>
          <tbody>
            {symRows.map(r => (
              <tr key={r.symbol}>
                <td>
                  <div className="sym">
                    <span className="sym-tag">{symTag(r.symbol)}</span>
                    <div className="sym-meta">
                      <span className="pair">{r.symbol}</span>
                      <span className="vendor">{r.n} işlem · {F.pct(r.win_rate, 0)} kazanma</span>
                    </div>
                  </div>
                </td>
                <td className="num">{r.n}</td>
                <td className="num"><Pill tone={r.win_rate >= 0.5 ? 'profit' : 'warn'}>{F.pct(r.win_rate, 0)}</Pill></td>
                <td className="num">{F.usd(r.notional, {compact:true})}</td>
                <td className="num"><span className="mono" style={{fontSize:11.5}}>{r.avg_lev.toFixed(1)}× <span style={{color:'var(--text-muted)'}}>· {r.lev_range[0]}–{r.lev_range[r.lev_range.length-1]}×</span></span></td>
                <td className={'num tone--' + pnlTone(r.R)}>{F.r(r.R)}</td>
                <td className={'num tone--' + pnlTone(r.pnl)}>{F.usd(r.pnl)}</td>
                <td>
                  <div className="strat-bar-track" style={{width: 140}}>
                    {r.pnl >= 0
                      ? <div className="strat-bar-fill" style={{left:'50%', width: (r.pnl/symMaxPnl*50) + '%', background:'var(--profit)'}}/>
                      : <div className="strat-bar-fill" style={{right:'50%', width: (Math.abs(r.pnl)/symMaxPnl*50) + '%', background:'var(--loss)'}}/>}
                    <div style={{position:'absolute', top:0, bottom:0, left:'50%', width:1, background:'var(--border-strong)'}}/>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Card>

      <div className="grid-overview-bottom">
        <Card title={t.section.win_vs_loss} subtitle="risk-getiri profili">
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 14}}>
            <div style={{padding:'14px 16px', background:'var(--profit-soft)', borderRadius:10, border:'1px solid rgba(74,222,128,0.2)'}}>
              <div style={{fontSize:11, color:'var(--profit)', textTransform:'uppercase', letterSpacing:'.06em', marginBottom:4}}>{t.label.avg_win}</div>
              <div className="mono" style={{fontSize:24, color:'var(--profit)'}}>+{F.usd(avgWin).replace('+','')}</div>
              <div style={{fontSize:11.5, color:'var(--text-muted)', marginTop:2}}>{wins.length} kazanan · brüt {F.usd(grossWin, {compact:true})}</div>
            </div>
            <div style={{padding:'14px 16px', background:'var(--loss-soft)', borderRadius:10, border:'1px solid rgba(248,113,113,0.2)'}}>
              <div style={{fontSize:11, color:'var(--loss)', textTransform:'uppercase', letterSpacing:'.06em', marginBottom:4}}>{t.label.avg_loss}</div>
              <div className="mono" style={{fontSize:24, color:'var(--loss)'}}>−{F.usd(-avgLoss).replace('−','')}</div>
              <div style={{fontSize:11.5, color:'var(--text-muted)', marginTop:2}}>{losses.length} kaybeden · brüt {F.usd(-grossLoss, {compact:true})}</div>
            </div>
          </div>
          <div style={{marginTop:18, paddingTop:14, borderTop:'1px solid var(--border-soft)'}}>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:12.5}}>
              <span style={{color:'var(--text-muted)'}}>{t.label.rr_ratio}</span>
              <span className="mono">{(avgWin / (avgLoss || 1)).toFixed(2)}</span>
            </div>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:12.5, marginTop:6}}>
              <span style={{color:'var(--text-muted)'}}>{t.label.pf}</span>
              <span className="mono">{data.kpi.profit_factor.toFixed(2)}</span>
            </div>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:12.5, marginTop:6}}>
              <span style={{color:'var(--text-muted)'}}>{t.label.avg_hold}</span>
              <span className="mono">{(data.trades.reduce((a,x)=>a+(x.hold_hours||0),0)/data.trades.length).toFixed(1)}sa</span>
            </div>
          </div>
        </Card>

        <Card title={t.section.strat_perf}>
          <div className="stack">
            {stratRows.map(([name, s]) => (
              <div key={name} className="strat-row">
                <div className="strat-name">{name}</div>
                <div className="strat-bar-track">
                  {s.pnl >= 0
                    ? <div className="strat-bar-fill" style={{left:'50%', width: (s.pnl/maxAbs*50) + '%', background:'var(--profit)'}}/>
                    : <div className="strat-bar-fill" style={{right:'50%', width: (Math.abs(s.pnl)/maxAbs*50) + '%', background:'var(--loss)'}}/>}
                  <div style={{position:'absolute', top:0, bottom:0, left:'50%', width:1, background:'var(--border-strong)'}}/>
                </div>
                <div className="strat-val" style={{color: s.pnl>0?'var(--profit)':'var(--loss)'}}>{F.usd(s.pnl)}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title={t.section.recent} subtitle={data.trades.length + ' kayıt · tüm işlem geçmişi'} padded={false}
        action={
          <div className="row">
            <input className="search-input" placeholder={t.misc.search} value={query} onChange={e=>setQuery(e.target.value)}/>
            <div className="seg">
              <div className={'seg-btn ' + (filter==='all'?'active':'')} onClick={()=>setFilter('all')}>{t.misc.all}</div>
              <div className={'seg-btn ' + (filter==='wins'?'active':'')} onClick={()=>setFilter('wins')}>{t.misc.wins}</div>
              <div className={'seg-btn ' + (filter==='losses'?'active':'')} onClick={()=>setFilter('losses')}>{t.misc.losses}</div>
            </div>
          </div>
        }>
        <div style={{maxHeight: 580, overflowY: 'auto'}}>
          <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>{t.label.exit}</th>
                <th>{t.label.symbol}</th>
                <th>{t.label.side}</th>
                <th className="num">{t.label.leverage}</th>
                <th className="num">{t.label.notional}</th>
                <th>{t.label.pattern}</th>
                <th>{t.label.strat}</th>
                <th className="num">{t.label.rmul}</th>
                <th className="num">PnL</th>
                <th className="num">{t.label.hold}</th>
                <th className="num">MAE</th>
                <th className="num">MFE</th>
                <th>{t.label.classification}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(tr => (
                <tr key={tr.trade_id}>
                  <td className="muted mono" style={{fontSize:11.5}}>{F.shortDate(tr.exit_ts)}</td>
                  <td>
                    <div className="sym">
                      <span className="sym-tag">{symTag(tr.symbol)}</span>
                      <div className="sym-meta">
                        <span className="pair">{tr.symbol}</span>
                        <span className="vendor">{tr.trade_id}</span>
                      </div>
                    </div>
                  </td>
                  <td><Pill tone={sideTone(tr.side)} icon={tr.side==='long'?<I.Long/>:<I.Short/>}>{t.label[tr.side]}</Pill></td>
                  <td className="num mono">{tr.leverage}×</td>
                  <td className="num mono">{F.usd(tr.notional_usdt || 0, {compact:true})}</td>
                  <td><span className="mono" style={{fontSize:11.5, color:'var(--text-secondary)'}}>{window.PA_PATTERNS.find(p=>p.id===tr.pattern_id)?.label || tr.pattern_id}</span></td>
                  <td><span className="mono" style={{fontSize:11.5, color:'var(--text-secondary)'}}>{tr.strategy_id}</span></td>
                  <td className={'num tone--' + pnlTone(tr.realized_r_multiple)}>{F.r(tr.realized_r_multiple)}</td>
                  <td className={'num tone--' + pnlTone(tr.realized_pnl_usdt)}>{F.usd(tr.realized_pnl_usdt)}</td>
                  <td className="num muted">{(tr.hold_hours || 0).toFixed(1)}sa</td>
                  <td className="num muted">{tr.mae_pct.toFixed(1)}%</td>
                  <td className="num muted">{tr.mfe_pct.toFixed(1)}%</td>
                  <td>{tr.classification ? <Pill tone="warn">{tr.classification}</Pill> : <Pill tone="profit">{t.label.clean}</Pill>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      </Card>
    </div>
  );
};

// ============================================================ RISK
const RiskScreen = ({data, lang, actions}) => {
  const t = STRINGS[lang];
  const { breakers, correlations, positions } = data;
  const totalNotional = positions.reduce((a,p)=>a+p.notional_usdt,0);
  const totalRisk = positions.reduce((a,p)=>a + p.notional_usdt / (p.leverage || 1) / 10000, 0);
  // leverage per symbol
  const levRows = positions.map(p => ({
    sym: p.symbol,
    notional: p.notional_usdt,
    lev: p.leverage,
    pct: p.notional_usdt / totalNotional,
    side: p.side,
  })).sort((a,b) => b.notional - a.notional);

  return (
    <div className="stack" style={{gap:18}}>
      <Card title={t.section.breakers} subtitle="drawdown koruması · gerçek zamanlı izleme">
        <div className="breaker-grid">
          {['daily','weekly','monthly'].map(k => {
            const b = breakers[k];
            const used = Math.abs(b.used);
            const pct = used / b.limit;
            return (
              <div key={k} className={'breaker-box ' + (b.tripped ? 'tripped' : '')}>
                <div className="breaker-box-head">
                  <span className="breaker-box-name">{t.label[k]}</span>
                  {b.tripped ? <Pill tone="loss" icon={<I.Halt/>}>{t.label.tripped}</Pill> : <Pill tone="profit" icon={<I.Check/>}>{t.label.clean}</Pill>}
                </div>
                <div className="breaker-box-val" style={{color: b.tripped ? 'var(--loss)' : b.used < 0 ? 'var(--profit)' : 'var(--text-primary)'}}>{F.pctSigned(b.used, 2)}</div>
                <ProgressBar value={used} max={b.limit} tone={b.tripped ? 'loss' : pct > 0.7 ? 'warn' : 'accent'}
                  label={<span className="mono" style={{fontSize:11.5, color:'var(--text-muted)'}}>{F.pct(used,2)} / {F.pct(b.limit,0)}</span>}
                  secondary={null}/>
              </div>
            );
          })}
        </div>
      </Card>

      <div className="grid-overview-bottom">
        <Card title={t.section.corr} subtitle="açık pozisyonlar · pearson · 90 günlük getiri">
          <div style={{overflowX:'auto'}}>
            <table className="corr-table">
              <thead><tr><th></th>{correlations.syms.map(s => <th key={s}>{s}</th>)}</tr></thead>
              <tbody>
                {correlations.matrix.map((row, i) => (
                  <tr key={i}>
                    <th>{correlations.syms[i]}</th>
                    {row.map((v, j) => {
                      const intensity = Math.abs(v);
                      const color = v > 0
                        ? `rgba(74,222,128,${intensity*0.6})`
                        : `rgba(248,113,113,${intensity*0.6})`;
                      const tx = v > 0.7 ? '#0E1014' : intensity > 0.3 ? 'var(--text-primary)' : 'var(--text-muted)';
                      return <td key={j} style={{background:color, color: tx}}>{v.toFixed(2)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title={t.section.leverage} subtitle="tavan 3× · sembol başına kullanım">
          <div className="stack" style={{gap:12}}>
            {levRows.map(r => (
              <div key={r.sym}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:4}}>
                  <span className="row" style={{gap:6}}>
                    <span className="sym-tag" style={{width:22, height:22, fontSize:9}}>{symTag(r.sym)}</span>
                    <span style={{fontSize:13}}>{r.sym}</span>
                    <Pill tone={sideTone(r.side)}>{t.label[r.side]}</Pill>
                  </span>
                  <span className="mono" style={{fontSize:11.5, color:'var(--text-muted)'}}>{r.lev}× · {F.usd(r.notional, {compact:true})}</span>
                </div>
                <div className="pbar-track"><div className="pbar-fill tone--accent" style={{width: (r.pct*100).toFixed(1)+'%'}}/></div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title={t.section.risk_config} subtitle="configs/risk.yaml · düzenlenebilir (paper)"
            action={actions ? <Pill tone="info" icon={<I.Cog/>}>{t.label.editable}</Pill> : null}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:14}}>
          <ConfTile k="risk_per_trade"     v={(data.risk_config?.risk_per_trade ?? 2.0).toFixed(2)+'%'}    sub={t.risk_cfg.fixed_frac}   actions={actions} onSave={v => actions?.saveRiskConfig({risk_per_trade: parseFloat(v)})} lang={lang}/>
          <ConfTile k="kelly_cap"          v={(data.risk_config?.kelly_cap ?? 0.25).toFixed(2)}            sub={t.risk_cfg.paranoid}     actions={actions} onSave={v => actions?.saveRiskConfig({kelly_cap: parseFloat(v)})} lang={lang}/>
          <ConfTile k="max_leverage"       v={(data.risk_config?.max_leverage ?? 3) + '×'}                 sub={t.risk_cfg.per_sym}      actions={actions} onSave={v => actions?.saveRiskConfig({max_leverage: parseFloat(v)})} lang={lang}/>
          <ConfTile k="correlation_gate"   v={(data.risk_config?.correlation_gate ?? 0.70).toFixed(2)}     sub={t.risk_cfg.halve}        actions={actions} onSave={v => actions?.saveRiskConfig({correlation_gate: parseFloat(v)})} lang={lang}/>
          <ConfTile k="daily_dd_breaker"   v={(data.risk_config?.daily_dd_breaker ?? 5.0).toFixed(1)+'%'}  sub={t.risk_cfg.blocks}       actions={actions} onSave={v => actions?.saveRiskConfig({daily_dd_breaker: parseFloat(v)})} lang={lang}/>
          <ConfTile k="weekly_dd_breaker"  v={(data.risk_config?.weekly_dd_breaker ?? 10.0).toFixed(1)+'%'} sub={t.risk_cfg.manual_review} actions={actions} onSave={v => actions?.saveRiskConfig({weekly_dd_breaker: parseFloat(v)})} lang={lang}/>
          <ConfTile k="monthly_dd_breaker" v={(data.risk_config?.monthly_dd_breaker ?? 15.0).toFixed(1)+'%'} sub={t.risk_cfg.freeze}      actions={actions} onSave={v => actions?.saveRiskConfig({monthly_dd_breaker: parseFloat(v)})} lang={lang}/>
          <ConfTile k="liquidity_check"    v={t.risk_cfg.liq} sub={t.risk_cfg.split} actions={null} lang={lang}/>
        </div>
      </Card>
    </div>
  );
};

const ConfTile = ({k, v, sub, actions, onSave, lang}) => {
  const t = STRINGS[lang || 'tr'];
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(() => String(v).replace(/[%×]/g,'').trim());
  React.useEffect(() => setDraft(String(v).replace(/[%×]/g,'').trim()), [v]);
  const editable = actions && onSave;

  if (editing) {
    return (
      <div className="conf-tile editing">
        <div className="mono" style={{fontSize:11, color:'var(--text-muted)'}}>{k}</div>
        <input
          autoFocus
          className="conf-edit-input"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { onSave(draft); setEditing(false); } if (e.key === 'Escape') setEditing(false); }}
        />
        <div className="conf-edit-row">
          <Button tone="primary" size="xs" onClick={() => { onSave(draft); setEditing(false); }}>{t.action.save}</Button>
          <Button tone="soft" size="xs" onClick={() => setEditing(false)}>{t.action.cancel}</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="conf-tile" onClick={editable ? () => setEditing(true) : undefined} style={{cursor: editable ? 'pointer' : 'default'}}>
      <div className="mono" style={{fontSize:11, color:'var(--text-muted)', display:'flex', justifyContent:'space-between'}}>
        <span>{k}</span>
        {editable && <span style={{color:'var(--text-dim)'}}>{t.label.edit}</span>}
      </div>
      <div className="mono" style={{fontSize:17, color:'var(--text-primary)', marginTop:2}}>{v}</div>
      <div style={{fontSize:11, color:'var(--text-muted)', marginTop:2}}>{sub}</div>
    </div>
  );
};

// ============================================================ DEPARTMENTS
const Departments = ({data, lang}) => {
  const t = STRINGS[lang];
  const okCount = data.departments.filter(d => d.status === 'ok').length;
  const warnCount = data.departments.filter(d => d.status === 'warn').length;
  return (
    <div className="stack" style={{gap:18}}>
      <Card padded={false}>
        <div className="kpi-strip" style={{gridTemplateColumns:'repeat(5,1fr)'}}>
          <KpiTile label="Departman" value="10" sub="aktif"/>
          <KpiTile label="Sağlık" value={okCount} tone="profit" sub="OK durumu"/>
          <KpiTile label={t.label.warnings} value={warnCount} tone={warnCount>0?'warn':'muted'}/>
          <KpiTile label={t.label.llm_led} value="4" sub="ceo · researcher · analyst · lab"/>
          <KpiTile label={t.label.uptime + ' 30g'} value="99.97%" tone="profit"/>
        </div>
      </Card>

      <Card title={t.section.system_flow}
            subtitle="ARCHITECTURE.md · veri akışı · LLM emir vermez">
        <SystemFlow lang={lang}/>
      </Card>

      <Card title={t.section.dept_health} subtitle="contracts in src/price_action/contracts.py">
        <div className="dept-grid">
          {data.departments.map(d => (
            <div key={d.key} className="dept-card">
              <div className="dept-head">
                <div className={'dept-icon ' + (d.llm ? 'llm' : '')}>{d.llm ? <I.Brain/> : <I.Cog/>}</div>
                <div style={{flex:1, minWidth:0}}>
                  <div className="dept-name">{d.name}</div>
                  <div className="dept-pkg">{d.pkg}</div>
                </div>
                {d.status === 'ok'
                  ? <Pill tone="profit" icon={<I.Dot color="var(--profit)"/>}>OK</Pill>
                  : <Pill tone="warn" icon={<I.Warn/>}>UYARI</Pill>}
              </div>
              <div className="dept-meta">
                <div className="dept-meta-row">
                  <span className="k">{t.label.kpi}</span>
                  <span className="v">{d.kpi}</span>
                </div>
                <div className="dept-meta-row">
                  <span className="k">{t.label.last_run}</span>
                  <span className="v">{d.last}</span>
                </div>
                <div className="dept-meta-row" style={{textAlign:'right'}}>
                  <span className="k">{t.label.llm}</span>
                  <span className="v">{d.llm ? 'evet' : 'hayır'}</span>
                </div>
              </div>
              <div className="dept-note">{d.note}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

// System flow — recreates ARCHITECTURE.md section 2 as a live diagram
const SystemFlow = ({lang}) => {
  const t = STRINGS[lang];
  const node = (k, label, sub, tone, llm=false, icon=null) => (
    <div className={`flow-node flow-node--${tone}`} key={k}>
      <div className="flow-node-head">
        <span className="flow-node-icon">{icon || (llm ? <I.Brain/> : <I.Cog/>)}</span>
        {llm && <span className="flow-node-llm">LLM</span>}
      </div>
      <div className="flow-node-title">{label}</div>
      <div className="flow-node-sub">{sub}</div>
    </div>
  );
  return (
    <div className="flow">
      <div className="flow-row">
        {node('exch', 'Borsa (ccxt WS)', 'binance · bybit', 'info', false, <I.Pulse/>)}
        <FlowArrow/>
        {node('data', 'Veri Mühendisliği', 'data/ · DuckDB + Parquet', 'info')}
        <FlowArrow/>
        {node('sig', 'Sinyal Mühendisliği', 'signals/ · kalıp + confluence', 'info')}
        <FlowArrow/>
        {node('risk', 'Risk Officer', 'risk/ · boyutlandırma + breaker', 'warn')}
        <FlowArrow/>
        {node('port', 'Portföy', 'portfolio/ · korelasyon', 'info')}
        <FlowArrow/>
        {node('exec', 'Execution', 'execution/ · paper/live', 'accent', false, <I.Pulse/>)}
      </div>
      <div className="flow-row flow-row--meta">
        <div className="flow-col">
          <div className="flow-col-label">{t.flow.observers}</div>
          <div className="flow-col-nodes">
            {node('rsr', 'Researcher', 'agents/researcher · hipotez', 'accent', true)}
            {node('lab', 'Lab Scientist', 'agents/lab_scientist · drift', 'accent', true)}
          </div>
        </div>
        <div className="flow-col">
          <div className="flow-col-label">{t.flow.leadership}</div>
          <div className="flow-col-nodes">
            {node('ceo', 'CEO Office', 'agents/ceo · direktif', 'accent', true)}
            {node('an', 'Analytics & PM', 'agents/analyst · brief', 'accent', true)}
          </div>
        </div>
        <div className="flow-col">
          <div className="flow-col-label">{t.flow.operations}</div>
          <div className="flow-col-nodes">
            {node('ops', 'Operations / SRE', 'agents/ops_engineer · uptime', 'info')}
            {node('rag', 'Bilgi Tabanı / RAG', 'knowledge/ · ChromaDB', 'info', false, <I.Brain/>)}
          </div>
        </div>
      </div>
      <div className="flow-note">{t.flow.note}</div>
    </div>
  );
};

const FlowArrow = () => (
  <div className="flow-arrow">
    <svg width="22" height="14" viewBox="0 0 22 14" fill="none">
      <path d="M0 7h18M14 2l5 5-5 5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  </div>
);

// ============================================================ REPORTS
const Reports = ({data, lang}) => {
  const t = STRINGS[lang];
  const [tab, setTab] = React.useState('ceo');
  const md = tab === 'ceo' ? data.reports.ceo : data.reports.analytics;
  return (
    <div className="stack" style={{gap:18}}>
      <Card padded={false} action={null}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', padding:'14px 18px', borderBottom: '1px solid var(--border-soft)'}}>
          <div className="seg">
            <div className={'seg-btn ' + (tab==='ceo'?'active':'')} onClick={()=>setTab('ceo')}>{t.reports_tab.ceo}</div>
            <div className={'seg-btn ' + (tab==='analytics'?'active':'')} onClick={()=>setTab('analytics')}>{t.reports_tab.analytics}</div>
          </div>
          <div className="row">
            <Pill icon={<I.Clock/>}>17 Mayıs 2026</Pill>
            <Pill tone="info">{t.reports_tab.markdown}</Pill>
          </div>
        </div>
        <div style={{padding: '20px 28px', maxWidth: 820, margin: '0 auto'}}>
          <Markdown text={md}/>
        </div>
      </Card>
    </div>
  );
};

// Minimal markdown renderer — supports H1/H2/H3, paragraphs, lists, bold, inline code, tables.
const Markdown = ({text}) => {
  const lines = text.split('\n');
  const out = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('# ')) { out.push(<h1 key={key++}>{inline(line.slice(2))}</h1>); i++; }
    else if (line.startsWith('## ')) { out.push(<h2 key={key++}>{inline(line.slice(3))}</h2>); i++; }
    else if (line.startsWith('### ')) { out.push(<h3 key={key++}>{inline(line.slice(4))}</h3>); i++; }
    else if (line.startsWith('- ')) {
      const items = [];
      while (i < lines.length && lines[i].startsWith('- ')) { items.push(lines[i].slice(2)); i++; }
      out.push(<ul key={key++}>{items.map((x,k) => <li key={k}>{inline(x)}</li>)}</ul>);
    }
    else if (line.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) { rows.push(lines[i]); i++; }
      const cells = rows.map(r => r.split('|').slice(1, -1).map(c => c.trim()));
      const head = cells[0];
      const body = cells.slice(2); // skip separator row
      out.push(
        <table key={key++}>
          <thead><tr>{head.map((c, k) => <th key={k} className={k===0?'':'num'}>{c}</th>)}</tr></thead>
          <tbody>{body.map((row, r) => <tr key={r}>{row.map((c, k) => <td key={k} className={k===0?'':'num'}>{inline(c)}</td>)}</tr>)}</tbody>
        </table>
      );
    }
    else if (line.trim() === '') { i++; }
    else {
      let para = line;
      i++;
      while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('#') && !lines[i].startsWith('- ') && !lines[i].startsWith('|')) {
        para += ' ' + lines[i];
        i++;
      }
      out.push(<p key={key++}>{inline(para)}</p>);
    }
  }
  return <div className="md">{out}</div>;
};

function inline(text){
  // Split into <strong>, <code>, plain segments
  const parts = [];
  const rx = /(\*\*([^*]+)\*\*|`([^`]+)`)/g;
  let last = 0, m, k = 0;
  while ((m = rx.exec(text)) !== null){
    if (m.index > last) parts.push(<React.Fragment key={k++}>{text.slice(last, m.index)}</React.Fragment>);
    if (m[2] != null) parts.push(<strong key={k++}>{m[2]}</strong>);
    else if (m[3] != null) parts.push(<code key={k++}>{m[3]}</code>);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(<React.Fragment key={k++}>{text.slice(last)}</React.Fragment>);
  return parts;
}

window.Journal = Journal;
window.RiskScreen = RiskScreen;
window.Departments = Departments;
window.Reports = Reports;
