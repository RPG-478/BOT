import asyncio
import json
import random
from collections import Counter
import os
import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ======================================================
#  CPU プレイヤー定義
# ======================================================
PERSONALITIES  = ["論理的", "攻撃的", "慎重", "臆病", "お調子者"]
_CPU_NAMES     = ["あごむにAI1号", "あごむにAI2号", "あごむにAI3号", "あごむにAI4号", "あごむにAI5号"]
_CPU_ID_BASE   = -10001   # 負値IDでDiscord IDと衝突しない


class CPUMember:
    """discord.Member の簡易モック（CPU専用）"""
    def __init__(self, cpu_id: int, name: str):
        self.id           = cpu_id
        self.display_name = name
        self.mention      = f"**{name}**"


class CPUPlayer:
    """AIプレイヤーの状態・記憶管理（仕様書 §3）"""
    def __init__(self, cpu_id: int, name: str, personality: str):
        self.member            = CPUMember(cpu_id, name)
        self.personality       = personality
        # 記憶層（Memory Layer）
        self.long_term_memo: str  = ""    # フェーズ終了時にMemoAIが更新
        self.divination_results: dict = {}  # 占い師CPU用 {対象名: "人狼"/"人間"}


# ======================================================
#  ゲーム状態（AI拡張版）
# ======================================================
class JinrouAIGame:
    def __init__(self):
        self.is_running              = False
        self.players                 = []
        self.roles: dict             = {}       # {player_id: role_name}
        self.alive_players           = []
        self.night_actions: dict     = {}       # {player_id: target_id}
        self.voted_count: dict       = {}
        self.last_executed           = None
        self.game_channel            = None
        self.used_hadouhou           = False
        self.day_count               = 0
        self.wan_owner: dict         = {}
        self.masai_evasion: dict     = {}
        self.silenced_players        = set()
        self.chairman_skip_event     = None
        self.chairman_ketsugu_used   = False
        self.chairman_ketsugu_target = None
        self.in_discussion           = False
        self.riacchu_pairs           = []
        self.kizoku_slave: dict      = {}
        # ── AI拡張フィールド ──────────────────────────
        self.cpu_players: dict[int, CPUPlayer] = {}
        self.public_event_log: list[str] = []   # 夜の出来事・追放等の全体公開ログ
        self.discussion_log:   list[str] = []   # 現フェーズのチャットログ（短期ログ）


# ======================================================
#  Cog 本体
# ======================================================
class JinrouAICog(commands.Cog):
    def __init__(self, bot):
        self.bot         = bot
        self.games: dict[int, JinrouAIGame] = {}
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # ── ゲーム取得 ──────────────────────────────────────
    def get_game(self, channel_id: int) -> JinrouAIGame:
        if channel_id not in self.games:
            self.games[channel_id] = JinrouAIGame()
        return self.games[channel_id]

    # ── 汎用ヘルパー ────────────────────────────────────
    def _get_player_name(self, game: JinrouAIGame, guild, p_id: int) -> str:
        """CPU・人間問わず表示名を返す"""
        if p_id in game.cpu_players:
            return game.cpu_players[p_id].member.display_name
        m = guild.get_member(p_id)
        return m.display_name if m else f"不明({p_id})"

    def get_wolves_names(self, game: JinrouAIGame) -> str:
        wolves = []
        for p_id, role in game.roles.items():
            if role in ["人狼", "デカ狼"]:
                wolves.append(self._get_player_name(game, game.game_channel.guild, p_id))
        return "、".join(wolves) if wolves else "なし"

    # ======================================================
    #  Groq API ラッパー（reply_2.py のパターンを流用）
    # ======================================================
    async def _groq_async(self, model: str, messages: list, max_tokens: int = 200) -> str:
        loop = asyncio.get_event_loop()
        try:
            resp = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.groq_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.8,
                        max_tokens=max_tokens
                    )
                ),
                timeout=15.0
            )
            return resp.choices[0].message.content.strip()
        except asyncio.TimeoutError:
            print(f"[Groq Timeout] model={model}")
            return ""
        except Exception as e:
            print(f"[Groq Error] {e}")
            return ""

    # ======================================================
    #  戦略判断層 — Decision AI（仕様書 §2.2）
    # ======================================================
    async def _decision_ai_discuss(self, game: JinrouAIGame, cpu: CPUPlayer) -> dict:
        """発言すべきか・どんな戦略で発言するかを判断"""
        role        = game.roles.get(cpu.member.id, "不明")
        alive_names = [self._get_player_name(game, game.game_channel.guild, p.id)
                       for p in game.alive_players]
        recent_log  = "\n".join(game.discussion_log[-10:]) or "なし"

        prompt = (
            f"人狼ゲームCPU「{cpu.member.display_name}」（性格:{cpu.personality}、役職:{role}）\n"
            f"生存者: {', '.join(alive_names)}\n"
            f"最近の会話:\n{recent_log}\n"
            f"長期メモ: {cpu.long_term_memo or 'なし'}\n\n"
            "今このタイミングで発言すべきか判断し、以下のJSON形式のみで返してください（余分な文字不要）:\n"
            '{"should_speak": true, "strategy_prompt": "発言の方向性（30文字以内）"}\n'
            'または {"should_speak": true, "strategy_prompt": ""}'
        )
        result = await self._groq_async(
            "llama3-8b-8192",
            [{"role": "user", "content": prompt}],
            max_tokens=80
        )
        try:
            s = result.find("{"); e = result.rfind("}") + 1
            if s >= 0 and e > s:
                return json.loads(result[s:e])
        except Exception:
            pass
        return {"should_speak": True, "strategy_prompt": "議論に参加する"}

    async def _decision_ai_vote(self, game: JinrouAIGame, cpu: CPUPlayer) -> int | None:
        """投票対象を戦略的に決定"""
        role       = game.roles.get(cpu.member.id, "不明")
        candidates = [p for p in game.alive_players if p.id != cpu.member.id]
        if not candidates:
            return None

        c_names  = [self._get_player_name(game, game.game_channel.guild, p.id) for p in candidates]
        disc_log = "\n".join(game.discussion_log[-15:]) or "なし"
        evt_log  = "\n".join(game.public_event_log[-8:])  or "なし"

        prompt = (
            f"人狼ゲームCPU「{cpu.member.display_name}」（性格:{cpu.personality}、役職:{role}）の投票フェーズ。\n"
            f"追放候補リスト: {', '.join(c_names)}\n"
            f"ゲームイベント:\n{evt_log}\n"
            f"今日の議論:\n{disc_log}\n"
            f"長期メモ: {cpu.long_term_memo or 'なし'}\n\n"
            "追放候補リストの中から最も排除すべき1人を選び、その名前のみを1行で返してください。"
        )
        result = await self._groq_async(
            "llama-3.3-70b-versatile",
            [{"role": "user", "content": prompt}],
            max_tokens=30
        )
        result = result.strip().split("\n")[0].strip()
        for p in candidates:
            name = self._get_player_name(game, game.game_channel.guild, p.id)
            if name in result or result in name:
                return p.id
        return random.choice([p.id for p in candidates])

    async def _decision_ai_night(self, game: JinrouAIGame, cpu: CPUPlayer) -> int | None:
        """夜のアクション対象を戦略的に決定"""
        role     = game.roles.get(cpu.member.id, "不明")
        wolf_ids = {pid for pid, r in game.roles.items()
                    if r in ["人狼", "デカ狼", "狂人", "狂信者"]}

        # 人狼陣営CPUは村人陣営を優先的に狙う（フェアプレイ・ルール §3.2 は維持）
        if role in ["人狼", "デカ狼"]:
            candidates = [p for p in game.alive_players
                          if p.id != cpu.member.id and p.id not in wolf_ids]
        else:
            candidates = [p for p in game.alive_players if p.id != cpu.member.id]

        if not candidates:
            candidates = [p for p in game.alive_players if p.id != cpu.member.id]
        if not candidates:
            return None

        c_names   = [self._get_player_name(game, game.game_channel.guild, p.id) for p in candidates]
        role_guide = {
            "人狼":          "最も危険な村人を排除せよ",
            "デカ狼":        "最も危険な村人を排除せよ",
            "占い師":        "最も怪しい人物を占え",
            "騎士":          "狼に狙われそうな重要人物を守れ",
            "罠師":          "狼に狙われそうな重要人物を守れ",
            "マサイ族":      "最も怪しい人物を観察せよ",
            "あごむに破道砲":"最も危険な人物を排除せよ",
            "ワンころ":      "最も信頼できる人物を飼い主に選べ",
        }.get(role, "戦略的に選択せよ")

        prompt = (
            f"人狼ゲームCPU「{cpu.member.display_name}」（役職:{role}）の夜アクション。\n"
            f"行動指針: {role_guide}\n"
            f"対象候補: {', '.join(c_names)}\n"
            f"長期メモ: {cpu.long_term_memo or 'なし'}\n"
            f"占い記録: {str(cpu.divination_results) if cpu.divination_results else 'なし'}\n\n"
            "対象候補の中から1人を選び、名前のみを1行で返してください。"
        )
        result = await self._groq_async(
            "llama-3.3-70b-versatile",
            [{"role": "user", "content": prompt}],
            max_tokens=30
        )
        result = result.strip().split("\n")[0].strip()
        for p in candidates:
            name = self._get_player_name(game, game.game_channel.guild, p.id)
            if name in result or result in name:
                return p.id
        return random.choice([p.id for p in candidates])

    # ======================================================
    #  性格・表現層 — Generation AI（仕様書 §2.3）
    # ======================================================
    async def _generation_ai(self, game: JinrouAIGame, cpu: CPUPlayer, strategy: str) -> str:
        """戦略プロンプトを個別口調のメッセージに変換"""
        role        = game.roles.get(cpu.member.id, "不明")
        alive_names = [self._get_player_name(game, game.game_channel.guild, p.id)
                       for p in game.alive_players]
        recent_log  = "\n".join(game.discussion_log[-8:]) or "なし"
        p_desc      = {
            "論理的":   "冷静・根拠重視・断定的な口調",
            "攻撃的":   "積極的・強引・他者を追い詰める口調",
            "慎重":     "様子見・曖昧な言い方・断言を避ける口調",
            "臆病":     "自信なさそう・同調しがちな口調",
            "お調子者": "明るい・軽口が多い・場を和ませる口調",
        }.get(cpu.personality, cpu.personality)

        prompt = (
            f"人狼ゲームプレイヤー「{cpu.member.display_name}」として発言してください。\n"
            f"口調・性格: {p_desc}\n"
            f"役職（内部情報・直接言及は戦略的に必要な場合のみ）: {role}\n"
            f"生存者: {', '.join(alive_names)}\n"
            f"最近の会話:\n{recent_log}\n"
            f"戦略指示: {strategy}\n\n"
            "制約:\n"
            "・AIや機械であることを示唆する表現は絶対禁止\n"
            "・ゲーム外の話題に言及しない\n"
            "・80文字以内でタメ語"
        )
        result = await self._groq_async(
            "llama3-8b-8192",
            [{"role": "user", "content": prompt}],
            max_tokens=120
        )
        return (result[:97] + "…") if len(result) > 100 else result

    # ======================================================
    #  記憶層 — Memo AI（仕様書 §2.1）
    # ======================================================
    async def _update_cpu_memos(self, game: JinrouAIGame):
        """フェーズ終了時に全CPU生存者の長期メモを更新"""
        if not game.cpu_players:
            return
        disc_log = "\n".join(game.discussion_log[-15:]) or "なし"
        evt_log  = "\n".join(game.public_event_log[-5:])  or "なし"

        alive_cpu_ids = [p.id for p in game.alive_players if p.id in game.cpu_players]
        tasks = [
            self._update_single_memo(
                game, game.cpu_players[cid],
                game.roles.get(cid, "不明"), evt_log, disc_log
            )
            for cid in alive_cpu_ids
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _update_single_memo(
        self, game: JinrouAIGame, cpu: CPUPlayer,
        role: str, evt_log: str, disc_log: str
    ):
        prompt = (
            f"人狼ゲームCPU「{cpu.member.display_name}」（役職:{role}）のフェーズ終了メモ更新。\n"
            f"既存メモ: {cpu.long_term_memo or 'なし'}\n"
            f"今フェーズの出来事: {evt_log}\n"
            f"今フェーズの議論: {disc_log}\n\n"
            "次フェーズへの引き継ぎ情報を100文字以内で。"
            "疑わしい人物・注目点・有効な戦略を簡潔に記録してください。"
        )
        new_memo = await self._groq_async(
            "llama3-8b-8192",
            [{"role": "user", "content": prompt}],
            max_tokens=150
        )
        if new_memo:
            cpu.long_term_memo = new_memo

    # ======================================================
    #  CPUゲームアクション
    # ======================================================
    async def _cpu_discussion_task(self, game: JinrouAIGame, cpu: CPUPlayer):
        """CPUの議論参加タスク。run_discussionと並行実行（仕様書 §4.1）"""
        try:
            await asyncio.sleep(random.uniform(10, 35))
            speak_count = 0

            while game.in_discussion and game.is_running and speak_count < 2:
                if not any(p.id == cpu.member.id for p in game.alive_players):
                    break

                # 戦略判断層: 発言すべきか判断
                decision = await self._decision_ai_discuss(game, cpu)
                if decision.get("should_speak"):
                    strategy = decision.get("strategy_prompt", "議論に参加する")
                    # 性格・表現層: メッセージ生成
                    msg_text = await self._generation_ai(game, cpu, strategy)
                    if msg_text and game.in_discussion and game.is_running:
                        embed = discord.Embed(
                            description=f"**{cpu.member.display_name}**: {msg_text}",
                            color=0xAAAAAA
                        )
                        await game.game_channel.send(embed=embed)
                        # 短期ログに自分の発言も追加
                        game.discussion_log.append(f"{cpu.member.display_name}: {msg_text}")
                        speak_count += 1

                if speak_count < 2:
                    # 次の発言まで待機（戦略的沈黙の実装）
                    await asyncio.sleep(random.uniform(30, 70))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[CPU Discuss Error] {cpu.member.display_name}: {e}")

    async def _cpu_vote_all(self, game: JinrouAIGame):
        """全CPU生存者の投票を並列処理（仕様書 §4.2）"""
        alive_cpus = [game.cpu_players[p.id] for p in game.alive_players
                      if p.id in game.cpu_players]
        if alive_cpus:
            await asyncio.gather(
                *[self._cpu_single_vote(game, cpu) for cpu in alive_cpus],
                return_exceptions=True
            )

    async def _cpu_single_vote(self, game: JinrouAIGame, cpu: CPUPlayer):
        await asyncio.sleep(random.uniform(3, 20))
        if not game.is_running or cpu.member.id in game.voted_count:
            return
        target_id = await self._decision_ai_vote(game, cpu)
        if target_id is not None:
            # ボタンUIを介さず game.voted_count に直接書き込む（仕様書 §4.2）
            game.voted_count[cpu.member.id] = str(target_id)
            await game.game_channel.send(
                f"🤖 **{cpu.member.display_name}** さんが投票を完了しました。"
            )

    async def _cpu_night_actions_all(self, game: JinrouAIGame):
        """全CPU生存者の夜アクションを並列処理（仕様書 §4.2）"""
        active_roles = {"占い師", "騎士", "罠師", "人狼", "デカ狼",
                        "あごむに破道砲", "マサイ族", "ワンころ"}
        alive_cpus = []
        for p in game.alive_players:
            if p.id not in game.cpu_players:
                continue
            role = game.roles.get(p.id)
            if role not in active_roles:
                continue
            if role == "ワンころ"      and game.day_count != 1:
                continue
            if role == "あごむに破道砲" and game.day_count < 3:
                continue
            alive_cpus.append(game.cpu_players[p.id])

        if alive_cpus:
            await asyncio.gather(
                *[self._cpu_single_night_action(game, cpu) for cpu in alive_cpus],
                return_exceptions=True
            )

    async def _cpu_single_night_action(self, game: JinrouAIGame, cpu: CPUPlayer):
        await asyncio.sleep(random.uniform(2, 15))
        if cpu.member.id in game.night_actions:
            return

        target_id = await self._decision_ai_night(game, cpu)
        if target_id is None:
            return

        # ルール遵守チェック: 対象が生存しているか最終確認（仕様書 §6）
        alive_ids = {p.id for p in game.alive_players}
        if target_id not in alive_ids:
            alts = [p.id for p in game.alive_players if p.id != cpu.member.id]
            if not alts:
                return
            target_id = random.choice(alts)

        # game.night_actions に直接書き込む（仕様書 §4.2）
        game.night_actions[cpu.member.id] = target_id
        role = game.roles.get(cpu.member.id)

        # 占い師CPUの場合：結果を記憶層（long_term_memo）に記録
        if role == "占い師":
            t_role = game.roles.get(target_id)
            t_name = self._get_player_name(game, game.game_channel.guild, target_id)
            res    = "人狼" if t_role in ["人狼", "入狼", "ワンころ"] else "人間"
            # ビー玉ブレイカー効果
            if any(game.roles.get(p.id) == "ビー玉ブレイカー" for p in game.alive_players):
                if random.random() < 0.3:
                    res = "人間" if res == "人狼" else "人狼"
            cpu.divination_results[t_name] = res
            cpu.long_term_memo += f"\n[占い結果] {t_name}: {res}"

        # ワンころCPUの飼い主設定
        if role == "ワンころ" and game.day_count == 1:
            game.wan_owner[cpu.member.id] = target_id

    # ======================================================
    #  メッセージ監視（サイレンス・議長・短期ログ記録）
    # ======================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        game = self.games.get(message.channel.id)
        if not game or not game.is_running:
            return

        # 短期ログに記録（議論フェーズ中、コマンド以外）
        if game.in_discussion and message.content and not message.content.startswith("/"):
            game.discussion_log.append(
                f"{message.author.display_name}: {message.content[:80]}"
            )

        # サイレンス処理
        if message.author.id in game.silenced_players:
            try:
                await message.delete()
            except Exception:
                pass
            return

        # 議長コマンド
        if game.in_discussion:
            player_role = game.roles.get(message.author.id)
            is_alive    = any(p.id == message.author.id for p in game.alive_players)

            if player_role == "議長" and is_alive:
                content = message.content.strip()

                if content == "スキップ":
                    if game.chairman_skip_event and not game.chairman_skip_event.is_set():
                        await game.game_channel.send(
                            "議長がスキップを宣言。議論を終了し投票フェーズに移行します。"
                        )
                        game.chairman_skip_event.set()

                elif content.startswith("決議") and not game.chairman_ketsugu_used:
                    target_name = content[2:].strip()
                    if target_name:
                        target_player = None
                        for p in game.alive_players:
                            if p.id == message.author.id:
                                continue
                            name = self._get_player_name(game, game.game_channel.guild, p.id)
                            if name == target_name:
                                target_player = p
                                break
                        if target_player:
                            game.chairman_ketsugu_target = target_player.id
                            game.chairman_ketsugu_used   = True
                            if game.chairman_skip_event and not game.chairman_skip_event.is_set():
                                game.chairman_skip_event.set()
                            await game.game_channel.send(
                                f"議長が決議を発動！ **{target_name}** の追放が決定されました。"
                            )

    # ======================================================
    #  役職割当（jinrou_6.py より流用）
    # ======================================================
    def assign_roles(self, game: JinrouAIGame):
        num        = len(game.players)
        num_wolves = max(1, num // 5)

        promotion_map = {
            "人狼": "デカ狼",   "騎士": "罠師",
            "一般通過あごむに": "タフむに", "狂人": "狂信者",
            "入狼": "ワンころ", "ハゲ": "コウモリむに",
        }
        def maybe_promote(role):
            if role in promotion_map and random.random() < 0.4:
                return promotion_map[role]
            return role

        pool  = [maybe_promote("一般通過あごむに"), maybe_promote("占い師"), maybe_promote("騎士")]
        pool += [maybe_promote("人狼") for _ in range(num_wolves)]

        pro_roles  = ["ハゲ", "メンヘラ", "あごむに破道砲", "パン屋", "マサイ族",
                      "入狼", "議長", "ビー玉ブレイカー"]
        base_roles = ["霊媒師", "狂人"]

        while len(pool) < num:
            if num >= 6 and pro_roles:
                choice = random.choice(pro_roles + base_roles)
                pool.append(maybe_promote(choice))
                if choice in pro_roles:    pro_roles.remove(choice)
                elif choice in base_roles: base_roles.remove(choice)
            else:
                if base_roles:
                    choice = random.choice(base_roles)
                    pool.append(maybe_promote(choice))
                    base_roles.remove(choice)
                else:
                    pool.append(maybe_promote("一般通過あごむに"))

        pool = pool[:num]

        if num >= 8 and random.random() < 0.3:
            pair_type  = random.choice(["リア充", "貴族奴隷"])
            pair_roles = ["リア充", "リア充"] if pair_type == "リア充" else ["貴族", "奴隷"]
            replaceable = [i for i, r in enumerate(pool) if r in ["一般通過あごむに", "タフむに"]]
            if len(replaceable) >= 2:
                idxs = random.sample(replaceable, 2)
                for i, idx in enumerate(idxs): pool[idx] = pair_roles[i]
            elif len(replaceable) == 1:
                pool[replaceable[0]] = pair_roles[0]
                if len(pool) < num: pool.append(pair_roles[1])
                else: pool[-1] = pair_roles[1]
            else:
                safe = [i for i, r in enumerate(pool) if r not in ["人狼", "デカ狼", "占い師"]]
                if len(safe) >= 2:
                    idxs = random.sample(safe, 2)
                    for i, idx in enumerate(idxs): pool[idx] = pair_roles[i]

        pool = pool[:num]
        random.shuffle(pool)

        for i, p in enumerate(game.players):
            game.roles[p.id] = pool[i]

        riacchu_ids = []; kizoku_id = None; dorei_id = None
        for p in game.players:
            role = game.roles[p.id]
            if role == "リア充":    riacchu_ids.append(p.id)
            elif role == "貴族":    kizoku_id = p.id
            elif role == "奴隷":    dorei_id  = p.id

        if len(riacchu_ids) >= 2:
            game.riacchu_pairs.append((riacchu_ids[0], riacchu_ids[1]))
        if kizoku_id and dorei_id:
            game.kizoku_slave[kizoku_id] = dorei_id

    # ======================================================
    #  コマンド
    # ======================================================
    @app_commands.command(name="kill_ai", description="（AI版）このチャンネルで進行中の人狼ゲームを強制終了します")
    async def kill_ai(self, interaction: discord.Interaction):
        game = self.get_game(interaction.channel_id)
        if not game.is_running:
            embed = discord.Embed(description="このチャンネルで実行中のゲームはありません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        game.is_running    = False
        game.in_discussion = False
        game.silenced_players.clear()
        if game.chairman_skip_event:
            game.chairman_skip_event.set()
        embed = discord.Embed(description="管理者によりゲームが強制終了されました。", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="jinrou_help_ai", description="（AI版）各役職の詳細な説明を表示します")
    async def jinrou_help_ai(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="人狼ゲーム（AI版）役職説明書",
            description="各役職の役割と特徴の一覧です。🤖マークのプレイヤーはAIです。",
            color=0xFFFFFF
        )
        roles_info = {
            "【基本職】一般通過あごむに": "空気。存在しているだけで偉い。特に何もしない。",
            "【上級職】タフむに":         "殺された時に最後の一撃で相手を道連れにする根性の一般通過。",
            "【基本職】占い師":           "毎晩1人を占える。安物のビー玉で人間か人狼かを見抜く。",
            "【基本職】霊媒師":           "昨日追放された者が人間か人狼かを確認する悪趣味な仕事。",
            "【基本職】騎士":             "毎晩1人をつまようじで守る。",
            "【上級職】罠師":             "騎士の上位職。守るだけでなく、狼が守った対象を襲撃した場合に返り討ち。",
            "【基本職】人狼":             "村人を食べる。仲間同士は誰が人狼か知っている。",
            "【上級職】デカ狼":           "占い師を賄賂で黙らせる人狼。占い師に白判定を出させる。",
            "【基本職】狂人":             "人狼の味方をする人間。人狼が誰かは知らない。",
            "【上級職】狂信者":           "人狼とデカ狼が誰かを知っている熱狂的なファン。",
            "【基本職】ハゲ":             "追放されたら勝利。目立ちすぎるバグが発生している。",
            "【上級職】コウモリむに":     "追放されても勝利。最後まで生き残っても個人勝利できる。",
            "【基本職】メンヘラ":         "自分に関与した（占う、守る、食べる）者を物理的に消去する。",
            "【基本職】あごむに破道砲":   "自爆して対象を道連れ。誤発でもう1人巻き込む。（3日目以降）",
            "【基本職】パン屋":           "生きていれば朝にパンを配る。死んでいても何故か届く。",
            "【基本職】マサイ族":         "夜に1人を観察。人狼なら50%で回避準備。",
            "【基本職】入狼":             "占われると人狼判定が出る不幸な村人。",
            "【上級職】ワンころ":         "飼い主を決める。飼い主が死ぬと野良化して人狼になる。",
            "【発展職】議長":             "『スキップ』で議論打ち切り→投票。ゲーム中1回だけ『決議 [名前]』で強制追放。",
            "【発展職】ビー玉ブレイカー": "生きているだけで占い師の判定が30%逆転。パッシブ効果。",
            "【2人役】リア充":            "2人1組。片方が死ぬともう片方も道連れになる。",
            "【2人役】貴族":              "奴隷とセット。死亡判定を奴隷に肩代わりさせる。",
            "【2人役】奴隷":              "貴族とセット。貴族の死亡判定を代わりに受ける。",
        }
        for name, desc in roles_info.items():
            embed.add_field(name=name, value=desc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="jinrou_ai", description="AIプレイヤー入りの人狼ゲームを開始します")
    @app_commands.describe(
        wait_minutes="募集時間（分）。1〜60分で指定（デフォルト: 1）",
        cpu_count="追加するAIプレイヤー数（1〜5、デフォルト: 3）"
    )
    async def jinrou_ai(
        self,
        interaction: discord.Interaction,
        wait_minutes: int = 1,
        cpu_count:    int = 3
    ):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            embed = discord.Embed(description="このチャンネルでは既にゲームが進行中です。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        wait_minutes = max(1, min(wait_minutes, 60))
        cpu_count    = max(1, min(cpu_count, 5))

        # ゲーム状態リセット
        game.is_running              = True
        game.game_channel            = interaction.channel
        game.players                 = []
        game.roles                   = {}
        game.day_count               = 0
        game.wan_owner               = {}
        game.used_hadouhou           = False
        game.last_executed           = None
        game.masai_evasion           = {}
        game.silenced_players        = set()
        game.chairman_ketsugu_used   = False
        game.chairman_ketsugu_target = None
        game.in_discussion           = False
        game.riacchu_pairs           = []
        game.kizoku_slave            = {}
        game.cpu_players             = {}
        game.public_event_log        = []
        game.discussion_log          = []

        view = RecruitView(game, timeout=wait_minutes * 60)
        await interaction.response.send_message(
            f"<a:POYOPOYO:1490724627805110392>人狼ゲーム（AI版）募集開始。"
            f"募集時間: {wait_minutes}分 / AIプレイヤー: {cpu_count}人",
            view=view
        )

        for _ in range(wait_minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running:
                return

        # ── CPUプレイヤーを追加（仕様書 §3.1 擬似アイデンティティ）──
        names_pool = _CPU_NAMES.copy()
        random.shuffle(names_pool)
        for i in range(cpu_count):
            cpu_id      = _CPU_ID_BASE - i
            name        = names_pool[i] if i < len(names_pool) else f"あごむにAI{i+1}号"
            personality = random.choice(PERSONALITIES)
            cpu         = CPUPlayer(cpu_id, name, personality)
            game.cpu_players[cpu_id] = cpu
            game.players.append(cpu.member)   # game.players に人間と混在させる

        await self._start_game_loop(game, interaction.channel)

    # ======================================================
    #  ゲームループ
    # ======================================================
    async def _start_game_loop(self, game: JinrouAIGame, channel):
        if len(game.players) < 5:
            game.is_running = False
            await channel.send("<:failed:1490986584676368535>参加者が5人未満のため、ゲームを中止します。")
            return

        game.alive_players = game.players.copy()
        self.assign_roles(game)

        mentions       = " ".join([p.mention for p in game.players])
        roles_for_disp = []
        for r in game.roles.values():
            if r == "タフむに": roles_for_disp.append("一般通過あごむに")
            elif r == "入狼":   roles_for_disp.append("人狼")
            else:               roles_for_disp.append(r)
        roles_list = " / ".join(set(roles_for_disp))

        await channel.send(
            f"<:success:1490985168100659322>{mentions}\n"
            f"ゲーム開始。今回の役職内訳: {roles_list}\n"
            "下のボタンで自分の役職を確認してください。（🤖はAIプレイヤーです）",
            view=RoleCheckView(game, self)
        )

        # ── CPU初期メモ設定（役職・仲間情報を記憶層へ）──────
        for cpu_id, cpu in game.cpu_players.items():
            role       = game.roles.get(cpu_id, "不明")
            memo_parts = [f"自分の役職: {role}"]

            for pair in game.riacchu_pairs:
                if cpu_id in pair:
                    partner_id   = pair[1] if pair[0] == cpu_id else pair[0]
                    partner_name = self._get_player_name(game, channel.guild, partner_id)
                    memo_parts.append(f"リア充パートナー: {partner_name}")

            if role == "貴族":
                slave_id = game.kizoku_slave.get(cpu_id)
                if slave_id:
                    memo_parts.append(f"奴隷: {self._get_player_name(game, channel.guild, slave_id)}")
            if role == "奴隷":
                for k_id, s_id in game.kizoku_slave.items():
                    if s_id == cpu_id:
                        memo_parts.append(f"貴族: {self._get_player_name(game, channel.guild, k_id)}")

            if role in ["人狼", "デカ狼", "狂信者"]:
                memo_parts.append(f"人狼仲間: {self.get_wolves_names(game)}")

            cpu.long_term_memo = " / ".join(memo_parts)

        # ── 人間プレイヤーへDM通知（CPU にはスキップ）──────
        for pair in game.riacchu_pairs:
            for i, p_id in enumerate(pair):
                if p_id in game.cpu_players:
                    continue
                partner_id   = pair[1] if i == 0 else pair[0]
                member       = channel.guild.get_member(p_id)
                partner_name = self._get_player_name(game, channel.guild, partner_id)
                if member:
                    try:
                        await member.send(
                            f"あなたは **リア充** です。パートナーは **{partner_name}** です。"
                            "片方が死ぬともう片方も道連れになります。"
                        )
                    except Exception:
                        pass

        for kizoku_id, dorei_id in game.kizoku_slave.items():
            for p_id, role_key in [(kizoku_id, "貴族"), (dorei_id, "奴隷")]:
                if p_id in game.cpu_players:
                    continue
                m = channel.guild.get_member(p_id)
                if not m:
                    continue
                other_id   = dorei_id if role_key == "貴族" else kizoku_id
                other_name = self._get_player_name(game, channel.guild, other_id)
                desc = (
                    f"あなたは **貴族** です。奴隷は **{other_name}** です。"
                    "死亡判定がかかった際、奴隷が生存していれば自動的に肩代わりされます。"
                    if role_key == "貴族" else
                    f"あなたは **奴隷** です。貴族は **{other_name}** です。"
                    "貴族に死亡判定がかかると、代わりにあなたが死にます。"
                )
                try:
                    await m.send(desc)
                except Exception:
                    pass

        try:
            await self.run_discussion(game, minutes=2, title="特別ディスカッション")

            while game.is_running:
                await self.run_night_phase(game)
                if not game.is_running or await self.check_victory(game):
                    break

                game.chairman_ketsugu_target = None
                await self.run_discussion(game, minutes=3, title="昼のディスカッション")
                if not game.is_running:
                    break

                if game.chairman_ketsugu_target:
                    await self.apply_forced_execution(game, game.chairman_ketsugu_target)
                    game.chairman_ketsugu_target = None
                else:
                    await self.run_voting_phase(game)

                if not game.is_running or await self.check_victory(game):
                    break

        except Exception as e:
            print(f"[Game Error] {e}")
        finally:
            game.silenced_players.clear()
            game.in_discussion = False
            game.is_running    = False

    # ======================================================
    #  フェーズ処理
    # ======================================================
    async def run_discussion(self, game: JinrouAIGame, minutes: int, title: str):
        if not game.is_running:
            return
        game.chairman_skip_event = asyncio.Event()
        game.in_discussion       = True
        game.discussion_log      = []   # 短期ログをリセット（仕様書 §4.3）

        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        if any(game.roles.get(p.id) == "パン屋" for p in game.alive_players):
            await game.game_channel.send("<:PANYA:1490254577558093944>パン屋がパンを焼きました")

        # CPU発言タスクを各CPU分起動
        cpu_tasks = [
            asyncio.create_task(
                self._cpu_discussion_task(game, game.cpu_players[p.id])
            )
            for p in game.alive_players if p.id in game.cpu_players
        ]

        for _ in range(minutes * 60):
            if game.chairman_skip_event.is_set():
                break
            await asyncio.sleep(1)
            if not game.is_running:
                game.in_discussion = False
                for t in cpu_tasks: t.cancel()
                return

        game.in_discussion = False
        for t in cpu_tasks:
            t.cancel()

        await game.game_channel.send(f"ーー {title}終了 ーー")

        # フェーズ終了時にMemoAIでメモ更新（仕様書 §4.3）
        await self._update_cpu_memos(game)

    async def run_night_phase(self, game: JinrouAIGame):
        if not game.is_running:
            return
        game.day_count += 1
        await game.game_channel.send(f"ーー 第{game.day_count}夜（1分） ーー")
        game.silenced_players.update(p.id for p in game.alive_players)

        game.night_actions = {}
        view = NightActionView(game)
        msg  = await game.game_channel.send("アクションを選択してください", view=view)

        # CPUの夜アクションを並列で非同期起動
        asyncio.create_task(self._cpu_night_actions_all(game))

        req_roles = ["占い師", "騎士", "罠師", "人狼", "デカ狼", "あごむに破道砲", "マサイ族"]
        if game.day_count == 1:
            req_roles.append("ワンころ")
        req = sum(1 for p in game.alive_players if game.roles.get(p.id) in req_roles)

        t = 0
        while len(game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running:
                break

        try:
            await msg.delete()
        except Exception:
            pass

        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        await self.process_night_results(game)

    async def process_night_results(self, game: JinrouAIGame):
        if not game.is_running:
            return
        dead_ids          = set()
        wolf_attacks      = {}
        knight_targets    = set()
        trap_targets      = {}
        psycho_killer_ids = {p.id for p in game.alive_players if game.roles.get(p.id) == "メンヘラ"}
        menhera_triggered = False

        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)
            if t_id in psycho_killer_ids:
                dead_ids.add(p_id)
                menhera_triggered = True
            if role in ["人狼", "デカ狼"]:
                wolf_attacks[p_id] = t_id
            elif role == "騎士":
                knight_targets.add(t_id)
            elif role == "罠師":
                trap_targets[t_id] = p_id
            elif role == "あごむに破道砲":
                dead_ids.add(p_id); dead_ids.add(t_id)
                game.used_hadouhou = True
                others = [p.id for p in game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))
                await game.game_channel.send("あごむに破道砲が火を噴きました。")
            elif role == "ワンころ" and game.day_count == 1:
                game.wan_owner[p_id] = t_id

        if menhera_triggered:
            await game.game_channel.send("<:MENHERA:1490254584739008522>誰かがメンヘラに返り討ちにされました。")

        for wolf_id, target_id in wolf_attacks.items():
            if wolf_id in dead_ids:
                continue
            if target_id in trap_targets:
                dead_ids.add(wolf_id)
                await game.game_channel.send("罠師の罠が発動！ 狼が罠にかかりました。")
                continue
            if target_id in knight_targets:
                continue
            if game.roles.get(target_id) == "マサイ族" and game.masai_evasion.get(target_id):
                if random.random() < 0.5:
                    await game.game_channel.send("<:MASAI:1490254590757572758>マサイ族は襲撃を回避しました。")
                    continue
            dead_ids.add(target_id)

        # 貴族/奴隷置換
        final_dead          = set()
        already_substituted = set()
        for d_id in list(dead_ids):
            if d_id in already_substituted:
                continue
            if game.roles.get(d_id) == "貴族":
                slave_id = game.kizoku_slave.get(d_id)
                if (slave_id
                        and slave_id in {p.id for p in game.alive_players}
                        and slave_id not in dead_ids):
                    await game.game_channel.send("貴族の死亡判定が奴隷に肩代わりされました。")
                    final_dead.add(slave_id)
                    already_substituted.add(slave_id)
                    continue
            final_dead.add(d_id)

        # リア充連鎖死
        for pair in game.riacchu_pairs:
            if pair[0] in final_dead or pair[1] in final_dead:
                final_dead.add(pair[0])
                final_dead.add(pair[1])

        # 死亡処理（_get_player_name で CPU/人間を統一）
        if final_dead:
            for d_id in list(final_dead):
                if d_id not in {p.id for p in game.alive_players}:
                    continue
                name = self._get_player_name(game, game.game_channel.guild, d_id)
                await game.game_channel.send(f"夜の結果: **{name}** さんが犠牲になりました。")
                game.public_event_log.append(f"第{game.day_count}夜: {name}が犠牲になった")

                # タフむにの反撃
                if game.roles.get(d_id) == "タフむに":
                    killers = [
                        pid for pid, tid in game.night_actions.items()
                        if tid == d_id
                        and pid not in final_dead
                        and pid in {p.id for p in game.alive_players}
                    ]
                    if killers:
                        k_id   = random.choice(killers)
                        k_name = self._get_player_name(game, game.game_channel.guild, k_id)
                        await game.game_channel.send(f"タフむにの反撃。**{k_name}** を道連れにしました。")
                        game.silenced_players.add(k_id)
                        game.alive_players = [p for p in game.alive_players if p.id != k_id]
                        game.public_event_log.append(f"タフむに反撃: {k_name}が道連れ")

                game.silenced_players.add(d_id)
                game.alive_players = [p for p in game.alive_players if p.id != d_id]
        else:
            await game.game_channel.send("<:KISHI:1490254592800456794>夜の結果: 昨晩の犠牲者はいないようです。")

    # ======================================================
    #  勝利判定
    # ======================================================
    async def check_victory(self, game: JinrouAIGame) -> bool:
        if not game.is_running:
            return True

        wolves_alive = [p for p in game.alive_players if game.roles.get(p.id) in ["人狼", "デカ狼"]]
        if not wolves_alive:
            await game.game_channel.send("人狼全滅。村人陣営の勝利です。")
            await self._check_koumorimuni_win(game)
            game.is_running = False
            return True

        def is_wolf_side(p_id):
            r = game.roles.get(p_id)
            if r in ["人狼", "デカ狼", "狂人", "狂信者"]: return True
            if r == "ワンころ":
                owner_id = game.wan_owner.get(p_id)
                if owner_id is None: return True
                if owner_id not in {p.id for p in game.alive_players}: return True
            return False

        wolves     = [p for p in game.alive_players if is_wolf_side(p.id)]
        non_wolves = [p for p in game.alive_players if not is_wolf_side(p.id)]
        if len(wolves) >= len(non_wolves):
            await game.game_channel.send("人狼が支配した。人狼陣営の勝利です。")
            await self._check_koumorimuni_win(game)
            game.is_running = False
            return True

        return False

    async def _check_koumorimuni_win(self, game: JinrouAIGame):
        koumoris = [p for p in game.alive_players if game.roles.get(p.id) == "コウモリむに"]
        if not koumoris:
            return
        names = [self._get_player_name(game, game.game_channel.guild, p.id) for p in koumoris]
        await game.game_channel.send(f"さらに、{'、'.join(names)} は最後まで生き残り個人勝利しました！")

    # ======================================================
    #  議長の強制追放
    # ======================================================
    async def apply_forced_execution(self, game: JinrouAIGame, target_id: int):
        if not game.is_running: return
        alive_ids = {p.id for p in game.alive_players}
        if target_id not in alive_ids: return

        actual_id = target_id
        if game.roles.get(actual_id) == "貴族":
            slave_id = game.kizoku_slave.get(actual_id)
            if slave_id and slave_id in alive_ids:
                slave_name = self._get_player_name(game, game.game_channel.guild, slave_id)
                await game.game_channel.send(f"貴族の処刑判定が奴隷 **{slave_name}** に肩代わりされました。")
                actual_id = slave_id

        name = self._get_player_name(game, game.game_channel.guild, actual_id)
        game.last_executed = actual_id
        game.silenced_players.add(actual_id)
        game.alive_players = [p for p in game.alive_players if p.id != actual_id]
        game.public_event_log.append(f"議長決議追放: {name}")

        executed_role = game.roles.get(actual_id)
        if executed_role == "ハゲ":
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492>ハゲが追放された。ハゲの勝利です。")
            game.is_running = False; return
        elif executed_role == "コウモリむに":
            await game.game_channel.send("コウモリむにが追放された。コウモリむにの勝利です。")
            game.is_running = False; return

        for pair in game.riacchu_pairs:
            if actual_id in pair:
                partner_id = pair[1] if pair[0] == actual_id else pair[0]
                if partner_id in {p.id for p in game.alive_players}:
                    partner_name = self._get_player_name(game, game.game_channel.guild, partner_id)
                    await game.game_channel.send(f"リア充のパートナー **{partner_name}** も道連れになりました。")
                    game.silenced_players.add(partner_id)
                    game.alive_players = [p for p in game.alive_players if p.id != partner_id]
                break

    # ======================================================
    #  投票フェーズ
    # ======================================================
    async def run_voting_phase(self, game: JinrouAIGame):
        if not game.is_running: return
        await game.game_channel.send("ーー 投票フェーズ（40秒） ーー")
        game.silenced_players.update(p.id for p in game.alive_players)

        opts = [discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in game.alive_players]
        opts.append(discord.SelectOption(label="スキップ", value="skip"))
        game.voted_count = {}
        view = PublicVoteView(game, opts)
        msg  = await game.game_channel.send("生存者は投票してください", view=view)

        # CPUの投票を並列で非同期起動
        asyncio.create_task(self._cpu_vote_all(game))

        for _ in range(40):
            await asyncio.sleep(1)
            if not game.is_running: break

        try:
            await msg.delete()
        except Exception:
            pass

        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        if not game.voted_count:
            return await game.game_channel.send("投票なし。追放はありません。")

        counts = Counter(game.voted_count.values())
        most   = counts.most_common()

        if len(most) > 1 and most[0][1] == most[1][1]:
            return await game.game_channel.send("同数票のためスキップされました。追放はありません。")

        target_id_str = most[0][0]
        if target_id_str == "skip":
            return await game.game_channel.send("投票の結果、スキップされました。追放はありません。")

        actual_target_id = int(target_id_str)
        target_name      = self._get_player_name(game, game.game_channel.guild, actual_target_id)

        # 貴族/奴隷チェック
        if game.roles.get(actual_target_id) == "貴族":
            slave_id = game.kizoku_slave.get(actual_target_id)
            if slave_id and slave_id in {p.id for p in game.alive_players}:
                slave_name = self._get_player_name(game, game.game_channel.guild, slave_id)
                await game.game_channel.send(f"貴族の処刑判定が奴隷 **{slave_name}** に肩代わりされました。")
                actual_target_id = slave_id
                target_name      = slave_name

        await game.game_channel.send(f"**{target_name}** さんが追放されました。")
        game.last_executed = actual_target_id
        game.silenced_players.add(actual_target_id)
        game.alive_players = [p for p in game.alive_players if p.id != actual_target_id]
        game.public_event_log.append(f"追放: {target_name}")

        executed_role = game.roles.get(actual_target_id)
        if executed_role == "ハゲ":
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492>ハゲが追放された。ハゲの勝利です。")
            game.is_running = False; return
        elif executed_role == "コウモリむに":
            await game.game_channel.send("コウモリむにが追放された。コウモリむにの勝利です。")
            game.is_running = False; return

        for pair in game.riacchu_pairs:
            if actual_target_id in pair:
                partner_id = pair[1] if pair[0] == actual_target_id else pair[0]
                if partner_id in {p.id for p in game.alive_players}:
                    partner_name = self._get_player_name(game, game.game_channel.guild, partner_id)
                    await game.game_channel.send(f"リア充のパートナー **{partner_name}** も道連れになりました。")
                    game.silenced_players.add(partner_id)
                    game.alive_players = [p for p in game.alive_players if p.id != partner_id]
                break


# ======================================================
#  UI コンポーネント（役職確認・夜アクション・募集・投票）
# ======================================================
class RoleCheckView(discord.ui.View):
    def __init__(self, game: JinrouAIGame, cog: JinrouAICog):
        super().__init__(timeout=None)
        self.game = game
        self.cog  = cog

    @discord.ui.button(label="役職確認", style=discord.ButtonStyle.primary)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        real_role = self.game.roles.get(interaction.user.id)
        if real_role is None:
            embed = discord.Embed(description="あなたはゲームに参加していません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        display_role = real_role
        if real_role == "タフむに": display_role = "一般通過あごむに"
        elif real_role == "入狼":   display_role = "人狼"

        wolves = self.cog.get_wolves_names(self.game)
        guild  = self.game.game_channel.guild

        # リア充パートナー
        partner_name = "不明"
        for pair in self.game.riacchu_pairs:
            if interaction.user.id in pair:
                partner_id   = pair[1] if pair[0] == interaction.user.id else pair[0]
                partner_name = self.cog._get_player_name(self.game, guild, partner_id)

        # 貴族の奴隷
        slave_name = "不明"
        if real_role == "貴族":
            slave_id = self.game.kizoku_slave.get(interaction.user.id)
            if slave_id:
                slave_name = self.cog._get_player_name(self.game, guild, slave_id)

        # 奴隷の貴族
        kizoku_name = "不明"
        if real_role == "奴隷":
            for k_id, s_id in self.game.kizoku_slave.items():
                if s_id == interaction.user.id:
                    kizoku_name = self.cog._get_player_name(self.game, guild, k_id)
                    break

        descs = {
            "一般通過あごむに": "一般通過あごむに。空気より存在感が薄い。",
            "占い師":           "毎晩1人を占える。金がないのでビー玉で占っている。",
            "霊媒師":           "昨日追放された者の正体を覗き見る趣味がある。",
            "人狼":             f"仲間: {wolves}",
            "騎士":             "毎晩一人をつまようじで守る。",
            "罠師":             "毎晩一人を守る。狼が守った対象を攻撃した場合、その狼を返り討ちにする。",
            "狂人":             "人狼の味方。基本的に無能である。",
            "ハゲ":             "追放されたら勝てる。",
            "コウモリむに":     "追放されても勝利。最後まで生き残っても個人勝利できる。",
            "メンヘラ":         "自分に関与した者を物理的に消す。",
            "あごむに破道砲":   "自らを弾にして1人を狙い撃ち。誤発でもう1人殺す。（3日目夜以降）",
            "デカ狼":           f"占い師に白判定を出させる。仲間: {wolves}",
            "パン屋":           "生きているうちは朝にパンを配る。",
            "マサイ族":         "夜に1人を観察。人狼なら50%で回避準備。",
            "入狼":             "生まれた名前が悪かった。占われると人狼判定が出る村人。",
            "ワンころ":         "最初の夜に飼い主を決める。飼い主がいないと人狼になる。",
            "タフむに":         "殺された時に相手を道連れにする根性の一般通過あごむに。",
            "狂信者":           f"人狼とデカ狼を知っている熱狂的なファン。仲間: {wolves}",
            "議長":             "『スキップ』で議論終了→投票へ。ゲーム中1回『決議 [名前]』で強制追放。",
            "ビー玉ブレイカー": "生きているだけで占い師の判定が30%逆転。パッシブ効果。",
            "リア充":           f"パートナー: {partner_name}。片方が死ぬと両方道連れになる。",
            "貴族":             f"奴隷: {slave_name}。死亡判定を奴隷に肩代わりさせられる。",
            "奴隷":             f"貴族: {kizoku_name}。貴族の死亡判定を代わりに受ける。",
        }

        role_image_map = {
            "一般通過あごむに": "NOMAL.PNG",      "人狼": "JINROU.PNG",          "マサイ族": "MASAI.PNG",
            "メンヘラ": "MENHERA.PNG",             "入狼": "NYUROU.PNG",           "騎士": "KISHI.PNG",
            "占い師": "URANAI.PNG",                "霊媒師": "REIBAI.PNG",         "パン屋": "PANYA.PNG",
            "狂人": "KYOJIN.PNG",                  "ハゲ": "HAGE.PNG",             "デカ狼": "DEKAROU.PNG",
            "あごむに破道砲": "AGOMUNIHADOHOU.PNG","ワンころ": "WANKORO.PNG",
            "タフむに": "TAHUMUNI.PNG",             "狂信者": "KYOUSINSYA.PNG",
            "罠師": "WANASSI.PNG",                  "議長": "GICHOU.PNG",
            "ビー玉ブレイカー": "BEEBREAKER.PNG",  "リア充": "RIAJUU.PNG",
            "貴族": "KIZOKU.PNG",                   "奴隷": "DOREI.PNG",           "コウモリむに": "KOUMORI.PNG",
        }

        embed = discord.Embed(
            title=f"あなたの役職は 【{display_role}】 です",
            description=descs.get(real_role, "詳細なし"),
            color=0xFFFFFF
        )

        filename = role_image_map.get(real_role)
        if filename:
            file_path = f"Assets/{filename}"
            if os.path.exists(file_path):
                file = discord.File(file_path, filename="role_img.png")
                embed.set_image(url="attachment://role_img.png")
                await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
                return

        await interaction.response.send_message(embed=embed, ephemeral=True)


class NightActionView(discord.ui.View):
    def __init__(self, game: JinrouAIGame):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="夜のアクション", style=discord.ButtonStyle.success)
    async def action(self, interaction: discord.Interaction, button: discord.ui.Button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return

        if p_id in self.game.night_actions:
            embed = discord.Embed(description="アクションは既に完了しています。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        role = self.game.roles.get(p_id)

        if role == "あごむに破道砲" and self.game.day_count < 3:
            embed = discord.Embed(
                description=f"あごむに破道砲は第3夜からしか使用できません。(現在は第{self.game.day_count}夜)",
                color=0xFFFFFF
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        passive_roles = [
            "一般通過あごむに", "霊媒師", "狂人", "ハゲ", "コウモリむに",
            "メンヘラ", "パン屋", "入狼", "タフむに", "狂信者",
            "ビー玉ブレイカー", "リア充", "貴族", "奴隷", "議長"
        ]
        if role in passive_roles:
            embed = discord.Embed(description="お前は寝てろ。明日の朝までじっとしてなさい。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        opts = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in self.game.alive_players if p.id != p_id
        ]
        if not opts:
            embed = discord.Embed(description="対象がいません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(description="対象を選択してください：", color=0xFFFFFF)
        await interaction.response.send_message(
            embed=embed, view=ActionSelectView(self.game, opts, role), ephemeral=True
        )


class ActionSelectView(discord.ui.View):
    def __init__(self, game: JinrouAIGame, options: list, role: str):
        super().__init__(timeout=60)
        self.game = game
        self.role = role
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction: discord.Interaction):
        p_id = interaction.user.id
        if p_id in self.game.night_actions:
            embed = discord.Embed(description="既にアクションは受理されています。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        t_id = int(self.children[0].values[0])
        self.game.night_actions[p_id] = t_id

        if self.role == "占い師":
            r   = self.game.roles.get(t_id)
            res = "人狼" if r in ["人狼", "入狼", "ワンころ"] else "人間"
            if any(self.game.roles.get(p.id) == "ビー玉ブレイカー" for p in self.game.alive_players):
                if random.random() < 0.3:
                    res = "人間" if res == "人狼" else "人狼"
            embed = discord.Embed(description=f"<:URANAI:1490255412837093568>結果: 【{res}】", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.role == "マサイ族":
            r = self.game.roles.get(t_id)
            if r in ["人狼", "デカ狼"]:
                self.game.masai_evasion[p_id] = True
            embed = discord.Embed(description="<:MASAI:1490254590757572758>対象の観察を完了しました。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.role == "罠師":
            embed = discord.Embed(description="対象に罠を設置しました。狼が攻撃した場合、返り討ちにします。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.role == "ワンころ" and self.game.day_count == 1:
            master_m    = self.game.game_channel.guild.get_member(t_id) if self.game.game_channel else None
            master_name = master_m.display_name if master_m else "不明"
            embed = discord.Embed(
                description=f"飼い主を **{master_name}** に決めました。",
                color=0xFFFFFF
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(description="完了。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)


class RecruitView(discord.ui.View):
    def __init__(self, game: JinrouAIGame, timeout: int):
        super().__init__(timeout=timeout)
        self.game = game

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players:
            self.game.players.append(interaction.user)
            await interaction.response.send_message(
                f"<a:AGOMUNIMUNI:1490255555632037909>{interaction.user.display_name} さんが参加しました。"
            )


class PublicVoteView(discord.ui.View):
    def __init__(self, game: JinrouAIGame, options: list):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction: discord.Interaction):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]:
            embed = discord.Embed(description="死人に口なし。墓場で大人しくしていなさい。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if p_id in self.game.voted_count:
            embed = discord.Embed(description="既に投票済みです。意志を何度も変えることはできません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        self.game.voted_count[p_id] = self.children[0].values[0]
        await interaction.response.send_message(
            f"<u:success:1490985168100659322>{interaction.user.display_name} さんが投票を完了しました。"
        )


async def setup(bot):
    await bot.add_cog(JinrouAICog(bot))
