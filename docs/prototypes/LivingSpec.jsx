import React, { useState, useEffect } from "react";
import {
  Lock,
  Compass,
  Check,
  CircleDot,
  Sparkles,
  GitBranch,
  ArrowRight,
  Cpu,
  User,
  CornerDownRight,
} from "lucide-react";

export default function LivingSpec() {
  // Load distinctive fonts (no @import in <style> for reliability)
  useEffect(() => {
    const id = "ls-fonts";
    if (!document.getElementById(id)) {
      const link = document.createElement("link");
      link.id = id;
      link.rel = "stylesheet";
      link.href =
        "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap";
      document.head.appendChild(link);
    }
  }, []);

  const STAGES = [
    "Discover",
    "Shape",
    "Bet",
    "Decompose",
    "Implement",
    "Verify",
    "Learn",
  ];
  const currentStage = 4; // Implement

  const [constraints, setConstraints] = useState([
    { id: "c1", text: "Must not weaken security for first-time or high-risk sign-ins.", isNew: false },
    { id: "c2", text: "Web-first. No native app dependency.", isNew: false },
    { id: "c3", text: "Reuse existing WorkOS identity — no parallel auth system.", isNew: false },
    { id: "c4", text: "Ships behind a flag, default off until verified in canary.", isNew: false },
  ]);

  const discretion = [
    "Passkey vs. magic-link vs. device-trust token — your call, optimise for fewest taps.",
    "Copy and layout of the sign-in screen.",
    "Session caching approach, within the security constraints.",
  ];

  const [criteria, setCriteria] = useState([
    { id: "a1", text: "A returning user on a known device signs in in \u22641 deliberate action.", isNew: false },
    { id: "a2", text: "A new device always falls back to full sign-in.", isNew: false },
    { id: "a3", text: "Zero increase in account-takeover rate over a 2-week canary.", isNew: false },
  ]);

  const [decisions, setDecisions] = useState([]);

  const [proposal, setProposal] = useState("pending"); // pending | accepted | dismissed
  const [escalation, setEscalation] = useState({ status: "open", choice: null }); // open | resolved

  const acceptProposal = () => {
    setConstraints((prev) => [
      ...prev,
      {
        id: "c5",
        text: "On shared or public devices, never offer one-tap \u2014 require full sign-in.",
        isNew: true,
      },
    ]);
    setProposal("accepted");
  };

  const resolveEscalation = (choice) => {
    setEscalation({ status: "resolved", choice });
    if (choice === "perDevice") {
      setDecisions((prev) => [
        ...prev,
        {
          id: "d1",
          text: "Trust is scoped per-device. Switching devices triggers a fresh trust handshake.",
          rationale: "Honours the security constraint over convenience.",
          isNew: true,
        },
      ]);
      setCriteria((prev) => [
        ...prev,
        { id: "a4", text: "Trust never transfers between devices without re-authentication.", isNew: true },
      ]);
    } else {
      setDecisions((prev) => [
        ...prev,
        {
          id: "d1",
          text: "Trust syncs across a user's devices via a server-held token.",
          rationale: "Prioritises convenience; widens attack surface \u2014 revisit in Verify.",
          isNew: true,
        },
      ]);
      setCriteria((prev) => [
        ...prev,
        { id: "a4", text: "Synced trust token is revocable from any device within 30s.", isNew: true },
      ]);
    }
  };

  return (
    <div className="ls-root">
      <style>{css}</style>

      {/* ---------- Header ---------- */}
      <header className="ls-head">
        <div className="ls-head-top">
          <div className="ls-eyebrow">Initiative</div>
          <div className="ls-meta">
            <span className="ls-dot-live" /> agents active · 2 units in flight
          </div>
        </div>
        <h1 className="ls-title">Let returning users sign in without a password</h1>
        <nav className="ls-stepper" aria-label="lifecycle">
          {STAGES.map((s, i) => (
            <div
              key={s}
              className={
                "ls-step " +
                (i < currentStage ? "done " : "") +
                (i === currentStage ? "active " : "")
              }
            >
              <span className="ls-step-tick" />
              {s}
            </div>
          ))}
        </nav>
      </header>

      {/* ---------- Body: two surfaces ---------- */}
      <div className="ls-body">
        {/* ===== The living spec (the artifact) ===== */}
        <main className="ls-spec" style={{ animationDelay: "0.05s" }}>
          <div className="ls-spec-label">
            <span>The living spec</span>
            <span className="ls-spec-sub">what you've committed to</span>
          </div>

          <section className="ls-block" style={{ animationDelay: "0.10s" }}>
            <h2 className="ls-h intent-h">Intent</h2>
            <p className="ls-intent">
              Returning users abandon at the password step. We want them back into
              the product in one tap from a device they've used before &mdash;
              without us, or them, lowering the security bar for everyone else.
            </p>
            <span className="ls-prov human">
              <CircleDot size={11} strokeWidth={2.2} /> yours
            </span>
          </section>

          <section className="ls-block" style={{ animationDelay: "0.16s" }}>
            <h2 className="ls-h">
              <Lock size={13} strokeWidth={2.2} /> Constraints
              <span className="ls-h-note">locked &mdash; I will not cross these</span>
            </h2>
            <ul className="ls-list">
              {constraints.map((c) => (
                <li key={c.id} className={"ls-item locked" + (c.isNew ? " is-new" : "")}>
                  <span className="ls-bar" />
                  {c.text}
                </li>
              ))}
            </ul>
          </section>

          <section className="ls-block" style={{ animationDelay: "0.22s" }}>
            <h2 className="ls-h">
              <Compass size={13} strokeWidth={2.2} /> Discretion
              <span className="ls-h-note">my latitude &mdash; decide as I build</span>
            </h2>
            <ul className="ls-list">
              {discretion.map((d, i) => (
                <li key={i} className="ls-item open">
                  <span className="ls-bar" />
                  {d}
                </li>
              ))}
            </ul>
          </section>

          <section className="ls-block" style={{ animationDelay: "0.28s" }}>
            <h2 className="ls-h">
              <Check size={13} strokeWidth={2.4} /> Acceptance criteria
              <span className="ls-h-note">how the work gets judged</span>
            </h2>
            <ul className="ls-list">
              {criteria.map((a) => (
                <li key={a.id} className={"ls-item crit" + (a.isNew ? " is-new" : "")}>
                  <span className="ls-check" />
                  {a.text}
                </li>
              ))}
            </ul>
          </section>

          {decisions.length > 0 && (
            <section className="ls-block">
              <h2 className="ls-h">
                <GitBranch size={13} strokeWidth={2.2} /> Decisions
                <span className="ls-h-note">judgment calls, written back</span>
              </h2>
              <ul className="ls-list">
                {decisions.map((d) => (
                  <li key={d.id} className={"ls-item decision" + (d.isNew ? " is-new" : "")}>
                    <span className="ls-bar" />
                    <div>
                      {d.text}
                      <span className="ls-rationale">{d.rationale}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </main>

        {/* ===== The conversation / steering rail (the input) ===== */}
        <aside className="ls-rail" style={{ animationDelay: "0.12s" }}>
          <div className="ls-rail-label">
            <span>Conversation</span>
            <span className="ls-rail-sub">how you author & steer it</span>
          </div>

          {/* agent work strip — the board, demoted to a byproduct */}
          <div className="ls-agents">
            <div className="ls-agents-h">
              <Cpu size={12} strokeWidth={2.2} /> Agents against the spec
            </div>
            <div className="ls-units">
              <span className="ls-unit done">sign-in screen</span>
              <span className="ls-unit done">known-device check</span>
              <span className="ls-unit run">fallback path</span>
              <span className={"ls-unit " + (escalation.status === "open" ? "block" : "run")}>
                device-trust {escalation.status === "open" ? "· waiting on you" : "· resumed"}
              </span>
            </div>
          </div>

          <div className="ls-thread">
            {/* a settled exchange */}
            <div className="ls-msg you">
              <span className="ls-role"><User size={11} strokeWidth={2.4} /> you</span>
              People keep getting stuck logging back in. Make it one tap if we already know them.
            </div>
            <div className="ls-msg ai">
              <span className="ls-role"><Sparkles size={11} strokeWidth={2.2} /> draft</span>
              I shaped that into the intent and four constraints on the left. One thing you
              said in passing &mdash; "obviously not on a shared computer" &mdash; isn't captured yet.
            </div>

            {/* a proposal: correction over authoring */}
            {proposal === "pending" && (
              <div className="ls-card propose">
                <div className="ls-card-h">
                  <Sparkles size={13} strokeWidth={2.2} /> Proposed constraint
                </div>
                <p className="ls-card-body">
                  "On shared or public devices, never offer one-tap &mdash; require full sign-in."
                </p>
                <div className="ls-card-foot">
                  <span className="ls-card-hint">add to the spec?</span>
                  <div className="ls-card-btns">
                    <button className="ls-btn ghost" onClick={() => setProposal("dismissed")}>
                      Dismiss
                    </button>
                    <button className="ls-btn solid" onClick={acceptProposal}>
                      <Check size={13} strokeWidth={2.6} /> Accept
                    </button>
                  </div>
                </div>
              </div>
            )}
            {proposal === "accepted" && (
              <div className="ls-sys">
                <CornerDownRight size={12} strokeWidth={2.2} /> Added to Constraints. It's now part
                of what I build against.
              </div>
            )}
            {proposal === "dismissed" && (
              <div className="ls-sys">
                <CornerDownRight size={12} strokeWidth={2.2} /> Left out. I won't treat shared
                devices as a special case.
              </div>
            )}

            {/* an escalation: continuous, mid-flight, your judgment */}
            {escalation.status === "open" && (
              <div className="ls-card escalate">
                <div className="ls-card-h amber">
                  <GitBranch size={13} strokeWidth={2.2} /> Needs your judgment
                  <span className="ls-from">from the device-trust unit</span>
                </div>
                <p className="ls-card-body">
                  Building device trust, I found people switch between phone and laptop a lot.
                  Letting trust span devices is smoother but widens the attack surface. This is a
                  product call, not a technical one.
                </p>
                <p className="ls-rec">
                  <span>My recommendation:</span> per-device trust &mdash; it honours your security
                  constraint.
                </p>
                <div className="ls-card-btns wide">
                  <button className="ls-btn solid" onClick={() => resolveEscalation("perDevice")}>
                    Per-device <span className="ls-btn-sub">safer</span>
                  </button>
                  <button className="ls-btn ghost" onClick={() => resolveEscalation("synced")}>
                    Synced <span className="ls-btn-sub">smoother</span>
                  </button>
                </div>
              </div>
            )}
            {escalation.status === "resolved" && (
              <div className="ls-sys">
                <CornerDownRight size={12} strokeWidth={2.2} /> Logged as a Decision and a new
                acceptance criterion. The unit resumed against your call.
              </div>
            )}

            <div className="ls-compose">
              <span>Say what you mean&hellip;</span>
              <ArrowRight size={15} strokeWidth={2.2} />
            </div>
          </div>
        </aside>
      </div>

      <footer className="ls-foot">
        Two surfaces, one initiative &mdash; you speak on the right, it crystallises into the
        committed spec on the left. You react to its understanding instead of authoring from a
        blank page; it escalates the calls that are yours to make.
      </footer>
    </div>
  );
}

const css = `
.ls-root{
  --paper:#F2EEE4; --paper-2:#ECE5D6; --card:#F7F3EA;
  --ink:#221C15; --ink-soft:#5C5346; --ink-faint:#8C8170;
  --rule:#DAD1BF;
  --accent:#B5642A; --accent-deep:#8E4A1C;
  --ai:#456470; --ai-soft:#7E97A0;
  --good:#5E7A4F;
  --rail:#1B1712; --rail-2:#241E17; --rail-card:#2B241B;
  --rail-ink:#ECE4D5; --rail-soft:#A99E8B; --rail-rule:#3A3127;
  font-family:'IBM Plex Sans',sans-serif;
  color:var(--ink);
  background:
    radial-gradient(120% 90% at 12% 0%, #F7F3EA 0%, var(--paper) 46%, #EDE6D7 100%);
  min-height:100%;
  padding:30px clamp(16px,4vw,52px) 0;
  box-sizing:border-box;
  line-height:1.5;
}
.ls-root *{box-sizing:border-box;}

/* header */
.ls-head{max-width:1180px;margin:0 auto 22px;}
.ls-head-top{display:flex;justify-content:space-between;align-items:baseline;}
.ls-eyebrow{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--accent-deep);font-weight:600;}
.ls-meta{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--ink-faint);
  display:flex;align-items:center;gap:7px;}
.ls-dot-live{width:7px;height:7px;border-radius:50%;background:var(--good);
  box-shadow:0 0 0 0 rgba(94,122,79,.5);animation:pulse 2.4s infinite;}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(94,122,79,.45);}70%{box-shadow:0 0 0 6px rgba(94,122,79,0);}100%{box-shadow:0 0 0 0 rgba(94,122,79,0);}}
.ls-title{font-family:'Fraunces',serif;font-weight:500;font-size:clamp(26px,3.4vw,40px);
  line-height:1.08;letter-spacing:-.01em;margin:8px 0 18px;max-width:18ch;color:var(--ink);}
.ls-stepper{display:flex;flex-wrap:wrap;gap:4px;border-top:1px solid var(--rule);
  padding-top:14px;}
.ls-step{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.04em;
  color:var(--ink-faint);display:flex;align-items:center;gap:6px;padding:3px 12px 3px 4px;}
.ls-step-tick{width:8px;height:8px;border-radius:50%;border:1.5px solid var(--rule);}
.ls-step.done{color:var(--ink-soft);}
.ls-step.done .ls-step-tick{background:var(--ink-soft);border-color:var(--ink-soft);}
.ls-step.active{color:var(--accent-deep);font-weight:600;}
.ls-step.active .ls-step-tick{background:var(--accent);border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(181,100,42,.16);}

/* body */
.ls-body{max-width:1180px;margin:0 auto;display:flex;gap:26px;align-items:flex-start;
  padding-bottom:28px;}
.ls-spec,.ls-rail{opacity:0;transform:translateY(10px);
  animation:rise .6s cubic-bezier(.2,.7,.2,1) forwards;}
@keyframes rise{to{opacity:1;transform:none;}}

/* spec column */
.ls-spec{flex:1 1 60%;min-width:0;}
.ls-spec-label,.ls-rail-label{display:flex;align-items:baseline;gap:10px;margin-bottom:18px;}
.ls-spec-label>span:first-child{font-family:'Fraunces',serif;font-size:15px;font-weight:600;
  letter-spacing:.01em;}
.ls-spec-sub,.ls-rail-sub{font-family:'IBM Plex Mono',monospace;font-size:10.5px;
  color:var(--ink-faint);letter-spacing:.03em;}
.ls-block{opacity:0;transform:translateY(8px);animation:rise .55s cubic-bezier(.2,.7,.2,1) forwards;
  margin-bottom:24px;}
.ls-h{font-family:'IBM Plex Mono',monospace;font-size:11.5px;font-weight:600;
  text-transform:uppercase;letter-spacing:.13em;color:var(--ink-soft);
  display:flex;align-items:center;gap:8px;margin:0 0 11px;}
.ls-h.intent-h{color:var(--accent-deep);}
.ls-h-note{font-weight:400;text-transform:none;letter-spacing:.01em;color:var(--ink-faint);
  font-size:10.5px;margin-left:2px;}
.ls-intent{font-family:'Fraunces',serif;font-size:19px;line-height:1.5;font-weight:400;
  color:var(--ink);margin:0 0 10px;max-width:54ch;}
.ls-prov{display:inline-flex;align-items:center;gap:5px;font-family:'IBM Plex Mono',monospace;
  font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--accent-deep);}

.ls-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px;}
.ls-item{position:relative;background:var(--card);border:1px solid var(--rule);
  border-radius:7px;padding:11px 13px 11px 16px;font-size:13.5px;color:var(--ink);
  display:flex;gap:11px;align-items:flex-start;
  font-family:'IBM Plex Mono',monospace;line-height:1.45;letter-spacing:-.01em;}
.ls-bar{position:absolute;left:0;top:0;bottom:0;width:3px;border-radius:7px 0 0 7px;}
.ls-item.locked .ls-bar{background:var(--ink-soft);}
.ls-item.open{border-style:dashed;color:var(--ink-soft);}
.ls-item.open .ls-bar{background:var(--ai-soft);}
.ls-item.decision .ls-bar{background:var(--accent);}
.ls-rationale{display:block;color:var(--ink-faint);font-size:11.5px;margin-top:4px;
  font-style:normal;}
.ls-check{width:14px;height:14px;border-radius:4px;border:1.5px solid var(--good);
  flex:none;margin-top:1px;position:relative;}
.ls-item.crit{color:var(--ink-soft);}
.ls-item.is-new{animation:flash 1.5s ease-out;}
@keyframes flash{0%{background:#F3E2CF;border-color:var(--accent);}
  100%{background:var(--card);border-color:var(--rule);}}

/* rail */
.ls-rail{flex:1 1 40%;min-width:300px;background:var(--rail);border-radius:14px;
  padding:20px 18px;box-shadow:0 18px 40px -22px rgba(33,28,21,.6);
  position:sticky;top:24px;}
.ls-rail-label>span:first-child{font-family:'Fraunces',serif;font-size:15px;font-weight:600;
  color:var(--rail-ink);}
.ls-rail .ls-rail-sub{color:var(--rail-soft);}

.ls-agents{background:var(--rail-2);border:1px solid var(--rail-rule);border-radius:10px;
  padding:11px 12px;margin-bottom:16px;}
.ls-agents-h{font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;
  letter-spacing:.12em;color:var(--rail-soft);display:flex;align-items:center;gap:6px;
  margin-bottom:9px;}
.ls-units{display:flex;flex-wrap:wrap;gap:6px;}
.ls-unit{font-family:'IBM Plex Mono',monospace;font-size:10.5px;padding:4px 9px;border-radius:20px;
  color:var(--rail-soft);border:1px solid var(--rail-rule);letter-spacing:.01em;}
.ls-unit.done{color:#9DB68F;border-color:#3a4633;}
.ls-unit.done::before{content:"\\2713  ";color:var(--good);}
.ls-unit.run{color:#D9CDB7;border-color:#4a4030;}
.ls-unit.run::before{content:"\\25CF  ";color:var(--accent);}
.ls-unit.block{color:#E8B98C;border-color:var(--accent-deep);background:rgba(181,100,42,.1);}
.ls-unit.block::before{content:"\\25CB  ";color:var(--accent);}

.ls-thread{display:flex;flex-direction:column;gap:11px;}
.ls-msg{font-size:13px;line-height:1.5;color:var(--rail-ink);padding-left:2px;}
.ls-role{display:flex;align-items:center;gap:5px;font-family:'IBM Plex Mono',monospace;
  font-size:9.5px;text-transform:uppercase;letter-spacing:.13em;margin-bottom:4px;}
.ls-msg.you .ls-role{color:var(--rail-soft);}
.ls-msg.ai .ls-role{color:var(--ai-soft);}
.ls-msg.ai{color:var(--rail-soft);}

.ls-card{border-radius:10px;padding:13px;margin:3px 0;}
.ls-card.propose{background:var(--rail-card);border:1px solid #3b4d54;}
.ls-card.escalate{background:rgba(181,100,42,.09);border:1px solid var(--accent-deep);
  animation:glow 2.8s ease-in-out infinite;}
@keyframes glow{0%,100%{box-shadow:0 0 0 0 rgba(181,100,42,0);}
  50%{box-shadow:0 0 16px -2px rgba(181,100,42,.35);}}
.ls-card-h{font-family:'IBM Plex Mono',monospace;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.1em;color:var(--ai-soft);display:flex;align-items:center;gap:7px;
  margin-bottom:8px;}
.ls-card-h.amber{color:var(--accent);}
.ls-from{margin-left:auto;color:var(--rail-soft);text-transform:none;letter-spacing:0;
  font-size:9.5px;}
.ls-card-body{font-size:13px;line-height:1.5;color:var(--rail-ink);margin:0 0 10px;}
.ls-rec{font-size:12px;color:var(--rail-soft);margin:0 0 11px;line-height:1.45;}
.ls-rec span{color:var(--accent);font-family:'IBM Plex Mono',monospace;font-size:10px;
  text-transform:uppercase;letter-spacing:.08em;margin-right:5px;}
.ls-card-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;}
.ls-card-hint{font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--rail-soft);}
.ls-card-btns{display:flex;gap:8px;}
.ls-card-btns.wide{width:100%;}
.ls-card-btns.wide .ls-btn{flex:1;justify-content:center;}
.ls-btn{font-family:'IBM Plex Sans',sans-serif;font-size:12.5px;font-weight:500;
  border-radius:7px;padding:8px 13px;cursor:pointer;border:1px solid transparent;
  display:inline-flex;align-items:center;gap:6px;transition:all .16s ease;}
.ls-btn.solid{background:var(--accent);color:#1B1712;border-color:var(--accent);}
.ls-btn.solid:hover{background:#C9763A;transform:translateY(-1px);}
.ls-btn.ghost{background:transparent;color:var(--rail-ink);border-color:var(--rail-rule);}
.ls-btn.ghost:hover{border-color:var(--rail-soft);background:rgba(255,255,255,.04);}
.ls-btn-sub{font-family:'IBM Plex Mono',monospace;font-size:9px;text-transform:uppercase;
  letter-spacing:.08em;opacity:.7;}

.ls-sys{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--ai-soft);
  display:flex;align-items:flex-start;gap:7px;line-height:1.45;padding:2px 0 2px 2px;}
.ls-sys svg{flex:none;margin-top:2px;}

.ls-compose{margin-top:6px;border:1px dashed var(--rail-rule);border-radius:9px;
  padding:11px 13px;display:flex;justify-content:space-between;align-items:center;
  color:var(--rail-soft);font-size:13px;font-style:italic;}
.ls-compose svg{color:var(--ai-soft);}

.ls-foot{max-width:1180px;margin:0 auto;border-top:1px solid var(--rule);
  padding:16px 0 26px;font-size:12.5px;color:var(--ink-faint);line-height:1.55;
  max-width:74ch;}

@media(max-width:860px){
  .ls-body{flex-direction:column;}
  .ls-rail{position:static;width:100%;}
}
`;
