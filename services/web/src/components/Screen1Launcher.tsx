'use client';

import React, { useState } from 'react';
import { IncidentSummary } from '../types';
import { generateIncident, startInvestigation, startDemoInvestigation } from '../lib/api';
import { Play, Sparkles, RefreshCw, Activity, Server, Clock, AlertCircle, ShieldAlert, Cpu } from 'lucide-react';

interface Screen1LauncherProps {
  incidents: IncidentSummary[];
  loadingIncidents: boolean;
  onRefreshIncidents: () => void;
  onStartInvestigation: (incidentId: string) => void;
}

export function Screen1Launcher({
  incidents,
  loadingIncidents,
  onRefreshIncidents,
  onStartInvestigation,
}: Screen1LauncherProps) {
  const [selectedType, setSelectedType] = useState<string>('random');
  const [seedInput, setSeedInput] = useState<string>('');
  const [generating, setGenerating] = useState<boolean>(false);
  const [demoStarting, setDemoStarting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setGenerating(true);
    setError(null);
    try {
      const seedVal = seedInput.trim() ? parseInt(seedInput.trim(), 10) : undefined;
      const newInc = await generateIncident(selectedType, seedVal);
      onRefreshIncidents();
      // Directly kick off investigation on generated incident
      onStartInvestigation(newInc.incident_id);
    } catch (err: any) {
      setError(err.message || 'Failed to generate incident');
      setGenerating(false);
    }
  };

  const handleRunDemo = async () => {
    setDemoStarting(true);
    setError(null);
    try {
      const inv = await startDemoInvestigation();
      onStartInvestigation(inv.incident_id);
    } catch (err: any) {
      setError(err.message || 'Failed to start demo incident');
      setDemoStarting(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-10 space-y-8 animate-in fade-in duration-200">
      {/* Header Banner */}
      <div className="space-y-3 text-center sm:text-left border-b border-slate-800 pb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/60 border border-cyan-800/80 text-cyan-400 text-xs font-mono uppercase tracking-wider font-semibold">
          <Cpu className="w-3.5 h-3.5" /> Autonomous SRE Root-Cause Engine
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white flex items-center justify-center sm:justify-start gap-3">
          TRACE <span className="text-slate-500 font-light text-2xl">| Multi-Hypothesis Investigation</span>
        </h1>
        <p className="text-slate-400 text-sm max-w-3xl leading-relaxed">
          TRACE dynamically constructs hypotheses, retrieves real multi-modal telemetry (logs, metrics, traces, database connections, and deployments), and applies deterministic falsification to discover true root causes without prompt-only hallucinations.
        </p>
      </div>

      {/* Demo Mode Action Card */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-cyan-950/40 via-slate-900 to-indigo-950/40 border border-cyan-800/40 shadow-xl flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-semibold text-slate-100">Deterministic Evaluated Demo Scenario</h2>
          </div>
          <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
            Instantly run a verified live investigation (<span className="font-mono text-cyan-300">bad_deployment_db_exhaustion, seed=1</span>). Watch the agent scope telemetry, compute candidate scores, run live Gemini self-critique with deterministic slope checks, and emit an evidence-grounded RCA.
          </p>
        </div>
        <button
          onClick={handleRunDemo}
          disabled={demoStarting || generating}
          className="w-full md:w-auto px-6 py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-semibold text-sm shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/30 transition-all flex items-center justify-center gap-2.5 disabled:opacity-50 shrink-0 cursor-pointer"
        >
          {demoStarting ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Launching Demo...</span>
            </>
          ) : (
            <>
              <Play className="w-4 h-4 fill-current" />
              <span>Run Demo Incident</span>
            </>
          )}
        </button>
      </div>

      {/* Generator Form & Active Incidents Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column: Generator Form */}
        <div className="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl space-y-6">
          <div className="flex items-center gap-2.5 border-b border-slate-800 pb-4">
            <Server className="w-5 h-5 text-indigo-400" />
            <h2 className="text-base font-semibold text-slate-100">Launch New Incident</h2>
          </div>

          <form onSubmit={handleGenerate} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-mono text-slate-400 block">INCIDENT ARCHETYPE</label>
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-sm font-mono text-slate-200 focus:outline-none focus:border-cyan-500 transition-colors"
              >
                <option value="random">🎲 Random Archetype (Balanced)</option>
                <option value="bad_deployment_db_exhaustion">Bad Deployment → DB Pool Exhaustion</option>
                <option value="dependency_failure_cascade">Payment Dependency Failure Cascade</option>
                <option value="memory_leak_masked_deployment">Slow Memory Leak w/ Coincidental Deploy</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-mono text-slate-400 block">SYNTHETIC RANDOM SEED (OPTIONAL)</label>
              <input
                type="number"
                placeholder="e.g. 42 (blank for random)"
                value={seedInput}
                onChange={(e) => setSeedInput(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-sm font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500 transition-colors"
              />
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={generating || demoStarting}
              className="w-full py-3 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-100 font-medium text-sm transition-all flex items-center justify-center gap-2 disabled:opacity-50 cursor-pointer"
            >
              {generating ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
                  <span>Synthesizing Telemetry...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 text-cyan-400" />
                  <span>Generate & Investigate</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Right Column: Previously Generated Incidents */}
        <div className="lg:col-span-2 p-6 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div className="flex items-center gap-2.5">
              <Clock className="w-5 h-5 text-cyan-400" />
              <h2 className="text-base font-semibold text-slate-100">Telemetry Incident History</h2>
            </div>
            <button
              onClick={onRefreshIncidents}
              disabled={loadingIncidents}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
              title="Refresh incidents"
            >
              <RefreshCw className={`w-4 h-4 ${loadingIncidents ? 'animate-spin' : ''}`} />
            </button>
          </div>

          <div className="overflow-x-auto">
            {incidents.length === 0 ? (
              <div className="py-12 text-center text-slate-500 text-sm">
                No incidents ingested yet. Click &quot;Run Demo Incident&quot; or &quot;Generate & Investigate&quot; above to create one.
              </div>
            ) : (
              <div className="space-y-3">
                {incidents.map((inc) => (
                  <div
                    key={inc.incident_id}
                    className="p-4 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-slate-700 transition-all flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-mono font-bold text-slate-200">
                          {inc.incident_type}
                        </span>
                        <span className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded uppercase ${
                          inc.severity === 'sev1' ? 'bg-rose-950 text-rose-300 border border-rose-800' : 'bg-amber-950 text-amber-300 border border-amber-800'
                        }`}>
                          {inc.severity}
                        </span>
                        <span className="text-xs font-mono text-slate-500">
                          {new Date(inc.started_at).toLocaleTimeString()} ({inc.duration_minutes}m window)
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[11px] font-mono text-slate-400">Affected:</span>
                        {inc.affected_services.map((svc) => (
                          <span key={svc} className="px-2 py-0.5 text-[11px] font-mono bg-slate-900 border border-slate-800 text-slate-300 rounded">
                            {svc}
                          </span>
                        ))}
                      </div>
                    </div>

                    <button
                      onClick={() => onStartInvestigation(inc.incident_id)}
                      className="px-4 py-2 text-xs font-semibold bg-cyan-950/80 hover:bg-cyan-900 border border-cyan-700/80 text-cyan-300 rounded-xl transition-colors flex items-center gap-1.5 shrink-0 cursor-pointer"
                    >
                      <Play className="w-3.5 h-3.5 fill-current" />
                      <span>Investigate</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
