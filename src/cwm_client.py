from __future__ import annotations

import requests

from cwm_constants import BASE_URL, DEFAULT_HEADERS, DEFAULT_TIMEOUT_S


class CiweimaoClient:
    def __init__(self, *, session: requests.Session | None = None, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.session = session or requests.Session()
        self.timeout_s = int(timeout_s)
        self.session.headers.update(DEFAULT_HEADERS)

    def search_name(self, name: str, page: int = 1) -> str:
        url = f"{BASE_URL}/get-search-book-list/0-0-0-0-0-0/全部/{name}/{page}"
        resp = self.session.get(url, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.text

    def get_book_details(self, book_id: int) -> str:
        url = f"{BASE_URL}/book/{int(book_id)}"
        resp = self.session.get(url, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.text

