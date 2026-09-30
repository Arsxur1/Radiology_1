// Вход через Keycloak: OpenID Connect, Authorization Code + PKCE (S256), без библиотек.
//
// - Токены — в sessionStorage (живут в рамках вкладки, не переживают закрытие браузера).
// - Access token обновляется по refresh token за минуту до истечения.
// - В сети клиники интерфейс открывают по http://<IP>: это «небезопасный контекст», где
//   браузер не даёт crypto.subtle, поэтому SHA-256 для PKCE есть и в чистом JS.

const K = {
  access: "medviz.oidc.access",
  refresh: "medviz.oidc.refresh",
  id: "medviz.oidc.id",
  exp: "medviz.oidc.exp",
  pkce: "medviz.oidc.pkce",
};

interface AuthConfig {
  issuer: string | null;
  realm: string;
  client_id: string;
}

let configPromise: Promise<{ issuer: string; clientId: string }> | null = null;

async function config() {
  if (!configPromise) {
    configPromise = fetch("/api/auth/config")
      .then((r) => r.json() as Promise<AuthConfig>)
      .then((c) => ({
        // По умолчанию Keycloak на том же хосте, порт 8080 (docker-compose).
        issuer: c.issuer ?? `${window.location.protocol}//${window.location.hostname}:8080/realms/${c.realm}`,
        clientId: c.client_id,
      }));
  }
  return configPromise;
}

const redirectUri = () => `${window.location.origin}/auth/callback`;

function b64url(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(n = 48): string {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return b64url(a);
}

// SHA-256 (FIPS 180-4) — запасной путь для http без crypto.subtle.
function sha256Js(data: Uint8Array): Uint8Array {
  const K256 = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
    0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
    0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2,
  ]);
  const h = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const len = data.length;
  const total = ((len + 9 + 63) >> 6) << 6;
  const buf = new Uint8Array(total);
  buf.set(data);
  buf[len] = 0x80;
  const bits = len * 8;
  const view = new DataView(buf.buffer);
  view.setUint32(total - 4, bits >>> 0);
  view.setUint32(total - 8, Math.floor(bits / 2 ** 32));
  const w = new Uint32Array(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K256[i] + w[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h[0] += a;
    h[1] += b;
    h[2] += c;
    h[3] += d;
    h[4] += e;
    h[5] += f;
    h[6] += g;
    h[7] += hh;
  }
  const out = new Uint8Array(32);
  const ov = new DataView(out.buffer);
  h.forEach((v, i) => ov.setUint32(i * 4, v));
  return out;
}

export async function sha256(text: string): Promise<Uint8Array> {
  const data = new TextEncoder().encode(text);
  if (window.crypto?.subtle) return new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  return sha256Js(data);
}

export async function login(returnTo = "/"): Promise<void> {
  const { issuer, clientId } = await config();
  const verifier = randomString(48);
  const state = randomString(16);
  sessionStorage.setItem(K.pkce, JSON.stringify({ verifier, state, returnTo }));
  const challenge = b64url(await sha256(verifier));
  const q = new URLSearchParams({
    client_id: clientId,
    response_type: "code",
    scope: "openid",
    redirect_uri: redirectUri(),
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  window.location.assign(`${issuer}/protocol/openid-connect/auth?${q}`);
}

function saveTokens(t: { access_token: string; refresh_token?: string; id_token?: string; expires_in: number }) {
  sessionStorage.setItem(K.access, t.access_token);
  if (t.refresh_token) sessionStorage.setItem(K.refresh, t.refresh_token);
  if (t.id_token) sessionStorage.setItem(K.id, t.id_token);
  sessionStorage.setItem(K.exp, String(Date.now() + t.expires_in * 1000));
}

async function tokenRequest(body: Record<string, string>) {
  const { issuer } = await config();
  const r = await fetch(`${issuer}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body),
  });
  if (!r.ok) throw new Error(`Keycloak: ${r.status}`);
  saveTokens(await r.json());
}

/** Завершить вход после возврата из Keycloak. Возвращает адрес, куда вернуть врача. */
export async function handleCallback(search: string): Promise<string> {
  const p = new URLSearchParams(search);
  const saved = JSON.parse(sessionStorage.getItem(K.pkce) ?? "null");
  sessionStorage.removeItem(K.pkce);
  if (p.get("error")) throw new Error(p.get("error_description") ?? p.get("error") ?? "Ошибка входа");
  if (!saved || p.get("state") !== saved.state) throw new Error("Сеанс входа устарел — войдите ещё раз");
  const { clientId } = await config();
  await tokenRequest({
    grant_type: "authorization_code",
    code: p.get("code") ?? "",
    redirect_uri: redirectUri(),
    client_id: clientId,
    code_verifier: saved.verifier,
  });
  return saved.returnTo || "/";
}

export function oidcAccessToken(): string | null {
  return sessionStorage.getItem(K.access);
}

export function hasOidcSession(): boolean {
  return !!sessionStorage.getItem(K.refresh);
}

let refreshing: Promise<boolean> | null = null;

/** Обновить токен, если до истечения меньше минуты. false — сеанс закончился.
 * Параллельные запросы ждут одно общее обновление (иначе при ротации refresh token
 * в Keycloak второй запрос выкинул бы врача из системы). */
export async function ensureFresh(force = false): Promise<boolean> {
  if (!hasOidcSession()) return true;
  const exp = Number(sessionStorage.getItem(K.exp) ?? 0);
  if (!force && exp - Date.now() > 60_000) return true;
  if (!refreshing) refreshing = doRefresh().finally(() => (refreshing = null));
  return refreshing;
}

async function doRefresh(): Promise<boolean> {
  try {
    const { clientId } = await config();
    await tokenRequest({
      grant_type: "refresh_token",
      refresh_token: sessionStorage.getItem(K.refresh) ?? "",
      client_id: clientId,
    });
    return true;
  } catch {
    clearOidc();
    return false;
  }
}

export function clearOidc(): void {
  Object.values(K).forEach((k) => sessionStorage.removeItem(k));
}

export async function logout(): Promise<void> {
  const idToken = sessionStorage.getItem(K.id);
  clearOidc();
  const { issuer, clientId } = await config();
  const q = new URLSearchParams({ client_id: clientId, post_logout_redirect_uri: `${window.location.origin}/login` });
  if (idToken) q.set("id_token_hint", idToken);
  window.location.assign(`${issuer}/protocol/openid-connect/logout?${q}`);
}
