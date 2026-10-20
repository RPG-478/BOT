"""Components V2で既存のセレクト系パネルを表示する補助。"""
from __future__ import annotations

import asyncio
import traceback

import discord

__all__ = [
    "embed_text",
    "build_rows",
    "PanelLayoutView",
    "edit_panel_v2",
    "edit_message_v2",
    "as_panel_v2",
]


def embed_text(embed: discord.Embed | None) -> str:
    """Embed相当の内容をComponents V2のTextDisplay用Markdownへ変換する。"""
    if embed is None:
        return "(表示内容がありません)"
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


def build_rows(items: list[discord.ui.Item]) -> list[list[discord.ui.Item]]:
    """V1のchildrenをComponents V2のActionRow規約へ分割する。

    - Selectは1つのActionRowに1つだけ
    - Button等は1つのActionRowに5つまで
    """
    explicit: dict[int, list[discord.ui.Item]] = {}
    auto: list[discord.ui.Item] = []
    for item in items:
        row = getattr(item, "row", None)
        if row is None:
            auto.append(item)
        else:
            explicit.setdefault(row, []).append(item)

    groups = [explicit[r] for r in sorted(explicit)]
    if auto:
        groups.append(auto)

    rows: list[list[discord.ui.Item]] = []
    buffer: list[discord.ui.Item] = []
    for group in groups:
        for item in group:
            if isinstance(item, discord.ui.Select):
                if buffer:
                    rows.append(buffer)
                    buffer = []
                rows.append([item])
            else:
                buffer.append(item)
                if len(buffer) >= 5:
                    rows.append(buffer)
                    buffer = []
        if buffer:
            rows.append(buffer)
            buffer = []
    return rows


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
        rows = build_rows(list(self.panel.children))
        for row in rows:
            for item in row:
                # callback内の self.view がラッパーを指すようにする
                try:
                    item._view = self
                except Exception:
                    pass
        source_embed = self.panel.embed()
        if source_embed is None:
            source_embed = discord.Embed()
        container = discord.ui.Container(
            discord.ui.TextDisplay(embed_text(source_embed)),
            *[discord.ui.ActionRow(*items) for items in rows],
            accent_colour=getattr(source_embed, "colour", None),
        )
        self.add_item(container)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        """例外を必ずACKして可視化する（無応答エラーの防止と原因特定用）。"""
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ 内部エラー: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ 内部エラー: {error}", ephemeral=True)
        except discord.HTTPException:
            pass

    def refresh(self, interaction: discord.Interaction | None = None):
        """状態を更新する。interactionを渡した場合のみawait可能なオブジェクトを返す。

        - ``view.refresh()``               : 同期呼び出し（旧コード互換）。
        - ``await view.refresh(interaction)`` : 編集まで行ってタイムアウトを防止。
        """
        self.panel.genre = getattr(self, "genre", getattr(self.panel, "genre", None))
        pending = self.panel.refresh()

        if asyncio.iscoroutine(pending):
            if interaction is None:
                pending.close()
                self._sync()
                return None

            async def _apply_pending():
                await pending
                self._sync()
                return await edit_panel_v2(interaction, self)

            return _apply_pending()

        self._sync()
        if interaction is None:
            return None
        return edit_panel_v2(interaction, self)

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
        return await edit_panel_v2(interaction, PanelLayoutView(next_panel))


async def edit_panel_v2(interaction: discord.Interaction, view: discord.ui.LayoutView):
    """Edit a message with a V2 view, clearing legacy message payloads.

    Discord rejects a message update that adds/replaces a LayoutView unless
    content, embeds, and attachments are explicitly supplied as cleared values.
    Omitting them makes the component interaction fail and appear to users as
    the bot not responding.
    """
    if interaction.response.is_done():
        return await interaction.edit_original_response(
            content=None,
            embed=None,
            attachments=[],
            view=view,
        )
    return await interaction.response.edit_message(
        content=None,
        embed=None,
        attachments=[],
        view=view,
    )


async def edit_message_v2(message: discord.Message, view: discord.ui.LayoutView):
    """Replace a normal message with a Components V2 view safely."""
    return await message.edit(
        content=None,
        embed=None,
        attachments=[],
        view=view,
    )


def as_panel_v2(panel: discord.ui.View) -> PanelLayoutView:
    return PanelLayoutView(panel)
