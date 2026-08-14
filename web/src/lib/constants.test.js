import { describe, it, expect } from "vitest";
import { LENSES, LENS_CODES } from "./constants.js";

describe("lens metadata", () => {
  it("defines the three lenses in Firestore-category order", () => {
    expect(LENS_CODES).toEqual(["AIML", "NLP", "CV"]);
  });

  it("every lens carries a code, label, and sources string", () => {
    expect(LENSES).toHaveLength(3);
    for (const lens of LENSES) {
      expect(lens.code).toBeTruthy();
      expect(lens.label).toBeTruthy();
      expect(lens.sources).toBeTruthy();
    }
  });

  it("LENS_CODES is derived from LENSES", () => {
    expect(LENS_CODES).toEqual(LENSES.map((l) => l.code));
  });
});
