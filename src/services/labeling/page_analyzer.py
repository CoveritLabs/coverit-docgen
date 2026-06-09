from bs4 import BeautifulSoup
from urllib.parse import urlparse


def get_page_info(url: str, soup: BeautifulSoup) -> dict:
    name = None
    description = None

    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        name = title_tag.get_text(strip=True)

    if not name:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content", "").strip():
            name = og["content"].strip()

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content", "").strip():
        description = meta_desc["content"].strip()

    if not description:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content", "").strip():
            description = og_desc["content"].strip()

    if not name:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        path = parsed.path.strip("/")
        name = (
            path.split("/")[-1].replace("-", " ").replace("_", " ").title()
            if path
            else domain
        )

    return {"name": name, "description": description}
