'use client';

import React, { useState } from 'react';
import { IncidentSummary, Investigation } from '../types';
import { generateIncident, startInvestigation, startDemoInvestigation, extractErrorMessage, formatLocalTime } from '../lib/api';
import { Play, Sparkles, RefreshCw, Activity, Server, Clock, AlertCircle, ShieldAlert, Cpu, Loader2 } from 'lucide-react';

interface Screen1LauncherProps {
  incidents: IncidentSummary[];
  loadingIncidents: boolean;
  onRefreshIncidents: () => void;
  onStartInvestigation: (incidentId: string) => Promise<void>;
  onInvestigationStarted: (investigation: Investigation) => void;
}

export function Screen1Launcher({
  incidents,
  loadingIncidents,
  onRefreshIncidents,
  onStartInvestigation,
  onInvestigationStarted,
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
      const cleanSeed = seedInput.trim();
      const seedVal = cleanSeed ? parseInt(cleanSeed, 10) : undefined;
      const newInc = await generateIncident(selectedType, seedVal);
      onRefreshIncidents();
      const inv = await startInvestigation(newInc.incident_id);
      onInvestigationStarted(inv);
    } catch (err: any) {
      setError(extractErrorMessage(err, 'Failed to generate incident'));
    } finally {
      setGenerating(false);
    }
  };

  const handleRunDemo = async () => {
    setDemoStarting(true);
    setError(null);
    try {
      const inv = await startDemoInvestigation();
      onInvestigationStarted(inv);
    } catch (err: any) {
      setError(extractErrorMessage(err, 'Failed to start demo incident'));
    } finally {
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
          <p className="text-xs text-slate-400 font-mono max-w-2xl leading-relaxed">
            Instantly boots a full microservice incident with telemetry, unindexed query regressions, and masked distractors. Evaluated through 8 autonomous state machine steps.
          </p>
        </div>

        <button
          onClick={handleRunDemo}
          disabled={demoStarting}
          className="w-full md:w-auto px-6 py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-sm font-mono shadow-lg shadow-cyan-950/50 flex items-center justify-center gap-2.5 transition-all disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer shrink-0"
        >
          {demoStarting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Launching Investigation...</span>
            </>
          ) : (
            <>
              <Play className="w-4 h-4 fill-slate-950" />
              <span>Run Demo Incident</span>
            </>
          )}
        </button>
      </div>

      {demoStarting && (
        <div className="p-3.5 rounded-xl bg-cyan-950/40 border border-cyan-800/50 text-cyan-300 text-xs font-mono flex items-center gap-2.5 animate-pulse">
          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
          <span>Warming up cloud backend & generating synthetic telemetry (takes ~15-25s on cloud instances)...</span>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-950/80 border border-rose-800 text-rose-200 text-xs font-mono flex items-center gap-3">
          <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Generator & Manual Incident Launcher Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Synthetic Generator Card */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-6 shadow-xl">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-mono">
              Generate New Incident
            </h2>
            <p className="text-xs text-slate-400 font-mono">
              Inject synthetic failures into simulated e-commerce microservices.
            </p>
          </div>

          <form onSubmit={handleGenerate} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-mono text-slate-300">Failure Archetype</label>
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value)}
                className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-cyan-600"
              >
                <option value="random">🎲 Random Complex Failure</option>
                <option value="bad_deployment_db_exhaustion">🚀 Bad Deployment + DB Saturation</option>
                <option value="dependency_failure_cascade">⚡ Downstream Dependency Cascade</option>
                <option value="memory_leak_masked_deployment">🧠 Memory Leak + Red-Herring Deployment</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-mono text-slate-300">Deterministic Seed (Optional)</label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                placeholder="e.g. 42 (leave blank for random)"
                value={seedInput}
                onChange={(e) => setSeedInput(e.target.value.replace(/[^0-9]/g, ''))}
                className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-xl text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <button
              type="submit"
              disabled={generating}
              className="w-full py-2.5 text-xs font-mono font-bold bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-100 rounded-xl transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
            >
              {generating ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Generating Telemetry...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Synthesize & Investigate</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Existing Incidents List */}
        <div className="lg:col-span-2 p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-6 shadow-xl">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-mono">
                Telemetry Store Incidents ({incidents.length})
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                Select an incident to launch real-time multi-hypothesis root-cause analysis.
              </p>
            </div>
            <button
              onClick={onRefreshIncidents}
              disabled={loadingIncidents}
              className="p-2 text-slate-400 hover:text-slate-200 bg-slate-950 border border-slate-800 rounded-xl transition-colors cursor-pointer"
              title="Refresh incidents"
            >
              <RefreshCw className={`w-4 h-4 ${loadingIncidents ? 'animate-spin' : ''}`} />
            </button>
          </div>

          <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
            {loadingIncidents && incidents.length === 0 ? (
              <div className="p-8 text-center text-xs font-mono text-slate-500">
                <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-cyan-500" />
                Loading incident history from telemetry database...
              </div>
            ) : incidents.length === 0 ? (
              <div className="p-8 text-center text-xs font-mono text-slate-500 border border-dashed border-slate-800 rounded-xl">
                No incidents in database yet. Click "Run Demo Incident" or "Generate New Incident" above to begin.
              </div>
            ) : (
              incidents.map((inc) => (
                <div
                  key={inc.incident_id}
                  className="p-4 rounded-xl bg-slate-950 border border-slate-800/80 hover:border-cyan-800/80 transition-all flex items-center justify-between gap-4 group"
                >
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs font-bold text-slate-200 truncate">
                        {inc.incident_type.replace(/_/g, ' ').toUpperCase()}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-rose-950/80 text-rose-300 border border-rose-900">
                        {inc.severity}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500 flex-wrap">
                      <span className="flex items-center gap-1">
                        <Server className="w-3 h-3 text-cyan-400" /> {inc.affected_services?.join(', ') || 'cluster'}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3 text-slate-400" /> {formatLocalTime(inc.started_at)}
                      </span>
                      <span className="flex items-center gap-1">
                        <Activity className="w-3 h-3 text-emerald-400" /> {inc.duration_minutes}m duration
                      </span>
                    </div>
                  </div>

                  <button
                    onClick={() => onStartInvestigation(inc.incident_id)}
                    className="px-3.5 py-1.5 text-xs font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 rounded-lg transition-colors flex items-center gap-1.5 shrink-0 cursor-pointer shadow-sm"
                  >
                    <Play className="w-3 h-3 fill-cyan-300" />
                    <span>Investigate</span>
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
