/**
 * useProjectState — subscribes to the SSE event stream and exposes the
 * canonical Curation snapshot, connection status, last error, and active
 * progress.
 *
 * SSE pattern (the load-bearing detail from spec §6.5 and the 2026-05-13
 * debugging session):
 *   The server emits TYPED events of the form
 *
 *     event: state
 *     data: <json>
 *
 *     event: progress
 *     data: <json>
 *
 *   So the browser MUST subscribe via
 *   `addEventListener("state", handler)` etc. — `onmessage` only catches
 *   unnamed `event: message` SSE frames and silently swallows everything
 *   else. We learned this the hard way; don't regress it.
 *
 * Why a custom hook (vs TanStack Query):
 *   The server pushes state via SSE — there's no polling cadence. TanStack
 *   Query is reserved for the intent mutations.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { streamUrl } from "@/lib/api";
import type { Curation } from "@/lib/api-types.generated";
import type {
  ConnectionStatus,
  SseLogPayload,
  SseProgressPayload,
  SseStatePayload,
} from "@/lib/popup-types";

export interface ProgressState {
  operation: string;
  fraction: number;
  message?: string;
}

export interface LogEntry {
  id: string;
  level: "info" | "warn" | "error";
  message: string;
  at: number;
}

export interface UseProjectStateResult {
  /** Active curation document (or null if none active). */
  curation: Curation | null;
  /** Active curation name (mirrors curation?.name when present). */
  activeCurationName: string | null;
  status: ConnectionStatus;
  error: string | null;
  progress: ProgressState | null;
  /** Toast-bound log events. */
  logs: LogEntry[];
  /** Acknowledge a log event so the toast doesn't re-fire. */
  clearLog: (id: string) => void;
  /** Force-reconnect the SSE stream. */
  reconnect: () => void;
}

/** Inject a custom EventSource constructor for testing. */
export interface UseProjectStateOptions {
  EventSourceCtor?: typeof EventSource;
  url?: string;
}

function safeParse<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function useProjectState(
  opts: UseProjectStateOptions = {},
): UseProjectStateResult {
  const [curation, setCuration] = useState<Curation | null>(null);
  const [activeCurationName, setActiveCurationName] = useState<string | null>(
    null,
  );
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTokenRef = useRef(0);

  const handleStateEvent = useCallback((evt: MessageEvent<string>) => {
    const payload = safeParse<SseStatePayload>(evt.data);
    if (!payload) {
      setError("malformed SSE state payload");
      return;
    }
    setCuration(payload.curation ?? null);
    setActiveCurationName(
      payload.active_curation_name ?? payload.curation?.name ?? null,
    );
  }, []);

  const handleProgressEvent = useCallback((evt: MessageEvent<string>) => {
    const payload = safeParse<SseProgressPayload>(evt.data);
    if (!payload) return;
    if (payload.done) {
      setProgress(null);
      return;
    }
    setProgress({
      operation: payload.operation,
      fraction: payload.fraction,
      message: payload.message,
    });
  }, []);

  const handleLogEvent = useCallback((evt: MessageEvent<string>) => {
    const payload = safeParse<SseLogPayload>(evt.data);
    if (!payload) return;
    setLogs((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        level: payload.level,
        message: payload.message,
        at: Date.now(),
      },
    ]);
  }, []);

  const handleErrorEvent = useCallback((evt: MessageEvent<string>) => {
    const payload = safeParse<{ message: string }>(evt.data);
    if (payload?.message) setError(payload.message);
  }, []);

  useEffect(() => {
    const Ctor = opts.EventSourceCtor ?? globalThis.EventSource;
    if (!Ctor) {
      setStatus("error");
      setError("EventSource API not available in this environment");
      return;
    }

    setStatus("connecting");
    setError(null);
    const es = new Ctor(opts.url ?? streamUrl());
    esRef.current = es;

    es.onopen = () => setStatus("connected");
    es.onerror = () => {
      setStatus("disconnected");
      // EventSource auto-reconnects; we just surface state.
    };

    // Typed SSE channels (load-bearing — see header comment).
    es.addEventListener("state", handleStateEvent as EventListener);
    es.addEventListener("progress", handleProgressEvent as EventListener);
    es.addEventListener("log", handleLogEvent as EventListener);
    es.addEventListener("error_event", handleErrorEvent as EventListener);

    return () => {
      es.removeEventListener("state", handleStateEvent as EventListener);
      es.removeEventListener("progress", handleProgressEvent as EventListener);
      es.removeEventListener("log", handleLogEvent as EventListener);
      es.removeEventListener("error_event", handleErrorEvent as EventListener);
      es.close();
      esRef.current = null;
    };
    // reconnectTokenRef triggers re-running this effect when reconnect() is
    // invoked imperatively.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    handleStateEvent,
    handleProgressEvent,
    handleLogEvent,
    handleErrorEvent,
    opts.EventSourceCtor,
    opts.url,
    reconnectTokenRef.current,
  ]);

  const reconnect = useCallback(() => {
    esRef.current?.close();
    reconnectTokenRef.current += 1;
    setStatus("connecting");
  }, []);

  const clearLog = useCallback((id: string) => {
    setLogs((prev) => prev.filter((l) => l.id !== id));
  }, []);

  return {
    curation,
    activeCurationName,
    status,
    error,
    progress,
    logs,
    clearLog,
    reconnect,
  };
}
