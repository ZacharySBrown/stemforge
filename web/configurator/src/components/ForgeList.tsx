import { motion } from "framer-motion";
import {
  Anchor,
  Eye,
  FolderInput,
  FolderOpen,
  Hammer,
  Loader2,
  Plus,
  PowerOff,
  RefreshCw,
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
  useLoadForge,
  usePickManifest,
  useReAnchorForge,
  useReCurateForge,
  useShowForgeInFinder,
  useUnloadForge,
} from "@/hooks/useIntent";
import { useForges } from "@/hooks/useForges";
import type { Curation } from "@/lib/api-types.generated";
import type { ForgeIndexEntry } from "@/lib/popup-types";
import { isForgeStale } from "@/lib/popup-types";
import { cn } from "@/lib/utils";

interface ForgeListProps {
  /** Active curation, used for stale-reference detection. */
  curation: Curation | null;
}

interface ForgeRowProps {
  forge: ForgeIndexEntry;
  stale: boolean;
}

function StaleBadge() {
  return (
    <Tooltip delayDuration={200}>
      <TooltipTrigger asChild>
        <Badge
          variant="warning"
          className="!text-[9px] !px-1.5 !py-0"
          data-testid="stale-badge"
        >
          stale
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="top">
        forge has been re-anchored or re-curated since this curation last
        referenced it
      </TooltipContent>
    </Tooltip>
  );
}

function ForgeRow({ forge, stale }: ForgeRowProps) {
  const load = useLoadForge();
  const unload = useUnloadForge();
  const reAnchor = useReAnchorForge();
  const reCurate = useReCurateForge();
  const reveal = useShowForgeInFinder();

  const busy =
    load.isPending ||
    unload.isPending ||
    reAnchor.isPending ||
    reCurate.isPending;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.16 }}
      className={cn(
        "group rounded-lg border border-border bg-elevated/40 p-2.5",
        "hover:border-[hsl(0_0%_22%)] transition-colors",
      )}
      data-testid="forge-row"
      data-forge-slug={forge.slug}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Hammer className="h-3 w-3 shrink-0 text-muted-foreground" />
            <div className="truncate text-[12px] font-semibold tracking-tightish text-foreground">
              {forge.name ?? forge.slug}
            </div>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground tabular">
            {forge.bpm != null && <span>{forge.bpm.toFixed(1)} bpm</span>}
            {forge.clip_count != null && (
              <>
                <span className="text-muted-foreground/40">·</span>
                <span>{forge.clip_count} clips</span>
              </>
            )}
            {forge.chunk_count != null && forge.chunk_count > 0 && (
              <>
                <span className="text-muted-foreground/40">·</span>
                <span>{forge.chunk_count} chunks</span>
              </>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {forge.loaded && (
            <Badge variant="success" className="!text-[9px] !px-1.5 !py-0">
              loaded
            </Badge>
          )}
          {stale && <StaleBadge />}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-5 gap-1">
        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy || forge.loaded}
              onClick={() => load.mutate(forge.slug)}
              aria-label={`Load ${forge.slug}`}
            >
              {load.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FolderOpen className="h-3.5 w-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Load into Live</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy || !forge.loaded}
              onClick={() => unload.mutate(forge.slug)}
              aria-label={`Unload ${forge.slug}`}
            >
              {unload.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <PowerOff className="h-3.5 w-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Unload from Live</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy}
              onClick={() => {
                const raw = window.prompt(
                  "downbeat (sec)",
                  "0.0",
                );
                if (raw == null) return;
                const sec = Number(raw);
                if (Number.isFinite(sec)) {
                  reAnchor.mutate({ slug: forge.slug, downbeat_sec: sec });
                }
              }}
              aria-label={`Re-anchor ${forge.slug}`}
            >
              {reAnchor.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Anchor className="h-3.5 w-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Re-anchor</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              disabled={busy}
              onClick={() => reCurate.mutate({ slug: forge.slug })}
              aria-label={`Re-curate ${forge.slug}`}
            >
              {reCurate.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Re-curate</TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="!h-7 !w-full"
              onClick={() => reveal.mutate(forge.slug)}
              aria-label={`Show ${forge.slug} in Finder`}
            >
              <Eye className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Show in Finder</TooltipContent>
        </Tooltip>
      </div>
    </motion.div>
  );
}

function ForgeListEmpty() {
  return (
    <div className="rounded-lg border border-dashed border-border/60 p-6 text-center">
      <FolderInput className="mx-auto h-5 w-5 text-muted-foreground/70" />
      <div className="mt-2 text-[12px] font-medium text-foreground">
        no forges yet
      </div>
      <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground/80">
        forge a track via the strip device — or click{" "}
        <span className="text-foreground/90">Add forge…</span> below to pick a
        manifest.
      </div>
    </div>
  );
}

function ForgeListSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-[88px] w-full rounded-lg" />
      ))}
    </div>
  );
}

/**
 * ForgeList — left rail.
 *
 * Scan-driven list of forges from `GET /forges`. Per-entry actions wire to
 * the spec §4.3 forge endpoints (`/forges/{slug}/load|unload|re-anchor|
 * re-curate|reveal`). Stale-reference badge surfaces when the active
 * curation references the forge at a different `manifest_hash`.
 */
export function ForgeList({ curation }: ForgeListProps) {
  const { data, isLoading, isError, error, refetch } = useForges();
  const pickManifest = usePickManifest();

  const forges = data?.forges ?? [];
  const refs = curation?.referenced_forges;

  return (
    <motion.aside
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, ease: "easeOut", delay: 0.04 }}
      className="glass relative flex w-72 shrink-0 flex-col gap-3 p-3"
      data-testid="forge-list"
    >
      <div className="flex items-center justify-between px-1 pb-0.5">
        <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          forges
        </div>
        {forges.length > 0 && (
          <Badge variant="muted" className="!text-[10px]">
            {forges.length}
          </Badge>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-0.5">
        {isLoading ? (
          <ForgeListSkeleton />
        ) : isError ? (
          <div
            className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-[12px] text-foreground"
            data-testid="forge-list-error"
            role="alert"
          >
            <div className="font-medium">failed to load forges</div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {error?.message ?? "unknown error"}
            </div>
            <Button
              size="sm"
              variant="outline"
              className="mt-2 w-full"
              onClick={() => refetch()}
              data-testid="forge-list-retry"
            >
              retry
            </Button>
          </div>
        ) : forges.length === 0 ? (
          <ForgeListEmpty />
        ) : (
          forges.map((f) => (
            <ForgeRow
              key={f.slug}
              forge={f}
              stale={isForgeStale(refs, f)}
            />
          ))
        )}
      </div>

      <Button
        size="sm"
        variant="outline"
        className="w-full"
        onClick={() => pickManifest.mutate()}
        disabled={pickManifest.isPending}
        data-testid="add-forge"
      >
        {pickManifest.isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Plus className="h-3.5 w-3.5" />
        )}
        add forge…
      </Button>
    </motion.aside>
  );
}
