import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { EvidenceBlock } from "../components/EvidenceBlock";
import { useApp } from "../store";

export function ThesisConfirm() {
  const api = useApi();
  const { draft, setStage, lockStage, setProfileVersion } = useApp();
  if (!draft) return null;

  async function confirm() {
    const { version } = await api.confirmThesis();
    setProfileVersion(version);
    lockStage("profile_draft");
    lockStage("awaiting_confirmation");
    setStage("watchlist");
  }

  return (
    <div>
      <h2>Your thesis</h2>
      <p className="serif">{draft.employerThesis}</p>
      <p className="serif">
        Role shapes: {draft.roleShapes.join("; ")}. Hard constraints:{" "}
        {draft.hardConstraints.join("; ")}.
      </p>
      <p className="serif">
        Preferred work: {draft.preferredWork.join("; ")}. Excluded work:{" "}
        {draft.excludedWork.join("; ")}.
      </p>
      <h3>Known gaps</h3>
      <p className="serif">{draft.knownGaps.join(". ")}.</p>
      <h3>Evidence</h3>
      {draft.evidence.map((e) => <EvidenceBlock key={e.evidenceId} item={e} />)}
      <p className="muted">
        Confirming locks this as an immutable version of your profile. Editing
        later starts a new version — nothing is rewritten behind you.
      </p>
      <ClayButton onClick={confirm}>Confirm thesis</ClayButton>
    </div>
  );
}
