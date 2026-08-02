import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiContext } from "../src/App";
import { App } from "../src/App";
import { makeFakeApi } from "../src/fakeApi";
import { useApp } from "../src/store";

function renderWith(api = makeFakeApi()) {
  return render(<ApiContext.Provider value={api}><App /></ApiContext.Provider>);
}

beforeEach(() => {
  useApp.setState({
    stage: "discovering", discovery: [], shortlist: [], emptyReason: null,
    confirmedStages: ["upload", "profile_draft", "awaiting_confirmation", "watchlist"],
  });
});

describe("discovery fill-in", () => {
  it("keeps a failed company visible with its reason, then shows ranked results", async () => {
    renderWith(makeFakeApi({ failCompany: "Databricks" }));
    expect(await screen.findByText(/source error: board unreachable/)).toBeInTheDocument();
    expect(await screen.findByText("Senior Developer, AI Software Engineer")).toBeInTheDocument();
    expect(useApp.getState().stage).toBe("ready");
    // the failed source stays visible above the results
    expect(screen.getByText(/source error: board unreachable/)).toBeInTheDocument();
  });

  it("explains an empty shortlist", async () => {
    renderWith(makeFakeApi({ emptyShortlist: true }));
    expect(await screen.findByText(/No postings matched/)).toBeInTheDocument();
  });
});

describe("shortlist ledger", () => {
  it("opens one row at a time with evidence, unknowns, and only three actions", async () => {
    renderWith();
    const title = await screen.findByText("Senior Developer, AI Software Engineer");
    await userEvent.click(title);
    const open = title.closest(".ledger-item")!;
    expect(within(open as HTMLElement).getByText(/Built 12-agent runtime/)).toBeInTheDocument();
    expect(within(open as HTMLElement).getByText(/Not stated in posting/)).toBeInTheDocument();
    expect(within(open as HTMLElement).getByRole("link", { name: /open original/i }))
      .toHaveAttribute("href", "https://jobs.workable.com/view/nb-1");
    // second click on another row closes the first
    await userEvent.click(screen.getByText("Principal Engineer, GenAI Team"));
    expect(screen.queryByText(/Built 12-agent runtime/)).not.toBeInTheDocument();
  });

  it("records feedback on the open row", async () => {
    const api = makeFakeApi();
    const spy = vi.spyOn(api, "sendFeedback");
    renderWith(api);
    await userEvent.click(await screen.findByText("Senior Developer, AI Software Engineer"));
    await userEvent.click(screen.getByRole("button", { name: "Useful" }));
    expect(spy).toHaveBeenCalledWith("https://jobs.workable.com/view/nb-1", "useful");
  });
});
