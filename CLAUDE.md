# Project Rules

## Python

- Python 3.12+, type hints where useful
- SOLID, composition over inheritance
- No unnecessary abstractions - simple > clever
- External input (filenames, API responses) must be sanitized
- Save critical data (transcript) before risky operations (moving files)
- Use subprocess.run with input= for large payloads, never pass large strings as CLI arguments (ARG_MAX limit ~256KB on macOS)
- Handle external service failures gracefully (save what you can, skip what you can't)

## Shell Scripts

- Always `set -euo pipefail`
- Quote ALL variables: `"$var"` not `$var`
- Use `if grep ...; then continue; fi` instead of `grep ... && continue` (the latter breaks under `set -e` when grep returns 1)
- Create required directories with `mkdir -p` before writing files
- Don't export secrets broadly with `set -a; source .env` - read only needed vars with `grep`
- Use `lsof` to check if a file is still being written before processing
- Lock files for preventing parallel execution
- Log both stdout and stderr to files, not just capture in variables

## General

- Secrets (.env, tokens) never in git
- Conventional commits format
- No Co-Authored-By or AI attribution in commits
- README in English for public repos
- Test edge cases: empty input, large input, missing dependencies, no network
