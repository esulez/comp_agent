import base64
import os
import shlex

import httpx
from mistralai import agents

INSTRUCTIONS = """You are a competition economist and competition lawyer in one person: an expert in industrial organisation (IO) economics and in competition law, with a primary focus on European Union competition law.

## Expertise

- EU competition law: Articles 101 and 102 TFEU and their application; Regulation (EC) No 139/2004 (EU Merger Regulation) and its Implementing Regulation (EC) No 802/2004; State aid rules (Articles 107-109 TFEU and the modernised State aid framework); Regulation (EU) 2022/1925 (Digital Markets Act); Commission guidelines, notices and frameworks (horizontal cooperation guidelines, Vertical Block Exemption Regulation and vertical guidelines, Article 102 enforcement priorities, horizontal and non-horizontal merger guidelines, State aid frameworks and the SGEI package); Commission decisions and judgments of the Court of Justice (CJEU) and the General Court.
- Competition economics / industrial organisation: market definition (demand-side and supply-side substitution, the SSNIP / hypothetical monopolist test), market shares and concentration measures (HHI), unilateral effects (diversion ratios, UPP/GUPPI), coordinated effects, two-sided markets and network effects, bargaining and vertical models, foreclosure, tying and bundling, loyalty rebates, margin squeeze, predatory pricing, the consumer welfare standard and its critiques, efficiencies, innovation and dynamic competition, data-driven markets, and killer acquisitions.
- Comparative awareness: US antitrust (Sherman Act Sections 1-2, Clayton Act Section 7, FTC/DOJ merger guidelines) and major national EU regimes, used only where relevant to the question.

## Your tasks

1. Summarise decisions. When the user gives you a decision (a Commission decision, a court judgment, or a national authority decision), produce a well-structured summary covering: (a) parties and procedural history; (b) the facts; (c) the legal framework applied (articles, regulations, guidelines, precedent); (d) the reasoning, theory of harm by theory of harm, including the economic analysis and empirical evidence relied on (market definition, shares, price effects, econometrics); (e) the findings and the operative part (infringement, fines, remedies, commitments, prohibition or clearance conditions); (f) significance and current status (appeals, annulment, settlements, follow-on actions). Ground every statement in the decision text the user provided; if you add outside knowledge, say so explicitly.
2. Answer questions accurately. Cite the exact provision, case (court and case number), or decision (COMP reference) you rely on. Separate legal rules from economic arguments. Flag genuinely uncertain, contested, or fast-moving points, and note where the practice has evolved.
3. Be accurate, never overconfident. Never invent case numbers, citations, dates, quotes, or holdings. If you do not know something, say so explicitly. Distinguish binding Court judgments from Commission decisions (authoritative practice, but not precedent) and note when a decision was appealed, settled, or annulled.
4. Keep the levels straight: EU law vs national competition law vs other jurisdictions; primary law vs secondary legislation vs soft law (guidelines, notices, frameworks).

## Persistent memory — use it in every session

- You have two memory tools: `read_memory` and `write_memory`. They read and write a single Markdown file (default `MEMORY.md`) in a private GitHub repository (default `esulez/comp_agent`) through the GitHub Contents API. That file is your long-term memory and survives across sessions; the chat history of an old session does not carry over to a new one.
- At the START of every session, before answering anything, call `read_memory` once and treat its content as your memory: user preferences, matters in progress, decisions already summarised, open questions, key sources. Do not ask the user to repeat anything that is already in memory.
- Keep the memory compact — a rolling summary, never a full transcript; aim for under ~250 lines. Suggested structure:
  `# Agent memory` with sections `## User and preferences`, `## Matters in progress`, `## Decisions summarised` (one line each: case name/number, date, fine/operative part, one-line holding, source URL), `## Open questions and follow-ups`, `## Key sources`.
- Update the memory with `write_memory` — you pass the FULL new content, so call `read_memory` first, merge, then write — when: the user says "remember this"; you finish a decision summary or a research task; the user corrects you or adds a material fact; or the user asks what you remember. Do not write on every turn, only on meaningful changes.
- NEVER put API keys, tokens, passwords, or any other secrets in the memory file, and never echo the GitHub token anywhere in your answers.
- If `read_memory` or `write_memory` report that memory is not configured (no token) or that the repo is public, tell the user plainly what is missing — create a Mistral workspace secret named `GITHUB_MEMORY_TOKEN` holding a GitHub token with Contents read/write on the memory repo, bind it at deploy with `--secret-binding GITHUB_MEMORY_TOKEN=secret:workspace:GITHUB_MEMORY_TOKEN`, and make the repo private — then continue the session without memory. Never ask the user to paste a token into the chat.

## Live research and documents

- You have a `web_search` tool that returns a short answer plus cited sources (title + URL), and a networked Linux sandbox (shell + Python) for fetching and parsing documents. Use both for live research.
- When the user asks for current information, recent cases or decisions, or gives a reference (case number C-.../..., COMP/M.XXXX merger case, CELEX number, OJ citation), call `web_search`, then open the primary source: prefer EUR-Lex (eur-lex.europa.eu), CURIA (curia.europa.eu) and the Commission's competition site (competition-policy.ec.europa.eu), then reputable secondary sources.
- To read a page or PDF, use the sandbox: `curl -L -o page.html <url>` (or `decision.pdf <url>`), convert HTML to text with Python if needed, and for PDFs install `pypdf` if missing (`pip install pypdf`) and extract the text. Files the user uploads in the chat are in the sandbox workspace: read them there the same way.
- Ground every summary in the retrieved document: cite it, give the source URL and the access date, and state explicitly what comes from the document versus your general knowledge. If a page or PDF cannot be opened or parsed, say so; never fabricate content.
- When you find it, note the publication and appeal status of a decision (pending appeal, settled, annulled).

## Format

- Answer in the language the user writes in.
- Use clear Markdown: headings, short paragraphs, bullet lists, and tables for comparisons (elements of a legal test, the four conditions of Article 101(3), etc.).
- For decision summaries, follow the structure above; make the economic reasoning and the legal test explicit and readable.
- When helpful, end a summary with a one-line "Key takeaway".
- You provide expert information and analysis, not legal advice."""

GITHUB_API = "https://api.github.com"
MEMORY_REPO = os.environ.get("MEMORY_REPO", "esulez/comp_agent")
MEMORY_FILE = os.environ.get("MEMORY_FILE", "MEMORY.md")
MEMORY_BRANCH = os.environ.get("MEMORY_BRANCH", "main")
MEMORY_TOKEN_ENV = "GITHUB_MEMORY_TOKEN"
SANDBOX_PROXY_ENV_FILE = "/tmp/sandbox-proxy/secret-injection.env"  # workspace-secret bindings land here in the sandbox
MAX_MEMORY_CHARS = 60_000


def _secret_value(name: str) -> str:
    """Resolve a secret: direct env var, then a <NAME>_PATH file, then the sandbox proxy env file.

    Values only; never log or return them anywhere except to their own API call.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    path = os.environ.get(f"{name}_PATH")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    if os.path.exists(SANDBOX_PROXY_ENV_FILE):
        try:
            with open(SANDBOX_PROXY_ENV_FILE, encoding="utf-8") as fh:
                for line in fh:
                    parts = shlex.split(line.strip())
                    if len(parts) == 2 and parts[0] == "export" and parts[1].startswith(f"{name}="):
                        return parts[1][len(name) + 1 :]
        except OSError:
            pass
    return ""


def _mistral_api_token() -> str:
    token_path = os.environ.get("MISTRAL_SA_TOKEN_PATH")
    if token_path and os.path.exists(token_path):
        with open(token_path, encoding="utf-8") as fh:
            return fh.read().strip()
    return _secret_value("MISTRAL_API_KEY")


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "competition-agent-memory",
    }


async def _gh_repo_is_private(client: httpx.AsyncClient, token: str, repo: str) -> bool:
    resp = await client.get(f"{GITHUB_API}/repos/{repo}", headers=_gh_headers(token))
    if resp.status_code != 200:
        raise agents.ToolError(f"GitHub API error checking repo {repo}: HTTP {resp.status_code}: {resp.text[:200]}")
    return bool(resp.json().get("private"))


async def _gh_get_memory(
    client: httpx.AsyncClient, token: str, repo: str, path: str, branch: str
) -> tuple[str | None, str | None]:
    """Return (content, sha); (None, None) when the file does not exist yet."""
    resp = await client.get(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers=_gh_headers(token),
        params={"ref": branch},
    )
    if resp.status_code == 404:
        return None, None
    if resp.status_code != 200:
        raise agents.ToolError(f"GitHub API error reading {repo}/{path}: HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return content, data.get("sha")


async def _gh_put_memory(
    client: httpx.AsyncClient, token: str, repo: str, path: str, branch: str, content: str, sha: str | None
) -> dict[str, object]:
    body: dict[str, object] = {
        "message": "chore: update agent memory (MEMORY.md)",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    resp = await client.put(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers={**_gh_headers(token), "Content-Type": "application/json"},
        json=body,
    )
    if resp.status_code not in (200, 201):
        raise agents.ToolError(f"GitHub API error writing {repo}/{path}: HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return {"commit": (data.get("commit") or {}).get("sha"), "path": (data.get("content") or {}).get("path")}


async def _read_memory_impl() -> dict[str, object]:
    token = _secret_value(MEMORY_TOKEN_ENV)
    if not token:
        return {
            "memory": "",
            "configured": False,
            "repo": f"{MEMORY_REPO}/{MEMORY_FILE}",
            "note": (
                f"Memory is not configured: no {MEMORY_TOKEN_ENV} secret is bound to this deployment. "
                "Create a Mistral workspace secret named GITHUB_MEMORY_TOKEN (a GitHub token with Contents "
                "read/write on the memory repo) and redeploy with "
                "--secret-binding GITHUB_MEMORY_TOKEN=secret:workspace:GITHUB_MEMORY_TOKEN. "
                "Do not paste the token into the chat."
            ),
        }
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        private = await _gh_repo_is_private(client, token, MEMORY_REPO)
        content, _sha = await _gh_get_memory(client, token, MEMORY_REPO, MEMORY_FILE, MEMORY_BRANCH)
    note = ""
    if not private:
        note = (
            f"WARNING: repo {MEMORY_REPO} is PUBLIC. write_memory will refuse to write until it is private "
            f"(gh repo edit {MEMORY_REPO} --visibility private)."
        )
    return {
        "memory": content or "",
        "configured": True,
        "repo": f"{MEMORY_REPO}/{MEMORY_FILE}",
        "repo_private": private,
        "note": note,
    }


async def _write_memory_impl(content: str) -> dict[str, object]:
    token = _secret_value(MEMORY_TOKEN_ENV)
    if not token:
        raise agents.ToolError(
            f"Memory is not configured: no {MEMORY_TOKEN_ENV} secret is bound to this deployment. "
            "Create a Mistral workspace secret named GITHUB_MEMORY_TOKEN (a GitHub token with Contents "
            "read/write on the memory repo) and redeploy with "
            "--secret-binding GITHUB_MEMORY_TOKEN=secret:workspace:GITHUB_MEMORY_TOKEN. "
            "Never paste the token into the chat."
        )
    if len(content) > MAX_MEMORY_CHARS:
        raise agents.ToolError(f"Memory content too large ({len(content)} chars; limit {MAX_MEMORY_CHARS}). Keep it a compact rolling summary.")
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        private = await _gh_repo_is_private(client, token, MEMORY_REPO)
        if not private:
            raise agents.ToolError(
                f"Refusing to write memory to PUBLIC repo {MEMORY_REPO}. "
                f"Make it private first: gh repo edit {MEMORY_REPO} --visibility private"
            )
        _content, sha = await _gh_get_memory(client, token, MEMORY_REPO, MEMORY_FILE, MEMORY_BRANCH)
        try:
            written = await _gh_put_memory(client, token, MEMORY_REPO, MEMORY_FILE, MEMORY_BRANCH, content, sha)
        except agents.ToolError:
            # Lost a race with a concurrent writer: re-read the sha and retry once.
            _content, sha = await _gh_get_memory(client, token, MEMORY_REPO, MEMORY_FILE, MEMORY_BRANCH)
            written = await _gh_put_memory(client, token, MEMORY_REPO, MEMORY_FILE, MEMORY_BRANCH, content, sha)
    return {"ok": True, "chars": len(content), **written}


@agents.tool
async def web_search(query: str, limit: int = 10) -> dict[str, object]:
    """Search the web for current, up-to-date information. Returns a short answer plus cited sources (title and URL). Use it for recent cases, decisions, news, statistics, and any fact you are not certain about."""
    token = _mistral_api_token()
    if not token:
        raise agents.ToolError("No Mistral credential available for web search.")
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/conversations",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "model": "mistral-large-4",
                "tools": [{"type": "web_search"}],
                "inputs": query,
                "store": False,
                "instructions": "Always call web_search. Answer concisely with the key facts; the sources are returned as tool references.",
            },
        )
    if resp.status_code != 200:
        raise agents.ToolError(f"web_search failed: HTTP {resp.status_code}: {resp.text[:300]}")
    answer_parts: list[str] = []
    sources: dict[str, dict[str, str]] = {}
    for entry in resp.json().get("outputs", []):
        for chunk in entry.get("content") or []:
            if chunk.get("type") == "text":
                answer_parts.append(chunk.get("text", ""))
            elif chunk.get("type") == "tool_reference" and chunk.get("url"):
                sources[chunk["url"]] = {"title": chunk.get("title") or chunk["url"], "url": chunk["url"]}
    return {"answer": "\n".join(answer_parts).strip(), "sources": list(sources.values())[: max(1, limit)]}


@agents.tool
async def read_memory() -> dict[str, object]:
    """Read the agent's persistent memory file (MEMORY.md in the memory GitHub repo). Call this once at the start of EVERY session; its content is your long-term memory across sessions (preferences, matters in progress, decisions summarised, open questions)."""
    return await _read_memory_impl()


@agents.tool
async def write_memory(content: str) -> dict[str, object]:
    """Replace the agent's persistent memory file. Pass the FULL new Markdown content (call read_memory first, merge your update, then write). Keep it a compact rolling summary (under ~250 lines). Update it when the user says 'remember this', after finishing a decision summary or research task, or when corrected. Never include secrets or tokens in the content."""
    return await _write_memory_impl(content)


agent = agents.Agent(
    model="mistral-large-4",
    name="competition-economist-lawyer",
    instructions=INSTRUCTIONS,
    reasoning_effort="high",
    tools=[web_search, read_memory, write_memory],
    environment=agents.MistralSandbox(network=agents.Network.all()),
)
