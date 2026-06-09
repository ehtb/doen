# Project Evolution & Research Log

This document tracks the strategic intent and research foundations behind the architectural evolution of Doen, tracing the transition from a governed agent prototype to a human-overseen Agentic SDLC.

---

## [Current Phase] Shifting to Oversight (BD-12 to BD-25)

**Focus:** Minimizing the "Operator" tax and scaling human judgment.

### BD-25: Auto-Approve Learnings & Structured Review

- **Intent:** Minimizing review friction for routine project knowledge.
- **Research Thinking:** The Learning stage is often the highest friction point in the oversight loop. Many learnings are straightforward restatements of work done within granted discretion. BD-25 applies the **Auditor Pattern** to the learning draft: it evaluates proposed learning bullets against the initiative's discretion items and criteria. Items that clearly align with established boundaries are marked `auto_approved` and presented passively, while novel or high-entropy insights are flagged for human review. This ensures human attention is reserved for knowledge that actually expands the project's strategic horizons.

### BD-24: Scoped Observations & The "Reject" Signal

- **Intent:** Increasing observation precision and managing synthesis noise.
- **Research Thinking:** As a project's history deepens, advisor observations can become repetitive or irrelevant if not strictly bounded. BD-24 introduces **Temporal Scoping** for synthesis: observations are now explicitly linked to the specific initiative that triggered the discovery. This implements a "one-observation-per-initiative" lifecycle cap, preventing the advisor from re-surfacing the same insight across multiple synthesis cycles. Crucially, it also introduces the **Negative Signal (Reject)** flow. By allowing humans to dismiss an observation without acting, we capture an explicit signal of "not relevant" or "already known but unaddressed." This negative signal is as important as the positive "Resolve" signal for refining the advisor's future synthesis heuristics, ensuring that the discovery rail remains high-signal as the project scales.

### BD-22: Persisted Advisor Observations

- **Intent:** Closing the loop between synthesis and action.
- **Research Thinking:** While BD-20 introduced proactive synthesis, the resulting "observations" were transient UI elements. BD-22 formalizes these as **Persistent Observations**—first-class database entities that survive session reloads. It introduces a "Resolve to Initiative" flow, allowing humans to promote a specific advisor-generated insight directly into a shaped initiative. This transforms the synthesis engine from a "reporting" tool into a "generative" one, proactively populating the project backlog with data-driven suggestions.

### BD-20: Guided Discovery & Proactive Synthesis

- **Intent:** Bridging the gap from fuzzy "observation" to shaped "initiative."
- **Research Thinking:** Most product work starts not with a clear intent, but with a signal—a bug report, a user complaint, or a hunch. Standard AI assistants often rush to "solutionizing" (jumping to code) or remain too passive. BD-20 implements two research-backed shifts:

  1.  **Iterative Discovery Scaffolding (ArXiv:2512.09142):** Instead of a generic chat, the discovery rail uses a **Question Sequence** protocol. It forces the Advisor to extract five specific dimensions (Problem, People, Workarounds, Outcome, Smallest Learning) *before* proposing an initiative. This prevents "Vague Spec Syndrome" where agents are given under-specified goals. The Advisor also distinguishes between **Engineering** (build a thing) and **Research** (learn a thing) framings, pre-selecting the initiative type to align the verification loop from the start.
  2.  **Proactive Cross-Initiative Synthesis Engine:** As project memory grows, humans suffer from **Synthesis Fatigue**. BD-20 introduces the synthesis engine that performs proactive analysis on project load. When $\ge 5$ initiatives are completed, it triggers a "What We Know" analysis using the **Pattern-Assumption-Intent (PAI) Framework**. This ensures that lessons learned in `BD-4` are proactively surfaced when thinking about new work, turning the project page from a list of tasks into a strategic dashboard.

**Key References:**
- **Iterative Discovery Scaffolding (ArXiv:2512.09142)** — structured extraction of intent from ambiguous signals.
- **Synthesis Fatigue in Agentic Workflows (ArXiv:2601.10442)** — the need for proactive, cross-task summarization.
- **The PAI Framework for Institutional Memory** — categorizing knowledge into patterns (recurrent), assumptions (validated/invalidated), and intent alignment.

### BD-17: Compound Knowledge Flywheel (Heuristics)

- **Intent:** Transforming ephemeral project outcomes into durable, actionable guidance.
- **Research Thinking:** Standard "Lessons Learned" often fail because they lack actionability and discoverability. While Doen's memory stores narratives and decisions ("we decided X in BD-4"), research on **Experiential Reflective Learning (ERL, ArXiv:2603.24639)** shows that agents improve dramatically when experience is distilled into heuristics—concrete, actionable rules that transfer across tasks. A heuristic tells the agent what to do differently ("always verify migration compatibility before adding a new table"), whereas a narrative only tells it what was done. BD-17 implements three shifts to ensure Doen's knowledge flywheel compounds as actionable intelligence:

  1.  **Heuristic Extraction in Learn:** During the Learning stage, the Advisor extracts explicit cause-effect rules and failure patterns (e.g., "Always use asyncpg's connection pool with min_size=2..."). These are stored as a distinct memory type, tagged and retrievable, ensuring that `get_context` returns actionable rules alongside historical facts. Reference: ERL's "reflect on trajectories to generate transferable heuristics" pattern.
  2.  **Uncertainty-Aware Proposals:** Proposals are now classified by confidence. Items grounded in strong memory (heuristics/decisions) are marked `confident`, while those inferred from thin descriptions are `uncertain`. This allows the human to focus scrutiny where it matters most. Reference: **ARIA framework (ArXiv:2507.17131)**, where agents assess uncertainty and proactively flag knowledge gaps.
  3.  **Incremental Knowledge Evolution:** To avoid "context collapse"—where monolithic rewriting of `agents.md` degrades context over time—BD-17 adopts the **Agentic Context Engineering (ACE, ArXiv:2510.04618)** approach. Knowledge grows incrementally; heuristics are appended and contradicted entries are marked "superseded," never deleted. This preserves the evolution of decisions and ensures the "Living Handbook" accumulates rather than collapses.

**Key References:**
- **Experiential Reflective Learning (ArXiv:2603.24639)** — heuristic extraction from task trajectories.
- **ARIA framework (ArXiv:2507.17131)** — uncertainty-aware agents with knowledge gap identification.
- **Agentic Context Engineering / ACE (ArXiv:2510.04618)** — evolving playbooks, context collapse prevention.
- **Knowledge Activation (ArXiv:2603.14805)** — institutional knowledge as reusable primitives for agents.

### BD-16: Systematic Verification & Eval Harness

- **Intent:** Moving from "Ad-hoc Review" to "Verifiable Reliability."
- **Research Thinking:** As the system handles more complex logic (like Advisor-led reviews), the prompts governing these transitions become critical infrastructure. BD-16 introduces a **Promptfoo Evaluation Harness** to systematically measure prompt performance against known edge cases. This shift ensures that changes to the "Governor" (the LLM prompts) are themselves governed by evidence-based evaluation, preventing regressions in the quality of human-facing signals.

### BD-15: Research Initiatives (Engineering vs. Research Framing)

- **Intent:** Expanding Doen's governance model to non-code-shipping outcomes.
- **Research Thinking:** Not all software engineering work results in code. Investigations, spikes, and methodology research are critical but often escape formal governance. BD-15 introduces a "Research" framing that shifts the focus from "Acceptance" to "Success Criteria" and from "Evidence" to "Findings." This allows the same structured governance loop to apply to the _reasoning_ process itself, enabling a full lifecycle (draft -> investigating -> learning) without an MCP connection.

### BD-14: Advisor-Led Batch Review

- **Intent:** Eliminate the cognitive bottleneck of item-level approval.
- **Research Thinking:** Based on **Human-on-the-Loop (HOTL)** orchestration patterns. Human users should not spend time approving obvious, well-formed items that align with organizational memory. Classification into `confident`, `flagged`, and `uncertain` allows the system to prioritize human attention where it is most needed—on high-entropy judgment calls.

### BD-13: Discretion Auditor & Steering-Ratio Awareness

- **Intent:** Safeguarding organizational memory and managing "steering friction."
- **Research Thinking:** Addresses **Structural Capital Contamination** (KLRM, 2026). By enforcing that memory entries (learnings) must have human-verified sources, we prevent the "echo chamber" effect of AI-authored rationales. The Discretion Auditor identifies when an agent is acting within its human-granted latitude, reducing unnecessary interruptions.

### BD-12: Reflexive Memory Verification

- **Intent:** Preventing "Operational Amnesia" caused by codebase drift.
- **Research Thinking:** Organizational memory is often treated as static ground truth. BD-12 transforms memory hits into **verify-on-use obligations**. Agents are now required to audit the claims they read against the live codebase, ensuring that the context used for new decisions is always grounded in current reality.

---

## [Scaling Phase] Enterprise Readiness & Governance (BD-5 to BD-11)

**Focus:** Moving from a single-initiative tool to a project-lifecycle system.

### BD-11: Project Lifecycle & Archiving

- **Intent:** Managing the "long tail" of initiatives.
- **Research Thinking:** As a project matures, the volume of historical data increases. Archiving and project-level scoping prevent "Context Dilution," ensuring that the Advisor's recommendations remain focused on the relevant project scope rather than being overwhelmed by unrelated organizational noise.

### BD-10: MCP HTTP Transport (Remote Agents)

- **Intent:** Decoupling the Advisor from the local execution environment.
- **Research Thinking:** Moving beyond `stdio` to HTTP transport enables Doen to govern agents running in distributed environments or specialized containers. This is a prerequisite for **Polyglot Governance**, where the same spec-contract can be enforced across different language stacks and execution runtimes.

### BD-8/BD-9: Passive Polling & Onboarding

- **Intent:** Seamless integration with existing developer workflows.
- **Research Thinking:** Reducing the "Activation Energy" for new projects. Passive polling allows the system to remain aware of external changes without requiring constant human push, while structured onboarding ensures that the initial "Context Seed" of a project is correctly established.

### BD-7: Short IDs & Project-Scoped Identifiers

- **Intent:** Enhancing human-AI grounding via readable handles.
- **Research Thinking:** Internal UUIDs are "Machine-Only" context. By introducing sequential, project-prefixed short IDs (e.g., `BD-7`), we create a **Shared Vocabulary** between the human and the Advisor. This reduces the cognitive load during conversation, allowing both parties to refer to complex initiatives with a single, unambiguous token.

### BD-5: The "Criterion-as-Unit" Refactor

- **Intent:** Aligning verification with governance.
- **Research Thinking:** Originally, Doen tracked "Work Units" (tasks) and "Acceptance Criteria" separately. Research into **Executable Design Documents (EDD)** suggested this was redundant. By refactoring to use Criteria as the primary unit of verification, we ensure that "Done" is always defined by the fulfillment of a governing constraint, not just the completion of a task.

---

## [Foundation Phase] The Governed Agent (Initial Release to BD-4)

**Focus:** Establishing the "Spec-as-Code" hypothesis.

### The Doen Advisor & Conversation Rail

- **Intent:** Providing a "Mirror" for human intent.
- **Research Thinking:** The Advisor is not a chatbot; it is a **Reflexive Interface**. The Conversation Rail ensures that the dialogue between human and AI is always anchored in the Spec. Every conversation turn is an opportunity to extract or refine a governing constraint.

### AI-Assisted Spec Shaping

- **Intent:** Translating natural language intent into structured governance.
- **Research Thinking:** Based on the **Correction-over-Authoring** principle. The AI drafts the complex spec structure (constraints, discretion, acceptance), but the human remains the final authority. This minimizes the "Blank Page" problem while maintaining strict human control over agent behavior.

### Project Baseline: The Initial Spec Engine

- **Intent:** Proving that an agent can be governed by a living document.
- **Research Thinking:** The core hypothesis: if we can represent requirements as a structured, versioned, and verifiable "Spec-Contract," we can deploy autonomous agents with high confidence. The initial engine established the three-tier governance model: **Constraints** (Hard Rules), **Discretion** (Agent Latitude), and **Acceptance** (Verifiable Outcomes).

---

## Core Principles

All of these changes adhere to the **Doen Spec-Contract** (documented in `docs/spec-contract.md`):

- **Correction over Authoring:** AI drafts, humans correct/verify.
- **Living Spec as Governance:** The spec isn't a doc; it's the code that governs the agent.
- **Traceability:** Every confirmed item has a clear provenance (ai_proposed -> ai_confirmed_by_human).
