// Возврат из Keycloak после входа: обмен кода на токены (PKCE) и переход на исходную страницу.

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { handleCallback } from "../oidc";

export function AuthCallback() {
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    handleCallback(window.location.search)
      .then((to) => nav(to, { replace: true }))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [nav]);
  return (
    <div className="layout">
      {err ? (
        <div className="error">
          Вход не выполнен: {err}. <a href="/login">Попробовать снова</a>
        </div>
      ) : (
        "Вход…"
      )}
    </div>
  );
}
