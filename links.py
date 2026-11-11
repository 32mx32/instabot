"""Распознавание и нормализация ссылок на поддерживаемые платформы."""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

# Символы, которые часто «прилипают» к ссылке в тексте сообщения
_TRAILING_PUNCTUATION = ".,;:!?)]}>»\"'"

_INSTAGRAM_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/"
    r"(?:[A-Za-z0-9_.]+/)?"          # необязательный username: instagram.com/<user>/reel/...
    # ID не может продолжаться символами ID или «:» — иначе в склеенной
    # «.../reel/https://instagram.com/reel/ID» ID-ом стал бы «https»
    r"(reels?|p|tv)/([A-Za-z0-9_-]+)(?![A-Za-z0-9_-]|:)",
    re.IGNORECASE,
)
_INSTAGRAM_SHARE_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?instagram\.com/share/(?:reels?/|p/)?[A-Za-z0-9_-]+/?",
    re.IGNORECASE,
)
_INSTAGRAM_PATH_RE = re.compile(r"/(reels?|p|tv)/([A-Za-z0-9_-]+)", re.IGNORECASE)
_INSTAGRAM_STORIES_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?instagram\.com/stories/", re.IGNORECASE
)
_TIKTOK_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/[^\s]+",
    re.IGNORECASE,
)
_YOUTUBE_SHORTS_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?youtube\.com/shorts/([A-Za-z0-9_-]{5,})",
    re.IGNORECASE,
)

PLATFORM_NAMES = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube Shorts",
}


@dataclass(frozen=True)
class MediaLink:
    platform: str          # instagram | tiktok | youtube
    url: str               # нормализованная ссылка
    kind: str = "video"    # reel | post | tv | share | video
    media_id: Optional[str] = None

    @property
    def needs_resolve(self) -> bool:
        """Ссылки instagram.com/share/... нужно раскрыть редиректом до канонической."""
        return self.platform == "instagram" and self.kind == "share"

    @property
    def label(self) -> str:
        if self.platform == "instagram":
            return "Пост" if self.kind == "post" else "Reels"
        return PLATFORM_NAMES.get(self.platform, "Видео")


def _strip_trailing(url: str) -> str:
    return url.rstrip(_TRAILING_PUNCTUATION)


def _with_scheme(url: str) -> str:
    return url if url.lower().startswith(("http://", "https://")) else f"https://{url}"


def link_from_resolved_url(url: str) -> Optional[MediaLink]:
    """Разбирает URL после редиректа share-ссылки (в т.ч. .../accounts/login/?next=/reel/ID/)."""
    decoded = unquote(url)
    link = extract_link(decoded)
    if link and not link.needs_resolve:
        return link
    match = _INSTAGRAM_PATH_RE.search(decoded)
    if match:
        return extract_link(f"https://www.instagram.com/{match.group(1)}/{match.group(2)}/")
    return None


def is_instagram_stories(text: str) -> bool:
    return bool(_INSTAGRAM_STORIES_RE.search(text))


def extract_link(text: str) -> Optional[MediaLink]:
    """Находит первую поддерживаемую ссылку в любом месте текста."""
    if not text:
        return None

    # share-ссылки проверяем первыми: иначе «share/» примется за username
    match = _INSTAGRAM_SHARE_RE.search(text)
    if match:
        return MediaLink("instagram", _with_scheme(_strip_trailing(match.group(0))), "share")

    match = _INSTAGRAM_RE.search(text)
    if match:
        section, code = match.group(1).lower(), match.group(2)
        if section in ("reel", "reels"):
            kind, path = "reel", "reel"
        elif section == "tv":
            kind, path = "tv", "tv"
        else:
            kind, path = "post", "p"
        # Нормализуем до канонического вида: без username, igsh и прочих параметров
        return MediaLink("instagram", f"https://www.instagram.com/{path}/{code}/", kind, code)

    match = _YOUTUBE_SHORTS_RE.search(text)
    if match:
        code = match.group(1)
        return MediaLink("youtube", f"https://www.youtube.com/shorts/{code}", "video", code)

    match = _TIKTOK_RE.search(text)
    if match:
        return MediaLink("tiktok", _with_scheme(_strip_trailing(match.group(0))), "video")

    return None
