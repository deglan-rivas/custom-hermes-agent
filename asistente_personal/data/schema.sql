-- vida.db schema — Hermes personal assistant
-- Design ref: openspec/changes/hermes-personal-assistant/design.md §6,
--             openspec/changes/daily-routine-tracker/design.md §3 (v2 additions),
--             openspec/changes/pendientes-lifecycle/design.md §3 (v3 additions)
--
-- This file is the bootstrap for a FRESH database only. It must stay
-- schema-equivalent to a version-1 database migrated through every block in
-- vida.py's MIGRATIONS (D-0.4) -- enforced by
-- test_fresh_bootstrap_and_migrated_v1_have_identical_schema in
-- asistente_personal/tests/test_vida.py. An existing database is brought up
-- to date by vida.py's versioned migration runner (_aplicar_migraciones),
-- not by this file.

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
    fuente          TEXT    NOT NULL DEFAULT 'telegram' CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
    dificultad      TEXT    CHECK (dificultad IS NULL OR dificultad IN ('facil', 'media', 'dificil'))
);

CREATE INDEX IF NOT EXISTS idx_pend_estado_fecha ON pendientes(estado, fecha_objetivo);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    aplicado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- rutina_* (daily-routine-tracker, schema_version 2) ------------------------

CREATE TABLE IF NOT EXISTS rutina_bloques (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT    NOT NULL UNIQUE,
    hora_objetivo  TEXT,
    orden          INTEGER NOT NULL DEFAULT 0,
    activo         INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente         TEXT    NOT NULL DEFAULT 'telegram'
                           CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron'))
);

CREATE TABLE IF NOT EXISTS rutina_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bloque_id  INTEGER NOT NULL REFERENCES rutina_bloques(id) ON DELETE RESTRICT,
    nombre     TEXT    NOT NULL,
    orden      INTEGER NOT NULL DEFAULT 0,
    activo     INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente     TEXT    NOT NULL DEFAULT 'telegram'
                       CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
    UNIQUE (bloque_id, nombre)
);

CREATE TABLE IF NOT EXISTS rutina_completado (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES rutina_items(id) ON DELETE RESTRICT,
    fecha      TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    creado_en  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente     TEXT    NOT NULL DEFAULT 'telegram'
                       CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
    UNIQUE (item_id, fecha)
);

CREATE INDEX IF NOT EXISTS idx_rutina_items_bloque ON rutina_items(bloque_id, orden);
CREATE INDEX IF NOT EXISTS idx_rutina_compl_fecha ON rutina_completado(fecha);
CREATE INDEX IF NOT EXISTS idx_rutina_compl_item_fecha ON rutina_completado(item_id, fecha);

-- pendientes_completado (pendientes-lifecycle, schema_version 3) -----------

CREATE TABLE IF NOT EXISTS pendientes_completado (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pendiente_id  INTEGER NOT NULL REFERENCES pendientes(id) ON DELETE RESTRICT,
    fecha         TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    creado_en     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fuente        TEXT    NOT NULL DEFAULT 'telegram'
                          CHECK (fuente IN ('telegram', 'voz', 'cli', 'cron')),
    UNIQUE (pendiente_id, fecha)
);

CREATE INDEX IF NOT EXISTS idx_pend_compl_fecha ON pendientes_completado(fecha);
CREATE INDEX IF NOT EXISTS idx_pend_compl_pend_fecha ON pendientes_completado(pendiente_id, fecha);

INSERT OR IGNORE INTO schema_version (version) VALUES (1), (2), (3);
