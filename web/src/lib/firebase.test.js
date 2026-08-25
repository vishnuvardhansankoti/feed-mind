// @vitest-environment node
// The Firebase config assembly. `authDomain` is the interesting field: it was
// missing entirely while Firestore was the only SDK surface (reads don't need
// it), and a missing authDomain fails at sign-in time, not at build time.
import { describe, it, expect } from "vitest";
import { firebaseConfig } from "./firebase.js";

const ENV = {
  VITE_FIREBASE_API_KEY: "key-123",
  VITE_FIREBASE_PROJECT_ID: "feed-mind",
  VITE_FIREBASE_APP_ID: "1:2:web:3",
};

describe("firebaseConfig", () => {
  it("carries the keys the Firestore reader already relied on", () => {
    expect(firebaseConfig(ENV)).toMatchObject({
      apiKey: "key-123",
      projectId: "feed-mind",
      appId: "1:2:web:3",
    });
  });

  it("derives authDomain from the project id", () => {
    // The console provisions <projectId>.firebaseapp.com, so the common case
    // needs no extra env var — one less value to forget in .env.prod.
    expect(firebaseConfig(ENV).authDomain).toBe("feed-mind.firebaseapp.com");
  });

  it("prefers an explicit authDomain for a custom sign-in domain", () => {
    const env = { ...ENV, VITE_FIREBASE_AUTH_DOMAIN: "auth.example.com" };
    expect(firebaseConfig(env).authDomain).toBe("auth.example.com");
  });

  it("ignores an empty authDomain rather than passing it through", () => {
    // .env.local carries empty VITE_FIREBASE_* values for mock dev; an empty
    // string here would clobber the derived default in a misordered build.
    const env = { ...ENV, VITE_FIREBASE_AUTH_DOMAIN: "" };
    expect(firebaseConfig(env).authDomain).toBe("feed-mind.firebaseapp.com");
  });

  it("yields an empty authDomain when there is no project id either", () => {
    // A mock build: nothing configured, and nothing should be invented.
    expect(firebaseConfig({}).authDomain).toBe("");
  });
});
