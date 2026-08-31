import { IncidentSummary, Investigation, EvidenceItem, TimelineData, HypothesisData } from '../types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function handleResponse<T>(res: Response, fallbackMsg: string): Promise<T> {
  if (!res.ok) {
    let detail = '';
    try {
      const errJson = await res.json();
      detail = errJson.detail || '';
    } catch {
      detail = res.statusText;
    }
    throw new Error(detail || fallbackMsg);
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
