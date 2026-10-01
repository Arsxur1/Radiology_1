// Готовность данных площадки: что присылают аппараты (возраст, область, кодировка).
// Только агрегаты; нераспознанные описания — лишь частые, цифры скрыты (сервер).

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { SiteDataReport } from "../api/types";

const share = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

function Cell({ v }: { v: number | null }) {
  const bad = v !== null && v < 0.95;
  return <td style={bad ? { color: "var(--model)", fontWeight: 600 } : undefined}>{share(v)}</td>;
}

export function SiteDataReadiness({ days }: { days: number }) {
  const [r, setR] = useState<SiteDataReport | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    api
      .siteData(days)
      .then(setR)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [days]);

  if (err) return <div className="card error">Готовность данных: {err}</div>;
  if (!r) return <div className="card muted">Готовность данных: загрузка…</div>;

  return (
    <div className="card" style={{ gridColumn: "1 / -1" }}>
      <div className="row spread">
        <strong>Готовность данных площадки</strong>
        <span className={r.ready ? "badge badge-confirmed" : "badge badge-model"}>
          {r.studies === 0 ? "нет исследований" : r.ready ? "замечаний нет" : `замечаний: ${r.issues.length}`}
        </span>
      </div>
      <p className="muted" style={{ margin: "4px 0 8px" }}>
        Что присылают аппараты за {r.days} дн. ({r.studies} исследований). Без возраста и области
        модели отказывают (SR-7); кодировка, угаданная при приёме, — признак неверной настройки аппарата.
      </p>
      {r.issues.length > 0 && (
        <ul style={{ marginTop: 0 }}>
          {r.issues.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
      {r.per_device.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Аппарат</th>
                <th>Модальность</th>
                <th>Исследований</th>
                <th>Возраст</th>
                <th>BodyPartExamined</th>
                <th>Область определена</th>
                <th>Кодировка угадана</th>
                <th>Текст на снимке</th>
              </tr>
            </thead>
            <tbody>
              {r.per_device.map((d) => (
                <tr key={d.device}>
                  <td>{d.device}</td>
                  <td>{d.modalities.join(", ")}</td>
                  <td>{d.studies}</td>
                  <Cell v={d.age_share} />
                  <Cell v={d.body_part_share} />
                  <Cell v={d.region_share} />
                  <td>{d.charset_guessed || "—"}</td>
                  <td>{d.burned_in_risk || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ marginTop: 10 }}>
        <strong style={{ fontSize: 14 }}>Нераспознанные описания</strong>
        {r.unrecognized_descriptions.length === 0 ? (
          <p className="muted">Нет (с частотой от {r.min_description_count}).</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Протокол / описание</th>
                  <th>Исследований</th>
                </tr>
              </thead>
              <tbody>
                {r.unrecognized_descriptions.map((u) => (
                  <tr key={u.text}>
                    <td>{u.text}</td>
                    <td>{u.studies}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          Показаны строки, встречающиеся не реже {r.min_description_count} раз, цифры заменены на «#»
          (в описание иногда вписывают ФИО или номер). Редких строк скрыто: {r.rare_unrecognized_studies}.
          Конечности и прочее законно не распознаются — для них моделей нет. Этот список можно
          передавать разработчикам.
        </div>
      </div>
    </div>
  );
}
