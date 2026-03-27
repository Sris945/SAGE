#!/bin/bash
# sage-context.sh
# Fires on every `sage run` — injects full project context into the pipeline
# before the Planner sees the prompt.

CONTEXT=$(cat <<EOF
$(cat memory/system_state.json 2>/dev/null || echo "No prior state")
Recent commits: $(git log --oneline -5 2>/dev/null)
Modified files: $(git diff --name-only HEAD 2>/dev/null)
Current branch: $(git branch --show-current 2>/dev/null)
EOF
)

echo "$CONTEXT"
