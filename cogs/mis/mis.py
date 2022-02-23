from __future__ import annotations
import hashlib

from cogs.meta.robopage import SimplePages

from discord.ext import commands
from discord import Embed

import urllib.parse
import aiohttp
import discord
import re
import datetime
import typing
import os
import inspect
import json
from pathlib import Path
import io
import string
from html import unescape

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import (
    RoundedModuleDrawer,
    CircleModuleDrawer,
    GappedSquareModuleDrawer,
    HorizontalBarsDrawer,
    SquareModuleDrawer,
    VerticalBarsDrawer,
)
from qrcode.image.styles.colormasks import (
    RadialGradiantColorMask,
    SquareGradiantColorMask,
    HorizontalGradiantColorMask,
    VerticalGradiantColorMask,
    ImageColorMask,
    SolidFillColorMask,
)

from core import Parrot, Context, Cog

from utilities.youtube_search import YoutubeSearch
from utilities.converters import ToAsync, convert_bool
from utilities.paginator import PaginationView
from utilities.ttg import Truths

from PIL import Image


invitere = r"(?:https?:\/\/)?discord(?:\.gg|app\.com\/invite)?\/(?:#\/)([a-zA-Z0-9-]*)"
invitere2 = r"(http[s]?:\/\/)*discord((app\.com\/invite)|(\.gg))\/(invite\/)?(#\/)?([A-Za-z0-9\-]+)(\/)?"

google_key = os.environ["GOOGLE_KEY"]
cx = os.environ["GOOGLE_CX"]

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
    "https://upload.wikimedia.org/wikipedia/en/thumb/8/80/Wikipedia-logo-v2.svg"
    "/330px-Wikipedia-logo-v2.svg.png"
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


class TTFlag(commands.FlagConverter, case_insensitive=True, prefix="--", delimiter=" "):
    var: str
    con: str
    ints: convert_bool = False
    ascending: convert_bool = True
    table_format: str = "psql"
    align: str = "center"
    valuation: convert_bool = False
    latex: convert_bool = False


def _prepare_input(text: str) -> str:
    if match := FORMATTED_CODE_REGEX.match(text):
        return match.group("code")
    return text


def _process_image(data: bytes, out_file: typing.BinaryIO) -> None:
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    width, height = image.size
    background = Image.new("RGBA", (width + 2 * PAD, height + 2 * PAD), "WHITE")
    background.paste(image, (PAD, PAD), image)
    background.save(out_file)


class InvalidLatexError(Exception):
    """Represents an error caused by invalid latex."""

    def __init__(self, logs: str):
        super().__init__(logs)
        self.logs = logs


@ToAsync()
def _create_qr(
    text: str,
    *,
    version: typing.Optional[int] = 1,
    board_size: typing.Optional[int] = 10,
    border: typing.Optional[int] = 4,
    **kw,
) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=board_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white", **kw)
    _timestamp = int(datetime.datetime.utcnow().timestamp())  # float float
    img.save(f"temp/{_timestamp}.png")
    return f"temp/{_timestamp}.png"


class QRCodeFlags(
    commands.FlagConverter, case_insensitive=True, prefix="--", delimiter=" "
):
    board_size: typing.Optional[int] = 10
    border: typing.Optional[int] = 4
    module_drawer: typing.Optional[str] = None
    color_mask: typing.Optional[str] = None


qr_modular = {
    "square": SquareModuleDrawer(),
    "gapped": GappedSquareModuleDrawer(),
    "circle": CircleModuleDrawer(),
    "round": RoundedModuleDrawer(),
    "vertical": VerticalBarsDrawer(),
    "ver": VerticalBarsDrawer(),
    "horizontal": HorizontalBarsDrawer(),
    "hori": HorizontalBarsDrawer(),
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
    """Those commands which can't be listed"""

    def __init__(self, bot: Parrot):
        self.bot = bot
        self.snipes = {}

        @bot.listen("on_message_delete")
        async def on_message_delete(msg):
            if msg.author.bot:
                return
            self.snipes[msg.channel.id] = msg

        @bot.listen("on_message_edit")
        async def on_message_edit(before, after):
            if before.author.bot or after.author.bot:
                return
            if before.content != after.content:
                self.snipes[before.channel.id] = [before, after]

    async def wiki_request(
        self, channel: discord.TextChannel, search: str
    ) -> typing.List[str]:
        """Search wikipedia search string and return formatted first 10 pages found."""
        params = {**WIKI_PARAMS, **{"srlimit": 10, "srsearch": search}}
        async with self.bot.http_session.get(url=SEARCH_API, params=params) as resp:
            if resp.status != 200:
                raise commands.BadArgument(f"Wikipedia API {resp.status}")

            raw_data = await resp.json()

            if not raw_data.get("query"):
                raise commands.BadArgument(
                    f"Wikipedia API: {resp.status} {raw_data.get('errors')}"
                )

            lines = []
            if raw_data["query"]["searchinfo"]["totalhits"]:
                for article in raw_data["query"]["search"]:
                    line = WIKI_SEARCH_RESULT.format(
                        name=article["title"],
                        description=unescape(
                            re.sub(WIKI_SNIPPET_REGEX, "", article["snippet"])
                        ),
                        url=f"https://en.wikipedia.org/?curid={article['pageid']}",
                    )
                    lines.append(line)

            return lines

    def sanitise(self, string):
        if len(string) > 1024:
            string = string[0:1021] + "..."
        string = re.sub(invitere2, "[INVITE REDACTED]", string)
        return string

    async def _generate_image(self, query: str, out_file: typing.BinaryIO) -> None:
        """Make an API request and save the generated image to cache."""
        payload = {"code": query, "format": "png"}
        async with self.bot.http_session.post(
            LATEX_API_URL, data=payload, raise_for_status=True
        ) as response:
            response_json = await response.json()
        if response_json["status"] != "success":
            raise InvalidLatexError(logs=response_json["log"])
        async with self.bot.http_session.get(
            f"{LATEX_API_URL}/{response_json['filename']}", raise_for_status=True
        ) as response:
            _process_image(await response.read(), out_file)

    async def _upload_to_pastebin(
        self, text: str, lang: str = "txt"
    ) -> typing.Optional[str]:
        """Uploads `text` to the paste service, returning the url if successful."""
        async with aiohttp.ClientSession() as aioclient:
            post = await aioclient.post("https://hastebin.com/documents", data=text)
            if post.status == 200:
                response = await post.text()
                return f"https://hastebin.com/{response[8:-2]}"

            # Rollback bin
            post = await aioclient.post(
                "https://bin.readthedocs.fr/new", data={"code": text, "lang": lang}
            )
            if post.status == 200:
                return str(post.url)

    @commands.command()
    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    async def latex(self, ctx: commands.Context, *, query: str) -> None:
        """Renders the text in latex and sends the image."""
        query = _prepare_input(query)
        query_hash = hashlib.md5(query.encode()).hexdigest()
        image_path = CACHE_DIRECTORY / f"{query_hash}.png"
        async with ctx.typing():
            if not image_path.exists():
                try:
                    with open(image_path, "wb") as out_file:
                        await self._generate_image(
                            TEMPLATE.substitute(text=query), out_file
                        )
                except InvalidLatexError as err:
                    logs_paste_url = await self._upload_to_pastebin(err.logs)
                    embed = discord.Embed(title="Failed to render input.")
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

    @commands.command(aliases=["bigemote"])
    @commands.has_permissions(embed_links=True)
    @commands.bot_has_permissions(
        embed_links=True,
    )
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def bigemoji(self, ctx: Context, *, emoji: discord.Emoji):
        """To view the emoji in bigger form"""
        await ctx.reply(emoji.url)

    @commands.command(aliases=["calc", "cal"])
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def calculator(self, ctx: Context, *, text: str):
        """This is basic calculator with all the expression supported. Syntax is similar to python math module"""
        new_text = urllib.parse.quote(text)
        link = "http://twitch.center/customapi/math?expr=" + new_text

        async with aiohttp.ClientSession() as session:
            async with session.get(link) as r:
                if r.status == 200:
                    res = await r.text()
                else:
                    return
        embed = discord.Embed(
            title="Calculated!!",
            description=f"```ini\n[Answer is: {res}]```",
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_footer(text=f"{ctx.author.name}")

        await ctx.reply(embed=embed)

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def firstmessage(self, ctx: Context, *, channel: discord.TextChannel = None):
        """To get the first message of the specified channel"""
        channel = channel or ctx.channel
        async for msg in channel.history(limit=1, oldest_first=True):
            return await ctx.send(
                embed=discord.Embed(
                    title=f"First message in {channel.name}",
                    url=msg.jump_url,
                    description=f"{msg.content}",  # fuck you pycord
                    timestamp=datetime.datetime.utcnow(),
                ).set_footer(text=f"Message sent by {msg.author}")
            )

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def maths(self, ctx: Context, operation: str, *, expression: str):
        """Another calculator but quite advance one

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
        link = f"https://newton.now.sh/api/v2/{operation}/{new_expression}"
        async with aiohttp.ClientSession() as session:
            async with session.get(link) as r:
                if r.status == 200:
                    res = await r.json()
                else:
                    return await ctx.reply(
                        f"{ctx.author.mention} invalid **{expression}** or either **{operation}**"
                    )
        result = res["result"]
        embed = discord.Embed(
            title="Calculated!!",
            description=f"```ini\n[Answer is: {result}]```",
            timestamp=datetime.datetime.utcnow(),
        )
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.cooldown(1, 60, commands.BucketType.member)
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def news(self, ctx: Context, nat: str):
        """This command will fetch the latest news from all over the world."""
        key = os.environ["NEWSKEY"]

        link = "http://newsapi.org/v2/top-headlines?country=" + nat + "&apiKey=" + key
        async with aiohttp.ClientSession() as session:
            async with session.get(link) as r:
                if r.status == 200:
                    res = await r.json()

        if res["totalResults"] == 0:
            return await ctx.reply(
                f"{ctx.author.mention} **{nat}** is nothing, please provide a valid country code."
            )
        em_list = []
        for data in range(0, len(res["articles"])):

            source = res["articles"][data]["source"]["name"]
            # url = res['articles'][data]['url']
            author = res["articles"][data]["author"]
            title = res["articles"][data]["title"]
            description = res["articles"][data]["description"]
            img = res["articles"][data]["urlToImage"]
            content = res["articles"][data]["content"]
            if not content:
                content = "N/A"
            # publish = res['articles'][data]['publishedAt']

            embed = Embed(
                title=f"{title}",
                description=f"{description}",
                timestamp=datetime.datetime.utcnow(),
            )
            embed.add_field(name=f"{source}", value=f"{content}")
            embed.set_image(url=f"{img}")
            embed.set_author(name=f"{author}")
            embed.set_footer(text=f"{ctx.author}")
            em_list.append(embed)

        # paginator = Paginator(pages=em_list, timeout=60.0)
        # await paginator.start(ctx)
        await PaginationView(em_list).start(ctx=ctx)

    @commands.command(name="search", aliases=["googlesearch", "google"])
    @commands.cooldown(1, 60, commands.BucketType.member)
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def search(self, ctx: Context, *, search: str):
        """Simple google search Engine"""
        search = urllib.parse.quote(search)

        url = f"https://www.googleapis.com/customsearch/v1?key={google_key}&cx={cx}&q={search}"
        response = await self.bot.session.get(url)
        if response.status == 200:
            json_ = await response.json()
        else:
            return await ctx.reply(
                f"{ctx.author.mention} No results found.```\n{search}```"
            )

        pages = []

        for item in json_["items"]:
            title = item["title"]
            link = item["link"]
            snippet = item.get("snippet")

            pages.append(
                f"""**[Title: {title}]({link})**
>>> {snippet}
"""
            )
        page = SimplePages(entries=pages, ctx=ctx, per_page=3)
        await page.start()

    @commands.command()
    @commands.bot_has_permissions(read_message_history=True, embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def snipe(self, ctx: Context):
        """Snipes someone's message that's deleted"""
        snipe = self.snipes.get(ctx.channel.id)
        if snipe is None:
            return await ctx.reply(f"{ctx.author.mention} no snipes in this channel!")
        # there's gonna be a snipe after this point
        emb = discord.Embed()
        if type(snipe) is list:  # edit snipe
            emb.set_author(
                name=str(snipe[0].author), icon_url=snipe[0].author.display_avatar.url
            )
            emb.colour = snipe[0].author.colour
            emb.add_field(
                name="Before", value=self.sanitise(snipe[0].content), inline=False
            )
            emb.add_field(
                name="After", value=self.sanitise(snipe[1].content), inline=False
            )
            emb.timestamp = snipe[0].created_at
        else:  # delete snipe
            emb.set_author(
                name=str(snipe.author), icon_url=snipe.author.display_avatar.url
            )
            emb.description = f"{self.sanitise(snipe.content)}"  # fuck you pycord
            emb.colour = snipe.author.colour
            emb.timestamp = snipe.created_at
            emb.set_footer(
                text=f"Message sniped by {str(ctx.author)}",
                icon_url=ctx.author.display_avatar.url,
            )
        await ctx.reply(embed=emb)
        self.snipes[ctx.channel.id] = None

    @commands.command(
        aliases=["trutht", "tt", "ttable"],
    )
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def truthtable(self, ctx: Context, *, flags: TTFlag):
        """A simple command to generate Truth Table of given data. Make sure you use proper syntax.
        (Example: `tt --var a, b --con a and b, a or b`)
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
        """
        table = Truths(
            flags.var.replace(" ", "").split(","),
            flags.con.split(","),
            ints=flags.ints,
            ascending=flags.ascending,
        )
        main = table.as_tabulate(
            index=False, table_format=flags.table_format, align=flags.align
        )
        await ctx.reply(f"```{flags.table_format}\n{main}\n```")

    @commands.command(aliases=["w"])
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def weather(self, ctx: Context, *, location: str):
        """Weather API, for current weather forecast, supports almost every city."""
        appid = os.environ["WEATHERID"]

        loc = urllib.parse.quote(location)
        link = (
            "https://api.openweathermap.org/data/2.5/weather?q="
            + loc
            + "&appid="
            + appid
        )

        loc = loc.capitalize()
        async with aiohttp.ClientSession() as session:
            async with session.get(link) as r:
                if r.status == 200:
                    res = await r.json()
                else:
                    return await ctx.reply(
                        f"{ctx.author.mention} no location named, **{location}**"
                    )

        lat = res["coord"]["lat"]
        lon = res["coord"]["lon"]

        weather = res["weather"][0]["main"]

        max_temp = res["main"]["temp_max"] - 273.5
        min_temp = res["main"]["temp_min"] - 273.5

        press = res["main"]["pressure"] / 1000

        humidity = res["main"]["humidity"]

        visiblity = res["visibility"]
        wind_speed = res["wind"]["speed"]

        loc_id = res["id"]
        country = res["sys"]["country"]

        embed = discord.Embed(
            title=f"Weather Menu of: {location}",
            description=f"Weather: {weather}",
            timestamp=datetime.datetime.utcnow(),
        )
        embed.add_field(name="Latitude", value=f"{lat} Deg", inline=True)
        embed.add_field(name="Longitude", value=f"{lon} Deg", inline=True)
        embed.add_field(name="Humidity", value=f"{humidity} g/m³", inline=True)
        embed.add_field(
            name="Maximum Temperature", value=f"{round(max_temp)} C Deg", inline=True
        )
        embed.add_field(
            name="Minimum Temperature", value=f"{round(min_temp)} C Deg", inline=True
        )
        embed.add_field(name="Pressure", value=f"{press} Pascal", inline=True)

        embed.add_field(name="Visibility", value=f"{visiblity} m", inline=True)
        embed.add_field(name="Wind Speed", value=f"{wind_speed} m/s", inline=True)
        embed.add_field(name="Country", value=f"{country}", inline=True)
        embed.add_field(name="Loaction ID", value=f"{location}: {loc_id}", inline=True)
        embed.set_footer(text=f"{ctx.author.name}")

        await ctx.reply(embed=embed)

    @commands.command(aliases=["wiki"])
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def wikipedia(self, ctx: Context, *, search: str):
        """Web articles from Wikipedia."""
        contents = await self.wiki_request(ctx.channel, search)

        if contents:
            embed = Embed(title="Wikipedia Search Results", colour=ctx.author.color)
            embed.set_thumbnail(url=WIKI_THUMBNAIL)
            embed.timestamp = datetime.datetime.utcnow()
            page = SimplePages(entries=contents, ctx=ctx, per_page=3)
            await page.start()
        else:
            await ctx.send(
                "Sorry, we could not find a wikipedia article using that search term."
            )

    @commands.command(aliases=["yt"])
    @commands.bot_has_permissions(embed_links=True)
    @commands.is_nsfw()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def youtube(
        self, ctx: Context, limit: typing.Optional[int] = None, *, query: str
    ):
        """Search for videos on YouTube"""
        results = await YoutubeSearch(query, max_results=limit or 5).to_json()
        main = json.loads(results)

        em_list = []

        for i in range(0, len(main["videos"])):
            _1_title = main["videos"][i]["title"]
            _1_descr = main["videos"][i]["long_desc"]
            _1_chann = main["videos"][i]["channel"]
            _1_views = main["videos"][i]["views"]
            _1_urlsu = "https://www.youtube.com" + str(main["videos"][i]["url_suffix"])
            _1_durat = main["videos"][i]["duration"]
            _1_thunb = str(main["videos"][i]["thumbnails"][0])
            embed = discord.Embed(
                title=f"YouTube search results: {query}",
                description=f"{_1_urlsu}",
                colour=discord.Colour.red(),
                url=_1_urlsu,
            )
            embed.add_field(
                name=f"Video title:`{_1_title}`\n",
                value=f"Channel:```\n{_1_chann}\n```\nDescription:```\n{_1_descr}\n```\nViews:```\n{_1_views}\n```\nDuration:```\n{_1_durat}\n```",
                inline=False,
            )
            embed.set_thumbnail(
                url="https://cdn4.iconfinder.com/data/icons/social-messaging-ui-color-shapes-2-free/128/social"
                "-youtube-circle-512.png"
            )
            embed.set_image(url=f"{_1_thunb}")
            embed.set_footer(text=f"{ctx.author.name}")
            em_list.append(embed)

        # paginator = Paginator(pages=em_list, timeout=60.0)
        # await paginator.start(ctx)
        await PaginationView(em_list).start(ctx=ctx)

    @commands.command()
    @commands.has_permissions(embed_links=True)
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def embed(
        self,
        ctx: Context,
        channel: typing.Optional[discord.TextChannel] = None,
        *,
        data: typing.Union[dict, str] = None,
    ):
        """A nice command to make custom embeds, from `JSON`. Provided it is in the format that Discord expects it to be in.
        You can find the documentation on `https://discord.com/developers/docs/resources/channel#embed-object`."""
        channel = channel or ctx.channel
        if channel.permissions_for(ctx.author).embed_links:
            if not data:
                return await self.bot.invoke_help_command(ctx)
            try:
                data = json.loads(data)
                await channel.send(embed=discord.Embed.from_dict(data))
            except Exception as e:
                await ctx.reply(
                    f"{ctx.author.mention} you didn't provide the proper json object. Error raised: {e}"
                )
        else:
            await ctx.reply(
                f"{ctx.author.mention} you don't have Embed Links permission in {channel.mention}"
            )

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def snowflakeid(
        self,
        ctx: Context,
        *,
        target: typing.Union[
            discord.User,
            discord.Member,
            discord.Role,
            discord.Thread,
            discord.TextChannel,
            discord.VoiceChannel,
            discord.StageChannel,
            discord.Guild,
            discord.Emoji,
            discord.Invite,
            discord.Template,
            discord.CategoryChannel,
            discord.DMChannel,
            discord.GroupChannel,
        ],
    ):
        """To get the ID of discord models"""
        embed = discord.Embed(
            title="Snowflake lookup",
            color=ctx.author.color,
            timestamp=datetime.datetime.utcnow(),
        )
        embed.add_field(
            name="Type", value=f"`{target.__class__.__name__}`", inline=True
        )
        embed.add_field(
            name="Created At",
            value=f"<t:{int(target.created_at.timestamp())}>",
            inline=True,
        )
        embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def snowflaketime(self, ctx: Context, snowflake1: int, snowflake2: int):
        """Get the time difference in seconds, between two discord SnowFlakes"""
        first = discord.utils.snowflake_time(snowflake1)
        second = discord.utils.snowflake_time(snowflake2)

        if snowflake2 > snowflake1:
            timedelta = second - first
        else:
            timedelta = first - second

        await ctx.reply(
            f"{ctx.author.mention} total seconds between **{snowflake1}** and **{snowflake2}** is **{timedelta.total_seconds()}**"
        )

    @commands.command(aliases=["src"])
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def source(self, ctx: Context, *, command: str = None):
        """Displays my full source code or for a specific command."""
        source_url = self.bot.github
        branch = "main"
        if command is None:
            return await ctx.reply(source_url)

        if command == "help":
            src = type(self.bot.help_command)
            module = src.__module__

        else:
            obj = self.bot.get_command(command.replace(".", " "))
            if obj is None:
                return await ctx.reply("Could not find command.")
            src = obj.callback.__code__
            module = obj.callback.__module__

        lines, firstlineno = inspect.getsourcelines(src)

        location = module.replace(".", "/") + ".py"

        final_url = f"<{source_url}/blob/{branch}/{location}#L{firstlineno}-L{firstlineno + len(lines) - 1}>"
        await ctx.reply(final_url)

    @commands.group()
    @commands.has_permissions(embed_links=True, add_reactions=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def poll(
        self,
        ctx: Context,
    ):
        """To make polls. Thanks to Strawpoll API"""
        await self.bot.invoke_help_command(ctx)

    @poll.command(name="create")
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def create_poll(self, ctx: Context, question: str, *, options: str):
        """To create a poll, options should be seperated by commas"""
        parrot_db = self.bot.mongo["parrot_db"]
        collection = parrot_db["poll"]
        BASE_URL = "https://strawpoll.com/api/poll/"
        options = options.split(",")
        data = {"poll": {"title": question, "answers": options, "only_reg": True}}
        if len(options) > 10:
            return await ctx.reply(
                f"{ctx.author.mention} can not provide more than 10 options"
            )
        async with aiohttp.ClientSession() as session:
            poll = await session.post(
                BASE_URL, json=data, headers={"API-KEY": os.environ["STRAW_POLL"]}
            )

        data = await poll.json()
        _exists = await collection.find_one_and_update(
            {"_id": ctx.author.id}, {"$set": {"content_id": data["content_id"]}}
        )

        if not _exists:
            await collection.insert_one(
                {"_id": ctx.author.id, "content_id": data["content_id"]}
            )

        msg = await ctx.reply(
            f"Poll created: <https://strawpoll.com/{data['content_id']}>"
        )
        await msg.reply(
            f"{ctx.author.mention} your poll content id is: {data['content_id']}"
        )

    @poll.command(name="get")
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def get_poll(self, ctx: Context, content_id: str):
        """To get the poll data"""
        URL = f"https://strawpoll.com/api/poll/{content_id}"

        async with aiohttp.ClientSession() as session:
            poll = await session.get(URL, headers={"API-KEY": os.environ["STRAW_POLL"]})
        try:
            data = await poll.json()
        except json.decoder.JSONDecodeError:
            return
        except aiohttp.client_exceptions.ContentTypeError:
            return
        embed = discord.Embed(
            title=data["content"]["poll"]["title"],
            description=f"Total Options: {len(data['content']['poll']['poll_answers'])} | Total Votes: {data['content']['poll']['total_votes']}",
            timestamp=datetime.datetime.utcnow(),
            color=ctx.author.color,
        )
        for temp in data["content"]["poll"]["poll_answers"]:
            embed.add_field(
                name=temp["answer"], value=f"Votes: **{temp['votes']}**", inline=True
            )
        embed.set_footer(text=f"{ctx.author}")
        await ctx.reply(embed=embed)

    @poll.command(name="delete")
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def delete_poll(self, ctx: Context, content_id: str):
        """To delete the poll. Only if it's yours"""
        parrot_db = self.bot.mongo["parrot_db"]
        collection = parrot_db["poll"]
        _exists = await collection.find_one({"_id": ctx.author.id})
        if not _exists:
            return
        URL = "https://strawpoll.com/api/content/delete"
        async with aiohttp.ClientSession() as session:
            await session.delete(
                URL,
                data={"content_id": content_id},
                headers={"API-KEY": os.environ["STRAW_POLL"]},
            )
        await ctx.reply(f"{ctx.author.mention} deleted")

    @commands.command(name="orc")
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def ocr(self, ctx: Context, *, link: str = None):
        """To convert image to text"""
        link = link or ctx.message.attachments[0].url
        if not link:
            await ctx.reply(f"{ctx.author.mention} must provide the link")
        try:
            async with aiohttp.ClientSession() as session:
                res = await session.get(link)
        except Exception as e:
            return await ctx.reply(
                f"{ctx.author.mention} something not right. Error raised {e}"
            )
        else:
            json = await res.json()
        if str(json["status"]) != str(200):
            return await ctx.reply(f"{ctx.author.mention} something not right.")
        msg = json["message"][:2000:]
        await ctx.reply(
            embed=discord.Embed(
                description=msg,
                color=ctx.author.color,
                timestamp=datetime.datetime.utcnow(),
            ).set_footer(text=f"{ctx.author}")
        )

    @commands.command(name="qr", aliases=["createqr", "cqr"])
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def qrcode(self, ctx: Context, text: str, *, flags: QRCodeFlags):
        """To generate the QR from the given Text"""
        payload = {}
        if flags.module_drawer:
            payload["module_drawer"] = qr_modular.get(flags.module_drawer)
        if flags.color_mask:
            payload["color_mask"] = qr_modular.get(flags.color_mask)

        if payload:
            payload["image_factory"] = StyledPilImage
        payload["board_size"] = flags.board_size
        payload["border"] = flags.border
        path = await _create_qr(text, **payload)
        f = discord.File(path, filename="name.png")
        e = discord.Embed().set_image(url="attachment://name.png")
        await ctx.reply(embed=e, file=f)

    @commands.command(name="minecraftstatus", aliases=["mcs", "mcstatus"])
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    @Context.with_type
    async def mine_server_status(
        self, ctx: Context, address: str, bedrock: typing.Optional[convert_bool] = False
    ):
        """If you are minecraft fan, then you must be know about servers. Check server status with thi command"""
        if bedrock:
            link = f"https://api.mcsrvstat.us/bedrock/2/{address}"
        else:
            link = f"https://api.mcsrvstat.us/2/{address}"

        async with aiohttp.ClientSession() as session:
            res = await session.get(link)
            data = await res.json()
        try:
            if data["online"]:
                ip = data["ip"]
                port = data["port"]
                motd = "\n".join(data["motd"]["clean"])
                players_max = data["players"]["max"]
                players_onl = data["players"]["online"]
                version = data["version"]
                protocol = data["protocol"]
                hostname = data["hostname"]
        except KeyError:
            return await ctx.reply(f"{ctx.author.mention} no server exists")

        embed = discord.Embed(
            title="SERVER STATUS",
            description=f"IP: {ip}\n```\n{motd}\n```",
            timestamp=datetime.datetime.utcnow(),
            color=ctx.author.color,
        )
        embed.add_field(name="Hostname", value=hostname, inline=True)
        embed.add_field(name="Max Players", value=players_max, inline=True)
        embed.add_field(name="Player Online", value=players_onl, inline=True)
        embed.add_field(name="Protocol", value=protocol, inline=True)
        embed.add_field(name="Port", value=port, inline=True)
        embed.add_field(name="MC Version", value=version, inline=True)

        embed.set_footer(text=f"{ctx.author}")

        await ctx.send(embed=embed)

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    async def currencies(self, ctx: Context):
        """To see the currencies notations with names"""
        obj = await self.bot.session.get("https://api.coinbase.com/v2/currencies")
        data = await obj.json()
        entries = [f"`{temp['id']}` `{temp['name']}`" for temp in data["data"]]
        p = SimplePages(entries, ctx=ctx)
        await p.start()

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    async def exchangerate(self, ctx: Context, currency: str):
        """To see the currencies notations with names"""
        if len(currency) != 3:
            return await ctx.send(
                f"{ctx.author.mention} please provide a **valid currency!**"
            )
        obj = await self.bot.session.get(
            f"https://api.coinbase.com/v2/exchange-rates?currency={currency}"
        )
        data: dict = await obj.json()

        entries = [f"`{i}` `{j}`" for i, j in data["data"]["rates"].items()]
        p = SimplePages(entries, ctx=ctx)
        await p.start()
