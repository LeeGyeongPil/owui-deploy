# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-12

### Added
- `lint`: static (ast, no code execution) checks OWD001-OWD009 for Open WebUI Tools and Functions.
- `plan`: compare a git folder with a server (content, name, description, active/global), `--diff`, `--json`.
- `apply`: create/update, toggle only when the state differs, delete only with `--prune`, `commit_message` from `--message` or the git short hash.
- `pull`: export to files without writing valves values.
- `--fake`: built-in practice mock of Open WebUI 0.13.3 behaviour.
- English and Korean output (`--lang`, `OWUI_DEPLOY_LANG`).
- Exit codes: 0 no difference, 1 difference or problem found, 2 tool error.
