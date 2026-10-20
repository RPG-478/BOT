"""Components V2で既存のセレクト系パネルを表示する補助。"""
from __future__ import annotations

import discord


def embed_text(embed: discord.Embed) -> str:
    """Embed相当の内容をComponents V2のTextDisplay用Markdownへ変換する。"""
    parts: list[str] = []
    if embed.title:
        parts.append(f"## {embed.title}")
    if embed.description:
        parts.append(embed.description)
    for field in embed.fields:
        parts.append(f"**{field.name}**\n{field.value}")
    if embed.footer and embed.footer.text:
        parts.append(f"-# {embed.footer.text}")
    return "\n\n".join(parts)[:4000] or "(表示内容がありません)"


class PanelLayoutView(discord.ui.LayoutView):
    """既存のdiscord.ui.Viewを1つのContainerへ包むV2ビュー。"""

    def __init__(self, panel: discord.ui.View):
        super().__init__(timeout=panel.timeout)
        self.panel = panel
        self._sync()

    def __setattr__(self, name, value):
        """Forward callback state updates to the wrapped panel."""
        panel = self.__dict__.get("panel")
        if panel is not None and name != "panel" and hasattr(panel, name):
            setattr(panel, name, value)
            return
        super().__setattr__(name, value)

    def __getattr__(self, name):
        if name != "panel":
            panel = self.__dict__.get("panel")
            if panel is not None and hasattr(panel, name):
                return getattr(panel, name)
        raise AttributeError(name)

    def _sync(self):
        self.clear_items()
        rows: dict[int, list[discord.ui.Item]] = {}
        for item in self.panel.children:
            row = getattr(item, "row", None)
            if row is None:
                row = 0
            rows.setdefault(row, []).append(item)
        source_embed = self.panel.embed()
        container = discord.ui.Container(
            discord.ui.TextDisplay(embed_text(source_embed)),
            *[discord.ui.ActionRow(*items) for _, items in sorted(rows.items())],
            accent_colour=getattr(source_embed, "colour", None),
        )
        self.add_item(container)

    def refresh(self):
        self.panel.genre = getattr(self, "genre", getattr(self.panel, "genre", None))
        self.panel.refresh()
        self._sync()

    def embed(self):
        return None

    async def show(self, interaction, category_id, page):
        if self.panel.__class__.__name__ != "HelpView":
            return await self.panel.show(interaction, category_id, page)
        next_panel = self.panel.__class__(
            self.panel.catalog, category_id, page,
            getattr(self.panel, "shortcut_mode", False),
            getattr(self.panel, "shortcut_item", None),
        )
        self.stop()
        return await edit_panel_v2(interaction, PanelLayoutView(next_panel))


async def edit_panel_v2(interaction: discord.Interaction, view: discord.ui.LayoutView):
    """Edit a message with a V2 view, clearing legacy message payloads.

    Discord rejects a message update that adds/replaces a LayoutView unless
    content, embeds, and attachments are explicitly supplied as cleared values.
    Omitting them makes the component interaction fail and appear to users as
    the bot not responding.
    """
    return await interaction.response.edit_message(
        content=None,
        embed=None,
        embeds=[],
        attachments=[],
        view=view,
    )


def as_panel_v2(panel: discord.ui.View) -> PanelLayoutView:
    return PanelLayoutView(panel)
