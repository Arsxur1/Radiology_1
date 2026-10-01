// Карточка находки — сердце разделения «система посчитала / врач подтвердил»
// (ТЗ, раздел 11; SR-2, SR-6, FR-9).
//
// - Находка модели ЯВНО маркируется как черновик ИИ и требует активного действия.
// - Никакого «принять всё»: каждое решение — по одной находке.
// - Затраченное время фиксируется от момента появления карточки (обучающий сигнал).

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { FindingOut, RejectReason, VocabularyConcept } from "../api/types";
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

// Закрытый список причин — один запрос на страницу, общий для всех карточек.
let reasonsPromise: Promise<RejectReason[]> | null = null;
function loadReasons(): Promise<RejectReason[]> {
  reasonsPromise ??= api.rejectReasons().catch((e) => {
    reasonsPromise = null;
    throw e;
  });
  return reasonsPromise;
}

// Необязательный второй шаг после отклонения: почему (обучающий сигнал, SR-6).
function RejectReasonPicker({ finding, onChange }: { finding: FindingOut; onChange: (f: FindingOut) => void }) {
  const [reasons, setReasons] = useState<RejectReason[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    loadReasons().then(setReasons).catch((e) => setErr(String(e)));
  }, []);
  async function pick(code: string) {
    setBusy(true);
    setErr(null);
    try {
      onChange(await api.setRejectReason(finding.id, code));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const chosen = reasons.find((r) => r.code === finding.reject_reason);
  return (
    <div style={{ marginTop: 6 }}>
      <div className="muted" style={{ fontSize: 13, marginBottom: 4 }}>
        {chosen ? (
          <>
            Причина: <strong>{chosen.label}</strong> (можно изменить)
          </>
        ) : (
          "Почему? (необязательно — помогает улучшить модель)"
        )}
      </div>
      <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
        {reasons.map((r) => (
          <button
            key={r.code}
            disabled={busy || r.code === finding.reject_reason}
            onClick={() => pick(r.code)}
            style={{ fontSize: 12, padding: "3px 8px" }}
            aria-pressed={r.code === finding.reject_reason}
          >
            {r.label}
          </button>
        ))}
      </div>
      {err && <div className="error">Ошибка: {err}</div>}
    </div>
  );
}

// «Изменить» на месте (FR-9): код — выбором из словаря (опечатка в коде = неверная метка
// обучения), объём — числом. Раньше было окно window.prompt с вводом кода по памяти.
function ModifyEditor({
  finding,
  modality,
  busy,
  onSave,
  onCancel,
}: {
  finding: FindingOut;
  modality?: string;
  busy: boolean;
  onSave: (payload: { code?: string; measurements?: Record<string, unknown> }) => void;
  onCancel: () => void;
}) {
  const qualitative = (finding.code ?? "").startsWith("CXR-");
  const [concepts, setConcepts] = useState<VocabularyConcept[]>([]);
  const [code, setCode] = useState("");
  const current = finding.measurements.volume_ml;
  const [volume, setVolume] = useState(typeof current === "number" ? String(current) : "");
  useEffect(() => {
    if (qualitative) api.chestVocabulary(modality ?? "").then(setConcepts).catch(() => setConcepts([]));
  }, [qualitative, modality]);
  const groups = new Map<string, VocabularyConcept[]>();
  for (const c of concepts) if (c.code !== finding.code) groups.set(c.group, [...(groups.get(c.group) ?? []), c]);
  const vol = Number(volume.replace(",", "."));
  const volOk = volume.trim() !== "" && Number.isFinite(vol) && vol > 0;
  return (
    <div className="card" style={{ margin: "8px 0", padding: 10 }}>
      {qualitative ? (
        <label>
          Верная находка вместо «{finding.label ?? finding.code}»:{" "}
          <select value={code} onChange={(e) => setCode(e.target.value)} disabled={busy} autoFocus>
            <option value="">— выберите из словаря —</option>
            {[...groups.entries()].map(([g, items]) => (
              <optgroup key={g} label={g}>
                {items.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label_ru} ({c.code})
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      ) : (
        <label>
          Объём, мл:{" "}
          <input
            type="number"
            min="0"
            step="0.1"
            inputMode="decimal"
            value={volume}
            onChange={(e) => setVolume(e.target.value)}
            disabled={busy}
            autoFocus
            style={{ width: 110 }}
          />
        </label>
      )}
      <div className="row" style={{ marginTop: 8, gap: 6 }}>
        <button
          className="primary"
          disabled={busy || (qualitative ? !code : !volOk)}
          onClick={() => onSave(qualitative ? { code } : { measurements: { volume_ml: vol } })}
        >
          Сохранить исправление
        </button>
        <button disabled={busy} onClick={onCancel}>
          Отмена
        </button>
      </div>
    </div>
  );
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

export function FindingCard({
  finding,
  onChange,
  modality,
}: {
  finding: FindingOut;
  onChange: (f: FindingOut) => void;
  modality?: string;
}) {
  // Момент, когда карточка стала видна врачу — для расчёта затраченного времени.
  const shownAt = useRef<number>(Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const elapsed = () => (Date.now() - shownAt.current) / 1000;
  const decided = finding.confirmation_status !== "pending";

  async function act(fn: () => Promise<FindingOut>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function onModify(payload: { code?: string; measurements?: Record<string, unknown> }) {
    // При ошибке редактор остаётся открытым — врач видит причину и может исправить.
    if (await act(() => api.modifyFinding(finding.id, { ...payload, time_spent_seconds: elapsed() })))
      setEditing(false);
  }

  // Одно действие (SR-6): без диалога; причина — по желанию, кнопками на карточке.
  async function onReject() {
    await act(() => api.rejectFinding(finding.id, elapsed()));
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
          <button disabled={busy || editing} onClick={() => setEditing(true)}>
            Изменить
          </button>
          <button className="danger" disabled={busy} onClick={onReject}>
            Отклонить
          </button>
        </div>
      )}
      {!decided && editing && (
        <ModifyEditor
          finding={finding}
          modality={modality}
          busy={busy}
          onSave={onModify}
          onCancel={() => setEditing(false)}
        />
      )}
      {finding.source === "model" && finding.confirmation_status === "rejected" && (
        <RejectReasonPicker finding={finding} onChange={onChange} />
      )}
      {error && <div className="error">Ошибка: {error}</div>}
    </div>
  );
}
