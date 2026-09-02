# Identity V Twitter Scraper

This project is a Discord bot that tracks a specified Identity V Twitter account and sends its posts to a designated Discord channel. The bot uses Discord.py for Discord interactions and Tweety for fetching tweets.

## Features

- Monitors a configurable Identity V Twitter account and posts new tweets to a Discord channel.
- Slash commands under `/settings` let moderators change the send channel, tracked account, silent mode, reply filtering, and keyword filters.
- Slash commands under `/afk` let moderators set an AFK voice channel, set the looping audio source, and enable or disable playback.
- Keeps a hardcoded default channel from `.env`, but allows the server to override it at runtime.
- Includes a Flask web server for deployment compatibility.
- Configurable via environment variables.

## Settings

- Runtime settings can be changed with the `/settings` commands.
- The bot keeps hardcoded defaults from environment variables for the channel and tracked account.
- With Supabase configured, slash-command settings persist across redeploys.
- Without Supabase configured, settings are runtime-only on Render and reset after a redeploy.
- If slash commands do not appear yet, run `!sync` as a server admin to force a guild sync.

## Available Commands

- `/settings channel <channel>`
- `/settings user <username>`
- `/settings silent <true|false>`
- `/settings ignore_replies <true|false>`
- `/keywords add <word>`
- `/keywords remove <word>`
- `/afk channel <voice_channel>`
- `/afk audio <path_or_url>`
- `/afk enable`
- `/afk disable`
- `/afk view`