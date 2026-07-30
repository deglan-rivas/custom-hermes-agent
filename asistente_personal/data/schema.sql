-- vida.db schema — Hermes personal assistant (Fase 1)
-- Design ref: openspec/changes/hermes-personal-assistant/design.md §6
--
-- Applied idempotently by vida.py on first run (schema_version missing).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS gastos (
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

CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_cat_fecha ON gastos(categoria, fecha);

-- One row per SET, not per session.
CREATE TABLE IF NOT EXISTS entrenamientos (
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

CREATE INDEX IF NOT EXISTS idx_entren_ejercicio_fecha ON entrenamientos(ejercicio, fecha DESC);

CREATE TABLE IF NOT EXISTS tarjetas (
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

CREATE TABLE IF NOT EXISTS contactos (
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

CREATE TABLE IF NOT EXISTS pendientes (
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

CREATE INDEX IF NOT EXISTS idx_pend_estado_fecha ON pendientes(estado, fecha_objetivo);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    aplicado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
