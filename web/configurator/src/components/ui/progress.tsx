import { cn } from "@/lib/utils";

interface ProgressProps {
  /** 0..1 */
  value: number;
  className?: string;
  /** Color override; defaults to the accent ramp. */
  tone?: "accent" | "success" | "warning";
}

/**
 * Inline progress bar. Driven by SSE `progress` events.
 * The bar tweens via CSS transition for smoothness; bigger jumps animate
 * naturally without needing Framer Motion here.
 */
export function Progress({ value, className, tone = "accent" }: ProgressProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const bg =
    tone === "success"
      ? "bg-[hsl(var(--success))]"
      : tone === "warning"
        ? "bg-[hsl(var(--warning))]"
        : "bg-[hsl(var(--accent))]";
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={clamped}
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full bg-elevated",
        className,
      )}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-300 ease-out",
          bg,
        )}
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  );
}
