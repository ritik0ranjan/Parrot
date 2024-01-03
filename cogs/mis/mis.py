from __future__ import annotations

import asyncio
import hashlib
import inspect
import io
import json
import os
import re
import string
import urllib.parse
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, BinaryIO

import arrow
import qrcode
import sympy
import yarl
from dateutil.zoneinfo import get_zonefile_instance
from jishaku.paginators import PaginatorEmbedInterface
from PIL import Image
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import (
    HorizontalGradiantColorMask,
    RadialGradiantColorMask,
    SolidFillColorMask,
    SquareGradiantColorMask,
    VerticalGradiantColorMask,
)
from qrcode.image.styles.moduledrawers import (
    CircleModuleDrawer,
    GappedSquareModuleDrawer,
    HorizontalBarsDrawer,
    RoundedModuleDrawer,
    SquareModuleDrawer,
    VerticalBarsDrawer,
)
from rapidfuzz import process

import discord
from core import Cog, Context, Parrot, ParrotView
from discord import Embed
from discord.ext import commands
from utilities.converters import convert_bool
from utilities.imaging.graphing import boxplot, plotfn
from utilities.imaging.image import do_command
from utilities.paginator import PaginationView
from utilities.regex import INVITE_RE, LINKS_RE
from utilities.robopages import SimplePages
from utilities.ttg import Truths
from utilities.youtube_search import YoutubeSearch

from .__embed_view import EmbedBuilder, EmbedCancel, EmbedSend
from .__flags import SearchFlag, TTFlag

if TYPE_CHECKING:
    from .listeners import PingMessageListner, SnipeMessageListener

google_key: str = os.environ["GOOGLE_KEY"]
cx: str = os.environ["GOOGLE_CX"]

SEARCH_API = "https://en.wikipedia.org/w/api.php"
WIKI_PARAMS = {
    "action": "query",
    "list": "search",
    "prop": "info",
    "inprop": "url",
    "utf8": "",
    "format": "json",
    "origin": "*",
}
WIKI_THUMBNAIL = (
    "https://upload.wikimedia.org/wikipedia/en/thumb/8/80/Wikipedia-logo-v2.svg" "/330px-Wikipedia-logo-v2.svg.png"
)
WIKI_SNIPPET_REGEX = r"(<!--.*?-->|<[^>]*>)"
WIKI_SEARCH_RESULT = "**[{name}]({url})**\n{description}\n"

FORMATTED_CODE_REGEX = re.compile(
    r"(?P<delim>(?P<block>```)|``?)"  # code delimiter: 1-3 backticks; (?P=block) only matches if it's a block
    r"(?(block)(?:(?P<lang>[a-z]+)\n)?)"  # if we're in a block, match optional language (only letters plus newline)
    r"(?:[ \t]*\n)*"  # any blank (empty or tabs/spaces only) lines before the code
    r"(?P<code>.*?)"  # extract all code inside the markup
    r"\s*"  # any more whitespace before the end of the code markup
    r"(?P=delim)",  # match the exact same delimiter from the start again
    re.DOTALL | re.IGNORECASE,  # "." also matches newlines, case insensitive
)

LATEX_API_URL = "https://rtex.probablyaweb.site/api/v2"

THIS_DIR = Path(__file__).parent
CACHE_DIRECTORY = THIS_DIR / "_latex_cache"
CACHE_DIRECTORY.mkdir(exist_ok=True)
TEMPLATE = string.Template(Path("extra/latex_template.txt").read_text())

BG_COLOR = (54, 57, 63, 255)
PAD = 10

with open("extra/country.json", encoding="utf-8", errors="ignore") as f:
    COUNTRY_CODES = json.load(f)


_SEACH_FLAG_CONVERTERS = {
    "c2off": "c2coff",
    "exact_terms": "exactTerms",
    "exclude_terms": "excludeTerms",
    "file_type": "fileType",
    "filter": "filter",
    "gl": "gl",
    "high_range": "highRange",
    "hl": "hl",
    "hq": "hq",
    "img_color_type": "imgColorType",
    "img_dominant_color": "imgDominantColor",
    "img_size": "imgSize",
    "img_type": "imgType",
    "link_site": "linkSite",
    "low_range": "lowRange",
    "lr": "lr",
    "num": "num",
    "or_terms": "orTerms",
    "q": "q",
    "related_site": "relatedSite",
    "rights": "rights",
    "safe": "safe",
    "search_type": "searchType",
    "site_search_filter": "siteSearchFilter",
    "sort": "sort",
    "start": "start",
}


def get_country_code(country: str) -> str | None:
    return next(
        (
            c
            for c, n in COUNTRY_CODES.items()
            if country.lower() in (c.lower(), n.lower())
        ),
        None,
    )


def _prepare_input(text: str) -> str:
    if match := FORMATTED_CODE_REGEX.match(text):
        return match.group("code")
    return text


def _process_image(data: bytes, out_file: BinaryIO) -> None:
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    width, height = image.size
    background = Image.new("RGBA", (width + 2 * PAD, height + 2 * PAD), "WHITE")
    background.paste(image, (PAD, PAD), image)
    background.save(out_file)


class InvalidLatexError(Exception):
    """Represents an error caused by invalid latex."""

    def __init__(self, logs: str | None) -> None:
        super().__init__(logs)
        self.logs = logs


def _create_qr(
    text: str,
    *,
    version: int | None = 1,
    board_size: int | None = 10,
    border: int | None = 4,
    **kw,
) -> discord.File:
    qr = qrcode.QRCode(
        version=version,
        error_correction=qrcode.ERROR_CORRECT_L,
        box_size=board_size or 10,
        border=border or 4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white", **kw)

    out = io.BytesIO()
    img.save(out, "png")
    out.seek(0)
    return discord.File(out, filename="qr.png")


class QRCodeFlags(commands.FlagConverter, case_insensitive=True, prefix="--", delimiter=" "):
    board_size: int | None = commands.flag(name="board_size", default=10, aliases=["size", "board"])
    border: int | None = 4
    module_drawer: str | None = commands.flag(name="module_drawer", default="square", aliases=["modular", "module"])
    color_mask: str | None = commands.flag(name="color_mask", default="solid", aliases=["color", "mask"])


qr_modular = {
    "square": SquareModuleDrawer(),
    "gapped": GappedSquareModuleDrawer(),
    "circle": CircleModuleDrawer(),
    "round": RoundedModuleDrawer(),
    "vertical": VerticalBarsDrawer(),
    "ver": VerticalBarsDrawer(),
    "horizontal": HorizontalBarsDrawer(),
    "hor": HorizontalBarsDrawer(),
}

qr_color_mask = {
    "solid": SolidFillColorMask(),
    "radial": RadialGradiantColorMask(),
    "square": SquareGradiantColorMask(),
    "hor": HorizontalGradiantColorMask(),
    "horizontal": HorizontalGradiantColorMask(),
    "vertical": VerticalGradiantColorMask(),
    "ver": VerticalGradiantColorMask(),
}


class Misc(Cog):
    """Those commands which can't be listed."""

    def __init__(self, bot: Parrot) -> None:
        self.bot = bot
        self.ON_TESTING = False
        self.youtube_search = YoutubeSearch(5)
        self.valid_timezones: set[str] = set(get_zonefile_instance().zones)
        # User-friendly timezone names, some manual and most from the CLDR database.
        self._timezone_aliases: dict[str, str] = {
            "Eastern Time": "America/New_York",
            "Central Time": "America/Chicago",
            "Mountain Time": "America/Denver",
            "Pacific Time": "America/Los_Angeles",
            # (Unfortunately) special case American timezone abbreviations
            "EST": "America/New_York",
            "CST": "America/Chicago",
            "MST": "America/Denver",
            "PST": "America/Los_Angeles",
            "EDT": "America/New_York",
            "CDT": "America/Chicago",
            "MDT": "America/Denver",
            "PDT": "America/Los_Angeles",
            "IST": "Asia/Kolkata",
        }

    async def cog_unload(self) -> None:
        await self.youtube_search.close()

    async def wiki_request(self, _: discord.TextChannel, search: str) -> list[str]:
        """Search wikipedia search string and return formatted first 10 pages found."""
        params = {**WIKI_PARAMS, "srlimit": 10, "srsearch": search}
        async with self.bot.http_session.get(url=SEARCH_API, params=params) as resp:
            if resp.status != 200:
                msg = f"Wikipedia API {resp.status}"
                raise commands.BadArgument(msg)

            raw_data = await resp.json()

            if not raw_data.get("query"):
                msg = f"Wikipedia API: {resp.status} {raw_data.get('errors')}"
                raise commands.BadArgument(msg)

            lines = []
            if raw_data["query"]["searchinfo"]["totalhits"]:
                for article in raw_data["query"]["search"]:
                    line = WIKI_SEARCH_RESULT.format(
                        name=article["title"],
                        description=unescape(re.sub(WIKI_SNIPPET_REGEX, "", article["snippet"])),
                        url=f"https://en.wikipedia.org/?curid={article['pageid']}",
                    )
                    lines.append(line)

            return lines

    def sanitise(self, st: str) -> str:
        if len(st) > 1024:
            st = f"{st[:980]}..."
        return INVITE_RE.sub("[INVITE REDACTED]", st)

    async def _generate_image(self, query: str, out_file: BinaryIO) -> None:
        """Make an API request and save the generated image to cache."""
        payload = {"code": query, "format": "png"}
        async with self.bot.http_session.post(LATEX_API_URL, data=payload, raise_for_status=True) as response:
            response_json = await response.json()
        if response_json["status"] != "success":
            raise InvalidLatexError(logs=response_json.get("log"))
        async with self.bot.http_session.get(
            f"{LATEX_API_URL}/{response_json['filename']}",
            raise_for_status=True,
        ) as response:
            await asyncio.to_thread(_process_image, await response.read(), out_file)

    async def _upload_to_pastebin(self, text: str, lang: str = "txt") -> str | None:
        """Uploads `text` to the paste service, returning the url if successful."""
        post = await self.bot.http_session.post("https://hastebin.com/documents", data=text)

        if post.status == 200:
            response = await post.text()
            return f"https://hastebin.com/{response[8:-2]}"
        post = await self.bot.http_session.post("https://bin.readthedocs.fr/new", data={"code": text, "lang": lang})

        return str(post.url) if post.status == 200 else None

    @commands.command()
    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    @Context.with_type
    async def latex(self, ctx: Context, *, query: str) -> None:
        """Renders the text in latex and sends the image."""
        query = _prepare_input(query)
        query_hash = hashlib.md5(query.encode()).hexdigest()  # nosec
        image_path = CACHE_DIRECTORY / f"{query_hash}.png"
        if not image_path.exists():
            try:
                with open(image_path, "wb") as out_file:
                    await self._generate_image(TEMPLATE.substitute(text=query), out_file)
            except InvalidLatexError as err:
                embed = discord.Embed(title="Failed to render input.")
                if err.logs is None:
                    embed.description = "No logs available"
                else:
                    logs_paste_url = await self._upload_to_pastebin(err.logs)
                    if logs_paste_url:
                        embed.description = f"[View Logs]({logs_paste_url})"
                    else:
                        embed.description = "Couldn't upload logs."
                await ctx.send(embed=embed)
                image_path.unlink()
                return
        await ctx.send(file=discord.File(image_path, "latex.png"))

    @property
    def display_emoji(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name="Plus", id=892440360750555136)

    @commands.command(aliases=["calc", "cal"])
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def calculator(self, ctx: Context, *, text: str = None):
        """This is basic calculator with all the expression supported. Syntax is similar to python math module."""
        if text:
            new_text = urllib.parse.quote(text)
            url = yarl.URL("http://twitch.center/customapi/math")
            url = url.update_query({"expr": new_text})

            r = await self.bot.http_session.get(url)
            embed = discord.Embed(
                title="Calculated!!",
                description=f"```ini\n[Answer is: {await r.text()}]```",
                timestamp=discord.utils.utcnow(),
            )

            await ctx.reply(embed=embed)
        else:
            from cogs.mis.__calc_view import CalcView as CalculatorView

            await ctx.send(
                embed=discord.Embed(description="```\n \n```"),
                view=CalculatorView(timeout=120, ctx=ctx, arg=""),
            )

    @commands.command()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def firstmessage(
        self,
        ctx: Context,
        *,
        channel: discord.TextChannel | discord.VoiceChannel | None = None,
    ):
        """To get the first message of the specified channel."""
        channel = channel or ctx.channel  # type: ignore

        assert isinstance(channel, discord.TextChannel)

        async for msg in channel.history(limit=1, oldest_first=True):
            return await ctx.send(
                embed=discord.Embed(
                    title=f"First message in {channel.name}",
                    url=msg.jump_url,
                    description=f"{msg.content}",  # fuck you pycord
                    timestamp=discord.utils.utcnow(),
                ).set_footer(text=f"Message sent by {msg.author}"),
            )

    @commands.command()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def maths(self, ctx: Context, operation: str, *, expression: str):
        """Another calculator but quite advance one.

        Note: Available operation -
            - Simplify
            - Factor
            - Derive
            - Integrate
            - Zeroes
            - Tangent
            - Area
            - Cos
            - Sin
            - Tan
            - Arccos
            - Arcsin
            - Arctan
            - Abs
            - Log
        For more detailed use, visit: `https://github.com/aunyks/newton-api/blob/master/README.md`
        """
        new_expression = urllib.parse.quote(expression)
        url = yarl.URL("https://newton.now.sh/api/v2/")
        url = url / operation / new_expression

        r = await self.bot.http_session.get(url)
        if r.status == 200:
            res = await r.json()
        else:
            return await ctx.error(f"{ctx.author.mention} invalid **{expression}** or either **{operation}**")
        result = res["result"]
        embed = discord.Embed(
            title="Calculated!!",
            description=f"```ini\n[Answer is: {result}]```",
            timestamp=discord.utils.utcnow(),
        )
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.cooldown(1, 60, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def news(self, ctx: Context, *, nat: str):
        """This command will fetch the latest news from all over the world."""
        NEWS_KEY = os.environ["NEWSKEY"]
        if not get_country_code(nat):
            return await ctx.reply(f"{ctx.author.mention} **{nat}** is not a valid country code.")
        link = yarl.URL("http://newsapi.org/")
        link = link / "v2" / "top-headlines"
        link = link.update_query({"country": nat, "apiKey": NEWS_KEY})

        r = await self.bot.http_session.get(link)
        res = await r.json()

        if res["status"].upper() != "OK":
            return await ctx.error(f"{ctx.author.mention} something not right!")

        em_list = []
        for data in range(len(res["articles"])):
            source = res["articles"][data]["source"]["name"]
            author = res["articles"][data]["author"]
            title = res["articles"][data]["title"]
            description = res["articles"][data]["description"]
            img = res["articles"][data]["urlToImage"]
            content = res["articles"][data]["content"] or "N/A"

            embed = (
                Embed(
                    title=f"{title}",
                    description=f"{description}",
                    timestamp=discord.utils.utcnow(),
                )
                .add_field(name=f"{source}", value=f"{content}")
                .set_author(name=f"{author}")
                .set_footer(text=f"{ctx.author}")
            )
            if img:
                _r = await self.bot.http_session.get(img)
                if _r.ok:
                    embed.set_image(url=img)
            em_list.append(embed)

        await PaginationView(em_list).start(ctx=ctx)

    @commands.group(name="search", aliases=["googlesearch", "google"], invoke_without_command=True)
    @commands.cooldown(1, 60, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def search(self, ctx: Context[Parrot], *, search: str):
        """Simple google search Engine."""
        if ctx.invoked_subcommand:
            return
        search = urllib.parse.quote(search)
        safe = "off" if ctx.channel.nsfw else "active"
        url = yarl.URL("https://www.googleapis.com/")
        url = url / "customsearch" / "v1"
        url = url.update_query(
            {
                "key": google_key,
                "cx": cx,
                "q": search,
                "safe": safe,
            },
        )

        response = await self.bot.http_session.get(url)
        json_ = await response.json()
        if response.status != 200:
            return await ctx.error(f"{ctx.author.mention} No results found. `{json_['error']['message']}`")

        pages = []

        for item in json_.get("items", []):
            title = item["title"]
            link = item["link"]
            snippet = item.get("snippet")

            pages.append(
                f"""**[Title: {title}]({link})**
> {snippet}

""",
            )
        if not pages:
            return await ctx.error(f"{ctx.author.mention} No results found.`{urllib.parse.unquote(search)}`")
        page = SimplePages(entries=pages, ctx=ctx, per_page=3)
        await page.start()

    @search.command(name="custom")
    @commands.cooldown(1, 60, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def search_custom(self, ctx: Context, *, search: SearchFlag):
        """To make custom search request."""
        PAYLOAD = {"q": search.q}
        for k, v in _SEACH_FLAG_CONVERTERS.items():
            if hasattr(search, k):
                PAYLOAD[v] = getattr(search, k)
        if not ctx.channel.nsfw:  # type: ignore
            PAYLOAD["safe"] = "active"

        url = "https://www.googleapis.com/customsearch/v1"
        response = await self.bot.http_session.get(url, params=PAYLOAD)

        json_ = await response.json()
        if response.status != 200:
            return await ctx.error(f"{ctx.author.mention} No results found. `{json_['error']['message']}`")
        pages = []

        for item in json_.get("items", []):
            title = item["title"]
            link = item["link"]
            snippet = item.get("snippet")

            pages.append(
                f"""**[Title: {title}]({link})**
> {snippet}

""",
            )
        if not pages:
            return await ctx.error(f"{ctx.author.mention} No results found.`{urllib.parse.unquote(search)}`")
        page = SimplePages(entries=pages, ctx=ctx, per_page=3)
        await page.start()

    @commands.command(name="snipe")
    @commands.bot_has_permissions(read_message_history=True, embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def snipe_message(self, ctx: Context, channel: discord.TextChannel | None = None, index: int = 1):
        """Snipes someone's message that's deleted."""
        snipes: SnipeMessageListener = self.bot.SnipeMessageListener
        if snipes is None:
            return await ctx.error(f"{ctx.author.mention} Snipe cog is not loaded!")

        snipe: discord.Message = snipes.get_snipe(channel or ctx.channel, index=index)  # type: ignore
        if snipe is None:
            return await ctx.reply(f"{ctx.author.mention} no snipes in this channel!")

        if channel and not channel.permissions_for(ctx.author).read_message_history:
            channel = ctx.channel

        if not ctx.author.guild_permissions.manage_messages:
            index = 1

        emb = (
            discord.Embed(color=snipe.author.color, timestamp=snipe.created_at)
            .set_author(name=snipe.author, icon_url=snipe.author.display_avatar.url)
            .set_footer(
                text=f"Message sniped by {str(ctx.author)}",
                icon_url=ctx.author.display_avatar.url,
            )
        )
        if snipe.attachments:
            url = snipe.attachments[0].proxy_url
            if url.endswith(("png", "jpeg", "jpg", "gif", "webp")):
                emb.set_image(url=url)

        ref = snipe.reference.resolved if snipe.reference else None
        if LINKS_RE.fullmatch(snipe.content) and snipe.content.endswith(("png", "jpeg", "jpg", "gif", "webp")):
            if isinstance(ref, discord.Message):
                emb.description = f"Replied to: **[{ref.author}]({ref.jump_url})**"
            emb.set_image(url=snipe.content)
        elif isinstance(ref, discord.Message):
            emb.description = f"- **Replied to: [`{ref.author}`]({ref.jump_url})**\n\n{self.sanitise(snipe.content)}"

        else:
            emb.description = self.sanitise(snipe.content)

        await ctx.reply(embed=emb)
        snipes.delete_snipe(channel or ctx.channel, index=index)

    @commands.command(name="editsnipe", aliases=["esnipe"])
    @commands.bot_has_permissions(read_message_history=True, embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def edit_snipe_message(self, ctx: Context, channel: discord.TextChannel | None = None, index: int = 1):
        """Snipes someone's message that's deleted."""
        if channel and not channel.permissions_for(ctx.author).read_message_history:
            channel = ctx.channel

        if not ctx.author.guild_permissions.manage_messages:
            index = 1

        snipes: SnipeMessageListener = self.bot.SnipeMessageListener
        if snipes is None:
            return await ctx.error(f"{ctx.author.mention} Snipe cog is not loaded!")

        snipe: tuple[discord.Message, discord.Message] = snipes.get_edit_snipe(channel or ctx.channel, index=index)  # type: ignore
        if snipe is None:
            return await ctx.reply(f"{ctx.author.mention} no snipes in this channel!")

        emb = (
            discord.Embed(color=snipe[0].author.color, timestamp=snipe[0].created_at)
            .set_author(name=snipe[0].author, icon_url=snipe[0].author.display_avatar.url)
            .set_footer(
                text=f"Message sniped by {str(ctx.author)}",
                icon_url=ctx.author.display_avatar.url,
            )
        )
        if snipe[0].content and snipe[1].content:
            emb.description = (
                f"**Before:**\n{self.sanitise(snipe[0].content)}\n\n**After:**\n{self.sanitise(snipe[1].content)}"
            )

        await ctx.reply(embed=emb)
        snipes.delete_edit_snipe(channel or ctx.channel, index=index)

    @commands.command(aliases=["trutht", "tt", "ttable"])
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def truthtable(self, ctx: Context, *, flags: TTFlag):
        """A simple command to generate Truth Table of given data. Make sure you use proper syntax.

        ```
        Negation             : not, -, ~
        Logical disjunction  : or
        Logical nor          : nor
        Exclusive disjunction: xor, !=
        Logical conjunction  : and
        Logical NAND         : nand
        Material implication : =>, implies
        Logical biconditional: =
        ```

        **Example:**
        - `[p]truthtable --var p, q --con p and q`
        """
        table = Truths(
            [j.strip(" ") for j in flags.var.replace(" ", "").split(",")],
            [i.strip(" ") for i in flags.con.split(",")],
            ascending=flags.ascending,
        )
        main = table.as_tabulate(index=False, table_format=flags.table_format, align=flags.align)
        await ctx.reply(f"```{flags.table_format}\n{main}\n```")

    @commands.command(aliases=["w"])
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def weather(self, ctx: Context, *, location: str):
        """Weather API, for current weather forecast, supports almost every city."""
        appid = os.environ["WEATHERID"]

        loc = urllib.parse.quote(location)
        link = f"https://api.openweathermap.org/data/2.5/weather?q={loc}&appid={appid}"

        r = await self.bot.http_session.get(link)
        if r.status == 200:
            res = await r.json()
        else:
            return await ctx.reply(f"{ctx.author.mention} no location named, **{location}**")


        embed: discord.Embed = discord.Embed()
        res["coord"]["lat"]
        res["coord"]["lon"]

        if res["weather"]:
            weather = res["weather"][0]["main"]
            description = res["weather"][0]["description"]
            icon = res["weather"][0]["icon"]
            icon_url = f"http://openweathermap.org/img/w/{icon}.png"

            embed.set_thumbnail(url=icon_url)
            embed.description = f"{weather}: {description}"

        temp = res["main"]["temp"] - 273.15
        feels_like = res["main"]["feels_like"] - 273.15
        humidity = res["main"]["humidity"]
        pressure = res["main"]["pressure"]
        wind_speed = res["wind"]["speed"]
        wind_deg = res["wind"]["deg"]
        cloudiness = res["clouds"]["all"]
        visibliity = res["visibility"]
        sunrise = arrow.Arrow.fromtimestamp(res["sys"]["sunrise"])
        sunset = arrow.Arrow.fromtimestamp(res["sys"]["sunset"])
        country = res["sys"]["country"]
        _id = res["id"]
        name = res["name"]

        embed.add_field(name="Temperature", value=f"{temp:.2f}°C").add_field(
            name="Feels Like",
            value=f"{feels_like:.2f}°C",
        ).add_field(
            name="Humidity",
            value=f"{humidity}%",
        ).add_field(
            name="Pressure",
            value=f"{pressure}hPa",
        ).add_field(
            name="Wind Speed",
            value=f"{wind_speed}m/s",
        ).add_field(
            name="Wind Direction",
            value=f"{wind_deg}°",
        ).add_field(
            name="Cloudiness",
            value=f"{cloudiness}%",
        ).add_field(
            name="Visibility",
            value=f"{visibliity}m",
        ).add_field(
            name="Sunrise",
            value=f"{sunrise.strftime('%H:%M')}",
        ).add_field(
            name="Sunset",
            value=f"{sunset.strftime('%H:%M')}",
        ).add_field(
            name="Country",
            value=f"{country}",
        ).add_field(
            name="Name",
            value=f"{name}",
        ).set_footer(
            text=f"{ctx.author.name}",
            icon_url=ctx.author.display_avatar.url,
        ).set_author(
            name=f"{name}: {_id}",
            icon_url=ctx.author.display_avatar.url,
        )

        await ctx.reply(embed=embed)

    @commands.command(aliases=["wiki"])
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def wikipedia(self, ctx: Context, *, search: str):
        """Web articles from Wikipedia."""
        contents = await self.wiki_request(ctx.channel, search)

        if contents:
            embed = Embed(title="Wikipedia Search Results", colour=ctx.author.color)
            embed.set_thumbnail(url=WIKI_THUMBNAIL)
            embed.timestamp = discord.utils.utcnow()
            page = SimplePages(entries=contents, ctx=ctx, per_page=3)
            await page.start()
        else:
            await ctx.error("Sorry, we could not find a wikipedia article using that search term.")

    @commands.command(aliases=["yt"])
    @commands.is_nsfw()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def youtube(self, ctx: Context, *, query: str):
        """Search for videos on YouTube."""
        results = await self.youtube_search.to_json(query)
        main: dict[str, Any] = json.loads(results)

        em_list = []

        for i in range(len(main["videos"])):
            _1_title = main["videos"][i]["title"]
            _1_descr = main["videos"][i]["long_desc"]
            _1_chann = main["videos"][i]["channel"]
            _1_views = main["videos"][i]["views"]
            _1_urlsu = "https://www.youtube.com" + str(main["videos"][i]["url_suffix"])
            _1_durat = main["videos"][i]["duration"]
            _1_thunb = str(main["videos"][i]["thumbnails"][0])
            embed = (
                discord.Embed(
                    title=f"YouTube search results: {query}",
                    description=f"{_1_urlsu}",
                    colour=discord.Colour.red(),
                    url=_1_urlsu,
                )
                .add_field(
                    name=f"Video title:`{_1_title}`\n",
                    value=f"Channel:```\n{_1_chann}\n```\nDescription:```\n{_1_descr}\n```\nViews:```\n{_1_views}\n```\nDuration:```\n{_1_durat}\n```",
                    inline=False,
                )
                .set_thumbnail(
                    url="https://cdn4.iconfinder.com/data/icons/social-messaging-ui-color-shapes-2-free/128/social"
                    "-youtube-circle-512.png",
                )
                .set_image(url=f"{_1_thunb}")
                .set_footer(text=f"{ctx.author.name}")
            )
            em_list.append(embed)

        await PaginationView(em_list).start(ctx=ctx)

    @commands.command()
    @commands.has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def embed(
        self,
        ctx: Context,
        channel: discord.TextChannel | None = None,
        *,
        data: dict | str = None,
    ):
        """A nice command to make custom embeds, from `JSON`. Provided it is in the format that Discord expects it to be in.
        You can find the documentation on `https://discord.com/developers/docs/resources/channel#embed-object`.
        """
        channel = channel or ctx.channel  # type: ignore
        if channel.permissions_for(ctx.author).embed_links:  # type: ignore
            if not data:
                view = EmbedBuilder(ctx, items=[EmbedSend(channel), EmbedCancel()])  # type: ignore
                await view.rendor()
                return
            try:
                await channel.send(embed=discord.Embed.from_dict(json.loads(str(data))))  # type: ignore
            except Exception as e:
                await ctx.error(f"{ctx.author.mention} you didn't provide the proper json object. Error raised: {e}")
        else:
            await ctx.error(f"{ctx.author.mention} you don't have Embed Links permission in {channel.mention}")

    @commands.command()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def snowflakeid(
        self,
        ctx: Context,
        *,
        target: discord.User
        | discord.Member
        | discord.Role
        | discord.Thread
        | discord.TextChannel
        | discord.VoiceChannel
        | discord.StageChannel
        | discord.Guild
        | discord.Emoji
        | discord.Invite
        | discord.Template
        | discord.CategoryChannel
        | discord.DMChannel
        | discord.GroupChannel
        | discord.Object,
    ):
        """To get the ID of discord models."""
        embed = discord.Embed(
            title="Snowflake lookup",
            color=ctx.author.color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Type", value=f"`{target.__class__.__name__}`", inline=True)
        embed.add_field(
            name="Created At",
            value=f"{discord.utils.format_dt(target.created_at)}" if target.created_at is not None else "None",
            inline=True,
        )
        embed.add_field(name="ID", value=f"`{getattr(target, 'id', 'NA')}`", inline=True)
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def snowflaketime(self, ctx: Context, snowflake1: int, snowflake2: int):
        """Get the time difference in seconds, between two discord SnowFlakes."""
        first = discord.utils.snowflake_time(snowflake1)
        second = discord.utils.snowflake_time(snowflake2)

        timedelta = second - first if snowflake2 > snowflake1 else first - second
        await ctx.reply(
            f"{ctx.author.mention} total seconds between **{snowflake1}** and **{snowflake2}** is **{timedelta.total_seconds()}**",
        )

    @commands.command(aliases=["src"])
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def source(self, ctx: Context, *, command: str | None = None):
        """Displays my full source code or for a specific command.

        To display the source code of a subcommand you can separate it by
        periods, e.g. tag.create for the create subcommand of the tag command
        or by spaces.
        """
        source_url = "https://github.com/rtk-rnjn/Parrot"
        branch = "main"
        if command is None:
            return await ctx.reply(f"<{source_url}>")

        if command == "help":
            src = type(self.bot.help_command)
            module = src.__module__
            filename = inspect.getsourcefile(src)
        else:
            obj = self.bot.get_command(command.replace(".", " "))
            if obj is None:
                return await ctx.reply("Could not find command.")

            # since we found the command we're looking for, presumably anyway, let's
            # try to access the code itself
            callback = getattr(obj.callback, "_callback", obj.callback)
            src = callback.__code__
            module = callback.__module__
            filename = src.co_filename

        lines, firstlineno = inspect.getsourcelines(src)
        if module.startswith("discord"):
            location = module.replace(".", "/") + ".py"
            source_url = "https://github.com/Rapptz/discord.py"
            branch = "master"

        elif filename is None:
            return await ctx.reply("Could not find source for command.")

        else:
            location = os.path.relpath(filename).replace("\\", "/")
        final_url = f"<{source_url}/blob/{branch}/{location}#L{firstlineno}-L{firstlineno + len(lines) - 1}>"
        await ctx.reply(final_url)

    @commands.command()
    @commands.has_permissions(manage_messages=True, add_reactions=True)
    @commands.bot_has_permissions(embed_links=True, add_reactions=True, read_message_history=True)
    @Context.with_type
    async def quickpoll(self, ctx: Context, *questions_and_choices: str):
        """To make a quick poll for making quick decision.
        'Question must be in quotes' and 'Options' 'must' 'be' 'seperated' 'by' 'spaces'.
        Not more than 21 options. :).
        """

        def to_emoji(c) -> str:
            base = 0x1F1E6
            return chr(base + c)

        if len(questions_and_choices) < 3:
            return await ctx.send("Need at least 1 question with 2 choices.")
        if len(questions_and_choices) > 21:
            return await ctx.send("You can only have up to 20 choices.")

        question = questions_and_choices[0]
        choices = [(to_emoji(e), v) for e, v in enumerate(questions_and_choices[1:])]

        body = "\n".join(f"{key}: {c}" for key, c in choices)
        poll: discord.Message = await ctx.send(f"**Poll: {question}**\n\n{body}")
        await ctx.bulk_add_reactions(poll, *[emoji for emoji, _ in choices])

        await ctx.message.delete(delay=5)

    # TODO: Add Strawpoll
    # TODO: OCR

    @commands.command(name="qr", aliases=["createqr", "cqr"])
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def qrcode(self, ctx: Context, text: str, *, flags: QRCodeFlags):
        """To generate the QR from the given Text.

        **Flags:**
        - `--module` to change the module drawer.
        - `--color` to change the color mask.
        - `--board` to change the board size.
        - `--border` to change the border size.
        """
        payload: dict[str, Any] = {}
        if flags.module_drawer and (mod := qr_modular.get(flags.module_drawer)):
            payload["module_drawer"] = mod
        if flags.color_mask and (col := qr_color_mask.get(flags.color_mask)):
            payload["color_mask"] = col

        if payload:
            payload["image_factory"] = StyledPilImage
        payload["board_size"] = flags.board_size
        payload["border"] = flags.border
        file = await asyncio.to_thread(_create_qr, text, **payload)
        e = discord.Embed().set_image(url="attachment://qr.png")
        await ctx.reply(embed=e, file=file)

    @commands.command(name="minecraftstatus", aliases=["mcs", "mcstatus"])
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def mine_server_status(self, ctx: Context, address: str, bedrock: Annotated[bool | None, convert_bool] = False):
        """If you are minecraft fan, then you must be know about servers. Check server status with thi command."""
        if bedrock:
            link = f"https://api.mcsrvstat.us/bedrock/2/{address}"
        else:
            link = f"https://api.mcsrvstat.us/2/{address}"

        res = await self.bot.http_session.get(link)
        data = await res.json()
        try:
            if not data["online"]:
                return await ctx.reply(f"{ctx.author.mention} Server not online!")
            ip = data["ip"]
            port = data["port"]
            motd = "\n".join(data["motd"]["clean"])
            players_max = data["players"]["max"]
            players_onl = data["players"]["online"]
            version = data["version"]
            protocol = data["protocol"]
            hostname = data["hostname"]
        except KeyError:
            return await ctx.error(f"{ctx.author.mention} no server exists")

        embed = (
            discord.Embed(
                title="SERVER STATUS",
                description=f"IP: {ip}\n```\n{motd}\n```",
                timestamp=discord.utils.utcnow(),
                color=ctx.author.color,
            )
            .add_field(name="Hostname", value=hostname, inline=True)
            .add_field(name="Max Players", value=players_max, inline=True)
            .add_field(name="Player Online", value=players_onl, inline=True)
            .add_field(name="Protocol", value=protocol, inline=True)
            .add_field(name="Port", value=port, inline=True)
            .add_field(name="MC Version", value=version, inline=True)
            .set_footer(text=f"{ctx.author}")
        )

        await ctx.send(embed=embed)

    @commands.command()
    async def currencies(self, ctx: Context):
        """To see the currencies notations with names."""
        obj = await self.bot.http_session.get("https://api.coinbase.com/v2/currencies")
        data = await obj.json()
        entries = [f"`{temp['id']}` `{temp['name']}`" for temp in data["data"]]
        p = SimplePages(entries, ctx=ctx)
        await p.start()

    @commands.command()
    async def exchangerate(self, ctx: Context, currency: str):
        """To see the currencies notations with names."""
        if len(currency) != 3:
            return await ctx.send(f"{ctx.author.mention} please provide a **valid currency!**")
        obj = await self.bot.http_session.get(f"https://api.coinbase.com/v2/exchange-rates?currency={currency}")
        data: dict = await obj.json()

        entries = [f"`{i}` `{j}`" for i, j in data["data"]["rates"].items()]
        p = SimplePages(entries, ctx=ctx)
        await p.start()

    @commands.command()
    async def whatis(self, ctx: Context, *, query: str):
        """To get the meaning of the word."""
        query = query.lower()
        if data := await self.bot.dictionary.find_one({query: {"$exists": True}}):
            return await ctx.send(f"**{query.title()}**: {data[query]}")
        return await ctx.error("No word found, if you think its a mistake then contact the owner.")

    @commands.command(name="boxplot", aliases=("box", "boxwhisker", "numsetdata"))
    @Context.with_type
    async def _boxplot(self, ctx: Context, *numbers: float) -> None:
        """Plots the providednumber data set in a box & whisker plot
        showing Min, Max, Mean, Q1, Median and Q3.
        Numbers should be seperated by spaces per data point.
        """
        return await do_command(ctx, numbers, func=boxplot)

    @commands.command(name="plot", aliases=("line-graph", "graph"))
    @Context.with_type
    async def _plot(self, ctx: Context, *, equation: str) -> None:
        """Plots the provided equation out.
        Ex: `$plot 2x+1`.
        """
        try:
            return await do_command(ctx, equation, func=plotfn)
        except TypeError:
            await ctx.reply("Provided equation was invalid; the only variable present must be `x`")
        except (NameError, ValueError) as e:
            await ctx.reply(f"{ctx.author.mention} Provided equation was invalid; {e}")
        except (SyntaxError, sympy.SympifyError, ZeroDivisionError) as e:
            await ctx.reply(f"{ctx.author.mention} Provided equation was invalid; check your syntax.\nError: {e}")

    @commands.command(name="whispers", aliases=("whisper", "whisp"))
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def _whispers(self, ctx: Context) -> None:
        """Shows all the messages you got from whispers, once views it will be deleted."""
        collection = self.bot.user_collections_ind
        data = await collection.find_one({"_id": ctx.author.id, "whisper_messages": {"$exists": True}})
        if not data:
            await ctx.error(f"{ctx.author.mention} you don't have any whispers.")
            return

        if not data["whisper_messages"]:
            await ctx.error(f"{ctx.author.mention} you don't have any whispers.")
            return
        ls = []
        for message in data["whisper_messages"]:
            embed = discord.Embed(
                title="Whisper Message",
                description=f"""Server: **{self.bot.get_guild(message["guild_id"]) or 'Not Found'}** **[`This Message`](https://discord.com/channels/{message["guild_id"]}/{message["channel_id"]}/{message["message_id"]})**

**Message by {self.bot.get_user(message["author_id"]) or 'Not Found'}**:
{message["message"]}
""",
                color=discord.Color.blurple(),
                timestamp=message["created_at"],
            ).set_footer(text=f"Message ID: {message['message_id']} | Sent at")
            ls.append(embed)

        view = PaginationView(ls)
        view.ctx = ctx

        class V(ParrotView):
            @discord.ui.button(label="Delete", style=discord.ButtonStyle.red)
            async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.defer()
                await self.message.delete()
                await collection.update_one({"_id": ctx.author.id}, {"$set": {"whisper_messages": []}})

            @discord.ui.button(label="Show", style=discord.ButtonStyle.green)
            async def show(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.defer()
                await interaction.followup.send(embed=ls[0], view=view, ephemeral=True)

        main_view = V(timeout=10, ctx=ctx)
        main_view.message = await ctx.send(
            "Click `Show` to view your Whispers\nClick `Delete` to delete all your whispers",
            view=main_view,
        )

    @commands.command(name="timezone", aliases=["tz", "mytimezone", "mytz"])
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def _timezone(self, ctx: Context, *, tz: str | None = None):
        """Shows your current timezone, or sets a new one.
        Ex: `$timezone America/New_York`.
        """
        timestamp_r_utc = discord.utils.format_dt(arrow.utcnow().datetime, "R")
        timestamp_f_utc = discord.utils.format_dt(arrow.utcnow().datetime, "f")
        if not tz:
            timezone = await self.bot.get_user_timezone(ctx.author.id)
            now = arrow.utcnow().to(timezone).datetime
            timestamp_r = discord.utils.format_dt(now, "R")
            timestamp_f = discord.utils.format_dt(now, "f")

            await ctx.send(
                embed=discord.Embed(
                    description=f"""
## UTC
- Relative: {timestamp_r_utc}
- Full: {timestamp_f_utc}

## Your Timezone `{timezone}`
- Relative: {timestamp_r}
- Full: {timestamp_f}""",
                ),
            )
            return

        try:
            arrow.utcnow().to(tz).datetime.timestamp()  # noqa: B018
        except (ValueError, arrow.parser.ParserError):
            tz = self.get_timezone(tz)

        await self.bot.set_user_timezone(ctx.author.id, tz)
        await ctx.reply(f"{ctx.author.mention} Set your timezone to `{tz}`")

    def get_timezone(self, tz: str) -> str:
        if "/" in tz:
            result, score, position = process.extractOne(tz, self.valid_timezones)
            if score < 80:
                msg = f"{tz} is not a valid timezone."
                raise commands.BadArgument(msg)
            return result
        result, score, position = process.extractOne(tz, self._timezone_aliases.keys())
        if score < 80:
            msg = f"{tz} is not a valid timezone."
            raise commands.BadArgument(msg)
        return self._timezone_aliases[result]

    @commands.command(name="pings", aliases=["mypings", "myping"])
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def _pings(self, ctx: Context, ghost_pings: Annotated[bool, convert_bool] = True):
        """Shows your current mentions in which bot has much servers."""
        cog: PingMessageListner = self.bot.PingMessageListner
        if cog is None:
            return await ctx.error(f"{ctx.author.mention} Ping cog is not loaded!")

        page = commands.Paginator(prefix="", suffix="", max_size=1000)
        if ghost_pings:
            __pings = cog.get_ghost_pings(ctx.author.id)
        else:
            __pings = cog.get_pings(ctx.author.id)

        for message in __pings:
            guild_name = message.guild.name if message.guild else "DM"
            jump_url = message.jump_url if message.guild else ""
            human_timestamp = discord.utils.format_dt(message.created_at, "R")

            content = message.clean_content or "No content"
            content = f"{content[:256]}..." if len(content) > 256 else content

            page.add_line(f"**{human_timestamp} @ {guild_name}** -> [{content}]({jump_url})")

        if not page.pages:
            return await ctx.error(f"{ctx.author.mention} no pings!")

        interface = PaginatorEmbedInterface(ctx.bot, page, owner=ctx.author)
        await interface.send_to(ctx)
