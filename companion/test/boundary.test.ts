import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe("companion boundary", () => {
  it("imports nothing from the hunter8 repo root", () => {
    const files = walk("src").filter((f) => /\.(ts|tsx)$/.test(f));
    expect(files.length).toBeGreaterThan(0);
    const forbidden = /from\s+["'](\.\.\/)*\.\.\/(db|sources|watchlist|screen|score|discover|hunter8_core)/;
    for (const f of files) {
      expect(readFileSync(f, "utf8")).not.toMatch(forbidden);
    }
  });

  it("never references personal artifact names", () => {
    const files = walk("src");
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      expect(text).not.toMatch(/intent\.md|rubric\.md|hunter8\.db|watchlist\.yaml/);
    }
  });
});
