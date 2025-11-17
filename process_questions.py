#!/usr/bin/env python3
"""
Process questions from input JSON using deepwiki MCP service.
This script will be called iteratively to process one question at a time.
"""
import json
import sys
from pathlib import Path

def main():
    input_file = Path("/home/rchoudhu/deepwiki_eval/data/questions_with_facts/prs_raw_test_cases.json")
    output_file = Path("/home/rchoudhu/deepwiki_eval/data/questions_with_facts/prs_raw_test_cases_with_answers.json")

    # Load the data
    with open(input_file, 'r') as f:
        data = json.load(f)

    # Load existing output if it exists
    if output_file.exists():
        with open(output_file, 'r') as f:
            output_data = json.load(f)
    else:
        output_data = data.copy()

    # Find first unanswered question
    for i, item in enumerate(output_data):
        if item.get('deepwiki_answer') is None or item.get('deepwiki_answer') == "null":
            print(f"Next question to answer: Index {i}")
            print(f"Question ID: {item['id']}")
            print(f"Repo: {item['repo']}")
            print(f"Question: {item['question']}")
            print(f"\nWaiting for answer in: /tmp/deepwiki_answer_{i}.txt")

            # Check if answer file exists
            answer_file = Path(f"/tmp/deepwiki_answer_{i}.txt")
            if answer_file.exists():
                with open(answer_file, 'r') as f:
                    answer = f.read().strip()
                output_data[i]['deepwiki_answer'] = answer
                output_data[i]['status'] = 'completed'

                # Save output
                with open(output_file, 'w') as f:
                    json.dump(output_data, f, indent=2)

                # Remove answer file
                answer_file.unlink()
                print(f"✓ Saved answer for question {i}")

                # Report progress
                answered = sum(1 for item in output_data if item.get('deepwiki_answer') not in [None, "null", ""])
                print(f"\nProgress: {answered}/{len(output_data)} questions answered")

            sys.exit(0)

    print("All questions have been answered!")
    answered = sum(1 for item in output_data if item.get('deepwiki_answer') not in [None, "null", ""])
    print(f"Total: {answered}/{len(output_data)} questions answered")

if __name__ == "__main__":
    main()
