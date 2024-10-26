import traceback

from discord.ext import commands


class Errors(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context[commands.Bot], exc: commands.CommandError) -> None:
        if ctx.command and ctx.command.has_error_handler() or ctx.cog and ctx.cog.has_error_handler():
            return

        ignored_errors = (commands.CommandNotFound,)
        if isinstance(exc, ignored_errors):
            return

        assert ctx.command is not None
        if isinstance(exc, commands.CommandInvokeError):
            err = exc.original

            lines = traceback.format_exception(type(err), err, err.__traceback__)
            tb = "".join(lines)

            if len(tb) > 1700:
                length = len(tb) - 1700
                tb = f"```\n{tb[:1700]}```\n{length} characters omitted..."

            await ctx.send(f"An error occurred in ``{ctx.command.name}``: {tb}")
        else:
            await ctx.send(f"{exc}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Errors(bot))
