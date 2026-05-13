import { AnimatePresence, motion } from "framer-motion";
import { Activity, Clock3, Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { Curation } from "@/lib/api-types.generated";
import type { ProgressState } from "@/hooks/useProjectState";

interface StatusBarProps {
  curation: Curation | null;
  progress: ProgressState | null;
}

/**
 * StatusBar — footer.
 *
 * Three zones:
 *   left:   active curation summary (target + group count)
 *   middle: per-group template chips
 *   right:  active progress / idle
 */
export function StatusBar({ curation, progress }: StatusBarProps) {
  const groups = curation?.groups ?? {};
  const groupKeys = Object.keys(groups).sort();
  const filledTotal = groupKeys.reduce(
    (n, k) =>
      n + (groups[k].pads?.filter((p) => p.source != null).length ?? 0),
    0,
  );
  const padsTotal = groupKeys.reduce(
    (n, k) => n + (groups[k].pads?.length ?? 0),
    0,
  );

  return (
    <motion.footer
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut", delay: 0.06 }}
      className="glass relative flex h-12 shrink-0 items-center gap-6 px-4 text-[12px]"
      data-testid="status-bar"
    >
      <div className="flex min-w-[200px] items-center gap-2 text-muted-foreground">
        <Layers className="h-3.5 w-3.5" />
        {curation ? (
          <span className="tabular text-foreground">
            {curation.name}
            <span className="text-muted-foreground/70">
              {" "}
              · {filledTotal}/{padsTotal} pads filled
            </span>
          </span>
        ) : (
          <span>no curation active</span>
        )}
      </div>

      <div className="h-6 w-px bg-border" />

      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        {groupKeys.map((g) => (
          <div
            key={g}
            className="flex shrink-0 items-center gap-1.5 text-muted-foreground"
          >
            <span className="text-[10px] uppercase tracking-wider">{g}</span>
            <Badge variant="muted" className="!text-[10px] !py-0">
              {groups[g].template ?? "dry"}
            </Badge>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-4">
        <AnimatePresence mode="wait">
          {progress ? (
            <motion.div
              key="progress"
              initial={{ opacity: 0, x: 4 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -4 }}
              transition={{ duration: 0.16 }}
              className="flex items-center gap-2"
              data-testid="status-progress"
            >
              <Activity className="h-3.5 w-3.5 text-[hsl(var(--accent))]" />
              <div className="flex flex-col gap-1">
                <div className="text-foreground">
                  {progress.message ?? progress.operation}
                </div>
                <Progress value={progress.fraction} className="w-36" />
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-2 text-muted-foreground/60"
            >
              <Clock3 className="h-3.5 w-3.5" />
              <span>idle</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.footer>
  );
}
