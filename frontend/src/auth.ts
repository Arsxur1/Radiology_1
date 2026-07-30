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

/**
 * Роли текущего пользователя — только для показа/скрытия пунктов меню.
 * Безопасность обеспечивает backend (403). Для dev — из debug-ролей; для OIDC —
 * из payload JWT (realm_access.roles), декодированного без проверки подписи.
 */
export function getRoles(): string[] {
  const token = getToken();
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split(".")[1] ?? ""));
      const roles = payload?.realm_access?.roles;
      return Array.isArray(roles) ? roles : [];
    } catch {
      return [];
    }
  }
  const { roles } = getDebugIdentity();
  return roles ? roles.split(",").map((r) => r.trim()).filter(Boolean) : [];
}

export function hasRole(...roles: string[]): boolean {
  const mine = new Set(getRoles());
  return roles.some((r) => mine.has(r));
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  if (token) return { Authorization: `Bearer ${token}` };
  const { subject, roles } = getDebugIdentity();
  if (subject) return { "X-Debug-Subject": subject, "X-Debug-Roles": roles ?? "" };
  return {};
}
