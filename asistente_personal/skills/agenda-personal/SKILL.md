---
name: agenda-personal
description: Registra pendientes/recordatorios y cumpleaños, reporta lo que hay que hacer hoy y próximos cumpleaños. Se activa con frases como "recordame...", "¿qué tengo hoy?", "el cumple de X es el...", "ya lo hice".
---

# agenda-personal

## 1. Cuándo se activa

- "recordame llamar al banco mañana"
- "recordame pagar el alquiler el 5, todos los meses"
- "¿qué tengo pendiente hoy?"
- "¿qué se me vino venciendo?"
- "el cumple de Ana es el 15 de marzo"
- "¿quién cumple años pronto?"
- "ya lo hice" / "ya llamé al banco" / "listo, lo terminé"

## 2. Comando exacto

Agregar un pendiente:

```
python3 /opt/data/bin/vida.py pendiente add --titulo "llamar al banco" --fecha 2026-07-30 --prioridad media
```

Ver pendientes de hoy (incluye vencidos por default):

```
python3 /opt/data/bin/vida.py pendiente today
```

Marcar un pendiente como hecho (requiere el id resuelto primero):

```
python3 /opt/data/bin/vida.py pendiente done --id 12
```

Si el pendiente es recurrente (`recurrencia` no nula), marcarlo hecho NO lo cierra para
siempre: reaparece en `pendiente today` en su próxima ocurrencia (mañana si es `diaria`, el
próximo día de la semana si es `semanal:X`, etc.). Solo desaparece hasta ese día.

Editar un pendiente existente (requiere el id resuelto primero — NUNCA lo adivines, resolvelo
con `pendiente today` o `pendiente historial` antes de llamar `edit`):

```
python3 /opt/data/bin/vida.py pendiente edit --id 12 --fecha 2026-08-20 --prioridad alta
```

Campos editables: `--titulo`, `--detalle`, `--fecha`, `--hora`, `--prioridad`, `--dificultad`,
`--recurrencia`. Al menos uno es obligatorio. Pasar el flag con valor vacío (`--fecha ""`) borra
ese campo. No se puede editar un pendiente que ya está `hecho` o `cancelado` (falla con
`codigo: "pendiente_cerrado"`).

Agregar un cumpleaños:

```
python3 /opt/data/bin/vida.py cumple add --nombre "Ana" --mes 3 --dia 15 --relacion "hermana"
```

Ver próximos cumpleaños:

```
python3 /opt/data/bin/vida.py cumple upcoming --dias 30
```

## 3. Mapeo de lenguaje natural → flags

| Fragmento de la frase | Flag |
|---|---|
| "llamar al banco", "pagar el alquiler" | `--titulo` |
| "mañana", "el 5", "el próximo martes" | `--fecha` (resolver a ISO `YYYY-MM-DD` **antes** de la llamada; si no hay fecha mencionada, agregar SIN `--fecha` — un pendiente sin fecha es válido, no se descarta) |
| "a las 3pm" | `--hora` |
| "es urgente", "no es tan importante" | `--prioridad` (`alta`, `media` default, `baja`) |
| texto adicional describiendo el pendiente | `--detalle` |
| "todos los días" | `--recurrencia diaria` |
| "todos los lunes" | `--recurrencia semanal:lun` (códigos: lun, mar, mie, jue, vie, sab, dom) |
| "todos los 5 del mes" | `--recurrencia mensual:5` |
| "¿qué tengo hoy/pendiente?" | `pendiente today` |
| "ya lo hice" | primero `pendiente today` para resolver el `id` correcto por título, luego `pendiente done --id <id>` |
| "en realidad es para el viernes", "cambiale la prioridad" | primero `pendiente today` (o `historial`) para resolver el `id`, luego `pendiente edit --id <id> --fecha ...` |
| "el cumple de X es el DD de MES" | `cumple add --nombre X --mes <MES numérico> --dia DD` (agregar `--anio` solo si el usuario menciona el año de nacimiento) |
| "¿quién cumple pronto?", "en los próximos 60 días" | `cumple upcoming --dias 60` |

## 4. Cómo responder

- Después de `pendiente add`: confirmá `titulo` y `fecha_objetivo` (o decí explícitamente que quedó sin fecha si no se dio una).
- Después de `pendiente today`: listá cada item de `data.pendientes` con su `titulo`, `hora` (si tiene) y `prioridad`. Cada item trae `sin_fecha` (`true`/`false`); si `sin_fecha` es `true`, mencionalo como "sin fecha fija" en vez de omitirlo. No agregues pendientes que no estén en la lista.
- Para "ya lo hice" y para "editá el pendiente de...": SIEMPRE resolvé el `id` corriendo `pendiente today` (o `pendiente historial`, o preguntando cuál si hay ambigüedad) antes de llamar `pendiente done` o `pendiente edit` — nunca adivines un id.
- Después de `cumple add`: confirmá `nombre`, `cumple_mes` y `cumple_dia`.
- Después de `cumple upcoming`: por cada entrada en `data.proximos`, reportá `nombre`, `fecha_este_anio` y `dias_restantes` juntos. Si `edad_a_cumplir` no es `null`, incluí la edad que cumple.

## 5. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
textual; no reintentes en silencio ni asumas que se guardó.
