export function FeedbackPills({ value, onChange }:
  { value?: "useful" | "not_useful"; onChange: (v: "useful" | "not_useful") => void }) {
  return (
    <span className="feedback">
      <button className={`pill ${value === "useful" ? "pill-active" : ""}`}
        onClick={() => onChange("useful")}>Useful</button>
      <button className={`pill ${value === "not_useful" ? "pill-active" : ""}`}
        onClick={() => onChange("not_useful")}>Not useful</button>
    </span>
  );
}
