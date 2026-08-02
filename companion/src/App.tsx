import { createContext, useContext, useState } from "react";
import type { CompanionApi } from "./api";
import { SectionRail } from "./components/SectionRail";
import { makeFakeApi } from "./fakeApi";
import { useApp } from "./store";
import type { Stage } from "./domain";
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

// Screens register here as later tasks land; front_door is Task 5.
export const SCREENS: Partial<Record<Stage, ComponentType>> = {
  front_door: FrontDoor,
  upload: Upload,
  profile_draft: ProfileDraft,
  awaiting_confirmation: ThesisConfirm,
  watchlist: CompanyConfirm,
  discovering: Shortlist,
  ready: Shortlist,
};

export function App() {
  const stage = useApp((s) => s.stage);
  const [showAccount, setShowAccount] = useState(false);
  const Screen = SCREENS[stage];
  return (
    <>
      {stage !== "front_door" && <SectionRail />}
      <main className="dossier">
        {stage !== "front_door" && (
          <p style={{ textAlign: "right" }}>
            <button className="pill" onClick={() => setShowAccount(!showAccount)}>Account</button>
          </p>
        )}
        {showAccount ? <Account /> : Screen ? <Screen /> : null}
      </main>
    </>
  );
}
