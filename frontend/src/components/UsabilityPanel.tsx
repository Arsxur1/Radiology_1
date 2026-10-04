// Юзабилити (IEC 62366): объективные данные для проверки допущений файла рисков в пилоте.
// Только агрегаты по всем врачам — оценивается изделие, а не работа сотрудников.

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { UsabilityReport } from "../api/types";

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
const sec = (v: number | null) => (v === null ? "—" : `${v} с`);

export function UsabilityPanel({ days }: { days: number }) {
  const [u, setU] = useState<UsabilityReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setErr(null);
    api
      .usability(days)
      .then(setU)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [days]);

  if (err) return <div className="card error">Юзабилити: {err}</div>;
  if (!u) return <div className="card muted">Юзабилити: загрузка…</div>;
  const r = u.independent_reading;
  const fastBad = u.fast_confirm.share !== null && u.fast_confirm.share > u.fast_confirm.max_share;
  return (
    <div className="card" style={{ gridColumn: "1 / -1" }}>
      <strong>Юзабилити: как врачи работают с черновиками ИИ</strong>
      <p className="muted" style={{ margin: "4px 0 8px" }}>
        За {u.days} дн. Проверка допущений файла рисков: врач проверяет каждый черновик (R-01) и не
        принимает отсутствие черновика за норму (R-03). Только сводные цифры по всем врачам.
      </p>
      <div className="table-scroll">
        <table>
          <tbody>
            <tr>
              <td>Решений по черновикам ИИ</td>
              <td>
                {u.ai_decisions.total} (подтверждено {u.ai_decisions.accepted}, исправлено{" "}
                {u.ai_decisions.modified}, отклонено {u.ai_decisions.rejected})
              </td>
            </tr>
            <tr>
              <td>Время решения, медиана (10–90%)</td>
              <td>
                подтверждение {sec(u.decision_seconds.accepted.median)} ({sec(u.decision_seconds.accepted.p10)}–
                {sec(u.decision_seconds.accepted.p90)}); отклонение {sec(u.decision_seconds.rejected.median)}
              </td>
            </tr>
            <tr>
              <td>Подтверждения быстрее {u.fast_confirm.threshold_seconds} с</td>
              <td style={fastBad ? { color: "var(--model)", fontWeight: 600 } : undefined}>
                {u.fast_confirm.count} ({pct(u.fast_confirm.share)}; ориентир — не больше{" "}
                {pct(u.fast_confirm.max_share)})
              </td>
            </tr>
            <tr>
              <td>Свои находки врача в подписанных исследованиях</td>
              <td>
                без черновиков ИИ: {pct(r.own_findings_share_without_drafts)} из {r.signed_without_ai_drafts}; с
                черновиками: {pct(r.own_findings_share_with_drafts)} из {r.signed_with_ai_drafts}
              </td>
            </tr>
            <tr>
              <td>От приёма до подписи, медиана</td>
              <td>
                {u.turnaround_hours.median === null ? "—" : `${u.turnaround_hours.median} ч`} (подписано{" "}
                {u.turnaround_hours.n})
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {u.notes.length > 0 && (
        <ul style={{ marginBottom: 0 }}>
          {u.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        Время — от появления карточки находки на экране до решения. Цифры дополняют наблюдение и
        опрос врачей (план — docs/YUZABILITI.md) и не заменяют их.
      </div>
    </div>
  );
}
