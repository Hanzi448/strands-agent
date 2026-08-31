import { useEffect, useState } from "react";

import { listEscalations, resolveEscalation } from "@/dashboard/lib/dashboardApi";
import type { Escalation } from "@/dashboard/types";
import { EscalationCard } from "@/dashboard/components/EscalationCard";
import { EscalationDetailModal } from "@/dashboard/components/EscalationDetailModal";

/** `project-overview.md` -> Staff Dashboard: "View agent-flagged
 * escalations and mark them resolved." Only `status: "open"` items are
 * ever fetched (`listEscalations` -> `list_open_escalations`) -- a
 * resolved one leaves the queue by refetching rather than by a client-side
 * filter, so this view never has to reconcile two sources of truth. */
export function EscalationsView() {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Escalation | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  function refresh() {
    setLoading(true);
    setError(null);
    listEscalations()
      .then(setEscalations)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load."))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleResolve(escalation: Escalation) {
    setResolvingId(escalation.escalation_id);
    setError(null);
    try {
      await resolveEscalation(escalation.escalation_id);
      setSelected(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve.");
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-[var(--text-primary)]">Escalations</h1>

      {loading && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
      {error && <p className="text-sm text-[var(--state-error)]">{error}</p>}
      {!loading && !error && escalations.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">Nothing outstanding. Queue is clear.</p>
      )}

      <div className="flex flex-col gap-2">
        {escalations.map((escalation) => (
          <EscalationCard
            key={escalation.escalation_id}
            escalation={escalation}
            onOpen={setSelected}
            onResolve={handleResolve}
            resolving={resolvingId === escalation.escalation_id}
          />
        ))}
      </div>

      <EscalationDetailModal
        escalation={selected}
        onOpenChange={(open) => !open && setSelected(null)}
        onResolve={handleResolve}
        resolving={resolvingId === selected?.escalation_id}
      />
    </div>
  );
}
