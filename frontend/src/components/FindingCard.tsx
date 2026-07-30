// Карточка находки — сердце разделения «система посчитала / врач подтвердил»
// (ТЗ, раздел 11; SR-2, SR-6, FR-9).
//
// - Находка модели ЯВНО маркируется как черновик ИИ и требует активного действия.
// - Никакого «принять всё»: каждое решение — по одной находке.
// - Затраченное время фиксируется от момента появления карточки (обучающий сигнал).

import { useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { FindingOut } from "../api/types";

function StatusBadge({ f }: { f: FindingOut }) {
  if (f.confirmation_status === "confirmed")
    return <span className="badge badge-confirmed">подтверждено врачом</span>;
  if (f.confirmation_status === "rejected")
    return <span className="badge badge-rejected">отклонено</span>;
  if (f.source === "model")
    return <span className="badge badge-model">черновик ИИ — требует подтверждения</span>;
  return <span className="badge badge-physician">добавлено врачом</span>;
}

function Measurements({ m }: { m: Record<string, unknown> }) {
  const entries = Object.entries(m);
  if (entries.length === 0) return <span className="muted">измерения отсутствуют</span>;
  return (
    <span className="meas">
      {entries.map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("; ")}
    </span>
  );
}

export function FindingCard({ finding, onChange }: { finding: FindingOut; onChange: (f: FindingOut) => void }) {
  // Момент, когда карточка стала видна врачу — для расчёта затраченного времени.
  const shownAt = useRef<number>(Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const elapsed = () => (Date.now() - shownAt.current) / 1000;
  const decided = finding.confirmation_status !== "pending";

  async function act(fn: () => Promise<FindingOut>) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onModify() {
    const raw = window.prompt("Новый объём (мл), оставьте пустым чтобы не менять:");
    if (raw === null) return;
    const measurements = raw.trim() ? { volume_ml: Number(raw) } : undefined;
    await act(() => api.modifyFinding(finding.id, { measurements, time_spent_seconds: elapsed() }));
  }

  async function onReject() {
    const reason = window.prompt("Причина отклонения:") ?? "";
    await act(() => api.rejectFinding(finding.id, reason, elapsed()));
  }

  return (
    <div className="card">
      <div className="row spread">
        <strong>{finding.label ?? finding.code ?? "структура"}</strong>
        <StatusBadge f={finding} />
      </div>
      <div className="muted" style={{ margin: "6px 0" }}>
        {finding.coding_system}
        {finding.code ? `: ${finding.code}` : ""} · источник: {finding.source === "model" ? "модель" : "врач"}
      </div>
      <div style={{ marginBottom: 10 }}>
        <Measurements m={finding.measurements} />
      </div>
      {!decided && (
        <div className="row">
          {/* Активное действие по одной находке (SR-2). */}
          <button
            className="primary"
            disabled={busy}
            onClick={() => act(() => api.confirmFinding(finding.id, elapsed()))}
          >
            Подтвердить
          </button>
          <button disabled={busy} onClick={onModify}>
            Изменить
          </button>
          <button className="danger" disabled={busy} onClick={onReject}>
            Отклонить
          </button>
        </div>
      )}
      {error && <div className="error">Ошибка: {error}</div>}
    </div>
  );
}
