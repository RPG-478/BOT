"""DDD regression tests: python -m unittest test_ddd -v."""
import asyncio
import copy
import random
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

with patch("supabase.create_client"):
    from cogs import ddd_appraisal as scout
    from cogs import ddd_battle as battle
    from cogs import ddd_inventory as inventory
    from cogs import ddd_raid as raid
    from cogs import ddd_system as system
    from cogs import ddd_work as work


def monster(uid="1", mid="dot-1", level=5, stage=0):
    return {
        "id": mid,
        "user_id": uid,
        "name": "テストモンスター",
        "image_url": "https://example.com/dot.png",
        "element_type": "実",
        "characteristic": "標準",
        "trait_id": "none",
        "dice_level": level,
        "dice_talent": 360,
        "dice_ai": 50,
        "dice_ability": 50,
        "current_level": level,
        "current_exp": 0,
        "breakthrough_stage": stage,
        "max_hp": 80,
        "max_attack": 60,
        "max_defense": 55,
        "max_sp_atk": 60,
        "max_sp_def": 55,
        "max_speed": 50,
        "moves": [
            {"name": "打撃", "type": "実", "category": "physical", "power": 45, "accuracy": 100, "description": "攻撃"},
            {"name": "波動", "type": "実", "category": "special", "power": 45, "accuracy": 100, "description": "攻撃"},
            {"name": "回復", "type": "無", "category": "status", "power": 0, "accuracy": 100, "effect": "heal", "description": "回復"},
        ],
    }


def state(size=1):
    return {
        "p1": {"party": battle.prepare_party([monster("1", f"a-{index}") for index in range(size)]), "active_idx": 0},
        "p2": {"party": battle.prepare_party([monster("2", f"b-{index}") for index in range(size)]), "active_idx": 0},
        "logs": [],
        "version": 0,
    }


def interaction(uid=1):
    return SimpleNamespace(
        user=SimpleNamespace(id=uid, display_name="テスト", display_avatar=SimpleNamespace(url="https://example.com/avatar.png")),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), edit_message=AsyncMock(), send_modal=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
        message=MagicMock(),
    )


class FixedRandom:
    def __init__(self, value=0.5):
        self.value = value

    def random(self):
        return self.value

    def uniform(self, _a, b):
        return b


class ChestRandom:
    def __init__(self, random_values, gauss_value=0):
        self.random_values = iter(random_values)
        self.gauss_value = gauss_value

    def random(self):
        return next(self.random_values)

    def gauss(self, _mean, _stddev):
        return self.gauss_value

    def choice(self, values):
        return values[0]

    def sample(self, values, count):
        return list(values)[:count]

    def randint(self, low, _high):
        return low


class InventoryTests(unittest.TestCase):
    def test_chest_coins_are_bounded_and_low_end_is_mode(self):
        self.assertEqual(inventory.chest_coin_reward(ChestRandom([], 0)), 100)
        self.assertEqual(inventory.chest_coin_reward(ChestRandom([], 1_000_000)), 100_000)
        samples = [inventory.chest_coin_reward(random.Random(seed)) for seed in range(500)]
        self.assertTrue(all(100 <= value <= 100_000 for value in samples))
        self.assertLess(sum(samples) / len(samples), 20_000)

    def test_chest_reward_can_produce_each_category(self):
        coin_and_orb = inventory.roll_chest_reward(ChestRandom([0.1], 0))
        self.assertEqual(coin_and_orb["kind"], "bundle")
        self.assertEqual(coin_and_orb["amount"], 100)
        self.assertEqual(coin_and_orb["item_code"], "orb_虚")
        orb = inventory.roll_chest_reward(ChestRandom([0.1], 0))
        self.assertEqual(orb["item_code"], "orb_虚")
        herb = inventory.roll_chest_reward(ChestRandom([0.6], 0))
        self.assertEqual(herb["item_code"], inventory.HERB)
        ticket = inventory.roll_chest_reward(ChestRandom([0.75], 0))
        self.assertEqual(ticket["item_code"], inventory.MOVE_RESET_TICKET)
        trade_ticket = inventory.roll_chest_reward(ChestRandom([0.88], 0))
        self.assertEqual(trade_ticket["item_code"], inventory.TRADE_TICKET)
        raid_ticket = inventory.roll_chest_reward(ChestRandom([0.94], 0))
        self.assertEqual(raid_ticket["item_code"], inventory.RAID_TICKET)
        crystal = inventory.roll_chest_reward(ChestRandom([0.99], 0))
        self.assertEqual(crystal["item_code"], inventory.UPRAISE_CRYSTAL)
        self.assertEqual(crystal["metadata"]["boosts"], [{"stat": "hp", "amount": 1}, {"stat": "attack", "amount": 1}])

    def test_shop_prices_and_weekly_limits(self):
        self.assertEqual(system.SHOP_ITEMS[inventory.ORB_CODES["虚"]][:2], (10_000, 1))
        self.assertEqual(system.SHOP_ITEMS[inventory.MOVE_RESET_TICKET][:2], (7_000, 1))
        self.assertEqual(system.SHOP_ITEMS[inventory.TRADE_TICKET][:2], (7_000, 1))
        self.assertEqual(system.SHOP_ITEMS[inventory.RAID_TICKET][:2], (7_000, 1))
        self.assertEqual(system.SHOP_ITEMS[inventory.HERB][:2], (3_000, 5))
        friday = system.shop_week_start(datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc))
        monday = system.shop_week_start(datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(friday, monday)

    def test_elite_win_chest_rate_boundary(self):
        self.assertTrue(battle.elite_chest_drop(FixedRandom(0.019)))
        self.assertFalse(battle.elite_chest_drop(FixedRandom(0.02)))

    def test_crystal_metadata_has_two_distinct_valid_stats(self):
        metadata = inventory.create_crystal_metadata(random.Random(6))
        boosts = metadata["boosts"]
        self.assertEqual(len(boosts), 2)
        self.assertEqual(len({boost["stat"] for boost in boosts}), 2)
        self.assertTrue(all(boost["stat"] in inventory.STAT_KEYS and 1 <= boost["amount"] <= 10 for boost in boosts))
        self.assertIn("+", inventory.item_label(inventory.UPRAISE_CRYSTAL, metadata))


class ScoutTests(unittest.TestCase):
    def test_scout_tiers_have_required_bounds(self):
        for tier, data in scout.SCOUT_TIERS.items():
            self.assertEqual(data["cost"], {"normal": 500, "ultra": 10_000, "legend": 100_000}[tier])
        self.assertEqual(scout.SCOUT_TIERS["legend"]["talent"], (500, 650))
        self.assertEqual(scout.SCOUT_TIERS["legend"]["ai"], (70, 100))
        self.assertEqual(scout.SCOUT_TIERS["legend"]["ability"], (70, 100))

    def test_normalize_stats_preserves_legend_total(self):
        cog = scout.AppraisalCog(None)
        stats = cog.normalize_stats({"hp": 1, "attack": 9999}, 650, 650)
        self.assertEqual(sum(stats.values()), 650)
        self.assertTrue(all(value >= 10 for value in stats.values()))

    def test_api_key_list_keeps_direct_key_and_deduplicates(self):
        with patch.object(scout, "GEMINI_API_KEYS", ["direct-key", "", "direct-key", "backup-key"]):
            self.assertEqual(scout.unique_api_keys(), ["direct-key", "backup-key"])

    def test_scout_failure_contains_safe_code(self):
        failure = scout.ScoutFailure("SCOUT-008", "画像の保存に失敗しました。", ValueError("secret provider detail"))
        self.assertIn("SCOUT-008", scout.scout_error_text(failure))
        self.assertNotIn("secret provider detail", scout.scout_error_text(failure))

    def test_normal_roll_stays_within_bounds(self):
        for _ in range(200):
            self.assertTrue(500 <= scout.normal_roll(500, 650) <= 650)


class ProgressionTests(unittest.TestCase):
    def test_breakthrough_requirements(self):
        self.assertEqual(system.required_breakthrough(30, 0), (30, 1))
        self.assertEqual(system.required_breakthrough(40, 30), (40, 10))
        self.assertIsNone(system.required_breakthrough(29, 0))
        self.assertIsNone(system.required_breakthrough(41, 40))
        self.assertIsNone(system.required_breakthrough(31, 30))
        self.assertIsNone(system.required_breakthrough(40, 40))

    def test_experience_stops_at_unbroken_milestones(self):
        self.assertEqual(battle.add_experience(29, 80, 250, 0), (30, 230))
        self.assertEqual(battle.add_experience(30, 0, 1000, 0), (30, 1000))
        self.assertEqual(battle.add_experience(30, 1000, 5000, 0), (30, 1000))
        self.assertEqual(battle.add_experience(30, 0, 1000, 30), (31, 0))
        self.assertEqual(battle.add_experience(40, 0, 10_000, 30), (40, 10_000))
        self.assertEqual(battle.add_experience(40, 0, 10_000, 40), (41, 0))
        self.assertEqual(battle.experience_space(30, 200, 0), 800)
        self.assertEqual(battle.experience_space(40, 100, 30), 9900)
        self.assertEqual(battle.experience_space(50, 0, 40), 0)

    def test_stricter_monster_evaluation(self):
        low = monster()
        low.update(dice_talent=100, dice_ai=1, dice_ability=1)
        score, rank = system.strength_evaluation(low)
        self.assertLess(score, 45)
        self.assertEqual(rank, "D")
        high = monster()
        high.update(dice_talent=650, dice_ai=100, dice_ability=100)
        for key in inventory.STAT_KEYS:
            high[f"max_{key}"] = 100
        self.assertEqual(system.strength_evaluation(high)[1], "S")


class EngineTests(unittest.TestCase):
    def test_level_clamps_and_curve(self):
        self.assertEqual(battle.calc_stat(100, 30), 100)
        self.assertEqual(battle.calc_stat(100, 99), 144)
        self.assertEqual(battle.calc_stat(100, -1), battle.calc_stat(100, 1))
        self.assertGreaterEqual(battle.calc_stat(None, None), 1)

    def test_all_type_matchups(self):
        for attack in battle.TYPE_CHART:
            for defense in battle.TYPE_CHART:
                self.assertEqual(battle.get_type_multiplier(attack, defense), battle.TYPE_CHART[attack].get(defense, 1))

    def test_moves_normalize_missing_and_legacy_arrays(self):
        for source in (None, [], [None], [{"power": "bad", "accuracy": None}], [{}] * 7):
            moves = battle.normalize_moves(source)
            self.assertEqual(len(moves), 3)
            self.assertTrue(all(1 <= move["accuracy"] <= 100 for move in moves))

    def test_preparation_does_not_mutate_saved_monster(self):
        saved = monster()
        party = battle.prepare_party([saved])
        party[0]["moves"][0]["name"] = "changed"
        self.assertNotEqual(saved["moves"][0]["name"], "changed")
        self.assertNotIn("current_hp", saved)

    def test_stab_critical_and_guard_legacy_modifier(self):
        current = state()
        actor, target = current["p1"]["party"][0], current["p2"]["party"][0]
        target["element_type"] = "無"
        move = actor["moves"][0]
        damage = battle.calculate_damage(actor, target, move, FixedRandom())[0]
        actor["element_type"] = "正"
        neutral = battle.calculate_damage(actor, target, move, FixedRandom())[0]
        self.assertGreater(damage, neutral)
        critical = battle.calculate_damage(actor, target, move, FixedRandom(), True)[0]
        self.assertGreater(critical, neutral)
        target["guarding"] = True
        guarded = battle.calculate_damage(actor, target, move, FixedRandom())[0]
        self.assertLess(guarded, neutral)

    def test_herb_heals_to_full_and_is_not_guard_action(self):
        current = state()
        actor = current["p1"]["party"][0]
        actor["current_hp"] = 1
        battle.resolve_action(current, "p1", "herb", FixedRandom())
        self.assertEqual(actor["current_hp"], battle.calc_stat(actor["max_hp"], actor["current_level"]))
        with self.assertRaises(ValueError):
            battle.resolve_action(state(), "p1", "guard", FixedRandom())

    def test_accuracy_miss_boundary(self):
        current = state()
        current["p1"]["party"][0]["moves"][1]["accuracy"] = 80
        before = current["p2"]["party"][0]["current_hp"]
        battle.resolve_action(current, "p1", "1", FixedRandom(0.8))
        self.assertEqual(current["p2"]["party"][0]["current_hp"], before)
        self.assertIn("外れた", current["logs"][-1])

    def test_heal_cap_and_three_charges(self):
        current = state()
        actor = current["p1"]["party"][0]
        actor["current_hp"] = 1
        maximum = battle.calc_stat(actor["max_hp"], actor["current_level"])
        for _ in range(5):
            battle.resolve_action(current, "p1", "2", FixedRandom())
        self.assertEqual(actor["heals"], 0)
        self.assertLessEqual(actor["current_hp"], maximum)
        self.assertIn("回数切れ", current["logs"][-1])

    def test_switch_resets_ranks(self):
        current = state(3)
        actor = current["p1"]["party"][0]
        actor["ranks"]["attack"] = 3
        battle.resolve_action(current, "p1", "switch:2")
        self.assertEqual(actor["ranks"], {})
        self.assertEqual(current["p1"]["active_idx"], 2)

    def test_invalid_action_never_mutates_state(self):
        for action in ("switch:0", "switch:4", "switch:-1", "9", "nope", "guard"):
            current = state()
            before = copy.deepcopy(current)
            with self.assertRaises(ValueError):
                battle.resolve_action(current, "p1", action)
            self.assertEqual(current, before)

    def test_poison_duration(self):
        current = state()
        actor = current["p1"]["party"][0]
        actor["moves"][2].update(effect="poison")
        battle.resolve_action(current, "p1", "2", FixedRandom())
        target = current["p2"]["party"][0]
        before = target["current_hp"]
        for _ in range(3):
            battle.resolve_action(current, "p2", "herb")
        self.assertEqual(target["poison"], 0)
        self.assertLess(target["current_hp"], before)

    def test_rank_caps_and_multiplier(self):
        current = state()
        actor = current["p1"]["party"][0]
        actor["moves"][2]["effect"] = "attack_up"
        for _ in range(9):
            battle.resolve_action(current, "p1", "2", FixedRandom())
        self.assertEqual(actor["ranks"]["attack"], 6)
        self.assertEqual(battle.rank_multiplier(100), 4)
        self.assertEqual(battle.rank_multiplier(-100), 0.25)

    def test_auto_switch_and_victory(self):
        current = state(3)
        current["p2"]["party"][0]["current_hp"] = 1
        self.assertIsNone(battle.resolve_action(current, "p1", "0", FixedRandom()))
        self.assertEqual(current["p2"]["active_idx"], 1)
        for target in current["p2"]["party"]:
            target["current_hp"] = 0
        current["p2"]["party"][1]["current_hp"] = 1
        self.assertEqual(battle.resolve_action(current, "p1", "0", FixedRandom()), "p1")

    def test_raid_boss_uses_former_boss_tuning(self):
        boss = raid.build_raid_boss(monster(level=30), random.Random(1))
        self.assertIn(boss["raid_bonus_label"], ("HP3倍 / その他能力1.5倍", "HP4倍 / その他能力1.5倍", "HP5倍 / その他能力1.5倍"))
        self.assertGreater(boss["max_hp"], monster(level=30)["max_hp"])
        self.assertGreater(boss["max_attack"], monster(level=30)["max_attack"])

    def test_raid_boss_attacks_exactly_one_random_participant(self):
        first = battle.prepare_party([monster("1", "first", level=30)])[0]
        second = battle.prepare_party([monster("2", "second", level=30)])[0]
        boss = raid.build_raid_boss(monster("boss", "boss", level=30), random.Random(2))
        current = {
            "boss": boss,
            "participants": [
                {"user_id": "1", "monster": first, "withdrawn": False},
                {"user_id": "2", "monster": second, "withdrawn": False},
            ],
            "logs": [],
            "version": 0,
        }
        before = [first["current_hp"], second["current_hp"]]
        raid.resolve_raid_boss_turn(current, random.Random(3))
        after = [first["current_hp"], second["current_hp"]]
        self.assertEqual(sum(value < old for value, old in zip(after, before)), 1)

    def test_raid_boss_uses_damaging_fallback_for_all_status_moves(self):
        player = battle.prepare_party([monster("1", "player", level=30)])[0]
        boss = raid.build_raid_boss(monster("boss", "boss", level=30), random.Random(2))
        for move in boss["moves"]:
            move.update(category="status", effect="attack_up", power=0)
        current = {"boss": boss, "participants": [{"user_id": "1", "monster": player, "withdrawn": False}], "logs": [], "version": 0}
        before = player["current_hp"]
        raid.resolve_raid_boss_turn(current, random.Random(3))
        self.assertLess(player["current_hp"], before)
        self.assertEqual(boss["moves"][0]["name"], "レイドストライク")

    def test_raid_turn_order_respects_speed_and_skips_to_players(self):
        slow = battle.prepare_party([monster("1", "slow", level=30)])[0]
        slow["max_speed"] = 1
        fast = battle.prepare_party([monster("2", "fast", level=30)])[0]
        fast["max_speed"] = 100
        boss = raid.build_raid_boss(monster("boss", "boss", level=30), random.Random(4))
        boss["max_speed"] = 50
        current = {
            "boss": boss,
            "participants": [
                {"user_id": "1", "monster": slow, "withdrawn": False},
                {"user_id": "2", "monster": fast, "withdrawn": False},
            ],
            "turn_order": [
                {"kind": "player", "user_id": "2"},
                {"kind": "boss", "user_id": raid.RAID_BOSS_MARKER},
                {"kind": "player", "user_id": "1"},
            ],
            "turn_index": -1,
            "logs": [],
            "version": 0,
        }
        outcome, next_user = raid.advance_raid_until_player_turn(current, random.Random(5))
        self.assertIsNone(outcome)
        self.assertEqual(next_user, "2")
        raid.resolve_raid_player_action(current, "2", "surrender")
        outcome, next_user = raid.advance_raid_until_player_turn(current, random.Random(6))
        self.assertIsNone(outcome)
        self.assertEqual(next_user, "1")

    def test_raid_outcome_requires_boss_defeat(self):
        current = {
            "boss": battle.prepare_party([monster("boss", "boss", level=30)])[0],
            "participants": [{"user_id": "1", "monster": battle.prepare_party([monster("1", "player", level=30)])[0], "withdrawn": False}],
        }
        self.assertIsNone(raid.raid_outcome(current))
        current["boss"]["current_hp"] = 0
        self.assertEqual(raid.raid_outcome(current), "cleared")


class DiscordUITests(unittest.IsolatedAsyncioTestCase):
    async def test_cogs_load_and_commands_serialize_without_retired_commands(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        async with bot:
            with patch("supabase.create_client"):
                for extension in ("cogs.ddd_inventory", "cogs.ddd_appraisal", "cogs.ddd_battle", "cogs.ddd_raid", "cogs.ddd_system", "cogs.ddd_work"):
                    await bot.load_extension(extension)
            names = {command.name for command in bot.tree.get_commands()}
            expected = {"ddd_scout", "ddd_legend_scout", "ddd_box", "ddd_loadout", "ddd_upgrade", "ddd_open", "ddd_trade", "ddd_work", "ddd_random_match", "ddd_battle", "ddd_raid", "ddd_raid_resume", "ddd_rename"}
            self.assertTrue(expected <= names)
            retired = {f"ddd_{suffix}" for suffix in ("create", "practice", "appraise", "ultra_scout", "exchange", "unlock_palette")}
            self.assertFalse(retired & names)
            self.assertFalse({"ddd_rename_monster", "ddd_rename_move", "ddd_rename_ability"} & names)
            for command in bot.tree.get_commands():
                self.assertTrue(command.to_dict(bot.tree))

    async def test_box_paging_and_ownership(self):
        view = system.MonsterSelectView("1", [monster(mid=str(index)) for index in range(51)])
        self.assertEqual(len(view.children[0].options), 25)
        await view.page_callback(1)(interaction())
        self.assertEqual(view.children[0].options[0].value, "25")
        await view.page_callback(1)(interaction())
        self.assertEqual(view.children[0].options[0].value, "50")
        self.assertFalse(await view.interaction_check(interaction(2)))
        view.stop()

    async def test_cards_and_action_rows_fit_discord(self):
        self.assertLessEqual(len(system.monster_embed(monster())), 6000)
        current = state(3)
        self.assertLessEqual(len(battle.battle_embed(current)), 6000)
        pvp = battle.BattleView(SimpleNamespace(busy=set()), "b", current, "1", "1", "2")
        random_match = battle.BattleView(SimpleNamespace(busy=set()), None, current, "1", "1", "CPU", practice=True, mode="random")
        self.assertNotIn("薬草（HP全回復）", [child.label for child in pvp.children])
        self.assertIn("薬草（HP全回復）", [child.label for child in random_match.children])
        self.assertTrue(pvp.to_components())
        pvp.stop()
        random_match.stop()

    async def test_stale_board_never_awards(self):
        view = battle.BattleView(SimpleNamespace(busy=set()), "b", state(), "1", "1", "2")
        view.save_turn = MagicMock(return_value=[])
        view.award_exp = MagicMock()
        await view.execute_turn(interaction(), "surrender")
        view.award_exp.assert_not_called()
        view.stop()

    async def test_double_click_writes_once(self):
        view = battle.BattleView(SimpleNamespace(busy={"1", "2"}), "b", state(), "1", "1", "2")
        view.save_turn = MagicMock(return_value=[{"id": "b"}])
        view.award_exp = MagicMock()
        await asyncio.gather(view.execute_turn(interaction(), "surrender"), view.execute_turn(interaction(), "surrender"))
        view.save_turn.assert_called_once()
        view.award_exp.assert_called_once()

    async def test_work_views_have_no_emoji_and_require_owner(self):
        view = work.MonsterWorkSelectView(SimpleNamespace(), "1", [monster()], "normal")
        self.assertFalse(await view.interaction_check(interaction(2)))
        self.assertNotIn("💼", str(view.to_components()))
        view.stop()


if __name__ == "__main__":
    unittest.main()
