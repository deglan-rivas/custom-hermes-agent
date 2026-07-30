---
name: sobre-mi
description: Documento vivo con lo que es cierto sobre el usuario (rutina, vocabulario, preferencias). No ejecuta comandos — es contexto que las otras skills leen antes de actuar, y que el agente edita a sí mismo cuando aprende algo nuevo y estable.
---

# sobre-mi

Este archivo no dispara acciones. Es la fuente de verdad sobre **quién es el usuario y cómo
prefiere que le hablen** — el complemento de `vida.db`, que guarda **qué pasó**. La regla que
separa a los dos:

> Lo estable y duradero va acá. Lo puntual o de una sola vez va en `vida.db` a través de la
> skill correspondiente (`registrar-gasto`, `gym-tracker`, `tarjetas`, `agenda-personal`).

## 1. Rutina

_(seed — completar a medida que el agente aprende la rutina real del usuario)_

- Días de entrenamiento: sin confirmar todavía.
- Split de gym: sin confirmar todavía (ej. "empuje/tracción/pierna", "torso/pierna", full body).
- Horario habitual de mensajes / zona horaria: `America/Lima`.

## 2. Vocabulario canónico de categorías de gasto

Usar SIEMPRE una de estas categorías antes de crear una nueva (correr
`vida.py gasto categorias` para ver el uso real). Lista inicial, ampliar con moderación:

- `comida`
- `transporte`
- `super`
- `servicios` (luz, agua, internet, streaming)
- `salud`
- `entretenimiento`
- `ropa`
- `otros`

## 3. Moneda y formato

- Moneda por defecto cuando no se especifica: `PEN` (soles).
- Formato de fecha en respuestas: día + fecha relativa cuando aplica (ej. "el viernes 15, en 3
  días"), nunca solo un número de día ambiguo.

## 4. Alias de ejercicios

_(seed — completar con los alias que use el usuario)_

| Alias que puede decir el usuario | Nombre canónico en `vida.db` |
|---|---|
| "sentadilla", "squat" | `sentadilla` |
| "peso muerto", "deadlift" | `peso muerto` |
| "press banca", "bench" | `press banca` |
| "prensa", "leg press" | `prensa` |
| "hip thrust", "empuje de cadera" | `hip thrust` |

## 5. Tiempos de alerta por defecto

- Tarjetas: avisar 3 días antes del corte/pago (ajustable por tarjeta vía `--alerta-dias`).
- Cumpleaños: avisar 7 días antes (ajustable por contacto vía `--alerta-dias`).

## 6. Tono de conversación

_(seed — completar cuando el usuario exprese una preferencia de tono explícita: formal/informal,
uso de emojis, nivel de detalle en las respuestas, etc.)_

- Sin preferencia registrada todavía. Default: directo, sin rodeos, en español rioplatense/neutro
  según cómo escriba el usuario.

## 7. Protocolo de auto-actualización

Cuando el agente aprende un hecho **nuevo y estable** sobre el usuario en una conversación
(ej. "en realidad entreno torso/pierna, no full body", "siempre pago con la tarjeta BCP", "no me
digas 'genial', preferís que sea más directo"):

1. Editar esta sección correspondiente de `sobre-mi/SKILL.md` vía `skill_manage`.
2. Como `write_approval: true` está activo, la edición queda en `~/.hermes/pending/skills/`
   esperando aprobación explícita — no asumir que el cambio ya está vigente hasta que se apruebe.
3. Un hecho volátil o de una sola vez (un gasto puntual, una serie de gym, un pendiente con
   fecha) **NO** va acá — va en `vida.db` vía la skill correspondiente.
4. No sobreescribir secciones enteras sin necesidad — editar de forma incremental, preservando lo
   ya confirmado.

## 8. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
textual; no reintentes en silencio ni asumas que se guardó.
