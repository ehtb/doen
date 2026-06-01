import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { consumeInitiativeDraft, PREFILL_EVENT, stashInitiativeDraft } from "./initiativeDraft";

// The hand-off uses browser globals (sessionStorage, window events). The test env is node, so we
// stub just enough: an in-memory sessionStorage, a window that fans events out to listeners, and a
// minimal CustomEvent that carries `detail`.
beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  const handlers: ((e: Event) => void)[] = [];
  vi.stubGlobal("window", {
    dispatchEvent: (e: Event) => {
      handlers.forEach((h) => h(e));
      return true;
    },
    addEventListener: (_type: string, h: (e: Event) => void) => handlers.push(h),
    removeEventListener: () => {},
  });
  vi.stubGlobal(
    "CustomEvent",
    class {
      type: string;
      detail: unknown;
      constructor(type: string, init?: { detail?: unknown }) {
        this.type = type;
        this.detail = init?.detail;
      }
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("initiative draft hand-off (BD-1 u3)", () => {
  it("stash dispatches a prefill event carrying the projectId + description", () => {
    let detail: unknown = null;
    window.addEventListener(PREFILL_EVENT, (e) => {
      detail = (e as CustomEvent).detail;
    });
    stashInitiativeDraft("proj_1", "a dead-letter queue for webhooks that fail every retry");
    expect(detail).toEqual({
      projectId: "proj_1",
      description: "a dead-letter queue for webhooks that fail every retry",
    });
  });

  it("consume returns the stashed draft once, then clears it (one-shot)", () => {
    stashInitiativeDraft("proj_1", "ship a replay tool for dead-lettered webhooks");
    expect(consumeInitiativeDraft("proj_1")).toBe("ship a replay tool for dead-lettered webhooks");
    // consumed — a second read finds nothing, so the form can't re-fill later.
    expect(consumeInitiativeDraft("proj_1")).toBeNull();
  });

  it("keeps drafts isolated per project", () => {
    stashInitiativeDraft("proj_1", "one");
    stashInitiativeDraft("proj_2", "two");
    expect(consumeInitiativeDraft("proj_2")).toBe("two");
    expect(consumeInitiativeDraft("proj_1")).toBe("one");
  });
});
