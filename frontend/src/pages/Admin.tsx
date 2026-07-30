// Администрирование (ТЗ, раздел 2, FR-10). Только роль admin.
//
// - Режимы: смена RESEARCH/SHADOW/ASSIST; переход RESEARCH→ASSIST в обход SHADOW
//   отклоняется backend (409) с понятной причиной.
// - Модели: реестр, регистрация кандидата (стартует в SHADOW), проверка готовности
//   (гейт), продвижение (осознанное действие с обязательным обоснованием), откат.

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { ModeOut, ModelOut, OperatingMode, PromotionEvidence, PromotionGateResult } from "../api/types";

const MODES: OperatingMode[] = ["RESEARCH", "SHADOW", "ASSIST"];

function ModesSection() {
  const [modes, setModes] = useState<ModeOut[]>([]);
  const [modality, setModality] = useState("*");
  const [target, setTarget] = useState<OperatingMode>("SHADOW");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reload = () => api.listModes().then(setModes).catch(() => setModes([]));
  useEffect(() => {
    reload();
  }, []);

  async function apply() {
    setMsg(null);
    setErr(null);
    try {
      const r = await api.changeMode(modality, target);
      setMsg(`Режим ${r.modality} → ${r.mode}`);
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <section className="card">
      <h3>Режимы работы</h3>
      <table>
        <thead>
          <tr>
            <th>Область (модальность)</th>
            <th>Режим</th>
          </tr>
        </thead>
        <tbody>
          {modes.length === 0 && (
            <tr>
              <td colSpan={2} className="muted">
                Правил нет — действует значение по умолчанию (RESEARCH).
              </td>
            </tr>
          )}
          {modes.map((m) => (
            <tr key={m.modality}>
              <td>{m.modality}</td>
              <td>{m.mode}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 10 }}>
        <input value={modality} onChange={(e) => setModality(e.target.value)} placeholder="* или CT/MR" />
        <select value={target} onChange={(e) => setTarget(e.target.value as OperatingMode)}>
          {MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <button className="primary" onClick={apply}>
          Сменить режим
        </button>
      </div>
      <div className="muted" style={{ marginTop: 6 }}>
        Новая модель/клиника обязана пройти SHADOW перед ASSIST (раздел 9).
      </div>
      {msg && <div style={{ color: "#9be0b4" }}>{msg}</div>}
      {err && <div className="error">Ошибка: {err}</div>}
    </section>
  );
}

const EMPTY_EVIDENCE: PromotionEvidence = {
  frozen_test_cases: 0,
  frozen_test_superior: false,
  shadow_rejection_rate: null,
  no_regression_on_new_devices: false,
};

function ModelRow({ model, onChanged }: { model: ModelOut; onChanged: () => void }) {
  const [ev, setEv] = useState<PromotionEvidence>(EMPTY_EVIDENCE);
  const [gate, setGate] = useState<PromotionGateResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function guard<T>(fn: () => Promise<T>) {
    setErr(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <div className="row spread">
        <strong>
          {model.name} {model.semver}
        </strong>
        <span className={`badge badge-${model.status === "active" ? "confirmed" : model.status === "shadow" ? "model" : "rejected"}`}>
          {model.status}
        </span>
      </div>
      <div className="muted">весы: {model.weights_hash}</div>

      {model.status === "shadow" && (
        <div style={{ marginTop: 8 }}>
          <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
            <label>
              Замороженный тест:{" "}
              <input
                type="number"
                style={{ width: 90 }}
                value={ev.frozen_test_cases}
                onChange={(e) => setEv({ ...ev, frozen_test_cases: Number(e.target.value) })}
              />
            </label>
            <label>
              Доля отклонений:{" "}
              <input
                type="number"
                step="0.01"
                style={{ width: 90 }}
                value={ev.shadow_rejection_rate ?? ""}
                onChange={(e) =>
                  setEv({ ...ev, shadow_rejection_rate: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={ev.frozen_test_superior}
                onChange={(e) => setEv({ ...ev, frozen_test_superior: e.target.checked })}
              />{" "}
              превзошёл на тесте
            </label>
            <label>
              <input
                type="checkbox"
                checked={ev.no_regression_on_new_devices}
                onChange={(e) => setEv({ ...ev, no_regression_on_new_devices: e.target.checked })}
              />{" "}
              без деградации на новых аппаратах
            </label>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => guard(async () => setGate(await api.evaluateModel(model.id, ev)))}>
              Проверить готовность
            </button>
            <button
              className="primary"
              onClick={() =>
                guard(async () => {
                  const justification = window.prompt("Обоснование продвижения (обязательно):") ?? "";
                  if (!justification.trim()) throw new ApiError(400, "Требуется обоснование");
                  await api.promoteModel(model.id, ev, justification);
                  setGate(null);
                })
              }
            >
              Продвинуть в ASSIST
            </button>
          </div>
          {gate && (
            <div style={{ marginTop: 6 }} className={gate.ok ? "" : "error"}>
              {gate.ok ? "Готов к продвижению ✓" : "Нельзя продвинуть:"}
              {!gate.ok && (
                <ul>
                  {gate.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {(model.status === "active" || model.status === "retired") && (
        <div style={{ marginTop: 8 }}>
          <button
            className="danger"
            onClick={() =>
              guard(async () => {
                const reason = window.prompt("Причина отката:") ?? "";
                await api.rollbackModel(model.id, reason);
              })
            }
          >
            {model.status === "active" ? "Откатить (аварийно)" : "Сделать активной (откат)"}
          </button>
        </div>
      )}
      {err && <div className="error">Ошибка: {err}</div>}
    </div>
  );
}

function ModelsSection() {
  const [models, setModels] = useState<ModelOut[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", semver: "0.1.0", weights_hash: "" });

  const reload = () => api.listModels().then(setModels).catch((e) => setErr(String(e)));
  useEffect(() => {
    reload();
  }, []);

  async function register() {
    setErr(null);
    try {
      await api.registerCandidate(form);
      setForm({ name: "", semver: "0.1.0", weights_hash: "" });
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <section>
      <h3>Модели</h3>
      <div className="card">
        <strong>Зарегистрировать кандидата</strong>
        <div className="muted">Кандидат всегда стартует в SHADOW (раздел 2).</div>
        <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          <input placeholder="имя" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="semver" value={form.semver} onChange={(e) => setForm({ ...form, semver: e.target.value })} />
          <input
            placeholder="хеш весов"
            value={form.weights_hash}
            onChange={(e) => setForm({ ...form, weights_hash: e.target.value })}
          />
          <button onClick={register} disabled={!form.name || !form.weights_hash}>
            Зарегистрировать
          </button>
        </div>
      </div>
      {models.map((m) => (
        <ModelRow key={m.id} model={m} onChanged={reload} />
      ))}
      {models.length === 0 && <p className="muted">Моделей нет.</p>}
      {err && <div className="error">Ошибка: {err}</div>}
    </section>
  );
}

export function Admin() {
  return (
    <div className="layout">
      <h2>Администрирование</h2>
      <ModesSection />
      <ModelsSection />
    </div>
  );
}
