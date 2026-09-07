"""DDD raid lobby and turn-based multiplayer raid battle."""
from __future__ import annotations

import asyncio
import copy
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from supabase import Client, create_client

from .ddd_battle import calc_stat, hp_bar, normalize_moves, prepare_party, resolve_action

SUPABASE_URL = __import__("os").getenv("SUPABASE_URL")
SUPABASE_KEY = __import__("os").getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
logger = logging.getLogger(__name__)

RAID_TICKET = "raid_ticket"
RAID_TICKET_COST = 7_000
RAID_LOBBY_SECONDS = 180
RAID_MAX_PARTICIPANTS = 20
RAID_CHEST_REWARD = 5
RAID_COIN_REWARD = 20_000
RAID_BOSS_MARKER = "__raid_boss__"
RAID_RPC_SECRET = __import__("os").getenv("DDD_RAID_RPC_SECRET")


def payload(data: Any) -> dict:
    """Normalize PostgREST JSON RPC responses."""
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_raid_boss(monster: dict, rng: Any | None = None) -> dict:
    """Move the former random-match boss tuning into a reusable raid boss snapshot."""
    rng = rng or random
    boss = prepare_party([copy.deepcopy(monster)])[0]
    hp_multiplier = rng.randint(3, 5)
    boss["max_hp"] = min(9999, int(boss["max_hp"]) * hp_multiplier)
    for key in ("attack", "defense", "sp_atk", "sp_def", "speed"):
        boss[f"max_{key}"] = min(9999, int(boss[f"max_{key}"]) * 1.5)
    boss["current_hp"] = calc_stat(boss["max_hp"], boss["current_level"])
    boss["raid_bonus_label"] = f"HP{hp_multiplier}倍 / その他能力1.5倍"
    return boss


def raid_participant(state: dict, user_id: str) -> dict | None:
    return next((row for row in state.get("participants", []) if str(row.get("user_id")) == str(user_id)), None)


def raid_alive_participants(state: dict) -> list[dict]:
    return [
        row for row in state.get("participants", [])
        if not row.get("withdrawn") and int(row.get("monster", {}).get("current_hp") or 0) > 0
    ]


def raid_outcome(state: dict) -> str | None:
    if int(state.get("boss", {}).get("current_hp") or 0) <= 0:
        return "cleared"
    if not raid_alive_participants(state):
        return "failed"
    return None


def raid_turn_user(state: dict) -> str | None:
    order = state.get("turn_order") or []
    index = int(state.get("turn_index", -1))
    if not 0 <= index < len(order):
        return None
    entry = order[index]
    return str(entry.get("user_id")) if entry.get("kind") == "player" else None


def resolve_raid_player_action(state: dict, user_id: str, action: str, rng: Any | None = None) -> None:
    """Resolve one player's selected move against the shared boss without touching other players."""
    participant = raid_participant(state, user_id)
    if not participant or participant.get("withdrawn"):
        raise ValueError("このレイドには参加していません。")
    actor = participant["monster"]
    if int(actor.get("current_hp") or 0) <= 0:
        raise ValueError("戦闘不能のモンスターは行動できません。")
    if action == "surrender":
        participant["withdrawn"] = True
        actor["current_hp"] = 0
        state.setdefault("logs", []).append(f"<@{user_id}> はレイドから離脱した。")
        state["logs"] = state["logs"][-12:]
        return

    temporary = {
        "p1": {"party": [actor], "active_idx": 0},
        "p2": {"party": [state["boss"]], "active_idx": 0},
        "logs": state.setdefault("logs", []),
        "version": 0,
    }
    resolve_action(temporary, "p1", action, rng)
    state["logs"] = temporary["logs"][-12:]


def resolve_raid_boss_turn(state: dict, rng: Any | None = None) -> None:
    """The boss selects exactly one living participant, then uses an attacking move."""
    rng = rng or random
    targets = raid_alive_participants(state)
    if not targets:
        return
    target = rng.choice(targets)
    boss = state["boss"]
    moves = normalize_moves(boss.get("moves"))
    attack_slots = [index for index, move in enumerate(moves) if move["category"] != "status"]
    if not attack_slots:
        moves[0] = {
            "name": "レイドストライク",
            "type": boss.get("element_type", "無"),
            "category": "physical",
            "power": 50,
            "accuracy": 100,
            "description": "レイドボス固有の物理攻撃。",
        }
        boss["moves"] = moves
        attack_slots = [0]
    slot = str(rng.choice(attack_slots or [0]))
    state.setdefault("logs", []).append(f"レイドボスは <@{target['user_id']}> を狙った！")
    temporary = {
        "p1": {"party": [boss], "active_idx": 0},
        "p2": {"party": [target["monster"]], "active_idx": 0},
        "logs": state["logs"],
        "version": 0,
    }
    resolve_action(temporary, "p1", slot, rng)
    state["logs"] = temporary["logs"][-12:]


def advance_raid_until_player_turn(state: dict, rng: Any | None = None) -> tuple[str | None, str | None]:
    """Advance by speed order, automatically resolving every boss turn encountered."""
    outcome = raid_outcome(state)
    if outcome:
        return outcome, None
    order = state.get("turn_order") or []
    if not order:
        raise ValueError("レイドの行動順がありません。")

    for _ in range(len(order) * 2):
        state["turn_index"] = (int(state.get("turn_index", -1)) + 1) % len(order)
        entry = order[state["turn_index"]]
        if entry.get("kind") == "player":
            participant = raid_participant(state, str(entry.get("user_id")))
            if participant and participant in raid_alive_participants(state):
                return None, str(entry["user_id"])
            continue
        if int(state["boss"].get("current_hp") or 0) <= 0:
            return "cleared", None
        resolve_raid_boss_turn(state, rng)
        state["version"] = int(state.get("version", 0)) + 1
        outcome = raid_outcome(state)
        if outcome:
            return outcome, None
    return raid_outcome(state) or "failed", None


def raid_embed(state: dict) -> discord.Embed:
    boss = state["boss"]
    embed = discord.Embed(
        title=f"DDD RAID | TURN {int(state.get('version', 0)) + 1}",
        description="\n".join(state.get("logs", [])[-6:])[:3500] or "レイドが始まる。",
        color=discord.Color.red(),
    )
    embed.add_field(
        name=f"レイドボス | {boss['name']} Lv.{boss['current_level']} [{boss['element_type']}]"[:256],
        value=f"{hp_bar(boss)}\n{boss.get('raid_bonus_label', 'レイドボス')}",
        inline=False,
    )
    for participant in state.get("participants", [])[:RAID_MAX_PARTICIPANTS]:
        monster = participant["monster"]
        condition = "離脱" if participant.get("withdrawn") else "戦闘不能" if monster["current_hp"] <= 0 else hp_bar(monster)
        embed.add_field(
            name=f"<@{participant['user_id']}> | {monster['name']} Lv.{monster['current_level']}"[:256],
            value=condition[:1024],
            inline=True,
        )
    if boss.get("image_url"):
        embed.set_image(url=boss["image_url"])
    embed.set_footer(text="素早さ順に行動。レイドボスは攻撃ごとにランダムな参加者1人だけを狙う。")
    return embed


def raid_lobby_embed(raid: dict, participant_count: int) -> discord.Embed:
    deadline = parse_datetime(raid["join_deadline"])
    boss = raid.get("boss_state") or {}
    embed = discord.Embed(
        title="DDD RAID | 参加者募集中",
        description="レイドチケットを1枚使用して参加します。ホストはいつでも開始でき、募集は3分で自動開始します。",
        color=discord.Color.gold(),
    )
    embed.add_field(name="レイドボス", value=f"**{boss.get('name', '不明なボス')}**\n{boss.get('raid_bonus_label', 'HP強化')}", inline=True)
    embed.add_field(name="参加状況", value=f"{participant_count} / {RAID_MAX_PARTICIPANTS} 人", inline=True)
    embed.add_field(name="参加締切", value=f"<t:{int(deadline.timestamp())}:R>", inline=True)
    embed.add_field(name="討伐報酬（全参加者）", value=f"**宝箱 ×{RAID_CHEST_REWARD}**\n**コイン +{RAID_COIN_REWARD:,}**", inline=False)
    if boss.get("image_url"):
        embed.set_thumbnail(url=boss["image_url"])
    return embed


class RaidJoinSelectView(discord.ui.View):
    def __init__(self, cog: "RaidCog", lobby: "RaidLobbyView", raid_id: str, user_id: str, monsters: list[dict]):
        super().__init__(timeout=120)
        self.cog, self.lobby, self.raid_id, self.user_id, self.monsters = cog, lobby, raid_id, user_id, monsters
        self.page = 0
        self.render()

    def render(self) -> None:
        self.clear_items()
        rows = self.monsters[self.page * 25:(self.page + 1) * 25]
        options = [
            discord.SelectOption(
                label=f"{monster['name']} (Lv.{monster.get('current_level', 1)})"[:100],
                description=f"属性: {monster.get('element_type', '無')} | ID: {monster['id']}"[:100],
                value=str(monster["id"]),
            )
            for monster in rows
        ]
        select = discord.ui.Select(placeholder="レイドに出すモンスターを選択", options=options)
        select.callback = self.select_callback
        self.add_item(select)
        max_page = max(0, (len(self.monsters) - 1) // 25)
        for label, delta, disabled in (("前の25匹", -1, self.page == 0), ("次の25匹", 1, self.page >= max_page)):
            button = discord.ui.Button(label=label, disabled=disabled, row=1)
            button.callback = self.page_callback(delta)
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分のモンスターを選んでください。", ephemeral=True)
            return False
        return True

    def page_callback(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.page = max(0, min((len(self.monsters) - 1) // 25, self.page + delta))
            self.render()
            await interaction.response.edit_message(view=self)
        return callback

    async def select_callback(self, interaction: discord.Interaction):
        monster_id = interaction.data["values"][0]
        await interaction.response.defer()
        try:
            joined = await asyncio.to_thread(self.cog.join_raid, self.raid_id, self.user_id, monster_id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logger.exception("DDD raid join failed")
            await interaction.followup.send("レイド参加に失敗しました。時間を置いて再試行してください。", ephemeral=True)
            return
        self.stop()
        await self.lobby.refresh(int(joined.get("participant_count", 0)))
        await interaction.edit_original_response(content="レイドに参加しました。開始までお待ちください。", view=None)


class RaidLobbyView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid: dict, participant_count: int):
        deadline = parse_datetime(raid["join_deadline"])
        timeout = max(5, int((deadline - datetime.now(timezone.utc)).total_seconds()))
        super().__init__(timeout=timeout)
        self.cog, self.raid, self.participant_count = cog, raid, participant_count
        self.raid_id, self.host_user_id = str(raid["id"]), str(raid["host_user_id"])
        self.message: discord.Message | None = None
        self.start_lock = asyncio.Lock()
        self.started = False

    async def refresh(self, participant_count: int) -> None:
        self.participant_count = participant_count
        if self.message and not self.started:
            try:
                await self.message.edit(embed=raid_lobby_embed(self.raid, participant_count), view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="参加する（レイドチケット×1）", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        try:
            monsters = await asyncio.to_thread(self.cog.player_monsters, user_id)
        except Exception:
            logger.exception("DDD raid participant box load failed")
            await interaction.response.send_message("モンスターの読み込みに失敗しました。", ephemeral=True)
            return
        if not monsters:
            await interaction.response.send_message("レイドに出せるモンスターを所持していません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "レイドに出すモンスターを1体選択してください。参加時にレイドチケットを1枚使用します。",
            view=RaidJoinSelectView(self.cog, self, self.raid_id, user_id, monsters),
            ephemeral=True,
        )

    @discord.ui.button(label="レイドを開始", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.host_user_id:
            await interaction.response.send_message("レイドを開始できるのはホストだけです。", ephemeral=True)
            return
        await interaction.response.defer()
        await self.start(interaction.message)

    async def start(self, message: discord.Message | None) -> None:
        async with self.start_lock:
            if self.started:
                return
            self.started = True
            try:
                state, next_user_id, outcome = await asyncio.to_thread(self.cog.start_raid, self.raid_id, self.host_user_id)
            except ValueError as exc:
                self.started = False
                if message:
                    if "参加者が変わった" in str(exc):
                        await message.edit(content="参加者が増えたため、開始内容を更新しました。もう一度「レイドを開始」を押してください。", embed=raid_lobby_embed(self.raid, self.participant_count), view=self)
                    else:
                        await message.edit(content=str(exc), embed=None, view=None)
                return
            except Exception:
                self.started = False
                logger.exception("DDD raid start failed")
                if message:
                    await message.edit(content="レイド開始に失敗しました。ホストはもう一度開始してください。", embed=None, view=self)
                return
            self.stop()
            if not message:
                return
            if outcome:
                await asyncio.to_thread(self.cog.finalize_raid, self.raid_id, state, int(state.get("version", 0)), outcome)
                content = "レイドは開始直後に敗北しました。" if outcome == "failed" else "レイドを討伐しました。"
                await message.edit(content=content, embed=raid_embed(state), view=None)
                return
            view = RaidBattleView(self.cog, self.raid_id, state, next_user_id)
            view.message = message
            await message.edit(
                content=f"<@{next_user_id}> のターンです。",
                embed=raid_embed(state),
                view=view,
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=int(next_user_id))]),
            )

    async def on_timeout(self) -> None:
        await self.start(self.message)


class RaidBattleView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: str, state: dict, turn_user_id: str):
        super().__init__(timeout=180)
        self.cog, self.raid_id, self.state, self.turn_user_id = cog, raid_id, state, str(turn_user_id)
        self.version = int(state.get("version", 0))
        self.message: discord.Message | None = None
        self.lock = asyncio.Lock()
        self.used = False
        participant = raid_participant(state, self.turn_user_id)
        if not participant:
            return
        for index, move in enumerate(normalize_moves(participant["monster"].get("moves"))):
            effect = move.get("effect", "変化") if move["category"] == "status" else f"威{move['power']}"
            button = discord.ui.Button(
                label=f"{move['name']} [{move['type']}] {effect} / 命{move['accuracy']}"[:80],
                style=discord.ButtonStyle.primary,
                row=0,
            )
            button.callback = self.callback_for(str(index))
            self.add_item(button)
        leave = discord.ui.Button(label="レイドから離脱", style=discord.ButtonStyle.secondary, row=1)
        leave.callback = self.callback_for("surrender")
        self.add_item(leave)

    def callback_for(self, action: str):
        async def callback(interaction: discord.Interaction):
            await self.execute_turn(interaction, action)
        return callback

    async def execute_turn(self, interaction: discord.Interaction, action: str) -> None:
        if str(interaction.user.id) != self.turn_user_id:
            await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
            return
        await interaction.response.defer()
        async with self.lock:
            if self.used:
                await interaction.followup.send("このターンは処理済みです。", ephemeral=True)
                return
            state = copy.deepcopy(self.state)
            try:
                resolve_raid_player_action(state, self.turn_user_id, action)
                state["version"] = int(state.get("version", 0)) + 1
                outcome = raid_outcome(state)
                next_user_id = None
                if not outcome:
                    outcome, next_user_id = advance_raid_until_player_turn(state)
                if outcome:
                    finalized = await asyncio.to_thread(self.cog.finalize_raid, self.raid_id, state, self.version, outcome)
                    if not finalized:
                        self.used = True
                        await interaction.followup.send("古い操作です。/ddd_raid_resume で最新のレイドを開いてください。", ephemeral=True)
                        return
                else:
                    saved = await asyncio.to_thread(self.cog.save_raid_state, self.raid_id, state, self.version)
                    if not saved:
                        self.used = True
                        await interaction.followup.send("古い操作です。/ddd_raid_resume で最新のレイドを開いてください。", ephemeral=True)
                        return
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            except Exception:
                logger.exception("DDD raid turn failed")
                await interaction.followup.send("レイド更新に失敗しました。/ddd_raid_resume で最新状態を確認してください。", ephemeral=True)
                return

            self.used = True
            self.stop()
            if outcome:
                if outcome == "cleared":
                    state.setdefault("logs", []).append(f"レイド討伐！ 全参加者に宝箱×{RAID_CHEST_REWARD}、コイン+{RAID_COIN_REWARD:,}。")
                    content = "レイド討伐！ 全参加者に報酬を配布しました。"
                else:
                    state.setdefault("logs", []).append("参加者全員が戦闘不能になった。レイド失敗。")
                    content = "レイド失敗。次の挑戦に備えましょう。"
                await interaction.edit_original_response(content=content, embed=raid_embed(state), view=None)
                return
            view = RaidBattleView(self.cog, self.raid_id, state, next_user_id)
            view.message = interaction.message
            await interaction.edit_original_response(
                content=f"<@{next_user_id}> のターンです。",
                embed=raid_embed(state),
                view=view,
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=int(next_user_id))]),
            )

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="操作期限切れ。`/ddd_raid_resume` でレイドを再表示できます。", view=self)
            except discord.HTTPException:
                pass


class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_start_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self.auto_start_expired_raids.start()

    def cog_unload(self) -> None:
        self.auto_start_expired_raids.cancel()

    @staticmethod
    def rpc_secret() -> str:
        if not RAID_RPC_SECRET:
            raise RuntimeError("DDD_RAID_RPC_SECRET is not configured")
        return RAID_RPC_SECRET

    @tasks.loop(seconds=15)
    async def auto_start_expired_raids(self) -> None:
        """Start expired lobbies even if the original Discord view disappeared after a restart."""
        if self.auto_start_lock.locked():
            return
        async with self.auto_start_lock:
            expired = await asyncio.to_thread(
                lambda: supabase.table("ddd_raids").select("id,host_user_id,channel_id")
                .eq("status", "recruiting").lte("join_deadline", datetime.now(timezone.utc).isoformat())
                .order("join_deadline").limit(20).execute().data or []
            )
            for raid in expired:
                try:
                    state, next_user_id, outcome = await asyncio.to_thread(self.start_raid, str(raid["id"]), str(raid["host_user_id"]))
                    if outcome:
                        await asyncio.to_thread(self.finalize_raid, str(raid["id"]), state, int(state.get("version", 0)), outcome)
                    channel_id = raid.get("channel_id")
                    channel = self.bot.get_channel(int(channel_id)) if channel_id else None
                    if channel and hasattr(channel, "send"):
                        if outcome == "cleared":
                            await channel.send("レイド討伐！ 全参加者に報酬を配布しました。", embed=raid_embed(state))
                        elif outcome == "failed":
                            await channel.send("レイド失敗。次の挑戦に備えましょう。", embed=raid_embed(state))
                        else:
                            view = RaidBattleView(self, str(raid["id"]), state, str(next_user_id))
                            view.message = await channel.send(
                                content=f"<@{next_user_id}> のターンです。",
                                embed=raid_embed(state),
                                view=view,
                                allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=int(next_user_id))]),
                            )
                except ValueError as exc:
                    if "参加者が変わった" not in str(exc):
                        logger.warning("DDD automatic raid start skipped for %s: %s", raid["id"], exc)
                except Exception:
                    logger.exception("DDD automatic raid start failed for %s", raid["id"])

    @auto_start_expired_raids.before_loop
    async def before_auto_start_expired_raids(self) -> None:
        await self.bot.wait_until_ready()

    def player_monsters(self, user_id: str) -> list[dict]:
        return supabase.table("monsters").select("*").eq("user_id", str(user_id)).order("created_at", desc=True).execute().data or []

    def active_raid_for(self, user_id: str) -> dict | None:
        rows = supabase.table("ddd_raid_participants").select("raid_id").eq("user_id", str(user_id)).execute().data or []
        for row in rows:
            raid = supabase.table("ddd_raids").select("*").eq("id", row["raid_id"]).in_("status", ["recruiting", "active"]).limit(1).execute().data
            if raid:
                return raid[0]
        return None

    def create_raid(self, user_id: str, monster_id: str, channel_id: str | None) -> dict:
        own = supabase.table("monsters").select("*").eq("id", monster_id).eq("user_id", user_id).execute().data
        if not own:
            raise ValueError("指定したモンスターが見つかりません。/ddd_boxでIDを確認してください。")
        candidates = supabase.table("monsters").select("*").gte("current_level", 30).execute().data or []
        boss_source = random.choice(candidates or own)
        boss = build_raid_boss(boss_source)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=RAID_LOBBY_SECONDS)
        try:
            result = supabase.rpc("ddd_create_raid", {
                "p_host_user_id": user_id,
                "p_monster_id": monster_id,
                "p_boss_state": boss,
                "p_join_deadline": deadline.isoformat(),
                "p_channel_id": channel_id,
                "p_access_token": self.rpc_secret(),
            }).execute()
        except Exception as exc:
            raise ValueError(self.raid_error(exc)) from exc
        raid = payload(result.data)
        if not raid:
            raise RuntimeError("レイド募集の作成に失敗しました。")
        return raid

    def join_raid(self, raid_id: str, user_id: str, monster_id: str) -> dict:
        try:
            result = supabase.rpc("ddd_join_raid", {
                "p_raid_id": raid_id,
                "p_user_id": user_id,
                "p_monster_id": monster_id,
                "p_access_token": self.rpc_secret(),
            }).execute()
        except Exception as exc:
            raise ValueError(self.raid_error(exc)) from exc
        joined = payload(result.data)
        if not joined:
            raise RuntimeError("レイド参加を確定できませんでした。")
        return joined

    def start_raid(self, raid_id: str, host_user_id: str) -> tuple[dict, str | None, str | None]:
        record_result = supabase.table("ddd_raids").select("*").eq("id", raid_id).eq("status", "recruiting").limit(1).execute()
        if not record_result.data:
            raise ValueError("このレイドはすでに開始済み、または終了しています。")
        raid = record_result.data[0]
        if str(raid["host_user_id"]) != str(host_user_id):
            raise ValueError("レイドを開始できるのはホストだけです。")
        participants = supabase.table("ddd_raid_participants").select("user_id,monster_id,monster_snapshot,joined_at").eq("raid_id", raid_id).order("joined_at").execute().data or []
        if not participants:
            raise ValueError("参加者がいないためレイドを開始できません。")
        missing = [row for row in participants if not isinstance(row.get("monster_snapshot"), dict)]
        if missing:
            raise ValueError("参加モンスター情報が見つかりません。レイドを作り直してください。")
        raid_players = [
            {"user_id": str(row["user_id"]), "monster": prepare_party([row["monster_snapshot"]])[0], "withdrawn": False}
            for row in participants
        ]
        boss = copy.deepcopy(raid.get("boss_state") or {})
        if not boss:
            raise ValueError("レイドボス情報が見つかりません。")
        order = [
            {"kind": "player", "user_id": row["user_id"], "speed": calc_stat(row["monster"]["max_speed"], row["monster"]["current_level"])}
            for row in raid_players
        ]
        order.append({"kind": "boss", "user_id": RAID_BOSS_MARKER, "speed": calc_stat(boss["max_speed"], boss["current_level"])})
        order.sort(key=lambda row: (-int(row["speed"]), 1 if row["kind"] == "boss" else 0, str(row["user_id"])))
        state = {
            "mode": "raid",
            "boss": boss,
            "participants": raid_players,
            "roster": [{"user_id": str(row["user_id"]), "monster_id": str(row["monster_id"])} for row in participants],
            "turn_order": [{"kind": row["kind"], "user_id": row["user_id"]} for row in order],
            "turn_index": -1,
            "version": 0,
            "logs": [f"レイド開始！ {len(raid_players)}人が **{boss['name']}** に挑む。{boss.get('raid_bonus_label', '')}"],
        }
        outcome, next_user_id = advance_raid_until_player_turn(state)
        try:
            started = supabase.rpc("ddd_start_raid", {
                "p_raid_id": raid_id,
                "p_host_user_id": host_user_id,
                "p_state": state,
                "p_access_token": self.rpc_secret(),
            }).execute()
        except Exception as exc:
            raise ValueError(self.raid_error(exc)) from exc
        if not payload(started.data):
            raise RuntimeError("レイド開始の確定に失敗しました。")
        return state, next_user_id, outcome

    def save_raid_state(self, raid_id: str, state: dict, expected_version: int) -> bool:
        result = supabase.rpc("ddd_save_raid_state", {
            "p_raid_id": raid_id,
            "p_expected_version": expected_version,
            "p_state": state,
            "p_access_token": self.rpc_secret(),
        }).execute()
        return bool(payload(result.data))

    def finalize_raid(self, raid_id: str, state: dict, expected_version: int, outcome: str) -> bool:
        result = supabase.rpc("ddd_finalize_raid", {
            "p_raid_id": raid_id,
            "p_expected_version": expected_version,
            "p_state": state,
            "p_outcome": outcome,
            "p_access_token": self.rpc_secret(),
        }).execute()
        return bool(payload(result.data))

    @staticmethod
    def raid_error(exc: Exception) -> str:
        message = str(exc).lower()
        errors = {
            "raid_ticket_missing": "レイドチケットが必要です。宝箱から入手するか、ショップで購入してください。",
            "raid_monster_not_found": "指定したモンスターが見つかりません。",
            "raid_user_busy": "すでに参加中または進行中のレイドがあります。",
            "raid_recruitment_closed": "このレイドの募集は終了しています。",
            "raid_already_joined": "すでにこのレイドへ参加しています。",
            "raid_full": f"このレイドは最大{RAID_MAX_PARTICIPANTS}人です。",
            "raid_not_host": "レイドを開始できるのはホストだけです。",
            "raid_not_recruiting": "このレイドはすでに開始済み、または終了しています。",
            "raid_roster_changed": "レイド参加者が変わりました。もう一度開始してください。",
        }
        return next((text for code, text in errors.items() if code in message), "レイド処理に失敗しました。")

    @app_commands.command(name="ddd_raid", description="レイドチケットで3分間のマルチレイドを募集します")
    @app_commands.describe(monster_id="レイドに出すモンスターのID")
    async def raid(self, interaction: discord.Interaction, monster_id: str):
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        try:
            active = await asyncio.to_thread(self.active_raid_for, user_id)
            if active:
                raise ValueError("すでに参加中または進行中のレイドがあります。/ddd_raid_resume で再表示できます。")
            raid = await asyncio.to_thread(self.create_raid, user_id, monster_id, str(interaction.channel_id) if interaction.channel_id else None)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logger.exception("DDD raid creation failed")
            await interaction.followup.send("レイド募集の作成に失敗しました。", ephemeral=True)
            return
        view = RaidLobbyView(self, raid, 1)
        view.message = await interaction.followup.send(
            content=f"<@{user_id}> がレイド参加者を募集しています。",
            embed=raid_lobby_embed(raid, 1),
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(users=[interaction.user]),
        )

    @app_commands.command(name="ddd_raid_resume", description="募集中または進行中のレイドを再表示します")
    async def raid_resume(self, interaction: discord.Interaction):
        await interaction.response.defer()
        raid = await asyncio.to_thread(self.active_raid_for, str(interaction.user.id))
        if not raid:
            await interaction.followup.send("参加中または進行中のレイドはありません。", ephemeral=True)
            return
        if raid["status"] == "recruiting":
            if parse_datetime(raid["join_deadline"]) <= datetime.now(timezone.utc):
                await interaction.followup.send("募集締切を処理中です。レイドは自動で開始されます。", ephemeral=True)
                return
            count = await asyncio.to_thread(lambda: supabase.table("ddd_raid_participants").select("id", count="exact").eq("raid_id", raid["id"]).execute().count or 0)
            view = RaidLobbyView(self, raid, count)
            view.message = await interaction.followup.send(embed=raid_lobby_embed(raid, count), view=view, wait=True)
            return
        state = raid.get("raid_state") or {}
        user_id = raid_turn_user(state)
        if not user_id:
            await interaction.followup.send("レイド状態を復元できません。管理者へレイドIDを連絡してください。", ephemeral=True)
            return
        view = RaidBattleView(self, str(raid["id"]), state, user_id)
        view.message = await interaction.followup.send(
            content=f"<@{user_id}> のターンです。",
            embed=raid_embed(state),
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=int(user_id))]),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
