export interface IncidentSummary {
  incident_id: string;
  incident_type: string;
  severity: string;
  started_at: string;
  duration_minutes: number;
  affected_services: string[];
  expected_symptoms: string[];
}

export interface InvestigationStep {
  step_number: number;
  state: string;
  summary: string;
  details: Record<string, any>;
  timestamp: string;
}

export interface Investigation {
  investigation_id: string;
  incident_id: string;
  final_state: string;
  confidence: number;
  rca_narrative?: string | null;
  leading_hypothesis_id?: string | null;
  started_at: string;
  completed_at?: string | null;
  steps: InvestigationStep[];
}

export interface EvidenceRefData {
  evidence_id: string;
  evidence_type: string;
  relevance_note: string;
}

export interface VerdictData {
  question: string;
  verdict: 'supports' | 'contradicts' | 'inconclusive';
  reasoning: string;
  evidence_ids_cited: string[];
  verdict_source: 'llm_generated' | 'deterministic_trend_check';
}

export interface HypothesisData {
  hypothesis_id?: string;
  title: string;
  description: string;
  category?: string;
  status: string;
  initial_score: number;
  final_score: number;
  confidence: number;
  score_before?: number | null;
  score_after?: number | null;
  verdicts: VerdictData[];
  supporting_evidence?: EvidenceRefData[];
  contradictions_count: number;
  supporting_count: number;
  investigated?: boolean;
}

export interface EvidenceItem {
  evidence_id: string;
  evidence_type: string;
  service: string;
  timestamp: string;
  severity?: string;
  message?: string;
  metric_name?: string;
  value?: number;
  unit?: string;
  operation?: string;
  duration_ms?: number;
  status?: string;
  version?: string;
  description?: string;
  database_name?: string;
  metadata?: Record<string, any>;
  labels?: Record<string, any>;
  attributes?: Record<string, any>;
}

export interface TimelineCluster {
  cluster_id: string;
  start_time: string;
  end_time: string;
  event_count: number;
  involved_sources: string[];
  summary: string;
}

export interface TimelineData {
  incident_id: string;
  start_time: string;
  end_time?: string | null;
  total_events: number;
  clusters: TimelineCluster[];
}
