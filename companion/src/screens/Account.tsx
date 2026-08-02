import { useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";

export function Account() {
  const api = useApi();
  const [typed, setTyped] = useState("");
  const [state, setState] = useState<"idle" | "done" | "delete_error">("idle");

  async function destroy() {
    const res = await api.deleteAccount();
    setState(res.state);
  }

  if (state === "done") return <p className="serif">Deleted. Nothing of yours remains.</p>;

  return (
    <div>
      <h2>Delete account</h2>
      <p className="serif">
        This permanently removes your résumé-derived profile, evidence, watchlist,
        shortlist, feedback, and account. There is no undo.
      </p>
      <input className="text-input" placeholder="type delete to confirm"
        value={typed} onChange={(e) => setTyped(e.target.value)} />
      <p><ClayButton disabled={typed !== "delete"} onClick={destroy}>Delete everything</ClayButton></p>
      {state === "delete_error" && (
        <p className="inline-error">Deletion did not complete. It is safe to retry — nothing was reported deleted that wasn't.</p>
      )}
    </div>
  );
}
