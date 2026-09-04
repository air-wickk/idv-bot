import requests
import re
from datetime import datetime, timezone


class XProfileClient:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/140.0.0.0 Safari/537.36"
        })

    def get_user_tweets(self, username, limit=5):
        url = f"https://x.com/{username}"

        response = self.session.get(url, timeout=20)
        response.raise_for_status()

        html = response.text

        # Find the account's user ID
        user_id_match = re.search(
            r'UserResults:(\d+)',
            html
        )

        user_id = None

        # GameIdentityV's user ID is also available in the HTML.
        # This prevents accidentally returning quoted tweets.
        account_ids = re.findall(
            r'user_results:\$R\[\d+\]=\{__ref:"VXNlclJlc3VsdHM6(\d+)"',
            html
        )

        if account_ids:
            user_id = account_ids[0]

        tweets = []

        # Find tweet IDs from the profile timeline.
        tweet_ids = []

        for tweet_id in re.findall(
            r'rest_id:"(\d{18,20})"',
            html
        ):
            if tweet_id not in tweet_ids:
                tweet_ids.append(tweet_id)

        for tweet_id in tweet_ids:

            # Locate the tweet object.
            tweet_pos = html.find(
                f'rest_id:"{tweet_id}"'
            )

            if tweet_pos == -1:
                continue

            # Make sure this is actually a Tweet object.
            tweet_start = html.rfind(
                f'"Tweet:',
                200,
                tweet_pos
            )

            # Find the details reference belonging to this tweet.
            details_match = re.search(
                rf'client:VHdlZXQ6.*?{re.escape(tweet_id)}.*?'
                rf'details:\$R\[\d+\]=\{{__ref:"([^"]+)"\}}',
                html[tweet_pos - 500:tweet_pos + 1500]
            )

            if not details_match:
                # Try a simpler search within the surrounding object.
                surrounding = html[tweet_pos:tweet_pos + 2500]

                details_match = re.search(
                    r'details:\$R\[\d+\]=\{__ref:"([^"]+)"\}',
                    surrounding
                )

            if not details_match:
                continue

            details_ref = details_match.group(1)

            # Find the actual details object.
            details_pos = html.find(
                f'"{details_ref}":',
                tweet_pos
            )

            if details_pos == -1:
                continue

            details_data = html[
                details_pos:details_pos + 6000
            ]

            # Extract text.
            text_match = re.search(
                r'full_text:"((?:\\.|[^"])*)"',
                details_data
            )

            # Extract timestamp.
            date_match = re.search(
                r'created_at_ms:(\d+)',
                details_data
            )

            if not text_match or not date_match:
                continue

            text = text_match.group(1)

            # Decode escaped characters used by X's serialized data.
            text = (
                text
                .replace(r'\n', '\n')
                .replace(r'\"', '"')
                .replace(r'\\', '\\')
            )

            timestamp = int(date_match.group(1))

            created_at = datetime.fromtimestamp(
                timestamp / 1000,
                tz=timezone.utc
            )

            tweets.append({
                "id": tweet_id,
                "text": text,
                "created_at": created_at,
                "url": f"https://x.com/{username}/status/{tweet_id}",
            })

            if len(tweets) >= limit:
                break

        return tweets