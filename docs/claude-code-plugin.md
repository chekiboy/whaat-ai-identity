# Claude Code plugin

The plugin connects Claude Code to whaat. Its skills tell the agent what to observe and write down; its hooks make sure the agent sees its memory at the right moments, without having to remember to look. `whaat connect` installs it (see [Identities](identities.md)).

The plugin is a thin layer: most skills and hooks call the Whaat server, which does the actual work. Without a token the hooks stay silent, except `memory-write-guard`, which still declines writes into Claude Code's own memory folders.

## Skills

The agent calls most of them on its own when the work fits. You can also call them yourself as `/whaat:<name>`.

| Skill | When it runs | What it does |
|---|---|---|
| `memory` | Something should outlast the session; at the end of a task | Saves, updates or deletes a memory; records how recalled memories went |
| `memory-recall` | Before every reply, and before a push, commit or cloud call | Lists the triggers that apply and opens the memories that fit |
| `memory-curation` | You ask to tidy the memory, or a memory proved wrong | Writes a curation report, then applies or reverts the rows you decided |
| `memory-migrate` | A new identity has an older memory on this machine | Brings that memory in, group by group, on your choice |
| `journal` | At session end, or when you ask for a session summary | Writes the journal entry and the session report |
| `decisions` | A run stops for your decisions | Puts the questions on a decisions page, waits until you send your answer and goes on from it |
| `session-end` | You end the session | Runs memory, skill proposals and journal, in that order |
| `skill-proposals` | A procedure was repeated during the work; at session end | Notes candidates, then proposes them as skills and asks |

Details: [Memory](memory.md), [Curation](curation.md), [Migration](migration.md), [Journal and session end](journal.md).

## Hooks

Hooks are small scripts Claude Code runs by itself at fixed moments, such as a session start or a file read. Each runs through uv in exec form (`uv run --no-project --no-config python <hook>`), so it needs no shell and no particular name for Python, on any system, and the session repo's Python pins do not reach it. Exec-form hooks need Claude Code 2.1.139 or newer. Whaat's hooks never stop the session: when they decline something, they answer with what to do instead.

| Hook | When | What it does |
|---|---|---|
| `session-start` | A session starts | Starts the server if needed; puts in the personal core, the memory index that recall gives (global, project, repo and personal triggers, in parts) and a map of the memory folders. The text comes in several parts, because Claude Code caps each hook's output |
| `session-start` (compact) | Before the context is compacted | Logs the compaction, so the core and the index are put in again after it; prints nothing |
| `subagent-start` | A helper agent starts | Gives it the global index, the memory map, and the core files marked for every agent |
| `memory-frame` | After a recall, and on each of your messages | Puts an opened memory into the context, once per agent, so the agent treats it as your rule rather than as tool output; reminds the agent to recall before replying |
| `recall-guard` | Before a file read | Declines a direct read of a memory file and names the recall command to use instead |
| `memory-write-guard` | Before a file write | Declines writes into Claude Code's own memory folders and says where the memory goes in Whaat |
| `memory-outcome` | After a file read | Logs a read of a memory, and warns when it is history, uncertain or stale |

## With Claude Code's sandbox on

The skills run the `whaat` commands (`scripts/whaat`, through uv), and every command talks to the Whaat server on `127.0.0.1` and may start it. Inside Claude Code's sandbox that fails: the server is out of reach, and the state folder and uv's cache cannot be written. Allow the `whaat` commands, either by letting them run outside the sandbox or by allowing the server's port, the state folder and uv's cache (`uv cache dir`) in the sandbox settings (`/sandbox`). A command that can neither reach nor start the server says so and names the port and the state folder; when uv's cache is not writable, uv itself stops first, with its own error.

The hooks run outside the Bash tool, through uv, so the sandbox does not stop them.

## Why a recall rule in `CLAUDE.md` too

A plugin can bring skills and hooks, but not a standing instruction. `whaat connect` therefore adds a short rule to the config's `CLAUDE.md`: recall before every reply. The hooks remind the agent; the rule makes it a habit.
