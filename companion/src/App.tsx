import { createContext, useContext } from "react";
import type { CompanionApi } from "./api";
import { SectionRail } from "./components/SectionRail";
import { makeFakeApi } from "./fakeApi";
import { useApp } from "./store";
import type { Stage } from "./domain";
import type { ComponentType } from "react";
import { FrontDoor } from "./screens/FrontDoor";
import { Upload } from "./screens/Upload";

export const ApiContext = createContext<CompanionApi>(makeFakeApi());
export const useApi = () => useContext(ApiContext);

// Screens register here as later tasks land; front_door is Task 5.
export const SCREENS: Partial<Record<Stage, ComponentType>> = {
  front_door: FrontDoor,
  upload: Upload,
};

export function App() {
  const stage = useApp((s) => s.stage);
  const Screen = SCREENS[stage];
  return (
    <>
      {stage !== "front_door" && <SectionRail />}
      <main className="dossier">{Screen ? <Screen /> : null}</main>
    </>
  );
}
