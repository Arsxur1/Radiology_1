// Разбор GLB (glTF 2.0, как его пишет backend: services/mesh.py::to_glb) и отрисовка
// на WebGL без сторонних библиотек. Отдельный модуль — чтобы проверять без React.

export interface GlbMesh {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint32Array;
  min: [number, number, number];
  max: [number, number, number];
  color: [number, number, number];
}

interface Accessor {
  bufferView: number;
  byteOffset?: number;
  count: number;
  componentType: number;
  type: string;
  min?: number[];
  max?: number[];
}

export function parseGlb(buf: ArrayBuffer): GlbMesh {
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== 0x46546c67 || dv.getUint32(4, true) !== 2) throw new Error("Не GLB 2.0");
  const jsonLen = dv.getUint32(12, true);
  if (dv.getUint32(16, true) !== 0x4e4f534a) throw new Error("GLB: нет JSON-блока");
  const doc = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jsonLen)));
  const binStart = 20 + jsonLen + 8;
  if (dv.getUint32(20 + jsonLen + 4, true) !== 0x004e4942) throw new Error("GLB: нет BIN-блока");

  const prim = doc.meshes[0].primitives[0];
  const view = (i: number) => {
    const a: Accessor = doc.accessors[i];
    const bv = doc.bufferViews[a.bufferView];
    const offset = binStart + (bv.byteOffset ?? 0) + (a.byteOffset ?? 0);
    return { a, offset };
  };
  const vec3 = (i: number) => {
    const { a, offset } = view(i);
    if (a.componentType !== 5126 || a.type !== "VEC3") throw new Error("GLB: ожидались float32 VEC3");
    return { data: new Float32Array(buf.slice(offset, offset + a.count * 12)), a };
  };
  const pos = vec3(prim.attributes.POSITION);
  const nrm = vec3(prim.attributes.NORMAL);
  const { a: ia, offset: io } = view(prim.indices);
  let indices: Uint32Array;
  if (ia.componentType === 5125) indices = new Uint32Array(buf.slice(io, io + ia.count * 4));
  else if (ia.componentType === 5123) indices = Uint32Array.from(new Uint16Array(buf.slice(io, io + ia.count * 2)));
  else throw new Error("GLB: неподдерживаемый тип индексов");
  const mat = doc.materials?.[prim.material ?? 0]?.pbrMetallicRoughness?.baseColorFactor ?? [0.85, 0.55, 0.5, 1];
  return {
    positions: pos.data,
    normals: nrm.data,
    indices,
    min: (pos.a.min ?? [-1, -1, -1]) as [number, number, number],
    max: (pos.a.max ?? [1, 1, 1]) as [number, number, number],
    color: [mat[0], mat[1], mat[2]],
  };
}

// ── Матрицы 4×4 (столбцами, как ожидает WebGL) ─────────────────────────────────
type M4 = Float32Array;
function mul(a: M4, b: M4): M4 {
  const o = new Float32Array(16);
  for (let c = 0; c < 4; c++)
    for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
  return o;
}
function perspective(fovy: number, aspect: number, near: number, far: number): M4 {
  const f = 1 / Math.tan(fovy / 2);
  const o = new Float32Array(16);
  o[0] = f / aspect;
  o[5] = f;
  o[10] = (far + near) / (near - far);
  o[11] = -1;
  o[14] = (2 * far * near) / (near - far);
  return o;
}
function rotX(t: number): M4 {
  const c = Math.cos(t), s = Math.sin(t);
  return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]);
}
function rotY(t: number): M4 {
  const c = Math.cos(t), s = Math.sin(t);
  return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
}
function translate(x: number, y: number, z: number): M4 {
  return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
}
function scale(k: number): M4 {
  return new Float32Array([k, 0, 0, 0, 0, k, 0, 0, 0, 0, k, 0, 0, 0, 0, 1]);
}

const VS = `
attribute vec3 aPos; attribute vec3 aNrm;
uniform mat4 uMvp; uniform mat4 uRot;
varying vec3 vN;
void main() { vN = (uRot * vec4(aNrm, 0.0)).xyz; gl_Position = uMvp * vec4(aPos, 1.0); }`;
const FS = `
precision mediump float;
varying vec3 vN; uniform vec3 uColor;
void main() {
  vec3 n = normalize(vN);
  float d = abs(dot(n, normalize(vec3(0.4, 0.6, 1.0))));   // двусторонний свет
  gl_FragColor = vec4(uColor * (0.25 + 0.75 * d), 1.0);
}`;

export interface MeshView {
  draw(yaw: number, pitch: number, zoom: number): void;
  dispose(): void;
}

export function createMeshView(canvas: HTMLCanvasElement, mesh: GlbMesh): MeshView {
  const gl = (canvas.getContext("webgl2") ?? canvas.getContext("webgl")) as WebGLRenderingContext | null;
  if (!gl) throw new Error("Браузер не поддерживает WebGL");
  const isGl2 = typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext;
  if (!isGl2 && !gl.getExtension("OES_element_index_uint")) throw new Error("WebGL: нет 32-битных индексов");

  const sh = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader");
    return s;
  };
  const prog = gl.createProgram()!;
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  gl.useProgram(prog);

  const buffers: WebGLBuffer[] = [];
  const attr = (name: string, data: Float32Array) => {
    const b = gl.createBuffer()!;
    buffers.push(b);
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, name);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
  };
  attr("aPos", mesh.positions);
  attr("aNrm", mesh.normals);
  const ib = gl.createBuffer()!;
  buffers.push(ib);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.indices, gl.STATIC_DRAW);

  const center = [0, 1, 2].map((i) => (mesh.min[i] + mesh.max[i]) / 2);
  const extent = Math.max(...[0, 1, 2].map((i) => mesh.max[i] - mesh.min[i]), 1e-6);
  const uMvp = gl.getUniformLocation(prog, "uMvp");
  const uRot = gl.getUniformLocation(prog, "uRot");
  gl.uniform3fv(gl.getUniformLocation(prog, "uColor"), mesh.color);
  gl.enable(gl.DEPTH_TEST);

  return {
    draw(yaw, pitch, zoom) {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0.08, 0.09, 0.11, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const rot = mul(rotX(pitch), rotY(yaw));
      const model = mul(rot, mul(scale(2 / extent), translate(-center[0], -center[1], -center[2])));
      const view = translate(0, 0, -3.2 / zoom);
      const mvp = mul(perspective(Math.PI / 4, canvas.width / canvas.height, 0.1, 100), mul(view, model));
      gl.uniformMatrix4fv(uMvp, false, mvp);
      gl.uniformMatrix4fv(uRot, false, rot);
      gl.drawElements(gl.TRIANGLES, mesh.indices.length, gl.UNSIGNED_INT, 0);
    },
    dispose() {
      buffers.forEach((b) => gl.deleteBuffer(b));
      gl.deleteProgram(prog);
    },
  };
}
