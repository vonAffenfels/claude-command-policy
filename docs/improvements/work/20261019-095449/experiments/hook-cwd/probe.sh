#!/usr/bin/env bash
# Runs one headless probe session in the CURRENT directory with the logging hook
# attached. Usage: probe.sh <scenario-label> [extra allowed tool...]
#   probe.sh B            -> launched directly inside a worktree
#   probe.sh A EnterWorktree -> launched in the main checkout, then enters the worktree
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
worktree=/home/speckmaier/Projekte/intern/claude-command-policy/.claude/worktrees/improvement-20261019-095449
label="$1"
shift
echo "=== scenario $label launched from $PWD" >>"$here/hook-input.log"

if [ "$label" = A ]; then
  steps="1) Bash: echo A1; pwd  2) Bash: cd /tmp  3) Bash: echo A3; pwd  4) EnterWorktree with path=$worktree  5) Bash: echo A5; pwd  6) Bash: cd /tmp  7) Bash: echo A7; pwd  8) Read file CLAUDE.md (relative path, limit 1)"
else
  steps="1) Bash: echo B1; pwd  2) Bash: cd /tmp  3) Bash: echo B3; pwd  4) Read file CLAUDE.md (relative path, limit 1)"
fi

claude -p --model haiku \
  --settings "$here/settings.json" \
  --allowedTools Bash Read "$@" \
  -- "This is a probe. Perform exactly these tool calls, one at a time, in order, then reply DONE. $steps"
