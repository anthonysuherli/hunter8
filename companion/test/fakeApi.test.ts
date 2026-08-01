import { describe, expect, it } from "vitest";
import { overallStatus } from "../src/domain";
import { makeFakeApi } from "../src/fakeApi";

describe("overallStatus precedence", () => {
  it("fail beats unknown beats pass", () => {
    expect(overallStatus([
      { constraint: "a", status: "pass", explanation: "" },
      { constraint: "b", status: "unknown", explanation: "" },
    ])).toBe("unknown");
    expect(overallStatus([
      { constraint: "a", status: "unknown", explanation: "" },
      { constraint: "b", status: "fail", explanation: "" },
    ])).toBe("fail");
    expect(overallStatus([])).toBe("pass");
  });
});

describe("FakeCompanionApi", () => {
  it("refuses uninvited emails with a plain reason", async () => {
    const api = makeFakeApi();
    const res = await api.signIn("stranger@example.com");
    expect(res).toEqual({ ok: false, refusal: expect.stringContaining("invite") });
  });

  it("extracts a draft with unanswered questions from resume text", async () => {
    const api = makeFakeApi();
    await api.signIn("tester@delapan.ai");
    const up = await api.uploadResume("some resume text");
    if (!up.ok) throw new Error("expected ok");
    expect(up.draft.questions.length).toBeGreaterThan(0);
    expect(up.draft.questions[0].anchorSection).toBeTruthy();
  });

  it("rejects an empty upload with a parse reason", async () => {
    const api = makeFakeApi();
    const up = await api.uploadResume("");
    expect(up).toEqual({ ok: false, reason: expect.stringContaining("parse") });
  });

  it("streams discovery rows to done, keeping a failed company visible", async () => {
    const api = makeFakeApi({ failCompany: "Databricks" });
    const frames: { rows: string; done: boolean }[] = [];
    await new Promise<void>((resolve) => {
      api.subscribeDiscovery((rows, done) => {
        frames.push({ rows: JSON.stringify(rows), done });
        if (done) resolve();
      });
    });
    const last = JSON.parse(frames.at(-1)!.rows) as { company: string; state: string; detail: string }[];
    const failed = last.find((r) => r.company === "Databricks");
    expect(failed?.state).toBe("source_error");
    expect(failed?.detail).toContain("source error");
    expect(last.filter((r) => r.state === "assessed").length).toBeGreaterThan(0);
  });

  it("explains an empty shortlist instead of returning bare nothing", async () => {
    const api = makeFakeApi({ emptyShortlist: true });
    const res = await api.getShortlist();
    expect(res.items).toHaveLength(0);
    expect(res.emptyReason).toBeTruthy();
  });

  it("confirmThesis returns version 1 then version 2", async () => {
    const api = makeFakeApi();
    expect((await api.confirmThesis()).version).toBe(1);
    expect((await api.confirmThesis()).version).toBe(2);
  });
});
