// Сообщение об инциденте (YUZABILITI.md: R-22): закрытые списки, предупреждение о ФИО,
// привязка к исследованию, без лишних полей.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ fns: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  const { makeApi } = await import("./apiMock");
  return { ...orig, api: makeApi(m.fns) };
});

import { ReportIncident } from "../components/ReportIncident";

beforeEach(() => {
  for (const k of Object.keys(m.fns)) delete m.fns[k];
  m.fns.incidentKinds = vi.fn().mockResolvedValue({
    kinds: [{ value: "ai_misleading", label: "Находка ИИ могла повлиять на решение" }],
    severities: [{ value: "serious", label: "Мог быть или причинён вред пациенту — срочный разбор" }],
  });
  m.fns.reportIncident = vi.fn().mockResolvedValue({});
});
afterEach(cleanup);

async function open() {
  render(<ReportIncident studyId="st-1" findings={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Сообщить об инциденте…" }));
  await screen.findByRole("option", { name: "Находка ИИ могла повлиять на решение" });
}

describe("сообщение об инциденте", () => {
  it("предупреждает не писать ФИО и номер карты", async () => {
    await open();
    expect(screen.getByText("не пишите ФИО и номер карты")).toBeTruthy();
  });

  it("отправка недоступна без вида, тяжести и описания от 10 символов", async () => {
    await open();
    const send = screen.getByRole("button", { name: "Отправить" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Вид инцидента"), { target: { value: "ai_misleading" } });
    fireEvent.change(screen.getByLabelText("Тяжесть"), { target: { value: "serious" } });
    fireEvent.change(screen.getByLabelText("Описание инцидента"), { target: { value: "коротко" } });
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Описание инцидента"), {
      target: { value: "Черновик ИИ едва не ушёл в заключение" },
    });
    expect(send.disabled).toBe(false);
  });

  it("отправляет привязку к исследованию и только поля формы", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Вид инцидента"), { target: { value: "ai_misleading" } });
    fireEvent.change(screen.getByLabelText("Тяжесть"), { target: { value: "serious" } });
    fireEvent.change(screen.getByLabelText("Описание инцидента"), {
      target: { value: "Черновик ИИ едва не ушёл в заключение" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    await waitFor(() => expect(m.fns.reportIncident).toHaveBeenCalledTimes(1));
    expect(m.fns.reportIncident.mock.calls[0][0]).toEqual({
      kind: "ai_misleading",
      severity: "serious",
      description: "Черновик ИИ едва не ушёл в заключение",
      study_id: "st-1",
      finding_id: null,
    });
    expect(await screen.findByText(/Сообщение принято/)).toBeTruthy();
  });
});
