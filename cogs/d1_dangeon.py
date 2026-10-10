"""D1-omniによるダンジョン代理プレイ。

D1へ渡す入力は、直近のゲームログと map.png のみです。
モデルは次の1手を選ぶだけで、ゲーム状態の確定・ダメージ・報酬・保存は本体が担当します。
"""

import asyncio
import base64
import io
import os
import random
import time

import aiohttp
import discord
from discord.ext import commands

from cogs.dangeon import (
    D1_ENDPOINT,
    D_CHEST,
    D_EVENT,
    D_SHRINE,
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
    d_floor_modifier,
    d_progress_quest,
    dg_save_map,
    dg_save_player,
    dg_starts,
    d_use_job_skill,
    d1_candidate_log,
    d_normalize_choice,
    d_record_action,
    d_begin_run,
    d_end_run,
)


class D1DungeonPlayerCog(commands.Cog):
    """/dungeon画面から起動する連続D1プレイヤー。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks = {}
        self._stops = {}
        self.service_name = os.environ.get("D1_SERVICE_NAME", "llama-d1-omni")
        self._service_lock = asyncio.Lock()
        self._ready_until = 0.0
        self._run_stats = {}

    async def _test_response(self):
        """d1_test.pyと同じ最小pingでsystemoneの稼働を確認する。"""
        payload = {
            "state": "ping",
            "questions": {
                "ping": {
                    "type": "noul",
                    "instructions": "Is this a test?",
                }
            },
        }
        try:
            timeout = aiohttp.ClientTimeout(total=3.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(D1_ENDPOINT, json=payload) as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return False

    async def _start_service(self):
        """d1_test.pyと同じsystemdサービス起動手順を実行する。"""
        try:
            process = await asyncio.create_subprocess_exec(
                "sudo", "systemctl", "start", self.service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=15.0)
            return process.returncode == 0
        except (asyncio.TimeoutError, OSError):
            return False

    async def _ensure_d1_ready(self, logs):
        """ping→起動→モデルロード待機→再pingを一度だけ行う。"""
        if time.monotonic() < self._ready_until:
            return True
        async with self._service_lock:
            if time.monotonic() < self._ready_until:
                return True
            if await self._test_response():
                self._ready_until = time.monotonic() + 30.0
                return True
            logs.append("D1応答なし。systemdサービスを起動します。")
            if not await self._start_service():
                logs.append(f"D1サービス起動失敗: {self.service_name}")
                return False
            logs.append("D1サービスを起動しました。モデルロードを待機中です。")
            for _ in range(12):
                await asyncio.sleep(2.5)
                if await self._test_response():
                    self._ready_until = time.monotonic() + 30.0
                    logs.append("D1サービスの応答を確認しました。")
                    return True
            logs.append("D1サービスは起動しましたが、応答待ちがタイムアウトしました。")
            return False

    def _log_text(self, logs):
        """D1へ渡す唯一のテキスト入力。長すぎる状態やJSONは渡さない。"""
        return "\n".join(logs[-12:])[-5000:]

    async def _call_d1(self, logs, image_bytes, questions):
        """公式のSystem One形式でd1-omniへ画像＋テキストを送る。"""
        if not await self._ensure_d1_ready(logs):
            return ""
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
                        self._ready_until = 0.0
                        detail = " ".join(body.split())[:240]
                        if response.status == 501 and ("image input" in body.lower() or "mmproj" in body.lower()):
                            logs.append("D1画像入力が拒否されました。D1サービスをmmproj付きで起動してください。")
                        logs.append(f"D1 APIエラー: HTTP {response.status}" + (f" / {detail}" if detail else ""))
                        return ""
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        detail = " ".join(body.split())[:240]
                        logs.append("D1 APIエラー: JSON応答を解釈できません" + (f" / {detail}" if detail else ""))
                        return ""
                    answers = data.get("answers", {}) if isinstance(data, dict) else {}
                    key = next(iter(questions), "")
                    answer = answers.get(key, {}) if isinstance(answers, dict) else {}
                    if isinstance(answer, str):
                        return answer
                    if isinstance(answer, dict):
                        choice = answer.get("choice") or answer.get("answer") or answer.get("value")
                        if choice is not None:
                            return str(choice)
                    if isinstance(data, dict) and data.get("choice") is not None:
                        return str(data["choice"])
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
        embed.add_field(name="作戦", value=getattr(view, "d1_plan", "安全探索") + " / 停止: 終了ボタン", inline=False)
        embed.add_field(name="停止条件", value="HP30%未満 / ボス / 遺物 / 10ターン / APIエラー3回 / 同一地点3回", inline=False)
        embed.add_field(name="状態", value=f"{p['floor']}F / HP {p['hp']}/{stats['max_hp']} / {p.get('job', 'warrior')}", inline=False)
        embed.set_image(url="attachment://map.png")
        map_file = d_render_pillow(uid, p["floor"], p["x"], p["y"])
        await message.edit(embed=embed, view=None if final else view, attachments=[map_file])

    async def _run_loop(self, uid, message, view, stop_event):
        plan = getattr(view, "d1_plan", "安全探索")
        logs = [f"D1が代理プレイを開始しました。作戦: {plan} / 終了ボタンで停止できます。"]
        d_begin_run(uid, "d1")
        self._run_stats[uid] = {"turns": 0, "positions": [], "battles": 0}
        try:
            while not stop_event.is_set():
                reason = self._stop_reason(uid, logs)
                if reason:
                    logs.append(f"D1を停止しました: {reason}")
                    break
                await self._play_turn(uid, logs, plan)
                self._run_stats[uid]["turns"] += 1
                await self._edit_screen(message, view, logs)
                reason = self._stop_reason(uid, logs)
                if reason:
                    logs.append(f"D1を停止しました: {reason}")
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
            self._run_stats.pop(uid, None)
            d_end_run(uid, "d1_stop")
            logs.append("D1代理プレイを終了しました。")
            try:
                await self._edit_screen(message, view, logs, final=True)
            except Exception:
                pass

    def _stop_reason(self, uid, logs):
        """D1の安全停止条件をゲーム側で一元判定する。"""
        p = d_get_player(uid)
        stats = d_effective_stats(p)
        run = self._run_stats.setdefault(uid, {"turns": 0, "positions": [], "battles": 0})
        position = (p["floor"], p["x"], p["y"])
        positions = run.setdefault("positions", [])
        # 移動できなかったターンも履歴へ記録し、同じ場所での待機・壁選択を検知する。
        positions.append(position)
        positions[:] = positions[-12:]
        if p["hp"] <= 0:
            return "HPが0"
        if p["hp"] < stats["max_hp"] * 0.30:
            return "HPが30%未満"
        if p.get("coins", 0) >= 10000:
            return "所持金が停止閾値に到達"
        if p.get("active_effects"):
            return "状態異常を検知"
        if any("ボス" in line for line in logs[-8:]):
            return "ボス遭遇"
        if any("遺物" in line or "リ relic" in line for line in logs[-8:]):
            return "希少アイテム発見"
        if run.get("turns", 0) >= 10:
            return "1回のD1実行が10ターンに到達"
        if len(positions) >= 3 and positions[-1] == positions[-2] == positions[-3]:
            return "同じ場所で3回連続停止"
        error_lines = logs[-6:]
        if sum("D1 APIエラー" in line or "D1接続エラー" in line for line in error_lines) >= 3:
            return "D1 APIエラーが連続3回"
        if sum("と遭遇しました" in line for line in logs[-8:]) >= 3:
            return "連続戦闘が多いため"
        return ""

    async def _image_bytes(self, uid):
        p = d_get_player(uid)
        image = d_build_map_image(uid, p["floor"], p["x"], p["y"])
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    async def _choose(self, uid, logs, questions):
        return await self._call_d1(logs, await self._image_bytes(uid), questions)

    async def _play_turn(self, uid, logs, plan="安全探索"):
        p = d_get_player(uid)
        floor, x, y = p["floor"], p["x"], p["y"]
        cell = d_get_cell(floor, x, y)
        logs.append(d1_candidate_log(uid, plan))
        d_record_action(uid, "decision", source="d1", result=plan)

        if cell == D_STAIRS:
            choice = await self._choose(uid, logs, {
                "stairs": {"type": "choice", "instructions": "Choose the next action.", "criteria": {
                    "up": "Go to the next floor and recover HP", "stay": "Stay and keep exploring"
                }}
            })
            choice = d_normalize_choice(choice, {"up", "stay"}, "stay")
            if choice == "up" and floor < D_FLOORS:
                p["floor"] = floor + 1
                p["hp"] = d_effective_stats(p)["max_hp"]
                from cogs.dangeon import d_ensure_map
                d_ensure_map(p["floor"])
                p["x"], p["y"] = dg_starts[p["floor"]]
                d_progress_quest(uid, "floor", 1)
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
            choice = d_normalize_choice(choice, {"dig", "leave"}, "leave")
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
            choice = d_normalize_choice(choice, {"buy", "leave"}, "leave")
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
            "move": {"type": "choice", "instructions": "Choose one legal next action. ENTER inspects the current tile.", "criteria": {
                "up": "Move north", "down": "Move south", "left": "Move west", "right": "Move east",
                "leftup": "Move northwest", "rightup": "Move northeast", "leftdown": "Move southwest", "rightdown": "Move southeast",
                "enter": "Inspect or interact with the current tile"
            }}
        })
        directions = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
                      "leftup": (-1, -1), "rightup": (1, -1), "leftdown": (-1, 1), "rightdown": (1, 1)}
        choice = d_normalize_choice(choice, {"up", "down", "left", "right", "leftup", "rightup", "leftdown", "rightdown", "enter"}, "enter")
        if choice == "enter":
            logs.append(f"ENTER: {floor}F ({x},{y}) / {d_floor_modifier(floor)}を確認しました。")
            return
        if choice not in directions:
            logs.append("D1の応答が不正だったため、安全に待機しました。")
            return
        dx, dy = directions[choice]
        nx, ny = x + dx, y + dy
        corner_cut = dx != 0 and dy != 0 and (
            d_get_cell(floor, x + dx, y) == D_WALL or d_get_cell(floor, x, y + dy) == D_WALL
        )
        if (not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H)
                or d_get_cell(floor, nx, ny) == D_WALL or corner_cut):
            logs.append(f"{choice}へ進もうとしましたが壁でした。")
            return
        p["x"], p["y"] = nx, ny
        p["turns"] += 1
        p["season_score"] += 1
        d_progress_quest(uid, "turns", 1)
        logs.append(f"{choice}へ移動しました。現在地: {floor}F ({nx},{ny}) / {d_floor_modifier(floor)}")
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
        if cell == D_SHRINE:
            p["atk"] += 2
            d_consume(floor, x, y)
            logs.append("祭壇の祝福: 基礎ATKが2上昇しました。")
            await dg_save_map(floor, self.bot.supabase)
            return
        if cell == D_EVENT:
            gain = random.randint(40, 120)
            await d_apply_reward(uid, self.bot.supabase, coins=gain, xp=gain, season_score=25, material="ancient_shard")
            d_consume(floor, x, y)
            logs.append(f"旅人の依頼: コイン+{gain} / XP+{gain} / 古代欠片+1")
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
            choice = d_normalize_choice(choice, {"attack", "skill", "defend", "escape"}, "defend")
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
