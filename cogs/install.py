import sys
import subprocess
from pathlib import Path

REQUIRED_PACKAGES = [
    "psutil>=5.9.0"
]

def check_and_install_packages():
    print("=== 1. 依存ライブラリの確認とインストール ===")
    for pkg in REQUIRED_PACKAGES:
        pkg_name = pkg.split(">=")[0]
        try:
            __import__(pkg_name)
            print(f"  [OK] {pkg_name} は既にインストールされています。")
        except ImportError:
            print(f"  [+] {pkg_name} が見つかりません。インストール中...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
                print(f"  [OK] {pkg_name} のインストールに成功しました。")
            except subprocess.CalledProcessError as e:
                print(f"  [Error] {pkg_name} のインストールに失敗しました: {e}")
                sys.exit(1)

def setup_cogs_directory():
    print("\n=== 2. cogs ディレクトリ構造のセットアップ ===")
    cogs_dir = Path("cogs")
    if not cogs_dir.exists():
        cogs_dir.mkdir(parents=True, exist_ok=True)
        print("  [+] 'cogs' ディレクトリを作成しました。")
    else:
        print("  [OK] 'cogs' ディレクトリは既に存在します。")

    target_file = cogs_dir / "system_stats.py"
    
    cog_code = """import datetime
import os
import platform
import subprocess
from pathlib import Path
import discord
from discord.ext import commands
import psutil

class SystemStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = datetime.datetime.now(datetime.timezone.utc)

    def _get_git_info(self) -> str:
        try:
            commit_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
            commit_msg = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%s"], stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
            return f"`{commit_hash}`: {commit_msg}"
        except Exception:
            return "Git情報が取得できませんでした"

    def _get_py_file_tree(self, root_dir: Path = Path("."), ignore_dirs: set = None) -> str:
        if ignore_dirs is None:
            ignore_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "env"}

        tree_lines = []

        def build_tree(dir_path: Path, prefix: str = ""):
            entries = [
                e for e in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                if e.name not in ignore_dirs and not e.name.startswith(".")
            ]

            filtered_entries = []
            for entry in entries:
                if entry.is_dir():
                    if any(entry.rglob("*.py")):
                        filtered_entries.append(entry)
                elif entry.suffix == ".py":
                    filtered_entries.append(entry)

            count = len(filtered_entries)
            for idx, entry in enumerate(filtered_entries):
                is_last = (idx == count - 1)
                connector = "└── " if is_last else "├── "

                if entry.is_dir():
                    tree_lines.append(f"{prefix}{connector}{entry.name}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    build_tree(entry, new_prefix)
                else:
                    tree_lines.append(f"{prefix}{connector}{entry.name}")

        build_tree(root_dir)
        tree_text = "\\n".join(tree_lines)
        
        if len(tree_text) > 950:
            tree_text = tree_text[:900] + "\\n... (省略されました)"

        return f"```\\n{tree_text}\\n```" if tree_text else "`.py` ファイルが見つかりません"

    @commands.command(name="all_stats", aliases=["stats", "spec"])
    async def all_stats(self, ctx: commands.Context):
        async with ctx.typing():
            now = datetime.datetime.now(datetime.timezone.utc)
            uptime = now - self.start_time
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            days, hours = divmod(hours, 24)
            uptime_str = f"{days}日 {hours}時間 {minutes}分 {seconds}秒"

            ping = round(self.bot.latency * 1000)

            cpu_usage = psutil.cpu_percent(interval=0.5)
            cpu_count = psutil.cpu_count(logical=True)
            mem = psutil.virtual_memory()
            mem_total_gb = round(mem.total / (1024 ** 3), 2)
            mem_used_gb = round(mem.used / (1024 ** 3), 2)

            disk = psutil.disk_usage("/")
            disk_total_gb = round(disk.total / (1024 ** 3), 2)
            disk_free_gb = round(disk.free / (1024 ** 3), 2)

            process = psutil.Process(os.getpid())
            bot_mem_mb = round(process.memory_info().rss / (1024 ** 2), 2)
            bot_cpu_usage = process.cpu_percent(interval=None)

            guild_count = len(self.bot.guilds)
            user_count = sum(g.member_count or 0 for g in self.bot.guilds)
            loaded_cogs = ", ".join(f"`{cog}`" for cog in self.bot.cogs.keys()) or "なし"

            embed = discord.Embed(
                title="システム＆Bot総合ステータス",
                color=discord.Color.blue(),
                timestamp=now
            )

            embed.add_field(
                name="Bot状態",
                value=(
                    f"**Ping:** `{ping} ms`\\n"
                    f"**稼働時間:** `{uptime_str}`\\n"
                    f"**Python:** `v{platform.python_version()}` | **discord.py:** `v{discord.__version__}`"
                ),
                inline=False
            )

            embed.add_field(
                name="サーバースペック (全体)",
                value=(
                    f"**OS:** `{platform.system()} {platform.release()}`\\n"
                    f"**CPU使用率:** `{cpu_usage}%` ({cpu_count} Cores)\\n"
                    f"**RAM:** `{mem_used_gb} GB / {mem_total_gb} GB` ({mem.percent}%)\\n"
                    f"**Disk:** `{disk_free_gb} GB 空き / {disk_total_gb} GB` ({disk.percent}%)"
                ),
                inline=True
            )

            embed.add_field(
                name="Botプロセス (単体)",
                value=(
                    f"**メモリ使用量:** `{bot_mem_mb} MB`\\n"
                    f"**CPU使用率:** `{bot_cpu_usage}%`"
                ),
                inline=True
            )

            embed.add_field(
                name="Discord接続規模",
                value=(
                    f"**参加サーバー数:** `{guild_count}`\\n"
                    f"**アクセスユーザー数:** `{user_count}`\\n"
                    f"**読み込み済Cog:** {loaded_cogs}"
                ),
                inline=False
            )

            embed.add_field(
                name="最新Gitコミット",
                value=self._get_git_info(),
                inline=False
            )

            embed.add_field(
                name="プロジェクト .py ファイル構成",
                value=self._get_py_file_tree(),
                inline=False
            )

            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

            await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(SystemStatsCog(bot))
"""

    if not target_file.exists():
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(cog_code.strip())
        print(f"  [+] '{target_file}' を自動生成しました。")
    else:
        print(f"  [INFO] '{target_file}' は既に存在するため上書きしませんでした。")

if __name__ == "__main__":
    print("=== Discord Bot ステータスCog インストーラー ===\n")
    check_and_install_packages()
    setup_cogs_directory()
    print("\nセットアップが完了しました。")
