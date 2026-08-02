import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiContext } from "../src/App";
import { makeFakeApi } from "../src/fakeApi";
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

  it("surfaces a retryable error and re-enables the button when deletion fails", async () => {
    render(
      <ApiContext.Provider value={makeFakeApi({ deleteFails: true })}>
        <Account />
      </ApiContext.Provider>,
    );
    await userEvent.type(screen.getByPlaceholderText(/type delete/i), "delete");
    await userEvent.click(screen.getByRole("button", { name: /delete everything/i }));
    expect(await screen.findByText(/deletion did not complete/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/type delete/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: /delete everything/i })).toBeEnabled();
  });
});
