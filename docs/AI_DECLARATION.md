# Declaration of AI use

Team CSC21 (MOSAIC), INF2004 Embedded Systems.

We used AI coding assistants during this project. This page says which tools,
what we used them for, and what stayed with us.

## Tools

| Tool | Provider | Used through |
|---|---|---|
| Claude Code | Anthropic | Terminal and desktop app, working in this repository |
| Codex | OpenAI | Working in this repository |

The instructions we gave these tools so that they kept to fixed project decisions
(for example, that the node must run µT-Kernel 3.0 and talk MQTT) are in
[AGENTS.md](../AGENTS.md). [CLAUDE.md](../CLAUDE.md) points Claude Code at the
same file.

## What we used them for

- **Writing code.** Drafting and changing code in the node subsystems and the PC
  gateway, fusion engine, dashboard and simulator, from designs and decisions the
  team made.
- **Reviewing and debugging.** Reading code for bugs, explaining existing code,
  and checking changes against the course template's rules.
- **Testing.** Writing host and unit tests, and running them. Test-log rows that a
  tool ran on a member's behalf say so in the Tester column (for example
  "ZhiHao (run by Claude Code)").
- **Documentation.** Drafting READMEs, test logs, the decision log and other
  documents, and the presentation material.

## What stayed with the team

- **Design decisions.** The architecture, the choice of µT-Kernel, the MQTT
  design, the protocol, the classifier and the fusion rules were decided by the
  team; [docs/decision-log.md](decision-log.md) records who decided what and why.
- **Hardware.** All wiring, flashing, bench work and the demonstrations were done
  by team members.
- **Responsibility.** Each owner listed in [node/TEAM.md](../node/TEAM.md) is
  responsible for the code in their subsystem, and the team for the shared code,
  whoever or whatever drafted it.

## Commit history

Some commits from 8 to 27 October 2026 originally ended with a
`Co-Authored-By: Claude …` line, added automatically by Claude Code. On
26 November 2026 we removed that line from the commits written by team members,
so that GitHub's contributor list shows the people who made them. This
declaration replaces those lines. The two commits of the course template from
8 October were left as they are. [docs/commit-map.md](commit-map.md) lists each
rewritten commit's old and new ID, so the commit IDs cited in the test logs and
the decision log can still be followed.
