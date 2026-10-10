"""D1-omniによるダンジョン代理プレイ。

D1へ渡す入力は、直近のゲームログと map.png のみです。
モデルは次の1手を選ぶだけで、ゲーム状態の確定・ダメージ・報酬・保存は本体が担当します。
"""

import asyncio
import base64
import io
import os
import random

import aiohttp
import discord
from discord.ext import commands

from cogs.dangeon import (
    D1_ENDPOINT,
    D_CHEST,
    D_ENCOUNTER_RATES,
    D_FLOORS,
    D_MINE,
    D_REST,
    D_SHOP,
    D_STAIRS,
    D_TRAP,
    D_WALL,
    D_MAP_H,
    D_MAP_W,
    DungeonCombatView,
    d_apply_reward,
    d_build_map_image,
    d_consume,
    d_do_mine,
    d_effective_stats,
    d_get_biome,
    d_get_cell,
    d_get_player,
    d_make_enemy,
    d_render_pillow,
    d_trigger_trap,
    dg_save_map,
    dg_save_player,
    dg_starts,
    d_use_job_skill,
)


class D1DungeonPlayerCog(commands.Cog):
    """/dungeon画面から起動する連続D1プレイヤー。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks = {}
        self._stops = {}

    def _log_text(self, logs):
        """D1へ渡す唯一のテキスト入力。長すぎる状態やJSONは渡さない。"""
        return "\n".join(logs[-12:])[-5000:]

    async def _call_d1(self, logs, image_bytes, questions):
        """d1-omniのchoice結果を安全に取り出す。失敗時は空文字を返す。"""
        payload = {
            "state": self._log_text(logs),
            "images": ["data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")],
            "questions": questions,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(D1_ENDPOINT, json=payload) as response:
                    body = await response.text()
                    if response.status != 200:
                        logs.append(f"D1 APIエラー: HTTP {response.status}")
                        return ""
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        logs.append("D1 APIエラー: JSON応答を解釈できません")
                        return ""
                    answers = data.get("answers", {}) if isinstance(data, dict) else {}
                    key = next(iter(questions), "")
                    answer = answers.get(key, {}) if isinstance(answers, dict) else {}
                    if isinstance(answer, str):
                        return answer
                    if isinstance(answer, dict):
                        return str(answer.get("choice", ""))
                    logs.append("D1 APIエラー: choice結果がありません")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logs.append(f"D1接続エラー: {type(exc).__name__}")
        return ""

    def is_running(self, uid):
        task = self._tasks.get(str(uid))
        return bool(task and not task.done())

    async def start_loop(self, interaction, view):
        """現在の画面メッセージを更新しながら、停止までD1を連続実行する。"""
        uid = str(interaction.user.id)
        if self.is_running(uid):
            await interaction.response.send_message("D1はすでにプレイ中です。", ephemeral=True)
            return
        await interaction.response.defer()
        message = await interaction.original_response()
        stop_event = asyncio.Event()
        self._stops[uid] = stop_event
        task = asyncio.create_task(self._run_loop(uid, message, view, stop_event))
        self._tasks[uid] = task
        await task

    async def stop_loop(self, uid):
        event = self._stops.get(str(uid))
        if event:
            event.set()

    async def _edit_screen(self, message, view, logs, *, final=False):
        uid = view.uid
        p = d_get_player(uid)
        stats = d_effective_stats(p)
        embed = discord.Embed(
            title=f"D1代理プレイ {'終了' if final else '実行中'}",
            description="\n".join(logs[-8:])[-3500:] or "ログはまだありません。",
            color=0x8B5CF6 if not final else 0x666666,
        )
        embed.add_field(name="状態", value=f"{p['floor']}F / HP {p['hp']}/{stats['max_hp']} / {p.get('job', 'warrior')}", inline=False)
        embed.set_image(url="attachment://map.png")
        map_file = d_render_pillow(uid, p["floor"], p["x"], p["y"])
        await message.edit(embed=embed, view=None if final else view, attachments=[map_file])

    async def _run_loop(self, uid, message, view, stop_event):
        logs = ["D1が代理プレイを開始しました。終了ボタンで停止できます。"]
        try:
            while not stop_event.is_set():
                await self._play_turn(uid, logs)
                await self._edit_screen(message, view, logs)
                if d_get_player(uid)["hp"] <= 0:
                    logs.append("HPが0になったため、D1を停止しました。")
                    break
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logs.append("D1のタスクをキャンセルしました。")
            raise
        except Exception as exc:
            logs.append(f"D1プレイエラー: {type(exc).__name__}: {exc}")
        finally:
            self._tasks.pop(uid, None)
            self._stops.pop(uid, None)
            logs.append("D1代理プレイを終了しました。")
            try:
                await self._edit_screen(message, view, logs, final=True)
            except Exception:
                pass

    async def _image_bytes(self, uid):
        p = d_get_player(uid)
        image = d_build_map_image(uid, p["floor"], p["x"], p["y"])
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    async def _choose(self, uid, logs, questions):
        return await self._call_d1(logs, await self._image_bytes(uid), questions)

    async def _play_turn(self, uid, logs):
        p = d_get_player(uid)
        floor, x, y = p["floor"], p["x"], p["y"]
        cell = d_get_cell(floor, x, y)

        if cell == D_STAIRS:
            choice = await self._choose(uid, logs, {
                "stairs": {"type": "choice", "instructions": "Choose the next action.", "criteria": {
                    "up": "Go to the next floor and recover HP", "stay": "Stay and keep exploring"
                }}
            })
            if choice == "up" and floor < D_FLOORS:
                p["floor"] = floor + 1
                p["hp"] = d_effective_stats(p)["max_hp"]
                from cogs.dangeon import d_ensure_map
                d_ensure_map(p["floor"])
                p["x"], p["y"] = dg_starts[p["floor"]]
                logs.append(f"階段を上り、{p['floor']}Fへ進みました。")
            else:
                logs.append("階段では探索を続けました。")
            await dg_save_player(uid, self.bot.supabase)
            return

        if cell == D_MINE:
            choice = await self._choose(uid, logs, {
                "mine": {"type": "choice", "instructions": "Choose the action.", "criteria": {
                    "dig": "Mine coins", "leave": "Leave the mine"
                }}
            })
            if choice == "dig":
                gain = d_do_mine(uid)
                await d_apply_reward(uid, self.bot.supabase, coins=gain, season_score=10)
                d_consume(floor, x, y)
                logs.append(f"鉱山を採掘し、コインを{gain}枚獲得しました。")
                await dg_save_map(floor, self.bot.supabase)
            else:
                logs.append("鉱山を見送りました。")
            await dg_save_player(uid, self.bot.supabase)
            return

        if cell == D_REST:
            stats = d_effective_stats(p)
            before = p["hp"]
            p["hp"] = min(stats["max_hp"], p["hp"] + max(20, stats["max_hp"] // 3))
            d_consume(floor, x, y)
            logs.append(f"休憩所でHPを{p['hp'] - before}回復しました。")
            await dg_save_map(floor, self.bot.supabase)
            await dg_save_player(uid, self.bot.supabase)
            return

        if cell == D_SHOP:
            choice = await self._choose(uid, logs, {
                "shop": {"type": "choice", "instructions": "Choose the action.", "criteria": {
                    "buy": "Buy one healing bread for 30 coins", "leave": "Leave the shop"
                }}
            })
            if choice == "buy":
                try:
                    await d_apply_reward(uid, self.bot.supabase, coins=-30, bread=1)
                    logs.append("商店でレアパンを購入しました。")
                except Exception:
                    logs.append("コイン不足で購入できませんでした。")
            else:
                logs.append("商店で購入せずに進みました。")
            await dg_save_player(uid, self.bot.supabase)
            return

        choice = await self._choose(uid, logs, {
            "move": {"type": "choice", "instructions": "Choose one legal next action.", "criteria": {
                "up": "Move north", "down": "Move south", "left": "Move west", "right": "Move east", "check": "Stay and inspect"
            }}
        })
        directions = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        if choice == "check":
            logs.append(f"{floor}F ({x},{y})を確認しました。")
            return
        if choice not in directions:
            logs.append("D1の応答が不正だったため、安全に待機しました。")
            return
        dx, dy = directions[choice]
        nx, ny = x + dx, y + dy
        if not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H) or d_get_cell(floor, nx, ny) == D_WALL:
            logs.append(f"{choice}へ進もうとしましたが壁でした。")
            return
        p["x"], p["y"] = nx, ny
        logs.append(f"{choice}へ移動しました。現在地: {floor}F ({nx},{ny})")
        await self._resolve_tile(uid, logs)
        await dg_save_player(uid, self.bot.supabase)

    async def _resolve_tile(self, uid, logs):
        p = d_get_player(uid)
        floor, x, y = p["floor"], p["x"], p["y"]
        cell = d_get_cell(floor, x, y)
        if cell == D_CHEST:
            text, reward = d_open_chest(uid, self.bot.supabase)
            await d_apply_reward(uid, self.bot.supabase, **reward)
            d_consume(floor, x, y)
            logs.append(text)
            await dg_save_map(floor, self.bot.supabase)
            return
        if cell == D_TRAP:
            text, penalty = d_trigger_trap(uid)
            await d_apply_reward(uid, self.bot.supabase, **penalty)
            d_consume(floor, x, y)
            logs.append(text)
            await dg_save_map(floor, self.bot.supabase)
            return
        biome, *_ = d_get_biome(floor)
        if random.random() < D_ENCOUNTER_RATES.get(biome, 0.1):
            enemy = d_make_enemy(floor)
            logs.append(f"{enemy['name']}と遭遇しました。")
            await self._auto_combat(uid, enemy, logs)

    async def _auto_combat(self, uid, enemy, logs):
        combat = DungeonCombatView(uid, d_get_player(uid)["floor"], d_get_player(uid)["x"], d_get_player(uid)["y"], enemy, self.bot.supabase)
        while enemy["hp"] > 0 and d_get_player(uid)["hp"] > 0:
            choice = await self._choose(uid, logs, {
                "battle": {"type": "choice", "instructions": "Choose one battle action.", "criteria": {
                    "attack": "Attack normally", "skill": "Use the class skill", "defend": "Defend", "escape": "Try to escape"
                }}
            })
            p = d_get_player(uid)
            if choice == "skill":
                text, damage = d_use_job_skill(uid, enemy)
                enemy["hp"] = max(0, enemy["hp"] - damage)
                logs.append(text)
            elif choice == "defend":
                combat.defending = True
                logs.append("防御しました。")
            elif choice == "escape" and enemy.get("type") != "boss":
                if random.random() < 0.5:
                    logs.append("逃走に成功しました。")
                    return
                logs.append("逃走に失敗しました。")
            else:
                damage, critical = combat._calculate_damage(p, enemy)
                enemy["hp"] = max(0, enemy["hp"] - damage)
                logs.append(f"攻撃で{damage}ダメージを与えました。")
            if enemy["hp"] <= 0:
                await combat._win(_NoopInteraction())
                logs.append("戦闘に勝利しました。")
                return
            logs.append(combat._enemy_turn())
        if d_get_player(uid)["hp"] <= 0:
            await combat._lose(_NoopInteraction())
            logs.append("敗北し、1Fへ戻されました。")

    async def cog_unload(self):
        for event in self._stops.values():
            event.set()
        for task in self._tasks.values():
            task.cancel()


class _NoopResponse:
    async def edit_original_response(self, **kwargs):
        return None


class _NoopInteraction:
    response = _NoopResponse()

    async def edit_original_response(self, **kwargs):
        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(D1DungeonPlayerCog(bot))
