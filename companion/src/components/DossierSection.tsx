import type { ReactNode } from "react";
import type { Stage } from "../domain";

export function DossierSection({ title, summary, state, children }:
  { stage: Stage; title: string; summary: string;
    state: "locked" | "live" | "hidden"; children: ReactNode }) {
  if (state === "hidden") return null;
  if (state === "locked") {
    return (
      <section className="section section-locked">
        <h2>{title}</h2>
        <p className="section-summary">{summary}</p>
      </section>
    );
  }
  return (
    <section className="section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
