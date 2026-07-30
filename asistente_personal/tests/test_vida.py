"""Unit + contract tests for vida.py (design ref: design.md §9 Testing Strategy).

stdlib `unittest` only, per project convention (no pytest dependency).
Run with: python3 -m unittest discover asistente_personal/tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(os.path.dirname(TESTS_DIR), "bin")
sys.path.insert(0, BIN_DIR)

import vida  # noqa: E402  (import after sys.path tweak, by design)

VIDA_PY = os.path.join(BIN_DIR, "vida.py")


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
        self.assertEqual(payload["data"]["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
