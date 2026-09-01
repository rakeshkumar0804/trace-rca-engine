import { IncidentSummary, Investigation, EvidenceItem, TimelineData, HypothesisData } from '../types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export function extractErrorMessage(err: any, fallbackMsg: string = 'An unexpected error occurred.'): string {
  if (!err) return fallbackMsg;
  if (typeof err === 'string') return err;
  if (typeof err.message === 'string' && err.message !== '[object Object]') return err.message;
  if (typeof err.detail === 'string') return err.detail;
  if (Array.isArray(err.detail)) {
    const msgs = err.detail
      .map((item: any) => (typeof item === 'string' ? item : item?.msg || item?.message || 'Invalid field input'))
      .filter(Boolean);
    if (msgs.length > 0) return msgs.join('. ');
  }
  if (err.error) {
    if (typeof err.error === 'string') return err.error;
    if (typeof err.error.message === 'string') return err.error.message;
  }
  if (err.statusText && typeof err.statusText === 'string') return err.statusText;
  return fallbackMsg;
}

export function formatLocalTime(isoString: string | Date | undefined | null): string {
  if (!isoString) return '--:--:--';
  const str = String(isoString);
  // If string has date format without timezone offset (no Z or +/-), append Z so browser knows it is UTC
  const utcFormatted = (typeof isoString === 'string' && !str.includes('Z') && !str.match(/[+-]\d{2}:\d{2}$/))
    ? str.replace(' ', 'T') + 'Z'
    : isoString;
  try {
    return new Date(utcFormatted).toLocaleTimeString();
  } catch {
    return String(isoString);
  }
}

async function handleResponse<T>(res: Response, fallbackMsg: string): Promise<T> {
  if (!res.ok) {
    let errorText = '';
    try {
      const errJson = await res.json();
      errorText = extractErrorMessage(errJson, res.statusText || fallbackMsg);
    } catch {
      errorText = res.statusText || fallbackMsg;
    }
    throw new Error(errorText || fallbackMsg);
  }
  return res.json();
}

export async function fetchIncidents(): Promise<IncidentSummary[]> {
  const res = await fetch(`${API_BASE}/api/incidents`);
  return handleResponse<IncidentSummary[]>(res, 'Failed to fetch incidents');
}

export async function generateIncident(incidentType: string, seed?: number): Promise<IncidentSummary> {
  const res = await fetch(`${API_BASE}/api/incidents/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      incident_type: incidentType,
      seed: seed || undefined,
    }),
  });
  return handleResponse<IncidentSummary>(res, 'Failed to generate incident');
}

export async function startInvestigation(incidentId: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/api/investigations/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ incident_id: incidentId }),
  });
  return handleResponse<Investigation>(res, 'Failed to start investigation');
}

export async function startDemoInvestigation(): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/api/investigations/demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  return handleResponse<Investigation>(res, 'Failed to start demo investigation');
}

export async function fetchInvestigation(investigationId: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/api/investigations/${investigationId}`);
  return handleResponse<Investigation>(res, 'Failed to fetch investigation');
}

export async function fetchInvestigationTimeline(investigationId: string): Promise<TimelineData> {
  const res = await fetch(`${API_BASE}/api/investigations/${investigationId}/timeline`);
  return handleResponse<TimelineData>(res, 'Failed to fetch timeline');
}

export async function fetchInvestigationHypotheses(investigationId: string): Promise<HypothesisData[]> {
  const res = await fetch(`${API_BASE}/api/investigations/${investigationId}/hypotheses`);
  return handleResponse<HypothesisData[]>(res, 'Failed to fetch hypotheses');
}

export async function fetchEvidenceDetail(evidenceId: string): Promise<EvidenceItem> {
  const res = await fetch(`${API_BASE}/api/evidence/${evidenceId}`);
  return handleResponse<EvidenceItem>(res, `Failed to fetch evidence ${evidenceId}`);
}
