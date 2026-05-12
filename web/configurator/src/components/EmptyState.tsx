import { motion } from "framer-motion";
import { FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  onLoad?: () => void;
}

/**
 * Friendly empty-state used by the popup before any project is loaded.
 *
 * Centered icon + two-line copy + outline CTA. Microcopy is lower-case,
 * technical, matches the tone set by the rest of the device strip.
 */
export function EmptyState({ onLoad }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className="flex h-full items-center justify-center p-8"
    >
      <div className="max-w-md space-y-5 text-center">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-xl bg-accent-muted text-[hsl(var(--accent))]">
          <FolderOpen className="h-6 w-6" strokeWidth={2} />
        </div>
        <div className="space-y-1.5">
          <div className="text-xl font-semibold tracking-tighter2 text-foreground">
            no project loaded
          </div>
          <div className="text-[13px] leading-relaxed text-muted-foreground">
            load a manifest from the strip device or click below to browse.
            once loaded, the pad canvas will populate from server state.
          </div>
        </div>
        {onLoad && (
          <div className="pt-1">
            <Button variant="outline" onClick={onLoad} size="sm">
              <FolderOpen className="h-4 w-4" />
              load manifest…
            </Button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
