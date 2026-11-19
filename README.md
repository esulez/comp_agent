# competition-agent

A competition economist and lawyer agent: expertise in industrial organisation
(IO) economics and competition law, focused on EU competition law. Built with
the [Mistral Agents SDK](https://docs.mistral.ai/studio/agents/getting-started/quickstart)
(`mistralai-agents`, imported as `from mistralai import agents`).

Give it Commission decisions, court judgments, or authority decisions to
summarise, and ask it competition-law and competition-economics questions.

The agent has live web research (`web_search` connector: search + open URL)
and a networked Mistral sandbox (shell + Python) to download and parse PDFs
(e.g. from EUR-Lex, CURIA or competition-policy.ec.europa.eu) and to read
files uploaded in chat.

## Run locally

```bash
uv sync
export MISTRAL_API_KEY=...   # from https://console.mistral.ai/api-keys
uv run agents chat
```

## Deploy (Mistral-managed)

Push this repository, then either:

```bash
uv run --env-file .env agents deploy
```

or create a managed deployment of this Git repository in Mistral Studio
(Workflows > managed deployments).

## Use the deployed agent

- In Vibe Code Web: `https://chat.mistral.ai/managed-agents/competition-economist-lawyer`
- From Python: `agents.Agent.load_from(agent_name="competition-economist-lawyer")`
- From the CLI: `uv run agents chat competition-economist-lawyer`
