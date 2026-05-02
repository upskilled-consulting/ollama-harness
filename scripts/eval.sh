#!/bin/bash
# Pi/qwen task completion eval
# Run from inside Pi with: ! bash ~/Desktop/harness-engineering/eval.sh
# Or standalone: bash eval.sh

PASS=0
FAIL=0
RESULTS=()

check_file() {
  local path=$1
  local min_lines=${2:-5}
  local desc=$3

  expanded="${path/#\~/$HOME}"

  if [ -f "$expanded" ] && [ "$(wc -l < "$expanded")" -ge "$min_lines" ]; then
    RESULTS+=("  PASS  $desc")
    ((PASS++))
  else
    if [ ! -f "$expanded" ]; then
      RESULTS+=("  FAIL  $desc — file not found: $expanded")
    else
      RESULTS+=("  FAIL  $desc — file exists but has fewer than $min_lines lines")
    fi
    ((FAIL++))
  fi
}

# --- Add expected output artifacts here after each session ---
check_file ~/Desktop/harness-engineering/verification-patterns.md 10 "verification-patterns.md (task 1)"
# check_file ~/Desktop/harness-engineering/next-task-output.md 5 "next task output"

# --- Report ---
echo ""
echo "==============================="
echo " Pi Task Completion Eval"
echo "==============================="
for r in "${RESULTS[@]}"; do echo "$r"; done
echo "-------------------------------"
echo " Passed: $PASS  Failed: $FAIL"
echo "==============================="
echo ""
