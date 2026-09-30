// Просмотр 3D-модели структуры в браузере (FR-5): вращение мышью/пальцем, масштаб колесом.
// Модель — из подтверждённой маски; это наглядность, не измерение.

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { createMeshView, parseGlb, type MeshView } from "./meshGl";

export function MeshViewer({ findingId }: { findingId: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<MeshView | null>(null);
  const pose = useRef({ yaw: 0.6, pitch: -0.3, zoom: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const url = await api.meshUrl(findingId, "glb");
        const buf = await (await fetch(url)).arrayBuffer();
        URL.revokeObjectURL(url);
        if (cancelled || !canvas.current) return;
        view.current = createMeshView(canvas.current, parseGlb(buf));
        view.current.draw(pose.current.yaw, pose.current.pitch, pose.current.zoom);
      } catch (e) {
        if (!cancelled) setErr(e instanceof ApiError ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      view.current?.dispose();
      view.current = null;
    };
  }, [findingId]);

  const redraw = () => view.current?.draw(pose.current.yaw, pose.current.pitch, pose.current.zoom);

  return (
    <div style={{ marginTop: 6 }}>
      <canvas
        ref={canvas}
        width={420}
        height={320}
        style={{ width: "100%", maxWidth: 420, borderRadius: 6, touchAction: "none", cursor: "grab" }}
        onPointerDown={(e) => {
          drag.current = { x: e.clientX, y: e.clientY };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          pose.current.yaw += (e.clientX - drag.current.x) * 0.01;
          pose.current.pitch = Math.max(-1.5, Math.min(1.5, pose.current.pitch + (e.clientY - drag.current.y) * 0.01));
          drag.current = { x: e.clientX, y: e.clientY };
          redraw();
        }}
        onPointerUp={() => (drag.current = null)}
        onWheel={(e) => {
          pose.current.zoom = Math.max(0.5, Math.min(4, pose.current.zoom * (e.deltaY < 0 ? 1.1 : 0.9)));
          redraw();
        }}
      />
      <div className="muted" style={{ fontSize: 12 }}>
        Вращение — перетаскиванием, масштаб — колесом. Модель построена из подтверждённой маски.
      </div>
      {err && <div className="error">3D недоступно: {err}</div>}
    </div>
  );
}
