# AGENTS.md
## General Rules
- You **MUST** maintain this file and add useful context as part of each feature we build
- You **NEVER** modify or otherwise override any rule I define in the [Global Rules](#global-rules) H1

# Global Rules
## Git Rules
### General Git Rules
- **ALWAYS** do your your work from a feature branch - not from main!
- **ALWAYS** base your your branches on latest main branch - no complex branching strategies
- **ALWAYS** use [conventional branches](https://conventionalbranch.org/#spec) for your branch names
- **ALWAYS** use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#specification)
- **ALWAYS** keep commit messages below 75 words. If 75 words cannot convey necessary context for a commit, that is a hint the commit contains too many changes - break it up.
- **NEVER** create monolithic commits like "refactor codebase" or "implement new data model". Commits should contain complete changes, but not necessarily all changes required for the current feature.
- **ALWAYS** include a co-author statement in commits you author on my behalf in the commit footer, like below. This footer does not count against commit message length constraints specified above.
```shell
Co-authored-by: ${MODEL_PROVIDER} - ${MODEL_MAKING_THE_COMMIT} <${MODEL_PROVIDER_LOWERCASE_SNAKECASE}@${MODEL_PROVIDER_WEBSITE}>

# Example
Co-authored-by: DeepSeek - Flash 4.1 <deepseek@deepseek.com>
```

### Safety
- **NEVER** update git config
- **NEVER** run destructive commands (--force, hard reset) without explicit request
- **NEVER** skip hooks (--no-verify) unless user asks
- **NEVER** force push to main/master
- **ALWAYS** fix and create NEW commit (don't amend) if commit fails due to hooks

## Project Toolchain
- Use pre-commit hooks to ensure any code included in this project is linted/formatted/bugchecked/etc.
- Prefer Python for code in the repository
  - use uv to manage python environment, dependencies, etc. (https://github.com/astral-sh/uv)
  - use ruff for formatting, linting, etc. (https://github.com/astral-sh/ruff)
  - Configure all possible settings in pyproject.toml rather than tool-specific config files
- Use Shell sparingly if at all
- Use Task for repeatable tasks (https://taskfile.dev)
- When at all possible whatever runs in GitHub actions should also be able to run local (exceptions can be made - ask if there's a trade-off). This implies that most github actions are just invocations of a given Task task
- If there are a lot of system level dependencies (e.g. linux utilities, dev header files, etc.) bias towards building a Dockerfile that sets up that build container rather than installing any utilities locally on Mac

## Software Rules
- Follow good software patterns (POLA, SRP, DRY, abstractions and interfaces, favor composition over inheritance, etc.)
- Use abstractions where it's useful, but follow the rule of threes

# END Global Rules
