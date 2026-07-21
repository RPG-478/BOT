import json
import io
import discord
from discord import app_commands
from discord.ext import commands

class ServerCopyPaste(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="copy", description="サーバーの設定をJSONファイルに書き出します")
    @app_commands.checks.has_permissions(administrator=True)
    async def copy_server(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        data = {
            "settings": {
                "verification_level": guild.verification_level.value,
                "default_notifications": guild.default_notifications.value,
                "explicit_content_filter": guild.explicit_content_filter.value,
                "afk_timeout": guild.afk_timeout
            },
            "roles": [],
            "categories": []
        }

        roles = [role for role in reversed(guild.roles) if not role.is_default() and not role.managed]
        for role in roles:
            data["roles"].append({
                "id": role.id,
                "name": role.name,
                "permissions": role.permissions.value,
                "color": role.color.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable
            })

        for category in guild.categories:
            cat_overwrites = []
            for target, overwrite in category.overwrites.items():
                if isinstance(target, discord.Role):
                    pair = overwrite.pair()
                    cat_overwrites.append({
                        "role_id": target.id,
                        "allow": pair[0].value,
                        "deny": pair[1].value
                    })

            cat_data = {
                "name": category.name,
                "overwrites": cat_overwrites,
                "channels": []
            }

            for channel in category.channels:
                ch_overwrites = []
                for target, overwrite in channel.overwrites.items():
                    if isinstance(target, discord.Role):
                        pair = overwrite.pair()
                        ch_overwrites.append({
                            "role_id": target.id,
                            "allow": pair[0].value,
                            "deny": pair[1].value
                        })

                ch_info = {
                    "type": str(channel.type),
                    "name": channel.name,
                    "overwrites": ch_overwrites
                }

                if isinstance(channel, discord.TextChannel):
                    ch_info["topic"] = channel.topic
                    ch_info["nsfw"] = channel.nsfw
                    ch_info["slowmode_delay"] = channel.slowmode_delay
                elif isinstance(channel, discord.VoiceChannel):
                    ch_info["bitrate"] = channel.bitrate
                    ch_info["user_limit"] = channel.user_limit

                cat_data["channels"].append(ch_info)

            data["categories"].append(cat_data)

        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file = discord.File(io.BytesIO(json_bytes), filename="server_data.json")
        await interaction.followup.send("サーバー設定の抽出が完了しました。", file=file, ephemeral=True)

    @app_commands.command(name="paste", description="JSONファイルからサーバー設定を構築します")
    @app_commands.checks.has_permissions(administrator=True)
    async def paste_server(self, interaction: discord.Interaction, file: discord.Attachment):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if not file.filename.endswith(".json"):
            await interaction.followup.send("JSONファイルを添付してください。", ephemeral=True)
            return

        content = await file.read()
        data = json.loads(content.decode("utf-8"))

        settings = data.get("settings", {})
        try:
            await guild.edit(
                verification_level=discord.VerificationLevel(settings.get("verification_level", guild.verification_level.value)),
                default_notifications=discord.NotificationLevel(settings.get("default_notifications", guild.default_notifications.value)),
                explicit_content_filter=discord.ContentFilter(settings.get("explicit_content_filter", guild.explicit_content_filter.value)),
                afk_timeout=settings.get("afk_timeout", guild.afk_timeout)
            )
        except discord.HTTPException:
            pass

        role_map = {}
        role_map[guild.default_role.id] = guild.default_role

        for r_data in data.get("roles", []):
            try:
                new_role = await guild.create_role(
                    name=r_data["name"],
                    permissions=discord.Permissions(r_data["permissions"]),
                    color=discord.Color(r_data["color"]),
                    hoist=r_data["hoist"],
                    mentionable=r_data["mentionable"]
                )
                role_map[r_data["id"]] = new_role
            except discord.HTTPException:
                continue

        for cat_data in data.get("categories", []):
            cat_overwrites = {}
            for ow in cat_data.get("overwrites", []):
                old_role_id = ow["role_id"]
                if old_role_id in role_map:
                    target_role = role_map[old_role_id]
                    cat_overwrites[target_role] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(ow["allow"]),
                        discord.Permissions(ow["deny"])
                    )

            try:
                category = await guild.create_category(
                    name=cat_data["name"],
                    overwrites=cat_overwrites
                )
            except discord.HTTPException:
                continue

            for ch_data in cat_data.get("channels", []):
                ch_overwrites = {}
                for ow in ch_data.get("overwrites", []):
                    old_role_id = ow["role_id"]
                    if old_role_id in role_map:
                        target_role = role_map[old_role_id]
                        ch_overwrites[target_role] = discord.PermissionOverwrite.from_pair(
                            discord.Permissions(ow["allow"]),
                            discord.Permissions(ow["deny"])
                        )

                try:
                    if ch_data["type"] == "text":
                        await guild.create_text_channel(
                            name=ch_data["name"],
                            category=category,
                            topic=ch_data.get("topic"),
                            nsfw=ch_data.get("nsfw", False),
                            slowmode_delay=ch_data.get("slowmode_delay", 0),
                            overwrites=ch_overwrites
                        )
                    elif ch_data["type"] == "voice":
                        await guild.create_voice_channel(
                            name=ch_data["name"],
                            category=category,
                            bitrate=ch_data.get("bitrate", 64000),
                            user_limit=ch_data.get("user_limit", 0),
                            overwrites=ch_overwrites
                        )
                except discord.HTTPException:
                    continue

        await interaction.followup.send("サーバー設定の構築が完了しました。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCopyPaste(bot))
