'use client';

import React, { useEffect, useState, useRef } from 'react';
import { IncidentSummary, Investigation, HypothesisData, TimelineData } from '../types';
import { 
  fetchIncidents, startInvestigation, fetchInvestigation, 
  fetchInvestigationHypotheses, fetchInvestigationTimeline 
} from '../lib/api';
import { Screen1Launcher } from '../components/Screen1Launcher';
import { Screen2Investigation } from '../components/Screen2Investigation';
import { Screen3FinalRCA } from '../components/Screen3FinalRCA';
import { EvidenceModal } from '../components/EvidenceModal';
import { AlertCircle, RefreshCw, X } from 'lucide-react';

export default function Home() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [loadingIncidents, setLoadingIncidents] = useState(false);
  const [activeInvestigationId, setActiveInvestigationId] = useState<string | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [hypotheses, setHypotheses] = useState<HypothesisData[]>([]);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'live' | 'rca'>('live');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Load incidents on mount
  useEffect(() => {
    loadIncidents();
  }, []);

  const loadIncidents = async () => {
    setLoadingIncidents(true);
    setErrorMessage(null);
    try {
      const data = await fetchIncidents();
      setIncidents(data);
    } catch (err: any) {
      console.error('Failed to load incidents', err);
      setErrorMessage(err.message || 'Failed to connect to TRACE backend API. Please ensure the backend server is running.');
    } finally {
      setLoadingIncidents(false);
    }
  };

  // Set active investigation directly
  const handleInvestigationStarted = (inv: Investigation) => {
    setActiveInvestigationId(inv.investigation_id);
    setInvestigation(inv);
    setActiveTab('live');
    setErrorMessage(null);
  };

  // Start an investigation for an existing incident
  const handleStartInvestigation = async (incidentId: string) => {
    setErrorMessage(null);
    try {
      const inv = await startInvestigation(incidentId);
      handleInvestigationStarted(inv);
    } catch (err: any) {
      console.error('Failed to start investigation', err);
      setErrorMessage(err.message || 'Failed to initiate autonomous investigation.');
    }
  };

  // Polling loop when an active investigation is running
  useEffect(() => {
    if (!activeInvestigationId) return;

    let consecutiveErrors = 0;

    const poll = async () => {
      try {
        const inv = await fetchInvestigation(activeInvestigationId);
        setInvestigation(inv);
        consecutiveErrors = 0;

        // Fetch hypotheses & timeline
        const [hyps, tl] = await Promise.all([
          fetchInvestigationHypotheses(activeInvestigationId).catch(() => []),
          fetchInvestigationTimeline(activeInvestigationId).catch(() => null),
        ]);
        setHypotheses(hyps);
        if (tl) setTimeline(tl);

        // Auto-switch to RCA view when completed
        if (inv.final_state === 'rca_generated' || inv.final_state === 'inconclusive') {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
        }
      } catch (err: any) {
        console.error('Poll error', err);
        consecutiveErrors += 1;
        if (consecutiveErrors >= 5) {
          setErrorMessage('Connection interrupted while tracking investigation. Retrying in background...');
        }
      }
    };

    poll();
    pollIntervalRef.current = setInterval(poll, 2500);

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [activeInvestigationId]);

  return (
    <main className="min-h-screen bg-[#080c14] text-slate-100 flex flex-col justify-between">
      <div className="flex-1">
        {/* Global Error Banner */}
        {errorMessage && (
          <div className="max-w-6xl mx-auto px-4 pt-4">
            <div className="p-3.5 rounded-xl bg-rose-950/90 border border-rose-800 text-rose-200 text-xs font-mono flex items-center justify-between shadow-lg animate-in fade-in">
              <div className="flex items-center gap-2.5">
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{errorMessage}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => loadIncidents()}
                  className="px-2.5 py-1 rounded bg-rose-900 hover:bg-rose-800 text-rose-100 flex items-center gap-1.5 transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Retry</span>
                </button>
                <button
                  onClick={() => setErrorMessage(null)}
                  className="p-1 rounded text-rose-400 hover:text-rose-200 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}

        {!activeInvestigationId || !investigation ? (
          <Screen1Launcher
            incidents={incidents}
            loadingIncidents={loadingIncidents}
            onRefreshIncidents={loadIncidents}
            onStartInvestigation={handleStartInvestigation}
            onInvestigationStarted={handleInvestigationStarted}
          />
        ) : (
          <div className="space-y-2">
            {/* View Switcher Header (when investigation is done) */}
            {(investigation.final_state === 'rca_generated' || investigation.final_state === 'inconclusive') && (
              <div className="max-w-7xl mx-auto px-4 pt-4 flex items-center justify-end gap-2">
                <button
                  onClick={() => setActiveTab('live')}
                  className={`px-3 py-1.5 text-xs font-mono font-medium rounded-lg border transition-colors ${
                    activeTab === 'live'
                      ? 'bg-slate-800 text-cyan-300 border-cyan-800'
                      : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
                  }`}
                >
                  Investigation Process Trace
                </button>
                <button
                  onClick={() => setActiveTab('rca')}
                  className={`px-3 py-1.5 text-xs font-mono font-bold rounded-lg border transition-colors ${
                    activeTab === 'rca'
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
                  }`}
                >
                  Final RCA Report
                </button>
              </div>
            )}

            {activeTab === 'rca' && (investigation.final_state === 'rca_generated' || investigation.final_state === 'inconclusive') ? (
              <Screen3FinalRCA
                investigation={investigation}
                hypotheses={hypotheses}
                onBackToLauncher={() => {
                  setActiveInvestigationId(null);
                  setInvestigation(null);
                  loadIncidents();
                }}
                onOpenEvidence={(id) => setSelectedEvidenceId(id)}
              />
            ) : (
              <Screen2Investigation
                investigation={investigation}
                hypotheses={hypotheses}
                timeline={timeline}
                onBackToLauncher={() => {
                  setActiveInvestigationId(null);
                  setInvestigation(null);
                  loadIncidents();
                }}
                onOpenEvidence={(id) => setSelectedEvidenceId(id)}
              />
            )}
          </div>
        )}
      </div>

      {/* Global Evidence Detail Modal */}
      <EvidenceModal
        evidenceId={selectedEvidenceId}
        onClose={() => setSelectedEvidenceId(null)}
      />

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-4 px-6 text-center text-xs font-mono text-slate-400 bg-slate-950/80">
        TRACE — Telemetry Root-cause Autonomous Critique Engine | Ground-Truth Isolated Architecture
      </footer>
    </main>
  );
}
