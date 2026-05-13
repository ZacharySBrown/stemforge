/**
 * Thin TanStack Query mutation wrappers for the spec §4.3 endpoint set.
 *
 * State is delivered via SSE, so these mutations:
 *   - fire-and-forget the POST/PATCH/DELETE,
 *   - surface success/error toasts (caller hooks in via toast config),
 *   - do NOT invalidate any cache; SSE is the source of truth for the
 *     active curation. The `forges` and `curations` index queries DO get
 *     invalidated on lifecycle mutations (created/deleted/renamed).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ApiResult } from "@/lib/popup-types";

interface IntentToastConfig {
  label: string;
  silentSuccess?: boolean;
}

function buildOptions(cfg: IntentToastConfig) {
  return {
    onSuccess: (resp: ApiResult) => {
      if (resp?.warnings?.length) {
        for (const w of resp.warnings) toast.warning(w);
      }
      if (!cfg.silentSuccess) {
        toast.success(`${cfg.label} ok`, {
          description: resp?.warnings?.length
            ? `${resp.warnings.length} warning${resp.warnings.length === 1 ? "" : "s"}`
            : undefined,
        });
      }
    },
    onError: (err: Error) => {
      toast.error(`${cfg.label} failed`, { description: err.message });
    },
  };
}

// ── Forge actions ──────────────────────────────────────────────────────────

export function useLoadForge() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, string>({
    mutationFn: (slug) => api.loadForge(slug),
    ...buildOptions({ label: "load forge" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["forges"] }),
  });
}

export function useUnloadForge() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, string>({
    mutationFn: (slug) => api.unloadForge(slug),
    ...buildOptions({ label: "unload forge" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["forges"] }),
  });
}

export function useReAnchorForge() {
  return useMutation<
    ApiResult,
    Error,
    { slug: string; downbeat_sec: number }
  >({
    mutationFn: ({ slug, downbeat_sec }) =>
      api.reAnchorForge(slug, { downbeat_sec }),
    ...buildOptions({ label: "re-anchor" }),
  });
}

export function useReCurateForge() {
  return useMutation<
    ApiResult,
    Error,
    { slug: string; params?: Record<string, unknown> }
  >({
    mutationFn: ({ slug, params }) => api.reCurateForge(slug, { params }),
    ...buildOptions({ label: "re-curate" }),
  });
}

export function useShowForgeInFinder() {
  return useMutation<ApiResult, Error, string>({
    mutationFn: (slug) => api.showForgeInFinder(slug),
    ...buildOptions({ label: "reveal in finder", silentSuccess: true }),
  });
}

// ── Curation lifecycle ─────────────────────────────────────────────────────

export function useOpenCuration() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, string>({
    mutationFn: (name) => api.openCuration(name),
    ...buildOptions({ label: "open curation" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["curations"] }),
  });
}

export function useSaveAsCuration() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, { name: string; new_name: string }>({
    mutationFn: ({ name, new_name }) =>
      api.saveCurationAs(name, { new_name }),
    ...buildOptions({ label: "save as" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["curations"] }),
  });
}

export function useRenameCuration() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, { name: string; new_name: string }>({
    mutationFn: ({ name, new_name }) =>
      api.renameCuration(name, { new_name }),
    ...buildOptions({ label: "rename" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["curations"] }),
  });
}

export function useDeleteCuration() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, string>({
    mutationFn: (name) => api.deleteCuration(name),
    ...buildOptions({ label: "delete" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["curations"] }),
  });
}

export function useDuplicateCuration() {
  // Duplicate = save-as with a server-suggested name. Lane 1B can implement
  // this as save-as under the hood — caller passes new_name.
  return useSaveAsCuration();
}

export function useCloseCuration() {
  const qc = useQueryClient();
  return useMutation<ApiResult, Error, void>({
    mutationFn: () => api.closeActiveCuration(),
    ...buildOptions({ label: "close" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["curations"] }),
  });
}

// ── Curation edits ────────────────────────────────────────────────────────

export function useSetGroupTemplate() {
  return useMutation<
    ApiResult,
    Error,
    { name: string; group: string; template_name: string | null }
  >({
    mutationFn: ({ name, group, template_name }) =>
      api.patchCurationTemplate(name, { group, template_name }),
    ...buildOptions({ label: "template", silentSuccess: true }),
  });
}

export function useSetGroupLabel() {
  return useMutation<
    ApiResult,
    Error,
    { name: string; group: string; label: string }
  >({
    mutationFn: ({ name, group, label }) =>
      api.patchCurationTarget(name, { label: { group, label } }),
    ...buildOptions({ label: "label", silentSuccess: true }),
  });
}

// ── Bounce / export ──────────────────────────────────────────────────────

export function useTriggerBounce() {
  return useMutation<ApiResult, Error, string>({
    mutationFn: (name) => api.triggerBounce(name),
    ...buildOptions({ label: "trigger bounce" }),
  });
}

export function useExportCuration() {
  return useMutation<
    ApiResult,
    Error,
    { name: string; out_path: string; target_format?: "ppak" }
  >({
    mutationFn: ({ name, out_path, target_format }) =>
      api.exportCuration(name, { out_path, target_format }),
    ...buildOptions({ label: "export" }),
  });
}

export function usePickManifest() {
  return useMutation<ApiResult, Error, void>({
    mutationFn: () => api.pickManifest(),
    ...buildOptions({ label: "load manifest" }),
  });
}
