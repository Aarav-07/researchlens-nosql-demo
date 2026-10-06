"""arXiv source adapter (Atom API, no key required).

arXiv's `all:` field searches title, abstract, authors and comments. Results come
back as Atom XML, parsed with the stdlib - no extra dependency.
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

from ..documents import RawPaper
from ..logging_conf import get_logger
from .base import PaperSource, SourceError

log = get_logger(__name__)

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

SORT_FIELDS = {"relevance": "relevance", "date": "submittedDate", "updated": "lastUpdatedDate"}


class ArxivSource(PaperSource):
    name = "arxiv"

    def search(
        self,
        query: str,
        limit: int = 25,
        sort: str = "relevance",
        category: str | None = None,
        **kwargs,
    ) -> list[RawPaper]:
        search_query = f"all:{query}"
        if category:
            search_query = f"({search_query}) AND cat:{category}"

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max(1, min(limit, 200)),  # arXiv caps a page at 200
            "sortBy": SORT_FIELDS.get(sort, "relevance"),
            "sortOrder": "descending",
        }
        response = self._get(self.settings.arxiv_base_url, params)
        papers = self._parse(response.text)
        log.info("arxiv: %d papers for %r", len(papers), query)
        return papers

    def fetch_by_id(self, external_id: str) -> RawPaper | None:
        response = self._get(
            self.settings.arxiv_base_url, {"id_list": external_id, "max_results": 1}
        )
        papers = self._parse(response.text)
        return papers[0] if papers else None

    # ------------------------------------------------------------------ parsing

    def _parse(self, xml_text: str) -> list[RawPaper]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise SourceError(self.name, f"malformed Atom response: {exc}") from exc

        papers: list[RawPaper] = []
        for entry in root.findall("atom:entry", _NS):
            title = _text(entry, "atom:title")
            if not title:
                continue

            abs_url = _text(entry, "atom:id")
            pdf_url = None
            for link in entry.findall("atom:link", _NS):
                if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                    pdf_url = link.get("href")

            authors = [
                {"name": name}
                for name in (
                    _text(a, "atom:name") for a in entry.findall("atom:author", _NS)
                )
                if name
            ]

            categories = [
                c.get("term") for c in entry.findall("atom:category", _NS) if c.get("term")
            ]
            doi = _text(entry, "arxiv:doi")
            journal_ref = _text(entry, "arxiv:journal_ref")

            papers.append(
                RawPaper(
                    title=title,
                    source=self.name,
                    abstract=_text(entry, "atom:summary"),
                    authors=authors,
                    published_date=self._parse_date(_text(entry, "atom:published")),
                    venue=journal_ref or "arXiv",
                    doi=doi,
                    url=abs_url,
                    pdf_url=pdf_url,
                    topics=categories,
                    source_ids={"arxiv": abs_url or ""},
                )
            )
        return papers


def _text(element: ET.Element, path: str) -> str | None:
    found = element.find(path, _NS)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split()) or None
