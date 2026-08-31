import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge conditional class names, resolving Tailwind conflicts -- the
 * standard shadcn/ui helper every generated component imports. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
