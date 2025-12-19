# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cf-tool is a Python CLI for competitive programming on Codeforces. It's a rewrite of the original Go-based [cf-tool](https://github.com/xalanq/cf-tool).

## Common Commands

```bash
# Install in development mode
pip install -e .

# Run tests
pytest

# Format code
black cf/

# Lint
flake8 cf/

# Type check
mypy cf/
```

## Architecture

### Module Structure

- **cli.py** - Click-based CLI entry point. All commands defined here route to other modules.
- **session.py** - Authentication using DrissionPage (browser automation) for Cloudflare Turnstile bypass, then cloudscraper for subsequent HTTP requests. Sessions stored in `~/.cf/session`.
- **scraper.py** - BeautifulSoup-based parsing of Codeforces problem pages via cloudscraper.
- **parser.py** - Orchestrates problem downloading: creates directory structure (`contest_id/problem_id/`), saves test cases (`in1.txt`, `out1.txt`), generates solution files from templates.
- **tester.py** - Runs solutions against test cases. Handles compilation, execution, output comparison with whitespace normalization.
- **compiler.py** - Compiles C++/C/Java. Uses config-defined or default compiler commands.
- **runner.py** - Executes solutions with stdin/stdout handling, timeout enforcement. `ExecutionResult` class holds output, timing, error state.
- **submitter.py** - Posts solutions to Codeforces, extracts CSRF tokens, parses submission results.
- **config.py** - JSON config management at `~/.cf/config`. Supports dot notation for nested keys.
- **constants.py** - URLs, language IDs for submission, file patterns, default compiler commands.
- **utils.py** - Custom exceptions (`CFError` hierarchy), file detection, whitespace normalization.

### Key Patterns

- **Cloudflare bypass**: Login uses DrissionPage (real Chrome browser) to handle Turnstile. Subsequent requests use cloudscraper with saved cookies.
- **Test case flow**: `in{n}.txt` / `out{n}.txt` pattern. Output comparison normalizes trailing whitespace.
- **Language detection**: Based on file extension via `EXTENSION_TO_LANGUAGE` mapping.
- **Configuration**: Stored in `~/.cf/config` as JSON. Templates support `$PROBLEM$` and `$CONTEST$` variables.

### Directory Structure Created by Parse

```
{contest_id}/
└── {problem_id}/
    ├── in1.txt, out1.txt, ...  # Test cases
    ├── solution.cpp            # Generated from template
    └── problem.json            # Metadata
```

## Language IDs for Submission

When modifying submission logic, use IDs from `constants.py`:
- cpp: 89 (G++23), python: 31 (Python 3.8), java: 87 (Java 21)
