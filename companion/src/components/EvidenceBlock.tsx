import type { EvidenceItem } from "../domain";

export function EvidenceBlock({ item }: { item: EvidenceItem }) {
  return (
    <blockquote className="evidence">
      <p className="serif">“{item.sourceExcerpt}”</p>
      <footer className="evidence-src">— {item.sourceLocator}</footer>
    </blockquote>
  );
}
