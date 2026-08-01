import { useApi } from "../App";
import { EditorQuery } from "../components/EditorQuery";
import { EvidenceBlock } from "../components/EvidenceBlock";
import { useApp } from "../store";

const SECTION_TITLES: Record<string, string> = {
  roleShapes: "Target role shapes",
  hardConstraints: "Hard constraints",
  preferredWork: "Preferred work",
  excludedWork: "Excluded work",
};

export function ProfileDraft() {
  const api = useApi();
  const { draft, setDraft, setStage, lockStage } = useApp();
  if (!draft) return null;
  const active = draft.questions.find((q) => q.answer === undefined);

  async function answer(value: string) {
    if (!active) return;
    setDraft(await api.answerQuestion(active.key, value));
  }

  const lists: [keyof typeof SECTION_TITLES, string[]][] = [
    ["roleShapes", draft.roleShapes],
    ["hardConstraints", draft.hardConstraints],
    ["preferredWork", draft.preferredWork],
    ["excludedWork", draft.excludedWork],
  ];

  return (
    <div>
      <h2>Profile draft</h2>
      {lists.map(([key, items]) => (
        <section key={key} className="section">
          <h3>{SECTION_TITLES[key]}</h3>
          <ul className="serif">{items.map((x) => <li key={x}>{x}</li>)}</ul>
          {active?.anchorSection === key && <EditorQuery question={active} onAnswer={answer} />}
        </section>
      ))}
      <section className="section">
        <h3>Evidence</h3>
        {draft.evidence.map((e) => <EvidenceBlock key={e.evidenceId} item={e} />)}
      </section>
      {!active && (
        <button className="pill pill-active"
          onClick={() => { lockStage("profile_draft"); setStage("awaiting_confirmation"); }}>
          Review thesis
        </button>
      )}
    </div>
  );
}
