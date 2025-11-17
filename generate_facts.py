#!/usr/bin/env python3
"""Generate core facts from questions using Claude."""

import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Tuple
import uuid
import anthropic

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_fact_prompts(
    system_prompt_file: str = "prompts/fact_generation_system.txt",
    user_prompt_file: str = "prompts/fact_generation_user.txt"
) -> Tuple[str, str]:
    """Load the fact generation prompt templates (system and user)."""
    with open(system_prompt_file, 'r') as f:
        system_prompt = f.read()
    with open(user_prompt_file, 'r') as f:
        user_prompt = f.read()
    return system_prompt, user_prompt


def load_questions(questions_dir: str = "data/questions") -> Dict[str, List[Dict]]:
    """Load all generated questions."""
    questions_path = Path(questions_dir)
    all_questions = {}
    
    for questions_file in questions_path.glob("*_questions.json"):
        with open(questions_file, 'r') as f:
            data = json.load(f)
            repo_name = questions_file.stem.replace('_questions', '').replace('_', '/', 1)
            all_questions[repo_name] = data
            logger.info(f"Loaded {len(data)} question sets from {repo_name}")
    
    return all_questions


def build_fact_prompt(question_data: Dict, prompt_template: str) -> str:
    """
    Build the fact generation prompt for Claude.
    
    Args:
        question_data: Question dictionary with question, answer, key_files
        prompt_template: Prompt template string
    
    Returns:
        Formatted prompt string
    """
    key_files_str = ", ".join(question_data.get("key_files", []))
    
    prompt = prompt_template.format(
        question=question_data["question"],
        answer=question_data["answer"],
        key_files=key_files_str
    )
    
    return prompt


def generate_facts_with_claude(
    question_data: Dict,
    anthropic_client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt_template: str
) -> List[str]:
    """
    Use Claude to generate facts from a question/answer pair.
    
    Args:
        question_data: Question dictionary
        anthropic_client: Anthropic API client
        system_prompt: System prompt with guidelines
        user_prompt_template: User prompt template string
    
    Returns:
        List of facts
    """
    user_prompt = build_fact_prompt(question_data, user_prompt_template)
    
    try:
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        
        response_text = message.content[0].text
        
        # Extract JSON from response
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        
        result = json.loads(response_text)
        facts = result.get("facts", [])
        
        return facts
    
    except Exception as e:
        logger.error(f"  ✗ Error calling Claude: {e}")
        return []


def process_question_set(
    question_set: Dict,
    anthropic_client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt_template: str
) -> Dict:
    """Process a single question set (from one PR) to generate facts for all questions."""
    pr_number = question_set["pr_data"]["pr_number"]
    logger.info(f"\nProcessing PR #{pr_number}: {question_set['pr_data']['title'][:60]}...")
    
    questions_with_facts = []
    
    for i, question_data in enumerate(question_set["questions"], 1):
        logger.info(f"  [{i}/{len(question_set['questions'])}] Generating facts for: {question_data['question'][:80]}...")
        
        facts = generate_facts_with_claude(question_data, anthropic_client, system_prompt, user_prompt_template)
        
        if facts:
            logger.info(f"    ✓ Generated {len(facts)} facts")
            question_data["facts"] = facts
        else:
            logger.warning(f"    ✗ No facts generated")
            question_data["facts"] = []
        
        questions_with_facts.append(question_data)
    
    # Update question set with facts
    result = question_set.copy()
    result["questions"] = questions_with_facts
    
    return result


def main():
    """Main function."""
    import sys
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate facts from questions using Claude")
    parser.add_argument("input_file", nargs="?", default=None,
                        help="Path to specific questions JSON file (optional)")
    parser.add_argument("--n_prs", type=int, default=None,
                        help="Limit number of PRs to process (optional)")
    args = parser.parse_args()
    
    # Initialize Anthropic client
    anthropic_token = os.environ.get("ANTHROPIC_API_KEY")
    
    if not anthropic_token:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    anthropic_client = anthropic.Anthropic(api_key=anthropic_token)
    
    # Load prompt templates (system and user)
    logger.info("Loading fact generation prompts...")
    system_prompt, user_prompt_template = load_fact_prompts()
    
    # Load questions (from specific file or all files)
    if args.input_file:
        logger.info(f"Loading questions from: {args.input_file}")
        with open(args.input_file, 'r') as f:
            question_sets = json.load(f)
        # Extract repo name from file path
        file_path = Path(args.input_file)
        repo_name = file_path.stem.replace('_questions', '').replace('_', '/', 1)
        all_questions = {repo_name: question_sets}
    else:
        all_questions = load_questions()
    
    if not all_questions:
        logger.error("No questions found to process!")
        return
    
    # Create output directory
    output_dir = Path("data/questions_with_facts")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each repository
    for repo_full_name, question_sets in all_questions.items():
        repo_owner, repo_name = repo_full_name.split('/')
        
        # Limit number of PRs if specified
        if args.n_prs is not None:
            question_sets = question_sets[:args.n_prs]
            logger.info(f"Limiting to first {args.n_prs} PRs")
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing repository: {repo_full_name}")
        logger.info(f"{'='*80}")
        
        results = []
        
        for i, question_set in enumerate(question_sets, 1):
            logger.info(f"\n[{i}/{len(question_sets)}] Processing PR...")
            result = process_question_set(question_set, anthropic_client, system_prompt, user_prompt_template)
            results.append(result)
        
        # Save results
        output_file = output_dir / f"{repo_owner}_{repo_name}_questions_with_facts.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\n✓ Saved {len(results)} question sets with facts to {output_file}")
        
        # Also save in test_cases.json format for compatibility with evaluate_results.py
        test_cases_file = output_dir / f"{repo_owner}_{repo_name}_test_cases.json"
        test_cases = []
        
        for result in results:
            pr_data = result["pr_data"]
            for q in result["questions"]:
                # Map difficulty: core questions are typically harder
                difficulty = "hard" if q.get("is_core_question", False) else "moderate"
                
                # Determine type based on scope
                question_type = "open_question"  # All our questions are open questions
                
                test_case = {
                    "index": len(test_cases),
                    "id": str(uuid.uuid4()),
                    "repo": pr_data["repo"],
                    "commit": pr_data["commit_sha"],
                    "pr": pr_data["pr_number"],
                    "question": q["question"],
                    "ground_truth_answer": q.get("answer", ""),
                    "facts": q.get("facts", []),
                    "metadata": {
                        "difficulty": difficulty,
                        "type": question_type,
                        "scope": q.get("scope", "broad"),
                        "includes_code": False,  # Our questions don't include code snippets
                        "n_context_files": len(q.get("key_files", [])),
                        "key_files": q.get("key_files", []),
                        "is_core_question": q.get("is_core_question", False)
                    },
                    "status": "pending",
                    "deepwiki_answer": None
                }
                test_cases.append(test_case)
        
        with open(test_cases_file, 'w') as f:
            json.dump(test_cases, f, indent=2)
        
        logger.info(f"✓ Saved {len(test_cases)} test cases to {test_cases_file}")


if __name__ == "__main__":
    main()
