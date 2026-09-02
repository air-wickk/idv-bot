import bs4
import re

from tweety.http import MIGRATION_REGEX, Request
from tweety.transaction import find_on_demand_file


def patch_tweety_home_page_fallback():
    if getattr(Request.get_home_html, "_idv_home_page_patch", False):
        return

    original_get_home_html = Request.get_home_html

    async def get_home_html_with_fallback(self):
        home_page = None
        headers = self._get_request_headers()
        if headers.get("authorization"):
            del headers["authorization"]

        try:
            response = await self._session.request(
                method="GET",
                url="https://x.com/?mx=2",
                headers=headers,
            )

            if response.status_code not in range(200, 300):
                response = await self._session.request(
                    method="GET",
                    url=self._builder.URL_HOME_PAGE,
                    headers=headers,
                )

            home_page = bs4.BeautifulSoup(response.content, "lxml")
            migration_url = home_page.select_one("meta[http-equiv='refresh']")
            migration_redirection_url = re.search(MIGRATION_REGEX, str(migration_url)) or re.search(MIGRATION_REGEX, str(response.content))

            if migration_redirection_url:
                response = await self._session.request(
                    method="GET",
                    url=migration_redirection_url.group(0),
                    headers=headers,
                )
                home_page = bs4.BeautifulSoup(response.content, "lxml")

            migration_form = home_page.select_one("form[name='f']") or home_page.select_one("form[action='https://x.com/x/migrate']")
            if migration_form:
                url = migration_form.attrs.get("action", "https://x.com/x/migrate")
                method = migration_form.attrs.get("method", "POST")
                request_payload = {
                    input_field.get("name"): input_field.get("value")
                    for input_field in migration_form.select("input")
                }
                response = await self._session.request(
                    method=method,
                    url=url,
                    data=request_payload,
                    headers=headers,
                )
                home_page = bs4.BeautifulSoup(response.content, "lxml")

            if home_page and not find_on_demand_file(str(home_page)):
                response = await self._session.request(
                    method="GET",
                    url="https://x.com/home",
                    headers=headers,
                )
                if response.status_code in range(200, 300):
                    home_page = bs4.BeautifulSoup(response.content, "lxml")

        except Exception as twitter_home_error:
            raise ValueError(f"Unable to get Twitter Home Page : {str(twitter_home_error)}")

        return home_page

    get_home_html_with_fallback._idv_home_page_patch = True
    Request.get_home_html = get_home_html_with_fallback


patch_tweety_home_page_fallback()