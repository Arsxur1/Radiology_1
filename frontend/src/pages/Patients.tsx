// Объединение и разъединение записей пациентов (ТЗ, FR-1).
//
// Решает проблему транслитерации кириллица/латиница: один человек под разными
// написаниями ФИО/номерами. Поиск по номеру карты или ФИО (сравниваются ключевые токены) → выбор
// источника и приёмника → объединение. Разъединение — выделение новой записи
// с выбранными идентификаторами и исследованиями. Все операции пишутся в аудит.

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { hasRole } from "../auth";
import type { LinkReviewOut, PatientOut, StudyOut } from "../api/types";

// Номер карты и ФИО в обезличенном контуре не хранятся — только ключевые токены (SR-9).
// Показываем вид идентификатора и короткий отпечаток токена: по нему видно, что у двух
// записей один и тот же идентификатор, но не видно сам номер или ФИО.
const ID_TYPE: Record<string, string> = { mrn: "номер карты", name_translit: "ФИО" };

function idLabel(i: { id_type: string; normalized_value: string }): string {
  const kind = ID_TYPE[i.id_type] ?? i.id_type;
  return i.normalized_value.startsWith("h1:")
    ? `${kind} · отпечаток ${i.normalized_value.slice(3, 11)}`
    : `${kind}: ${i.normalized_value}`;
}

function IdentifierList({ p }: { p: PatientOut }) {
  return (
    <ul style={{ margin: "6px 0" }}>
      {p.identifiers.map((i) => (
        <li key={i.id} className="meas">
          {idLabel(i)}
          {i.issuer ? ` (${i.issuer})` : ""}
          {!i.active && <span className="muted"> — неактивен</span>}
        </li>
      ))}
      {p.identifiers.length === 0 && <li className="muted">нет идентификаторов</li>}
    </ul>
  );
}

// Записи, созданные при неоднозначном номере карты: присоединить к одному из кандидатов
// или подтвердить, что это другой пациент. Решает человек; ФИО сверяется через раскрытие
// личности на исследовании (с аудитом), здесь — только отпечатки и число исследований.
function LinkReviewQueue() {
  const [queue, setQueue] = useState<LinkReviewOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api
      .linkReviewQueue()
      .then(setQueue)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (queue === null && !err) return null;
  return (
    <div className="card" style={queue && queue.length ? { borderColor: "var(--model)" } : undefined}>
      <strong>Требуют сопоставления{queue ? `: ${queue.length}` : ""}</strong>
      <p className="muted" style={{ margin: "4px 0 8px" }}>
        При приёме номер карты совпал у нескольких записей — исследование не привязано молча. Пока
        запись не сопоставлена, врач видит предупреждение, а прошлые исследования ребёнка не
        попадают в сравнение. Сверьте пациента (раскрытие личности на исследовании) и выберите.
      </p>
      {err && <div className="error">{err}</div>}
      {queue?.length === 0 && <p className="muted">Нет.</p>}
      {queue?.map((q) => (
        <div key={q.patient.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
          <div className="row spread">
            <span>
              Новая запись {q.patient.id.slice(0, 8)}… · исследований: {q.patient.study_count} ·{" "}
              <Link to={`/patients/${q.patient.id}/dynamics`}>исследования</Link>
            </span>
            <button style={{ whiteSpace: "nowrap" }} onClick={() => act(() => api.keepSeparate(q.patient.id))}>
              Это другой пациент
            </button>
          </div>
          <ul style={{ margin: "6px 0" }}>
            {q.candidates.map((c) => (
              <li key={c.id} className="row" style={{ gap: 8 }}>
                <span>
                  Кандидат {c.id.slice(0, 8)}… · исследований: {c.study_count} ·{" "}
                  {c.identifiers.map(idLabel).join("; ") || "нет идентификаторов"} ·{" "}
                  <Link to={`/patients/${c.id}/dynamics`}>исследования</Link>
                </span>
                <button
                  className="primary"
                  style={{ whiteSpace: "nowrap" }}
                  onClick={() => act(() => api.mergePatients(q.patient.id, c.id))}
                >
                  Присоединить к нему
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// Отзыв согласия законного представителя на использование данных для улучшения моделей.
// Только администратор; основание — из списка (без свободного текста); всё — в аудит.
function TrainingExclusion({ patient, onDone }: { patient: PatientOut; onDone: () => void }) {
  const [bases, setBases] = useState<{ code: string; label: string }[]>([]);
  const [basis, setBasis] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.trainingExclusionBases().then(setBases).catch(() => setBases([]));
  }, []);
  const next = !patient.training_excluded;
  const options = bases.filter((b) => (next ? b.code !== "consent_restored" : b.code === "consent_restored"));
  return (
    <div className="row" style={{ flexWrap: "wrap", gap: 8, margin: "6px 0" }}>
      {patient.training_excluded ? (
        <span className="badge badge-model">исключён из обучения</span>
      ) : (
        <span className="muted">данные могут использоваться для обучения</span>
      )}
      <select value={basis} onChange={(e) => setBasis(e.target.value)} aria-label="Основание">
        <option value="">— основание —</option>
        {options.map((b) => (
          <option key={b.code} value={b.code}>
            {b.label}
          </option>
        ))}
      </select>
      <button
        disabled={!basis}
        onClick={async () => {
          setErr(null);
          try {
            await api.setTrainingExclusion(patient.id, next, basis);
            setBasis("");
            onDone();
          } catch (e) {
            setErr(e instanceof ApiError ? e.message : String(e));
          }
        }}
      >
        {next ? "Исключить из обучения" : "Вернуть в обучение"}
      </button>
      {err && <span className="error">{err}</span>}
    </div>
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
              {idLabel(i)}
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

      <LinkReviewQueue />

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
          {!p.is_merged && hasRole("admin") && <TrainingExclusion patient={p} onDone={search} />}
          {!p.is_merged && <SplitPanel patient={p} onDone={search} />}
        </div>
      ))}
    </div>
  );
}
