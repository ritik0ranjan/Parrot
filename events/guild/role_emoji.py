from __future__ import annotations
from contextlib import suppress
from typing import Sequence

from core import Cog, Parrot
import discord
import io
import json


class GuildRoleEmoji(Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot: Parrot):
        self.bot = bot
        self.collection = bot.mongo.parrot_db["logging"]

    def permissions_to_json(self, permissions: discord.Permissions) -> str:
        return json.dumps(dict(permissions), indent=4) if permissions else "{}"

    @Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self.bot.wait_until_ready()
        if not role.guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": role.guild.id, "on_role_create": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_role_create"], session=self.bot.http_session
            )
            with suppress(discord.HTTPException):
                async for entry in role.guild.audit_logs(
                    action=discord.AuditLogAction.role_create, limit=5
                ):
                    if entry.target.id == role.id:
                        content = f"""**Role Create**

`Name (ID)  :` **{role.name} [`{role.id}`]**
`Created At :` **{discord.utils.format_dt(role.created_at)}**
`Position   :` **{role.position}**
`Colour     :` **{role.color.to_rgb()} (RGB)**
`Mentionable:` **{role.mentionable}**
`Hoisted    :` **{role.hoist}**
`Bot Managed:` **{role.is_bot_managed()}**
`Integrated :` **{role.is_integration()}**
"""
                        fp = io.ByteIO(
                            self.permissions_to_json(role.permissions).encode()
                        )
                        await webhook.send(
                            content=content,
                            avatar_url=self.bot.user.avatar.url,
                            username=self.bot.user.name,
                            file=discord.File(fp, filename="permissions.json"),
                        )
                        break

    @Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self.bot.wait_until_ready()
        if not role.guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": role.guild.id, "on_role_delete": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_role_delete"], session=self.bot.http_session
            )
            with suppress(discord.HTTPException):
                async for entry in role.guild.audit_logs(
                    action=discord.AuditLogAction.role_create, limit=5
                ):
                    if entry.target.id == role.id:
                        content = f"""**Role Create**

`Name (ID)  :` **{role.name} [`{role.id}`]**
`Created At :` **{discord.utils.format_dt(role.created_at)}**
`Position   :` **{role.position}**
`Colour     :` **{role.color.to_rgb()} (RGB)**
`Mentionable:` **{role.mentionable}**
`Hoisted    :` **{role.hoist}**
`Bot Managed:` **{role.is_bot_managed()}**
`Integrated :` **{role.is_integration()}**
"""
                        fp = io.ByteIO(
                            self.permissions_to_json(role.permissions).encode()
                        )
                        await webhook.send(
                            content=content,
                            avatar_url=self.bot.user.avatar.url,
                            username=self.bot.user.name,
                            file=discord.File(fp, filename="permissions.json"),
                        )
                        break

        await self.bot.mongo.parrot_db["server_config"].update_one(
            {"_id": role.guild.id}, {"$set": {"mod_role": None}}, upsert=True
        )

        await self.bot.mongo.parrot_db["global_chat"].update_one(
            {"_id": role.guild.id}, {"$set": {"ignore_role": None}}, upsert=True
        )

        await self.bot.mongo.parrot_db["telephone"].update_one(
            {"_id": role.guild.id}, {"$set": {"pingrole": None}}, upsert=True
        )

        await self.bot.mongo.parrot_db["ticket"].update_one(
            {"_id": role.guild.id},
            {
                "$pull": {
                    "valid_roles": role.id,
                    "pinged_roles": role.id,
                    "verified_roles": role.id,
                }
            },
        )

    def _update_role(
        self,
        before,
        after,
    ):
        ls = []
        if before.name != after.name:
            ls.append(("`Name Changed      :`", after.name))
        if before.position != after.position:
            ls.append(("`Position Changed  :`", after.position))
        if before.hoist is not after.hoist:
            ls.append(("`Hoist Toggled     :`", after.hoist))
        if before.color != after.color:
            ls.append(("`Color Changed     :`", after.color.to_rgb()))
        return ls

    @Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        await self.bot.wait_until_ready()
        if not after.guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": before.guild.id, "on_role_update": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_role_update"], session=self.bot.http_session
            )
            with suppress(discord.HTTPException):
                async for entry in after.guild.audit_logs(
                    action=discord.AuditLogAction.role_update, limit=5
                ):
                    if entry.target.id == after.id:
                        reason = entry.reason or None
                        user = entry.user or "UNKNOWN#0000"
                        entryID = entry.id
                        ls = self._update_role(before, after)
                        ext = ""
                        for i, j in ls:
                            ext += f"{i} **{j}**\n"
                        content = f"""**Role Update Event**

`Name (ID) :` **{after.name} ({after.id})**
`Created at:` **{discord.utils.format_dt(after.created_at)}**
`Reason    :` **{reason if reason else 'No reason provided'}**
`Entry ID  :` **{entryID if entryID else None}**
`Updated by:` **{user}**

**Change/Update**
{ext}
"""
                        fp = io.BytesIO(
                            self.permissions_to_json(after.permissions).encode()
                        )
                        await webhook.send(
                            content=content,
                            avatar_url=self.bot.user.avatar.url,
                            username=self.bot.user.name,
                            file=discord.File(fp, filename="permissions.json"),
                        )
                        break

    @Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: Sequence[discord.Emoji],
        after: Sequence[discord.Emoji],
    ):
        await self.bot.wait_until_ready()
        if not guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": guild.id, "on_emoji_create": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_emoji_create"], session=self.bot.http_session
            )
            with suppress(discord.HTTPException):
                async for entry in guild.audit_logs(
                    action=discord.AuditLogAction.emoji_create, limit=1
                ):
                    emoji_name = entry.name
                    if isinstance(entry.target, discord.Emoji):
                        animated = entry.target.animated
                        _id = entry.target.id
                        url = entry.target.url
                    else:
                        animated = None
                        _id = entry.target.id
                        url = None
                content = f"""**On Emoji Create**

`Name    `: **{emoji_name}**
`Raw     `: **`{entry.target if isinstance(entry.target, discord.Emoji) else None}`**
`ID      `: **{_id}**
`URL     `: **<{url}>**
`Animated`: **{animated}**
"""
                await webhook.send(
                    content=content,
                    avatar_url=self.bot.user.avatar.url,
                    username=self.bot.user.name,
                )

        if data := await self.collection.find_one(
            {"_id": guild.id, "on_emoji_delete": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_emoji_delete"], session=self.bot.http_session
            )
            with suppress(discord.HTTPException):
                async for entry in guild.audit_logs(
                    action=discord.AuditLogAction.emoji_delete, limit=1
                ):
                    emoji_name = entry.name
                    if isinstance(entry.target, discord.Emoji):
                        animated = entry.target.animated
                        _id = entry.target.id
                        url = entry.target.url
                    else:
                        animated = None
                        _id = entry.target.id
                        url = None
                content = f"""**On Emoji Create**

`Raw     `: **`{entry.target if isinstance(entry.target, discord.Emoji) else None}`**
`ID      `: **{_id}**
`URL     `: **<{url}>**
"""
            await webhook.send(
                content=content,
                avatar_url=self.bot.user.avatar.url,
                username=self.bot.user.name,
            )

        if data := await self.collection.find_one(
            {"_id": guild.id, "on_emoji_update": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_emoji_update"], session=self.bot.http_session
            )
            with suppress(discord.HTTPException):
                async for entry in guild.audit_logs(
                    action=discord.AuditLogAction.emoji_update, limit=1
                ):
                    emoji_name = entry.name
                    if isinstance(entry.target, discord.Emoji):
                        animated = entry.target.animated
                        _id = entry.target.id
                        url = entry.target.url
                    else:
                        animated = None
                        _id = entry.target.id
                        url = None
                content = f"""**On Emoji Create**

`Raw     `: **`{entry.target if isinstance(entry.target, discord.Emoji) else None}`**
`ID      `: **{_id}**
`URL     `: **<{url}>**
"""
            await webhook.send(
                content=content,
                avatar_url=self.bot.user.avatar.url,
                username=self.bot.user.name,
            )


async def setup(bot: Parrot) -> None:
    await bot.add_cog(GuildRoleEmoji(bot))
