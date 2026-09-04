import asyncio
import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import requests
from dotenv import load_dotenv

import tweety_compat
from tweety import TwitterAsync


load_dotenv()

logger = logging.getLogger(__name__)


class TwitterClient:
    def __init__(self):
        self.username = os.getenv("LOGIN_USERNAME")
        self.email = os.getenv("LOGIN_EMAIL")
        self.password = os.getenv("LOGIN_PASSWORD")
        self.session_dir = "session"

        # Keep Tweety for authenticated features.
        self.client = TwitterAsync(self.session_dir)
        self.logged_in = False

        # Separate session for public X profile pages.
        self.http = requests.Session()

        self.http.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )

    # ================================================================
    # Tweety login
    # ================================================================

    async def login(self):
        if self.logged_in:
            return

        try:
            await self.client.connect()

            self.logged_in = True
            print("Connected using existing session")

        except Exception as e:
            print(f"Existing session failed, signing in fresh: {e}")

            if not self.username or not self.password:
                print(
                    "LOGIN_USERNAME or LOGIN_PASSWORD is not configured."
                )
                self.logged_in = False
                return

            try:
                await self.client.sign_in(
                    self.username,
                    self.password,
                )

                self.logged_in = True
                print("Fresh login successful")

            except Exception as signin_error:
                print(f"Login failed: {signin_error}")
                self.logged_in = False

    # ================================================================
    # Existing Tweety features
    # ================================================================

    async def search_tweet(self, query, limit=1):
        await self.login()

        if not self.logged_in:
            return []

        try:
            return await self.client.asyncsearch_tweet(
                query,
                product="Latest",
                count=limit,
            )
        except Exception as e:
            print(f"Error searching tweets: {e}")
            return []

    async def like_tweet(self, tweet):
        await self.login()

        if not self.logged_in:
            return

        try:
            await self.client.favorite_tweet(tweet.id)
        except Exception as e:
            print(f"Error liking tweet: {e}")

    async def bookmark_tweet(self, tweet):
        await self.login()

        if not self.logged_in:
            return

        try:
            await self.client.bookmark_tweet(tweet.id)
        except Exception as e:
            print(f"Error bookmarking tweet: {e}")

    async def get_notifications(self):
        await self.login()

        if not self.logged_in:
            return []

        try:
            return await self.client.get_notifications("Mentions")
        except Exception as e:
            print(f"Error fetching notifications: {e}")
            return []

    # ================================================================
    # X HTML parsing helpers
    # ================================================================

    @staticmethod
    def _decode_x_string(value):
        try:
            return json.loads(f'"{value}"')
        except Exception:
            return (
                value
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )

    @classmethod
    def _extract_x_string(cls, chunk, field):
        """
        Extract something like:

            full_text:"Hello\\nWorld"
        """

        match = re.search(
            rf'{re.escape(field)}:"((?:\\.|[^"])*)"',
            chunk,
        )

        if not match:
            return None

        return cls._decode_x_string(match.group(1))

    # ================================================================
    # Public X profile timeline
    # ================================================================

    def _fetch_profile_tweets_sync(self, username, limit=5):
        username = (
            str(username)
            .strip()
            .lstrip("@")
        )

        if not username:
            return []

        url = f"https://x.com/{username}"

        try:
            response = self.http.get(
                url,
                timeout=20,
            )
            response.raise_for_status()

        except requests.RequestException as e:
            logger.error(
                "Could not fetch X profile @%s: %s",
                username,
                e,
            )
            return []

        html = response.text

        logger.info(
            "Fetched X profile @%s (%s bytes)",
            username,
            len(html),
        )

        # ------------------------------------------------------------
        # Get the actual timeline tweet IDs.
        # ------------------------------------------------------------

        timeline_ids = []

        for tweet_id in re.findall(
            r"TimelineTimelineEntry:tweet-(\d+)",
            html,
        ):
            if tweet_id not in timeline_ids:
                timeline_ids.append(tweet_id)

        logger.info(
            "X profile @%s has %s timeline entries",
            username,
            len(timeline_ids),
        )

        results = []

        for tweet_id in timeline_ids:

            if len(results) >= limit:
                break

            # --------------------------------------------------------
            # Locate the Tweet:<id> object.
            # --------------------------------------------------------

            tweet_ref = base64.b64encode(
                f"Tweet:{tweet_id}".encode("utf-8")
            ).decode("ascii")

            tweet_marker = f'"{tweet_ref}"'

            tweet_pos = html.find(tweet_marker)

            if tweet_pos == -1:
                logger.warning(
                    "Could not locate tweet object %s",
                    tweet_id,
                )
                continue

            tweet_chunk = html[
                tweet_pos:tweet_pos + 15000
            ]

            # --------------------------------------------------------
            # Find the details reference.
            #
            # We no longer try to identify the author here.
            #
            # The tweet ID came directly from:
            #
            # TimelineTimelineEntry:tweet-ID
            #
            # so it is already a tweet displayed in this profile's
            # timeline.
            # --------------------------------------------------------

            details_match = re.search(
                r'details:\$R\[\d+\]=\{__ref:"([^"]+)"',
                tweet_chunk,
            )

            if not details_match:
                logger.warning(
                    "Could not locate details for tweet %s",
                    tweet_id,
                )
                continue

            details_ref = details_match.group(1)

            details_pos = html.find(
                f'"{details_ref}"',
                tweet_pos,
            )

            if details_pos == -1:
                logger.warning(
                    "Could not find details object for tweet %s",
                    tweet_id,
                )
                continue

            details_chunk = html[
                details_pos:details_pos + 15000
            ]

            # --------------------------------------------------------
            # Extract tweet text.
            # --------------------------------------------------------

            text = self._extract_x_string(
                details_chunk,
                "full_text",
            )

            if not text:
                text = self._extract_x_string(
                    details_chunk,
                    "text",
                )

            if text is None:
                text = ""

            # --------------------------------------------------------
            # Extract timestamp.
            # --------------------------------------------------------

            created_on = None

            created_match = re.search(
                r"created_at_ms:(\d+)",
                details_chunk,
            )

            if created_match:
                timestamp_ms = int(
                    created_match.group(1)
                )

                created_on = datetime.fromtimestamp(
                    timestamp_ms / 1000,
                    tz=timezone.utc,
                )

            # --------------------------------------------------------
            # Create an object compatible with the rest of your bot.
            # --------------------------------------------------------

            author = SimpleNamespace(
                username=username,
            )

            tweet = SimpleNamespace(
                id=tweet_id,
                text=text,
                full_text=text,
                created_on=created_on,
                created_at=created_on,

                author=author,

                is_reply=False,
                in_reply_to_status_id=None,

                url=(
                    f"https://x.com/"
                    f"{username}/status/{tweet_id}"
                ),
            )

            results.append(tweet)

            logger.info(
                "X TWEET: %s | %s | %s",
                tweet_id,
                created_on,
                text[:120].replace("\n", " "),
            )

        return results

    async def get_user_tweets(self, username, limit=5):
        """
        Fetch the newest tweets shown on an X profile.

        This intentionally does NOT use Tweety's get_tweets().
        """

        try:
            return await asyncio.to_thread(
                self._fetch_profile_tweets_sync,
                username,
                limit,
            )

        except Exception as e:
            logger.exception(
                "Error fetching @%s: %s",
                username,
                e,
            )
            return []