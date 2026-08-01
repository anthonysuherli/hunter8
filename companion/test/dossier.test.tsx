import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DossierSection } from "../src/components/DossierSection";
import { SectionRail } from "../src/components/SectionRail";
import { useApp } from "../src/store";

describe("store", () => {
  it("locks stages in order and advances", () => {
    useApp.setState({ stage: "upload", confirmedStages: [] });
    useApp.getState().lockStage("upload");
    useApp.getState().setStage("profile_draft");
    expect(useApp.getState().confirmedStages).toContain("upload");
    expect(useApp.getState().stage).toBe("profile_draft");
  });
});

describe("DossierSection", () => {
  it("renders a collapsed summary when locked", () => {
    render(
      <DossierSection stage="upload" title="Résumé" summary="Parsed 2 pages" state="locked">
        <p>full content</p>
      </DossierSection>,
    );
    expect(screen.getByText("Parsed 2 pages")).toBeInTheDocument();
    expect(screen.queryByText("full content")).not.toBeInTheDocument();
  });

  it("renders children when live", () => {
    render(
      <DossierSection stage="upload" title="Résumé" summary="" state="live">
        <p>full content</p>
      </DossierSection>,
    );
    expect(screen.getByText("full content")).toBeInTheDocument();
  });
});

describe("SectionRail", () => {
  it("marks the live stage", () => {
    useApp.setState({ stage: "profile_draft", confirmedStages: ["upload"] });
    render(<SectionRail />);
    expect(screen.getByText("Profile")).toHaveClass("rail-live");
    expect(screen.getByText("Résumé")).toHaveClass("rail-done");
  });
});
