---
name: rutina-diaria
description: Registra y hace seguimiento de la rutina diaria del usuario (bloques e ítems recurrentes), marca lo hecho hoy y reporta adherencia. Se activa con frases como "ya me duché", "¿qué me falta hoy?", "mi rutina de la mañana es…", "¿cómo vengo con mi rutina?".
---

# rutina-diaria

## 1. Cuándo se activa

Setup (registrar una rutina nueva):

- "mi rutina de la mañana es ducharme, skincare y cortarme las uñas"
- "todos los días hago esto al despertar: agradecer, mentalizarme, visualizar un día bueno"

Diario (marcar ítems hechos):

- "ya me duché"
- "listo el skincare"
- "ya hice todo lo de asearme"
- (nota de voz transcrita) "terminé la rutina de la mañana"

Consulta:

- "¿qué me falta hoy?"
- "¿cómo vengo con mi rutina este mes?"
- "¿qué hice ayer?"

**Contraste con `agenda-personal`**: "recordame X" es un `pendiente` (evento puntual con fecha);
"todos los días hago X" es una `rutina` (bloque/ítem recurrente sin fecha propia). Si la frase no
deja claro cuál es, preguntá antes de elegir el comando.

## 2. Comando exacto

Consultar la rutina de hoy (correr SIEMPRE antes de marcar algo hecho):

```
python3 /opt/data/bin/vida.py rutina today
```

Marcar un ítem como hecho (requiere el `item_id` resuelto por `rutina today`):

```
python3 /opt/data/bin/vida.py rutina done --id 3
```

Registrar un bloque nuevo:

```
python3 /opt/data/bin/vida.py rutina bloque-add --nombre "asearme" --hora-objetivo 07:00 --orden 1
```

Registrar un ítem dentro de un bloque existente:

```
python3 /opt/data/bin/vida.py rutina item-add --bloque "asearme" --nombre "ducharme" --orden 1
```

Ver el historial de un día o rango:

```
python3 /opt/data/bin/vida.py rutina historial --fecha ayer
python3 /opt/data/bin/vida.py rutina historial --desde 2026-07-01 --hasta 2026-07-07
```

Ver estadísticas de cumplimiento:

```
python3 /opt/data/bin/vida.py rutina stats --desde 2026-07-01 --hasta 2026-07-31
```

## 3. Mapeo de lenguaje natural → flags

| Fragmento de la frase | Flag / comando |
|---|---|
| descripción de una rutina completa ("mi rutina de la mañana es…") | UN `bloque-add` con `--nombre` del bloque, seguido de UN `item-add` por cada ítem mencionado (mirroring `gym-tracker`'s "expandir 3x8 en tres llamadas" — cada ítem es su propia llamada, nunca se agrupan en una sola) |
| "a las 7" | `--hora-objetivo` (solo en `bloque-add`; no existe a nivel ítem) |
| orden en que el usuario menciona los ítems | `--orden` 1..N, en el mismo orden de la frase |
| "ya me duché", "listo el skincare" | primero `rutina today` para resolver el `item_id`, luego `rutina done --id <id resuelto>` |
| "ayer" | `--fecha ayer` (en `done`/`today`/`historial`) |
| "anteayer" | `--fecha anteayer` |
| "este mes" | `rutina stats --desde <1º del mes en ISO> --hasta <hoy en ISO>` |
| "¿qué hice ayer?" | `rutina historial --fecha ayer` |
| nota de voz | `--fuente voz` |

## 4. Cómo responder

- Después de `rutina today`: leé `resumen.pct` y, si el usuario pregunta qué le falta, listá solo
  los ítems con `hecho_hoy: false`, agrupados por bloque.
- Después de `rutina done`: confirmá `item` y `bloque` tal como vienen en `data`. Si `ya_estaba` es
  `true`, decí que ya estaba marcado hoy — no digas que lo acabás de anotar.
- Después de `rutina stats`: citá `pct` por bloque/ítem exactamente como viene en el JSON. Si `pct`
  es `null`, decí que todavía no hay suficiente historial en vez de reportar 0%.
- Después de `bloque-add`/`item-add`: repetí el bloque y la lista de ítems agregados para que un
  ítem mal escuchado se corrija en el mismo turno.

## 5. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
textual; no reintentes en silencio ni asumas que se guardó.

Nunca adivines un `item_id`: siempre corré `rutina today` primero y usá el `item_id` que devuelve.
Si hay dos ítems parecidos, preguntá cuál. Nunca calcules porcentajes de cumplimiento ni rachas
por tu cuenta — vienen calculados en `rutina stats`.
