# Git Workflow / Quy trình Git

## Branching Strategy

```
main (production-ready)
  └── develop (integration)
        └── feature/xxx (feature branches)
```

## Commands

### Bắt đầu feature mới
```bash
# Luôn pull code mới từ main trước
git checkout main
git pull origin main

# Tạo branch mới
git checkout -b feature/ten-feature
```

### Commit theo nhóm
```bash
# 1. Thêm files liên quan
git add src/cli.py src/b1_extract/extract_text_and_heading.py

# 2. Commit với conventional commit
git commit -m "refactor: update CLI module docstrings"

# 3. Thêm các files khác
git add src/b2_convert/ src/b3_chunk/
git commit -m "refactor: add bilingual module docstrings to B2,B3"

# 4. Tiếp tục các commits khác...
```

### Push và tạo PR
```bash
# Push branch lên remote
git push -u origin feature/ten-feature

# Tạo PR bằng gh CLI
gh pr create --title "feat: mô tả feature" --body "Mô tả chi tiết"

# Hoặc tạo PR từ main
gh pr create --base main --head feature/ten-feature
```

### Quay lại main sau khi merge
```bash
git checkout main
git pull origin main
```

## Conventional Commits

| Type | Description |
|------|-------------|
| `feat:` | Feature mới |
| `fix:` | Bug fix |
| `refactor:` | Code refactor (không thay đổi behavior) |
| `docs:` | Thay đổi documentation |
| `chore:` | Thay đổi build process, dependencies |

## Ví dụ thực tế

```bash
# Bắt đầu
git checkout main
git pull origin main
git checkout -b docs/add-git-workflow

# Commit nhóm
git add docs/git-workflow.md docs/architecture.md
git commit -m "docs: add git workflow and architecture docs"

git add src/cli.py
git commit -m "refactor: add bilingual module docstring to CLI"

git add src/b1_extract/
git commit -m "refactor: update B1 module with Vietnamese docstrings"

git add src/b2_convert/ src/b3_chunk/ src/b4_merge/ src/b5_export/
git commit -m "refactor: update B2-B5 modules with bilingual docstrings"

# Push và PR
git push -u origin docs/add-git-workflow
gh pr create --title "docs: add git workflow documentation" --body "Add workflow docs and refactor module docstrings"

# Quay lại main
git checkout main
git pull origin main
```