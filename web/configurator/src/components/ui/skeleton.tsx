import { cn } from "@/lib/utils";

/**
 * Skeleton — shimmer loading placeholder. shadcn convention.
 * Used in lieu of spinners; the shimmer feels more intentional.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-md skeleton-shimmer",
        className,
      )}
      {...props}
    />
  );
}
