import { useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { useApp } from "../store";

export function FrontDoor() {
  const api = useApi();
  const setStage = useApp((s) => s.setStage);
  const [email, setEmail] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);

  async function submit() {
    const res = await api.signIn(email);
    if (res.ok) setStage("upload");
    else setRefusal(res.refusal);
  }

  return (
    <div>
      <h1 className="display">A career dossier, <u>written from your evidence</u>.</h1>
      <p className="serif">
        Upload a résumé. Confirm one career thesis. Receive an evidence-ranked
        shortlist of live roles. It never applies on your behalf.
      </p>
      <label htmlFor="email-input">Email address</label>
      <input id="email-input" className="text-input" placeholder="email address" value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <p><ClayButton onClick={submit}>Continue</ClayButton></p>
      <p>
        <button className="pill" disabled>Sign in with LinkedIn</button>
        <span className="muted"> sign-in only, we never read your profile</span>
      </p>
      {refusal && <p className="refusal">{refusal}</p>}
    </div>
  );
}
