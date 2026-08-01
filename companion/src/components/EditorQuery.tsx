import { useState } from "react";
import type { ProfileQuestion } from "../domain";

export function EditorQuery({ question, onAnswer }:
  { question: ProfileQuestion; onAnswer: (answer: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <aside className="query">
      <p className="query-reason">{question.reason}</p>
      <p className="serif">{question.prompt}</p>
      <input className="text-input" placeholder="your answer" value={value}
        onChange={(e) => setValue(e.target.value)} />
      <p><button className="pill" onClick={() => value.trim() && onAnswer(value)}>Answer</button></p>
    </aside>
  );
}
