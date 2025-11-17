#!/usr/bin/env python3
"""
Generic evaluation script that works with any test case format.
Evaluates system-generated answers against ground truth using Claude API.
"""

import json
import os
import sys
import logging
import re
from pathlib import Path
from collections import defaultdict
import anthropic
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_json(file_path):
    """Load JSON from file."""
    with open(file_path, 'r') as f:
        return json.load(f)


def validate_and_prepare_test_cases(test_cases, system_answer_field='deepwiki_answer'):
    """
    Validate test cases have all required fields and prepare them for evaluation.
    
    Args:
        test_cases: List of test case dicts
        system_answer_field: Field name for system answer
    
    Returns:
        List of prepared test cases
    
    Raises:
        ValueError: If required fields are missing
    """
    required_fields = ['question', 'facts', system_answer_field]
    
    if not test_cases:
        raise ValueError("Test cases list is empty")
    
    # Check first test case for required fields
    first_case = test_cases[0]
    missing_fields = [field for field in required_fields if field not in first_case]
    
    if missing_fields:
        raise ValueError(
            f"Test cases are missing required fields: {missing_fields}\n"
            f"Required fields: question, facts, {system_answer_field}\n"
            f"Found fields: {list(first_case.keys())}"
        )
    
    # Prepare test cases in standard format
    prepared = []
    for tc in test_cases:
        prepared_case = {
            'id': tc.get('id', 'N/A'),
            'question': tc['question'],
            'ground_truth': tc.get('ground_truth_answer', tc.get('answer', '')),
            'facts': tc['facts'],
            'metadata': tc.get('metadata', {}),
            'system_answer': tc.get(system_answer_field, '')
        }
        prepared.append(prepared_case)
    
    logger.info(f"Validated and prepared {len(prepared)} test cases")
    return prepared


def load_evaluation_prompt(prompt_file="prompts/evaluation_prompt.txt"):
    """Load the evaluation prompt template from file."""
    try:
        with open(prompt_file, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: Prompt file '{prompt_file}' not found")
        raise


def evaluate_with_claude(question, system_answer, ground_truth, facts, prompt_template):
    """
    Use Claude API to evaluate if the system answer is correct.
    Returns evaluation results with score and reasoning.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Format facts as numbered list
    facts_text = "\n".join(f"{i+1}. {fact}" for i, fact in enumerate(facts))

    # Fill in the template
    prompt = prompt_template.format(
        question=question,
        ground_truth=ground_truth,
        facts=facts_text,
        deepwiki_answer=system_answer,  # Using same placeholder name as template
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
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        
        logger.debug(f"JSON to parse (first 200 chars): {response_text[:200]}")
        # Parse JSON response
        result = json.loads(response_text)
        logger.debug(f"Successfully parsed JSON: {result}")

        # Convert to standard format
        # New format has scores.factual_correctness, fact_coverage, and specificity
        if 'scores' in result:
            # Extract scores
            factual = result['scores'].get('factual_correctness', 0)
            coverage = result['scores'].get('fact_coverage', 0)
            specificity = result['scores'].get('specificity', 0)
            
            # Handle N/A specificity
            if specificity == "N/A" or specificity is None:
                specificity = 0
                specificity_na = True
            else:
                specificity = float(specificity)
                specificity_na = False
            
            # Calculate weighted score: (2*F + C + S) / 40
            # Max: 2*10 + 10 + 10 = 40
            raw_score = (2 * factual) + coverage + specificity
            result['score'] = raw_score / 40.0
            result['raw_score'] = raw_score
            result['factual_correctness'] = factual
            result['fact_coverage'] = coverage
            result['specificity'] = specificity
            result['specificity_na'] = specificity_na
            
            # Extract facts covered count
            facts_found = result.get('reasoning', {}).get('facts_found', [])
            result['facts_covered'] = len(facts_found)
            result['total_facts'] = len(facts)
            
            # Use summary as analysis
            result['analysis'] = result.get('summary', '')
            
        elif 'score' in result:
            # Old format - normalize score from 0-100 to 0-1
            result['score'] = result['score'] / 100.0
            result['total_facts'] = len(facts)
        else:
            # Unknown format
            raise ValueError(f"Unknown response format: {result}")

        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        logger.error(f"Failed to parse response: {response_text[:500]}")
        return {
            'score': 0,
            'raw_score': 0,
            'factual_correctness': 0,
            'fact_coverage': 0,
            'specificity': 0,
            'specificity_na': False,
            'analysis': f'JSON parsing error: {str(e)}',
            'facts_covered': 0,
            'total_facts': len(facts),
            'error': True
        }
    except Exception as e:
        logger.error(f"Error calling Claude API: {e}", exc_info=True)
        return {
            'score': 0,
            'raw_score': 0,
            'factual_correctness': 0,
            'fact_coverage': 0,
            'specificity': 0,
            'specificity_na': False,
            'analysis': f'API error: {str(e)}',
            'facts_covered': 0,
            'total_facts': len(facts),
            'error': True
        }


def validate_test_case(tc):
    """
    Validate that test case has required fields.
    
    Returns (is_valid, error_message)
    """
    required = ['question', 'ground_truth', 'facts', 'system_answer', 'id']
    
    for field in required:
        if field not in tc:
            return False, f"Missing required field: {field}"
    
    if not tc['facts']:
        return False, "Facts list is empty"
    
    return True, None


def generate_report(test_cases, output_file, prompt_file):
    """Generate a comprehensive evaluation report."""
    
    # Load prompt template
    print(f"Loading evaluation prompt from {prompt_file}...")
    prompt_template = load_evaluation_prompt(prompt_file)
    
    # Validate test cases
    print(f"Validating {len(test_cases)} test cases...")
    valid_cases = []
    for tc in test_cases:
        is_valid, error = validate_test_case(tc)
        if is_valid:
            valid_cases.append(tc)
        else:
            logger.warning(f"Skipping test case {tc.get('id', 'unknown')}: {error}")
    
    print(f"Evaluating {len(valid_cases)} test cases using Claude API...")
    print()
    
    # Evaluate all test cases with progress bar
    evaluations = []
    
    # Use tqdm with position and leave settings for clean output
    with tqdm(total=len(valid_cases), desc="Evaluating", unit="case", 
              bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
        
        for tc in valid_cases:
            tc_id = str(tc['id'])[:8] if isinstance(tc['id'], str) else str(tc['id'])
            
            # Update progress bar description
            pbar.set_postfix_str(f"ID: {tc_id}")
            
            if not tc['system_answer']:
                tqdm.write(f"{tc_id}: Skipping - no system answer")
                eval_result = {
                    'score': 0,
                    'raw_score': 0,
                    'factual_correctness': 0,
                    'fact_coverage': 0,
                    'specificity': 0,
                    'specificity_na': False,
                    'analysis': 'No system answer provided',
                    'facts_covered': 0,
                    'total_facts': len(tc['facts']),
                    'error': True
                }
            else:
                eval_result = evaluate_with_claude(
                    tc['question'],
                    tc['system_answer'],
                    tc['ground_truth'],
                    tc['facts'],
                    prompt_template
                )
                
                # Print result under progress bar
                if eval_result.get('error'):
                    tqdm.write(f"{tc_id}: Error - {eval_result.get('analysis', '')[:50]}")
                else:
                    score = eval_result.get('score', 0)
                    raw = eval_result.get('raw_score', 0)
                    factual = eval_result.get('factual_correctness', 0)
                    coverage = eval_result.get('fact_coverage', 0)
                    specificity = eval_result.get('specificity', 0)
                    spec_na = eval_result.get('specificity_na', False)
                    
                    spec_str = "N/A" if spec_na else f"{specificity:.1f}"
                    tqdm.write(f"{tc_id}: Score={score:.3f} [{raw:.0f}/40] (F={factual:.1f}, C={coverage:.1f}, S={spec_str})")
            
            evaluations.append({
                'test_case': tc,
                'evaluation': eval_result
            })
            
            pbar.update(1)
    
    print()
    
    # Calculate statistics
    completed = [e for e in evaluations if not e['evaluation'].get('error', False)]
    
    if not completed:
        print("No completed test cases to evaluate!")
        return
    
    total_completed = len(completed)
    total_errors = len(evaluations) - total_completed
    
    avg_score = sum(e['evaluation']['score'] for e in completed) / total_completed
    avg_raw_score = sum(e['evaluation'].get('raw_score', 0) for e in completed) / total_completed
    avg_factual = sum(e['evaluation'].get('factual_correctness', 0) for e in completed) / total_completed
    avg_coverage = sum(e['evaluation'].get('fact_coverage', 0) for e in completed) / total_completed
    
    # Calculate average specificity (excluding N/A)
    specificity_scores = [e['evaluation'].get('specificity', 0) for e in completed 
                          if not e['evaluation'].get('specificity_na', False)]
    avg_specificity = sum(specificity_scores) / len(specificity_scores) if specificity_scores else 0
    specificity_na_count = sum(1 for e in completed if e['evaluation'].get('specificity_na', False))
    
    avg_facts_covered = sum(e['evaluation']['facts_covered'] for e in completed) / total_completed
    
    # Breakdown by metadata (if available) - collect scores
    by_difficulty = defaultdict(list)
    by_type = defaultdict(list)
    by_scope = defaultdict(list)
    
    for e in completed:
        tc = e['test_case']
        score = e['evaluation']['score']
        metadata = tc['metadata']
        
        if 'difficulty' in metadata:
            by_difficulty[metadata['difficulty']].append(score)
        if 'type' in metadata:
            by_type[metadata['type']].append(score)
        if 'scope' in metadata:
            by_scope[metadata['scope']].append(score)
    
    # Generate report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("EVALUATION REPORT (Claude API Evaluation)")
    report_lines.append("=" * 80)
    report_lines.append("")
    
    report_lines.append("OVERALL STATISTICS")
    report_lines.append("-" * 80)
    report_lines.append(f"Total test cases: {len(test_cases)}")
    report_lines.append(f"Completed: {total_completed}")
    if total_errors > 0:
        report_lines.append(f"Errors: {total_errors}")
    report_lines.append("")
    report_lines.append(f"Average Score: {avg_score:.3f} (normalized)")
    report_lines.append(f"Average Raw Score: {avg_raw_score:.1f}/40")
    report_lines.append("")
    report_lines.append("Component Scores (0-10 scale):")
    report_lines.append(f"  Factual Correctness (2x weight): {avg_factual:.2f}")
    report_lines.append(f"  Fact Coverage (1x weight): {avg_coverage:.2f}")
    if specificity_na_count > 0:
        report_lines.append(f"  Specificity (1x weight): {avg_specificity:.2f} ({specificity_na_count} N/A cases)")
    else:
        report_lines.append(f"  Specificity (1x weight): {avg_specificity:.2f}")
    report_lines.append("")
    report_lines.append(f"Average Facts Covered: {avg_facts_covered:.1f}")
    report_lines.append("")
    
    # Best and worst questions
    report_lines.append("BEST AND WORST SCORING QUESTIONS")
    report_lines.append("-" * 80)
    
    # Sort by score
    sorted_evals = sorted(completed, key=lambda e: e['evaluation']['score'], reverse=True)
    
    # Get top 2 and bottom 2
    best_2 = sorted_evals[:2] if len(sorted_evals) >= 2 else sorted_evals
    worst_2 = sorted_evals[-2:] if len(sorted_evals) >= 2 else []
    worst_2 = list(reversed(worst_2))  # Reverse so worst is first
    
    # Display best 2
    if best_2:
        report_lines.append("")
        report_lines.append("TOP 2 BEST SCORES:")
        report_lines.append("")
        for rank, e in enumerate(best_2, 1):
            tc = e['test_case']
            ev = e['evaluation']
            score = ev.get('score', 0)
            raw_score = ev.get('raw_score', 0)
            factual = ev.get('factual_correctness', 0)
            coverage = ev.get('fact_coverage', 0)
            specificity = ev.get('specificity', 0)
            spec_na = ev.get('specificity_na', False)
            spec_str = "N/A" if spec_na else f"{specificity:.1f}"
            
            report_lines.append(f"#{rank} - Score: {score:.3f} [{raw_score:.0f}/40]")
            report_lines.append(f"    Factual={factual:.1f}, Coverage={coverage:.1f}, Specificity={spec_str}")
            report_lines.append(f"    Question: {tc['question']}")
            report_lines.append(f"    Analysis: {ev['analysis'][:200]}...")
            report_lines.append("")
    
    # Display worst 2
    if worst_2:
        report_lines.append("TOP 2 WORST SCORES:")
        report_lines.append("")
        for rank, e in enumerate(worst_2, 1):
            tc = e['test_case']
            ev = e['evaluation']
            score = ev.get('score', 0)
            raw_score = ev.get('raw_score', 0)
            factual = ev.get('factual_correctness', 0)
            coverage = ev.get('fact_coverage', 0)
            specificity = ev.get('specificity', 0)
            spec_na = ev.get('specificity_na', False)
            spec_str = "N/A" if spec_na else f"{specificity:.1f}"
            
            report_lines.append(f"#{rank} - Score: {score:.3f} [{raw_score:.0f}/40]")
            report_lines.append(f"    Factual={factual:.1f}, Coverage={coverage:.1f}, Specificity={spec_str}")
            report_lines.append(f"    Question: {tc['question']}")
            report_lines.append(f"    Analysis: {ev['analysis'][:200]}...")
            report_lines.append("")
    
    report_lines.append("")
    
    # Breakdown by difficulty
    if by_difficulty:
        report_lines.append("BREAKDOWN BY DIFFICULTY")
        report_lines.append("-" * 80)
        for difficulty in ['easy', 'moderate', 'hard']:
            if difficulty in by_difficulty:
                scores = by_difficulty[difficulty]
                total = len(scores)
                avg = sum(scores) / total if total > 0 else 0
                report_lines.append(f"{difficulty.capitalize()}: {total} cases - Avg Score: {avg:.3f}")
        report_lines.append("")
    
    # Breakdown by type
    if by_type:
        report_lines.append("BREAKDOWN BY TYPE")
        report_lines.append("-" * 80)
        for qtype in sorted(by_type.keys()):
            scores = by_type[qtype]
            total = len(scores)
            avg = sum(scores) / total if total > 0 else 0
            report_lines.append(f"{qtype}: {total} cases - Avg Score: {avg:.3f}")
        report_lines.append("")
    
    # Breakdown by scope
    if by_scope:
        report_lines.append("BREAKDOWN BY SCOPE")
        report_lines.append("-" * 80)
        for scope in sorted(by_scope.keys()):
            scores = by_scope[scope]
            total = len(scores)
            avg = sum(scores) / total if total > 0 else 0
            report_lines.append(f"{scope}: {total} cases - Avg Score: {avg:.3f}")
        report_lines.append("")
    
    # Individual test case results
    report_lines.append("INDIVIDUAL TEST CASE RESULTS")
    report_lines.append("=" * 80)
    report_lines.append("")
    
    for i, e in enumerate(evaluations, 1):
        tc = e['test_case']
        ev = e['evaluation']
        
        score = ev.get('score', 0)
        raw_score = ev.get('raw_score', 0)
        
        tc_id = str(tc['id'])[:8] if isinstance(tc['id'], str) else str(tc['id'])
        factual = ev.get('factual_correctness', 0)
        coverage = ev.get('fact_coverage', 0)
        specificity = ev.get('specificity', 0)
        spec_na = ev.get('specificity_na', False)
        
        spec_str = "N/A" if spec_na else f"{specificity:.1f}"
        report_lines.append(f"[{i}/{len(evaluations)}] Score: {score:.3f} [{raw_score:.0f}/40]")
        report_lines.append(f"  Factual={factual:.1f}/10, Coverage={coverage:.1f}/10, Specificity={spec_str}/10")
        
        # Add metadata if available
        metadata_parts = []
        if 'difficulty' in tc['metadata']:
            metadata_parts.append(f"Difficulty: {tc['metadata']['difficulty']}")
        if 'type' in tc['metadata']:
            metadata_parts.append(f"Type: {tc['metadata']['type']}")
        if 'scope' in tc['metadata']:
            metadata_parts.append(f"Scope: {tc['metadata']['scope']}")
        
        if metadata_parts:
            report_lines.append(" | ".join(metadata_parts))
        
        report_lines.append("")
        report_lines.append(f"Question: {tc['question']}")
        report_lines.append("")
        report_lines.append(f"Facts Covered: {ev['facts_covered']}/{ev['total_facts']}")
        report_lines.append("")
        report_lines.append(f"Analysis: {ev['analysis']}")
        report_lines.append("-" * 80)
        report_lines.append("")
    
    # Write text report
    report_text = "\n".join(report_lines)
    
    with open(output_file, 'w') as f:
        f.write(report_text)
    
    # Save JSON results
    json_output_file = output_file.replace('.txt', '.json')
    json_results = {
        "summary": {
            "total_test_cases": len(test_cases),
            "completed": total_completed,
            "errors": total_errors,
            "average_score": avg_score,
            "average_raw_score": avg_raw_score,
            "average_factual_correctness": avg_factual,
            "average_fact_coverage": avg_coverage,
            "average_specificity": avg_specificity,
            "specificity_na_count": specificity_na_count,
            "average_facts_covered": avg_facts_covered
        },
        "breakdown": {
            "by_difficulty": {k: {"count": len(v), "avg_score": sum(v)/len(v)} for k, v in by_difficulty.items()},
            "by_type": {k: {"count": len(v), "avg_score": sum(v)/len(v)} for k, v in by_type.items()},
            "by_scope": {k: {"count": len(v), "avg_score": sum(v)/len(v)} for k, v in by_scope.items()}
        },
        "results": []
    }
    
    # Add individual results
    for e in evaluations:
        tc = e['test_case']
        ev = e['evaluation']
        
        result = {
            "id": tc['id'],
            "question": tc['question'],
            "ground_truth": tc['ground_truth'],
            "system_answer": tc['system_answer'],
            "facts": tc['facts'],
            "metadata": tc['metadata'],
            "evaluation": {
                "score": ev.get('score', 0),
                "raw_score": ev.get('raw_score', 0),
                "factual_correctness": ev.get('factual_correctness', 0),
                "fact_coverage": ev.get('fact_coverage', 0),
                "specificity": ev.get('specificity', 0),
                "specificity_na": ev.get('specificity_na', False),
                "facts_covered": ev.get('facts_covered', 0),
                "total_facts": ev.get('total_facts', 0),
                "analysis": ev.get('analysis', ''),
                "error": ev.get('error', False)
            }
        }
        json_results["results"].append(result)
    
    with open(json_output_file, 'w') as f:
        json.dump(json_results, f, indent=2)
    
    # Print summary to console - find the sections to print
    best_worst_start = None
    breakdown_start = None
    
    for i, line in enumerate(report_lines):
        if "BEST AND WORST SCORING QUESTIONS" in line:
            best_worst_start = i
        elif "BREAKDOWN BY DIFFICULTY" in line and best_worst_start is not None:
            breakdown_start = i
            break
    
    # Print overview and best/worst section
    print()
    if best_worst_start is not None and breakdown_start is not None:
        # Print from start to end of best/worst section
        print("\n".join(report_lines[:breakdown_start]))
    else:
        # Fallback to first 40 lines
        print("\n".join(report_lines[:40]))
    
    print(f"\nFull report saved to: {output_file}")
    print(f"JSON results saved to: {json_output_file}")


def main():
    """Main entry point."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Please set it with: export ANTHROPIC_API_KEY=your-key")
        sys.exit(1)
    
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("Usage: python3 evaluate_generic.py test_cases_json [system_answer_field] [output_report] [prompt_file]")
        print()
        print("Arguments:")
        print("  test_cases_json     : JSON file with test cases (must have: question, facts, and system answer)")
        print("  system_answer_field : Field name containing system's answer (default: 'deepwiki_answer')")
        print("  output_report       : Output report file (default: 'evaluation_report.txt')")
        print("  prompt_file         : Evaluation prompt template (default: 'prompts/evaluation_prompt.txt')")
        print()
        print("Example:")
        print("  python3 evaluate_generic.py data/test_cases.json")
        print("  python3 evaluate_generic.py data/test_cases.json deepwiki_answer report.txt")
        sys.exit(1)
    
    test_cases_file = sys.argv[1]
    system_answer_field = sys.argv[2] if len(sys.argv) > 2 else "deepwiki_answer"
    output_file = sys.argv[3] if len(sys.argv) > 3 else "evaluation_report.txt"
    prompt_file = sys.argv[4] if len(sys.argv) > 4 else "prompts/evaluation_prompt.txt"
    
    print(f"Test cases file: {test_cases_file}")
    print(f"System answer field: {system_answer_field}")
    print(f"Output file: {output_file}")
    print(f"Prompt file: {prompt_file}")
    print()
    
    # Load test cases
    print(f"Loading test cases from {test_cases_file}...")
    test_cases_raw = load_json(test_cases_file)
    print(f"Loaded {len(test_cases_raw)} test cases")
    print()
    
    # Validate and prepare test cases
    try:
        test_cases = validate_and_prepare_test_cases(test_cases_raw, system_answer_field)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Generate evaluation report
    generate_report(test_cases, output_file, prompt_file)


if __name__ == "__main__":
    main()
