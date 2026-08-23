# DriftGuard AI web application

The React/TypeScript dashboard presents the DriftGuard workflow: Detect, Understand, Fix,
Validate, and Review. It is intentionally a single-page product surface with anchored navigation.

From this directory:

```powershell
npm install
Copy-Item .env.example .env
npm run dev
```

The local API defaults to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` before `npm run build`
to target a different backend. Vite embeds this value at build time.

See the repository root README for complete setup, demo, security, and deployment guidance.
