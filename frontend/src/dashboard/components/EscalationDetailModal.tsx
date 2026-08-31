import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/shared/components/ui/dialog";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import type { Escalation } from "@/dashboard/types";

interface EscalationDetailModalProps {
  escalation: Escalation | null;
  onOpenChange: (open: boolean) => void;
  onResolve: (escalation: Escalation) => void;
  resolving: boolean;
}

/** `ui-context.md` -> Layout Patterns: "Modals: centered overlay with
 * backdrop blur, used for ... escalation detail view." */
export function EscalationDetailModal({
  escalation,
  onOpenChange,
  onResolve,
  resolving,
}: EscalationDetailModalProps) {
  return (
    <Dialog open={escalation !== null} onOpenChange={onOpenChange}>
      {escalation && (
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Escalation detail</DialogTitle>
            <DialogDescription>{escalation.escalation_id}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant={escalation.status === "open" ? "warning" : "success"}>
                {escalation.status === "open" ? "Open" : "Resolved"}
              </Badge>
              <Badge variant={escalation.source === "voice" ? "info" : "neutral"}>
                {escalation.source === "voice" ? "Live call" : "Background scan"}
              </Badge>
            </div>
            <p className="text-[var(--text-primary)]">{escalation.reason}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-[var(--text-muted)]">
              <dt>Raised</dt>
              <dd>{new Date(escalation.created_at).toLocaleString()}</dd>
              {escalation.resolved_at && (
                <>
                  <dt>Resolved</dt>
                  <dd>{new Date(escalation.resolved_at).toLocaleString()}</dd>
                </>
              )}
              {escalation.patient_id && (
                <>
                  <dt>Patient</dt>
                  <dd className="font-mono">{escalation.patient_id}</dd>
                </>
              )}
              {escalation.appointment_id && (
                <>
                  <dt>Appointment</dt>
                  <dd className="font-mono">{escalation.appointment_id}</dd>
                </>
              )}
            </dl>
            {escalation.status === "open" && (
              <Button
                disabled={resolving}
                onClick={() => onResolve(escalation)}
                className="self-start"
              >
                {resolving ? "Resolving…" : "Mark Resolved"}
              </Button>
            )}
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
