// Сообщить об инциденте (ТЗ, раздел 9 п. 7): что случилось, насколько серьёзно, по какому
// исследованию и находке ИИ. Привязка — к обезличенным сущностям; ФИО в текст не пишется.

import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { FindingOut, IncidentKinds } from "../api/types";

const STATUS: Record<string, string> = { pending: "черновик", confirmed: "подтверждена", rejected: "отклонена" };

export function ReportIncident({ studyId, findings }: { studyId: string; findings: FindingOut[] }) {
  const [open, setOpen] = useState(false);
  const [lists, setLists] = useState<IncidentKinds | null>(null);
  const [kind, setKind] = useState("");
  const [severity, setSeverity] = useState("");
  const [findingId, setFindingId] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (open && !lists) api.incidentKinds().then(setLists).catch((e) => setErr(String(e)));
  }, [open, lists]);

  if (!open)
    return (
      <p>
        <button onClick={() => (setOpen(true), setDone(false))}>Сообщить об инциденте…</button>
        {done && <span className="muted" style={{ marginLeft: 8 }}>Сообщение принято, ответственный уведомлён в журнале.</span>}
      </p>
    );

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      await api.reportIncident({
        kind,
        severity,
        description: text,
        study_id: studyId,
        finding_id: findingId || null,
      });
      setOpen(false);
      setDone(true);
      setKind("");
      setSeverity("");
      setFindingId("");
      setText("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" style={{ borderColor: "var(--model)" }}>
      <strong>Сообщение об инциденте</strong>
      <p className="muted" style={{ margin: "4px 0 8px" }}>
        Ошибка или сбой, которые повлияли или могли повлиять на пациента или работу. Исследование
        привязывается автоматически — <b>не пишите ФИО и номер карты</b> в описании.
      </p>
      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Вид инцидента">
          <option value="">— вид —</option>
          {lists?.kinds.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Тяжесть">
          <option value="">— тяжесть —</option>
          {lists?.severities.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <select value={findingId} onChange={(e) => setFindingId(e.target.value)} aria-label="Находка">
          <option value="">находка не выбрана</option>
          {findings.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label ?? f.code ?? "находка"} ({f.source === "model" ? "ИИ" : "врач"}, {STATUS[f.confirmation_status] ?? f.confirmation_status})
            </option>
          ))}
        </select>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        style={{ width: "100%", marginTop: 8 }}
        placeholder="Что произошло и что было сделано (не короче 10 символов)"
        aria-label="Описание инцидента"
      />
      <div className="row" style={{ marginTop: 8 }}>
        <button
          className="primary"
          disabled={busy || !kind || !severity || text.trim().length < 10}
          onClick={submit}
        >
          Отправить
        </button>
        <button onClick={() => setOpen(false)}>Отмена</button>
        {err && <span className="error">{err}</span>}
      </div>
    </section>
  );
}
