'use client';

import React, { useState } from 'react';
import { Investigation, HypothesisData, EvidenceItem, TimelineData } from '../types';
import { 
  ArrowLeft, CheckCircle2, XCircle, AlertTriangle, Activity, 
  Terminal, ShieldCheck, Sparkles, Brain, Cpu, Database, ChevronRight, Layers, HelpCircle
} from 'lucide-react';

interface Screen2InvestigationProps {
  investigation: Investigation;
  hypotheses: HypothesisData[];
  timeline: TimelineData | null;
  onBackToLauncher: () => void;
  onOpenEvidence: (evidenceId: string) => void;
}

export function Screen2Investigation({
  investigation,
  hypotheses,
  timeline,
  onBackToLauncher,
  onOpenEvidence,
}: Screen2InvestigationProps) {
  const isRunning = investigation.final_state === 'running';

  const getStateBadge = (state: string) => {
    switch (state) {
      case 'incident_detected': return { label: 'DETECTION', color: 'bg-blue-950 text-blue-300 border-blue-800' };
      case 'incident_scoped': return { label: 'SCOPING', color: 'bg-indigo-950 text-indigo-300 border-indigo-800' };
      case 'timeline_built': return { label: 'TIMELINE', color: 'bg-cyan-950 text-cyan-300 border-cyan-800' };
      case 'affected_components_identified': return { label: 'TOPOLOGY', color: 'bg-teal-950 text-teal-300 border-teal-800' };
      case 'initial_evidence_retrieved': return { label: 'RETRIEVAL', color: 'bg-amber-950 text-amber-300 border-amber-800' };
      case 'hypotheses_generated': return { label: 'GENERATION', color: 'bg-purple-950 text-purple-300 border-purple-800' };
      case 'hypotheses_ranked': return { label: 'RANKING', color: 'bg-indigo-950 text-indigo-300 border-indigo-800' };
      case 'hypothesis_investigated': return { label: 'SELF-CRITIQUE', color: 'bg-pink-950 text-pink-300 border-pink-800' };
      case 'best_explanation_selected': return { label: 'SELECTION', color: 'bg-emerald-950 text-emerald-300 border-emerald-800' };
      case 'rca_generated': return { label: 'RCA COMPLETE', color: 'bg-emerald-950 text-emerald-300 border-emerald-800' };
      case 'inconclusive': return { label: 'INCONCLUSIVE', color: 'bg-rose-950 text-rose-300 border-rose-800' };
      default: return { label: state.toUpperCase(), color: 'bg-slate-900 text-slate-300 border-slate-800' };
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
        <div className="flex items-center gap-4">
          <button
            onClick={onBackToLauncher}
            className="p-2 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-xl transition-colors border border-slate-800"
            title="Back to Incident Launcher"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-slate-100">Active Investigation</h1>
              <span className={`px-2.5 py-0.5 text-xs font-mono font-bold rounded-full border flex items-center gap-1.5 ${
                isRunning ? 'bg-cyan-950/80 text-cyan-300 border-cyan-700 animate-pulse' :
                investigation.final_state === 'rca_generated' ? 'bg-emerald-950 text-emerald-300 border-emerald-800' :
                'bg-rose-950 text-rose-300 border-rose-800'
              }`}>
                {isRunning && <Activity className="w-3.5 h-3.5 animate-spin" />}
                <span>{investigation.final_state.toUpperCase()}</span>
              </span>
            </div>
            <p className="text-xs font-mono text-slate-400 mt-0.5">
              ID: {investigation.investigation_id} | Started: {new Date(investigation.started_at).toLocaleTimeString()}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="px-3.5 py-1.5 rounded-xl bg-slate-950 border border-slate-800 flex items-center gap-2">
            <span className="text-xs font-mono text-slate-400">Confidence:</span>
            <span className={`text-sm font-mono font-bold ${
              investigation.confidence >= 70 ? 'text-emerald-400' :
              investigation.confidence >= 50 ? 'text-amber-400' : 'text-rose-400'
            }`}>
              {investigation.confidence.toFixed(1)}%
            </span>
          </div>
          <div className="px-3.5 py-1.5 rounded-xl bg-slate-950 border border-slate-800 flex items-center gap-2">
            <span className="text-xs font-mono text-slate-400">Steps Executed:</span>
            <span className="text-sm font-mono font-bold text-cyan-400">{investigation.steps.length}</span>
          </div>
        </div>
      </div>

      {/* Main 2-Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Live Activity Feed (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-200">Live Investigation Steps</h2>
            </div>
            {isRunning && (
              <span className="text-xs font-mono text-cyan-400 flex items-center gap-1.5 animate-pulse">
                <span className="w-2 h-2 rounded-full bg-cyan-400" /> Live Agent Reasoning
              </span>
            )}
          </div>

          <div className="space-y-3">
            {investigation.steps.map((step, idx) => {
              const badge = getStateBadge(step.state);
              const isCritiqueStep = step.state === 'hypothesis_investigated';
              const verdicts = step.details.verdicts || [];

              return (
                <div
                  key={idx}
                  className="p-4 rounded-xl bg-slate-900 border border-slate-800/90 shadow-md space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-200"
                >
                  {/* Step Header */}
                  <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 pb-2.5">
                    <div className="flex items-center gap-2.5">
                      <span className="w-5 h-5 rounded-full bg-slate-800 text-[11px] font-mono font-bold text-slate-300 flex items-center justify-center border border-slate-700">
                        {step.step_number}
                      </span>
                      <span className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded uppercase border ${badge.color}`}>
                        {badge.label}
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-slate-500">
                      {new Date(step.timestamp).toLocaleTimeString()}
                    </span>
                  </div>

                  {/* Step Summary */}
                  <p className="text-xs font-mono text-slate-200 leading-relaxed font-medium">
                    {step.summary}
                  </p>

                  {/* Step Details & Falsification Checks */}
                  {isCritiqueStep && (
                    <div className="p-3 rounded-lg bg-slate-950/80 border border-slate-800 space-y-2.5">
                      <div className="flex items-center justify-between text-xs font-mono">
                        <span className="text-slate-400">Score Trajectory:</span>
                        <div className="flex items-center gap-2">
                          <span className="text-slate-400">{step.details.score_before}</span>
                          <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
                          <span className={`font-bold ${
                            (step.details.score_after ?? 0) >= (step.details.score_before ?? 0) ? 'text-emerald-400' : 'text-rose-400'
                          }`}>
                            {step.details.score_after}
                          </span>
                          <span className={`text-[10px] px-1.5 py-0.2 rounded font-bold ${
                            step.details.status_after === 'confirmed' ? 'bg-emerald-950 text-emerald-300' : 'bg-rose-950 text-rose-300'
                          }`}>
                            {step.details.status_after?.toUpperCase()}
                          </span>
                        </div>
                      </div>

                      {/* Question Verdicts */}
                      {verdicts.length > 0 && (
                        <div className="space-y-1.5 pt-1 border-t border-slate-800/80">
                          <span className="text-[11px] font-mono text-slate-500 block">FALSIFICATION QUESTIONS:</span>
                          {verdicts.map((v: any, vIdx: number) => {
                            const isDeterministic = v.verdict_source === 'deterministic_trend_check';
                            return (
                              <div key={vIdx} className="p-2 rounded bg-slate-900 border border-slate-800 text-xs font-mono space-y-1">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="text-slate-300 font-medium truncate max-w-sm">{v.question}</span>
                                  <div className="flex items-center gap-1.5 shrink-0">
                                    <span className={`px-1.5 py-0.2 text-[10px] rounded font-bold ${
                                      isDeterministic ? 'bg-purple-950 text-purple-300 border border-purple-800' : 'bg-cyan-950 text-cyan-300 border border-cyan-800'
                                    }`}>
                                      {isDeterministic ? '⚡ TREND-CHECK' : '🤖 LLM'}
                                    </span>
                                    <span className={`px-1.5 py-0.2 text-[10px] rounded font-bold ${
                                      v.verdict === 'supports' ? 'text-emerald-400 bg-emerald-950/60' : 'text-rose-400 bg-rose-950/60'
                                    }`}>
                                      {v.verdict?.toUpperCase()}
                                    </span>
                                  </div>
                                </div>
                                <p className="text-[11px] text-slate-400 leading-snug">{v.reasoning}</p>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Retrieved Evidence Citations Links */}
                  {step.details.retrieved_evidence_ids && step.details.retrieved_evidence_ids.length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap pt-1">
                      <span className="text-[11px] font-mono text-slate-500">Cited Evidence:</span>
                      {step.details.retrieved_evidence_ids.slice(0, 4).map((eid: string) => (
                        <button
                          key={eid}
                          onClick={() => onOpenEvidence(eid)}
                          className="px-2 py-0.5 text-[11px] font-mono bg-slate-950 hover:bg-cyan-950 text-cyan-400 hover:text-cyan-300 border border-slate-800 hover:border-cyan-800 rounded transition-colors"
                        >
                          {eid.slice(0, 8)}...
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Hypotheses & Topology/Timeline (5 cols) */}
        <div className="lg:col-span-5 space-y-6">
          {/* Hypothesis Competition Panel */}
          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Brain className="w-4 h-4 text-purple-400" />
                <h2 className="text-sm font-bold uppercase tracking-wider text-slate-200">Hypothesis Ranking & Scores</h2>
              </div>
              <span className="text-xs font-mono text-slate-500">{hypotheses.length} evaluated</span>
            </div>

            {hypotheses.length === 0 ? (
              <div className="py-8 text-center text-slate-500 text-xs font-mono">
                Awaiting hypothesis ranking stage...
              </div>
            ) : (
              <div className="space-y-3">
                {hypotheses.map((hyp, hIdx) => {
                  const isTop = hIdx === 0;
                  const score = hyp.final_score ?? 0;
                  return (
                    <div
                      key={hyp.hypothesis_id || hyp.title}
                      className={`p-3.5 rounded-xl border transition-all ${
                        hyp.status === 'confirmed' ? 'bg-emerald-950/30 border-emerald-800/80 shadow-md shadow-emerald-950/20' :
                        hyp.status === 'rejected' || hyp.status === 'weak' ? 'bg-slate-950/80 border-slate-800 opacity-60' :
                        'bg-slate-950 border-slate-800'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-bold text-slate-200 line-clamp-1">{hyp.title}</span>
                          </div>
                          <span className="text-[10px] font-mono text-slate-500 block uppercase">{hyp.category}</span>
                        </div>
                        <span className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded uppercase ${
                          hyp.status === 'confirmed' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' :
                          hyp.status === 'investigating' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800 animate-pulse' :
                          hyp.status === 'rejected' || hyp.status === 'weak' ? 'bg-rose-950 text-rose-300 border border-rose-800' :
                          'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}>
                          {hyp.status}
                        </span>
                      </div>

                      {/* Score Bar */}
                      <div className="mt-3 space-y-1">
                        <div className="flex items-center justify-between text-[11px] font-mono">
                          <span className="text-slate-400">Score Weight:</span>
                          <span className="font-bold text-slate-200">{score.toFixed(1)} / 100</span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              hyp.status === 'confirmed' ? 'bg-gradient-to-r from-emerald-500 to-cyan-400' :
                              hyp.status === 'rejected' || hyp.status === 'weak' ? 'bg-rose-600' : 'bg-indigo-500'
                            }`}
                            style={{ width: `${Math.min(Math.max(score, 5), 100)}%` }}
                          />
                        </div>
                      </div>

                      {/* Before / After Diff */}
                      {hyp.score_before !== null && hyp.score_after !== null && (
                        <div className="mt-2 text-[10px] font-mono text-slate-400 flex items-center justify-between">
                          <span>Critique: {hyp.score_before} → {hyp.score_after}</span>
                          <span className="text-slate-500">{hyp.supporting_count} supp / {hyp.contradictions_count} contra</span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Timeline Clusters Panel */}
          {timeline && (
            <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-bold uppercase tracking-wider text-slate-200">Incident Timeline Clusters</h2>
                </div>
                <span className="text-xs font-mono text-slate-500">{timeline.total_events} raw events</span>
              </div>

              <div className="space-y-2.5">
                {timeline.clusters.map((c) => (
                  <div key={c.cluster_id} className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono space-y-1">
                    <div className="flex items-center justify-between text-slate-400">
                      <span className="text-cyan-300 font-medium">{new Date(c.start_time).toLocaleTimeString()} - {new Date(c.end_time).toLocaleTimeString()}</span>
                      <span>{c.event_count} events</span>
                    </div>
                    <p className="text-slate-300 text-[11px] leading-snug">{c.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
