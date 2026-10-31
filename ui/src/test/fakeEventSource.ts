import { act } from "@testing-library/react";
import { vi } from "vitest";

type Listener = (event: Event) => void;

/** Minimal EventSource double: tests drive open / named events / drops by hand. */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static get last(): FakeEventSource {
    const last = FakeEventSource.instances.at(-1);
    if (!last) throw new Error("no EventSource was created");
    return last;
  }

  readonly url: string;
  closed = false;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, listener: Listener) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }

  removeEventListener(name: string, listener: Listener) {
    this.listeners.set(
      name,
      (this.listeners.get(name) ?? []).filter((l) => l !== listener),
    );
  }

  close() {
    this.closed = true;
  }

  private dispatch(name: string, event: Event) {
    if (this.closed) return;
    for (const l of this.listeners.get(name) ?? []) l(event);
  }

  /** The (re)connection succeeded. */
  open() {
    act(() => this.dispatch("open", new Event("open")));
  }

  /** The connection dropped; a real EventSource then retries by itself. */
  drop() {
    act(() => this.dispatch("error", new Event("error")));
  }

  emit(name: string, data: unknown) {
    act(() => this.dispatch(name, new MessageEvent(name, { data: JSON.stringify(data) })));
  }
}

export function installFakeEventSource() {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
}
