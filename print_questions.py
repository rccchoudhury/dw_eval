#!/usr/bin/env python3
"""Iterate over the deep_code_bench dataset and print question information."""

from datasets import load_from_disk

def print_questions():
    """Load and print question information from the dataset."""
    # Load the dataset from local directory
    dataset = load_from_disk("data/deep_code_bench")

    print(f"Total examples: {len(dataset)}\n")
    print("=" * 80)

    # Iterate over each example
    for idx, example in enumerate(dataset):
        if idx > 2: break

        print(f"\n[Example {idx + 1}/{len(dataset)}]")
        print(f"ID: {example['id']}")
        print(f"Question: {example['question']}")
        print(f"\nAnswer: {example['answer']}")
        print(f"\nFacts ({len(example['facts'])} total):")
        for i, fact in enumerate(example['facts'], 1):
            print(f"  {i}. {fact}")
        print(f"\nMetadata:")
        print(f"  - Repo: {example['metadata']['repo']}")
        #print(f"  - PR: {example['metadata']['pr']}")
        print(f"  - Commit: {example['metadata']['commit']}")
        print(f"  - Difficulty: {example['metadata']['difficulty']}")
        print(f"  - Type: {example['metadata']['type']}")
        print(f"  - Scope: {example['metadata']['scope']}")
        print(f"  - Includes code: {example['metadata']['includes_code']}")
        print(f"  - Context files: {example['metadata']['n_context_files']}")
        print("=" * 80)

if __name__ == "__main__":
    print_questions()
