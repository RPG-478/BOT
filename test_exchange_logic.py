"""DDD育成の軽量回帰テスト。"""
from unittest.mock import patch

with patch("supabase.create_client"):
    from cogs.ddd_battle import add_experience
    from cogs.ddd_system import required_breakthrough

assert required_breakthrough(30, 0) == (30, 1)
assert required_breakthrough(40, 30) == (40, 10)
assert required_breakthrough(30, 30) is None
assert add_experience(30, 0, 1000, 0) == (30, 1000)
assert add_experience(30, 0, 1000, 30) == (31, 0)
assert add_experience(40, 0, 10_000, 30) == (40, 10_000)
assert add_experience(40, 0, 10_000, 40) == (41, 0)
print("DDD progression logic: OK")
