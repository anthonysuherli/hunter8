import type { ConstraintStatus } from "../domain";

export function ConstraintChip({ status, label }: { status: ConstraintStatus; label: string }) {
  return <span className={`chip chip-${status}`}>{label}</span>;
}
