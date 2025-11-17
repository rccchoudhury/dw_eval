#!/usr/bin/env python3
"""Test DeepWiki by comparing its answers to ground truth from the dataset."""

import random
from datasets import load_from_disk


def get_random_question():
    """Load dataset and return a random question with metadata."""
    dataset = load_from_disk("data/deep_code_bench")

    # Pick a random example
    idx = random.randint(0, len(dataset) - 1)
    example = dataset[idx]

    # Extract repo name from URL (remove https://github.com/ and .git)
    repo_url = example['metadata']['repo']
    repo = repo_url.replace('https://github.com/', '').replace('.git', '')

    return {
        'index': idx,
        'id': example['id'],
        'repo': repo,
        'commit': example['metadata']['commit'],
        'pr': example['metadata']['pr'],
        'question': example['question'],
        'answer': example['answer'],
        'facts': example['facts'],
        'metadata': example['metadata']
    }


def print_question_info(data):
    """Print formatted question information."""
    print("=" * 80)
    print(f"EXAMPLE #{data['index']} (ID: {data['id']})")
    print("=" * 80)
    print(f"\nRepo: {data['repo']}")
    print(f"Commit: {data['commit']}")
    print(f"PR: #{data['pr']}")
    print(f"Difficulty: {data['metadata']['difficulty']}")
    print(f"Type: {data['metadata']['type']}")
    print(f"Scope: {data['metadata']['scope']}")

    print(f"\n{'QUESTION':=^80}")
    print(data['question'])

    print(f"\n{'GROUND TRUTH ANSWER':=^80}")
    print(data['answer'])

    print(f"\n{'FACTS ({} total)'.format(len(data['facts'])):=^80}")
    for i, fact in enumerate(data['facts'], 1):
        print(f"{i}. {fact}")

    print("\n" + "=" * 80)
    return data


if __name__ == "__main__":
    random.seed()  # Use current time for randomness
    data = get_random_question()
    print_question_info(data)

    print(f"\n{'READY FOR DEEPWIKI':=^80}")
    print(f"Repo: {data['repo']}")
    print(f"Question: {data['question']}")
    print("=" * 80)
