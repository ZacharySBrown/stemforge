import { motion } from "framer-motion";
import { Disc3, Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ConnectionStatus } from "./ConnectionStatus";
import type { ConnectionStatus as ConnStatus, ProjectSpec } from "@/lib/types";

interface TopBarProps {
  state: ProjectSpec | null;
  status: ConnStatus;
  error: string | null;
}

/**
 * TopBar — 56px-tall sticky header.
 *
 * Composition:
 *   [brand]  ·  [project name / placeholder]  ·  [target chip]   |   [conn]
 *
 * Microcopy follows the terse-technical tone — e.g.
 *   "loaded breaks-n-beats1 manifest · 46 clips"
 */
export function TopBar({ state, status, error }: TopBarProps) {
  const projectName = state?.project_name?.trim() || null;
  const clipCount = state?.clip_count ?? null;
  const manifest = state?.manifest_path
    ? state.manifest_path.split("/").slice(-2).join("/")
    : null;
  const target = state?.target ?? "ep133";

  return (
    <motion.header
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="glass sticky top-0 z-20 flex h-14 items-center gap-4 px-4"
    >
      <div className="flex items-center gap-2.5">
        <div className="grid h-7 w-7 place-items-center rounded-md bg-accent-muted text-[hsl(var(--accent))]">
          <Disc3 className="h-4 w-4" strokeWidth={2.25} />
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold tracking-tighter2">
            StemForge
          </div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            configurator
          </div>
        </div>
      </div>

      <Separator orientation="vertical" className="h-7" />

      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Layers className="h-4 w-4 shrink-0 text-muted-foreground" />
        {projectName ? (
          <div className="flex min-w-0 flex-col">
            <div className="truncate text-[15px] font-semibold tracking-tighter2 text-foreground">
              {projectName}
            </div>
            <div className="truncate text-[11px] text-muted-foreground tabular">
              {manifest ? `loaded ${manifest}` : "loaded"}
              {clipCount != null && ` · ${clipCount} clip${clipCount === 1 ? "" : "s"}`}
            </div>
          </div>
        ) : (
          <div className="text-[13px] font-medium text-muted-foreground">
            no project loaded
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <Badge variant="default" className="uppercase">
          {target}
        </Badge>
        <Separator orientation="vertical" className="h-6" />
        <ConnectionStatus status={status} error={error} />
      </div>
    </motion.header>
  );
}
