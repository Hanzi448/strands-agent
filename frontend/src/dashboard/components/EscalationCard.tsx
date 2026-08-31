import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import type { Escalation } from "@/dashboard/types";

interface EscalationCardProps {
  escalation: Escalation;
  onOpen: (escalation: Escalation) => void;
  onResolve: (escalation: Escalation) => void;
  resolving: boolean;
}

/** `ui-context.md` -> Layout Patterns: "Escalation items: card-based list,
 * warning-accent left border, clear 'Mark Resolved' action." */
export function EscalationCard({ escalation, onOpen, onResolve, resolving }: EscalationCardProps) {
  return (
    <div
      className="flex items-start justify-between gap-3 rounded-xl border border-[var(--border-default)] border-l-4 border-l-[var(--state-warning)] bg-[var(--bg-surface)] p-4 shadow-sm"
    >
      <button
        type="button"
        className="flex-1 text-left"
        onClick={() => onOpen(escalation)}
      >
        <div className="mb-1 flex items-center gap-2">
          <Badge variant={escalation.source === "voice" ? "info" : "warning"}>
            {escalation.source === "voice" ? "Live call" : "Background scan"}
          </Badge>
          <span className="text-xs text-[var(--text-muted)]">
            {new Date(escalation.created_at).toLocaleString()}
          </span>
        </div>
        <p className="text-sm text-[var(--text-primary)]">{escalation.reason}</p>
      </button>
      <Button
        variant="outline"
        size="sm"
        disabled={resolving}
        onClick={() => onResolve(escalation)}
      >
        {resolving ? "Resolving…" : "Mark Resolved"}
      </Button>
    </div>
  );
}
