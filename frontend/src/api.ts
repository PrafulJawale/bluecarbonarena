// Centralized typed API client for BLUECARBON ARENA.
const BASE = import.meta.env.VITE_API_URL || '';   // '' => same-origin (Vite dev proxy /api -> :8000)
const KEY = 'bca_token';
export const token = () => localStorage.getItem(KEY);
export const setToken = (t: string | null) => { if (t === null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, t); };

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as any) };
  // Let the browser set multipart boundaries when a FormData body is used.
  if (!(opts.body instanceof FormData)) headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  const tok = token();
  if (tok) headers['Authorization'] = `Bearer ${tok}`;
  const r = await fetch(BASE + path, { ...opts, headers });
  if (!r.ok) {
    let m = r.statusText;
    try { const j = await r.json(); m = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? m); } catch { /* non-JSON error */ }
    throw new Error(`${r.status}: ${m}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json();
}

export type Project = { id: number; name: string; description: string; status: string; ecosystem: string; area_ha: number; country: string; region: string; latitude?: number | null; longitude?: number | null; boundary?: any; owner_id: number; reporting_years: number; start_date?: string; methodology?: string; data_quality?: string; evidence_count?: number; calculation_count?: number };
export type User = { id: number; email: string; full_name: string; role: string; is_active: boolean };
export type Paginated<T> = { items: T[]; total: number };
