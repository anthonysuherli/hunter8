import { createContext, useContext, useState } from "react";
import type { CompanionApi } from "./api";
import { DossierSection } from "./components/DossierSection";
import { RAIL_LABELS, SectionRail } from "./components/SectionRail";
import { makeFakeApi } from "./fakeApi";
import { useApp } from "./store";
import type { CompanyRec, Stage } from "./domain";
import type { ComponentType } from "react";
import { FrontDoor } from "./screens/FrontDoor";
import { Upload } from "./screens/Upload";
import { ProfileDraft } from "./screens/ProfileDraft";
import { ThesisConfirm } from "./screens/ThesisConfirm";
import { CompanyConfirm } from "./screens/CompanyConfirm";
import { Shortlist } from "./screens/Shortlist";
import { Account } from "./screens/Account";

export const ApiContext = createContext<CompanionApi>(makeFakeApi());
export const useApi = () => useContext(ApiContext);

export const SCREENS: Partial<Record<Stage, ComponentType>> = {
  front_door: FrontDoor,
  upload: Upload,
  profile_draft: ProfileDraft,
  awaiting_confirmation: ThesisConfirm,
  watchlist: CompanyConfirm,
  discovering: Shortlist,
  ready: Shortlist,
};

const RAIL_TITLES = Object.fromEntries(RAIL_LABELS) as Record<Stage, string>;

function lockedSummary(stage: Stage, profileVersion: number | null, companies: CompanyRec[]): string {
  switch (stage) {
    case "upload":
      return "Résumé parsed and profile drafted.";
    case "profile_draft":
      return "Queries resolved into the draft.";
    case "awaiting_confirmation":
      return `Thesis confirmed — version ${profileVersion}.`;
    case "watchlist":
      return `${companies.filter((c) => !c.removed && !c.pending).length} companies approved.`;
    case "discovering":
      return "Discovery complete.";
    default:
      return "";
  }
}

export function App() {
  const stage = useApp((s) => s.stage);
  const confirmedStages = useApp((s) => s.confirmedStages);
  const companies = useApp((s) => s.companies);
  const profileVersion = useApp((s) => s.profileVersion);
  const [showAccount, setShowAccount] = useState(false);
  const Screen = SCREENS[stage];

  if (stage === "front_door") {
    return <main className="dossier">{Screen ? <Screen /> : null}</main>;
  }

  return (
    <>
      <SectionRail />
      <main className="dossier">
        {stage !== "discovering" && (
          <p style={{ textAlign: "right" }}>
            <button className="pill" onClick={() => setShowAccount(!showAccount)}>Account</button>
          </p>
        )}
        {showAccount ? <Account /> : (
          <>
            {RAIL_LABELS.filter(([s]) => confirmedStages.includes(s)).map(([s]) => (
              <DossierSection key={s} stage={s} title={RAIL_TITLES[s]}
                summary={lockedSummary(s, profileVersion, companies)} state="locked">
                {null}
              </DossierSection>
            ))}
            {Screen ? <Screen /> : null}
          </>
        )}
      </main>
    </>
  );
}
