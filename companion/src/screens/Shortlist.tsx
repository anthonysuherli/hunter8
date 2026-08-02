import { useEffect, useState } from "react";
import { useApi } from "../App";
import { ConstraintChip } from "../components/ConstraintChip";
import { EvidenceBlock } from "../components/EvidenceBlock";
import { FeedbackPills } from "../components/FeedbackPills";
import { overallStatus } from "../domain";
import { useApp } from "../store";

export function Shortlist() {
  const api = useApi();
  const { stage, discovery, setDiscovery, shortlist, setShortlist,
    emptyReason, setEmptyReason, setStage, lockStage } = useApp();
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (stage !== "discovering") return;
    const unsub = api.subscribeDiscovery(async (rows, done) => {
      setDiscovery(rows);
      if (done) {
        const res = await api.getShortlist();
        setShortlist(res.items);
        setEmptyReason(res.emptyReason ?? null);
        lockStage("discovering");
        setStage("ready");
      }
    });
    return unsub;
  }, [stage]);

  const failures = discovery.filter((r) => r.state === "source_error");
  const total = discovery.length;
  const done = discovery.filter((r) => r.state === "assessed" || r.state === "source_error").length;
  const heading = stage === "discovering" && total > 0
    ? `Shortlist — discovering · ${done}/${total} boards read`
    : "Shortlist";

  return (
    <div>
      <h2>{heading}</h2>
      {stage === "discovering" && (
        <div>
          {discovery.map((r) => (
            <div key={r.company} className={`ledger-row ${r.state === "assessed" ? "" : "row-fade"}`}>
              <strong>{r.company}</strong>
              <span className={`row-meta ${r.state === "source_error" ? "inline-error" : ""}`}>{r.detail}</span>
            </div>
          ))}
        </div>
      )}
      {stage === "ready" && (
        <div>
          {failures.map((r) => (
            <div key={r.company} className="ledger-row row-fade">
              <strong>{r.company}</strong>
              <span className="row-meta inline-error">{r.detail}</span>
            </div>
          ))}
          {emptyReason && <p className="serif">{emptyReason}</p>}
          {shortlist.map((item) => {
            const isOpen = open === item.postingUrl;
            return (
              <div key={item.postingUrl} className="ledger-item">
                <div className="ledger-row" role="button" tabIndex={0}
                  onClick={() => setOpen(isOpen ? null : item.postingUrl)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setOpen(isOpen ? null : item.postingUrl);
                    }
                  }}>
                  <div>
                    <strong>{item.title}</strong>
                    <div className="row-meta">
                      {item.company} · {item.location} · {item.freshness} · {item.source}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <span className={`row-score ${isOpen ? "row-score-open" : ""}`}>{item.score}</span>
                    <div className="row-meta">constraints: {overallStatus(item.constraintResults)}</div>
                  </div>
                </div>
                {isOpen && (
                  <div className="ledger-open">
                    <h3>Why this fits</h3>
                    <p className="serif">{item.whyFit}</p>
                    {item.evidence.map((e) => <EvidenceBlock key={e.evidenceId} item={e} />)}
                    {(item.tradeoffs.length > 0 || item.uncertainties.length > 0 ||
                      item.constraintResults.some((c) => c.status !== "pass")) && (
                      <>
                        <h3>Trade-offs &amp; unknowns</h3>
                        <p className="serif">{item.tradeoffs.join(" ")}</p>
                        <p>
                          {item.constraintResults.filter((c) => c.status !== "pass").map((c) => (
                            <ConstraintChip key={c.constraint} status={c.status}
                              label={`${c.constraint}: ${c.explanation}`} />
                          ))}
                          {item.uncertainties.map((u) => (
                            <ConstraintChip key={u} status="unknown" label={u} />
                          ))}
                        </p>
                      </>
                    )}
                    <p>
                      <FeedbackPills value={item.feedback}
                        onChange={async (v) => {
                          await api.sendFeedback(item.postingUrl, v);
                          setShortlist(shortlist.map((s) =>
                            s.postingUrl === item.postingUrl ? { ...s, feedback: v } : s));
                        }} />
                      <a className="row-meta" style={{ color: "var(--accent)", float: "right" }}
                        href={item.postingUrl} target="_blank" rel="noreferrer">
                        Open original ↗
                      </a>
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
