import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Download,
  FileMusic,
  Layers,
  Loader2,
  Play,
  RefreshCw,
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
  usePickSavePath,
  useRefreshCuration,
  useSetGroupLabel,
  useSetGroupTemplate,
  useTriggerBounce,
} from "@/hooks/useIntent";
import { useForges } from "@/hooks/useForges";
import { useTemplates } from "@/hooks/useTemplates";
import type {
  Curation,
  Group as CurationGroup,
  Pad,
} from "@/lib/api-types.generated";
import { isForgeStale } from "@/lib/popup-types";
import type { TemplateIndexEntry } from "@/lib/popup-types";
import { cn } from "@/lib/utils";

interface ActiveCurationProps {
  curation: Curation | null;
}

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
  templates: TemplateIndexEntry[];
  templatesLoading: boolean;
}

function GroupBlock({
  curationName,
  groupKey,
  group,
  forgeStaleSet,
  templates,
  templatesLoading,
}: GroupBlockProps) {
  const setTemplate = useSetGroupTemplate();
  const setLabel = useSetGroupLabel();

  const [labelDraft, setLabelDraft] = useState<string>(group.label ?? "");
  useEffect(() => {
    setLabelDraft(group.label ?? "");
  }, [group.label]);

  // Phase 3A: optimistic pending state — selecting a template flips the
  // local pending flag and reverts on mutation error so the dropdown
  // doesn't lie about the persisted state.
  const [pendingTemplate, setPendingTemplate] = useState<string | null | "">("");
  const effectiveValue =
    pendingTemplate === ""
      ? (group.template ?? "")
      : (pendingTemplate ?? "");

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
            value={effectiveValue}
            disabled={setTemplate.isPending || templatesLoading}
            onChange={(e) => {
              const next = e.target.value || null;
              setPendingTemplate(next);
              setTemplate.mutate(
                {
                  name: curationName,
                  group: groupKey,
                  template_name: next,
                },
                {
                  onSettled: (_data, error) => {
                    if (error) {
                      // Server rejected — drop optimistic state so the
                      // dropdown re-renders the persisted value.
                      setPendingTemplate("");
                    } else {
                      // Success: let the next /curations fetch hydrate
                      // the real value; clear pending so we don't pin
                      // the stale optimistic.
                      setPendingTemplate("");
                    }
                  },
                },
              );
            }}
            aria-label={`Template for group ${groupKey}`}
            data-testid={`group-${groupKey}-template`}
            className="rounded-md border border-border bg-elevated px-2 py-1 text-[11px] text-foreground outline-none focus-visible:ring-1 focus-visible:ring-[hsl(var(--accent)/0.4)] disabled:opacity-60"
          >
            <option value="">— no template (dry) —</option>
            {templates.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
            {/* Surface a previously-saved template even if the server
                no longer lists it (e.g. .adg was renamed on disk) so
                the user sees what's actually persisted. */}
            {group.template &&
              !templates.some((t) => t.name === group.template) && (
                <option value={group.template}>{group.template} (missing)</option>
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
  const templates = useTemplates();
  const triggerBounce = useTriggerBounce();
  const exportCuration = useExportCuration();
  const pickSavePath = usePickSavePath();
  const refreshCuration = useRefreshCuration();

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
  const hasStaleForge = forgeStaleSet.size > 0;

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
          {hasStaleForge && (
            <Tooltip delayDuration={200}>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => refreshCuration.mutate(curation.name)}
                  disabled={refreshCuration.isPending}
                  data-testid="active-curation-refresh"
                >
                  {refreshCuration.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  refresh from forge
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                re-derive pad refs against the current forge manifests
              </TooltipContent>
            </Tooltip>
          )}
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
              templates={templates.data?.templates ?? []}
              templatesLoading={templates.isLoading}
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
            onClick={async () => {
              // Step 1: ask the server for a native save dialog. The
              // popup runs inside Live's [jweb] host without filesystem
              // access, so the dialog lives server-side (osascript).
              const pick = await pickSavePath
                .mutateAsync({
                  default_name: `${curation.name}.ppak`,
                  prompt: `Export ${curation.name}`,
                })
                .catch(() => null);
              if (!pick || !pick.path) return;
              // Step 2: fire the export with whatever path the user picked.
              exportCuration.mutate({
                name: curation.name,
                out_path: pick.path,
                target_format: "ppak",
              });
            }}
            disabled={exportCuration.isPending || pickSavePath.isPending}
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
