# DeepWiki Evaluation Workflow

This directory contains scripts for evaluating DeepWiki's performance on the deep_code_bench dataset.

## Files

- `generate_test_cases.py` - Generates random test cases from the dataset
- `run_evaluation.py` - Helper script to manage test case progress
- `evaluate_results.py` - Analyzes results and generates evaluation report
- `test_cases.json` - Test cases file (generated)
- `evaluation_report.txt` - Final evaluation report (generated)

## Workflow

### Step 1: Generate Test Cases

Generate N random test cases from the dataset:

```bash
python3 generate_test_cases.py 20  # Generate 20 test cases
```

This creates `test_cases.json` with pending test cases.

### Step 2: Run Evaluation

Since DeepWiki is accessed via MCP tools (only available to Claude), the evaluation requires a semi-automated workflow:

```bash
# Show the next pending test case
python3 run_evaluation.py next
```

This will display:
- The question to ask DeepWiki
- The repo name
- Progress statistics

### Step 3: Query DeepWiki (via Claude)

Use Claude to call the MCP tool:

```
mcp__deepwiki__ask_question(repoName="...", question="...")
```

### Step 4: Record Answer (via Claude)

Have Claude record the answer using:

```python
from run_evaluation import record_answer
record_answer(index=<case_index>, answer="<deepwiki_answer>")
```

Or if there was an error:

```python
from run_evaluation import record_error
record_error(index=<case_index>, error_msg="<error_message>")
```

### Step 5: Repeat

Repeat steps 2-4 until all test cases are completed.

Check progress at any time:

```bash
python3 run_evaluation.py progress
```

### Step 6: Generate Report

Once all test cases are completed, generate the evaluation report:

```bash
python3 evaluate_results.py test_cases.json evaluation_report.txt
```

This will create a comprehensive report with:
- Overall statistics (correct/partial/incorrect)
- Breakdown by difficulty, type, and repo
- Individual test case results
- Fact coverage analysis

## Evaluation Metrics

The evaluation uses multiple metrics:

1. **Ground Truth Similarity** - Word overlap between DeepWiki answer and ground truth (0-1)
2. **Fact Coverage** - How many facts from ground truth are mentioned in the answer
3. **Overall Score** - Weighted combination: 60% GT similarity + 40% fact coverage

### Classification

- **Correct** (✅): Overall score ≥ 0.7
- **Partial** (⚠️): Overall score 0.4-0.7
- **Incorrect** (❌): Overall score < 0.4

## Example Session

```bash
# Generate 10 test cases
python3 generate_test_cases.py 10

# Show first test case
python3 run_evaluation.py next
# [outputs question for DeepWiki]

# (Claude queries DeepWiki and records answer)

# Show next test case
python3 run_evaluation.py next
# [outputs next question]

# Continue until done...

# Generate final report
python3 evaluate_results.py
```

## Notes

- Test cases are randomly sampled from the dataset
- The evaluation is deterministic once test cases are generated
- You can restart the evaluation process by regenerating test cases
- Partial completions are saved in test_cases.json
