// Предыдущие исследования того же пациента в PACS клиники (FR-1, FR-7).
// Список — без ФИО, номера карты и исходных UID; загрузка — по действию врача,
// исследование проходит обычный приём и обезличивание. Поиск и запрос пишутся в аудит.

import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { PriorOut } from "../api/types";

function fmtDate(d: string | null): string {
  if (!d || d.length !== 8) return d ?? "—";
  return `${d.slice(6, 8)}.${d.slice(4, 6)}.${d.slice(0, 4)}`;
}

export function PacsPriors({ studyId }: { studyId: string }) {
  const [rows, setRows] = useState<PriorOut[] | null>(null);
  const [requested, setRequested] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    setErr(null);
    try {
      setRows(await api.pacsPriors(studyId));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function retrieve(token: string) {
    setErr(null);
    try {
      await api.retrievePacsPrior(studyId, token);
      setRequested(new Set(requested).add(token));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <section className="card">
      <div className="row spread">
        <strong>Предыдущие исследования в PACS</strong>
        <button disabled={busy} onClick={load}>
          {rows ? "Обновить" : "Найти в PACS"}
        </button>
      </div>
      {rows && rows.length === 0 && <div className="muted">Других исследований пациента в PACS нет.</div>}
      {rows && rows.length > 0 && (
        <table style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Дата</th>
              <th>Модальность</th>
              <th>Описание</th>
              <th>Серий</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.token}>
                <td>{fmtDate(r.study_date)}</td>
                <td>{r.modality ?? "—"}</td>
                <td>{r.description ?? "—"}</td>
                <td>{r.series_count ?? "—"}</td>
                <td>
                  {r.is_current ? (
                    <span className="muted">текущее</span>
                  ) : r.imported_study_id ? (
                    <Link to={`/studies/${r.imported_study_id}`}>открыть</Link>
                  ) : requested.has(r.token) ? (
                    <span className="muted">запрошено — появится после приёма</span>
                  ) : (
                    <button onClick={() => retrieve(r.token)}>Загрузить</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {err && <div className="error">{err}</div>}
    </section>
  );
}
