/**
 * Button — shadcn/ui pattern, adapted to StemForge's palette.
 *
 * Variants:
 *   - default: orange accent on slate; primary CTA
 *   - secondary: subtle elevated background, used for sidebar ops
 *   - outline: ghost with thin border, used in empty-state CTAs
 *   - ghost: text-only hover, used for inline actions
 *   - destructive: red — for the rare drop / reset action
 *
 * Sizes: sm (h-8), default (h-9), lg (h-10), icon (square).
 *
 * Motion: hover scale 1.02, active scale 0.98 via Tailwind (transition 120ms).
 *   Framer Motion wraps elsewhere where we want more elaborate state changes.
 */
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-[transform,background-color,color,border-color,box-shadow] duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.98] hover:scale-[1.02]",
  {
    variants: {
      variant: {
        default:
          "bg-accent text-accent-foreground hover:bg-accent/90 shadow-[0_0_0_1px_hsl(var(--accent)/0.5),0_6px_22px_-8px_hsl(var(--accent)/0.6)]",
        secondary:
          "bg-elevated text-foreground border border-border hover:bg-[hsl(var(--elevated))]/80 hover:border-[hsl(0_0%_18%)]",
        outline:
          "border border-border bg-transparent text-foreground hover:bg-elevated hover:border-[hsl(0_0%_22%)]",
        ghost:
          "bg-transparent text-foreground hover:bg-elevated/60 hover:text-foreground",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
      },
      size: {
        default: "h-9 px-3.5 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-5",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
