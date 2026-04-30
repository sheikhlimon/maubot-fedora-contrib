from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

if TYPE_CHECKING:
    from typing import Awaitable


class Config(BaseProxyConfig):
    """Loads settings from base-config.yaml. Maubot calls do_update() on startup."""

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("db_host")
        helper.copy("db_port")
        helper.copy("db_name")
        helper.copy("db_user")
        helper.copy("db_password")
        helper.copy("max_results")
        helper.copy("similarity_threshold")
        helper.copy("allowed_rooms")
        helper.copy("command_prefix")
        helper.copy("bot_name")


class FedoraContribBot(Plugin):
    """Maubot plugin that answers Fedora contributor questions from documentation."""

    @classmethod
    def get_config_class(cls) -> type[BaseProxyConfig]:
        return Config

    async def start(self) -> None:
        self.log.info("Fedora Contrib Bot starting...")
        self.engine = None
        await self._init_search_engine()

    async def stop(self) -> None:
        if self.engine:
            await self.engine.close()

    async def _init_search_engine(self) -> None:
        """Set up the docs2db-api search engine."""
        try:
            from docs2db_api.rag.engine import UniversalRAGEngine

            self.engine = UniversalRAGEngine(
                config=self._make_rag_config(),
            )
            await self.engine.start()
            self.log.info("Search engine ready")
        except Exception as e:
            self.log.error(f"Failed to init search engine: {e}")
            self.engine = None

    def _make_rag_config(self):
        """Build a RAG config from our plugin settings."""
        from docs2db_api.rag.engine import RAGConfig

        return RAGConfig(
            similarity_threshold=self.config["similarity_threshold"],
            max_chunks=self.config["max_results"],
            enable_question_refinement=False,
            enable_reranking=True,
        )

    @command.new(name="ask", help="Ask a question about contributing to Fedora", arg_fallthrough=False)
    @command.argument("question", pass_raw=True)
    async def ask(self, evt: MessageEvent, question: str) -> None:
        """Handle !ask <question> commands."""
        if not question.strip():
            await evt.reply("Please provide a question. Example: `!ask how do I fork a repo on Pagure?`")
            return

        if len(question) > 500:
            question = question[:497] + "..."

        if not self.engine:
            await evt.reply("Sorry, the search engine is not available. Please contact an admin.")
            return

        # Check room allowlist
        allowed = self.config.get("allowed_rooms", [])
        if allowed and evt.room_id not in allowed:
            return

        await evt.react("🔍")
        await self._search_and_reply(evt, question.strip())

    async def _search_and_reply(self, evt: MessageEvent, question: str) -> None:
        """Search docs and send formatted results to the room."""
        try:
            result = await asyncio.wait_for(
                self.engine.search_documents(question),
                timeout=30,
            )
        except asyncio.TimeoutError:
            await evt.reply("Search timed out. Try a shorter question.")
            return
        except Exception as e:
            self.log.error(f"Search error: {e}")
            await evt.reply("Search failed. Please try again or ask in the channel.")
            return

        docs = result.documents if hasattr(result, "documents") else []
        if not docs:
            await evt.reply(
                f"No documentation found for \"{question}\".\n\n"
                "Try rephrasing or ask in the channel — a human might know! 💬"
            )
            return

        await evt.reply(self._format_response(question, docs))

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip raw RST/Markdown markup artifacts from docs chunks."""
        # Remove numbered code-block markers like "\n1\n" or "\n12\n" on their own line
        text = re.sub(r"\n\d+\n", "\n", text)
        # Collapse multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _format_response(self, question: str, docs: list) -> str:
        """Turn search results into a readable Matrix message."""
        bot_name = self.config.get("bot_name", "Fedora Contributor Helper")
        lines = [f"**{bot_name}** — results for _{question}_:\n"]

        for i, doc in enumerate(docs[:self.config["max_results"]], 1):
            text = self._clean_text(doc.get("text", ""))
            source = doc.get("document_path", "")
            metadata = doc.get("metadata", {})
            origin = metadata.get("origin", {})
            filename = origin.get("filename", "")

            source_display = filename.replace(".html", "") if filename else (source or "unknown")

            # Trim long results for chat readability
            if len(text) > 400:
                text = text[:397] + "..."

            lines.append(f"**{i}.** {text}")
            lines.append(f"_source: {source_display}_\n")

        lines.append("💡 Ask more with `!ask <your question>`")
        return "\n".join(lines)
