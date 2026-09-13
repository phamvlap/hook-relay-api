from urllib.parse import urlparse


def validate_url(url: str) -> bool:
    parsed_url = urlparse(url)

    if parsed_url.scheme not in ("http", "https"):
        return False

    return bool(parsed_url.netloc and parsed_url.path)
