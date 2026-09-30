// Администрирование (ТЗ, раздел 2, FR-10). Только роль admin.
//
// - Режимы: смена RESEARCH/SHADOW/ASSIST; переход RESEARCH→ASSIST в обход SHADOW
//   отклоняется backend (409) с понятной причиной.
// - Модели: реестр, регистрация кандидата (стартует в SHADOW), проверка готовности
//   (гейт), продвижение (осознанное действие с обязательным обоснованием), откат.

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type {
  ModeOut,
  ModelOut,
  OperatingMode,
  PromotionGateResult,
  CalibrationProposal,
  SegmentationShadowReport,
  SegShadowSummary,
  ShadowReport,
} from "../api/types";

const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);

function CalibrationView({ model, onChanged }: { model: ModelOut; onChanged: () => void }) {
  const [p, setP] = useState<CalibrationProposal | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={() => run(async () => setP(await api.calibration(model.id)))}>Калибровка по площадке</button>
      {p && (
        <div style={{ marginTop: 6 }}>
          <div className="muted">
            Подписанных случаев для подбора: {p.calibration_cases}; отложено для проверки: {p.held_out_test_cases}.
            Порог меняется только при ≥5 позитивах и ≥5 негативах.
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Код</th>
                  <th>Позитивов / негативов</th>
                  <th>Порог сейчас</th>
                  <th>Предложен</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(p.per_code).map(([code, e]) => (
                  <tr key={code}>
                    <td>{code}</td>
                    <td>
                      {e.n_pos} / {e.n_neg}
                    </td>
                    <td>{e.current}</td>
                    <td>{e.changed ? <strong>{e.proposed}</strong> : <span className="muted">без изменений</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            className="primary"
            disabled={p.changed_codes.length === 0}
            onClick={() =>
              run(async () => {
                const m = await api.calibratedCandidate(model.id);
                setMsg(`Создан кандидат ${m.name} ${m.semver} (SHADOW)`);
                onChanged();
              })
            }
          >
            Создать откалиброванного кандидата
          </button>
        </div>
      )}
      {msg && <div className="muted">{msg}</div>}
    </div>
  );
}

function SliceTable({ title, rows }: { title: string; rows: ShadowReport["per_manufacturer"] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{title}</th>
            <th>Случаев</th>
            <th>Расхождение</th>
            <th>Пропуски</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>{v.cases}</td>
              <td>{pct(v.disagreement_rate)}</td>
              <td>{pct(v.miss_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SegRows({ title, rows }: { title: string; rows: Record<string, SegShadowSummary> }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{title}</th>
            <th>Сравнений</th>
            <th>Медианная ошибка объёма</th>
            <th>В пределах допуска</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>{v.n}</td>
              <td>{pct(v.median_rel_error)}</td>
              <td>{pct(v.within_tolerance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SegShadowView({ report }: { report: SegmentationShadowReport }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div>
        Теневых прогонов: {report.shadow_runs}; серий со сверкой с врачом: {report.compared_series}. Объём вне допуска
        ±{Math.round(report.tolerance * 100)}%: <strong>{pct(report.disagreement_rate)}</strong>
      </div>
      <SegRows title="Структура" rows={report.per_structure} />
      <SegRows title="Возраст" rows={report.per_age_group} />
    </div>
  );
}

function ShadowReportView({ report }: { report: ShadowReport }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div>
        Теневых прогонов: {report.shadow_runs}, с подписанным заключением: {report.reviewed_cases}. Расхождение
        (черновик, не включённый врачом): <strong>{pct(report.disagreement_rate)}</strong>, пропуски:{" "}
        <strong>{pct(report.miss_rate)}</strong>
      </div>
      <SliceTable title="Возраст" rows={report.per_age_group} />
      <SliceTable title="Аппарат" rows={report.per_manufacturer} />
    </div>
  );
}

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

function FrozenUpload({ modelId, onDone }: { modelId: string; onDone: () => void }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function send() {
    setErr(null);
    try {
      await api.frozenEvaluation(modelId, JSON.parse(text));
      setOpen(false);
      setText("");
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : e instanceof SyntaxError ? "Это не JSON" : String(e));
    }
  }
  if (!open) return <button onClick={() => setOpen(true)}>Загрузить результат замороженного теста</button>;
  return (
    <div style={{ marginTop: 6 }}>
      <div className="muted" style={{ fontSize: 12 }}>
        Вставьте JSON, который выдал <code>cli evaluate</code> на обучающем сервере (только метрики, без
        изображений). Принимается, только если посчитан на весах этой модели.
      </div>
      <textarea rows={5} style={{ width: "100%" }} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        <button className="primary" onClick={send} disabled={!text.trim()}>
          Сохранить
        </button>
        <button onClick={() => setOpen(false)}>Отмена</button>
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  );
}

function EvidenceView({ gate }: { gate: PromotionGateResult }) {
  const e = gate.evidence;
  return (
    <div style={{ marginTop: 6 }}>
      <table>
        <tbody>
          <tr>
            <td>Замороженный тест</td>
            <td>{e.frozen_test_cases} исследований</td>
          </tr>
          <tr>
            <td>Лучше действующей модели</td>
            <td>{e.frozen_test_superior ? "да" : "нет"}{e.active_model ? ` (${e.active_model})` : ""}</td>
          </tr>
          <tr>
            <td>Теневой прогон</td>
            <td>
              проверено врачом {e.shadow_reviewed_cases}; расхождений{" "}
              {e.shadow_rejection_rate === null ? "—" : `${Math.round(e.shadow_rejection_rate * 100)}%`}
            </td>
          </tr>
          <tr>
            <td>Аппараты и возрастные группы</td>
            <td>{e.no_regression_on_new_devices ? "без деградации" : "есть деградация"}</td>
          </tr>
        </tbody>
      </table>
      {e.notes.map((n, i) => (
        <div key={i} className="muted" style={{ fontSize: 12 }}>
          {n}
        </div>
      ))}
      <div className={gate.ok ? "" : "error"} style={{ marginTop: 4 }}>
        {gate.ok ? "Готов к продвижению ✓" : "Нельзя продвинуть:"}
        {!gate.ok && (
          <ul>
            {gate.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ModelRow({ model, onChanged }: { model: ModelOut; onChanged: () => void }) {
  const [gate, setGate] = useState<PromotionGateResult | null>(null);
  const [shadow, setShadow] = useState<ShadowReport | SegmentationShadowReport | null>(null);
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
      <div className="muted">
        {model.task === "classification"
          ? `классификация находок: ${Object.keys(model.operating_points).length} кодов с порогами${
              model.adapter?.type === "xrv" ? ` · открытая модель ${model.adapter.weights}` : ""
            }`
          : "сегментация"}
        {" · "}весы: {model.weights_hash}
      </div>

      {model.status === "shadow" && (
        <div style={{ marginTop: 8 }}>
          <div className="muted" style={{ fontSize: 12 }}>
            Свидетельства для продвижения платформа собирает сама: замороженный тест, теневой прогон
            против подписанных заключений, срезы по аппаратам и возрастным группам.
          </div>
          <FrozenUpload modelId={model.id} onDone={() => setGate(null)} />
          <div className="row" style={{ marginTop: 8 }}>
            <button
              onClick={() =>
                guard(async () => {
                  const r = await api.shadowReport(model.id);
                  setShadow(r);
                })
              }
            >
              Сравнить с заключениями
            </button>
            <button onClick={() => guard(async () => setGate(await api.evaluateModel(model.id)))}>
              Проверить готовность
            </button>
            <button
              className="primary"
              onClick={() =>
                guard(async () => {
                  const justification = window.prompt("Обоснование продвижения (обязательно):") ?? "";
                  if (!justification.trim()) throw new ApiError(400, "Требуется обоснование");
                  await api.promoteModel(model.id, justification);
                  setGate(null);
                })
              }
            >
              Продвинуть в ASSIST
            </button>
          </div>
          {shadow &&
            (shadow.task === "segmentation" ? <SegShadowView report={shadow} /> : <ShadowReportView report={shadow} />)}
          {gate && <EvidenceView gate={gate} />}
        </div>
      )}

      {model.task === "classification" && model.status !== "retired" && (
        <CalibrationView model={model} onChanged={onChanged} />
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
  const [regJson, setRegJson] = useState("");

  const reload = () => api.listModels().then(setModels).catch((e) => setErr(String(e)));
  useEffect(() => {
    reload();
  }, []);

  async function register() {
    setErr(null);
    try {
      // registration.json из обучающего контура (тип, пороги, границы применимости) либо ручной ввод.
      await api.registerCandidate(regJson.trim() ? JSON.parse(regJson) : form);
      setForm({ name: "", semver: "0.1.0", weights_hash: "" });
      setRegJson("");
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
          <button onClick={register} disabled={!regJson.trim() && (!form.name || !form.weights_hash)}>
            Зарегистрировать
          </button>
        </div>
        <textarea
          placeholder="…или вставьте registration.json из обучающего контура"
          rows={4}
          style={{ width: "100%", marginTop: 8 }}
          value={regJson}
          onChange={(e) => setRegJson(e.target.value)}
        />
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
