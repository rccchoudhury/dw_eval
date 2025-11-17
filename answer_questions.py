#!/usr/bin/env python3
"""
Process questions from input JSON using deepwiki MCP service.
Usage:
  - Get next question: python3 answer_questions.py next
  - Save answer: python3 answer_questions.py save <index> <answer_text>
"""
import json
import sys
from pathlib import Path

INPUT_FILE = Path("/home/rchoudhu/deepwiki_eval/data/questions_with_facts/prs_raw_test_cases.json")
OUTPUT_FILE = Path("/home/rchoudhu/deepwiki_eval/data/questions_with_facts/prs_raw_test_cases_with_answers.json")

def load_data():
    """Load data from output file if exists, otherwise from input file."""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r') as f:
            return json.load(f)
    else:
        with open(INPUT_FILE, 'r') as f:
            return json.load(f)

def save_data(data):
    """Save data to output file."""
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_next_question(data):
    """Find the first unanswered question."""
    for item in data:
        if not item.get('deepwiki_answer'):
            return item
    return None

def save_answer(data, index, answer):
    """Save answer for a specific question index."""
    if 0 <= index < len(data):
        data[index]['deepwiki_answer'] = answer
        data[index]['status'] = 'completed'
        save_data(data)
        return True
    return False

def get_progress(data):
    """Get answering progress."""
    total = len(data)
    answered = sum(1 for item in data if item.get('deepwiki_answer'))
    return answered, total

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Get next: python3 answer_questions.py next")
        print("  Save answer: python3 answer_questions.py save <index>")
        sys.exit(1)

    command = sys.argv[1]
    data = load_data()

    if command == "next":
        next_q = get_next_question(data)
        if next_q:
            print(json.dumps(next_q, indent=2))
        else:
            print("All questions answered!")
            answered, total = get_progress(data)
            print(f"Progress: {answered}/{total}")

    elif command == "save":
        if len(sys.argv) < 3:
            print("Error: Please provide question index")
            sys.exit(1)

        index = int(sys.argv[2])
        # Read answer from stdin
        answer = sys.stdin.read().strip()

        if save_answer(data, index, answer):
            answered, total = get_progress(data)
            print(f"✓ Saved answer for question {index}")
            print(f"Progress: {answered}/{total}")
        else:
            print(f"Error: Invalid index {index}")
            sys.exit(1)

    elif command == "progress":
        answered, total = get_progress(data)
        print(f"Progress: {answered}/{total} questions answered")
        remaining = [i for i, item in enumerate(data) if not item.get('deepwiki_answer')]
        if remaining:
            print(f"Remaining indices: {remaining[:10]}..." if len(remaining) > 10 else f"Remaining indices: {remaining}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
