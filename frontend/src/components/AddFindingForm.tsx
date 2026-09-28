// Врач добавляет находку из словаря ОГК (FR-9). Это главный сигнал «модель пропустила»:
// без него обучение не узнает о пропусках. Одна находка за действие, время фиксируется.

import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { FindingOut, VocabularyConcept } from "../api/types";

export function AddFindingForm({
  seriesId,
  modality,
  existingCodes,
  onAdded,
}: {
  seriesId: string;
  modality: string;
  existingCodes: string[];
  onAdded: (f: FindingOut) => void;
}) {
  const [concepts, setConcepts] = useState<VocabularyConcept[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const openedAt = useRef(Date.now());

  useEffect(() => {
    api.chestVocabulary(modality).then(setConcepts).catch(() => setConcepts([]));
  }, [modality]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = new Map<string, VocabularyConcept[]>();
    for (const c of concepts) {
      if (existingCodes.includes(c.code)) continue;
      if (q && !c.label_ru.toLowerCase().includes(q) && !c.code.toLowerCase().includes(q)) continue;
      out.set(c.group, [...(out.get(c.group) ?? []), c]);
    }
    return [...out.entries()];
  }, [concepts, query, existingCodes]);

  if (concepts.length === 0) return null;
  if (!open)
    return (
      <button
        onClick={() => {
          openedAt.current = Date.now();
          setOpen(true);
        }}
      >
        + Добавить находку
      </button>
    );

  async function add() {
    setBusy(true);
    setErr(null);
    try {
      const f = await api.createFinding({
        series_id: seriesId,
        code,
        time_spent_seconds: (Date.now() - openedAt.current) / 1000,
      });
      onAdded(f);
      setCode("");
      setQuery("");
      setOpen(false);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <strong>Добавить находку из словаря</strong>
      <div className="muted" style={{ marginBottom: 8 }}>
        Отмечайте то, что видите, в том числе пропущенное моделью. Это находка, не диагноз.
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <input placeholder="поиск: выпот, узел, CXR-200…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={code} onChange={(e) => setCode(e.target.value)} style={{ maxWidth: "100%" }}>
          <option value="">— выберите находку —</option>
          {groups.map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label_ru} ({c.code})
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <button className="primary" disabled={!code || busy} onClick={add}>
          Добавить
        </button>
        <button onClick={() => setOpen(false)}>Отмена</button>
      </div>
      {err && <div className="error">Ошибка: {err}</div>}
    </div>
  );
}
