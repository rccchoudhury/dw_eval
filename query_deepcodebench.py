#!/usr/bin/env python3
"""
Query DeepWiki for questions from deepcodebench.json.

This script is meant to be run by Claude Code, which has access to the
MCP deepwiki tools. It will iterate through the first 25 questions and
save the results to deepcodebench_results.json.
"""

import json
from pathlib import Path


def load_deepcodebench(filename="data/deep_code_bench/deepcodebench.json"):
    """Load deepcodebench questions from JSON."""
    with open(filename, 'r') as f:
        return json.load(f)


def save_results(results, filename="data/deep_code_bench/deepcodebench_results.json"):
    """Save results to JSON."""
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)


def extract_repo_name(repo_url):
    """Extract owner/repo from GitHub URL."""
    # e.g., "https://github.com/huggingface/transformers.git" -> "huggingface/transformers"
    if not repo_url:
        return None

    # Remove .git suffix
    repo_url = repo_url.replace('.git', '')

    # Extract owner/repo from URL
    parts = repo_url.rstrip('/').split('/')
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return None


def show_summary(questions, results_file="data/deep_code_bench/deepcodebench_results.json"):
    """Show summary of questions and results."""
    total = len(questions)

    # Try to load existing results
    completed = 0
    pending = total
    if Path(results_file).exists():
        with open(results_file, 'r') as f:
            results = json.load(f)
        completed = len([r for r in results if r.get('deepwiki_answer') is not None])
        pending = total - completed

    print("=" * 80)
    print("DEEPCODEBENCH QUERY SUMMARY")
    print("=" * 80)
    print(f"Total questions: {total}")
    print(f"Limit: first 25 questions")
    print(f"Completed: {completed}")
    print(f"Pending: {pending}")
    print()

    # Show first few questions
    print("First 5 questions:")
    for i, q in enumerate(questions[:5]):
        repo = extract_repo_name(q.get('metadata', {}).get('repo'))
        print(f"  [{i}] {repo} - {q['question'][:70]}...")

    if len(questions) > 5:
        print(f"  ... and {len(questions) - 5} more")
    print()


if __name__ == "__main__":
    # Load all questions
    all_questions = load_deepcodebench()

    # Take first 25
    questions = all_questions[:25]

    # Show summary
    show_summary(questions)

    print("Ready to query DeepWiki for these questions.")
    print("Claude will need to use the MCP deepwiki tools to query each question.")
