// Страница исследования: что врач видит об ИИ и пациенте (YUZABILITI.md: U-2, U-3, U-6; SR-2).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportOut, StudyOut } from "../api/types";
import { setRoles } from "./apiMock";

const m = vi.hoisted(() => ({ fns: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  const { makeApi } = await import("./apiMock");
  return { ...orig, api: makeApi(m.fns) };
});

import { ApiError } from "../api/client";
import { StudyReview } from "../pages/StudyReview";

function study(over: Partial<StudyOut> = {}, refusals: StudyOut["series"][0]["ai_refusals"] = []): StudyOut {
  return {
    id: "st-1",
    patient_id: "p-1",
    study_instance_uid: "1.2.3",
    modality: "DX",
    description: "Грудная клетка",
    manufacturer: "SynthCo",
    study_date: null,
    patient_age_years: 5,
    ai_pending: 0,
    report_status: "none",
    patient_link_review: false,
    series: [
      {
        id: "se-1",
        series_instance_uid: "1.2.3.1",
        modality: "DX",
        description: null,
        instance_count: 1,
        slice_thickness_mm: null,
        lossy_compressed: false,
        is_3d_capable: false,
        ai_refusals: refusals,
      },
    ],
    ...over,
  };
}

function show(s: StudyOut, report: ReportOut | null = null) {
  m.fns.getStudy = vi.fn().mockResolvedValue(s);
  m.fns.studyReport = report
    ? vi.fn().mockResolvedValue(report)
    : vi.fn().mockRejectedValue(new ApiError(404, "заключения нет"));
  return render(
    <MemoryRouter initialEntries={["/studies/st-1"]}>
      <Routes>
        <Route path="/studies/:studyId" element={<StudyReview />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const k of Object.keys(m.fns)) delete m.fns[k];
  localStorage.clear();
  setRoles("radiologist");
});
afterEach(cleanup);

describe("пустая серия и отказ ИИ", () => {
  it("пустая серия не выглядит как «норма» от ИИ (U-2)", async () => {
    show(study());
    expect(await screen.findByText(/Отсутствие черновиков ИИ не означает отсутствие патологии/)).toBeTruthy();
    expect(screen.queryByText(/^Находок нет/)).toBeNull();
  });

  it("отказ модели виден с причиной (U-3, SR-7)", async () => {
    show(study({}, [{ model: "cxr_peds@1.0", reasons: ["Не указана область исследования"] }]));
    const note = await screen.findByText(/ИИ не анализировал эту серию/);
    const box = note.closest('[role="status"]');
    expect(box?.textContent).toContain("cxr_peds@1.0");
    expect(box?.textContent).toContain("Не указана область исследования");
    expect(box?.textContent).toContain("не означает, что патологии нет");
  });

  it("без отказа баннера нет", async () => {
    show(study());
    await screen.findByText(/Отсутствие черновиков ИИ/);
    expect(screen.queryByText(/ИИ не анализировал эту серию/)).toBeNull();
  });
});

describe("сопоставление пациента (U-6)", () => {
  it("предупреждение о несопоставленном пациенте", async () => {
    show(study({ patient_link_review: true }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Пациент не сопоставлен однозначно");
    expect(alert.textContent).toContain("Прошлые исследования этого ребёнка здесь могут не отображаться");
  });

  it("обычный пациент — без предупреждения", async () => {
    show(study());
    await screen.findByText(/Отсутствие черновиков ИИ/);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("подпись заключения (SR-2)", () => {
  it("отказ сервера подписать показывается врачу дословно", async () => {
    const draft: ReportOut = {
      id: "r-1",
      study_id: "st-1",
      language: "ru",
      draft_text: "Выпот справа.",
      sentence_map: {},
      finalized_by: null,
      terminology_note: null,
    };
    m.fns.finalizeReport = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "Есть черновики ИИ без решения врача (1): Выпот"));
    show(study(), draft);
    await screen.findByText("Выпот справа.");
    fireEvent.click(screen.getByRole("button", { name: "Подписать" }));
    expect(await screen.findByText("Есть черновики ИИ без решения врача (1): Выпот")).toBeTruthy();
    expect(m.fns.finalizeReport).toHaveBeenCalledWith("r-1");
  });
});
