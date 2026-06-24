// Sidebar + topbar + halt banner + reusable screen chrome.

const Sidebar = ({active, onNav, lang, data, theme}) => {
  const t = STRINGS[lang];
  const items = [
    { id: 'overview',    icon: <I.Overview/>,   label: t.nav.overview,    count: null },
    { id: 'positions',   icon: <I.Positions/>,  label: t.nav.positions,   count: data.positions.length },
    { id: 'scanner',     icon: <I.Scanner/>,    label: t.nav.scanner,     count: data.scanner.length },
    { id: 'signals',     icon: <I.Signals/>,    label: t.nav.signals,     count: data.pending_signals.filter(s => s.gate_state !== 'risk_rejected').length },
    { id: 'journal',     icon: <I.Journal/>,    label: t.nav.journal,     count: data.trades.length },
    { id: 'risk',        icon: <I.Risk/>,       label: t.nav.risk,        count: null },
    { id: 'departments', icon: <I.Departments/>, label: t.nav.departments, count: 10 },
    { id: 'reports',     icon: <I.Reports/>,    label: t.nav.reports,     count: 2 },
  ];
  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <span className="sb-brand-logo"><I.Logo size={18}/></span>
        <div className="sb-brand-text">
          <div className="name">{t.brand}</div>
          <div className="tag">{t.tagline}</div>
        </div>
      </div>

      <div className="sb-section">Dashboard</div>
      {items.map(it => (
        <div
          key={it.id}
          className={'sb-link ' + (active === it.id ? 'active' : '')}
          onClick={() => onNav(it.id)}
        >
          {it.icon}
          <span>{it.label}</span>
          {it.count != null && <span className="sb-link-count">{it.count}</span>}
        </div>
      ))}

      <div className="sb-foot">
        <div className="sb-foot-row">
          <I.Phase/><span>{t.chip.phase6}</span>
        </div>
        <div className="sb-foot-row">
          <code>git e506e05</code>
        </div>
        <div className="sb-foot-row">
          <span style={{color: 'var(--text-muted)'}}>v0.6.2 · paper</span>
        </div>
      </div>
    </aside>
  );
};

const TopBar = ({title, subtitle, data, lang, right, actions}) => {
  const t = STRINGS[lang];
  return (
    <header className="topbar">
      <div>
        <div className="topbar-title">{title}</div>
        {subtitle && <span className="topbar-sub">{subtitle}</span>}
      </div>
      <div className="topbar-right">
        {right}
        <div className="statusbar">
          <span className={'live-dot ' + (data.halted ? 'halted' : '')}/>
          <span>{data.halted ? t.halted : t.paper}</span>
        </div>
        {actions && (data.halted
          ? <Button tone="primary" size="md" icon={<I.Pulse/>} onClick={actions.resumeBot}>{t.action.resume}</Button>
          : <Button tone="danger-outline" size="md" icon={<I.Halt/>} onClick={actions.haltBot}>{t.action.halt}</Button>
        )}
      </div>
    </header>
  );
};

const HaltBanner = ({lang}) => {
  const t = STRINGS[lang];
  return (
    <div className="halt-banner">
      <I.Halt/>
      <div>
        <b>{t.halted}</b> · <span style={{color:'var(--text-secondary)'}}>Daily DD breaker tripped at 6.12% &gt; 5.0% threshold. New orders blocked; open positions remain.</span>
      </div>
    </div>
  );
};

// helpers used by screens
const sideTone = side => side === 'long' ? 'profit' : 'loss';
const pnlTone = v => v > 0 ? 'profit' : v < 0 ? 'loss' : 'muted';
const symTag = pair => pair.split('/')[0];

window.Sidebar = Sidebar;
window.TopBar = TopBar;
window.HaltBanner = HaltBanner;
window.sideTone = sideTone;
window.pnlTone = pnlTone;
window.symTag = symTag;
