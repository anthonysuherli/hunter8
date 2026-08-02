import { create } from "zustand";
import type { CompanyRec, DiscoveryRow, ProfileDraftData, ShortlistItem, Stage } from "./domain";

interface AppState {
  stage: Stage;
  confirmedStages: Stage[];
  draft: ProfileDraftData | null;
  profileVersion: number | null;
  companies: CompanyRec[];
  discovery: DiscoveryRow[];
  shortlist: ShortlistItem[];
  emptyReason: string | null;
  setStage: (s: Stage) => void;
  lockStage: (s: Stage) => void;
  setDraft: (d: ProfileDraftData) => void;
  setProfileVersion: (v: number) => void;
  setCompanies: (c: CompanyRec[]) => void;
  setDiscovery: (d: DiscoveryRow[]) => void;
  setShortlist: (s: ShortlistItem[]) => void;
  setEmptyReason: (r: string | null) => void;
}

export const useApp = create<AppState>((set) => ({
  stage: "front_door",
  confirmedStages: [],
  draft: null,
  profileVersion: null,
  companies: [],
  discovery: [],
  shortlist: [],
  emptyReason: null,
  setStage: (stage) => set({ stage }),
  lockStage: (s) => set((st) => ({
    confirmedStages: st.confirmedStages.includes(s) ? st.confirmedStages : [...st.confirmedStages, s],
  })),
  setDraft: (draft) => set({ draft }),
  setProfileVersion: (profileVersion) => set({ profileVersion }),
  setCompanies: (companies) => set({ companies }),
  setDiscovery: (discovery) => set({ discovery }),
  setShortlist: (shortlist) => set({ shortlist }),
  setEmptyReason: (emptyReason) => set({ emptyReason }),
}));
