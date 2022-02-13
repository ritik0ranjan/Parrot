from __future__ import annotations
from cogs.meta.robopage import SimplePages

from core import Parrot, Cog, Context
from discord.ext import commands, tasks
import discord

import typing
import datetime
import asyncio

from utilities.database import parrot_db, todo
from utilities.time import ShortTime
from utilities.paginator import PaginationView
from utilities.converters import convert_bool

from cogs.utils import method as mt
from cogs.utils.method import giveaway

afk = parrot_db["afk"]


class afkFlags(commands.FlagConverter, prefix="--", delimiter=" "):
    ignore_channel: typing.Tuple[discord.TextChannel, ...] = []
    _global: typing.Optional[convert_bool] = commands.flag(name="global", default=False)
    _for: typing.Optional[ShortTime] = commands.flag(name="for", default=None)
    text: typing.Optional[str] = None
    after: typing.Optional[ShortTime] = None


class Utils(Cog):
    """Utilities for server, UwU"""

    def __init__(self, bot: Parrot):
        self.bot = bot
        self.react_collection = parrot_db["reactions"]
        self.reminder_task.start()
        self.collection = parrot_db["timers"]
        self.lock = asyncio.Lock()

    @property
    def display_emoji(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name="sparkles_", id=892435276264259665)

    async def create_timer(
        self,
        *,
        expires_at: float = None,
        created_at: float = None,
        content: str = None,
        message: discord.Message = None,
        dm_notify: bool = False,
        is_todo: bool = False,
        **kw,
    ):
        """|coro|

        Master Function to register Timers.

        Parameters
        ----------
        expires_at: :class:`float`
            Timer exprire timestamp
        created_at: :class:`float`
            Timer created timestamp
        content: :class:`str`
            Content of the Timer
        message: :class:`discord.Message`
            Message Object
        dm_notify: :class:`bool`
            To notify the user or not
        is_todo: :class:`bool`
            To provide whether the timer related to `TODO`
        """
        embed: dict = kw.get("embed_like") or kw.get("embed")
        mod_action: dict = kw.get("mod_action")
        cmd_exec_str: str = kw.get("cmd_exec_str")

        post = {
            "_id": message.id,
            "expires_at": expires_at,
            "created_at": created_at,
            "content": content,
            "embed": embed,
            "messageURL": message.jump_url,
            "messageAuthor": message.author.id,
            "messageChannel": message.channel.id,
            "dm_notify": dm_notify,
            "is_todo": is_todo,
            "mod_action": mod_action,
            "cmd_exec_str": cmd_exec_str,
            "extra": kw.get("extra"),
            **kw,
        }
        await self.collection.insert_one(post)

    async def delete_timer(self, **kw):
        collection = self.collection
        await collection.delete_one(kw)

    @commands.group(aliases=["remind"], invoke_without_command=True)
    @Context.with_type
    async def remindme(
        self, ctx: Context, age: ShortTime, *, task: commands.clean_content = None
    ):
        """To make reminders as to get your tasks done on time"""
        if not ctx.invoked_subcommand:
            seconds = age.dt.timestamp()
            text = (
                f"{ctx.author.mention} alright, you will be mentioned in {ctx.channel.mention} at **<t:{int(seconds)}>**."
                f"To delete your reminder consider typing ```\n{ctx.clean_prefix}remind delete {ctx.message.id}```"
            )
            try:
                await ctx.reply(f"{ctx.author.mention} check your DM", delete_after=5)
                await ctx.author.send(text)
            except discord.Fobidden:
                await ctx.reply(text)
            await self.create_timer(
                expires_at=seconds,
                created_at=ctx.message.created_at.timestamp(),
                content=task,
                message=ctx.message,
            )

    @remindme.command(name="list")
    @Context.with_type
    async def _list(self, ctx: Context):
        """To get all your reminders"""
        ls = []
        async for data in self.collection.find({"messageAuthor": ctx.author.id}):
            ls.append(
                f"<t:{int(data['expires_at'])}:R>\n> [{data['content']}]({data['messageURL']})"
            )
        if not ls:
            return await ctx.send(f"{ctx.author.mention} you don't have any reminders")
        p = SimplePages(ls, ctx=ctx, per_page=4)
        await p.start()

    @remindme.command(name="del", aliases=["delete"])
    @Context.with_type
    async def delremind(self, ctx: Context, message: int):
        """To delete the reminder"""
        await self.delete_timer(_id=message)
        await ctx.reply(f"{ctx.author.mention} deleted reminder of ID: **{message}**")

    @remindme.command(name="dm")
    @Context.with_type
    async def remindmedm(
        self, ctx: Context, age: ShortTime, *, task: commands.clean_content = None
    ):
        """Same as remindme, but you will be mentioned in DM. Make sure you have DM open for the bot"""
        seconds = age.dt.timestamp()
        text = (
            f"{ctx.author.mention} alright, you will be mentioned in your DM (Make sure you have your DM open for this bot) "
            f"within **<t:{int(seconds)}>**. To delete your reminder consider typing ```\n{ctx.clean_prefix}remind delete {ctx.message.id}```"
        )
        try:
            await ctx.reply(f"{ctx.author.mention} check your DM", delete_after=5)
            await ctx.author.send(text)
        except discord.Fobidden:
            await ctx.reply(text)
        await self.create_timer(
            expires_at=seconds,
            created_at=ctx.message.created_at.timestamp(),
            content=task,
            message=ctx.message,
            dm_notify=True,
        )

    @commands.group(invoke_without_command=True)
    @commands.bot_has_permissions(embed_links=True)
    async def tag(self, ctx: Context, *, tag: str = None):
        """Tag management, or to show the tag"""
        if not ctx.invoked_subcommand and tag is not None:
            await mt._show_tag(
                self.bot,
                ctx,
                tag,
                ctx.message.reference.resolved if ctx.message.reference else None,
            )

    @tag.command(name="create", aliases=["add"])
    @commands.bot_has_permissions(embed_links=True)
    async def tag_create(self, ctx: Context, tag: str, *, text: str):
        """To create tag. All tag have unique name"""
        await mt._create_tag(self.bot, ctx, tag, text)

    @tag.command(name="delete", aliases=["del"])
    @commands.bot_has_permissions(embed_links=True)
    async def tag_delete(self, ctx: Context, *, tag: str):
        """To delete tag. You must own the tag to delete"""
        await mt._delete_tag(self.bot, ctx, tag)

    @tag.command(name="editname")
    @commands.bot_has_permissions(embed_links=True)
    async def tag_edit_name(self, ctx: Context, tag: str, *, name: str):
        """To edit the tag name. You must own the tag to edit"""
        await mt._name_edit(self.bot, ctx, tag, name)

    @tag.command(name="edittext")
    @commands.bot_has_permissions(embed_links=True)
    async def tag_edit_text(self, ctx: Context, tag: str, *, text: str):
        """To edit the tag text. You must own the tag to edit"""
        await mt._text_edit(self.bot, ctx, tag, text)

    @tag.command(name="owner", aliases=["info"])
    @commands.bot_has_permissions(embed_links=True)
    async def tag_owner(self, ctx: Context, *, tag: str):
        """To check the tag details."""
        await mt._view_tag(self.bot, ctx, tag)

    @tag.command(name="snipe", aliases=["steal", "claim"])
    @commands.bot_has_permissions(embed_links=True)
    async def tag_claim(self, ctx: Context, *, tag: str):
        """To claim the ownership of the tag, if the owner of the tag left the server"""
        await mt._claim_owner(self.bot, ctx, tag)

    @tag.command(name="togglensfw", aliases=["nsfw", "tnsfw"])
    @commands.bot_has_permissions(embed_links=True)
    async def toggle_nsfw(self, ctx: Context, *, tag: str):
        """To enable/disable the NSFW of a Tag."""
        await mt._toggle_nsfw(self.bot, ctx, tag)

    @tag.command(name="give", aliases=["transfer"])
    @commands.bot_has_permissions(embed_links=True)
    async def tag_tranfer(self, ctx: Context, tag: str, *, member: discord.Member):
        """To transfer the ownership of tag you own to other member"""
        await mt._transfer_owner(self.bot, ctx, tag, member)

    @tag.command(name="all")
    @commands.bot_has_permissions(embed_links=True)
    async def tag_all(self, ctx: Context):
        """To show all tags"""
        await mt._show_all_tags(self.bot, ctx)

    @tag.command(name="mine")
    @commands.bot_has_permissions(embed_links=True)
    async def tag_mine(self, ctx: Context):
        """To show those tag which you own"""
        await mt._show_tag_mine(self.bot, ctx)

    @commands.command()
    @commands.has_permissions(manage_messages=True, add_reactions=True)
    @commands.bot_has_permissions(
        embed_links=True, add_reactions=True, read_message_history=True
    )
    @Context.with_type
    async def quickpoll(self, ctx: Context, *questions_and_choices: str):
        """
        To make a quick poll for making quick decision. 'Question must be in quotes' and Options, must, be, seperated, by, commans.
        Not more than 10 options. :)
        """

        def to_emoji(c):
            base = 0x1F1E6
            return chr(base + c)

        if len(questions_and_choices) < 3:
            return await ctx.send("Need at least 1 question with 2 choices.")
        if len(questions_and_choices) > 21:
            return await ctx.send("You can only have up to 20 choices.")

        question = questions_and_choices[0]
        choices = [(to_emoji(e), v) for e, v in enumerate(questions_and_choices[1:])]

        await ctx.message.delete(delay=0)

        body = "\n".join(f"{key}: {c}" for key, c in choices)
        poll = await ctx.send(f"**Poll: {question}**\n\n{body}")
        for emoji, _ in choices:
            await poll.add_reaction(emoji)

    @commands.group(name="todo", invoke_without_command=True)
    @commands.bot_has_permissions(embed_links=True)
    async def todo(self, ctx: Context):
        """For making the TODO list"""
        if not ctx.invoked_subcommand:
            await mt._list_todo(self.bot, ctx)

    @todo.command(name="show")
    @commands.bot_has_permissions(embed_links=True)
    async def todu_show(self, ctx: Context, *, name: str):
        """To show the TODO task you created"""
        await mt._show_todo(self.bot, ctx, name)

    @todo.command(name="create")
    @commands.bot_has_permissions(embed_links=True)
    async def todo_create(self, ctx: Context, name: str, *, text: str):
        """To create a new TODO"""
        await mt._create_todo(self.bot, ctx, name, text)

    @todo.command(name="editname")
    @commands.bot_has_permissions(embed_links=True)
    async def todo_editname(self, ctx: Context, name: str, *, new_name: str):
        """To edit the TODO name"""
        await mt._update_todo_name(self.bot, ctx, name, new_name)

    @todo.command(name="edittext")
    @commands.bot_has_permissions(embed_links=True)
    async def todo_edittext(self, ctx: Context, name: str, *, text: str):
        """To edit the TODO text"""
        await mt._update_todo_text(self.bot, ctx, name, text)

    @todo.command(name="delete")
    @commands.bot_has_permissions(embed_links=True)
    async def delete_todo(self, ctx: Context, *, name: str):
        """To delete the TODO task"""
        await mt._delete_todo(self.bot, ctx, name)

    @todo.command(name="settime", aliases=["set-time"])
    @commands.bot_has_permissions(embed_links=True)
    async def settime_todo(self, ctx: Context, name: str, *, deadline: ShortTime):
        """To set timer for your Timer"""
        await mt._set_timer_todo(self.bot, ctx, name, deadline.dt.timestamp())

    @commands.group(invoke_without_command=True)
    async def afk(self, ctx: Context, *, text: commands.clean_content = None):
        """To set AFK

        AFK will be removed once you message.
        If provided permissions, bot will add `[AFK]` as the prefix in nickname.
        The deafult AFK is on Server Basis
        """
        try:
            nick = f"[AFK] {ctx.author.display_name}"
            if len(nick) <= 32:  # discord limitation
                await ctx.author.edit(nick=nick, reason=f"{ctx.author} set their AFK")
        except discord.Forbidden:
            pass
        if not ctx.invoked_subcommand:
            if text and text.split(" ")[0].lower() in (
                "global",
                "till",
                "ignore",
                "after",
                "custom",
            ):
                return
            post = {
                "_id": ctx.message.id,
                "messageURL": ctx.message.jump_url,
                "messageAuthor": ctx.author.id,
                "guild": ctx.guild.id,
                "channel": ctx.channel.id,
                "pings": [],
                "at": ctx.message.created_at.timestamp(),
                "global": False,
                "text": text or "AFK",
                "ignoredChannel": [],
            }
            await ctx.send(f"{ctx.author.mention} AFK: {text or 'AFK'}")
            await afk.insert_one({**post})

    @afk.command(name="global")
    async def _global(self, ctx: Context, *, text: commands.clean_content = None):
        """To set the AFK globally (works only if the bot can see you)"""
        post = {
            "_id": ctx.message.id,
            "messageURL": ctx.message.jump_url,
            "messageAuthor": ctx.author.id,
            "guild": ctx.guild.id,
            "channel": ctx.channel.id,
            "pings": [],
            "at": ctx.message.created_at.timestamp(),
            "global": True,
            "text": text or "AFK",
            "ignoredChannel": [],
        }
        await afk.insert_one({**post})
        await ctx.send(f"{ctx.author.mention} AFK: {text or 'AFK'}")

    @afk.command(name="for")
    async def afk_till(
        self, ctx: Context, till: ShortTime, *, text: commands.clean_content = None
    ):
        """To set the AFK time"""
        if till.dt.timestamp() - ctx.message.created_at.timestamp() <= 120:
            return await ctx.send(f"{ctx.author.mention} time must be above 120s")
        post = {
            "_id": ctx.message.id,
            "messageURL": ctx.message.jump_url,
            "messageAuthor": ctx.author.id,
            "guild": ctx.guild.id,
            "channel": ctx.channel.id,
            "pings": [],
            "at": ctx.message.created_at.timestamp(),
            "global": True,
            "text": text or "AFK",
            "ignoredChannel": [],
        }
        await afk.insert_one({**post})
        await ctx.send(
            f"{ctx.author.mention} AFK: {text or 'AFK'}\n> Your AFK status will be removed {discord.utils.format_dt(till.dt, 'R')}"
        )
        await self.create_timer(
            expires_at=till.dt.timestamp(),
            created_at=ctx.message.created_at.timestamp(),
            extra={"name": "REMOVE_AFK", "main": {**post}},
            message=ctx.message,
        )

    @afk.command(name="after")
    async def afk_after(
        self, ctx: Context, after: ShortTime, *, text: commands.clean_content = None
    ):
        """To set the AFK future time"""
        if after.dt.timestamp() - ctx.message.created_at.timestamp() <= 120:
            return await ctx.send(f"{ctx.author.mention} time must be above 120s")
        post = {
            "_id": ctx.message.id,
            "messageURL": ctx.message.jump_url,
            "messageAuthor": ctx.author.id,
            "guild": ctx.guild.id,
            "channel": ctx.channel.id,
            "pings": [],
            "at": ctx.message.created_at.timestamp(),
            "global": True,
            "text": text or "AFK",
            "ignoredChannel": [],
        }
        await ctx.send(
            f"{ctx.author.mention} AFK: {text or 'AFK'}\n> Your AFK status will be set {discord.utils.format_dt(after.dt, 'R')}"
        )
        await self.create_timer(
            expires_at=after.dt.timestamp(),
            created_at=ctx.message.created_at.timestamp(),
            extra={"name": "SET_AFK", "main": {**post}},
            message=ctx.message,
        )

    @afk.command(name="custom")
    async def custom_afk(self, ctx: Context, *, flags: afkFlags):
        """To set the custom AFK"""
        payload = {}
        payload["text"] = flags.text or "AFK"
        payload["ignoredChannel"] = (
            [c.id for c in flags.ignore_channel] if flags.ignore_channel else []
        )
        payload["global"] = flags._global
        payload["at"] = ctx.message.created_at.timestamp()
        payload["guild"] = ctx.guild.id
        payload["messageAuthor"] = ctx.author.id
        payload["messageURL"] = ctx.message.jump_url
        payload["channel"] = ctx.channel.id
        payload["_id"] = ctx.message.id
        payload["pings"] = []

        if flags.after and flags._for:
            return await ctx.send(
                f"{ctx.author.mention} can not have both `after` and `for` argument"
            )
        await afk.insert_one({**payload})
        if flags.after:
            await self.create_timer(
                expires_at=flags.after.dt.timestamp(),
                created_at=ctx.message.created_at.timestamp(),
                extra={"name": "SET_AFK", "main": {**payload}},
                message=ctx.message,
            )
            await ctx.send(
                f"{ctx.author.mention} AFK: {flags.text or 'AFK'}\n> Your AFK status will be set {discord.utils.format_dt(flags.after.dt, 'R')}"
            )
            return
        if flags._for:
            await self.create_timer(
                expires_at=flags._for.dt.timestamp(),
                created_at=ctx.message.created_at.timestamp(),
                extra={"name": "REMOVE_AFK", "main": {**payload}},
                message=ctx.message,
            )
            await ctx.send(
                f"{ctx.author.mention} AFK: {flags.text or 'AFK'}\n> Your AFK status will be removed {discord.utils.format_dt(flags._for.dt, 'R')}"
            )
            return
        await ctx.send(f"{ctx.author.mention} AFK: {flags.text or 'AFK'}")

    @tasks.loop(seconds=3)
    async def reminder_task(self):
        async with asyncio.Lock():
            async for data in self.collection.find(
                {"expires_at": {"$lte": datetime.datetime.utcnow().timestamp()}}
            ):
                cog = self.bot.get_cog("EventCustom")
                await cog.on_timer_complete(**data)
                await self.collection.delete_one({"_id": data["_id"]})

    @reminder_task.before_loop
    async def before_reminder_task(self):
        await self.bot.wait_until_ready()
