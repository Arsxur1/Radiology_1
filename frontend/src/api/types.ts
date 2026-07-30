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
}

export interface StudyOut {
  id: string;
  patient_id: string;
  study_instance_uid: string;
  modality: string;
  description: string | null;
  manufacturer: string | null;
  series: SeriesOut[];
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
}

export type ModelStatus = "shadow" | "active" | "retired";

export interface ModelOut {
  id: string;
  name: string;
  semver: string;
  weights_hash: string;
  status: ModelStatus;
  applicability: Record<string, unknown>;
}

export interface PromotionEvidence {
  frozen_test_cases: number;
  frozen_test_superior: boolean;
  shadow_rejection_rate: number | null;
  no_regression_on_new_devices: boolean;
}

export interface PromotionGateResult {
  ok: boolean;
  reasons: string[];
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
}
