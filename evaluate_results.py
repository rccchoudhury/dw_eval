#!/usr/bin/env python3
"""Evaluate DeepWiki answers against ground truth using Claude API."""

import json
import os
import logging
from pathlib import Path
from collections import defaultdict
import anthropic

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_test_cases(input_file="data/test_cases.json"):
    """Load test cases from JSON file."""
    with open(input_file, 'r') as f:
        return json.load(f)


def load_evaluation_prompt(prompt_file="prompts/evaluation_prompt.txt"):
    """Load the evaluation prompt template from file."""
    try:
        with open(prompt_file, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: Prompt file '{prompt_file}' not found")
        raise


def evaluate_with_claude(question, deepwiki_answer, ground_truth, facts, prompt_template=None):
    """
    Use Claude API to evaluate if the DeepWiki answer is correct.
    Returns evaluation results with score and reasoning.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Load prompt template if not provided
    if prompt_template is None:
        prompt_template = load_evaluation_prompt()

    # Format facts as numbered list
    facts_text = "\n".join(f"{i+1}. {fact}" for i, fact in enumerate(facts))

    # Fill in the template
    prompt = prompt_template.format(
        question=question,
        ground_truth=ground_truth,
        facts=facts_text,
        deepwiki_answer=deepwiki_answer,
        total_facts=len(facts)
    )

    try:
        logger.debug(f"Sending evaluation request for question: {question[:50]}...")
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        if not message.content or not message.content[0].text:
            raise ValueError("Empty response from Claude API")

        response_text = message.content[0].text
        logger.debug(f"Received response (first 200 chars): {response_text[:200]}")

        # Try to extract JSON from response (might have markdown formatting)
        if "```json" in response_text:
            # Extract JSON from code block
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
            logger.debug("Extracted JSON from ```json code block")
        elif "```" in response_text:
            # Extract from generic code block
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
            logger.debug("Extracted JSON from generic code block")

        logger.debug(f"JSON to parse (first 200 chars): {response_text[:200]}")
        # Parse JSON response
        result = json.loads(response_text)
        logger.debug(f"Successfully parsed JSON: {result}")

        # Score is already 0-100 from Claude, normalize to 0-1 range
        result['score'] = result['score'] / 100.0

        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        logger.error(f"Failed to parse response: {response_text[:500]}")
        return {
            'score': 0,
            'status': 'error',
            'analysis': f'JSON parsing error: {str(e)}',
            'facts_covered': 0,
            'total_facts': len(facts)
        }
    except Exception as e:
        logger.error(f"Error calling Claude API: {e}", exc_info=True)
        logger.error(f"Question: {question[:100]}")
        logger.error(f"DeepWiki answer: {deepwiki_answer[:100] if deepwiki_answer else 'None'}")
        return {
            'score': 0,
            'status': 'error',
            'analysis': f'API error: {str(e)}',
            'facts_covered': 0,
            'total_facts': len(facts)
        }


def evaluate_answer(question, deepwiki_answer, ground_truth, facts):
    """
    Evaluate a single answer using Claude API.
    Returns a score and analysis.
    """
    if not deepwiki_answer:
        return {
            'score': 0,
            'status': 'no_answer',
            'analysis': 'No DeepWiki answer provided',
            'facts_covered': 0,
            'total_facts': len(facts)
        }

    return evaluate_with_claude(question, deepwiki_answer, ground_truth, facts)


def generate_report(test_cases, output_file="evaluation_report.txt", prompt_file="evaluation_prompt.txt"):
    """Generate a comprehensive evaluation report."""

    # Load prompt template once
    print(f"Loading evaluation prompt from {prompt_file}...")
    prompt_template = load_evaluation_prompt(prompt_file)

    # Evaluate all test cases
    evaluations = []
    total_cases = len(test_cases)

    print(f"Evaluating {total_cases} test cases using Claude API...")

    for i, tc in enumerate(test_cases, 1):
        print(f"  [{i}/{total_cases}] Evaluating case {tc['id'][:8]}...")
        logger.info(f"Processing test case {i}/{total_cases}: {tc['id'][:8]} (repo: {tc['repo']})")

        if tc['status'] != 'completed' or not tc.get('deepwiki_answer'):
            logger.warning(f"Skipping case {tc['id'][:8]}: status={tc['status']}, has_answer={bool(tc.get('deepwiki_answer'))}")
            eval_result = {
                'score': 0,
                'status': 'skipped',
                'analysis': f"Test case status: {tc['status']}",
                'facts_covered': 0,
                'total_facts': len(tc['facts'])
            }
        else:
            logger.info(f"Evaluating case {tc['id'][:8]} with {len(tc['facts'])} facts")
            eval_result = evaluate_with_claude(
                tc['question'],
                tc['deepwiki_answer'],
                tc['ground_truth_answer'],
                tc['facts'],
                prompt_template=prompt_template
            )
            logger.info(f"Case {tc['id'][:8]} result: status={eval_result.get('status')}, score={eval_result.get('score')}")

        evaluations.append({
            'test_case': tc,
            'evaluation': eval_result
        })

    # Calculate statistics
    completed = [e for e in evaluations if e['evaluation']['status'] not in ['skipped', 'no_answer', 'error']]

    if not completed:
        print("No completed test cases to evaluate!")
        return

    total_completed = len(completed)
    correct = sum(1 for e in completed if e['evaluation']['status'] == 'correct')
    partial = sum(1 for e in completed if e['evaluation']['status'] == 'partial')
    incorrect = sum(1 for e in completed if e['evaluation']['status'] == 'incorrect')

    avg_score = sum(e['evaluation']['score'] for e in completed) / total_completed
    avg_facts_covered = sum(e['evaluation']['facts_covered'] for e in completed) / total_completed

    # Breakdown by metadata
    by_difficulty = defaultdict(list)
    by_type = defaultdict(list)
    by_scope = defaultdict(list)
    by_repo = defaultdict(list)

    for e in completed:
        tc = e['test_case']
        status = e['evaluation']['status']

        by_difficulty[tc['metadata']['difficulty']].append(status)
        by_type[tc['metadata']['type']].append(status)
        by_scope[tc['metadata']['scope']].append(status)
        by_repo[tc['repo']].append(status)

    # Generate report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("DEEPWIKI EVALUATION REPORT (Claude API Evaluation)")
    report_lines.append("=" * 80)
    report_lines.append("")

    report_lines.append("OVERALL STATISTICS")
    report_lines.append("-" * 80)
    report_lines.append(f"Total test cases: {len(test_cases)}")
    report_lines.append(f"Completed: {total_completed}")
    report_lines.append(f"Skipped/Error: {len(test_cases) - total_completed}")
    report_lines.append("")
    report_lines.append(f"Correct: {correct} ({correct/total_completed*100:.1f}%)")
    report_lines.append(f"Partial: {partial} ({partial/total_completed*100:.1f}%)")
    report_lines.append(f"Incorrect: {incorrect} ({incorrect/total_completed*100:.1f}%)")
    report_lines.append("")
    report_lines.append(f"Average Score: {avg_score:.3f}")
    report_lines.append(f"Average Facts Covered: {avg_facts_covered:.1f}")
    report_lines.append("")

    # Breakdown by difficulty
    report_lines.append("BREAKDOWN BY DIFFICULTY")
    report_lines.append("-" * 80)
    for difficulty in ['easy', 'moderate', 'hard']:
        if difficulty in by_difficulty:
            statuses = by_difficulty[difficulty]
            total = len(statuses)
            corr = sum(1 for s in statuses if s == 'correct')
            part = sum(1 for s in statuses if s == 'partial')
            report_lines.append(f"{difficulty.capitalize()}: {total} cases - "
                              f"Correct: {corr} ({corr/total*100:.0f}%), "
                              f"Partial: {part} ({part/total*100:.0f}%)")
    report_lines.append("")

    # Breakdown by type
    report_lines.append("BREAKDOWN BY TYPE")
    report_lines.append("-" * 80)
    for qtype in sorted(by_type.keys()):
        statuses = by_type[qtype]
        total = len(statuses)
        corr = sum(1 for s in statuses if s == 'correct')
        part = sum(1 for s in statuses if s == 'partial')
        report_lines.append(f"{qtype}: {total} cases - "
                          f"Correct: {corr} ({corr/total*100:.0f}%), "
                          f"Partial: {part} ({part/total*100:.0f}%)")
    report_lines.append("")

    # Breakdown by repo
    report_lines.append("BREAKDOWN BY REPO")
    report_lines.append("-" * 80)
    for repo in sorted(by_repo.keys(), key=lambda r: len(by_repo[r]), reverse=True):
        statuses = by_repo[repo]
        total = len(statuses)
        corr = sum(1 for s in statuses if s == 'correct')
        part = sum(1 for s in statuses if s == 'partial')
        report_lines.append(f"{repo}: {total} cases - "
                          f"Correct: {corr} ({corr/total*100:.0f}%), "
                          f"Partial: {part} ({part/total*100:.0f}%)")
    report_lines.append("")

    # Individual test case details
    report_lines.append("INDIVIDUAL TEST CASE RESULTS")
    report_lines.append("=" * 80)
    for i, e in enumerate(completed, 1):
        tc = e['test_case']
        ev = e['evaluation']

        status_emoji = {
            'correct': '✅',
            'partial': '⚠️',
            'incorrect': '❌'
        }.get(ev['status'], '❓')

        report_lines.append(f"\n[{i}/{total_completed}] {status_emoji} {ev['status'].upper()} "
                          f"(Score: {ev['score']:.2f})")
        report_lines.append(f"Repo: {tc['repo']} | PR: {tc['pr']} | Commit: {tc['commit'][:8]}")
        report_lines.append(f"Difficulty: {tc['metadata']['difficulty']} | "
                          f"Type: {tc['metadata']['type']} | "
                          f"Scope: {tc['metadata']['scope']}")
        report_lines.append(f"\nQuestion: {tc['question']}")
        report_lines.append(f"\nFacts Covered: {ev['facts_covered']}/{ev['total_facts']}")
        report_lines.append(f"\nAnalysis: {ev['analysis']}")
        report_lines.append("-" * 80)

    # Write report
    report_text = "\n".join(report_lines)

    with open(output_file, 'w') as f:
        f.write(report_text)

    print(report_text)
    print(f"\nReport saved to: {Path(output_file).absolute()}")

    return evaluations


if __name__ == "__main__":
    import sys

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Please set it with: export ANTHROPIC_API_KEY=your-key")
        sys.exit(1)

    input_file = sys.argv[1] if len(sys.argv) > 1 else "data/test_cases.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "evaluation_report.txt"
    prompt_file = sys.argv[3] if len(sys.argv) > 3 else "prompts/evaluation_prompt.txt"

    test_cases = load_test_cases(input_file)
    generate_report(test_cases, output_file, prompt_file)
