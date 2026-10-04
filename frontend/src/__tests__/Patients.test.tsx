// «Пациенты»: сопоставление и отзыв согласия — действия с последствиями (R-05; хранение, п. 3).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PatientOut } from "../api/types";
import { setRoles } from "./apiMock";

const m = vi.hoisted(() => ({ fns: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  const { makeApi } = await import("./apiMock");
  return { ...orig, api: makeApi(m.fns) };
});

import { Patients } from "../pages/Patients";

function patient(id: string, over: Partial<PatientOut> = {}): PatientOut {
  return {
    id,
    merged_into_id: null,
    is_merged: false,
    identifiers: [{ id: `i-${id}`, id_type: "mrn", normalized_value: "h1:269cb56b0000", issuer: null, active: true }],
    study_count: 1,
    link_review: false,
    training_excluded: false,
    ...over,
  };
}

function page() {
  return render(
    <MemoryRouter>
      <Patients />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const k of Object.keys(m.fns)) delete m.fns[k];
  localStorage.clear();
});
afterEach(cleanup);

describe("очередь сопоставления", () => {
  it("«Присоединить» сливает НОВУЮ запись в кандидата, а не наоборот", async () => {
    setRoles("admin");
    m.fns.linkReviewQueue = vi.fn().mockResolvedValue([
      { patient: patient("new-0001", { link_review: true, identifiers: [] }), candidates: [patient("cand-0002")] },
    ]);
    m.fns.mergePatients = vi.fn().mockResolvedValue(patient("cand-0002"));
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Присоединить к нему" }));
    await waitFor(() => expect(m.fns.mergePatients).toHaveBeenCalledTimes(1));
    expect(m.fns.mergePatients).toHaveBeenCalledWith("new-0001", "cand-0002"); // источник, приёмник
    expect(m.fns.linkReviewQueue).toHaveBeenCalledTimes(2); // очередь перечитана
  });

  it("«Это другой пациент» снимает пометку с новой записи", async () => {
    setRoles("radiologist");
    m.fns.linkReviewQueue = vi.fn().mockResolvedValue([
      { patient: patient("new-0001", { link_review: true }), candidates: [patient("cand-0002")] },
    ]);
    m.fns.keepSeparate = vi.fn().mockResolvedValue(patient("new-0001"));
    page();
    fireEvent.click(await screen.findByRole("button", { name: "Это другой пациент" }));
    await waitFor(() => expect(m.fns.keepSeparate).toHaveBeenCalledWith("new-0001"));
  });

  it("номер карты не показывается — только отпечаток токена", async () => {
    setRoles("admin");
    m.fns.linkReviewQueue = vi.fn().mockResolvedValue([
      { patient: patient("new-0001", { link_review: true, identifiers: [] }), candidates: [patient("cand-0002")] },
    ]);
    page();
    expect(await screen.findByText(/отпечаток 269cb56b/)).toBeTruthy();
    expect(screen.queryByText(/h1:/)).toBeNull();
  });
});

describe("отзыв согласия на обучение", () => {
  async function found(roles: string, p: PatientOut) {
    setRoles(roles);
    m.fns.linkReviewQueue = vi.fn().mockResolvedValue([]);
    m.fns.searchPatients = vi.fn().mockResolvedValue([p]);
    m.fns.trainingExclusionBases = vi.fn().mockResolvedValue([
      { code: "consent_withdrawn", label: "Законный представитель отозвал согласие" },
      { code: "consent_restored", label: "Согласие получено вновь (снятие исключения)" },
    ]);
    m.fns.setTrainingExclusion = vi.fn().mockResolvedValue({ ...p, training_excluded: true });
    page();
    fireEvent.change(screen.getByPlaceholderText(/ФИО или номер карты/), { target: { value: "MRN-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    await screen.findByText(/Пациент p-000001/);
  }

  it("только администратор; без основания — нельзя; основание уходит на сервер", async () => {
    await found("admin", patient("p-000001"));
    const btn = (await screen.findByRole("button", { name: "Исключить из обучения" })) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    const basis = screen.getByLabelText("Основание");
    await screen.findByRole("option", { name: "Законный представитель отозвал согласие" });
    // Для исключения не предлагается «получено вновь».
    expect(screen.queryByRole("option", { name: /получено вновь/ })).toBeNull();
    fireEvent.change(basis, { target: { value: "consent_withdrawn" } });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(m.fns.setTrainingExclusion).toHaveBeenCalledWith("p-000001", true, "consent_withdrawn"),
    );
  });

  it("врач не видит управления согласием", async () => {
    await found("radiologist", patient("p-000001"));
    expect(screen.queryByRole("button", { name: "Исключить из обучения" })).toBeNull();
  });
});
