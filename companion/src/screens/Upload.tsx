import { useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { useApp } from "../store";

export function Upload() {
  const api = useApi();
  const { setStage, lockStage, setDraft } = useApp();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function extract() {
    setError(null);
    const res = await api.uploadResume(text);
    if (!res.ok) { setError(res.reason); return; }
    setDraft(res.draft);
    lockStage("upload");
    setStage("profile_draft");
  }

  return (
    <div>
      <h2>Résumé</h2>
      <label htmlFor="resume-textarea">Paste your résumé text here</label>
      <textarea id="resume-textarea" className="text-input" rows={10}
        placeholder="paste your résumé text here" value={text}
        onChange={(e) => setText(e.target.value)} />
      <p className="muted">
        Extracted text is sent to the configured model provider to draft your
        profile. The raw document never leaves the parser.
      </p>
      <ClayButton onClick={extract}>Extract profile</ClayButton>
      {error && <p className="inline-error">{error} — fix the text and retry.</p>}
    </div>
  );
}
