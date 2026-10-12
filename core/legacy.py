"""旧コマンドから新しいコマンドへの移行を助ける部品。

- ``Responder``: commands.Context と discord.Interaction のどちらからでも同じ書き方で返信できる薄い包み。
  新旧どちらのコマンドからも同じ実装関数（``_xxx_impl``）を呼べるようにするために使う。
- ``legacy("/music volume")``: 旧コマンドに付けるデコレーター。本来の処理のあとに
  「このコマンドは /music volume に移りました」と案内する（同じ人・同じコマンドには 1 日 1 回まで）。
  記録はメモリ上だけなので、Bot を再起動すると数え直しになる。
"""
from __future__ import annotations

import datetime
import functools
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

JST = datetime.timezone(datetime.timedelta(hours=9))


def is_interaction(source) -> bool:
    return hasattr(source, "response") and hasattr(source, "followup")


class Responder:
    """ctx / interaction の違いを吸収する。"""

    def __init__(self, source):
        self.source = source
        self.is_interaction = is_interaction(source)

    @property
    def guild(self):
        return getattr(self.source, "guild", None)

    @property
    def guild_id(self) -> Optional[int]:
        guild = self.guild
        return guild.id if guild is not None else getattr(self.source, "guild_id", None)

    @property
    def user(self):
        return getattr(self.source, "user", None) if self.is_interaction else getattr(self.source, "author", None)

    @property
    def channel(self):
        return getattr(self.source, "channel", None)

    @property
    def voice_client(self):
        guild = self.guild
        return getattr(guild, "voice_client", None) if guild is not None else None

    @property
    def attachments(self) -> list:
        message = getattr(self.source, "message", None)
        return list(getattr(message, "attachments", None) or []) if not self.is_interaction else []

    def is_done(self) -> bool:
        return bool(self.is_interaction and self.source.response.is_done())

    async def defer(self, *, ephemeral: bool = False) -> None:
        if self.is_interaction and not self.source.response.is_done():
            await self.source.response.defer(ephemeral=ephemeral)

    async def send(self, content: Any = None, *, embed=None, view=None, file=None, ephemeral: bool = False,
                   want_message: bool = False):
        """返信する。``want_message`` のときは送ったメッセージを返す（あとで編集するため）。"""
        kwargs: dict[str, Any] = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file
        if not self.is_interaction:
            return await self.source.send(**kwargs)
        kwargs["ephemeral"] = ephemeral
        if self.source.response.is_done():
            if want_message:
                kwargs["wait"] = True
            return await self.source.followup.send(**kwargs)
        await self.source.response.send_message(**kwargs)
        if want_message:
            return await self.source.original_response()
        return None


class LegacyNotices:
    """「移りました」の案内を、同じ人・同じ旧コマンドには 1 日（日本時間）1 回だけ出す。"""

    def __init__(self):
        self._seen: dict[tuple[int, str], datetime.date] = {}

    @staticmethod
    def today() -> datetime.date:
        return datetime.datetime.now(JST).date()

    def should_notify(self, user_id: int, old_name: str) -> bool:
        key = (user_id, old_name)
        today = self.today()
        if self._seen.get(key) == today:
            return False
        self._seen[key] = today
        if len(self._seen) > 10000:  # 古い日付の記録を捨てる
            self._seen = {k: v for k, v in self._seen.items() if v == today}
        return True

    def clear(self) -> None:
        self._seen.clear()


NOTICES = LegacyNotices()


def notice_text(new_name: str) -> str:
    return f"💡 このコマンドは `{new_name}` に移りました。今のコマンドもしばらくは使えます。"


async def send_legacy_notice(source, old_name: str, new_name: str) -> bool:
    responder = Responder(source)
    user = responder.user
    if user is None or not NOTICES.should_notify(getattr(user, "id", 0), old_name):
        return False
    try:
        await responder.send(notice_text(new_name), ephemeral=True)
    except Exception:
        logger.debug("legacy notice failed", exc_info=True)
        return False
    return True


def legacy(new_name: str, old_name: Optional[str] = None):
    """旧コマンドのコールバックに付ける（``@commands.command`` / ``@app_commands.command`` の下に書く）。

    コールバックの引数（型注釈を含む）はそのまま見えるので、discord.py の引数解析は変わらない。
    """
    def decorator(func):
        name = old_name or func.__name__

        @functools.wraps(func)
        async def wrapper(self, source, *args, **kwargs):
            result = await func(self, source, *args, **kwargs)
            await send_legacy_notice(source, name, new_name)
            return result

        wrapper.__legacy_new_name__ = new_name
        return wrapper
    return decorator
