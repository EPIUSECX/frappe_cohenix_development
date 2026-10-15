import { describe, expect, it } from "vitest";
import { PROFILES } from "./api";

describe("profiles allowlist", () => {
  it("includes hr as default-facing profile", () => {
    expect(PROFILES.some((p) => p.id === "hr")).toBe(true);
  });

  it("matches config/profiles.toml identifiers", () => {
    const ids = PROFILES.map((p) => p.id).sort();
    expect(ids).toEqual(
      ["erp", "frappe", "full-cohenix", "hr", "integrations", "localisation"].sort(),
    );
  });
});
