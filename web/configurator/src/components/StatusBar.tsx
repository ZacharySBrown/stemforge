import { AnimatePresence, motion } from "framer-motion";
import { Cpu, Activity, Clock3 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { GroupKey, ProjectSpec, SceneSpec } from "@/lib/types";
import type { ProgressState } from "@/hooks/useProjectState";
import { formatElapsed, formatMB } from "@/lib/utils";

interface StatusBarProps {
  state: ProjectSpec | null;
  progress: ProgressState | null;
}

const EP133_CAP_BYTES = 64 * 1024 * 1024;
const GROUPS: GroupKey[] = ["A", "B", "C", "D"];

function firstScene(state: ProjectSpec | null): SceneSpec | null {
  return state?.songs?.[0]?.scenes?.[0] ?? null;
}

/**
 * StatusBar — 48px tall footer.
 *
 * Three zones:
 *   left:   memory usage / 64 MB with progress bar
 *   middle: per-group format chips (Decision 16)
 *   right:  last operation elapsed-time + live progress
 */
export function StatusBar({ state, progress }: StatusBarProps) {
  const usedBytes = state?.capacity?.used_bytes ?? 0;
  const capBytes = state?.capacity?.cap_bytes ?? EP133_CAP_BYTES;
  const memFraction = capBytes > 0 ? usedBytes / capBytes : 0;
  const memTone =
    memFraction >= 1
      ? "warning"
      : memFraction >= 0.9
        ? "warning"
        : "accent";
  const scene = firstScene(state);
  const lastOp = state?.last_operation ?? null;

  return (
    <motion.footer
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut", delay: 0.06 }}
      className="glass relative flex h-12 shrink-0 items-center gap-6 px-4 text-[12px]"
    >
      {/* Memory rollup */}
      <Tooltip delayDuration={200}>
        <TooltipTrigger asChild>
          <div className="flex min-w-[200px] items-center gap-3">
            <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
            <div className="flex flex-col gap-1">
              <div className="flex items-baseline gap-1.5 text-muted-foreground">
                <span className="tabular text-foreground">
                  {formatMB(usedBytes)}
                </span>
                <span className="text-muted-foreground/60">/</span>
                <span className="tabular">{formatMB(capBytes)} MB</span>
              </div>
              <Progress
                value={memFraction}
                tone={memTone}
                className="w-44"
              />
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top">
          ep-133 sample memory · 64 MB cap · per-group format determines
          downsample rate (decision 16)
        </TooltipContent>
      </Tooltip>

      <div className="h-6 w-px bg-border" />

      {/* Per-group format chips */}
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {GROUPS.map((g) => {
          const grp = scene?.groups?.find((x) => x.group === g);
          const fmt = grp?.format_profile ?? "preserve_source";
          return (
            <div
              key={g}
              className="flex items-center gap-1.5 text-muted-foreground"
            >
              <span className="text-[10px] uppercase tracking-wider">
                {g}
              </span>
              <Badge variant="muted" className="!text-[10px] !py-0">
                {fmt === "preserve_source" ? "preserve" : fmt}
              </Badge>
            </div>
          );
        })}
      </div>

      {/* Last operation + active progress */}
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
            >
              <Activity className="h-3.5 w-3.5 text-[hsl(var(--accent))]" />
              <div className="flex flex-col gap-1">
                <div className="text-foreground">
                  {progress.message ?? progress.operation}
                </div>
                <Progress value={progress.fraction} className="w-36" />
              </div>
            </motion.div>
          ) : lastOp ? (
            <motion.div
              key="last-op"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-2 text-muted-foreground"
            >
              <Clock3 className="h-3.5 w-3.5" />
              <span>
                <span className="text-foreground">{lastOp.name}</span>{" "}
                <span className="tabular">· {formatElapsed(lastOp.duration_ms)}</span>
              </span>
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
