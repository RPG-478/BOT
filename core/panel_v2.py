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
    """既存のdiscord.ui.Viewを1つのContainerへ包むV2ビュー。

    既存Selectのcallbackから見える ``genre`` や ``refresh`` はこのクラスが
    プロキシし、状態変更時も同じV2メッセージを再構築する。
    """

    def __init__(self, panel: discord.ui.View):
        super().__init__(timeout=panel.timeout)
        self.panel = panel
        self._sync()

    def __setattr__(self, name, value):
        """Forward callback state updates to the wrapped panel.

        Components V2 callbacks receive this layout wrapper as ``self.view``.
        Without forwarding assignments, a selection such as ``chess_mode`` is
        visible in the wrapper but the launcher still reads the old value from
        the underlying view.
        """
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
        # V2メッセージはEmbedを持てないため、callback互換の空値を返す。
        return None

    async def show(self, interaction, category_id, page):
        """/help のページ遷移をV2ビューのまま行う。"""
        if self.panel.__class__.__name__ != "HelpView":
            return await self.panel.show(interaction, category_id, page)
        next_panel = self.panel.__class__(
            self.panel.catalog, category_id, page,
            getattr(self.panel, "shortcut_mode", False),
            getattr(self.panel, "shortcut_item", None),
        )
        self.stop()
        await interaction.response.edit_message(view=PanelLayoutView(next_panel))


def as_panel_v2(panel: discord.ui.View) -> PanelLayoutView:
    return PanelLayoutView(panel)
