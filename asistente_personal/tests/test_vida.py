"""Unit + contract tests for vida.py (design ref: design.md §9 Testing Strategy).

stdlib `unittest` only, per project convention (no pytest dependency).
Run with: python3 -m unittest discover asistente_personal/tests
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(os.path.dirname(TESTS_DIR), "bin")
sys.path.insert(0, BIN_DIR)

import vida  # noqa: E402  (import after sys.path tweak, by design)

VIDA_PY = os.path.join(BIN_DIR, "vida.py")

# Frozen Fase 1 (schema_version=1) DDL, embedded so the migration tests do NOT
# depend on the live schema.sql -- which now IS the v2 shape (design.md §7.1).
# Deliberately NOT imported/read from disk: reading the live file would make
# "does v1 -> v2 migration work" tautological the moment schema.sql changes.
SCHEMA_V1_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE gastos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    monto            REAL   NOT NULL CHECK (monto > 0),
    moneda          TEXT    NOT NULL DEFAULT 'PEN' CHECK (moneda IN ('PEN', 'USD')),
    categoria       TEXT    NOT NULL,
    descripcion     TEXT,
    metodo_pago     TEXT    CHECK (metodo_pago IN ('efectivo', 'debito', 'credito', 'yape', 'plin', 'transferencia')),
    tarjeta_id      INTEGER REFERENCES tarjetas(id) ON DELETE SET NULL,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente          TEXT    NOT NULL DEFAULT 'telegram' CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron'))
);

CREATE INDEX idx_gastos_fecha ON gastos(fecha);
CREATE INDEX idx_gastos_cat_fecha ON gastos(categoria, fecha);

CREATE TABLE entrenamientos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    ejercicio       TEXT    NOT NULL,
    serie           INTEGER NOT NULL CHECK (serie >= 1),
    peso            REAL    NOT NULL CHECK (peso >= 0),
    repeticiones    INTEGER NOT NULL CHECK (repeticiones >= 1),
    rpe             REAL    CHECK (rpe IS NULL OR (rpe BETWEEN 1 AND 10)),
    notas           TEXT,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente          TEXT    NOT NULL DEFAULT 'telegram' CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
    UNIQUE (fecha, ejercicio, serie)
);

CREATE INDEX idx_entren_ejercicio_fecha ON entrenamientos(ejercicio, fecha DESC);

CREATE TABLE tarjetas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre              TEXT    NOT NULL UNIQUE,
    banco               TEXT,
    dia_corte           INTEGER NOT NULL CHECK (dia_corte BETWEEN 1 AND 31),
    dia_pago            INTEGER NOT NULL CHECK (dia_pago BETWEEN 1 AND 31),
    moneda              TEXT    NOT NULL DEFAULT 'PEN',
    linea_credito       REAL    CHECK (linea_credito IS NULL OR linea_credito > 0),
    alerta_dias_antes   INTEGER NOT NULL DEFAULT 3 CHECK (alerta_dias_antes BETWEEN 0 AND 15),
    activa              INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1)),
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE contactos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre              TEXT    NOT NULL UNIQUE,
    cumple_mes          INTEGER NOT NULL CHECK (cumple_mes BETWEEN 1 AND 12),
    cumple_dia          INTEGER NOT NULL CHECK (cumple_dia BETWEEN 1 AND 31),
    cumple_anio         INTEGER CHECK (cumple_anio IS NULL OR (cumple_anio BETWEEN 1900 AND 2100)),
    relacion            TEXT,
    alerta_dias_antes   INTEGER NOT NULL DEFAULT 7 CHECK (alerta_dias_antes BETWEEN 0 AND 60),
    notas               TEXT,
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE pendientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo          TEXT    NOT NULL,
    detalle         TEXT,
    fecha_objetivo  TEXT,
    hora            TEXT,
    prioridad       TEXT    NOT NULL DEFAULT 'media' CHECK (prioridad IN ('alta', 'media', 'baja')),
    estado          TEXT    NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto', 'hecho', 'cancelado')),
    recurrencia     TEXT,
    completado_en   TEXT,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente          TEXT    NOT NULL DEFAULT 'telegram' CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron'))
);

CREATE INDEX idx_pend_estado_fecha ON pendientes(estado, fecha_objetivo);

CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    aplicado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""


def _build_v1_db(db_path: str) -> None:
    """Build a frozen v1 database at db_path with one seed row per v1 table."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_V1_SQL)
    conn.commit()
    with conn:
        conn.execute(
            "INSERT INTO gastos (monto, categoria) VALUES (10.0, 'comida')"
        )
        conn.execute(
            "INSERT INTO entrenamientos (fecha, ejercicio, serie, peso, repeticiones) "
            "VALUES ('2025-06-01', 'sentadilla', 1, 80, 8)"
        )
        conn.execute(
            "INSERT INTO tarjetas (nombre, dia_corte, dia_pago) VALUES ('BCP Visa', 15, 5)"
        )
        conn.execute(
            "INSERT INTO contactos (nombre, cumple_mes, cumple_dia) VALUES ('Ana', 1, 3)"
        )
        conn.execute(
            "INSERT INTO pendientes (titulo) VALUES ('Pagar luz')"
        )
    conn.close()


# ---------------------------------------------------------------------------
# Date helper edge cases — the core TDD targets called out in the design doc
# ---------------------------------------------------------------------------

class TestClampDia(unittest.TestCase):
    def test_feb_31_clamps_to_28_in_non_leap_year(self):
        self.assertEqual(vida.clamp_dia(2023, 2, 31), 28)

    def test_feb_31_clamps_to_29_in_leap_year(self):
        self.assertEqual(vida.clamp_dia(2024, 2, 31), 29)

    def test_day_within_range_is_unchanged(self):
        self.assertEqual(vida.clamp_dia(2025, 6, 15), 15)

    def test_april_31_clamps_to_30(self):
        self.assertEqual(vida.clamp_dia(2025, 4, 31), 30)


class TestResolverCicloTarjeta(unittest.TestCase):
    def test_dia_pago_menor_a_dia_corte_rolls_into_next_month(self):
        # corte=15, pago=5 -> pago must land in the month AFTER the cut's month.
        ciclo = vida.resolver_ciclo_tarjeta(15, 5, desde=date(2025, 6, 20))
        self.assertEqual(ciclo["proximo_corte"], "2025-07-15")
        self.assertEqual(ciclo["proximo_pago"], "2025-08-05")

    def test_dia_pago_mayor_o_igual_a_dia_corte_stays_same_month(self):
        ciclo = vida.resolver_ciclo_tarjeta(5, 20, desde=date(2025, 6, 1))
        self.assertEqual(ciclo["proximo_corte"], "2025-06-05")
        self.assertEqual(ciclo["proximo_pago"], "2025-06-20")

    def test_dec_to_jan_rollover(self):
        # desde is after this year's day-28 cut -> corte rolls Dec -> Jan,
        # and since pago(5) < corte(28), pago rolls one further month (Jan -> Feb).
        ciclo = vida.resolver_ciclo_tarjeta(28, 5, desde=date(2025, 12, 30))
        self.assertEqual(ciclo["proximo_corte"], "2026-01-28")
        self.assertEqual(ciclo["proximo_pago"], "2026-02-05")

    def test_dias_restantes_is_correct(self):
        ciclo = vida.resolver_ciclo_tarjeta(15, 5, desde=date(2025, 6, 20))
        self.assertEqual(ciclo["dias_restantes"], 25)


class TestDiasHastaCumple(unittest.TestCase):
    def test_year_wrap_dec_to_jan(self):
        # Dec 28 -> Jan 3 must be 6 days, not -359.
        resultado = vida.dias_hasta_cumple(1, 3, desde=date(2025, 12, 28))
        self.assertEqual(resultado["dias_restantes"], 6)
        self.assertEqual(resultado["fecha_este_anio"], "2026-01-03")

    def test_same_year_no_wrap(self):
        resultado = vida.dias_hasta_cumple(8, 15, desde=date(2025, 6, 1))
        self.assertEqual(resultado["fecha_este_anio"], "2025-08-15")
        self.assertEqual(resultado["dias_restantes"], 75)

    def test_birthday_today_is_zero_days(self):
        resultado = vida.dias_hasta_cumple(6, 1, desde=date(2025, 6, 1))
        self.assertEqual(resultado["dias_restantes"], 0)

    def test_feb_29_birthday_in_non_leap_year_clamps(self):
        resultado = vida.dias_hasta_cumple(2, 29, desde=date(2025, 1, 1))
        self.assertEqual(resultado["fecha_este_anio"], "2025-02-28")


class TestCalcularSugerencia(unittest.TestCase):
    def test_no_history_returns_null_sugerencia(self):
        sugerencia = vida.calcular_sugerencia([], "sentadilla")
        self.assertIsNone(sugerencia["peso"])
        self.assertEqual(sugerencia["razon"], "sin historial")

    def test_complete_session_progresses_with_known_exercise_increment(self):
        sesiones = [
            {
                "fecha": "2025-06-01",
                "sets": [
                    {"serie": 1, "peso": 80.0, "repeticiones": 8},
                    {"serie": 2, "peso": 80.0, "repeticiones": 8},
                ],
                "top_set": {"serie": 1, "peso": 80.0, "repeticiones": 8},
                "volumen": 1280.0,
            }
        ]
        sugerencia = vida.calcular_sugerencia(sesiones, "sentadilla")
        self.assertEqual(sugerencia["peso"], 85.0)
        self.assertEqual(sugerencia["razon"], "progresion: sesion anterior completa")

    def test_incomplete_session_repeats_weight(self):
        sesiones = [
            {
                "fecha": "2025-06-01",
                "sets": [
                    {"serie": 1, "peso": 80.0, "repeticiones": 8},
                    {"serie": 2, "peso": 80.0, "repeticiones": 5},
                ],
                "top_set": {"serie": 1, "peso": 80.0, "repeticiones": 8},
                "volumen": 1040.0,
            }
        ]
        sugerencia = vida.calcular_sugerencia(sesiones, "sentadilla")
        self.assertEqual(sugerencia["peso"], 80.0)
        self.assertEqual(sugerencia["razon"], "repetir: sesion anterior incompleta")

    def test_unknown_exercise_uses_default_increment(self):
        sesiones = [
            {
                "fecha": "2025-06-01",
                "sets": [{"serie": 1, "peso": 40.0, "repeticiones": 10}],
                "top_set": {"serie": 1, "peso": 40.0, "repeticiones": 10},
                "volumen": 400.0,
            }
        ]
        sugerencia = vida.calcular_sugerencia(sesiones, "curl biceps")
        self.assertEqual(sugerencia["peso"], 42.5)


# ---------------------------------------------------------------------------
# Migration tests (daily-routine-tracker design.md §3, §7.1) -- the class
# that justifies the whole D-0 migration mechanism.
# ---------------------------------------------------------------------------

_V1_TABLES = ("gastos", "entrenamientos", "tarjetas", "contactos", "pendientes")
_V2_ONLY_TABLES = ("rutina_bloques", "rutina_items", "rutina_completado")
_V2_INDEXES = (
    "idx_rutina_items_bloque",
    "idx_rutina_compl_fecha",
    "idx_rutina_compl_item_fecha",
)


class TestMigracionV1aV2(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "vida.db")
        _build_v1_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_v1_db_is_migrated_to_v2_on_open(self):
        conn = vida.get_connection(self.db_path)
        try:
            self.assertEqual(vida._schema_version(conn), 2)
            versiones = [
                r["version"]
                for r in conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
            ]
            self.assertEqual(versiones, [1, 2])
        finally:
            conn.close()

    def test_migration_preserves_every_row(self):
        pre_counts = {}
        pre_conn = sqlite3.connect(self.db_path)
        pre_conn.row_factory = sqlite3.Row
        for t in _V1_TABLES:
            pre_counts[t] = pre_conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        pre_pendiente = dict(pre_conn.execute("SELECT * FROM pendientes WHERE id = 1").fetchone())
        pre_conn.close()

        conn = vida.get_connection(self.db_path)
        try:
            for t in _V1_TABLES:
                n = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                self.assertEqual(n, pre_counts[t], msg=f"row count changed for {t}")
            post_pendiente = dict(conn.execute("SELECT * FROM pendientes WHERE id = 1").fetchone())
            for key in pre_pendiente:
                self.assertEqual(post_pendiente[key], pre_pendiente[key], msg=f"column {key} changed")
        finally:
            conn.close()

    def test_existing_pendientes_get_null_dificultad(self):
        conn = vida.get_connection(self.db_path)
        try:
            rows = conn.execute("SELECT dificultad FROM pendientes").fetchall()
            self.assertTrue(all(r["dificultad"] is None for r in rows))
        finally:
            conn.close()

    def test_new_tables_exist_after_migration(self):
        conn = vida.get_connection(self.db_path)
        try:
            nombres = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for t in _V2_ONLY_TABLES:
                self.assertIn(t, nombres)
            indices = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            for idx in _V2_INDEXES:
                self.assertIn(idx, indices)
        finally:
            conn.close()

    def test_fresh_bootstrap_and_migrated_v1_have_identical_schema(self):
        fresh_path = os.path.join(self.tmpdir.name, "fresh.db")
        fresh_conn = vida.get_connection(fresh_path)
        migrated_conn = vida.get_connection(self.db_path)
        try:
            self._assert_same_schema(fresh_conn, migrated_conn)
        finally:
            fresh_conn.close()
            migrated_conn.close()

    def _assert_same_schema(self, conn_a, conn_b):
        tablas_a = {
            r["name"]
            for r in conn_a.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
            ).fetchall()
        }
        tablas_b = {
            r["name"]
            for r in conn_b.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
            ).fetchall()
        }
        self.assertEqual(tablas_a, tablas_b)

        for tabla in sorted(tablas_a):
            info_a = [tuple(r) for r in conn_a.execute(f"PRAGMA table_info({tabla})").fetchall()]
            info_b = [tuple(r) for r in conn_b.execute(f"PRAGMA table_info({tabla})").fetchall()]
            self.assertEqual(info_a, info_b, msg=f"table_info differs for {tabla}")

            idx_a = sorted(
                (r["name"], r["unique"]) for r in conn_a.execute(f"PRAGMA index_list({tabla})").fetchall()
            )
            idx_b = sorted(
                (r["name"], r["unique"]) for r in conn_b.execute(f"PRAGMA index_list({tabla})").fetchall()
            )
            self.assertEqual(idx_a, idx_b, msg=f"index_list differs for {tabla}")

            for nombre_idx, _ in idx_a:
                cols_a = [tuple(r) for r in conn_a.execute(f"PRAGMA index_info({nombre_idx})").fetchall()]
                cols_b = [tuple(r) for r in conn_b.execute(f"PRAGMA index_info({nombre_idx})").fetchall()]
                self.assertEqual(cols_a, cols_b, msg=f"index_info differs for {nombre_idx}")

            fk_a = [tuple(r) for r in conn_a.execute(f"PRAGMA foreign_key_list({tabla})").fetchall()]
            fk_b = [tuple(r) for r in conn_b.execute(f"PRAGMA foreign_key_list({tabla})").fetchall()]
            self.assertEqual(fk_a, fk_b, msg=f"foreign_key_list differs for {tabla}")

        versiones_a = [r["version"] for r in conn_a.execute("SELECT version FROM schema_version ORDER BY version")]
        versiones_b = [r["version"] for r in conn_b.execute("SELECT version FROM schema_version ORDER BY version")]
        self.assertEqual(versiones_a, versiones_b)

    def test_migration_is_idempotent(self):
        conn = vida.get_connection(self.db_path)
        conn.close()
        conn2 = vida.get_connection(self.db_path)
        try:
            conn2.close()
            conn3 = vida.get_connection(self.db_path)
            try:
                self.assertEqual(vida._schema_version(conn3), 2)
                versiones = [
                    r["version"]
                    for r in conn3.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
                ]
                self.assertEqual(versiones, [1, 2])
            finally:
                conn3.close()
        except Exception:
            raise

    def test_failed_migration_rolls_back_completely(self):
        original = vida.MIGRATIONS[2]
        rota = original[:-1] + ("ESTO NO ES SQL VALIDO",)
        vida.MIGRATIONS[2] = rota
        try:
            with self.assertRaises(Exception):
                vida.get_connection(self.db_path)
        finally:
            vida.MIGRATIONS[2] = original

        check_conn = sqlite3.connect(self.db_path)
        check_conn.row_factory = sqlite3.Row
        try:
            version = check_conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM schema_version"
            ).fetchone()["v"]
            self.assertEqual(version, 1)
            nombres = {
                r["name"]
                for r in check_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for t in _V2_ONLY_TABLES:
                self.assertNotIn(t, nombres)
            columnas = {r["name"] for r in check_conn.execute("PRAGMA table_info(pendientes)").fetchall()}
            self.assertNotIn("dificultad", columnas)
        finally:
            check_conn.close()

    def test_missing_migration_definition_reports_json_error(self):
        original_target = vida.TARGET_SCHEMA_VERSION
        vida.TARGET_SCHEMA_VERSION = 3
        try:
            with self.assertRaises(vida.VidaError) as ctx:
                vida.get_connection(self.db_path)
            self.assertEqual(ctx.exception.codigo, "migracion_faltante")
        finally:
            vida.TARGET_SCHEMA_VERSION = original_target

    def test_fresh_db_never_runs_migrations(self):
        fresh_path = os.path.join(self.tmpdir.name, "fresh2.db")
        original_migrations = vida.MIGRATIONS
        vida.MIGRATIONS = {}
        try:
            conn = vida.get_connection(fresh_path)
            try:
                self.assertEqual(vida._schema_version(conn), 2)
            finally:
                conn.close()
        finally:
            vida.MIGRATIONS = original_migrations


# ---------------------------------------------------------------------------
# Schema constraint tests
# ---------------------------------------------------------------------------

class TestSchemaConstraints(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "vida.db")
        self.conn = vida.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_monto_cero_o_negativo_rejected(self):
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO gastos (monto, categoria) VALUES (?, ?)", (0, "comida")
            )
            self.conn.commit()

    def test_monto_negativo_rejected(self):
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute(
                    "INSERT INTO gastos (monto, categoria) VALUES (?, ?)", (-5, "comida")
                )

    def test_unique_fecha_ejercicio_serie_rejected(self):
        import sqlite3

        with self.conn:
            self.conn.execute(
                "INSERT INTO entrenamientos (fecha, ejercicio, serie, peso, repeticiones) "
                "VALUES ('2025-06-01', 'sentadilla', 1, 80, 8)"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute(
                    "INSERT INTO entrenamientos (fecha, ejercicio, serie, peso, repeticiones) "
                    "VALUES ('2025-06-01', 'sentadilla', 1, 82, 6)"
                )

    def test_invalid_estado_pendiente_rejected(self):
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute(
                    "INSERT INTO pendientes (titulo, estado) VALUES ('test', 'inventado')"
                )


# ---------------------------------------------------------------------------
# Contract tests — every subcommand emits parseable JSON with correct exit codes
# ---------------------------------------------------------------------------

class TestSubcommandContract(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "vida.db")
        self.env = dict(os.environ, VIDA_DB=self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, *args):
        result = subprocess.run(
            [sys.executable, VIDA_PY, *args],
            env=self.env,
            capture_output=True,
            text=True,
        )
        return result

    def _assert_json_ok(self, result, expect_ok=True, expect_exit=0):
        self.assertEqual(result.returncode, expect_exit, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ok"], expect_ok)
        return payload

    def test_gasto_add_and_report(self):
        result = self._run("gasto", "add", "--monto", "50", "--categoria", "comida")
        payload = self._assert_json_ok(result)
        self.assertEqual(payload["data"]["categoria"], "comida")

        hoy = date.today().strftime("%Y-%m")
        result = self._run("gasto", "report", "--mes", hoy)
        payload = self._assert_json_ok(result)
        self.assertEqual(payload["data"]["n_gastos"], 1)

    def test_gasto_add_invalid_monto_fails_cleanly(self):
        result = self._run("gasto", "add", "--monto", "-10", "--categoria", "comida")
        payload = self._assert_json_ok(result, expect_ok=False, expect_exit=1)
        self.assertEqual(payload["codigo"], "validacion")

    def test_gasto_categorias(self):
        self._run("gasto", "add", "--monto", "10", "--categoria", "transporte")
        result = self._run("gasto", "categorias")
        payload = self._assert_json_ok(result)
        self.assertTrue(any(c["categoria"] == "transporte" for c in payload["data"]["categorias"]))

    def test_gym_log_and_progress(self):
        result = self._run("gym", "log", "--ejercicio", "sentadilla", "--peso", "80", "--reps", "8")
        payload = self._assert_json_ok(result)
        self.assertEqual(payload["data"]["serie"], 1)

        result = self._run("gym", "log", "--ejercicio", "sentadilla", "--peso", "80", "--reps", "8")
        payload = self._assert_json_ok(result)
        self.assertEqual(payload["data"]["serie"], 2)

        result = self._run("gym", "progress", "--ejercicio", "sentadilla")
        payload = self._assert_json_ok(result)
        self.assertIsNotNone(payload["data"]["sugerencia"]["peso"])

    def test_gym_log_duplicate_serie_fails_cleanly(self):
        self._run(
            "gym", "log", "--ejercicio", "sentadilla", "--peso", "80", "--reps", "8", "--serie", "1"
        )
        result = self._run(
            "gym", "log", "--ejercicio", "sentadilla", "--peso", "82", "--reps", "6", "--serie", "1"
        )
        payload = self._assert_json_ok(result, expect_ok=False, expect_exit=1)
        self.assertEqual(payload["codigo"], "duplicado")

    def test_gym_resumen(self):
        self._run("gym", "log", "--ejercicio", "sentadilla", "--peso", "80", "--reps", "8")
        result = self._run("gym", "resumen")
        payload = self._assert_json_ok(result)
        self.assertEqual(len(payload["data"]["resumen"]), 1)

    def test_tarjeta_add_and_next(self):
        result = self._run(
            "tarjeta", "add", "--nombre", "BCP Visa", "--dia-corte", "15", "--dia-pago", "5"
        )
        payload = self._assert_json_ok(result)
        self.assertEqual(payload["data"]["nombre"], "BCP Visa")

        result = self._run("tarjeta", "next")
        payload = self._assert_json_ok(result)
        self.assertEqual(len(payload["data"]["tarjetas"]), 1)
        self.assertIn("dias_restantes", payload["data"]["tarjetas"][0])

    def test_tarjeta_add_duplicate_nombre_fails_cleanly(self):
        self._run("tarjeta", "add", "--nombre", "BCP Visa", "--dia-corte", "15", "--dia-pago", "5")
        result = self._run(
            "tarjeta", "add", "--nombre", "BCP Visa", "--dia-corte", "1", "--dia-pago", "10"
        )
        payload = self._assert_json_ok(result, expect_ok=False, expect_exit=1)
        self.assertEqual(payload["codigo"], "duplicado")

    def test_cumple_add_and_upcoming(self):
        result = self._run("cumple", "add", "--nombre", "Ana", "--mes", "1", "--dia", "3")
        self._assert_json_ok(result)

        result = self._run("cumple", "upcoming", "--dias", "366")
        payload = self._assert_json_ok(result)
        self.assertTrue(any(p["nombre"] == "Ana" for p in payload["data"]["proximos"]))

    def test_pendiente_add_today_done(self):
        hoy = date.today().isoformat()
        result = self._run("pendiente", "add", "--titulo", "Pagar luz", "--fecha", hoy)
        payload = self._assert_json_ok(result)
        pendiente_id = payload["data"]["id"]

        result = self._run("pendiente", "today")
        payload = self._assert_json_ok(result)
        self.assertTrue(any(p["titulo"] == "Pagar luz" for p in payload["data"]["pendientes"]))

        result = self._run("pendiente", "done", "--id", str(pendiente_id))
        payload = self._assert_json_ok(result)
        self.assertEqual(payload["data"]["estado"], "hecho")

    def test_pendiente_done_unknown_id_fails_cleanly(self):
        result = self._run("pendiente", "done", "--id", "9999")
        payload = self._assert_json_ok(result, expect_ok=False, expect_exit=1)
        self.assertEqual(payload["codigo"], "no_encontrado")

    def test_health(self):
        result = self._run("health")
        payload = self._assert_json_ok(result)
        self.assertTrue(payload["data"]["integrity_ok"])
        self.assertEqual(payload["data"]["schema_version"], 2)

    def test_health_incluye_tablas_rutina(self):
        result = self._run("health")
        payload = self._assert_json_ok(result)
        for tabla in ("rutina_bloques", "rutina_items", "rutina_completado"):
            self.assertIn(tabla, payload["data"]["conteos"])


if __name__ == "__main__":
    unittest.main()
