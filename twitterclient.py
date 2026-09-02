import os
from dotenv import load_dotenv
import tweety_compat
from tweety import TwitterAsync

from settings_store import SupabaseSettingsStore
from twitter_session_store import SupabaseTwitterSessionStore

load_dotenv()

class TwitterClient:
    def __init__(self):
        self.username = os.getenv('LOGIN_USERNAME')
        self.email = os.getenv('LOGIN_EMAIL')
        self.password = os.getenv('LOGIN_PASSWORD')
        self.session_dir = "session"
        self.supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or ""
        self.session_table = (os.getenv("SUPABASE_SESSION_TABLE") or "twitter_sessions").strip()
        self.session_key = (os.getenv("SUPABASE_TWITTER_SESSION_KEY") or "twitter_session").strip()
        self.session_store = SupabaseTwitterSessionStore(
            self.supabase_url,
            self.supabase_key,
            table_name=self.session_table,
            session_key=self.session_key,
        )
        self.client = TwitterAsync(self.session_dir)
        self.logged_in = False

    async def login(self):
        if self.logged_in:
            return
        try:
            if self.session_store.enabled:
                restored = await self.session_store.load_session(self.session_dir)
                if restored:
                    print("Restored Tweety session from Supabase")
            # Try to use existing session first
            await self.client.connect()
            self.logged_in = True
            print("Connected using existing session")
        except Exception as e:
            print(f"Existing session failed, signing in fresh: {e}")
            try:
                await self.client.sign_in(self.username, self.password)
                self.logged_in = True
                print("Fresh login successful")
                if self.session_store.enabled:
                    await self.session_store.save_session(self.session_dir)
            except Exception as signin_error:
                print(f"Login failed: {signin_error}")
                self.logged_in = False

    async def search_tweet(self, query, limit=1):
        await self.login()
        try:
            tweets = await self.client.asyncsearch_tweet(query, product="Latest", count=limit)
            return tweets
        except Exception as e:
            print(f"Error searching tweets: {e}")
            return []

    async def like_tweet(self, tweet):
        await self.login()
        try:
            await self.client.favorite_tweet(tweet.id)
        except Exception as e:
            print(f"Error liking tweet: {e}")

    async def bookmark_tweet(self, tweet):
        await self.login()
        try:
            await self.client.bookmark_tweet(tweet.id)
        except Exception as e:
            print(f"Error bookmarking tweet: {e}")

    async def get_notifications(self):
        await self.login()
        try:
            notifs = await self.client.get_notifications("Mentions")
            return notifs
        except Exception as e:
            print(f"Error fetching notifications: {e}")
            return []

    async def get_user_tweets(self, username, limit=3):
        await self.login()
        try:
            user_tweets = await self.client.get_tweets(username, pages=1)
            return user_tweets.tweets[:limit]
        except Exception as e:
            print(f"Error fetching user tweets: {e}")
            return []