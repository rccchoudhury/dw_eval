# DeepWiki Evaluation Pipeline

Complete pipeline for generating evaluation test cases from GitHub PRs.

## Prerequisites

```bash
export GITHUB_TOKEN=your_github_token
export ANTHROPIC_API_KEY=your_anthropic_key
```

## Pipeline Steps

### 1. Scrape PRs from GitHub

Fetch high-quality PRs based on filters:

```bash
python3 scrape_prs.py
```

**Output**: `data/prs_raw/huggingface_transformers/prs.json`

**Configuration**: Edit `data/config.yaml` to:
- Set `max_prs_per_repo` (e.g., 50)
- Adjust file count filters (`min_files_changed`, `max_files_changed`)
- Set date cutoffs (`created_before`)

---

### 2. Filter PRs for Substance

Use Claude to filter out low-quality PRs:

```bash
python3 filter_prs.py
```

**Input**: `data/prs_raw/huggingface_transformers/prs.json`  
**Output**: `data/prs_raw/huggingface_transformers/prs_filtered.json`

This removes PRs with:
- Trivial changes (typos, formatting)
- Empty descriptions
- Pure config/dependency updates
- No substantive logic

---

### 3. Generate Questions from PRs

Use Claude to generate codebase questions:

```bash
# Process all filtered PRs (default: uses patches)
python3 generate_questions.py \
  data/prs_raw/huggingface_transformers/prs_filtered.json

# Or limit to first N PRs for testing
python3 generate_questions.py \
  data/prs_raw/huggingface_transformers/prs_filtered.json \
  --n_prs 10

# Use full files instead of patches (slower, more context)
python3 generate_questions.py \
  data/prs_raw/huggingface_transformers/prs_filtered.json \
  --n_prs 10 \
  --use_full_files
```

**Output**: `data/questions/huggingface_transformers_questions.json`

Each question includes:
- `question`: The codebase question
- `answer`: Ground truth answer
- `scope`: "broad" or "deep"
- `is_core_question`: Boolean
- `key_files`: Relevant file paths

---

### 4. Generate Facts from Questions

Extract atomic facts from question-answer pairs:

```bash
# Process all questions
python3 generate_facts.py \
  data/questions/huggingface_transformers_questions.json

# Or limit to first N PRs
python3 generate_facts.py \
  data/questions/huggingface_transformers_questions.json \
  --n_prs 10
```

**Outputs**:
- `data/questions_with_facts/huggingface_transformers_questions_with_facts.json`
- `data/questions_with_facts/huggingface_transformers_test_cases.json` (QODO format)

Each test case includes:
- Question + ground truth answer
- 2-5 atomic facts for evaluation
- Metadata (difficulty, scope, key files)
- UUID for tracking

---

### 5. Run DeepWiki to Get Answers

**Manual Step**: Query your DeepWiki instance with each question and record answers.

Format answers as:
```json
[
  {
    "id": "test_case_uuid",
    "question": "...",
    "ground_truth_answer": "...",
    "deepwiki_answer": "YOUR SYSTEM'S ANSWER HERE",
    "facts": [...],
    "metadata": {...}
  }
]
```

Save to: `data/deepwiki_results/huggingface_transformers_results.json`

---

### 6. Evaluate Results

Run LLM-based evaluation:

```bash
python3 evaluate_generic.py \
  data/questions_with_facts/huggingface_transformers_test_cases.json \
  data/deepwiki_results/huggingface_transformers_results.json
```

**Output**: `evaluation_report.txt`

Evaluation metrics:
- **Factual Correctness** (0-10): Accuracy of information
- **Fact Coverage** (0-10): Percentage of facts covered
- **Specificity** (0-10): Code references provided
- **Final Score**: `(2*Correctness + Coverage + Specificity) / 40`

---

## Quick Start (Testing)

Test the full pipeline with 3 PRs:

```bash
# 1. Scrape (edit config first to set max_prs_per_repo: 10)
python3 scrape_prs.py

# 2. Filter
python3 filter_prs.py

# 3. Generate questions
python3 generate_questions.py \
  data/prs_raw/huggingface_transformers/prs_filtered.json \
  --n_prs 3

# 4. Generate facts
python3 generate_facts.py \
  data/questions/huggingface_transformers_questions.json \
  --n_prs 3

# 5. View test cases
cat data/questions_with_facts/huggingface_transformers_test_cases.json
```

---

## Output Structure

```
data/
├── prs_raw/
│   └── huggingface_transformers/
│       ├── prs.json                    # Raw scraped PRs
│       ├── prs_filtered.json           # Filtered PRs (substance check)
│       └── checkpoint.json             # Scraping progress
├── questions/
│   └── huggingface_transformers_questions.json  # Questions without facts
└── questions_with_facts/
    ├── huggingface_transformers_questions_with_facts.json
    └── huggingface_transformers_test_cases.json  # Ready for evaluation
```

---

## Configuration Files

- **`data/config.yaml`**: PR scraping filters and repo list
- **`prompts/question_generation_system.txt`**: Question generation guidelines
- **`prompts/question_generation_user.txt`**: Question prompt template
- **`prompts/fact_generation.txt`**: Fact extraction prompt
- **`prompts/evaluation_prompt.txt`**: Evaluation criteria
- **`prompts/pr_filter.txt`**: PR filtering criteria

---

## Tips

- **Use patches (default)**: 10-20x smaller context, faster, cheaper
- **Start small**: Test with `--n_prs 3` before running full pipeline
- **Monitor costs**: Sonnet-4.5 is used for quality; adjust model in scripts if needed
- **Check quality**: Review filtered PRs and generated questions before scaling up
- **Iterate prompts**: Adjust prompt files based on output quality
