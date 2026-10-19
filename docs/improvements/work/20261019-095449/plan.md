# Improvement 20261019-095449: Resolve project config to the main worktree

## Meta

- Related Ticket: None
- Status: planned
- Created: 2026-10-19
- Updated: 2026-10-19
- Plan started: 2026-10-19T09:55:20+02:00
- Merge target: main

## This Improvement's Objective

Inside a linked worktree (launched there directly or entered via EnterWorktree), every command-policy component that reads or writes the project-scope command-policy.json uses the MAIN worktree's file, so the effective policy is the same in both cases. Outside a repository, or in a layout the resolver does not recognise, the existing project-dir/.claude/command-policy.json behaviour is kept.
