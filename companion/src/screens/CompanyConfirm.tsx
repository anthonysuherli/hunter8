import { useEffect, useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { ConstraintChip } from "../components/ConstraintChip";
import { useApp } from "../store";
import type { CompanyRec } from "../domain";

const TIERS: { key: CompanyRec["tier"]; title: string; sub: string }[] = [
  { key: "core", title: "Core", sub: "Strongest fit to your role shapes and evidence." },
  { key: "adjacent", title: "Adjacent", sub: "Credible paths with one meaningful trade-off each." },
  { key: "exploratory", title: "Exploratory", sub: "Plausible, less certain — kept small on purpose." },
];

export function CompanyConfirm() {
  const api = useApi();
  const { companies, setCompanies, setStage, lockStage } = useApp();
  const [url, setUrl] = useState("");

  useEffect(() => {
    if (companies.length === 0) api.getCompanies().then(setCompanies);
  }, []);

  const active = companies.filter((c) => !c.removed && !c.pending);
  const pending = companies.filter((c) => !c.removed && c.pending);

  function toggle(name: string) {
    setCompanies(companies.map((c) => (c.name === name ? { ...c, removed: !c.removed } : c)));
  }

  async function add() {
    if (!url.trim()) return;
    setCompanies([...companies, await api.addCompany(url)]);
    setUrl("");
  }

  async function approve() {
    await api.approveCompanies(active.map((c) => c.name));
    lockStage("watchlist");
    setStage("discovering");
  }

  return (
    <div>
      <h2>Companies</h2>
      {TIERS.map(({ key, title, sub }) => {
        const rows = companies.filter((c) => c.tier === key);
        const kept = rows.filter((c) => !c.removed);
        return (
          <section key={key}>
            <h3 className="tier-heading">{title} <span className="muted">· {kept.length} of {rows.length}</span></h3>
            <p className="tier-sub">{sub}</p>
            {rows.map((c) => (
              <div key={c.name} className={`ledger-row ${c.removed ? "row-fade" : ""}`}>
                <div>
                  <strong>{c.name}</strong>{" "}
                  {c.pending && <ConstraintChip status="unknown" label="verifying…" />}
                  <div className="row-meta serif">{c.reason}</div>
                </div>
                {c.removed
                  ? <button className="pill" onClick={() => toggle(c.name)}>undo</button>
                  : <button className="remove-x" aria-label="✕" onClick={() => toggle(c.name)}>✕</button>}
              </div>
            ))}
          </section>
        );
      })}
      <div className="ledger-row">
        <input className="text-input" placeholder="Add a company careers URL…"
          value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="pill" onClick={add}>Add</button>
      </div>
      <p className="muted">{active.length} active · {pending.length} pending</p>
      <ClayButton onClick={approve}>Approve {active.length} companies →</ClayButton>
    </div>
  );
}
