---
name: registrar-gasto
description: Registra gastos personales y responde preguntas sobre gastos ya registrados. Se activa con frases como "gasté 45 soles en almuerzo", "pagué 120 en el super", "compré...", "me cobraron...", "¿cuánto gasté en...?", "¿cuánto llevo gastado este mes?".
---

# registrar-gasto

## 1. Cuándo se activa

- "gasté 45 soles en almuerzo"
- "pagué 120 soles en el super con la tarjeta bcp"
- "me cobraron 25 dólares de netflix"
- "compré zapatillas por 250 soles, débito"
- (nota de voz transcrita) "gasté treinta y cinco soles en un uber"
- "¿cuánto gasté en comida este mes?"
- "¿cuánto llevo gastado en total en julio?"
- "dame las categorías de gastos que tengo"

## 2. Comando exacto

Registrar un gasto:

```
python3 /opt/data/bin/vida.py gasto add --monto 45 --categoria "comida" --descripcion "almuerzo" --metodo efectivo
```

Consultar gastos de un mes:

```
python3 /opt/data/bin/vida.py gasto report --mes 2026-07
```

Consultar gastos por rango de fechas y categoría:

```
python3 /opt/data/bin/vida.py gasto report --desde 2026-07-01 --hasta 2026-07-15 --categoria "comida"
```

Ver las categorías existentes (correr esto ANTES de elegir una categoría nueva):

```
python3 /opt/data/bin/vida.py gasto categorias
```

## 3. Mapeo de lenguaje natural → flags

| Fragmento de la frase | Flag |
|---|---|
| "45 soles", "120 dólares" | `--monto` (solo el número) + `--moneda` (`PEN` si "soles", `USD` si "dólares"/"dolares") |
| "en almuerzo", "en el super", "de netflix" | `--categoria` (usar una categoría existente de `gasto categorias`, no inventar una nueva casi-duplicada) |
| texto libre adicional describiendo el gasto | `--descripcion` |
| "con la tarjeta bcp", "débito", "efectivo", "yape", "plin", "transferencia" | `--metodo` (uno de: `efectivo`, `debito`, `credito`, `yape`, `plin`, `transferencia`) |
| "ayer", "el lunes", fecha explícita | `--fecha` (resolver a ISO `YYYY-MM-DD` antes de llamar; si no se menciona, `vida.py` usa hoy) |
| "con la tarjeta X" cuando el método es crédito | `--tarjeta` (id numérico de la tarjeta, resuelto vía la skill `tarjetas` si hace falta) |
| nota de voz | `--fuente voz` (si no se especifica, `vida.py` usa `cli`) |
| "¿cuánto gasté en julio?" | `gasto report --mes 2026-07` |
| "¿cuánto gasté en comida entre el 1 y el 15?" | `gasto report --desde ... --hasta ... --categoria comida` |

## 4. Cómo responder

- Después de `gasto add`: leé del `data` los campos `monto`, `moneda`, `categoria` y `fecha` devueltos por `vida.py`, y devolvéselos al usuario tal cual ("Anoté S/ 45.00 en comida (almuerzo), hoy"). Esto confirma que el parseo fue correcto.
- Si `--moneda` no fue mencionada, decilo explícitamente: "asumí soles (PEN)".
- Después de `gasto report`: leé `total`, `moneda`, `n_gastos` y `por_categoria` directamente del JSON. Nunca sumes ni calcules porcentajes vos mismo — si el usuario pide un desglose, listá `por_categoria` tal cual viene.
- Si `moneda` es `null` en la respuesta (multi-moneda), leé el desglose por moneda de `total` (es un objeto, no un número) y reportalo separado por moneda.

## 5. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá.
Nunca escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error`
textual; no reintentes en silencio ni asumas que se guardó.
