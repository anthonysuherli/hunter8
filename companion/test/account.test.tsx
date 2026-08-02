import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Account } from "../src/screens/Account";

describe("deletion", () => {
  it("requires the typed word before enabling, then reports done", async () => {
    render(<Account />);
    expect(screen.getByText(/permanently removes your résumé/i)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /delete everything/i });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(/type delete/i), "delete");
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(await screen.findByText(/deleted\. nothing of yours remains/i)).toBeInTheDocument();
  });
});
