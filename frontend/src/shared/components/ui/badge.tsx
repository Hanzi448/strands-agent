import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/shared/lib/utils";

// `ai-workflow-rules.md` -> Protected Files: shadcn-generated, regenerate
// via the CLI rather than hand-editing. Variants map to `ui-context.md` ->
// Colors' state roles, since a badge is how status (`scheduled`,
// `cancelled`, `open`, ...) reads at a glance in a list.
const badgeVariants = cva(
  "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "bg-[var(--bg-base)] text-[var(--text-muted)]",
        success: "bg-[var(--bg-state-success-wash)] text-[var(--state-success)]",
        warning: "bg-[var(--bg-state-warning-wash)] text-[var(--state-warning)]",
        error: "bg-[var(--bg-state-error-wash)] text-[var(--state-error)]",
        info: "bg-[var(--bg-accent-secondary-wash)] text-[var(--accent-secondary)]",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { Badge, badgeVariants };
