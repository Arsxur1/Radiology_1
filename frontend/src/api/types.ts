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
