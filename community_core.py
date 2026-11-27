"""
community_core.py - 자동 고정 메시지(#8), SNS 링크 미리보기/추적 제거(#12),
동시 입장(Raid) 비상 방어(#42), 릴레이 소설(#48), 임시 음성방(#11),
예약 이벤트 신청표(RSVP & 자동 리마인드) 코어 로직 및 데이터 헬퍼
"""

from __future__ import annotations

import collections
import datetime
import re
import time
import urllib.parse
import uuid
from typing import Optional

import core

# ==========================================
# 1. 📌 자동 고정 메시지 (Sticky Message - #8)
# ==========================================
STICKY_COLOR_MAP: dict[str, int] = {
    "gold": 0xF1C40F,
    "blue": 0x3498DB,
    "green": 0x2ECC71,
    "pink": 0xFF69B4,
    "purple": 0x9B59B6,
    "red": 0xE74C3C,
}

STICKY_COLOR_LABELS: dict[str, str] = {
    "gold": "🌟 골드 (노랑)",
    "blue": "💙 블루 (파랑)",
    "green": "💚 그린 (초록)",
    "pink": "🩷 핑크 (분홍)",
    "purple": "💜 퍼플 (보라)",
    "red": "❤️ 레드 (빨강)",
}


def get_guild_stickies(data: dict, guild_id: int) -> dict[str, dict]:
    root = core.as_dict(data.get("sticky_messages"))
    return core.as_dict(root.get(str(guild_id)))


def get_sticky_config(data: dict, guild_id: int, channel_id: int) -> Optional[dict]:
    g_map = get_guild_stickies(data, guild_id)
    cfg = g_map.get(str(channel_id))
    return cfg if isinstance(cfg, dict) else None


STICKY_TRIGGER_MODE_LABELS: dict[str, str] = {
    "count": "💬 메시지 개수 기준 (N개 메시지 이후 즉시)",
    "delay": "⏱️ 마지막 메시지 후 대기 (N초 동안 조용하면)",
    "both": "🔗 복합 조건 (N개 이상 쌓인 뒤 N초 조용하면)",
}


def format_sticky_trigger_summary(cfg: dict | None) -> str:
    if not isinstance(cfg, dict):
        return "미설정"
    mode = str(cfg.get("trigger_mode") or "count")
    iv = max(1, int(cfg.get("interval", 1) or 1))
    dl = max(0, int(cfg.get("delay_sec", 0) or 0))
    cd = max(2, int(cfg.get("cooldown_sec", 3) or 3))
    if mode == "delay" and dl > 0:
        return f"⏱️ 마지막 메시지로부터 `{dl}초` 뒤 갱신 (최소 쿨타임 `{cd}초`)"
    if mode == "both" and dl > 0:
        return f"🔗 `{iv}개` 메시지 이후 + 마지막 메시지 `{dl}초` 뒤 갱신"
    return f"💬 `{iv}개` 메시지 이후 즉시 갱신 (최소 쿨타임 `{cd}초`)"


def set_sticky_config(
    data: dict,
    guild_id: int,
    channel_id: int,
    title: str,
    content: str,
    *,
    color: str = "gold",
    interval: int = 1,
    delay_sec: int = 0,
    trigger_mode: str = "count",
    cooldown_sec: int = 3,
    updated_by: int = 0,
    last_message_id: Optional[int] = None,
) -> dict:
    g_map = core.ensure_dict_path(data, "sticky_messages", str(guild_id))
    prev = g_map.get(str(channel_id)) if isinstance(g_map.get(str(channel_id)), dict) else {}
    safe_color = color if color in STICKY_COLOR_MAP else "gold"
    safe_interval = max(1, min(100, int(interval or prev.get("interval") or 1)))
    raw_delay = delay_sec if delay_sec is not None else int(prev.get("delay_sec", 0) or 0)
    safe_delay = max(0, min(600, int(raw_delay or 0)))
    safe_mode = trigger_mode if trigger_mode in STICKY_TRIGGER_MODE_LABELS else str(prev.get("trigger_mode") or ("delay" if safe_delay > 0 and safe_interval == 1 else "count"))
    if safe_mode in ("delay", "both") and safe_delay <= 0:
        safe_delay = 5
    safe_cd = max(2, min(300, int(cooldown_sec or prev.get("cooldown_sec") or 3)))
    entry = {
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "title": (title or "").strip()[:120],
        "content": (content or "").strip()[:1800],
        "color": safe_color,
        "interval": safe_interval,
        "delay_sec": safe_delay,
        "trigger_mode": safe_mode,
        "cooldown_sec": safe_cd,
        "last_message_id": last_message_id if last_message_id is not None else prev.get("last_message_id"),
        "msg_count": 0,
        "last_posted_ts": float(prev.get("last_posted_ts", 0.0) or 0.0),
        "enabled": bool(prev.get("enabled", True)),
        "updated_by": int(updated_by or 0),
        "updated_at": datetime.datetime.now(core.KST).isoformat(),
    }
    g_map[str(channel_id)] = entry
    return entry


def remove_sticky_config(data: dict, guild_id: int, channel_id: int) -> Optional[dict]:
    g_map = core.ensure_dict_path(data, "sticky_messages", str(guild_id))
    c_key = str(channel_id)
    removed = g_map.pop(c_key, None)
    return removed if isinstance(removed, dict) else None


def toggle_sticky_config(data: dict, guild_id: int, channel_id: int, enabled: bool) -> Optional[dict]:
    cfg = get_sticky_config(data, guild_id, channel_id)
    if not cfg:
        return None
    cfg["enabled"] = bool(enabled)
    cfg["updated_at"] = datetime.datetime.now(core.KST).isoformat()
    return cfg


# ==========================================
# 2. 🔗 SNS 링크 미리보기 개선 & 추적 파라미터 제거 (#12)
# ==========================================
GLOBAL_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id", "utm_name",
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "igsh", "si", "pp", "feature", "ab_channel",
    "ref_src", "ref_url", "sender_device", "is_from_webapp", "_r", "_t",
    "share_id", "rdid", "share_url", "usp",
}
TWITTER_TRACKING_PARAMS = {"s", "t", "cxt"}
SPOTIFY_TRACKING_PARAMS = {"nd", "context"}
NAVER_TRACKING_PARAMS = {"NaPm", "n_media", "n_query", "n_rank", "n_ad_group", "n_ad", "n_campaign_type"}

CODE_BLOCK_RE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)
SPOILER_RE = re.compile(r"\|\|.*?\|\|", re.DOTALL)
ANGLE_URL_RE = re.compile(r"<https?://[^>\s]+>")
RAW_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`|]+")


def get_link_preview_config(data: dict, guild_id: int) -> dict:
    root = core.as_dict(data.get("link_preview_configs"))
    raw = core.as_dict(root.get(str(guild_id)))
    return {
        "enabled": bool(raw.get("enabled", False)),
        "sns_preview": bool(raw.get("sns_preview", True)),
        "strip_tracking": bool(raw.get("strip_tracking", True)),
        "suppress_original": bool(raw.get("suppress_original", True)),
        "ignored_channels": [int(c) for c in (raw.get("ignored_channels") or []) if str(c).isdigit()],
        "updated_at": raw.get("updated_at"),
    }


def save_link_preview_config(data: dict, guild_id: int, cfg: dict) -> dict:
    root = core.ensure_dict_path(data, "link_preview_configs")
    entry = {
        "enabled": bool(cfg.get("enabled", False)),
        "sns_preview": bool(cfg.get("sns_preview", True)),
        "strip_tracking": bool(cfg.get("strip_tracking", True)),
        "suppress_original": bool(cfg.get("suppress_original", True)),
        "ignored_channels": sorted({int(c) for c in (cfg.get("ignored_channels") or []) if str(c).isdigit()}),
        "updated_at": datetime.datetime.now(core.KST).isoformat(),
    }
    root[str(guild_id)] = entry
    return entry


def _strip_ignored_segments(text: str) -> str:
    cleaned = CODE_BLOCK_RE.sub(" ", text)
    cleaned = SPOILER_RE.sub(" ", cleaned)
    cleaned = ANGLE_URL_RE.sub(" ", cleaned)
    return cleaned


def _trim_trailing_punct(url: str) -> str:
    while url and url[-1] in ".,!?;:":
        url = url[:-1]
    return url


def transform_single_url(
    raw_url: str,
    *,
    sns_preview: bool = True,
    strip_tracking: bool = True,
) -> Optional[dict]:
    url = _trim_trailing_punct(raw_url)
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    host = parsed.netloc.lower()
    path = parsed.path or ""
    new_host = host
    service_label = None
    platform_key = "web"
    is_twitter = False

    if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "mobile.x.com"):
        is_twitter = True
        if sns_preview and re.match(r"^/(?:[^/]+|i/web)/status/\d+", path):
            new_host = "fxtwitter.com"
            service_label = "X (Twitter)"
            platform_key = "x"
    elif host in ("instagram.com", "www.instagram.com", "m.instagram.com"):
        if sns_preview and re.match(r"^/(?:[^/]+/)?(p|reel|reels|tv|stories|share)/", path):
            new_host = "oginstagram.com"
            service_label = "Instagram"
            platform_key = "instagram"
    elif host in ("tiktok.com", "www.tiktok.com", "m.tiktok.com", "vt.tiktok.com", "vm.tiktok.com"):
        if sns_preview and path and path != "/":
            if host == "vt.tiktok.com":
                new_host = "vt.vxtiktok.com"
            elif host == "vm.tiktok.com":
                new_host = "vm.vxtiktok.com"
            else:
                new_host = "vxtiktok.com"
            service_label = "TikTok"
            platform_key = "tiktok"
    elif host in ("threads.net", "www.threads.net", "threads.com", "www.threads.com"):
        if sns_preview and "/post/" in path:
            new_host = "vxthreads.net"
            service_label = "Threads"
            platform_key = "threads"
    elif host in ("reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "m.reddit.com", "redd.it"):
        if sns_preview and ("/comments/" in path or "/s/" in path or host == "redd.it"):
            new_host = "rxddit.com" if host != "redd.it" else host
            service_label = "Reddit"
            platform_key = "reddit"
    elif host in ("pixiv.net", "www.pixiv.net"):
        if sns_preview and "/artworks/" in path:
            new_host = "phixiv.net"
            service_label = "Pixiv"
            platform_key = "pixiv"
    elif host in ("bsky.app", "www.bsky.app"):
        if sns_preview and "/profile/" in path and "/post/" in path:
            new_host = "bskyx.app"
            service_label = "Bluesky"
            platform_key = "bluesky"
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        if sns_preview and path.startswith("/shorts/"):
            service_label = "YouTube Shorts"
            platform_key = "youtube"
        elif host == "youtu.be" or path.startswith("/watch"):
            platform_key = "youtube"
    elif host in ("facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"):
        if sns_preview and (host == "fb.watch" or any(seg in path for seg in ("/reel/", "/videos/", "/posts/", "/share/", "/watch", "/photo"))):
            new_host = "facebed.com" if host != "fb.watch" else host
            service_label = "Facebook"
            platform_key = "facebook"
    elif host in ("pinterest.com", "www.pinterest.com", "kr.pinterest.com", "pin.it"):
        if sns_preview and (host == "pin.it" or "/pin/" in path):
            service_label = "Pinterest"
            platform_key = "pinterest"

    # 추적 파라미터 정리
    new_query = parsed.query
    stripped_params: list[str] = []
    if strip_tracking and parsed.query:
        drop_keys = set(GLOBAL_TRACKING_PARAMS)
        if is_twitter:
            drop_keys |= TWITTER_TRACKING_PARAMS
        if "spotify.com" in host:
            drop_keys |= SPOTIFY_TRACKING_PARAMS
        if host.endswith("naver.com"):
            drop_keys |= NAVER_TRACKING_PARAMS

        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        kept_pairs = []
        for k, v in pairs:
            if k in drop_keys or k.lower().startswith("utm_"):
                stripped_params.append(k)
            else:
                kept_pairs.append((k, v))
        new_query = urllib.parse.urlencode(kept_pairs, doseq=True)

    scheme = "https" if service_label else parsed.scheme
    cleaned_url = urllib.parse.urlunsplit((scheme, new_host, parsed.path, new_query, parsed.fragment))
    canonical_url = urllib.parse.urlunsplit((scheme, host, parsed.path, new_query, parsed.fragment))
    if cleaned_url == url and not service_label:
        return None

    return {
        "original": url,
        "cleaned": cleaned_url,
        "canonical": canonical_url,
        "kind": "sns" if service_label else "tracking",
        "platform": platform_key,
        "service": service_label or host,
        "stripped_params": stripped_params,
    }


def extract_and_transform_urls(text: str, cfg: dict, max_items: int = 3) -> list[dict]:
    if not text or not cfg.get("enabled", False):
        return []
    sns_preview = bool(cfg.get("sns_preview", True))
    strip_tracking = bool(cfg.get("strip_tracking", True))
    if not sns_preview and not strip_tracking:
        return []

    sanitized = _strip_ignored_segments(text)
    results: list[dict] = []
    seen_cleaned: set[str] = set()
    for match in RAW_URL_RE.finditer(sanitized):
        item = transform_single_url(
            match.group(0),
            sns_preview=sns_preview,
            strip_tracking=strip_tracking,
        )
        if not item:
            continue
        if item["cleaned"] in seen_cleaned:
            continue
        seen_cleaned.add(item["cleaned"])
        results.append(item)
        if len(results) >= max_items:
            break
    return results


_LINK_TOKEN_RE = re.compile(
    r"(?P<code>```.*?```|`[^`\n]+`)"
    r"|(?P<spoiler>\|\|.*?\|\|)"
    r"|(?P<angle><https?://[^>\s]+>)"
    r"|(?P<masked>\[[^\]]+\]\(https?://[^)\s]+\))"
    r"|(?P<url>https?://[^\s<>()\[\]\"'`|]+)",
    re.DOTALL,
)


def replace_urls_with_clean_links(
    text: str,
    cfg: dict,
    max_items: int = 3,
    *,
    canonical_plain: bool = False,
) -> tuple[str, list[dict]]:
    """
    원본 메시지 본문의 텍스트·코드블록·스포일러·<링크>·기존 마크다운 링크는 그대로 보존하면서,
    변환 대상 raw URL만 깔끔하게 치환합니다.
    - canonical_plain=True: Components V2 상단 표시용으로 추적 파라미터만 제거된 공식 클린 URL로 치환
    - canonical_plain=False: 프록시 임베드용 숨김 트리거(<공식클린URL>[\u2800](프록시URL))로 치환
      (Discord는 표시 텍스트가 https://...인 마스킹 링크를 피싱 방지로 차단하므로 <공식URL> + 비가시 브레일 공백 마스킹 사용)
    """
    if not text or not cfg.get("enabled", False):
        return text, []
    sns_preview = bool(cfg.get("sns_preview", True))
    strip_tracking = bool(cfg.get("strip_tracking", True))
    if not sns_preview and not strip_tracking:
        return text, []

    items: list[dict] = []

    def _repl(match: re.Match) -> str:
        raw_url = match.group("url")
        if not raw_url or len(items) >= max_items:
            return match.group(0)
        item = transform_single_url(
            raw_url,
            sns_preview=sns_preview,
            strip_tracking=strip_tracking,
        )
        if not item:
            return match.group(0)
        items.append(item)
        trailing = raw_url[len(item["original"]):]
        if canonical_plain or item["canonical"] == item["cleaned"]:
            return f"{item['canonical']}{trailing}"
        return f"<{item['canonical']}>[\u2800]({item['cleaned']}){trailing}"

    replaced = _LINK_TOKEN_RE.sub(_repl, text)
    return replaced, items


# ==========================================
# 3. 🚨 동시 입장(Raid) · 봇 테러 비상 방어 (#42)
# ==========================================
RAID_ACTION_LABELS: dict[str, str] = {
    "timeout": "⏳ 60분 타임아웃(활동 제한)",
    "kick": "👢 즉시 추방 (Kick)",
    "quarantine": "🔒 격리 역할 부여 (신규 격리)",
}


def get_raid_defense_config(data: dict, guild_id: int) -> dict:
    root = core.as_dict(data.get("raid_defense_configs"))
    raw = core.as_dict(root.get(str(guild_id)))
    return {
        "enabled": bool(raw.get("enabled", False)),
        "threshold": max(3, min(30, int(raw.get("threshold", 5) or 5))),
        "window_sec": max(5, min(60, int(raw.get("window_sec", 10) or 10))),
        "action": raw.get("action") if raw.get("action") in RAID_ACTION_LABELS else "timeout",
        "timeout_min": max(5, min(10080, int(raw.get("timeout_min", 60) or 60))),
        "quarantine_role_id": int(raw["quarantine_role_id"]) if str(raw.get("quarantine_role_id", "")).isdigit() else None,
        "min_account_age_days": max(0, min(365, int(raw.get("min_account_age_days", 0) or 0))),
        "pause_invites": bool(raw.get("pause_invites", True)),
        "alert_channel_id": int(raw["alert_channel_id"]) if str(raw.get("alert_channel_id", "")).isdigit() else None,
        "lockdown_active": bool(raw.get("lockdown_active", False)),
        "lockdown_reason": str(raw.get("lockdown_reason") or ""),
        "lockdown_started_at": raw.get("lockdown_started_at"),
        "lockdown_by": str(raw.get("lockdown_by") or ""),
        "invites_paused_by_bot": bool(raw.get("invites_paused_by_bot", False)),
        "blocked_log": list(raw.get("blocked_log") or [])[-25:],
        "updated_at": raw.get("updated_at"),
    }


def save_raid_defense_config(data: dict, guild_id: int, cfg: dict) -> dict:
    root = core.ensure_dict_path(data, "raid_defense_configs")
    entry = {
        "enabled": bool(cfg.get("enabled", False)),
        "threshold": max(3, min(30, int(cfg.get("threshold", 5) or 5))),
        "window_sec": max(5, min(60, int(cfg.get("window_sec", 10) or 10))),
        "action": cfg.get("action") if cfg.get("action") in RAID_ACTION_LABELS else "timeout",
        "timeout_min": max(5, min(10080, int(cfg.get("timeout_min", 60) or 60))),
        "quarantine_role_id": int(cfg["quarantine_role_id"]) if str(cfg.get("quarantine_role_id", "")).isdigit() else None,
        "min_account_age_days": max(0, min(365, int(cfg.get("min_account_age_days", 0) or 0))),
        "pause_invites": bool(cfg.get("pause_invites", True)),
        "alert_channel_id": int(cfg["alert_channel_id"]) if str(cfg.get("alert_channel_id", "")).isdigit() else None,
        "lockdown_active": bool(cfg.get("lockdown_active", False)),
        "lockdown_reason": str(cfg.get("lockdown_reason") or "")[:200],
        "lockdown_started_at": cfg.get("lockdown_started_at"),
        "lockdown_by": str(cfg.get("lockdown_by") or "")[:80],
        "invites_paused_by_bot": bool(cfg.get("invites_paused_by_bot", False)),
        "blocked_log": [b for b in (cfg.get("blocked_log") or []) if isinstance(b, dict)][-25:],
        "updated_at": datetime.datetime.now(core.KST).isoformat(),
    }
    root[str(guild_id)] = entry
    return entry


def append_raid_blocked_log(cfg: dict, user_id: int, user_name: str, action: str, reason: str) -> None:
    logs = list(cfg.get("blocked_log") or [])
    logs.append({
        "user_id": int(user_id),
        "user_name": str(user_name)[:64],
        "action": str(action)[:32],
        "reason": str(reason)[:120],
        "ts": datetime.datetime.now(core.KST).strftime("%m-%d %H:%M:%S"),
    })
    cfg["blocked_log"] = logs[-25:]


class RaidJoinTracker:
    """서버별 최근 입장 시각/유저 슬라이딩 윈도우 추적기"""

    def __init__(self):
        self._joins: dict[int, collections.deque[tuple[float, int]]] = {}

    def record_join(
        self,
        guild_id: int,
        user_id: int,
        window_sec: int,
        threshold: int,
        now_ts: Optional[float] = None,
    ) -> tuple[bool, list[int]]:
        now = float(now_ts if now_ts is not None else time.monotonic())
        dq = self._joins.setdefault(int(guild_id), collections.deque())
        cutoff = now - max(1, int(window_sec))
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        dq.append((now, int(user_id)))
        unique_ids: list[int] = []
        seen: set[int] = set()
        for _, uid in dq:
            if uid not in seen:
                seen.add(uid)
                unique_ids.append(uid)
        triggered = len(unique_ids) >= max(2, int(threshold))
        return triggered, unique_ids

    def current_rate(self, guild_id: int, window_sec: int, now_ts: Optional[float] = None) -> int:
        now = float(now_ts if now_ts is not None else time.monotonic())
        dq = self._joins.get(int(guild_id))
        if not dq:
            return 0
        cutoff = now - max(1, int(window_sec))
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        return len({uid for _, uid in dq})

    def clear_guild(self, guild_id: int) -> None:
        self._joins.pop(int(guild_id), None)


RAID_TRACKER = RaidJoinTracker()


# ==========================================
# 4. ✍️ 한 줄씩 이어 쓰는 릴레이 소설 (#48)
# ==========================================
def _ensure_guild_relay_root(data: dict, guild_id: int) -> dict:
    g_root = core.ensure_dict_path(data, "relay_novels", str(guild_id))
    if not isinstance(g_root.get("active_channels"), dict):
        g_root["active_channels"] = {}
    if not isinstance(g_root.get("completed"), list):
        g_root["completed"] = []
    return g_root


def get_active_relay_novel(data: dict, guild_id: int, channel_id: int = 0) -> Optional[dict]:
    g_root = core.as_dict(core.as_dict(data.get("relay_novels")).get(str(guild_id)))
    act = core.as_dict(g_root.get("active_channels"))
    if channel_id:
        story = act.get(str(channel_id))
        return story if isinstance(story, dict) else None
    for story in act.values():
        if isinstance(story, dict):
            return story
    return None


def get_active_relay(data: dict, guild_id: int, channel_id: int = 0) -> Optional[dict]:
    """대시보드 및 구버전 호환용: 현재 채널 우선 조회 후 없으면 서버 내 활성 릴레이 소설 반환"""
    if channel_id:
        story = get_active_relay_novel(data, guild_id, channel_id)
        if story:
            return story
    return get_active_relay_novel(data, guild_id, 0)


def get_completed_relay_novels(data: dict, guild_id: int) -> list[dict]:
    g_root = core.as_dict(core.as_dict(data.get("relay_novels")).get(str(guild_id)))
    comp = g_root.get("completed")
    return [c for c in comp if isinstance(c, dict)] if isinstance(comp, list) else []


def get_relay_completed_list(data: dict, guild_id: int) -> list[dict]:
    """호환용 별칭: 완결 릴레이 소설 목록 반환"""
    return get_completed_relay_novels(data, guild_id)


def get_relay_archives(data: dict, guild_id: int) -> list[dict]:
    """대시보드 호환용 별칭: 완결 릴레이 소설 서재 목록 반환"""
    return get_completed_relay_novels(data, guild_id)


def start_relay_novel(
    data: dict,
    guild_id: int,
    channel_id: int,
    creator_id: int,
    creator_name: str,
    title: str,
    first_sentence: str,
    *,
    max_turns: int = 10,
    blind_mode: bool = True,
    allow_consecutive: bool = False,
) -> tuple[bool, str, Optional[dict]]:
    g_root = _ensure_guild_relay_root(data, guild_id)
    ch_key = str(channel_id)
    if ch_key in g_root["active_channels"]:
        existing = g_root["active_channels"][ch_key]
        return False, f"이미 이 채널에서 『**{existing.get('title', '릴레이 소설')}**』이 진행 중입니다!", None

    clean_title = (title or "").strip()[:80]
    clean_first = " ".join((first_sentence or "").strip().splitlines())[:280]
    if not clean_title or not clean_first:
        return False, "제목과 첫 문장을 모두 입력해 주세요.", None

    now_iso = datetime.datetime.now(core.KST).isoformat()
    story = {
        "id": uuid.uuid4().hex[:8],
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "title": clean_title,
        "creator_id": int(creator_id),
        "creator_name": str(creator_name)[:64],
        "max_turns": max(3, min(30, int(max_turns or 10))),
        "blind_mode": bool(blind_mode),
        "allow_consecutive": bool(allow_consecutive),
        "message_id": None,
        "turns": [
            {
                "user_id": int(creator_id),
                "user_name": str(creator_name)[:64],
                "text": clean_first,
                "ts": now_iso,
            }
        ],
        "created_at": now_iso,
    }
    g_root["active_channels"][ch_key] = story
    g_root["updated_at"] = now_iso
    return True, "시작 완료", story


def append_relay_turn(
    data: dict,
    guild_id: int,
    channel_id: int,
    user_id: int,
    user_name: str,
    sentence: str,
) -> tuple[bool, str, Optional[dict], bool]:
    """
    Returns (ok, message, story_or_completed_dict, is_completed)
    """
    g_root = _ensure_guild_relay_root(data, guild_id)
    ch_key = str(channel_id)
    story = g_root["active_channels"].get(ch_key)
    if not isinstance(story, dict):
        return False, "현재 이 채널에서 진행 중인 릴레이 소설이 없습니다.", None, False

    turns = story.get("turns") or []
    if not story.get("allow_consecutive", False) and turns:
        if int(turns[-1].get("user_id", 0)) == int(user_id):
            return False, "직전 문장을 본인이 작성했어요! 다른 멤버가 한 줄 쓴 뒤 이어서 참여해 주세요.", story, False

    clean_line = " ".join((sentence or "").strip().splitlines())[:280]
    if len(clean_line) < 2:
        return False, "최소 2글자 이상의 문장을 입력해 주세요.", story, False

    now_iso = datetime.datetime.now(core.KST).isoformat()
    turns.append({
        "user_id": int(user_id),
        "user_name": str(user_name)[:64],
        "text": clean_line,
        "ts": now_iso,
    })
    story["turns"] = turns
    g_root["updated_at"] = now_iso

    if len(turns) >= int(story.get("max_turns", 10) or 10):
        completed = _finalize_relay_story(g_root, ch_key, story, now_iso)
        return True, "완결", completed, True

    return True, "등록", story, False


def finish_relay_novel_early(
    data: dict,
    guild_id: int,
    channel_id: int,
) -> tuple[bool, str, Optional[dict]]:
    g_root = _ensure_guild_relay_root(data, guild_id)
    ch_key = str(channel_id)
    story = g_root["active_channels"].get(ch_key)
    if not isinstance(story, dict):
        return False, "현재 이 채널에서 진행 중인 릴레이 소설이 없습니다.", None
    turns = story.get("turns") or []
    if len(turns) < 2:
        return False, "최소 2줄 이상 작성되어야 소설을 완결할 수 있습니다.", story
    now_iso = datetime.datetime.now(core.KST).isoformat()
    completed = _finalize_relay_story(g_root, ch_key, story, now_iso)
    return True, "완결 완료", completed


def cancel_relay_novel(data: dict, guild_id: int, channel_id: int) -> Optional[dict]:
    g_root = _ensure_guild_relay_root(data, guild_id)
    ch_key = str(channel_id)
    removed = g_root["active_channels"].pop(ch_key, None)
    if isinstance(removed, dict):
        g_root["updated_at"] = datetime.datetime.now(core.KST).isoformat()
        return removed
    return None


def _finalize_relay_story(g_root: dict, ch_key: str, story: dict, now_iso: str) -> dict:
    g_root["active_channels"].pop(ch_key, None)
    completed = {
        "id": story.get("id", uuid.uuid4().hex[:8]),
        "title": story.get("title", "무제"),
        "creator_id": story.get("creator_id", 0),
        "creator_name": story.get("creator_name", "작가"),
        "blind_mode": bool(story.get("blind_mode", True)),
        "turns": list(story.get("turns") or []),
        "completed_at": now_iso,
    }
    comp_list = list(g_root.get("completed") or [])
    comp_list.insert(0, completed)
    g_root["completed"] = comp_list[:30]
    g_root["updated_at"] = now_iso
    return completed


def format_relay_progress_bar(cur: int, total: int, width: int = 10) -> str:
    total = max(1, int(total))
    cur = max(0, min(total, int(cur)))
    filled = round((cur / total) * width)
    return "🟦" * filled + "⬜" * (width - filled)


def format_relay_full_story(story: dict) -> str:
    turns = story.get("turns") or []
    lines = []
    for idx, t in enumerate(turns, start=1):
        lines.append(f"**{idx}.** {t.get('text', '')}  *(— {t.get('user_name', '작가')})*")
    joined = "\n".join(lines)
    if len(joined) > 3600:
        joined = joined[:3580] + "\n... *(이하 생략)*"
    return joined


# ==========================================
# 5. 🔊 임시 음성방 자동 생성기 — Join to Create (#11)
# ==========================================
DEFAULT_TEMP_VOICE_TEMPLATE = "🔊 {user}님의 음성방"


def format_temp_voice_room_name(template: str, user_name: str, index: int = 1) -> str:
    tpl = (template or DEFAULT_TEMP_VOICE_TEMPLATE).strip()
    if "{user}" not in tpl and "{name}" not in tpl:
        tpl = f"{tpl} · {{user}}"
    safe_user = (user_name or "멤버").strip()[:32]
    rendered = (
        tpl.replace("{user}", safe_user)
        .replace("{name}", safe_user)
        .replace("{num}", str(max(1, int(index or 1))))
    )
    return rendered.strip()[:95] or f"🔊 {safe_user}님의 음성방"


def _normalize_generator_channel_ids(raw_cfg: dict) -> list[int]:
    ids: list[int] = []
    raw_list = raw_cfg.get("generator_channel_ids")
    if isinstance(raw_list, list):
        for item in raw_list:
            if str(item or "").isdigit():
                cid = int(item)
                if cid > 0 and cid not in ids:
                    ids.append(cid)
    single_gen = raw_cfg.get("generator_channel_id")
    if str(single_gen or "").isdigit():
        scid = int(single_gen)
        if scid > 0 and scid not in ids:
            ids.insert(0, scid)
    return ids[:10]


def is_temp_voice_generator_channel(cfg: dict, channel_id: int) -> bool:
    if not channel_id or not isinstance(cfg, dict):
        return False
    cid = int(channel_id)
    if cid in _normalize_generator_channel_ids(cfg):
        return True
    return cid == int(cfg.get("generator_channel_id") or 0)


def add_temp_voice_generator_channel(cfg: dict, channel_id: int) -> list[int]:
    ids = _normalize_generator_channel_ids(cfg)
    cid = int(channel_id)
    if cid > 0:
        if cid in ids:
            ids.remove(cid)
        ids.insert(0, cid)
    ids = ids[:10]
    cfg["generator_channel_ids"] = ids
    cfg["generator_channel_id"] = ids[0] if ids else None
    return ids


def remove_temp_voice_generator_channel(cfg: dict, channel_id: int) -> list[int]:
    ids = _normalize_generator_channel_ids(cfg)
    cid = int(channel_id)
    if cid in ids:
        ids.remove(cid)
    cfg["generator_channel_ids"] = ids
    cfg["generator_channel_id"] = ids[0] if ids else None
    return ids


def clear_temp_voice_generator_channels(cfg: dict) -> None:
    cfg["generator_channel_ids"] = []
    cfg["generator_channel_id"] = None


def get_temp_voice_config(data: dict, guild_id: int) -> dict:
    root = core.as_dict(data.get("temp_voice_configs"))
    raw = core.as_dict(root.get(str(guild_id)))
    raw_rooms = core.as_dict(raw.get("active_rooms"))
    active_rooms: dict[str, dict] = {}
    for ch_id_s, r_info in raw_rooms.items():
        if str(ch_id_s).isdigit() and isinstance(r_info, dict):
            active_rooms[str(ch_id_s)] = {
                "channel_id": int(ch_id_s),
                "owner_id": int(r_info.get("owner_id", 0) or 0),
                "owner_name": str(r_info.get("owner_name") or "방장")[:64],
                "room_name": str(r_info.get("room_name") or "")[:95],
                "user_limit": max(0, min(99, int(r_info.get("user_limit", 0) or 0))),
                "locked": bool(r_info.get("locked", False)),
                "hidden": bool(r_info.get("hidden", False)),
                "panel_message_id": int(r_info["panel_message_id"]) if str(r_info.get("panel_message_id", "")).isdigit() else None,
                "created_at": str(r_info.get("created_at") or ""),
            }
    gen_ids = _normalize_generator_channel_ids(raw)
    primary_gen = gen_ids[0] if gen_ids else None
    cat_id = raw.get("category_id")
    return {
        "enabled": bool(raw.get("enabled", False)),
        "generator_channel_id": primary_gen,
        "generator_channel_ids": gen_ids,
        "category_id": int(cat_id) if str(cat_id or "").isdigit() else None,
        "name_template": (str(raw.get("name_template") or DEFAULT_TEMP_VOICE_TEMPLATE).strip()[:80] or DEFAULT_TEMP_VOICE_TEMPLATE),
        "default_limit": max(0, min(99, int(raw.get("default_limit", 0) or 0))),
        "active_rooms": active_rooms,
        "updated_at": raw.get("updated_at"),
    }


def save_temp_voice_config(data: dict, guild_id: int, cfg: dict) -> dict:
    root = core.ensure_dict_path(data, "temp_voice_configs")
    cur = get_temp_voice_config(data, guild_id)
    merged_rooms = cfg.get("active_rooms") if isinstance(cfg.get("active_rooms"), dict) else cur["active_rooms"]
    clean_rooms: dict[str, dict] = {}
    for ch_id_s, r_info in merged_rooms.items():
        if str(ch_id_s).isdigit() and isinstance(r_info, dict):
            clean_rooms[str(ch_id_s)] = {
                "channel_id": int(ch_id_s),
                "owner_id": int(r_info.get("owner_id", 0) or 0),
                "owner_name": str(r_info.get("owner_name") or "방장")[:64],
                "room_name": str(r_info.get("room_name") or "")[:95],
                "user_limit": max(0, min(99, int(r_info.get("user_limit", 0) or 0))),
                "locked": bool(r_info.get("locked", False)),
                "hidden": bool(r_info.get("hidden", False)),
                "panel_message_id": int(r_info["panel_message_id"]) if str(r_info.get("panel_message_id", "")).isdigit() else None,
                "created_at": str(r_info.get("created_at") or datetime.datetime.now(core.KST).isoformat()),
            }
    gen_ids = _normalize_generator_channel_ids(cfg)
    primary_gen = gen_ids[0] if gen_ids else None
    cat_id = cfg.get("category_id")
    entry = {
        "enabled": bool(cfg.get("enabled", False)),
        "generator_channel_id": primary_gen,
        "generator_channel_ids": gen_ids,
        "category_id": int(cat_id) if str(cat_id or "").isdigit() else None,
        "name_template": (str(cfg.get("name_template") or DEFAULT_TEMP_VOICE_TEMPLATE).strip()[:80] or DEFAULT_TEMP_VOICE_TEMPLATE),
        "default_limit": max(0, min(99, int(cfg.get("default_limit", 0) or 0))),
        "active_rooms": clean_rooms,
        "updated_at": datetime.datetime.now(core.KST).isoformat(),
    }
    root[str(guild_id)] = entry
    return entry


def register_temp_voice_room(
    data: dict,
    guild_id: int,
    channel_id: int,
    owner_id: int,
    owner_name: str,
    *,
    room_name: str = "",
    user_limit: int = 0,
    panel_message_id: Optional[int] = None,
) -> dict:
    cfg = get_temp_voice_config(data, guild_id)
    now_iso = datetime.datetime.now(core.KST).isoformat()
    room_entry = {
        "channel_id": int(channel_id),
        "owner_id": int(owner_id),
        "owner_name": str(owner_name or "방장")[:64],
        "room_name": str(room_name or "")[:95],
        "user_limit": max(0, min(99, int(user_limit or 0))),
        "locked": False,
        "hidden": False,
        "panel_message_id": int(panel_message_id) if panel_message_id else None,
        "created_at": now_iso,
    }
    cfg["active_rooms"][str(channel_id)] = room_entry
    save_temp_voice_config(data, guild_id, cfg)
    return room_entry


def get_temp_voice_room(data: dict, guild_id: int, channel_id: int) -> Optional[dict]:
    cfg = get_temp_voice_config(data, guild_id)
    room = cfg["active_rooms"].get(str(channel_id))
    return room if isinstance(room, dict) else None


def update_temp_voice_room(data: dict, guild_id: int, channel_id: int, **kwargs) -> Optional[dict]:
    cfg = get_temp_voice_config(data, guild_id)
    ch_key = str(channel_id)
    room = cfg["active_rooms"].get(ch_key)
    if not isinstance(room, dict):
        return None
    for k, v in kwargs.items():
        if k in ("owner_id", "user_limit"):
            room[k] = int(v or 0)
        elif k in ("locked", "hidden"):
            room[k] = bool(v)
        elif k in ("owner_name", "room_name"):
            room[k] = str(v or "")[:95]
        elif k == "panel_message_id":
            room[k] = int(v) if v else None
    cfg["active_rooms"][ch_key] = room
    save_temp_voice_config(data, guild_id, cfg)
    return room


def remove_temp_voice_room(data: dict, guild_id: int, channel_id: int) -> Optional[dict]:
    cfg = get_temp_voice_config(data, guild_id)
    removed = cfg["active_rooms"].pop(str(channel_id), None)
    save_temp_voice_config(data, guild_id, cfg)
    return removed if isinstance(removed, dict) else None


# ==========================================
# 6. 🗓️ 예약 이벤트 신청표 (RSVP & 자동 리마인드)
# ==========================================
def parse_kst_event_datetime(
    raw: str,
    now_kst: Optional[datetime.datetime] = None,
) -> tuple[Optional[datetime.datetime], str]:
    """
    유저가 입력한 KST 일시 문자열을 파싱합니다.
    지원 형식:
      - YYYY-MM-DD HH:MM (예: 2026-05-15 21:00)
      - MM-DD HH:MM 또는 MM/DD HH:MM (예: 05-15 21:00, 5/15 21:00)
      - 오늘 HH:MM / 내일 HH:MM / 모레 HH:MM
      - +30분 / +2시간 / +1시간 30분
    """
    text = (raw or "").strip()
    if not text:
        return None, "시작 일시를 입력해 주세요. (예: `내일 21:00`, `05-15 20:30`, `2026-05-15 21:00`, `+2시간`)"

    now = now_kst or datetime.datetime.now(core.KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=core.KST)

    # 1) 상대 시간: +30분, +2시간, +1시간 30분
    rel_m = re.fullmatch(r"\+\s*(?:(\d+)\s*시간)?\s*(?:(\d+)\s*분)?", text)
    if rel_m and (rel_m.group(1) or rel_m.group(2)):
        hrs = int(rel_m.group(1) or 0)
        mins = int(rel_m.group(2) or 0)
        total_min = hrs * 60 + mins
        if total_min < 5 or total_min > 60 * 24 * 60:
            return None, "상대 시간은 최소 5분 이상, 최대 60일 이내로 입력해 주세요."
        target = (now + datetime.timedelta(minutes=total_min)).replace(second=0, microsecond=0)
        return target, ""

    # 2) 오늘/내일/모레 HH:MM
    day_m = re.fullmatch(r"(오늘|내일|모레)\s+(\d{1,2})[:시]\s*(\d{1,2})분?", text)
    if day_m:
        day_word, hh_s, mm_s = day_m.group(1), day_m.group(2), day_m.group(3)
        offset = {"오늘": 0, "내일": 1, "모레": 2}[day_word]
        hh, mm = int(hh_s), int(mm_s)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None, "시각은 `00:00 ~ 23:59` 범위로 입력해 주세요."
        base_date = (now + datetime.timedelta(days=offset)).date()
        target = datetime.datetime(base_date.year, base_date.month, base_date.day, hh, mm, tzinfo=core.KST)
        if target <= now:
            return None, "이미 지난 시각입니다. 현재 시각 이후로 입력해 주세요."
        return target, ""

    # 3) YYYY-MM-DD HH:MM (또는 YYYY/MM/DD HH:MM, YYYY.MM.DD HH:MM)
    full_m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d{1,2})[:시]\s*(\d{1,2})분?", text)
    if full_m:
        y, mo, d, hh, mm = (int(full_m.group(i)) for i in range(1, 6))
        try:
            target = datetime.datetime(y, mo, d, hh, mm, tzinfo=core.KST)
        except ValueError:
            return None, "올바른 날짜·시각이 아닙니다. (예: `2026-05-15 21:00`)"
        if target <= now:
            return None, "이미 지난 시각입니다. 현재 시각 이후로 입력해 주세요."
        return target, ""

    # 4) MM-DD HH:MM (또는 MM/DD HH:MM)
    short_m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})\s+(\d{1,2})[:시]\s*(\d{1,2})분?", text)
    if short_m:
        mo, d, hh, mm = (int(short_m.group(i)) for i in range(1, 5))
        try:
            target = datetime.datetime(now.year, mo, d, hh, mm, tzinfo=core.KST)
        except ValueError:
            return None, "올바른 월·일·시각이 아닙니다. (예: `05-15 21:00`)"
        if target <= now:
            try:
                target = datetime.datetime(now.year + 1, mo, d, hh, mm, tzinfo=core.KST)
            except ValueError:
                return None, "이미 지난 시각입니다. 연도를 포함해 다시 입력해 주세요."
        return target, ""

    return None, "일시 형식을 인식하지 못했습니다. 예: `내일 21:00`, `05-15 20:30`, `2026-05-15 21:00`, `+2시간`"


def _normalize_uid_list(raw) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            iv = int(x)
        except (TypeError, ValueError):
            continue
        if iv > 0 and iv not in out:
            out.append(iv)
    return out


def get_guild_events(data: dict, guild_id: int, *, include_closed: bool = False) -> list[dict]:
    root = core.as_dict(data.get("guild_events"))
    g_map = core.as_dict(root.get(str(guild_id)))
    out: list[dict] = []
    for ev in g_map.values():
        if not isinstance(ev, dict):
            continue
        status = str(ev.get("status") or "open")
        if not include_closed and status != "open":
            continue
        out.append(ev)
    out.sort(key=lambda e: int(e.get("start_ts", 0) or 0))
    return out


def get_guild_event(data: dict, guild_id: int, event_id: str) -> Optional[dict]:
    root = core.as_dict(data.get("guild_events"))
    g_map = core.as_dict(root.get(str(guild_id)))
    ev = g_map.get(str(event_id))
    return ev if isinstance(ev, dict) else None


def find_guild_event_by_message_id(data: dict, guild_id: int, message_id: int) -> Optional[dict]:
    if not message_id:
        return None
    root = core.as_dict(data.get("guild_events"))
    g_map = core.as_dict(root.get(str(guild_id)))
    for ev in g_map.values():
        if isinstance(ev, dict) and int(ev.get("message_id") or 0) == int(message_id):
            return ev
    return None


def create_guild_event(
    data: dict,
    guild_id: int,
    channel_id: int,
    host_id: int,
    host_name: str,
    title: str,
    start_dt: datetime.datetime,
    *,
    max_slots: int = 0,
    description: str = "",
    message_id: Optional[int] = None,
) -> dict:
    g_map = core.ensure_dict_path(data, "guild_events", str(guild_id))
    ev_id = f"ev_{uuid.uuid4().hex[:8]}"
    safe_slots = max(0, min(100, int(max_slots or 0)))
    entry = {
        "id": ev_id,
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "message_id": int(message_id) if message_id else None,
        "host_id": int(host_id),
        "host_name": str(host_name or "주최자")[:64],
        "title": (title or "예약 이벤트").strip()[:80],
        "description": (description or "").strip()[:500],
        "start_iso": start_dt.isoformat(),
        "start_ts": int(start_dt.timestamp()),
        "max_slots": safe_slots,
        "going": [int(host_id)],
        "waitlist": [],
        "maybe": [],
        "declined": [],
        "status": "open",
        "reminded_15m": False,
        "started_notified": False,
        "created_at": datetime.datetime.now(core.KST).isoformat(),
    }
    g_map[ev_id] = entry
    return entry


def set_guild_event_message_id(data: dict, guild_id: int, event_id: str, message_id: int) -> Optional[dict]:
    ev = get_guild_event(data, guild_id, event_id)
    if not ev:
        return None
    ev["message_id"] = int(message_id)
    return ev


def update_event_rsvp(event: dict, user_id: int, action: str) -> tuple[str, Optional[int]]:
    """
    예약 이벤트 RSVP 상태를 갱신합니다.
    action: "going" | "maybe" | "declined"
    반환: (결과 상태 ["going"|"waitlist"|"maybe"|"declined"|"closed"], 자동 승격된 대기자 user_id 또는 None)
    """
    if str(event.get("status") or "open") != "open":
        return "closed", None

    uid = int(user_id)
    going = _normalize_uid_list(event.get("going"))
    waitlist = _normalize_uid_list(event.get("waitlist"))
    maybe = _normalize_uid_list(event.get("maybe"))
    declined = _normalize_uid_list(event.get("declined"))
    max_slots = max(0, int(event.get("max_slots") or 0))

    was_going = uid in going
    going = [x for x in going if x != uid]
    waitlist = [x for x in waitlist if x != uid]
    maybe = [x for x in maybe if x != uid]
    declined = [x for x in declined if x != uid]

    promoted_uid: Optional[int] = None
    result_state = action

    if action == "going":
        if max_slots > 0 and len(going) >= max_slots:
            waitlist.append(uid)
            result_state = "waitlist"
        else:
            going.append(uid)
            result_state = "going"
    elif action == "maybe":
        maybe.append(uid)
        result_state = "maybe"
    else:
        declined.append(uid)
        result_state = "declined"

    # 기존 확정 참가자가 빠지면서 빈자리가 생기면 대기열 1순위를 자동 승격
    if was_going and action != "going" and max_slots > 0 and len(going) < max_slots and waitlist:
        promoted_uid = waitlist.pop(0)
        going.append(promoted_uid)

    event["going"] = going
    event["waitlist"] = waitlist
    event["maybe"] = maybe
    event["declined"] = declined
    return result_state, promoted_uid


def set_guild_event_status(data: dict, guild_id: int, event_id: str, status: str) -> Optional[dict]:
    ev = get_guild_event(data, guild_id, event_id)
    if not ev:
        return None
    if status not in ("open", "closed", "cancelled"):
        return None
    ev["status"] = status
    return ev


def collect_due_event_reminders(data: dict, now_ts: Optional[int] = None) -> list[tuple[dict, str]]:
    """
    15분 전 자동 리마인드 및 시작 시각 알림 대상 이벤트를 수집하고 플래그를 표시합니다.
    24시간이 지난 오픈 이벤트는 자동으로 closed 처리하며, 종료 후 7일이 경과한 이벤트는 자동 정리합니다.
    """
    ts = int(now_ts if now_ts is not None else time.time())
    root = core.as_dict(data.get("guild_events"))
    due: list[tuple[dict, str]] = []
    for g_map in root.values():
        if not isinstance(g_map, dict):
            continue
        stale_eids: list[str] = []
        for eid, ev in g_map.items():
            if not isinstance(ev, dict):
                continue
            status = str(ev.get("status") or "open")
            start_ts = int(ev.get("start_ts") or 0)
            if status in ("closed", "cancelled"):
                if start_ts > 0 and (ts - start_ts) > 7 * 86400:
                    stale_eids.append(str(eid))
                continue
            if status != "open" or start_ts <= 0:
                continue
            diff = start_ts - ts
            # 15분 전 (0 < diff <= 900)
            if 0 < diff <= 900 and not ev.get("reminded_15m"):
                ev["reminded_15m"] = True
                due.append((ev, "15m"))
            # 시작 시각 도달 (-600 <= diff <= 0)
            elif -600 <= diff <= 0 and not ev.get("started_notified"):
                ev["started_notified"] = True
                due.append((ev, "start"))
            # 시작 후 24시간 경과 시 자동 마감
            elif diff < -86400:
                ev["status"] = "closed"
        for eid in stale_eids:
            g_map.pop(eid, None)
    return due


# ==========================================
# 7. 👋 웰컴 / 작별 이미지 카드 & 메시지 설정 (서버 관리자 전용)
# ==========================================
DEFAULT_WELCOME_TITLE = "🎉 {server} · 신규 멤버 환영합니다!"
DEFAULT_GOODBYE_TITLE = "👋 {server} · 멤버 퇴장 안내"
DEFAULT_WELCOME_MSG = "🎉 {user}님, **{server}** 서버에 오신 것을 환영합니다! (`{count}번째` 멤버)"
DEFAULT_GOODBYE_MSG = "👋 **{username}님**이 **{server}** 서버에서 퇴장하셨습니다. (현재 `{count}명`)"
DEFAULT_WELCOME_SUBTITLE = "{count}번째 멤버로 함께하게 되었어요!"
DEFAULT_GOODBYE_SUBTITLE = "{server} 서버와 함께해 주셔서 감사합니다."
DEFAULT_WELCOME_BADGE = "WELCOME · 서버 신규 멤버 입장"
DEFAULT_GOODBYE_BADGE = "GOODBYE · 다음에 또 만나요"

_HIDE_TITLE_KEYWORDS = {"없음", "숨김", "삭제", "지움", "비움", "none", "hide", "off", "-"}


def normalize_welcome_embed_title(raw_val: object, default_title: str) -> str:
    """
    임베드 제목 설정값을 정규화합니다.
    - None이면 기본 제목(default_title) 반환
    - 빈 문자열("") 또는 '없음', '숨김', 'none', 'off', '-' 입력 시 ""(제목 숨김) 반환
    """
    if raw_val is None:
        return default_title
    s = str(raw_val).strip()[:200]
    if not s or s.lower() in _HIDE_TITLE_KEYWORDS:
        return ""
    return s

WELCOME_COLOR_PRESETS: dict[str, str] = {
    "블루": "#5865F2",
    "파랑": "#5865F2",
    "디스코드": "#5865F2",
    "blue": "#5865F2",
    "blurple": "#5865F2",
    "그린": "#2ECC71",
    "초록": "#2ECC71",
    "에메랄드": "#2ECC71",
    "green": "#2ECC71",
    "골드": "#F1C40F",
    "노랑": "#F1C40F",
    "황금": "#F1C40F",
    "gold": "#F1C40F",
    "yellow": "#F1C40F",
    "핑크": "#FF69B4",
    "분홍": "#FF69B4",
    "pink": "#FF69B4",
    "퍼플": "#9B59B6",
    "보라": "#9B59B6",
    "purple": "#9B59B6",
    "레드": "#E74C3C",
    "빨강": "#E74C3C",
    "red": "#E74C3C",
    "민트": "#1ABC9C",
    "청록": "#1ABC9C",
    "mint": "#1ABC9C",
    "teal": "#1ABC9C",
    "하늘": "#00CCDD",
    "스카이": "#00CCDD",
    "시안": "#00CCDD",
    "sky": "#00CCDD",
    "cyan": "#00CCDD",
    "주황": "#E67E22",
    "오렌지": "#E67E22",
    "orange": "#E67E22",
    "화이트": "#FFFFFF",
    "흰색": "#FFFFFF",
    "white": "#FFFFFF",
}


def _normalize_hex_color(raw_hex: str, default_hex: str = "#5865F2") -> str:
    s = str(raw_hex or "").strip()
    if not s:
        return default_hex
    preset = WELCOME_COLOR_PRESETS.get(s.lower()) or WELCOME_COLOR_PRESETS.get(s.lstrip("#").lower())
    if preset:
        return preset
    if not s.startswith("#"):
        s = "#" + s
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", s):
        return s.upper()
    return default_hex


def hex_to_rgb_tuple(raw_hex: str, default_rgb: tuple[int, int, int] = (88, 101, 242)) -> tuple[int, int, int]:
    norm = _normalize_hex_color(raw_hex, "")
    if len(norm) == 7:
        try:
            return (int(norm[1:3], 16), int(norm[3:5], 16), int(norm[5:7], 16))
        except Exception:
            pass
    return default_rgb


def _normalize_welcome_auto_role_ids(raw: dict) -> list[int]:
    result: list[int] = []
    raw_list = raw.get("auto_role_ids")
    if isinstance(raw_list, list):
        for item in raw_list:
            if str(item or "").isdigit():
                val = int(item)
                if val > 0 and val not in result:
                    result.append(val)
    single = raw.get("auto_role_id")
    if not result and str(single or "").isdigit():
        val = int(single)
        if val > 0:
            result.append(val)
    return result[:10]


def update_welcome_auto_roles(cfg: dict, selected_role_ids: list[int]) -> tuple[list[int], list[int], list[int]]:
    """
    선택된 역할들을 자동 부여 역할 목록에 반영합니다.
    - 이미 등록된 역할 1개만 다시 선택한 경우: 해당 역할을 목록에서 해제(토글)합니다.
    - 그 외(신규 역할 선택 또는 다중 선택): 기존 목록에 새로운 역할들을 추가(최대 10개)합니다.
    반환값: (전체_역할_ID_목록, 추가된_ID_목록, 제거된_ID_목록)
    """
    current = _normalize_welcome_auto_role_ids(cfg)
    incoming: list[int] = []
    for r in selected_role_ids:
        if str(r or "").isdigit():
            val = int(r)
            if val > 0 and val not in incoming:
                incoming.append(val)
    added: list[int] = []
    removed: list[int] = []
    if len(incoming) == 1 and incoming[0] in current:
        target = incoming[0]
        current.remove(target)
        removed.append(target)
    else:
        for rid in incoming:
            if rid not in current:
                if len(current) >= 10:
                    break
                current.append(rid)
                added.append(rid)
    cfg["auto_role_ids"] = current[:10]
    cfg["auto_role_id"] = cfg["auto_role_ids"][0] if cfg["auto_role_ids"] else None
    return cfg["auto_role_ids"], added, removed


def remove_welcome_auto_role(cfg: dict, role_id: int) -> list[int]:
    current = _normalize_welcome_auto_role_ids(cfg)
    rid = int(role_id)
    if rid in current:
        current.remove(rid)
    cfg["auto_role_ids"] = current
    cfg["auto_role_id"] = current[0] if current else None
    return current


def clear_welcome_auto_roles(cfg: dict) -> None:
    cfg["auto_role_ids"] = []
    cfg["auto_role_id"] = None


def get_welcome_config(data: dict, guild_id: int) -> dict:
    root = core.as_dict(data.get("welcome_configs"))
    raw = core.as_dict(root.get(str(guild_id)))
    w_ch = raw.get("welcome_channel_id")
    g_ch = raw.get("goodbye_channel_id")
    role_ids = _normalize_welcome_auto_role_ids(raw)
    w_sub = str(raw.get("welcome_card_subtitle") or raw.get("banner_subtitle") or DEFAULT_WELCOME_SUBTITLE).strip()[:100] or DEFAULT_WELCOME_SUBTITLE
    g_sub = str(raw.get("goodbye_card_subtitle") or DEFAULT_GOODBYE_SUBTITLE).strip()[:100] or DEFAULT_GOODBYE_SUBTITLE
    w_badge = str(raw.get("welcome_card_badge") or DEFAULT_WELCOME_BADGE).strip()[:60] or DEFAULT_WELCOME_BADGE
    g_badge = str(raw.get("goodbye_card_badge") or DEFAULT_GOODBYE_BADGE).strip()[:60] or DEFAULT_GOODBYE_BADGE
    return {
        "welcome_enabled": bool(raw.get("welcome_enabled", False)),
        "goodbye_enabled": bool(raw.get("goodbye_enabled", False)),
        "banner_enabled": bool(raw.get("banner_enabled", True)),
        "welcome_channel_id": int(w_ch) if str(w_ch or "").isdigit() else None,
        "goodbye_channel_id": int(g_ch) if str(g_ch or "").isdigit() else None,
        "auto_role_id": role_ids[0] if role_ids else None,
        "auto_role_ids": role_ids,
        "welcome_title": normalize_welcome_embed_title(raw.get("welcome_title"), DEFAULT_WELCOME_TITLE),
        "goodbye_title": normalize_welcome_embed_title(raw.get("goodbye_title"), DEFAULT_GOODBYE_TITLE),
        "welcome_message": (str(raw.get("welcome_message") or DEFAULT_WELCOME_MSG).strip()[:500] or DEFAULT_WELCOME_MSG),
        "goodbye_message": (str(raw.get("goodbye_message") or DEFAULT_GOODBYE_MSG).strip()[:500] or DEFAULT_GOODBYE_MSG),
        "banner_subtitle": w_sub,
        "welcome_card_subtitle": w_sub,
        "goodbye_card_subtitle": g_sub,
        "welcome_card_badge": w_badge,
        "goodbye_card_badge": g_badge,
        "accent_color": _normalize_hex_color(str(raw.get("accent_color") or "#5865F2")),
        "updated_at": raw.get("updated_at"),
    }


def save_welcome_config(data: dict, guild_id: int, cfg: dict) -> dict:
    root = core.ensure_dict_path(data, "welcome_configs")
    w_ch = cfg.get("welcome_channel_id")
    g_ch = cfg.get("goodbye_channel_id")
    role_ids = _normalize_welcome_auto_role_ids(cfg)
    w_sub = str(cfg.get("welcome_card_subtitle") or cfg.get("banner_subtitle") or DEFAULT_WELCOME_SUBTITLE).strip()[:100] or DEFAULT_WELCOME_SUBTITLE
    g_sub = str(cfg.get("goodbye_card_subtitle") or DEFAULT_GOODBYE_SUBTITLE).strip()[:100] or DEFAULT_GOODBYE_SUBTITLE
    w_badge = str(cfg.get("welcome_card_badge") or DEFAULT_WELCOME_BADGE).strip()[:60] or DEFAULT_WELCOME_BADGE
    g_badge = str(cfg.get("goodbye_card_badge") or DEFAULT_GOODBYE_BADGE).strip()[:60] or DEFAULT_GOODBYE_BADGE
    entry = {
        "welcome_enabled": bool(cfg.get("welcome_enabled", False)),
        "goodbye_enabled": bool(cfg.get("goodbye_enabled", False)),
        "banner_enabled": bool(cfg.get("banner_enabled", True)),
        "welcome_channel_id": int(w_ch) if str(w_ch or "").isdigit() else None,
        "goodbye_channel_id": int(g_ch) if str(g_ch or "").isdigit() else None,
        "auto_role_id": role_ids[0] if role_ids else None,
        "auto_role_ids": role_ids,
        "welcome_title": normalize_welcome_embed_title(cfg.get("welcome_title"), DEFAULT_WELCOME_TITLE),
        "goodbye_title": normalize_welcome_embed_title(cfg.get("goodbye_title"), DEFAULT_GOODBYE_TITLE),
        "welcome_message": (str(cfg.get("welcome_message") or DEFAULT_WELCOME_MSG).strip()[:500] or DEFAULT_WELCOME_MSG),
        "goodbye_message": (str(cfg.get("goodbye_message") or DEFAULT_GOODBYE_MSG).strip()[:500] or DEFAULT_GOODBYE_MSG),
        "banner_subtitle": w_sub,
        "welcome_card_subtitle": w_sub,
        "goodbye_card_subtitle": g_sub,
        "welcome_card_badge": w_badge,
        "goodbye_card_badge": g_badge,
        "accent_color": _normalize_hex_color(str(cfg.get("accent_color") or "#5865F2")),
        "updated_at": datetime.datetime.now(core.KST).isoformat(),
    }
    root[str(guild_id)] = entry
    return entry


def format_welcome_text(
    template: str,
    *,
    user_mention: str,
    username: str,
    server_name: str,
    member_count: int,
) -> str:
    base = str(template or "").strip()
    if not base:
        return ""
    safe_name = str(username or "멤버").replace("@", "@\u200b")
    safe_server = str(server_name or "서버").replace("@", "@\u200b")
    cnt_str = f"{max(1, int(member_count or 1)):,}"
    return (
        base.replace("{user}", str(user_mention or safe_name))
        .replace("{username}", safe_name)
        .replace("{server}", safe_server)
        .replace("{count}", cnt_str)
    )


def render_welcome_banner_png(
    guild_name: str,
    member_name: str,
    member_count: int,
    avatar_bytes: Optional[bytes] = None,
    *,
    is_goodbye: bool = False,
    accent_hex: str = "#5865F2",
    subtitle: str = "",
    goodbye_subtitle: str = "",
    badge_text: str = "",
) -> Optional[bytes]:
    """신규 입장 또는 퇴장 멤버용 800x260 고해상도 PNG 환영/작별 배너 카드를 생성합니다."""
    import io
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    W, H = 800, 260
    accent_rgb = (237, 66, 69) if is_goodbye else hex_to_rgb_tuple(accent_hex, (88, 101, 242))
    bg_dark = (20, 22, 31)
    card_bg = (29, 32, 46)

    img = Image.new("RGBA", (W, H), (*bg_dark, 255))
    draw = ImageDraw.Draw(img)

    # 배경 카드 및 상단·좌측 포인트 컬러 바
    draw.rounded_rectangle((14, 14, W - 14, H - 14), radius=22, fill=(*card_bg, 255), outline=(*accent_rgb, 180), width=2)
    draw.rounded_rectangle((14, 14, 26, H - 14), radius=6, fill=(*accent_rgb, 255))

    # 우측 상단 은은한 장식 원
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.ellipse((W - 210, -70, W + 50, 190), fill=(*accent_rgb, 32))
    ov_draw.ellipse((W - 130, H - 110, W + 60, H + 80), fill=(*accent_rgb, 22))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # 원형 아바타 (148x148)
    av_size = 148
    av_x, av_y = 54, (H - av_size) // 2
    draw.ellipse((av_x - 5, av_y - 5, av_x + av_size + 5, av_y + av_size + 5), fill=(*accent_rgb, 255))
    draw.ellipse((av_x - 2, av_y - 2, av_x + av_size + 2, av_y + av_size + 2), fill=(*bg_dark, 255))

    avatar_img = None
    if avatar_bytes:
        try:
            raw_av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = raw_av.resize((av_size, av_size), Image.Resampling.LANCZOS)
        except Exception:
            avatar_img = None

    if avatar_img is None:
        avatar_img = Image.new("RGBA", (av_size, av_size), (*accent_rgb, 255))
        av_d = ImageDraw.Draw(avatar_img)
        init_font = core._get_grid_font(56, bold=True)
        initial_ch = (str(member_name or "N").strip()[:1] or "N").upper()
        av_d.text((av_size // 2, av_size // 2), initial_ch, fill=(255, 255, 255, 255), font=init_font, anchor="mm")

    mask = Image.new("L", (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, av_size, av_size), fill=255)
    img.paste(avatar_img, (av_x, av_y), mask)

    # 우측 텍스트 영역
    tx = 232
    f_badge = core._get_grid_font(17, bold=True)
    f_name = core._get_grid_font(36, bold=True)
    f_sub = core._get_grid_font(20, bold=False)
    f_meta = core._get_grid_font(16, bold=True)

    disp_name = str(member_name or "신규 멤버").strip()[:22]
    raw_badge = badge_text.strip() if badge_text and badge_text.strip() else (DEFAULT_GOODBYE_BADGE if is_goodbye else DEFAULT_WELCOME_BADGE)
    badge_txt = format_welcome_text(
        raw_badge,
        user_mention=disp_name,
        username=disp_name,
        server_name=str(guild_name or "서버"),
        member_count=member_count,
    )[:36]
    try:
        bbox = draw.textbbox((0, 0), badge_txt, font=f_badge)
        badge_w = max(180, min(520, (bbox[2] - bbox[0]) + 32))
    except Exception:
        badge_w = 290
    draw.rounded_rectangle((tx, 44, tx + badge_w, 76), radius=10, fill=(*accent_rgb, 45), outline=(*accent_rgb, 190), width=1)
    draw.text((tx + 14, 60), badge_txt, fill=(*accent_rgb, 255), font=f_badge, anchor="lm")

    draw.text((tx, 114), disp_name, fill=(255, 255, 255, 255), font=f_name, anchor="lm")

    if is_goodbye:
        raw_sub = goodbye_subtitle or subtitle or DEFAULT_GOODBYE_SUBTITLE
    else:
        raw_sub = subtitle or DEFAULT_WELCOME_SUBTITLE
    sub_line = format_welcome_text(
        raw_sub,
        user_mention=disp_name,
        username=disp_name,
        server_name=str(guild_name or "서버"),
        member_count=member_count,
    )[:44]
    draw.text((tx, 162), sub_line, fill=(200, 206, 224, 255), font=f_sub, anchor="lm")

    now_str = datetime.datetime.now(core.KST).strftime("%Y.%m.%d %H:%M KST")
    meta_txt = f"{str(guild_name or 'Server')[:20]}  ·  MEMBER #{max(1, int(member_count or 1)):,}  ·  {now_str}"
    draw.text((tx, 204), meta_txt, fill=(142, 150, 175, 255), font=f_meta, anchor="lm")

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ==========================================
# 8. ⏳ 서버 관리자 실시간 카운트다운 타이머 임베드 (countdown_timers)
# ==========================================
def parse_countdown_time_spec(raw_spec: str, now_dt: Optional[datetime.datetime] = None) -> Optional[int]:
    """
    서버 관리자가 입력한 시간 문자열을 목표 UNIX 타임스탬프(초)로 변환합니다.
    지원 형식:
      - 상대 시간: '30분', '1시간 30분', '2시간', '1일 2시간', '90m', '2h', '45' (숫자만 입력 시 분 단위)
      - 오늘/내일 시각: '21:00', '오후 9:30', '내일 20:00'
      - 날짜+시각: '2026-11-27 20:00', '11-27 20:00'
    """
    s = str(raw_spec or "").strip()
    if not s:
        return None
    base_now = now_dt if now_dt is not None else datetime.datetime.now(core.KST)
    now_ts = int(base_now.timestamp())

    # 1) 순수 숫자 -> 분 단위
    if s.isdigit():
        mins = int(s)
        if 1 <= mins <= 525600:
            return now_ts + mins * 60
        return None

    # 2) 상대 시간 ('1일', '2시간', '30분', '20초', '1d', '2h', '30m', '30s')
    rel_matches = re.findall(r"(\d+)\s*(일|시간|시|분|초|d|day|days|h|hr|hrs|m|min|mins|s|sec|secs)", s, flags=re.IGNORECASE)
    if rel_matches and not re.search(r"\d{1,2}:\d{2}", s):
        total_sec = 0
        for num_s, unit_s in rel_matches:
            val = int(num_s)
            u = unit_s.lower()
            if u in ("일", "d", "day", "days"):
                total_sec += val * 86400
            elif u in ("시간", "시", "h", "hr", "hrs"):
                total_sec += val * 3600
            elif u in ("분", "m", "min", "mins"):
                total_sec += val * 60
            elif u in ("초", "s", "sec", "secs"):
                total_sec += val
        if 10 <= total_sec <= 365 * 86400:
            return now_ts + total_sec

    # 3) YYYY-MM-DD HH:MM 또는 MM-DD HH:MM
    m_full = re.match(r"^(?:(\d{4})[-./])?(\d{1,2})[-./](\d{1,2})\s+(\d{1,2}):(\d{2})$", s)
    if m_full:
        yr = int(m_full.group(1)) if m_full.group(1) else base_now.year
        mo, dy, hh, mm = int(m_full.group(2)), int(m_full.group(3)), int(m_full.group(4)), int(m_full.group(5))
        try:
            dt = datetime.datetime(yr, mo, dy, hh, mm, tzinfo=core.KST)
            if not m_full.group(1) and dt <= base_now:
                dt = datetime.datetime(yr + 1, mo, dy, hh, mm, tzinfo=core.KST)
            if dt > base_now:
                return int(dt.timestamp())
        except ValueError:
            return None

    # 4) [오늘/내일] [오전/오후] HH:MM
    m_tod = re.match(r"^(?:(오늘|내일|모레)\s*)?(?:(오전|오후|am|pm)\s*)?(\d{1,2}):(\d{2})$", s, flags=re.IGNORECASE)
    if m_tod:
        day_word = (m_tod.group(1) or "").strip()
        ampm = (m_tod.group(2) or "").strip().lower()
        hh, mm = int(m_tod.group(3)), int(m_tod.group(4))
        if ampm in ("오후", "pm") and hh < 12:
            hh += 12
        elif ampm in ("오전", "am") and hh == 12:
            hh = 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        day_offset = 1 if day_word == "내일" else (2 if day_word == "모레" else 0)
        target_date = (base_now + datetime.timedelta(days=day_offset)).date()
        dt = datetime.datetime(target_date.year, target_date.month, target_date.day, hh, mm, tzinfo=core.KST)
        if day_offset == 0 and dt <= base_now:
            dt += datetime.timedelta(days=1)
        return int(dt.timestamp())

    return None


def create_countdown_timer(
    data: dict,
    guild_id: int,
    channel_id: int,
    creator_id: int,
    *,
    title: str,
    target_ts: int,
    description: str = "",
    mention_target: str = "none",
    message_id: Optional[int] = None,
) -> dict:
    root = core.ensure_dict_path(data, "countdown_timers")
    g_map = core.ensure_dict_path(root, str(guild_id))
    timer_id = f"cd_{uuid.uuid4().hex[:8]}"
    now_ts = int(time.time())
    entry = {
        "timer_id": timer_id,
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "message_id": int(message_id) if message_id else None,
        "creator_id": int(creator_id),
        "title": str(title or "카운트다운 이벤트").strip()[:100],
        "description": str(description or "").strip()[:800],
        "target_ts": int(target_ts),
        "created_ts": now_ts,
        "mention_target": str(mention_target or "none").strip()[:64],
        "subscribers": [int(creator_id)] if creator_id else [],
        "status": "active",
    }
    g_map[timer_id] = entry
    return entry


def get_guild_countdown_timers(data: dict, guild_id: int, *, active_only: bool = False) -> list[dict]:
    root = core.as_dict(data.get("countdown_timers"))
    g_map = core.as_dict(root.get(str(guild_id)))
    out: list[dict] = []
    for t in g_map.values():
        if not isinstance(t, dict):
            continue
        if active_only and str(t.get("status") or "active") != "active":
            continue
        out.append(t)
    out.sort(key=lambda x: int(x.get("target_ts") or 0))
    return out


def get_countdown_timer(data: dict, guild_id: int, timer_id: str) -> Optional[dict]:
    root = core.as_dict(data.get("countdown_timers"))
    g_map = core.as_dict(root.get(str(guild_id)))
    t = g_map.get(str(timer_id))
    return t if isinstance(t, dict) else None


def find_countdown_timer_by_message(data: dict, guild_id: int, message_id: int) -> Optional[dict]:
    if not message_id:
        return None
    for t in get_guild_countdown_timers(data, guild_id):
        if int(t.get("message_id") or 0) == int(message_id):
            return t
    return None


def toggle_countdown_subscriber(data: dict, guild_id: int, timer_id: str, user_id: int) -> tuple[bool, int]:
    t = get_countdown_timer(data, guild_id, timer_id)
    if not t:
        return False, 0
    subs = _normalize_uid_list(t.get("subscribers"))
    uid = int(user_id)
    if uid in subs:
        subs.remove(uid)
        added = False
    else:
        subs.append(uid)
        added = True
    t["subscribers"] = subs
    return added, len(subs)


def extend_countdown_timer(data: dict, guild_id: int, timer_id: str, delta_sec: int = 600) -> Optional[dict]:
    t = get_countdown_timer(data, guild_id, timer_id)
    if not t or str(t.get("status") or "active") != "active":
        return None
    base_ts = max(int(time.time()), int(t.get("target_ts") or 0))
    t["target_ts"] = base_ts + int(delta_sec)
    return t


def cancel_countdown_timer(data: dict, guild_id: int, timer_id: str) -> Optional[dict]:
    t = get_countdown_timer(data, guild_id, timer_id)
    if not t:
        return None
    t["status"] = "cancelled"
    return t


def collect_due_countdown_timers(data: dict, now_ts: Optional[int] = None) -> list[dict]:
    """목표 시각에 도달한 활성 카운트다운 타이머를 수집하고 completed 상태로 전환하며, 종료 후 7일이 지난 타이머는 자동 정리합니다."""
    ts = int(now_ts if now_ts is not None else time.time())
    root = core.as_dict(data.get("countdown_timers"))
    due: list[dict] = []
    for g_map in root.values():
        if not isinstance(g_map, dict):
            continue
        stale_tids: list[str] = []
        for tid, t in g_map.items():
            if not isinstance(t, dict):
                continue
            status = str(t.get("status") or "active")
            target_ts = int(t.get("target_ts") or 0)
            if status in ("completed", "cancelled"):
                if target_ts > 0 and (ts - target_ts) > 7 * 86400:
                    stale_tids.append(str(tid))
                continue
            if status != "active" or target_ts <= 0:
                continue
            if target_ts <= ts:
                t["status"] = "completed"
                due.append(t)
        for tid in stale_tids:
            g_map.pop(tid, None)
    return due



