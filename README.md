# DeepWiki Evaluation Pipeline

A comprehensive system for generating high-quality codebase questions from GitHub PRs and evaluating AI-powered code search systems.

## Overview

This pipeline creates evaluation test cases by:
1. Scraping substantive PRs from GitHub repositories
2. Filtering PRs for technical depth and quality
3. Generating codebase questions using Claude AI
4. Extracting atomic facts for evaluation
5. Collecting system answers (via Claude Code + MCP)
6. Evaluating answers using an LLM-as-judge approach

---

## Prerequisites

```bash
export GITHUB_TOKEN=your_github_token
export ANTHROPIC_API_KEY=your_anthropic_key
```

---

## Pipeline Steps

### 1. Finding PRs: Scraping GitHub

The scraper fetches merged PRs from specified repositories with quality filters to ensure substantive code changes.

**What it does:**
- Fetches merged PRs from configured repositories
- Checks up to 500 PRs per repository (stops early if PRs become too old)
- Filters by file count (4-20 files changed)
- Excludes trivial changes (docs, configs, tests-only)
- Captures full PR metadata and git patches
- Supports incremental scraping with checkpointing

**Configuration:** Edit `data/config.yaml`
```yaml
repositories:
  - owner: huggingface
    name: transformers
    
pr_filters:
  min_files_changed: 4
  max_files_changed: 20
  min_description_length: 50
  created_before: "2024-11-01"
  
max_prs_per_repo: 50
```

**Command:**
```bash
python3 scrape_prs.py
```

**Output:** `data/prs_raw/huggingface_transformers/prs.json`

---

### 2. Filtering PRs: Quality Control

Uses Claude to filter out low-quality PRs and keep only those with substantial technical content suitable for generating meaningful questions.

**What it does:**
- Automatically processes all repositories in `data/prs_raw/`
- Reviews PR title, description, and code changes for each PR
- Filters out: typo fixes, formatting changes, config updates, trivial refactors
- Accepts: new features, bug fixes with logic changes, algorithmic improvements
- Provides reasoning for each accept/reject decision
- Assigns substance level (low/medium/high)
- Combines all filtered PRs into a single output file with `repository` field

**Filtering Criteria (from `prompts/pr_filter.txt`):**
- **Accept:** New features, bug fixes with logic, performance improvements, algorithmic changes
- **Reject:** Typos, formatting, pure config changes, trivial refactors

**Command:**
```bash
python3 filter_prs.py
```

**Outputs:**
- `data/prs_raw/all_prs_filtered.json` - **Combined filtered PRs from all repositories**
- `data/prs_raw/all_prs_rejected.json` - Rejected PRs for analysis
- `data/prs_raw/all_prs_filter_summary.json` - Summary with per-repo breakdown

---

### 3. Obtaining Questions: Claude-Generated Questions

Generates focused codebase questions from filtered PRs using Claude Sonnet with carefully designed prompts.

**What it does:**
- Uses git patches (diffs) instead of full files for efficiency
- Generates 1 question per PR focused on the code changes
- Questions test understanding of implementation details
- Includes ground truth answers with specific code references
- Classifies questions by scope (deep/broad) and importance (core/non-core)

**Question Guidelines (from `prompts/question_generation_system.txt`):**
- Must be grounded in actual code context
- No file paths or line numbers in the question itself
- Prefer questions spanning multiple components
- Keep wording concise and clear
- Avoid overly obvious identifier references (make search challenging)
- Should be answerable in 2-3 sentences
- Answers MUST reference specific files, classes, and methods

**Examples:**
- **Deep:** "When the processor encounters video input without an explicitly provided fps parameter, how does it determine what frame rate to use?"
- **Broad:** "How does the attention mechanism coordinate state between encoder and decoder components?"

**Commands:**
```bash
# Process all filtered PRs (uses patches by default)
python3 generate_questions.py data/prs_raw/huggingface_transformers/prs_filtered.json

# Process limited number for testing
python3 generate_questions.py data/prs_raw/huggingface_transformers/prs_filtered.json --n_prs 10

# Use full files instead of patches (slower, more context)
python3 generate_questions.py data/prs_raw/huggingface_transformers/prs_filtered.json --use_full_files
```

**Output:** `data/questions/huggingface_transformers_questions.json`

**Format:**
```json
{
  "pr_data": {...},
  "questions": [
    {
      "question": "...",
      "answer": "...",
      "scope": "deep",
      "is_core_question": true,
      "key_files": ["file1.py", "file2.py"]
    }
  ]
}
```

---

### 4. Obtaining Facts: Atomic Fact Extraction

Extracts 2-5 atomic, verifiable facts from each question-answer pair for structured evaluation.

**What it does:**
- Analyzes ground truth answers
- Extracts independent, verifiable facts
- Each fact is a single, self-contained statement
- Facts are specific (mention classes, methods, parameters)
- Focuses on essential information, not peripheral details

**Fact Guidelines (from `prompts/fact_generation_system.txt`):**
- 2-5 facts per answer
- Atomic: Each fact stands alone
- Verifiable: Can be checked independently
- Specific: Includes code identifiers
- Concise: 1-2 sentences maximum

**Example:**
```
Question: "How does the cache system coordinate state management?"
Answer: "The EncoderDecoderCache contains two separate DynamicCache instances..."

Facts:
1. EncoderDecoderCache contains two separate DynamicCache instances
2. One DynamicCache is used for self_attention_cache
3. Another DynamicCache is used for cross_attention_cache
4. BltModel.forward() extracts these caches from EncoderDecoderCache
```

**Commands:**
```bash
# Process all questions
python3 generate_facts.py data/questions/huggingface_transformers_questions.json

# Process limited number for testing
python3 generate_facts.py data/questions/huggingface_transformers_questions.json --n_prs 5
```

**Outputs:**
- `data/questions_with_facts/huggingface_transformers_questions_with_facts.json` - Full data
- `data/questions_with_facts/huggingface_transformers_test_cases.json` - Evaluation-ready format

**Test Case Format:**
```json
{
  "id": "uuid",
  "question": "...",
  "ground_truth_answer": "...",
  "facts": ["fact1", "fact2", "fact3"],
  "metadata": {
    "difficulty": "hard",
    "scope": "deep",
    "is_core_question": true,
    "key_files": [...]
  },
  "deepwiki_answer": ""  // To be filled by your system
}
```

---

### 5. Generating Responses: Claude Code + MCP

**Manual Step:** Use your AI system to answer each question.

For Claude Code with DeepWiki MCP integration:
1. Load the test cases JSON file
2. For each question, query DeepWiki using the MCP tool:
   ```
   deepwiki - ask_question(repoName: "huggingface/transformers", question: "...")
   ```
3. Collect the response and populate the `deepwiki_answer` field
4. Save the updated JSON file

**Alternative:** You can use any system - just populate the `deepwiki_answer` field with your system's responses.

---

### 6. Grading Questions: LLM-as-Judge Evaluation

Evaluates system answers against ground truth using Claude with a structured rubric.

**Evaluation Rubric:**

The evaluation uses three weighted metrics:

#### **F: Factual Correctness (0-10)** - Weight: 2x
- Are the facts in the system answer accurate?
- Does it contain any hallucinations or incorrect information?
- Is the technical information precise?

**Scoring:**
- 9-10: Completely accurate, no errors
- 7-8: Mostly accurate, minor imprecisions
- 5-6: Some errors but core information correct
- 3-4: Significant factual errors
- 0-2: Mostly or completely incorrect

#### **C: Fact Coverage (0-10)** - Weight: 1x
- How many of the ground truth facts are covered?
- Percentage-based: (facts_covered / total_facts) * 10

**Scoring:**
- 10: Covers all facts (100%)
- 8: Covers 80% of facts
- 5: Covers 50% of facts
- 0: Covers none of the facts

#### **S: Specificity (0-10)** - Weight: 1x
- Does the answer reference specific code elements?
- Are class names, method names, file paths mentioned?
- Is it concrete or vague?

**Scoring:**
- 9-10: Highly specific with multiple code references
- 7-8: Reasonably specific with some references
- 5-6: Some specificity but mostly general
- 3-4: Vague with few concrete details
- 0-2: Completely generic, no code references
- N/A: Question doesn't require specificity

#### **Final Score Calculation:**
```
Final Score = (2 × Factual + Coverage + Specificity) / 40
```

This gives a score between 0.0 and 1.0, with factual correctness weighted twice as heavily as the other metrics.

**Command:**
```bash
python3 evaluate_generic.py data/questions_with_facts/huggingface_transformers_test_cases.json

# Specify different answer field name
python3 evaluate_generic.py data/questions_with_facts/test_cases.json my_system_answer

# Specify custom output file
python3 evaluate_generic.py data/questions_with_facts/test_cases.json deepwiki_answer my_report.txt
```

**Output:** `evaluation_report.txt`

**Report Contents:**
- Overall statistics (mean, median, std dev)
- Score distribution by quartile
- Per-question breakdown with:
  - Final score and raw score
  - Individual metric scores (F, C, S)
  - Question metadata (difficulty, scope)
  - Full question, ground truth, and system answer
  - Detailed analysis and reasoning

---

## Quick Start: Full Pipeline

Run the complete pipeline on all configured repositories:

```bash
# 1. Configure scraping (edit data/config.yaml first)
#    Enable desired repositories
#    Set max_prs_per_repo (e.g., 10 for testing)

# 2. Scrape PRs from all enabled repositories
python3 scrape_prs.py
# Output: data/prs_raw/{owner}_{repo}/prs.json for each repo

# 3. Filter PRs for quality (automatically processes all repos)
python3 filter_prs.py
# Output: data/prs_raw/all_prs_filtered.json (combined)

# 4. Generate questions from filtered PRs
python3 generate_questions.py data/prs_raw/all_prs_filtered.json --n_prs 10
# Output: data/questions/{owner}_{repo}_questions.json for each repo

# 5. Extract facts (run for each repository)
python3 generate_facts.py data/questions/huggingface_transformers_questions.json --n_prs 5
python3 generate_facts.py data/questions/Dao-AILab_flash-attention_questions.json --n_prs 5
# ... repeat for other repos

# 6. Answer questions with your system
#    (populate deepwiki_answer field in test_cases.json)

# 7. Evaluate (run for each repository)
python3 evaluate_generic.py \
  data/questions_with_facts/huggingface_transformers_test_cases.json
```

---

## Directory Structure

```
deepwiki_eval/
├── README.md                          # This file
├── PIPELINE.md                        # Detailed pipeline documentation
│
├── scrape_prs.py                      # Step 1: PR scraping
├── filter_prs.py                      # Step 2: PR filtering
├── generate_questions.py              # Step 3: Question generation
├── generate_facts.py                  # Step 4: Fact extraction
├── evaluate_generic.py                # Step 6: Evaluation
│
├── prompts/
│   ├── pr_filter.txt                  # PR filtering criteria
│   ├── question_generation_system.txt # Question generation guidelines
│   ├── question_generation_user.txt   # Question generation template
│   ├── fact_generation_system.txt     # Fact extraction guidelines
│   ├── fact_generation_user.txt       # Fact extraction template
│   └── evaluation_prompt.txt          # Evaluation rubric
│
└── data/
    ├── config.yaml                    # Scraping configuration
    ├── prs_raw/
    │   ├── all_prs_filtered.json      # Combined filtered PRs (all repos)
    │   ├── all_prs_rejected.json      # Combined rejected PRs
    │   ├── all_prs_filter_summary.json # Filter summary by repo
    │   ├── summary.json               # Scraping summary
    │   ├── huggingface_transformers/
    │   │   ├── prs.json               # Raw scraped PRs
    │   │   └── checkpoint.json        # Scraping progress
    │   ├── Dao-AILab_flash-attention/
    │   │   ├── prs.json
    │   │   └── checkpoint.json
    │   └── ... (other repos)
    ├── questions/
    │   ├── huggingface_transformers_questions.json
    │   └── ... (per repo)
    └── questions_with_facts/
        ├── huggingface_transformers_questions_with_facts.json
        ├── huggingface_transformers_test_cases.json
        └── ... (per repo)
```

---

## Configuration Files

### `data/config.yaml`
Configure repositories and PR filters:
```yaml
repositories:
  - owner: huggingface
    name: transformers

pr_filters:
  min_files_changed: 4
  max_files_changed: 20
  min_description_length: 50
  exclude_patterns:
    - "^docs/"
    - "\\.md$"
    - "^tests/"

max_prs_per_repo: 50
```

### Prompt Files
All prompts use a system/user split for better Claude API usage:
- **System prompts**: Static guidelines and examples
- **User prompts**: Dynamic data (PR info, questions, etc.)

---

## Tips & Best Practices

### Efficiency
- **Use patches (default)**: 10-20x smaller than full files, much faster
- **Test small first**: Use `--n_prs 3` to validate before scaling
- **Monitor costs**: Sonnet-4.5 is used for quality; switch to Haiku if needed
- **Smart scraping**: The scraper checks max 500 PRs per repo and stops early when encountering old PRs (saves API calls)

### Quality Control
- **Review filtered PRs**: Check `prs_filtered.json` before generating questions
- **Check questions**: Review generated questions for quality and relevance
- **Iterate on prompts**: Adjust prompt files based on output quality

### Scaling
- **Incremental scraping**: Scraper supports checkpointing for large repos
- **Batch processing**: Process PRs in batches with `--n_prs` flag
- **Parallel evaluation**: Run multiple evaluation jobs in parallel if needed

---

## Model Usage

- **PR Filtering**: Claude Sonnet 4.5 (requires good judgment)
- **Question Generation**: Claude Sonnet 4.5 (needs quality outputs)
- **Fact Extraction**: Claude Sonnet 4.5 (precision matters)
- **Evaluation**: Claude Sonnet 3.5 (rubric-based scoring)

You can modify model selections in the respective scripts if needed.

---

## Cost Estimation

Approximate costs for 50 PRs (using Sonnet 4.5):

| Step | API Calls | Est. Cost |
|------|-----------|-----------|
| Filter PRs | 50 | $0.50 |
| Generate Questions | 50 | $2.00 |
| Generate Facts | 50 | $1.00 |
| Evaluate | 50 | $2.50 |
| **Total** | **200** | **~$6.00** |

Costs vary based on PR size and complexity.

---

## Troubleshooting

### "No module named 'anthropic'"
```bash
pip install anthropic
```

### "GITHUB_TOKEN not set"
```bash
export GITHUB_TOKEN=your_token
```

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY=your_key
```

### "No results found for question"
Ensure the test cases JSON has the `deepwiki_answer` field populated.

### Questions seem too simple/complex
Adjust the guidelines in `prompts/question_generation_system.txt`.

---

## Contributing

To adapt this pipeline for your own repository:

1. Update `data/config.yaml` with your repository details
2. Adjust PR filters based on your repo's structure
3. Modify prompts to match your codebase characteristics
4. Test with small batches first

---

## License

MIT License - See LICENSE file for details
