"""Experiment harness for the find-auto-allowed-command model comparison.

Modes:
  cases                 print each test case's authentic live-config deny reason
  filters <program>...  dump raw filter definitions for those allowedCommands entries
  score <file>          read a JSON list of {id, model, candidate} and report, for each,
                        whether the engine actually auto-allows the proposed candidate

Uses the REAL merged user+project config, so both the deny reasons handed to the
agents and the verdicts on their answers come from the live engine rather than
from a reimplementation of it.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "packages", "command-policy", "lib"))

from config_loader import load_config_from_environment
from reason_renderer import render

CASES_PATH = os.path.join(HERE, "cases.json")


def verdict(config, command):
    decision = config.decision_for(command)
    if decision.is_allow:
        return True, "allow"
    reason = decision.reason
    return False, render(reason) if not isinstance(reason, str) else reason


def print_cases(config):
    for case in json.load(open(CASES_PATH)):
        allowed, text = verdict(config, case["denied"])
        print(f"### {case['id']} ({case['tier']})")
        print(f"GOAL:   {case['goal']}")
        print(f"DENIED: {case['denied']}")
        print(f"ENGINE: {'ALLOW (unexpected!)' if allowed else text}")
        print()


def score(config, path):
    for row in json.load(open(path)):
        candidate = (row.get("candidate") or "").strip()
        if not candidate or candidate.upper() == "NONE":
            print(f"{row['id']:4} {row['model']:8} NONE-CLAIMED")
            continue
        allowed, text = verdict(config, candidate)
        print(f"{row['id']:4} {row['model']:8} {'AUTO-ALLOWED' if allowed else 'STILL-DENIED'}  {candidate}")
        if not allowed:
            print(f"                  -> {text}")


def main(argv):
    config = load_config_from_environment()

    if argv and argv[0] == "filters":
        for entry in config.allowed_commands:
            if entry.program in argv[1:]:
                print(f"{entry.program}: {entry.filters}")
        return 0

    if argv and argv[0] == "score":
        score(config, argv[1])
        return 0

    print_cases(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
