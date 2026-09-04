import asyncio
import logging
import os
import random
from threading import Thread

import discord
from discord import Activity, ActivityType, Intents, app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask

from afk_voice import AfkVoiceManager
from settings_store import SupabaseSettingsStore
from twitterclient import TwitterClient

DEFAULT_TWEET_LIMIT = 3
DEFAULT_POLL_MIN_SECONDS = 30
DEFAULT_POLL_MAX_SECONDS = 90
AUTHORIZED_USER_ID = 305168559804514304


def parse_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def has_manage_guild_or_authorized_user(interaction: discord.Interaction):
    return interaction.user.id == AUTHORIZED_USER_ID or interaction.user.guild_permissions.manage_guild


load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DEFAULT_DISCORD_CHANNEL_ID = parse_int(os.getenv("DISCORD_CHANNEL_ID"))
GUILD_ID = parse_int(os.getenv("GUILD_ID"))
DEFAULT_TRACKED_USERNAME = (os.getenv("TRACKED_USERNAME") or os.getenv("TRACKED_USER_ID") or "").strip()
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or ""
SUPABASE_TABLE = (os.getenv("SUPABASE_SETTINGS_TABLE") or "bot_settings").strip()

DEFAULT_CONFIG = {
    "channel_id": None,
    "tracked_username": DEFAULT_TRACKED_USERNAME,
    "silent": False,
    "ignore_replies": True,
    "keywords": [],
    "afk_enabled": False,
    "afk_voice_channel_id": None,
    "afk_audio_source": (os.getenv("AFK_AUDIO_SOURCE") or os.getenv("AFK_AUDIO_FILE") or "").strip(),
}


def normalize_config(config):
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(config)
    normalized["channel_id"] = parse_int(normalized.get("channel_id"))
    normalized["afk_voice_channel_id"] = parse_int(normalized.get("afk_voice_channel_id"))
    normalized["tracked_username"] = str(normalized.get("tracked_username", "")).strip().lstrip("@")
    normalized["silent"] = bool(normalized.get("silent", False))
    normalized["ignore_replies"] = bool(normalized.get("ignore_replies", True))
    normalized["afk_enabled"] = bool(normalized.get("afk_enabled", False))
    normalized["afk_audio_source"] = str(normalized.get("afk_audio_source", "") or "").strip()
    keywords = normalized.get("keywords", [])
    if keywords is None:
        keywords = []
    if isinstance(keywords, str):
        keywords = [item.strip().lower() for item in keywords.split(",") if item.strip()]
    else:
        keywords = [str(item).strip().lower() for item in keywords if str(item).strip()]
    normalized["keywords"] = keywords
    return normalized


def get_primary_guild_id():
    if GUILD_ID:
        return GUILD_ID
    if bot.guilds:
        return bot.guilds[0].id
    return None


settings_store = SupabaseSettingsStore(SUPABASE_URL, SUPABASE_KEY, SUPABASE_TABLE)


async def load_bot_config(guild_id):
    return await settings_store.load_settings(guild_id, DEFAULT_CONFIG, normalize_config)


async def save_bot_config(guild_id, config):
    await settings_store.save_settings(guild_id, config)


bot_config = normalize_config({})

intents = Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
twitter = TwitterClient()
afk_manager = AfkVoiceManager(bot, lambda: bot_config, save_bot_config)

identity_v_statuses = [
    "I think you're eating too much.",
    "I can only repay people's trust with actions.",
    "A letter is a hug from miles away.",
    "Ink fades, but the heartbeat behind it stays vivid.",
    "Fireworks are letters to the sky.",
    "I hope you have fun!",
    "Face-to-face conversation is the most hypocrite thing.",
    "I am a post man.",
    "Feelings hidden in the lines are most truthful.",
    "I've never been so sure about the endlessly sincere writings.",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def get_effective_channel_id():
    return bot_config.get("channel_id") or DEFAULT_DISCORD_CHANNEL_ID


def get_effective_tracked_username():
    return bot_config.get("tracked_username", "").strip().lstrip("@")


def get_keyword_list():
    return bot_config.get("keywords", [])


def keyword_filter_matches(tweet_text):
    keywords = get_keyword_list()
    if not keywords:
        return True

    normalized_text = (tweet_text or "").lower()
    return not any(keyword in normalized_text for keyword in keywords)


def is_reply_tweet(tweet):
    if hasattr(tweet, "in_reply_to_status_id") and getattr(tweet, "in_reply_to_status_id", None):
        return True
    if hasattr(tweet, "is_reply"):
        return bool(getattr(tweet, "is_reply"))
    return False


async def resolve_channel(channel_id):
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except Exception:
        return None


async def random_sleep():
    minimum = bot_config.get("poll_min_seconds", DEFAULT_POLL_MIN_SECONDS)
    maximum = bot_config.get("poll_max_seconds", DEFAULT_POLL_MAX_SECONDS)
    await asyncio.sleep(random.randint(minimum, maximum))


settings_group = app_commands.Group(name="settings", description="Manage scraper settings")


@settings_group.command(name="channel", description="Set the channel where tweets are sent")
@app_commands.check(has_manage_guild_or_authorized_user)
async def settings_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    bot_config["channel_id"] = channel.id
    await save_bot_config(interaction.guild_id, bot_config)
    await interaction.response.send_message(f"Send channel updated to {channel.mention}.", ephemeral=True)


@settings_group.command(name="user", description="Set the Identity V Twitter account to track")
@app_commands.check(has_manage_guild_or_authorized_user)
async def settings_user(interaction: discord.Interaction, username: str):
    cleaned_username = username.strip().lstrip("@")
    bot_config["tracked_username"] = cleaned_username
    await save_bot_config(interaction.guild_id, bot_config)
    await interaction.response.send_message(f"Tracked account updated to @{cleaned_username}.", ephemeral=True)


@settings_group.command(name="silent", description="Send tweets without push notifications")
@app_commands.check(has_manage_guild_or_authorized_user)
async def settings_silent(interaction: discord.Interaction, enabled: bool):
    bot_config["silent"] = bool(enabled)
    await save_bot_config(interaction.guild_id, bot_config)
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(f"Silent mode {state}.", ephemeral=True)


@settings_group.command(name="ignore_replies", description="Ignore reply tweets when posting")
@app_commands.check(has_manage_guild_or_authorized_user)
async def settings_ignore_replies(interaction: discord.Interaction, enabled: bool = True):
    bot_config["ignore_replies"] = bool(enabled)
    await save_bot_config(interaction.guild_id, bot_config)
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(f"Ignore replies {state}.", ephemeral=True)

@settings_group.command(name="view", description="View current bot settings")
@app_commands.check(has_manage_guild_or_authorized_user)
async def settings_view(interaction: discord.Interaction):
    channel_id = get_effective_channel_id()
    channel_mention = f"<#{channel_id}>" if channel_id else "Not set"

    tracked = get_effective_tracked_username()
    tracked_display = f"@{tracked}" if tracked else "Not set"

    silent = bot_config.get("silent", False)
    ignore_replies = bot_config.get("ignore_replies", True)
    keywords = get_keyword_list()
    keywords_display = ", ".join(f"`{k}`" for k in keywords) if keywords else "None (all tweets pass through)"

    lines = [
        "**Current settings**",
        f"Channel: {channel_mention}",
        f"Tracked account: {tracked_display}",
        f"Silent mode: {'On' if silent else 'Off'}",
        f"Ignore replies: {'Yes' if ignore_replies else 'No'}",
        f"Keywords: {keywords_display}",
    ]

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


keywords_group = app_commands.Group(name="keywords", description="Manage tweet keyword filtering")


@keywords_group.command(name="add", description="Block tweets containing this word")
@app_commands.check(has_manage_guild_or_authorized_user)
async def keywords_add(interaction: discord.Interaction, word: str):
    keyword = word.strip().lower()
    if not keyword:
        await interaction.response.send_message("Please provide a keyword.", ephemeral=True)
        return
    keywords = get_keyword_list()
    if keyword not in keywords:
        keywords.append(keyword)
    bot_config["keywords"] = keywords
    await save_bot_config(interaction.guild_id, bot_config)
    await interaction.response.send_message(f"Added keyword: `{keyword}`.", ephemeral=True)


@keywords_group.command(name="remove", description="Remove a keyword from the filter list")
@app_commands.check(has_manage_guild_or_authorized_user)
async def keywords_remove(interaction: discord.Interaction, word: str):
    keyword = word.strip().lower()
    if not keyword:
        await interaction.response.send_message("Please provide a keyword.", ephemeral=True)
        return
    keywords = [item for item in get_keyword_list() if item != keyword]
    bot_config["keywords"] = keywords
    await save_bot_config(interaction.guild_id, bot_config)
    await interaction.response.send_message(f"Removed keyword: `{keyword}`.", ephemeral=True)


bot.tree.add_command(keywords_group)


bot.tree.add_command(settings_group)


@bot.tree.command(name="delete", description="Delete the bot's recent messages")
@app_commands.check(has_manage_guild_or_authorized_user)
@app_commands.describe(amount="Number of bot messages to delete")
async def delete_messages(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100],
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    channel = interaction.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This command can only be used in a text channel.",
            ephemeral=True,
        )
        return

    bot_member = interaction.guild.me

    if bot_member is None or not channel.permissions_for(bot_member).manage_messages:
        await interaction.response.send_message(
            "I need the Manage Messages permission in this channel.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    deleted = 0

    async for message in channel.history(limit=200):
        if deleted >= amount:
            break

        if message.author.id != bot.user.id:
            continue

        try:
            await message.delete()
            deleted += 1
        except discord.HTTPException:
            pass

    await interaction.followup.send(
        f"Deleted {deleted} of my recent messages.",
        ephemeral=True,
    )


afk_group = afk_manager.create_command_group()
bot.tree.add_command(afk_group)


async def sync_app_commands():
    synced_commands = await bot.tree.sync()
    logging.info("Synced %s global commands", len(synced_commands))
    return synced_commands


@bot.command(name="sync")
@commands.guild_only()
@commands.check(lambda ctx: ctx.author.id == AUTHORIZED_USER_ID or ctx.author.guild_permissions.manage_guild)
async def sync_prefix_command(ctx):
    synced_commands = await sync_app_commands()
    await ctx.reply(f"Synced {len(synced_commands)} global application commands.")


@tasks.loop(minutes=5)
async def change_status():
    if not bot_config.get("status_rotation_enabled", True):
        return
    status = random.choice(identity_v_statuses)
    await bot.change_presence(activity=Activity(type=ActivityType.watching, name=status))


@bot.event
async def on_ready():
    global bot_config

    print(f"Logged in as {bot.user}")
    await sync_app_commands()
    print("Synced global commands")

    if not check_tweets.is_running():
        check_tweets.start()
    if not change_status.is_running():
        change_status.start()
    afk_manager.start()

    primary_guild_id = get_primary_guild_id()
    bot_config = await load_bot_config(primary_guild_id)
    if settings_store.enabled:
        logging.info("Loaded settings from Supabase for guild %s", primary_guild_id)
    else:
        logging.warning("Supabase is not configured. Settings are runtime-only.")


@bot.event
async def on_voice_state_update(member, before, after):
    await afk_manager.handle_voice_state_update(member, before, after)


@tasks.loop(seconds=1)
async def check_tweets():
    channel_id = get_effective_channel_id()
    tracked_username = get_effective_tracked_username()
    silent = bool(bot_config.get("silent", False))
    ignore_replies = bool(bot_config.get("ignore_replies", True))

    if not channel_id:
        logging.warning(
            "No send channel configured yet. "
            "Set DISCORD_CHANNEL_ID or use /settings channel."
        )
        await random_sleep()
        return

    if not tracked_username:
        logging.warning(
            "No tracked Twitter username configured yet. "
            "Set TRACKED_USERNAME or use /settings user."
        )
        await random_sleep()
        return

    channel = await resolve_channel(channel_id)

    if channel is None:
        logging.error(
            "Could not resolve Discord channel %s",
            channel_id,
        )
        await random_sleep()
        return

    await random_sleep()

    try:
        tweets = await twitter.get_user_tweets(
            tracked_username,
            limit=5,
        )

        if not tweets:
            logging.info(
                "No tweets found for @%s",
                tracked_username,
            )
            return

        # --------------------------------------------------------------
        # Collect tweet IDs already posted by this bot.
        # --------------------------------------------------------------

        sent_ids = set()

        async for msg in channel.history(limit=300):
            if msg.author == bot.user:
                parts = msg.content.strip().split("/")

                if parts and parts[-1].isdigit():
                    sent_ids.add(parts[-1])

        # --------------------------------------------------------------
        # Apply filters.
        # --------------------------------------------------------------

        tweets_to_send = []

        for tweet in tweets:

            if ignore_replies and is_reply_tweet(tweet):
                continue

            tweet_text = " ".join(
                [
                    str(
                        getattr(tweet, "text", "")
                        or ""
                    ),
                    str(
                        getattr(tweet, "full_text", "")
                        or ""
                    ),
                ]
            ).strip()

            if not keyword_filter_matches(tweet_text):
                continue

            tweet_id = getattr(tweet, "id", None)

            if tweet_id is None:
                continue

            tweet_id = str(tweet_id)

            if tweet_id in sent_ids:
                continue

            tweets_to_send.append(tweet)

        # --------------------------------------------------------------
        # Send oldest -> newest so multiple missed tweets appear in
        # chronological order.
        # --------------------------------------------------------------

        for tweet in reversed(tweets_to_send):

            author = getattr(tweet, "author", None)
            username = getattr(
                author,
                "username",
                tracked_username,
            )

            tweet_url = (
                f"https://fixupx.com/"
                f"{username}/status/{tweet.id}"
            )

            await channel.send(
                tweet_url,
                silent=silent,
            )

            logging.info(
                "Posted tweet %s from @%s",
                tweet.id,
                username,
            )

    except Exception as error:
        logging.exception(
            "Error fetching tweets: %s",
            error,
        )


app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running!"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


flask_thread = Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()


if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)