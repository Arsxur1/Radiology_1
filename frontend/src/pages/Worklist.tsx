// Рабочий список исследований (ТЗ, FR-2).

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { StudyOut } from "../api/types";

function formatAge(years: number | null): string {
  if (years === null) return "—";
  if (years < 1) return `${Math.round(years * 12)} мес.`;
  return `${Math.floor(years)} л.`;
}

const REPORT_LABEL = {
  none: "—",
  draft: "черновик",
  signed: "подписано",
} as const;

export function Worklist() {
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [studies, setStudies] = useState<StudyOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listStudies()
      .then(setStudies)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="layout">Загрузка…</div>;
  if (error) return <div className="layout error">Ошибка: {error}</div>;

  return (
    <div className="layout">
      <div className="row spread">
        <h2>Исследования</h2>
        <label className="muted">
          <input
            type="checkbox"
            checked={onlyAttention}
            onChange={(e) => setOnlyAttention(e.target.checked)}
          />{" "}
          только требующие внимания
        </label>
      </div>
      {studies.length === 0 && <p className="muted">Нет исследований.</p>}
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
            {studies
              .filter(
                (s) =>
                  !onlyAttention ||
                  s.ai_pending > 0 ||
                  s.report_status !== "signed",
              )
              .map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.study_date
                      ? new Date(s.study_date).toLocaleDateString()
                      : "—"}
                  </td>
                  <td>{formatAge(s.patient_age_years)}</td>
                  <td>{s.modality}</td>
                  <td>
                  <Link to={`/studies/${s.id}`}>{s.description ?? s.study_instance_uid}</Link>
                </td>
                  <td>{s.manufacturer ?? "—"}</td>
                  <td>
                    {s.ai_pending > 0 ? (
                      <span className="badge badge-model">
                        {s.ai_pending} ждут решения
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {s.report_status === "signed" ? (
                      <span className="badge badge-confirmed">подписано</span>
                    ) : (
                      <span className="muted">
                        {REPORT_LABEL[s.report_status]}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
