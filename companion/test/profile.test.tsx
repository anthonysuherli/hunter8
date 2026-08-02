import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ApiContext } from "../src/App";
import { App } from "../src/App";
import type { CompanionApi } from "../src/api";
import type { ProfileDraftData } from "../src/domain";
import { makeFakeApi } from "../src/fakeApi";
import { useApp } from "../src/store";

async function seedDraft() {
  const api = makeFakeApi();
  const up = await api.uploadResume("resume");
  if (!up.ok) throw new Error("seed failed");
  useApp.setState({
    stage: "profile_draft", confirmedStages: ["upload"],
    draft: up.draft, profileVersion: null,
  });
}

describe("profile draft with editor's queries", () => {
  beforeEach(seedDraft);

  it("shows one active query with its reason as the anchor", () => {
    render(<App />);
    expect(screen.getByText(/Location constraint unclear/)).toBeInTheDocument();
    expect(screen.queryByText(/Work authorization affects/)).not.toBeInTheDocument();
  });

  it("resolves a query into the draft and surfaces the next one", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/your answer/i), "NYC or remote");
    await userEvent.click(screen.getByRole("button", { name: /^answer$/i }));
    expect(await screen.findByText(/Work authorization affects/)).toBeInTheDocument();
    expect(screen.getByText("NYC or remote")).toBeInTheDocument();
  });

  it("offers Review thesis only when all queries are answered", async () => {
    render(<App />);
    expect(screen.queryByRole("button", { name: /review thesis/i })).not.toBeInTheDocument();
    for (const answer of ["NYC or remote", "no sponsorship needed"]) {
      await userEvent.type(screen.getByPlaceholderText(/your answer/i), answer);
      await userEvent.click(screen.getByRole("button", { name: /^answer$/i }));
    }
    await userEvent.click(await screen.findByRole("button", { name: /review thesis/i }));
    expect(useApp.getState().stage).toBe("awaiting_confirmation");
  });
});

describe("profile draft with an unanchored query", () => {
  it("falls back to rendering after Evidence instead of dead-ending", async () => {
    const draft: ProfileDraftData = {
      roleShapes: ["Agentic systems engineer"],
      hardConstraints: ["New York or remote (US)"],
      preferredWork: [],
      excludedWork: [],
      evidence: [],
      knownGaps: [],
      employerThesis: "",
      questions: [
        { key: "thesis", prompt: "What's the employer thesis?",
          reason: "Employer thesis unclear", anchorSection: "employerThesis" },
      ],
    };
    const api: CompanionApi = {
      ...makeFakeApi(),
      async answerQuestion(key, answer) {
        return { ...draft, questions: draft.questions.map((q) => (q.key === key ? { ...q, answer } : q)) };
      },
    };
    useApp.setState({ stage: "profile_draft", confirmedStages: ["upload"], draft, profileVersion: null });
    render(<ApiContext.Provider value={api}><App /></ApiContext.Provider>);
    expect(screen.getByText(/Employer thesis unclear/)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/your answer/i), "AI systems roles near investment decisions.");
    await userEvent.click(screen.getByRole("button", { name: /^answer$/i }));
    expect(await screen.findByRole("button", { name: /review thesis/i })).toBeInTheDocument();
  });
});

describe("thesis confirmation", () => {
  beforeEach(async () => {
    await seedDraft();
    useApp.setState({ stage: "awaiting_confirmation" });
  });

  it("states known gaps in prose and confirms into an immutable version", async () => {
    render(<App />);
    expect(screen.getByText(/Work authorization unstated/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /confirm thesis/i }));
    await screen.findByRole("button", { name: /approve.*companies/i });
    expect(useApp.getState().profileVersion).toBe(1);
    expect(useApp.getState().stage).toBe("watchlist");
    expect(useApp.getState().confirmedStages).toEqual(
      expect.arrayContaining(["profile_draft", "awaiting_confirmation"]),
    );
  });
});
