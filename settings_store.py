import asyncio
import json
import logging
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


class SupabaseSettingsStore:
    def __init__(self, url, api_key, table_name="bot_settings"):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key or ""
        self.table_name = (table_name or "bot_settings").strip()

    @property
    def enabled(self):
        return bool(self.url and self.api_key and self.table_name)

    def _headers(self, prefer=None):
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(self, method, query_suffix="", payload=None, prefer=None):
        if not self.enabled:
            return None

        url = f"{self.url}/rest/v1/{self.table_name}{query_suffix}"
        request_payload = None
        if payload is not None:
            request_payload = json.dumps(payload).encode("utf-8")

        request = urllib_request.Request(
            url=url,
            data=request_payload,
            headers=self._headers(prefer=prefer),
            method=method,
        )

        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                raw_body = response.read().decode("utf-8")
                if not raw_body:
                    return None
                return json.loads(raw_body)
        except urllib_error.HTTPError as http_error:
            error_body = http_error.read().decode("utf-8", errors="replace")
            logging.error("Supabase request failed (%s): %s", http_error.code, error_body)
        except Exception as error:
            logging.error("Supabase request failed: %s", error)
        return None

    def load_settings_sync(self, guild_id, defaults, normalizer):
        if not self.enabled or not guild_id:
            return normalizer(defaults)

        query = urllib_parse.urlencode({"guild_id": f"eq.{guild_id}", "select": "*", "limit": 1})
        rows = self._request("GET", f"?{query}")
        if isinstance(rows, list) and rows:
            merged = dict(defaults)
            merged.update(rows[0])
            return normalizer(merged)

        fallback = normalizer(defaults)
        self.save_settings_sync(guild_id, fallback)
        return fallback

    def save_settings_sync(self, guild_id, config):
        if not self.enabled or not guild_id:
            return

        payload = {
            "guild_id": int(guild_id),
            "channel_id": config.get("channel_id"),
            "tracked_username": config.get("tracked_username"),
            "silent": bool(config.get("silent", False)),
            "ignore_replies": bool(config.get("ignore_replies", True)),
            "keywords": config.get("keywords", []),
            "afk_enabled": bool(config.get("afk_enabled", False)),
            "afk_voice_channel_id": config.get("afk_voice_channel_id"),
            "afk_audio_source": config.get("afk_audio_source"),
        }
        self._request(
            "POST",
            "?on_conflict=guild_id",
            payload=payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    async def load_settings(self, guild_id, defaults, normalizer):
        return await asyncio.to_thread(self.load_settings_sync, guild_id, defaults, normalizer)

    async def save_settings(self, guild_id, config):
        await asyncio.to_thread(self.save_settings_sync, guild_id, config)
