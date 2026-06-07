# Contributing to this project

## Branch model: **github_flow** — primary branch: `main`

## Rules

- **Fork the repository** and create your feature branch from `main`.
- **Branch Naming**: Use descriptive branch names like `feat/add-new-feature` or `fix/bug-description`.
- **Commit Messages**: Follow the Conventional Commits specification (e.g., `feat: add new API endpoint`). Use `cz commit` for guidance.
- **Run Pre-commit Hooks**: Ensure all pre-commit checks pass before pushing (`pre-commit install && pre-commit run --all-files`).
- **Create Pull Requests**: Target the `main` branch. Provide a clear description using the PR template.
- **Code Style**: Adhere to PEP 8 and project-specific formatting (enforced by `black` and `flake8`).
- **Testing**: Add unit tests for new features or bug fixes. Ensure existing tests pass.
- **Review Process**: Address reviewer comments promptly. A PR must have at least one approval.
- **Squash and Merge**: PRs will be squashed and merged to `main` to maintain a clean linear history.

## Releasing
Releases are managed by the configured release tool — humans should not manually edit version numbers or `CHANGELOG.md`.
