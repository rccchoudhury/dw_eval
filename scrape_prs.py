#!/usr/bin/env python3
"""Scrape pull requests from GitHub repositories."""

import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import yaml
from datetime import datetime, timedelta

from src.github_api import GitHubAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "data/config.yaml") -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def matches_exclude_pattern(filename: str, patterns: List[str]) -> bool:
    """Check if filename matches any exclude pattern."""
    from fnmatch import fnmatch
    
    for pattern in patterns:
        if fnmatch(filename, pattern):
            return True
    return False


def filter_pr(
    pr: Dict,
    files: List[Dict],
    config: Dict
) -> Tuple[bool, Optional[str]]:
    """
    Filter PR based on criteria.
    
    Args:
        pr: PR dictionary
        files: List of changed files
        config: Configuration dictionary
    
    Returns:
        (should_include, reason_if_excluded)
    """
    filters = config["pr_filters"]
    
    # Check if merged
    if filters["merged_only"] and not pr.get("merged_at"):
        return False, "not merged"
    
    # Check created date (if created_before is set)
    created_before = filters.get("created_before")
    if created_before:
        created_at = pr.get("created_at")
        if created_at:
            created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            cutoff_date = datetime.fromisoformat(created_before).replace(tzinfo=created_date.tzinfo)
            if created_date >= cutoff_date:
                return False, f"created too late ({created_date.date()})"
    
    # Check age (if max_age_months is set)
    max_age_months = filters.get("max_age_months")
    if max_age_months is not None:
        merged_at = pr.get("merged_at")
        if merged_at:
            # Parse ISO 8601 timestamp
            merged_date = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
            cutoff_date = datetime.now(merged_date.tzinfo) - timedelta(days=max_age_months * 30)
            
            if merged_date < cutoff_date:
                return False, f"too old (merged {merged_date.date()})"
    
    # Check file count
    num_files = len(files)
    if num_files < filters["min_files_changed"]:
        return False, f"too few files ({num_files})"
    if num_files > filters["max_files_changed"]:
        return False, f"too many files ({num_files})"
    
    # Check description
    body = pr.get("body") or ""
    if filters["require_description"] and len(body) < filters["min_description_length"]:
        return False, "insufficient description"
    
    # Check if all files are excluded patterns (docs only, etc.)
    exclude_patterns = filters["exclude_patterns"]
    non_excluded_files = [
        f for f in files
        if not matches_exclude_pattern(f["filename"], exclude_patterns)
    ]
    
    if not non_excluded_files:
        return False, "only excluded file types"
    
    # Check if it's a trivial change (all files have very few changes)
    avg_changes = sum(f.get("changes", 0) for f in non_excluded_files) / len(non_excluded_files)
    if avg_changes < 5:
        return False, "trivial changes"
    
    return True, None


def scrape_repository(
    github: GitHubAPI,
    owner: str,
    repo: str,
    config: Dict,
    output_dir: Path
) -> List[Dict]:
    """
    Scrape PRs from a single repository.
    
    Args:
        github: GitHub API client
        owner: Repository owner
        repo: Repository name
        config: Configuration dictionary
        output_dir: Output directory for data
    
    Returns:
        List of filtered PR data
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"Scraping repository: {owner}/{repo}")
    logger.info(f"{'='*80}")
    
    # Create repo-specific output directory
    repo_dir = output_dir / f"{owner}_{repo}"
    repo_dir.mkdir(parents=True, exist_ok=True)
    
    # Load checkpoint if exists
    checkpoint_file = repo_dir / "checkpoint.json"
    if checkpoint_file.exists():
        with open(checkpoint_file, 'r') as f:
            checkpoint = json.load(f)
            processed_prs = set(checkpoint.get("processed_pr_numbers", []))
            filtered_data = checkpoint.get("filtered_prs", [])
            logger.info(f"Resuming from checkpoint: {len(processed_prs)} PRs already processed")
    else:
        processed_prs = set()
        filtered_data = []
    
    # Fetch and process PRs incrementally
    scraping_config = config["scraping"]
    max_prs = scraping_config["max_prs_per_repo"]
    per_page = scraping_config["per_page"]
    max_prs_to_check = 500  # Maximum number of PRs to check before stopping
    
    logger.info(f"Looking for {max_prs} good PRs (will check up to {max_prs_to_check} PRs)...")
    
    included_count = 0
    skipped_count = 0
    page = 1
    total_fetched = 0
    total_checked = 0
    
    # Fetch PRs page by page until we have enough good ones
    while included_count < max_prs:
        # Fetch one page of PRs
        github._check_rate_limit()
        
        url = f"{github.BASE_URL}/repos/{owner}/{repo}/pulls"
        params = {
            "state": config["pr_filters"]["state"],
            "per_page": per_page,
            "sort": "created",
            "direction": "desc",
            "page": page
        }
        
        logger.info(f"Fetching PR list page {page}...")
        response = github.session.get(url, params=params)
        response.raise_for_status()
        
        prs = response.json()
        if not prs:
            logger.info("No more PRs available")
            break
        
        total_fetched += len(prs)
        logger.info(f"  Retrieved {len(prs)} PRs (total fetched: {total_fetched})")
        
        # Process PRs in this page
        for i, pr in enumerate(prs, 1):
            pr_number = pr["number"]
            
            # Skip if already processed
            if pr_number in processed_prs:
                logger.debug(f"  PR #{pr_number}: already processed")
                continue
            
            # Stop if we've reached the limit
            if included_count >= max_prs:
                logger.info(f"✅ Reached target of {max_prs} PRs")
                break
            
            logger.info(f"  [{included_count}/{max_prs}] Processing PR #{pr_number}: {pr['title'][:60]}...")
            
            # Get PR files
            try:
                files = github.get_pull_request_files(owner, repo, pr_number)
            except Exception as e:
                logger.error(f"    Error fetching files: {e}")
                processed_prs.add(pr_number)
                continue
            
            # Increment checked count
            total_checked += 1
            
            # Apply filters
            should_include, reason = filter_pr(pr, files, config)
            
            if not should_include:
                logger.info(f"    ❌ Excluded: {reason}")
                skipped_count += 1
                processed_prs.add(pr_number)
                
                # If PR is too old, break early (PRs are sorted by creation date descending)
                if "too old" in reason:
                    logger.info(f"\n⚠️  Encountered old PR - stopping search (checked {total_checked} PRs)")
                    save_checkpoint(repo_dir, checkpoint_file, processed_prs, filtered_data)
                    return filtered_data
                
                continue
            
            # Extract relevant data
            pr_data = {
                "pr_number": pr_number,
                "title": pr["title"],
                "body": pr.get("body", ""),
                "html_url": pr["html_url"],
                "created_at": pr["created_at"],
                "merged_at": pr.get("merged_at"),
                "merge_commit_sha": pr.get("merge_commit_sha"),
                "base_ref": pr["base"]["ref"],
                "head_sha": pr["head"]["sha"],
                "user": pr["user"]["login"],
                "files": [
                    {
                        "filename": f["filename"],
                        "status": f["status"],
                        "additions": f["additions"],
                        "deletions": f["deletions"],
                        "changes": f["changes"],
                        "patch": f.get("patch", "")
                    }
                    for f in files
                ],
                "num_files": len(files),
                "scraped_at": datetime.now().isoformat()
            }
            
            filtered_data.append(pr_data)
            processed_prs.add(pr_number)
            included_count += 1
            
            logger.info(f"    ✅ Included ({included_count}/{max_prs})")
            
            # Save checkpoint periodically
            if included_count % scraping_config["checkpoint_interval"] == 0:
                save_checkpoint(repo_dir, checkpoint_file, processed_prs, filtered_data)
        
        # Stop if we've found enough good PRs
        if included_count >= max_prs:
            break
        
        # Stop if we've checked too many PRs
        if total_checked >= max_prs_to_check:
            logger.info(f"\n⚠️  Reached max check limit of {max_prs_to_check} PRs")
            break
        
        # Check if there are more pages
        if "next" not in response.links:
            logger.info("No more pages available")
            break
        
        page += 1
    
    # Final save
    save_checkpoint(repo_dir, checkpoint_file, processed_prs, filtered_data)
    
    logger.info(f"\nRepository summary:")
    logger.info(f"  Total PRs fetched: {total_fetched}")
    logger.info(f"  Total PRs checked: {total_checked}")
    logger.info(f"  Included: {included_count}")
    logger.info(f"  Skipped: {skipped_count}")
    
    return filtered_data


def save_checkpoint(repo_dir: Path, checkpoint_file: Path, processed_prs: set, filtered_data: List[Dict]):
    """Save checkpoint data."""
    checkpoint = {
        "processed_pr_numbers": list(processed_prs),
        "filtered_prs": filtered_data,
        "last_updated": datetime.now().isoformat()
    }
    
    with open(checkpoint_file, 'w') as f:
        json.dump(checkpoint, f, indent=2)
    
    # Also save as final output
    output_file = repo_dir / "prs.json"
    with open(output_file, 'w') as f:
        json.dump(filtered_data, f, indent=2)
    
    logger.debug(f"Checkpoint saved: {len(filtered_data)} PRs")


def main():
    """Main function."""
    # Load configuration
    config = load_config()
    
    # Initialize GitHub API
    token = os.environ.get(config["github"]["token_env"])
    github = GitHubAPI(
        token=token,
        rate_limit_buffer=config["github"]["rate_limit_buffer"]
    )
    
    # Create output directory
    output_dir = Path(config["scraping"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Scrape each repository
    all_results = {}
    
    for repo_config in config["repositories"]:
        if not repo_config.get("enabled", True):
            logger.info(f"Skipping disabled repository: {repo_config['owner']}/{repo_config['name']}")
            continue
        
        try:
            filtered_prs = scrape_repository(
                github=github,
                owner=repo_config["owner"],
                repo=repo_config["name"],
                config=config,
                output_dir=output_dir
            )
            
            repo_key = f"{repo_config['owner']}/{repo_config['name']}"
            all_results[repo_key] = {
                "count": len(filtered_prs),
                "prs": filtered_prs
            }
        
        except Exception as e:
            logger.error(f"Error scraping {repo_config['owner']}/{repo_config['name']}: {e}", exc_info=True)
            continue
    
    # Save summary
    summary_file = output_dir / "summary.json"
    summary = {
        "scraped_at": datetime.now().isoformat(),
        "repositories": {
            repo: {"count": data["count"]}
            for repo, data in all_results.items()
        },
        "total_prs": sum(data["count"] for data in all_results.values())
    }
    
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"\n{'='*80}")
    logger.info("SCRAPING COMPLETE")
    logger.info(f"{'='*80}")
    logger.info(f"Total PRs collected: {summary['total_prs']}")
    logger.info(f"Summary saved to: {summary_file}")
    
    for repo, info in summary["repositories"].items():
        logger.info(f"  {repo}: {info['count']} PRs")


if __name__ == "__main__":
    main()
