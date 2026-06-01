import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";

import {
  _resetDbForTests,
  appendMessage,
  clearConversation,
  CONVERSATION_CAP,
  loadConversation,
  recentWindow,
} from "./conversations";

// Each test gets a pristine IndexedDB (and a fresh cached connection) so state never leaks.
beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  _resetDbForTests();
});

describe("conversation store (IndexedDB)", () => {
  it("persists and reloads a conversation keyed by initiative", async () => {
    const scope = { initiativeId: "BD-1" };
    await appendMessage(scope, { role: "human", content: "what should I build first?" });
    await appendMessage(scope, { role: "advisor", content: "start with the migration." });

    // A fresh connection (as a page reload would get) restores the history from IndexedDB.
    _resetDbForTests();
    const restored = await loadConversation(scope);
    expect(restored.map((m) => m.content)).toEqual([
      "what should I build first?",
      "start with the migration.",
    ]);
    expect(restored.map((m) => m.role)).toEqual(["human", "advisor"]);
  });

  it("isolates conversations by scope — an indexed lookup returns only that owner's messages", async () => {
    await appendMessage({ initiativeId: "BD-1" }, { role: "human", content: "init one" });
    await appendMessage({ initiativeId: "BD-2" }, { role: "human", content: "init two" });
    await appendMessage({ projectId: "build-doen" }, { role: "human", content: "project turn" });

    expect((await loadConversation({ initiativeId: "BD-1" })).map((m) => m.content)).toEqual(["init one"]);
    expect((await loadConversation({ initiativeId: "BD-2" })).map((m) => m.content)).toEqual(["init two"]);
    expect((await loadConversation({ projectId: "build-doen" })).map((m) => m.content)).toEqual([
      "project turn",
    ]);
  });

  // AC item_4fc6d5df5211: conversations are capped; on write the oldest are pruned automatically,
  // the store holds exactly the cap, and the kept messages are the most recent ones.
  it("prunes to the cap on write, keeping the most recent messages", async () => {
    const scope = { initiativeId: "BD-1" };
    const total = CONVERSATION_CAP + 10;
    for (let i = 0; i < total; i++) {
      await appendMessage(scope, { role: i % 2 === 0 ? "human" : "advisor", content: `m${i}` });
    }

    const all = await loadConversation(scope);
    expect(all.length).toBe(CONVERSATION_CAP);
    // the oldest 10 (m0..m9) are gone; the kept window is m10..m{total-1}, oldest-first.
    expect(all[0].content).toBe(`m${total - CONVERSATION_CAP}`);
    expect(all[all.length - 1].content).toBe(`m${total - 1}`);
  });

  it("sends a bounded recent window for the Advisor call", async () => {
    const scope = { initiativeId: "BD-1" };
    for (let i = 0; i < 8; i++) {
      await appendMessage(scope, { role: "human", content: `m${i}` });
    }
    const window = await recentWindow(scope, 3);
    expect(window).toEqual([
      { role: "human", content: "m5" },
      { role: "human", content: "m6" },
      { role: "human", content: "m7" },
    ]);
  });

  it("reset clears only the target conversation, leaving siblings untouched", async () => {
    await appendMessage({ initiativeId: "BD-1" }, { role: "human", content: "keep me out of it" });
    await appendMessage({ initiativeId: "BD-2" }, { role: "human", content: "clear me" });

    await clearConversation({ initiativeId: "BD-2" });

    expect(await loadConversation({ initiativeId: "BD-2" })).toEqual([]);
    expect((await loadConversation({ initiativeId: "BD-1" })).map((m) => m.content)).toEqual([
      "keep me out of it",
    ]);
  });

  // AC item_599cae4aaa38: after reset, IndexedDB holds zero records for that scope AND the next
  // Advisor call carries no prior history. The rail builds that history live from recentWindow on
  // every turn, so a cleared store yields an empty window — proving the next call sends nothing.
  it("reset leaves the next Advisor window empty for that scope", async () => {
    const scope = { initiativeId: "BD-7" };
    for (let i = 0; i < 5; i++) {
      await appendMessage(scope, { role: "human", content: `m${i}` });
    }
    expect((await recentWindow(scope)).length).toBe(5);

    await clearConversation(scope);

    // zero records by id-keyed lookup, and an empty next-call window.
    expect(await loadConversation(scope)).toEqual([]);
    expect(await recentWindow(scope)).toEqual([]);
  });

  it("preserves proposal-card metadata round-trip", async () => {
    const scope = { initiativeId: "BD-1" };
    await appendMessage(scope, {
      role: "advisor",
      content: "here's a proposal",
      metadata: { proposals: [{ section: "constraints", text: "must be idempotent" }] },
    });
    const [msg] = await loadConversation(scope);
    expect(msg.metadata.proposals?.[0]?.text).toBe("must be idempotent");
  });
});
