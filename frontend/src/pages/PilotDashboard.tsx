// Сводная панель пилота NCMC: видимый прогресс без данных пациентов (только агрегаты).

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { PilotDashboard as Dashboard } from "../api/types";
import { WeeklyColumns } from "../components/charts/WeeklyColumns";

const pct = (v: number | null) =>
  v === null ? "—" : `${(v * 100).toFixed(1)}%`;

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="card" style={{ flex: "1 1 150px", margin: 0 }}>
      <div className="muted">{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700 }}>{value}</div>
      {hint && (
        <div className="muted" style={{ fontSize: 12 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

function KeyValueTable({
  rows,
  head,
}: {
  rows: [string, string | number][];
  head: [string, string];
}) {
  if (rows.length === 0) return <p className="muted">Нет данных.</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{head[0]}</th>
            <th>{head[1]}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PilotDashboard() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [weeks, setWeeks] = useState(12);
  const [err, setErr] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    setErr(null);
    api
      .pilotDashboard(weeks)
      .then(setD)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [weeks]);

  if (err) return <div className="layout error">Ошибка: {err}</div>;
  if (!d) return <div className="layout">Загрузка…</div>;
  const t = d.totals;
  const charts: [keyof Dashboard["weekly"], string][] = [
    ["studies", "Принято исследований"],
    ["physician_decisions", "Решений врачей по находкам"],
    ["reports_finalized", "Подписано заключений"],
    ["ai_refusals", "Отказов ИИ (вне границ применимости)"],
  ];

  return (
    <div className="layout">
      <div className="row spread">
        <h2>Пилот: сводка</h2>
        <label className="muted">
          период:{" "}
          <select
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
          >
            {[4, 12, 26, 52].map((w) => (
              <option key={w} value={w}>
                {w} нед.
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted">
        Только агрегаты, без данных пациентов. Обновлено{" "}
        {new Date(d.generated_at).toLocaleString()}.
      </p>

      <div className="row" style={{ flexWrap: "wrap", marginBottom: 12 }}>
        <Tile
          label="Исследований"
          value={t.studies}
          hint={`дети ${t.pediatric_studies} · взрослые ${t.adult_studies}`}
        />
        <Tile
          label="Без возраста в DICOM"
          value={t.studies_without_age}
          hint="не проходят гейт и не идут в обучение"
        />
        <Tile label="Подписано заключений" value={t.reports_finalized} />
        <Tile
          label="Решений врачей"
          value={t.physician_decisions}
          hint={`+ ${t.physician_added_findings} находок добавлено врачами`}
        />
        <Tile
          label="Принято черновиков ИИ"
          value={pct(d.ai_drafts.acceptance_rate)}
          hint={`ожидают решения: ${d.ai_drafts.pending}`}
        />
      </div>

      <div className="card">
        <div className="row spread">
          <strong>По неделям</strong>
          <button onClick={() => setShowTable(!showTable)}>
            {showTable ? "Графики" : "Таблица"}
          </button>
        </div>
        {showTable ? (
          <div className="table-scroll">
            <table style={{ marginTop: 8 }}>
              <thead>
                <tr>
                  <th>Неделя с</th>
                  {charts.map(([, label]) => (
                    <th key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.weeks.map((w, i) => (
                  <tr key={w}>
                    <td>{w}</td>
                    {charts.map(([key]) => (
                      <td key={key}>{d.weekly[key][i]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(min(260px, 100%), 1fr))",
              gap: 16,
              marginTop: 8,
            }}
          >
            {charts.map(([key, label]) => (
              <WeeklyColumns
                key={key}
                title={label}
                weeks={d.weeks}
                values={d.weekly[key]}
              />
            ))}
          </div>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(300px, 100%), 1fr))",
          gap: 12,
        }}
      >
        <div className="card" style={{ gridColumn: "1 / -1" }}>
          <strong>Теневой прогон кандидатов</strong>
          {d.shadow_models.length === 0 ? (
            <p className="muted">Кандидатов в SHADOW нет.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Модель</th>
                    <th>Проверено</th>
                    <th>Расхождение</th>
                    <th>Пропуски</th>
                  </tr>
                </thead>
                <tbody>
                  {d.shadow_models.map((m) => (
                    <tr key={m.model_version_id}>
                      <td>{m.model}</td>
                      <td>
                        {m.reviewed_cases} / {m.shadow_runs}
                      </td>
                      <td>{pct(m.disagreement_rate)}</td>
                      <td>{pct(m.miss_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            «Проверено» — исследования с подписанным заключением из всех теневых
            прогонов.
          </div>
        </div>

        <div className="card">
          <strong>Обучающие данные площадки</strong>
          <div className="muted" style={{ margin: "4px 0 8px" }}>
            {d.training_data.records} серий с метками (подписано:{" "}
            {d.training_data.finalized}); без возраста пропущено:{" "}
            {d.training_data.skipped_no_age}
          </div>
          <KeyValueTable
            head={["Находка", "Позитивов"]}
            rows={d.training_data.positives.map((p) => [
              `${p.label} (${p.code})`,
              p.count,
            ])}
          />
        </div>

        <div className="card">
          <strong>Причины отказов ИИ</strong>
          <KeyValueTable
            head={["Причина", "Отказов"]}
            rows={Object.entries(d.refusal_reasons)}
          />
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            Много отказов по возрасту в детском центре — ожидаемо для взрослых
            моделей (SR-7).
          </div>
        </div>
      </div>
    </div>
  );
}
