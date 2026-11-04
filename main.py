"""
Backend chico para los Planes de Accion SMART de NPS (Hiper Sur, octubre 2026).

Guarda en SQLite el plan que cada tienda completa desde el reporte estatico
(nps_hiper_sur/octubre_report.html) y expone una vista /admin para que Carlos
los revise desde su navegador, sin depender de localStorage por tienda.

Endpoints:
  GET  /health                  -> chequeo simple
  GET  /api/plan/{store_code}   -> trae el plan guardado de una tienda (o vacio)
  PUT  /api/plan/{store_code}   -> guarda/actualiza el plan de una tienda
  GET  /admin?key=ADMIN_KEY     -> vista HTML de solo lectura con los 2 planes

Solo se aceptan los store_code definidos en ALLOWED_STORES (evita que cualquiera
mande datos de tiendas que no corresponden a este plan de accion puntual).
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("PLAN_ACCION_DB_PATH", Path(__file__).parent / "plan_accion.db"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "dev-local-key-cambiar-en-render")

ALLOWED_STORES = {
    "0120": "Temuco",
    "0670": "Puerto Montt (Cardonal)",
}

app = FastAPI(title="NPS Plan de Accion - Hiper Sur")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # datos de bajo riesgo (texto operativo, sin PII); sin cookies/credenciales
    allow_methods=["GET", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planes (
                store_code TEXT PRIMARY KEY,
                store_name TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


init_db()


class PlanPayload(BaseModel):
    data: dict


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/plan/{store_code}")
def get_plan(store_code: str):
    if store_code not in ALLOWED_STORES:
        raise HTTPException(status_code=404, detail="Tienda no habilitada para este plan de accion")
    with get_db() as conn:
        row = conn.execute(
            "SELECT store_code, store_name, data, updated_at FROM planes WHERE store_code = ?",
            (store_code,),
        ).fetchone()
    if row is None:
        return {
            "store_code": store_code,
            "store_name": ALLOWED_STORES[store_code],
            "data": {},
            "updated_at": None,
            "found": False,
        }
    return {
        "store_code": row["store_code"],
        "store_name": row["store_name"],
        "data": json.loads(row["data"]),
        "updated_at": row["updated_at"],
        "found": True,
    }


@app.put("/api/plan/{store_code}")
def save_plan(store_code: str, payload: PlanPayload):
    if store_code not in ALLOWED_STORES:
        raise HTTPException(status_code=404, detail="Tienda no habilitada para este plan de accion")
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO planes (store_code, store_name, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(store_code) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (store_code, ALLOWED_STORES[store_code], json.dumps(payload.data), now),
        )
    return {"store_code": store_code, "updated_at": now, "saved": True}


def _escape(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_ficha_admin(store_code: str, store_name: str, row) -> str:
    if row is None:
        return f"""
        <div class="bg-white rounded-xl shadow p-6 mb-6">
          <h3 class="text-lg font-bold text-slate-700">{_escape(store_code)} {_escape(store_name)}</h3>
          <p class="text-sm text-slate-400 mt-2">Todavia no cargo ningun plan de accion.</p>
        </div>
        """
    data = json.loads(row["data"])
    acciones_html = ""
    i = 1
    while f"accion{i}" in data or f"resp{i}" in data or f"fecha{i}" in data:
        accion = data.get(f"accion{i}", "")
        resp = data.get(f"resp{i}", "")
        fecha = data.get(f"fecha{i}", "")
        if accion or resp or fecha:
            acciones_html += (
                f"<tr><td class='p-2 font-bold align-top'>{i}</td>"
                f"<td class='p-2'>{_escape(accion)}</td>"
                f"<td class='p-2'>{_escape(resp)}</td>"
                f"<td class='p-2'>{_escape(fecha)}</td></tr>"
            )
        i += 1
    if not acciones_html:
        acciones_html = "<tr><td colspan='4' class='p-2 text-slate-400'>Sin acciones cargadas.</td></tr>"

    alcanzado_map = {"si": "Si", "no": "No", "": "Pendiente"}
    alcanzado = alcanzado_map.get(data.get("alcanzado", ""), "Pendiente")

    return f"""
    <div class="bg-white rounded-xl shadow-lg overflow-hidden mb-6">
      <div class="bg-blue-800 text-white px-6 py-4 flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-lg font-bold">Plan de Accion SMART: NPS (Meta 60) - {_escape(store_code)} {_escape(store_name)}</h3>
        <span class="bg-emerald-400 text-blue-900 text-xs font-bold px-3 py-1 rounded-full">
          Guardado {_escape(row["updated_at"])}
        </span>
      </div>
      <div class="grid md:grid-cols-2 gap-4 p-6">
        <div class="border-2 border-blue-700 rounded-lg p-4">
          <h4 class="font-bold text-blue-800 mb-2 underline">1. Contexto</h4>
          <p class="text-sm"><strong>Fecha:</strong> {_escape(data.get("fecha"))}</p>
          <p class="text-sm"><strong>Responsable:</strong> {_escape(data.get("responsable"))}</p>
        </div>
        <div class="border-2 border-blue-700 rounded-lg p-4">
          <h4 class="font-bold text-blue-800 mb-2 underline">2. Foco del problema</h4>
          <p class="text-sm"><strong>Area/Categoria:</strong> {_escape(data.get("area"))}</p>
          <p class="text-sm mt-2 whitespace-pre-wrap">{_escape(data.get("diagnostico"))}</p>
        </div>
        <div class="md:col-span-2 border-2 border-blue-700 rounded-lg p-4">
          <h4 class="font-bold text-blue-800 mb-2 underline">3. Plan de Accion</h4>
          <table class="w-full text-sm">
            <thead><tr class="bg-blue-800 text-white text-left">
              <th class="p-2 w-8">#</th><th class="p-2">Accion</th>
              <th class="p-2 w-40">Responsable</th><th class="p-2 w-32">Fecha Limite</th>
            </tr></thead>
            <tbody>{acciones_html}</tbody>
          </table>
        </div>
        <div class="md:col-span-2 border-2 border-blue-700 rounded-lg p-4">
          <h4 class="font-bold text-blue-800 mb-2 underline">4. Seguimiento</h4>
          <p class="text-sm"><strong>Fecha nueva medicion:</strong> {_escape(data.get("fechaMedicion"))}</p>
          <p class="text-sm"><strong>Se alcanzo el 60 de NPS:</strong> {_escape(alcanzado)}</p>
          <p class="text-sm mt-2"><strong>Comentarios de cierre:</strong> {_escape(data.get("comentarios"))}</p>
        </div>
      </div>
    </div>
    """


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, key: str = ""):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clave invalida")
    with get_db() as conn:
        rows = {
            r["store_code"]: r
            for r in conn.execute("SELECT * FROM planes").fetchall()
        }
    fichas = "".join(
        _render_ficha_admin(code, name, rows.get(code))
        for code, name in ALLOWED_STORES.items()
    )
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <title>Admin - Planes de Accion NPS Hiper Sur</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-100 text-slate-800">
      <header class="bg-blue-900 text-white py-6 px-4">
        <div class="max-w-4xl mx-auto">
          <h1 class="text-2xl font-bold">Planes de Accion - NPS Hiper Sur (vista admin)</h1>
          <p class="text-blue-200 text-sm mt-1">Datos cargados directamente por las tiendas. Refresca la pagina para ver lo ultimo.</p>
        </div>
      </header>
      <main class="max-w-4xl mx-auto px-4 py-8">
        {fichas}
      </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
