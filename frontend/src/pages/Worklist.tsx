// Рабочий список исследований (ТЗ, FR-2).

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { StudyOut } from "../api/types";

export function Worklist() {
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
      <h2>Исследования</h2>
      {studies.length === 0 && <p className="muted">Нет исследований.</p>}
      <table>
        <thead>
          <tr>
            <th>Модальность</th>
            <th>Описание</th>
            <th>Аппарат</th>
            <th>Серий</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {studies.map((s) => (
            <tr key={s.id}>
              <td>{s.modality}</td>
              <td>{s.description ?? "—"}</td>
              <td>{s.manufacturer ?? "—"}</td>
              <td>{s.series.length}</td>
              <td>
                <Link to={`/studies/${s.id}`}>Открыть</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
