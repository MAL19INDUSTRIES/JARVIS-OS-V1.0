"use client";

import { FormEvent, useState } from "react";
import { Check, ExternalLink, KeyRound, LockKeyhole } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type User } from "@/lib/api";

export function Onboarding({ user, onComplete, onSignOut }: { user: User; onComplete: () => void; onSignOut: () => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await api("/me/gemini-key", {
        method: "POST",
        body: JSON.stringify({ api_key: data.get("api_key"), validate: true }),
      });
      onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The key could not be verified");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="onboarding-shell">
      <header className="onboarding-header">
        <div className="wordmark"><span className="wordmark-mark">J</span> JARVIS</div>
        <button className="text-button" onClick={onSignOut}>Use another account</button>
      </header>
      <section className="onboarding-sequence">
        <div className="sequence-rail" aria-label="Setup progress">
          <div className="sequence-step complete"><span><Check size={14} /></span><div><b>Identity</b><small>{user.email}</small></div></div>
          <div className="sequence-line" />
          <div className="sequence-step active"><span>02</span><div><b>Gemini Live</b><small>Private model access</small></div></div>
        </div>
        <div className="key-stage">
          <p className="section-index">INITIALIZATION / 02</p>
          <KeyRound className="stage-icon" size={28} />
          <h1>Connect your intelligence layer.</h1>
          <p>
            JARVIS uses your Gemini API key for live voice and reasoning. The key is encrypted at rest and never returned to the browser.
          </p>
          <form onSubmit={submit} className="key-form">
            <label>Gemini API key<Input name="api_key" type="password" autoComplete="off" required minLength={20} placeholder="Paste the key from Google AI Studio" /></label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <Button disabled={pending} type="submit" className="w-full">
              <LockKeyhole size={16} /> {pending ? "Verifying with Gemini" : "Encrypt and initialize"}
            </Button>
          </form>
          <a className="external-link" href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer">
            Open Google AI Studio <ExternalLink size={14} />
          </a>
        </div>
      </section>
    </main>
  );
}
