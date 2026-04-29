# Agent Notes

Use in-repo worktrees for parallel work:

```bash
mkdir -p .worktrees
git worktree add .worktrees/<name> -b <branch> origin/main
```

Do not create sibling worktrees such as `../switch-main` for agent work. In-repo worktrees stay under the workspace writable root, while sibling directories may require escalated filesystem permissions for ordinary build and Git operations.
