# UI Context

> These are proposed defaults for a custom-designed UI, chosen to
> fit a patient-facing healthcare product rather than a dark
> developer-tool aesthetic. Treat as a starting point — adjust freely.

## Theme

Light theme. Calm, trustworthy, clinical-but-warm — this is a
product patients talk to about their health/appearance, so it should
read as approachable and clean, not like a technical dashboard. The
staff dashboard can reuse the same tokens with a slightly denser
layout, still light theme (no dark mode for v1).

## Colors

| Role            | CSS Variable       | Value       | Notes                              |
| ---------------- | ------------------- | ------------ | ------------------------------------ |
| Page background | `--bg-base`        | `#F7F8FA`   | Soft off-white, not pure white      |
| Surface         | `--bg-surface`     | `#FFFFFF`   | Cards, panels                        |
| Primary text    | `--text-primary`   | `#1B2430`   | Near-black slate, not pure black    |
| Muted text      | `--text-muted`     | `#5C6B7A`   | Secondary labels, timestamps        |
| Primary accent  | `--accent-primary` | `#2F8F7E`   | Calm teal — voice agent, primary CTAs |
| Secondary accent| `--accent-secondary`| `#5B7FDB`  | Links, informational highlights     |
| Border          | `--border-default` | `#E2E6EA`   | Card/input borders                   |
| Error           | `--state-error`    | `#D64545`   | Failed booking, validation errors    |
| Success         | `--state-success`  | `#2FA36B`   | Confirmed booking, resolved item     |
| Warning/Escalation | `--state-warning` | `#D98A2B` | Items flagged for staff decision     |

Dental clinic and cosmetic clinic demo instances use the same token
set — differentiate them via clinic name/logo text and content, not
a separate color scheme, to keep the demo simple.

## Typography

| Role      | Font          | Variable      |
| --------- | -------------- | -------------- |
| UI text   | Inter          | `--font-sans` |
| Code/mono | JetBrains Mono | `--font-mono` (used sparingly — e.g. appointment IDs in the dashboard) |

## Border Radius

| Context           | Class          |
| ------------------ | --------------- |
| Inline / small UI  | `rounded-md`   |
| Cards / panels     | `rounded-xl`   |
| Modals / overlays  | `rounded-2xl`  |
| Voice orb / avatar | `rounded-full` |

## Component Library

shadcn/ui on top of Tailwind. Components live in
`frontend/src/shared/components/ui/`. Use the shadcn CLI to add new
primitives rather than hand-writing them — this is a protected
generated folder (see `ai-workflow-rules.md`).

## Layout Patterns

- **Voice screen**: full-viewport, centered layout — a single large
  voice orb/avatar as the focal point, minimal chrome, live
  transcript optionally shown below it, clinic name/logo in a slim
  top bar.
- **Staff dashboard**: left sidebar (navigation: Appointments,
  Escalations, Settings) + main content area, top bar with clinic
  name and logged-in user. Standard admin-dashboard layout, not the
  voice screen's minimal style.
- **Escalation items**: card-based list, warning-accent left border,
  clear "Mark Resolved" action.
- **Modals**: centered overlay with backdrop blur, used for
  booking confirmation details and escalation detail view.

## Icons

Lucide React. Stroke-based icons only. Sizes: `h-4 w-4` for inline
icons (list rows, badges), `h-5 w-5` for buttons and nav items,
`h-8 w-8` for the voice screen's mic/state icon.
