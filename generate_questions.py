#!/usr/bin/env python3
"""Generate questions from scraped PRs using Claude."""

import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Tuple
import anthropic

from src.github_api import GitHubAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_scraped_prs(data_dir: str = "data/prs_raw", specific_file: str = None) -> Dict[str, List[Dict]]:
    """Load all scraped PR data."""
    all_prs = {}
    
    # If specific file provided, load just that file
    if specific_file:
        with open(specific_file, 'r') as f:
            prs = json.load(f)
            # Extract repo name from file path (e.g., huggingface_transformers -> huggingface/transformers)
            file_path = Path(specific_file)
            parent_name = file_path.parent.name
            repo_name = parent_name.replace('_', '/', 1)
            all_prs[repo_name] = prs
            logger.info(f"Loaded {len(prs)} PRs from {repo_name}")
        return all_prs
    
    # Otherwise load all from directory
    data_path = Path(data_dir)
    
    for repo_dir in data_path.iterdir():
        if not repo_dir.is_dir():
            continue
        
        prs_file = repo_dir / "prs.json"
        if not prs_file.exists():
            continue
        
        with open(prs_file, 'r') as f:
            prs = json.load(f)
            repo_name = repo_dir.name.replace('_', '/', 1)  # Convert huggingface_transformers -> huggingface/transformers
            all_prs[repo_name] = prs
            logger.info(f"Loaded {len(prs)} PRs from {repo_name}")
    
    return all_prs


def fetch_full_file_contents(
    github: GitHubAPI,
    owner: str,
    repo: str,
    pr_data: Dict
) -> Dict[str, str]:
    """
    Fetch full contents of all files changed in the PR.
    
    Args:
        github: GitHub API client
        owner: Repository owner
        repo: Repository name
        pr_data: PR data dictionary
    
    Returns:
        Dictionary mapping filename -> file content
    """
    file_contents = {}
    commit_sha = pr_data["merge_commit_sha"]
    
    logger.info(f"  Fetching {len(pr_data['files'])} file(s) at commit {commit_sha[:8]}...")
    
    for file_info in pr_data["files"]:
        filename = file_info["filename"]
        
        # Skip deleted files
        if file_info["status"] == "removed":
            logger.debug(f"    Skipping deleted file: {filename}")
            continue
        
        try:
            content = github.get_file_content(owner, repo, filename, ref=commit_sha)
            if content:
                file_contents[filename] = content
                logger.debug(f"    ✓ {filename} ({len(content)} chars)")
            else:
                logger.warning(f"    ✗ Could not fetch: {filename}")
        except Exception as e:
            logger.error(f"    ✗ Error fetching {filename}: {e}")
    
    return file_contents


def extract_patches_from_pr(pr_data: Dict) -> Dict[str, str]:
    """
    Extract git patches from PR data (already in the JSON).
    Formats patches to show full code context with changes highlighted.
    
    Args:
        pr_data: PR data dictionary with files containing patches
    
    Returns:
        Dictionary mapping filename -> formatted patch content
    """
    patches = {}
    
    logger.info(f"  Extracting patches from {len(pr_data['files'])} file(s)...")
    
    for file_info in pr_data["files"]:
        filename = file_info["filename"]
        patch = file_info.get("patch", "")
        
        # Skip files without patches (binary files, etc.)
        if not patch:
            logger.debug(f"    Skipping {filename} (no patch)")
            continue
        
        status = file_info["status"]
        additions = file_info["additions"]
        deletions = file_info["deletions"]
        
        # Format the patch with metadata and clear explanation
        formatted_patch = f"""File Status: {status}
Changes: +{additions} additions, -{deletions} deletions

The diff below shows the changes made to this file.
Lines starting with '+' were added, lines with '-' were removed, and other lines provide context.

{patch}"""
        
        patches[filename] = formatted_patch
        logger.debug(f"    ✓ {filename} ({len(patch)} chars)")
    
    return patches


def load_question_prompts(
    system_prompt_file: str = "prompts/question_generation_system.txt",
    user_prompt_file: str = "prompts/question_generation_user.txt"
) -> Tuple[str, str]:
    """Load the question generation prompt templates (system and user)."""
    with open(system_prompt_file, 'r') as f:
        system_prompt = f.read()
    with open(user_prompt_file, 'r') as f:
        user_prompt = f.read()
    return system_prompt, user_prompt


def build_context_prompt(pr_data: Dict, file_contents: Dict[str, str], prompt_template: str, is_patch: bool = False) -> str:
    """
    Build the context prompt for Claude.
    
    Args:
        pr_data: PR data dictionary
        file_contents: Dictionary of filename -> content (either full files or patches)
        prompt_template: Prompt template string
        is_patch: Whether the content is a git patch (diff format)
    
    Returns:
        Formatted prompt string
    """
    # Build files content section
    files_parts = []
    for filename, content in file_contents.items():
        files_parts.append(f"\n## File: {filename}\n")
        
        # Use diff syntax highlighting for patches
        if is_patch:
            files_parts.append("```diff")
        else:
            files_parts.append("```")
        
        files_parts.append(content)
        files_parts.append("```\n")
    
    files_content = "\n".join(files_parts)
    
    # Fill in the template
    prompt = prompt_template.format(
        title=pr_data['title'],
        pr_number=pr_data['pr_number'],
        html_url=pr_data['html_url'],
        body=pr_data['body'],
        files_content=files_content
    )
    
    return prompt


def generate_questions_with_claude(
    pr_data: Dict,
    file_contents: Dict[str, str],
    anthropic_client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt_template: str,
    is_patch: bool = False
) -> Dict:
    """
    Use Claude to generate questions about the PR.
    
    Args:
        pr_data: PR data dictionary
        file_contents: Dictionary of filename -> content (or patches)
        anthropic_client: Anthropic API client
        system_prompt: System prompt with instructions/guidelines
        user_prompt_template: User prompt template for PR-specific data
        is_patch: Whether the content is patches (diff format)
    
    Returns:
        Dictionary with summary, analysis, and questions
    """
    user_prompt = build_context_prompt(pr_data, file_contents, user_prompt_template, is_patch=is_patch)
    
    logger.info(f"  Sending to Claude (user prompt length: {len(user_prompt)} chars)...")
    
    try:
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
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
        logger.info(f"  ✓ Generated {len(result.get('questions', []))} questions")
        
        return result
    
    except Exception as e:
        logger.error(f"  ✗ Error calling Claude: {e}")
        return {
            "questions": [],
            "error": str(e)
        }


def process_pr(
    pr_data: Dict,
    repo_owner: str,
    repo_name: str,
    github: GitHubAPI,
    anthropic_client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt_template: str,
    use_patches: bool = False
) -> Dict:
    """Process a single PR to generate questions."""
    logger.info(f"\nProcessing PR #{pr_data['pr_number']}: {pr_data['title'][:60]}...")
    
    # Get file contents (either full files or patches)
    if use_patches:
        file_contents = extract_patches_from_pr(pr_data)
    else:
        file_contents = fetch_full_file_contents(github, repo_owner, repo_name, pr_data)
    
    if not file_contents:
        logger.warning(f"  No file contents retrieved, skipping")
        return None
    
    # Generate questions with Claude
    result = generate_questions_with_claude(
        pr_data, 
        file_contents, 
        anthropic_client,
        system_prompt,
        user_prompt_template,
        is_patch=use_patches
    )
    
    # Add metadata
    result["pr_data"] = {
        "pr_number": pr_data["pr_number"],
        "title": pr_data["title"],
        "html_url": pr_data["html_url"],
        "repo": f"{repo_owner}/{repo_name}",
        "commit_sha": pr_data["merge_commit_sha"],
        "files": list(file_contents.keys())
    }
    
    return result


def main():
    """Main function."""
    import sys
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate questions from scraped PRs using Claude")
    parser.add_argument("input_file", nargs="?", default=None,
                        help="Path to specific PRs JSON file (optional)")
    parser.add_argument("--n_prs", type=int, default=None,
                        help="Limit number of PRs to process (optional)")
    parser.add_argument("--use_full_files", action="store_true",
                        help="Fetch full files from GitHub instead of using patches (slower, more context)")
    args = parser.parse_args()
    
    # Default to using patches (more efficient)
    args.use_patches = not args.use_full_files
    
    # Initialize clients
    github_token = os.environ.get("GITHUB_TOKEN")
    anthropic_token = os.environ.get("ANTHROPIC_API_KEY")
    
    # GitHub token only required if not using patches
    if not args.use_patches and not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set (not needed with --use_patches)")
    if not anthropic_token:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    github = GitHubAPI(token=github_token) if github_token else None
    anthropic_client = anthropic.Anthropic(api_key=anthropic_token)
    
    # Load prompt templates (system and user)
    logger.info("Loading question generation prompts...")
    system_prompt, user_prompt_template = load_question_prompts()
    
    # Load scraped PRs (accept optional file path from command line)
    all_prs = load_scraped_prs(specific_file=args.input_file)
    
    # Create output directory
    output_dir = Path("data/questions")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each repository
    for repo_full_name, prs in all_prs.items():
        repo_owner, repo_name = repo_full_name.split('/')
        
        # Limit number of PRs if specified
        if args.n_prs is not None:
            prs = prs[:args.n_prs]
            logger.info(f"Limiting to first {args.n_prs} PRs")
        
        # Log mode
        mode = "patches (diffs only)" if args.use_patches else "full files (GitHub API)"
        logger.info(f"Mode: {mode}")
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing repository: {repo_full_name}")
        logger.info(f"{'='*80}")
        
        results = []
        
        # Process all PRs (or limited subset)
        for i, pr_data in enumerate(prs, 1):
            logger.info(f"\n[{i}/{len(prs)}] Processing PR...")
            result = process_pr(
                pr_data, 
                repo_owner, 
                repo_name, 
                github, 
                anthropic_client,
                system_prompt,
                user_prompt_template,
                use_patches=args.use_patches
            )
            if result:
                results.append(result)
        
        # Save results
        output_file = output_dir / f"{repo_owner}_{repo_name}_questions.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\n✓ Saved {len(results)} question sets to {output_file}")


if __name__ == "__main__":
    main()
