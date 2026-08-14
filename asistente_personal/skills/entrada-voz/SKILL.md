---
name: entrada-voz
description: Transcribe notas de voz de Telegram a texto vía whisper y despacha el texto resultante al skill de dominio correspondiente (gasto, gym, tarjeta, agenda). Se activa automáticamente cuando el mensaje entrante es un adjunto de audio/nota de voz, no con una frase.
---

# entrada-voz

## 0. Decisión de diseño (F0.7, design.md §15)

`design.md` §15 dejaba dos alternativas abiertas para la integración de voz: un hook a nivel de
gateway que intercepta antes del matching de skills, o un skill que llama a
`/v1/audio/transcriptions` directamente — ambas terminan en el mismo contrato
`POST /v1/audio/transcriptions` contra `whisper:8000`. **Esta PR resuelve F0.7 eligiendo la
segunda opción: skill, no hook de gateway.**

Razón: el mecanismo de hook pre-mensaje de Hermes no está confirmado (F0.7 seguía abierto y
no-bloqueante por proposal.md), y construir sobre un hook de core sin verificar es exactamente el
riesgo que la degradación gradual busca evitar. El patrón de skill ya está probado por los otros
cinco skills de este proyecto — cada uno invoca un binario/script vía shell y lee el JSON de
vuelta — así que reusar ese patrón para llegar a `whisper` no agrega ninguna capacidad nueva de
Hermes, solo un script más. Si más adelante se confirma un hook nativo pre-mensaje, este skill se
puede reemplazar sin tocar el contrato HTTP que ya usa `ops/transcribe-voice.sh`.

## 1. Cuándo se activa

- Cualquier mensaje entrante de Telegram cuyo tipo sea nota de voz / adjunto de audio (no texto).
- No hay "frase disparadora": el disparador es el tipo de adjunto del mensaje, no su contenido.

## 2. Comando exacto

```
ops/transcribe-voice.sh <ruta-al-archivo-de-audio-descargado>
```

El archivo de audio ya debe estar descargado localmente (la ruta del adjunto que Hermes entrega
para ese mensaje). El script hace `POST` a
`${WHISPER_URL:-http://whisper:8000}/v1/audio/transcriptions` con `curl` y devuelve un único
objeto JSON, con el mismo formato de contrato que `vida.py`.

## 3. Mapeo de resultado → acción

| Campo del JSON de salida | Qué hacer |
|---|---|
| `ok: true`, `data.texto` | Tratar `data.texto` como si fuera el mensaje de texto original del usuario y correr el matching normal de skills (`registrar-gasto`, `gym-tracker`, `tarjetas`, `agenda-personal`) sobre ese texto — incluyendo `--fuente voz` cuando el skill de destino soporte ese flag (ver `gym-tracker` §3). |
| `ok: false`, `codigo: whisper_no_disponible` | GPU/whisper no disponible (degradación F0.2) o servicio caído. Responder: "no pude transcribir tu nota de voz (el servicio de voz no está disponible ahora) — ¿me la podés escribir?". Nunca reintentar en silencio. |
| `ok: false`, `codigo: transcripcion_vacia` | El audio no produjo texto reconocible. Pedir que repita el mensaje, en texto o en voz. |
| `ok: false`, otro `codigo` | Decir el `error` textual y pedir que escriba el mensaje. |

## 4. Cómo responder

- Nunca sigas adelante con una acción (`gasto add`, `gym log`, etc.) si `ok` es `false` para la
  transcripción — continuar sería indistinguible de inventar el contenido del mensaje.
- Si la transcripción tiene éxito, confirmá brevemente lo que entendiste antes de ejecutar la
  acción del skill de dominio ("entendí: 'hice sentadilla 3x8 con 60' — anoto eso"), así un error
  de transcripción se corrige antes de escribir en `vida.db`.

## 5. Nunca

Nunca calcules totales, promedios, fechas ni pesos objetivo por tu cuenta — corré el comando y
leé el campo. Nunca inventes un valor faltante: si falta `monto` o `ejercicio`, preguntá. Nunca
escribas en `vida.db` por otra vía que `vida.py`. Si `ok` es `false`, decí el `error` textual; no
reintentes en silencio ni asumas que se transcribió o se guardó.
