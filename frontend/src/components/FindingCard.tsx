// Карточка находки — сердце разделения «система посчитала / врач подтвердил»
// (ТЗ, раздел 11; SR-2, SR-6, FR-9).
//
// - Находка модели ЯВНО маркируется как черновик ИИ и требует активного действия.
// - Никакого «принять всё»: каждое решение — по одной находке.
// - Затраченное время фиксируется от момента появления карточки (обучающий сигнал).

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { FindingOut } from "../api/types";
import { MeshViewer } from "./MeshViewer";

function StatusBadge({ f }: { f: FindingOut }) {
  if (f.confirmation_status === "confirmed")
    return <span className="badge badge-confirmed">подтверждено врачом</span>;
  if (f.confirmation_status === "rejected")
    return <span className="badge badge-rejected">отклонено</span>;
  if (f.source === "model")
    return <span className="badge badge-model">черновик ИИ — требует подтверждения</span>;
  return <span className="badge badge-physician">добавлено врачом</span>;
}

// Служебные величины классификатора показываются отдельно, не как измерения.
const SERVICE_KEYS = new Set(["confidence", "threshold"]);

function Measurements({ m, qualitative }: { m: Record<string, unknown>; qualitative: boolean }) {
  const entries = Object.entries(m).filter(([k]) => !SERVICE_KEYS.has(k));
  if (entries.length === 0 && qualitative) return null;
  if (entries.length === 0) return <span className="muted">измерения отсутствуют</span>;
  return (
    <span className="meas">
      {entries.map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("; ")}
    </span>
  );
}

function Confidence({ m }: { m: Record<string, unknown> }) {
  const p = typeof m.confidence === "number" ? m.confidence : null;
  const t = typeof m.threshold === "number" ? m.threshold : null;
  if (p === null) return null;
  return (
    <div className="muted" style={{ marginBottom: 6 }} title="Оценка модели, а не вероятность диагноза">
      уверенность модели: <strong>{Math.round(p * 100)}%</strong>
      {t !== null && <> (порог показа {Math.round(t * 100)}%)</>}
      <div style={{ background: "#333", height: 4, borderRadius: 2, marginTop: 3, maxWidth: 240 }}>
        <div style={{ width: `${Math.round(p * 100)}%`, background: "#d9a441", height: 4, borderRadius: 2 }} />
      </div>
    </div>
  );
}

function HeatmapView({ finding }: { finding: FindingOut }) {
  const [urls, setUrls] = useState<{ image: string; heat: string } | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(
    () => () => {
      if (urls) {
        URL.revokeObjectURL(urls.image);
        URL.revokeObjectURL(urls.heat);
      }
    },
    [urls],
  );

  async function toggle() {
    setErr(null);
    if (!open && !urls) {
      try {
        const [image, heat] = await Promise.all([
          api.seriesPreviewUrl(finding.series_id),
          api.findingHeatmapUrl(finding.id),
        ]);
        setUrls({ image, heat });
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : String(e));
        return;
      }
    }
    setOpen(!open);
  }

  return (
    <div style={{ marginBottom: 10 }}>
      <button onClick={toggle}>{open ? "Скрыть зону внимания" : "Зона внимания ИИ"}</button>
      {open && urls && (
        <div style={{ marginTop: 6 }}>
          <div style={{ position: "relative", display: "inline-block", maxWidth: "100%" }}>
            <img src={urls.image} alt="снимок" style={{ display: "block", maxWidth: "100%", maxHeight: 420 }} />
            <img
              src={urls.heat}
              alt="зона внимания модели"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
            />
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            Показывает, на какие области опиралась модель. Это не разметка патологии и не измерение.
          </div>
        </div>
      )}
      {err && <div className="error">Карта недоступна: {err}</div>}
    </div>
  );
}

// 3D-модель структуры (FR-5): только по подтверждённой и не исправленной маске модели.
// Гейт (толщина среза, сжатие, подтверждение) проверяет сервер и сообщает причину отказа.
function MeshPanel({ finding, onChange }: { finding: FindingOut; onChange: (f: FindingOut) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show3d, setShow3d] = useState(false);
  const mesh = finding.mesh;

  useEffect(() => {
    if (mesh?.status !== "queued") return;
    const t = window.setInterval(async () => {
      try {
        const fresh = (await api.listSeriesFindings(finding.series_id)).find((f) => f.id === finding.id);
        if (fresh && fresh.mesh?.status !== "queued") onChange(fresh);
      } catch {
        /* повторим на следующем тике */
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [mesh?.status, finding.id, finding.series_id, onChange]);

  async function build() {
    setBusy(true);
    setErr(null);
    try {
      onChange(await api.requestMesh(finding.id));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function download(fmt: "stl" | "glb") {
    setErr(null);
    try {
      const url = await api.meshUrl(finding.id, fmt);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${finding.label ?? "structure"}.${fmt}`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div style={{ marginBottom: 10 }}>
      {(!mesh || mesh.status === "failed") && (
        <button disabled={busy} onClick={build}>
          Построить 3D-модель
        </button>
      )}
      {mesh?.status === "queued" && <span className="muted">3D-модель строится…</span>}
      {mesh?.status === "failed" && <div className="error">Не построена: {mesh.reason}</div>}
      {mesh?.status === "ready" && (
        <div className="row">
          <span className="muted">
            3D-модель: {mesh.faces?.toLocaleString("ru-RU")} граней, объём {mesh.volume_ml} мл
          </span>
          <button onClick={() => download("stl")} title="Для 3D-печати">
            STL
          </button>
          <button onClick={() => download("glb")} title="Для просмотра (glTF)">
            GLB
          </button>
          <button onClick={() => setShow3d(!show3d)}>{show3d ? "Скрыть 3D" : "Показать 3D"}</button>
        </div>
      )}
      {mesh?.status === "ready" && show3d && <MeshViewer findingId={finding.id} />}
      {err && <div className="error">{err}</div>}
    </div>
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
    if ((finding.code ?? "").startsWith("CXR-")) {
      // Качественная находка ОГК: правка — это замена кода на верный из словаря.
      const code = window.prompt("Верный код находки из словаря (например, CXR-201):", finding.code ?? "");
      if (!code || code.trim() === finding.code) return;
      await act(() => api.modifyFinding(finding.id, { code: code.trim(), time_spent_seconds: elapsed() }));
      return;
    }
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
      {finding.source === "model" && <Confidence m={finding.measurements} />}
      <div style={{ marginBottom: 10 }}>
        <Measurements m={finding.measurements} qualitative={(finding.code ?? "").startsWith("CXR-")} />
      </div>
      {finding.has_heatmap && <HeatmapView finding={finding} />}
      {finding.source === "model" &&
        finding.confirmation_status === "confirmed" &&
        typeof finding.measurements.volume_ml === "number" && <MeshPanel finding={finding} onChange={onChange} />}
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
