// Карточка находки ИИ: метка черновика, смысл уверенности, решение по одной находке (SR-1, SR-2, SR-6).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FindingOut } from "../api/types";

const m = vi.hoisted(() => ({ fns: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  const { makeApi } = await import("./apiMock");
  return { ...orig, api: makeApi(m.fns) };
});

import { FindingCard } from "../components/FindingCard";

function draft(over: Partial<FindingOut> = {}): FindingOut {
  return {
    id: "f-1",
    series_id: "se-1",
    coding_system: "RadLex",
    code: "CXR-200",
    label: "Плевральный выпот",
    measurements: { confidence: 0.91, threshold: 0.5 },
    source: "model",
    confirmation_status: "pending",
    has_heatmap: false,
    mesh: null,
    ...over,
  };
}

beforeEach(() => {
  for (const k of Object.keys(m.fns)) delete m.fns[k];
});
afterEach(cleanup);

describe("черновик ИИ", () => {
  it("помечен как черновик, требующий подтверждения", () => {
    render(<FindingCard finding={draft()} onChange={() => {}} />);
    expect(screen.getByText("черновик ИИ — требует подтверждения")).toBeTruthy();
    expect(screen.getByText(/источник: модель/)).toBeTruthy();
  });

  it("уверенность объяснена как оценка модели, а не вероятность диагноза (U-4)", () => {
    render(<FindingCard finding={draft()} onChange={() => {}} />);
    const conf = screen.getByText(/уверенность модели/);
    expect(conf.closest("[title]")?.getAttribute("title")).toBe("Оценка модели, а не вероятность диагноза");
    expect(conf.textContent).toContain("91%");
    expect(conf.textContent).toContain("порог показа 50%");
  });

  it("нет действия «принять всё» — только решение по этой находке (SR-2)", () => {
    render(<FindingCard finding={draft()} onChange={() => {}} />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual(expect.arrayContaining(["Подтвердить", "Изменить", "Отклонить"]));
    expect(labels.some((l) => /все|всё/i.test(l ?? ""))).toBe(false);
  });

  it("подтверждение отправляет время решения", async () => {
    const onChange = vi.fn();
    m.fns.confirmFinding = vi.fn().mockResolvedValue(draft({ confirmation_status: "confirmed" }));
    render(<FindingCard finding={draft()} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [id, seconds] = m.fns.confirmFinding.mock.calls[0];
    expect(id).toBe("f-1");
    expect(typeof seconds).toBe("number");
    expect(seconds).toBeGreaterThanOrEqual(0);
  });

  it("отклонение — одно действие, без диалога (SR-6)", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    const promptSpy = vi.spyOn(window, "prompt");
    m.fns.rejectFinding = vi.fn().mockResolvedValue(draft({ confirmation_status: "rejected" }));
    const onChange = vi.fn();
    render(<FindingCard finding={draft()} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(m.fns.rejectFinding).toHaveBeenCalledTimes(1);
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(promptSpy).not.toHaveBeenCalled();
  });

  it("ошибка сервера видна на карточке, решение не принято", async () => {
    const { ApiError } = await import("../api/client");
    m.fns.confirmFinding = vi.fn().mockRejectedValue(new ApiError(409, "Находка уже решена другим врачом"));
    const onChange = vi.fn();
    render(<FindingCard finding={draft()} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByText("Ошибка: Находка уже решена другим врачом")).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("решённые находки", () => {
  it("подтверждённая — без кнопок решения", () => {
    render(<FindingCard finding={draft({ confirmation_status: "confirmed" })} onChange={() => {}} />);
    expect(screen.getByText("подтверждено врачом")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Подтвердить" })).toBeNull();
  });

  it("находка врача не выдаётся за ИИ", () => {
    render(
      <FindingCard finding={draft({ source: "physician", measurements: {} })} onChange={() => {}} />,
    );
    expect(screen.getByText("добавлено врачом")).toBeTruthy();
    expect(screen.queryByText(/черновик ИИ/)).toBeNull();
    expect(screen.queryByText(/уверенность модели/)).toBeNull();
  });
});
