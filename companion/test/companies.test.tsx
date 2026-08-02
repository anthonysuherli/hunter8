import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../src/App";
import { useApp } from "../src/store";

beforeEach(() => {
  useApp.setState({
    stage: "watchlist", companies: [], discovery: [],
    confirmedStages: ["upload", "profile_draft", "awaiting_confirmation"],
  });
});

describe("company confirmation", () => {
  it("renders three tier sections with counts and reasons", async () => {
    render(<App />);
    expect(await screen.findByText(/^Core/)).toBeInTheDocument();
    expect(screen.getByText(/^Adjacent/)).toBeInTheDocument();
    expect(screen.getByText(/^Exploratory/)).toBeInTheDocument();
    expect(screen.getByText(/MCP \+ RAG explicitly/)).toBeInTheDocument();
  });

  it("marks unverified companies pending and excludes them from the active count", async () => {
    render(<App />);
    const row = (await screen.findByText("Norm Ai")).closest(".ledger-row")!;
    expect(within(row as HTMLElement).getByText(/verifying/)).toHaveClass("chip-unknown");
    expect(screen.getByText(/5 active · 1 pending/)).toBeInTheDocument();
  });

  it("remove is undoable and adjusts the approve count", async () => {
    render(<App />);
    const row = (await screen.findByText("Notion")).closest(".ledger-row")!;
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: "✕" }));
    expect(screen.getByText(/approve 4 companies/i)).toBeInTheDocument();
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: /undo/i }));
    expect(screen.getByText(/approve 5 companies/i)).toBeInTheDocument();
  });

  it("adding a URL appends a pending row", async () => {
    render(<App />);
    await screen.findByText("Hebbia");
    await userEvent.type(screen.getByPlaceholderText(/careers url/i), "https://ramp.com/careers");
    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    const row = (await screen.findByText("ramp")).closest(".ledger-row")!;
    expect(within(row as HTMLElement).getByText(/verifying/)).toBeInTheDocument();
  });

  it("approval advances to discovering", async () => {
    render(<App />);
    await screen.findByText("Hebbia");
    await userEvent.click(screen.getByRole("button", { name: /approve 5 companies/i }));
    expect(useApp.getState().stage).toBe("discovering");
  });
});
