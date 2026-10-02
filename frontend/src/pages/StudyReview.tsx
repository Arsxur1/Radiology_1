// Разбор исследования: серии, находки, черновик заключения (ТЗ, FR-2, FR-8, FR-9).
//
// Заключение собирается ТОЛЬКО из подтверждённых находок; финализация — активное
// действие врача. Кнопка финализации доступна лишь после генерации черновика.

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { FindingOut, ReportOut, StudyOut } from "../api/types";
import { hasRole } from "../auth";
import { AddFindingForm } from "../components/AddFindingForm";
import { FindingCard } from "../components/FindingCard";
import { PacsPriors } from "../components/PacsPriors";
import { SendToPacs } from "../components/SendToPacs";
import { PatientIdentity } from "../components/PatientIdentity";
import { ReportIncident } from "../components/ReportIncident";

export function StudyReview() {
  const { studyId } = useParams<{ studyId: string }>();
  const [study, setStudy] = useState<StudyOut | null>(null);
  const [findings, setFindings] = useState<Record<string, FindingOut[]>>({});
  const [report, setReport] = useState<ReportOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [language, setLanguage] = useState<"ru" | "uz">("ru");

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
    // Уже существующее заключение (черновик или подписанное) — видно сразу при открытии.
    api
      .studyReport(studyId)
      .then((r) => {
        setReport(r);
        if (r.language === "ru" || r.language === "uz") setLanguage(r.language);
      })
      .catch(() => setReport(null)); // 404 — заключения ещё нет
  }, [studyId, loadFindings]);

  function onFindingChange(seriesId: string, updated: FindingOut) {
    setFindings((prev) => ({
      ...prev,
      [seriesId]: (prev[seriesId] ?? []).map((f) => (f.id === updated.id ? updated : f)),
    }));
  }

  async function onGenerateReport() {
    if (!studyId) return;
    setReportError(null);
    try {
      setReport(await api.generateReport(studyId, language));
    } catch (e) {
      setReportError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function onFinalize() {
    if (!report) return;
    setReportError(null);
    try {
      setReport(await api.finalizeReport(report.id));
    } catch (e) {
      // Напр.: есть черновики ИИ без решения, или находки изменились после сборки.
      setReportError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (error) return <div className="layout error">Ошибка: {error}</div>;
  if (!study) return <div className="layout">Загрузка…</div>;

  return (
    <div className="layout">
      <p className="row spread">
        <Link to="/">← К списку</Link>
        <span className="row">
          {/* OHIF (MPR, окна, измерения) — на том же сервере, порт 3000; UID псевдонимный. */}
          <a
            href={`${window.location.protocol}//${window.location.hostname}:3000/viewer?StudyInstanceUIDs=${study.study_instance_uid}`}
            target="_blank"
            rel="noreferrer"
          >
            Открыть в просмотрщике ↗
          </a>
          <Link to={`/patients/${study.patient_id}/dynamics`}>Динамика пациента →</Link>
          <Link to={`/patients/${study.patient_id}/registration`}>Совмещение модальностей →</Link>
        </span>
      </p>
      <h2>
        {study.modality} · {study.description ?? study.study_instance_uid}
      </h2>
      {hasRole("radiologist", "clinician") && <PatientIdentity studyId={study.id} />}
      {hasRole("radiologist", "clinician") && <PacsPriors studyId={study.id} />}

      {study.series.map((se) => (
        <section key={se.id} style={{ marginBottom: 20 }}>
          <h3>
            Серия {se.modality} {se.description ? `· ${se.description}` : ""}{" "}
            {!se.is_3d_capable && <span className="muted">(не пригодна для 3D)</span>}
            {se.burned_in_risk && (
              <span className="badge badge-model" style={{ marginLeft: 8 }} title="BurnedInAnnotation=YES или копия экрана: обезличивание тегов не убирает надписи в изображении">
                возможен текст с данными пациента на снимке — не идёт в обучение
              </span>
            )}
          </h3>
          {(findings[se.id] ?? []).length === 0 ? (
            <p className="muted">
              Находок нет (в режиме SHADOW результаты моделей не отображаются).
            </p>
          ) : (
            (findings[se.id] ?? []).map((f) => (
              <FindingCard key={f.id} finding={f} modality={se.modality} onChange={(u) => onFindingChange(se.id, u)} />
            ))
          )}
          {hasRole("radiologist") && (
            <AddFindingForm
              seriesId={se.id}
              modality={se.modality}
              existingCodes={(findings[se.id] ?? [])
                .filter((f) => f.confirmation_status === "confirmed" && f.code)
                .map((f) => f.code as string)}
              onAdded={(f) => setFindings((prev) => ({ ...prev, [se.id]: [...(prev[se.id] ?? []), f] }))}
            />
          )}
        </section>
      ))}

      <section className="card">
        <div className="row spread">
          <strong>{report?.finalized_by ? "Заключение (подписано)" : "Черновик заключения"}</strong>
          <div className="row">
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as "ru" | "uz")}
              disabled={!!report?.finalized_by}
              aria-label="Язык заключения"
            >
              <option value="ru">Русский</option>
              <option value="uz">O‘zbekcha</option>
            </select>
            <button onClick={onGenerateReport} disabled={!!report?.finalized_by}>
              Собрать из подтверждённых находок
            </button>
            <button className="primary" disabled={!report || !!report.finalized_by} onClick={onFinalize}>
              Подписать
            </button>
          </div>
        </div>
        {report && (
          <>
            <p style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
              {report.draft_text || "Нет подтверждённых находок для заключения."}
            </p>
            {report.finalized_by && (
              <div className="muted">Подписано: {report.finalized_by}</div>
            )}
            {report.finalized_by && hasRole("radiologist") && <SendToPacs reportId={report.id} />}
          </>
        )}
        {report?.terminology_note && (
          <div className="badge badge-model" style={{ display: "block", whiteSpace: "normal", marginTop: 8 }}>
            {report.terminology_note}
          </div>
        )}
        {reportError && <div className="error" style={{ marginTop: 8 }}>{reportError}</div>}
        <div className="muted" style={{ marginTop: 8 }}>
          Заключение формируется только из подтверждённых врачом находок (FR-8). Перед подписью
          примите решение по каждому черновику ИИ.
        </div>
      </section>
      {hasRole("radiologist", "clinician", "admin") && (
        <ReportIncident studyId={study.id} findings={Object.values(findings).flat()} />
      )}
    </div>
  );
}
