/* BLUECARBON ARENA — application shell, pages and workflows.
   Every page is wired to the real /api/v1 backend (proxied by Vite in dev). */
import { BrowserRouter, Routes, Route, Link, Navigate, useNavigate, useParams, useLocation } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api, token, setToken, type Project } from './api';
import { MapContainer, TileLayer, Marker, Polygon, Popup, useMap } from 'react-leaflet';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts';
import L from 'leaflet';

delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false } } });

/* ---------- design tokens ---------- */
const btn = 'inline-flex items-center gap-2 bg-teal-700 text-white px-4 py-2 rounded-lg font-medium hover:bg-teal-800 active:bg-teal-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors';
const btnGhost = 'inline-flex items-center gap-2 border border-slate-300 bg-white text-slate-700 px-4 py-2 rounded-lg font-medium hover:bg-slate-50 disabled:opacity-50 transition-colors';
const btnDanger = 'inline-flex items-center gap-2 bg-red-700 text-white px-4 py-2 rounded-lg font-medium hover:bg-red-800 disabled:opacity-50 transition-colors';
const inp = 'w-full border border-slate-300 rounded-lg p-2.5 bg-white text-[15px] focus:border-teal-600';
const card = 'bg-white rounded-xl shadow-sm border border-slate-200/70 p-5';
const label = 'block text-sm font-medium text-slate-600 mb-1';

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700', submitted: 'bg-amber-100 text-amber-800',
  under_review: 'bg-blue-100 text-blue-800', approved: 'bg-emerald-100 text-emerald-800',
  rejected: 'bg-red-100 text-red-800', archived: 'bg-slate-200 text-slate-600',
  pending: 'bg-amber-100 text-amber-800', accepted: 'bg-emerald-100 text-emerald-800',
};
function StatusBadge({ s }: { s: string }) {
  return <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_COLORS[s] || 'bg-slate-100 text-slate-700'}`}>{s.replace(/_/g, ' ')}</span>;
}
function EcoName({ e }: { e: string }) { return <>{e.replace(/_/g, ' ')}</>; }
function Loading({ what = 'Loading…' }: { what?: string }) {
  return <div className="flex items-center gap-3 text-slate-500 p-6" role="status"><span className="animate-spin h-5 w-5 border-2 border-teal-600 border-t-transparent rounded-full inline-block" />{what}</div>;
}
function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = (error as Error)?.message || String(error);
  let hint = '';
  if (msg.startsWith('401')) hint = 'Your session has expired or is invalid. Please log in again.';
  else if (msg.startsWith('403')) hint = 'Your role does not permit this action. See the role matrix in docs/SECURITY.md.';
  else if (msg.startsWith('404')) hint = 'The record was not found. It may have been archived.';
  else if (msg.startsWith('422') || msg.startsWith('400') || msg.startsWith('409')) hint = 'Please correct the input and try again.';
  else if (msg.startsWith('5')) hint = 'The backend returned a server error. Your data was not lost; retry shortly.';
  return <div className="bg-red-50 border border-red-200 text-red-800 rounded-lg p-4 my-3" role="alert">
    <p className="font-semibold">Request failed</p><p className="text-sm mt-1">{msg}</p>
    {hint && <p className="text-sm mt-1 text-red-700">{hint}</p>}
    {onRetry && <button className={btnGhost + ' mt-3'} onClick={onRetry}>Retry</button>}
  </div>;
}
function Empty({ title, body, cta }: { title: string; body: string; cta?: React.ReactNode }) {
  return <div className="border border-dashed border-slate-300 rounded-xl p-8 text-center bg-slate-50">
    <p className="font-semibold text-slate-700">{title}</p><p className="text-sm text-slate-500 mt-1">{body}</p>
    {cta && <div className="mt-4">{cta}</div>}</div>;
}
function Breadcrumbs({ items }: { items: [string, string][] }) {
  return <nav aria-label="Breadcrumb" className="text-sm text-slate-500 mb-4"><ol className="flex gap-2 flex-wrap">
    {items.map(([to, t], i) => <li key={to} className="flex gap-2">{i > 0 && <span aria-hidden>/</span>}{i === items.length - 1 ? <span aria-current="page" className="text-slate-800 font-medium">{t}</span> : <Link className="hover:text-teal-700" to={to}>{t}</Link>}</li>)}
  </ol></nav>;
}
function fmt(n?: number | null, digits = 2) { return n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits }); }
function Dd({ k, v }: { k: string; v: React.ReactNode }) {
  return <div><dt className="text-slate-500">{k}</dt><dd className="font-medium text-slate-800 mt-0.5">{v}</dd></div>;
}
function DdRow({ k, v }: { k: string; v?: React.ReactNode }) {
  return <div className="flex justify-between border-b py-2"><dt className="text-slate-500">{k}</dt><dd className="font-medium capitalize">{v ?? '—'}</dd></div>;
}

/* ---------- auth ---------- */
function useMe() { return useQuery({ queryKey: ['me'], queryFn: () => api('/api/v1/auth/me'), enabled: !!token(), retry: false, staleTime: 60_000 }); }

function Shell({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe(); const nav = useNavigate(); const loc = useLocation();
  const [open, setOpen] = useState(false);
  const allLinks: [string, string, string[]][] = [
    ['/app', 'Dashboard', []], ['/projects', 'Projects', ['/projects']], ['/map', 'Map', ['/map']],
    ['/marketplace', 'Marketplace', ['/marketplace']], ['/registry', 'Credit Registry', ['/registry']],
    ['/verification', 'Verification', ['/verification']],
    ...(me?.role === 'admin' ? ([['/admin', 'User Admin', ['/admin']], ['/audit', 'Audit Log', ['/audit']]] as [string, string, string[]][]) : []),
    ['/profile', 'Profile & Settings', ['/profile']],
  ];
  const links = allLinks.filter(([, , pre]) => pre.length === 0 || pre.some(p => loc.pathname.startsWith(p)));
  const logout = async () => {
    try { await api('/api/v1/auth/logout', { method: 'POST' }); } catch { /* token may already be invalid */ }
    setToken(null); qc.clear(); nav('/login');
  };
  return <div className="flex min-h-screen">
    <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 bg-white text-teal-800 px-3 py-2 rounded z-50">Skip to content</a>
    <aside className={`${open ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0 transition-transform fixed md:sticky top-0 z-40 h-screen w-64 bg-[#06283d] text-white p-5 flex flex-col`}>
      <Link to="/" className="text-lg font-extrabold tracking-wide leading-snug">🌊 BLUECARBON<br /><span className="text-teal-300">ARENA</span></Link>
      <p className="text-[11px] text-slate-300 mt-2">Blue-carbon project management &amp; illustrative accounting. Demo credits are simulated.</p>
      <nav className="mt-6 space-y-1 flex-1 overflow-y-auto" aria-label="Primary">{links.map(([h, l]) =>
        <Link key={h} to={h} aria-current={loc.pathname.startsWith(h) ? 'page' : undefined}
          className={`block rounded-lg px-3 py-2 text-sm transition-colors ${loc.pathname === h ? 'bg-teal-600/90 font-semibold' : 'hover:bg-white/10'}`}>{l}</Link>)}</nav>
      {me && <div className="mt-4 border-t border-white/15 pt-3 text-sm">
        <p className="font-semibold">{me.full_name}</p><p className="text-xs text-slate-300 capitalize">{me.role}</p>
        <button onClick={logout} className="mt-2 text-teal-300 underline text-sm hover:text-teal-200">Log out</button></div>}
    </aside>
    {open && <div className="fixed inset-0 bg-black/40 z-30 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
    <div className="flex-1 min-w-0">
      <header className="bg-white shadow-sm border-b border-slate-200 px-4 py-3 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center gap-3">
          <button className={btnGhost + ' md:hidden !px-3 !py-1.5'} aria-label="Toggle navigation menu" onClick={() => setOpen(o => !o)}>☰</button>
          <span className="md:hidden font-bold text-[#06283d]">BLUECARBON ARENA</span>
          <span className="hidden md:block text-sm text-slate-500">Project management · evidence · verification · illustrative carbon accounting</span>
        </div>
        {me ? <span className="text-sm text-slate-600">{me.full_name} <span className="capitalize bg-teal-50 text-teal-800 rounded-full px-2 py-0.5 ml-1 text-xs font-semibold">{me.role}</span></span>
          : <Link className={btn + ' !py-1.5'} to="/login">Login</Link>}
      </header>
      <main id="main" className="p-4 md:p-8 max-w-7xl mx-auto">{children}</main>
    </div>
  </div>;
}

function Protected({ children, roles }: { children: React.ReactNode; roles?: string[] }) {
  const { isLoading, isError, data: me } = useMe();
  const loc = useLocation();
  if (!token()) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (isLoading) return <Loading what="Restoring your session…" />;
  if (isError || !me) return <Shell><ErrorBox error={{ message: '401: Session expired' }} /><Link className={btn} to="/login">Log in again</Link></Shell>;
  if (roles && !roles.includes(me.role)) return <Shell><div className="max-w-lg mx-auto mt-10 text-center"><h1 className="text-2xl font-bold text-slate-800">403 — Not permitted</h1>
    <p className="text-slate-600 mt-2">Your role (<b className="capitalize">{me.role}</b>) cannot access this workspace. This restriction is enforced by the backend, not just hidden here.</p>
    <Link className={btn + ' mt-4'} to="/app">Back to dashboard</Link></div></Shell>;
  return <Shell>{children}</Shell>;
}

/* ---------- landing ---------- */
function Landing() {
  return <div className="min-h-screen bg-[#f4f7f5]">
    <header className="bg-[#06283d] text-white px-6 py-4 flex justify-between items-center sticky top-0 z-30">
      <b className="tracking-wide">🌊 BLUECARBON ARENA</b>
      <span className="space-x-4"><Link className="hover:text-teal-300" to="/login">Login</Link><Link className="bg-teal-600 hover:bg-teal-500 rounded-lg px-4 py-2 text-sm font-medium" to="/register">Register</Link></span>
    </header>
    <section className="px-6 py-16 max-w-5xl mx-auto">
      <p className="text-teal-700 font-semibold text-sm uppercase tracking-widest">Blue-carbon ecosystem restoration platform</p>
      <h1 className="text-4xl md:text-5xl font-extrabold text-[#06283d] mt-3 leading-tight">Mangroves, tidal marshes &amp; seagrass — managed end-to-end with traceable evidence</h1>
      <p className="mt-5 text-lg text-slate-600 max-w-3xl">Projects, field evidence, deterministic illustrative calculations, internal review decisions, a simulated credit registry and a demo marketplace — all connected through real, persisted backend workflows with role-based authorization and a full audit trail.</p>
      <div className="mt-8 flex gap-3 flex-wrap"><Link to="/register"><button className={btn}>Get started</button></Link><Link to="/login"><button className={btnGhost}>Demo accounts</button></Link></div>
      <div className="grid md:grid-cols-3 gap-4 mt-14">{([
        ['Evidence & Verification', 'Field photos, surveys and monitoring reports reviewed against a checklist with attributed, persisted decisions.'],
        ['Deterministic Calculations', 'Versioned illustrative methodology, exact input snapshots, immutable calculation runs, 44/12 CO₂ conversion.'],
        ['Simulated Marketplace', 'Issuance, listings and purchases are clearly labelled demonstrations — no accredited registry or real payments.']] as [string, string][]
      ).map(([t, d]) => <div key={t} className={card}><h3 className="font-bold text-[#06283d]">{t}</h3><p className="text-sm text-slate-600 mt-2">{d}</p></div>)}</div>
      <p className="mt-10 text-xs text-slate-500 max-w-3xl">Scientific-integrity notice: BLUECARBON ARENA is a project-management and carbon-accounting application. It is not an accredited registry, independent certifier, or source of officially verified carbon credits. All seeded records are fictional demonstration data.</p>
    </section>
    <footer className="bg-[#06283d] text-slate-300 text-sm px-6 py-6 text-center">BLUECARBON ARENA — university demonstration build · FastAPI + React + TypeScript</footer>
  </div>;
}

/* ---------- login / register ---------- */
const DEMO_ACCOUNTS: [string, string][] = [['admin', 'Administrator'], ['verifier', 'Verification officer'], ['developer', 'Project developer'], ['researcher', 'Researcher'], ['buyer', 'Buyer'], ['community', 'Community participant']];
function Auth({ mode }: { mode: 'login' | 'register' }) {
  const nav = useNavigate(); const loc = useLocation();
  const [e, setE] = useState(''); const [p, setP] = useState(''); const [n, setN] = useState(''); const [role, setRole] = useState('developer');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const from = (loc.state as any)?.from || '/app';
  async function submit(ev: React.FormEvent, email?: string, pass?: string) {
    ev.preventDefault(); setErr(''); setBusy(true);
    try {
      const path = mode === 'register' ? '/api/v1/auth/register' : '/api/v1/auth/login';
      const body: any = { email: email ?? e, password: pass ?? p };
      if (mode === 'register') { body.full_name = n; body.role = role; }
      const d = await api(path, { method: 'POST', body: JSON.stringify(body) });
      setToken(d.access_token); qc.invalidateQueries(); nav(from);
    } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  }
  return <div className="min-h-screen bg-gradient-to-b from-[#06283d] to-[#0a4d6b] flex items-start justify-center p-4">
    <div className="max-w-md w-full mt-10 bg-white p-8 rounded-2xl shadow-xl">
      <Link to="/" className="text-[#06283d] font-extrabold">🌊 BLUECARBON ARENA</Link>
      <h1 className="text-2xl font-bold mt-3">{mode === 'register' ? 'Create account' : 'Sign in'}</h1>
      {err && <p className="bg-red-50 border border-red-200 text-red-700 p-3 rounded-lg mt-3 text-sm" role="alert">{err}</p>}
      <form onSubmit={submit} className="space-y-3 mt-4">
        {mode === 'register' && <>
          <div><label className={label} htmlFor="reg-name">Full name</label><input id="reg-name" className={inp} value={n} onChange={x => setN(x.target.value)} /></div>
          <div><label className={label} htmlFor="reg-role">Role</label><select id="reg-role" className={inp} value={role} onChange={x => setRole(x.target.value)}>
            <option value="developer">Project developer</option><option value="researcher">Researcher / field contributor</option>
            <option value="buyer">Buyer</option><option value="community">Community participant</option></select>
            <p className="text-xs text-slate-500 mt-1">Admin and verifier accounts are created by an administrator only.</p></div>
        </>}
        <div><label className={label} htmlFor="auth-email">Email</label><input id="auth-email" type="email" className={inp} value={e} onChange={x => setE(x.target.value)} placeholder="you@example.com" required autoComplete="username" /></div>
        <div><label className={label} htmlFor="auth-pass">Password</label><input id="auth-pass" type="password" className={inp} value={p} onChange={x => setP(x.target.value)} required minLength={8} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} /></div>
        <button disabled={busy} className={btn + ' w-full justify-center'}>{busy ? 'Please wait…' : mode === 'register' ? 'Register' : 'Log in'}</button>
      </form>
      {mode === 'login' && <div className="mt-5 border-t pt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Development demo accounts (password <code className="bg-slate-100 px-1 rounded">DemoPass123!</code>)</p>
        <div className="grid grid-cols-2 gap-2 mt-2">{DEMO_ACCOUNTS.map(([u, t]) =>
          <button key={u} type="button" className="text-left text-sm border rounded-lg px-3 py-2 hover:bg-teal-50 hover:border-teal-400 transition-colors"
            onClick={ev => submit(ev as any, `${u}@bluecarbonarena.local`, 'DemoPass123!')}>
            <span className="font-medium text-slate-800">{t}</span><br /><span className="text-xs text-slate-500">{u}@…local</span></button>)}</div>
        <p className="text-[11px] text-slate-400 mt-2">Demo shortcuts work only while the backend runs in demo mode; they never grant extra permissions.</p>
      </div>}
      <p className="mt-4 text-sm">{mode === 'register' ? <Link to="/login">Already registered? Log in</Link> : <Link to="/register">No account? Register</Link>}</p>
    </div>
  </div>;
}

/* ---------- dashboard ---------- */
function Dashboard() {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['dash'], queryFn: () => api('/api/v1/dashboard') });
  const { data: me } = useMe();
  if (isLoading) return <Loading what="Loading dashboard from the API…" />;
  if (isError) return <div><h1 className="text-3xl font-bold mb-4">Dashboard</h1><ErrorBox error={error} onRetry={() => refetch()} /><p className="text-sm text-slate-500">Metrics above are never shown as zero when the request fails.</p></div>;
  const cards: [string, string | number, string][] = [
    ['Total projects', data.total_projects, 'All statuses visible to your role'],
    ['Draft', data.draft, ''], ['Submitted', data.submitted, 'Awaiting reviewer pickup'], ['Under review', data.under_review, ''],
    ['Approved', data.approved, 'Internal technical approval'], ['Rejected', data.rejected, ''],
    ['Evidence pending', data.evidence_pending, 'Needs reviewer attention'], ['Calculation runs', data.calculations, 'Immutable history'],
    ['Estimated potential (tCO₂e)', fmt(data.potential_tco2e), 'Illustrative estimate — not verified quantity'],
    ['Issued demo credits', fmt(data.issued_credits), 'Simulated — not externally verified'],
    ['Available credits', fmt(data.available_credits), 'Unsold/unretired in batches'], ['Active listings', data.active_listings, 'Simulated marketplace inventory'],
  ];
  const chart = Object.entries(data.ecosystem_distribution as Record<string, number>).map(([k, v]) => ({ name: k.replace(/_/g, ' '), Projects: v }));
  return <div>
    <h1 className="text-3xl font-bold text-[#06283d]">Dashboard</h1>
    <p className="text-sm text-slate-500 mt-1">Signed in as {me?.full_name} · role <span className="capitalize font-medium">{me?.role}</span>. Figures come from live database queries scoped to your permissions.</p>
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-6">{cards.map(([k, v, sub]) =>
      <div key={k} className={card}><p className="text-xs uppercase tracking-wide text-slate-500 font-semibold">{k}</p>
        <p className="text-2xl font-extrabold text-[#06283d] mt-1">{v}</p>{sub && <p className="text-[11px] text-slate-400 mt-1">{sub}</p>}</div>)}</div>
    <div className="grid lg:grid-cols-2 gap-4 mt-6">
      <div className={card + ' h-80'}>
        <h2 className="font-bold text-[#06283d]">Projects by ecosystem (count)</h2>
        {chart.length ? <ResponsiveContainer width="100%" height="85%"><BarChart data={chart}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Bar dataKey="Projects" fill="#0e7c7b" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
          : <Empty title="No projects yet" body="Create a project to see ecosystem distribution." cta={<Link className={btn} to="/projects/new">New project</Link>} />}
      </div>
      <div className={card}>
        <h2 className="font-bold text-[#06283d]">Recent projects</h2>
        {!data.recent_projects.length ? <Empty title="Nothing recorded yet" body="Projects you can view will appear here." /> :
          <ul className="divide-y mt-2">{data.recent_projects.map((p: Project) => <li key={p.id} className="py-2 flex justify-between items-center gap-2">
            <Link to={`/projects/${p.id}`} className="font-medium hover:text-teal-700 truncate">{p.name}</Link>
            <span className="shrink-0 flex items-center gap-2 text-sm text-slate-500"><EcoName e={p.ecosystem} /> <StatusBadge s={p.status} /></span></li>)}</ul>}
      </div>
    </div>
  </div>;
}

/* ---------- projects ---------- */
function Projects() {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['projects'], queryFn: () => api('/api/v1/projects') });
  const { data: me } = useMe();
  const [q, setQ] = useState(''); const [st, setSt] = useState(''); const [eco, setEco] = useState('');
  if (isLoading) return <Loading what="Loading projects…" />;
  if (isError) return <ErrorBox error={error} onRetry={() => refetch()} />;
  const items: Project[] = (data?.items ?? data ?? []).filter((p: Project) =>
    (!q || (p.name + p.region + p.country).toLowerCase().includes(q.toLowerCase())) && (!st || p.status === st) && (!eco || p.ecosystem === eco));
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/projects', 'Projects']]} />
    <div className="flex justify-between items-center flex-wrap gap-3">
      <div><h1 className="text-3xl font-bold text-[#06283d]">Project Explorer</h1>
        <p className="text-sm text-slate-500 mt-1">{me?.role === 'developer' ? 'Showing projects you own or collaborate on.' : 'Showing projects visible to your role.'} {data.total != null && `${data.items?.length ?? items.length} of ${data.total} loaded.`}</p></div>
      {(me?.role === 'developer' || me?.role === 'admin') && <Link to="/projects/new"><button className={btn}>+ New project</button></Link>}
    </div>
    <div className="grid md:grid-cols-3 gap-3 my-4">
      <input aria-label="Search projects" className={inp} placeholder="Search name, region, country…" value={q} onChange={e => setQ(e.target.value)} />
      <select aria-label="Filter by status" className={inp} value={st} onChange={e => setSt(e.target.value)}><option value="">Any status</option>{['draft', 'submitted', 'under_review', 'approved', 'rejected', 'archived'].map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select>
      <select aria-label="Filter by ecosystem" className={inp} value={eco} onChange={e => setEco(e.target.value)}><option value="">Any ecosystem</option>{['mangrove', 'tidal_marsh', 'seagrass'].map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select>
    </div>
    {!items.length ? <Empty title="No matching projects" body="Adjust filters, or create a project if you are a developer." cta={<Link className={btnGhost} to="/projects">Clear filters</Link>} /> :
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{items.map(p =>
        <Link key={p.id} to={`/projects/${p.id}`} className={card + ' block hover:shadow-md hover:border-teal-300 transition-all'}>
          <div className="flex justify-between items-start gap-2"><h3 className="font-bold text-[#06283d]">{p.name}</h3><StatusBadge s={p.status} /></div>
          <p className="text-sm text-slate-600 mt-2 line-clamp-2">{p.description || 'No description.'}</p>
          <p className="text-sm mt-3 text-slate-700"><EcoName e={p.ecosystem} /> · {fmt(p.area_ha)} ha · {p.reporting_years}-yr period</p>
          <p className="text-xs text-slate-400 mt-1">{p.region ? p.region + ', ' : ''}{p.country}{p.data_quality === 'stale' && <span className="ml-2 text-amber-600 font-medium">⚠ calculation stale</span>}</p>
        </Link>)}</div>}
  </div>;
}

function ProjectForm({ editId }: { editId?: number }) {
  const nav = useNavigate(); const { data: me } = useMe();
  const { data: existing, isLoading } = useQuery({ queryKey: ['p', editId], queryFn: () => api(`/api/v1/projects/${editId}`), enabled: !!editId });
  const [f, setF] = useState<any>({ name: '', description: '', ecosystem: 'mangrove', area_ha: 10, country: 'India', region: '', start_date: '2024-01-01', reporting_years: 5, latitude: 19.05, longitude: 72.85, boundary: null as any });
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false); const [loaded, setLoaded] = useState(false);
  useEffect(() => { if (existing && !loaded) { setF({ ...existing, boundary: existing.boundary ?? null }); setLoaded(true); } }, [existing, loaded]);
  if (editId && isLoading) return <Loading what="Loading project…" />;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === 'number' ? Number(e.target.value) : e.target.value });
  const makeRect = (lat: number, lon: number, d = 0.02) => ({ type: 'Polygon', coordinates: [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]] });
  async function submit(ev: React.FormEvent) {
    ev.preventDefault(); setErr(''); setBusy(true);
    try {
      const body = { name: f.name, description: f.description, country: f.country, region: f.region, ecosystem: f.ecosystem, area_ha: f.area_ha, start_date: f.start_date, reporting_years: f.reporting_years, methodology: f.methodology || 'BCA-ILLUSTRATIVE v1.0', latitude: f.latitude === '' ? null : f.latitude, longitude: f.longitude === '' ? null : f.longitude, boundary: f.boundary };
      const p = await api(editId ? `/api/v1/projects/${editId}` : '/api/v1/projects', { method: editId ? 'PUT' : 'POST', body: JSON.stringify(body) });
      qc.invalidateQueries(); nav(`/projects/${p.id}`);
    } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  }
  const num = (k: string, l: string, extra?: string) => <div><label className={label} htmlFor={'pf-' + k}>{l}{extra && <span className="font-normal text-slate-400"> {extra}</span>}</label><input id={'pf-' + k} type="number" step="any" className={inp} value={f[k] ?? ''} onChange={set(k)} /></div>;
  return <form onSubmit={submit} className={card + ' space-y-4 max-w-2xl'}>
    <Breadcrumbs items={[['/app', 'Home'], ['/projects', 'Projects'], ['/projects/new', editId ? 'Edit' : 'New']]} />
    <h1 className="text-2xl font-bold text-[#06283d]">{editId ? 'Edit project' : 'Create project'}</h1>
    <p className="text-sm text-slate-500">New projects start as <b>Draft</b>. Editing material fields (area, ecosystem, period, geometry…) of an approved project reopens it for review and marks calculations stale.</p>
    {err && <ErrorBox error={{ message: err }} />}
    <div><label className={label} htmlFor="pf-name">Project name *</label><input id="pf-name" className={inp} value={f.name} onChange={set('name')} required /></div>
    <div><label className={label} htmlFor="pf-desc">Description</label><textarea id="pf-desc" className={inp} rows={3} value={f.description} onChange={set('description')} placeholder="Restoration approach, partners, community involvement…" /></div>
    <div className="grid md:grid-cols-2 gap-4">
      <div><label className={label} htmlFor="pf-eco">Ecosystem</label><select id="pf-eco" className={inp} value={f.ecosystem} onChange={set('ecosystem')}><option value="mangrove">Mangrove</option><option value="tidal_marsh">Tidal marsh</option><option value="seagrass">Seagrass meadow</option></select></div>
      {num('area_ha', 'Eligible area', '(hectares)')}
      <div><label className={label} htmlFor="pf-country">Country</label><input id="pf-country" className={inp} value={f.country} onChange={set('country')} /></div>
      <div><label className={label} htmlFor="pf-region">Region / coast</label><input id="pf-region" className={inp} value={f.region} onChange={set('region')} /></div>
      <div><label className={label} htmlFor="pf-start">Start date (YYYY-MM-DD)</label><input id="pf-start" className={inp} value={f.start_date} onChange={set('start_date')} pattern="\d{4}-\d{2}-\d{2}" title="YYYY-MM-DD" /></div>
      {num('reporting_years', 'Reporting period', '(years, 1–100)')}
      {num('latitude', 'Latitude', '(-90…90, WGS84)')}{num('longitude', 'Longitude', '(-180…180, WGS84)')}
    </div>
    <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={!!f.boundary} onChange={e => setF({ ...f, boundary: e.target.checked ? (f.boundary ?? makeRect(f.latitude, f.longitude)) : null })} /> Include a rectangular demonstration boundary polygon around the site coordinates</label>
    <div className="flex gap-3"><button disabled={busy} className={btn}>{busy ? 'Saving…' : editId ? 'Save changes' : 'Create draft'}</button><Link className={btnGhost} to={editId ? `/projects/${editId}` : '/projects'}>Cancel</Link></div>
    {me?.role !== 'developer' && me?.role !== 'admin' && <p className="text-sm text-amber-700">Note: your role cannot create projects — the backend will reject this with 403.</p>}
  </form>;
}

function ProjectDetail() {
  const { id } = useParams(); const queryClient = useQueryClient();
  const { data: p, isLoading, isError, error, refetch } = useQuery({ queryKey: ['p', id], queryFn: () => api(`/api/v1/projects/${id}`) });
  const { data: ev, isLoading: evL } = useQuery({ queryKey: ['ev', id], queryFn: () => api(`/api/v1/projects/${id}/evidence`) });
  const { data: calcs } = useQuery({ queryKey: ['calc', id], queryFn: () => api(`/api/v1/projects/${id}/calculations`) });
  const { data: obs } = useQuery({ queryKey: ['obs', id], queryFn: () => api(`/api/v1/projects/${id}/observations`) });
  const { data: decs } = useQuery({ queryKey: ['decs', id], queryFn: () => api(`/api/v1/projects/${id}/decisions`) });
  const { data: me } = useMe();
  const [out, setOut] = useState(''); const [title, setTitle] = useState(''); const [cat, setCat] = useState('field_photo');
  const [file, setFile] = useState<File | null>(null); const [unc, setUnc] = useState(0.10); const [base, setBase] = useState(0);
  const [note, setNote] = useState(''); const [kind, setKind] = useState('vegetation');
  const canManage = me && (me.role === 'admin' || me.owner_id === undefined ? me.role === 'admin' : p?.owner_id === me.id);
  if (isLoading) return <Loading what="Loading project…" />;
  if (isError) return <div><ErrorBox error={error} onRetry={() => refetch()} />{(error as Error).message.startsWith('403') && <Link className={btn} to="/projects">Back to projects</Link>}</div>;
  async function act(path: string, method = 'POST', body?: any) {
    setOut(''); try { const r = await api(path, { method, body: body ? JSON.stringify(body) : undefined }); setOut(typeof r === 'string' ? r : JSON.stringify(r, null, 1)); queryClient.invalidateQueries(); }
    catch (e: any) { setOut('✗ ' + e.message); }
  }
  async function submitEvidence(e: React.FormEvent) {
    e.preventDefault(); setOut('');
    const fd = new FormData(); fd.append('title', title); fd.append('category', cat); if (file) fd.append('file', file);
    try { await api(`/api/v1/projects/${id}/evidence`, { method: 'POST', headers: {}, body: fd }); setTitle(''); setFile(null); (document.getElementById('ev-file') as HTMLInputElement).value = ''; queryClient.invalidateQueries({ queryKey: ['ev', id] }); setOut('Evidence submitted and persisted.'); }
    catch (x: any) { setOut('✗ ' + x.message); }
  }
  const st = p.status;
  return <div className="space-y-6">
    <Breadcrumbs items={[['/app', 'Home'], ['/projects', 'Projects'], [`/projects/${id}`, p.name]]} />
    <div className={card}>
      <div className="flex justify-between items-start flex-wrap gap-3">
        <div><h1 className="text-3xl font-bold text-[#06283d]">{p.name}</h1>
          <p className="text-slate-600 mt-1 max-w-2xl">{p.description}</p></div>
        <div className="flex items-center gap-2"><StatusBadge s={st} />{p.data_quality === 'stale' && <span className="text-xs font-semibold bg-amber-100 text-amber-800 rounded-full px-2 py-1">⚠ inputs changed — recalculate</span>}</div>
      </div>
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 text-sm">
        <Dd k="Ecosystem" v={<EcoName e={p.ecosystem} />} />
        <Dd k="Area" v={`${fmt(p.area_ha)} ha`} />
        <Dd k="Period" v={`${p.reporting_years} years from ${p.start_date}`} />
        <Dd k="Methodology" v={p.methodology} />
        <Dd k="Location" v={`${p.region ? p.region + ', ' : ''}${p.country}`} />
        <Dd k="Coordinates" v={p.latitude != null ? `${p.latitude}, ${p.longitude}` : 'not set'} />
        <Dd k="Owner" v={`user #${p.owner_id}${me?.id === p.owner_id ? ' (you)' : ''}`} />
        <Dd k="Evidence / calcs" v={`${p.evidence_count} / ${p.calculation_count}`} />
      </dl>
      {out && <pre className="bg-slate-50 border rounded-lg p-3 mt-4 overflow-auto text-xs max-h-56">{out}</pre>}
      <div className="flex gap-2 mt-5 flex-wrap">
        {canManage && st === 'draft' && <button className={btn} onClick={() => act(`/api/v1/projects/${id}/transition?new_status=submitted`)}>Submit for review</button>}
        {canManage && st === 'rejected' && <button className={btn} onClick={() => act(`/api/v1/projects/${id}/transition?new_status=submitted`)}>Resubmit after corrections</button>}
        {canManage && (st === 'draft' || st === 'approved' || st === 'rejected') && <Link className={btnGhost} to={`/projects/${id}/edit`}>Edit project</Link>}
        {(canManage || me?.role === 'verifier') && <button className={btnGhost} onClick={() => act(`/api/v1/projects/${id}/calculations`, 'POST', { uncertainty: unc, baseline_tco2e: base })}>Run calculation (unc {unc}, baseline {base})</button>}
        <label className="flex items-center gap-1 text-sm text-slate-600">uncertainty <input aria-label="Uncertainty deduction" className="border rounded p-1 w-16" type="number" step="0.01" min="0" max="0.5" value={unc} onChange={e => setUnc(Number(e.target.value))} /></label>
        <label className="flex items-center gap-1 text-sm text-slate-600">baseline tCO₂e <input aria-label="Baseline stock" className="border rounded p-1 w-20" type="number" step="any" min="0" value={base} onChange={e => setBase(Number(e.target.value))} /></label>
      </div>
      <p className="text-xs text-slate-400 mt-3">Approval/rejection is performed only by verification officers in the Verification workspace — never from this screen.</p>
    </div>

    <div className="grid lg:grid-cols-2 gap-6">
      <section className={card}>
        <h2 className="font-bold text-xl text-[#06283d]">Evidence</h2>
        <p className="text-sm text-slate-500">Supporting records with provenance (SHA-256, size, validated content type). Evidence supports review; it does not independently prove scientific conclusions.</p>
        {evL ? <Loading /> : !ev?.length ? <Empty title="No evidence yet" body="Submit photographs, surveys, monitoring reports or documentation." /> :
          <ul className="divide-y mt-3">{ev.map((e: any) => <li key={e.id} className="py-2.5 flex justify-between items-center gap-2 flex-wrap">
            <div><p className="font-medium text-slate-800">{e.title} <span className="text-xs text-slate-500">· {e.category.replace(/_/g, ' ')}</span></p>
              {e.sha256 && <p className="text-[11px] text-slate-400">sha256:{e.sha256.slice(0, 16)}… · {e.size_bytes} bytes</p>}
              {e.reviewer_notes && <p className="text-xs text-slate-500 italic">reviewer: {e.reviewer_notes}</p>}</div>
            <div className="flex items-center gap-2"><StatusBadge s={e.status} />{e.filename && <a className="text-sm underline" href={`/api/v1/evidence/${e.id}/download`} onClick={async ev2 => { ev2.preventDefault(); const r = await fetch(`/api/v1/evidence/${e.id}/download`, { headers: { Authorization: `Bearer ${token()}` } }); if (!r.ok) { setOut('✗ Download failed: ' + r.status); return; } const blob = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = e.filename; a.click(); }}>Download</a>}</div>
          </li>)}</ul>}
        {me && me.role !== 'buyer' && <form onSubmit={submitEvidence} className="flex gap-2 mt-4 flex-wrap">
          <input aria-label="Evidence title" className={inp + ' flex-1 min-w-40'} value={title} onChange={e => setTitle(e.target.value)} placeholder="Evidence title" required />
          <select aria-label="Evidence category" className={inp + ' w-44'} value={cat} onChange={e => setCat(e.target.value)}>{['field_photo', 'site_survey', 'project_documentation', 'monitoring_report', 'satellite_derived', 'ecological_measurement', 'administrative'].map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}</select>
          <input id="ev-file" aria-label="Attach file" type="file" accept=".jpg,.jpeg,.png,.pdf,.txt,.csv,image/jpeg,image/png,application/pdf,text/plain,text/csv" className="text-sm border rounded p-2 flex-1 min-w-48" onChange={e => setFile(e.target.files?.[0] ?? null)} />
          <button className={btn}>Submit</button>
        </form>}
        <p className="text-[11px] text-slate-400 mt-2">Files ≤ 10 MB; JPEG/PNG/PDF/TXT/CSV validated by magic bytes; stored privately outside web roots.</p>
      </section>

      <section className={card}>
        <h2 className="font-bold text-xl text-[#06283d]">Calculation history</h2>
        <p className="text-sm text-slate-500">Immutable, versioned illustrative runs. Each row stores its exact input snapshot; edits never overwrite history.</p>
        {!calcs?.length ? <Empty title="No calculation runs yet" body="Owners and reviewers can run the deterministic engine." /> :
          <ul className="divide-y mt-3">{calcs.map((c: any) => <li key={c.id} className="py-3">
            <p className="font-semibold text-slate-800">Run #{c.id}: <span className="text-teal-800">{fmt(c.result_tco2e)} tCO₂e</span> net estimated removals <span className="text-xs font-normal text-slate-500">(gross {fmt(c.gross_tco2e)})</span></p>
            <p className="text-xs text-slate-500">{c.methodology_version} · inputs: {JSON.stringify(c.inputs)} · by user #{c.created_by} · {new Date(c.created_at).toLocaleString()}</p>
            <details className="mt-1"><summary className="text-xs cursor-pointer text-teal-700">Show formula steps</summary><ol className="text-xs text-slate-600 list-decimal ml-5 mt-1">{c.steps.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol></details>
            {!!c.warnings?.length && <p className="text-amber-700 text-xs mt-1">⚠ {c.warnings.join(' ')}</p>}
          </li>)}</ul>}
      </section>

      <section className={card}>
        <h2 className="font-bold text-xl text-[#06283d]">Review decisions</h2>
        {!decs?.length ? <p className="text-sm text-slate-500 mt-2">No decisions recorded yet. Decisions are made only in the Verification workspace by authorized reviewers.</p> :
          <ul className="divide-y mt-2">{decs.map((d: any) => <li key={d.id} className="py-2 text-sm"><StatusBadge s={d.decision} /> <span className="text-slate-600">by reviewer #{d.reviewer_id} · {new Date(d.created_at).toLocaleString()}</span><p className="text-slate-500 mt-1">{d.reason}</p></li>)}</ul>}
        <p className="text-[11px] text-slate-400 mt-2">Internal technical review — explicitly not independent third-party certification.</p>
      </section>

      <section className={card}>
        <h2 className="font-bold text-xl text-[#06283d]">Field observations</h2>
        {!obs?.length ? <p className="text-sm text-slate-500 mt-2">No observations recorded.</p> :
          <ul className="divide-y max-h-56 overflow-auto">{obs.map((o: any) => <li key={o.id} className="py-2 text-sm"><b className="capitalize">{o.kind.replace(/_/g, ' ')}</b> <span className="text-slate-500">{o.observed_on}</span><p className="text-slate-600">{o.note}</p>{o.latitude != null && <p className="text-xs text-slate-400">@ {o.latitude}, {o.longitude}</p>}</li>)}</ul>}
        {me && me.role !== 'buyer' && <form className="flex gap-2 mt-3 flex-wrap" onSubmit={async e => { e.preventDefault(); if (!note.trim()) return; await act(`/api/v1/projects/${id}/observations`, 'POST', { kind, note }); setNote(''); }}>
          <select aria-label="Observation kind" className={inp + ' w-44'} value={kind} onChange={e => setKind(e.target.value)}>{['vegetation', 'water_quality', 'wildlife_sighting', 'erosion', 'community_feedback', 'other'].map(k => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}</select>
          <input aria-label="Observation note" className={inp + ' flex-1 min-w-40'} value={note} onChange={e => setNote(e.target.value)} placeholder="Observation note…" required />
          <button className={btnGhost}>Add observation</button>
        </form>}
      </section>
    </div>
  </div>;
}

/* ---------- verification workspace ---------- */
function Verification() {
  const { data, isLoading, isError, error } = useQuery({ queryKey: ['projects'], queryFn: () => api('/api/v1/projects') });
  const [sel, setSel] = useState<number | null>(null);
  const { data: pkg, isFetching: pkgL } = useQuery({ queryKey: ['pkg', sel], queryFn: () => api(`/api/v1/projects/${sel}/review-package`), enabled: !!sel });
  const [reason, setReason] = useState(''); const [checklist, setChecklist] = useState<Record<string, boolean>>({}); const [msg, setMsg] = useState('');
  const qc2 = useQueryClient();
  if (isLoading) return <Loading what="Loading queue…" />;
  if (isError) return <ErrorBox error={error} />;
  const queue = (data?.items ?? data ?? []).filter((p: Project) => ['submitted', 'under_review'].includes(p.status));
  async function decide(decision: string) {
    if (!sel) return; setMsg('');
    if (decision === 'approved' && Object.keys(checklist).some(k => !checklist[k])) { setMsg('✗ Complete every checklist item before approving.'); return; }
    try {
      const r = await api(`/api/v1/projects/${sel}/decisions`, { method: 'POST', body: JSON.stringify({ decision, reason, checklist }) });
      setMsg('✓ ' + JSON.stringify(r)); setSel(null); setChecklist({}); setReason('');
      qc2.invalidateQueries(); qc2.invalidateQueries({ queryKey: ['pkg'] });
    } catch (e: any) { setMsg('✗ ' + e.message); }
  }
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/verification', 'Verification']]} />
    <h1 className="text-3xl font-bold text-[#06283d]">Verification Workspace</h1>
    <p className="text-sm text-slate-500 mt-1">Internal technical review by verification officers. Decisions are persisted with attribution and audit entries. Approval ≠ third-party certification, and alone does not authorize issuance unless prerequisites pass at issue time.</p>
    {msg && <pre className="bg-white border rounded-lg p-3 mt-3 text-sm whitespace-pre-wrap">{msg}</pre>}
    <div className="grid lg:grid-cols-5 gap-4 mt-6">
      <div className="lg:col-span-2 space-y-2">
        <h2 className="font-bold text-slate-700">Review queue ({queue.length})</h2>
        {!queue.length ? <Empty title="Queue is empty" body="Projects submitted by developers appear here." /> :
          queue.map((p: Project) => <button key={p.id} onClick={() => { setSel(p.id); setChecklist({}); }} className={`${card} w-full text-left block ${sel === p.id ? '!border-teal-500 ring-2 ring-teal-200' : 'hover:border-teal-300'}`}>
            <div className="flex justify-between gap-2"><span className="font-semibold text-slate-800">{p.name}</span><StatusBadge s={p.status} /></div>
            <p className="text-xs text-slate-500 mt-1"><EcoName e={p.ecosystem} /> · {fmt(p.area_ha)} ha · owner #{p.owner_id}</p></button>)}
      </div>
      <div className="lg:col-span-3">
        {!sel ? <Empty title="Select a project" body="Open a review package: project data, evidence statuses, latest calculation, missing items and prior decisions." /> :
          pkgL && !pkg ? <Loading what="Assembling review package…" /> : pkg && <div className={card}>
            <h2 className="font-bold text-xl text-[#06283d]">{pkg.project.name}</h2>
            <p className="text-sm text-slate-600 mt-1">{pkg.project.description}</p>
            <div className="grid grid-cols-2 gap-3 text-sm mt-3">
              <p><span className="text-slate-500">Area:</span> {fmt(pkg.project.area_ha)} ha</p><p><span className="text-slate-500">Period:</span> {pkg.project.reporting_years} yr</p>
              <p><span className="text-slate-500">Methodology:</span> {pkg.project.methodology}</p><p><span className="text-slate-500">Data quality:</span> {pkg.project.data_quality}</p>
            </div>
            {!!pkg.missing_items.length && <p className="mt-3 text-sm bg-amber-50 border border-amber-200 text-amber-800 rounded p-2">Missing: {pkg.missing_items.join('; ')}</p>}
            <h3 className="font-semibold mt-4 text-slate-700">Evidence ({pkg.evidence.length})</h3>
            <ul className="text-sm divide-y">{pkg.evidence.map((e: any) => <li key={e.id} className="py-1.5 flex justify-between"><span>{e.title} <span className="text-xs text-slate-400">({e.category})</span></span><StatusBadge s={e.status} /></li>)}</ul>
            <h3 className="font-semibold mt-4 text-slate-700">Latest calculation</h3>
            {pkg.latest_calculation ? <p className="text-sm mt-1">Run #{pkg.latest_calculation.id}: <b>{fmt(pkg.latest_calculation.result_tco2e)} tCO₂e</b> net estimate · {pkg.latest_calculation.methodology_version} {pkg.latest_calculation.warnings?.length ? <span className="text-amber-700">· ⚠ {pkg.latest_calculation.warnings.join(' ')}</span> : null}</p> : <p className="text-sm text-slate-500 mt-1">None — request a calculation from the owner.</p>}
            <h3 className="font-semibold mt-4 text-slate-700">Previous decisions</h3>
            {!pkg.previous_decisions.length ? <p className="text-sm text-slate-500">First review for this project.</p> :
              <ul className="text-sm">{pkg.previous_decisions.map((d: any) => <li key={d.id} className="py-1"><StatusBadge s={d.decision} /> {d.reason} <span className="text-slate-400">· {new Date(d.created_at).toLocaleString()}</span></li>)}</ul>}
            <h3 className="font-semibold mt-4 text-slate-700">Review checklist</h3>
            <ul className="mt-1 space-y-1">{(pkg.checklist_template as string[]).map(k => <li key={k}><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!checklist[k]} onChange={e => setChecklist({ ...checklist, [k]: e.target.checked })} /> {k.replace(/_/g, ' ')}</label></li>)}</ul>
            <div className="mt-3"><label className={label} htmlFor="vr-reason">Decision reason (required, persisted & audited)</label><textarea id="vr-reason" className={inp} rows={2} value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. Boundary matches survey; two accepted monitoring reports; inputs consistent with methodology v1.0" /></div>
            <div className="flex gap-2 mt-3"><button className={btn} onClick={() => decide('approved')}>Approve (internal review)</button><button className={btnDanger} onClick={() => decide('rejected')}>Reject</button></div>
          </div>}
      </div>
    </div>
  </div>;
}

/* ---------- registry ---------- */
function Registry() {
  const { data: me } = useMe();
  const { data: calcs } = useQuery({ queryKey: ['projects'], queryFn: () => api('/api/v1/projects') });
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['credits'], queryFn: () => api('/api/v1/credits') });
  const { data: auditish } = useQuery({ queryKey: ['orders'], queryFn: () => api('/api/v1/orders') });
  const [cid, setCid] = useState(''); const [qty, setQty] = useState(''); const [msg, setMsg] = useState('');
  const qc2 = useQueryClient();
  // gather calculations per project lazily when issuing
  async function issue() {
    setMsg(''); try {
      const r = await api('/api/v1/credits/issue', { method: 'POST', body: JSON.stringify({ calculation_id: Number(cid), quantity: Number(qty) }) });
      setMsg('✓ Issued batch ' + r.serial + ' (' + r.quantity + ' credits) — ' + r.label); qc2.invalidateQueries();
    } catch (e: any) { setMsg('✗ ' + e.message); }
  }
  async function retire(id: number) {
    const q = prompt('Quantity to retire from batch #' + id + ':'); if (!q) return;
    const fd = new FormData(); fd.append('quantity', q); fd.append('reason', 'demo retirement');
    try { const r = await api(`/api/v1/credits/${id}/retire`, { method: 'POST', headers: {}, body: fd }); setMsg('✓ Retired. Batch now: ' + r.retired + ' retired, ' + r.available + ' available. ' + r.note); qc2.invalidateQueries(); }
    catch (e: any) { setMsg('✗ ' + e.message); }
  }
  if (isLoading) return <Loading what="Loading registry…" />;
  if (isError) return <ErrorBox error={error} onRetry={() => refetch()} />;
  const batches = data?.items ?? [];
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/registry', 'Credit Registry']]} />
    <h1 className="text-3xl font-bold text-[#06283d]">Credit Registry <span className="align-middle text-xs font-semibold bg-amber-100 text-amber-800 rounded-full px-2 py-1 ml-2">SIMULATED</span></h1>
    <p className="text-sm text-slate-500 mt-1 max-w-3xl">Demonstration issuance only. These are not externally verified, accredited, or tradable credits. Lifecycle tracked per batch: issued → listed → sold → retired, with consistency enforced server-side (no double issuance beyond the eligible calculated quantity).</p>
    {msg && <pre className="bg-white border rounded-lg p-3 mt-3 text-sm whitespace-pre-wrap">{msg}</pre>}
    {(me?.role === 'verifier' || me?.role === 'admin') && <div className={card + ' mt-4 flex items-end gap-3 flex-wrap'}>
      <div><label className={label} htmlFor="iss-calc">Calculation run ID</label><input id="iss-calc" className={inp + ' w-36'} value={cid} onChange={e => setCid(e.target.value)} placeholder="e.g. 1" /></div>
      <div><label className={label} htmlFor="iss-qty">Quantity (≤ eligible calc result)</label><input id="iss-qty" className={inp + ' w-36'} type="number" step="any" min="0" value={qty} onChange={e => setQty(e.target.value)} /></div>
      <button className={btn} onClick={issue}>Issue simulated batch</button>
      <p className="text-xs text-slate-500 basis-full">Server enforces: approved project, fresh (non-stale) inputs, latest calculation run, quantity ≤ result, no duplicate issuance beyond the eligible quantity.</p>
    </div>}
    <div className="overflow-x-auto mt-5"><table className="w-full text-sm bg-white rounded-xl shadow-sm border">
      <thead className="bg-slate-50 text-left text-slate-600"><tr>{['Batch', 'Serial', 'Project', 'Calc run', 'Issued', 'Available', 'Sold', 'Retired', 'Status', 'Actions'].map(h => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
      <tbody>{!batches.length ? <tr><td colSpan={10} className="p-6 text-center text-slate-500">No credit batches exist yet.</td></tr> :
        batches.map((b: any) => <tr key={b.id} className="border-t hover:bg-slate-50">
          <td className="px-3 py-2">#{b.id}</td><td className="px-3 py-2 font-mono text-xs">{b.serial}</td>
          <td className="px-3 py-2"><Link className="underline" to={`/projects/${b.project_id}`}>proj #{b.project_id}</Link></td>
          <td className="px-3 py-2">#{b.calculation_id}</td><td className="px-3 py-2">{fmt(b.quantity)}</td><td className="px-3 py-2 font-semibold text-teal-800">{fmt(b.available)}</td>
          <td className="px-3 py-2">{fmt(b.sold)}</td><td className="px-3 py-2">{fmt(b.retired)}</td><td className="px-3 py-2"><StatusBadge s={b.status} /></td>
          <td className="px-3 py-2"><button className={btnGhost + ' !px-2 !py-1 text-xs'} onClick={() => retire(b.id)}>Retire</button></td></tr>)}</tbody></table></div>
    <div className="grid md:grid-cols-3 gap-4 mt-6">{(['issued', 'available', 'sold'] as const).map(k => {
      const total = batches.reduce((s: number, b: any) => s + (b[k === 'issued' ? 'quantity' : k] || 0), 0);
      return <div key={k} className={card}><p className="text-xs uppercase text-slate-500 font-semibold">{k} totals (simulated credits)</p><p className="text-2xl font-extrabold text-[#06283d] mt-1">{fmt(total)}</p></div>; })}</div>
    <h2 className="font-bold text-xl mt-8 text-[#06283d]">Issuance & transaction history</h2>
    <p className="text-sm text-slate-500">Orders referencing these batches (your scope):</p>
    <ul className="mt-2 text-sm space-y-1">{(auditish?.items ?? []).slice(0, 10).map((o: any) => <li key={o.id} className="bg-white border rounded px-3 py-2">Order #{o.id} · listing #{o.listing_id} · buyer #{o.buyer_id} · {fmt(o.quantity)} credits @ ${fmt(o.unit_price)} = ${fmt(o.total_usd)} · <StatusBadge s={o.status} /></li>)}
      {!(auditish?.items ?? []).length && <li className="text-slate-500">No orders yet.</li>}</ul>
    {calcs && <p className="text-xs text-slate-400 mt-4">Tip for demos: open an approved project, run a calculation, then issue against that run's ID above.</p>}
  </div>;
}

/* ---------- marketplace ---------- */
function Marketplace() {
  const { data: me } = useMe();
  const [q, setQ] = useState(''); const [eco, setEco] = useState(''); const [sort, setSort] = useState('new');
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['listings', q, eco], queryFn: () => api(`/api/v1/listings?q=${encodeURIComponent(q)}&ecosystem=${eco}`) });
  const { data: orders } = useQuery({ queryKey: ['orders'], queryFn: () => api('/api/v1/orders') });
  const { data: credits } = useQuery({ queryKey: ['credits'], queryFn: () => api('/api/v1/credits') });
  const [msg, setMsg] = useState(''); const [qtyBy, setQtyBy] = useState<Record<number, string>>({}); const [busyId, setBusyId] = useState<number | null>(null);
  const qc2 = useQueryClient();
  async function buy(l: any) {
    setBusyId(l.id); setMsg('');
    const qty = Number(qtyBy[l.id] || 1);
    try { const r = await api(`/api/v1/listings/${l.id}/purchase`, { method: 'POST', body: JSON.stringify({ quantity: qty, idempotency_key: crypto.randomUUID() }) });
      setMsg(`✓ Simulated order #${r.id} placed: ${r.quantity} credits for $${r.total_usd} (${r.status}). No real payment processed.`); qc2.invalidateQueries(); }
    catch (e: any) { setMsg('✗ ' + e.message); } finally { setBusyId(null); }
  }
  async function list(batchId: string, title: string, price: string, qty: string) {
    setMsg(''); try { const r = await api('/api/v1/listings', { method: 'POST', body: JSON.stringify({ batch_id: Number(batchId), title, price_usd: Number(price), quantity: Number(qty) }) }); setMsg('✓ Listing created (#' + r.id + '). ' + r.note); qc2.invalidateQueries(); }
    catch (e: any) { setMsg('✗ ' + e.message); }
  }
  if (isLoading) return <Loading what="Loading marketplace…" />;
  if (isError) return <ErrorBox error={error} onRetry={() => refetch()} />;
  let items = (data?.items ?? []).slice();
  if (sort === 'price_asc') items.sort((a: any, b: any) => a.price_usd - b.price_usd);
  if (sort === 'price_desc') items.sort((a: any, b: any) => b.price_usd - a.price_usd);
  const myListable = (credits?.items ?? []).filter((b: any) => ['issued', 'partially_sold', 'listed'].includes(b.status) && b.available > 0);
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/marketplace', 'Marketplace']]} />
    <h1 className="text-3xl font-bold text-[#06283d]">Marketplace <span className="align-middle text-xs font-semibold bg-amber-100 text-amber-800 rounded-full px-2 py-1 ml-2">SIMULATED TRANSACTIONS</span></h1>
    <p className="text-sm text-slate-500 mt-1 max-w-3xl">No payment gateway is configured; purchases create demo orders and move demo inventory atomically. Inventory checks, overselling protection and duplicate-submission prevention are enforced server-side.</p>
    {msg && <pre className="bg-white border rounded-lg p-3 mt-3 text-sm whitespace-pre-wrap">{msg}</pre>}
    <div className="grid md:grid-cols-3 gap-3 my-4">
      <input aria-label="Search listings" className={inp} placeholder="Search project or listing title…" value={q} onChange={e => setQ(e.target.value)} />
      <select aria-label="Ecosystem filter" className={inp} value={eco} onChange={e => setEco(e.target.value)}><option value="">Any ecosystem</option>{['mangrove', 'tidal_marsh', 'seagrass'].map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select>
      <select aria-label="Sort" className={inp} value={sort} onChange={e => setSort(e.target.value)}><option value="new">Newest</option><option value="price_asc">Price ↑</option><option value="price_desc">Price ↓</option></select>
    </div>
    {!items.length ? <Empty title="No active listings" body="Developers can list available credit batches from their approved projects below." /> :
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{items.map((l: any) => <div key={l.id} className={card + ' flex flex-col'}>
        <div className="flex justify-between gap-2"><h3 className="font-bold text-[#06283d]">{l.title}</h3><span className="text-xs bg-emerald-50 text-emerald-700 rounded-full px-2 py-0.5 h-fit">{l.status}</span></div>
        <p className="text-sm text-slate-600 mt-1"><Link className="underline" to={`/projects/${l.project_id}`}>{l.project_name}</Link> · <EcoName e={l.ecosystem} /></p>
        <p className="text-xs text-slate-500 mt-1">Batch {l.batch_serial} · {l.verification_status}</p>
        <div className="flex justify-between items-end mt-3">
          <p><span className="text-2xl font-extrabold text-teal-800">${fmt(l.price_usd)}</span> <span className="text-sm text-slate-500">/ credit USD</span></p>
          <p className="text-sm text-right"><b>{fmt(l.available, 0)}</b> available<span className="block text-xs text-slate-400">of {fmt(l.quantity, 0)} listed</span></p></div>
        <div className="flex gap-2 mt-3 items-center">
          <input aria-label={`Quantity for ${l.title}`} className="border rounded-lg p-2 w-24" type="number" min="1" step="1" defaultValue="1" onChange={e => setQtyBy(s => ({ ...s, [l.id]: e.target.value }))} />
          <button className={btn} disabled={busyId === l.id || !(me?.role === 'buyer' || me?.role === 'admin')} onClick={() => buy(l)}>{busyId === l.id ? 'Placing…' : 'Buy (simulated)'}</button>
        </div>
        {me?.role !== 'buyer' && me?.role !== 'admin' && <p className="text-[11px] text-slate-400 mt-2">Only buyers/admins can place orders — backend enforces this (403 otherwise).</p>}
      </div>)}</div>}
    {(me?.role === 'developer' || me?.role === 'admin') && myListable.length > 0 && <div className={card + ' mt-6'}>
      <h2 className="font-bold text-lg text-[#06283d]">List one of your available batches</h2>
      <ListForm batches={myListable} onCreate={list} /></div>}
    <h2 className="font-bold text-xl mt-8 text-[#06283d]">My transactions</h2>
    {orders ? (!orders.items.length ? <p className="text-sm text-slate-500 mt-2">No orders recorded for your account/scope yet.</p> :
      <div className="overflow-x-auto"><table className="w-full text-sm bg-white rounded-xl shadow-sm border mt-2"><thead className="bg-slate-50 text-left"><tr>{['Order', 'Listing', 'Quantity', 'Unit price', 'Total', 'Status', 'When'].map(h => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
        <tbody>{orders.items.map((o: any) => <tr key={o.id} className="border-t"><td className="px-3 py-2">#{o.id}</td><td className="px-3 py-2">#{o.listing_id}</td><td className="px-3 py-2">{fmt(o.quantity)}</td><td className="px-3 py-2">${fmt(o.unit_price)}</td><td className="px-3 py-2 font-semibold">${fmt(o.total_usd)}</td><td className="px-3 py-2"><StatusBadge s={o.status} /></td><td className="px-3 py-2 text-slate-500">{new Date(o.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>) : <Loading />}
  </div>;
}
function ListForm({ batches, onCreate }: { batches: any[]; onCreate: (b: string, t: string, p: string, q: string) => void }) {
  const [b, setB] = useState(String(batches[0]?.id ?? '')); const [t, setT] = useState('Demo credits'); const [p, setP] = useState('12.50'); const [q, setQ] = useState('10');
  return <form className="grid md:grid-cols-5 gap-3 mt-3 items-end" onSubmit={e => { e.preventDefault(); onCreate(b, t, p, q); }}>
    <div><label className={label}>Batch</label><select className={inp} value={b} onChange={e => setB(e.target.value)}>{batches.map(x => <option key={x.id} value={x.id}>#{x.id} {x.serial} ({fmt(x.available, 0)} avail)</option>)}</select></div>
    <div><label className={label}>Title</label><input className={inp} value={t} onChange={e => setT(e.target.value)} /></div>
    <div><label className={label}>Price USD/credit</label><input className={inp} type="number" step="0.01" min="0.01" value={p} onChange={e => setP(e.target.value)} /></div>
    <div><label className={label}>Quantity</label><input className={inp} type="number" min="1" value={q} onChange={e => setQ(e.target.value)} /></div>
    <button className={btn}>Create listing</button>
  </form>;
}

/* ---------- map ---------- */
function Fit({ pts }: { pts: [number, number][] }) {
  const map = useMap();
  useEffect(() => { if (pts.length === 1) map.setView(pts[0], 12); else if (pts.length > 1) map.fitBounds(pts, { padding: [30, 30], maxZoom: 13 }); }, [pts, map]);
  return null;
}
function MapPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['projects'], queryFn: () => api('/api/v1/projects') });
  const [sel, setSel] = useState<Project | null>(null);
  const [eco, setEco] = useState(''); const [tilesOk, setTilesOk] = useState(true); const [coords, setCoords] = useState<[number, number] | null>(null);
  const tileRef = useRef<any>(null);
  useEffect(() => { // detect persistent tile errors → show fallback notice, but keep interaction alive
    const t = tileRef.current; if (!t) return;
    let errs = 0;
    const onError = () => { errs++; if (errs >= 4) setTilesOk(false); };
    t.on('tileerror', onError); return () => { try { t.off('tileerror', onError); } catch { /* noop */ } };
  }, [data]);
  if (isLoading) return <Loading what="Loading geospatial projects…" />;
  if (isError) return <div><h1 className="text-3xl font-bold">Geospatial Map</h1><ErrorBox error={error} onRetry={() => refetch()} /></div>;
  const all: Project[] = data?.items ?? data ?? [];
  const geo = all.filter(p => p.latitude != null && p.longitude != null);
  const shown = eco ? geo.filter(p => p.ecosystem === eco) : geo;
  const noGeo = all.length - geo.length;
  const pts = shown.map(p => [p.latitude!, p.longitude!] as [number, number]);
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/map', 'Map']]} />
    <div className="flex justify-between items-center flex-wrap gap-3"><div><h1 className="text-3xl font-bold text-[#06283d]">Interactive Geospatial Map</h1>
      <p className="text-sm text-slate-500 mt-1">Base tiles © OpenStreetMap contributors (standard raster; high-resolution satellite imagery is not integrated — boundaries shown are demonstration geometries, not remote-sensing products).</p></div>
      <select aria-label="Ecosystem layer filter" className={inp + ' w-48'} value={eco} onChange={e => setEco(e.target.value)}><option value="">All ecosystems</option>{['mangrove', 'tidal_marsh', 'seagrass'].map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select></div>
    {!tilesOk && <p className="mt-3 text-sm bg-amber-50 border border-amber-200 text-amber-800 rounded-lg p-3">Tile provider unreachable (offline or blocked). Markers, polygons, zoom and pan still work on the blank canvas — reconnect and press Retry to reload tiles. <button className={btnGhost + ' !py-1 ml-2'} onClick={() => { setTilesOk(true); setTimeout(() => window.location.reload(), 100); }}>Retry</button></p>}
    <div className="grid lg:grid-cols-3 gap-4 mt-4">
      <div className="lg:col-span-2 rounded-xl overflow-hidden border shadow-sm" style={{ height: 560 }}>
        <MapContainer center={[19.05, 72.85]} zoom={9} style={{ height: '100%', width: '100%' }} scrollWheelZoom whenReady={() => setTilesOk(t => t)}

          <TileLayer ref={tileRef} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={19} />
          <Fit pts={pts} />
          {shown.map(p => <Marker key={p.id} position={[p.latitude!, p.longitude!]} eventHandlers={{ click: () => setSel(p) }}>
            <Popup><b>{p.name}</b><br />{p.ecosystem.replace(/_/g, ' ')} · {p.area_ha} ha<br /><StatusBadge s={p.status} /></Popup></Marker>)}
          {shown.filter(p => p.boundary?.type === 'Polygon').map(p => <Polygon key={'b' + p.id} positions={p.boundary.coordinates[0].map((c: number[]) => [c[1], c[0]] as [number, number])}
            pathOptions={{ color: p.id === sel?.id ? '#0e7c7b' : '#2e7d4f', weight: p.id === sel?.id ? 3 : 2, fillOpacity: 0.12 }} eventHandlers={{ click: () => setSel(p) }} />)}
        </MapContainer>
      </div>
      <div className="space-y-3">
        <div className={card}>
          <h2 className="font-bold text-slate-700">{sel ? 'Selected project' : 'Project detail panel'}</h2>
          {sel ? <div className="mt-2">
            <h3 className="font-bold text-[#06283d]">{sel.name}</h3>
            <p className="text-sm text-slate-600 mt-1"><EcoName e={sel.ecosystem} /> · {fmt(sel.area_ha)} ha · <StatusBadge s={sel.status} /></p>
            <p className="text-sm text-slate-500 mt-1">{sel.region ? sel.region + ', ' : ''}{sel.country}</p>
            <p className="text-xs text-slate-400 mt-1 font-mono">WGS84: {sel.latitude}, {sel.longitude}{sel.boundary ? ' · has boundary polygon' : ' · point only'}</p>
            <Link className={btn + ' mt-3 w-full justify-center'} to={`/projects/${sel.id}`}>Open project</Link>
          </div> : <p className="text-sm text-slate-500 mt-2">Click a marker or polygon. Zoom with wheel/buttons, drag to pan. Cursor: <span className="font-mono text-xs">{coords ? coords.join(', ') : '—'}</span></p>}
        </div>
        <div className={card + ' max-h-72 overflow-auto'}>
          <h2 className="font-bold text-slate-700">Geolocated projects ({shown.length})</h2>
          {noGeo > 0 && <p className="text-xs text-slate-400 mt-1">{noGeo} project(s) without coordinates are omitted from the map (not lost — see Projects page).</p>}
          <ul className="mt-2 space-y-1">{shown.map(p => <li key={p.id}><button onClick={() => setSel(p)} className={`w-full text-left text-sm rounded px-2 py-1.5 hover:bg-teal-50 ${sel?.id === p.id ? 'bg-teal-50 font-semibold' : ''}`}>{p.name} <span className="text-xs text-slate-400">· {p.status}</span></button></li>)}</ul>
        </div>
      </div>
    </div>
  </div>;
}

/* ---------- admin / audit / profile ---------- */
function Admin() {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['users'], queryFn: () => api('/api/v1/users') });
  const { data: me } = useMe(); const qc2 = useQueryClient();
  const [msg, setMsg] = useState('');
  async function patch(uid: number, path: string, body: any) {
    setMsg(''); try { const r = await api(`/api/v1/users/${uid}/${path}`, { method: 'PATCH', body: JSON.stringify(body) }); setMsg(`✓ Updated user ${r.email} → ${r.role ? r.role : (r.is_active ? 'active' : 'inactive')} (their tokens were revoked for safety).`); qc2.invalidateQueries(); }
    catch (e: any) { setMsg('✗ ' + e.message); }
  }
  if (isLoading) return <Loading what="Loading users…" />;
  if (isError) return <ErrorBox error={error} onRetry={() => refetch()} />;
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/admin', 'Users']]} />
    <h1 className="text-3xl font-bold text-[#06283d]">User Administration</h1>
    <p className="text-sm text-slate-500 mt-1">Role changes revoke the target user's existing tokens server-side (token_version bump), so stale client claims cannot be reused.</p>
    {msg && <p className="bg-white border rounded-lg p-3 mt-3 text-sm">{msg}</p>}
    <div className="overflow-x-auto mt-4"><table className="w-full text-sm bg-white rounded-xl shadow-sm border">
      <thead className="bg-slate-50 text-left"><tr>{['ID', 'Name', 'Email', 'Role', 'Status', 'Change role', 'Activate/Deactivate'].map(h => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
      <tbody>{data.items.map((u: any) => <tr key={u.id} className="border-t">
        <td className="px-3 py-2">{u.id}</td><td className="px-3 py-2 font-medium">{u.full_name}</td><td className="px-3 py-2 text-slate-500">{u.email}</td>
        <td className="px-3 py-2 capitalize">{u.role}</td><td className="px-3 py-2">{u.is_active ? <StatusBadge s="accepted" /> : <StatusBadge s="rejected" />}</td>
        <td className="px-3 py-2"><select aria-label={`Role for ${u.email}`} className="border rounded p-1.5 text-sm" defaultValue={u.role} onChange={e => patch(u.id, 'role', { role: e.target.value })}>
          {['admin', 'verifier', 'developer', 'researcher', 'buyer', 'community'].map(r => <option key={r} value={r}>{r}</option>)}</select></td>
        <td className="px-3 py-2"><button disabled={u.id === me?.id} className={btnGhost + ' !py-1 text-xs'} onClick={() => patch(u.id, 'active', { is_active: !u.is_active })}>{u.is_active ? 'Deactivate' : 'Activate'}</button></td>
      </tr>)}</tbody></table></div>
  </div>;
}
function Audit() {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['audit'], queryFn: () => api('/api/v1/audit') });
  const [f, setF] = useState('');
  if (isLoading) return <Loading what="Loading audit trail…" />;
  if (isError) return <ErrorBox error={error} onRetry={() => refetch()} />;
  const rows = (data ?? []).filter((a: any) => !f || (a.action + a.resource_type + a.resource_id).toLowerCase().includes(f.toLowerCase()));
  return <div>
    <Breadcrumbs items={[['/app', 'Home'], ['/audit', 'Audit']]} />
    <h1 className="text-3xl font-bold text-[#06283d]">Audit Log</h1>
    <p className="text-sm text-slate-500 mt-1">Append-only trail of significant actions (actor, action, resource, timestamp, safe metadata). Visible to administrators and verification officers; ordinary users cannot read, edit or delete it.</p>
    <input aria-label="Filter audit" className={inp + ' my-3 max-w-md'} placeholder="Filter by action or resource…" value={f} onChange={e => setF(e.target.value)} />
    <div className="bg-white rounded-xl shadow-sm border overflow-hidden">
      <table className="w-full text-sm"><thead className="bg-slate-50 text-left"><tr>{['When', 'Actor', 'Action', 'Resource', 'Metadata'].map(h => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
        <tbody>{rows.map((a: any) => <tr key={a.id} className="border-t hover:bg-slate-50">
          <td className="px-3 py-2 whitespace-nowrap text-slate-500">{new Date(a.created_at).toLocaleString()}</td>
          <td className="px-3 py-2">#{a.actor_id ?? 'system'}</td><td className="px-3 py-2 font-mono text-xs">{a.action}</td>
          <td className="px-3 py-2">{a.resource_type}{a.resource_id ? ' #' + a.resource_id : ''}</td>
          <td className="px-3 py-2 text-xs text-slate-500 font-mono">{Object.keys(a.meta || {}).length ? JSON.stringify(a.meta) : '—'}</td></tr>)}</tbody></table>
      {!rows.length && <p className="p-6 text-center text-slate-500">No audit events match.</p>}
    </div>
  </div>;
}
function Profile() {
  const { data: me } = useMe(); const nav = useNavigate();
  return <div className="max-w-xl">
    <Breadcrumbs items={[['/app', 'Home'], ['/profile', 'Profile']]} />
    <div className={card}>
      <h1 className="text-2xl font-bold text-[#06283d]">Profile & Settings</h1>
      <dl className="mt-4 space-y-2 text-sm">
        <DdRow k="Name" v={me?.full_name} />
        <DdRow k="Email" v={me?.email} />
        <DdRow k="Role" v={me?.role} />
        <DdRow k="Account" v={me?.is_active ? 'active' : 'disabled'} />
      </dl>
      <p className="text-xs text-slate-500 mt-3">Sessions use short-lived bearer tokens with server-side revocation (token version). Logging out invalidates all previously issued tokens for this account. Password change and profile editing are planned next steps — see README limitations.</p>
      <button className={btnDanger + ' mt-4'} onClick={async () => { try { await api('/api/v1/auth/logout', { method: 'POST' }); } catch { /* ignore */ } setToken(null); qc.clear(); nav('/login'); }}>Log out everywhere</button>
    </div>
  </div>;
}

/* ---------- root ---------- */
export default function App() {
  return <QueryClientProvider client={qc}><BrowserRouter>
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Auth mode="login" />} />
      <Route path="/register" element={<Auth mode="register" />} />
      <Route path="/app" element={<Protected><Dashboard /></Protected>} />
      <Route path="/projects" element={<Protected><Projects /></Protected>} />
      <Route path="/projects/new" element={<Protected roles={['developer', 'admin']}><ProjectForm /></Protected>} />
      <Route path="/projects/:id" element={<Protected><ProjectDetail /></Protected>} />
      <Route path="/projects/:id/edit" element={<Protected roles={['developer', 'admin']}><ProjectEdit /></Protected>} />
      <Route path="/verification" element={<Protected roles={['verifier', 'admin']}><Verification /></Protected>} />
      <Route path="/registry" element={<Protected><Registry /></Protected>} />
      <Route path="/marketplace" element={<Protected><Marketplace /></Protected>} />
      <Route path="/map" element={<Protected><MapPage /></Protected>} />
      <Route path="/admin" element={<Protected roles={['admin']}><Admin /></Protected>} />
      <Route path="/audit" element={<Protected roles={['admin', 'verifier']}><Audit /></Protected>} />
      <Route path="/profile" element={<Protected><Profile /></Protected>} />
      <Route path="/403" element={<Protected><div className="text-center max-w-md mx-auto mt-10"><h1 className="text-3xl font-bold">403 Forbidden</h1><p className="text-slate-600 mt-2">Your role does not permit access to this resource.</p><Link className={btn + ' mt-4'} to="/app">Go to dashboard</Link></div></Protected>} />
      <Route path="*" element={<div className="min-h-screen flex flex-col items-center justify-center bg-[#06283d] text-white p-6 text-center"><h1 className="text-5xl font-extrabold">404</h1><p className="mt-2 text-slate-300">That page drifted out to sea.</p><Link to="/" className={btn + ' mt-6'}>Return to shore</Link></div>} />
    </Routes>
  </BrowserRouter></QueryClientProvider>;
}
function ProjectEdit() { const { id } = useParams(); return <ProjectForm editId={Number(id)} />; }
