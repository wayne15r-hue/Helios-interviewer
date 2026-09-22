import type { Assessment } from './types';

/** Keep reviews comparable: a re-analysis replaces a session's prior score. */
export function latestAssessments(assessments: Assessment[]): Assessment[] {
  const sessions = new Map<string, Assessment>();
  for (const assessment of [...assessments].filter(item => !item.stale).sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    if (!sessions.has(assessment.session_id)) sessions.set(assessment.session_id, assessment);
  }
  return [...sessions.values()];
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !(options.body instanceof Blob) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'The request could not be completed.');
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
export const remove = (path: string) => api<void>(path, { method: 'DELETE' });
export function time(seconds = 0): string {
  const value = Math.max(0, Math.round(seconds));
  return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`;
}
export function date(value?: string, detailed = false): string {
  if (!value) return 'Not scheduled';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Not scheduled';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', ...(detailed ? { hour: 'numeric', minute: '2-digit' } : {}) }).format(parsed);
}
export function label(value: string): string { return value.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase()); }
