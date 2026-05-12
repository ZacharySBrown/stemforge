/**
 * MockEventSource — minimal stand-in for the platform EventSource so hook
 * tests can deterministically push events.
 */

export class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  withCredentials = false;
  readyState = 0;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
  closed = false;

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
    // Defer the open so subscribers can attach handlers first.
    queueMicrotask(() => this._open());
  }

  _open() {
    if (this.closed) return;
    this.readyState = MockEventSource.OPEN;
    this.onopen?.call(this as unknown as EventSource, new Event("open"));
  }

  /** Push a JSON-stringified payload as a message event. */
  emit(data: unknown) {
    if (this.closed) return;
    const evt = new MessageEvent("message", { data: JSON.stringify(data) });
    this.onmessage?.call(this as unknown as EventSource, evt);
  }

  /** Simulate a transport error (auto-reconnect semantics handled by hook). */
  fail() {
    this.onerror?.call(this as unknown as EventSource, new Event("error"));
  }

  close() {
    this.closed = true;
    this.readyState = MockEventSource.CLOSED;
  }

  static reset() {
    MockEventSource.instances = [];
  }
}
