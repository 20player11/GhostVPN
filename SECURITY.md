# Security Policy

## Reporting a Vulnerability

GhostVPN takes security seriously. If you discover a security vulnerability, please report it privately.

**Do not report security vulnerabilities via public GitHub issues.**

### How to report

1. **GitHub Private Vulnerability Reporting** (preferred):  
   Go to https://github.com/20player11/GhostVPN/security/advisories/new

2. **Email**: Send details to the repository owner via their GitHub profile.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact
- Any suggested fixes (if known)

### Response timeline

- **24 hours**: Acknowledgment of receipt
- **7 days**: Initial assessment and remediation plan
- **30 days**: Fix released or coordinated disclosure

## Scope

The following are considered in scope:

- Remote code execution
- Privilege escalation (e.g., from non-root to root via GhostVPN)
- Exposure of sensitive data (proxy credentials, logs)
- Network-level attacks facilitated by GhostVPN (e.g., DNS leaks, routing bypass)

The following are **out of scope**:

- Dependency CVEs (report them to the respective projects)
- Theoretical attacks without proof of concept
- Proxy list reliability or uptime
- Social engineering of project maintainers

## Supported versions

| Version | Supported |
| ------- | --------- |
| latest  | ✅ Yes    |
| older   | ❌ No     |

## Recognition

We believe in coordinated disclosure and will credit researchers who report valid vulnerabilities (with their consent).
