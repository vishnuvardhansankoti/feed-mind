// Lens display metadata — keyed by the `category` codes in Firestore (PRD §3.1).
export const LENSES = [
  { code: "AIML", label: "AI / ML", sources: "cs.LG · cs.AI" },
  { code: "NLP", label: "NLP", sources: "cs.CL" },
  { code: "CV", label: "Computer Vision", sources: "cs.CV" },
];

export const LENS_CODES = LENSES.map((l) => l.code);
