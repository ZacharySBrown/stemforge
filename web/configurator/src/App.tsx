import { motion } from "framer-motion";
import { useEffect } from "react";
import { toast } from "sonner";
import { ActiveCuration } from "@/components/ActiveCuration";
import { CurationList } from "@/components/CurationList";
import { ForgeList } from "@/components/ForgeList";
import { StatusBar } from "@/components/StatusBar";
import { TopBar } from "@/components/TopBar";
import { useProjectState } from "@/hooks/useProjectState";

/**
 * App — three-panel popup layout per spec §3.2.
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │ TopBar — active curation · save/save-as/close · pop-out · status │
 *   ├──────────┬────────────────────────────────────────┬──────────────┤
 *   │ ForgeList│         ActiveCuration                 │ CurationList │
 *   │  (left)  │  (center — read-only pad grid)         │   (right)    │
 *   ├──────────┴────────────────────────────────────────┴──────────────┤
 *   │ StatusBar — curation summary · group templates · progress        │
 *   └──────────────────────────────────────────────────────────────────┘
 *
 * State flows from the SSE stream (`useProjectState`). Logs surface as
 * toasts via sonner.
 */
export function App() {
  const { curation, activeCurationName, status, error, progress, logs, clearLog } =
    useProjectState();

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

  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="flex h-screen w-screen flex-col overflow-hidden"
    >
      <TopBar
        curation={curation}
        activeCurationName={activeCurationName}
        status={status}
        error={error}
      />
      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <ForgeList curation={curation} />
        <main className="glass relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg">
          <ActiveCuration curation={curation} />
        </main>
        <CurationList activeCurationName={activeCurationName} />
      </div>
      <StatusBar curation={curation} progress={progress} />
    </motion.div>
  );
}
