// Типы ответов backend (соответствуют Pydantic-схемам API).

export type OperatingMode = "RESEARCH" | "SHADOW" | "ASSIST";

export interface SeriesOut {
  id: string;
  series_instance_uid: string;
  modality: string;
  description: string | null;
  instance_count: number | null;
  slice_thickness_mm: number | null;
  lossy_compressed: boolean;
  is_3d_capable: boolean;
  /** Возможен текст с данными пациента в пикселях: в обучение не идёт. */
  burned_in_risk?: boolean;
}

export interface StudyOut {
  id: string;
  patient_id: string;
  study_instance_uid: string;
  modality: string;
  description: string | null;
  manufacturer: string | null;
  series: SeriesOut[];
  study_date: string | null;
  patient_age_years: number | null;
  ai_pending: number;
  report_status: "none" | "draft" | "signed";
}

export type FindingSource = "model" | "physician";
export type ConfirmationStatus = "pending" | "confirmed" | "rejected";

export interface FindingOut {
  id: string;
  series_id: string;
  coding_system: string;
  code: string | null;
  label: string | null;
  measurements: Record<string, unknown>;
  source: FindingSource;
  confirmation_status: ConfirmationStatus;
  has_heatmap: boolean;
  mesh: MeshState | null;
  /** Код причины отклонения (SR-6), если врач её указал. */
  reject_reason?: string | null;
}

export interface RejectReason {
  code: string;
  label: string;
}

/** 3D-модель структуры (FR-5): строится в фоне из подтверждённой маски. */
export interface MeshState {
  status: "queued" | "ready" | "failed";
  reason?: string;
  vertices?: number;
  faces?: number;
  surface_mm2?: number;
  volume_ml?: number;
  marching_cubes_step?: number;
}

export interface ModeOut {
  modality: string;
  mode: OperatingMode;
}

export interface ReportOut {
  id: string;
  study_id: string;
  language: string;
  draft_text: string | null;
  sentence_map: Record<string, string>;
  finalized_by: string | null;
  terminology_note: string | null;
}

export type ModelStatus = "shadow" | "active" | "retired";

export interface ModelOut {
  id: string;
  name: string;
  semver: string;
  weights_hash: string;
  status: ModelStatus;
  applicability: Record<string, unknown>;
  task: "segmentation" | "classification";
  operating_points: Record<string, { threshold: number }>;
  adapter: { type?: string; weights?: string };
}

export interface CalibrationProposal {
  model: string;
  calibration_cases: number;
  held_out_test_cases: number;
  changed_codes: string[];
  per_code: Record<
    string,
    { current: number; proposed: number; n_pos: number; n_neg: number; changed: boolean; sensitivity?: number; specificity?: number }
  >;
}

export interface ShadowCounts {
  tp: number;
  fp: number;
  fn: number;
}

export interface SegShadowSummary {
  n: number;
  median_rel_error: number;
  within_tolerance: number;
}

export interface SegmentationShadowReport {
  task: "segmentation";
  model: string;
  tolerance: number;
  shadow_runs: number;
  compared_series: number;
  disagreement_rate: number | null;
  overall: SegShadowSummary | null;
  per_structure: Record<string, SegShadowSummary>;
  per_age_group: Record<string, SegShadowSummary>;
}

export interface ShadowReport {
  task?: undefined;
  model: string;
  shadow_runs: number;
  reviewed_cases: number;
  disagreement_rate: number | null;
  miss_rate: number | null;
  per_code: Record<string, ShadowCounts & { tn: number; sensitivity: number | null; ppv: number | null }>;
  per_manufacturer: Record<
    string,
    ShadowCounts & { cases: number; disagreement_rate: number | null; miss_rate: number | null }
  >;
  per_age_group: Record<
    string,
    ShadowCounts & { cases: number; disagreement_rate: number | null; miss_rate: number | null }
  >;
}

/** Свидетельства гейта, собранные сервером (не вводятся вручную). */
export interface PromotionEvidence {
  frozen_test_cases: number;
  frozen_test_superior: boolean;
  shadow_rejection_rate: number | null;
  shadow_reviewed_cases: number;
  no_regression_on_new_devices: boolean;
  slice_problems: string[];
  notes: string[];
  active_model: string | null;
  /** Внешние детские проверки (открытые наборы): название набора → сводка. */
  external_tests?: Record<
    string,
    {
      n?: { total?: number } | null;
      any_finding_auroc?: number | null;
      any_finding_auroc_ci95?: [number, number] | null;
      normal_with_any_draft?: number | null;
      pneumonia_with_any_draft?: number | null;
    }
  >;
  /** Происхождение обучающих данных и право на коммерческое применение. */
  data_provenance?: {
    training_data: string[];
    commercial: "yes" | "no" | "unknown";
    research_only: string[];
    unverified: string[];
    checked: string;
  };
}

export interface PromotionGateResult {
  ok: boolean;
  reasons: string[];
  evidence: PromotionEvidence;
}

export interface TemporalDelta {
  metric: string;
  previous: number;
  current: number;
  absolute: number;
  percent: number | null;
  direction: string;
}

export interface TemporalPoint {
  study_id: string;
  study_date: string | null;
  finding_id: string;
  measurements: Record<string, number>;
}

export interface TemporalSeries {
  key: string;
  label: string | null;
  points: TemporalPoint[];
  deltas: TemporalDelta[];
}

export interface DriftSlice {
  dimension: string;
  value: string;
  total: number;
  rejected: number;
  rate: number;
}

export interface PatientIdentifierOut {
  id: string;
  id_type: string;
  normalized_value: string;
  issuer: string | null;
  active: boolean;
}

export interface PatientOut {
  id: string;
  merged_into_id: string | null;
  is_merged: boolean;
  identifiers: PatientIdentifierOut[];
  study_count: number;
}

export type RegistrationStage = "rigid" | "affine" | "deformable";
export type RegistrationReview = "pending" | "approved" | "rejected";

export interface RegistrationOut {
  id: string;
  fixed_series_id: string;
  moving_series_id: string;
  stage: RegistrationStage;
  metric_name: string;
  metric_value: number | null;
  quality: Record<string, unknown>;
  review_status: RegistrationReview;
  usable_for_measurements: boolean;
  review_blockers: string[];
  has_preview: boolean;
  created_at?: string;
}

export interface RegistrationStageQuality {
  mi: number;
  dice: number;
  accepted?: boolean;
  jacobian_min?: number;
  jacobian_max?: number;
}

export interface PilotDashboard {
  generated_at: string;
  weeks: string[];
  totals: {
    studies: number;
    pediatric_studies: number;
    adult_studies: number;
    studies_without_age: number;
    studies_by_modality: Record<string, number>;
    series_by_modality: Record<string, number>;
    reports_finalized: number;
    physician_decisions: number;
    physician_added_findings: number;
    ai_refusals: number;
  };
  weekly: Record<"studies" | "physician_decisions" | "reports_finalized" | "ai_refusals", number[]>;
  ai_drafts: {
    pending: number;
    confirmed: number;
    rejected: number;
    acceptance_rate: number | null;
    corrections_by_type: Record<string, number>;
  };
  refusal_reasons: Record<string, number>;
  reject_reasons: Record<string, number>;
  training_data: {
    records: number;
    populations: Record<string, number>;
    finalized: number;
    skipped_no_age: number;
    positives: { code: string; label: string; count: number }[];
    splits: Record<string, number>;
  };
  shadow_models: {
    model_version_id: string;
    model: string;
    shadow_runs: number;
    reviewed_cases: number;
    disagreement_rate: number | null;
    miss_rate: number | null;
  }[];
}

export interface VocabularyConcept {
  code: string;
  label_ru: string;
  group: string;
  modalities: string[];
  radlex: string | null;
  note: string | null;
}

export interface AuditEntry {
  id: string;
  seq: number | null;
  created_at: string;
  actor: string;
  actor_role: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown>;
}

export interface IdentityOut {
  patient_name: string | null;
  patient_mrn: string | null;
  original_study_instance_uid: string | null;
  purpose: string;
}

/** Исследование пациента в PACS клиники — без PHI; token заменяет исходный UID. */
export interface PriorOut {
  token: string;
  study_date: string | null;
  modality: string | null;
  description: string | null;
  series_count: number | null;
  is_current: boolean;
  imported_study_id: string | null;
}

export interface SystemCheck {
  name: string;
  ok: boolean;
  warn: boolean;
  detail: string;
  ms: number;
}

export interface SystemStatusOut {
  status: "ok" | "degraded" | "down";
  functions: Record<string, "ok" | "degraded" | "down">;
  checks: SystemCheck[];
  checked_at: number;
}

export interface SiteDataDevice {
  device: string;
  studies: number;
  modalities: string[];
  body_part_share: number | null;
  age_share: number | null;
  region_share: number | null;
  charset_guessed: number;
  burned_in_risk?: number;
}

export interface SiteDataReport {
  days: number;
  studies: number;
  modalities: Record<string, number>;
  age_groups: Record<string, number>;
  region_source: Record<string, number>;
  charset_guessed: Record<string, number>;
  per_device: SiteDataDevice[];
  unrecognized_descriptions: { text: string; studies: number }[];
  rare_unrecognized_studies: number;
  min_description_count: number;
  issues: string[];
  ready: boolean;
}
