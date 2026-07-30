# Asistente personal en labia03 (Hermes Agent + Telegram)

## Context

Quieres un asistente personal accesible desde el celular para registrar gastos, llevar la
progresión de pesos del gym, recibir recordatorios de actividades, avisos de pago de tarjetas
y alertas de cumpleaños. Debe partir de una documentación base pero irse actualizando solo.

Restricciones reales del entorno:

- Vive en **labia03** (servidor JNE, red interna, GPU 48GB), accesible solo por **Tailscale**.
- **Solo tienes ese servidor hasta enero 2027** → la portabilidad de los datos no es opcional,
  es requisito de diseño desde el día uno.
- Tienes suscripción de **opencode** con acceso a DeepSeek (atada al trabajo, probablemente
  muere junto con labia03).

Decisiones tomadas: Telegram como canal principal + CLI/Claude Code como segundo frente;
modelo híbrido (DeepSeek para razonar, GPU local para voz/embeddings); todo en Docker con
backup cifrado a la nube; datos estructurados en SQLite propia con skills a medida;
voz solo de entrada (Whisper local); puente a Claude Code en fase 2. Proactividad desde
fase 1: briefing diario, alertas financieras y cumpleaños.

---

## Respuestas directas a tus preguntas

**¿Exponer labia03 públicamente? No. No hace falta y no deberías.**
Un bot de Telegram funciona por *long polling*: el proceso hace peticiones HTTPS **salientes**
a `api.telegram.org`. No requiere ningún puerto de entrada, ni IP pública, ni túnel. La razón
por la que todas las guías dicen "usa un VPS" es que asumen que no tienes una máquina siempre
encendida — tú sí la tienes. Exponer una máquina de la red interna del JNE para esto sería
tomar un riesgo real (para ti y para la institución) a cambio de cero beneficio funcional.
Tailscale sigue siendo tu vía para el acceso SSH/CLI.
*(Nota: si hubieras elegido Slack, sí habría hecho falta Socket Mode o webhooks entrantes.
Es otra razón por la que Telegram es la elección correcta aquí.)*

**¿Mensajes de voz? Sí, y sale casi gratis.**
Telegram entrega las notas de voz como archivos OGG/Opus. Con tu GPU de 48GB, `faster-whisper`
(modelo `large-v3`) transcribe una nota de 15 segundos en bajo un segundo, en local, sin que
tus datos financieros salgan del servidor. Sin costo por uso.

**¿Retomar sesiones de Claude Code? Sí, en fase 2** — reusando `claude-remote/` y
`claude-simple/`, que ya resuelven el patrón de Claude Code containerizado en este repo.

**¿Migración en enero 2027?** Resuelta por diseño: todo el estado vive en **un solo volumen
Docker**. Migrar = `docker compose up` en la máquina nueva + restaurar el volumen. Ver la
sección de Portabilidad.

---

## Arquitectura

```
Celular (Telegram)                         labia03 (red interna JNE)
      │                                    ┌──────────────────────────────────┐
      │  long polling HTTPS saliente       │  docker compose                  │
      └────────► api.telegram.org ◄────────┤   ├─ hermes      (agente)        │
                                           │   ├─ whisper     (STT, GPU)      │
Laptop ──Tailscale SSH──────────────────►  │   └─ backup      (restic cron)   │
                                           │                                  │
                                           │  volumen: hermes-data            │
                                           │    ├─ .hermes/  (memoria, skills)│
                                           │    └─ data/vida.db (SQLite mía)  │
                                           └───────────────┬──────────────────┘
                                                           │ restic cifrado
                                                           ▼  (saliente)
                                                    Google Drive / S3
```

Sin puertos entrantes. Todo el tráfico es saliente.

## Componentes

**Hermes Agent** (Nous Research, MIT) — instala en `~/.hermes/`, persiste memoria, skills e
historial de sesión en SQLite con FTS5. Trae **cron scheduler integrado con entrega a
cualquier plataforma**, que es exactamente lo que cubre tus tres necesidades proactivas sin
código adicional. Skills = archivos `SKILL.md` con frontmatter YAML, con carga progresiva por
niveles; el agente puede crear y mejorar sus propias skills vía la herramienta `skill_manage`
(activar `write_approval` al inicio para revisar lo que se escribe a disco).

**Whisper local** — `faster-whisper` sobre la GPU, expuesto como servicio interno del compose.

**SQLite propia (`vida.db`)** — la pieza que hace que esto siga sirviendo a los 6 meses.
Tablas: `gastos`, `entrenamientos`, `tarjetas`, `contactos`, `pendientes`. La memoria nativa
de Hermes es para contexto blando ("prefiero entrenar en las mañanas"); los números viven aquí
para que "cuánto gasté en comida en junio" sea una consulta exacta y no una alucinación.

---

## Plan por fases

### Fase 0 — Verificaciones bloqueantes (hacer primero)

1. **¿opencode expone un endpoint OpenAI-compatible que Hermes pueda consumir?**
   Este es el mayor desconocido del plan. Hermes acepta "cualquier endpoint", pero la
   suscripción de opencode puede estar atada a su propio CLI y no ofrecer un base_url usable.
   Comprobar con un `curl` a un `/v1/chat/completions` antes de construir nada encima.
   - **Plan B** (y probablemente mejor a largo plazo): API key personal de DeepSeek u
     OpenRouter. Es barato para uso personal y *no muere en enero 2027*. Recomiendo dejar la
     config apuntando a una variable de entorno `LLM_BASE_URL` desde el inicio, de modo que
     cambiar de proveedor sea editar una línea del `.env`.
2. Confirmar acceso a la GPU desde contenedores (`nvidia-container-toolkit` instalado).
3. Crear el bot con **@BotFather** y anotar el token. Restringir el bot a **tu único user_id**
   de Telegram — un bot es público por defecto, cualquiera que sepa el nombre puede escribirle.
4. Elegir destino de backup (Google Drive personal o S3) y generar la passphrase de restic.

### Fase 1 — Asistente base funcionando (el objetivo)

**1. Contenedor de Hermes.** No existe imagen Docker oficial: hay que escribir un `Dockerfile`
propio sobre Debian/Ubuntu que ejecute el instalador oficial
(`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`) y fije `HERMES_HOME`
al volumen persistente. Configurar el proveedor (`hermes model`) y el gateway de Telegram
(`hermes gateway setup` / `hermes gateway start`) apuntando al token del `.env`.

**2. Esquema de `vida.db`** + un pequeño script CLI (`vida.py`, stdlib de Python, sin ORM) con
subcomandos: `gasto add/report`, `gym log/progress`, `tarjeta add/next`, `cumple add/upcoming`,
`pendiente add/today`. Que devuelva JSON — es lo que el agente consume mejor.

**3. Skills a medida** en `~/.hermes/skills/`, una por dominio, cada una un `SKILL.md` que le
enseña al agente cuándo y cómo llamar a `vida.py`:
- `registrar-gasto/` — parsea lenguaje natural ("45 soles en almuerzo") a una fila tipada.
- `gym-tracker/` — registra series y responde "cuánto me toca hoy" según la progresión previa.
- `tarjetas/` — fechas de corte y pago, cuánto debes.
- `agenda-personal/` — pendientes y cumpleaños.

**4. Voz.** Servicio `whisper` en el compose con acceso a GPU; hook en Hermes que intercepte
mensajes de voz de Telegram, los transcriba y los inyecte como texto al agente.

**5. Proactividad** vía el cron nativo de Hermes, definido en lenguaje natural:
- Briefing matutino (~7am): pendientes de hoy + entrenamiento del día con pesos objetivo.
- Alerta de tarjeta: N días antes de cada fecha de corte y de pago.
- Cumpleaños: aviso con anticipación configurable.
- Resumen semanal de gastos por categoría.

**6. Documentación base viva.** Un skill `sobre-mi/` con tus preferencias, rutina, categorías
de gasto y contexto personal. Es el "documento base que se actualiza": el agente puede
editarlo vía `skill_manage` conforme aprende de ti.

### Fase 2 — Puente a Claude Code (después de validar la fase 1)

Reusar los patrones de `claude-remote/` (Claude Code containerizado, devcontainer, nginx) y
`claude-simple/` (montaje SSHFS de directorios remotos) para exponer un skill de Hermes que
lance y retome sesiones de Claude Code por Telegram. Se hace después, para que un stack no
bloquee al otro.

---

## Portabilidad y backups (requisito de enero 2027)

**Un solo volumen.** `hermes-data` contiene `.hermes/` (memoria, skills, historial) y
`data/vida.db`. No hay estado fuera de ahí.

**Backup:** contenedor `restic` en cron diario → repositorio cifrado en Google Drive o S3 vía
rclone. Cifrado del lado del cliente: el proveedor de nube nunca ve tus gastos en claro.
Retención escalonada (7 diarios / 4 semanales / 12 mensuales).

**Prueba de restauración:** hacer una restauración real en tu laptop durante la fase 1, no en
enero 2027. Un backup no verificado no es un backup.

**Migración:** copiar `docker-compose.yml` + `.env` + restaurar el volumen desde restic, en un
VPS de ~5 USD/mes o en tu propia máquina. El `.env` con `LLM_BASE_URL` es lo que hace que
perder la suscripción de opencode sea un cambio de una línea y no una reescritura.

## Seguridad

- Cero puertos entrantes; labia03 no se expone.
- Whitelist del `user_id` de Telegram — sin esto, el bot le responde a cualquiera.
- Secretos en `.env` fuera de cualquier repo; `.gitignore` desde el primer commit.
- `write_approval` activado al inicio para revisar las skills que el agente se escribe solo.
- La transcripción de voz y los datos financieros nunca salen del servidor.

## Archivos a crear

```
asistente_personal/
├── docker-compose.yml          # hermes + whisper (GPU) + restic
├── Dockerfile                  # imagen propia: instalador oficial de Hermes
├── .env.template               # LLM_BASE_URL, LLM_API_KEY, TELEGRAM_TOKEN, TG_USER_ID, RESTIC_*
├── data/schema.sql             # esquema de vida.db
├── bin/vida.py                 # CLI de datos estructurados (salida JSON)
├── skills/{registrar-gasto,gym-tracker,tarjetas,agenda-personal,sobre-mi}/SKILL.md
├── backup/{backup.sh,restore.sh}
└── README.md
```

## Verificación

1. `docker compose up -d` y `docker compose logs -f hermes` → gateway conectado a Telegram.
2. Desde el celular: "gasté 45 soles en almuerzo" → responder y confirmar con
   `vida.py gasto report --mes actual` que la fila existe con categoría correcta.
3. Nota de **voz** con un registro de gym → verificar transcripción y fila en `entrenamientos`.
4. Preguntar "¿cuánto me toca en press banca hoy?" → debe responder desde la progresión real.
5. Programar un cron de prueba a 2 minutos → confirmar que llega el push a Telegram.
6. Ejecutar `backup.sh` y luego `restore.sh` **en la laptop**, levantar el compose ahí y
   comprobar que la memoria y `vida.db` están intactas. Este es el paso que valida enero 2027.
7. Desde un segundo usuario de Telegram, escribirle al bot → debe ignorarlo (whitelist).
```
