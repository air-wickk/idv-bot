import asyncio
import base64
import io
import json
import logging
import os
import shutil
import zipfile
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


class SupabaseTwitterSessionStore:
    def __init__(self, url, api_key, table_name="twitter_sessions", session_key="twitter_session"):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key or ""
        self.table_name = (table_name or "twitter_sessions").strip()
        self.session_key = (session_key or "twitter_session").strip()

    @property
    def enabled(self):
        return bool(self.url and self.api_key and self.table_name and self.session_key)

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
            logging.error("Supabase session request failed (%s): %s", http_error.code, error_body)
        except Exception as error:
            logging.error("Supabase session request failed: %s", error)
        return None

    def _session_archive_blob(self, session_dir):
        if not os.path.isdir(session_dir):
            return None

        buffer = io.BytesIO()
        file_count = 0
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for root, _, files in os.walk(session_dir):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(file_path, session_dir)
                    archive.write(file_path, relative_path)
                    file_count += 1

        if file_count == 0:
            return None

        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _safe_extract_archive(self, archive, session_dir):
        os.makedirs(session_dir, exist_ok=True)
        session_root = os.path.realpath(session_dir)

        for member in archive.infolist():
            destination_path = os.path.realpath(os.path.join(session_dir, member.filename))
            if not destination_path.startswith(session_root + os.sep) and destination_path != session_root:
                raise ValueError(f"Unsafe session archive entry: {member.filename}")

        archive.extractall(session_dir)

    def load_session_sync(self, session_dir):
        if not self.enabled:
            return False

        query = urllib_parse.urlencode({"session_key": f"eq.{self.session_key}", "select": "session_blob", "limit": 1})
        rows = self._request("GET", f"?{query}")
        if not (isinstance(rows, list) and rows):
            return False

        session_blob = rows[0].get("session_blob")
        if not session_blob:
            return False

        raw_archive = base64.b64decode(session_blob)
        with zipfile.ZipFile(io.BytesIO(raw_archive), mode="r") as archive:
            if os.path.isdir(session_dir):
                shutil.rmtree(session_dir)
            self._safe_extract_archive(archive, session_dir)
        return True

    def save_session_sync(self, session_dir):
        if not self.enabled:
            return False

        session_blob = self._session_archive_blob(session_dir)
        if not session_blob:
            return False

        payload = {
            "session_key": self.session_key,
            "session_blob": session_blob,
        }
        self._request(
            "POST",
            "?on_conflict=session_key",
            payload=payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        return True

    async def load_session(self, session_dir):
        return await asyncio.to_thread(self.load_session_sync, session_dir)

    async def save_session(self, session_dir):
        return await asyncio.to_thread(self.save_session_sync, session_dir)
