#!/usr/bin/env python3
"""
Query DeepWiki for all pending test cases.

This script is meant to be run by Claude Code, which has access to the
MCP deepwiki tools. It will iterate through pending test cases and
save the results to test_cases.json.
"""

import json
from pathlib import Path


def load_test_cases(filename="data/test_cases.json"):
    """Load test cases from JSON."""
    with open(filename, 'r') as f:
        return json.load(f)


def save_test_cases(test_cases, filename="data/test_cases.json"):
    """Save test cases to JSON."""
    with open(filename, 'w') as f:
        json.dump(test_cases, f, indent=2)


def get_pending_cases(test_cases):
    """Get all pending test cases."""
    return [(i, tc) for i, tc in enumerate(test_cases) if tc['status'] == 'pending']


def mark_completed(test_cases, index, deepwiki_answer):
    """Mark a test case as completed."""
    test_cases[index]['deepwiki_answer'] = deepwiki_answer
    test_cases[index]['status'] = 'completed'
    return test_cases


def mark_error(test_cases, index, error_message):
    """Mark a test case as error."""
    test_cases[index]['deepwiki_answer'] = None
    test_cases[index]['error'] = error_message
    test_cases[index]['status'] = 'error'
    return test_cases


def show_pending_summary(filename="data/test_cases.json"):
    """Show summary of pending test cases."""
    test_cases = load_test_cases(filename)
    pending = get_pending_cases(test_cases)

    total = len(test_cases)
    completed = sum(1 for tc in test_cases if tc['status'] == 'completed')
    error = sum(1 for tc in test_cases if tc['status'] == 'error')

    print("=" * 80)
    print("TEST CASES SUMMARY")
    print("=" * 80)
    print(f"Total: {total}")
    print(f"Completed: {completed}")
    print(f"Pending: {len(pending)}")
    print(f"Error: {error}")
    print()

    if pending:
        print(f"Pending test cases to query:")
        for idx, tc in pending[:5]:  # Show first 5
            print(f"  [{idx}] {tc['repo']} - {tc['question'][:60]}...")
        if len(pending) > 5:
            print(f"  ... and {len(pending) - 5} more")

    return test_cases, pending


if __name__ == "__main__":
    show_pending_summary()
    print("\nTo query all pending cases, have Claude run:")
    print("  python3 query_deepwiki.py --query-all")
