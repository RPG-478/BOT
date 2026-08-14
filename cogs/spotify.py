import discord
from discord.ext import commands

class SpotifyTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_user_id = 1320705325686587408
        self.target_channel_id = 1407389497016193177
        self.last_track_id = {}

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.id != self.target_user_id:
            return

        before_spotify = discord.utils.get(before.activities, type=discord.ActivityType.listening)
        after_spotify = discord.utils.get(after.activities, type=discord.ActivityType.listening)

        if isinstance(before_spotify, discord.Spotify):
            before_id = before_spotify.track_id
        else:
            before_id = None

        if isinstance(after_spotify, discord.Spotify):
            after_id = after_spotify.track_id
        else:
            after_id = None

        if not after_id:
            return

        if before_id == after_id:
            return

        if self.last_track_id.get(after.id) == after_id:
            return

        self.last_track_id[after.id] = after_id

        channel = self.bot.get_channel(self.target_channel_id)
        if not channel:
            return

        message_text = f"再生曲変更: {after_spotify.title} - {after_spotify.artist}\n{after_spotify.track_url}"

        try:
            await channel.send(message_text)
        except discord.HTTPException as e:
            if e.status == 429:
                pass

async def setup(bot):
    await bot.add_cog(SpotifyTracker(bot))
