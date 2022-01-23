from __future__ import annotations

from core import Parrot, Cog

import discord
from discord.ext import commands
from discord import utils


class OnThread(Cog):
    def __init__(self, bot: Parrot):
        self.bot = bot

    @Cog.listener()
    async def on_thread_join(self, thread: discord.Thread):
        if not thread.guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": thread.guild.id, "on_thread_create": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_thread_create"], session=self.bot.session
            )
            if webhook:
                async for entry in thread.guild.audit_logs(
                    action=discord.AuditLogAction.thread_create, limit=5
                ):
                    if entry.target.id == thread.id:
                        reason = entry.reason
                        user = entry.user or "UNKNOWN#0000"
                        entryID = entry.id

                        content = f"""**On Thread Create**

`Name      :` **{thread.name}** **(`{thread.id}`)**
`Created by:` **{user}**
`Created at:` **{utils.format_dt(utils.snowflake_time(thread.id))}**
`Reason    :` **{reason}**
`Entry ID  :` **{entryID}**
`Parent    :` **<#{thread.parent_id}>**
`Owner     :` **{thread.owner}** **(`{thread.owner_id}`)**
"""
                        await webhook.send(
                            content=content,
                            avatar_url=self.bot.user.avatar.url,
                            username=self.bot.user.name,
                        )
                        break

    @Cog.listener()
    async def on_thread_remove(self, thread: discord.Thread):
        if not thread.guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": thread.guild.id, "on_thread_remove": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_thread_remove"], session=self.bot.session
            )
            if webhook:
                content = f"""**On Thread Remove**

`Name      :` **{thread.name}** **(`{thread.id}`)**
`Created at:` **{utils.format_dt(utils.snowflake_time(thread.id))}**
`Parent    :` **<#{thread.parent_id}>**
`Owner     :` **{thread.owner}** **(`{thread.owner_id}`)**
"""
                await webhook.send(
                    content=content,
                    avatar_url=self.bot.user.avatar.url,
                    username=self.bot.user.name,
                )

    @Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        if not thread.guild.me.guild_permissions.view_audit_log:
            return
        if data := await self.collection.find_one(
            {"_id": thread.guild.id, "on_thread_delete": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_thread_delete"], session=self.bot.session
            )
            if webhook:
                async for entry in thread.guild.audit_logs(
                    action=discord.AuditLogAction.thread_delete, limit=5
                ):
                    if entry.target.id == thread.id:
                        reason = entry.reason
                        entryID = entry.id

                        content = f"""**On Thread Create**

`Name      :` **{thread.name}** **(`{thread.id}`)**
`Created at:` **{utils.format_dt(utils.snowflake_time(thread.id))}**
`Reason    :` **{reason}**
`Entry ID  :` **{entryID}**
`Parent    :` **<#{thread.parent_id}>**
`Owner     :` **{thread.owner}** **(`{thread.owner_id}`)**
"""
                        await webhook.send(
                            content=content,
                            avatar_url=self.bot.user.avatar.url,
                            username=self.bot.user.name,
                        )
                        break

    @Cog.listener()
    async def on_thread_member_join(self, member: discord.ThreadMember):
        if data := await self.collection.find_one(
            {"_id": member.thread.guild.id, "on_member_join_thread": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_member_join_thread"], session=self.bot.session
            )
            if webhook:
                content = f"""**On Member Thread Join**

`Member    :` **{member.thred.guild.get_member(member.id)}** **(`{member.id}`)**
`Name      :` **{member.thread.name}** **(`{member.thread.id}`)**
`Created at:` **{utils.format_dt(utils.snowflake_time(member.thread.id))}**
`Joined at :` **{utils.format_dt(member.joined_at)}**
`Parent    :` **<#{member.thread.parent_id}>**
`Owner     :` **{member.thread.owner}** **(`{member.thread.owner_id}`)**
"""
                await webhook.send(
                    content=content,
                    avatar_url=self.bot.user.avatar.url,
                    username=self.bot.user.name,
                )

    @Cog.listener()
    async def on_thread_member_remove(self, member: discord.ThreadMember):
        if data := await self.collection.find_one(
            {"_id": member.thread.guild.id, "on_member_leave_thread": {"$exists": True}}
        ):
            webhook = discord.Webhook.from_url(
                data["on_member_leave_thread"], session=self.bot.session
            )
            if webhook:
                content = f"""**On Member Thread Leave**

`Member    :` **{member.thred.guild.get_member(member.id)}** **(`{member.id}`)**
`Name      :` **{member.thread.name}** **(`{member.thread.id}`)**
`Created at:` **{utils.format_dt(utils.snowflake_time(member.thread.id))}**
`Joined at :` **{utils.format_dt(member.joined_at)}**
`Parent    :` **<#{member.thread.parent_id}>**
`Owner     :` **{member.thread.owner}** **(`{member.thread.owner_id}`)**
"""
                await webhook.send(
                    content=content,
                    avatar_url=self.bot.user.avatar.url,
                    username=self.bot.user.name,
                )


def setup(bot: Parrot):
    bot.add_cog(OnThread(bot))
