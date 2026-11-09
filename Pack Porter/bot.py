
import io
import os
import zipfile

import discord

from pathlib import PurePosixPath
from discord import app_commands
from dotenv import load_dotenv

from converter.bedrock_to_java import convert_bedrock_to_java
from converter.java_to_bedrock import convert_java_to_bedrock
from converter.texture_mapper import (
    MAX_FILES,
    MAX_UNPACKED,
    validate_archive,
)


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

MAX_UPLOAD = 25 * 1024 * 1024


def inspect_pack(data, filename):

    extension = PurePosixPath(filename.lower()).suffix

    if extension not in {".zip", ".mcpack", ".mcaddon"}:
        return None, "Unsupported file format."

    if len(data) > MAX_UPLOAD:
        return None, "File exceeds the 25 MB limit."

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:

            entries = validate_archive(archive)
            names = [
                entry.filename.lower()
                for entry in entries
            ]

            java = any(
                PurePosixPath(name).name == "pack.mcmeta"
                for name in names
            )

            bedrock = any(
                PurePosixPath(name).name == "manifest.json"
                for name in names
            )

            nested_packs = any(
                name.endswith(".mcpack")
                for name in names
            )

            if nested_packs:
                edition = "Bedrock Add-on"
            elif java and bedrock:
                edition = "Mixed / Needs inspection"
            elif java:
                edition = "Minecraft Java"
            elif bedrock:
                edition = "Minecraft Bedrock"
            else:
                edition = "Unknown / Unsupported structure"

            return {
                "filename": filename,
                "edition": edition,
                "files": len(entries),
                "unpacked_size": sum(
                    entry.file_size for entry in entries
                ),
                "format": extension
            }, None

    except zipfile.BadZipFile:
        return None, "Invalid ZIP-based resource pack."

    except ValueError as error:
        return None, str(error)

    except (OSError, RuntimeError):
        return None, "Unable to read this archive."


class PackPorter(discord.Client):

    def __init__(self):
        super().__init__(
            intents=discord.Intents.default()
        )
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synchronized!")

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        print("PACK PORTER IS ONLINE!")


bot = PackPorter()


# ==========================================
# PING
# ==========================================

@bot.tree.command(
    name="ping",
    description="Check Pack Porter's response time"
)
async def ping(interaction: discord.Interaction):

    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        f"🏓 Pong! `{latency}ms`"
    )


# ==========================================
# ABOUT
# ==========================================

@bot.tree.command(
    name="about",
    description="About Pack Porter"
)
async def about(interaction: discord.Interaction):

    embed = discord.Embed(
        title="📦 Pack Porter",
        description="Minecraft Java ↔ Bedrock Resource Pack Converter",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Accepted formats",
        value="ZIP • MCPACK • MCADDON",
        inline=False
    )

    embed.add_field(
        name="Commands",
        value=(
            "`/ping` - Check latency\n"
            "`/about` - Bot information\n"
            "`/inspect` - Inspect a pack\n"
            "`/convert` - Convert a pack"
        ),
        inline=False
    )

    embed.add_field(
        name="Conversion status",
        value="Experimental texture conversion",
        inline=False
    )

    await interaction.response.send_message(embed=embed)


# ==========================================
# INSPECT
# ==========================================

@bot.tree.command(
    name="inspect",
    description="Inspect a Minecraft resource pack"
)
@app_commands.describe(
    pack="Upload a ZIP, MCPACK or MCADDON file"
)
async def inspect(
    interaction: discord.Interaction,
    pack: discord.Attachment
):

    await interaction.response.defer(ephemeral=True)

    if pack.size > MAX_UPLOAD:
        await interaction.followup.send(
            "❌ File exceeds the 25 MB limit."
        )
        return

    try:
        data = await pack.read()

        result, error = inspect_pack(data, pack.filename)

        if error:
            await interaction.followup.send(f"❌ {error}")
            return

        embed = discord.Embed(
            title="📦 Pack Inspection Results",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="Filename",
            value=result["filename"],
            inline=False
        )

        embed.add_field(
            name="Detected edition",
            value=result["edition"],
            inline=True
        )

        embed.add_field(
            name="Format",
            value=result["format"].upper(),
            inline=True
        )

        embed.add_field(
            name="Files",
            value=str(result["files"]),
            inline=True
        )

        embed.add_field(
            name="Unpacked size",
            value=f'{result["unpacked_size"] / (1024 * 1024):.2f} MB',
            inline=True
        )

        await interaction.followup.send(embed=embed)

    except Exception as error:
        print(f"Inspection error: {error}")

        await interaction.followup.send(
            "❌ Inspection failed."
        )


# ==========================================
# CONVERT
# ==========================================

@bot.tree.command(
    name="convert",
    description="Convert Minecraft resource packs"
)
@app_commands.describe(
    pack="Upload your resource pack",
    direction="Choose conversion direction",
    target_version="Choose target Minecraft version"
)
@app_commands.choices(
    direction=[
        app_commands.Choice(
            name="Bedrock → Java",
            value="bedrock_to_java"
        ),
        app_commands.Choice(
            name="Java → Bedrock",
            value="java_to_bedrock"
        )
    ],
    target_version=[
        app_commands.Choice(
            name="Auto / Default",
            value="auto"
        ),
        app_commands.Choice(
            name="Java 1.21.4",
            value="java:1.21.4"
        ),
        app_commands.Choice(
            name="Java 1.20.1",
            value="java:1.20.1"
        ),
        app_commands.Choice(
            name="Bedrock 1.21.50",
            value="bedrock:1.21.50"
        ),
        app_commands.Choice(
            name="Bedrock 1.20.80",
            value="bedrock:1.20.80"
        )
    ]
)
async def convert(
    interaction: discord.Interaction,
    pack: discord.Attachment,
    direction: app_commands.Choice[str],
    target_version: app_commands.Choice[str]
):

    await interaction.response.defer(ephemeral=True)

    if pack.size > MAX_UPLOAD:
        await interaction.followup.send(
            "❌ File exceeds the 25 MB limit."
        )
        return

    try:
        data = await pack.read()

        if direction.value == "bedrock_to_java":

            if not pack.filename.lower().endswith(
                (".mcpack", ".zip")
            ):
                await interaction.followup.send(
                    "❌ Upload a Bedrock MCPACK or ZIP."
                )
                return

            if target_version.value != "auto" and not target_version.value.startswith("java:"):
                await interaction.followup.send(
                    "❌ Choose a Java target version for this direction."
                )
                return

            converted_data, report, error = (
                convert_bedrock_to_java(
                    data,
                    pack.filename,
                    target_version.value
                )
            )

            output_extension = ".zip"

        else:

            if not pack.filename.lower().endswith(".zip"):
                await interaction.followup.send(
                    "❌ Upload a Java resource-pack ZIP."
                )
                return

            if target_version.value != "auto" and not target_version.value.startswith("bedrock:"):
                await interaction.followup.send(
                    "❌ Choose a Bedrock target version for this direction."
                )
                return

            converted_data, report, error = (
                convert_java_to_bedrock(
                    data,
                    pack.filename,
                    target_version.value
                )
            )

            output_extension = ".mcpack"

        if error:
            await interaction.followup.send(
                f"❌ {error}"
            )
            return

        output_name = (
            PurePosixPath(pack.filename).stem
            + "_PackPorter"
            + output_extension
        )

        discord_file = discord.File(
            io.BytesIO(converted_data),
            filename=output_name
        )

        embed = discord.Embed(
            title="📦 Pack Porter Conversion Results",
            description="Conversion completed",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="Direction",
            value=direction.name,
            inline=False
        )

        embed.add_field(
            name="Target version",
            value=target_version.name,
            inline=True
        )

        embed.add_field(
            name="Converted textures",
            value=str(report["converted_texture_count"]),
            inline=True
        )

        embed.add_field(
            name="Unsupported textures",
            value=str(report["unsupported_texture_count"]),
            inline=True
        )

        embed.add_field(
            name="Output",
            value=output_name,
            inline=False
        )

        embed.set_footer(
            text="Pack Porter • Experimental Texture Converter"
        )

        await interaction.followup.send(
            embed=embed,
            files=[discord_file]
        )

    except discord.HTTPException:
        await interaction.followup.send(
            "❌ Discord could not send the output file."
        )

    except Exception as error:
        print(f"Conversion error: {error}")

        await interaction.followup.send(
            "❌ An unexpected conversion error occurred."
        )


# ==========================================
# START
# ==========================================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing from .env")


bot.run(TOKEN)
