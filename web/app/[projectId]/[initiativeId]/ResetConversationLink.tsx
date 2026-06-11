"use client";

import { useState } from "react";
import { clearConversation, type ConversationScope } from "@/lib/conversations";

export const CONVERSATION_RESET_EVENT = "doen:conversation-reset";

export default function ResetConversationLink({ scope }: { scope: ConversationScope }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function reset() {
    if (busy) return;
    setBusy(true);
    try {
      await clearConversation(scope);
      window.dispatchEvent(new CustomEvent(CONVERSATION_RESET_EVENT, { detail: scope }));
    } catch {
      // ignore
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <p className="mt-3 text-center text-[11.5px] text-ink-faint">
        Clears message history only.{" "}
        <button
          type="button"
          onClick={reset}
          disabled={busy}
          className="text-primary hover:underline disabled:opacity-50"
        >
          {busy ? "Resetting…" : "Yes, reset"}
        </button>
        {" · "}
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="hover:text-ink-soft"
        >
          Cancel
        </button>
      </p>
    );
  }

  return (
    <div className="mt-3 text-center">
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="text-[11.5px] text-ink-faint transition-colors hover:text-ink-soft"
      >
        ↺ Reset conversation
      </button>
    </div>
  );
}
