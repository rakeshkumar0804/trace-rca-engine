'use client';

import React from 'react';
import { Investigation, HypothesisData, EvidenceRefData, VerdictData } from '../types';
import { 
  CheckCircle2, AlertTriangle, ShieldAlert, Brain, FileText, ArrowLeft, 
  HelpCircle, Sparkles, ExternalLink, ChevronRight, Activity, Zap, Layers,
  Database, GitCommit, Bell, BarChart3, Terminal
} from 'lucide-react';

interface Screen3FinalRCAProps {
  investigation: Investigation;
  hypotheses: HypothesisData[];
  onBackToLauncher: () => void;
  onOpenEvidence: (evidenceId: string) => void;
}

export function Screen3FinalRCA({
  investigation,
  hypotheses,
  onBackToLauncher,
  onOpenEvidence,
}: Screen3FinalRCAProps) {
  const isInconclusive = investigation.final_state === 'inconclusive';
  const confidence = investigation.confidence ?? 0;

  const getConfidenceLevel = (conf: number) => {
    if (conf >= 70) return { label: 'HIGH CONFIDENCE', color: 'text-emerald-400 bg-emerald-950/80 border-emerald-800' };
    if (conf >= 50) return { label: 'MEDIUM CONFIDENCE', color: 'text-amber-400 bg-amber-950/80 border-amber-800' };
    return { label: 'LOW CONFIDENCE', color: 'text-rose-400 bg-rose-950/80 border-rose-800' };
  };

  const confLevel = getConfidenceLevel(confidence);

  // Extract leading hypothesis
  const leadingHyp = hypotheses.find((h) => h.status === 'confirmed') || hypotheses[0];

  // Partition other hypotheses into investigated vs uninvestigated
  const nonConfirmedHypotheses = hypotheses.filter((h) => h !== leadingHyp);
  const investigatedDistractors = nonConfirmedHypotheses.filter(
    (h) => h.investigated || (h.verdicts && h.verdicts.length > 0)
  );
  const uninvestigatedDistractors = nonConfirmedHypotheses.filter(
    (h) => !h.investigated && (!h.verdicts || h.verdicts.length === 0)
  );

  const getSourceIcon = (sourceType: string) => {
    const s = (sourceType || '').toLowerCase();
    if (s.includes('deploy') || s.includes('commit') || s.includes('git')) {
      return <GitCommit className="w-3.5 h-3.5 text-blue-400" />;
    }
    if (s.includes('db') || s.includes('database')) {
      return <Database className="w-3.5 h-3.5 text-emerald-400" />;
    }
    if (s.includes('metric')) {
      return <BarChart3 className="w-3.5 h-3.5 text-amber-400" />;
    }
    if (s.includes('alert')) {
      return <Bell className="w-3.5 h-3.5 text-rose-400" />;
    }
    return <Terminal className="w-3.5 h-3.5 text-cyan-400" />;
  };

  const getSourceBadgeColor = (sourceType: string) => {
    const s = (sourceType || '').toLowerCase();
    if (s.includes('deploy') || s.includes('commit')) return 'bg-blue-950/90 text-blue-300 border-blue-800';
    if (s.includes('db') || s.includes('database')) return 'bg-emerald-950/90 text-emerald-300 border-emerald-800';
    if (s.includes('metric')) return 'bg-amber-950/90 text-amber-300 border-amber-800';
    if (s.includes('alert')) return 'bg-rose-950/90 text-rose-300 border-rose-800';
    return 'bg-cyan-950/90 text-cyan-300 border-cyan-800';
  };

  // Helper to parse narrative and make evidence citations clickable
  const renderInteractiveNarrative = (text: string) => {
    const uuidRegex = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/gi;
    const parts = text.split(uuidRegex);

    return (
      <div className="text-slate-200 text-sm font-mono whitespace-pre-wrap leading-relaxed">
        {parts.map((part, i) => {
          if (part.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i)) {
            return (
              <button
                key={i}
                onClick={() => onOpenEvidence(part)}
                className="inline-flex items-center gap-1 px-2 py-0.5 mx-1 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 font-mono text-xs transition-colors cursor-pointer"
                title="Click to inspect evidence record"
              >
                <span>{part.slice(0, 8)}...</span>
                <ExternalLink className="w-3 h-3" />
              </button>
            );
          }
          return <span key={i}>{part}</span>;
        })}
      </div>
    );
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8 animate-in fade-in duration-300">
      {/* Back button header */}
      <div className="flex items-center justify-between">
        <button
          onClick={onBackToLauncher}
          className="px-4 py-2 text-xs font-mono bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-xl transition-colors flex items-center gap-2 cursor-pointer shadow-md"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Return to Launcher</span>
        </button>
        <span className="text-xs font-mono text-slate-500">
          TRACE Investigation: {investigation.investigation_id}
        </span>
      </div>

      {isInconclusive ? (
        /* Inconclusive Honest Path */
        <div className="p-8 rounded-2xl bg-gradient-to-b from-rose-950/30 to-slate-900 border border-rose-800/80 shadow-2xl space-y-6">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-xl bg-rose-950 border border-rose-800 text-rose-400">
              <ShieldAlert className="w-8 h-8" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-2xl font-bold text-rose-200">Investigation Inconclusive</h1>
                <span className="px-2.5 py-0.5 text-xs font-mono font-bold rounded bg-rose-950 text-rose-300 border border-rose-800">
                  CONFIDENCE &lt; 70%
                </span>
              </div>
              <p className="text-xs font-mono text-slate-400 mt-1">
                No single root-cause hypothesis cleared the required deterministic evidence validation threshold.
              </p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-sm font-mono text-slate-300 leading-relaxed">
            {investigation.rca_narrative || 'The investigation evaluated candidate hypotheses against retrieved telemetry, but candidates were either contradicted during self-critique or lacked sufficient causal support.'}
          </div>

          <div className="space-y-4">
            <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-300">
              Evaluated Candidates & Falsification Trace:
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {hypotheses.map((h) => (
                <div key={h.hypothesis_id || h.title} className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-200">{h.title}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-rose-950 text-rose-400 border border-rose-800">
                      {h.status.toUpperCase()} (Score: {h.final_score})
                    </span>
                  </div>
                  {h.verdicts && h.verdicts.length > 0 ? (
                    <div className="space-y-2 pt-2 border-t border-slate-900">
                      {h.verdicts.map((v, vi) => (
                        <div key={vi} className="p-2 rounded bg-slate-900 border border-slate-800 space-y-1">
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-slate-300">Q: {v.question}</span>
                            <span className="text-rose-400 uppercase font-bold">{v.verdict}</span>
                          </div>
                          <p className="text-[11px] text-slate-400">{v.reasoning}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-500 italic">
                      Eliminated on baseline scoring without deep retrieval (Score: {h.final_score}).
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        /* Confirmed Root Cause Path */
        <div className="space-y-8">
          {/* Executive RCA Banner */}
          <div className="p-8 rounded-2xl bg-gradient-to-r from-emerald-950/30 via-slate-900 to-cyan-950/30 border border-emerald-800/80 shadow-2xl space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="p-3 rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400 shadow-lg">
                  <CheckCircle2 className="w-8 h-8" />
                </div>
                <div>
                  <span className="text-xs font-mono font-bold uppercase tracking-wider text-emerald-400">Root Cause Identified</span>
                  <h1 className="text-2xl font-bold text-slate-100 mt-0.5">
                    {leadingHyp?.title || 'Confirmed Incident Root Cause'}
                  </h1>
                </div>
              </div>

              <div className={`px-4 py-2 rounded-xl border text-xs font-mono font-bold flex items-center gap-2 ${confLevel.color} shadow-lg`}>
                <Sparkles className="w-4 h-4" />
                <span>{confLevel.label} ({confidence.toFixed(1)}%)</span>
              </div>
            </div>

            {/* RCA Narrative */}
            <div className="p-6 rounded-xl bg-slate-950/90 border border-slate-800 space-y-3 shadow-inner">
              <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
                <FileText className="w-4 h-4 text-cyan-400" />
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-300">
                  Autonomous RCA Executive Report
                </h3>
              </div>
              {renderInteractiveNarrative(investigation.rca_narrative || 'RCA generation completed.')}
            </div>
          </div>

          {/* Falsification & Validation Breakdown Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Supporting Evidence Card */}
            <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-5 shadow-xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                    Supporting Causal Evidence
                  </h3>
                </div>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                  {leadingHyp?.supporting_evidence?.length || 0} Citations
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                Verified telemetry records and change events directly substantiating this failure mode (click to inspect underlying DB record):
              </p>

              {/* Real Supporting Evidence Cards */}
              <div className="space-y-3">
                {leadingHyp?.supporting_evidence && leadingHyp.supporting_evidence.length > 0 ? (
                  leadingHyp.supporting_evidence.map((ref: EvidenceRefData, i: number) => (
                    <div 
                      key={i} 
                      onClick={() => onOpenEvidence(ref.evidence_id)}
                      className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-cyan-600/80 transition-all cursor-pointer group shadow-sm hover:shadow-cyan-950/20"
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border flex items-center gap-1.5 ${getSourceBadgeColor(ref.evidence_type)}`}>
                            {getSourceIcon(ref.evidence_type)}
                            <span>{ref.evidence_type}</span>
                          </span>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenEvidence(ref.evidence_id);
                          }}
                          className="text-[11px] font-mono text-cyan-400 group-hover:text-cyan-300 flex items-center gap-1 bg-cyan-950/40 hover:bg-cyan-950 px-2 py-0.5 rounded border border-cyan-900/60"
                        >
                          <span>{ref.evidence_id.slice(0, 8)}...</span>
                          <ExternalLink className="w-3 h-3" />
                        </button>
                      </div>
                      <p className="text-xs font-mono text-slate-300 leading-relaxed group-hover:text-slate-100">
                        {ref.relevance_note}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-slate-400">
                    No discrete evidence references attached.
                  </div>
                )}
              </div>

              {/* Confirmed Hypothesis's Falsification Test Trace */}
              {leadingHyp?.verdicts && leadingHyp.verdicts.length > 0 && (
                <div className="pt-4 border-t border-slate-800 space-y-3">
                  <h4 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                    <Brain className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Falsification Tests Passed:</span>
                  </h4>
                  <div className="space-y-2">
                    {leadingHyp.verdicts.map((v: VerdictData, vi: number) => (
                      <div key={vi} className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono space-y-1.5">
                        <div className="flex items-center justify-between text-emerald-400 font-medium">
                          <span>✓ {v.question}</span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-300 font-bold uppercase border border-emerald-800">
                            {v.verdict.toUpperCase()}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400 leading-relaxed">{v.reasoning}</p>
                        {v.evidence_ids_cited && v.evidence_ids_cited.length > 0 && (
                          <div className="flex items-center gap-1.5 pt-1">
                            <span className="text-[10px] text-slate-500">Cited Evidence:</span>
                            {v.evidence_ids_cited.map((eid, eidx) => (
                              <button
                                key={eidx}
                                onClick={() => onOpenEvidence(eid)}
                                className="text-[10px] font-mono text-cyan-400 hover:text-cyan-300 underline inline-flex items-center gap-0.5"
                              >
                                <span>{eid.slice(0, 8)}</span>
                                <ExternalLink className="w-2.5 h-2.5" />
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Contradicting & Ruled-Out Distractors Card */}
            <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-5 shadow-xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-5 h-5 text-purple-400" />
                  <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                    Ruled-Out Distractors & Falsification
                  </h3>
                </div>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800 font-bold">
                  {nonConfirmedHypotheses.length} Distractors
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                Competing failure modes actively evaluated and eliminated via self-critique, timeline checks, and deterministic trend differentials:
              </p>

              {/* Group 1: Investigated & Falsified Distractors */}
              {investigatedDistractors.length > 0 && (
                <div className="space-y-3">
                  <div className="text-[11px] font-mono font-bold uppercase tracking-wider text-rose-400 flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5" />
                    <span>Investigated & Falsified Candidates ({investigatedDistractors.length}):</span>
                  </div>
                  {investigatedDistractors.map((h, i) => (
                    <div key={i} className="p-3.5 rounded-xl bg-slate-950 border border-rose-900/40 text-xs font-mono space-y-2.5">
                      <div className="flex items-center justify-between text-slate-300 font-medium">
                        <span className="font-bold text-slate-200">{h.title}</span>
                        <div className="flex items-center gap-2">
                          {h.score_before !== null && h.score_after !== null && (
                            <span className="text-[11px] text-slate-400 font-mono">
                              {h.score_before} → {h.score_after}
                            </span>
                          )}
                          <span className="text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-400 font-bold uppercase border border-rose-800">
                            {h.status.toUpperCase()}
                          </span>
                        </div>
                      </div>
                      
                      {h.verdicts && h.verdicts.length > 0 && (
                        <div className="space-y-2 pt-2 border-t border-slate-900">
                          {h.verdicts.map((v: VerdictData, vi: number) => (
                            <div key={vi} className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
                              <div className="flex items-center justify-between text-[11px]">
                                <span className="text-slate-300 font-medium">Q: {v.question}</span>
                                <span className="text-[10px] font-bold uppercase px-1.5 py-0.2 rounded bg-rose-950 text-rose-400 border border-rose-800">
                                  {v.verdict}
                                </span>
                              </div>
                              <p className="text-[11px] text-rose-300/90 leading-relaxed">
                                {v.verdict_source === 'deterministic_trend_check' ? (
                                  <span className="text-amber-400 font-bold mr-1">⚡ [Trend-Check Falsification]:</span>
                                ) : (
                                  <span className="text-purple-400 font-bold mr-1">🧠 [Self-Critique]:</span>
                                )}
                                {v.reasoning}
                              </p>
                              {v.evidence_ids_cited && v.evidence_ids_cited.length > 0 && (
                                <div className="flex items-center gap-1.5 pt-1">
                                  <span className="text-[10px] text-slate-500">Cited Evidence:</span>
                                  {v.evidence_ids_cited.map((eid, eidx) => (
                                    <button
                                      key={eidx}
                                      onClick={() => onOpenEvidence(eid)}
                                      className="text-[10px] font-mono text-cyan-400 hover:text-cyan-300 underline inline-flex items-center gap-0.5"
                                    >
                                      <span>{eid.slice(0, 8)}</span>
                                      <ExternalLink className="w-2.5 h-2.5" />
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Group 2: Uninvestigated Candidate Hypotheses */}
              {uninvestigatedDistractors.length > 0 && (
                <div className="space-y-3 pt-2">
                  <div className="text-[11px] font-mono font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5" />
                    <span>Uninvestigated Candidates (Bounded Execution):</span>
                  </div>
                  <p className="text-[11px] text-slate-500 font-mono">
                    Ranked below the top-3 cutoff during baseline deterministic scoring; eliminated without deep telemetry retrieval:
                  </p>
                  <div className="space-y-2">
                    {uninvestigatedDistractors.map((h, i) => (
                      <div key={i} className="p-2.5 rounded-lg bg-slate-950/70 border border-slate-800/80 text-xs font-mono flex items-center justify-between">
                        <div className="space-y-0.5">
                          <span className="text-slate-300 font-medium">{h.title}</span>
                          <p className="text-[10px] text-slate-500 line-clamp-1">{h.description}</p>
                        </div>
                        <span className="text-[11px] font-mono text-slate-400 px-2 py-0.5 rounded bg-slate-900 border border-slate-800 shrink-0 ml-3">
                          Baseline: {h.initial_score ?? h.final_score}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
