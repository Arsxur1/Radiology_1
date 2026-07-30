// Динамика находок пациента во времени (ТЗ, FR-7). Без ИИ, по подтверждённым находкам.

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { TemporalSeries } from "../api/types";
import { LineChart, type LinePoint } from "../components/charts/LineChart";

function seriesToLine(s: TemporalSeries, metric: string): LinePoint[] {
  return s.points
    .filter((p) => typeof p.measurements[metric] === "number")
    .map((p) => ({
      label: p.study_date ? p.study_date.slice(0, 10) : "—",
      value: p.measurements[metric] as number,
    }));
}

function metricsOf(s: TemporalSeries): string[] {
  const keys = new Set<string>();
  s.points.forEach((p) => Object.entries(p.measurements).forEach(([k, v]) => {
    if (typeof v === "number") keys.add(k);
  }));
  return [...keys];
}

export function PatientDynamics() {
  const { patientId } = useParams<{ patientId: string }>();
  const [series, setSeries] = useState<TemporalSeries[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!patientId) return;
    api
      .patientDynamics(patientId)
      .then(setSeries)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [patientId]);

  if (loading) return <div className="layout">Загрузка…</div>;
  if (err) return <div className="layout error">Ошибка: {err}</div>;

  return (
    <div className="layout">
      <p>
        <Link to="/">← К списку</Link>
      </p>
      <h2>Динамика пациента</h2>
      <p className="muted">Только подтверждённые находки. Функция работает без ИИ-моделей (FR-7).</p>
      {series.length === 0 && <p className="muted">Нет данных для сравнения.</p>}
      {series.map((s) => (
        <section key={s.key} className="card">
          <strong>{s.label ?? s.key}</strong>
          {metricsOf(s).map((metric) => {
            const pts = seriesToLine(s, metric);
            if (pts.length === 0) return null;
            return (
              <div key={metric} style={{ marginTop: 10 }}>
                <div className="muted">{metric}</div>
                <LineChart points={pts} />
              </div>
            );
          })}
          {s.deltas.length > 0 && (
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Метрика</th>
                  <th>Было</th>
                  <th>Стало</th>
                  <th>Δ</th>
                  <th>%</th>
                  <th>Динамика</th>
                </tr>
              </thead>
              <tbody>
                {s.deltas.map((d) => (
                  <tr key={d.metric}>
                    <td>{d.metric}</td>
                    <td>{d.previous}</td>
                    <td>{d.current}</td>
                    <td>{d.absolute}</td>
                    <td>{d.percent === null ? "—" : `${d.percent}%`}</td>
                    <td>{d.direction}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ))}
    </div>
  );
}
