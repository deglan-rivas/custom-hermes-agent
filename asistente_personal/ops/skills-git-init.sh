#!/bin/sh
# Group 8, tasks 8.1 + 8.3 (design.md §11, §13 step 4): bootstrap
# $HERMES_DATA/skills as a local, commit-only git repo seeded from the
# project's own asistente_personal/skills/ directory.
#
# Idempotent: safe to re-run. Never re-copies over an existing skill file
# (the agent owns skills/ after first boot via write_approval -- this
# script's job is the ONE-TIME seed, not an ongoing sync).
#
# Usage: ops/skills-git-init.sh
# Env: HERMES_DATA (defaults to ./state/hermes, same as docker-compose.yml D9)

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_DATA_DIR="${HERMES_DATA:-$COMPOSE_DIR/state/hermes}"
SKILLS_DIR="$HERMES_DATA_DIR/skills"
SEED_DIR="$COMPOSE_DIR/skills"

mkdir -p "$SKILLS_DIR"

# Seed: copy each seed skill dir + the shared .gitignore, without
# clobbering anything already present (the agent may have edited it since
# a previous run).
for entry in "$SEED_DIR"/*; do
  name="$(basename "$entry")"
  [ "$name" = ".gitkeep" ] && continue
  if [ -d "$entry" ]; then
    if [ ! -d "$SKILLS_DIR/$name" ]; then
      cp -R "$entry" "$SKILLS_DIR/$name"
      echo "skills-git-init.sh: seeded $name"
    fi
  elif [ -f "$entry" ]; then
    if [ ! -f "$SKILLS_DIR/$name" ]; then
      cp "$entry" "$SKILLS_DIR/$name"
    fi
  fi
done

# `.gitignore` is a dotfile -- the glob above does not match it in `sh`.
if [ -f "$SEED_DIR/.gitignore" ] && [ ! -f "$SKILLS_DIR/.gitignore" ]; then
  cp "$SEED_DIR/.gitignore" "$SKILLS_DIR/.gitignore"
  echo "skills-git-init.sh: seeded .gitignore"
fi

if [ ! -d "$SKILLS_DIR/.git" ]; then
  git -C "$SKILLS_DIR" init -q
  git -C "$SKILLS_DIR" config --local user.name "hermes-autocommit"
  git -C "$SKILLS_DIR" config --local user.email "hermes@labia03.local"
  echo "skills-git-init.sh: initialized git repo at $SKILLS_DIR (local-only, no remote)"
fi

if [ -n "$(git -C "$SKILLS_DIR" status --porcelain)" ]; then
  git -C "$SKILLS_DIR" add -A
  git -C "$SKILLS_DIR" commit -q -m "seed: initial skills snapshot $(date -Iseconds)"
  echo "skills-git-init.sh: committed initial snapshot"
else
  echo "skills-git-init.sh: nothing to commit, repo already up to date"
fi
