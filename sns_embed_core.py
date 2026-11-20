"""
sns_embed_core.py - 다중 SNS(X/Twitter, Instagram, TikTok, Threads, Bluesky, Reddit, Pixiv, YouTube, Facebook, Pinterest 등)
실시간 메타데이터·미디어 추출 및 Discord Components V2 리치 카드(LayoutView + Container + Section + MediaGallery) 빌더
"""

from __future__ import annotations

import asyncio
import datetime
import html
import io
import ipaddress
import json
import re
import socket
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp
import discord

MAX_VIDEO_BYTES = 9_500_000   # Discord 기본 서버 업로드 상한(10MB) 미만 안전선
MAX_IMAGE_BYTES = 4_500_000
MAX_HTML_BYTES = 512_000
MAX_JSON_BYTES = 1_500_000
HTTP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DISCORD_BOT_UA = "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"

PLATFORM_META: dict[str, dict[str, Any]] = {
    "x": {"name": "X", "emoji": "𝕏", "color": 0x1DA1F2},
    "instagram": {"name": "Instagram", "emoji": "📷", "color": 0xE1306C},
    "tiktok": {"name": "TikTok", "emoji": "🎵", "color": 0xFE2C55},
    "threads": {"name": "Threads", "emoji": "🧵", "color": 0x2B2D31},
    "bluesky": {"name": "Bluesky", "emoji": "🦋", "color": 0x0085FF},
    "reddit": {"name": "Reddit", "emoji": "👽", "color": 0xFF4500},
    "pixiv": {"name": "Pixiv", "emoji": "🎨", "color": 0x0096FA},
    "youtube": {"name": "YouTube", "emoji": "▶️", "color": 0xFF0000},
    "facebook": {"name": "Facebook", "emoji": "📘", "color": 0x1877F2},
    "pinterest": {"name": "Pinterest", "emoji": "📌", "color": 0xE60023},
    "web": {"name": "Link", "emoji": "🔗", "color": 0x00CCDD},
}


@dataclass
class SnsPostData:
    platform: str
    url: str
    author_name: str = ""
    author_handle: str = ""
    author_url: str = ""
    author_avatar: str = ""
    caption: str = ""
    views: Optional[int] = None
    likes: Optional[int] = None
    reposts: Optional[int] = None
    comments: Optional[int] = None
    created_ts: Optional[int] = None
    video_url: str = ""
    video_headers: dict[str, str] = field(default_factory=dict)
    image_urls: list[str] = field(default_factory=list)
    image_headers: dict[str, str] = field(default_factory=dict)
    download_images: bool = False
    site_label: str = ""


def _safe_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        n = int(val)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _is_safe_public_url(url: str) -> bool:
    """SSRF 방어: http/https 공개 호스트만 허용 (사설/루프백/링크로컬 IP 차단)."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower().strip(".")
    if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal")):
        return False
    try:
        ip_obj = ipaddress.ip_address(host)
        return not (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        )
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return False
    return True


async def _is_safe_public_url_async(url: str) -> bool:
    return await asyncio.to_thread(_is_safe_public_url, url)


def detect_sns_platform(url: str) -> Optional[str]:
    """URL에서 지원 SNS 플랫폼 키를 판별합니다."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host in ("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"):
        if re.match(r"^/[^/]+/status/\d+", path):
            return "x"
    elif host in ("instagram.com", "www.instagram.com", "m.instagram.com", "kkinstagram.com", "ddinstagram.com", "vxinstagram.com"):
        if re.match(r"^/(p|reel|reels|tv|stories)/", path):
            return "instagram"
    elif host in ("tiktok.com", "www.tiktok.com", "m.tiktok.com", "vt.tiktok.com", "vm.tiktok.com", "vxtiktok.com", "vt.vxtiktok.com", "vm.vxtiktok.com"):
        if path and path != "/":
            return "tiktok"
    elif host in ("threads.net", "www.threads.net", "threads.com", "www.threads.com", "vxthreads.net", "fixthreads.net"):
        if "/post/" in path:
            return "threads"
    elif host in ("bsky.app", "www.bsky.app", "bskyx.app"):
        if "/profile/" in path and "/post/" in path:
            return "bluesky"
    elif host in ("reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "m.reddit.com", "rxddit.com", "redd.it"):
        if "/comments/" in path or "/s/" in path or host == "redd.it":
            return "reddit"
    elif host in ("pixiv.net", "www.pixiv.net", "phixiv.net"):
        if re.search(r"/artworks/\d+", path):
            return "pixiv"
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        if host == "youtu.be" and len(path) > 1:
            return "youtube"
        if path.startswith(("/shorts/", "/watch")):
            return "youtube"
    elif host in ("facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"):
        if host == "fb.watch" or any(seg in path for seg in ("/reel/", "/videos/", "/posts/", "/share/", "/watch", "/photo")):
            return "facebook"
    elif host in ("pinterest.com", "www.pinterest.com", "kr.pinterest.com", "pin.it"):
        if host == "pin.it" or "/pin/" in path:
            return "pinterest"
    return None


def _canonical_original_url(url: str, platform: str) -> str:
    """fxtwitter/kkinstagram 등 프록시 도메인 입력도 깔끔한 공식 원본 URL로 정규화합니다."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if platform == "x" and host in ("fxtwitter.com", "vxtwitter.com", "fixupx.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "mobile.x.com"):
        return urllib.parse.urlunsplit(("https", "x.com", parsed.path, "", ""))
    if platform == "instagram" and host in ("kkinstagram.com", "ddinstagram.com", "vxinstagram.com", "m.instagram.com", "instagram.com"):
        return urllib.parse.urlunsplit(("https", "www.instagram.com", parsed.path, "", ""))
    if platform == "tiktok" and host in ("vxtiktok.com", "vt.vxtiktok.com", "vm.vxtiktok.com"):
        orig_host = "vt.tiktok.com" if host.startswith("vt.") else ("vm.tiktok.com" if host.startswith("vm.") else "www.tiktok.com")
        return urllib.parse.urlunsplit(("https", orig_host, parsed.path, "", ""))
    if platform == "threads" and host in ("vxthreads.net", "fixthreads.net"):
        return urllib.parse.urlunsplit(("https", "www.threads.net", parsed.path, "", ""))
    if platform == "bluesky" and host == "bskyx.app":
        return urllib.parse.urlunsplit(("https", "bsky.app", parsed.path, "", ""))
    if platform == "reddit" and host == "rxddit.com":
        return urllib.parse.urlunsplit(("https", "www.reddit.com", parsed.path, "", ""))
    if platform == "pixiv" and host == "phixiv.net":
        return urllib.parse.urlunsplit(("https", "www.pixiv.net", parsed.path, "", ""))
    return url


async def _fetch_json(session: aiohttp.ClientSession, url: str, headers: Optional[dict] = None, timeout_sec: float = 6.5) -> Optional[Any]:
    if not await _is_safe_public_url_async(url):
        return None
    req_headers = {"User-Agent": HTTP_UA, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    try:
        async with session.get(url, headers=req_headers, timeout=aiohttp.ClientTimeout(total=timeout_sec), allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            raw = await resp.content.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                return None
            return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None


async def _fetch_html_og(session: aiohttp.ClientSession, url: str, ua: str = DISCORD_BOT_UA, timeout_sec: float = 6.5) -> dict[str, str]:
    if not await _is_safe_public_url_async(url):
        return {}
    try:
        async with session.get(
            url,
            headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                return {}
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "xml" not in ctype and ctype:
                return {}
            raw = await resp.content.read(MAX_HTML_BYTES)
            text = raw.decode("utf-8", errors="replace")
    except Exception:
        return {}

    og: dict[str, str] = {}
    for m in re.finditer(r"<meta\s+([^>]+)>", text, re.IGNORECASE):
        attrs = m.group(1)
        k_m = re.search(r'(?:property|name)\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        v_m = re.search(r'content\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        if k_m and v_m:
            key = k_m.group(1).strip().lower()
            val = html.unescape(v_m.group(1).strip())
            if val and key not in og:
                og[key] = val
    if "og:title" not in og:
        t_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        if t_m:
            og["og:title"] = html.unescape(re.sub(r"\s+", " ", t_m.group(1)).strip())
    return og


async def _download_media_bytes(
    session: aiohttp.ClientSession,
    url: str,
    max_bytes: int,
    headers: Optional[dict[str, str]] = None,
    timeout_sec: float = 12.0,
) -> Optional[bytes]:
    if not await _is_safe_public_url_async(url):
        return None
    req_headers = {"User-Agent": HTTP_UA}
    if headers:
        req_headers.update(headers)
    try:
        async with session.get(url, headers=req_headers, timeout=aiohttp.ClientTimeout(total=timeout_sec), allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > max_bytes:
                return None
            buf = bytearray()
            async for chunk in resp.content.iter_chunked(65536):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    return None
            return bytes(buf) if buf else None
    except Exception:
        return None


async def _ytdlp_extract_info(url: str, timeout_sec: float = 9.0) -> Optional[dict]:
    """설치된 yt-dlp를 활용해 Instagram/TikTok/Threads/YouTube Shorts 메타데이터 및 직접 MP4 URL 추출."""
    if not await _is_safe_public_url_async(url):
        return None

    def _run():
        try:
            import yt_dlp
        except Exception:
            return None
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": False,
            "socket_timeout": 6,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if isinstance(info, dict) and info.get("entries"):
                    entries = [e for e in info["entries"] if isinstance(e, dict)]
                    if entries:
                        return entries[0]
                return info if isinstance(info, dict) else None
        except Exception:
            return None

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_sec)
    except Exception:
        return None


def _pick_best_small_mp4(info: dict) -> tuple[str, dict[str, str]]:
    """yt-dlp 포맷 목록에서 Discord 업로드 가능한 9.5MB 이하 MP4 URL을 우선 선택합니다."""
    formats = info.get("formats") or []
    candidates: list[tuple[int, int, str, dict]] = []
    for f in formats:
        if not isinstance(f, dict):
            continue
        f_url = str(f.get("url") or "")
        if not f_url.startswith(("http://", "https://")):
            continue
        ext = str(f.get("ext") or "").lower()
        proto = str(f.get("protocol") or "").lower()
        if "m3u8" in proto or "dash" in proto:
            continue
        if ext != "mp4":
            continue
        vcodec = str(f.get("vcodec") or "")
        acodec = str(f.get("acodec") or "")
        if vcodec == "none":
            continue
        has_audio = 1 if (acodec and acodec != "none") else 0
        fsize = _safe_int(f.get("filesize") or f.get("filesize_approx")) or 0
        if fsize > MAX_VIDEO_BYTES:
            continue
        height = _safe_int(f.get("height")) or 0
        hdrs = f.get("http_headers") if isinstance(f.get("http_headers"), dict) else {}
        candidates.append((has_audio, height, f_url, hdrs))

    if candidates:
        # 오디오 포함 + 720p 이하 적당 해상도 우선
        candidates.sort(key=lambda x: (x[0], -(abs(x[1] - 720) if x[1] else 9999)), reverse=True)
        _, _, best_url, best_hdrs = candidates[0]
        return best_url, best_hdrs

    direct = str(info.get("url") or "")
    if direct.startswith(("http://", "https://")) and str(info.get("ext") or "").lower() == "mp4":
        hdrs = info.get("http_headers") if isinstance(info.get("http_headers"), dict) else {}
        return direct, hdrs
    return "", {}


def _parse_iso_ts(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return None


# ==========================================
# 플랫폼별 추출기
# ==========================================
async def _extract_x(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    m = re.search(r"/([^/]+)/status/(\d+)", urllib.parse.urlsplit(url).path)
    if not m:
        return None
    user_seg, status_id = m.group(1), m.group(2)
    canonical = f"https://x.com/{user_seg}/status/{status_id}"

    data = await _fetch_json(session, f"https://api.fxtwitter.com/{user_seg}/status/{status_id}")
    if isinstance(data, dict) and isinstance(data.get("tweet"), dict):
        tw = data["tweet"]
        author = tw.get("author") or {}
        media = tw.get("media") or {}
        photos = [str(p.get("url")) for p in (media.get("photos") or []) if isinstance(p, dict) and p.get("url")]
        videos = [v for v in (media.get("videos") or []) if isinstance(v, dict) and v.get("url")]
        video_url = ""
        if videos:
            # 가장 적절한 비트레이트/크기 MP4 선택
            v0 = videos[0]
            variants = [vr for vr in (v0.get("variants") or []) if isinstance(vr, dict) and str(vr.get("content_type", "")).startswith("video/mp4") and vr.get("url")]
            if variants:
                variants.sort(key=lambda x: _safe_int(x.get("bitrate")) or 0)
                mid = variants[len(variants) // 2]
                video_url = str(mid.get("url") or v0.get("url") or "")
            else:
                video_url = str(v0.get("url") or "")
            if not photos and v0.get("thumbnail_url"):
                photos.append(str(v0["thumbnail_url"]))

        handle = str(author.get("screen_name") or user_seg)
        return SnsPostData(
            platform="x",
            url=canonical,
            author_name=str(author.get("name") or handle),
            author_handle=handle,
            author_url=f"https://x.com/{handle}",
            author_avatar=str(author.get("avatar_url") or ""),
            caption=str(tw.get("text") or ""),
            views=_safe_int(tw.get("views")),
            likes=_safe_int(tw.get("likes")),
            reposts=_safe_int(tw.get("retweets")),
            comments=_safe_int(tw.get("replies")),
            created_ts=_safe_int(tw.get("created_timestamp")),
            video_url=video_url,
            image_urls=photos[:4],
            site_label="X (Twitter)",
        )
    return None


async def _extract_instagram(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    canonical = _canonical_original_url(url, "instagram")
    parsed = urllib.parse.urlsplit(canonical)

    # 1순위: yt-dlp (작성자, @핸들, 조회수/좋아요/댓글, 캡션, MP4 영상까지 풀 추출)
    info = await _ytdlp_extract_info(canonical, timeout_sec=8.5)
    if isinstance(info, dict) and (info.get("uploader") or info.get("channel") or info.get("description") or info.get("thumbnail")):
        handle = str(info.get("uploader_id") or info.get("channel_id") or info.get("uploader") or "").lstrip("@")
        author_name = str(info.get("uploader") or info.get("channel") or handle or "Instagram")
        video_url, video_hdrs = _pick_best_small_mp4(info)
        thumb = str(info.get("thumbnail") or "")
        images = [thumb] if thumb.startswith(("http://", "https://")) else []
        ts = _safe_int(info.get("timestamp"))
        if not ts and info.get("upload_date") and len(str(info["upload_date"])) == 8:
            try:
                dt = datetime.datetime.strptime(str(info["upload_date"]), "%Y%m%d").replace(tzinfo=datetime.timezone.utc)
                ts = int(dt.timestamp())
            except Exception:
                pass
        return SnsPostData(
            platform="instagram",
            url=canonical,
            author_name=author_name,
            author_handle=handle,
            author_url=f"https://www.instagram.com/{handle}/" if handle else canonical,
            author_avatar="",
            caption=str(info.get("description") or info.get("title") or ""),
            views=_safe_int(info.get("view_count")),
            likes=_safe_int(info.get("like_count")),
            comments=_safe_int(info.get("comment_count")),
            created_ts=ts,
            video_url=video_url,
            video_headers=video_hdrs,
            image_urls=images[:4],
            download_images=bool(images),
            site_label="Instagram",
        )

    # 2순위: kkinstagram / vxinstagram OG 메타데이터 추출
    for proxy_host in ("kkinstagram.com", "vxinstagram.com"):
        proxy_url = urllib.parse.urlunsplit(("https", proxy_host, parsed.path, "", ""))
        og = await _fetch_html_og(session, proxy_url, ua=DISCORD_BOT_UA)
        if og.get("og:title") or og.get("og:description") or og.get("og:video") or og.get("og:image"):
            raw_title = og.get("og:title") or "Instagram"
            handle_m = re.search(r"@([A-Za-z0-9._]+)", raw_title)
            handle = handle_m.group(1) if handle_m else ""
            author_name = re.sub(r"\s*\(@[^)]+\)\s*", "", raw_title).strip() or handle or "Instagram"
            vid = og.get("og:video:secure_url") or og.get("og:video") or ""
            img = og.get("og:image") or ""
            return SnsPostData(
                platform="instagram",
                url=canonical,
                author_name=author_name,
                author_handle=handle,
                author_url=f"https://www.instagram.com/{handle}/" if handle else canonical,
                caption=og.get("og:description") or "",
                video_url=vid,
                image_urls=[img] if img.startswith(("http://", "https://")) else [],
                download_images=bool(img),
                site_label="Instagram",
            )
    return None


async def _extract_tiktok(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    canonical = _canonical_original_url(url, "tiktok")
    q = urllib.parse.quote(canonical, safe="")
    res = await _fetch_json(session, f"https://www.tikwm.com/api/?url={q}")
    if isinstance(res, dict) and res.get("code") == 0 and isinstance(res.get("data"), dict):
        d = res["data"]
        author = d.get("author") or {}
        handle = str(author.get("unique_id") or "")
        author_name = str(author.get("nickname") or handle or "TikTok")
        images = [str(u) for u in (d.get("images") or []) if isinstance(u, str) and u.startswith(("http://", "https://"))]
        video_url = "" if images else str(d.get("play") or "")
        if not images and d.get("cover"):
            images = [str(d["cover"])]
        return SnsPostData(
            platform="tiktok",
            url=canonical,
            author_name=author_name,
            author_handle=handle,
            author_url=f"https://www.tiktok.com/@{handle}" if handle else canonical,
            author_avatar=str(author.get("avatar") or ""),
            caption=str(d.get("title") or ""),
            views=_safe_int(d.get("play_count")),
            likes=_safe_int(d.get("digg_count")),
            reposts=_safe_int(d.get("share_count")),
            comments=_safe_int(d.get("comment_count")),
            created_ts=_safe_int(d.get("create_time")),
            video_url=video_url,
            image_urls=images[:4],
            site_label="TikTok",
        )

    info = await _ytdlp_extract_info(canonical, timeout_sec=8.5)
    if isinstance(info, dict):
        handle = str(info.get("uploader_id") or info.get("uploader") or "").lstrip("@")
        video_url, video_hdrs = _pick_best_small_mp4(info)
        thumb = str(info.get("thumbnail") or "")
        return SnsPostData(
            platform="tiktok",
            url=canonical,
            author_name=str(info.get("uploader") or handle or "TikTok"),
            author_handle=handle,
            author_url=f"https://www.tiktok.com/@{handle}" if handle else canonical,
            caption=str(info.get("description") or info.get("title") or ""),
            views=_safe_int(info.get("view_count")),
            likes=_safe_int(info.get("like_count")),
            reposts=_safe_int(info.get("repost_count")),
            comments=_safe_int(info.get("comment_count")),
            created_ts=_safe_int(info.get("timestamp")),
            video_url=video_url,
            video_headers=video_hdrs,
            image_urls=[thumb] if thumb.startswith(("http://", "https://")) else [],
            site_label="TikTok",
        )
    return None


async def _extract_bluesky(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    canonical = _canonical_original_url(url, "bluesky")
    m = re.search(r"/profile/([^/]+)/post/([^/?#]+)", urllib.parse.urlsplit(canonical).path)
    if not m:
        return None
    actor, rkey = m.group(1), m.group(2)
    uri = urllib.parse.quote(f"at://{actor}/app.bsky.feed.post/{rkey}", safe="")
    res = await _fetch_json(session, f"https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?uri={uri}&depth=0&parentHeight=0")
    thread = res.get("thread") if isinstance(res, dict) else None
    post = thread.get("post") if isinstance(thread, dict) else None
    if not isinstance(post, dict):
        return None
    author = post.get("author") or {}
    rec = post.get("record") or {}
    embed = post.get("embed") or {}

    images: list[str] = []
    if isinstance(embed.get("images"), list):
        for im in embed["images"]:
            if isinstance(im, dict) and im.get("fullsize"):
                images.append(str(im["fullsize"]))
    elif isinstance(embed.get("media"), dict) and isinstance(embed["media"].get("images"), list):
        for im in embed["media"]["images"]:
            if isinstance(im, dict) and im.get("fullsize"):
                images.append(str(im["fullsize"]))
    if not images and embed.get("thumbnail"):
        images.append(str(embed["thumbnail"]))

    handle = str(author.get("handle") or actor)
    return SnsPostData(
        platform="bluesky",
        url=canonical,
        author_name=str(author.get("displayName") or handle),
        author_handle=handle,
        author_url=f"https://bsky.app/profile/{handle}",
        author_avatar=str(author.get("avatar") or ""),
        caption=str(rec.get("text") or ""),
        likes=_safe_int(post.get("likeCount")),
        reposts=_safe_int(post.get("repostCount")),
        comments=_safe_int(post.get("replyCount")),
        created_ts=_parse_iso_ts(rec.get("createdAt") or post.get("indexedAt")),
        image_urls=images[:4],
        site_label="Bluesky",
    )


async def _extract_pixiv(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    m = re.search(r"/artworks/(\d+)", urllib.parse.urlsplit(url).path)
    if not m:
        return None
    art_id = m.group(1)
    canonical = f"https://www.pixiv.net/artworks/{art_id}"
    res = await _fetch_json(session, f"https://www.phixiv.net/api/info?id={art_id}")
    if not isinstance(res, dict) or not res.get("title"):
        return None
    author_name = str(res.get("author_name") or "Pixiv Artist")
    author_id = str(res.get("author_id") or "")
    raw_desc = str(res.get("description") or "")
    clean_desc = html.unescape(re.sub(r"<[^>]+>", " ", raw_desc)).strip()
    tags = [f"#{t}" for t in (res.get("tags") or [])[:8] if isinstance(t, str)]
    caption_parts = [f"**{res.get('title')}**"]
    if clean_desc:
        caption_parts.append(clean_desc[:400])
    if tags:
        caption_parts.append(" ".join(tags))
    imgs = [str(u) for u in (res.get("image_proxy_urls") or []) if isinstance(u, str) and u.startswith(("http://", "https://"))]
    return SnsPostData(
        platform="pixiv",
        url=canonical,
        author_name=author_name,
        author_handle=f"pixiv/{author_id}" if author_id else "",
        author_url=f"https://www.pixiv.net/users/{author_id}" if author_id else canonical,
        author_avatar=str(res.get("profile_image_url") or ""),
        caption="\n".join(caption_parts),
        created_ts=_parse_iso_ts(res.get("create_date")),
        image_urls=imgs[:4],
        site_label="Pixiv",
    )


async def _extract_reddit(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    canonical = _canonical_original_url(url, "reddit")
    parsed = urllib.parse.urlsplit(canonical)
    json_url = urllib.parse.urlunsplit(("https", "www.reddit.com", parsed.path.rstrip("/") + ".json", "", ""))
    res = await _fetch_json(session, json_url, headers={"User-Agent": "norosi-bot/1.0 (Discord Embed Preview)"})
    if isinstance(res, list) and res and isinstance(res[0], dict):
        children = (res[0].get("data") or {}).get("children") or []
        if children and isinstance(children[0], dict):
            p = children[0].get("data") or {}
            author = str(p.get("author") or "redditor")
            sub = str(p.get("subreddit_name_prefixed") or "r/reddit")
            title = html.unescape(str(p.get("title") or ""))
            body = html.unescape(str(p.get("selftext") or "")).strip()
            caption = f"**{title}**" + (f"\n{body[:500]}" if body else "")
            video_url = ""
            images: list[str] = []
            media = p.get("secure_media") or p.get("media") or {}
            if isinstance(media, dict) and isinstance(media.get("reddit_video"), dict):
                video_url = str(media["reddit_video"].get("fallback_url") or "")
            if p.get("is_gallery") and isinstance(p.get("media_metadata"), dict):
                for item in list(p["media_metadata"].values())[:4]:
                    if isinstance(item, dict):
                        s_url = html.unescape(str((item.get("s") or {}).get("u") or ""))
                        if s_url.startswith("http"):
                            images.append(s_url)
            if not images:
                preview_imgs = (p.get("preview") or {}).get("images") or []
                if preview_imgs and isinstance(preview_imgs[0], dict):
                    s_url = html.unescape(str((preview_imgs[0].get("source") or {}).get("url") or ""))
                    if s_url.startswith("http"):
                        images.append(s_url)
            return SnsPostData(
                platform="reddit",
                url=canonical,
                author_name=sub,
                author_handle=f"u/{author}",
                author_url=f"https://www.reddit.com/user/{author}",
                caption=caption,
                likes=_safe_int(p.get("ups") or p.get("score")),
                comments=_safe_int(p.get("num_comments")),
                created_ts=_safe_int(p.get("created_utc")),
                video_url=video_url,
                image_urls=images[:4],
                site_label="Reddit",
            )
    return None


async def _extract_threads(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    canonical = _canonical_original_url(url, "threads")
    parsed = urllib.parse.urlsplit(canonical)
    handle_m = re.search(r"/@([^/]+)/", parsed.path)
    handle = handle_m.group(1) if handle_m else ""

    for proxy_host in ("vxthreads.net", "fixthreads.net"):
        proxy_url = urllib.parse.urlunsplit(("https", proxy_host, parsed.path, "", ""))
        og = await _fetch_html_og(session, proxy_url, ua=DISCORD_BOT_UA)
        if og.get("og:description") or og.get("og:image") or og.get("og:video"):
            title = og.get("og:title") or (f"@{handle}" if handle else "Threads")
            vid = og.get("og:video:secure_url") or og.get("og:video") or ""
            img = og.get("og:image") or ""
            return SnsPostData(
                platform="threads",
                url=canonical,
                author_name=title,
                author_handle=handle,
                author_url=f"https://www.threads.net/@{handle}" if handle else canonical,
                caption=og.get("og:description") or "",
                video_url=vid,
                image_urls=[img] if img.startswith(("http://", "https://")) else [],
                site_label="Threads",
            )
    return None


async def _extract_youtube(session: aiohttp.ClientSession, url: str) -> Optional[SnsPostData]:
    parsed = urllib.parse.urlsplit(url)
    is_shorts = "/shorts/" in (parsed.path or "")
    q = urllib.parse.quote(url, safe="")
    oembed = await _fetch_json(session, f"https://www.youtube.com/oembed?url={q}&format=json")
    info = await _ytdlp_extract_info(url, timeout_sec=7.5) if is_shorts else None

    if isinstance(info, dict):
        video_url, video_hdrs = _pick_best_small_mp4(info)
        thumb = str(info.get("thumbnail") or (oembed.get("thumbnail_url") if isinstance(oembed, dict) else "") or "")
        handle = str(info.get("uploader_id") or "").lstrip("@")
        return SnsPostData(
            platform="youtube",
            url=url,
            author_name=str(info.get("uploader") or info.get("channel") or "YouTube"),
            author_handle=handle,
            author_url=str(info.get("channel_url") or info.get("uploader_url") or url),
            caption=str(info.get("title") or ""),
            views=_safe_int(info.get("view_count")),
            likes=_safe_int(info.get("like_count")),
            comments=_safe_int(info.get("comment_count")),
            created_ts=_safe_int(info.get("timestamp")),
            video_url=video_url,
            video_headers=video_hdrs,
            image_urls=[thumb] if thumb.startswith("http") else [],
            site_label="YouTube Shorts",
        )

    if isinstance(oembed, dict) and oembed.get("title"):
        thumb = str(oembed.get("thumbnail_url") or "")
        return SnsPostData(
            platform="youtube",
            url=url,
            author_name=str(oembed.get("author_name") or "YouTube"),
            author_url=str(oembed.get("author_url") or url),
            caption=str(oembed.get("title") or ""),
            image_urls=[thumb] if thumb.startswith("http") else [],
            site_label="YouTube",
        )
    return None


async def _extract_generic_og(session: aiohttp.ClientSession, url: str, platform: str) -> Optional[SnsPostData]:
    og = await _fetch_html_og(session, url, ua=DISCORD_BOT_UA)
    if not og:
        og = await _fetch_html_og(session, url, ua=HTTP_UA)
    if not (og.get("og:title") or og.get("og:description") or og.get("og:image") or og.get("og:video")):
        return None
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    site_name = og.get("og:site_name") or PLATFORM_META.get(platform, {}).get("name") or host
    title = og.get("og:title") or site_name
    desc = og.get("og:description") or ""
    caption = f"**{title}**" + (f"\n{desc[:500]}" if desc and desc != title else "")
    img = og.get("og:image") or ""
    vid = og.get("og:video:secure_url") or og.get("og:video") or ""
    return SnsPostData(
        platform=platform if platform in PLATFORM_META else "web",
        url=url,
        author_name=site_name,
        author_url=url,
        caption=caption,
        video_url=vid if vid.startswith(("http://", "https://")) else "",
        image_urls=[img] if img.startswith(("http://", "https://")) else [],
        site_label=site_name,
    )


async def fetch_sns_post_data(url: str, platform: Optional[str] = None) -> Optional[SnsPostData]:
    """지원 SNS/웹 링크에서 작성자·통계·본문·미디어 정보를 추출합니다."""
    plat = platform or detect_sns_platform(url) or "web"
    async with aiohttp.ClientSession() as session:
        extractors = {
            "x": _extract_x,
            "instagram": _extract_instagram,
            "tiktok": _extract_tiktok,
            "bluesky": _extract_bluesky,
            "pixiv": _extract_pixiv,
            "reddit": _extract_reddit,
            "threads": _extract_threads,
            "youtube": _extract_youtube,
        }
        fn = extractors.get(plat)
        data = None
        if fn:
            try:
                data = await fn(session, url)
            except Exception:
                data = None
        if data is None and plat in ("facebook", "pinterest", "threads", "web"):
            data = await _extract_generic_og(session, url, plat)
        return data


def _format_stats_line(post: SnsPostData) -> str:
    parts: list[str] = []
    if post.views is not None:
        parts.append(f"▶️ **{post.views:,}**")
    if post.likes is not None:
        parts.append(f"❤️ **{post.likes:,}**")
    if post.reposts is not None:
        parts.append(f"🔁 **{post.reposts:,}**")
    if post.comments is not None:
        parts.append(f"💬 **{post.comments:,}**")
    return "  ".join(parts)


async def build_sns_components_v2_payload(
    post: SnsPostData,
    *,
    top_text: str,
    sender_prefix: str = "",
) -> tuple[discord.ui.LayoutView, list[discord.File]]:
    """
    스크린샷과 동일한 Discord Components V2 리치 카드(LayoutView + Container + Section + Thumbnail + MediaGallery + Link Button)를 생성합니다.
    영상(<=9.5MB)은 직접 첨부해 카드 안에서 바로 재생되도록 구성합니다.
    """
    meta = PLATFORM_META.get(post.platform, PLATFORM_META["web"])
    accent = discord.Colour(int(meta["color"]))
    p_name = post.site_label or meta["name"]
    p_emoji = meta["emoji"]

    files: list[discord.File] = []
    gallery_items: list[discord.MediaGalleryItem] = []

    async with aiohttp.ClientSession() as session:
        # 1) 동영상 우선 다운로드 (9.5MB 이하 시 카드 내 인라인 재생!)
        video_attached = False
        if post.video_url:
            v_bytes = await _download_media_bytes(
                session,
                post.video_url,
                MAX_VIDEO_BYTES,
                headers=post.video_headers or None,
                timeout_sec=12.0,
            )
            if v_bytes:
                files.append(discord.File(io.BytesIO(v_bytes), filename="sns_video.mp4"))
                gallery_items.append(discord.MediaGalleryItem("attachment://sns_video.mp4"))
                video_attached = True

        # 2) 이미지 갤러리 (영상 미첨부 시 또는 다중 이미지 게시물)
        if not video_attached and post.image_urls:
            for idx, img_url in enumerate(post.image_urls[:4]):
                if not img_url.startswith(("http://", "https://")):
                    continue
                if post.download_images:
                    i_bytes = await _download_media_bytes(
                        session,
                        img_url,
                        MAX_IMAGE_BYTES,
                        headers=post.image_headers or None,
                        timeout_sec=8.0,
                    )
                    if i_bytes:
                        fname = f"sns_img_{idx}.jpg"
                        files.append(discord.File(io.BytesIO(i_bytes), filename=fname))
                        gallery_items.append(discord.MediaGalleryItem(f"attachment://{fname}"))
                        continue
                gallery_items.append(discord.MediaGalleryItem(img_url))

    layout = discord.ui.LayoutView(timeout=None)

    # 카드 상단 본문 / 클린 URL
    header_top = f"{sender_prefix}\n{top_text}" if sender_prefix else top_text
    if header_top.strip():
        layout.add_item(discord.ui.TextDisplay(header_top[:1800]))

    container_children: list[discord.ui.Item] = []

    # 1. 작성자 헤더 (+ 우측 상단 프로필 썸네일)
    author_lines: list[str] = []
    if post.author_name:
        author_lines.append(f"**{discord.utils.escape_markdown(post.author_name[:100])}**")
    if post.author_handle:
        h_disp = post.author_handle if post.author_handle.startswith(("@", "u/", "r/", "pixiv/")) else f"@{post.author_handle}"
        if post.author_url and post.author_url.startswith(("http://", "https://")):
            author_lines.append(f"[{h_disp}]({post.author_url})")
        else:
            author_lines.append(h_disp)

    if author_lines:
        author_text = "\n".join(author_lines)
        if post.author_avatar and post.author_avatar.startswith(("http://", "https://")):
            container_children.append(
                discord.ui.Section(
                    discord.ui.TextDisplay(author_text),
                    accessory=discord.ui.Thumbnail(post.author_avatar),
                )
            )
        else:
            container_children.append(discord.ui.TextDisplay(author_text))

    # 2. 통계(조회수·좋아요·리트윗·댓글) + 본문 캡션
    body_blocks: list[str] = []
    stats_line = _format_stats_line(post)
    if stats_line:
        body_blocks.append(stats_line)
    if post.caption and post.caption.strip():
        cap = post.caption.strip()
        if len(cap) > 1200:
            cap = cap[:1197].rstrip() + "…"
        body_blocks.append(cap)
    if body_blocks:
        container_children.append(discord.ui.TextDisplay("\n\n".join(body_blocks)))

    # 3. 미디어 갤러리 (인라인 영상 플레이어 / 이미지 최대 4장)
    if gallery_items:
        container_children.append(discord.ui.MediaGallery(*gallery_items))

    # 4. 하단 푸터 (플랫폼명 · 현지화 타임스탬프 + 우측 바로가기 버튼)
    ts_part = f" · <t:{post.created_ts}:f>" if post.created_ts else ""
    footer_text = f"-# {p_emoji} {p_name}{ts_part}"
    btn_url = post.url if (post.url.startswith(("http://", "https://")) and len(post.url) <= 512) else None
    if btn_url:
        container_children.append(
            discord.ui.Section(
                discord.ui.TextDisplay(footer_text),
                accessory=discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label=p_name[:80],
                    url=btn_url,
                ),
            )
        )
    else:
        container_children.append(discord.ui.TextDisplay(footer_text))

    container = discord.ui.Container(*container_children, accent_colour=accent)
    layout.add_item(container)
    return layout, files
