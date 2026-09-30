// Раскрытие личности пациента для описывающего/лечащего врача (SR-9).
// Только по действию врача и с целью; факт раскрытия пишется в журнал аудита.
// Данные живут лишь в памяти страницы — не сохраняются в браузере.

import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { IdentityOut } from "../api/types";

const PURPOSES: [string, string][] = [
  ["report", "подписание / передача заключения"],
  ["clinical", "клиническое решение по пациенту"],
  ["comparison", "сопоставление с прежними исследованиями в PACS"],
];

export function PatientIdentity({ studyId }: { studyId: string }) {
  const [purpose, setPurpose] = useState("report");
  const [identity, setIdentity] = useState<IdentityOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (identity)
    return (
      <div className="card" style={{ borderColor: "var(--model)" }}>
        <div className="row spread">
          <strong>
            {identity.patient_name ?? "имя не указано"} · карта {identity.patient_mrn ?? "—"}
          </strong>
          <button onClick={() => setIdentity(null)}>Скрыть</button>
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          Исходный UID исследования в PACS: {identity.original_study_instance_uid ?? "—"}. Цель: {identity.purpose}.
          Доступ записан в журнал аудита.
        </div>
      </div>
    );

  return (
    <div className="row" style={{ flexWrap: "wrap", marginBottom: 8 }}>
      <select value={purpose} onChange={(e) => setPurpose(e.target.value)} aria-label="Цель доступа">
        {PURPOSES.map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
      <button
        onClick={async () => {
          setErr(null);
          try {
            setIdentity(await api.revealIdentity(studyId, purpose));
          } catch (e) {
            setErr(e instanceof ApiError ? e.message : String(e));
          }
        }}
      >
        Показать данные пациента
      </button>
      {err && <span className="error">{err}</span>}
    </div>
  );
}
