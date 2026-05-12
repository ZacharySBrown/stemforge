/**
 * Thin TanStack Query mutation wrappers per intent. State is delivered via
 * SSE, so these mutations:
 *   - fire-and-forget the POST,
 *   - surface success/error toasts (caller hooks in),
 *   - do NOT invalidate any cache; SSE is the source of truth.
 */

import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { intents } from "@/lib/api";
import type {
  AssignPadRequest,
  ClearPadRequest,
  ExportRequest,
  IntentResponse,
  LoadManifestRequest,
  SetGroupFormatRequest,
} from "@/lib/types";

interface IntentToastConfig {
  /** Short label, e.g. "commit", "export". */
  label: string;
  /** Suppress success toast (e.g. for ambient polls). */
  silentSuccess?: boolean;
}

function buildOptions(cfg: IntentToastConfig) {
  return {
    onSuccess: (resp: IntentResponse) => {
      if (resp.warnings.length) {
        for (const w of resp.warnings) toast.warning(w);
      }
      if (!cfg.silentSuccess) {
        toast.success(`${cfg.label} ok`, {
          description:
            resp.warnings.length > 0
              ? `${resp.warnings.length} warning${
                  resp.warnings.length === 1 ? "" : "s"
                }`
              : undefined,
        });
      }
    },
    onError: (err: Error) => {
      toast.error(`${cfg.label} failed`, {
        description: err.message,
      });
    },
  };
}

export function useLoadManifest() {
  return useMutation<IntentResponse, Error, LoadManifestRequest>({
    mutationFn: intents.loadManifest,
    ...buildOptions({ label: "load manifest" }),
  });
}

export function useCommit() {
  return useMutation<IntentResponse, Error, void>({
    mutationFn: () => intents.commit(),
    ...buildOptions({ label: "commit" }),
  });
}

export function useAssignPad() {
  return useMutation<IntentResponse, Error, AssignPadRequest>({
    mutationFn: intents.assignPad,
    ...buildOptions({ label: "assign pad", silentSuccess: true }),
  });
}

export function useClearPad() {
  return useMutation<IntentResponse, Error, ClearPadRequest>({
    mutationFn: intents.clearPad,
    ...buildOptions({ label: "clear pad", silentSuccess: true }),
  });
}

export function useSetGroupFormat() {
  return useMutation<IntentResponse, Error, SetGroupFormatRequest>({
    mutationFn: intents.setGroupFormat,
    ...buildOptions({ label: "format" }),
  });
}

export function useRecompute() {
  return useMutation<IntentResponse, Error, void>({
    mutationFn: () => intents.recompute(),
    ...buildOptions({ label: "recompute" }),
  });
}

export function useExport() {
  return useMutation<IntentResponse, Error, ExportRequest>({
    mutationFn: intents.export,
    ...buildOptions({ label: "export" }),
  });
}
