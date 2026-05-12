import { motion } from "framer-motion";
import {
  FolderOpen,
  GitCommitHorizontal,
  RefreshCw,
  Package,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useCommit,
  useExport,
  useLoadManifest,
  useRecompute,
} from "@/hooks/useIntent";
import type { ProjectSpec } from "@/lib/types";
import { cn } from "@/lib/utils";

interface LeftRailProps {
  state: ProjectSpec | null;
}

interface OpButtonProps {
  icon: typeof FolderOpen;
  label: string;
  hint: string;
  loading: boolean;
  onClick: () => void;
  disabled?: boolean;
  accent?: boolean;
}

function OpButton({
  icon: Icon,
  label,
  hint,
  loading,
  onClick,
  disabled,
  accent,
}: OpButtonProps) {
  return (
    <Tooltip delayDuration={250}>
      <TooltipTrigger asChild>
        <Button
          variant={accent ? "default" : "secondary"}
          onClick={onClick}
          disabled={disabled || loading}
          className={cn(
            "w-full justify-start gap-2.5 text-[13px]",
            accent ? "" : "hover:!border-[hsl(var(--accent)/0.4)]",
          )}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Icon className="h-4 w-4" />
          )}
          <span className="truncate">{label}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent side="right">{hint}</TooltipContent>
    </Tooltip>
  );
}

/**
 * LeftRail — 240px-wide sidebar with the canonical ops surface for Phase 3.
 *
 * Each button is an `intent/*` mutation. The buttons are disabled when no
 * project is loaded except for `Load manifest`, which is always usable.
 */
export function LeftRail({ state }: LeftRailProps) {
  const loadManifest = useLoadManifest();
  const commit = useCommit();
  const recompute = useRecompute();
  const exportIntent = useExport();

  const hasProject = state != null;

  return (
    <motion.aside
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, ease: "easeOut", delay: 0.04 }}
      className="glass relative flex w-60 shrink-0 flex-col gap-2 p-3"
    >
      <div className="px-1 pb-1 pt-0.5">
        <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          operations
        </div>
      </div>

      <OpButton
        icon={FolderOpen}
        label="Load manifest"
        hint="POST /intent/load-manifest — pick a stems.json"
        loading={loadManifest.isPending}
        onClick={() => {
          // Phase 3 placeholder — Lane C will open a [shell] file picker.
          // For now we fire with a dev-only placeholder path that the server
          // will reject cleanly. This is the wiring proof.
          loadManifest.mutate({
            manifest_path: window.prompt(
              "manifest path",
              "/path/to/curated/manifest.json",
            ) ?? "",
          });
        }}
        accent
      />

      <Separator className="my-1" />

      <OpButton
        icon={GitCommitHorizontal}
        label="Commit"
        hint="POST /intent/commit — snapshot current session+arrangement state"
        loading={commit.isPending}
        onClick={() => commit.mutate()}
        disabled={!hasProject}
      />

      <OpButton
        icon={RefreshCw}
        label="Recompute"
        hint="POST /intent/recompute — re-run slot reconciliation"
        loading={recompute.isPending}
        onClick={() => recompute.mutate()}
        disabled={!hasProject}
      />

      <Separator className="my-1" />

      <OpButton
        icon={Package}
        label="Export"
        hint="POST /intent/export — render .ppak to disk"
        loading={exportIntent.isPending}
        onClick={() =>
          exportIntent.mutate({
            target: "ep133",
            out_path:
              window.prompt(
                "output .ppak path",
                "~/Desktop/stemforge_export.ppak",
              ) ?? "",
          })
        }
        disabled={!hasProject}
      />

      <div className="mt-auto px-1 pt-2 text-[10px] leading-relaxed text-muted-foreground/70">
        phase 3 plumbing · pad assignment lands in phase 4
      </div>
    </motion.aside>
  );
}
