# Project Evolution & Research Log

This document tracks the strategic intent and research foundations behind the architectural evolution of Doen, tracing the transition from a governed agent prototype to a human-overseen Agentic SDLC.

---

## [Current Phase] Shifting to Oversight (BD-12 to BD-14)
**Focus:** Minimizing the "Operator" tax and scaling human judgment.

### BD-14: Advisor-Led Batch Review
*   **Intent:** Eliminate the cognitive bottleneck of item-level approval.
*   **Research Thinking:** Based on **Human-on-the-Loop (HOTL)** orchestration patterns. Human users should not spend time approving obvious, well-formed items that align with organizational memory. Classification into `confident`, `flagged`, and `uncertain` allows the system to prioritize human attention where it is most needed—on high-entropy judgment calls.

### BD-13: Discretion Auditor & Steering-Ratio Awareness
*   **Intent:** Safeguarding organizational memory and managing "steering friction."
*   **Research Thinking:** Addresses **Structural Capital Contamination** (KLRM, 2026). By enforcing that memory entries (learnings) must have human-verified sources, we prevent the "echo chamber" effect of AI-authored rationales. The Discretion Auditor identifies when an agent is acting within its human-granted latitude, reducing unnecessary interruptions.

### BD-12: Reflexive Memory Verification
*   **Intent:** Preventing "Operational Amnesia" caused by codebase drift.
*   **Research Thinking:** Organizational memory is often treated as static ground truth. BD-12 transforms memory hits into **verify-on-use obligations**. Agents are now required to audit the claims they read against the live codebase, ensuring that the context used for new decisions is always grounded in current reality.

---

## [Scaling Phase] Enterprise Readiness & Governance (BD-5 to BD-11)
**Focus:** Moving from a single-initiative tool to a project-lifecycle system.

### BD-11: Project Lifecycle & Archiving
*   **Intent:** Managing the "long tail" of initiatives.
*   **Research Thinking:** As a project matures, the volume of historical data increases. Archiving and project-level scoping prevent "Context Dilution," ensuring that the Advisor's recommendations remain focused on the relevant project scope rather than being overwhelmed by unrelated organizational noise.

### BD-8/BD-9: Passive Polling & Onboarding
*   **Intent:** Seamless integration with existing developer workflows.
*   **Research Thinking:** Reducing the "Activation Energy" for new projects. Passive polling allows the system to remain aware of external changes without requiring constant human push, while structured onboarding ensures that the initial "Context Seed" of a project is correctly established.

### BD-5: The "Criterion-as-Unit" Refactor
*   **Intent:** Aligning verification with governance.
*   **Research Thinking:** Originally, Doen tracked "Work Units" (tasks) and "Acceptance Criteria" separately. Research into **Executable Design Documents (EDD)** suggested this was redundant. By refactoring to use Criteria as the primary unit of verification, we ensure that "Done" is always defined by the fulfillment of a governing constraint, not just the completion of a task.

---

## [Foundation Phase] The Governed Agent (Initial Release to BD-4)
**Focus:** Establishing the "Spec-as-Code" hypothesis.

### The Doen Advisor & Conversation Rail
*   **Intent:** Providing a "Mirror" for human intent.
*   **Research Thinking:** The Advisor is not a chatbot; it is a **Reflexive Interface**. The Conversation Rail ensures that the dialogue between human and AI is always anchored in the Spec. Every conversation turn is an opportunity to extract or refine a governing constraint.

### AI-Assisted Spec Shaping
*   **Intent:** Translating natural language intent into structured governance.
*   **Research Thinking:** Based on the **Correction-over-Authoring** principle. The AI drafts the complex spec structure (constraints, discretion, acceptance), but the human remains the final authority. This minimizes the "Blank Page" problem while maintaining strict human control over agent behavior.

### Project Baseline: The Initial Spec Engine
*   **Intent:** Proving that an agent can be governed by a living document.
*   **Research Thinking:** The core hypothesis: if we can represent requirements as a structured, versioned, and verifiable "Spec-Contract," we can deploy autonomous agents with high confidence. The initial engine established the three-tier governance model: **Constraints** (Hard Rules), **Discretion** (Agent Latitude), and **Acceptance** (Verifiable Outcomes).

---

## Core Principles
All of these changes adhere to the **Doen Spec-Contract** (documented in `docs/spec-contract.md`):
*   **Correction over Authoring:** AI drafts, humans correct/verify.
*   **Living Spec as Governance:** The spec isn't a doc; it's the code that governs the agent.
*   **Traceability:** Every confirmed item has a clear provenance (ai_proposed -> ai_confirmed_by_human).
