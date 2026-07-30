# systemd timers — alternative to `ops/hermes-ops.cron` (D12)

Install **only one** of `ops/hermes-ops.cron` (primary, D12) or these
`.service`/`.timer` pairs — never both, per `design.md` §10.

`OnCalendar=` timers use the **host's local timezone**, not per-unit `TZ=`
(unlike the cron fragment's `CRON_TZ=America/Lima`). Set the host's system
timezone to `America/Lima` before enabling `hermes-db-snapshot.timer` /
`hermes-check-backup.timer`, or their fixed clock times will fire at the
wrong hour.

## Install

```sh
sudo cp asistente_personal/ops/systemd/hermes-*.service \
        asistente_personal/ops/systemd/hermes-*.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  hermes-check-stack.timer \
  hermes-skills-autocommit.timer \
  hermes-db-snapshot.timer \
  hermes-check-backup.timer
```

`hermes-db-snapshot.timer` has no restic dependency and can be enabled as
soon as `vida.db`/`state.db` exist. `hermes-check-backup.timer` is
`[BLOCKED: F0.5]` — enabling it before the `restic` service produces real
snapshots (task 7.9) will alert on every run.

Edit `WorkingDirectory=`/`ExecStart=` in each `.service` file if the
deployment path is not `/srv/asistente_personal`.
