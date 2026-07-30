// Разбор исследования: серии, находки, черновик заключения (ТЗ, FR-2, FR-8, FR-9).
//
// Заключение собирается ТОЛЬКО из подтверждённых находок; финализация — активное
// действие врача. Кнопка финализации доступна лишь после генерации черновика.

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { FindingOut, ReportOut, StudyOut } from "../api/types";
import { FindingCard } from "../components/FindingCard";

export function StudyReview() {
  const { studyId } = useParams<{ studyId: string }>();
  const [study, setStudy] = useState<StudyOut | null>(null);
  const [findings, setFindings] = useState<Record<string, FindingOut[]>>({});
  const [report, setReport] = useState<ReportOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadFindings = useCallback(async (seriesId: string) => {
    const list = await api.listSeriesFindings(seriesId);
    setFindings((prev) => ({ ...prev, [seriesId]: list }));
  }, []);

  useEffect(() => {
    if (!studyId) return;
    api
      .getStudy(studyId)
      .then((s) => {
        setStudy(s);
        s.series.forEach((se) => loadFindings(se.id));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [studyId, loadFindings]);

  function onFindingChange(seriesId: string, updated: FindingOut) {
    setFindings((prev) => ({
      ...prev,
      [seriesId]: (prev[seriesId] ?? []).map((f) => (f.id === updated.id ? updated : f)),
    }));
  }

  async function onGenerateReport() {
    if (!studyId) return;
    setError(null);
    try {
      setReport(await api.generateReport(studyId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function onFinalize() {
    if (!report) return;
    try {
      setReport(await api.finalizeReport(report.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (error) return <div className="layout error">Ошибка: {error}</div>;
  if (!study) return <div className="layout">Загрузка…</div>;

  return (
    <div className="layout">
      <p className="row spread">
        <Link to="/">← К списку</Link>
        <Link to={`/patients/${study.patient_id}/dynamics`}>Динамика пациента →</Link>
      </p>
      <h2>
        {study.modality} · {study.description ?? study.study_instance_uid}
      </h2>

      {study.series.map((se) => (
        <section key={se.id} style={{ marginBottom: 20 }}>
          <h3>
            Серия {se.modality} {se.description ? `· ${se.description}` : ""}{" "}
            {!se.is_3d_capable && <span className="muted">(не пригодна для 3D)</span>}
          </h3>
          {(findings[se.id] ?? []).length === 0 ? (
            <p className="muted">
              Находок нет (в режиме SHADOW результаты моделей не отображаются).
            </p>
          ) : (
            (findings[se.id] ?? []).map((f) => (
              <FindingCard key={f.id} finding={f} onChange={(u) => onFindingChange(se.id, u)} />
            ))
          )}
        </section>
      ))}

      <section className="card">
        <div className="row spread">
          <strong>Черновик заключения</strong>
          <div className="row">
            <button onClick={onGenerateReport}>Собрать из подтверждённых находок</button>
            <button className="primary" disabled={!report} onClick={onFinalize}>
              Финализировать
            </button>
          </div>
        </div>
        {report && (
          <>
            <p style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
              {report.draft_text || "Нет подтверждённых находок для заключения."}
            </p>
            {report.finalized_by && (
              <div className="muted">Финализировано: {report.finalized_by}</div>
            )}
          </>
        )}
        <div className="muted" style={{ marginTop: 8 }}>
          Заключение формируется только из подтверждённых врачом находок (FR-8).
        </div>
      </section>
    </div>
  );
}
