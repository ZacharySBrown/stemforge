import { AnimatePresence, motion } from "framer-motion";
import { Mic2, Drum, Sparkles, Waves } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  FormatProfile,
  GroupKey,
  GroupSpec,
  PadSpec,
  ProjectSpec,
  SceneSpec,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface PadCanvasProps {
  state: ProjectSpec | null;
}

const GROUP_ORDER: GroupKey[] = ["A", "B", "C", "D"];

// Per VERSE_SWAP_DECK_PLAN.md: A/B = vocals, C = drums, D = texture/IDM.
const GROUP_META: Record<
  GroupKey,
  {
    label: string;
    role: string;
    icon: typeof Mic2;
    colorVar: string;
  }
> = {
  A: { label: "A", role: "vocals", icon: Mic2, colorVar: "--group-a" },
  B: { label: "B", role: "vocals (alt)", icon: Mic2, colorVar: "--group-b" },
  C: { label: "C", role: "drums", icon: Drum, colorVar: "--group-c" },
  D: { label: "D", role: "texture / idm", icon: Sparkles, colorVar: "--group-d" },
};

const FORMAT_LABEL: Record<FormatProfile, string> = {
  vocal: "vocal",
  drum: "drum",
  texture: "texture",
  preserve_source: "preserve",
};

function pickScene(state: ProjectSpec | null): SceneSpec | null {
  return state?.songs?.[0]?.scenes?.[0] ?? null;
}

function findGroup(scene: SceneSpec | null, key: GroupKey): GroupSpec | null {
  return scene?.groups?.find((g) => g.group === key) ?? null;
}

function findPad(group: GroupSpec | null, pad: number): PadSpec | null {
  return group?.pads?.find((p) => p.pad === pad) ?? null;
}

interface PadProps {
  group: GroupKey;
  pad: number;
  data: PadSpec | null;
}

function Pad({ group, pad, data }: PadProps) {
  const filled = !!data?.clip_id;
  const colorVar = GROUP_META[group].colorVar;

  return (
    <Tooltip delayDuration={250}>
      <TooltipTrigger asChild>
        <motion.div
          layout
          className={cn(
            "group relative flex aspect-square select-none flex-col items-start justify-between overflow-hidden rounded-lg border p-2 transition-colors duration-150",
            "cursor-default", // Phase 4 will swap to drop-target cursor
            filled
              ? "border-[hsl(0_0%_100%/0.08)] bg-[hsl(var(--elevated))]"
              : "border-dashed border-[hsl(0_0%_100%/0.05)] bg-[hsl(0_0%_6%)]",
          )}
          style={{
            // a thin colored edge cue at the bottom — group identity at a
            // glance without dominating the cell.
            boxShadow: filled
              ? `inset 0 -2px 0 hsl(var(${colorVar}) / 0.65)`
              : `inset 0 -1px 0 hsl(var(${colorVar}) / 0.18)`,
          }}
          whileHover={{ y: -1 }}
          transition={{ type: "spring", stiffness: 320, damping: 24 }}
        >
          <div className="flex w-full items-center justify-between">
            <span className="text-[10px] font-mono uppercase text-muted-foreground/80 tabular">
              {group}
              <span className="text-muted-foreground/40">·</span>
              {String(pad).padStart(2, "0")}
            </span>
            {filled && (
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: `hsl(var(${colorVar}))` }}
              />
            )}
          </div>

          <AnimatePresence mode="wait" initial={false}>
            {filled ? (
              <motion.div
                key={data!.clip_id ?? "filled"}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="w-full"
              >
                <div className="truncate text-[11px] font-medium text-foreground">
                  {data!.name ?? data!.clip_id?.slice(0, 8) ?? "clip"}
                </div>
                {data!.mode && (
                  <div className="text-[9px] uppercase tracking-wider text-muted-foreground/70">
                    {data!.mode}
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.14 }}
                className="text-[10px] italic text-muted-foreground/40"
              >
                empty
              </motion.div>
            )}
          </AnimatePresence>

          {/* hover glow */}
          <div
            className="pointer-events-none absolute inset-0 rounded-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100"
            style={{
              background: `radial-gradient(180px 90px at 50% -10%, hsl(var(${colorVar}) / 0.08), transparent 70%)`,
            }}
          />
        </motion.div>
      </TooltipTrigger>
      <TooltipContent side="top">
        {filled ? (
          <div className="space-y-0.5">
            <div className="font-medium">
              {data!.name ?? data!.clip_id}
            </div>
            <div className="text-muted-foreground tabular">
              group {group} · pad {pad} · {data!.mode ?? "—"}
            </div>
          </div>
        ) : (
          <>
            group {group} · pad {pad} · empty
            <div className="text-muted-foreground/60">
              click to assign — phase 4
            </div>
          </>
        )}
      </TooltipContent>
    </Tooltip>
  );
}

interface GroupRowProps {
  group: GroupKey;
  spec: GroupSpec | null;
}

function GroupRow({ group, spec }: GroupRowProps) {
  const meta = GROUP_META[group];
  const Icon = meta.icon;
  const pads = Array.from({ length: 12 }, (_, i) => i + 1);
  const format = spec?.format_profile ?? "preserve_source";
  const filled = (spec?.pads ?? []).filter((p) => p.clip_id).length;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18 }}
      className="space-y-2"
    >
      <div className="flex items-center justify-between px-0.5">
        <div className="flex items-center gap-2.5">
          <div
            className="grid h-6 w-6 place-items-center rounded-md"
            style={{
              background: `hsl(var(${meta.colorVar}) / 0.18)`,
              color: `hsl(var(${meta.colorVar}))`,
            }}
          >
            <Icon className="h-3.5 w-3.5" strokeWidth={2.25} />
          </div>
          <div>
            <div className="text-[13px] font-semibold tracking-tightish">
              group {meta.label}
            </div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              {meta.role}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="muted">{FORMAT_LABEL[format]}</Badge>
          <Badge variant="outline" className="tabular">
            {filled}/12
          </Badge>
        </div>
      </div>
      <div className="grid grid-cols-12 gap-2">
        {pads.map((p) => (
          <Pad
            key={`${group}-${p}`}
            group={group}
            pad={p}
            data={findPad(spec, p)}
          />
        ))}
      </div>
    </motion.div>
  );
}

/**
 * PadCanvas — the main 4×12 grid (4 groups stacked, 12 pads each).
 *
 * Renders read-only Phase 3 state. Drag-to-assign is a Phase 4 deliverable.
 * Pads animate via Framer Motion AnimatePresence keyed on `clip_id` so a
 * server-pushed assignment fades in cleanly.
 */
export function PadCanvas({ state }: PadCanvasProps) {
  const scene = pickScene(state);
  const sceneName = scene?.name ?? "default";

  return (
    <section className="flex h-full min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            scene
          </div>
          <div className="text-2xl font-semibold tracking-tighter2">
            {sceneName}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="tabular">
            <Waves className="h-3 w-3" /> 4 groups
          </Badge>
          <Badge variant="outline" className="tabular">
            48 pads
          </Badge>
        </div>
      </div>

      <div className="flex flex-col gap-5">
        {GROUP_ORDER.map((g) => (
          <GroupRow key={g} group={g} spec={findGroup(scene, g)} />
        ))}
      </div>
    </section>
  );
}
