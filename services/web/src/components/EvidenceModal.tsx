'use client';

import React, { useEffect, useState } from 'react';
import { EvidenceItem } from '../types';
import { fetchEvidenceDetail, extractErrorMessage } from '../lib/api';
import { X, CheckCircle2, AlertTriangle, Activity, Database, GitCommit, FileText, Copy, Terminal } from 'lucide-react';

interface EvidenceModalProps {
  evidenceId: string | null;
  onClose: () => void;
}

export function EvidenceModal({ evidenceId, onClose }: EvidenceModalProps) {
  const [evidence, setEvidence] = useState<EvidenceItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (!evidenceId) return;
    setLoading(true);
    setError(null);
    setShowRaw(false);

    fetchEvidenceDetail(evidenceId)
      .then((data) => setEvidence(data))
      .catch((err) => setError(extractErrorMessage(err, 'Failed to load evidence record.')))
      .finally(() => setLoading(false));
  }, [evidenceId]);

  if (!evidenceId) return null;

  const handleCopy = () => {
    if (!evidence) return;
    navigator.clipboard.writeText(JSON.stringify(evidence, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getSourceIcon = (type: string) => {
    switch (type) {
      case 'log': return <FileText className="w-5 h-5 text-amber-400" />;
      case 'metric': return <Activity className="w-5 h-5 text-cyan-400" />;
      case 'trace': return <Terminal className="w-5 h-5 text-emerald-400" />;
      case 'deployment': return <GitCommit className="w-5 h-5 text-purple-400" />;
      case 'database': return <Database className="w-5 h-5 text-blue-400" />;
      case 'alert': return <AlertTriangle className="w-5 h-5 text-rose-400" />;
      default: return <FileText className="w-5 h-5 text-slate-400" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
      <div 
        className="relative w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/50">
          <div className="flex items-center gap-3">
            {evidence ? getSourceIcon(evidence.evidence_type) : <Activity className="w-5 h-5 text-cyan-400 animate-spin" />}
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-slate-200">Evidence Record</h3>
                {evidence && (
                  <span className="px-2 py-0.5 text-xs font-mono font-medium uppercase rounded bg-slate-800 text-slate-300 border border-slate-700">
                    {evidence.evidence_type}
                  </span>
                )}
              </div>
              <p className="text-xs font-mono text-slate-400 truncate max-w-md">{evidenceId}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors text-xs flex items-center gap-1.5 border border-slate-800"
              title="Copy JSON"
            >
              {copied ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-4">
          {loading ? (
            <div className="py-12 text-center text-slate-400 flex flex-col items-center gap-3">
              <Activity className="w-8 h-8 text-cyan-400 animate-spin" />
              <p className="text-sm font-mono">Fetching telemetry item from database...</p>
            </div>
          ) : error ? (
            <div className="p-4 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300 text-sm">
              Failed to load evidence: {error}
            </div>
          ) : evidence ? (
            <div className="space-y-4">
              {/* Primary metadata row */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block">SERVICE</span>
                  <span className="text-sm font-mono font-medium text-slate-200">{evidence.service}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block">TIMESTAMP (UTC)</span>
                  <span className="text-sm font-mono text-slate-200">
                    {new Date(evidence.timestamp).toLocaleTimeString()} ({new Date(evidence.timestamp).toISOString().split('T')[0]})
                  </span>
                </div>
                {evidence.severity && (
                  <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800">
                    <span className="text-xs text-slate-500 font-mono block">SEVERITY</span>
                    <span className={`text-sm font-mono font-bold ${
                      evidence.severity === 'ERROR' || evidence.severity === 'CRITICAL' ? 'text-rose-400' :
                      evidence.severity === 'WARN' ? 'text-amber-400' : 'text-slate-300'
                    }`}>
                      {evidence.severity}
                    </span>
                  </div>
                )}
              </div>

              {/* Specific Content Type Display */}
              {evidence.message && (
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block mb-1">LOG MESSAGE</span>
                  <p className="text-sm font-mono text-amber-200/90 whitespace-pre-wrap">{evidence.message}</p>
                </div>
              )}

              {evidence.metric_name && (
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block mb-1">METRIC SAMPLE</span>
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-mono text-slate-400">{evidence.metric_name}:</span>
                    <span className="text-lg font-mono font-bold text-cyan-400">{evidence.value}</span>
                    <span className="text-xs font-mono text-slate-400">{evidence.unit}</span>
                  </div>
                </div>
              )}

              {evidence.operation && (
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block mb-1">SPAN TRACE</span>
                  <div className="space-y-1 font-mono text-xs text-slate-300">
                    <div>Operation: <span className="text-emerald-400 font-medium">{evidence.operation}</span></div>
                    <div>Duration: <span className="text-slate-100 font-bold">{evidence.duration_ms} ms</span></div>
                    <div>Status: <span className="text-slate-100">{evidence.status}</span></div>
                  </div>
                </div>
              )}

              {evidence.version && (
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block mb-1">DEPLOYMENT DETAILS</span>
                  <div className="space-y-1 font-mono text-xs text-slate-300">
                    <div>Release Version: <span className="text-purple-400 font-bold">{evidence.version}</span></div>
                    <div>Status: <span className="text-slate-100">{evidence.status}</span></div>
                  </div>
                </div>
              )}

              {evidence.database_name && (
                <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-xs text-slate-500 font-mono block mb-1">DATABASE TELEMETRY</span>
                  <div className="space-y-1 font-mono text-xs text-slate-300">
                    <div>Database: <span className="text-blue-400 font-medium">{evidence.database_name}</span></div>
                    <div>Active Connections: <span className="text-slate-100 font-bold">{evidence.metadata?.connections_active} / {evidence.metadata?.connections_max}</span></div>
                    <div>Query Latency: <span className="text-slate-100">{evidence.metadata?.latency_ms} ms</span></div>
                  </div>
                </div>
              )}

              {/* Raw JSON Toggle */}
              <div className="pt-2">
                <button
                  onClick={() => setShowRaw(!showRaw)}
                  className="text-xs font-mono text-slate-400 hover:text-cyan-400 transition-colors"
                >
                  {showRaw ? '▼ Hide Full JSON Payload' : '▶ Show Full JSON Payload'}
                </button>
                {showRaw && (
                  <pre className="mt-2 p-3 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-300 overflow-x-auto max-h-48">
                    {JSON.stringify(evidence, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-800 bg-slate-950/40 text-right">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
