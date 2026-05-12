import { motion } from "framer-motion";
import { useEffect } from "react";
import { toast } from "sonner";
import { TopBar } from "@/components/TopBar";
import { LeftRail } from "@/components/LeftRail";
import { PadCanvas } from "@/components/PadCanvas";
import { PadCanvasSkeleton } from "@/components/Skeletons";
import { StatusBar } from "@/components/StatusBar";
import { EmptyState } from "@/components/EmptyState";
import { useProjectState } from "@/hooks/useProjectState";

/**
 * App — top-level layout.
 *
 *   ┌──────────────────────────────────────────────┐
 *   │ TopBar                                       │
 *   ├──────────┬───────────────────────────────────┤
 *   │ LeftRail │ PadCanvas / Skeleton / EmptyState │
 *   │          │                                   │
 *   ├──────────┴───────────────────────────────────┤
 *   │ StatusBar                                    │
 *   └──────────────────────────────────────────────┘
 *
 * Mounts with a 200ms fade+slide-down. Logs from the SSE stream surface as
 * toasts via sonner.
 */
export function App() {
  const { state, status, error, progress, logs, clearLog } = useProjectState();

  // Drain log events into toasts.
  useEffect(() => {
    for (const log of logs) {
      const fn =
        log.level === "error"
          ? toast.error
          : log.level === "warn"
            ? toast.warning
            : toast.message;
      fn(log.message);
      clearLog(log.id);
    }
  }, [logs, clearLog]);

  const showSkeleton = status === "connecting" && !state;
  const showEmpty = (status === "connected" || status === "disconnected") && !state;

  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="flex h-screen w-screen flex-col overflow-hidden"
    >
      <TopBar state={state} status={status} error={error} />
      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <LeftRail state={state} />
        <main className="glass relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg">
          {showSkeleton ? (
            <PadCanvasSkeleton />
          ) : showEmpty ? (
            <EmptyState />
          ) : state ? (
            <PadCanvas state={state} />
          ) : (
            <PadCanvasSkeleton />
          )}
        </main>
      </div>
      <StatusBar state={state} progress={progress} />
    </motion.div>
  );
}
