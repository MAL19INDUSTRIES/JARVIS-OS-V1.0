"use client";

import { FormEvent, useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type Session } from "@/lib/api";

export function AuthScreen({ onSession }: { onSession: (session: Session) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const session = await api<Session>(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({
          email: data.get("email"),
          password: data.get("password"),
          ...(mode === "signup" ? { display_name: data.get("display_name") } : {}),
        }),
      });
      onSession(session);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="entry-shell">
      <section className="entry-identity" aria-labelledby="entry-title">
        <div className="wordmark"><span className="wordmark-mark">J</span> JARVIS</div>
        <div className="entry-reactor" aria-hidden="true"><span /></div>
        <p className="eyebrow">Personal intelligence system</p>
        <h1 id="entry-title">Command without friction.</h1>
        <p className="entry-copy">
          Voice, text, research, and creation share one continuous operational context.
        </p>
        <div className="trust-line"><ShieldCheck size={16} /> Your Gemini key is encrypted before storage.</div>
      </section>

      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="mode-switch" role="tablist" aria-label="Account access">
          <button role="tab" aria-selected={mode === "login"} onClick={() => setMode("login")}>Sign in</button>
          <button role="tab" aria-selected={mode === "signup"} onClick={() => setMode("signup")}>Create account</button>
        </div>
        <div>
          <p className="section-index">ACCESS / 01</p>
          <h2 id="auth-title">{mode === "login" ? "Resume session" : "Establish identity"}</h2>
        </div>
        <form onSubmit={submit} className="auth-form">
          {mode === "signup" && (
            <label>Display name<Input name="display_name" autoComplete="name" required placeholder="How JARVIS should address you" /></label>
          )}
          <label>Email<Input name="email" type="email" autoComplete="email" required placeholder="operator@example.com" /></label>
          <label>Password<Input name="password" type="password" minLength={10} autoComplete={mode === "login" ? "current-password" : "new-password"} required placeholder="At least 10 characters" /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <Button type="submit" disabled={pending} className="w-full">
            {pending ? "Authorizing" : mode === "login" ? "Enter JARVIS" : "Create secure account"}
            {!pending && <ArrowRight size={16} />}
          </Button>
        </form>
      </section>
    </main>
  );
}
