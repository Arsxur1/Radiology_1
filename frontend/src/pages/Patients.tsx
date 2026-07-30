// Объединение и разъединение записей пациентов (ТЗ, FR-1).
//
// Решает проблему транслитерации кириллица/латиница: один человек под разными
// написаниями ФИО/номерами. Поиск по нормализованному идентификатору → выбор
// источника и приёмника → объединение. Разъединение — выделение новой записи
// с выбранными идентификаторами и исследованиями. Все операции пишутся в аудит.

import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { PatientOut, StudyOut } from "../api/types";

function IdentifierList({ p }: { p: PatientOut }) {
  return (
    <ul style={{ margin: "6px 0" }}>
      {p.identifiers.map((i) => (
        <li key={i.id} className="meas">
          {i.id_type}: {i.normalized_value}
          {i.issuer ? ` (${i.issuer})` : ""}
          {!i.active && <span className="muted"> — неактивен</span>}
        </li>
      ))}
      {p.identifiers.length === 0 && <li className="muted">нет идентификаторов</li>}
    </ul>
  );
}

// Разъединение конкретного пациента: выбрать идентификаторы и исследования → новая запись.
function SplitPanel({ patient, onDone }: { patient: PatientOut; onDone: () => void }) {
  const [studies, setStudies] = useState<StudyOut[] | null>(null);
  const [idIds, setIdIds] = useState<Set<string>>(new Set());
  const [studyIds, setStudyIds] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function toggleOpen() {
    setOpen(!open);
    if (!open && studies === null) {
      try {
        setStudies(await api.listStudies(undefined, patient.id));
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : String(e));
      }
    }
  }

  function toggle(set: Set<string>, id: string, setter: (s: Set<string>) => void) {
    const next = new Set(set);
    next.has(id) ? next.delete(id) : next.add(id);
    setter(next);
  }

  async function doSplit() {
    setErr(null);
    try {
      await api.splitPatient({
        source_patient_id: patient.id,
        identifier_ids: [...idIds],
        study_ids: [...studyIds],
      });
      setIdIds(new Set());
      setStudyIds(new Set());
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={toggleOpen}>{open ? "Скрыть разъединение" : "Разъединить…"}</button>
      {open && (
        <div style={{ marginTop: 8 }}>
          <div className="muted">Выберите, что выделить в новую запись:</div>
          <strong>Идентификаторы</strong>
          {patient.identifiers.map((i) => (
            <label key={i.id} style={{ display: "block" }}>
              <input
                type="checkbox"
                checked={idIds.has(i.id)}
                onChange={() => toggle(idIds, i.id, setIdIds)}
              />{" "}
              {i.id_type}: {i.normalized_value}
            </label>
          ))}
          <strong>Исследования</strong>
          {studies === null ? (
            <div className="muted">загрузка…</div>
          ) : studies.length === 0 ? (
            <div className="muted">нет</div>
          ) : (
            studies.map((s) => (
              <label key={s.id} style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={studyIds.has(s.id)}
                  onChange={() => toggle(studyIds, s.id, setStudyIds)}
                />{" "}
                {s.modality} · {s.description ?? s.study_instance_uid}
              </label>
            ))
          )}
          <button
            className="danger"
            style={{ marginTop: 8 }}
            disabled={idIds.size === 0 && studyIds.size === 0}
            onClick={doSplit}
          >
            Выделить в новую запись
          </button>
          {err && <div className="error">Ошибка: {err}</div>}
        </div>
      )}
    </div>
  );
}

export function Patients() {
  const [value, setValue] = useState("");
  const [results, setResults] = useState<PatientOut[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  async function search() {
    setErr(null);
    setMsg(null);
    try {
      setResults(await api.searchPatients(value));
      setSearched(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function merge() {
    if (!source || !target) return;
    setErr(null);
    setMsg(null);
    try {
      await api.mergePatients(source, target);
      setMsg("Записи объединены.");
      setSource(null);
      setTarget(null);
      await search();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div className="layout">
      <h2>Пациенты — объединение и разъединение</h2>
      <p className="muted">
        Поиск учитывает транслитерацию кириллица/латиница. Объедините записи одного человека или
        разъедините ошибочно слитые (FR-1). Все операции фиксируются в аудите.
      </p>

      <div className="card">
        <div className="row">
          <input
            style={{ flex: 1 }}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="ФИО или номер карты (напр. Иванов Пётр / ivanov petr)"
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
          <button className="primary" onClick={search} disabled={!value.trim()}>
            Найти
          </button>
        </div>
      </div>

      {source && target && (
        <div className="card">
          Объединить <span className="badge badge-rejected">источник</span> → {" "}
          <span className="badge badge-confirmed">приёмник</span>?
          <div style={{ marginTop: 8 }}>
            <button className="primary" onClick={merge}>
              Объединить
            </button>{" "}
            <button
              onClick={() => {
                setSource(null);
                setTarget(null);
              }}
            >
              Сбросить выбор
            </button>
          </div>
        </div>
      )}

      {msg && <div style={{ color: "#9be0b4" }}>{msg}</div>}
      {err && <div className="error">Ошибка: {err}</div>}

      {searched && results.length === 0 && <p className="muted">Ничего не найдено.</p>}

      {results.map((p) => (
        <div key={p.id} className="card">
          <div className="row spread">
            <strong>
              Пациент {p.id.slice(0, 8)}…{" "}
              {p.is_merged && <span className="badge badge-model">объединён</span>}
            </strong>
            <span className="muted">исследований: {p.study_count}</span>
          </div>
          <IdentifierList p={p} />
          <div className="row">
            <button
              disabled={p.is_merged}
              className={source === p.id ? "danger" : ""}
              onClick={() => setSource(p.id)}
            >
              {source === p.id ? "✓ источник" : "Выбрать источником"}
            </button>
            <button
              disabled={p.is_merged}
              className={target === p.id ? "primary" : ""}
              onClick={() => setTarget(p.id)}
            >
              {target === p.id ? "✓ приёмник" : "Выбрать приёмником"}
            </button>
          </div>
          {!p.is_merged && <SplitPanel patient={p} onDone={search} />}
        </div>
      ))}
    </div>
  );
}
