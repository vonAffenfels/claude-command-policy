# Improvement 20261106-092940: Agent-initiated bypass-policy and add-allow-policy proposals

## Meta

- Related Ticket: None
- Status: planned
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T09:29:46+01:00
- Merge target: main

## This Improvement's Objective

Make sessions use bypass-policy on their own when no auto-allowed command fits (instead of asking the operator to run !command), and use add-allow-policy to propose durable rules — up front when a task will need many bypasses, or at session end when workarounds piled up (handed to the operator when the session is part of a wider process) — with guidance that produces correct rules.
