from __future__ import annotations

from core import Parrot

from .cc import CustomCommand


async def setup(bot: Parrot) -> None:
    await bot.add_cog(CustomCommand(bot))
