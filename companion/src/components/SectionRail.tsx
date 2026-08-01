import type { Stage } from "../domain";
import { useApp } from "../store";

export const RAIL_LABELS: [Stage, string][] = [
  ["upload", "Résumé"],
  ["profile_draft", "Profile"],
  ["awaiting_confirmation", "Thesis"],
  ["watchlist", "Companies"],
  ["discovering", "Discovery"],
  ["ready", "Shortlist"],
];

export function SectionRail() {
  const { stage, confirmedStages } = useApp();
  return (
    <nav className="rail">
      {RAIL_LABELS.map(([s, label]) => (
        <div key={s}
          className={`rail-item ${s === stage ? "rail-live" : confirmedStages.includes(s) ? "rail-done" : ""}`}>
          {label}
        </div>
      ))}
    </nav>
  );
}
