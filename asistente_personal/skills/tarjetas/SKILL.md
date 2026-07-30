---
name: tarjetas
description: Registra tarjetas de crédito y reporta próximas fechas de corte/pago y gasto del ciclo actual. Se activa con frases como "agregá la tarjeta BCP", "¿cuándo me cortan la tarjeta?", "¿cuánto debo este mes?", "¿cuándo tengo que pagar la tarjeta?".
---

# tarjetas

## 1. Cuándo se activa

- "agregá la tarjeta BCP, corte el 15, pago el 5"
- "registrá mi tarjeta Interbank, corta el día 20 y pago el día 10"
- "¿cuándo me cortan la tarjeta?"
- "¿cuánto debo este mes en la BCP?"
- "¿cuándo tengo que pagar?"
- "¿qué tarjetas tengo que se vencen pronto?"

## 2. Comando exacto

Registrar una tarjeta:

```
python3 /opt/data/bin/vida.py tarjeta add --nombre "BCP" --dia-corte 15 --dia-pago 5 --banco "BCP" --moneda PEN
```

Consultar próximos cortes/pagos de todas las tarjetas:

```
python3 /opt/data/bin/vida.py tarjeta next
```

Consultar una tarjeta específica, o limitar la ventana de días:

```
python3 /opt/data/bin/vida.py tarjeta next --nombre "BCP" --dias 10
```

## 3. Mapeo de lenguaje natural → flags

| Fragmento de la frase | Flag |
|---|---|
| "la tarjeta BCP", "mi tarjeta Interbank" | `--nombre` |
| "corte el 15", "corta el día 20" | `--dia-corte` (día del mes, 1-31) |
| "pago el 5", "pago el día 10" | `--dia-pago` (día del mes, 1-31) |
| "del BCP", "Interbank" (como banco) | `--banco` |
| "en dólares" / default soles | `--moneda` (`USD` o `PEN`, default `PEN`) |
| "línea de 5000" | `--linea` |
| "avisame 3 días antes" | `--alerta-dias` (default 3 si no se especifica) |
| "¿cuándo me cortan?", "¿cuánto debo?" | `tarjeta next` (sin `--nombre` si es sobre todas) |
| "en los próximos 5 días" | `tarjeta next --dias 5` |

**Importante**: si el usuario da solo el día de corte o solo el día de pago, PREGUNTAR por el que falta antes de llamar `tarjeta add` — ambos son requeridos por `vida.py` y no deben adivinarse.

## 4. Cómo responder

- Después de `tarjeta add`: confirmá `nombre`, `dia_corte` y `dia_pago` tal como fueron guardados.
- Después de `tarjeta next`: por cada tarjeta en `data.tarjetas`, reportá la fecha ISO resuelta **y** `dias_restantes` juntos — nunca solo el día del mes, porque "el 15" es ambiguo y "el viernes 15 (en 3 días)" no lo es. Ejemplo: "BCP: próximo corte el {proximo_corte} (en {dias_restantes} días), próximo pago el {proximo_pago}".
- Si `alertar` es `true` para alguna tarjeta, destacalo como urgente en la respuesta.
- Reportá `gasto_ciclo_actual` cuando el usuario pregunte "¿cuánto debo?" — es el gasto acumulado en crédito del ciclo actual, léelo tal cual del JSON.

## 5. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
textual; no reintentes en silencio ni asumas que se guardó.
