"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Activity, ArrowUp, LogOut, Mic, MicOff, Radio, RefreshCw, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Reactor } from "@/components/reactor";
import { useJarvisSocket } from "@/hooks/use-jarvis-socket";
import { api, type Action, type User } from "@/lib/api";

export function JarvisConsole({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const live = useJarvisSocket();
  const [actions, setActions] = useState<Action[]>([]);
  const [draft, setDraft] = useState("");
  const [transitionMode, setTransitionMode] = useState<"ultron" | "atlas" | null>(null);
  const logEnd = useRef<HTMLDivElement>(null);
  const previousMode = useRef(live.mode);

  useEffect(() => { api<{ actions: Action[] }>("/actions").then((data) => setActions(data.actions)).catch(() => undefined); }, []);
  useEffect(() => { logEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [live.messages]);
  useEffect(() => {
    const prior = previousMode.current;
    previousMode.current = live.mode;
    if (prior === live.mode || live.mode === "jarvis") return;
    setTransitionMode(live.mode);
    const timer = window.setTimeout(() => setTransitionMode(null), 1100);
    return () => window.clearTimeout(timer);
  }, [live.mode]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await live.sendText(draft)) setDraft("");
  }

  const connected = !["OFFLINE", "CONNECTING"].includes(live.state);
  const modeName = live.mode.toUpperCase();
  const targetModeName = live.targetMode.toUpperCase();
  const controlsReady = connected && !live.modeSwitching;
  const modeOrder = ["jarvis", "ultron", "atlas"] as const;
  const nextMode = modeOrder[(modeOrder.indexOf(live.mode) + 1) % modeOrder.length];

  return (
    <main className={`console-shell mode-${live.mode}`}>
      {transitionMode && <div className={`mode-transition transition-${transitionMode}`} aria-live="assertive"><b>{transitionMode === "ultron" ? "SERIOUS MODE" : "PORTAL CONTROL"}</b><span>{transitionMode.toUpperCase()} ONLINE</span></div>}
      <header className="console-header">
        <div className="wordmark"><span className="wordmark-mark">{modeName[0]}</span> {modeName} <small>{live.mode === "ultron" ? "SERIOUS MODE" : live.mode === "atlas" ? "PORTAL CONTROL" : "MARK XXXIX"}</small></div>
        <div className="header-state" aria-live="polite">
          {connected ? <Wifi size={14} /> : <WifiOff size={14} />}
          <span>{live.state}</span>
        </div>
        <div className="operator-menu"><span>{user.display_name}</span><Button variant="ghost" size="sm" disabled={!controlsReady} onClick={() => live.switchMode(nextMode)}><RefreshCw size={14} /> {live.modeSwitching ? `Switching · ${targetModeName}` : `Switch mode · ${modeName}`}</Button><Button variant="ghost" size="sm" onClick={onSignOut}><LogOut size={14} /> Sign out</Button></div>
      </header>

      <div className="console-grid">
        <section className="mission-log" aria-labelledby="log-title">
          <div className="panel-heading"><div><p className="section-index">CHANNEL / PRIMARY</p><h2 id="log-title">Mission log</h2></div><Radio size={17} /></div>
          <div className="message-stream" aria-live="polite">
            {live.messages.length === 0 ? (
              <div className="empty-log"><span>Awaiting first instruction</span><p>Speak naturally or type a request. JARVIS will keep the same context across both inputs.</p></div>
            ) : live.messages.map((message) => (
              <article key={message.id} className={`message message-${message.role}`}>
                <div><span>{message.role === "assistant" ? modeName : message.role === "user" ? "YOU" : "SYSTEM"}</span><time>{new Date(message.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>
                <p>{message.content}</p>
              </article>
            ))}
            <div ref={logEnd} />
          </div>
        </section>

        <section className="command-stage" aria-labelledby="command-title">
          <div className="state-caption"><span className="state-dot" /> LIVE CORE / {live.modeSwitching ? `SWITCHING TO ${targetModeName}` : live.state}</div>
          <Reactor state={live.state} mode={live.mode} />
          <div className="voice-caption">
            <h1 id="command-title">{live.modeSwitching ? "Changing persona" : live.state === "SPEAKING" ? "Responding" : live.state === "THINKING" ? "Reasoning" : live.state === "LISTENING" ? "Listening" : live.state === "MUTED" ? "Voice paused" : "Establishing link"}</h1>
            <p>{live.modeSwitching ? `The previous voice is silent. Connecting ${targetModeName}.` : live.transcript || (live.micActive ? "Microphone is live. Speak when ready." : "Text channel ready. Enable the microphone for voice.")}</p>
          </div>
          <form className="command-composer" onSubmit={submit}>
            <textarea value={draft} disabled={!controlsReady} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={live.modeSwitching ? `Connecting ${targetModeName}` : "Issue an instruction"} aria-label={`Message ${modeName}`} rows={2} />
            <Button type="button" variant={live.micActive ? "danger" : "secondary"} size="icon" disabled={!controlsReady} aria-label={live.micActive ? "Mute microphone" : "Enable microphone"} onClick={() => live.micActive ? live.stopMic() : live.startMic()}>
              {live.micActive ? <MicOff size={18} /> : <Mic size={18} />}
            </Button>
            <Button type="submit" size="icon" aria-label="Send instruction" disabled={!draft.trim() || !controlsReady}><ArrowUp size={18} /></Button>
          </form>
          {live.error && <p className="console-error" role="alert">{live.error}</p>}
        </section>

        <aside className="systems-panel" aria-labelledby="systems-title">
          <div className="panel-heading"><div><p className="section-index">SYSTEM / LIVE</p><h2 id="systems-title">Operational state</h2></div><Activity size={17} /></div>
          <dl className="status-readout">
            <div><dt>Gemini Live</dt><dd data-on={connected}>{connected ? "LINKED" : "STANDBY"}</dd></div>
            <div><dt>Voice input</dt><dd data-on={live.micActive}>{live.micActive ? "OPEN" : "MUTED"}</dd></div>
            <div><dt>Tenant boundary</dt><dd data-on="true"><ShieldCheck size={13} /> ISOLATED</dd></div>
          </dl>
          {live.progress && (
            <section className="real-progress" aria-label={`${live.progress.kind} progress`}>
              <div><span>{live.progress.label}</span><b>{Math.round(live.progress.percent)}%</b></div>
              <div className="progress-track"><span style={{ transform: `scaleX(${live.progress.percent / 100})` }} /></div>
              <p>{live.progress.phase}</p>
            </section>
          )}
          <section className="capability-index">
            <div className="capability-heading"><span>Cloud actions</span><b>{String(actions.length).padStart(2, "0")}</b></div>
            <ul>
              {actions.map((action) => <li key={action.name}><span>{action.name.replaceAll("_", " ")}</span><i /></li>)}
            </ul>
          </section>
        </aside>
      </div>
      <footer className="creator-mark" aria-label="Created by AMDCREATIONZ, GitHub MAL19INDUSTRIES">
        Creation by AMDCREATIONZ <span>·</span> <a href="https://github.com/MAL19INDUSTRIES" target="_blank" rel="noreferrer">GitHub MAL19INDUSTRIES</a> <span>·</span> <a href="https://www.instagram.com/AMDCREATIONZ/" target="_blank" rel="noreferrer">Instagram @AMDCREATIONZ</a>
      </footer>
    </main>
  );
}
