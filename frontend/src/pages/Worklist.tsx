// Рабочий список исследований (ТЗ, FR-2).
// Фильтры — на сервере: «неописанные» ищутся среди всех исследований, а не среди
// последних N. Очередь — старые сверху, чтобы ничего не залёживалось.

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { StudyOut } from "../api/types";

function formatAge(years: number | null): string {
  if (years === null) return "—";
  // Детская больница: у новорождённых счёт идёт на дни и недели.
  if (years < 1 / 12) return `${Math.max(1, Math.round(years * 365))} дн.`;
  if (years < 1) return `${Math.round(years * 12)} мес.`;
  return `${Math.floor(years)} л.`;
}

const REPORT_LABEL = {
  none: "—",
  draft: "черновик",
  signed: "подписано",
} as const;

type View = "unsigned" | "all" | "signed";
const VIEWS: [View, string][] = [
  ["unsigned", "Очередь: без подписанного заключения"],
  ["all", "Все"],
  ["signed", "Подписанные"],
];
const PAGE = 50;

export function Worklist() {
  const [view, setView] = useState<View>("unsigned");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [studies, setStudies] = useState<StudyOut[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (offset: number) => {
      setLoading(true);
      setError(null);
      const q = new URLSearchParams({
        status: view,
        order: view === "unsigned" ? "asc" : "desc",
        limit: String(PAGE),
        offset: String(offset),
      });
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);
      try {
        const page = await api.studiesPage(q);
        setStudies((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [view, dateFrom, dateTo],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  return (
    <div className="layout">
      <div className="row spread" style={{ flexWrap: "wrap", gap: 8 }}>
        <h2>Исследования</h2>
        <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
          <select value={view} onChange={(e) => setView(e.target.value as View)}>
            {VIEWS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
          <label className="muted">
            с <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label className="muted">
            по <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
        </div>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {view === "unsigned" ? "Старые сверху. " : ""}Найдено: {total.toLocaleString("ru-RU")}
      </p>
      {error && <div className="error">Ошибка: {error}</div>}
      {!loading && studies.length === 0 && !error && <p className="muted">Нет исследований.</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Дата</th>
              <th>Возраст</th>
              <th>Модальность</th>
              <th>Описание</th>
              <th>Аппарат</th>
              <th>ИИ</th>
              <th>Заключение</th>
            </tr>
          </thead>
          <tbody>
            {studies.map((s) => (
              <tr key={s.id}>
                <td>{s.study_date ? new Date(s.study_date).toLocaleDateString("ru-RU") : "—"}</td>
                <td>{formatAge(s.patient_age_years)}</td>
                <td>{s.modality}</td>
                <td>
                  <Link to={`/studies/${s.id}`}>{s.description ?? s.study_instance_uid}</Link>
                </td>
                <td>{s.manufacturer ?? "—"}</td>
                <td>
                  {s.ai_pending > 0 ? (
                    <span className="badge badge-model">
                      {s.ai_pending} {s.ai_pending % 10 === 1 && s.ai_pending % 100 !== 11 ? "ждёт" : "ждут"} решения
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {s.report_status === "signed" ? (
                    <span className="badge badge-confirmed">подписано</span>
                  ) : (
                    <span className="muted">{REPORT_LABEL[s.report_status]}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loading && <p className="muted">Загрузка…</p>}
      {!loading && studies.length < total && (
        <button onClick={() => load(studies.length)} style={{ marginTop: 10 }}>
          Показать ещё ({(total - studies.length).toLocaleString("ru-RU")})
        </button>
      )}
    </div>
  );
}
