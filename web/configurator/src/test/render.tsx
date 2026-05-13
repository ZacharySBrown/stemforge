/**
 * Test render helper — wraps components in the providers main.tsx mounts:
 * QueryClient, TooltipProvider, Toaster (passive in tests).
 */

import type { ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

export function buildClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 0, gcTime: 0, staleTime: 0 },
      mutations: { retry: 0 },
    },
  });
}

export function renderWithProviders(
  ui: ReactNode,
  opts: { client?: QueryClient } & Omit<RenderOptions, "wrapper"> = {},
) {
  const { client = buildClient(), ...rest } = opts;
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={0}>{children}</TooltipProvider>
    </QueryClientProvider>
  );
  return { client, ...render(ui, { wrapper: Wrapper, ...rest }) };
}
