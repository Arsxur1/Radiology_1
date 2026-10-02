// Журнал инцидентов (ТЗ, раздел 9 п. 7; пострегистрационный надзор).
// Врач и клиницист видят свои сообщения; администратор разбирает и закрывает с выводом,
// аудитор видит всё. Серьёзные открытые — сверху и в «Состоянии системы».

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { IncidentOut, IncidentStatus } from "../api/types";
import { hasRole } from "../auth";

const STATUS: Record<IncidentStatus, string> = {
  new: "новый",
  investigating: "на разборе",
  closed: "закрыт",
};
const NEXT: Record<IncidentStatus, IncidentStatus[]> = {
  new: ["investigating", "closed"],
  investigating: ["closed"],
  closed: ["investigating"],
};

function Review({ inc, onDone }: { inc: IncidentOut; onDone: (u: IncidentOut) => void }) {
  const [to, setTo] = useState<IncidentStatus>(NEXT[inc.status][0]);
  const [text, setText] = useState(inc.resolution ?? "");
  const [err, setErr] = useState<string | null>(null);
  const needText = to === "closed";
  return (
    <div style={{ marginTop: 6 }}>
      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        <select value={to} onChange={(e) => setTo(e.target.value as IncidentStatus)} aria-label="Новый статус">
          {NEXT[inc.status].map((s) => (
            <option key={s} value={s}>
              {s === "investigating" && inc.status === "closed" ? "вернуть на разбор" : STATUS[s]}
            </option>
          ))}
        </select>
        <button
          disabled={needText && text.trim().length < 10}
          onClick={async () => {
            setErr(null);
            try {
              onDone(await api.updateIncident(inc.id, to, text));
            } catch (e) {
              setErr(e instanceof ApiError ? e.message : String(e));
            }
          }}
        >
          Сохранить
        </button>
        {err && <span className="error">{err}</span>}
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        style={{ width: "100%", marginTop: 6 }}
        placeholder={needText ? "Вывод разбора и принятые меры (обязательно для закрытия)" : "Заметки разбора"}
        aria-label="Вывод разбора"
      />
    </div>
  );
}

export function Incidents() {
  const [rows, setRows] = useState<IncidentOut[] | null>(null);
  const [filter, setFilter] = useState<IncidentStatus | "">("");
  const [err, setErr] = useState<string | null>(null);
  const admin = hasRole("admin");

  const load = useCallback(() => {
    setErr(null);
    api
      .listIncidents(filter || undefined)
      .then(setRows)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [filter]);
  useEffect(load, [load]);

  const sorted = [...(rows ?? [])].sort(
    (a, b) =>
      Number(b.status !== "closed" && b.severity === "serious") -
        Number(a.status !== "closed" && a.severity === "serious") || b.created_at.localeCompare(a.created_at),
  );

  return (
    <div className="layout">
      <div className="row spread">
        <h2>Инциденты</h2>
        <select value={filter} onChange={(e) => setFilter(e.target.value as IncidentStatus | "")} aria-label="Статус">
          <option value="">все</option>
          {(Object.keys(STATUS) as IncidentStatus[]).map((s) => (
            <option key={s} value={s}>
              {STATUS[s]}
            </option>
          ))}
        </select>
      </div>
      <p className="muted">
        Сообщить можно со страницы исследования («Сообщить об инциденте…»). {admin
          ? "Закрытие — только с выводом разбора; каждое изменение статуса пишется в журнал аудита."
          : hasRole("auditor")
            ? "Показаны все сообщения."
            : "Показаны ваши сообщения."}
      </p>
      {err && <div className="error">{err}</div>}
      {rows && rows.length === 0 && <p className="muted">Сообщений нет.</p>}
      {sorted.map((i) => (
        <div
          key={i.id}
          className="card"
          style={i.severity === "serious" && i.status !== "closed" ? { borderColor: "#e05d5d" } : undefined}
        >
          <div className="row spread">
            <strong>{i.kind_label}</strong>
            <span className={i.status === "closed" ? "badge badge-confirmed" : "badge badge-model"}>
              {STATUS[i.status]}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            {new Date(i.created_at).toLocaleString()} · {i.reported_by} · {i.severity_label}
            {i.study_id && (
              <>
                {" "}· <Link to={`/studies/${i.study_id}`}>исследование</Link>
              </>
            )}
            {i.model_version_id && <> · модель {i.model_version_id.slice(0, 8)}</>}
          </div>
          <p style={{ whiteSpace: "pre-wrap", margin: "6px 0" }}>{i.description}</p>
          {i.resolution && (
            <div style={{ fontSize: 14 }}>
              <b>Разбор:</b> {i.resolution}
              {i.closed_by && <span className="muted"> — {i.closed_by}</span>}
            </div>
          )}
          {admin && <Review key={i.status} inc={i} onDone={(u) => setRows((p) => (p ?? []).map((r) => (r.id === u.id ? u : r)))} />}
        </div>
      ))}
    </div>
  );
}
