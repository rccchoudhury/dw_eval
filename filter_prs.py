#!/usr/bin/env python3
"""Filter scraped PRs to identify which ones have enough substance for question generation."""

import json
import os
import logging
from pathlib import Path
from typing import List, Dict
import anthropic

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_filter_prompts(
    system_file: str = "prompts/pr_filter_system.txt",
    user_file: str = "prompts/pr_filter_user.txt"
) -> tuple:
    """Load the PR filter prompt templates."""
    with open(system_file, 'r') as f:
        system_prompt = f.read()
    with open(user_file, 'r') as f:
        user_prompt = f.read()
    return system_prompt, user_prompt


def load_scraped_prs(prs_file: str) -> List[Dict]:
    """Load scraped PRs from JSON file."""
    with open(prs_file, 'r') as f:
        return json.load(f)


def build_filter_prompt(pr_data: Dict, system_template: str, user_template: str) -> tuple:
    """
    Build the filter prompts for Claude.
    
    Args:
        pr_data: PR data dictionary
        system_template: System prompt template string
        user_template: User prompt template string
    
    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    # Build files content section (show patches/diffs)
    files_parts = []
    for file_info in pr_data["files"][:10]:  # Limit to first 10 files to save tokens
        filename = file_info["filename"]
        status = file_info["status"]
        additions = file_info["additions"]
        deletions = file_info["deletions"]
        patch = file_info.get("patch", "")
        
        files_parts.append(f"\n## File: {filename}")
        files_parts.append(f"Status: {status} (+{additions}/-{deletions})")
        if patch:
            files_parts.append("```diff")
            # Limit patch size to avoid token overflow
            patch_lines = patch.split('\n')[:50]
            files_parts.append('\n'.join(patch_lines))
            if len(patch.split('\n')) > 50:
                files_parts.append("... (truncated)")
            files_parts.append("```")
        files_parts.append("")
    
    if len(pr_data["files"]) > 10:
        files_parts.append(f"\n... and {len(pr_data['files']) - 10} more files")
    
    files_content = "\n".join(files_parts)
    
    # Fill in the system template with PR-specific data
    system_prompt = system_template.format(
        title=pr_data['title'],
        pr_number=pr_data['pr_number'],
        body=pr_data.get('body', '(No description provided)'),
        files_content=files_content
    )
    
    return system_prompt, user_template


def filter_pr_with_claude(
    pr_data: Dict,
    anthropic_client: anthropic.Anthropic,
    system_template: str,
    user_template: str
) -> Dict:
    """
    Use Claude to evaluate if a PR is suitable for question generation.
    
    Args:
        pr_data: PR data dictionary
        anthropic_client: Anthropic API client
        system_template: System prompt template string
        user_template: User prompt template string
    
    Returns:
        Dictionary with accept, reasoning, and substance_level
    """
    system_prompt, user_prompt = build_filter_prompt(pr_data, system_template, user_template)
    
    try:
        message = anthropic_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
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
        
        return {
            "accept": result.get("accept", False),
            "reasoning": result.get("reasoning", ""),
            "substance_level": result.get("substance_level", "low")
        }
    
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return {
            "accept": False,
            "reasoning": f"Error during filtering: {str(e)}",
            "substance_level": "unknown",
            "error": True
        }


def find_all_pr_files(prs_raw_dir: str = "data/prs_raw") -> List[tuple]:
    """
    Find all prs.json files in subdirectories of prs_raw.
    
    Returns:
        List of tuples: (repository_name, file_path)
    """
    prs_raw_path = Path(prs_raw_dir)
    pr_files = []
    
    if not prs_raw_path.exists():
        logger.warning(f"Directory not found: {prs_raw_dir}")
        return pr_files
    
    for subdir in prs_raw_path.iterdir():
        if subdir.is_dir():
            prs_file = subdir / "prs.json"
            if prs_file.exists():
                repo_name = subdir.name  # e.g., "huggingface_transformers"
                pr_files.append((repo_name, str(prs_file)))
    
    return pr_files


def main():
    """Main function."""
    import sys
    
    # Check for API key
    anthropic_token = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_token:
        logger.error("ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    anthropic_client = anthropic.Anthropic(api_key=anthropic_token)
    
    # Load prompt templates
    system_template, user_template = load_filter_prompts()
    logger.info("Loaded filter prompt templates")
    
    # Find all PR files
    logger.info("Scanning for PR files in data/prs_raw/...")
    pr_files = find_all_pr_files()
    
    if not pr_files:
        logger.error("No prs.json files found in data/prs_raw/ subdirectories")
        sys.exit(1)
    
    logger.info(f"Found {len(pr_files)} repositories to process:")
    for repo_name, _ in pr_files:
        logger.info(f"  - {repo_name}")
    
    # Load all PRs from all repositories
    all_prs = []
    for repo_name, prs_file in pr_files:
        logger.info(f"\nLoading PRs from {repo_name}...")
        prs = load_scraped_prs(prs_file)
        logger.info(f"  Loaded {len(prs)} PRs")
        
        # Add repository field to each PR
        for pr in prs:
            pr["repository"] = repo_name
        
        all_prs.extend(prs)
    
    logger.info(f"\nTotal PRs across all repositories: {len(all_prs)}")
    
    # Filter PRs
    logger.info("\nFiltering PRs with Claude...")
    filtered_prs = []
    rejected_prs = []
    
    for i, pr in enumerate(all_prs, 1):
        pr_number = pr["pr_number"]
        repo_name = pr["repository"]
        logger.info(f"[{i}/{len(all_prs)}] {repo_name} - PR #{pr_number}: {pr['title'][:60]}...")
        
        decision = filter_pr_with_claude(pr, anthropic_client, system_template, user_template)
        
        if decision.get("error"):
            logger.warning(f"  Error filtering PR, skipping: {decision['reasoning']}")
            continue
        
        # Add filter decision to PR data
        pr["filter_decision"] = decision
        
        if decision["accept"]:
            logger.info(f"  ✓ ACCEPT ({decision['substance_level']}) - {decision['reasoning'][:80]}")
            filtered_prs.append(pr)
        else:
            logger.info(f"  ✗ REJECT ({decision['substance_level']}) - {decision['reasoning'][:80]}")
            rejected_prs.append(pr)
    
    # Output file
    output_file = "data/prs_raw/all_prs_filtered.json"
    
    # Save results
    logger.info(f"\nFiltering complete:")
    logger.info(f"  Total PRs processed: {len(all_prs)}")
    logger.info(f"  Accepted: {len(filtered_prs)}")
    logger.info(f"  Rejected: {len(rejected_prs)}")
    
    # Save filtered PRs
    with open(output_file, 'w') as f:
        json.dump(filtered_prs, f, indent=2)
    logger.info(f"\nSaved filtered PRs to: {output_file}")
    
    # Save rejected PRs for analysis
    rejected_file = "data/prs_raw/all_prs_rejected.json"
    with open(rejected_file, 'w') as f:
        json.dump(rejected_prs, f, indent=2)
    logger.info(f"Saved rejected PRs to: {rejected_file}")
    
    # Save summary with per-repo breakdown
    by_repo = {}
    for pr in filtered_prs:
        repo = pr["repository"]
        if repo not in by_repo:
            by_repo[repo] = {"accepted": 0, "rejected": 0}
        by_repo[repo]["accepted"] += 1
    
    for pr in rejected_prs:
        repo = pr["repository"]
        if repo not in by_repo:
            by_repo[repo] = {"accepted": 0, "rejected": 0}
        by_repo[repo]["rejected"] += 1
    
    summary = {
        "total_prs": len(all_prs),
        "accepted": len(filtered_prs),
        "rejected": len(rejected_prs),
        "acceptance_rate": len(filtered_prs) / len(all_prs) if all_prs else 0,
        "by_substance_level": {
            "high": sum(1 for pr in filtered_prs if pr["filter_decision"]["substance_level"] == "high"),
            "medium": sum(1 for pr in filtered_prs if pr["filter_decision"]["substance_level"] == "medium"),
            "low": sum(1 for pr in filtered_prs if pr["filter_decision"]["substance_level"] == "low")
        },
        "by_repository": by_repo
    }
    
    summary_file = "data/prs_raw/all_prs_filter_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Saved summary to: {summary_file}")
    
    logger.info("\n" + "="*80)
    logger.info("Summary:")
    logger.info(f"  Acceptance rate: {summary['acceptance_rate']:.1%}")
    logger.info(f"  High substance: {summary['by_substance_level']['high']}")
    logger.info(f"  Medium substance: {summary['by_substance_level']['medium']}")
    logger.info(f"  Low substance: {summary['by_substance_level']['low']}")
    logger.info("\nBy repository:")
    for repo, stats in by_repo.items():
        logger.info(f"  {repo}: {stats['accepted']} accepted, {stats['rejected']} rejected")


if __name__ == "__main__":
    main()
