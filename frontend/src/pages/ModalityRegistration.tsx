// Совмещение модальностей (ТЗ, FR-4). Запуск и визуальная проверка врачом.
//
// Ключевой инвариант: совмещение с неподтверждённым качеством НЕ используется
// для измерений — статус и предупреждение показываются явно.

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { RegistrationOut, RegistrationStage, RegistrationStageQuality, StudyOut } from "../api/types";
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

const STAGE_RU: Record<string, string> = { rigid: "жёсткая", affine: "аффинная", deformable: "деформируемая" };

function QualityTable({ q }: { q: Record<string, unknown> }) {
  const stages = (q.stages ?? {}) as Record<string, RegistrationStageQuality>;
  const warnings = (q.warnings ?? []) as { code: string; text: string; blocking: boolean }[];
  if (!q.mi_initial && Object.keys(stages).length === 0) return null;
  return (
    <div style={{ margin: "8px 0" }}>
      <table>
        <thead>
          <tr>
            <th>Стадия</th>
            <th title="Взаимная информация, больше — лучше">MI</th>
            <th title="Перекрытие контуров тела">Dice</th>
            <th>Примечание</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>до совмещения</td>
            <td>{String(q.mi_initial ?? "—")}</td>
            <td>{String(q.dice_initial ?? "—")}</td>
            <td />
          </tr>
          {STAGES.filter((s) => stages[s]).map((s) => (
            <tr key={s} style={stages[s].accepted === false ? { opacity: 0.55 } : undefined}>
              <td>{STAGE_RU[s]}</td>
              <td>{stages[s].mi}</td>
              <td>{stages[s].dice}</td>
              <td className="muted">
                {stages[s].accepted === false && "не применена (ухудшила) "}
                {stages[s].jacobian_min !== undefined &&
                  `якобиан ${stages[s].jacobian_min}…${stages[s].jacobian_max}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {typeof q.runtime_s === "number" && (
        <div className="muted" style={{ fontSize: 12 }}>
          {String(q.engine ?? "")} {String(q.engine_version ?? "")}, {q.runtime_s} с
        </div>
      )}
      {warnings.map((w) => (
        <div key={w.code} className={w.blocking ? "error" : "muted"}>
          ⚠ {w.text}
        </div>
      ))}
    </div>
  );
}

function Preview({ r }: { r: RegistrationOut }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!r.has_preview) return;
    let u: string | null = null;
    api
      .registrationPreviewUrl(r.id)
      .then((x) => setUrl((u = x)))
      .catch(() => setUrl(null));
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [r.id, r.has_preview]);
  if (!url) return null;
  return (
    <div style={{ margin: "8px 0" }}>
      <img src={url} alt="шахматка совмещения" style={{ maxWidth: "100%", imageRendering: "auto" }} />
      <div className="muted" style={{ fontSize: 12 }}>
        Шахматка: клетки опорной и совмещённой серий чередуются (аксиальный, корональный, сагиттальный срезы).
        Контуры органов должны продолжаться через границы клеток без сдвига.
      </div>
    </div>
  );
}

function PublishBlock({ r, studyUid, onPublish }: { r: RegistrationOut; studyUid?: string; onPublish: () => void }) {
  const pub = r.quality.published as { status: string; instances?: number; error?: string } | undefined;
  const viewer = studyUid
    ? `${window.location.protocol}//${window.location.hostname}:3000/viewer?StudyInstanceUIDs=${studyUid}`
    : null;
  return (
    <div style={{ marginTop: 10 }}>
      {(!pub || pub.status === "failed") && (
        <button className="primary" onClick={onPublish}>
          Показать совмещённую серию в просмотрщике
        </button>
      )}
      {pub?.status === "queued" && <span className="muted">Готовится совмещённая серия…</span>}
      {pub?.status === "failed" && <div className="error">Не удалось: {pub.error}</div>}
      {pub?.status === "done" && (
        <div className="row">
          <span className="muted">
            Совмещённая серия ({pub.instances} срезов) добавлена в опорное исследование — та же система координат,
            синхронная прокрутка и наложение в OHIF.
          </span>
          {viewer && (
            <a href={viewer} target="_blank" rel="noreferrer">
              Открыть в просмотрщике ↗
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function ModalityRegistration() {
  const { patientId } = useParams<{ patientId: string }>();
  const [studies, setStudies] = useState<StudyOut[]>([]);
  const [fixed, setFixed] = useState("");
  const [moving, setMoving] = useState("");
  const [stage, setStage] = useState<RegistrationStage>("deformable");
  const [useStub, setUseStub] = useState(false);
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
  const status = (result?.quality.status as string | undefined) ?? "done";

  const publishing = (result?.quality.published as { status?: string } | undefined)?.status === "queued";
  // Настоящее совмещение и публикация считаются в воркере — опрашиваем до готовности.
  useEffect(() => {
    if (!result || (status !== "queued" && status !== "running" && !publishing)) return;
    const t = window.setInterval(() => {
      api
        .getRegistration(result.id)
        .then(setResult)
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(t);
  }, [result, status, publishing]);

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
                демо-заглушка (результат нельзя подтвердить)
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
          {status === "queued" || status === "running" ? (
            <div className="muted" style={{ margin: "8px 0" }}>
              {status === "queued" ? "В очереди…" : "Считается (жёсткая → аффинная → деформируемая)…"}
            </div>
          ) : (
            <>
              <div className="meas" style={{ margin: "8px 0" }}>
                достигнутая стадия: {STAGE_RU[result.stage] ?? result.stage}
                {result.quality.requested_stage && result.quality.requested_stage !== result.stage
                  ? ` (запрошена: ${STAGE_RU[result.quality.requested_stage as string]})`
                  : ""}{" "}
                · {result.metric_name}: {result.metric_value ?? "—"}
              </div>
              <QualityTable q={result.quality} />
              <Preview r={result} />
            </>
          )}

          {!result.usable_for_measurements && (
            <div className="error" style={{ marginTop: 8 }}>
              Не используется для измерений, пока врач не подтвердит качество (FR-4).
            </div>
          )}

          {result.review_status === "pending" && canReview && result.review_blockers.length > 0 && (
            <div className="muted" style={{ marginTop: 8 }}>
              Подтвердить нельзя: {result.review_blockers.join("; ")}
            </div>
          )}
          {result.review_status === "pending" && canReview && (
            <div className="row" style={{ marginTop: 10 }}>
              <button
                className="primary"
                disabled={result.review_blockers.length > 0}
                onClick={() => review(true)}
              >
                Подтвердить качество
              </button>
              <button className="danger" onClick={() => review(false)}>
                Отклонить
              </button>
            </div>
          )}
          {result.review_status === "approved" && canReview && (
            <PublishBlock
              r={result}
              studyUid={studies.find((st) => st.series.some((se) => se.id === result.fixed_series_id))?.study_instance_uid}
              onPublish={async () => {
                setErr(null);
                try {
                  setResult(await api.publishRegistration(result.id));
                } catch (e) {
                  setErr(e instanceof ApiError ? e.message : String(e));
                }
              }}
            />
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
