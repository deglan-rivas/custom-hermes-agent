# Hermes native cron jobs (Group 5 — design.md §13 step 7, spec §5)

Hermes' cron scheduler is registered **conversationally, in natural language, directly to the
bot** — there is no separate YAML/JSON job file for Hermes to read (confirmed in `explore.md`:
the gateway daemon ticks every 60s and natural-language schedule definition is a real, documented
feature — not a config file this repo ships). This file is a **runbook for the human operator**:
the literal Spanish messages to send the bot once, to register each job. It is not executed by
any script.

Prerequisite: `TZ=America/Lima` is set on the `hermes` service (D4, already in
`docker-compose.yml`) and the Telegram allowlist/`write_approval` are live (design §13 steps 1-4)
before registering any job — a cron job registered against an unauthenticated gateway is a job
registered against nobody.

All times below are Lima local time. Each message assumes the corresponding `vida.py` subcommand
already exists (Group 2) and that the agent reads only fields from its JSON output, never
computing its own numbers (same guardrail as every skill's **Nunca** block).

## 5.1 — Daily morning briefing (~7am)

> Todos los días a las 7:00 am (hora de Lima) corré `python3 /opt/data/bin/vida.py pendiente today`
> y `python3 /opt/data/bin/vida.py gym progress --ejercicio <el ejercicio de mi rutina de hoy según
> sobre-mi>`, y mandame un resumen breve por Telegram: mis pendientes de hoy con su prioridad, y mi
> objetivo de entrenamiento del día si tengo rutina asignada hoy. Nunca inventes pendientes ni
> pesos que no vengan del JSON de cada comando; si `pendiente today` viene vacío decime "sin
> pendientes hoy".

Satisfies spec §5 "Morning briefing delivered unprompted".

## 5.2 — Tarjeta due-date alert

> Todos los días corré `python3 /opt/data/bin/vida.py tarjeta next` y por cada resultado con
> `alertar: true`, mandame un Telegram con el nombre de la tarjeta, la fecha (`proximo_corte` o
> `proximo_pago`, la que corresponda) y `dias_restantes`. Si ninguna tarjeta tiene `alertar: true`,
> no mandes nada ese día.

Satisfies spec §5 "Tarjeta due-date alert" (threshold per card is `tarjetas.alerta_dias_antes`,
already resolved inside `tarjeta next`'s `alertar` field — the cron job does not recompute it).

## 5.3 — Birthday alert

> Todos los días corré `python3 /opt/data/bin/vida.py cumple upcoming --dias 7` y si hay
> resultados, mandame un Telegram con el nombre y `dias_restantes` de cada cumpleaños próximo. No
> uses un `--dias` distinto al que yo te pida — el lead time por defecto es 7 salvo que cambie mi
> preferencia en `sobre-mi`.

Satisfies spec §5 "Scheduled jobs" (birthday alert, configurable lead time — the `--dias` value is
the configurable part, adjustable by editing this registered job's wording, not by a code change).

## 5.4 — Weekly expense summary by category

> Todos los lunes a las 8:00 am corré `python3 /opt/data/bin/vida.py gasto report --desde <lunes de
> la semana pasada> --hasta <domingo de la semana pasada>` y mandame por Telegram el total y el
> desglose por categoría (`por_categoria`) tal cual viene en el JSON — no recalculés vos los
> totales ni conviertas moneda.

Satisfies spec §5 "Scheduled jobs" (weekly expense summary).

## 5.5 — Smoke test procedure (design §13 step 7)

Before trusting any job above at its real schedule:

1. Register a throwaway variant with a 2-minute interval, e.g.:
   > Cada 2 minutos corré `python3 /opt/data/bin/vida.py pendiente today` y mandame el resultado
   > por Telegram (esto es una prueba, borrá este job después de 2-3 avisos).
2. Confirm 2-3 firings arrive correctly (right data, right channel, right formatting).
3. Ask the bot to delete/cancel the throwaway job, then register the real job (5.1-5.4 above) at
   its intended schedule.
4. Do this for at least the 07:00 briefing (5.1) first — it is the one job with an explicit spec
   scenario (spec §5 "Morning briefing delivered unprompted").

This step is manual and requires a live Hermes gateway (Groups 1-3 already deployed, allowlist
live) — it cannot be exercised from a code review or a sandboxed checkout.
