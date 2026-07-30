import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import type { OperatingMode } from "./api/types";
import { authHeaders, clearAuth, hasRole } from "./auth";
import { ModeBanner } from "./components/ModeBanner";
import { Admin } from "./pages/Admin";
import { DriftPanel } from "./pages/DriftPanel";
import { Login } from "./pages/Login";
import { ModalityRegistration } from "./pages/ModalityRegistration";
import { PatientDynamics } from "./pages/PatientDynamics";
import { Patients } from "./pages/Patients";
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
        <span className="row">
          {hasRole("admin", "radiologist") && <Link to="/patients">Пациенты</Link>}
          {hasRole("admin") && <Link to="/admin">Администрирование</Link>}
          {hasRole("admin", "auditor") && <Link to="/drift">Дрейф</Link>}
          <button
            onClick={() => {
              clearAuth();
              nav("/login");
            }}
          >
            Выйти
          </button>
        </span>
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
      <Route
        path="/patients/:patientId/dynamics"
        element={
          <RequireAuth>
            <PatientDynamics />
          </RequireAuth>
        }
      />
      <Route
        path="/patients/:patientId/registration"
        element={
          <RequireAuth>
            <ModalityRegistration />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth>
            <Admin />
          </RequireAuth>
        }
      />
      <Route
        path="/drift"
        element={
          <RequireAuth>
            <DriftPanel />
          </RequireAuth>
        }
      />
      <Route
        path="/patients"
        element={
          <RequireAuth>
            <Patients />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
