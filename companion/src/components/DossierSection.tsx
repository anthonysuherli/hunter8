import type { ReactNode } from "react";
import type { Stage } from "../domain";

export function DossierSection({ stage, title, summary, state, children }:
  { stage: Stage; title: string; summary: string;
    state: "locked" | "live" | "hidden"; children: ReactNode }) {
  if (state === "hidden") return null;
  if (state === "locked") {
    return (
      <section className="section section-locked" data-stage={stage}>
        <h2>{title}</h2>
        <p className="section-summary">{summary}</p>
      </section>
    );
  }
  return (
    <section className="section" data-stage={stage}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
