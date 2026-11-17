"""
community_core.py - 자동 고정 메시지(#8), SNS 링크 미리보기/추적 제거(#12),
동시 입장(Raid) 비상 방어(#42), 릴레이 소설(#48) 코어 로직 및 데이터 헬퍼
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


def set_sticky_config(
    data: dict,
    guild_id: int,
    channel_id: int,
    title: str,
    content: str,
    *,
    color: str = "gold",
    interval: int = 1,
    cooldown_sec: int = 3,
    updated_by: int = 0,
    last_message_id: Optional[int] = None,
) -> dict:
    g_map = core.ensure_dict_path(data, "sticky_messages", str(guild_id))
    prev = g_map.get(str(channel_id)) if isinstance(g_map.get(str(channel_id)), dict) else {}
    safe_color = color if color in STICKY_COLOR_MAP else "gold"
    safe_interval = max(1, min(30, int(interval or 1)))
    safe_cd = max(2, min(60, int(cooldown_sec or 3)))
    entry = {
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "title": (title or "📌 채널 안내").strip()[:120],
        "content": (content or "").strip()[:1800],
        "color": safe_color,
        "interval": safe_interval,
        "cooldown_sec": safe_cd,
        "last_message_id": last_message_id if last_message_id is not None else prev.get("last_message_id"),
        "msg_count": 0,
        "last_posted_ts": float(prev.get("last_posted_ts", 0.0) or 0.0),
        "enabled": True,
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
        "enabled": bool(raw.get("enabled", True)),
        "sns_preview": bool(raw.get("sns_preview", True)),
        "strip_tracking": bool(raw.get("strip_tracking", True)),
        "suppress_original": bool(raw.get("suppress_original", True)),
        "ignored_channels": [int(c) for c in (raw.get("ignored_channels") or []) if str(c).isdigit()],
        "updated_at": raw.get("updated_at"),
    }


def save_link_preview_config(data: dict, guild_id: int, cfg: dict) -> dict:
    root = core.ensure_dict_path(data, "link_preview_configs")
    entry = {
        "enabled": bool(cfg.get("enabled", True)),
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
    is_twitter = False

    if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "mobile.x.com"):
        is_twitter = True
        if sns_preview and re.match(r"^/[^/]+/status/\d+", path):
            new_host = "fxtwitter.com"
            service_label = "X (Twitter)"
    elif host in ("instagram.com", "www.instagram.com"):
        if sns_preview and re.match(r"^/(p|reel|reels|tv|stories)/", path):
            new_host = "kkinstagram.com"
            service_label = "Instagram"
    elif host in ("tiktok.com", "www.tiktok.com", "m.tiktok.com", "vt.tiktok.com", "vm.tiktok.com"):
        if sns_preview and path and path != "/":
            if host == "vt.tiktok.com":
                new_host = "vt.vxtiktok.com"
            elif host == "vm.tiktok.com":
                new_host = "vm.vxtiktok.com"
            else:
                new_host = "vxtiktok.com"
            service_label = "TikTok"
    elif host in ("threads.net", "www.threads.net", "threads.com", "www.threads.com"):
        if sns_preview and "/post/" in path:
            new_host = "vxthreads.net"
            service_label = "Threads"
    elif host in ("reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com"):
        if sns_preview and ("/comments/" in path or "/s/" in path):
            new_host = "rxddit.com"
            service_label = "Reddit"
    elif host in ("pixiv.net", "www.pixiv.net"):
        if sns_preview and "/artworks/" in path:
            new_host = "phixiv.net"
            service_label = "Pixiv"
    elif host == "bsky.app":
        if sns_preview and "/profile/" in path and "/post/" in path:
            new_host = "bskyx.app"
            service_label = "Bluesky"

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
    if cleaned_url == url:
        return None

    return {
        "original": url,
        "cleaned": cleaned_url,
        "kind": "sns" if service_label else "tracking",
        "service": service_label or host,
        "stripped_params": stripped_params,
    }


def extract_and_transform_urls(text: str, cfg: dict, max_items: int = 3) -> list[dict]:
    if not text or not cfg.get("enabled", True):
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
        return False, f"이미 이 채널에서 **『{existing.get('title', '릴레이 소설')}』**이 진행 중입니다!", None

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
