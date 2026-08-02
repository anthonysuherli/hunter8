import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

// Matches the specifier string out of any of the four ways a module can be
// referenced: a bare side-effect import, a named/default `from` import,
// `require(...)`, or a dynamic `import(...)`.
const SPECIFIER =
  /(?:\bimport\s+["']([^"']+)["'])|(?:\bfrom\s+["']([^"']+)["'])|(?:\brequire\(\s*["']([^"']+)["']\s*\))|(?:\bimport\(\s*["']([^"']+)["']\s*\))/g;

// src/ files sit one level below companion/ (src/App.tsx) or two levels
// below (src/components/X.tsx, src/screens/X.tsx). A single "../" from a
// src-root file already reaches companion/, so it cannot be told apart from
// a legitimate src-internal "../" written one level deeper — that's what the
// explicit name ban below is for. Two or more "../" always escapes
// companion/ regardless of which file it's written in, so it's forbidden
// outright.
const ESCAPES_COMPANION = /^(\.\.\/){2,}/;

// Names that only make sense as personal hunter8-repo modules. Banned even
// behind a single "../", since that case is indistinguishable from a
// legitimate src-internal import by path shape alone.
const FORBIDDEN_NAMES =
  "db|sources|watchlist|screen|score|discover|hunter8_core|analyze|apply|tracker|triage|calibrate|handlers|plugin";
const FORBIDDEN_NAME_IMPORT = new RegExp(`^(\\.\\./)+(${FORBIDDEN_NAMES})(/|$)`);

function specifiersIn(text: string): string[] {
  const specs: string[] = [];
  let m: RegExpExecArray | null;
  SPECIFIER.lastIndex = 0;
  while ((m = SPECIFIER.exec(text))) {
    specs.push(m[1] ?? m[2] ?? m[3] ?? m[4]);
  }
  return specs;
}

describe("companion boundary", () => {
  it("imports nothing that escapes companion/ or names a personal-repo module", () => {
    const files = walk("src").filter((f) => /\.(ts|tsx)$/.test(f));
    expect(files.length).toBeGreaterThan(0);
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      for (const spec of specifiersIn(text)) {
        expect(spec, `${f}: "${spec}" escapes companion/`).not.toMatch(ESCAPES_COMPANION);
        expect(spec, `${f}: "${spec}" names a forbidden module`).not.toMatch(FORBIDDEN_NAME_IMPORT);
      }
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
