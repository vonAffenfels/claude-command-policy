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

if [ "${label#A}" != "$label" ]; then
  steps="1) Bash: echo A1; pwd  2) Bash: cd /tmp  3) Bash: echo A3; pwd  4) EnterWorktree with name=hook-cwd-probe (EnterWorktree and ExitWorktree are deferred tools: load them first with ToolSearch query select:EnterWorktree,ExitWorktree; if a call fails, reply with its exact error instead of DONE)  5) Bash: echo A5; pwd  6) Bash: cd /tmp  7) Bash: echo A7; pwd  8) Read file CLAUDE.md (relative path, limit 1)  9) ExitWorktree with action=remove"
else
  steps="1) Bash: echo B1; pwd  2) Bash: cd docs  3) Bash: echo B3; pwd  4) Read file CLAUDE.md (relative path, limit 1)"
fi

claude -p --model haiku --verbose --output-format stream-json \
  --settings "$here/settings.json" \
  --allowedTools Bash Read ToolSearch "$@" \
  -- "This is a probe. Perform exactly these tool calls, one at a time, in order, then reply DONE. $steps" \
  >"$here/transcript-$label.jsonl"
jq -r 'select(.type == "result") | .result' "$here/transcript-$label.jsonl"
