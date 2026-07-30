import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import type { OperatingMode } from "./api/types";
import { authHeaders, clearAuth } from "./auth";
import { ModeBanner } from "./components/ModeBanner";
import { Login } from "./pages/Login";
import { StudyReview } from "./pages/StudyReview";
import { Worklist } from "./pages/Worklist";

function isAuthed(): boolean {
  return Object.keys(authHeaders()).length > 0;
}

function Shell({ children }: { children: React.ReactNode }) {
  const nav = useNavigate();
  const [mode, setMode] = useState<OperatingMode>("RESEARCH");

  useEffect(() => {
    // Режим установки: берём правило '*' или первое доступное (по умолчанию RESEARCH).
    api
      .listModes()
      .then((rows) => {
        const star = rows.find((r) => r.modality === "*") ?? rows[0];
        if (star) setMode(star.mode);
      })
      .catch(() => setMode("RESEARCH"));
  }, []);

  return (
    <>
      <ModeBanner mode={mode} />
      <div className="topbar">
        <span className="brand">
          <Link to="/">medviz</Link> · рабочее место врача
        </span>
        <button
          onClick={() => {
            clearAuth();
            nav("/login");
          }}
        >
          Выйти
        </button>
      </div>
      {children}
    </>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!isAuthed()) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Worklist />
          </RequireAuth>
        }
      />
      <Route
        path="/studies/:studyId"
        element={
          <RequireAuth>
            <StudyReview />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
