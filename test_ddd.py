"""Offline DDD regression tests: python -m unittest test_ddd -v.

Supabase creation is patched before importing the Cogs. No credentials, database,
Discord connection or external AI requests are used by this suite.
"""
import asyncio
import copy
import struct
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

with patch("supabase.create_client"):
    from cogs import ddd_appraisal as studio
    from cogs import ddd_battle as battle
    from cogs import ddd_system as system


def monster(uid="1", mid="dot-1"):
    return {**studio.creator_record(uid, "テストドット", "実", "バランス", "https://example.com/dot.png"), "id": mid}


def state(size=1):
    return {
        "p1": {"party": battle.prepare_party([monster("1", f"a-{i}") for i in range(size)]), "active_idx": 0},
        "p2": {"party": battle.prepare_party([monster("2", f"b-{i}") for i in range(size)]), "active_idx": 0},
        "logs": [], "version": 0,
    }


def interaction(uid=1):
    return SimpleNamespace(user=SimpleNamespace(id=uid), response=SimpleNamespace(
        defer=AsyncMock(), send_message=AsyncMock(), edit_message=AsyncMock(), send_modal=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock(), message=MagicMock())


class FixedRandom:
    def __init__(self, value=0.5):
        self.value = value

    def random(self):
        return self.value

    def uniform(self, a, b):
        return b


class PixelTests(unittest.TestCase):
    def test_all_templates_are_eight_by_eight(self):
        for template in studio.PIXEL_TEMPLATES.values():
            self.assertEqual(len(studio.parse_pixels(template)), 8)

    def test_grid_validation(self):
        for invalid in ("", "1234", "/".join(["44444444"] * 8), "/".join(["0000000"] * 8)):
            with self.assertRaises(ValueError):
                studio.parse_pixels(invalid)

    def test_png_dimensions_checksums_and_transparency(self):
        for color in studio.PIXEL_COLORS:
            data = studio.pixel_png(studio.parse_pixels(studio.PIXEL_TEMPLATES["スライム"]), color)
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            offset, raw = 8, b""
            while offset < len(data):
                length = struct.unpack(">I", data[offset:offset + 4])[0]
                kind = data[offset + 4:offset + 8]
                payload = data[offset + 8:offset + 8 + length]
                checksum = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
                self.assertEqual(checksum, zlib.crc32(kind + payload) & 0xffffffff)
                if kind == b"IHDR":
                    self.assertEqual(struct.unpack(">II", payload[:8]), (256, 256))
                if kind == b"IDAT":
                    raw += payload
                offset += length + 12
            pixels = zlib.decompress(raw)
            self.assertEqual(len(pixels), 256 * (1 + 256 * 4))
            self.assertEqual(pixels[:5], b"\0" * 5)

    def test_style_budgets_and_three_moves(self):
        for style in studio.ARCHETYPES:
            record = studio.creator_record("1", "相棒", "正", style, "url")
            self.assertEqual(sum(record[f"max_{key}"] for key in battle.STAT_KEYS), 360)
            self.assertEqual(len(record["moves"]), 3)
            self.assertEqual(record["current_level"], 5)

    def test_empty_box_capacity_prevents_upload(self):
        cog = studio.AppraisalCog(None)
        cog.get_user_profile = MagicMock(return_value={"max_box_slots": 20})
        cog.check_box_capacity = MagicMock(return_value=(False, 20))
        with patch.object(studio, "supabase") as database:
            with self.assertRaises(ValueError):
                cog.save_creation(SimpleNamespace(user_id="1"))
            database.storage.from_.assert_not_called()

    def test_creation_does_not_debit_or_use_ai(self):
        cog = studio.AppraisalCog(None)
        cog.get_user_profile = MagicMock(return_value={"max_box_slots": 20})
        cog.check_box_capacity = MagicMock(return_value=(True, 0))
        cog.deduct_coins_transaction = MagicMock(side_effect=AssertionError("not free"))
        cog.generate_ai_monster = AsyncMock(side_effect=AssertionError("AI called"))
        editor = SimpleNamespace(user_id="1", name="相棒", element="実", style="バランス", color="ミント",
                                 rows=studio.parse_pixels(studio.PIXEL_TEMPLATES["スライム"]))
        with patch.object(studio, "supabase") as database:
            database.storage.from_.return_value.get_public_url.return_value = "https://example.com/dot.png"
            database.table.return_value.insert.return_value.execute.return_value.data = [monster()]
            self.assertEqual(cog.save_creation(editor)["id"], "dot-1")
            cog.deduct_coins_transaction.assert_not_called()
            cog.generate_ai_monster.assert_not_called()

    def test_failed_registration_cleans_up_image(self):
        cog = studio.AppraisalCog(None)
        cog.get_user_profile = MagicMock(return_value={"max_box_slots": 20})
        cog.check_box_capacity = MagicMock(return_value=(True, 0))
        editor = SimpleNamespace(user_id="1", name="相棒", element="実", style="バランス", color="ミント",
                                 rows=studio.parse_pixels(studio.PIXEL_TEMPLATES["スライム"]))
        with patch.object(studio, "supabase") as database:
            database.table.return_value.insert.return_value.execute.side_effect = RuntimeError("offline")
            with self.assertRaises(RuntimeError):
                cog.save_creation(editor)
            database.storage.from_.return_value.remove.assert_called_once()


class EngineTests(unittest.TestCase):
    def test_level_clamps_and_existing_curve(self):
        self.assertEqual(battle.calc_stat(100, 30), 100)
        self.assertEqual(battle.calc_stat(100, 99), 144)
        self.assertEqual(battle.calc_stat(100, -1), battle.calc_stat(100, 1))
        self.assertGreaterEqual(battle.calc_stat(None, None), 1)

    def test_all_25_type_matchups(self):
        for attack in battle.TYPE_CHART:
            for defense in battle.TYPE_CHART:
                expected = battle.TYPE_CHART[attack].get(defense, 1)
                self.assertEqual(battle.get_type_multiplier(attack, defense), expected)

    def test_moves_normalize_missing_and_legacy_arrays(self):
        for source in (None, [], [None], [{"power": "bad", "accuracy": None}], [{}] * 7):
            moves = battle.normalize_moves(source)
            self.assertEqual(len(moves), 3)
            self.assertTrue(all(1 <= m["accuracy"] <= 100 for m in moves))

    def test_preparation_does_not_mutate_saved_monster(self):
        saved = monster()
        party = battle.prepare_party([saved])
        party[0]["moves"][0]["name"] = "changed"
        self.assertNotEqual(saved["moves"][0]["name"], "changed")
        self.assertNotIn("current_hp", saved)

    def test_stab_critical_and_guard_modifiers(self):
        s = state()
        actor, target = s["p1"]["party"][0], s["p2"]["party"][0]
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

    def test_status_has_no_damage(self):
        s = state()
        a, d = s["p1"]["party"][0], s["p2"]["party"][0]
        self.assertEqual(battle.calculate_damage(a, d, a["moves"][2])[0], 0)

    def test_accuracy_miss_boundary(self):
        s = state()
        before = s["p2"]["party"][0]["current_hp"]
        battle.resolve_action(s, "p1", "1", FixedRandom(0.8))
        self.assertEqual(s["p2"]["party"][0]["current_hp"], before)
        self.assertIn("外れた", s["logs"][-1])

    def test_heal_cap_and_three_charges(self):
        s = state()
        actor = s["p1"]["party"][0]
        actor["current_hp"] = 1
        maximum = battle.calc_stat(actor["max_hp"], actor["current_level"])
        for _ in range(5):
            battle.resolve_action(s, "p1", "2", FixedRandom())
        self.assertEqual(actor["heals"], 0)
        self.assertLessEqual(actor["current_hp"], maximum)
        self.assertIn("回数切れ", s["logs"][-1])

    def test_guard_and_switch_reset_ranks(self):
        s = state(3)
        actor = s["p1"]["party"][0]
        battle.resolve_action(s, "p1", "guard")
        self.assertTrue(actor["guarding"])
        actor["ranks"]["attack"] = 3
        battle.resolve_action(s, "p1", "switch:2")
        self.assertFalse(actor["guarding"])
        self.assertEqual(actor["ranks"], {})
        self.assertEqual(s["p1"]["active_idx"], 2)

    def test_invalid_action_never_mutates_state(self):
        for action in ("switch:0", "switch:4", "switch:-1", "9", "nope"):
            s = state()
            before = copy.deepcopy(s)
            with self.assertRaises(ValueError):
                battle.resolve_action(s, "p1", action)
            self.assertEqual(s, before)

    def test_poison_duration(self):
        s = state()
        actor = s["p1"]["party"][0]
        actor["moves"][2].update(effect="poison")
        battle.resolve_action(s, "p1", "2", FixedRandom())
        target = s["p2"]["party"][0]
        before = target["current_hp"]
        for _ in range(3):
            battle.resolve_action(s, "p2", "guard")
        self.assertEqual(target["poison"], 0)
        self.assertLess(target["current_hp"], before)

    def test_rank_caps_and_multiplier(self):
        s = state()
        actor = s["p1"]["party"][0]
        actor["moves"][2]["effect"] = "attack_up"
        for _ in range(9):
            battle.resolve_action(s, "p1", "2", FixedRandom())
        self.assertEqual(actor["ranks"]["attack"], 6)
        self.assertEqual(battle.rank_multiplier(100), 4)
        self.assertEqual(battle.rank_multiplier(-100), 0.25)

    def test_unknown_effect_is_safe(self):
        s = state()
        actor = s["p1"]["party"][0]
        actor["moves"][2]["effect"] = {"arbitrary": "text"}
        battle.resolve_action(s, "p1", "2", FixedRandom())
        self.assertIn("未対応", s["logs"][-1])

    def test_auto_switch_and_victory(self):
        s = state(3)
        s["p2"]["party"][0]["current_hp"] = 1
        self.assertIsNone(battle.resolve_action(s, "p1", "0", FixedRandom()))
        self.assertEqual(s["p2"]["active_idx"], 1)
        for target in s["p2"]["party"]:
            target["current_hp"] = 0
        s["p2"]["party"][1]["current_hp"] = 1
        self.assertEqual(battle.resolve_action(s, "p1", "0", FixedRandom()), "p1")

    def test_simultaneous_knockout_draw(self):
        s = state()
        actor, target = s["p1"]["party"][0], s["p2"]["party"][0]
        actor.update(current_hp=1, poison=1)
        target["current_hp"] = 1
        self.assertEqual(battle.resolve_action(s, "p1", "0", FixedRandom()), "draw")

    def test_surrender_and_turn_limit(self):
        self.assertEqual(battle.resolve_action(state(), "p1", "surrender"), "p2")
        s = state()
        s["version"] = 79
        self.assertEqual(battle.resolve_action(s, "p1", "guard"), "draw")

    def test_exp_carryover_and_cap(self):
        self.assertEqual(battle.add_experience(5, 80, 50), (6, 30))
        self.assertEqual(battle.add_experience(5, 80, 250), (8, 30))
        self.assertEqual(battle.add_experience(29, 80, 250), (30, 230))

    def test_all_loadout_effects_are_supported(self):
        for name, technique in system.TECHNIQUES.items():
            s = state()
            actor = s["p1"]["party"][0]
            actor["moves"][0] = {"name": name, "type": "無", "power": 0, "accuracy": 100, **technique}
            battle.resolve_action(s, "p1", "0", FixedRandom())
            self.assertFalse(any("未対応" in log for log in s["logs"]))


class DiscordUITests(unittest.IsolatedAsyncioTestCase):
    async def test_all_cogs_load_and_commands_serialize(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        async with bot:
            await studio.setup(bot)
            await battle.setup(bot)
            await system.setup(bot)
            names = {cmd.name for cmd in bot.tree.get_commands()}
            self.assertTrue({"ddd_create", "ddd_box", "ddd_loadout", "ddd_practice", "ddd_resume", "ddd_guide", "ddd_battle"} <= names)
            for command in bot.tree.get_commands():
                self.assertTrue(command.to_dict(bot.tree))

    async def test_studio_components_and_modal_fit_discord_limits(self):
        editor = studio.PixelStudio(None, "1", "相棒")
        self.assertEqual(len(editor.to_components()), 5)
        self.assertLessEqual(len(editor.embed()), 6000)
        self.assertEqual(len(studio.PixelModal(editor).to_dict()["components"]), 2)
        editor.stop()

    async def test_studio_ownership_saved_and_undo(self):
        editor = studio.PixelStudio(None, "1", "相棒")
        self.assertFalse(await editor.interaction_check(interaction(2)))
        editor.snapshot()
        editor.name = "changed"
        await editor.undo.callback(interaction())
        self.assertEqual(editor.name, "相棒")
        editor.saved = True
        self.assertFalse(await editor.interaction_check(interaction()))
        editor.stop()

    async def test_box_can_reach_more_than_25_monsters(self):
        view = system.MonsterSelectView("1", [monster(mid=str(i)) for i in range(51)])
        self.assertEqual(len(view.children[0].options), 25)
        await view.page_callback(1)(interaction())
        self.assertEqual(view.children[0].options[0].value, "25")
        await view.page_callback(1)(interaction())
        self.assertEqual(view.children[0].options[0].value, "50")
        self.assertEqual(len(view.children[0].options), 1)
        self.assertTrue(view.children[-1].disabled)
        self.assertFalse(await view.interaction_check(interaction(2)))
        view.stop()

    async def test_cards_and_action_rows_fit_discord(self):
        self.assertLessEqual(len(system.monster_embed(monster())), 6000)
        s = state(3)
        self.assertLessEqual(len(battle.battle_embed(s)), 6000)
        view = battle.BattleView(SimpleNamespace(busy=set()), "b", s, "1", "1", "2")
        self.assertEqual(len(view.children), 7)
        self.assertTrue(view.to_components())
        view.stop()

    async def test_wrong_player_and_stale_board_never_award(self):
        view = battle.BattleView(SimpleNamespace(busy=set()), "b", state(), "1", "1", "2")
        view.save_turn = MagicMock(return_value=[])
        view.award_exp = MagicMock()
        await view.execute_turn(interaction(2), "surrender")
        view.save_turn.assert_not_called()
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

    async def test_version_filter_is_required_for_save(self):
        view = battle.BattleView(SimpleNamespace(busy=set()), "b", state(), "1", "1", "2")
        query = MagicMock()
        query.eq.return_value = query
        with patch.object(battle, "supabase") as database:
            database.table.return_value.update.return_value = query
            view.save_turn(state(), "2", False)
        self.assertIn(unittest.mock.call("battle_state->>version", "0"), query.eq.call_args_list)
        self.assertIn(unittest.mock.call("is_finished", False), query.eq.call_args_list)
        view.stop()

    async def test_practice_does_not_write_or_clear_pvp_busy(self):
        cog = SimpleNamespace(busy={"1", "2"})
        view = battle.BattleView(cog, None, state(), "1", "1", "CPU", practice=True)
        view.save_turn = MagicMock(side_effect=AssertionError("practice wrote to DB"))
        view.award_exp = MagicMock(side_effect=AssertionError("practice awarded EXP"))
        await view.execute_turn(interaction(), "surrender")
        view.save_turn.assert_not_called()
        view.award_exp.assert_not_called()
        self.assertEqual(cog.busy, {"1", "2"})

    async def test_challenge_requires_opponent_and_decline_unlocks(self):
        cog = SimpleNamespace(busy={"1", "2"})
        view = battle.ChallengeView(cog, "1", "2")
        self.assertFalse(await view.interaction_check(interaction(1)))
        self.assertTrue(await view.interaction_check(interaction(2)))
        await view.decline.callback(interaction(2))
        self.assertEqual(cog.busy, set())

    async def test_release_confirmation_ownership(self):
        view = system.ReleaseConfirm("1", monster())
        self.assertFalse(await view.interaction_check(interaction(2)))
        await view.cancel.callback(interaction())
        self.assertFalse(await view.interaction_check(interaction()))


if __name__ == "__main__":
    unittest.main()
