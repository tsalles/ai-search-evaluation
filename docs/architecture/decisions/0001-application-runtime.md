# 0001 Application Runtime

Status: Accepted  
Date: 2026-10-22

## Context

The generator needs reusable content generation and six native file renderers, operating locally with an existing authenticated Azure deployment. The user selected a Python library and local CLI during planning.

## Priorities and requirements

1. Native document handling: PDF, Word, Excel, and PowerPoint must retain inspectable text and tables.
2. Reusable phase boundaries: generation and rendering must be callable separately and together.
3. Local operational simplicity: the first release needs no hosted application or new Azure infrastructure.

## Options evaluated

| Option | Native handling | Phase reuse | Local simplicity | Cost or limitation |
|--------|-----------------|-------------|------------------|--------------------|
| Python library and CLI | Existing native libraries for all requested formats | Direct typed library functions and CLI | Meets | Requires disciplined cross-renderer fidelity checks |
| TypeScript library and CLI | Available libraries; PDF/Office choices require a separate evaluation | Meets | Meets | No existing TypeScript investment in this empty workspace |
| Hosted API/web application | Can use either ecosystem | Meets | Partial | Adds hosting, authentication, deployment, and service operations outside the requested local workflow |

## Decision

Use a Python library and CLI. This is the user-confirmed option and meets the ordered requirements without adding a hosted service.

## Consequences

Propose Python 3.12 as the initial compatibility baseline; verify and lock actual dependency versions during implementation. Library and CLI behavior must share public contracts. CI/remote hosting remains undecided. This decision does not approve unverified provider parameters or every rendering library.
