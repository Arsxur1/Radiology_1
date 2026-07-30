// Панель контроля дрейфа (ТЗ, FR-11). Доля отклонений врачом по аппаратам.
// Рост доли на конкретном аппарате — сигнал деградации, невидимый по общей метрике.

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { DriftSlice } from "../api/types";
import { BarChart } from "../components/charts/BarChart";

export function DriftPanel() {
  const [slices, setSlices] = useState<DriftSlice[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .driftRejectionRate()
      .then((r) => setSlices(r.slices))
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="layout">Загрузка…</div>;
  if (err) return <div className="layout error">Ошибка: {err}</div>;

  return (
    <div className="layout">
      <h2>Контроль дрейфа</h2>
      <p className="muted">
        Доля отклонённых врачом результатов по производителю аппарата. Рост на конкретном аппарате
        означает деградацию, которую нельзя увидеть по общей метрике (FR-11).
      </p>
      {slices.length === 0 ? (
        <p className="muted">Нет данных (правки ещё не накоплены).</p>
      ) : (
        <div className="card">
          <BarChart
            bars={slices.map((s) => ({
              label: s.value,
              value: s.rate,
              caption: `${s.rejected}/${s.total}`,
            }))}
          />
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Аппарат</th>
                <th>Всего</th>
                <th>Отклонено</th>
                <th>Доля</th>
              </tr>
            </thead>
            <tbody>
              {slices.map((s) => (
                <tr key={s.value}>
                  <td>{s.value}</td>
                  <td>{s.total}</td>
                  <td>{s.rejected}</td>
                  <td>{(s.rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
