#!/usr/bin/env bash
# Verifies which git commands answer "main repository root" and "worktree root"
# across the layouts the resolver must handle. Builds everything in a temp dir.
# Usage: probe.sh <scratch-dir>
set -u
base="$1/git-commands-probe"
rm -rf "$base"
mkdir -p "$base"
cd "$base" || exit 1

git init -q main
git -C main commit -q --allow-empty -m init
mkdir -p main/sub/deeper
git -C main worktree add -q "$base/main/.claude/worktrees/linked" -b linked
mkdir -p main/.claude/worktrees/linked/sub
git -C main worktree add -q "$base/outside-linked" -b outside
git init -q main/vendor-sub-repo
mkdir -p not-a-repo

probe() {
  local label="$1" dir="$2"
  echo "== $label ($dir)"
  echo "   worktree list (first 'worktree' line):"
  git -C "$dir" worktree list --porcelain 2>&1 | grep -m1 '^worktree ' | sed 's/^/     /'
  echo "   exit=${PIPESTATUS[0]}"
  echo "   rev-parse --show-toplevel:"
  git -C "$dir" rev-parse --show-toplevel 2>&1 | sed 's/^/     /'
  echo "   exit=${PIPESTATUS[0]}"
}

probe "main root" main
probe "main subdir" main/sub/deeper
probe "linked worktree inside main/.claude" main/.claude/worktrees/linked
probe "linked worktree subdir" main/.claude/worktrees/linked/sub
probe "linked worktree outside main" outside-linked
probe "nested independent repo" main/vendor-sub-repo
probe "not a repo" not-a-repo
