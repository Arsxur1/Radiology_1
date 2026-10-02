// HTTP-клиент backend. Единая точка добавления заголовков аутентификации.

import { authHeaders } from "../auth";
import { ensureFresh, hasOidcSession, login } from "../oidc";
import type {
  AuditEntry,
  CalibrationProposal,
  DriftSlice,
  FindingOut,
  IdentityOut,
  PriorOut,
  SystemStatusOut,
  ModeOut,
  ModelOut,
  OperatingMode,
  PatientOut,
  PilotDashboard,
  RejectReason,
  SiteDataReport,
  PromotionGateResult,
  RegistrationOut,
  RegistrationStage,
  ReportOut,
  SegmentationShadowReport,
  ShadowReport,
  StudyOut,
  TemporalSeries,
  VocabularyConcept,
} from "./types";

const BASE = "/api";

async function send(path: string, init?: RequestInit): Promise<Response> {
  await ensureFresh();
  const doFetch = () =>
    fetch(BASE + path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(init?.headers ?? {}),
      },
    });
  let resp = await doFetch();
  if (resp.status === 401 && hasOidcSession()) {
    // Токен отозван/истёк раньше срока — одна попытка обновить, иначе повторный вход.
    if (await ensureFresh(true)) resp = await doFetch();
    if (resp.status === 401) await login(window.location.pathname);
  }
  return resp;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await send(path, init);
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = (await resp.json()).detail;
    } catch {
      detail = resp.statusText;
    }
    throw new ApiError(resp.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

/** Бинарный ответ (PNG) с заголовками аутентификации → object URL для <img>. */
async function requestBlobUrl(path: string): Promise<string> {
  const resp = await send(path, { headers: { "Content-Type": "" } });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return URL.createObjectURL(await resp.blob());
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Страница рабочего списка: исследования и общее число по фильтру (X-Total-Count). */
async function studiesPage(params: URLSearchParams): Promise<{ items: StudyOut[]; total: number }> {
  const resp = await send(`/studies?${params}`);
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return { items: (await resp.json()) as StudyOut[], total: Number(resp.headers.get("X-Total-Count") ?? 0) };
}

export const api = {
  studiesPage,
  pacsPriors: (studyId: string) => request<PriorOut[]>(`/studies/${studyId}/pacs-priors`),
  retrievePacsPrior: (studyId: string, token: string) =>
    request<{ requested: boolean; detail: string }>(`/studies/${studyId}/pacs-priors/${token}/retrieve`, {
      method: "POST",
    }),
  revealIdentity: (studyId: string, purpose: string) =>
    request<IdentityOut>(`/studies/${studyId}/identity?purpose=${encodeURIComponent(purpose)}`),

  auditList: (params: URLSearchParams) => request<AuditEntry[]>(`/audit?${params}`),
  auditVerify: () =>
    request<{ intact: boolean; checked: number; broken_at_seq: number | null }>("/audit/verify"),
  auditCsvUrl: (params: URLSearchParams) => requestBlobUrl(`/audit/export.csv?${params}`),

  chestVocabulary: (modality: string) =>
    request<VocabularyConcept[]>(`/vocabulary/chest-findings?modality=${encodeURIComponent(modality)}`),
  createFinding: (payload: { series_id: string; code: string; time_spent_seconds: number }) =>
    request<FindingOut>("/findings", { method: "POST", body: JSON.stringify({ measurements: {}, ...payload }) }),

  systemStatus: () => request<SystemStatusOut>("/system/status"),

  pilotDashboard: (weeks = 12) => request<PilotDashboard>(`/pilot/dashboard?weeks=${weeks}`),
  siteData: (days = 90) => request<SiteDataReport>(`/pilot/site-data?days=${days}`),

  seriesPreviewUrl: (seriesId: string) => requestBlobUrl(`/studies/series/${seriesId}/preview`),
  findingHeatmapUrl: (findingId: string) => requestBlobUrl(`/findings/${findingId}/heatmap`),
  requestMesh: (findingId: string) => request<FindingOut>(`/findings/${findingId}/mesh`, { method: "POST" }),
  meshUrl: (findingId: string, fmt: "stl" | "glb") => requestBlobUrl(`/findings/${findingId}/mesh.${fmt}`),

  listStudies: (modality?: string, patientId?: string) => {
    const q = new URLSearchParams();
    if (modality) q.set("modality", modality);
    if (patientId) q.set("patient_id", patientId);
    const qs = q.toString();
    return request<StudyOut[]>(`/studies${qs ? `?${qs}` : ""}`);
  },
  getStudy: (id: string) => request<StudyOut>(`/studies/${id}`),

  listModes: () => request<ModeOut[]>("/modes"),

  listSeriesFindings: (seriesId: string) =>
    request<FindingOut[]>(`/findings/series/${seriesId}`),

  confirmFinding: (id: string, timeSpentSeconds: number) =>
    request<FindingOut>(`/findings/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ time_spent_seconds: timeSpentSeconds }),
    }),

  modifyFinding: (
    id: string,
    payload: { measurements?: Record<string, unknown>; code?: string; label?: string; time_spent_seconds: number },
  ) =>
    request<FindingOut>(`/findings/${id}/modify`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Отклонение — одно действие (SR-6); причина уточняется отдельно и необязательно.
  rejectFinding: (id: string, timeSpentSeconds: number) =>
    request<FindingOut>(`/findings/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ time_spent_seconds: timeSpentSeconds }),
    }),

  setRejectReason: (id: string, reason: string) =>
    request<FindingOut>(`/findings/${id}/reject-reason`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  rejectReasons: () => request<RejectReason[]>("/findings/reject-reasons"),

  generateReport: (studyId: string, language = "ru") =>
    request<ReportOut>("/reports/generate", {
      method: "POST",
      body: JSON.stringify({ study_id: studyId, language }),
    }),

  studyReport: (studyId: string) => request<ReportOut>(`/reports/by-study/${studyId}`),
  finalizeReport: (reportId: string) =>
    request<ReportOut>(`/reports/${reportId}/finalize`, { method: "POST" }),
  sendReportToPacs: (reportId: string) =>
    request<{ sent: boolean; sop_instance_uid: string }>(`/reports/${reportId}/send-to-pacs`, { method: "POST" }),

  // ── Режимы работы (раздел 2) ─────────────────────────────────────────────
  changeMode: (modality: string, targetMode: OperatingMode) =>
    request<ModeOut>("/modes", {
      method: "POST",
      body: JSON.stringify({ modality, target_mode: targetMode }),
    }),

  // ── Реестр и жизненный цикл моделей (FR-10) ──────────────────────────────
  listModels: () => request<ModelOut[]>("/models"),

  registerCandidate: (payload: {
    name: string;
    semver: string;
    weights_hash: string;
    applicability?: Record<string, unknown>;
    task?: string;
    operating_points?: Record<string, { threshold: number }>;
  }) =>
    request<ModelOut>("/models/candidates", {
      method: "POST",
      body: JSON.stringify({ applicability: {}, ...payload }),
    }),

  calibration: (versionId: string) => request<CalibrationProposal>(`/models/${versionId}/calibration`),
  calibratedCandidate: (versionId: string) =>
    request<ModelOut>(`/models/${versionId}/calibrated-candidate`, { method: "POST" }),
  shadowReport: (versionId: string) =>
    request<ShadowReport | SegmentationShadowReport>(`/models/${versionId}/shadow-report`),

  evaluateModel: (candidateId: string) =>
    request<PromotionGateResult>(`/models/${candidateId}/evaluate`, { method: "POST" }),

  frozenEvaluation: (candidateId: string, result: unknown) =>
    request<Record<string, unknown>>(`/models/${candidateId}/frozen-evaluation`, {
      method: "POST",
      body: JSON.stringify(result),
    }),

  externalEvaluation: (candidateId: string, report: unknown) =>
    request<Record<string, unknown>>(`/models/${candidateId}/external-evaluation`, {
      method: "POST",
      body: JSON.stringify(report),
    }),

  promoteModel: (candidateId: string, justification: string) =>
    request<ModelOut>(`/models/${candidateId}/promote`, {
      method: "POST",
      body: JSON.stringify({ justification }),
    }),

  // active: версия, ставшая ACTIVE; null — ИИ этой линейки отключён (предыдущей нет).
  rollbackModel: (versionId: string, reason: string) =>
    request<{ active: ModelOut | null }>(`/models/${versionId}/rollback`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  // ── Сравнение во времени (FR-7) ──────────────────────────────────────────
  patientDynamics: (patientId: string) =>
    request<TemporalSeries[]>(`/temporal/patient/${patientId}`),

  // ── Контроль дрейфа (FR-11) ──────────────────────────────────────────────
  driftRejectionRate: () =>
    request<{ slices: DriftSlice[] }>("/learning/drift/rejection-rate"),

  // ── Совмещение модальностей (FR-4) ───────────────────────────────────────
  runRegistration: (payload: {
    fixed_series_id: string;
    moving_series_id: string;
    up_to_stage: RegistrationStage;
    use_stub: boolean;
  }) =>
    request<RegistrationOut>("/registration", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getRegistration: (id: string) => request<RegistrationOut>(`/registration/${id}`),
  listRegistrations: (patientId: string) => request<RegistrationOut[]>(`/registration?patient_id=${patientId}`),
  publishRegistration: (id: string) =>
    request<RegistrationOut>(`/registration/${id}/publish`, { method: "POST" }),
  registrationPreviewUrl: (id: string) => requestBlobUrl(`/registration/${id}/preview`),
  reviewRegistration: (id: string, approved: boolean) =>
    request<RegistrationOut>(`/registration/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),

  // ── Пациенты: объединение/разъединение (FR-1) ────────────────────────────
  getPatient: (id: string) => request<PatientOut>(`/patients/${id}`),

  searchPatients: (value: string) =>
    request<PatientOut[]>(`/patients/search/by-identifier?value=${encodeURIComponent(value)}`),

  mergePatients: (sourceId: string, targetId: string) =>
    request<PatientOut>("/patients/merge", {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    }),

  splitPatient: (payload: { source_patient_id: string; identifier_ids: string[]; study_ids: string[] }) =>
    request<PatientOut>("/patients/split", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
