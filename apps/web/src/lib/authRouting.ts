import type { AuthStatus } from "./api";

export function authenticationRedirectFor(
  path: string,
  status: AuthStatus | null,
  loading = false,
): string | null {
  if (loading || status === null) return null;
  const hasSession = status.mode === "github" && status.authenticated;
  if ((path === "/login" || path === "/signup" || path === "/dev/login") && hasSession) {
    return "/app";
  }
  if (path.startsWith("/app") && status.mode === "github" && !status.authenticated) {
    return "/login";
  }
  return null;
}

export function developmentAuthAllowed(
  developmentBuild: boolean,
  status: AuthStatus | null,
): boolean {
  return developmentBuild && Boolean(status?.development_auth);
}
