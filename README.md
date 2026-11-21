# competition-agent

A competition economist and lawyer agent: expertise in industrial organisation
(IO) economics and competition law, focused on EU competition law. Built with
the [Mistral Agents SDK](https://docs.mistral.ai/studio/agents/getting-started/quickstart)
(`mistralai-agents`, imported as `from mistralai import agents`).

Give it Commission decisions, court judgments, or authority decisions to
summarise, and ask it competition-law and competition-economics questions.

The agent has:

- live web research — a `web_search` tool backed by Mistral's Conversations
  API `web_search` built-in, returning answers with cited sources;
- a networked Mistral sandbox (shell + Python) to fetch pages, download and
  parse PDFs (e.g. from EUR-Lex, CURIA or competition-policy.ec.europa.eu),
  and read files uploaded in chat;
- persistent cross-session memory — `read_memory` / `write_memory` tools that
  keep a compact rolling summary in `MEMORY.md` in this (private) repository
  via the GitHub Contents API.

## Run locally

```bash
uv sync
export MISTRAL_API_KEY=...   # from https://console.mistral.ai/api-keys
uv run agents chat
```

## Deploy (Mistral-managed)

Push this repository, then either run the `Deploy competition-agent` GitHub
Action (needs the `MISTRAL_API_KEY` repo secret), or:

```bash
uv run --env-file .env agents deploy --name competition-agent --yes \
  --secret-binding GITHUB_MEMORY_TOKEN=secret:workspace:GITHUB_MEMORY_TOKEN
```

or create a managed deployment of this Git repository in Mistral Studio
(Workflows > managed deployments).

## Persistent memory setup (one-time)

1. Make this repository **private** (the agent refuses to write memory to a
   public repo):
   `gh repo edit esulez/comp_agent --visibility private`
2. Create a GitHub token with **Contents: read & write** on this repo
   (fine-grained PAT at github.com/settings/tokens, or a classic PAT with
   `repo` scope). Never paste it into chat or commit it.
3. In the Mistral console, create a **workspace secret** named
   `GITHUB_MEMORY_TOKEN` with that token as its value.
4. Deploy with the binding shown above (the Actions workflow already passes
   `--secret-binding GITHUB_MEMORY_TOKEN=secret:workspace:GITHUB_MEMORY_TOKEN`;
   the binding is a reference by name — the value stays in the workspace
   secret store).

At the start of every session the agent calls `read_memory`; when you say
"remember this" (or it finishes a decision summary), it merges and calls
`write_memory`. `MEMORY.md` is a rolling summary, not a transcript — keep it
compact. Memory is global to everyone who uses this agent deployment.

Override the location with env vars `MEMORY_REPO` (default
`esulez/comp_agent`), `MEMORY_FILE` (default `MEMORY.md`), `MEMORY_BRANCH`
(default `main`).

## Use the deployed agent

- In a browser / Vibe: the managed-agents link printed by `agents deploy`
  (Studio > Managed Agents > `competition-agent`, or
  `https://chat.mistral.ai/managed-agents/competition-agent`)
- From Python: `agents.Agent.load_from(agent_name="competition-agent")`
- From the CLI: `uv run agents chat competition-agent`

Note: the deployment/agent record is named `competition-agent` (via
`--name`), while the workflow name inside the code is
`competition-economist-lawyer`. Use `competition-agent` in Studio, Vibe and
the CLI.
