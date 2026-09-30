// Отправка подписанного заключения в PACS клиники как DICOM SR (FR-8).
// SR ложится к настоящему исследованию пациента; повторная отправка заменяет документ.

import { useState } from "react";
import { ApiError, api } from "../api/client";

export function SendToPacs({ reportId }: { reportId: string }) {
  const [state, setState] = useState<"idle" | "busy" | "sent">("idle");
  const [err, setErr] = useState<string | null>(null);

  async function send() {
    setState("busy");
    setErr(null);
    try {
      await api.sendReportToPacs(reportId);
      setState("sent");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
      setState("idle");
    }
  }

  return (
    <div className="row" style={{ marginTop: 6 }}>
      <button disabled={state === "busy"} onClick={send}>
        {state === "sent" ? "Отправить повторно" : "Отправить в PACS"}
      </button>
      {state === "sent" && <span className="muted">Заключение принято PACS (DICOM SR)</span>}
      {err && <span className="error">{err}</span>}
    </div>
  );
}
