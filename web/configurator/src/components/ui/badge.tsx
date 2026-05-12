import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider tabular transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-accent-muted text-[hsl(var(--accent))]",
        outline:
          "border-border bg-transparent text-muted-foreground",
        muted:
          "border-transparent bg-elevated text-muted-foreground",
        success:
          "border-transparent bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]",
        warning:
          "border-transparent bg-[hsl(var(--warning)/0.18)] text-[hsl(var(--warning))]",
        destructive:
          "border-transparent bg-[hsl(var(--destructive)/0.2)] text-[hsl(var(--destructive))]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}
