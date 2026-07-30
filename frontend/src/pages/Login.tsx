// Вход. Продакшн: OIDC-токен Keycloak. Dev-стенд: X-Debug-идентификация
// (работает только при ALLOW_DEBUG_AUTH=true на backend).

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setDebugIdentity, setToken } from "../auth";

export function Login() {
  const nav = useNavigate();
  const [token, setTok] = useState("");
  const [subject, setSubject] = useState("dr.ivanov");
  const [roles, setRoles] = useState("radiologist");

  return (
    <div className="layout" style={{ maxWidth: 480 }}>
      <h2>Вход</h2>

      <div className="card">
        <h3>OIDC-токен (продакшн)</h3>
        <p className="muted">Bearer-токен, выданный Keycloak.</p>
        <input
          style={{ width: "100%" }}
          value={token}
          onChange={(e) => setTok(e.target.value)}
          placeholder="eyJ..."
        />
        <div style={{ marginTop: 10 }}>
          <button
            className="primary"
            disabled={!token.trim()}
            onClick={() => {
              setToken(token.trim());
              nav("/");
            }}
          >
            Войти по токену
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Отладочный вход (только стенд)</h3>
        <p className="muted">
          Работает лишь если backend запущен с ALLOW_DEBUG_AUTH=true. Не использовать в продакшне.
        </p>
        <div className="row">
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="subject" />
          <select value={roles} onChange={(e) => setRoles(e.target.value)}>
            <option value="radiologist">radiologist</option>
            <option value="admin">admin</option>
            <option value="clinician">clinician</option>
            <option value="researcher">researcher</option>
            <option value="auditor">auditor</option>
          </select>
        </div>
        <div style={{ marginTop: 10 }}>
          <button
            onClick={() => {
              setDebugIdentity(subject, roles);
              nav("/");
            }}
          >
            Войти (dev)
          </button>
        </div>
      </div>
    </div>
  );
}
