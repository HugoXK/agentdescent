---
description: Ask DeepWiki about AgentDescent from the corner widget or your agent's MCP client, and browse the indexed pages.
---

# Ask DeepWiki

[DeepWiki](https://deepwiki.com/ThinkFlowLab/agentdescent) indexes the repository
and answers with links to the source. It is a third-party, model-generated index;
these docs and the repository are canonical.

## Two ways to ask

**Use the corner widget.** The **Ask DeepWiki** button at the bottom-right opens
a panel with two choices: **Chat here** asks without leaving the page, and
**Open page** jumps to the DeepWiki page. The widget calls DeepWiki's public MCP
endpoint directly — no key, no backend, and no question leaves the browser except
to DeepWiki.

**Use your agent.** Connect the same MCP server to Claude Code, Codex, OpenCode
or DeepSeek Harness and ask from inside your agent.

[Open DeepWiki ↗](https://deepwiki.com/ThinkFlowLab/agentdescent){ .md-button .md-button--primary }

## Index status

!!! note "Indexed"

    DeepWiki indexes `ThinkFlowLab/agentdescent`. The corner widget asks this
    repository directly. If a page is missing or stale, open the DeepWiki page
    once to refresh its index.

## Ask from your agent (MCP)

DeepWiki exposes a free, no-authentication MCP server at
`https://mcp.deepwiki.com/mcp` (streamable HTTP). The endpoint is CORS-enabled,
which is why the corner widget can call it from a static page.

Available tools:

- `ask_wiki_question` — ask a question grounded in a repository's wiki.
- `read_wiki_structure` — list the documentation topics for a repository.
- `read_wiki_contents` — read the full wiki for a repository.

```bash
claude mcp add -s user -t http deepwiki https://mcp.deepwiki.com/mcp
```

For a client that reads JSON:

```json
{
  "mcpServers": {
    "deepwiki": {
      "url": "https://mcp.deepwiki.com/mcp"
    }
  }
}
```

Then ask your agent, for example:

- How does AgentDescent merge conflicting diffs?
- What is the difference between the default and asynchronous runtime?
- Where is the acceptance gate implemented, and what does it read?
- How do I evolve a skill directory with `evolve()`?
- What evidence supports the merge cost lever, and what are its limits?

## Good questions to start with

DeepWiki is best for "where is this in the code" and "how does this mechanism
work". For a number, open [measured results](results.md); for a command, open
[install](install.md). The widget's suggested questions are the same starting
points.

!!! warning "It can be wrong"
    DeepWiki is an external service. Verify a load-bearing answer against the
    source link it returns, or against these docs. If a page is missing, the
    repository is the source of truth.
