import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../src/App";
import { useApp } from "../src/store";

beforeEach(() => {
  useApp.setState({ stage: "front_door", confirmedStages: [], draft: null });
});

describe("front door", () => {
  it("shows the three-line promise and both sign-in controls", () => {
    render(<App />);
    expect(screen.getByText(/never applies on your behalf/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument();
    expect(screen.getByText(/sign-in only, we never read your profile/i)).toBeInTheDocument();
  });

  it("refuses an uninvited email inline without advancing", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/email/i), "stranger@example.com");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/invite-only/i)).toBeInTheDocument();
    expect(useApp.getState().stage).toBe("front_door");
  });

  it("advances an invited email to upload", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/email/i), "tester@delapan.ai");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText(/paste your résumé/i);
    expect(useApp.getState().stage).toBe("upload");
  });
});

describe("upload", () => {
  beforeEach(() => useApp.setState({ stage: "upload" }));

  it("names the provider before anything is sent", () => {
    render(<App />);
    expect(screen.getByText(/extracted text is sent to the configured model provider/i)).toBeInTheDocument();
  });

  it("shows a parse error inline and stays on upload", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: /extract/i }));
    expect(await screen.findByText(/parse error/i)).toBeInTheDocument();
    expect(useApp.getState().stage).toBe("upload");
  });

  it("locks the section and advances on success", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/paste your résumé/i), "my resume text");
    await userEvent.click(screen.getByRole("button", { name: /extract/i }));
    await screen.findByText(/Profile/);
    expect(useApp.getState().stage).toBe("profile_draft");
    expect(useApp.getState().confirmedStages).toContain("upload");
  });
});
