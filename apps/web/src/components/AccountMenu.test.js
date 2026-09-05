// The masthead sign-in control. What matters here is that all four session
// states render distinctly — especially `rejected`, which exists because
// Firebase Auth lets anyone with a Google account sign in while
// firestore.rules only lets allowlisted addresses touch anything.
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/svelte";
import AccountMenu from "./AccountMenu.svelte";
import { session } from "../lib/session.svelte.js";

const USER = {
  uid: "u1",
  email: "someone@example.com",
  displayName: "Some One",
  photoURL: "",
};

const setSession = (patch) => Object.assign(session, patch);

beforeEach(() => setSession({ status: "loading", user: null, error: null }));
afterEach(() => setSession({ status: "loading", user: null, error: null }));

describe("AccountMenu", () => {
  it("renders nothing while auth state is unknown", () => {
    // A "Sign in" button that flips to an avatar one tick later reads as a bug.
    render(AccountMenu);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers sign-in when signed out", () => {
    setSession({ status: "out" });
    render(AccountMenu);
    expect(screen.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  it("shows an avatar, not a sign-in button, when signed in", () => {
    setSession({ status: "in", user: USER });
    render(AccountMenu);
    expect(screen.getByRole("button", { name: "Account menu" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
  });

  it("keeps the menu closed until the avatar is clicked", async () => {
    setSession({ status: "in", user: USER });
    render(AccountMenu);
    expect(screen.queryByRole("menu")).toBeNull();

    await screen.getByRole("button", { name: "Account menu" }).click();
    expect(screen.getByRole("menu")).toBeVisible();
    expect(screen.getByText(USER.email)).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
  });

  it("falls back to an initial when the account has no photo", () => {
    setSession({ status: "in", user: USER });
    render(AccountMenu);
    expect(screen.getByText("S")).toBeVisible();
  });

  it("uses the email's initial when there is no display name either", () => {
    setSession({ status: "in", user: { ...USER, displayName: "" } });
    render(AccountMenu);
    expect(screen.getByText("S")).toBeVisible(); // someone@example.com
  });

  it("explains rejection instead of leaving a broken signed-in UI", () => {
    setSession({ status: "rejected", user: null });
    render(AccountMenu);

    expect(screen.getByRole("status")).toHaveTextContent("doesn’t have access");
    // Crucially not signed-in-looking: no avatar, nothing to click into.
    expect(screen.queryByRole("button", { name: "Account menu" })).toBeNull();
  });

  it("returns to the signed-out state when the rejection is dismissed", async () => {
    setSession({ status: "rejected", user: null });
    render(AccountMenu);

    await screen.getByRole("button", { name: "Dismiss" }).click();
    expect(session.status).toBe("out");
  });

  it("surfaces a sign-in failure next to the button", () => {
    setSession({ status: "out", error: "Network request failed" });
    render(AccountMenu);
    expect(screen.getByRole("alert")).toHaveTextContent("Network request failed");
  });
});
