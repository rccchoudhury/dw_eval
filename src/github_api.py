"""GitHub API wrapper with rate limiting and error handling."""

import os
import time
import requests
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class GitHubAPI:
    """Wrapper for GitHub REST API with rate limiting."""
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, token: Optional[str] = None, rate_limit_buffer: int = 100):
        """
        Initialize GitHub API client.
        
        Args:
            token: GitHub personal access token. If None, reads from GITHUB_TOKEN env var.
            rate_limit_buffer: Stop when this many API calls remain.
        """
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token not provided. Set GITHUB_TOKEN environment variable.")
        
        self.rate_limit_buffer = rate_limit_buffer
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        })
        
        logger.info("GitHub API client initialized")
    
    def _check_rate_limit(self):
        """Check rate limit and wait if necessary."""
        response = self.session.get(f"{self.BASE_URL}/rate_limit")
        response.raise_for_status()
        
        data = response.json()
        core_remaining = data["resources"]["core"]["remaining"]
        core_reset = data["resources"]["core"]["reset"]
        
        logger.debug(f"Rate limit: {core_remaining} requests remaining")
        
        if core_remaining < self.rate_limit_buffer:
            wait_time = core_reset - time.time() + 10  # Add 10s buffer
            if wait_time > 0:
                logger.warning(f"Rate limit approaching. Waiting {wait_time:.0f} seconds...")
                time.sleep(wait_time)
    
    def get_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "closed",
        per_page: int = 100,
        max_pages: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch pull requests from a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            state: PR state (open, closed, all)
            per_page: Results per page
            max_pages: Maximum pages to fetch (None = all)
        
        Returns:
            List of PR dictionaries
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls"
        params = {
            "state": state,
            "per_page": per_page,
            "sort": "created",
            "direction": "desc"
        }
        
        all_prs = []
        page = 1
        
        while True:
            if max_pages and page > max_pages:
                break
            
            self._check_rate_limit()
            
            params["page"] = page
            logger.info(f"Fetching PRs from {owner}/{repo} (page {page})...")
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            prs = response.json()
            if not prs:
                break
            
            all_prs.extend(prs)
            logger.info(f"  Retrieved {len(prs)} PRs (total: {len(all_prs)})")
            
            # Check if there are more pages
            if "next" not in response.links:
                break
            
            page += 1
        
        return all_prs
    
    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> Dict:
        """
        Get detailed information about a specific PR.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            PR dictionary with detailed info
        """
        self._check_rate_limit()
        
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
        response = self.session.get(url)
        response.raise_for_status()
        
        return response.json()
    
    def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pr_number: int
    ) -> List[Dict]:
        """
        Get list of files changed in a PR.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            List of file change dictionaries
        """
        self._check_rate_limit()
        
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        params = {"per_page": 100}
        
        all_files = []
        page = 1
        
        while True:
            params["page"] = page
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            files = response.json()
            if not files:
                break
            
            all_files.extend(files)
            
            if "next" not in response.links:
                break
            
            page += 1
        
        return all_files
    
    def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main"
    ) -> Optional[str]:
        """
        Get content of a file at a specific ref.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: File path
            ref: Git ref (branch, tag, commit SHA)
        
        Returns:
            File content as string, or None if not found
        """
        self._check_rate_limit()
        
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        params = {"ref": ref}
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Content is base64 encoded
            import base64
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"File not found: {path} at ref {ref}")
                return None
            raise
