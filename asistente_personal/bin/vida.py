#!/usr/bin/env python3
"""vida.py — the only data gateway for the Hermes personal assistant.

Design ref: openspec/changes/hermes-personal-assistant/design.md §7.

Constraints: Python 3 stdlib only (argparse, sqlite3, json, datetime, calendar,
os, sys). No ORM, no third-party dependencies. JSON-only stdout contract:

    success -> {"ok": true, "action": "<cmd.sub>", "data": {...}}   exit 0
    failure -> {"ok": false, "action": "...", "error": "...", "codigo": "..."} exit 1
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# In the container, docker-compose mounts data/schema.sql alongside vida.py at
# /opt/data/bin/schema.sql. In local/dev checkouts it lives at ../data/schema.sql
# relative to this file. Support both without requiring the mount for tests.
_SCHEMA_CANDIDATES = (
    os.path.join(SCRIPT_DIR, "schema.sql"),
    os.path.join(SCRIPT_DIR, "..", "data", "schema.sql"),
)
SCHEMA_PATH = next((p for p in _SCHEMA_CANDIDATES if os.path.exists(p)), _SCHEMA_CANDIDATES[0])
DEFAULT_DB_PATH = "/opt/data/data/vida.db"

INCREMENTO_KG = {
    "sentadilla": 5.0,
    "peso muerto": 5.0,
    "prensa": 5.0,
    "hip thrust": 5.0,
}
INCREMENTO_DEFAULT_KG = 2.5

METODOS_PAGO = ("efectivo", "debito", "credito", "yape", "plin", "transferencia")
PRIORIDADES = ("alta", "media", "baja")
ESTADOS_PENDIENTE = ("abierto", "hecho", "cancelado")
DIFICULTADES = ("facil", "media", "dificil")

# ---------------------------------------------------------------------------
# Versioned schema migrations (daily-routine-tracker design.md §3, D-0)
# ---------------------------------------------------------------------------

TARGET_SCHEMA_VERSION = 2

# Migrations are ADDITIVE ONLY (D-0.5): add tables/columns/indexes, never drop
# or rewrite. That convention is what makes "revert the code, keep the data"
# safe. Each version maps to a tuple of INDIVIDUAL statements -- no ";"
# splitting, ever.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        "ALTER TABLE pendientes ADD COLUMN dificultad TEXT "
        "CHECK (dificultad IS NULL OR dificultad IN ('facil', 'media', 'dificil'))",

        """CREATE TABLE rutina_bloques (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre         TEXT    NOT NULL UNIQUE,
            hora_objetivo  TEXT,
            orden          INTEGER NOT NULL DEFAULT 0,
            activo         INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
            creado_en      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            fuente         TEXT    NOT NULL DEFAULT 'telegram'
                                   CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron'))
        )""",

        """CREATE TABLE rutina_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            bloque_id  INTEGER NOT NULL REFERENCES rutina_bloques(id) ON DELETE RESTRICT,
            nombre     TEXT    NOT NULL,
            orden      INTEGER NOT NULL DEFAULT 0,
            activo     INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
            creado_en  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            fuente     TEXT    NOT NULL DEFAULT 'telegram'
                               CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
            UNIQUE (bloque_id, nombre)
        )""",

        """CREATE TABLE rutina_completado (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id    INTEGER NOT NULL REFERENCES rutina_items(id) ON DELETE RESTRICT,
            fecha      TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
            creado_en  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            fuente     TEXT    NOT NULL DEFAULT 'telegram'
                               CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
            UNIQUE (item_id, fecha)
        )""",

        "CREATE INDEX idx_rutina_items_bloque ON rutina_items(bloque_id, orden)",
        "CREATE INDEX idx_rutina_compl_fecha ON rutina_completado(fecha)",
        "CREATE INDEX idx_rutina_compl_item_fecha ON rutina_completado(item_id, fecha)",
    ),
}


class VidaError(Exception):
    """A user-facing, JSON-reportable error. `codigo` is a short slug."""

    def __init__(self, mensaje: str, codigo: str = "error"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# ---------------------------------------------------------------------------
# Date helpers — the only real logic, hence the only real tests (design §7/§9)
# ---------------------------------------------------------------------------

def clamp_dia(anio: int, mes: int, dia: int) -> int:
    """Clamp `dia` to the last valid day of (anio, mes).

    e.g. clamp_dia(2023, 2, 31) -> 28 (2023 is not a leap year).
    e.g. clamp_dia(2024, 2, 31) -> 29 (2024 is a leap year).
    """
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return min(dia, ultimo_dia)


def _sumar_mes(anio: int, mes: int, delta: int = 1) -> tuple[int, int]:
    """Add `delta` months to (anio, mes), returning the wrapped (anio, mes)."""
    total = (anio * 12 + (mes - 1)) + delta
    return total // 12, (total % 12) + 1


def proxima_fecha_de_dia(dia: int, desde: date | None = None) -> date:
    """Next calendar date (on/after `desde`) whose day-of-month is `dia`.

    Clamped per month length. Rolls into next month (and year, if needed)
    when the clamped day-of-month for the current month has already passed.
    """
    desde = desde or date.today()
    anio, mes = desde.year, desde.month
    candidata = date(anio, mes, clamp_dia(anio, mes, dia))
    if candidata < desde:
        anio, mes = _sumar_mes(anio, mes, 1)
        candidata = date(anio, mes, clamp_dia(anio, mes, dia))
    return candidata


def resolver_ciclo_tarjeta(dia_corte: int, dia_pago: int, desde: date | None = None) -> dict:
    """Resolve the next real cut/payment dates for a credit card cycle.

    `dia_pago` rolls into the month AFTER the cut's month whenever
    `dia_pago < dia_corte` (payment happens after the statement closes);
    otherwise payment lands in the same month as the cut. Handles Dec->Jan
    (and further) month rollover via `_sumar_mes`.
    """
    desde = desde or date.today()
    proximo_corte = proxima_fecha_de_dia(dia_corte, desde)

    if dia_pago < dia_corte:
        anio_pago, mes_pago = _sumar_mes(proximo_corte.year, proximo_corte.month, 1)
    else:
        anio_pago, mes_pago = proximo_corte.year, proximo_corte.month
    proximo_pago = date(anio_pago, mes_pago, clamp_dia(anio_pago, mes_pago, dia_pago))

    return {
        "proximo_corte": proximo_corte.isoformat(),
        "proximo_pago": proximo_pago.isoformat(),
        "dias_restantes": (proximo_corte - desde).days,
    }


def dias_hasta_cumple(cumple_mes: int, cumple_dia: int, desde: date | None = None) -> dict:
    """Days until the next birthday occurrence, year-wrap safe.

    e.g. desde=2025-12-28, cumple=(mes=1, dia=3) -> 6 days, not -359.
    """
    desde = desde or date.today()
    anio = desde.year
    candidata = date(anio, cumple_mes, clamp_dia(anio, cumple_mes, cumple_dia))
    if candidata < desde:
        anio += 1
        candidata = date(anio, cumple_mes, clamp_dia(anio, cumple_mes, cumple_dia))
    return {
        "fecha_este_anio": candidata.isoformat(),
        "dias_restantes": (candidata - desde).days,
    }


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    db_path = db_path or os.environ.get("VIDA_DB", DEFAULT_DB_PATH)
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    _ensure_schema(conn)
    return conn


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
    return int(row["v"])


def _ensure_schema(conn: sqlite3.Connection) -> None:
    existe = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if existe is None:
        # Fresh database: schema.sql IS the latest shape and inserts every
        # version row up front (D-0.4).
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.commit()
        return
    _aplicar_migraciones(conn)


def _aplicar_migraciones(conn: sqlite3.Connection) -> None:
    actual = _schema_version(conn)
    if actual >= TARGET_SCHEMA_VERSION:
        return  # up to date, or newer DB + older code -- safe, migrations are additive (D-0.5)

    previo = conn.isolation_level
    conn.isolation_level = None  # manual control: sqlite3 does NOT wrap DDL (D-0.3)
    try:
        for version in range(actual + 1, TARGET_SCHEMA_VERSION + 1):
            sentencias = MIGRATIONS.get(version)
            if sentencias is None:
                raise VidaError(
                    f"falta la definicion de la migracion {version}", "migracion_faltante"
                )
            conn.execute("BEGIN IMMEDIATE")
            try:
                for sentencia in sentencias:
                    conn.execute(sentencia)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.isolation_level = previo


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _hoy() -> date:
    return date.today()


def _parse_fecha(valor: str, codigo: str = "fecha_invalida") -> date:
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError as exc:
        raise VidaError(f"Fecha invalida: {valor!r} (esperado YYYY-MM-DD)", codigo) from exc


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


# ---------------------------------------------------------------------------
# gasto
# ---------------------------------------------------------------------------

def cmd_gasto_add(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.monto <= 0:
        raise VidaError("monto debe ser mayor a 0", "validacion")
    if args.metodo and args.metodo not in METODOS_PAGO:
        raise VidaError(f"metodo_pago invalido: {args.metodo!r}", "validacion")

    fecha = args.fecha or _hoy().isoformat()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO gastos (fecha, monto, moneda, categoria, descripcion,
                                 metodo_pago, tarjeta_id, fuente)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fecha,
                args.monto,
                args.moneda or "PEN",
                args.categoria,
                args.descripcion,
                args.metodo,
                args.tarjeta,
                args.fuente or "cli",
            ),
        )
        gasto_id = cur.lastrowid
    row = conn.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
    return _row_to_dict(row)


def cmd_gasto_report(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.mes:
        try:
            anio_str, mes_str = args.mes.split("-")
            anio, mes = int(anio_str), int(mes_str)
        except ValueError as exc:
            raise VidaError(f"--mes invalido: {args.mes!r} (esperado YYYY-MM)", "validacion") from exc
        desde = date(anio, mes, 1)
        _, ultimo = calendar.monthrange(anio, mes)
        hasta = date(anio, mes, ultimo)
    elif args.desde and args.hasta:
        desde = _parse_fecha(args.desde)
        hasta = _parse_fecha(args.hasta)
    else:
        raise VidaError("se requiere --mes o --desde/--hasta", "validacion")

    query = "SELECT * FROM gastos WHERE fecha BETWEEN ? AND ?"
    params: list = [desde.isoformat(), hasta.isoformat()]
    if args.categoria:
        query += " AND categoria = ?"
        params.append(args.categoria)

    rows = conn.execute(query, params).fetchall()
    if args.limite:
        rows = rows[: args.limite]

    monedas = {r["moneda"] for r in rows}
    total_por_moneda: dict = {}
    for r in rows:
        total_por_moneda[r["moneda"]] = total_por_moneda.get(r["moneda"], 0.0) + r["monto"]

    if len(monedas) <= 1:
        moneda_unica = next(iter(monedas), None)
        total = total_por_moneda.get(moneda_unica, 0.0)
    else:
        moneda_unica = None
        total = total_por_moneda  # multi-currency: report per-moneda totals

    categorias: dict = {}
    for r in rows:
        clave = (r["categoria"], r["moneda"])
        if clave not in categorias:
            categorias[clave] = {"categoria": r["categoria"], "moneda": r["moneda"], "total": 0.0, "n": 0}
        categorias[clave]["total"] += r["monto"]
        categorias[clave]["n"] += 1

    return {
        "total": total,
        "moneda": moneda_unica,
        "por_categoria": list(categorias.values()),
        "rango": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "n_gastos": len(rows),
    }


def cmd_gasto_categorias(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    query = "SELECT categoria, COUNT(*) AS n FROM gastos"
    params: list = []
    if args.desde:
        query += " WHERE fecha >= ?"
        params.append(args.desde)
    query += " GROUP BY categoria ORDER BY n DESC"
    rows = conn.execute(query, params).fetchall()
    return {"categorias": [{"categoria": r["categoria"], "n": r["n"]} for r in rows]}


# ---------------------------------------------------------------------------
# gym
# ---------------------------------------------------------------------------

def cmd_gym_log(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.peso < 0:
        raise VidaError("peso no puede ser negativo", "validacion")
    if args.reps < 1:
        raise VidaError("repeticiones debe ser >= 1", "validacion")
    if args.rpe is not None and not (1 <= args.rpe <= 10):
        raise VidaError("rpe debe estar entre 1 y 10", "validacion")

    ejercicio = args.ejercicio.strip().lower()
    fecha = args.fecha or _hoy().isoformat()

    serie = args.serie
    if serie is None:
        row = conn.execute(
            "SELECT MAX(serie) AS max_serie FROM entrenamientos WHERE fecha = ? AND ejercicio = ?",
            (fecha, ejercicio),
        ).fetchone()
        serie = (row["max_serie"] or 0) + 1

    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO entrenamientos (fecha, ejercicio, serie, peso, repeticiones,
                                             rpe, notas, fuente)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fecha,
                    ejercicio,
                    serie,
                    args.peso,
                    args.reps,
                    args.rpe,
                    args.notas,
                    args.fuente or "cli",
                ),
            )
            entren_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise VidaError(
            f"ya existe una serie {serie} para {ejercicio} en {fecha}", "duplicado"
        ) from exc

    row = conn.execute("SELECT * FROM entrenamientos WHERE id = ?", (entren_id,)).fetchone()
    return _row_to_dict(row)


def _sesiones_ejercicio(conn: sqlite3.Connection, ejercicio: str, limite: int) -> list[dict]:
    """Last `limite` sessions (grouped by fecha) for an exercise, most recent first."""
    fechas = [
        r["fecha"]
        for r in conn.execute(
            "SELECT DISTINCT fecha FROM entrenamientos WHERE ejercicio = ? ORDER BY fecha DESC LIMIT ?",
            (ejercicio, limite),
        ).fetchall()
    ]
    sesiones = []
    for fecha in fechas:
        sets_ = conn.execute(
            "SELECT * FROM entrenamientos WHERE ejercicio = ? AND fecha = ? ORDER BY serie ASC",
            (ejercicio, fecha),
        ).fetchall()
        sets_ = [_row_to_dict(r) for r in sets_]
        top_set = max(sets_, key=lambda s: (s["peso"], s["repeticiones"]))
        volumen = sum(s["peso"] * s["repeticiones"] for s in sets_)
        sesiones.append({"fecha": fecha, "sets": sets_, "top_set": top_set, "volumen": volumen})
    return sesiones


def calcular_sugerencia(sesiones: list[dict], ejercicio: str) -> dict:
    """Deterministic progression rule (design §7, D11).

    NOTE (deviation, documented): the design's "hit their target reps" refers
    to a target that is not stored anywhere in the schema. We interpret the
    target as the reps of the FIRST set (serie 1) of that session — i.e. the
    session is "complete" when no later set faded below the opening set's
    rep count. This is the only deterministic signal available without a new
    schema column.
    """
    if not sesiones:
        return {"peso": None, "reps": None, "razon": "sin historial"}

    ultima = sesiones[0]
    top_set = ultima["top_set"]
    primera_serie = min(ultima["sets"], key=lambda s: s["serie"])
    objetivo_reps = primera_serie["repeticiones"]
    completa = all(s["repeticiones"] >= objetivo_reps for s in ultima["sets"])

    if completa:
        incremento = INCREMENTO_KG.get(ejercicio, INCREMENTO_DEFAULT_KG)
        return {
            "peso": top_set["peso"] + incremento,
            "reps": top_set["repeticiones"],
            "razon": "progresion: sesion anterior completa",
        }
    return {
        "peso": top_set["peso"],
        "reps": top_set["repeticiones"],
        "razon": "repetir: sesion anterior incompleta",
    }


def cmd_gym_progress(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    ejercicio = args.ejercicio.strip().lower()
    limite = args.limite or 5
    sesiones = _sesiones_ejercicio(conn, ejercicio, limite)

    historial = [
        {
            "fecha": s["fecha"],
            "top_set": {"peso": s["top_set"]["peso"], "repeticiones": s["top_set"]["repeticiones"]},
            "volumen": s["volumen"],
        }
        for s in sesiones
    ]
    ultimo_top_set = historial[0]["top_set"] if historial else None
    sugerencia = calcular_sugerencia(sesiones, ejercicio)

    return {
        "historial": historial,
        "ultimo_top_set": ultimo_top_set,
        "sugerencia": sugerencia,
    }


def cmd_gym_resumen(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    query = "SELECT ejercicio, fecha, peso, repeticiones FROM entrenamientos"
    params: list = []
    condiciones = []
    if args.desde:
        condiciones.append("fecha >= ?")
        params.append(args.desde)
    if args.hasta:
        condiciones.append("fecha <= ?")
        params.append(args.hasta)
    if condiciones:
        query += " WHERE " + " AND ".join(condiciones)
    rows = conn.execute(query, params).fetchall()

    por_ejercicio: dict = {}
    for r in rows:
        entry = por_ejercicio.setdefault(
            r["ejercicio"], {"ejercicio": r["ejercicio"], "volumen": 0.0, "sesiones": set()}
        )
        entry["volumen"] += r["peso"] * r["repeticiones"]
        entry["sesiones"].add(r["fecha"])

    resumen = [
        {"ejercicio": v["ejercicio"], "volumen": v["volumen"], "sesiones": len(v["sesiones"])}
        for v in por_ejercicio.values()
    ]
    return {"resumen": resumen}


# ---------------------------------------------------------------------------
# tarjeta
# ---------------------------------------------------------------------------

def cmd_tarjeta_add(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if not (1 <= args.dia_corte <= 31):
        raise VidaError("dia-corte debe estar entre 1 y 31", "validacion")
    if not (1 <= args.dia_pago <= 31):
        raise VidaError("dia-pago debe estar entre 1 y 31", "validacion")

    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO tarjetas (nombre, banco, dia_corte, dia_pago, moneda,
                                       linea_credito, alerta_dias_antes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    args.nombre,
                    args.banco,
                    args.dia_corte,
                    args.dia_pago,
                    args.moneda or "PEN",
                    args.linea,
                    args.alerta_dias if args.alerta_dias is not None else 3,
                ),
            )
            tarjeta_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise VidaError(f"ya existe una tarjeta llamada {args.nombre!r}", "duplicado") from exc

    row = conn.execute("SELECT * FROM tarjetas WHERE id = ?", (tarjeta_id,)).fetchone()
    return _row_to_dict(row)


def cmd_tarjeta_next(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    query = "SELECT * FROM tarjetas WHERE activa = 1"
    params: list = []
    if args.nombre:
        query += " AND nombre = ?"
        params.append(args.nombre)
    tarjetas = conn.execute(query, params).fetchall()

    hoy = _hoy()
    resultados = []
    for t in tarjetas:
        ciclo = resolver_ciclo_tarjeta(t["dia_corte"], t["dia_pago"], hoy)
        corte_anterior = proxima_fecha_de_dia(t["dia_corte"], hoy - timedelta(days=32))
        if corte_anterior >= hoy:
            corte_anterior = corte_anterior - timedelta(days=31)

        gasto_row = conn.execute(
            """
            SELECT COALESCE(SUM(monto), 0) AS total FROM gastos
            WHERE tarjeta_id = ? AND metodo_pago = 'credito' AND fecha > ? AND fecha <= ?
            """,
            (t["id"], corte_anterior.isoformat(), hoy.isoformat()),
        ).fetchone()

        alertar = ciclo["dias_restantes"] <= t["alerta_dias_antes"]
        resultados.append(
            {
                "nombre": t["nombre"],
                "proximo_corte": ciclo["proximo_corte"],
                "proximo_pago": ciclo["proximo_pago"],
                "dias_restantes": ciclo["dias_restantes"],
                "alertar": alertar,
                "gasto_ciclo_actual": gasto_row["total"],
            }
        )

    if args.dias is not None:
        resultados = [r for r in resultados if r["dias_restantes"] <= args.dias]

    return {"tarjetas": resultados}


# ---------------------------------------------------------------------------
# cumple
# ---------------------------------------------------------------------------

def cmd_cumple_add(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if not (1 <= args.mes <= 12):
        raise VidaError("mes debe estar entre 1 y 12", "validacion")
    if not (1 <= args.dia <= 31):
        raise VidaError("dia debe estar entre 1 y 31", "validacion")

    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO contactos (nombre, cumple_mes, cumple_dia, cumple_anio,
                                        relacion, alerta_dias_antes, notas)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    args.nombre,
                    args.mes,
                    args.dia,
                    args.anio,
                    args.relacion,
                    args.alerta_dias if args.alerta_dias is not None else 7,
                    args.notas,
                ),
            )
            contacto_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise VidaError(f"ya existe un contacto llamado {args.nombre!r}", "duplicado") from exc

    row = conn.execute("SELECT * FROM contactos WHERE id = ?", (contacto_id,)).fetchone()
    return _row_to_dict(row)


def cmd_cumple_upcoming(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    dias_max = args.dias if args.dias is not None else 30
    hoy = _hoy()
    rows = conn.execute("SELECT * FROM contactos").fetchall()

    proximos = []
    for c in rows:
        resultado = dias_hasta_cumple(c["cumple_mes"], c["cumple_dia"], hoy)
        if resultado["dias_restantes"] > dias_max:
            continue
        edad = None
        if c["cumple_anio"] is not None:
            anio_cumple = int(resultado["fecha_este_anio"][:4])
            edad = anio_cumple - c["cumple_anio"]
        proximos.append(
            {
                "nombre": c["nombre"],
                "fecha_este_anio": resultado["fecha_este_anio"],
                "dias_restantes": resultado["dias_restantes"],
                "edad_a_cumplir": edad,
            }
        )

    proximos.sort(key=lambda p: p["dias_restantes"])
    return {"proximos": proximos}


# ---------------------------------------------------------------------------
# pendiente
# ---------------------------------------------------------------------------

def cmd_pendiente_add(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.prioridad and args.prioridad not in PRIORIDADES:
        raise VidaError(f"prioridad invalida: {args.prioridad!r}", "validacion")
    if args.dificultad and args.dificultad not in DIFICULTADES:
        raise VidaError(f"dificultad invalida: {args.dificultad!r}", "validacion")

    with conn:
        cur = conn.execute(
            """
            INSERT INTO pendientes (titulo, detalle, fecha_objetivo, hora, prioridad,
                                     recurrencia, dificultad)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                args.titulo,
                args.detalle,
                args.fecha,
                args.hora,
                args.prioridad or "media",
                args.recurrencia,
                args.dificultad,
            ),
        )
        pendiente_id = cur.lastrowid
    row = conn.execute("SELECT * FROM pendientes WHERE id = ?", (pendiente_id,)).fetchone()
    return _row_to_dict(row)


def _recurrencia_vence_hoy(recurrencia: str, hoy: date) -> bool:
    if recurrencia == "diaria":
        return True
    if recurrencia.startswith("semanal:"):
        dias_semana = {
            "lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6,
        }
        objetivo = dias_semana.get(recurrencia.split(":", 1)[1])
        return objetivo is not None and hoy.weekday() == objetivo
    if recurrencia.startswith("mensual:"):
        try:
            dia_objetivo = int(recurrencia.split(":", 1)[1])
        except ValueError:
            return False
        return hoy.day == clamp_dia(hoy.year, hoy.month, dia_objetivo)
    return False


def cmd_pendiente_today(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    # No code change needed for `dificultad`: SELECT * (via _row_to_dict) picks
    # up the new column for free. Additive contract -- a new key appears in
    # the payload, none disappear (daily-routine-tracker design.md §5.6).
    hoy = _hoy()
    incluir_vencidos = args.incluir_vencidos if args.incluir_vencidos is not None else True

    query = "SELECT * FROM pendientes WHERE estado = 'abierto'"
    rows = conn.execute(query).fetchall()

    prioridad_orden = {"alta": 0, "media": 1, "baja": 2}
    items = []
    for r in rows:
        vence_hoy = r["fecha_objetivo"] == hoy.isoformat()
        vencido = (
            incluir_vencidos
            and r["fecha_objetivo"] is not None
            and r["fecha_objetivo"] < hoy.isoformat()
        )
        recurrente_hoy = bool(r["recurrencia"]) and _recurrencia_vence_hoy(r["recurrencia"], hoy)
        if vence_hoy or vencido or recurrente_hoy:
            items.append(_row_to_dict(r))

    items.sort(key=lambda i: (prioridad_orden.get(i["prioridad"], 9), i["hora"] or "99:99"))
    return {"pendientes": items}


def cmd_pendiente_done(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    row = conn.execute("SELECT * FROM pendientes WHERE id = ?", (args.id,)).fetchone()
    if row is None:
        raise VidaError(f"no existe pendiente con id {args.id}", "no_encontrado")

    with conn:
        conn.execute(
            "UPDATE pendientes SET estado = 'hecho', completado_en = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), args.id),
        )
    row = conn.execute("SELECT * FROM pendientes WHERE id = ?", (args.id,)).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def cmd_health(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    version_row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    tablas = [
        "gastos", "entrenamientos", "tarjetas", "contactos", "pendientes",
        "rutina_bloques", "rutina_items", "rutina_completado",
    ]
    conteos = {
        t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tablas
    }
    integridad = conn.execute("PRAGMA integrity_check").fetchone()[0]

    return {
        "db_path": args.db_path or os.environ.get("VIDA_DB", DEFAULT_DB_PATH),
        "schema_version": version_row["v"],
        "conteos": conteos,
        "integrity_ok": integridad == "ok",
    }


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vida.py")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    gasto = subparsers.add_parser("gasto")
    gasto_sub = gasto.add_subparsers(dest="subcomando", required=True)

    gasto_add = gasto_sub.add_parser("add")
    gasto_add.add_argument("--monto", type=float, required=True)
    gasto_add.add_argument("--categoria", required=True)
    gasto_add.add_argument("--descripcion")
    gasto_add.add_argument("--fecha")
    gasto_add.add_argument("--moneda")
    gasto_add.add_argument("--metodo")
    gasto_add.add_argument("--tarjeta", type=int)
    gasto_add.add_argument("--fuente")
    gasto_add.set_defaults(func=cmd_gasto_add)

    gasto_report = gasto_sub.add_parser("report")
    gasto_report.add_argument("--mes")
    gasto_report.add_argument("--desde")
    gasto_report.add_argument("--hasta")
    gasto_report.add_argument("--categoria")
    gasto_report.add_argument("--limite", type=int)
    gasto_report.set_defaults(func=cmd_gasto_report)

    gasto_cat = gasto_sub.add_parser("categorias")
    gasto_cat.add_argument("--desde")
    gasto_cat.set_defaults(func=cmd_gasto_categorias)

    gym = subparsers.add_parser("gym")
    gym_sub = gym.add_subparsers(dest="subcomando", required=True)

    gym_log = gym_sub.add_parser("log")
    gym_log.add_argument("--ejercicio", required=True)
    gym_log.add_argument("--peso", type=float, required=True)
    gym_log.add_argument("--reps", type=int, required=True)
    gym_log.add_argument("--serie", type=int)
    gym_log.add_argument("--rpe", type=float)
    gym_log.add_argument("--fecha")
    gym_log.add_argument("--notas")
    gym_log.add_argument("--fuente")
    gym_log.set_defaults(func=cmd_gym_log)

    gym_progress = gym_sub.add_parser("progress")
    gym_progress.add_argument("--ejercicio", required=True)
    gym_progress.add_argument("--limite", type=int)
    gym_progress.set_defaults(func=cmd_gym_progress)

    gym_resumen = gym_sub.add_parser("resumen")
    gym_resumen.add_argument("--desde")
    gym_resumen.add_argument("--hasta")
    gym_resumen.set_defaults(func=cmd_gym_resumen)

    tarjeta = subparsers.add_parser("tarjeta")
    tarjeta_sub = tarjeta.add_subparsers(dest="subcomando", required=True)

    tarjeta_add = tarjeta_sub.add_parser("add")
    tarjeta_add.add_argument("--nombre", required=True)
    tarjeta_add.add_argument("--dia-corte", type=int, required=True, dest="dia_corte")
    tarjeta_add.add_argument("--dia-pago", type=int, required=True, dest="dia_pago")
    tarjeta_add.add_argument("--banco")
    tarjeta_add.add_argument("--moneda")
    tarjeta_add.add_argument("--linea", type=float)
    tarjeta_add.add_argument("--alerta-dias", type=int, dest="alerta_dias")
    tarjeta_add.set_defaults(func=cmd_tarjeta_add)

    tarjeta_next = tarjeta_sub.add_parser("next")
    tarjeta_next.add_argument("--dias", type=int)
    tarjeta_next.add_argument("--nombre")
    tarjeta_next.set_defaults(func=cmd_tarjeta_next)

    cumple = subparsers.add_parser("cumple")
    cumple_sub = cumple.add_subparsers(dest="subcomando", required=True)

    cumple_add = cumple_sub.add_parser("add")
    cumple_add.add_argument("--nombre", required=True)
    cumple_add.add_argument("--mes", type=int, required=True)
    cumple_add.add_argument("--dia", type=int, required=True)
    cumple_add.add_argument("--anio", type=int)
    cumple_add.add_argument("--relacion")
    cumple_add.add_argument("--alerta-dias", type=int, dest="alerta_dias")
    cumple_add.add_argument("--notas")
    cumple_add.set_defaults(func=cmd_cumple_add)

    cumple_upcoming = cumple_sub.add_parser("upcoming")
    cumple_upcoming.add_argument("--dias", type=int)
    cumple_upcoming.set_defaults(func=cmd_cumple_upcoming)

    pendiente = subparsers.add_parser("pendiente")
    pendiente_sub = pendiente.add_subparsers(dest="subcomando", required=True)

    pendiente_add = pendiente_sub.add_parser("add")
    pendiente_add.add_argument("--titulo", required=True)
    pendiente_add.add_argument("--fecha")
    pendiente_add.add_argument("--hora")
    pendiente_add.add_argument("--prioridad")
    pendiente_add.add_argument("--detalle")
    pendiente_add.add_argument("--recurrencia")
    pendiente_add.add_argument("--dificultad")
    pendiente_add.set_defaults(func=cmd_pendiente_add)

    pendiente_today = pendiente_sub.add_parser("today")
    pendiente_today.add_argument("--incluir-vencidos", type=int, dest="incluir_vencidos")
    pendiente_today.set_defaults(func=cmd_pendiente_today)

    pendiente_done = pendiente_sub.add_parser("done")
    pendiente_done.add_argument("--id", type=int, required=True)
    pendiente_done.set_defaults(func=cmd_pendiente_done)

    health = subparsers.add_parser("health")
    health.add_argument("--db-path", dest="db_path")
    health.set_defaults(func=cmd_health)

    return parser


def _accion(args: argparse.Namespace) -> str:
    sub = getattr(args, "subcomando", None)
    return f"{args.comando}.{sub}" if sub else args.comando


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    accion = _accion(args)

    try:
        conn = get_connection(getattr(args, "db_path", None))
        try:
            data = args.func(conn, args)
        finally:
            conn.close()
    except VidaError as exc:
        print(json.dumps({"ok": False, "action": accion, "error": exc.mensaje, "codigo": exc.codigo}))
        return 1
    except sqlite3.IntegrityError as exc:
        print(json.dumps({"ok": False, "action": accion, "error": str(exc), "codigo": "integridad"}))
        return 1
    except Exception as exc:  # noqa: BLE001 - JSON contract requires catching everything
        print(json.dumps({"ok": False, "action": accion, "error": str(exc), "codigo": "error"}))
        return 1

    print(json.dumps({"ok": True, "action": accion, "data": data}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
