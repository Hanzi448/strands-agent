import type { Config } from "tailwindcss";

// Color values are not duplicated here -- components reference the CSS
// custom properties defined in `src/index.css` (`ui-context.md` -> Colors)
// directly via Tailwind's arbitrary-value syntax, e.g. `bg-[var(--bg-surface)]`.
// This file only extends what Tailwind cannot express as a CSS variable
// reference: font stacks.
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
