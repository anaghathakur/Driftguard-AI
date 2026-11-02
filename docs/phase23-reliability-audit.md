# Phase 23 reliability audit

Audited against the local main branch before changes. These classifications describe
observed implementation and evidence, not successful live-provider acceptance.

| Path | Initial classification | Evidence / gap |
| --- | --- | --- |
| OpenAPI manual comparison and ZIP analysis | REAL_END_TO_END | Existing endpoint, scanner, risk, migration and persistence tests; previous manual runs |
| GraphQL comparison | REAL_END_TO_END | Saleor comparison and saved analysis reproduced |
| GraphQL impact | PARTIAL | Parsed operations plus low-confidence lexical fallback; lexical occurrences can match unrelated operations |
| Migration | REAL_BACKEND_ONLY | Deterministic and Gemini transports; production fallback disabled; live Gemini not demonstrated |
| GraphQL patch | BROKEN | Regex removes argument without variable/JS cleanup; one-to-one pair treated as replacement evidence |
| Patch persistence | REAL_END_TO_END | Saved Saleor proposal; SQLite provider-column migration repaired in Phase 22 |
| GraphQL validation | BROKEN | Change-only checks, no complete new schema; malformed documents silently omitted |
| Validation execution | PARTIAL | Bounded local runner restricted to development/test; no production execution sandbox |
| Real OAuth/session/RBAC | REAL_BACKEND_ONLY | Real exchange, HttpOnly cookies, CSRF, persisted sessions and workspace roles; real-user acceptance pending |
| Development A/B | MOCK_DEVELOPMENT_ONLY | Explicit provider, frontend DEV gate, production startup rejects mock OAuth |
| Google OAuth | NOT_CONFIGURED | Disabled UI; no implementation |
| GitHub installation/private repository | REAL_BACKEND_ONLY | Installation token transport and server-derived workspace authorization |
| GitHub webhook/Checks | REAL_BACKEND_ONLY | HMAC verification, delivery idempotency, real Checks transport; live acceptance pending |
| PR preview/create | PARTIAL | Human confirmation, immutable base and no-force branch writes; draft flag absent |
| GitHub worker | PARTIAL | SQLite queue/retries persist; RUNNING jobs never recovered; claim errors terminate task |
| Monitors | PARTIAL | Public HTTPS OpenAPI plus required public repository; persisted baseline/history, process-local scheduler/lock |
| Provider status | PARTIAL | Production mocks rejected but aggregate readiness does not establish live integrations or durable scheduling |
| Contract subscriptions | PARTIAL | Existing monitor baseline is reusable; no HTTP/GraphQL/connected-file subscription resource yet |

Phase 24 is gated on Phase 23 acceptance. Real OAuth accounts, GitHub App installation,
webhook delivery and draft PR acceptance require configured providers and user actions.
Do not describe mock transport tests as live GitHub verification.

## Source references

- GraphQL document validation: https://spec.graphql.org/October2021/#sec-Validation
- graphql-core schema/TypeInfo utilities: https://graphql-core-3.readthedocs.io/en/latest/modules/utilities.html
- GitHub draft PR API: https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request
