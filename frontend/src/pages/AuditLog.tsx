// Журнал аудита (FR-12, SR-8): только чтение для аудитора и администратора.
// Кто, когда и к каким данным обращался; целостность хеш-цепочки проверяется на сервере.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { AuditEntry } from "../api/types";

const ACTIONS: Record<string, string> = {
  patient_access: "доступ к данным",
  study_ingest: "приём исследования",
  anonymization: "обезличивание",
  mode_change: "смена режима",
  finding_confirm: "подтверждение находки",
  finding_reject: "отклонение находки",
  correction: "правка / находка врача",
  report_finalize: "подпись заключения",
  model_promote: "модели",
  export: "выгрузка данных",
};

const PAGE = 100;

function describe(e: AuditEntry): string {
  const d = e.details ?? {};
  const what = typeof d.what === "string" ? d.what : typeof d.event === "string" ? d.event : "";
  return [what, e.entity_type].filter(Boolean).join(" · ");
}

export function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [intact, setIntact] = useState<boolean | null>(null);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [more, setMore] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const params = useCallback(
    (beforeSeq?: number) => {
      const p = new URLSearchParams({ limit: String(PAGE) });
      if (actor.trim()) p.set("actor", actor.trim());
      if (action) p.set("action", action);
      if (since) p.set("since", `${since}T00:00:00`);
      if (until) p.set("until", `${until}T23:59:59`);
      if (beforeSeq) p.set("before_seq", String(beforeSeq));
      return p;
    },
    [actor, action, since, until],
  );

  const load = useCallback(
    async (append = false) => {
      setErr(null);
      try {
        const last = append ? rows[rows.length - 1]?.seq ?? undefined : undefined;
        const page = await api.auditList(params(last));
        setRows((prev) => (append ? [...prev, ...page] : page));
        setMore(page.length === PAGE);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : String(e));
      }
    },
    [params, rows],
  );

  useEffect(() => {
    api.auditVerify().then((r) => setIntact(r.intact)).catch(() => setIntact(null));
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function exportCsv() {
    try {
      const p = params();
      p.delete("limit");
      const url = await api.auditCsvUrl(p);
      const a = document.createElement("a");
      a.href = url;
      a.download = "audit.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div className="layout">
      <div className="row spread">
        <h2>Журнал аудита</h2>
        {intact === true && <span className="badge badge-confirmed">цепочка записей цела</span>}
        {intact === false && <span className="badge badge-rejected">НАРУШЕНА целостность журнала</span>}
      </div>
      <p className="muted">
        Все действия и обращения к данным. Журнал только дополняется; изменить или удалить запись нельзя.
      </p>

      <div className="card row" style={{ flexWrap: "wrap" }}>
        <input placeholder="пользователь" value={actor} onChange={(e) => setActor(e.target.value)} />
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Действие">
          <option value="">все действия</option>
          {Object.entries(ACTIONS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <label className="muted">
          с <input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
        <label className="muted">
          по <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
        <button className="primary" onClick={() => load(false)}>
          Показать
        </button>
        <button onClick={exportCsv}>Выгрузить CSV</button>
      </div>

      {err && <div className="error">Ошибка: {err}</div>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>№</th>
              <th>Время</th>
              <th>Пользователь</th>
              <th>Роль</th>
              <th>Действие</th>
              <th>Объект</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="muted">{r.seq}</td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.actor}</td>
                <td className="muted">{r.actor_role ?? "—"}</td>
                <td>{ACTIONS[r.action] ?? r.action}</td>
                <td className="muted" title={JSON.stringify(r.details)}>
                  {describe(r)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="muted">Записей нет.</p>}
      {more && (
        <button style={{ marginTop: 8 }} onClick={() => load(true)}>
          Загрузить ещё
        </button>
      )}
    </div>
  );
}
