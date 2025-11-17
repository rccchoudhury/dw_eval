#!/usr/bin/env python3
"""
Query DeepWiki using MCP (Model Context Protocol) and Claude API.

This script programmatically connects to the DeepWiki MCP server and uses
Claude to answer questions from test cases.

Requirements:
    pip install anthropic mcp

Environment Variables:
    ANTHROPIC_API_KEY: Your Anthropic API key
"""

import json
import os
import sys
import asyncio
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def load_test_cases(filename: str) -> list[dict]:
    """Load test cases from JSON file."""
    with open(filename, 'r') as f:
        return json.load(f)


def save_test_cases(test_cases: list[dict], filename: str):
    """Save test cases to JSON file."""
    with open(filename, 'w') as f:
        json.dump(test_cases, f, indent=2)
    print(f"Saved to: {filename}")


def get_pending_cases(test_cases: list[dict]) -> list[tuple[int, dict]]:
    """Get test cases without deepwiki_answer."""
    return [(i, tc) for i, tc in enumerate(test_cases) 
            if 'deepwiki_answer' not in tc or tc['deepwiki_answer'] is None]


async def query_deepwiki_with_mcp(
    question: str,
    repo: str,
    session: ClientSession,
    anthropic_client: Anthropic
) -> str:
    """
    Query DeepWiki using MCP tools and Claude.
    
    Args:
        question: The question to ask
        repo: Repository in format "owner/repo"
        session: MCP client session
        anthropic_client: Anthropic API client
        
    Returns:
        DeepWiki's answer
    """
    # Get available tools from MCP server
    tools_result = await session.list_tools()
    available_tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        }
        for tool in tools_result.tools
    ]
    
    # Construct prompt for Claude
    prompt = f"""Use the DeepWiki MCP tools to answer this question about the {repo} repository:

Question: {question}

Please query the DeepWiki knowledge base and provide a comprehensive answer based on what you find."""

    messages = [{"role": "user", "content": prompt}]
    
    # Call Claude with tool use
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        tools=available_tools,
        messages=messages
    )
    
    # Process tool calls if any
    while response.stop_reason == "tool_use":
        # Extract tool use blocks
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        
        # Execute each tool call via MCP
        tool_results = []
        for tool_use in tool_uses:
            print(f"  Calling MCP tool: {tool_use.name}")
            result = await session.call_tool(tool_use.name, tool_use.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result.content
            })
        
        # Add assistant response and tool results to conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        
        # Get next response from Claude
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            tools=available_tools,
            messages=messages
        )
    
    # Extract final text answer
    answer_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            answer_text += block.text
    
    return answer_text.strip()


async def process_test_cases(
    input_file: str,
    output_file: str,
    max_questions: int = None
):
    """
    Process test cases by querying DeepWiki via MCP.
    
    Args:
        input_file: Path to input JSON with test cases
        output_file: Path to save results
        max_questions: Maximum number of questions to process (None = all)
    """
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Initialize Anthropic client
    anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    # Load test cases
    print(f"Loading test cases from: {input_file}")
    test_cases = load_test_cases(input_file)
    pending = get_pending_cases(test_cases)
    
    print(f"\nTotal test cases: {len(test_cases)}")
    print(f"Pending (no deepwiki_answer): {len(pending)}")
    
    if not pending:
        print("\nAll test cases already have answers!")
        return
    
    # Limit if requested
    if max_questions:
        pending = pending[:max_questions]
        print(f"Processing first {len(pending)} questions")
    
    print("\nConnecting to DeepWiki MCP server...")
    
    # MCP server configuration for DeepWiki
    # Adjust the command based on your DeepWiki MCP server setup
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@deepwiki/mcp-server"],
        env=None
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("✓ Connected to DeepWiki MCP server\n")
                
                # Process each pending test case
                for i, (idx, tc) in enumerate(pending, 1):
                    question = tc.get('question', '')
                    repo = tc.get('pr_data', {}).get('repository', 'unknown/repo')
                    
                    print(f"[{i}/{len(pending)}] Processing question {idx}")
                    print(f"  Repo: {repo}")
                    print(f"  Question: {question[:80]}...")
                    
                    try:
                        # Query DeepWiki
                        answer = await query_deepwiki_with_mcp(
                            question, repo, session, anthropic_client
                        )
                        
                        # Save answer
                        test_cases[idx]['deepwiki_answer'] = answer
                        print(f"  ✓ Got answer ({len(answer)} chars)\n")
                        
                        # Auto-save after each question
                        save_test_cases(test_cases, output_file)
                        
                    except Exception as e:
                        print(f"  ✗ Error: {e}\n")
                        test_cases[idx]['deepwiki_answer'] = None
                        test_cases[idx]['deepwiki_error'] = str(e)
                
                print(f"\n✓ Completed! Results saved to: {output_file}")
                
    except Exception as e:
        print(f"\n✗ Failed to connect to MCP server: {e}")
        print("\nTroubleshooting:")
        print("  1. Ensure DeepWiki MCP server is installed:")
        print("     npm install -g @deepwiki/mcp-server")
        print("  2. Check that npx is available in your PATH")
        print("  3. Verify the MCP server command is correct")
        sys.exit(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Query DeepWiki using MCP and Claude API"
    )
    parser.add_argument(
        "input_file",
        help="Input JSON file with test cases"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file (default: input file with '_with_answers' suffix)",
        default=None
    )
    parser.add_argument(
        "-n", "--max-questions",
        type=int,
        help="Maximum number of questions to process",
        default=None
    )
    
    args = parser.parse_args()
    
    # Determine output file
    if args.output:
        output_file = args.output
    else:
        # Create output filename
        input_path = Path(args.input_file)
        output_file = str(input_path.parent / f"{input_path.stem}_with_answers.json")
    
    # Run async process
    asyncio.run(process_test_cases(args.input_file, output_file, args.max_questions))


if __name__ == "__main__":
    main()
