from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import Dict, Optional


def get_page_info(url: str, soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """
    Extracts the name (title) and description from an HTML document.
    Cascades through standard HTML tags, Open Graph metadata, and URL pathing
    to ensure a reliable structural fallback.
    """
    name: Optional[str] = None
    description: Optional[str] = None

    title_tag = soup.find("title")
    if title_tag:
        name = title_tag.get_text(strip=True)

    if not name:
        og_title = soup.find("meta", property="og:title") or soup.find(
            "meta", attrs={"name": "og:title"}
        )
        if og_title:
            name = og_title.get("content", "").strip()

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        description = meta_desc.get("content", "").strip()

    if not description:
        og_desc = soup.find("meta", property="og:description") or soup.find(
            "meta", attrs={"name": "og:description"}
        )
        if og_desc:
            description = og_desc.get("content", "").strip()

    if not name:
        parsed = urlparse(url)
        domain = (
            parsed.netloc[4:] if parsed.netloc.startswith("www.") else parsed.netloc
        )
        path = parsed.path.strip("/")

        if path:
            name = path.split("/")[-1].replace("-", " ").replace("_", " ").title()
        else:
            name = domain

    return {"name": name or None, "description": description or None}
