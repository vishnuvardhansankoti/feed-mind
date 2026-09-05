// @vitest-environment jsdom
// The mock auth backend — the one `npm run dev` and every component test run
// against, since dev builds carry empty Firebase keys and have no project to
// authenticate against. Its contract has to match the Firebase path closely
// enough that the UI can't tell them apart.
import { describe, it, expect, beforeEach, vi } from "vitest";
import { signIn, signOut, onUser, isMockAuth } from "./auth.js";

beforeEach(async () => {
  localStorage.clear();
  await signOut();
});

describe("mock auth", () => {
  it("is the backend selected when VITE_DATA_SOURCE isn't firestore", () => {
    expect(isMockAuth).toBe(true);
  });

  it("returns a normalized user with the fields the UI renders", async () => {
    const user = await signIn();
    expect(user).toMatchObject({
      uid: expect.any(String),
      email: expect.any(String),
      displayName: expect.any(String),
      photoURL: expect.any(String),
    });
  });

  it("notifies subscribers on sign-in and sign-out", async () => {
    const seen = [];
    const stop = onUser((u) => seen.push(u?.uid ?? null));
    await Promise.resolve(); // the initial async callback

    await signIn();
    await signOut();
    stop();

    expect(seen).toEqual([null, "mock-user", null]);
  });

  it("calls back asynchronously, never during subscribe", async () => {
    // onAuthStateChanged is async; a synchronous first call would run before
    // the caller finished wiring its own state up.
    let called = false;
    const stop = onUser(() => (called = true));
    expect(called).toBe(false);
    await Promise.resolve();
    expect(called).toBe(true);
    stop();
  });

  it("stops notifying after unsubscribe", async () => {
    const cb = vi.fn();
    const stop = onUser(cb);
    await Promise.resolve();
    cb.mockClear();

    stop();
    await signIn();
    expect(cb).not.toHaveBeenCalled();
  });

  it("survives a reload, like Firebase's default local persistence", async () => {
    await signIn();
    // A fresh subscriber stands in for a reload: state comes from storage,
    // not from memory.
    const seen = [];
    const stop = onUser((u) => seen.push(u?.uid ?? null));
    await Promise.resolve();
    stop();
    expect(seen).toEqual(["mock-user"]);
  });

  it("treats unavailable storage as signed out rather than throwing", async () => {
    // Private browsing: localStorage exists but throws on access.
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const seen = [];
    const stop = onUser((u) => seen.push(u));
    await Promise.resolve();
    stop();
    spy.mockRestore();
    expect(seen).toEqual([null]);
  });

  it("is idempotent on repeated sign-out", async () => {
    await expect(signOut()).resolves.toBeUndefined();
    await expect(signOut()).resolves.toBeUndefined();
  });
});
