import asyncio
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import discord
import pyszuru
import yarl
from discord import app_commands
from discord.ext import commands
from jishaku.functools import executor_function

import config

URL_REGEX = re.compile(
    r"(https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|www\.[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9]+\.[^\s]{2,}|www\.[a-zA-Z0-9]+\.[^\s]{2,})"
)


class URLSubmitModal(discord.ui.Modal, title="Booru Submit"):
    urls = discord.ui.TextInput(label="URLs", style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction[commands.Bot]) -> None:
        await interaction.response.defer()


class Booru(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.szuru = pyszuru.API(config.booru_url, username=config.booru_username, token=config.booru_token)
        self.booru_add_context = app_commands.ContextMenu(
            name="Upload to booru", callback=self.booru_from_url_context, guild_ids=config.guilds
        )
        self.bot.tree.add_command(self.booru_add_context)

    @executor_function
    def get_or_create_tag(self, tag: str) -> pyszuru.Tag:
        try:
            t = self.szuru.getTag(tag)
        except pyszuru.SzurubooruHTTPError:
            t = self.szuru.createTag(tag)

        return t

    async def get_gallery_from_url(self, url: str, *args) -> list[str]:
        command = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "gallery_dl",
            url,
            "--write-metadata",
            "-D",
            "./tmp",
            *args,
            stdout=subprocess.PIPE,
        )
        (stdout, _) = await command.communicate()

        if command.returncode != 0:
            raise Exception(f"There was an error when communicating with gallery-dl: {stdout.decode()}")

        return [line.lstrip("# ") for line in stdout.decode().splitlines()]

    async def upload_file(self, path: Path, url: str) -> pyszuru.Post:
        with path.open("rb") as fp:
            file_token = await asyncio.to_thread(self.szuru.upload_file, fp)

        try:
            post = await asyncio.to_thread(self.szuru.createPost, file_token, "safe")
        except pyszuru.SzurubooruHTTPError as e:
            raise Exception(f"Szurubooru API error: ``{e}``") from e

        jsonpath = path.with_suffix(path.suffix + ".json")
        with open(jsonpath) as fp:
            metadata = json.load(fp)

        tags = []
        hashtags = metadata.get("hashtags")
        if hashtags:
            tags += hashtags

        author = metadata["author"]["name"]  # i believe this should always exist.
        tags.append(author)

        post.tags = [await self.get_or_create_tag(tag) for tag in tags]
        post.source = [url]
        await asyncio.to_thread(post.push)

        return post

    async def booru_from_url_context(self, interaction: discord.Interaction, message: discord.Message):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("You are not the owner of this bot!", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)

        matches = URL_REGEX.findall(message.content)
        if not matches:
            await interaction.followup.send("No urls detected in this message.")
            return

        paths: list[tuple[str, str]] = []

        for match in matches:
            url = str(yarl.URL(match.rstrip(">")).with_query(None))
            paths += [(i, url) for i in await self.get_gallery_from_url(url)]

        if not paths:
            await interaction.followup.send("No paths given by gallery-dl?")
            return

        posts: list[pyszuru.Post] = []

        for path, url in paths:
            realpath = Path(path)

            posts.append(await self.upload_file(realpath, url))

        joined = "\n".join(f"{config.booru_url}/post/{p.id_}" for p in posts)
        await interaction.followup.send(f"Returned posts: {joined or 'None'}", ephemeral=True)

        await asyncio.to_thread(shutil.rmtree, "./tmp")  # clean up

    @commands.hybrid_group()
    async def booru(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @booru.command()
    @commands.is_owner()
    async def add(self, ctx: commands.Context, strip_query: bool | None = True, *, links: str | None = None):
        if links is None and ctx.interaction:
            modal = URLSubmitModal()
            await ctx.interaction.response.send_modal(modal)

            completed = await modal.wait()
            if not completed:
                url = modal.urls.value
            else:
                return await ctx.send("Submit modal cancelled...")
        elif links is None and not ctx.interaction:
            return await ctx.send("Links must be filled out if this is not an interaction.")
        else:
            await ctx.defer()
            url: str = links  # type: ignore

        urls = url.split(",") if "," in url else [url]

        paths: list[tuple[str, str]] = []

        for url in urls:
            url = url.lstrip("<").rstrip(">")
            if strip_query:
                url = str(yarl.URL(url).with_query(None))

            paths += [(i, url) for i in await self.get_gallery_from_url(url)]

        if not paths:
            await ctx.send("No paths given by gallery-dl?")
            return

        posts: list[pyszuru.Post] = []

        for path, url in paths:
            realpath = Path(path)

            posts.append(await self.upload_file(realpath, url))

        joined = "\n".join(f"{config.booru_url}/post/{p.id_}" for p in posts)
        await ctx.send(f"Returned posts: {joined or 'None'}")

        await asyncio.to_thread(shutil.rmtree, "./tmp")  # clean up

    @commands.hybrid_command(name="bookmarks")
    async def import_from_twitter_bookmarks(self, ctx: commands.Context, limit: int = 5):
        if not Path("./cookies.txt").exists():
            await ctx.send("File ``cookies.txt`` does not exist. Fill this out with twitter cookies")
            return

        paths: list[str] = await self.get_gallery_from_url(
            "https://twitter.com/i/bookmarks", "-C", "./cookies.txt", "--range", f"0-{limit}"
        )
        posts: list[pyszuru.Post] = []
        for path in paths:
            realpath = Path(path)
            with realpath.with_suffix(f"{realpath.suffix}.json").open() as fp:
                contents = json.load(fp)

            user = contents["author"]["name"]
            tweet_id = contents["tweet_id"]
            url = f"https://twitter.com/{user}/status/{tweet_id}"

            try:
                posts.append(await self.upload_file(realpath, url))
            except:
                pass

        joined = "\n".join(f"{config.booru_url}/post/{p.id_}" for p in posts)
        await ctx.send(f"Returned posts: {joined or 'None'}", ephemeral=True)

        await asyncio.to_thread(shutil.rmtree, "./tmp")  # clean up


async def setup(bot: commands.Bot):
    await bot.add_cog(Booru(bot))
