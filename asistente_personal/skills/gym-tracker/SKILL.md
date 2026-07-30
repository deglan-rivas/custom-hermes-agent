---
name: gym-tracker
description: Registra series de entrenamiento y responde qué peso/reps le toca al usuario en cada ejercicio. Se activa con frases como "hice sentadilla 3x8 con 60", "levanté 80 en peso muerto", "¿cuánto me toca en press banca?", notas de voz describiendo series.
---

# gym-tracker

## 1. Cuándo se activa

- "hice sentadilla 3x8 con 60"
- "levanté 80 kilos en peso muerto, 5 repeticiones"
- "press banca: 3 series de 8 con 60, la última al fallo"
- (nota de voz transcrita) "acabo de hacer prensa, tres por diez con cien kilos"
- "¿cuánto me toca en sentadilla?"
- "¿qué peso uso hoy en press banca?"
- "resumen de mi entrenamiento de esta semana"

## 2. Comando exacto

Registrar UNA serie:

```
python3 /opt/data/bin/vida.py gym log --ejercicio "sentadilla" --peso 60 --reps 8
```

Registrar una serie específica con RPE y notas:

```
python3 /opt/data/bin/vida.py gym log --ejercicio "peso muerto" --peso 80 --reps 5 --serie 2 --rpe 8 --notas "buena tecnica"
```

Consultar progresión / qué peso toca hoy:

```
python3 /opt/data/bin/vida.py gym progress --ejercicio "sentadilla"
```

Resumen de volumen por ejercicio:

```
python3 /opt/data/bin/vida.py gym resumen --desde 2026-07-01 --hasta 2026-07-31
```

## 3. Mapeo de lenguaje natural → flags

| Fragmento de la frase | Flag |
|---|---|
| nombre del ejercicio ("sentadilla", "peso muerto", "press banca", "prensa", "hip thrust") | `--ejercicio` (normalizado a minúsculas; usar el vocabulario/alias de `sobre-mi` si el usuario usa un sinónimo) |
| "con 60", "60 kilos" | `--peso` |
| "8 repeticiones", "por 8" | `--reps` |
| "3x8x60" o "3 series de 8 con 60" | expandir a **tres** llamadas `gym log` separadas (una por serie), NO una sola fila. Cada llamada usa el mismo `--ejercicio`, `--peso`, `--reps`; dejar que `--serie` se auto-incremente (omitir el flag) salvo que el usuario indique una serie específica |
| "al fallo", "se sintió pesado", comentario cualitativo | `--notas` |
| "sensación de esfuerzo 8/10" o similar | `--rpe` (1-10) |
| "ayer", fecha explícita | `--fecha` (ISO, si no se menciona usa hoy) |
| nota de voz | `--fuente voz` |
| "¿cuánto me toca?", "qué peso uso" | `gym progress --ejercicio <nombre>` |
| "resumen de la semana/mes" | `gym resumen --desde ... --hasta ...` |

## 4. Cómo responder

- Después de cada `gym log`: confirmá `ejercicio`, `serie`, `peso` y `reps` tal como vienen en `data`. Si se expandieron varias series, confirmá el total ("Anoté 3 series de sentadilla: 8x60, 8x60, 8x60").
- Después de `gym progress`: leé `sugerencia.peso` y `sugerencia.razon` del JSON y decilos tal cual — nunca calcules vos el próximo peso.
  - Si `sugerencia.peso` es `null` (razon `"sin historial"`), preguntale al usuario con qué peso quiere arrancar; no inventes un valor de partida.
  - Si `sugerencia.razon` es `"progresion: sesion anterior completa"`, comunicá el aumento sugerido y por qué ("como completaste todas las series la vez pasada, subimos a X kg").
  - Si `sugerencia.razon` es `"repetir: sesion anterior incompleta"`, indicá que se repite el peso anterior.
- Después de `gym resumen`: leé `resumen[]` (volumen y sesiones por ejercicio) directamente; no sumes volúmenes vos mismo si el usuario pide un total — si hace falta, pedí que `vida.py` lo calcule (no existe un flag de total agregado; reportá por ejercicio).

## 5. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
textual; no reintentes en silencio ni asumas que se guardó.
