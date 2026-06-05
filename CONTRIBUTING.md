# Contributing to GhostVPN

Thanks for your interest! Here's how to help.

## Reporting bugs

Open a [GitHub Issue](https://github.com/20player11/GhostVPN/issues/new) with:

- Steps to reproduce
- Expected vs actual behavior
- Platform (OS, Python version)
- Logs if possible (`--verbose` flag)

## Requesting features

Open a [GitHub Issue](https://github.com/20player11/GhostVPN/issues/new) describing:

- What you want to achieve
- Why existing functionality isn't enough
- Any implementation ideas (optional)

## Pull requests

1. Fork the repo
2. Create a branch off `main`
3. Write code — follow the existing style (no `else`, no `try`/`except` unless necessary, short variable names)
4. Test your changes: `python vpn.py --cli --mode socks --interval 300`
5. Open a PR to `main`

## Code style

- Single-word variable names by preference
- No `else` — use early returns
- Avoid `try`/`except` where possible
- Functional style (`map`, `filter`) over imperative loops
- Snake case for everything

## Security

See [SECURITY.md](SECURITY.md) for vulnerability disclosure.
