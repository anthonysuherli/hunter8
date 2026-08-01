import type { ReactNode } from "react";

export function ClayButton({ children, onClick, disabled }:
  { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button className="clay-button" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
