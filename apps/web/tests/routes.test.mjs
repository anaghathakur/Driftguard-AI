import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

let server;
let App;
let LandingPage;
let authenticationRedirectFor;
let developmentAuthAllowed;
let DevelopmentAuth;

before(async () => {
  installWindow("/");
  server = await createServer({
    appType: "custom",
    server: { middlewareMode: true },
  });
  ({ App } = await server.ssrLoadModule("/src/App.tsx"));
  ({ authenticationRedirectFor, developmentAuthAllowed } = await server.ssrLoadModule("/src/lib/authRouting.ts"));
  ({ default: DevelopmentAuth } = await server.ssrLoadModule("/src/pages/DevelopmentAuth.tsx"));
  ({ LandingPage } = await server.ssrLoadModule("/src/pages/LandingPage.tsx"));
});

after(async () => {
  await server?.close();
});

test("landing page renders public product content without user statistics", () => {
  const html = renderToStaticMarkup(React.createElement(LandingPage, {
    authenticated: false,
    onGetStarted() {},
    onSignIn() {},
    onOpenApp() {},
  }));

  assert.match(html, /Ship API changes/);
  assert.match(html, /Illustrative product workflow/);
  assert.match(html, /Start for free/);
  assert.match(html, /Sign in/);
  assert.match(html, /Get started/);
  assert.doesNotMatch(html, /Open dashboard/);
  assert.doesNotMatch(html, /1,248|64 active monitors|DevTeam Alpha|Pro Plan/);
});

test("authenticated landing navigation contains Open dashboard", () => {
  const html = renderToStaticMarkup(React.createElement(LandingPage, {
    authenticated: true,
    onGetStarted() {},
    onSignIn() {},
    onOpenApp() {},
  }));

  assert.match(html, /Open dashboard/);
  assert.doesNotMatch(html, />Sign in</);
  assert.doesNotMatch(html, />Get started</);
});

test("local workspace mode does not masquerade as a signed-in public session", () => {
  installWindow("/");
  const html = renderApp(localStatus());

  assert.match(html, /Sign in/);
  assert.match(html, /Get started/);
  assert.doesNotMatch(html, /Open dashboard/);
});

test("protected app routes redirect unauthenticated users to login", () => {
  installWindow("/app/repositories");
  const html = renderApp(unauthenticatedStatus());

  assert.match(html, /Sign in to DriftGuard/);
  assert.doesNotMatch(html, /Authorized repositories/);
  assert.equal(authenticationRedirectFor("/app/repositories", unauthenticatedStatus()), "/login");
});

test("login and signup routes render their respective authentication copy", () => {
  installWindow("/login");
  assert.match(renderApp(unauthenticatedStatus()), /Sign in to DriftGuard/);

  installWindow("/signup");
  assert.match(renderApp(unauthenticatedStatus()), /Create your DriftGuard account/);
});

test("development identities render only when the backend enables development auth", () => {
  const developmentStatus = { ...unauthenticatedStatus(), development_auth: true };
  assert.equal(developmentAuthAllowed(true, developmentStatus), true);
  assert.equal(developmentAuthAllowed(false, developmentStatus), false);
  const developmentHtml = renderToStaticMarkup(React.createElement(DevelopmentAuth));
  assert.match(developmentHtml, /Development testing/);
  assert.match(developmentHtml, /development user A/);
  assert.match(developmentHtml, /development user B/);

  installWindow("/login");
  const productionHtml = renderApp(unauthenticatedStatus());
  assert.doesNotMatch(productionHtml, /Development testing|development user A|development user B/);
});

test("authenticated users are redirected away from login and signup", () => {
  assert.equal(authenticationRedirectFor("/login", authenticatedStatus()), "/app");
  assert.equal(authenticationRedirectFor("/signup", authenticatedStatus()), "/app");
});

test("authenticated users can render the protected application shell", () => {
  installWindow("/app");
  const html = renderApp(authenticatedStatus());

  assert.match(html, /Detect breaking API changes before they break production/);
  assert.match(html, /Personal Workspace/);
});

function renderApp(status) {
  return renderToStaticMarkup(React.createElement(App, {
    initialAuthStatus: status,
    initialAuthResolved: true,
  }));
}

function unauthenticatedStatus() {
  return {
    mode: "github",
    authenticated: false,
    development_auth: false,
    github_auth_configured: true,
    google_auth_configured: false,
    user: null,
    workspace: null,
    workspaces: [],
    csrf_token: null,
  };
}

function authenticatedStatus() {
  return {
    ...unauthenticatedStatus(),
    authenticated: true,
    user: {
      id: "user-1",
      github_login: "developer",
      github_display_name: "Developer",
      avatar_url: null,
      auth_provider: "github",
      email: "developer@example.com",
    },
    workspace: {
      id: "workspace-1",
      name: "Personal Workspace",
      slug: "personal-workspace",
      role: "owner",
    },
    workspaces: [{
      id: "workspace-1",
      name: "Personal Workspace",
      slug: "personal-workspace",
      role: "owner",
    }],
    csrf_token: "csrf",
  };
}

function localStatus() {
  return {
    ...unauthenticatedStatus(),
    mode: "local",
    github_auth_configured: false,
    workspace: {
      id: "local",
      name: "Local Workspace",
      slug: "local",
      role: "owner",
    },
  };
}

function installWindow(pathname) {
  globalThis.window = {
    location: { pathname, origin: "http://localhost:5173" },
    history: {
      pushState() {},
      replaceState() {},
    },
    addEventListener() {},
    removeEventListener() {},
    scrollTo() {},
    setTimeout,
  };
}
