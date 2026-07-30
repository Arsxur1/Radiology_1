// Аутентификация клиента.
//
// В продакшне используется OIDC-токен Keycloak (Bearer). Здесь хранится либо
// токен, либо dev-идентификация через заголовки X-Debug-* (работает ТОЛЬКО когда
// backend запущен с ALLOW_DEBUG_AUTH=true — изолированные стенды).

const TOKEN_KEY = "medviz.token";
const DEBUG_SUBJECT_KEY = "medviz.debug.subject";
const DEBUG_ROLES_KEY = "medviz.debug.roles";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getDebugIdentity(): { subject: string | null; roles: string | null } {
  return {
    subject: localStorage.getItem(DEBUG_SUBJECT_KEY),
    roles: localStorage.getItem(DEBUG_ROLES_KEY),
  };
}

export function setDebugIdentity(subject: string, roles: string): void {
  localStorage.setItem(DEBUG_SUBJECT_KEY, subject);
  localStorage.setItem(DEBUG_ROLES_KEY, roles);
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(DEBUG_SUBJECT_KEY);
  localStorage.removeItem(DEBUG_ROLES_KEY);
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  if (token) return { Authorization: `Bearer ${token}` };
  const { subject, roles } = getDebugIdentity();
  if (subject) return { "X-Debug-Subject": subject, "X-Debug-Roles": roles ?? "" };
  return {};
}
