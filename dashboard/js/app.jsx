// Top-level App: routing, tweaks panel wiring, accent swapping.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "lang": "tr",
  "scenario": "normal",
  "accent": "mint",
  "density": "cozy",
  "theme": "dark"
}/*EDITMODE-END*/;

const ACCENTS = {
  mint:    { name: 'Mint',    swatch: '#5EEAD4', line: 'rgba(94,234,212,0.32)',  soft: 'rgba(94,234,212,0.14)'  },
  iris:    { name: 'Iris',    swatch: '#A78BFA', line: 'rgba(167,139,250,0.35)', soft: 'rgba(167,139,250,0.16)' },
  amber:   { name: 'Amber',   swatch: '#F5C04A', line: 'rgba(245,192,74,0.35)',  soft: 'rgba(245,192,74,0.16)'  },
  rose:    { name: 'Rose',    swatch: '#FB7185', line: 'rgba(251,113,133,0.35)', soft: 'rgba(251,113,133,0.16)' },
  azure:   { name: 'Azure',   swatch: '#60A5FA', line: 'rgba(96,165,250,0.35)',  soft: 'rgba(96,165,250,0.16)'  },
};

const SCENARIOS = ['normal','winning','breaker'];
const DENSITIES = ['compact','cozy','comfortable'];

const App = () => {
  const [tweaks, setTweak] = window.useTweaks(TWEAK_DEFAULTS);
  const [route, setRoute] = React.useState('overview');
  window.__navTo = setRoute;

  // Live data: PA_FETCH pulls from real API endpoints; mock is used as
  // initial render + fallback for endpoints not yet wired (Phase 3).
  const [data, setData] = React.useState(() => window.PA_BUILD(tweaks.scenario));
  React.useEffect(() => {
    let cancelled = false;
    let timer = null;
    const refresh = async () => {
      try {
        const live = await window.PA_FETCH(tweaks.scenario);
        if (!cancelled) setData(live);
      } catch (e) {
        console.error('PA_FETCH failed:', e);
      }
    };
    refresh();
    timer = setInterval(refresh, 4000);
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [tweaks.scenario]);

  // action layer
  const { actions, confirmState, dismiss, toasts, removeToast } = window.useActions(data, setData, tweaks.lang);

  // apply accent + theme + density tokens
  React.useEffect(() => {
    const root = document.documentElement;
    const acc = ACCENTS[tweaks.accent] || ACCENTS.mint;
    root.style.setProperty('--accent', acc.swatch);
    root.style.setProperty('--accent-soft', acc.soft);
    root.style.setProperty('--accent-line', acc.line);
    root.setAttribute('data-theme', tweaks.theme);
    // density
    const dens = tweaks.density;
    root.style.setProperty('--row-py', dens === 'compact' ? '7px' : dens === 'comfortable' ? '14px' : '11px');
    document.body.style.fontSize = dens === 'compact' ? '13px' : dens === 'comfortable' ? '14.5px' : '14px';
  }, [tweaks.accent, tweaks.theme, tweaks.density]);

  const t = STRINGS[tweaks.lang];
  const titles = {
    overview:    t.nav.overview,
    positions:   t.nav.positions,
    scanner:     t.nav.scanner,
    signals:     t.nav.signals,
    journal:     t.nav.journal,
    risk:        t.nav.risk,
    departments: t.nav.departments,
    reports:     t.nav.reports,
  };
  const subs = t.subs;

  let screen;
  switch (route) {
    case 'positions':   screen = <Positions data={data} lang={tweaks.lang} actions={actions}/>; break;
    case 'scanner':     screen = <Scanner data={data} lang={tweaks.lang}/>; break;
    case 'signals':     screen = <SignalQueue data={data} lang={tweaks.lang} actions={actions}/>; break;
    case 'journal':     screen = <Journal data={data} lang={tweaks.lang}/>; break;
    case 'risk':        screen = <RiskScreen data={data} lang={tweaks.lang} actions={actions}/>; break;
    case 'departments': screen = <Departments data={data} lang={tweaks.lang}/>; break;
    case 'reports':     screen = <Reports data={data} lang={tweaks.lang}/>; break;
    default:            screen = <Overview data={data} lang={tweaks.lang} actions={actions}/>;
  }

  return (
    <div className="app">
      <Sidebar active={route} onNav={setRoute} lang={tweaks.lang} data={data} theme={tweaks.theme}/>
      <main className="main">
        <TopBar title={titles[route]} subtitle={subs[route]} data={data} lang={tweaks.lang} actions={actions}/>
        <div className="page" data-screen-label={route}>
          {screen}
        </div>
      </main>

      <Tweaks tweaks={tweaks} setTweak={setTweak}/>
      <window.Confirm
        open={!!confirmState}
        title={confirmState?.title}
        body={confirmState?.body}
        confirmLabel={confirmState?.confirmLabel}
        cancelLabel={confirmState?.cancelLabel}
        tone={confirmState?.tone}
        onConfirm={confirmState?.onConfirm}
        onCancel={dismiss}
      />
      <window.ToastHost toasts={toasts} onDismiss={removeToast}/>
    </div>
  );
};

const Tweaks = ({tweaks, setTweak}) => (
  <window.TweaksPanel title="Ayarlar">
    <window.TweakSection label="Tema"/>
    <window.TweakRadio label="Görünüm" value={tweaks.theme} onChange={v => setTweak('theme', v)} options={[
      { value: 'dark', label: 'Koyu' },
      { value: 'light', label: 'Açık' },
    ]}/>
    <window.TweakSelect label="Aksan rengi" value={tweaks.accent} onChange={v => setTweak('accent', v)} options={
      Object.entries(ACCENTS).map(([k, v]) => ({ value: k, label: v.name }))
    }/>
    <window.TweakRadio label="Yoğunluk" value={tweaks.density} onChange={v => setTweak('density', v)} options={[
      { value: 'compact', label: 'Sıkı' },
      { value: 'cozy', label: 'Orta' },
      { value: 'comfortable', label: 'Rahat' },
    ]}/>
    <window.TweakSection label="Dil"/>
    <window.TweakRadio label="Arayüz dili" value={tweaks.lang} onChange={v => setTweak('lang', v)} options={[
      { value: 'tr', label: 'Türkçe' },
      { value: 'en', label: 'English' },
    ]}/>
    <window.TweakSection label="Mock Senaryo"/>
    <window.TweakRadio label="Gün tipi" value={tweaks.scenario} onChange={v => setTweak('scenario', v)} options={[
      { value: 'normal', label: 'Normal' },
      { value: 'winning', label: 'Kazanan' },
      { value: 'breaker', label: 'Breaker' },
    ]}/>
  </window.TweaksPanel>
);

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
