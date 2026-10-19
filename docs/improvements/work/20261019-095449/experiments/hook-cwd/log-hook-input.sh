#!/usr/bin/env bash
# Debug PreToolUse hook: records what a hook process sees, decides nothing.
log="$(dirname "$0")/hook-input.log"
{
  echo "--- process PWD=$PWD CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR:-<unset>}"
  cat
  echo
} >>"$log"
