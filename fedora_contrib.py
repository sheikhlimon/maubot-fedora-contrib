from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import aiohttp
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

if TYPE_CHECKING:
    from typing import Awaitable

WELCOME_ISSUE_TEMPLATE = """\
### Welcome Message & Introduction

# Welcome

Hello `@{username}`([FAS profile](https://accounts.fedoraproject.org/user/{username}/))! Welcome to Fedora!

Before we begin, please subscribe to the [Fedora join mailing list at fedora-join@lists.fedoraproject.org](https://lists.fedoraproject.org/admin/lists/fedora-join.lists.fedoraproject.org/). We use this list for general discussion, and it is also where the community shares tasks that need help.

These links are a good read to begin with. They tell you what the Free/Open Source community is about, and then they'll introduce you to Fedora: what Fedora is all about, and what we do, and of course, how we do it:

- [What is Free Software: a quick video!](https://www.fsf.org/blogs/community/user-liberation-watch-and-share-our-new-video)
- [Fedora's Mission and Foundations](https://docs.fedoraproject.org/en-US/project/)
- [Fedora's Code of Conduct](https://docs.fedoraproject.org/en-US/project/code-of-conduct/)
- [How is Fedora Organized?](https://docs.fedoraproject.org/en-US/project/orgchart/)
- [Fedora's Current 12-18 Month Community Objectives](https://docs.fedoraproject.org/en-US/project/objectives/)
- [Get started with badges!](https://docs.fedoraproject.org/en-US/fedora-join/welcome/badges/)
- [How to be a successful contributor](https://docs.fedoraproject.org/en-US/fedora-join/contribute/successful-contributor/)

Next, when you're ready, could you please introduce yourself (preferably on the list) so that the community can get to know you? (Interests, skills, anything you wish to say about yourself really).

Finally, could you let us know how you learned about the Fedora project? Was it from a colleague, or social media, for example?

If you have any questions at all, please ask! We'll use this ticket to keep in touch! :)

## Get to know each other better

In addition, could you provide some information to understand your requirements better? (You can write them in the introduction, or answer here if you feel more comfortable).

For example:

- your experience with Free/Open Source Software (FOSS) communities/ecosystems:
    - have you participated in FOSS before, or is this the first time?
    - how do you imagine your place in a FOSS community?

- your background/skills, for example:
    - community development and outreach, campaigning, journalism
    - Operating System (Do you use GNU/Linux as your main OS? Is Fedora Linux your main distribution?)
    - non-software development: design (Inkscape/Gimp/?), music/video/podcasting, marketing, language proficiency
    - software development related: command line, version control: git/hg/svn/?, rpm/packaging, programming languages/frameworks/utilities, testing, infrastructure/sysadmin

- your experience in communication platforms:
    - have you used mailing lists before?
    - what is your preferred real time chat platform?
    - have you helped with moderating/administering forums?

- how much time are you looking to/are you able to spend on volunteering (approximate hours per week)?

Remember that this is not a job interview at all. This is just an icebreaker to help all your new friends get to know you quicker. The better we know you, the better we can support you in identifying Fedora activities that promise to be relevant for you.

Please write how much/whatever you wish. :).
"""


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
        helper.copy("forgejo_base_url")
        helper.copy("forgejo_api_token")
        helper.copy("forgejo_repo")
        helper.copy("forgejo_welcome_label_ids")


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

    @command.new(name="openticket", help="Open a Welcome to Fedora ticket for a newcomer", arg_fallthrough=False)
    @command.argument("username", pass_raw=True)
    async def openticket(self, evt: MessageEvent, username: str) -> None:
        """Handle !openticket <username> commands."""
        username = username.strip().lstrip("@")
        if not username:
            await evt.reply("Please provide a username. Example: `!openticket limon`")
            return

        # Check room allowlist
        allowed = self.config.get("allowed_rooms", [])
        if allowed and evt.room_id not in allowed:
            return

        api_token = self.config.get("forgejo_api_token", "")
        if not api_token:
            await evt.reply("Forgejo API token not configured. Ask an admin to set `forgejo_api_token`.")
            return

        base_url = self.config.get("forgejo_base_url", "https://forge.fedoraproject.org").rstrip("/")
        repo = self.config.get("forgejo_repo", "join/WelcomeToFedora")
        label_ids = self.config.get("forgejo_welcome_label_ids", [3564, 3602])

        await evt.react("📋")
        await self._create_welcome_issue(evt, base_url, repo, api_token, username, label_ids)

    async def _create_welcome_issue(
        self,
        evt: MessageEvent,
        base_url: str,
        repo: str,
        api_token: str,
        username: str,
        label_ids: list[int],
    ) -> None:
        """Create a Welcome issue on the Fedora Forgejo instance."""
        title = f"Welcome to Fedora: @{username}"
        body = WELCOME_ISSUE_TEMPLATE.format(username=username)

        url = f"{base_url}/api/v1/repos/{repo}/issues"
        headers = {
            "Authorization": f"token {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "title": title,
            "body": body,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 201:
                        data = await resp.json()
                        issue_number = data.get("number", "?")
                        issue_url = data.get("html_url", f"{base_url}/{repo}/issues/{issue_number}")

                        # Try to apply labels via PATCH (requires token with label write scope)
                        if label_ids:
                            await self._apply_labels(session, base_url, repo, api_token, headers, issue_number, label_ids)

                        await evt.reply(
                            f"Welcome ticket created for **@{username}**!\n\n"
                            f"[#{issue_number} — {title}]({issue_url})\n\n"
                            f"A mentor will follow up on the ticket to help with onboarding."
                        )
                    elif resp.status == 401:
                        self.log.error("Forgejo API returned 401 — invalid or expired token")
                        await evt.reply("Failed to create ticket: API token is invalid or expired. Contact an admin.")
                    elif resp.status == 403:
                        self.log.error("Forgejo API returned 403 — token lacks permission")
                        await evt.reply("Failed to create ticket: API token lacks issue creation permissions. Contact an admin.")
                    elif resp.status == 404:
                        self.log.error("Forgejo API returned 404 — repo not found: %s", repo)
                        await evt.reply(f"Failed to create ticket: repository `{repo}` not found. Check config.")
                    else:
                        error_text = await resp.text()
                        self.log.error("Forgejo API error %d: %s", resp.status, error_text[:500])
                        await evt.reply(f"Failed to create ticket (HTTP {resp.status}). Check logs for details.")
        except aiohttp.ClientError as e:
            self.log.error("Forgejo connection error: %s", e)
            await evt.reply("Could not reach the Fedora Forge. Please try again later.")
        except asyncio.TimeoutError:
            await evt.reply("Forgejo request timed out. Please try again later.")

    async def _apply_labels(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        repo: str,
        api_token: str,
        headers: dict,
        issue_number: int,
        label_ids: list[int],
    ) -> None:
        """Attempt to apply labels to an issue. Logs a warning if token lacks permission."""
        patch_url = f"{base_url}/api/v1/repos/{repo}/issues/{issue_number}"
        try:
            async with session.patch(patch_url, json={"labels": label_ids}, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201):
                    self.log.info("Applied labels %s to issue #%d", label_ids, issue_number)
                else:
                    self.log.warning("Could not apply labels to issue #%d (HTTP %d) — token may lack label scope", issue_number, resp.status)
        except Exception as e:
            self.log.warning("Failed to apply labels to issue #%d: %s", issue_number, e)

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
