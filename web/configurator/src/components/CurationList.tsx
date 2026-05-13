import { motion } from "framer-motion";
import {
  BookOpen,
  Copy,
  FolderPlus,
  Loader2,
  Pencil,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useDeleteCuration,
  useDuplicateCuration,
  useOpenCuration,
  useRenameCuration,
} from "@/hooks/useIntent";
import { useCurations } from "@/hooks/useCurations";
import type { CurationIndexEntry } from "@/lib/popup-types";
import { cn } from "@/lib/utils";

interface CurationListProps {
  activeCurationName: string | null;
}

interface CurationRowProps {
  entry: CurationIndexEntry;
  active: boolean;
}

function timeAgo(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const sec = Math.max(0, Math.round((now - then) / 1000));
    if (sec < 60) return `${sec}s ago`;
    const min = Math.round(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.round(hr / 24);
    return `${day}d ago`;
  } catch {
    return iso;
  }
}

function CurationRow({ entry, active }: CurationRowProps) {
  const open = useOpenCuration();
  const dupe = useDuplicateCuration();
  const rename = useRenameCuration();
  const del = useDeleteCuration();

  const busy = open.isPending || dupe.isPending || rename.isPending || del.isPending;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.16 }}
      className={cn(
        "group rounded-lg border p-2.5 transition-colors",
        active
          ? "border-[hsl(var(--accent)/0.55)] bg-accent-muted/30"
          : "border-border bg-elevated/40 hover:border-[hsl(0_0%_22%)]",
      )}
      data-testid="curation-row"
      data-curation-name={entry.name}
      data-active={active ? "true" : "false"}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-[12px] font-semibold tracking-tightish text-foreground">
              {entry.name}
            </div>
            {active && (
              <Badge
                variant="default"
                className="!text-[9px] !px-1.5 !py-0"
                data-testid="active-badge"
              >
                active
              </Badge>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground tabular">
            {entry.target_device && (
              <span className="uppercase">{entry.target_device}</span>
            )}
            {entry.target_groups && entry.target_pads_per_group && (
              <>
                <span className="text-muted-foreground/40">·</span>
                <span>
                  {entry.target_groups}×{entry.target_pads_per_group}
                </span>
              </>
            )}
            <span className="text-muted-foreground/40">·</span>
            <span>modified {timeAgo(entry.modified_at)}</span>
          </div>
          {(entry.last_bounced_at || entry.last_exported_at) && (
            <div className="mt-0.5 text-[10px] text-muted-foreground/70 tabular">
              {entry.last_bounced_at && (
                <span>bounced {timeAgo(entry.last_bounced_at)}</span>
              )}
              {entry.last_bounced_at && entry.last_exported_at && (
                <span className="text-muted-foreground/40"> · </span>
              )}
              {entry.last_exported_at && (
                <span>exported {timeAgo(entry.last_exported_at)}</span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-4 gap-1">
        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy || active}
              onClick={() => open.mutate(entry.name)}
              aria-label={`Open ${entry.name}`}
            >
              {open.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <BookOpen className="h-3.5 w-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Open as active</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy}
              onClick={() => {
                const newName = window.prompt(
                  "duplicate as",
                  `${entry.name}_copy`,
                );
                if (newName) {
                  dupe.mutate({ name: entry.name, new_name: newName });
                }
              }}
              aria-label={`Duplicate ${entry.name}`}
            >
              <Copy className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Duplicate</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy}
              onClick={() => {
                const newName = window.prompt("rename to", entry.name);
                if (newName && newName !== entry.name) {
                  rename.mutate({ name: entry.name, new_name: newName });
                }
              }}
              aria-label={`Rename ${entry.name}`}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Rename</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full hover:!text-[hsl(var(--destructive))]"
              disabled={busy || active}
              onClick={() => {
                if (
                  window.confirm(`delete curation "${entry.name}"?`)
                ) {
                  del.mutate(entry.name);
                }
              }}
              aria-label={`Delete ${entry.name}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            {active ? "cannot delete active" : "Delete"}
          </TooltipContent>
        </Tooltip>
      </div>
    </motion.div>
  );
}

function CurationListEmpty() {
  return (
    <div
      className="rounded-lg border border-dashed border-border/60 p-6 text-center"
      data-testid="curation-list-empty"
    >
      <FolderPlus className="mx-auto h-5 w-5 text-muted-foreground/70" />
      <div className="mt-2 text-[12px] font-medium text-foreground">
        no curations yet
      </div>
      <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground/80">
        commit on the device to create your first curation.
      </div>
    </div>
  );
}

function CurationListSkeleton() {
  return (
    <div className="space-y-2" data-testid="curation-list-skeleton">
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-[88px] w-full rounded-lg" />
      ))}
    </div>
  );
}

/**
 * CurationList — right rail.
 *
 * Lists every curation file under `~/stemforge/curations/` (via
 * `GET /curations`). Per-entry actions: Open / Duplicate / Rename / Delete
 * wired to spec §4.3 endpoints. The active curation is highlighted.
 */
export function CurationList({ activeCurationName }: CurationListProps) {
  const { data, isLoading, isError, error, refetch } = useCurations();

  const curations = data?.curations ?? [];

  return (
    <motion.aside
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, ease: "easeOut", delay: 0.04 }}
      className="glass relative flex w-72 shrink-0 flex-col gap-3 p-3"
      data-testid="curation-list"
    >
      <div className="flex items-center justify-between px-1 pb-0.5">
        <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          curations
        </div>
        {curations.length > 0 && (
          <Badge variant="muted" className="!text-[10px]">
            {curations.length}
          </Badge>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-0.5">
        {isLoading ? (
          <CurationListSkeleton />
        ) : isError ? (
          <div
            className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-[12px] text-foreground"
            data-testid="curation-list-error"
            role="alert"
          >
            <div className="font-medium">failed to load curations</div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {error?.message ?? "unknown error"}
            </div>
            <Button
              size="sm"
              variant="outline"
              className="mt-2 w-full"
              onClick={() => refetch()}
              data-testid="curation-list-retry"
            >
              retry
            </Button>
          </div>
        ) : curations.length === 0 ? (
          <CurationListEmpty />
        ) : (
          curations.map((c) => (
            <CurationRow
              key={c.name}
              entry={c}
              active={
                c.active === true ||
                (activeCurationName != null && activeCurationName === c.name)
              }
            />
          ))
        )}
      </div>
    </motion.aside>
  );
}
