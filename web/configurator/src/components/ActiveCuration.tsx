import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Download,
  FileMusic,
  Layers,
  Play,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useExportCuration,
  useSetGroupLabel,
  useSetGroupTemplate,
  useTriggerBounce,
} from "@/hooks/useIntent";
import { useForges } from "@/hooks/useForges";
import type {
  Curation,
  Group as CurationGroup,
  Pad,
} from "@/lib/api-types.generated";
import { isForgeStale } from "@/lib/popup-types";
import { cn } from "@/lib/utils";

interface ActiveCurationProps {
  curation: Curation | null;
}

// Common per-group templates surfaced as a dropdown. The server is the
// authority but we don't have a /templates endpoint in spec §4.3 yet; we
// fall back to a known-good shortlist plus a free-text "custom" option
// when Lane 1B publishes one.
const COMMON_TEMPLATES: string[] = [
  "VOCAL_LO_KEY",
  "VOCAL_HI_KEY",
  "DRUM_PUNCH",
  "DRUM_ONESHOT",
  "TEXTURE_BLOOM",
  "TEXTURE_GRAIN",
  "BASS_TIGHT",
];

interface PadCellProps {
  group: string;
  pad: Pad;
  forgeStaleSet: Set<string>;
}

function PadCell({ group, pad, forgeStaleSet }: PadCellProps) {
  const filled = !!pad.source;
  const forgeSlug = pad.source?.forge;
  const stale = forgeSlug != null && forgeStaleSet.has(forgeSlug);

  return (
    <Tooltip delayDuration={250}>
      <TooltipTrigger asChild>
        <motion.div
          layout
          className={cn(
            "group relative flex aspect-square select-none flex-col items-start justify-between overflow-hidden rounded-lg border p-1.5",
            "transition-colors duration-150",
            filled
              ? "border-[hsl(0_0%_100%/0.08)] bg-[hsl(var(--elevated))]"
              : "border-dashed border-[hsl(0_0%_100%/0.05)] bg-[hsl(0_0%_6%)]",
            stale && "ring-1 ring-[hsl(var(--warning)/0.45)]",
          )}
          data-testid="pad-cell"
          data-pad-id={pad.pad_id}
        >
          <div className="flex w-full items-center justify-between">
            <span className="text-[9px] font-mono uppercase text-muted-foreground/80 tabular">
              {pad.pad_id}
            </span>
            {filled ? (
              <CheckCircle2 className="h-2.5 w-2.5 text-[hsl(var(--success))]" />
            ) : (
              <Circle className="h-2.5 w-2.5 text-muted-foreground/30" />
            )}
          </div>
          <AnimatePresence initial={false}>
            {filled ? (
              <motion.div
                key={pad.source!.clip_id}
                initial={{ opacity: 0, y: 2 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="w-full overflow-hidden"
              >
                <div className="truncate text-[10px] font-medium text-foreground">
                  {pad.source!.clip_id}
                </div>
                <div className="truncate text-[8px] text-muted-foreground/80">
                  {pad.source!.forge}
                </div>
              </motion.div>
            ) : (
              <span className="text-[9px] italic text-muted-foreground/40">
                empty
              </span>
            )}
          </AnimatePresence>
          {stale && (
            <span
              data-testid="stale-badge-pad"
              className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-[hsl(var(--warning))]"
            />
          )}
        </motion.div>
      </TooltipTrigger>
      <TooltipContent side="top">
        {filled ? (
          <div className="space-y-0.5">
            <div className="font-medium">{pad.source!.clip_id}</div>
            <div className="text-muted-foreground tabular">
              {group} · {pad.pad_id} · {pad.source!.forge}
            </div>
            {stale && (
              <div className="text-[hsl(var(--warning))]">
                forge has changed since this pad was committed
              </div>
            )}
          </div>
        ) : (
          <>
            {group} · {pad.pad_id} · empty
          </>
        )}
      </TooltipContent>
    </Tooltip>
  );
}

interface GroupBlockProps {
  curationName: string;
  groupKey: string;
  group: CurationGroup;
  forgeStaleSet: Set<string>;
}

function GroupBlock({
  curationName,
  groupKey,
  group,
  forgeStaleSet,
}: GroupBlockProps) {
  const setTemplate = useSetGroupTemplate();
  const setLabel = useSetGroupLabel();

  const [labelDraft, setLabelDraft] = useState<string>(group.label ?? "");
  useEffect(() => {
    setLabelDraft(group.label ?? "");
  }, [group.label]);

  const filled = (group.pads ?? []).filter((p) => p.source).length;
  const padsPerGroup = group.pads?.length ?? 12;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18 }}
      className="space-y-2"
      data-testid="active-curation-group"
      data-group-key={groupKey}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="grid h-6 w-6 place-items-center rounded-md bg-accent-muted text-[hsl(var(--accent))]">
            <span className="text-[10px] font-mono">{groupKey}</span>
          </div>
          <input
            type="text"
            value={labelDraft}
            onChange={(e) => setLabelDraft(e.target.value)}
            onBlur={() => {
              if (labelDraft !== (group.label ?? "")) {
                setLabel.mutate({
                  name: curationName,
                  group: groupKey,
                  label: labelDraft,
                });
              }
            }}
            placeholder={`group ${groupKey} label`}
            aria-label={`Label for group ${groupKey}`}
            data-testid={`group-${groupKey}-label`}
            className="min-w-0 flex-1 bg-transparent text-[12px] font-semibold tracking-tightish text-foreground outline-none placeholder:text-muted-foreground/40 focus-visible:ring-1 focus-visible:ring-[hsl(var(--accent)/0.4)] rounded px-1"
          />
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="tabular !text-[10px]">
            {filled}/{padsPerGroup}
          </Badge>
          <select
            value={group.template ?? ""}
            onChange={(e) =>
              setTemplate.mutate({
                name: curationName,
                group: groupKey,
                template_name: e.target.value || null,
              })
            }
            aria-label={`Template for group ${groupKey}`}
            data-testid={`group-${groupKey}-template`}
            className="rounded-md border border-border bg-elevated px-2 py-1 text-[11px] text-foreground outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--accent)/0.4)]"
          >
            <option value="">— no template (dry) —</option>
            {COMMON_TEMPLATES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
            {group.template && !COMMON_TEMPLATES.includes(group.template) && (
              <option value={group.template}>{group.template}</option>
            )}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-12 gap-1.5">
        {(group.pads ?? []).map((p) => (
          <PadCell
            key={p.pad_id}
            group={groupKey}
            pad={p}
            forgeStaleSet={forgeStaleSet}
          />
        ))}
      </div>
    </motion.div>
  );
}

function ActiveCurationEmpty() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
      className="flex h-full items-center justify-center p-8"
      data-testid="active-curation-empty"
    >
      <div className="max-w-md space-y-4 text-center">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-xl bg-accent-muted text-[hsl(var(--accent))]">
          <FileMusic className="h-6 w-6" strokeWidth={2} />
        </div>
        <div className="space-y-1.5">
          <div className="text-xl font-semibold tracking-tighter2 text-foreground">
            no active curation
          </div>
          <div className="text-[13px] leading-relaxed text-muted-foreground">
            open a curation from the right rail, or create a new one. the
            popup is read-only — pad assignment happens in Live.
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/**
 * ActiveCuration — center panel.
 *
 * Read-only grid of `curated_layout` for the active curation. Per-group:
 * template selector (`PATCH /curations/{name}/template`) and editable
 * label field (`PATCH /curations/{name}/target` with label payload).
 * Bottom toolbar: BOUNCE / EXPORT triggers.
 */
export function ActiveCuration({ curation }: ActiveCurationProps) {
  const forges = useForges();
  const triggerBounce = useTriggerBounce();
  const exportCuration = useExportCuration();

  const forgeStaleSet = useMemo(() => {
    if (!curation || !forges.data) return new Set<string>();
    const out = new Set<string>();
    for (const f of forges.data.forges) {
      if (isForgeStale(curation.referenced_forges, f)) out.add(f.slug);
    }
    return out;
  }, [curation, forges.data]);

  if (!curation) return <ActiveCurationEmpty />;

  const groups = curation.groups ?? {};
  const groupKeys = Object.keys(groups).sort();
  const hasBounce = !!curation.last_bounce;
  const hasExport = !!curation.last_export;

  return (
    <section
      className="flex h-full min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 py-4"
      data-testid="active-curation"
    >
      <header className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            active curation
          </div>
          <div className="truncate text-2xl font-semibold tracking-tighter2 text-foreground">
            {curation.name}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="muted">
            <Layers className="h-3 w-3" />
            {groupKeys.length} groups
          </Badge>
          {curation.target?.device && (
            <Badge variant="outline" className="uppercase">
              {curation.target.device}
            </Badge>
          )}
        </div>
      </header>

      <div className="flex flex-col gap-5">
        {groupKeys.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border/60 p-6 text-center text-[12px] text-muted-foreground">
            curation has no groups yet — open it from the right rail or
            edit the target to materialize staging tracks
          </div>
        ) : (
          groupKeys.map((g) => (
            <GroupBlock
              key={g}
              curationName={curation.name}
              groupKey={g}
              group={groups[g]}
              forgeStaleSet={forgeStaleSet}
            />
          ))
        )}
      </div>

      <div className="mt-auto flex items-center justify-between gap-3 border-t border-border/40 pt-3">
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground tabular">
          <span className={cn(hasBounce && "text-foreground")}>
            {hasBounce
              ? `bounced ${new Date(curation.last_bounce!.bounced_at).toLocaleString()}`
              : "not bounced"}
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span className={cn(hasExport && "text-foreground")}>
            {hasExport
              ? `exported ${new Date(curation.last_export!.exported_at).toLocaleString()}`
              : "not exported"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => triggerBounce.mutate(curation.name)}
            disabled={triggerBounce.isPending}
            data-testid="trigger-bounce"
          >
            <Play className="h-3.5 w-3.5" />
            bounce in live
          </Button>
          <Button
            size="sm"
            variant="default"
            onClick={() => {
              const out =
                window.prompt(
                  "output .ppak path",
                  `~/Desktop/${curation.name}.ppak`,
                ) ?? "";
              if (out) {
                exportCuration.mutate({
                  name: curation.name,
                  out_path: out,
                  target_format: "ppak",
                });
              }
            }}
            disabled={!hasBounce || exportCuration.isPending}
            data-testid="export-curation"
          >
            <Download className="h-3.5 w-3.5" />
            export .ppak…
          </Button>
        </div>
      </div>
    </section>
  );
}
