import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ClayButton } from "../src/components/ClayButton";
import { ConstraintChip } from "../src/components/ConstraintChip";
import { EvidenceBlock } from "../src/components/EvidenceBlock";
import { FeedbackPills } from "../src/components/FeedbackPills";

describe("ConstraintChip", () => {
  it("renders each status as its own visual class", () => {
    const { rerender } = render(<ConstraintChip status="pass" label="NYC" />);
    expect(screen.getByText("NYC")).toHaveClass("chip", "chip-pass");
    rerender(<ConstraintChip status="fail" label="onsite only" />);
    expect(screen.getByText("onsite only")).toHaveClass("chip-fail");
    rerender(<ConstraintChip status="unknown" label="sponsorship?" />);
    expect(screen.getByText("sponsorship?")).toHaveClass("chip-unknown");
  });
});

describe("ClayButton", () => {
  it("fires onClick and respects disabled", async () => {
    const onClick = vi.fn();
    render(<ClayButton onClick={onClick}>Confirm</ClayButton>);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("EvidenceBlock", () => {
  it("quotes the excerpt and shows the source locator", () => {
    render(<EvidenceBlock item={{ evidenceId: "e", claim: "c",
      sourceExcerpt: "Built 12-agent runtime", sourceLocator: "résumé p.1" }} />);
    expect(screen.getByText(/Built 12-agent runtime/)).toBeInTheDocument();
    expect(screen.getByText(/résumé p\.1/)).toBeInTheDocument();
  });
});

describe("FeedbackPills", () => {
  it("offers exactly Useful and Not useful and reports the choice", async () => {
    const onChange = vi.fn();
    render(<FeedbackPills onChange={onChange} />);
    expect(screen.getAllByRole("button")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Useful" }));
    expect(onChange).toHaveBeenCalledWith("useful");
  });
});
