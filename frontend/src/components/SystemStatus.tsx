// Состояние системы для администратора и ИТ (SR-4): по функциям и по компонентам.
// Отказ ИИ показывается отдельно — просмотр и приём от него не зависят.

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { SystemStatusOut } from "../api/types";

const NAMES: Record<string, string> = {
  postgres: "БД (доверенный контур)",
  postgres_idmap: "БД (идентифицирующий контур)",
  redis: "Redis",
  s3: "Объектное хранилище",
  orthanc_clean: "Просмотрщик (обезличенный Orthanc)",
  orthanc_raw: "Приёмник от PACS (orthanc-raw)",
  watcher: "Наблюдатель приёма",
  raw_backlog: "Застрявшие в приёмнике (с ФИО)",
  disk: "Диск с данными",
  debug_auth: "Отладочный вход без пароля",
  pseudonym_key: "Ключ псевдонимизации",
  queue: "Очередь задач",
  workers: "Воркеры анализа",
  models: "Действующие модели",
  backup: "Резервная копия",
};
const FUNCS: [string, string][] = [
  ["viewer", "Просмотр"],
  ["ingest", "Приём снимков"],
  ["ai", "ИИ"],
];
const COLOR: Record<string, string> = { ok: "#3fb27f", degraded: "#d9a441", down: "#e05d5d" };

export function SystemStatus() {
  const [st, setSt] = useState<SystemStatusOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .systemStatus()
        .then((s) => alive && (setSt(s), setErr(null)))
        .catch((e) => alive && setErr(e instanceof ApiError ? e.message : String(e)));
    load();
    const t = window.setInterval(load, 30_000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  return (
    <section className="card">
      <div className="row spread">
        <strong>Состояние системы</strong>
        {st && (
          <span className="muted" style={{ fontSize: 12 }}>
            проверено {new Date(st.checked_at * 1000).toLocaleTimeString("ru-RU")}
          </span>
        )}
      </div>
      {err && <div className="error">Не удалось получить состояние: {err}</div>}
      {st && (
        <>
          <div className="row" style={{ gap: 16, margin: "8px 0" }}>
            {FUNCS.map(([k, label]) => (
              <span key={k}>
                <span style={{ color: COLOR[st.functions[k]] ?? "#999" }}>●</span> {label}:{" "}
                {{ ok: "работает", degraded: "требует внимания", down: "не работает" }[st.functions[k]] ??
                  st.functions[k]}
              </span>
            ))}
          </div>
          <table>
            <tbody>
              {st.checks.map((c) => (
                <tr key={c.name}>
                  <td>
                    <span style={{ color: !c.ok ? COLOR.down : c.warn ? COLOR.degraded : COLOR.ok }}>●</span>{" "}
                    {NAMES[c.name] ?? c.name}
                  </td>
                  <td className={c.ok ? "muted" : "error"}>{c.detail}</td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {c.ms} мс
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
