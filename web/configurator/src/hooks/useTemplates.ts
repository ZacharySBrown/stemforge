/**
 * useTemplates — TanStack Query wrapper for `GET /templates` (Phase 3A).
 *
 * The template index is scan-driven on the server (walks
 * `~/stemforge/templates/*.adg`); the popup polls it on mount and after
 * any successful PATCH to a template assignment so the dropdown reflects
 * newly saved racks.
 *
 * The `staleTime` is a touch tighter than `useForges` because users
 * typically save a new device group in Live and then expect the popup to
 * see it without a full refresh.
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TemplateIndexResponse } from "@/lib/popup-types";

export function useTemplates() {
  return useQuery<TemplateIndexResponse, Error>({
    queryKey: ["templates"],
    queryFn: () => api.fetchTemplates(),
    staleTime: 5_000,
  });
}
