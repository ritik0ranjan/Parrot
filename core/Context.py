from __future__ import annotations

from discord.ext import commands
import discord
import typing
import asyncio
import io
import functools
from utilities.emotes import emojis
from typing import Any, Literal, Union

__all__ = ("Context",)

CONFIRM_REACTIONS = (
    "\N{THUMBS UP SIGN}",
    "\N{THUMBS DOWN SIGN}",
)


class ConfirmationView(discord.ui.View):
    def __init__(
        self,
        *,
        timeout: float,
        author_id: int,
        reacquire: bool,
        ctx: Context,
        delete_after: bool,
    ) -> None:
        super().__init__(timeout=timeout)
        self.value: typing.Optional[bool] = None
        self.delete_after: bool = delete_after
        self.author_id: int = author_id
        self.ctx: Context = ctx
        self.reacquire: bool = reacquire
        self.message: typing.Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "This confirmation dialog is not for you.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        if self.reacquire:
            await self.ctx.acquire()
        if self.delete_after and self.message:
            await self.message.delete(delay=0)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        self.value = True
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_message()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.value = False
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_message()
        self.stop()


class Context(commands.Context):
    """A custom implementation of commands.Context class."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        # we need this for our cache key strategy
        return f"<core.{self.bot.user.name} Context>"

    @property
    def session(self) -> Any:
        return self.bot.session

    @discord.utils.cached_property
    def replied_reference(self) -> typing.Optional[discord.Message]:
        ref = self.message.reference
        if ref and isinstance(ref.resolved, discord.Message):
            return ref.resolved.to_reference()
        return None

    def get_flag(
        self,
        ls,
        ann,
        *,
        deli,
        pref,
        alis,
    ) -> list:
        for flag in (ann).get_flags().values():
            if flag.required:
                ls.append(f"<{pref}{flag.name}{'|'.join(alis)}{deli}>")
            else:
                ls.append(f"[{pref}{flag.name}{'|'.join(alis)}{deli}={flag.default}]")
        return ls

    @property
    def command_syntax(
        self,
    ):
        cmd = self.command
        if cmd.usage is not None:
            return cmd.usage

        params = cmd.clean_params
        if not params:
            return ""

        result = []
        for name, param in params.items():
            greedy = isinstance(param.annotation, commands.Greedy)
            optional = False  # postpone evaluation of if it's an optional argument

            # for typing.Literal[...], typing.Optional[typing.Literal[...]], and Greedy[typing.Literal[...]], the
            # parameter signature is a literal list of it's values
            annotation = param.annotation.converter if greedy else param.annotation
            origin = getattr(annotation, "__origin__", None)
            if not greedy and origin is Union:
                none_cls = type(None)
                union_args = annotation.__args__
                optional = union_args[-1] is none_cls
                if len(union_args) == 2 and optional:
                    annotation = union_args[0]
                    origin = getattr(annotation, "__origin__", None)

            if origin is Literal:
                name = "|".join(
                    f'"{v}"' if isinstance(v, str) else str(v)
                    for v in annotation.__args__
                )
            if param.default is not param.empty:
                # We don't want None or '' to trigger the [name=value] case and instead it should
                # do [name] since [name=None] or [name=] are not exactly useful for the user.
                should_print = (
                    param.default
                    if isinstance(param.default, str)
                    else param.default is not None
                )
                if should_print:
                    result.append(
                        f"[{name}={param.default}]"
                        if not greedy
                        else f"[{name}={param.default}]..."
                    )
                    continue
                else:
                    result.append(f"[{name}]")

            elif param.kind == param.VAR_POSITIONAL:
                if cmd.require_var_positional:
                    result.append(f"<{name}...>")
                else:
                    result.append(f"[{name}...]")
            elif greedy:
                result.append(f"[{name}]...")
            elif optional:
                result.append(f"[{name}]")
            elif isinstance(param.annotation, commands.flags.FlagsMeta):
                ann = param.annotation
                deli = ann.__commands_flag_delimiter__
                pref = ann.__commands_flag_prefix__
                alis = ann.__commands_flag_aliases__
                self.get_flag(result, param.annotation, deli=deli, pref=pref, alis=alis)
            else:
                result.append(f"<{name}>")

        return " ".join(result)

    def with_type(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            context = args[0] if isinstance(args[0], commands.Context) else args[1]
            try:
                async with context.typing():
                    await func(*args, **kwargs)
            except discord.Forbidden:
                await func(*args, **kwargs)

        return wrapped

    async def show_help(self, command=None):
        cmd = self.bot.get_command("help")
        command = command or self.command.qualified_name
        await self.invoke(cmd, command=command)

    async def send(
        self, content: typing.Optional[str] = None, **kwargs
    ) -> typing.Optional[discord.Message]:
        perms = self.channel.permissions_for(self.me)
        if not (perms.send_messages and perms.embed_links):
            try:
                await self.author.send(
                    "Bot don't have either Embed Links/Send Messages permission in that channel. Please give sufficient permissions to the bot."
                )
            except discord.Forbidden:  # DMs locked
                pass
            return

        return await super().send(content, **kwargs)

    async def reply(self, content: typing.Optional[str] = None, **kwargs):
        perms = self.channel.permissions_for(self.me)
        if not (perms.send_messages and perms.embed_links):
            try:
                await self.author.send(
                    "Bot don't have permission to send message in that channel. Please give me sufficient permissions to do so."
                )
            except discord.Fobidden:
                pass
            return
        return await super().reply(content, **kwargs)

    async def entry_to_code(self, entries) -> typing.Optional[discord.Message]:
        width = max(len(str(a)) for a, b in entries)
        output = ["```"]
        for name, entry in entries:
            output.append(f"{name:<{width}}: {entry}")
        output.append("```")
        await self.send("\n".join(output))

    async def indented_entry_to_code(self, entries) -> typing.Optional[discord.Message]:
        width = max(len(str(a)) for a, b in entries)
        output = ["```"]
        for name, entry in entries:
            output.append(f"\u200b{name:>{width}}: {entry}")
        output.append("```")
        await self.send("\n".join(output))

    async def emoji(self, emoji: str) -> str:
        return emojis[emoji]

    async def prompt(
        self,
        message: str,
        *,
        timeout: float = 60.0,
        delete_after: bool = True,
        reacquire: bool = True,
        author_id: typing.Optional[int] = None,
        **kwargs,
    ) -> typing.Optional[bool]:
        author_id = author_id or self.author.id
        view = ConfirmationView(
            timeout=timeout,
            delete_after=delete_after,
            reacquire=reacquire,
            ctx=self,
            author_id=author_id,
        )
        view.message = await self.send(message, view=view, **kwargs)
        await view.wait()
        return view.value

    async def release(self) -> None:
        await asyncio.sleep(0)

    async def safe_send(
        self, content, *, escape_mentions=True, **kwargs
    ) -> typing.Optional[discord.Message]:
        if escape_mentions:
            content = discord.utils.escape_mentions(content)

        if len(content) > 2000:
            fp = io.BytesIO(content.encode())
            kwargs.pop("file", None)
            return await self.send(
                file=discord.File(fp, filename="message_too_long.txt"), **kwargs
            )
        return await self.send(content)

    async def bulk_add_reactions(
        self, message: discord.Message, *reactions: typing.Union[discord.Emoji, str]
    ) -> None:
        coros = [
            asyncio.ensure_future(message.add_reaction(reaction))
            for reaction in reactions
        ]
        await asyncio.wait(coros)

    async def confirm(
        self,
        bot: Any,
        channel: discord.TextChannel,
        user: typing.Union[discord.Member, discord.User],
        *args: typing.Any,
        timeout: float = 60,
        delete_after: bool = False,
        **kwargs: typing.Any,
    ) -> typing.Optional[bool]:
        message = await channel.send(*args, **kwargs)
        await self.bulk_add_reactions(message, *CONFIRM_REACTIONS)

        def check(payload: discord.RawReactionActionEvent) -> bool:
            return (
                payload.message_id == message.id
                and payload.user_id == user.id
                and str(payload.emoji) in CONFIRM_REACTIONS
            )

        try:
            payload = await bot.wait_for(
                "raw_reaction_add", check=check, timeout=timeout
            )
            return str(payload.emoji) == "\N{THUMBS UP SIGN}"
        except asyncio.TimeoutError:
            return None
        finally:
            if delete_after:
                await message.delete(delay=0)
