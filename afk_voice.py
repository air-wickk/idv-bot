import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import tasks


class AfkVoiceManager:
    def __init__(self, bot, get_settings, save_settings):
        self.bot = bot
        self.get_settings = get_settings
        self.save_settings = save_settings
        self.ffmpeg_executable = os.getenv("FFMPEG_BINARY") or os.getenv("FFMPEG_PATH") or "ffmpeg"

    def _config(self):
        return self.get_settings() or {}

    def _enabled(self):
        return bool(self._config().get("afk_enabled", False))

    def _channel_id(self):
        return self._config().get("afk_voice_channel_id")

    def _audio_source(self):
        config_value = self._config().get("afk_audio_source") or ""
        env_value = os.getenv("AFK_AUDIO_SOURCE") or os.getenv("AFK_AUDIO_FILE") or ""
        return (config_value or env_value).strip()

    def _resolve_voice_channel(self, guild):
        channel_id = self._channel_id()
        if not channel_id:
            return None

        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            return channel
        return None

    def _non_bot_members_present(self, channel):
        return any(not member.bot for member in channel.members)

    def _build_audio_source(self):
        audio_source = self._audio_source()
        if not audio_source:
            return None

        return discord.FFmpegPCMAudio(
            audio_source,
            executable=self.ffmpeg_executable,
            before_options="-stream_loop -1",
        )

    async def refresh_guild(self, guild, restart=False):
        if guild is None:
            return

        voice_channel = self._resolve_voice_channel(guild)
        voice_client = guild.voice_client
        audio_source = self._audio_source()
        should_run = self._enabled() and voice_channel is not None and bool(audio_source)

        if not should_run:
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect(force=True)
            return

        if not self._non_bot_members_present(voice_channel):
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect(force=True)
            return

        if voice_client and voice_client.channel.id != voice_channel.id:
            await voice_client.move_to(voice_channel)
            voice_client = guild.voice_client

        if not voice_client:
            voice_client = await voice_channel.connect(self_deaf=True)

        if restart and voice_client.is_playing():
            voice_client.stop()

        if not voice_client.is_playing():
            source = self._build_audio_source()
            if source is None:
                logging.warning("AFK audio source is missing or empty.")
                return
            voice_client.play(source)

    async def handle_voice_state_update(self, member, before, after):
        if member.bot:
            return

        channel_id = self._channel_id()
        if not channel_id:
            return

        before_matches = before.channel and before.channel.id == channel_id
        after_matches = after.channel and after.channel.id == channel_id
        if not before_matches and not after_matches:
            return

        await self.refresh_guild(member.guild, restart=False)

    @tasks.loop(seconds=10)
    async def monitor(self):
        for guild in self.bot.guilds:
            try:
                await self.refresh_guild(guild, restart=False)
            except Exception as error:
                logging.error("AFK monitor error for guild %s: %s", guild.id, error)

    @monitor.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()

    def start(self):
        if not self.monitor.is_running():
            self.monitor.start()

    async def stop(self):
        if self.monitor.is_running():
            self.monitor.cancel()

    def create_command_group(self):
        afk_group = app_commands.Group(name="afk", description="Manage AFK voice playback")

        @afk_group.command(name="channel", description="Set the AFK voice channel")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def afk_channel(interaction: discord.Interaction, channel: discord.VoiceChannel):
            settings = self._config()
            settings["afk_voice_channel_id"] = channel.id
            settings["afk_enabled"] = True
            await self.save_settings(interaction.guild_id, settings)
            await interaction.response.send_message(
                f"AFK voice channel set to {channel.mention}.",
                ephemeral=True,
            )
            await self.refresh_guild(interaction.guild, restart=True)

        @afk_group.command(name="audio", description="Set the audio source used in AFK voice")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def afk_audio(interaction: discord.Interaction, source: str):
            cleaned_source = source.strip()
            if not cleaned_source:
                await interaction.response.send_message("Please provide an audio file path or URL.", ephemeral=True)
                return

            settings = self._config()
            settings["afk_audio_source"] = cleaned_source
            await self.save_settings(interaction.guild_id, settings)
            await interaction.response.send_message(
                "AFK audio source updated.",
                ephemeral=True,
            )
            await self.refresh_guild(interaction.guild, restart=True)

        @afk_group.command(name="enable", description="Enable AFK voice playback")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def afk_enable(interaction: discord.Interaction):
            settings = self._config()
            settings["afk_enabled"] = True
            await self.save_settings(interaction.guild_id, settings)
            await interaction.response.send_message("AFK voice playback enabled.", ephemeral=True)
            await self.refresh_guild(interaction.guild, restart=True)

        @afk_group.command(name="disable", description="Disable AFK voice playback")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def afk_disable(interaction: discord.Interaction):
            settings = self._config()
            settings["afk_enabled"] = False
            await self.save_settings(interaction.guild_id, settings)
            await interaction.response.send_message("AFK voice playback disabled.", ephemeral=True)
            await self.refresh_guild(interaction.guild, restart=True)

        @afk_group.command(name="view", description="View current AFK voice settings")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def afk_view(interaction: discord.Interaction):
            settings = self._config()
            channel_id = settings.get("afk_voice_channel_id")
            channel_mention = f"<#{channel_id}>" if channel_id else "Not set"
            audio_source = settings.get("afk_audio_source") or os.getenv("AFK_AUDIO_SOURCE") or os.getenv("AFK_AUDIO_FILE") or "Not set"
            enabled = "On" if settings.get("afk_enabled", False) else "Off"

            lines = [
                "**AFK Voice Settings**",
                f"Enabled: {enabled}",
                f"AFK channel: {channel_mention}",
                f"Audio source: `{audio_source}`",
            ]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        return afk_group
