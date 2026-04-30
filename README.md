# maubot-fedora-contrib

A [Maubot](https://github.com/maubot/maubot) plugin that answers Fedora contributor questions by searching Fedora documentation using RAG (Retrieval-Augmented Generation).

## How it works

Users type `!ask <question>` in a Matrix room and the bot replies with relevant Fedora documentation snippets.

```
!ask how do I fork a repo on Pagure?
```

The bot searches a PostgreSQL database of Fedora docs using vector similarity + BM25 hybrid search, reranks results with a cross-encoder model, and returns the top matches.

## Architecture

```
Matrix room
    ↓  !ask <question>
Maubot + this plugin
    ↓  search query
docs2db-api (RAG engine)
    ↓  hybrid vector + BM25 search
PostgreSQL + pgvector (Fedora docs database)
    ↓  results
Plugin formats and replies in Matrix
```

## Where does the database come from?

This plugin queries a pre-built RAG database of Fedora documentation. The database is built by the [FedoraDocsRAG](https://github.com/Lifto/FedoraDocsRAG) pipeline, which uses the [docs2db](https://github.com/rhel-lightspeed/docs2db) toolchain:

1. **[docs2db](https://github.com/rhel-lightspeed/docs2db)** — ingests, chunks, and embeds documents into PostgreSQL with pgvector
2. **[FedoraDocsRAG](https://github.com/Lifto/FedoraDocsRAG)** — uses docs2db to build a RAG database from all Fedora documentation (64 repos, 1681+ pages)
3. **[docs2db-api](https://github.com/rhel-lightspeed/docs2db-api)** — queries the database with hybrid search + reranking
4. **This plugin** — wraps docs2db-api as a Maubot plugin for Matrix

### Building the database

```bash
# Option 1: Download pre-built dump (fast)
curl -LO https://github.com/Lifto/FedoraDocsRAG/releases/latest/download/fedora-docs.sql

# Option 2: Build from source (slow, clones 64 repos)
git clone https://github.com/Lifto/FedoraDocsRAG.git
cd FedoraDocsRAG && uv sync && uv run python build.py
```

### Restoring the database

```bash
# Start PostgreSQL via Podman/Docker
uvx docs2db db-start

# Restore the dump
uvx docs2db db-restore fedora-docs.sql

# Verify it works
uvx docs2db-api query "how do I fork a repo on Pagure?"
```

## Setup

### Prerequisites

- [Maubot](https://github.com/maubot/maubot) server running
- PostgreSQL database populated with Fedora docs (see above)
- Python 3.12

### Install

1. Build the plugin:
   ```bash
   mbc build .
   ```

2. Upload `fedora.contrib-v0.1.0.mbp` to your Maubot instance via the admin UI or:
   ```bash
   mbc upload fedora.contrib-v0.1.0.mbp
   ```

3. Create a new instance in the Maubot admin UI, selecting the `fedora.contrib` plugin and your Matrix client.

4. Configure the instance with your database settings (see `base-config.yaml` for all options).

### Configuration

| Setting | Default | Description |
|---|---|---|
| `db_host` | `localhost` | PostgreSQL host for docs2db |
| `db_port` | `5432` | PostgreSQL port |
| `db_name` | `ragdb` | Database name |
| `db_user` | `postgres` | Database user |
| `db_password` | `postgres` | Database password |
| `max_results` | `3` | Max search results to return |
| `similarity_threshold` | `0.5` | Minimum similarity score |
| `allowed_rooms` | `[]` | Room IDs to respond in (empty = all) |
| `bot_name` | `Fedora Contributor Helper` | Display name in responses |

### Running locally for development

```bash
# Set up environment
uv sync

# Test search independently
uv run python test_search.py

# Run maubot with the plugin
uv run python -m maubot -c config.yaml
```

## Usage

In any Matrix room where the bot is present:

```
!ask how do I become a Fedora contributor?
!ask git clone ssh failing on src.fedoraproject.org
!ask how do I create a Bodhi update?
```

## Related projects

- **[docs2db](https://github.com/rhel-lightspeed/docs2db)** — RAG database builder (Red Hat)
- **[docs2db-api](https://github.com/rhel-lightspeed/docs2db-api)** — Query API for docs2db databases (Red Hat)
- **[docs2db-mcp-server](https://github.com/rhel-lightspeed/docs2db-mcp-server)** — MCP server for AI assistants (Red Hat)
- **[FedoraDocsRAG](https://github.com/Lifto/FedoraDocsRAG)** — Pre-built Fedora docs RAG database
- **[Maubot](https://github.com/maubot/maubot)** — Plugin-based Matrix bot framework

## License

Apache-2.0
