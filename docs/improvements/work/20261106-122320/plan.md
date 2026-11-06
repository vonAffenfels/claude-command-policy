# Improvement 20261106-122320: Scratchpad as allowed path prefix

## Meta

- Related Ticket: PHPT-582
- Status: planned
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T12:23:26+01:00
- Merge target: main

## This Improvement's Objective

command-policy recognises the session's scratchpad directory deterministically and treats paths inside it as within the allowed prefixes — effectively the same as if the command ran inside the repository.
