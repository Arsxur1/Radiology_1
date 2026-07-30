// Совмещение модальностей (ТЗ, FR-4). Запуск и визуальная проверка врачом.
//
// Ключевой инвариант: совмещение с неподтверждённым качеством НЕ используется
// для измерений — статус и предупреждение показываются явно.

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { RegistrationOut, RegistrationStage, StudyOut } from "../api/types";
import { hasRole } from "../auth";

interface SeriesOption {
  id: string;
  label: string;
}

const STAGES: RegistrationStage[] = ["rigid", "affine", "deformable"];

function ReviewBadge({ r }: { r: RegistrationOut }) {
  if (r.review_status === "approved")
    return <span className="badge badge-confirmed">качество подтверждено врачом</span>;
  if (r.review_status === "rejected")
    return <span className="badge badge-rejected">отклонено</span>;
  return <span className="badge badge-model">качество не подтверждено</span>;
}

export function ModalityRegistration() {
  const { patientId } = useParams<{ patientId: string }>();
  const [studies, setStudies] = useState<StudyOut[]>([]);
  const [fixed, setFixed] = useState("");
  const [moving, setMoving] = useState("");
  const [stage, setStage] = useState<RegistrationStage>("deformable");
  const [useStub, setUseStub] = useState(true);
  const [result, setResult] = useState<RegistrationOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!patientId) return;
    api
      .listStudies(undefined, patientId)
      .then(setStudies)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [patientId]);

  // Плоский список серий пациента (по всем исследованиям).
  const options: SeriesOption[] = useMemo(
    () =>
      studies.flatMap((s) =>
        s.series.map((se) => ({
          id: se.id,
          label: `${se.modality} · ${se.description ?? s.description ?? s.study_instance_uid}`,
        })),
      ),
    [studies],
  );

  async function run() {
    setErr(null);
    setResult(null);
    if (fixed === moving) {
      setErr("Опорная и совмещаемая серии должны различаться");
      return;
    }
    setBusy(true);
    try {
      setResult(
        await api.runRegistration({
          fixed_series_id: fixed,
          moving_series_id: moving,
          up_to_stage: stage,
          use_stub: useStub,
        }),
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function review(approved: boolean) {
    if (!result) return;
    setErr(null);
    try {
      setResult(await api.reviewRegistration(result.id, approved));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  const canReview = hasRole("radiologist");

  return (
    <div className="layout">
      <p>
        <Link to="/">← К списку</Link>
      </p>
      <h2>Совмещение модальностей</h2>
      <p className="muted">
        Последовательность: жёсткая → аффинная → деформируемая; метрика для разных модальностей —
        mutual information. Совмещение с неподтверждённым качеством не используется для измерений (FR-4).
      </p>

      <section className="card">
        {options.length < 2 ? (
          <p className="muted">Недостаточно серий пациента для совмещения (нужно ≥2).</p>
        ) : (
          <>
            <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
              <label>
                Опорная (fixed):{" "}
                <select value={fixed} onChange={(e) => setFixed(e.target.value)}>
                  <option value="">—</option>
                  {options.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Совмещаемая (moving):{" "}
                <select value={moving} onChange={(e) => setMoving(e.target.value)}>
                  <option value="">—</option>
                  {options.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Стадия:{" "}
                <select value={stage} onChange={(e) => setStage(e.target.value as RegistrationStage)}>
                  {STAGES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <input type="checkbox" checked={useStub} onChange={(e) => setUseStub(e.target.checked)} />{" "}
                заглушка (без GPU-стенда)
              </label>
            </div>
            <div style={{ marginTop: 10 }}>
              <button className="primary" disabled={busy || !fixed || !moving} onClick={run}>
                Совместить
              </button>
            </div>
          </>
        )}
        {err && <div className="error">Ошибка: {err}</div>}
      </section>

      {result && (
        <section className="card">
          <div className="row spread">
            <strong>Результат совмещения</strong>
            <ReviewBadge r={result} />
          </div>
          <div className="meas" style={{ margin: "8px 0" }}>
            стадия: {result.stage} · {result.metric_name}: {result.metric_value ?? "—"}
          </div>
          <div className="muted">качество: {JSON.stringify(result.quality)}</div>

          {!result.usable_for_measurements && (
            <div className="error" style={{ marginTop: 8 }}>
              Не используется для измерений, пока врач не подтвердит качество (FR-4).
            </div>
          )}

          {result.review_status === "pending" && canReview && (
            <div className="row" style={{ marginTop: 10 }}>
              <button className="primary" onClick={() => review(true)}>
                Подтвердить качество
              </button>
              <button className="danger" onClick={() => review(false)}>
                Отклонить
              </button>
            </div>
          )}
          {result.review_status === "pending" && !canReview && (
            <div className="muted" style={{ marginTop: 10 }}>
              Визуальную проверку качества выполняет врач-рентгенолог.
            </div>
          )}
        </section>
      )}
    </div>
  );
}
