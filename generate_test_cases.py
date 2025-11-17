#!/usr/bin/env python3
"""Generate test cases for DeepWiki evaluation."""

import json
import random
from pathlib import Path
from datasets import load_from_disk


def generate_test_cases(num_cases=20, output_file="data/test_cases.json"):
    """Generate random test cases from the dataset."""
    dataset = load_from_disk("data/deep_code_bench")

    # Get random indices
    indices = random.sample(range(len(dataset)), min(num_cases, len(dataset)))

    test_cases = []
    for idx in indices:
        example = dataset[idx]

        # Extract repo name from URL
        repo_url = example['metadata']['repo']
        repo = repo_url.replace('https://github.com/', '').replace('.git', '')

        test_case = {
            'index': idx,
            'id': example['id'],
            'repo': repo,
            'commit': example['metadata']['commit'],
            'pr': example['metadata']['pr'],
            'question': example['question'],
            'ground_truth_answer': example['answer'],
            'facts': example['facts'],
            'metadata': {
                'difficulty': example['metadata']['difficulty'],
                'type': example['metadata']['type'],
                'scope': example['metadata']['scope'],
                'includes_code': example['metadata']['includes_code'],
                'n_context_files': example['metadata']['n_context_files']
            },
            'deepwiki_answer': None,  # To be filled in
            'status': 'pending'  # pending, completed, error
        }
        test_cases.append(test_case)

    # Save to JSON
    output_path = Path(output_file)
    with open(output_path, 'w') as f:
        json.dump(test_cases, f, indent=2)

    print(f"Generated {len(test_cases)} test cases")
    print(f"Saved to: {output_path.absolute()}")
    print(f"\nDifficulty breakdown:")
    for difficulty in ['easy', 'moderate', 'hard']:
        count = sum(1 for tc in test_cases if tc['metadata']['difficulty'] == difficulty)
        print(f"  {difficulty}: {count}")

    print(f"\nType breakdown:")
    for qtype in set(tc['metadata']['type'] for tc in test_cases):
        count = sum(1 for tc in test_cases if tc['metadata']['type'] == qtype)
        print(f"  {qtype}: {count}")

    return test_cases


if __name__ == "__main__":
    import sys
    num_cases = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    generate_test_cases(num_cases)
