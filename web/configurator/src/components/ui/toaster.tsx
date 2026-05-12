import { Toaster as SonnerToaster } from "sonner";

/**
 * Top-level toaster mount. sonner's defaults match the dark theme; we tweak
 * position + duration to match the design language.
 */
export function Toaster() {
  return (
    <SonnerToaster
      theme="dark"
      position="bottom-right"
      richColors
      closeButton
      duration={3500}
      gap={8}
      toastOptions={{
        classNames: {
          toast:
            "glass !bg-[hsl(var(--elevated))]/90 !border-[hsl(0_0%_100%/0.07)] !text-foreground !rounded-lg !backdrop-blur-md",
          title: "!text-sm !font-medium !tracking-tightish",
          description: "!text-xs !text-muted-foreground",
          actionButton: "!bg-accent !text-accent-foreground",
        },
      }}
    />
  );
}
