#!/usr/bin/env python3
"""
Helper script to run DeepWiki evaluation.

This script manages the test case file and provides utilities for
tracking progress during evaluation.
"""

import json
from pathlib import Path
from datetime import datetime


def load_test_cases(filename="data/test_cases.json"):
    """Load test cases from JSON."""
    with open(filename, 'r') as f:
        return json.load(f)


def save_test_cases(test_cases, filename="data/test_cases.json"):
    """Save test cases to JSON."""
    with open(filename, 'w') as f:
        json.dump(test_cases, f, indent=2)


def get_next_pending(test_cases):
    """Get the next pending test case."""
    for i, tc in enumerate(test_cases):
        if tc['status'] == 'pending':
            return i, tc
    return None, None


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


def get_progress_stats(test_cases):
    """Get progress statistics."""
    total = len(test_cases)
    pending = sum(1 for tc in test_cases if tc['status'] == 'pending')
    completed = sum(1 for tc in test_cases if tc['status'] == 'completed')
    error = sum(1 for tc in test_cases if tc['status'] == 'error')

    return {
        'total': total,
        'pending': pending,
        'completed': completed,
        'error': error,
        'progress_pct': (completed + error) / total * 100 if total > 0 else 0
    }


def show_next_case(filename="data/test_cases.json"):
    """Show the next pending test case for evaluation."""
    test_cases = load_test_cases(filename)
    idx, tc = get_next_pending(test_cases)

    if tc is None:
        print("No pending test cases!")
        stats = get_progress_stats(test_cases)
        print(f"\nProgress: {stats['completed']}/{stats['total']} completed, "
              f"{stats['error']} errors")
        return None

    stats = get_progress_stats(test_cases)

    print("=" * 80)
    print(f"TEST CASE #{idx} ({stats['completed']+1}/{stats['total']}) "
          f"[{stats['progress_pct']:.1f}% complete]")
    print("=" * 80)
    print(f"ID: {tc['id']}")
    print(f"Repo: {tc['repo']}")
    print(f"Difficulty: {tc['metadata']['difficulty']} | "
          f"Type: {tc['metadata']['type']} | "
          f"Scope: {tc['metadata']['scope']}")
    print(f"\nQUESTION:")
    print(tc['question'])
    print("\n" + "=" * 80)
    print(f"\nTo answer this question, use:")
    print(f"  Repo: {tc['repo']}")
    print(f"  Question: {tc['question']}")
    print("\n" + "=" * 80)

    return idx


def record_answer(index, answer, filename="data/test_cases.json"):
    """Record a DeepWiki answer for a test case."""
    test_cases = load_test_cases(filename)

    if index < 0 or index >= len(test_cases):
        print(f"Error: Invalid index {index}")
        return

    test_cases = mark_completed(test_cases, index, answer)
    save_test_cases(test_cases, filename)

    stats = get_progress_stats(test_cases)
    print(f"✓ Recorded answer for test case #{index}")
    print(f"Progress: {stats['completed']}/{stats['total']} completed "
          f"({stats['progress_pct']:.1f}%)")


def record_error(index, error_msg, filename="data/test_cases.json"):
    """Record an error for a test case."""
    test_cases = load_test_cases(filename)

    if index < 0 or index >= len(test_cases):
        print(f"Error: Invalid index {index}")
        return

    test_cases = mark_error(test_cases, index, error_msg)
    save_test_cases(test_cases, filename)

    stats = get_progress_stats(test_cases)
    print(f"✗ Recorded error for test case #{index}")
    print(f"Progress: {stats['completed']}/{stats['total']} completed "
          f"({stats['progress_pct']:.1f}%)")


def show_progress(filename="data/test_cases.json"):
    """Show overall progress."""
    test_cases = load_test_cases(filename)
    stats = get_progress_stats(test_cases)

    print("=" * 80)
    print("EVALUATION PROGRESS")
    print("=" * 80)
    print(f"Total test cases: {stats['total']}")
    print(f"Completed: {stats['completed']} ({stats['completed']/stats['total']*100:.1f}%)")
    print(f"Pending: {stats['pending']} ({stats['pending']/stats['total']*100:.1f}%)")
    print(f"Errors: {stats['error']} ({stats['error']/stats['total']*100:.1f}%)")
    print(f"\nOverall progress: {stats['progress_pct']:.1f}%")
    print("=" * 80)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python run_evaluation.py next             - Show next pending test case")
        print("  python run_evaluation.py progress         - Show progress")
        sys.exit(1)

    command = sys.argv[1]

    if command == "next":
        show_next_case()
    elif command == "progress":
        show_progress()
    else:
        print(f"Unknown command: {command}")
