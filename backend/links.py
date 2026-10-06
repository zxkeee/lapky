import re
from urllib.parse import urlparse

IBAN_RE = re.compile(r"^UA\d{27}$")
CARD_RE = re.compile(r"^\d{16}$")
HTTPS_RE = re.compile(r"^https://[^\s/]+\.[^\s]+$")

_LINK_DOMAINS = {
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "instagram": ("instagram.com", "instagr.am"),
    "telegram": ("t.me", "telegram.me", "telegram.org"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "viber": ("viber.com", "invite.viber.com"),
}
_FUND_DOMAINS = {
    "monobank_jar": ("send.monobank.ua", "base.monobank.ua"),
    "privat": ("privatbank.ua", "next.privat24.ua", "privat24.ua"),
    "paypal": ("paypal.com", "paypal.me"),
    "patreon": ("patreon.com",),
}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def detect_link_kind(url: str) -> str:
    host = _host(url)
    for kind, domains in _LINK_DOMAINS.items():
        if _matches(host, domains):
            return kind
    return "website" if host else "other"


def normalize_requisites(value: str) -> str:
    compact = re.sub(r"[\s-]", "", value).upper()
    if IBAN_RE.match(compact) or CARD_RE.match(compact):
        return compact
    return value.strip()


def detect_fundraiser_kind(value: str) -> str:
    value = normalize_requisites(value)
    if value.startswith(("http://", "https://")):
        host = _host(value)
        for kind, domains in _FUND_DOMAINS.items():
            if _matches(host, domains):
                return kind
        return "other"
    if IBAN_RE.match(value):
        return "iban"
    if CARD_RE.match(value):
        return "card"
    return "other"


def normalize_url(value: str, kind_hint: str | None = None) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if v.startswith("@") or (kind_hint in ("instagram", "telegram", "facebook") and "/" not in v and "." not in v):
        handle = v.lstrip("@")
        base = {"instagram": "https://instagram.com/", "telegram": "https://t.me/",
                "facebook": "https://facebook.com/"}.get(kind_hint or "", "https://t.me/")
        return base + handle
    if v.startswith("http://"):
        v = "https://" + v[len("http://"):]
    elif not v.startswith("https://"):
        v = "https://" + v
    return v if HTTPS_RE.match(v) else None
