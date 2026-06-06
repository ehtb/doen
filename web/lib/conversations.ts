// Browser-local conversation storage (spec uvama, u1).
//
// Conversations are a session concern, not a durable server artifact: they live here, in the
// browser's IndexedDB, keyed per initiative/project. The backend is stateless about messages —
// the rail loads its own history from here and sends a windowed slice with each Advisor call.
//
// Why IndexedDB (not localStorage): an async API that never blocks the main thread, a structured
// object store with a real secondary index (so "all messages for this initiative" is an indexed
// lookup, not a parse-and-filter scan), and effectively unbounded capacity. We use the `idb`
// wrapper for a promise-based surface over the raw event API.

import { type DBSchema, type IDBPDatabase, openDB } from "idb";
import type { Message, Proposal } from "./types";

const DB_NAME = "doen-conversations";
const DB_VERSION = 1;
const STORE = "messages";
const SCOPE_INDEX = "scopeKey";

// The cap on stored messages per conversation (discretion item_556466333749: 100 is the starting
// point, tune on observed length). On every write we prune the oldest beyond this — so a long
// conversation stays bounded and the Advisor keeps functioning after pruning.
export const CONVERSATION_CAP = 100;
// How many recent turns we replay into an Advisor call (matches the backend's defensive cap). The
// backend assembles the prompt from this slice plus spec + memory; sending the whole history would
// defeat the stateless contract and balloon token cost as the conversation grows.
export const ADVISOR_WINDOW = 30;

// A conversation is owned by exactly one of an initiative, a project (general rail), or a project
// discovery session (BD-20). The scope key is the secondary index we query and prune by.
// `discoveryProjectId` produces a distinct "disc:{id}" key so discovery history is separate from
// the general project conversation ("proj:{id}") — switching modes preserves each thread.
export type ConversationScope = { initiativeId: string } | { projectId: string } | { discoveryProjectId: string };

type MessageMetadata = { proposals?: Proposal[] } & Record<string, unknown>;

// What actually sits in the object store: the rail's Message plus the index key and a monotonic
// per-conversation sequence number that gives a stable total order (createdAt can tie when two
// writes land in the same millisecond — e.g. a tight test loop).
interface StoredMessage {
  id: string;
  scopeKey: string;
  initiativeId?: string;
  projectId?: string;
  role: "human" | "advisor";
  content: string;
  metadata: MessageMetadata;
  createdAt: string;
  seq: number;
}

interface ConversationDB extends DBSchema {
  messages: {
    key: string; // the unique message id
    value: StoredMessage;
    indexes: { scopeKey: string };
  };
}

function scopeKey(scope: ConversationScope): string {
  if ("initiativeId" in scope) return `init:${scope.initiativeId}`;
  if ("discoveryProjectId" in scope) return `disc:${scope.discoveryProjectId}`;
  return `proj:${scope.projectId}`;
}

function newId(): string {
  // crypto.randomUUID is available in every browser we target and in the Node test runner.
  return `msg_${crypto.randomUUID()}`;
}

let _db: Promise<IDBPDatabase<ConversationDB>> | null = null;

function getDB(): Promise<IDBPDatabase<ConversationDB>> {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new Error("IndexedDB is unavailable (conversations are browser-only)"));
  }
  if (_db === null) {
    _db = openDB<ConversationDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        // Keyed by the unique message id; indexed on scopeKey so loading/pruning one
        // conversation is an indexed range query, never a full-store scan.
        const store = db.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex(SCOPE_INDEX, "scopeKey");
      },
    });
  }
  return _db;
}

function toMessage(m: StoredMessage): Message {
  return {
    id: m.id,
    initiative_id: m.initiativeId ?? null,
    project_id: m.projectId ?? null,
    role: m.role,
    content: m.content,
    metadata: m.metadata,
    created_at: m.createdAt,
  };
}

/** Every message for a conversation, oldest-first. An indexed lookup by scope, sorted by seq. */
export async function loadConversation(scope: ConversationScope): Promise<Message[]> {
  const db = await getDB();
  const rows = await db.getAllFromIndex(STORE, SCOPE_INDEX, scopeKey(scope));
  return rows.sort((a, b) => a.seq - b.seq).map(toMessage);
}

/**
 * Append one turn and prune the conversation back to the cap in the same transaction — pruning
 * fires on write (not on read, not on a timer), so the store never sits above the cap. Returns the
 * stored message (with its generated id + timestamp) so the rail can render it.
 */
export async function appendMessage(
  scope: ConversationScope,
  input: { role: "human" | "advisor"; content: string; metadata?: MessageMetadata },
): Promise<Message> {
  const db = await getDB();
  const key = scopeKey(scope);
  const tx = db.transaction(STORE, "readwrite");
  const existing = await tx.store.index(SCOPE_INDEX).getAll(key);
  const maxSeq = existing.reduce((m, r) => Math.max(m, r.seq), 0);

  const stored: StoredMessage = {
    id: newId(),
    scopeKey: key,
    initiativeId: "initiativeId" in scope ? scope.initiativeId : undefined,
    projectId:
      "projectId" in scope
        ? scope.projectId
        : "discoveryProjectId" in scope
          ? scope.discoveryProjectId
          : undefined,
    role: input.role,
    content: input.content,
    metadata: input.metadata ?? {},
    createdAt: new Date().toISOString(),
    seq: maxSeq + 1,
  };
  await tx.store.put(stored);

  // Prune the oldest beyond the cap (the cap + this new write may put us one over).
  const ordered = [...existing, stored].sort((a, b) => a.seq - b.seq);
  const overflow = ordered.length - CONVERSATION_CAP;
  for (let i = 0; i < overflow; i++) {
    await tx.store.delete(ordered[i].id);
  }
  await tx.done;
  return toMessage(stored);
}

/** The most recent `n` turns, oldest-first — the windowed slice sent to the Advisor. */
export async function recentWindow(
  scope: ConversationScope,
  n: number = ADVISOR_WINDOW,
): Promise<{ role: "human" | "advisor"; content: string }[]> {
  const all = await loadConversation(scope);
  return all.slice(-n).map((m) => ({ role: m.role, content: m.content }));
}

/** Persist a proposal verdict (accepted/dismissed) onto the stored message so it survives reload. */
export async function updateProposalVerdict(
  messageId: string,
  proposalIdx: number,
  verdict: "accepted" | "dismissed",
): Promise<void> {
  const db = await getDB();
  const stored = await db.get(STORE, messageId);
  if (!stored) return;
  const proposals = stored.metadata.proposals ? [...stored.metadata.proposals] : [];
  if (proposalIdx >= proposals.length) return;
  proposals[proposalIdx] = { ...proposals[proposalIdx], verdict };
  await db.put(STORE, { ...stored, metadata: { ...stored.metadata, proposals } });
}

/** Drop a single message (used to roll back an optimistic human turn when the Advisor call fails). */
export async function deleteMessage(id: string): Promise<void> {
  const db = await getDB();
  await db.delete(STORE, id);
}

/**
 * Clear an entire conversation — every message for this initiative/project, and nothing else
 * (the spec, decisions, work units, and memory are separate stores entirely). Backs the rail's
 * 'Reset conversation' action.
 */
export async function clearConversation(scope: ConversationScope): Promise<void> {
  const db = await getDB();
  const tx = db.transaction(STORE, "readwrite");
  const keys = await tx.store.index(SCOPE_INDEX).getAllKeys(scopeKey(scope));
  for (const k of keys) {
    await tx.store.delete(k);
  }
  await tx.done;
}

/** Test-only: reset the cached connection so a fresh fake-indexeddb is picked up between cases. */
export function _resetDbForTests(): void {
  _db = null;
}
