# Phase 16: authentication, workspaces, and GitHub onboarding

Phase 16 adds GitHub identity, server-side sessions, workspace tenancy, GitHub App
installation onboarding, and connected/private repository analysis. The existing local,
specification-only, ZIP-upload, and public-GitHub workflows remain available when
`DRIFTGUARD_AUTH_MODE=local`.

## Legacy data migration

SQLite migration is additive and runs during repository initialization. Existing databases do
not need to be deleted or recreated.

- A deterministic `Local Workspace` is created with ID
  `00000000-0000-0000-0000-000000000001`.
- Existing analyses and monitors whose `workspace_id` is absent are assigned to that local
  workspace.
- Existing patch proposals, validation runs, and Pull Request records remain related through
  their parent analysis and inherit access control from it.
- Existing local request fingerprints retain their previous format. Authenticated workspace
  fingerprints include the workspace ID so identical submissions in different workspaces do not
  collide.
- Firestore adapters store `workspace_id` on new documents and treat legacy documents without it
  as Local Workspace data, matching SQLite behavior.

Back up production persistence before any deployment as usual. The migration never drops the
legacy tables or deletes existing records.

## Authentication modes

`DRIFTGUARD_AUTH_MODE=local` preserves anonymous demo behavior and does not require OAuth.

`DRIFTGUARD_AUTH_MODE=github` requires all of the following:

- `DRIFTGUARD_SESSION_SECRET` with at least 32 characters
- `DRIFTGUARD_GITHUB_OAUTH_CLIENT_ID`
- `DRIFTGUARD_GITHUB_OAUTH_CLIENT_SECRET`
- an allowlisted `DRIFTGUARD_FRONTEND_URL`
- a matching `DRIFTGUARD_GITHUB_OAUTH_CALLBACK_URL`

Use `DRIFTGUARD_SECURE_COOKIES=true` behind HTTPS. Authentication uses opaque, HttpOnly,
server-side sessions and a separate CSRF cookie/header pair. GitHub OAuth access tokens are used
only to resolve identity and are not persisted.

## GitHub App onboarding

Production onboarding requires `DRIFTGUARD_GITHUB_WRITE_PROVIDER=github_app` plus:

- `DRIFTGUARD_GITHUB_APP_ID`
- `DRIFTGUARD_GITHUB_APP_PRIVATE_KEY_PATH`
- `DRIFTGUARD_GITHUB_APP_INSTALL_URL`

The frontend starts installation through DriftGuard's server endpoint. A short-lived, one-time
state value protects the callback. Installation access tokens are minted server-side when needed
and are never stored or sent to the browser. Direct installation-ID registration is available
only with the deterministic mock provider.

## Repository ingestion limits

Connected repositories are read through GitHub metadata and tree APIs. DriftGuard filters to
supported Python, JavaScript, and TypeScript source files before downloading content. Configure
the bounds documented in `.env.example`:

- `DRIFTGUARD_MAX_REPOSITORY_TREE_ENTRIES`
- `DRIFTGUARD_MAX_REPOSITORY_SOURCE_FILES`
- `DRIFTGUARD_MAX_REPOSITORY_SOURCE_FILE_BYTES`
- `DRIFTGUARD_MAX_REPOSITORY_SOURCE_BYTES`

Repository content is treated as untrusted data and is never installed, imported, or executed.
