#!/bin/bash
# post-commit.sh
# Install: cp scripts/post-commit.sh .git/hooks/post-commit && chmod +x .git/hooks/post-commit
# Every commit is permanently recorded for agent context — zero effort.

echo "$(date '+%Y-%m-%d %H:%M') | $(git log -1 --oneline)" >> .sage-memory.md
