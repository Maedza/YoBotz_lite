# Contributing to YoBotz Lite

Thanks for your interest in contributing! This document describes the development workflow, code quality expectations, and the standards every change must meet.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Code Quality Guidelines](#code-quality-guidelines)
3. [Code Style and Tests](#code-style-and-tests)
4. [Pull Requests](#pull-requests)
5. [CI and Checks](#ci-and-checks)
6. [Contact / Support](#contact--support)

---

## Getting Started

1. Fork the repository and create a feature branch from `main` (or your working branch):

   ```bash
   git checkout -b feat/your-feature
   ```

2. Install dependencies and create a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

---

## Code Quality Guidelines

These rules are non-negotiable. Every contribution must respect them:

1. **Never remove thread safety mechanisms** — e.g. `threading.RLock()` in shared state managers. They protect multi-user/multi-platform concurrency.
2. **Verify all method calls before deletion** — grep for callers/imports before removing any method or function.
3. **Never touch WhatsApp/Telegram message firing** — platform integration code is off-limits unless the change is explicitly requested.
4. **Preserve fallback patterns** — `try/except` fallbacks for optional dependencies (Redis, external APIs) are intentional. Keep them.
5. **One method, one responsibility** — avoid duplicate logic within a file; reuse shared methods.
6. **No verbose debug code in production** — remove excess debug prints and debugging blocks before committing.
7. **Minimal and efficient implementation** — resolve one issue at a time; avoid unnecessary file fragmentation or module splitting.
8. **Use proper logging, not `print()`** — use the configured `logger`, never `print()` statements.

---

## Code Style and Tests

- Keep changes focused and well-scoped.
- Run tests before opening a PR:

  ```bash
  pytest -q
  ```

- If you add or change behavior, add or update tests.
- Match the existing style: modern Python, clear naming, minimal comments.

---

## Pull Requests

- Open a PR from your fork and include a clear description of the change and **why** it is needed.
- Link any related issues.
- Address review comments in follow-up commits.

---

## CI and Checks

- We recommend adding CI to run `pytest` and linting; ask if you want a GitHub Actions workflow added.
- Before submitting, run a local sanity check:

  ```bash
  pytest -q
  python -m compileall -q <changed_modules>
  ```

---

## Contact / Support

- If unsure where to start, open an issue or message a repository maintainer.

Thank you for helping improve YoBotz Lite!
