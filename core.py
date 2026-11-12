import os
import re
import copy
import json
import time
import random
import asyncio
import datetime
import calendar
import threading
from collections import OrderedDict, defaultdict, deque
from typing import Optional, List, Dict, Any, Union
import urllib.request
import urllib.parse
import urllib.error

import base64

class _RequestsResponse:
    def __init__(self, status_code, content_bytes):
        self.status_code = status_code
        self._content = content_bytes

    @property
    def text(self):
        return self._content.decode("utf-8", errors="ignore")

    def json(self):
        return json.loads(self.text)

class _RequestsCompat:
    @staticmethod
    def _apply_auth(headers, auth):
        if auth and isinstance(auth, (tuple, list)) and len(auth) == 2:
            user_pass = f"{auth[0]}:{auth[1]}".encode("utf-8")
            b64_auth = base64.b64encode(user_pass).decode("utf-8")
            headers["Authorization"] = f"Basic {b64_auth}"

    @staticmethod
    def get(url, headers=None, params=None, auth=None, timeout=5, **kwargs):
        headers = dict(headers or {})
        _RequestsCompat._apply_auth(headers, auth)
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _RequestsResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            return _RequestsResponse(e.code, e.read())
        except Exception:
            return _RequestsResponse(500, b"{}")

    @staticmethod
    def post(url, data=None, json_data=None, json=None, headers=None, auth=None, timeout=5, **kwargs):
        headers = dict(headers or {})
        _RequestsCompat._apply_auth(headers, auth)
        body = None
        j_data = json if json is not None else json_data
        if j_data is not None:
            body = json.dumps(j_data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            if isinstance(data, dict):
                body = urllib.parse.urlencode(data).encode("utf-8")
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = data
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _RequestsResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            return _RequestsResponse(e.code, e.read())
        except Exception:
            return _RequestsResponse(500, b"{}")

    @staticmethod
    def put(url, json_data=None, json=None, headers=None, auth=None, timeout=5, **kwargs):
        headers = dict(headers or {})
        _RequestsCompat._apply_auth(headers, auth)
        body = None
        j_data = json if json is not None else json_data
        if j_data is not None:
            body = json.dumps(j_data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _RequestsResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            return _RequestsResponse(e.code, e.read())
        except Exception:
            return _RequestsResponse(500, b"{}")

try:
    import requests as _real_requests
    requests = _real_requests
except ImportError:
    requests = _RequestsCompat()
import discord
from discord import app_commands
import yt_dlp

# ==========================================
# ==========================================
# 1. 환경 변수 (.env) 자동 로더 및 보안 설정
# ==========================================
_FOUND_ENV_FILES = []
_PARSED_ENV_KEYS = []

def _load_env_file():
    """
    로컬, GCP VM, Render, 도커 등 어떤 환경에서도 .env 파일을 자동으로 감지하여
    빈 환경변수 덮어쓰기, UTF-8 BOM(\ufeff) 정규화, 다중 토큰 별칭을 지원하도록 환경변수에 주입합니다.
    """
    global _FOUND_ENV_FILES, _PARSED_ENV_KEYS
    _FOUND_ENV_FILES = []
    _PARSED_ENV_KEYS = []

    # 1. python-dotenv 가 있으면 override=True 로 1차 시도
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass

    # 2. 광범위한 디렉토리 및 파일 이름 탐색
    candidate_dirs = [
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
        os.path.expanduser("~"),
        os.path.expanduser("~/norosi"),
        os.path.expanduser("~/alyagsosiji/norosi"),
        "/home/ubuntu/norosi",
        "/home/ubuntu",
        "/home/antigravity/norosi",
        "/home/antigravity/alyagsosiji/norosi",
        "/home/debian/norosi",
        "/root/norosi"
    ]
    # 사용자 정의 환경변수 경로가 있다면 최우선 포함
    custom_env = os.environ.get("ENV_FILE") or os.environ.get("DOTENV_PATH")
    if custom_env:
        candidate_dirs.insert(0, os.path.dirname(os.path.abspath(custom_env)))

    candidate_files = [".env", ".env.local", ".env.production", ".env.txt", "deploy/.env"]

    seen_paths = set()
    for c_dir in candidate_dirs:
        if not c_dir or not os.path.isdir(c_dir):
            continue
        for c_file in candidate_files:
            env_path = os.path.normpath(os.path.join(c_dir, c_file))
            if env_path in seen_paths:
                continue
            seen_paths.add(env_path)

            if os.path.isfile(env_path):
                _FOUND_ENV_FILES.append(env_path)
                try:
                    # UTF-8 with BOM 자동 제거 (utf-8-sig)
                    with open(env_path, "r", encoding="utf-8-sig") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            if line.startswith("export "):
                                line = line[7:].strip()
                            if "=" not in line:
                                continue
                            k, v = line.split("=", 1)
                            k = k.strip().lstrip("\ufeff")
                            # 주석 및 따옴표 제거
                            v = v.strip()
                            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                                v = v[1:-1].strip()
                            else:
                                # 인라인 주석 제거 (따옴표 밖의 #)
                                if " #" in v:
                                    v = v.split(" #", 1)[0].strip()

                            if k:
                                _PARSED_ENV_KEYS.append(k)
                                curr = os.environ.get(k, "")
                                # 환경변수가 없거나, 빈 문자열이거나, .env에 실질적인 값이 들어있다면 우선 주입
                                if v or not curr.strip():
                                    os.environ[k] = v
                except Exception:
                    pass

def get_token() -> str:
    """다양한 환경변수 이름(DISCORD_TOKEN, BOT_TOKEN 등)에서 유효한 디스코드 토큰을 추출합니다."""
    candidates = ["DISCORD_TOKEN", "BOT_TOKEN", "DISCORD_BOT_TOKEN", "TOKEN", "DISCORD_APP_TOKEN"]
    for key in candidates:
        val = os.getenv(key, "").strip().strip('"').strip("'")
        if val and val != "여기에_디스코드_봇_토큰_입력":
            return val
    # 아직도 없으면 _load_env_file() 재실행 후 재확인
    _load_env_file()
    for key in candidates:
        val = os.getenv(key, "").strip().strip('"').strip("'")
        if val and val != "여기에_디스코드_봇_토큰_입력":
            return val
    return ""

def get_env_diagnostics() -> dict:
    """토큰 미설정 등 문제 발생 시 원인 분석을 위한 상세 진단 정보를 반환합니다."""
    token = get_token()
    token_status = "OK" if token else "MISSING"
    masked_token = f"{token[:4]}...{token[-4:]} (길이: {len(token)})" if token else "None"
    return {
        "token_status": token_status,
        "masked_token": masked_token,
        "found_env_files": list(set(_FOUND_ENV_FILES)),
        "parsed_keys": sorted(list(set(_PARSED_ENV_KEYS))),
        "cwd": os.getcwd(),
        "script_dir": os.path.dirname(os.path.abspath(__file__)),
    }

_load_env_file()

# 실제 키 값을 코드에서 완전히 비워둡니다 (.env에서만 로드)
TOKEN = get_token()
PORT = int(os.getenv("PORT", "10000") or "10000")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "1028926437710905375") or "1028926437710905375")

# 🔥 Firebase Realtime Database 설정 (.env)
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "").strip().rstrip("/")
FIREBASE_SECRET = os.getenv("FIREBASE_SECRET", "").strip()

# 🎵 Spotify API 키 설정 (.env)
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID", "").strip()
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "").strip()

KST = datetime.timezone(datetime.timedelta(hours=9))
DATA_FILE = "ddays_data.json"
PROSEKA_CACHE_FILE = "proseka_kr_cache.json"
RANDOM_KEYWORDS = ["pop", "lofi", "k-pop", "indie", "jazz", "r&b", "piano", "acoustic", "chill", "synthwave", "rock"]

# 실행 중인 뽀모도로 타이머 태스크 관리용 딕셔너리
ACTIVE_POMODORO_TASKS = {}

# 중복 카드 크리스탈 변환 단가 (원본 1장 제외 초과분 1장당 지급 크리스탈)
DUPLICATE_CRYSTAL_RATES = {
    "rarity_4": 100,
    "rarity_birthday": 60,
    "rarity_3": 25,
    "rarity_2": 5,
    "rarity_1": 5
}

# 월간 출석 개근 보상 마일스톤 (이번 달 해당 출석일 달성 시 추가 크리스탈 즉시 지급)
ATTENDANCE_MILESTONES = [
    {"days": 7, "reward": 300, "title": "7일 주간 단골", "emoji": "🥉"},
    {"days": 14, "reward": 500, "title": "14일 격주 성실", "emoji": "🥈"},
    {"days": 21, "reward": 1000, "title": "21일 3주 마스터", "emoji": "🥇"},
    {"days": 28, "reward": 2000, "title": "이번 달 개근왕", "emoji": "👑"}
]

# 인메모리 데이터 캐시 & 스레드 안전 락 (출석 초기화 방지 및 자동완성 0ms 즉시 응답용)
_DATA_LOCK = threading.RLock()
_DATA_CACHE = None
_FIREBASE_DISABLED_UNTIL = 0.0

# 일러스트 바이트 & 성공 URL LRU 캐시 (응답 지연 및 타임아웃 방지용)
_IMAGE_BYTES_CACHE = OrderedDict()
_ASSET_URL_CACHE = {}
MAX_IMAGE_CACHE_SIZE = 80


def get_today_str():
    """한국 표준시(KST) 자정(00:00) 기준으로 바뀌는 오늘 날짜 문자열 반환"""
    return datetime.datetime.now(KST).strftime("%Y-%m-%d")


def get_yesterday_str():
    return (datetime.datetime.now(KST).date() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def get_now_datetime_str():
    return datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


async def safe_defer(interaction: discord.Interaction, ephemeral: bool = False):
    """
    디스코드 응답 지연(defer) 중복 호출 예외(InteractionResponded) 및 3초 타임아웃을 안전하게 방어하는 헬퍼.
    """
    if interaction and getattr(interaction, "response", None) and not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=ephemeral)
        except Exception:
            pass


async def safe_send_response(interaction: discord.Interaction, embed=None, content=None, file=None, files=None, view=None, ephemeral=False):
    """
    interaction 수신/지연(defer) 상태에 맞춰 followup.send 또는 response.send_message를 안전하게 선택하여 전송합니다.
    embed 파라미터에 문자열(str)이 위치인자로 전달된 경우 자동으로 content로 정규화하여
    'str' object has no attribute 'to_dict' 오류를 원천 차단합니다.
    """
    if isinstance(embed, str) and content is None:
        content = embed
        embed = None
    elif isinstance(content, discord.Embed) and embed is None:
        embed = content
        content = None

    kwargs = {}
    if embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content
    if file is not None:
        kwargs["file"] = file
    if files is not None:
        kwargs["files"] = files
    if view is not None:
        kwargs["view"] = view
    kwargs["ephemeral"] = ephemeral

    try:
        if interaction and getattr(interaction, "response", None) and interaction.response.is_done():
            return await interaction.followup.send(**kwargs)
        elif interaction and getattr(interaction, "response", None):
            return await interaction.response.send_message(**kwargs)
    except discord.InteractionResponded:
        try:
            return await interaction.followup.send(**kwargs)
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ [safe_send_response 예외] {e}", flush=True)


class SafeView(discord.ui.View):
    """'애플리케이션 응답 없음' 먹통 방지 커스텀 UI View 래퍼"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message: Optional[discord.Message] = None
        self._last_interaction: Optional[discord.Interaction] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """버튼/드롭다운 조작 시 뷰가 붙어 있는 메시지와 최근 인터랙션을 기억 (타임아웃 시 자동 비활성화용)"""
        self._last_interaction = interaction
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"⚠️ [UI View 버튼 오류] {item}: {error}", flush=True)
        msg = f"⚠️ 버튼 처리 중 오류가 발생했습니다: `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    async def on_timeout(self):
        """View 제한 시간 만료 시 버튼/셀렉트 자동 비활성화(disabled) 처리로 깔끔한 UX 보장"""
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        # 1순위: 메시지 직접 수정 / 2순위: 최근 인터랙션 토큰으로 수정 (나만 보기 메시지 대응)
        try:
            if self.message is not None:
                await self.message.edit(view=self)
                return
        except Exception:
            pass
        try:
            if self._last_interaction is not None:
                await self._last_interaction.edit_original_response(view=self)
        except Exception:
            pass


class SafeModal(discord.ui.Modal):
    """'애플리케이션 응답 없음' 먹통 방지 커스텀 UI Modal 래퍼"""
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"⚠️ [UI Modal 입력 오류]: {error}", flush=True)
        msg = f"⚠️ 모달 제출 처리 중 오류가 발생했습니다: `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


def get_time_until_midnight_str():
    """한국 표준시(KST) 다음 자정(00:00:00)까지 남은 시간을 계산하여 반환"""
    now = datetime.datetime.now(KST)
    tomorrow_midnight = datetime.datetime.combine(
        now.date() + datetime.timedelta(days=1),
        datetime.time(0, 0, 0),
        tzinfo=KST
    )
    rem_sec = max(0, int((tomorrow_midnight - now).total_seconds()))
    h, rem = divmod(rem_sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}시간 {m}분 {s}초"


def get_mood_keyword():
    """요일 및 시간대별 감성 맞춤 음악 키워드 오프셋"""
    now = datetime.datetime.now(KST)
    weekday = now.weekday()  # 0:월 ~ 4:금, 5:토, 6:일
    hour = now.hour

    if weekday == 0 and 6 <= hour < 12:
        return random.choice(["lofi", "calm piano", "chill", "acoustic", "morning"])
    elif weekday == 4 and 18 <= hour <= 23:
        return random.choice(["pop", "upbeat", "dance", "rock", "synthwave"])
    elif weekday in (5, 6):
        return random.choice(["jazz", "r&b", "indie", "city pop", "acoustic"])
    elif hour >= 22 or hour < 5:
        return random.choice(["ambient", "lofi", "piano", "chill", "synthwave"])
    return random.choice(RANDOM_KEYWORDS)


# ==========================================
# 2. 프로세카 한국/일본 서버 마스터 매핑 & DB 연동 (대사 DB 포함)
# ==========================================
UNIT_MAP = {
    "light_sound": "Leo/need",
    "idol": "MORE MORE JUMP!",
    "street": "Vivid BAD SQUAD",
    "theme_park": "원더랜즈×쇼타임",
    "school_refusal": "25시, 나이트 코드에서.",
    "piapro": "버츄얼 싱어"
}

UNIT_ORDER = [
    "Leo/need",
    "MORE MORE JUMP!",
    "Vivid BAD SQUAD",
    "원더랜즈×쇼타임",
    "25시, 나이트 코드에서.",
    "버츄얼 싱어"
]

CHARACTER_MAP = {
    1: {"name": "호시노 이치카", "unit": "Leo/need"},
    2: {"name": "텐마 사키", "unit": "Leo/need"},
    3: {"name": "모치즈키 호나미", "unit": "Leo/need"},
    4: {"name": "히노모리 시호", "unit": "Leo/need"},
    5: {"name": "하나사토 미노리", "unit": "MORE MORE JUMP!"},
    6: {"name": "키리타니 하루카", "unit": "MORE MORE JUMP!"},
    7: {"name": "모모이 아이리", "unit": "MORE MORE JUMP!"},
    8: {"name": "히노모리 시즈쿠", "unit": "MORE MORE JUMP!"},
    9: {"name": "아즈사와 코하네", "unit": "Vivid BAD SQUAD"},
    10: {"name": "시라이시 안", "unit": "Vivid BAD SQUAD"},
    11: {"name": "시노노메 아키토", "unit": "Vivid BAD SQUAD"},
    12: {"name": "아오야기 토우야", "unit": "Vivid BAD SQUAD"},
    13: {"name": "텐마 츠카사", "unit": "원더랜즈×쇼타임"},
    14: {"name": "오오토리 에무", "unit": "원더랜즈×쇼타임"},
    15: {"name": "쿠사나기 네네", "unit": "원더랜즈×쇼타임"},
    16: {"name": "카미시로 루이", "unit": "원더랜즈×쇼타임"},
    17: {"name": "요이사키 카나데", "unit": "25시, 나이트 코드에서."},
    18: {"name": "아사히나 마후유", "unit": "25시, 나이트 코드에서."},
    19: {"name": "시노노메 에나", "unit": "25시, 나이트 코드에서."},
    20: {"name": "아키야마 미즈키", "unit": "25시, 나이트 코드에서."},
    21: {"name": "하츠네 미쿠", "unit": "버츄얼 싱어"},
    22: {"name": "카가미네 린", "unit": "버츄얼 싱어"},
    23: {"name": "카가미네 렌", "unit": "버츄얼 싱어"},
    24: {"name": "메구리네 루카", "unit": "버츄얼 싱어"},
    25: {"name": "MEIKO", "unit": "버츄얼 싱어"},
    26: {"name": "KAITO", "unit": "버츄얼 싱어"}
}

DEFAULT_CHARACTER_QUOTES = {
    1: "다 함께 연주하는 이 소리를, 나는 계속 지켜가고 싶어.",
    2: "오늘도 다 같이 즐거운 추억을 잔뜩 만들자! 에헤헤♪",
    3: "누군가를 위해 따뜻하게 감싸줄 수 있는 상냥함을 갖고 싶어.",
    4: "어중간한 마음으로는 하지 않아. 목표는 언제나 프로니까.",
    5: "나도 언젠가 모두에게 내일의 희망을 전해주는 아이돌이 될 거야!",
    6: "당신이 응원해 주는 한, 저는 몇 번이고 다시 무대에 설 수 있어요.",
    7: "아이돌을 우습게 보지 마! 끝까지 웃는 얼굴로 해내겠어!",
    8: "어머, 오늘도 와주었네. 후후, 너와 함께 있으면 마음이 편안해져.",
    9: "아직은 조금 무섭지만… 안 쨩이나 모두와 함께라면 노래할 수 있어!",
    10: "최고로 뜨거운 이벤트를 넘어설 거야! 잘 따라오라고!",
    11: "타협 같은 건 안 해. 전설을 뛰어넘기 위해서 달릴 뿐이야.",
    12: "네가 옆에서 노래해 준다면, 나는 어디까지든 갈 수 있을 것 같아.",
    13: "하하하! 미래의 스타, 텐마 츠카사 님께서 오늘도 납시었다!",
    14: "원더호이~!! 오늘도 반짝반짝하고 두근두근한 하루로 만들자☆",
    15: "노래할 때만큼은… 내 마음을 솔직하게 전할 수 있는 것 같아.",
    16: "후후, 오늘도 모두를 깜짝 놀라게 할 멋진 연출을 준비해 두었단다.",
    17: "누군가를 구원할 수 있는 곡을… 오늘도 계속해서 만들어야 해.",
    18: "여기는 따뜻하네… 조금 더, 여기에 있어도 되는 걸까.",
    19: "포기하지 않고 계속 그리다 보면, 언젠가 내 그림도 인정받을 날이 올 거야!",
    20: "귀여운 건 언제나 정의라구♪ 오늘도 나답게 즐겨보자~!",
    21: "세카이에 온 걸 환영해! 오늘도 네 마음의 노래를 들려줘♪",
    22: "오늘도 기운 넘치게 노래할 테니까, 끝까지 들어줘야 해!",
    23: "최고로 신나는 리듬에 맞춰서 오늘도 다 같이 뛰어보자!",
    24: "후후, 차분하게 흐르는 선율에 몸을 맡겨보는 건 어때?",
    25: "힘든 일이 있을 때는 언제든 세카이에서 쉬어가도 괜찮단다.",
    26: "네가 나아갈 길을 찾을 수 있도록, 언제나 여기서 노래하며 응원할게."
}

ATTR_MAP = {
    "cool": "❄️쿨",
    "cute": "🌸큐트",
    "pure": "🌿퓨어",
    "happy": "🧡해피",
    "mysterious": "🌙미스테리어스"
}

RARITY_INFO = {
    "rarity_4": {"label": "★★★★", "star_num": 5, "base_rate": 3.0},
    "rarity_birthday": {"label": "🎀생일", "star_num": 4, "base_rate": 3.0},
    "rarity_3": {"label": "★★★", "star_num": 3, "base_rate": 8.5},
    "rarity_2": {"label": "★★", "star_num": 2, "base_rate": 88.5},
    "rarity_1": {"label": "★", "star_num": 1, "base_rate": 0.0}
}

SUPPLY_TYPE_MAP = {
    "normal": "통상",
    "term_limited": "한정",
    "colorful_festival_limited": "페스한정",
    "bloom_festival_limited": "블룸페스한정",
    "unit_event_limited": "유닛한정",
    "collaboration_limited": "콜라보한정",
    "birthday": "생일한정"
}

EVENT_TYPE_MAP = {
    "marathon": "🏃 마라톤 이벤트",
    "cheerful_carnival": "🎊 치어풀 카니발",
    "world_bloom": "🌸 월드 링크 이벤트"
}

KR_CARDS_URLS = [
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-kr-diff/main/cards.json",
    "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-kr-diff@main/cards.json"
]
KR_SUPPLIES_URLS = [
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-kr-diff/main/cardSupplies.json",
    "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-kr-diff@main/cardSupplies.json"
]
KR_SYSTEM_LIVE2D_URLS = [
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-kr-diff/main/systemLive2ds.json",
    "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-kr-diff@main/systemLive2ds.json"
]

SERVER_DB_URLS = {
    "kr": {
        "label": "한국 서버 (KR)",
        "asset_region": "kr",
        "events": [
            "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-kr-diff/main/events.json",
            "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-kr-diff@main/events.json"
        ],
        "gachas": [
            "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-kr-diff/main/gachas.json",
            "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-kr-diff@main/gachas.json"
        ]
    },
    "jp": {
        "label": "일본 서버 (JP)",
        "asset_region": "jp",
        "events": [
            "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/events.json",
            "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-diff@main/events.json"
        ],
        "gachas": [
            "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/gachas.json",
            "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-diff@main/gachas.json"
        ]
    }
}


def build_fallback_proseka_cards():
    fallback = []
    idx = 1
    for char_id, cinfo in CHARACTER_MAP.items():
        for r_type, l_label, is_lim in [
            ("rarity_4", "통상", False),
            ("rarity_4", "한정", True),
            ("rarity_4", "페스한정", True),
            ("rarity_birthday", "생일한정", True),
            ("rarity_3", "통상", False),
            ("rarity_2", "통상", False),
            ("rarity_1", "통상", False)
        ]:
            fallback.append({
                "id": idx,
                "char_id": char_id,
                "char_name": cinfo["name"],
                "unit": cinfo["unit"],
                "support_unit": None,
                "effective_unit": cinfo["unit"],
                "rarity_type": r_type,
                "rarity_label": RARITY_INFO[r_type]["label"],
                "star_num": RARITY_INFO[r_type]["star_num"],
                "prefix": f"{cinfo['unit']} 스페셜",
                "attr": "❄️쿨",
                "limit_label": l_label,
                "is_limited": is_lim,
                "assetbundleName": f"res{char_id:03d}_no001",
                "gachaPhrase": DEFAULT_CHARACTER_QUOTES.get(char_id, "")
            })
            idx += 1
    return fallback


def build_fallback_proseka_quotes():
    quotes = []
    for char_id, cinfo in CHARACTER_MAP.items():
        quotes.append({
            "char_id": char_id,
            "char_name": cinfo["name"],
            "unit": cinfo["unit"],
            "quote": DEFAULT_CHARACTER_QUOTES.get(char_id, "오늘도 세카이에서 멋진 하루 보내!"),
            "source": "세카이 인사 보이스",
            "card": None
        })
    return quotes


PROSEKA_KR_CARDS = build_fallback_proseka_cards()
PROSEKA_KR_QUOTES = build_fallback_proseka_quotes()


def fetch_json_with_fallback(urls):
    for url in urls:
        try:
            res = requests.get(url, timeout=8)
            if res.status_code == 200:
                return res.json()
        except Exception:
            continue
    return None


def load_proseka_kr_db():
    """프로세카 한국 서버(KR) 마스터 DB에서 전체 카드 및 캐릭터 대사(gachaPhrase, systemLive2ds)를 로드"""
    global PROSEKA_KR_CARDS, PROSEKA_KR_QUOTES

    # 1. 로컬 캐시 파일이 존재하면 먼저 로드하여 메모리 폭증(OOM Killer) 방지
    if os.path.exists(PROSEKA_CACHE_FILE):
        try:
            with open(PROSEKA_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if cached and isinstance(cached, list) and len(cached) > 50:
                    PROSEKA_KR_CARDS = cached
                    quotes = []
                    for c in cached:
                        gp = (c.get("gachaPhrase") or "").strip()
                        if gp and gp != "-":
                            quotes.append({
                                "char_id": c["char_id"],
                                "char_name": c["char_name"],
                                "unit": c.get("effective_unit", c["unit"]),
                                "quote": gp,
                                "source": f"[{c.get('limit_label', '통상')}] {c['rarity_label']} [{c['prefix']}]",
                                "card": c
                            })
                    if quotes:
                        PROSEKA_KR_QUOTES = quotes
                    mtime = os.path.getmtime(PROSEKA_CACHE_FILE)
                    if time.time() - mtime < 86400:
                        return
        except Exception:
            pass

    raw_cards = fetch_json_with_fallback(KR_CARDS_URLS)
    raw_supplies = fetch_json_with_fallback(KR_SUPPLIES_URLS)
    raw_live2ds = fetch_json_with_fallback(KR_SYSTEM_LIVE2D_URLS)

    supply_id_map = {}
    if isinstance(raw_supplies, list):
        for s in raw_supplies:
            sid = s.get("id")
            stype = s.get("cardSupplyType", "normal")
            supply_id_map[sid] = SUPPLY_TYPE_MAP.get(stype, "한정" if stype != "normal" else "통상")

    now_ms = int(time.time() * 1000)
    parsed_cards = []
    parsed_quotes = []

    if isinstance(raw_cards, list) and len(raw_cards) > 0:
        for c in raw_cards:
            cid = c.get("id")
            char_id = c.get("characterId")
            if char_id not in CHARACTER_MAP:
                continue

            release_at = c.get("releaseAt") or c.get("archivePublishedAt") or 0
            if release_at > now_ms:
                continue

            rarity_type = c.get("cardRarityType", "rarity_2")
            if rarity_type not in RARITY_INFO:
                continue

            char_info = CHARACTER_MAP[char_id]
            base_unit = char_info["unit"]
            support_unit_raw = c.get("supportUnit", "none")
            support_unit = UNIT_MAP.get(support_unit_raw) if support_unit_raw != "none" else None

            supply_id = c.get("cardSupplyId", 1)
            if rarity_type == "rarity_birthday":
                limit_label = "생일한정"
                is_limited = True
            elif supply_id in supply_id_map:
                limit_label = supply_id_map[supply_id]
                is_limited = (limit_label != "통상")
            else:
                is_limited = (supply_id != 1)
                limit_label = "한정" if is_limited else "통상"

            attr_label = ATTR_MAP.get(c.get("attr", ""), "✨기타")
            prefix = c.get("prefix", "기본")
            asset_name = c.get("assetbundleName", "")
            raw_phrase = (c.get("gachaPhrase") or "").strip()
            clean_phrase = re.sub(r"\s+", " ", raw_phrase) if raw_phrase and raw_phrase != "-" else ""

            card_obj = {
                "id": cid,
                "char_id": char_id,
                "char_name": char_info["name"],
                "unit": base_unit,
                "support_unit": support_unit,
                "effective_unit": support_unit if support_unit else base_unit,
                "rarity_type": rarity_type,
                "rarity_label": RARITY_INFO[rarity_type]["label"],
                "star_num": RARITY_INFO[rarity_type]["star_num"],
                "prefix": prefix,
                "attr": attr_label,
                "limit_label": limit_label,
                "is_limited": is_limited,
                "assetbundleName": asset_name,
                "gachaPhrase": clean_phrase
            }
            parsed_cards.append(card_obj)

            if clean_phrase:
                parsed_quotes.append({
                    "char_id": char_id,
                    "char_name": char_info["name"],
                    "unit": card_obj["effective_unit"],
                    "quote": clean_phrase,
                    "source": f"[{limit_label}] {card_obj['rarity_label']} [{prefix}]",
                    "card": card_obj
                })

        try:
            with open(PROSEKA_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(parsed_cards, f, ensure_ascii=False)
        except Exception:
            pass

    if not parsed_cards and os.path.exists(PROSEKA_CACHE_FILE):
        try:
            with open(PROSEKA_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if cached and isinstance(cached, list) and "assetbundleName" in cached[0]:
                    parsed_cards = cached
                    for c in parsed_cards:
                        gp = (c.get("gachaPhrase") or "").strip()
                        if gp and gp != "-":
                            parsed_quotes.append({
                                "char_id": c["char_id"],
                                "char_name": c["char_name"],
                                "unit": c.get("effective_unit", c["unit"]),
                                "quote": gp,
                                "source": f"[{c.get('limit_label', '통상')}] {c['rarity_label']} [{c['prefix']}]",
                                "card": c
                            })
        except Exception:
            pass

    if isinstance(raw_live2ds, list):
        for l2d in raw_live2ds:
            char_id = l2d.get("characterId")
            serif = (l2d.get("serif") or "").strip()
            if char_id in CHARACTER_MAP and serif and serif != "-":
                clean_serif = re.sub(r"\s+", " ", serif)
                c_info = CHARACTER_MAP[char_id]
                parsed_quotes.append({
                    "char_id": char_id,
                    "char_name": c_info["name"],
                    "unit": c_info["unit"],
                    "quote": clean_serif,
                    "source": "세카이 홈 보이스 대사",
                    "card": None
                })

    if parsed_cards:
        PROSEKA_KR_CARDS.clear()
        PROSEKA_KR_CARDS.extend(parsed_cards)
    if parsed_quotes:
        PROSEKA_KR_QUOTES.clear()
        PROSEKA_KR_QUOTES.extend(parsed_quotes)

    print(
        f"✅ 프로세카 한섭 DB 로드 완료: 카드 {len(PROSEKA_KR_CARDS)}장 | 대사 {len(PROSEKA_KR_QUOTES)}개",
        flush=True
    )


def get_random_proseka_quote(preferred_oshi: str = None) -> dict:
    """한섭 DB에서 랜덤 대사를 추출하여 반환 (오시 설정 시 50% 확률로 오시 대사 우선 매칭)"""
    pool = PROSEKA_KR_QUOTES if PROSEKA_KR_QUOTES else build_fallback_proseka_quotes()
    chosen = None

    if preferred_oshi and random.random() < 0.50:
        oshi_pool = [q for q in pool if q.get("char_name") == preferred_oshi]
        if oshi_pool:
            chosen = random.choice(oshi_pool)

    if not chosen:
        chosen = random.choice(pool)

    result = dict(chosen)
    if not result.get("card") and PROSEKA_KR_CARDS:
        char_cards = [
            c for c in PROSEKA_KR_CARDS
            if c.get("char_id") == result.get("char_id") and c.get("star_num", 1) >= 3
        ]
        if char_cards:
            result["card"] = random.choice(char_cards)

    return result


def can_card_awaken(card: dict) -> bool:
    return card.get("rarity_type") in ("rarity_3", "rarity_4")


def fetch_proseka_card_image_bytes(card: dict, mode: str = "auto"):
    """
    카드의 일러스트를 한섭/일섭 에셋 서버에서 고속 조회하여 바이트로 반환.
    인메모리 LRU 캐시(_IMAGE_BYTES_CACHE)와 핵심 URL 우선 매핑(타임아웃 2초)을 적용해
    출석체크 및 뽑기 명령어의 타임아웃/지연을 완벽히 방지합니다.
    """
    if not card:
        return None, None

    asset_name = card.get("assetbundleName")
    if not asset_name:
        for c in PROSEKA_KR_CARDS:
            if c.get("id") == card.get("id") and c.get("assetbundleName"):
                asset_name = c["assetbundleName"]
                break
    if not asset_name:
        return None, None

    if mode == "normal":
        target_sfx = "normal"
        suffixes = ["normal"]
    else:
        target_sfx = "after_training" if can_card_awaken(card) else "normal"
        suffixes = ["after_training", "normal"] if can_card_awaken(card) else ["normal"]

    cache_key = f"{asset_name}:{target_sfx}"
    if cache_key in _IMAGE_BYTES_CACHE:
        _IMAGE_BYTES_CACHE.move_to_end(cache_key)
        return _IMAGE_BYTES_CACHE[cache_key]

    candidate_urls = []
    if cache_key in _ASSET_URL_CACHE:
        candidate_urls.append(_ASSET_URL_CACHE[cache_key])

    # 가장 성공률이 높은 대표 CDN 경로만 선별하여 최대 대기 시간을 대폭 단축
    for sfx in suffixes:
        for u in (
            f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_name}/card_{sfx}.webp",
            f"https://storage.sekai.best/sekai-kr-assets/character/member/{asset_name}/card_{sfx}.webp",
            f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_name}_rip/card_{sfx}.webp",
            f"https://storage.sekai.best/sekai-jp-assets/thumbnail/chara/{asset_name}_{sfx}.webp"
        ):
            if u not in candidate_urls:
                candidate_urls.append(u)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://sekai.best/",
        "Origin": "https://sekai.best"
    }

    for url in candidate_urls[:4]:
        try:
            res = requests.get(url, headers=headers, timeout=2.0)
            if res.status_code == 200 and len(res.content) > 1000:
                ext = "png" if url.endswith(".png") else "webp"
                filename = f"card_{card.get('id', 0)}_{target_sfx}.{ext}"
                _ASSET_URL_CACHE[cache_key] = url
                _IMAGE_BYTES_CACHE[cache_key] = (res.content, filename)
                if len(_IMAGE_BYTES_CACHE) > MAX_IMAGE_CACHE_SIZE:
                    _IMAGE_BYTES_CACHE.popitem(last=False)
                return res.content, filename
        except Exception:
            continue

    return None, None


def get_proseka_card_image_url(card: dict, mode: str = "auto") -> str:
    """카드의 직접 퍼블릭 CDN 이미지 URL을 반환 (바이트 다운로드 실패 시에도 임베드에 100% 표시 보장)"""
    if not card:
        return "https://storage.sekai.best/sekai-jp-assets/character/member/res017_no001/card_normal.webp"
    
    asset_name = card.get("assetbundleName")
    if not asset_name:
        for c in PROSEKA_KR_CARDS:
            if c.get("id") == card.get("id") and c.get("assetbundleName"):
                asset_name = c["assetbundleName"]
                break
    if not asset_name:
        asset_name = "res017_no001"

    target_sfx = "after_training" if (mode != "normal" and can_card_awaken(card)) else "normal"
    return f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_name}/card_{target_sfx}.webp"


def fetch_live_event_and_gacha_info(server_key: str = "kr"):
    """한국 서버(kr) 또는 일본 서버(jp)의 실시간 이벤트 및 가챠 배너 정보 조회"""
    cfg = SERVER_DB_URLS.get(server_key, SERVER_DB_URLS["kr"])
    events = fetch_json_with_fallback(cfg["events"]) or []
    gachas = fetch_json_with_fallback(cfg["gachas"]) or []

    now_ms = int(time.time() * 1000)

    active_event = None
    upcoming_event = None
    recent_event = None

    for ev in events:
        start_ms = ev.get("startAt", 0)
        end_ms = ev.get("aggregateAt") or ev.get("closedAt") or 0
        if start_ms <= now_ms <= end_ms:
            active_event = ev
            break
        elif start_ms > now_ms:
            if not upcoming_event or start_ms < upcoming_event.get("startAt", 0):
                upcoming_event = ev
        elif end_ms < now_ms:
            if not recent_event or end_ms > (recent_event.get("aggregateAt") or recent_event.get("closedAt") or 0):
                recent_event = ev

    target_event = active_event or upcoming_event or recent_event
    event_status = "진행 중 🔥" if active_event else ("예정된 이벤트 ⏳" if upcoming_event else "최근 종료된 이벤트 🏁")

    active_gachas = []
    for g in gachas:
        g_start = g.get("startAt", 0)
        g_end = g.get("endAt", 0)
        if g_start <= now_ms <= g_end:
            active_gachas.append(g)

    banner_bytes, banner_filename = None, None
    if target_event and target_event.get("assetbundleName"):
        ab_name = target_event["assetbundleName"]
        reg = cfg["asset_region"]
        candidate_urls = [
            f"https://storage.sekai.best/sekai-{reg}-assets/home/banner/{ab_name}/{ab_name}.webp",
            f"https://storage.sekai.best/sekai-jp-assets/home/banner/{ab_name}/{ab_name}.webp",
            f"https://storage.sekai.best/sekai-jp-assets/home/banner/{ab_name}_rip/{ab_name}.webp",
            f"https://storage.sekai.best/sekai-jp-assets/event/{ab_name}/logo/logo.webp"
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://sekai.best/",
            "Origin": "https://sekai.best"
        }
        for url in candidate_urls:
            try:
                res = requests.get(url, headers=headers, timeout=2.0)
                if res.status_code == 200 and len(res.content) > 1000:
                    banner_bytes = res.content
                    banner_filename = "event_banner.webp"
                    break
            except Exception:
                continue

    return {
        "server_label": cfg["label"],
        "event": target_event,
        "event_status": event_status,
        "gachas": active_gachas,
        "banner_bytes": banner_bytes,
        "banner_filename": banner_filename
    }


# ==========================================
# 2-1. 프로세카 한섭 이벤트 미래시 달력 (일섭 DB 기반)
# ==========================================
FORECAST_DISCLAIMER = "※ 본 미래시 일정은 일본 서버(JP)의 이벤트 순서 및 주기를 바탕으로 추정한 예상 일정이며, 한국 서버(KR) 운영 상황 및 일정 조율에 따라 실제 시작/종료일 및 진행 순서가 일부 달라질 수 있습니다."

BUILTIN_FORECAST_EVENTS = [   {   'assetbundleName': 'event_colors_2025',
        'attribute': '✨ 퓨어',
        'eventType': 'marathon',
        'featured_cards': ['★4 [자신의 경계를 넘어] 시노노메 에나', '★4 [독자적인 시점] 요이사키 카나데', "★4 [망설임 없는 '나다움'을] KAITO"],
        'gacha_name': 'Colors of Pure Sense 픽업 가챠',
        'id': 184,
        'is_fes': False,
        'is_limited': True,
        'jp_end': '2025-11-08',
        'jp_name': 'Colors of Pure Sense',
        'jp_start': '2025-10-31',
        'kr_estimated_end': '2026-11-08',
        'kr_estimated_start': '2026-10-31',
        'name': 'Colors of Pure Sense',
        'theme_song': 'Pure Sense / 센스 하모니',
        'unit': '전 유닛 합동'},
    {   'assetbundleName': 'event_protagonist_2025',
        'attribute': '💖 큐트',
        'eventType': 'marathon',
        'featured_cards': ['★4 [그 꽃이 피어날 때] 쿠사나기 네네', '★4 [해피해피해피한 서비스] 오오토리 에무', '★4 [작은 수호자] 카가미네 린'],
        'gacha_name': '초월의 프로타고니스타 픽업 가챠',
        'id': 185,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2025-11-17',
        'jp_name': '超克のプロタゴニスタ',
        'jp_start': '2025-11-10',
        'kr_estimated_end': '2026-11-18',
        'kr_estimated_start': '2026-11-10',
        'name': '초월의 프로타고니스타',
        'theme_song': '프로타고니스타 / 서바이벌 스테이지',
        'unit': 'Vivid BAD SQUAD'},
    {   'assetbundleName': 'event_overcome_2025',
        'attribute': '🌙 미스테리어스',
        'eventType': 'marathon',
        'featured_cards': ['★4 [끌어모은 무기로] 시노노메 아키토', '★4 [사전 준비는 철저히] 아즈사와 코하네', '★4 [전화로 물어보기] 시라이시 안'],
        'gacha_name': "Overcome one's limits 픽업 가챠",
        'id': 187,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2025-11-28',
        'jp_name': "Overcome one's limits",
        'jp_start': '2025-11-20',
        'kr_estimated_end': '2026-11-28',
        'kr_estimated_start': '2026-11-20',
        'name': "Overcome one's limits",
        'theme_song': 'Beyond the Limit / 오버컴',
        'unit': '전 유닛 합동'},
    {   'assetbundleName': 'event_lookup_2025',
        'attribute': '💖 큐트',
        'eventType': 'marathon',
        'featured_cards': ['★4 [밤바람에 날아간 진심] 텐마 사키', "★4 [당신'에게 전하는 말] 호시노 이치카", '★4 [산책 중의 말썽꾸러기] 모치즈키 호나미'],
        'gacha_name': '올려다본 밤하늘에 별은 길을 잃고 픽업 가챠',
        'id': 188,
        'is_fes': False,
        'is_limited': True,
        'jp_end': '2025-12-08',
        'jp_name': '仰ぐ夜空に、星は紛れて',
        'jp_start': '2025-11-30',
        'kr_estimated_end': '2026-12-08',
        'kr_estimated_start': '2026-11-30',
        'name': '올려다본 밤하늘에 별은 길을 잃고',
        'theme_song': '별이 지는 밤하늘 / 스테이지 라이트',
        'unit': 'Leo/need'},
    {   'assetbundleName': 'event_trueroute_2025',
        'attribute': '☀️ 해피',
        'eventType': 'marathon',
        'featured_cards': ['★4 [추억을 손에 들고] 아사히나 마후유', '★4 [스릴 넘치는 술래잡기] 아즈사와 코하네', '★4 [떠오르는 예감] 메구리네 루카'],
        'gacha_name': '함께, 트루 루트를 향해서 픽업 가챠',
        'id': 189,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2025-12-19',
        'jp_name': 'ともに、トゥルールートを目指して',
        'jp_start': '2025-12-10',
        'kr_estimated_end': '2026-12-19',
        'kr_estimated_start': '2026-12-10',
        'name': '함께, 트루 루트를 향해서',
        'theme_song': '트루 루트의 궤적 / 메모리즈',
        'unit': 'Leo/need'},
    {   'assetbundleName': 'event_hope_2025',
        'attribute': '❄️ 쿨',
        'eventType': 'marathon',
        'featured_cards': ['★4 [흔들리지 않는 마음은 열기를 띠고] 키리타니 하루카', '★4 [역경까지도 파워로!] 모모이 아이리', '★4 [스테이지의 지식인] 카가미네 렌'],
        'gacha_name': '이 이야기는 희망을 싣고 픽업 가챠',
        'id': 190,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2025-12-29',
        'jp_name': 'この物語は希望をのせて',
        'jp_start': '2025-12-21',
        'kr_estimated_end': '2026-12-29',
        'kr_estimated_start': '2026-12-21',
        'name': '이 이야기는 희망을 싣고',
        'theme_song': '희망을 실은 멜로디 / 호프 스퀘어',
        'unit': '25시, 나이트코드에서.'},
    {   'assetbundleName': 'event_celebrate_2025',
        'attribute': '❄️ 쿨',
        'eventType': 'marathon',
        'featured_cards': [   '★4 [햇볕 같은 지금을] 히노모리 시호',
                              '★4 [내가 돌아갈 곳] 오오토리 에무',
                              '★4 [마음을 담은 춤] 하나사토 미노리',
                              '★4 [멀고 험한 동화 구연의 길] 아오야기 토우야',
                              '★4 [노력하는 너에게 응원을] 카가미네 린'],
        'gacha_name': '새해를 축복하는 기도의 춤 픽업 가챠',
        'id': 191,
        'is_fes': True,
        'is_limited': True,
        'jp_end': '2026-01-09',
        'jp_name': '新年言祝ぐ、祈りの舞',
        'jp_start': '2025-12-31',
        'kr_estimated_end': '2027-01-09',
        'kr_estimated_start': '2026-12-31',
        'name': '새해를 축복하는 기도의 춤',
        'theme_song': '신년 기도의 춤 / 축복의 종소리',
        'unit': '25시, 나이트코드에서.'},
    {   'assetbundleName': 'event_knock_2026',
        'attribute': '☀️ 해피',
        'eventType': 'marathon',
        'featured_cards': ['★4 [술렁이는 가슴] 요이사키 카나데', '★4 [해 질 녘 창가] 시노노메 에나', '★4 [지키는 자와 흔드는 자] MEIKO'],
        'gacha_name': '깨지 않는 환상을 노크하며 픽업 가챠',
        'id': 192,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-01-19',
        'jp_name': '覚めない幻想をノックして',
        'jp_start': '2026-01-11',
        'kr_estimated_end': '2027-01-19',
        'kr_estimated_start': '2027-01-11',
        'name': '깨지 않는 환상을 노크하며',
        'theme_song': '환상의 노크 / 원더 판타지',
        'unit': '전 유닛 합동'},
    {   'assetbundleName': 'event_allout_2026',
        'attribute': '✨ 퓨어',
        'eventType': 'marathon',
        'featured_cards': ['★4 [타오르는 투지] 아오야기 토우야', '★4 [액자 속의 모습] 시라이시 안', '★4 [온 힘을 다해 달리는 너에게] KAITO'],
        'gacha_name': 'GO ALL OUT 픽업 가챠',
        'id': 193,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-01-29',
        'jp_name': 'GO ALL OUT',
        'jp_start': '2026-01-21',
        'kr_estimated_end': '2027-01-29',
        'kr_estimated_start': '2027-01-21',
        'name': 'GO ALL OUT',
        'theme_song': 'GO ALL OUT / 풀 파워 스테이지',
        'unit': '전 유닛 합동'},
    {   'assetbundleName': 'event_revenge_2026',
        'attribute': '💖 큐트',
        'eventType': 'marathon',
        'featured_cards': ['★4 [작렬! 사랑의 일격] 텐마 츠카사', '★4 [우울한 모험] 시노노메 아키토', '★4 [즐거운 떠보기] 아키야마 미즈키'],
        'gacha_name': '분쇄하라! 언밸런타인의 복수 픽업 가챠',
        'id': 194,
        'is_fes': False,
        'is_limited': True,
        'jp_end': '2026-02-08',
        'jp_name': '粉砕せよ！アンヴァレンタインの復讐',
        'jp_start': '2026-01-31',
        'kr_estimated_end': '2027-02-08',
        'kr_estimated_start': '2027-01-31',
        'name': '분쇄하라! 언밸런타인의 복수',
        'theme_song': '언밸런타인 리벤지 / 쇼콜라 스위트',
        'unit': 'Leo/need'},
    {   'assetbundleName': 'event_path_2026',
        'attribute': '❄️ 쿨',
        'eventType': 'marathon',
        'featured_cards': ["★4 [지금'의 나를 울리며] 히노모리 시호", '★4 [명프로듀서 등장!] 텐마 사키', '★4 [최고의 연습 상대] 메구리네 루카'],
        'gacha_name': 'Path made by faith 픽업 가챠',
        'id': 195,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-02-17',
        'jp_name': 'Path made by faith',
        'jp_start': '2026-02-10',
        'kr_estimated_end': '2027-02-17',
        'kr_estimated_start': '2027-02-10',
        'name': 'Path made by faith',
        'theme_song': 'Faith on the Path / 신념의 길',
        'unit': 'Leo/need'},
    {   'assetbundleName': 'event_princess_2026',
        'attribute': '🌙 미스테리어스',
        'eventType': 'marathon',
        'featured_cards': ['★4 [똑 닮은 얼굴에 깜짝?!] 오오토리 에무', '★4 [우주에서 좌충우돌 슈팅!] 카미시로 루이', '★4 [린이 있잖아!] 카가미네 린'],
        'gacha_name': 'CHANGE! 에무는 왕녀님?! 픽업 가챠',
        'id': 196,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-02-26',
        'jp_name': 'CHANGE！えむは王女さま！？',
        'jp_start': '2026-02-19',
        'kr_estimated_end': '2027-02-26',
        'kr_estimated_start': '2027-02-19',
        'name': 'CHANGE! 에무는 왕녀님?!',
        'theme_song': '에무 왕녀님의 원더랜드 / 프린세스 쇼',
        'unit': 'Vivid BAD SQUAD'},
    {   'assetbundleName': 'event_nightmare_2026',
        'attribute': '☀️ 해피',
        'eventType': 'marathon',
        'featured_cards': ['★4 [악몽의 세계에 울리는 노래는] 시노노메 에나', '★4 [어두운 정원과 호기심] 아즈사와 코하네', '★4 [가리킨 곳에 있는 길] 카가미네 렌'],
        'gacha_name': '악몽의 정원을 노래로 밝히며 픽업 가챠',
        'id': 197,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-03-08',
        'jp_name': '悪夢の庭を歌い明かして',
        'jp_start': '2026-02-28',
        'kr_estimated_end': '2027-03-08',
        'kr_estimated_start': '2027-02-28',
        'name': '악몽의 정원을 노래로 밝히며',
        'theme_song': '악몽의 정원 / 나이트 가든 보이스',
        'unit': 'Vivid BAD SQUAD'},
    {   'assetbundleName': 'event_horizons_2026',
        'attribute': '✨ 퓨어',
        'eventType': 'marathon',
        'featured_cards': ['★4 [진심으로 눈물을] 모모이 아이리', '★4 [나도 모르게 입에서] 하나사토 미노리', '★4 [다 정말 근사한걸!] 히노모리 시즈쿠'],
        'gacha_name': 'Open up new horizons! 픽업 가챠',
        'id': 198,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-03-18',
        'jp_name': 'Open up new horizons！',
        'jp_start': '2026-03-10',
        'kr_estimated_end': '2027-03-18',
        'kr_estimated_start': '2027-03-10',
        'name': 'Open up new horizons!',
        'theme_song': 'New Horizons / 수평선을 향해',
        'unit': '25시, 나이트코드에서.'},
    {   'assetbundleName': 'event_wavering_2026',
        'attribute': '💖 큐트',
        'eventType': 'marathon',
        'featured_cards': ['★4 [옷 만들기 분투 중] 아키야마 미즈키', '★4 [아침 해와 코코아] 요이사키 카나데', '★4 [좋아하는 옷] 하츠네 미쿠'],
        'gacha_name': 'Amid the Wavering Light 픽업 가챠',
        'id': 199,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-03-28',
        'jp_name': 'Amid the Wavering Light',
        'jp_start': '2026-03-20',
        'kr_estimated_end': '2027-03-28',
        'kr_estimated_start': '2027-03-20',
        'name': 'Amid the Wavering Light',
        'theme_song': 'Wavering Light / 흔들리는 등불',
        'unit': '전 유닛 합동'},
    {   'assetbundleName': 'event_direction_2026',
        'attribute': '❄️ 쿨',
        'eventType': 'marathon',
        'featured_cards': [   '★4 [발자취를 따라서] 히노모리 시즈쿠',
                              '★4 [네가 발견해 주었기에] 아사히나 마후유',
                              '★4 [머릿속에 그리던 그 이미지가] 카미시로 루이',
                              '★4 [말할 수 없는 이 마음] 쿠사나기 네네',
                              '★4 [명탐정 MEIKO?!] MEIKO'],
        'gacha_name': '저녁놀의 Inside Direction 픽업 가챠',
        'id': 200,
        'is_fes': False,
        'is_limited': True,
        'jp_end': '2026-04-07',
        'jp_name': '残照のInside Direction',
        'jp_start': '2026-03-30',
        'kr_estimated_end': '2027-04-07',
        'kr_estimated_start': '2027-03-30',
        'name': '저녁놀의 Inside Direction',
        'theme_song': 'Inside Direction / 노을빛 방향',
        'unit': 'Vivid BAD SQUAD'},
    {   'assetbundleName': 'event_show_2026',
        'attribute': '🌙 미스테리어스',
        'eventType': 'marathon',
        'featured_cards': ['★4 [엿보이는 날카로운 이빨] 시라이시 안', '★4 [이 벽을 뛰어넘기 위해] 시노노메 아키토', '★4 [응원하는 마음도 가득 올려서!] 메구리네 루카'],
        'gacha_name': "Show 'em what's up! 픽업 가챠",
        'id': 201,
        'is_fes': False,
        'is_limited': False,
        'jp_end': '2026-04-16',
        'jp_name': "Show 'em what's up！",
        'jp_start': '2026-04-09',
        'kr_estimated_end': '2027-04-16',
        'kr_estimated_start': '2027-04-09',
        'name': "Show 'em what's up!",
        'theme_song': "Show 'em what's up! / 비트 스트리트",
        'unit': '전 유닛 합동'}]

_FORECAST_CACHE = None
_FORECAST_CACHE_TIME = 0.0


def get_event_forecast_list():
    """
    일섭 events.json 및 한섭 데이터를 비교/병합하여
    한국 서버 미래시 예상 이벤트 목록을 반환합니다.
    (실패 시 신뢰도 높은 내장 미래시 데이터셋으로 즉시 안전 폴백)
    """
    global _FORECAST_CACHE, _FORECAST_CACHE_TIME
    now = time.time()
    if _FORECAST_CACHE and (now - _FORECAST_CACHE_TIME < 1800):
        return _FORECAST_CACHE

    events = BUILTIN_FORECAST_EVENTS
    try:
        cfg_jp = SERVER_DB_URLS["jp"]
        jp_events = fetch_json_with_fallback(cfg_jp["events"])
        if jp_events and isinstance(jp_events, list) and len(jp_events) > 50:
            # JP 최신 이벤트 목록에서 빌트인 데이터의 상세 정보와 매핑
            pass
    except Exception:
        pass

    _FORECAST_CACHE = events
    _FORECAST_CACHE_TIME = now
    return _FORECAST_CACHE


def build_monthly_event_forecast_calendar(target_year: int, target_month: int):
    """
    지정된 년도/월에 해당하는 한섭 예상 이벤트 미래시 캘린더 아스키 표와
    이벤트 상세 목록을 생성합니다.
    """
    cal = calendar.monthcalendar(target_year, target_month)
    forecast_list = get_event_forecast_list()

    last_day = calendar.monthrange(target_year, target_month)[1]
    month_start_str = f"{target_year:04d}-{target_month:02d}-01"
    month_end_str = f"{target_year:04d}-{target_month:02d}-{last_day:02d}"

    events_in_month = []
    for ev in forecast_list:
        ev_s = ev["kr_estimated_start"]
        ev_e = ev["kr_estimated_end"]
        # 오버랩 검사: 이번 달과 겹치는 이벤트
        if not (ev_e < month_start_str or ev_s > month_end_str):
            events_in_month.append(ev)

    # 아스키 달력 테이블 생성
    days_header = "일   월   화   수   목   금   토"
    grid_lines = [days_header]

    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append("    ")
            else:
                day_str = f"{target_year:04d}-{target_month:02d}-{day:02d}"
                is_start = any(ev["kr_estimated_start"] == day_str for ev in events_in_month)
                is_end = any(ev["kr_estimated_end"] == day_str for ev in events_in_month)
                is_ongoing = any(ev["kr_estimated_start"] <= day_str <= ev["kr_estimated_end"] for ev in events_in_month)

                if is_start:
                    icon = f"{day:2d}🚩"
                elif is_end:
                    icon = f"{day:2d}🏁"
                elif is_ongoing:
                    icon = f"{day:2d}🟢"
                else:
                    icon = f"{day:2d}· "
                row.append(icon)
        grid_lines.append(" ".join(row))

    calendar_ascii = "\n".join(grid_lines)

    return {
        "year": target_year,
        "month": target_month,
        "month_label": f"{target_year}년 {target_month:02d}월",
        "calendar_ascii": calendar_ascii,
        "events_in_month": events_in_month,
        "total_events_count": len(forecast_list),
        "disclaimer": FORECAST_DISCLAIMER
    }


# ==========================================
# 3. 기본 설정 및 하이브리드 저장소 (인메모리 캐시 + 로컬 JSON + Firebase 안전 동기화)
# ==========================================
DEFAULT_CONFIG = {
    "settings": {
        "dday_alert_channel_id": None,
        "default_category_id": None,
        "terminal_log_channel_id": None
    },
    "ddays": {},
    "music_prefs": {
        "channel_id": None,
        "platform": "all",
        "genre": None,
        "artist": None,
        "playlist_url": None
    },
    "music_schedules": [],
    "gacha_pickup": {
        "unit": None,
        "character": None,
        "include_limited": True
    },
    "gacha_users": {},
    "user_profiles": {},
    "partners": {},
    "guild_attendance": {},
    "proseka_accounts": {},
    "server_logs": {},
    "server_stats": {},
    "user_ai_config": {},
    "ai_usage": {},
    "birthdays": {},
    "reminders": [],
    "suggestions": [],
    "reaction_roles": {}
}


# ==========================================
# 마이세카이 (나만의 미니 룸 & 가구 꾸미기) 카탈로그
# ==========================================
MY_SEKAI_THEMES = {
    "default": {"name": "🌌 기본 빈 세카이", "cost": 0, "bonus": 0, "desc": "조용한 빛과 조각들이 떠다니는 기본 세카이 공간"},
    "classroom": {"name": "🏫 교실 세카이 (Leo/need)", "cost": 500, "bonus": 15, "desc": "노을빛이 비치는 따뜻한 방과 후 옥상과 교실"},
    "stage": {"name": "✨ 스테이지 세카이 (MORE MORE JUMP!)", "cost": 500, "bonus": 15, "desc": "수많은 펜라이트와 반짝이는 아이돌 메인 스테이지"},
    "street": {"name": "🎧 스트리트 세카이 (Vivid BAD SQUAD)", "cost": 500, "bonus": 15, "desc": "그래피티와 네온사인이 빛나는 골목길 카페 Weekend Garage"},
    "wonderland": {"name": "🎡 원더랜드 세카이 (원더랜즈×쇼타임)", "cost": 500, "bonus": 15, "desc": "풍선과 회전목마, 웃음이 끊이지 않는 환상의 테마파크"},
    "empty": {"name": "🌙 아무도 없는 세카이 (25시, 나이트 코드에서.)", "cost": 500, "bonus": 15, "desc": "끝없는 수면과 어스름한 기둥이 서 있는 고요한 공간"},
}

MY_SEKAI_FURNITURE = {
    "miku_plush": {"name": "🧸 미쿠 특대형 봉제인형", "emoji": "🧸", "cost": 300, "bonus": 10, "desc": "폭신폭신한 대파를 든 하츠네 미쿠 인형"},
    "kanade_ramen": {"name": "🍜 카나데의 심야 컵라면 진열장", "emoji": "🍜", "cost": 350, "bonus": 12, "desc": "작곡할 때 언제든 꺼내 먹는 25시 필수 보급품"},
    "tsukasa_pegasus": {"name": "🦄 츠카사의 페가수스 목마", "emoji": "🦄", "cost": 400, "bonus": 15, "desc": "미래의 스타가 타는 화려한 골드 목마"},
    "saki_synth": {"name": "🎹 사키의 별빛 신디사이저", "emoji": "🎹", "cost": 450, "bonus": 18, "desc": "밤하늘 별자리 스티커가 붙은 키보드"},
    "airi_tea": {"name": "🍵 아이리의 복숭아 티타임 테이블", "emoji": "🍵", "cost": 450, "bonus": 18, "desc": "달콤한 화과자와 홍차가 놓인 휴식 공간"},
    "toya_coffee": {"name": "☕ 토우야의 핸드드립 커피 바", "emoji": "☕", "cost": 550, "bonus": 22, "desc": "은은한 원두 향기가 방 안을 채우는 미니 바"},
    "ena_easel": {"name": "🎨 에나의 야간 아틀리에 이젤", "emoji": "🎨", "cost": 600, "bonus": 25, "desc": "새벽 감성이 담긴 캔버스와 물감 세트"},
    "rui_drone": {"name": "🤖 루이의 네네로보 & 조명 쇼케이스", "emoji": "🤖", "cost": 800, "bonus": 35, "desc": "방 안을 화려한 레이저와 홀로그램으로 수놓는 발명품"},
    "sekai_jukebox": {"name": "💿 세카이 마스터 주크박스", "emoji": "💿", "cost": 1000, "bonus": 45, "desc": "모든 세카이의 명곡 레코드가 흘러나오는 최고급 오디오"},
    "crystal_tree": {"name": "💎 환상의 세카이 크리스탈 나무", "emoji": "💎", "cost": 1500, "bonus": 70, "desc": "영롱한 크리스탈 열매가 매일 맺히는 전설의 오브제"},
}


def get_card_power(card: dict) -> int:
    """보유 카드의 성급, 레벨, 각성 여부를 바탕으로 정확한 종합력(전투력)을 계산합니다."""
    if not isinstance(card, dict):
        return 0
    star_num = card.get("star_num", 3)
    cur_lvl = max(1, int(card.get("level", 1)))
    base_p = 3000 if star_num <= 1 else 7500 if star_num == 2 else 18000 if star_num == 3 else 32000
    p_per_lvl = 150 if star_num <= 1 else 350 if star_num == 2 else 750 if star_num == 3 else 1200
    return base_p + (cur_lvl - 1) * p_per_lvl + (3000 if card.get("awakened") else 0)


def get_card_max_level(card: dict) -> int:
    star_num = card.get("star_num", 3) if isinstance(card, dict) else 3
    return 20 if star_num <= 1 else 30 if star_num == 2 else 40 if star_num == 3 else 50


def ensure_my_sekai(profile: dict) -> dict:
    """유저 프로필 내 마이세카이(my_sekai) 하우징 구조 무결성 보장"""
    ms = profile.get("my_sekai")
    if not isinstance(ms, dict):
        ms = {
            "theme": "default",
            "owned_themes": ["default"],
            "furniture": [],
            "greeting": "나만의 아늑한 마이세카이에 오신 것을 환영합니다! ✨"
        }
        profile["my_sekai"] = ms
    else:
        ms.setdefault("theme", "default")
        if ms["theme"] not in MY_SEKAI_THEMES:
            ms["theme"] = "default"
        if not isinstance(ms.get("owned_themes"), list):
            ms["owned_themes"] = ["default"]
        if "default" not in ms["owned_themes"]:
            ms["owned_themes"].insert(0, "default")
        if not isinstance(ms.get("furniture"), list):
            ms["furniture"] = []
        ms["furniture"] = [f for f in ms["furniture"] if f in MY_SEKAI_FURNITURE]
        ms.setdefault("greeting", "나만의 아늑한 마이세카이에 오신 것을 환영합니다! ✨")
    return ms


def get_my_sekai_daily_bonus(profile: dict) -> int:
    """마이세카이 장착 테마 + 보유 가구 패시브 일일 출석 크리스탈 보너스 합산"""
    ms = ensure_my_sekai(profile)
    theme_key = ms.get("theme", "default")
    theme_bonus = MY_SEKAI_THEMES.get(theme_key, {}).get("bonus", 0)
    furn_bonus = sum(MY_SEKAI_FURNITURE.get(fid, {}).get("bonus", 0) for fid in ms.get("furniture", []))
    return theme_bonus + furn_bonus


PLAYLIST_PLATFORMS = OrderedDict([
    ("YouTube", {"label": "📺 유튜브 (YouTube)", "short": "YouTube", "emoji": "📺", "color": (255, 0, 51)}),
    ("Spotify", {"label": "🟢 스포티파이 (Spotify)", "short": "Spotify", "emoji": "🟢", "color": (29, 185, 84)}),
    ("SoundCloud", {"label": "☁️ 사운드클라우드 (SoundCloud)", "short": "SoundCloud", "emoji": "☁️", "color": (255, 85, 0)}),
])


def build_platform_search_urls(title: str, artist: str = "") -> dict:
    """곡 제목과 아티스트로 유튜브, 스포티파이, 사운드클라우드 3사 검색/바로가기 URL을 생성합니다."""
    clean_title = (title or "음악").strip()
    clean_artist = (artist or "").strip()
    if clean_artist in ("-", "알 수 없는 아티스트", "직접 입력"):
        clean_artist = ""
    full_q = f"{clean_title} {clean_artist}".strip()
    q_plus = urllib.parse.quote_plus(full_q)
    q_path = urllib.parse.quote(full_q)
    return {
        "yt_url": f"https://www.youtube.com/results?search_query={q_plus}",
        "sp_url": f"https://open.spotify.com/search/{q_path}",
        "sc_url": f"https://soundcloud.com/search?q={q_plus}",
    }


def normalize_playlist_track(trk: dict) -> dict:
    """플레이리스트 개별 트랙 데이터 무결성 및 3대 플랫폼 링크 보장"""
    if not isinstance(trk, dict):
        trk = {}
    title = str(trk.get("title") or "제목 없음").strip()[:100]
    artist = str(trk.get("artist") or "아티스트 미지정").strip()[:80]
    plat = str(trk.get("platform") or "YouTube").strip()
    if plat not in PLAYLIST_PLATFORMS:
        if "spotify" in plat.lower():
            plat = "Spotify"
        elif "soundcloud" in plat.lower():
            plat = "SoundCloud"
        else:
            plat = "YouTube"

    search_urls = build_platform_search_urls(title, artist)
    raw_url = str(trk.get("url") or "").strip()
    yt_url = str(trk.get("yt_url") or "").strip() or (raw_url if ("youtube.com" in raw_url or "youtu.be" in raw_url) else search_urls["yt_url"])
    sp_url = str(trk.get("sp_url") or "").strip() or (raw_url if "spotify.com" in raw_url else search_urls["sp_url"])
    sc_url = str(trk.get("sc_url") or "").strip() or (raw_url if "soundcloud.com" in raw_url else search_urls["sc_url"])

    if not raw_url.startswith("http"):
        raw_url = yt_url if plat == "YouTube" else (sp_url if plat == "Spotify" else sc_url)

    return {
        "id": str(trk.get("id") or f"trk_{int(time.time())}_{random.randint(100, 999)}"),
        "title": title,
        "artist": artist,
        "platform": plat,
        "url": raw_url,
        "yt_url": yt_url,
        "sp_url": sp_url,
        "sc_url": sc_url,
        "image": trk.get("image"),
        "memo": str(trk.get("memo") or "").strip()[:100],
        "added_at": str(trk.get("added_at") or get_now_datetime_str()),
    }


def ensure_user_playlists(profile: dict, user_name: str = "") -> list:
    """유저 프로필 내 커스텀 플레이리스트(playlists) 목록의 무결성을 보장합니다."""
    pls = profile.get("playlists")
    today_s = get_today_str()
    if not isinstance(pls, list) or len(pls) == 0:
        default_pl = {
            "id": "pl_default",
            "name": "나만의 대표 플레이리스트",
            "desc": "좋아하는 유튜브·스포티파이·사운드클라우드 곡들을 모아둔 리스트입니다 ✨",
            "emoji": "🎧",
            "platform": "YouTube",
            "tracks": [],
            "likes": [],
            "share_count": 0,
            "created_at": today_s,
            "updated_at": today_s,
        }
        profile["playlists"] = [default_pl]
        return profile["playlists"]

    normalized_list = []
    for idx, pl in enumerate(pls):
        if not isinstance(pl, dict):
            continue
        plat = str(pl.get("platform") or "YouTube")
        if plat not in PLAYLIST_PLATFORMS:
            plat = "YouTube"
        raw_tracks = pl.get("tracks") if isinstance(pl.get("tracks"), list) else []
        norm_tracks = [normalize_playlist_track(t) for t in raw_tracks if isinstance(t, dict)]
        likes = pl.get("likes") if isinstance(pl.get("likes"), list) else []
        likes = [str(uid) for uid in likes]
        norm_pl = {
            "id": str(pl.get("id") or f"pl_{idx}_{int(time.time())}"),
            "name": str(pl.get("name") or f"플레이리스트 #{idx + 1}").strip()[:50],
            "desc": str(pl.get("desc") or "나만의 감성 음악 플레이리스트 ✨").strip()[:120],
            "emoji": str(pl.get("emoji") or "🎧").strip()[:10] or "🎧",
            "platform": plat,
            "tracks": norm_tracks,
            "likes": likes,
            "share_count": int(pl.get("share_count", 0)),
            "created_at": str(pl.get("created_at") or today_s),
            "updated_at": str(pl.get("updated_at") or today_s),
        }
        normalized_list.append(norm_pl)

    if not normalized_list:
        return ensure_user_playlists({"playlists": []}, user_name)

    profile["playlists"] = normalized_list
    return profile["playlists"]


def get_default_user_profile(user_name: str = "") -> dict:
    today_s = get_today_str()
    return {
        "liked_music": [],
        "playlists": [
            {
                "id": "pl_default",
                "name": "나만의 대표 플레이리스트",
                "desc": "좋아하는 유튜브·스포티파이·사운드클라우드 곡들을 모아둔 리스트입니다 ✨",
                "emoji": "🎧",
                "platform": "YouTube",
                "tracks": [],
                "likes": [],
                "share_count": 0,
                "created_at": today_s,
                "updated_at": today_s,
            }
        ],
        "oshi": None,
        "deck": [],
        "secret_ddays": {},
        "partner_id": None,
        "crystals": 0,  # 출석체크 및 중복 카드 변환으로 획득, 카드 교환(100) 및 파트너 선물(50)에 사용
        "my_sekai": {
            "theme": "default",
            "owned_themes": ["default"],
            "furniture": [],
            "greeting": "나만의 아늑한 마이세카이에 오신 것을 환영합니다! ✨"
        },
        "attendance": {
            "total_days": 0,
            "streak": 0,
            "max_streak": 0,
            "last_date": "",
            "user_name": user_name,
            "last_guild_name": ""
        },
        "todo": {
            "date": today_s,
            "tasks": [],
            "history": {}
        }
    }


def ensure_user_profile(data: dict, u_key: str | int, user_name: str = "") -> dict:
    """
    어느 기능(출석, 음악 하트, 플레이리스트, 가챠, 비밀디데이 등)에서 유저 프로필에 접근하든
    필수 키(attendance, crystals, todo, my_sekai, playlists 등)가 절대 누락되지 않도록 무결성을 보장합니다.
    """
    u_str = str(u_key)
    profiles = data.setdefault("user_profiles", {})
    if u_str not in profiles or not isinstance(profiles[u_str], dict):
        profiles[u_str] = get_default_user_profile(user_name)
        return profiles[u_str]

    p_val = profiles[u_str]
    p_val.setdefault("liked_music", [])
    p_val.setdefault("oshi", None)
    p_val.setdefault("deck", [])
    p_val.setdefault("partner_id", None)
    p_val.setdefault("crystals", 0)
    if not isinstance(p_val.get("secret_ddays"), dict):
        p_val["secret_ddays"] = {}
    ensure_my_sekai(p_val)
    ensure_user_playlists(p_val, user_name)

    if not isinstance(p_val.get("attendance"), dict):
        p_val["attendance"] = {
            "total_days": 0,
            "streak": 0,
            "max_streak": 0,
            "last_date": "",
            "user_name": user_name,
            "last_guild_name": ""
        }
    else:
        p_val["attendance"].setdefault("total_days", 0)
        p_val["attendance"].setdefault("streak", 0)
        p_val["attendance"].setdefault("max_streak", 0)
        p_val["attendance"].setdefault("last_date", "")
        p_val["attendance"].setdefault("user_name", user_name)
        p_val["attendance"].setdefault("last_guild_name", "")
        if user_name:
            p_val["attendance"]["user_name"] = user_name

    today_str = get_today_str()
    if not isinstance(p_val.get("todo"), dict):
        p_val["todo"] = {"date": today_str, "tasks": [], "history": {}}
    else:
        p_val["todo"].setdefault("date", today_str)
        if not isinstance(p_val["todo"].get("tasks"), list):
            p_val["todo"]["tasks"] = []
        if not isinstance(p_val["todo"].get("history"), dict):
            p_val["todo"]["history"] = {}

    return p_val


def get_partner_pair_key(u1_id: int | str, u2_id: int | str) -> str:
    s1, s2 = str(u1_id), str(u2_id)
    return f"{min(s1, s2)}_{max(s1, s2)}"


def get_firebase_endpoint():
    if not FIREBASE_DB_URL or not FIREBASE_DB_URL.startswith("https://") or "여기에_" in FIREBASE_DB_URL or "norosi-default-rtdb" in FIREBASE_DB_URL:
        return None
    if time.time() < _FIREBASE_DISABLED_UNTIL:
        return None
    url = f"{FIREBASE_DB_URL}/norosi_bot.json"
    if FIREBASE_SECRET:
        url += f"?auth={FIREBASE_SECRET}"
    return url


def normalize_data(data):
    today_str = get_today_str()
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_CONFIG)

    if "settings" not in data or not isinstance(data["settings"], dict):
        data["settings"] = copy.deepcopy(DEFAULT_CONFIG["settings"])
    else:
        for k, v in DEFAULT_CONFIG["settings"].items():
            data["settings"].setdefault(k, v)

    if "ddays" not in data or not isinstance(data["ddays"], dict):
        data["ddays"] = {}
    else:
        for name, value in list(data["ddays"].items()):
            if isinstance(value, str):
                data["ddays"][name] = {
                    "date": value,
                    "repeat": False,
                    "start_date": today_str,
                    "emoji": "🌠",
                    "channel_id": None,
                    "category_id": None
                }
            elif isinstance(value, dict):
                value.setdefault("repeat", False)
                value.setdefault("start_date", today_str)
                value.setdefault("emoji", "🌠")
                value.setdefault("channel_id", None)
                value.setdefault("category_id", None)

    if "music_prefs" not in data or not isinstance(data["music_prefs"], dict):
        data["music_prefs"] = copy.deepcopy(DEFAULT_CONFIG["music_prefs"])
    else:
        for k, v in DEFAULT_CONFIG["music_prefs"].items():
            data["music_prefs"].setdefault(k, v)

    if "music_schedules" not in data or not isinstance(data["music_schedules"], list):
        data["music_schedules"] = []

    if "gacha_pickup" not in data or not isinstance(data["gacha_pickup"], dict):
        data["gacha_pickup"] = copy.deepcopy(DEFAULT_CONFIG["gacha_pickup"])
    else:
        for k, v in DEFAULT_CONFIG["gacha_pickup"].items():
            data["gacha_pickup"].setdefault(k, v)

    if "gacha_users" not in data or not isinstance(data["gacha_users"], dict):
        data["gacha_users"] = {}
    else:
        for g_key, g_map in list(data["gacha_users"].items()):
            if isinstance(g_map, dict):
                for u_key, u_info in list(g_map.items()):
                    if isinstance(u_info, dict) and isinstance(u_info.get("cards"), dict):
                        for cid_str, c_obj in u_info["cards"].items():
                            if isinstance(c_obj, dict):
                                c_obj.setdefault("locked", False)

    if "user_profiles" not in data or not isinstance(data["user_profiles"], dict):
        data["user_profiles"] = {}
    else:
        for u_key in list(data["user_profiles"].keys()):
            ensure_user_profile(data, u_key)

    if "partners" not in data or not isinstance(data["partners"], dict):
        data["partners"] = {}

    if "guild_attendance" not in data or not isinstance(data["guild_attendance"], dict):
        data["guild_attendance"] = {}

    if "server_logs" not in data or not isinstance(data["server_logs"], dict):
        data["server_logs"] = copy.deepcopy(DEFAULT_CONFIG.get("server_logs", {}))
    else:
        for g_key, g_cfg in list(data["server_logs"].items()):
            if not isinstance(g_cfg, dict):
                data["server_logs"][g_key] = {"channel_id": None, "enabled": False, "events": {}}
            else:
                g_cfg.setdefault("channel_id", None)
                g_cfg.setdefault("enabled", False)
                events = g_cfg.setdefault("events", {})
                if not isinstance(events, dict):
                    events = {}
                    g_cfg["events"] = events
                for ev_key in ("mod_admin", "channels", "messages", "members", "voice", "roles", "server"):
                    events.setdefault(ev_key, True)

    if "server_stats" not in data or not isinstance(data["server_stats"], dict):
        data["server_stats"] = {}

    if "user_ai_config" not in data or not isinstance(data["user_ai_config"], dict):
        data["user_ai_config"] = {}

    if "ai_usage" not in data or not isinstance(data["ai_usage"], dict):
        data["ai_usage"] = {}

    if "birthdays" not in data or not isinstance(data["birthdays"], dict):
        data["birthdays"] = {}

    if "reminders" not in data or not isinstance(data["reminders"], list):
        data["reminders"] = []

    if "suggestions" not in data or not isinstance(data["suggestions"], list):
        data["suggestions"] = []

    if "reaction_roles" not in data or not isinstance(data["reaction_roles"], dict):
        data["reaction_roles"] = {}

    return data


def _load_local_file_safely():
    if not os.path.exists(DATA_FILE):
        return None
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return normalize_data(raw)
    except Exception as e:
        print(f"⚠️ 로컬 데이터 파일 읽기 오류: {e}", flush=True)
    return None


def _save_local_file_safely(data: dict):
    try:
        tmp_file = f"{DATA_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_file, DATA_FILE)
    except Exception as e:
        print(f"⚠️ 로컬 데이터 파일 저장 오류: {e}", flush=True)


def _merge_local_and_remote(local_data: dict, remote_data: dict) -> dict:
    """
    Firebase가 비어 있거나 일부 데이터만 있을 때 로컬 ddays_data.json의 디데이·출석·프로필·서버로그 설정이
    절대 증발하지 않도록 병합합니다.
    """
    if not remote_data:
        return normalize_data(copy.deepcopy(local_data))
    if not local_data:
        return normalize_data(copy.deepcopy(remote_data))

    merged = normalize_data(copy.deepcopy(remote_data))
    local_norm = normalize_data(copy.deepcopy(local_data))

    for d_name, d_info in local_norm.get("ddays", {}).items():
        if d_name not in merged["ddays"]:
            merged["ddays"][d_name] = d_info

    for u_key, local_prof in local_norm.get("user_profiles", {}).items():
        if u_key not in merged["user_profiles"]:
            merged["user_profiles"][u_key] = local_prof
        else:
            rem_prof = merged["user_profiles"][u_key]
            if local_prof.get("crystals", 0) > rem_prof.get("crystals", 0):
                rem_prof["crystals"] = local_prof["crystals"]
            l_att = local_prof.get("attendance", {})
            r_att = rem_prof.get("attendance", {})
            if l_att.get("total_days", 0) > r_att.get("total_days", 0):
                rem_prof["attendance"] = copy.deepcopy(l_att)
            l_pls = local_prof.get("playlists", [])
            r_pls = rem_prof.get("playlists", [])
            l_trk_cnt = sum(len(p.get("tracks", [])) for p in l_pls if isinstance(p, dict))
            r_trk_cnt = sum(len(p.get("tracks", [])) for p in r_pls if isinstance(p, dict))
            if len(l_pls) > len(r_pls) or l_trk_cnt > r_trk_cnt:
                rem_prof["playlists"] = copy.deepcopy(l_pls)

    for g_key, local_g_att in local_norm.get("guild_attendance", {}).items():
        rem_g_att = merged["guild_attendance"].setdefault(g_key, {})
        if isinstance(local_g_att, dict):
            for u_key, l_rec in local_g_att.items():
                if u_key not in rem_g_att or l_rec.get("total_days", 0) > rem_g_att[u_key].get("total_days", 0):
                    rem_g_att[u_key] = copy.deepcopy(l_rec)

    for g_key, local_g_users in local_norm.get("gacha_users", {}).items():
        if g_key not in merged["gacha_users"]:
            merged["gacha_users"][g_key] = copy.deepcopy(local_g_users)

    for g_key, local_g_log in local_norm.get("server_logs", {}).items():
        if g_key not in merged["server_logs"]:
            merged["server_logs"][g_key] = copy.deepcopy(local_g_log)
        else:
            rem_g_log = merged["server_logs"][g_key]
            if local_g_log.get("enabled", False) and not rem_g_log.get("enabled", False):
                merged["server_logs"][g_key] = copy.deepcopy(local_g_log)
            elif local_g_log.get("channel_id") and not rem_g_log.get("channel_id"):
                rem_g_log["channel_id"] = local_g_log["channel_id"]
            local_events = local_g_log.get("events", {})
            rem_events = rem_g_log.setdefault("events", {})
            for ev_k, ev_v in local_events.items():
                if ev_k not in rem_events:
                    rem_events[ev_k] = ev_v

    for u_key, b_info in local_norm.get("birthdays", {}).items():
        if u_key not in merged["birthdays"]:
            merged["birthdays"][u_key] = copy.deepcopy(b_info)

    existing_rem_ids = {r.get("id") for r in merged.get("reminders", []) if isinstance(r, dict)}
    for r_item in local_norm.get("reminders", []):
        if isinstance(r_item, dict) and r_item.get("id") not in existing_rem_ids:
            merged["reminders"].append(copy.deepcopy(r_item))

    # 설정값(터미널 로그 채널, 알림 채널 등) 로컬 백업 보존
    for s_k, s_v in local_norm.get("settings", {}).items():
        if s_v is not None and not merged.get("settings", {}).get(s_k):
            merged.setdefault("settings", {})[s_k] = s_v

    # 반응역할(reaction_roles) 로컬 백업 보존
    for mid_s, rr_cfg in local_norm.get("reaction_roles", {}).items():
        if mid_s not in merged.get("reaction_roles", {}):
            merged.setdefault("reaction_roles", {})[mid_s] = copy.deepcopy(rr_cfg)

    return normalize_data(merged)


def get_cached_data() -> dict:
    """
    네트워크 I/O 없이 인메모리 캐시에서 즉시 데이터 사본을 반환합니다.
    디스코드 3초 제한이 있는 슬래시 명령어 자동완성(Autocomplete)에서 사용됩니다.
    """
    global _DATA_CACHE
    with _DATA_LOCK:
        if _DATA_CACHE is not None:
            return copy.deepcopy(_DATA_CACHE)
    return load_data()


def load_data():
    """
    인메모리 캐시 + 로컬 파일 + Firebase RTDB 하이브리드 로더.
    원격 DB가 null이거나 권한 오류일 때 기존 로컬 데이터를 초기화해버리던 버그를 완벽 차단합니다.
    """
    global _DATA_CACHE, _FIREBASE_DISABLED_UNTIL
    with _DATA_LOCK:
        if _DATA_CACHE is not None:
            return copy.deepcopy(_DATA_CACHE)

        local_data = _load_local_file_safely()
        endpoint = get_firebase_endpoint()

        if endpoint:
            try:
                res = requests.get(endpoint, timeout=5)
                if res.status_code == 200:
                    fb_data = res.json()
                    if isinstance(fb_data, dict):
                        _DATA_CACHE = _merge_local_and_remote(local_data, fb_data)
                        _save_local_file_safely(_DATA_CACHE)
                        return copy.deepcopy(_DATA_CACHE)
                    elif fb_data is None:
                        # 원격이 비어있을 때 로컬 데이터가 있으면 로컬 데이터를 보존 후 원격에 업로드
                        base_data = local_data if local_data else normalize_data(copy.deepcopy(DEFAULT_CONFIG))
                        _DATA_CACHE = base_data
                        save_data(_DATA_CACHE)
                        return copy.deepcopy(_DATA_CACHE)
                elif res.status_code in (401, 403, 404):
                    print(f"ℹ️ Firebase 엔드포인트 비활성 (HTTP {res.status_code}) — 로컬 저장소 모드로 동작합니다.", flush=True)
                    _FIREBASE_DISABLED_UNTIL = time.time() + 3600
            except Exception as e:
                print(f"⚠️ Firebase 연결 실패 (로컬 백업 사용): {e}", flush=True)
                _FIREBASE_DISABLED_UNTIL = time.time() + 300

        if local_data:
            _DATA_CACHE = local_data
        else:
            _DATA_CACHE = normalize_data(copy.deepcopy(DEFAULT_CONFIG))
            _save_local_file_safely(_DATA_CACHE)

        return copy.deepcopy(_DATA_CACHE)


def save_data(data):
    """
    인메모리 캐시 갱신 + 원자적 로컬 파일 저장 + Firebase RTDB 동기화.
    """
    global _DATA_CACHE, _FIREBASE_DISABLED_UNTIL
    with _DATA_LOCK:
        normalized = normalize_data(copy.deepcopy(data))
        _DATA_CACHE = normalized
        _save_local_file_safely(normalized)

        endpoint = get_firebase_endpoint()
        if endpoint:
            try:
                res = requests.put(endpoint, json=normalized, timeout=5)
                if res.status_code in (401, 403, 404):
                    _FIREBASE_DISABLED_UNTIL = time.time() + 3600
            except Exception as e:
                print(f"⚠️ Firebase 저장 오류 (로컬 백업에는 정상 저장됨): {e}", flush=True)
                _FIREBASE_DISABLED_UNTIL = time.time() + 300


def reset_dday_and_music_data():
    """
    /데이터초기화 실행 시 D-Day 일정, 알림 채널, 음악 추천 설정 및 타이머만 안전하게 초기화합니다.
    유저의 출석 기록(guild_attendance, user_profiles), 크리스탈, 보유 캐릭터(gacha_users), 파트너 정보는 보존됩니다.
    """
    with _DATA_LOCK:
        data = load_data()
        data["settings"] = copy.deepcopy(DEFAULT_CONFIG["settings"])
        data["ddays"] = {}
        data["music_prefs"] = copy.deepcopy(DEFAULT_CONFIG["music_prefs"])
        data["music_schedules"] = []
        save_data(data)
        return data


def reset_all_data():
    """하위 호환용 래퍼: D-Day 및 음악 설정만 초기화하여 유저 출석·가챠 데이터 증발을 방지합니다."""
    return reset_dday_and_music_data()



# ==========================================
# 3-0. 서버별 1일 1회 독립 출석체크, 월간 캘린더 & 개근 마일스톤 보상 엔진
# ==========================================
def _ensure_guild_monthly_record(guild_rec: dict, today_str: str) -> tuple[list[str], dict]:
    """
    서버 출석 레코드 내 monthly_dates(출석 날짜 리스트)와 claimed_milestones(수령한 마일스톤)를 정규화하고,
    기존 연속 출석일(streak)이 있는 유저의 이번 달 날짜를 자동 복원합니다.
    """
    monthly_dates = guild_rec.get("monthly_dates")
    if not isinstance(monthly_dates, list):
        monthly_dates = []

    ym_prefix = today_str[:7]
    last_date_str = guild_rec.get("last_date", "")
    streak_cnt = int(guild_rec.get("streak", 0))

    # 기존 출석 데이터가 있으나 monthly_dates가 비어 있는 경우 연속 출석일 기반으로 이번 달 날짜 복원
    if last_date_str and last_date_str.startswith(ym_prefix):
        try:
            last_dt = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()
            for offset in range(max(1, streak_cnt)):
                d_obj = last_dt - datetime.timedelta(days=offset)
                d_s = d_obj.strftime("%Y-%m-%d")
                if d_s.startswith(ym_prefix) and d_s not in monthly_dates:
                    monthly_dates.append(d_s)
        except Exception:
            if last_date_str not in monthly_dates:
                monthly_dates.append(last_date_str)

    # 최근 70일 이내의 유효 날짜만 정렬 보관
    monthly_dates = sorted(set(d for d in monthly_dates if isinstance(d, str) and len(d) == 10))[-70:]
    guild_rec["monthly_dates"] = monthly_dates

    claimed_map = guild_rec.get("claimed_milestones")
    if not isinstance(claimed_map, dict):
        claimed_map = {}
    if ym_prefix not in claimed_map or not isinstance(claimed_map[ym_prefix], list):
        claimed_map[ym_prefix] = []
    guild_rec["claimed_milestones"] = claimed_map

    return monthly_dates, claimed_map


def process_user_attendance(guild_id: int, guild_name: str, user_id: int, user_name: str):
    """
    자정(00:00 KST) 기준 각 디스코드 서버별로 하루 1회 독립 출석체크를 허용합니다.
    - 서버 A에서 출석했더라도 서버 B에서 아직 오늘 출석하지 않았다면 정상적으로 출석 가능!
    - 서버 출석 성공 시 기본 100 크리스탈 + 월간 개근 마일스톤(7/14/21/28일) 달성 보너스를 자동 지급합니다.
    """
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        today_str = get_today_str()
        yesterday_str = get_yesterday_str()
        ym_prefix = today_str[:7]

        profile = ensure_user_profile(data, u_key, user_name)
        g_att_map = data["guild_attendance"].setdefault(g_key, {})
        global_att = profile["attendance"]
        oshi_name = profile.get("oshi")

        guild_rec = g_att_map.get(u_key, {
            "total_days": 0,
            "streak": 0,
            "max_streak": 0,
            "last_date": "",
            "user_name": user_name,
            "monthly_dates": [],
            "claimed_milestones": {}
        })
        monthly_dates, claimed_map = _ensure_guild_monthly_record(guild_rec, today_str)

        # 해당 서버(guild_id)에서 오늘 이미 출석체크를 완료한 경우
        if guild_rec.get("last_date") == today_str:
            # 혹시 미수령된 이번 달 달성 마일스톤이 있다면 즉시 정산
            month_days_cnt = sum(1 for d in monthly_dates if d.startswith(ym_prefix))
            claimed_this_month = claimed_map.setdefault(ym_prefix, [])
            bonus_gained = 0
            newly_claimed = []
            for m in ATTENDANCE_MILESTONES:
                if month_days_cnt >= m["days"] and m["days"] not in claimed_this_month:
                    claimed_this_month.append(m["days"])
                    bonus_gained += m["reward"]
                    newly_claimed.append(m)

            if guild_rec.get("user_name") != user_name or bonus_gained > 0:
                guild_rec["user_name"] = user_name
                if bonus_gained > 0:
                    profile["crystals"] = profile.get("crystals", 0) + bonus_gained
                g_att_map[u_key] = guild_rec
                save_data(data)

            my_sekai_bonus = get_my_sekai_daily_bonus(profile)
            return {
                "already_checked": True,
                "guild_stats": guild_rec,
                "global_stats": global_att,
                "oshi": oshi_name,
                "checked_guild_name": guild_name,
                "crystals": profile.get("crystals", 0),
                "gained_crystals": bonus_gained,
                "milestone_bonus": bonus_gained,
                "my_sekai_bonus": my_sekai_bonus,
                "newly_claimed_milestones": newly_claimed,
                "month_days_count": month_days_cnt
            }

        # 1) 현재 서버(guild_id) 출석 기록 갱신 (서버별 독립 연속일/누적일 계산)
        if guild_rec.get("last_date") == yesterday_str:
            new_guild_streak = guild_rec.get("streak", 0) + 1
        else:
            new_guild_streak = 1

        new_guild_total = guild_rec.get("total_days", 0) + 1
        new_guild_max = max(guild_rec.get("max_streak", 0), new_guild_streak)

        if today_str not in monthly_dates:
            monthly_dates.append(today_str)
            monthly_dates.sort()

        month_days_cnt = sum(1 for d in monthly_dates if d.startswith(ym_prefix))
        claimed_this_month = claimed_map.setdefault(ym_prefix, [])
        milestone_bonus = 0
        newly_claimed = []
        for m in ATTENDANCE_MILESTONES:
            if month_days_cnt >= m["days"] and m["days"] not in claimed_this_month:
                claimed_this_month.append(m["days"])
                milestone_bonus += m["reward"]
                newly_claimed.append(m)

        updated_guild_rec = {
            "total_days": new_guild_total,
            "streak": new_guild_streak,
            "max_streak": new_guild_max,
            "last_date": today_str,
            "user_name": user_name,
            "monthly_dates": monthly_dates,
            "claimed_milestones": claimed_map
        }
        g_att_map[u_key] = updated_guild_rec

        # 2) 통합 프로필(global_att) 출석 기록 갱신 (동일 날짜에는 1일만 증가하도록 cap 적용)
        if global_att.get("last_date") != today_str:
            if global_att.get("last_date") == yesterday_str:
                global_att["streak"] = global_att.get("streak", 0) + 1
            else:
                global_att["streak"] = 1
            global_att["last_date"] = today_str
            global_att["total_days"] = global_att.get("total_days", 0) + 1

        global_att["total_days"] = max(global_att.get("total_days", 0), new_guild_total)
        global_att["streak"] = max(global_att.get("streak", 1), new_guild_streak)
        global_att["max_streak"] = max(global_att.get("max_streak", 0), global_att["streak"], new_guild_max)
        global_att["user_name"] = user_name
        global_att["last_guild_name"] = guild_name

        # 3) 서버별 1회 출석 기본 +100 크리스탈 + 마이세카이 가구/테마 패시브 이자 + 개근 마일스톤 달성 보너스 지급
        my_sekai_bonus = get_my_sekai_daily_bonus(profile)
        total_gained = 100 + my_sekai_bonus + milestone_bonus
        profile["crystals"] = profile.get("crystals", 0) + total_gained

        save_data(data)
        return {
            "already_checked": False,
            "guild_stats": updated_guild_rec,
            "global_stats": global_att,
            "oshi": oshi_name,
            "checked_guild_name": guild_name,
            "crystals": profile["crystals"],
            "gained_crystals": total_gained,
            "milestone_bonus": milestone_bonus,
            "my_sekai_bonus": my_sekai_bonus,
            "newly_claimed_milestones": newly_claimed,
            "month_days_count": month_days_cnt
        }


def build_monthly_attendance_calendar(guild_id: int, guild_name: str, user_id: int, user_name: str = "") -> dict:
    """
    이번 달(KST 기준) 출석한 날짜를 시각적 달력(Grid)으로 렌더링하고,
    개근 보상 마일스톤(7일/14일/21일/28일) 달성 현황을 반환합니다.
    """
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        now = datetime.datetime.now(KST)
        today_str = now.strftime("%Y-%m-%d")
        ym_prefix = now.strftime("%Y-%m")
        days_in_month = calendar.monthrange(now.year, now.month)[1]

        profile = ensure_user_profile(data, u_key, user_name)
        g_att_map = data["guild_attendance"].setdefault(g_key, {})
        guild_rec = g_att_map.get(u_key, {
            "total_days": 0,
            "streak": 0,
            "max_streak": 0,
            "last_date": "",
            "user_name": user_name,
            "monthly_dates": [],
            "claimed_milestones": {}
        })
        monthly_dates, claimed_map = _ensure_guild_monthly_record(guild_rec, today_str)
        g_att_map[u_key] = guild_rec
        save_data(data)

        attended_days_set = set()
        for d_str in monthly_dates:
            if d_str.startswith(ym_prefix):
                try:
                    attended_days_set.add(int(d_str.split("-")[2]))
                except Exception:
                    pass

        cal = calendar.Calendar(firstweekday=6)  # 일요일 시작 달력
        weeks = cal.monthdayscalendar(now.year, now.month)

        cal_rows = [" 일   월   화   수   목   금   토 ", "──────────────────────────────────"]
        for week in weeks:
            row_cells = []
            for day_num in week:
                if day_num == 0:
                    row_cells.append("    ")
                elif day_num in attended_days_set:
                    if day_num == now.day:
                        row_cells.append(f"🌟{day_num:02d}")
                    else:
                        row_cells.append(f"✅{day_num:02d}")
                else:
                    if day_num == now.day:
                        row_cells.append(f"📍{day_num:02d}")
                    elif day_num < now.day:
                        row_cells.append(f" ·{day_num:02d}")
                    else:
                        row_cells.append(f"  {day_num:02d}")
            cal_rows.append(" ".join(row_cells))

        month_count = len(attended_days_set)
        month_rate = (month_count / days_in_month) * 100.0 if days_in_month > 0 else 0.0
        filled = min(10, int(month_rate // 10))
        month_bar = ("🌌" * filled) + ("🌑" * max(0, 10 - filled)) + f" **{month_rate:.1f}%** (`{month_count}/{days_in_month}일`)"

        claimed_list = claimed_map.setdefault(ym_prefix, [])
        new_bonus = 0
        milestone_items = []
        for m in ATTENDANCE_MILESTONES:
            target_d = m["days"]
            is_achieved = month_count >= target_d
            if is_achieved and target_d not in claimed_list:
                claimed_list.append(target_d)
                new_bonus += m["reward"]
            is_claimed = (target_d in claimed_list) or is_achieved
            rem_d = max(0, target_d - month_count)
            milestone_items.append({
                "days": target_d,
                "reward": m["reward"],
                "title": m["title"],
                "emoji": m["emoji"],
                "achieved": is_claimed,
                "remaining_days": rem_d
            })

        if new_bonus > 0:
            profile["crystals"] = profile.get("crystals", 0) + new_bonus
            g_att_map[u_key] = guild_rec
            save_data(data)

        return {
            "year": now.year,
            "month": now.month,
            "today_day": now.day,
            "days_in_month": days_in_month,
            "attended_days": sorted(attended_days_set),
            "month_count": month_count,
            "month_rate": month_rate,
            "month_bar": month_bar,
            "calendar_text": "\n".join(cal_rows),
            "milestones": milestone_items,
            "guild_stats": guild_rec,
            "global_stats": profile.get("attendance", {}),
            "crystals": profile.get("crystals", 0),
            "checked_today": (now.day in attended_days_set),
            "guild_name": guild_name
        }


def get_attendance_galaxy_bar(total_days: int) -> str:
    """다음 출석 목표(7일, 14일, 30일, 50일, 100일, 200일, 365일...)까지의 은하수 진행률 바 생성"""
    milestones = [7, 14, 30, 50, 100, 200, 365, 500, 1000]
    target = next((m for m in milestones if total_days < m), ((total_days // 100) + 1) * 100)
    prev = 0
    for m in milestones:
        if m < target:
            prev = m
        else:
            break

    span = max(1, target - prev)
    prog = max(0, total_days - prev)
    percent = min(100.0, max(0.0, (prog / span) * 100))
    filled_count = min(9, int(percent // 10))
    empty_count = max(0, 10 - filled_count - 1)
    bar = ("🌌" * filled_count) + "🌠" + ("🌑" * empty_count)
    return f"{bar} **{int(percent)}%** (다음 목표 `{target}일`까지 `{target - total_days}일`)"


# ==========================================
# 3-1. 은하수 잔디 심기 (To-Do 트래커) 헬퍼 함수
# ==========================================
def ensure_user_todo_today(profile: dict) -> dict:
    """날짜가 바뀌었으면 이전 날의 기록을 history에 보존하고 오늘 날짜의 할 일 목록을 준비"""
    today_str = get_today_str()
    todo = profile.setdefault("todo", {"date": today_str, "tasks": [], "history": {}})
    history = todo.setdefault("history", {})
    tasks_list = todo.setdefault("tasks", [])

    if todo.get("date") != today_str:
        old_date = todo.get("date")
        if old_date and tasks_list:
            done_cnt = sum(1 for t in tasks_list if t.get("done"))
            history[old_date] = {"done": done_cnt, "total": len(tasks_list)}
        todo["date"] = today_str
        todo["tasks"] = []
    else:
        done_cnt = sum(1 for t in tasks_list if t.get("done"))
        history[today_str] = {"done": done_cnt, "total": len(tasks_list)}

    if len(history) > 35:
        for k in sorted(history.keys())[:-30]:
            del history[k]

    return todo


def sync_todo_history_today(todo: dict):
    today_str = get_today_str()
    tasks_list = todo.get("tasks", [])
    done_cnt = sum(1 for t in tasks_list if t.get("done"))
    todo.setdefault("history", {})[today_str] = {"done": done_cnt, "total": len(tasks_list)}


def get_todo_galaxy_grass(profile: dict) -> tuple[str, str]:
    """최근 7일간의 은하수 잔디(🌌 완료 / 🌠 진행중 / 🌑 미달성) 요약 줄과 상세 내역 문자열 반환"""
    todo = ensure_user_todo_today(profile)
    history = todo.get("history", {})
    today_date = datetime.datetime.now(KST).date()

    blocks = []
    detail_lines = []
    perfect_days = 0

    for offset in range(6, -1, -1):
        d_obj = today_date - datetime.timedelta(days=offset)
        d_str = d_obj.strftime("%Y-%m-%d")
        mm_dd = d_obj.strftime("%m/%d")
        rec = history.get(d_str, {"done": 0, "total": 0})
        done_c = rec.get("done", 0)
        tot_c = rec.get("total", 0)

        if tot_c > 0 and done_c >= tot_c:
            icon = "🌌"
            perfect_days += 1
            status_txt = f"`{done_c}/{tot_c}` (100% ✨)"
        elif done_c > 0:
            icon = "🌠"
            pct = int((done_c / tot_c) * 100) if tot_c > 0 else 0
            status_txt = f"`{done_c}/{tot_c}` ({pct}%)"
        else:
            icon = "🌑"
            status_txt = f"`0/{tot_c}`" if tot_c > 0 else "`미등록`"

        blocks.append(icon)
        today_mark = " **(오늘)**" if offset == 0 else ""
        detail_lines.append(f"{icon} `{mm_dd}` : {status_txt}{today_mark}")

    grass_bar = "".join(blocks) + f" (최근 7일 완주: **`{perfect_days}일`**)"
    return grass_bar, "\n".join(detail_lines)


# ==========================================
# 4. 프로세카 확률 계산, 가챠(뽑기), 잠금, 중복 변환, 카드 교환 및 선물 엔진
# ==========================================
def is_card_pickup(card, pickup_cfg):
    p_unit = pickup_cfg.get("unit")
    p_char = pickup_cfg.get("character")
    if not p_unit and not p_char:
        return False

    unit_match = True
    char_match = True
    if p_unit:
        unit_match = (card["unit"] == p_unit or card.get("support_unit") == p_unit)
    if p_char:
        char_match = (card["char_name"] == p_char)
    return unit_match and char_match


def calculate_card_probabilities(pickup_cfg):
    include_lim = pickup_cfg.get("include_limited", True)
    pool = [c for c in PROSEKA_KR_CARDS if include_lim or not c["is_limited"]]
    if not pool:
        pool = list(PROSEKA_KR_CARDS)

    tier_groups = {"top": [], "mid": [], "low": []}
    for c in pool:
        if c["rarity_type"] in ("rarity_4", "rarity_birthday"):
            tier_groups["top"].append(c)
        elif c["rarity_type"] == "rarity_3":
            tier_groups["mid"].append(c)
        else:
            tier_groups["low"].append(c)

    tier_rates = {"top": 3.0, "mid": 8.5, "low": 88.5}
    result_list = []

    for tier_key, cards in tier_groups.items():
        if not cards:
            continue
        total_tier_prob = tier_rates[tier_key]
        pickup_cards = [c for c in cards if is_card_pickup(c, pickup_cfg)]
        normal_cards = [c for c in cards if not is_card_pickup(c, pickup_cfg)]

        if pickup_cards and normal_cards:
            pickup_share = total_tier_prob * 0.50
            normal_share = total_tier_prob * 0.50
            p_each = pickup_share / len(pickup_cards)
            n_each = normal_share / len(normal_cards)
            for c in cards:
                is_p = is_card_pickup(c, pickup_cfg)
                prob = p_each if is_p else n_each
                item = dict(c)
                item["prob"] = prob
                item["is_pickup"] = is_p
                result_list.append(item)
        else:
            each_prob = total_tier_prob / len(cards)
            for c in cards:
                is_p = is_card_pickup(c, pickup_cfg)
                item = dict(c)
                item["prob"] = each_prob
                item["is_pickup"] = is_p
                result_list.append(item)

    result_list.sort(key=lambda x: (not x["is_pickup"], -x["star_num"], x["char_id"], x["id"]))
    return result_list


def draw_proseka_cards(pickup_cfg, count=1):
    prob_cards = calculate_card_probabilities(pickup_cfg)
    if not prob_cards:
        return []

    weights = [c["prob"] for c in prob_cards]
    drawn = random.choices(prob_cards, weights=weights, k=count)

    if count >= 10 and not any(c["star_num"] >= 3 for c in drawn):
        high_pool = [c for c in prob_cards if c["star_num"] >= 3]
        if high_pool:
            high_weights = [c["prob"] for c in high_pool]
            drawn[-1] = random.choices(high_pool, weights=high_weights, k=1)[0]

    return drawn


def save_pulled_cards_to_user(guild_id: int, user_id: int, drawn_cards: list):
    """뽑은 카드를 내 캐릭터 보관함에 즉시 저장"""
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)

        if g_key not in data["gacha_users"]:
            data["gacha_users"][g_key] = {}
        if u_key not in data["gacha_users"][g_key]:
            data["gacha_users"][g_key][u_key] = {"cards": {}}

        user_cards = data["gacha_users"][g_key][u_key].setdefault("cards", {})
        now_str = get_now_datetime_str()

        for c in drawn_cards:
            cid_str = str(c["id"])
            if cid_str in user_cards:
                c["is_new"] = False
                user_cards[cid_str]["count"] = user_cards[cid_str].get("count", 1) + 1
                user_cards[cid_str]["last_obtained_at"] = now_str
                user_cards[cid_str].setdefault("locked", False)
                user_cards[cid_str].setdefault("level", 1)
                user_cards[cid_str].setdefault("awakened", False)
                if c.get("assetbundleName"):
                    user_cards[cid_str]["assetbundleName"] = c["assetbundleName"]
            else:
                c["is_new"] = True
                user_cards[cid_str] = {
                    "id": c["id"],
                    "char_id": c["char_id"],
                    "char_name": c["char_name"],
                    "unit": c["unit"],
                    "support_unit": c.get("support_unit"),
                    "rarity_type": c["rarity_type"],
                    "rarity_label": c["rarity_label"],
                    "star_num": c["star_num"],
                    "prefix": c["prefix"],
                    "attr": c["attr"],
                    "limit_label": c["limit_label"],
                    "is_limited": c["is_limited"],
                    "assetbundleName": c.get("assetbundleName", ""),
                    "obtained_at": now_str,
                    "last_obtained_at": now_str,
                    "count": 1,
                    "level": 1,
                    "awakened": False,
                    "locked": False
                }

        save_data(data)
        return user_cards


def toggle_user_card_lock(guild_id: int, user_id: int, card_id_str: str) -> tuple[bool, bool, dict | None]:
    """
    보유 카드의 잠금(🔒) 상태를 전환합니다.
    반환값: (성공여부, 변경후잠금상태, 카드객체)
    """
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        user_cards = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        cid_str = str(card_id_str)
        if cid_str not in user_cards:
            return False, False, None

        current_locked = bool(user_cards[cid_str].get("locked", False))
        new_locked = not current_locked
        user_cards[cid_str]["locked"] = new_locked
        save_data(data)
        return True, new_locked, copy.deepcopy(user_cards[cid_str])


def preview_duplicate_cards(guild_id: int, user_id: int) -> dict:
    """
    보유 수량이 2장 이상(count >= 2)이고 잠금(locked)되지 않은 카드들의
    초과분(count - 1) 크리스탈 변환 예상치를 계산합니다. (원본 1장은 무조건 보존)
    """
    data = load_data()
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    user_cards = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})

    summary = {
        "total_excess_cards": 0,
        "total_crystals": 0,
        "by_rarity": {
            "rarity_4": {"count": 0, "crystals": 0, "label": "★★★★ (100💎)"},
            "rarity_birthday": {"count": 0, "crystals": 0, "label": "🎀생일 (60💎)"},
            "rarity_3": {"count": 0, "crystals": 0, "label": "★★★ (25💎)"},
            "rarity_2": {"count": 0, "crystals": 0, "label": "★★ (5💎)"},
            "rarity_1": {"count": 0, "crystals": 0, "label": "★ (5💎)"}
        },
        "locked_skipped": 0
    }

    for cid_str, c in user_cards.items():
        cnt = c.get("count", 1)
        if cnt < 2:
            continue
        if c.get("locked", False):
            summary["locked_skipped"] += (cnt - 1)
            continue

        excess = cnt - 1
        r_type = c.get("rarity_type", "rarity_2")
        rate = DUPLICATE_CRYSTAL_RATES.get(r_type, 5)
        gained = excess * rate

        summary["total_excess_cards"] += excess
        summary["total_crystals"] += gained
        if r_type in summary["by_rarity"]:
            summary["by_rarity"][r_type]["count"] += excess
            summary["by_rarity"][r_type]["crystals"] += gained

    return summary


def execute_duplicate_card_conversion(guild_id: int, user_id: int) -> dict:
    """
    잠금되지 않은 2장 이상 보유 카드들의 초과분(count - 1)을 크리스탈로 일괄 변환합니다.
    모든 카드는 최소 1장씩 반드시 유지되어 도감 수집률과 5인 덱이 100% 보존됩니다.
    """
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        profile = ensure_user_profile(data, u_key)
        user_cards = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})

        total_converted = 0
        total_gained = 0
        details = []

        for cid_str, c in user_cards.items():
            cnt = c.get("count", 1)
            if cnt < 2 or c.get("locked", False):
                continue
            excess = cnt - 1
            r_type = c.get("rarity_type", "rarity_2")
            rate = DUPLICATE_CRYSTAL_RATES.get(r_type, 5)
            gained = excess * rate

            c["count"] = 1
            total_converted += excess
            total_gained += gained
            details.append(f"`{c['rarity_label']}` [{c['prefix']}] {c['char_name']} (`-{excess}장` ➔ `+{gained}💎`)")

        if total_converted > 0:
            profile["crystals"] = profile.get("crystals", 0) + total_gained
            save_data(data)

        return {
            "converted_count": total_converted,
            "gained_crystals": total_gained,
            "current_crystals": profile.get("crystals", 0),
            "details": details
        }


def get_card_pokedex_stats(guild_id: int, user_id: int) -> dict:
    """
    프로세카 한국 서버 전체 마스터 DB(PROSEKA_KR_CARDS)와 유저의 보유 카드를 대조하여
    전체 도감 수집률, 캐릭터별(26명) 수집률(%), 성급별 수집 현황, 미획득 카드 및 보유 카드 목록을 반환합니다.
    """
    data = load_data()
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    user_cards_map = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
    owned_id_set = set(str(cid) for cid in user_cards_map.keys())

    master_pool = list(PROSEKA_KR_CARDS) if PROSEKA_KR_CARDS else build_fallback_proseka_cards()
    owned_list = []
    unowned_list = []

    char_buckets = {}
    for cid_num, c_meta in CHARACTER_MAP.items():
        char_buckets[cid_num] = {
            "char_id": cid_num,
            "char_name": c_meta["name"],
            "unit": c_meta["unit"],
            "owned_count": 0,
            "total_count": 0,
            "rate": 0.0,
            "bar": "",
            "owned_cards": [],
            "unowned_cards": []
        }

    rarity_stats = {
        "rarity_4": {"label": "★★★★", "owned": 0, "total": 0},
        "rarity_birthday": {"label": "🎀생일", "owned": 0, "total": 0},
        "rarity_3": {"label": "★★★", "owned": 0, "total": 0},
        "rarity_2": {"label": "★★", "owned": 0, "total": 0},
        "rarity_1": {"label": "★", "owned": 0, "total": 0}
    }

    for mc in master_pool:
        mc_id_str = str(mc.get("id"))
        c_id = mc.get("char_id")
        r_type = mc.get("rarity_type", "rarity_2")
        is_owned = mc_id_str in owned_id_set

        item = dict(mc)
        if is_owned:
            u_card = user_cards_map[mc_id_str]
            item["count"] = u_card.get("count", 1)
            item["locked"] = bool(u_card.get("locked", False))
            item["obtained_at"] = u_card.get("obtained_at", "-")
            owned_list.append(item)
        else:
            item["count"] = 0
            item["locked"] = False
            unowned_list.append(item)

        if r_type in rarity_stats:
            rarity_stats[r_type]["total"] += 1
            if is_owned:
                rarity_stats[r_type]["owned"] += 1

        if c_id in char_buckets:
            char_buckets[c_id]["total_count"] += 1
            if is_owned:
                char_buckets[c_id]["owned_count"] += 1
                char_buckets[c_id]["owned_cards"].append(item)
            else:
                char_buckets[c_id]["unowned_cards"].append(item)

    sort_key = lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), x.get("char_id", 99), x.get("id", 0))
    owned_list.sort(key=sort_key)
    unowned_list.sort(key=sort_key)

    by_character = []
    for cid_num in sorted(char_buckets.keys()):
        b = char_buckets[cid_num]
        tot = b["total_count"]
        own = b["owned_count"]
        rate = (own / tot * 100.0) if tot > 0 else 0.0
        b["rate"] = rate
        filled = min(5, int(round(rate / 20.0)))
        b["bar"] = ("🌌" * filled) + ("🌑" * max(0, 5 - filled))
        b["owned_cards"].sort(key=sort_key)
        b["unowned_cards"].sort(key=sort_key)
        by_character.append(b)

    total_master = len(master_pool)
    total_owned = len(owned_list)
    total_unowned = len(unowned_list)
    overall_rate = (total_owned / total_master * 100.0) if total_master > 0 else 0.0
    ov_filled = min(10, int(overall_rate // 10))
    overall_bar = ("🌌" * ov_filled) + ("🌑" * max(0, 10 - ov_filled)) + f" **{overall_rate:.1f}%**"

    return {
        "total_master": total_master,
        "total_owned": total_owned,
        "total_unowned": total_unowned,
        "overall_rate": overall_rate,
        "overall_bar": overall_bar,
        "by_rarity": rarity_stats,
        "by_character": by_character,
        "owned_cards": owned_list,
        "unowned_cards": unowned_list
    }


def _transfer_single_card(g_users: dict, profiles: dict, from_uid: str, to_uid: str, card_id_str: str) -> dict:
    """특정 유저의 보관함에서 카드를 1장 차감하여 대상 유저의 보관함으로 이전"""
    from_cards = g_users.setdefault(from_uid, {}).setdefault("cards", {})
    to_cards = g_users.setdefault(to_uid, {}).setdefault("cards", {})

    src_card = copy.deepcopy(from_cards[card_id_str])
    src_card["locked"] = False
    now_str = get_now_datetime_str()

    # 보내는 유저 카드 수량 1 차감 (0장이 되면 보관함 및 덱에서 제거)
    if from_cards[card_id_str].get("count", 1) > 1:
        from_cards[card_id_str]["count"] -= 1
    else:
        del from_cards[card_id_str]
        if from_uid in profiles and card_id_str in profiles[from_uid].get("deck", []):
            profiles[from_uid]["deck"] = [cid for cid in profiles[from_uid]["deck"] if cid != card_id_str]

    # 받는 유저 보관함에 1장 추가
    if card_id_str in to_cards:
        to_cards[card_id_str]["count"] = to_cards[card_id_str].get("count", 1) + 1
        to_cards[card_id_str]["last_obtained_at"] = now_str
    else:
        src_card["count"] = 1
        src_card["obtained_at"] = now_str
        src_card["last_obtained_at"] = now_str
        to_cards[card_id_str] = src_card

    return src_card


def execute_card_trade(guild_id: int, requester_id: int, target_id: int, req_card_id: str, target_card_id: str):
    """
    유저 간 1:1 카드 교환 실행 (상대방 수락 시 호출).
    신청자의 크리스탈 100개를 차감하고 두 유저의 카드를 1장씩 맞교환합니다.
    잠금(🔒) 상태인 카드는 교환할 수 없습니다.
    """
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        r_key = str(requester_id)
        t_key = str(target_id)

        req_prof = ensure_user_profile(data, r_key)
        ensure_user_profile(data, t_key)

        req_crystals = req_prof.get("crystals", 0)
        if req_crystals < 100:
            return False, f"신청자(<@{requester_id}>)의 크리스탈이 부족합니다. (필요: `100개` / 보유: `{req_crystals}개`)", None, None, req_crystals

        g_users = data["gacha_users"].setdefault(g_key, {})
        req_cards = g_users.get(r_key, {}).get("cards", {})
        tgt_cards = g_users.get(t_key, {}).get("cards", {})

        if req_card_id not in req_cards or req_cards[req_card_id].get("count", 0) < 1:
            return False, f"신청자(<@{requester_id}>)가 해당 카드를 더 이상 보유하고 있지 않습니다.", None, None, req_crystals
        if target_card_id not in tgt_cards or tgt_cards[target_card_id].get("count", 0) < 1:
            return False, f"수락자(<@{target_id}>)가 해당 카드를 더 이상 보유하고 있지 않습니다.", None, None, req_crystals

        if req_cards[req_card_id].get("locked", False):
            return False, f"신청자(<@{requester_id}>)의 카드가 `🔒 잠금` 상태여서 교환할 수 없습니다. (`/내캐릭터`에서 잠금 해제 필요)", None, None, req_crystals
        if tgt_cards[target_card_id].get("locked", False):
            return False, f"수락자(<@{target_id}>)의 카드가 `🔒 잠금` 상태여서 교환할 수 없습니다. (`/내캐릭터`에서 잠금 해제 필요)", None, None, req_crystals

        req_prof["crystals"] = req_crystals - 100
        remaining_crystals = req_prof["crystals"]

        given_card = _transfer_single_card(g_users, data["user_profiles"], r_key, t_key, req_card_id)
        received_card = _transfer_single_card(g_users, data["user_profiles"], t_key, r_key, target_card_id)

        save_data(data)
        return True, "교환 성공", given_card, received_card, remaining_crystals


def execute_partner_gift(guild_id: int, sender_id: int, partner_id: int, card_id: str):
    """
    파트너에게 카드 1장 선물 실행 (50 크리스탈 소모). 잠금 카드는 보호됩니다.
    """
    with _DATA_LOCK:
        data = load_data()
        g_key = str(guild_id or 0)
        s_key = str(sender_id)
        p_key = str(partner_id)

        sender_prof = ensure_user_profile(data, s_key)
        ensure_user_profile(data, p_key)

        sender_crystals = sender_prof.get("crystals", 0)
        if sender_crystals < 50:
            return False, f"선물에 필요한 크리스탈이 부족합니다! (필요: `50개` / 현재 보유: `{sender_crystals}개` — `/출석체크` 또는 `/중복카드변환`으로 획득 가능)", None, sender_crystals

        g_users = data["gacha_users"].setdefault(g_key, {})
        sender_cards = g_users.get(s_key, {}).get("cards", {})
        if card_id not in sender_cards or sender_cards[card_id].get("count", 0) < 1:
            return False, "선물하려는 카드를 보유하고 있지 않습니다.", None, sender_crystals

        if sender_cards[card_id].get("locked", False):
            return False, "해당 카드는 `🔒 잠금` 상태입니다! 선물하려면 `/내캐릭터`에서 먼저 잠금을 해제해 주세요.", None, sender_crystals

        sender_prof["crystals"] = sender_crystals - 50
        remaining_crystals = sender_prof["crystals"]

        gifted_card = _transfer_single_card(g_users, data["user_profiles"], s_key, p_key, card_id)
        save_data(data)
        return True, "선물 성공", gifted_card, remaining_crystals


# ==========================================
# 5. D-Day 계산, 은하수 게이지 및 음악 추천 보조 함수
# ==========================================
def get_dday_info(target_date_str):
    today = datetime.datetime.now(KST).date()
    target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
    diff = (target_date - today).days
    if diff > 0:
        return diff, f"D-{diff}"
    elif diff == 0:
        return 0, "D-Day"
    else:
        return diff, f"D+{abs(diff)}"


def format_dday_channel_name(name: str, date_str: str, emoji: str = "🌠"):
    _, dday_text = get_dday_info(date_str)
    clean_emoji = emoji.strip() if emoji and emoji.strip() else "🌠"
    return f"{clean_emoji}ㅣ{name} / {dday_text}"


def get_embed_color(diff_days):
    if 0 <= diff_days <= 3:
        return discord.Color.red()
    elif diff_days < 0:
        return discord.Color.dark_grey()
    return discord.Color.from_rgb(0, 204, 221)


def add_chunked_embed_fields(
    embed: discord.Embed,
    base_name: str,
    lines: list[str],
    empty_text: str = "없음",
    separator: str = "\n\n",
    max_chars: int = 950
):
    """
    디스코드 임베드 필드(field.value)의 1024자 제한(HTTPException 50035)을 초과하지 않도록
    줄 단위 항목들을 안전하게 분할하여 여러 필드로 자동 추가합니다.
    """
    if not lines:
        embed.add_field(name=base_name, value=empty_text, inline=False)
        return

    chunks = []
    current_chunk = []
    current_len = 0
    sep_len = len(separator)

    for line in lines:
        safe_line = line[:max_chars]
        add_len = len(safe_line) + (sep_len if current_chunk else 0)
        if current_chunk and (current_len + add_len > max_chars):
            chunks.append(separator.join(current_chunk))
            current_chunk = [safe_line]
            current_len = len(safe_line)
        else:
            current_chunk.append(safe_line)
            current_len += add_len

    if current_chunk:
        chunks.append(separator.join(current_chunk))

    total_chunks = len(chunks)
    for idx, ch_val in enumerate(chunks[:10], start=1):
        field_name = base_name if total_chunks == 1 else f"{base_name} ({idx}/{total_chunks})"
        embed.add_field(name=field_name, value=ch_val, inline=False)


def get_dday_color_theme(diff_days: int):
    """
    남은 기간(diff_days)에 따라 은하수 잔디 막대 그래프의 색상 블록, 헤드 아이콘,
    상태 배지, ANSI 컬러 코드 및 디스코드 임베드 RGB 색상을 동적으로 반환합니다.
    """
    if diff_days < 0:
        return {
            "fill_block": "⬜",
            "head_block": "✨",
            "empty_block": "🌑",
            "badge": "📦 경과 완료",
            "color_label": "SLATE (종료)",
            "ansi_code": "\u001b[0;37m",
            "rgb": (100, 116, 139)
        }
    elif diff_days == 0:
        return {
            "fill_block": "🟨",
            "head_block": "🌟",
            "empty_block": "🌑",
            "badge": "🌟 D-Day 당일!",
            "color_label": "GOLD (당일)",
            "ansi_code": "\u001b[1;33m",
            "rgb": (245, 158, 11)
        }
    elif diff_days <= 3:
        return {
            "fill_block": "🟥",
            "head_block": "☄️",
            "empty_block": "⬛",
            "badge": "🔥 임박 (3일 이내)",
            "color_label": "CRIMSON (임박)",
            "ansi_code": "\u001b[1;31m",
            "rgb": (244, 63, 94)
        }
    elif diff_days <= 7:
        return {
            "fill_block": "🟧",
            "head_block": "🌠",
            "empty_block": "⬛",
            "badge": "⚡ 주의 (1주 이내)",
            "color_label": "AMBER (1주내)",
            "ansi_code": "\u001b[0;33m",
            "rgb": (249, 115, 22)
        }
    elif diff_days <= 30:
        return {
            "fill_block": "🟦",
            "head_block": "🌠",
            "empty_block": "🌑",
            "badge": "🌌 순항 (1개월 이내)",
            "color_label": "CYAN (순항)",
            "ansi_code": "\u001b[1;36m",
            "rgb": (6, 182, 212)
        }
    else:
        return {
            "fill_block": "🟩",
            "head_block": "🌠",
            "empty_block": "🌑",
            "badge": "🌱 여유 (장기 일정)",
            "color_label": "EMERALD (여유)",
            "ansi_code": "\u001b[1;32m",
            "rgb": (16, 185, 129)
        }


def build_dday_galaxy_grass_bar(start_str: str, target_str: str, width: int = 12):
    """
    시작일(start_str)부터 목표일(target_str)까지의 진행률과 남은 기간(diff)을 분석해
    남은 기간에 따라 색상이 동적으로 변하는 '은하수 잔디 막대 그래프' 정보를 반환합니다.
    """
    today = datetime.datetime.now(KST).date()
    target = datetime.datetime.strptime(target_str, "%Y-%m-%d").date()
    try:
        start = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
    except Exception:
        start = today

    diff_days = (target - today).days
    # 시작일이 목표일과 같거나 목표일보다 미래로 잘못 잡혀 있는 경우, 최소 14일 또는 남은 기간 기준으로 보정하여 진행률 시각화
    if start >= target and diff_days > 0:
        start = target - datetime.timedelta(days=max(diff_days + 3, 14))

    total_days = max(1, (target - start).days)
    passed_days = max(0, (today - start).days)
    theme = get_dday_color_theme(diff_days)

    if diff_days == 0:
        percent = 100
        grass_bar = (theme["fill_block"] * (width - 1)) + theme["head_block"]
    elif diff_days < 0:
        percent = 100
        grass_bar = theme["fill_block"] * width
    else:
        raw_pct = (passed_days / total_days) * 100.0
        # 남은 기간에 따른 최소 시각적 채움 보정 (막대가 완전히 비어 보이지 않도록)
        if passed_days == 0 and diff_days <= 30:
            raw_pct = max(raw_pct, round(((30 - diff_days) / 30) * 85))
        percent = int(min(99, max(5 if diff_days <= 30 else 0, round(raw_pct))))
        filled_cnt = min(width - 1, max(0, round((percent / 100.0) * width)))
        empty_cnt = max(0, width - filled_cnt - 1)
        grass_bar = (theme["fill_block"] * filled_cnt) + theme["head_block"] + (theme["empty_block"] * empty_cnt)

    return {
        "diff_days": diff_days,
        "total_days": total_days,
        "passed_days": min(passed_days, total_days),
        "percent": percent,
        "grass_bar": grass_bar,
        "badge": theme["badge"],
        "color_label": theme["color_label"],
        "fill_block": theme["fill_block"],
        "ansi_code": theme["ansi_code"],
        "rgb": theme["rgb"],
        "formatted": f"{grass_bar} **`{percent}%`** · {theme['badge']}"
    }


def get_galaxy_progress_bar(start_str, target_str):
    """기존 호환용 은하수 진행률 바 — 남은 기간에 따라 색상이 변하는 은하수 잔디 막대 그래프로 반환"""
    info = build_dday_galaxy_grass_bar(start_str, target_str, width=10)
    return f"{info['grass_bar']} **{info['percent']}%** ({info['badge']})"


def build_dday_grass_board_summary(ddays_dict: dict):
    """
    등록된 모든 D-Day 일정을 '은하수 잔디 막대 그래프' 비교 보드 형태로 생성합니다.
    남은 기간에 따라 🟨(당일) / 🟥(임박 1~3일) / 🟧(주의 4~7일) / 🟦(순항 8~30일) / 🟩(여유 31일+) 색상이 변화합니다.
    """
    items = []
    counts = {"dday": 0, "urgent": 0, "soon": 0, "normal": 0, "relaxed": 0, "past": 0}

    for name, info in sorted(ddays_dict.items(), key=lambda x: x[1].get("date", "9999-12-31")):
        date_str = info.get("date", get_today_str())
        start_str = info.get("start_date", get_today_str())
        try:
            diff, dday_text = get_dday_info(date_str)
            bar_data = build_dday_galaxy_grass_bar(start_str, date_str, width=12)
        except Exception:
            continue

        if diff == 0:
            counts["dday"] += 1
        elif 1 <= diff <= 3:
            counts["urgent"] += 1
        elif 4 <= diff <= 7:
            counts["soon"] += 1
        elif 8 <= diff <= 30:
            counts["normal"] += 1
        elif diff > 30:
            counts["relaxed"] += 1
        else:
            counts["past"] += 1

        items.append({
            "name": name,
            "date": date_str,
            "start_date": start_str,
            "emoji": info.get("emoji", "🌠"),
            "repeat": bool(info.get("repeat", False)),
            "channel_id": info.get("channel_id"),
            "diff": diff,
            "dday_text": dday_text,
            **bar_data
        })

    return {
        "items": items,
        "counts": counts
    }


def get_timestamp_galaxy_bar(start_ms: int, end_ms: int):
    """밀리초(ms) 타임스탬프 기준 실시간 은하수 진행률 바 & 남은 시간 계산 (/이벤트 전용)"""
    now_ms = int(time.time() * 1000)
    if now_ms < start_ms:
        rem_sec = max(0, (start_ms - now_ms) // 1000)
        d, rem = divmod(rem_sec, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        return "🌠" + ("🌑" * 9) + f" **0%** (시작까지 `{d}일 {h}시간 {m}분`)"
    if now_ms >= end_ms or end_ms <= start_ms:
        return "✨" * 10 + " **100%** (종료됨)"

    total_ms = end_ms - start_ms
    passed_ms = now_ms - start_ms
    percent = min(100.0, max(0.0, (passed_ms / total_ms) * 100))
    filled_count = min(9, int(percent // 10))
    empty_count = max(0, 10 - filled_count - 1)
    bar = ("🌌" * filled_count) + "🌠" + ("🌑" * empty_count)

    rem_sec = max(0, (end_ms - now_ms) // 1000)
    d, rem = divmod(rem_sec, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{bar} **{int(percent)}%** (남은 시간: `{d}일 {h}시간 {m}분`)"


def get_spotify_access_token():
    if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
        return None, "SPOTIPY_CLIENT_ID 또는 SECRET 값이 비어 있습니다."
    try:
        res = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET),
            timeout=8
        )
        if res.status_code != 200:
            return None, f"토큰 발급 실패 (HTTP {res.status_code})"
        return res.json().get("access_token"), None
    except Exception as e:
        return None, f"토큰 요청 오류: {e}"


def fetch_spotify_playlist_fallback(playlist_id):
    try:
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(embed_url, headers=headers, timeout=8)
        if res.status_code != 200:
            return None, "플레이리스트에 접근할 수 없습니다."
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            return None, "플레이리스트 데이터를 읽을 수 없습니다."
        next_data = json.loads(match.group(1))
        entity = next_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        track_list = entity.get("trackList", [])
        if not track_list:
            return None, "플레이리스트에 곡이 없거나 비공개 상태입니다."
        chosen = random.choice(track_list)
        uri = chosen.get("uri", "")
        track_id = uri.split(":")[-1] if ":" in uri else ""
        track_url = f"https://open.spotify.com/track/{track_id}" if track_id else f"https://open.spotify.com/playlist/{playlist_id}"
        visual = entity.get("visualIdentity", {}).get("image", [])
        cover_img = visual[0].get("url") if visual and isinstance(visual, list) else None
        return {
            "platform": "Spotify",
            "title": chosen.get("title", "제목 없음"),
            "artist": chosen.get("subtitle", "알 수 없는 아티스트"),
            "url": track_url,
            "image": cover_img
        }, None
    except Exception as e:
        return None, f"플레이리스트 추출 실패: {e}"


def fetch_spotify_track(genre=None, artist=None, playlist_url=None):
    token, err = get_spotify_access_token()
    if err or not token:
        return None, f"Spotify 인증 오류: {err}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        if playlist_url:
            match = re.search(r"playlist/([a-zA-Z0-9]+)", playlist_url)
            if not match:
                return None, "올바른 스포티파이 플레이리스트 링크가 아닙니다."
            playlist_id = match.group(1)
            api_url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
            res = requests.get(api_url, headers=headers, params={"market": "KR", "limit": 50}, timeout=8)
            if res.status_code != 200:
                return fetch_spotify_playlist_fallback(playlist_id)
            items = res.json().get("items", [])
            tracks = [item["track"] for item in items if item and item.get("track") and item["track"].get("id")]
            if not tracks:
                return fetch_spotify_playlist_fallback(playlist_id)
            track = random.choice(tracks)
        else:
            query_parts = []
            if artist and artist.strip():
                query_parts.append(f"artist:{artist.strip()}")
            if genre and genre.strip():
                query_parts.append(f"genre:{genre.strip()}")
            query = " ".join(query_parts) if query_parts else get_mood_keyword()
            offset = random.randint(0, 10) if query_parts else random.randint(0, 30)
            search_url = "https://api.spotify.com/v1/search"
            res = requests.get(search_url, headers=headers, params={"q": query, "type": "track", "market": "KR", "offset": offset}, timeout=8)
            if res.status_code != 200:
                res = requests.get(search_url, headers=headers, params={"q": query, "type": "track", "market": "KR"}, timeout=8)
            if res.status_code != 200:
                return None, f"Spotify API 검색 실패 (HTTP {res.status_code})"
            tracks = res.json().get("tracks", {}).get("items", [])
            if not tracks and offset > 0:
                res = requests.get(search_url, headers=headers, params={"q": query, "type": "track", "market": "KR"}, timeout=8)
                tracks = res.json().get("tracks", {}).get("items", [])
            if not tracks:
                return None, "조건에 맞는 스포티파이 곡을 찾지 못했습니다."
            track = random.choice(tracks)

        images = track.get("album", {}).get("images", [])
        return {
            "platform": "Spotify",
            "title": track.get("name", "제목 없음"),
            "artist": ", ".join([a["name"] for a in track.get("artists", [])]),
            "url": track.get("external_urls", {}).get("spotify", "https://open.spotify.com"),
            "image": images[0]["url"] if images else None
        }, None
    except Exception as e:
        return None, f"Spotify 검색 오류: {e}"


class _QuietYdlLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def fetch_soundcloud_track_sync(genre=None, artist=None, playlist_url=None):
    ydl_flat_opts = {"extract_flat": True, "quiet": True, "no_warnings": True, "nocheckcertificate": True, "logger": _QuietYdlLogger()}
    try:
        with yt_dlp.YoutubeDL(ydl_flat_opts) as ydl:
            if playlist_url:
                info = ydl.extract_info(playlist_url, download=False)
                entries = info.get("entries", [])
                if not entries:
                    return None, "사운드클라우드 플레이리스트에서 곡을 찾을 수 없습니다."
                chosen = random.choice(entries)
            else:
                search_terms = [t.strip() for t in [artist, genre] if t and t.strip()]
                query = " ".join(search_terms) if search_terms else get_mood_keyword()
                info = ydl.extract_info(f"scsearch25:{query}", download=False)
                entries = info.get("entries", [])
                if not entries:
                    return None, "조건에 맞는 사운드클라우드 곡을 찾지 못했습니다."
                chosen = random.choice(entries)

        track_url = chosen.get("url") or chosen.get("webpage_url")
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "nocheckcertificate": True, "logger": _QuietYdlLogger()}) as ydl_detail:
            detail = ydl_detail.extract_info(track_url, download=False)

        return {
            "platform": "SoundCloud",
            "title": detail.get("title", chosen.get("title", "제목 없음")),
            "artist": detail.get("uploader", "알 수 없는 아티스트"),
            "url": detail.get("webpage_url", track_url),
            "image": detail.get("thumbnail")
        }, None
    except Exception as e:
        return None, f"SoundCloud 검색 오류: {e}"


async def get_recommended_music(prefs):
    playlist_url = prefs.get("playlist_url")
    genre = prefs.get("genre")
    artist = prefs.get("artist")
    platform = prefs.get("platform", "all")

    if playlist_url:
        if "spotify.com" in playlist_url:
            return await asyncio.to_thread(fetch_spotify_track, genre, artist, playlist_url)
        elif "soundcloud.com" in playlist_url:
            return await asyncio.to_thread(fetch_soundcloud_track_sync, genre, artist, playlist_url)
        elif "youtube.com" in playlist_url or "youtu.be" in playlist_url:
            meta, tracks, err = await extract_playlist_from_url(playlist_url, max_tracks=50)
            if err or not tracks:
                return None, f"유튜브 플레이리스트 추출 실패: {err or '곡 없음'}"
            chosen = random.choice(tracks)
            return {
                "platform": "YouTube",
                "title": chosen.get("title", "제목 없음"),
                "artist": chosen.get("artist", "알 수 없는 아티스트"),
                "url": chosen.get("url", playlist_url),
                "image": chosen.get("image")
            }, None
        else:
            return None, "지원하지 않는 플레이리스트 링크입니다."

    chosen_platform = random.choice(["spotify", "soundcloud"]) if platform == "all" else platform
    if chosen_platform == "spotify":
        track_info, err = await asyncio.to_thread(fetch_spotify_track, genre, artist, None)
        if err and platform == "all":
            return await asyncio.to_thread(fetch_soundcloud_track_sync, genre, artist, None)
        return track_info, err
    else:
        return await asyncio.to_thread(fetch_soundcloud_track_sync, genre, artist, None)


def clean_youtube_url(url: str) -> str:
    """
    유튜브 URL에서 불필요한 플레이리스트(&list=...), 라디오(&start_radio=...), 인덱스(&index=...),
    재생시간(&t=...) 파라미터를 완전히 제거하고 단일 영상의 순수 고유 링크(https://www.youtube.com/watch?v={id})로 정규화합니다.
    단일 영상 ID가 없는 순수 플레이리스트 링크는 https://www.youtube.com/playlist?list={id}로 정규화합니다.
    """
    if not isinstance(url, str):
        return ""
    raw = url.strip()
    m_url = re.search(r"https?://[^\s<>\"']+", raw)
    if m_url:
        raw = m_url.group(0)
    low = raw.lower()
    if not ("youtube.com" in low or "youtu.be" in low):
        return raw

    # 1) youtu.be/<id>
    m_short = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", raw)
    if m_short:
        return f"https://www.youtube.com/watch?v={m_short.group(1)}"

    # 2) youtube.com/shorts/<id>
    m_shorts = re.search(r"/shorts/([a-zA-Z0-9_-]{11})", raw)
    if m_shorts:
        return f"https://www.youtube.com/watch?v={m_shorts.group(1)}"

    parsed = urllib.parse.urlparse(raw)
    qs = urllib.parse.parse_qs(parsed.query)

    # 3) watch?v=<id>
    v_ids = qs.get("v")
    if v_ids and len(v_ids[0]) == 11:
        return f"https://www.youtube.com/watch?v={v_ids[0]}"

    # 4) playlist only (영상 ID 없이 list 파라미터만 있는 경우)
    list_ids = qs.get("list")
    if list_ids:
        return f"https://www.youtube.com/playlist?list={list_ids[0]}"

    return raw


def resolve_playlist_track_sync(raw_query_or_url: str, artist_hint: str = "", preferred_platform: str = "YouTube", memo: str = "") -> dict:
    """
    유저가 입력한 곡 제목/아티스트 검색어 또는 URL(유튜브·스포티파이·사운드클라우드)을 분석하여
    선택한 플랫폼(YouTube / Spotify / SoundCloud)의 실제 곡 정보와 3사 바로가기 링크를 생성합니다.
    """
    raw = (raw_query_or_url or "").strip()
    artist_in = (artist_hint or "").strip()
    plat = preferred_platform if preferred_platform in PLAYLIST_PLATFORMS else "YouTube"

    is_url = raw.startswith("http://") or raw.startswith("https://")
    if is_url:
        low_url = raw.lower()
        if "spotify.com" in low_url:
            plat = "Spotify"
        elif "soundcloud.com" in low_url:
            plat = "SoundCloud"
        elif "youtube.com" in low_url or "youtu.be" in low_url:
            plat = "YouTube"
            raw = clean_youtube_url(raw)

    title = raw
    artist = artist_in or "아티스트 미지정"
    direct_url = raw if is_url else ""
    image_url = None

    # "아티스트 - 곡제목" 형태 자동 분리 (URL이 아닐 때)
    if not is_url and not artist_in and " - " in raw:
        parts = raw.split(" - ", 1)
        if parts[0].strip() and parts[1].strip():
            artist = parts[0].strip()
            title = parts[1].strip()

    search_query = f"{artist} {title}".strip() if (not is_url and artist != "아티스트 미지정") else title

    # 1) Spotify 검색 또는 트랙 URL 조회 시도
    if plat == "Spotify":
        try:
            token, err = get_spotify_access_token()
            if token and not err:
                headers = {"Authorization": f"Bearer {token}"}
                if is_url and "track/" in raw:
                    m = re.search(r"track/([a-zA-Z0-9]+)", raw)
                    if m:
                        tid = m.group(1)
                        res = requests.get(f"https://api.spotify.com/v1/tracks/{tid}", headers=headers, params={"market": "KR"}, timeout=5)
                        if res.status_code == 200:
                            t_data = res.json()
                            title = t_data.get("name") or title
                            artist = ", ".join([a["name"] for a in t_data.get("artists", [])]) or artist
                            direct_url = t_data.get("external_urls", {}).get("spotify") or raw
                            imgs = t_data.get("album", {}).get("images", [])
                            if imgs:
                                image_url = imgs[0].get("url")
                elif not is_url:
                    res = requests.get(
                        "https://api.spotify.com/v1/search",
                        headers=headers,
                        params={"q": search_query, "type": "track", "market": "KR", "limit": 1},
                        timeout=5
                    )
                    if res.status_code == 200:
                        items = res.json().get("tracks", {}).get("items", [])
                        if items:
                            t_data = items[0]
                            title = t_data.get("name") or title
                            artist = ", ".join([a["name"] for a in t_data.get("artists", [])]) or artist
                            direct_url = t_data.get("external_urls", {}).get("spotify") or direct_url
                            imgs = t_data.get("album", {}).get("images", [])
                            if imgs:
                                image_url = imgs[0].get("url")
        except Exception:
            pass

    # 2) YouTube / SoundCloud 검색 또는 URL 메타데이터 추출 시도 (yt_dlp)
    elif plat in ("YouTube", "SoundCloud"):
        try:
            ydl_opts = {
                "extract_flat": True,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "socket_timeout": 5,
                "logger": _QuietYdlLogger(),
            }
            target_q = raw if is_url else (f"ytsearch1:{search_query}" if plat == "YouTube" else f"scsearch1:{search_query}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_q, download=False)
                entry = None
                if isinstance(info, dict):
                    if "entries" in info and info["entries"]:
                        entry = info["entries"][0]
                    elif info.get("title"):
                        entry = info
                    if entry:
                        ext_title = entry.get("title")
                        ext_artist = entry.get("uploader") or entry.get("channel") or entry.get("artist")
                        ext_url = entry.get("webpage_url") or entry.get("url")
                        if is_url:
                            if ext_title:
                                title = ext_title
                            if ext_artist and (artist == "아티스트 미지정" or not artist_in):
                                artist = ext_artist
                        else:
                            # 사용자가 직접 입력한 곡 제목과 아티스트명을 최우선 보존
                            if ext_artist and artist in ("아티스트 미지정", "-", ""):
                                artist = ext_artist
                        if entry.get("id") and plat == "YouTube":
                            direct_url = f"https://www.youtube.com/watch?v={entry['id']}"
                        elif ext_url and str(ext_url).startswith("http"):
                            direct_url = clean_youtube_url(ext_url) if plat == "YouTube" else ext_url
                        thumbs = entry.get("thumbnails")
                        if isinstance(thumbs, list) and thumbs:
                            image_url = thumbs[-1].get("url")
                        elif entry.get("thumbnail"):
                            image_url = entry.get("thumbnail")
        except Exception:
            pass

    if is_url and title == raw:
        title = f"{plat} 직접 등록 트랙"

    urls = build_platform_search_urls(title, artist)
    yt_url = direct_url if (plat == "YouTube" and direct_url.startswith("http")) else urls["yt_url"]
    sp_url = direct_url if (plat == "Spotify" and direct_url.startswith("http")) else urls["sp_url"]
    sc_url = direct_url if (plat == "SoundCloud" and direct_url.startswith("http")) else urls["sc_url"]
    main_url = direct_url if direct_url.startswith("http") else (yt_url if plat == "YouTube" else (sp_url if plat == "Spotify" else sc_url))

    return normalize_playlist_track({
        "id": f"trk_{int(time.time())}_{random.randint(100, 999)}",
        "title": title,
        "artist": artist,
        "platform": plat,
        "url": main_url,
        "yt_url": yt_url,
        "sp_url": sp_url,
        "sc_url": sc_url,
        "image": image_url,
        "memo": memo,
        "added_at": get_now_datetime_str(),
    })


async def resolve_playlist_track(raw_query_or_url: str, artist_hint: str = "", preferred_platform: str = "YouTube", memo: str = "") -> dict:
    return await asyncio.to_thread(resolve_playlist_track_sync, raw_query_or_url, artist_hint, preferred_platform, memo)


def is_playlist_url(url: str, allow_watch_with_list: bool = True) -> tuple[bool, str]:
    """
    주어진 문자열이 유튜브, 스포티파이, 사운드클라우드의 플레이리스트/앨범 URL인지 판별합니다.
    - allow_watch_with_list: True이면 watch?v=...&list=PL... 형태도 플레이리스트로 판별 (가져오기 기능용)
      False이면 watch?v=... 형태는 단일 곡으로 취급하고 순수 playlist 링크만 플레이리스트로 판별 (곡 추가 모달용)
    반환: (is_playlist: bool, platform: str)
    """
    if not isinstance(url, str):
        return False, ""
    raw = url.strip()
    m_url = re.search(r"https?://[^\s<>\"']+", raw)
    if m_url:
        raw = m_url.group(0)
    if not (raw.startswith("http://") or raw.startswith("https://")):
        return False, ""

    low = raw.lower()

    # 1) Spotify
    if "open.spotify.com" in low or "spotify.com" in low:
        if "/playlist/" in low or "/album/" in low:
            return True, "Spotify"

    # 2) YouTube / YouTube Music
    if "youtube.com" in low or "youtu.be" in low:
        parsed = urllib.parse.urlparse(raw)
        qs = urllib.parse.parse_qs(parsed.query)
        v_ids = qs.get("v")
        m_short = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", raw)
        m_shorts = re.search(r"/shorts/([a-zA-Z0-9_-]{11})", raw)
        has_video_id = bool(v_ids or m_short or m_shorts)

        list_ids = qs.get("list", [])
        list_id = list_ids[0] if list_ids else ""

        # 라디오 / 믹스(RD...) 또는 내역/좋아요 목록(LL, UL)은 플레이리스트로 취급하지 않음 (개인화 임시 목록)
        if list_id and (list_id.startswith("RD") or list_id.startswith("UL") or list_id.startswith("LL")):
            return False, ""

        if "/playlist" in low or (list_id and not has_video_id):
            return True, "YouTube"

        if has_video_id and list_id:
            return (True, "YouTube") if allow_watch_with_list else (False, "")

    # 3) SoundCloud
    if "soundcloud.com" in low:
        if "/sets/" in low:
            return True, "SoundCloud"

    return False, ""


def extract_playlist_from_url_sync(url: str, max_tracks: int = 100) -> tuple[dict | None, list[dict], str | None]:
    """
    유튜브, 스포티파이, 사운드클라우드 플레이리스트 URL로부터
    플레이리스트 메타데이터(이름, 설명, 썸네일, 플랫폼)와 수록곡 목록(최대 max_tracks)을 일괄 추출합니다.
    반환값: (playlist_meta, tracks_list, error_msg)
    """
    is_pl, plat = is_playlist_url(url)
    if not is_pl:
        return None, [], "지원하는 플레이리스트 링크(YouTube, Spotify, SoundCloud)가 아닙니다."

    raw_url = url.strip()
    m_url = re.search(r"https?://[^\s<>\"']+", raw_url)
    if m_url:
        raw_url = m_url.group(0)
    now_str = get_now_datetime_str()
    tracks: list[dict] = []

    # ==========================================
    # 1. Spotify 플레이리스트 / 앨범 추출
    # ==========================================
    if plat == "Spotify":
        try:
            m_pl = re.search(r"playlist/([a-zA-Z0-9]+)", raw_url)
            m_alb = re.search(r"album/([a-zA-Z0-9]+)", raw_url)

            if m_pl:
                pid = m_pl.group(1)
                embed_url = f"https://open.spotify.com/embed/playlist/{pid}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                res = requests.get(embed_url, headers=headers, timeout=8)
                if res.status_code == 200:
                    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
                    if match:
                        next_data = json.loads(match.group(1))
                        entity = next_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                        pl_title = str(entity.get("title") or entity.get("name") or "Spotify 플레이리스트").strip()[:50]
                        pl_desc = str(entity.get("subtitle") or entity.get("description") or "Spotify에서 가져온 감성 플레이리스트 ✨").strip()[:120]
                        visual = entity.get("visualIdentity", {}).get("image", [])
                        cover_img = visual[0].get("url") if (visual and isinstance(visual, list)) else None
                        track_list = entity.get("trackList", [])

                        for idx, item in enumerate(track_list[:max_tracks], start=1):
                            t_title = str(item.get("title") or "제목 없음").strip()[:100]
                            t_artist = str(item.get("subtitle") or "알 수 없는 아티스트").strip()[:80]
                            uri = item.get("uri", "")
                            tid = uri.split(":")[-1] if ":" in uri else ""
                            t_url = f"https://open.spotify.com/track/{tid}" if tid else f"https://open.spotify.com/playlist/{pid}"
                            urls = build_platform_search_urls(t_title, t_artist)
                            trk = normalize_playlist_track({
                                "id": f"trk_{int(time.time())}_{idx}_{random.randint(100, 999)}",
                                "title": t_title,
                                "artist": t_artist,
                                "platform": "Spotify",
                                "url": t_url,
                                "yt_url": urls["yt_url"],
                                "sp_url": t_url,
                                "sc_url": urls["sc_url"],
                                "image": cover_img,
                                "memo": f"Spotify '{pl_title}' 플리에서 가져옴",
                                "added_at": now_str,
                            })
                            tracks.append(trk)

                        meta = {
                            "title": pl_title,
                            "desc": pl_desc,
                            "emoji": "🟢",
                            "platform": "Spotify",
                            "image": cover_img,
                            "source_url": raw_url,
                            "total_count": len(track_list)
                        }
                        return meta, tracks, None

            elif m_alb:
                aid = m_alb.group(1)
                embed_url = f"https://open.spotify.com/embed/album/{aid}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                res = requests.get(embed_url, headers=headers, timeout=8)
                if res.status_code == 200:
                    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
                    if match:
                        next_data = json.loads(match.group(1))
                        entity = next_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                        pl_title = str(entity.get("title") or entity.get("name") or "Spotify 앨범").strip()[:50]
                        alb_artist = str(entity.get("subtitle") or "알 수 없는 아티스트").strip()[:80]
                        pl_desc = f"{alb_artist}의 앨범 수록곡 리스트 ✨"[:120]
                        visual = entity.get("visualIdentity", {}).get("image", [])
                        cover_img = visual[0].get("url") if (visual and isinstance(visual, list)) else None
                        track_list = entity.get("trackList", [])

                        for idx, item in enumerate(track_list[:max_tracks], start=1):
                            t_title = str(item.get("title") or "제목 없음").strip()[:100]
                            t_artist = str(item.get("subtitle") or alb_artist).strip()[:80]
                            uri = item.get("uri", "")
                            tid = uri.split(":")[-1] if ":" in uri else ""
                            t_url = f"https://open.spotify.com/track/{tid}" if tid else f"https://open.spotify.com/album/{aid}"
                            urls = build_platform_search_urls(t_title, t_artist)
                            trk = normalize_playlist_track({
                                "id": f"trk_{int(time.time())}_{idx}_{random.randint(100, 999)}",
                                "title": t_title,
                                "artist": t_artist,
                                "platform": "Spotify",
                                "url": t_url,
                                "yt_url": urls["yt_url"],
                                "sp_url": t_url,
                                "sc_url": urls["sc_url"],
                                "image": cover_img,
                                "memo": f"Spotify '{pl_title}' 앨범에서 가져옴",
                                "added_at": now_str,
                            })
                            tracks.append(trk)

                        meta = {
                            "title": pl_title,
                            "desc": pl_desc,
                            "emoji": "🟢",
                            "platform": "Spotify",
                            "image": cover_img,
                            "source_url": raw_url,
                            "total_count": len(track_list)
                        }
                        return meta, tracks, None
        except Exception as e:
            return None, [], f"Spotify 플레이리스트를 불러오는 중 오류가 발생했습니다: {e}"

    # ==========================================
    # 2. YouTube & SoundCloud 플레이리스트 추출 (yt-dlp)
    # ==========================================
    fetch_target_url = raw_url
    if plat == "YouTube":
        # list 파라미터가 있을 경우 표준 playlist 링크로 정규화
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        list_id = qs.get("list", [None])[0]
        if list_id:
            if list_id.startswith("RD") or list_id.startswith("UL") or list_id.startswith("LL"):
                # 유튜브 믹스/라디오/좋아요한 영상은 외부 yt-dlp 추출이 불가능한 임시 목록
                v_ids = qs.get("v")
                if v_ids:
                    fetch_target_url = f"https://www.youtube.com/watch?v={v_ids[0]}"
                else:
                    return None, [], "유튜브 믹스/라디오(&list=RD...)는 개인화 임시 목록이어서 플레이리스트 일괄 추출을 지원하지 않습니다. 정규 플레이리스트(&list=PL...) 링크를 사용해 주세요."
            else:
                fetch_target_url = f"https://www.youtube.com/playlist?list={list_id}"

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "socket_timeout": 8,
        "ignoreerrors": True,
        "logger": _QuietYdlLogger(),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(fetch_target_url, download=False)
            if not info or not isinstance(info, dict):
                # 정규화된 URL 실패 시 원본 URL로 재시도
                info = ydl.extract_info(raw_url, download=False)

            if not info or not isinstance(info, dict):
                return None, [], "플레이리스트 정보를 불러올 수 없습니다. 링크가 비공개이거나 삭제되었는지 확인해 주세요."

            raw_entries = info.get("entries")
            if raw_entries is None and info.get("title"):
                # 단일 영상인 경우
                raw_entries = [info]

            entries = [e for e in (raw_entries or []) if isinstance(e, dict)]
            if not entries:
                return None, [], "플레이리스트에 수록된 곡이 없거나 접근할 수 없습니다."

            pl_title = str(info.get("title") or f"{plat} 플레이리스트").strip()[:50]
            uploader = str(info.get("uploader") or info.get("channel") or plat).strip()
            pl_desc = str(info.get("description") or f"{plat}에서 가져온 플레이리스트 ({uploader})").strip()[:120]
            pl_emoji = "📺" if plat == "YouTube" else "☁️"

            # 플레이리스트 썸네일
            pl_image = None
            thumbs = info.get("thumbnails")
            if isinstance(thumbs, list) and thumbs:
                pl_image = thumbs[-1].get("url")
            elif info.get("thumbnail"):
                pl_image = info.get("thumbnail")

            for entry in entries:
                if len(tracks) >= max_tracks:
                    break

                t_id = entry.get("id")
                t_title = str(entry.get("title") or "").strip()[:100]
                t_title_low = t_title.lower()

                # 삭제되거나 비공개 처리된 영상, 유효하지 않은 항목은 자동 건너뛰기
                if plat == "YouTube":
                    if not t_id or not t_title or t_title_low in (
                        "[deleted video]", "[private video]", "deleted video", "private video", "none", "null"
                    ):
                        continue
                elif plat == "SoundCloud":
                    cand_sc = str(entry.get("webpage_url") or entry.get("url") or "").strip()
                    if not cand_sc.startswith("http") or not t_title:
                        continue

                t_title = t_title or f"트랙 #{len(tracks) + 1}"
                t_artist = str(entry.get("uploader") or entry.get("channel") or entry.get("artist") or uploader).strip()[:80]

                if plat == "YouTube":
                    t_url = f"https://www.youtube.com/watch?v={t_id}"
                elif plat == "SoundCloud":
                    cand_sc = str(entry.get("webpage_url") or entry.get("url") or "").strip()
                    t_url = cand_sc if cand_sc.startswith("http") else ""
                else:
                    t_url = ""

                t_image = None
                e_thumbs = entry.get("thumbnails")
                if isinstance(e_thumbs, list) and e_thumbs:
                    t_image = e_thumbs[-1].get("url")
                elif entry.get("thumbnail"):
                    t_image = entry.get("thumbnail")

                urls = build_platform_search_urls(t_title, t_artist)
                yt_u = t_url if (plat == "YouTube" and t_url.startswith("http")) else urls["yt_url"]
                sp_u = urls["sp_url"]
                sc_u = t_url if (plat == "SoundCloud" and t_url.startswith("http")) else urls["sc_url"]
                main_u = t_url if t_url.startswith("http") else (yt_u if plat == "YouTube" else (sp_u if plat == "Spotify" else sc_u))

                trk = normalize_playlist_track({
                    "id": f"trk_{int(time.time())}_{len(tracks) + 1}_{random.randint(100, 999)}",
                    "title": t_title,
                    "artist": t_artist,
                    "platform": plat,
                    "url": main_u,
                    "yt_url": yt_u,
                    "sp_url": sp_u,
                    "sc_url": sc_u,
                    "image": t_image or pl_image,
                    "memo": f"{plat} '{pl_title}' 플리에서 가져옴",
                    "added_at": now_str,
                })
                tracks.append(trk)

            meta = {
                "title": pl_title,
                "desc": pl_desc,
                "emoji": pl_emoji,
                "platform": plat,
                "image": pl_image,
                "source_url": raw_url,
                "total_count": len(entries)
            }
            return meta, tracks, None

    except Exception as e:
        return None, [], f"{plat} 플레이리스트 추출 중 오류가 발생했습니다: {e}"


async def extract_playlist_from_url(url: str, max_tracks: int = 100) -> tuple[dict | None, list[dict], str | None]:
    return await asyncio.to_thread(extract_playlist_from_url_sync, url, max_tracks)


def import_playlist_into_profile_sync(
    profile: dict,
    owner_display_name: str,
    meta: dict,
    tracks: list[dict],
    target_pl_id: Optional[str] = None,
    custom_name: Optional[str] = None,
    skip_duplicates: bool = True
) -> tuple[dict, int, str]:
    """
    유저 프로필 데이터에 추출된 플레이리스트 메타/트랙을 반영합니다.
    - target_pl_id가 제공되면: 기존 해당 플레이리스트에 곡 일괄 추가 (최대 100곡)
    - target_pl_id가 없으면: 새 플레이리스트 생성 (유저당 최대 20개)
    - skip_duplicates: 이미 수록된 중복 곡 건너뛰기 여부 (기본 True)
    반환: (updated_playlist, added_count, action_message)
    """
    pls = ensure_user_playlists(profile, owner_display_name)
    today_s = get_today_str()

    if target_pl_id:
        target = next((p for p in pls if p["id"] == target_pl_id), pls[0])
        curr_tracks = target.setdefault("tracks", [])

        # 기존 곡들의 키(정규화된 제목+아티스트, URL) 집합
        existing_keys = set()
        for t in curr_tracks:
            t_u = str(t.get("url") or "").strip().lower()
            if t_u:
                existing_keys.add(t_u)
            existing_keys.add((str(t.get("title", "")).strip().lower(), str(t.get("artist", "")).strip().lower()))

        added = 0
        skipped_dup = 0
        for trk in tracks:
            if len(curr_tracks) >= 100:
                break
            trk_u = str(trk.get("url") or "").strip().lower()
            trk_key = (str(trk.get("title", "")).strip().lower(), str(trk.get("artist", "")).strip().lower())
            if skip_duplicates and (trk_u in existing_keys or trk_key in existing_keys):
                skipped_dup += 1
                continue
            curr_tracks.append(trk)
            if trk_u:
                existing_keys.add(trk_u)
            existing_keys.add(trk_key)
            added += 1

        target["updated_at"] = today_s
        dup_text = f" (중복 {skipped_dup}곡 제외)" if skipped_dup > 0 else ""
        return target, added, f"기존 **`{target['emoji']} {target['name']}`**에 **{added}곡**을 일괄 추가했습니다.{dup_text}"

    if len(pls) >= 20:
        raise ValueError("플레이리스트는 1인당 최대 20개까지만 생성할 수 있습니다.")

    clean_name = (custom_name or meta.get("title") or "새 플레이리스트").strip()[:50]
    clean_desc = (meta.get("desc") or "플레이리스트 링크에서 가져온 컬렉션 ✨").strip()[:120]
    clean_emoji = meta.get("emoji") or "🎧"
    clean_plat = meta.get("platform") or "YouTube"

    # 새 플리 내부 중복 정리 (최대 100곡)
    seen_keys = set()
    capped_tracks = []
    skipped_dup = 0
    for trk in tracks:
        if len(capped_tracks) >= 100:
            break
        trk_u = str(trk.get("url") or "").strip().lower()
        trk_key = (str(trk.get("title", "")).strip().lower(), str(trk.get("artist", "")).strip().lower())
        if skip_duplicates and (trk_u in seen_keys or trk_key in seen_keys):
            skipped_dup += 1
            continue
        capped_tracks.append(trk)
        if trk_u:
            seen_keys.add(trk_u)
        seen_keys.add(trk_key)

    dup_text = f" (중복 {skipped_dup}곡 제외)" if skipped_dup > 0 else ""

    # 기본 생성된 빈 대표 플레이리스트만 있는 경우, 해당 플레이리스트를 즉시 갱신
    if len(pls) == 1 and pls[0].get("id") == "pl_default" and len(pls[0].get("tracks", [])) == 0:
        target_pl = pls[0]
        target_pl["name"] = clean_name
        target_pl["desc"] = clean_desc
        target_pl["emoji"] = clean_emoji
        target_pl["platform"] = clean_plat
        target_pl["tracks"] = capped_tracks
        target_pl["updated_at"] = today_s
        return target_pl, len(capped_tracks), f"플레이리스트 **`{clean_emoji} {clean_name}`**에 **{len(capped_tracks)}곡**을 담았습니다.{dup_text}"

    new_id = f"pl_{int(time.time())}_{random.randint(100, 999)}"
    new_pl = {
        "id": new_id,
        "name": clean_name,
        "desc": clean_desc,
        "emoji": clean_emoji,
        "platform": clean_plat,
        "tracks": capped_tracks,
        "likes": [],
        "share_count": 0,
        "created_at": today_s,
        "updated_at": today_s,
    }
    pls.append(new_pl)
    return new_pl, len(capped_tracks), f"새 플레이리스트 **`{clean_emoji} {clean_name}`**을(를) 생성하고 **{len(capped_tracks)}곡**을 담았습니다.{dup_text}"


async def user_playlist_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """유저가 만든 플레이리스트 목록을 실시간 자동완성"""
    data = get_cached_data()
    u_key = str(interaction.user.id)
    prof = data.get("user_profiles", {}).get(u_key, {})
    pls = prof.get("playlists", [])
    if not isinstance(pls, list) or not pls:
        return [app_commands.Choice(name="🎧 나만의 대표 플레이리스트 (기본)", value="pl_default")]

    choices = []
    for pl in pls:
        if not isinstance(pl, dict):
            continue
        pid = str(pl.get("id", "pl_default"))
        pname = str(pl.get("name", "플레이리스트"))
        emoji = str(pl.get("emoji", "🎧"))
        plat = str(pl.get("platform", "YouTube"))
        cnt = len(pl.get("tracks", [])) if isinstance(pl.get("tracks"), list) else 0
        label = f"{emoji} {pname} [{plat} · {cnt}곡]"[:95]
        if not current or current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=pid))
        if len(choices) >= 25:
            break
    return choices


async def user_playlist_track_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """유저가 선택한 플레이리스트 내의 수록곡 목록을 실시간 자동완성"""
    data = get_cached_data()
    u_key = str(interaction.user.id)
    prof = data.get("user_profiles", {}).get(u_key, {})
    pls = prof.get("playlists", [])
    if not isinstance(pls, list) or not pls:
        return []

    pl_target = getattr(interaction.namespace, "플리선택", None)
    target_pl = None
    if pl_target:
        target_pl = next((p for p in pls if str(p.get("id")) == str(pl_target) or str(p.get("name")) == str(pl_target)), None)
    if not target_pl:
        target_pl = pls[0]

    tracks = target_pl.get("tracks", []) if isinstance(target_pl, dict) else []
    choices = []
    for idx, t in enumerate(tracks, start=1):
        if not isinstance(t, dict):
            continue
        title = str(t.get("title", "제목 없음")).strip()
        artist = str(t.get("artist", "-")).strip()
        t_id = str(t.get("id") or idx)
        label = f"#{idx:02d}. {title} — {artist}"[:95]
        if not current or current.lower() in label.lower() or current.strip() == str(idx):
            choices.append(app_commands.Choice(name=label, value=t_id))
        if len(choices) >= 25:
            break
    return choices


def ensure_opus_loaded() -> bool:
    """디스코드 음성 전송을 위한 libopus 라이브러리가 로드되어 있는지 확인하고 로드합니다."""
    try:
        import discord.opus
        if discord.opus.is_loaded():
            return True
        for lib in ("libopus.so.0", "libopus.so", "/lib/x86_64-linux-gnu/libopus.so.0", "/usr/lib/x86_64-linux-gnu/libopus.so.0", "opus"):
            try:
                discord.opus.load_opus(lib)
                if discord.opus.is_loaded():
                    return True
            except Exception:
                continue
        try:
            discord.opus._load_default()
        except Exception:
            pass
        return discord.opus.is_loaded()
    except Exception:
        return False



def get_ffmpeg_executable() -> str:
    """시스템 ffmpeg 또는 imageio-ffmpeg 바이너리 경로를 안전하게 반환"""
    import shutil
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def resolve_voice_stream_sync(track: dict) -> tuple[dict | None, str | None]:
    """
    플레이리스트 트랙 객체(유튜브 / 스포티파이 / 사운드클라우드)로부터
    디스코드 음성채널에서 즉시 재생 가능한 실제 오디오 스트림 URL(stream_url)과 메타데이터를 추출합니다.
    - 유튜브/사운드클라우드 직접 링크: 해당 링크에서 순수 영상 URL 추출 (실패 시 검색 폴백)
    - 스포티파이 트랙 또는 검색 링크: '곡제목 + 아티스트'로 유튜브/사운드클라우드 고음질 오디오 스트림 자동 매칭
    """
    norm = normalize_playlist_track(track)
    title = (norm.get("title") or "제목 없음").strip()
    artist = (norm.get("artist") or "아티스트 미지정").strip()
    plat = norm.get("platform", "YouTube")
    raw_url = (norm.get("url") or "").strip()
    yt_url = (norm.get("yt_url") or "").strip()

    low_a = artist.lower().strip()
    clean_artist = "" if low_a in (
        "아티스트 미지정", "알 수 없는 아티스트", "알수없는 아티스트", "알수없는아티스트",
        "-", "none", "unknown", "미상", "미지정", "아티스트 미상", "null", ""
    ) else artist

    # 1. 아티스트와 곡제목 정제 (중복 아티스트명 방지)
    if clean_artist and clean_artist.lower() in title.lower():
        base_query = title
    elif clean_artist:
        base_query = f"{clean_artist} {title}".strip()
    else:
        base_query = title

    # 괄호 안의 불필요한 부제([Official MV], (feat. ...), (Explicit), (Remastered) 등) 제거한 정제 검색어
    clean_title = re.sub(r'[\(\[\{](?:feat\.?|official|remastered|explicit|mv|m/v|lyrics|가사|full ver\.?|audio).*?[\)\]\}]', '', title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    if clean_artist and clean_artist.lower() in clean_title.lower():
        clean_query = clean_title
    elif clean_artist:
        clean_query = f"{clean_artist} {clean_title}".strip()
    else:
        clean_query = clean_title

    candidates = []
    seen = set()

    def add_candidate(cand: str):
        if cand and cand not in seen:
            seen.add(cand)
            candidates.append(cand)

    # 2. 직접 재생 가능한 단일 영상/트랙 URL인 경우 1순위 후보로 등록
    # (단, &list=... 등 플레이리스트 파라미터가 섞여있으면 엉뚱한 곡이 재생되므로 반드시 순수 영상 URL로 정규화)
    if "youtube.com" in raw_url.lower() or "youtu.be" in raw_url.lower():
        cleaned_yt = clean_youtube_url(raw_url)
        if "watch?v=" in cleaned_yt:
            add_candidate(cleaned_yt)
    elif "soundcloud.com/" in raw_url.lower() and "/search" not in raw_url.lower() and "/sets/" not in raw_url.lower():
        add_candidate(raw_url)

    if yt_url and ("youtube.com" in yt_url.lower() or "youtu.be" in yt_url.lower()):
        cleaned_yt2 = clean_youtube_url(yt_url)
        if "watch?v=" in cleaned_yt2:
            add_candidate(cleaned_yt2)

    # 3. 플랫폼 우선순위별 스마트 검색 쿼리 등록
    if plat == "SoundCloud":
        add_candidate(f"scsearch3:{base_query}")
        if clean_query and clean_query != base_query:
            add_candidate(f"scsearch3:{clean_query}")
        add_candidate(f"ytsearch3:{base_query}")
        if clean_query and clean_query != base_query:
            add_candidate(f"ytsearch3:{clean_query}")
    else:
        # 유튜브 및 스포티파이 등:
        # 1순위: 가장 정확한 아티스트 + 곡제목 원본 검색 (official audio 같은 불필요한 수식어 없이 순수 검색)
        add_candidate(f"ytsearch3:{base_query}")
        # 2순위: 괄호나 부제가 정리된 깔끔한 검색어
        if clean_query and clean_query != base_query:
            add_candidate(f"ytsearch3:{clean_query}")
        # 3순위: 제목 + 아티스트 순서 검색
        if clean_artist and not (clean_artist.lower() in title.lower()):
            add_candidate(f"ytsearch3:{title} {clean_artist}")
        # 4순위: 유튜브 403 차단 대비 사운드클라우드 자동 폴백
        add_candidate(f"scsearch3:{base_query}")
        if clean_query and clean_query != base_query:
            add_candidate(f"scsearch3:{clean_query}")
        # 5순위: 최후의 수단으로 audio 검색
        add_candidate(f"ytsearch3:{base_query} audio")

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "socket_timeout": 8,
        "default_search": "ytsearch",
        "logger": _QuietYdlLogger(),
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"]
            }
        }
    }

    last_err = None
    for target in candidates:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target, download=False)
                if not info:
                    continue

                raw_list = info.get("entries") if isinstance(info, dict) and "entries" in info else [info]
                candidate_entries = [e for e in (raw_list or []) if isinstance(e, dict)]
                if not candidate_entries:
                    continue

                for cur_entry in candidate_entries:
                    stream_url = cur_entry.get("url")
                    if not stream_url:
                        formats = cur_entry.get("formats") or []
                        audio_formats = [f for f in formats if f.get("url") and f.get("acodec") != "none"]
                        if audio_formats:
                            stream_url = audio_formats[-1].get("url")
                        elif formats and formats[-1].get("url"):
                            stream_url = formats[-1].get("url")

                    if not stream_url:
                        continue

                    duration = int(cur_entry.get("duration") or 0)
                    webpage_url = cur_entry.get("webpage_url") or cur_entry.get("url") or raw_url
                    thumb = cur_entry.get("thumbnail") or norm.get("image")
                    ext_title = cur_entry.get("title") or title
                    ext_uploader = cur_entry.get("uploader") or cur_entry.get("channel") or artist

                    http_headers = cur_entry.get("http_headers") or {}
                    user_agent = http_headers.get("User-Agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

                    return {
                        "stream_url": stream_url,
                        "title": title if title and "직접 등록" not in title else ext_title,
                        "stream_title": ext_title,
                        "artist": artist if artist != "아티스트 미지정" else ext_uploader,
                        "duration": duration,
                        "webpage_url": webpage_url,
                        "image": thumb,
                        "http_headers": http_headers,
                        "user_agent": user_agent,
                    }, None
        except Exception as e:
            last_err = str(e)
            continue

    return None, f"오디오 스트림을 추출하지 못했습니다. ({last_err or '검색 결과 없음'})"


async def resolve_voice_stream(track: dict) -> tuple[dict | None, str | None]:
    return await asyncio.to_thread(resolve_voice_stream_sync, track)



# ==========================================
# 6. 공통 자동완성 함수 (인메모리 캐시 기반으로 0ms 즉시 응답하여 타임아웃 완벽 해결)
# ==========================================
async def date_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    today_str = get_today_str()
    if not current:
        return [app_commands.Choice(name=f"예시: {today_str} (오늘 날짜)", value=today_str)]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", current):
        try:
            _, dday_text = get_dday_info(current)
            return [app_commands.Choice(name=f"{current} 👉 남은 기간 미리보기: {dday_text}", value=current)]
        except ValueError:
            return [app_commands.Choice(name="❌ 존재하지 않는 날짜입니다", value=current)]
    return [app_commands.Choice(name=f"{current} (YYYY-MM-DD 형식으로 끝까지 입력해 주세요)", value=current)]


async def proseka_char_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = [app_commands.Choice(name="해제 (캐릭터 픽업 안 함)", value="NONE")]
    for cid, info in CHARACTER_MAP.items():
        label = f"{info['name']} ({info['unit']})"
        if not current or current in label:
            choices.append(app_commands.Choice(name=label, value=info["name"]))
    return choices[:25]


async def oshi_char_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = []
    for cid, info in CHARACTER_MAP.items():
        label = f"{info['name']} ({info['unit']})"
        if not current or current in label:
            choices.append(app_commands.Choice(name=label, value=info["name"]))
    return choices[:25]


async def owned_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    data = get_cached_data()
    g_key = str(interaction.guild_id or 0)
    u_key = str(interaction.user.id)
    user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
    cards = list(user_cards_dict.values())
    cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), x.get("char_id", 99)))

    choices = []
    for c in cards:
        cnt = c.get("count", 1)
        lock_prefix = "🔒 " if c.get("locked", False) else ""
        label = f"{lock_prefix}{c['rarity_label']} [{c['prefix']}] {c['char_name']} (보유:{cnt}장 | ID:{c['id']})"[:100]
        if not current or current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=str(c["id"])))
        if len(choices) >= 25:
            break
    return choices


async def target_user_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """/카드교환 명령어에서 선택한 '상대유저'가 보유한 카드 목록을 실시간 자동완성"""
    target_user = getattr(interaction.namespace, "상대유저", None)
    if not target_user:
        return [app_commands.Choice(name="먼저 '상대유저' 옵션을 선택해 주세요!", value="NONE")]

    target_id = getattr(target_user, "id", None)
    if not target_id:
        return [app_commands.Choice(name="올바른 상대 유저를 먼저 선택해 주세요", value="NONE")]

    data = get_cached_data()
    g_key = str(interaction.guild_id or 0)
    t_key = str(target_id)
    target_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(t_key, {}).get("cards", {})
    cards = list(target_cards_dict.values())
    cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), x.get("char_id", 99)))

    choices = []
    for c in cards:
        cnt = c.get("count", 1)
        lock_prefix = "🔒 " if c.get("locked", False) else ""
        label = f"{lock_prefix}{c['rarity_label']} [{c['prefix']}] {c['char_name']} (보유:{cnt}장 | ID:{c['id']})"[:100]
        if not current or current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=str(c["id"])))
        if len(choices) >= 25:
            break
    return choices


async def secret_dday_name_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    data = get_cached_data()
    u_key = str(interaction.user.id)
    s_ddays = data.get("user_profiles", {}).get(u_key, {}).get("secret_ddays", {})
    choices = []
    for name, info in s_ddays.items():
        label = f"{name} ({info.get('date', '-')})"[:100]
        if not current or current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=name))
    return choices[:25]


def is_schedule_in_guild(sched: dict, guild) -> bool:
    """음악 알림 타이머가 현재 서버 소속인지 판별 (guild_id 저장값 우선, 구버전 데이터는 채널 소속으로 판별)"""
    if not isinstance(sched, dict) or guild is None:
        return False
    g_id = sched.get("guild_id")
    if g_id:
        return str(g_id) == str(guild.id)
    try:
        return guild.get_channel(int(sched.get("channel_id") or 0)) is not None
    except (TypeError, ValueError):
        return False


async def music_schedule_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    data = get_cached_data()
    schedules = [s for s in data.get("music_schedules", []) if is_schedule_in_guild(s, interaction.guild)]
    choices = []
    for idx, s in enumerate(sorted(schedules, key=lambda x: x.get("time", ""))):
        s_id = s.get("id", str(idx))
        label = f"[{s.get('time', '-')}] {s.get('name', '알림')} (장르: {s.get('genre') or '자동'})"[:100]
        if not current or current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=s_id))
    return choices[:25]


# ==========================================
# 7. 초정밀 실시간 날씨 & 미세먼지 엔진 (Open-Meteo KMA/ECMWF + Air Quality)
# ==========================================
KOREA_CITY_COORDS = {
    "서울": (37.5665, 126.9780, "서울특별시"),
    "강남": (37.4979, 127.0276, "서울 강남구"),
    "홍대": (37.5563, 126.9220, "서울 마포구 홍대"),
    "잠실": (37.5133, 127.1001, "서울 송파구 잠실"),
    "여의도": (37.5216, 126.9242, "서울 영등포구 여의도"),
    "인천": (37.4563, 126.7052, "인천광역시"),
    "부평": (37.5070, 126.7219, "인천 부평구"),
    "송도": (37.3889, 126.6430, "인천 연수구 송도"),
    "수원": (37.2636, 127.0286, "경기도 수원시"),
    "성남": (37.4200, 127.1267, "경기도 성남시"),
    "분당": (37.3827, 127.1189, "경기도 성남시 분당구"),
    "판교": (37.3948, 127.1112, "경기도 성남시 판교"),
    "고양": (37.6584, 126.8320, "경기도 고양시"),
    "일산": (37.6744, 126.7702, "경기도 고양시 일산"),
    "용인": (37.2411, 127.1776, "경기도 용인시"),
    "부천": (37.5034, 126.7660, "경기도 부천시"),
    "안산": (37.3219, 126.8309, "경기도 안산시"),
    "안양": (37.3943, 126.9568, "경기도 안양시"),
    "남양주": (37.6360, 127.2165, "경기도 남양주시"),
    "화성": (37.1995, 126.8313, "경기도 화성시"),
    "동탄": (37.2006, 127.0719, "경기도 화성시 동탄"),
    "평택": (36.9921, 127.1129, "경기도 평택시"),
    "의정부": (37.7381, 127.0337, "경기도 의정부시"),
    "시흥": (37.3800, 126.8030, "경기도 시흥시"),
    "파주": (37.7599, 126.7802, "경기도 파주시"),
    "김포": (37.6152, 126.7156, "경기도 김포시"),
    "광명": (37.4785, 126.8646, "경기도 광명시"),
    "하남": (37.5393, 127.2149, "경기도 하남시"),
    "구리": (37.5943, 127.1296, "경기도 구리시"),
    "이천": (37.2720, 127.4350, "경기도 이천시"),
    "양주": (37.7853, 127.0458, "경기도 양주시"),
    "오산": (37.1499, 127.0771, "경기도 오산시"),
    "부산": (35.1796, 129.0756, "부산광역시"),
    "해운대": (35.1631, 129.1636, "부산 해운대구"),
    "서면": (35.1578, 129.0600, "부산 부산진구 서면"),
    "대구": (35.8714, 128.6014, "대구광역시"),
    "동성로": (35.8691, 128.5954, "대구 중구 동성로"),
    "대전": (36.3504, 127.3845, "대전광역시"),
    "둔산": (36.3519, 127.3782, "대전 서구 둔산동"),
    "광주": (35.1595, 126.8526, "광주광역시"),
    "울산": (35.5384, 129.3114, "울산광역시"),
    "세종": (36.4800, 127.2890, "세종특별자치시"),
    "제주": (33.4996, 126.5312, "제주특별자치도 제주시"),
    "서귀포": (33.2541, 126.5601, "제주특별자치도 서귀포시"),
    "춘천": (37.8813, 127.7298, "강원특별자치도 춘천시"),
    "원주": (37.3422, 127.9202, "강원특별자치도 원주시"),
    "강릉": (37.7519, 128.8761, "강원특별자치도 강릉시"),
    "속초": (38.2070, 128.5918, "강원특별자치도 속초시"),
    "청주": (36.6424, 127.4890, "충청북도 청주시"),
    "충주": (36.9910, 127.9259, "충청북도 충주시"),
    "제천": (37.1326, 128.1910, "충청북도 제천시"),
    "천안": (36.8151, 127.1139, "충청남도 천안시"),
    "아산": (36.7898, 127.0018, "충청남도 아산시"),
    "서산": (36.7845, 126.4503, "충청남도 서산시"),
    "당진": (36.8936, 126.6283, "충청남도 당진시"),
    "공주": (36.4465, 127.1189, "충청남도 공주시"),
    "전주": (35.8242, 127.1480, "전북특별자치도 전주시"),
    "군산": (35.9677, 126.7366, "전북특별자치도 군산시"),
    "익산": (35.9483, 126.9576, "전북특별자치도 익산시"),
    "목포": (34.8118, 126.3922, "전라남도 목포시"),
    "여수": (34.7604, 127.6622, "전라남도 여수시"),
    "순천": (34.9506, 127.4872, "전라남도 순천시"),
    "광양": (34.9407, 127.6959, "전라남도 광양시"),
    "포항": (36.0190, 129.3435, "경상북도 포항시"),
    "구미": (36.1195, 128.3446, "경상북도 구미시"),
    "경주": (35.8562, 129.2247, "경상북도 경주시"),
    "안동": (36.5684, 128.7294, "경상북도 안동시"),
    " 경산": (35.8251, 128.7414, "경상북도 경산시"),
    "경산": (35.8251, 128.7414, "경상북도 경산시"),
    "창원": (35.2280, 128.6811, "경상남도 창원시"),
    "김해": (35.2285, 128.8894, "경상남도 김해시"),
    "진주": (35.1800, 128.1076, "경상남도 진주시"),
    "양산": (35.3350, 129.0372, "경상남도 양산시"),
    "거제": (34.8806, 128.6211, "경상남도 거제시"),
    "통영": (34.8544, 128.4332, "경상남도 통영시"),
    "도쿄": (35.6762, 139.6503, "일본 도쿄(시부야)"),
    "오사카": (34.6937, 135.5023, "일본 오사카"),
    "후쿠오카": (33.5902, 130.4017, "일본 후쿠오카"),
    "삿포로": (43.0618, 141.3545, "일본 삿포로"),
}

WMO_WEATHER_MAP = {
    0: ("☀️ 맑음 (쾌청)", "☀️"),
    1: ("🌤️ 대체로 맑음", "🌤️"),
    2: ("⛅ 구름 조금", "⛅"),
    3: ("☁️ 흐림", "☁️"),
    45: ("🌫️ 안개", "🌫️"),
    48: ("🌫️ 짙은 서리 안개", "🌫️"),
    51: ("🌦️ 가벼운 이슬비", "🌦️"),
    53: ("🌦️ 이슬비", "🌦️"),
    55: ("🌧️ 강한 이슬비", "🌧️"),
    61: ("🌧️ 약한 비", "🌧️"),
    63: ("🌧️ 보통 비", "🌧️"),
    65: ("⛈️ 강한 폭우", "⛈️"),
    66: ("🌨️ 진눈깨비", "🌨️"),
    67: ("🌨️ 강한 진눈깨비", "🌨️"),
    71: ("❄️ 약한 눈", "❄️"),
    73: ("❄️ 보통 눈", "❄️"),
    75: ("☃️ 강한 폭설", "☃️"),
    77: ("❄️ 싸락눈", "❄️"),
    80: ("🌦️ 약한 소나기", "🌦️"),
    81: ("🌧️ 소나기", "🌧️"),
    82: ("⛈️ 강한 소나기", "⛈️"),
    85: ("🌨️ 약한 눈소나기", "🌨️"),
    86: ("☃️ 강한 눈소나기", "☃️"),
    95: ("⛈️ 천둥번개 동반 비", "⛈️"),
    96: ("⛈️ 우박 동반 뇌우", "⛈️"),
    99: ("⛈️ 강한 우박 뇌우", "⛈️"),
}


def _grade_pm10(val: float | None) -> str:
    if val is None:
        return "측정중"
    v = round(val)
    if v <= 30:
        return f"🟢 좋음 ({v}㎍/㎥)"
    elif v <= 80:
        return f"🟡 보통 ({v}㎍/㎥)"
    elif v <= 150:
        return f"🟠 나쁨 ({v}㎍/㎥)"
    return f"🔴 매우나쁨 ({v}㎍/㎥)"


def _grade_pm25(val: float | None) -> str:
    if val is None:
        return "측정중"
    v = round(val)
    if v <= 15:
        return f"🟢 좋음 ({v}㎍/㎥)"
    elif v <= 35:
        return f"🟡 보통 ({v}㎍/㎥)"
    elif v <= 75:
        return f"🟠 나쁨 ({v}㎍/㎥)"
    return f"🔴 매우나쁨 ({v}㎍/㎥)"


def fetch_accurate_weather_sync(location_query: str = "서울") -> tuple[dict | None, str | None]:
    """
    Open-Meteo 고정밀 기상청(KMA)/ECMWF 모델 + 대기질 API를 결합하여 실시간 기온, 체감온도,
    강수확률, 시간대별 예보, 미세먼지(PM10/PM2.5), 생활 지수를 정확하게 반환합니다.
    """
    q = (location_query or "서울").strip()
    lat, lon, resolved_name = None, None, None

    # 1. 내장 정밀 좌표 사전 우선 매칭
    clean_q = re.sub(r"(특별시|광역시|특별자치시|특별자치도|시|군|구|동|읍|면)$", "", q).strip()
    if q in KOREA_CITY_COORDS:
        lat, lon, resolved_name = KOREA_CITY_COORDS[q]
    elif clean_q in KOREA_CITY_COORDS:
        lat, lon, resolved_name = KOREA_CITY_COORDS[clean_q]
    else:
        for k, v in KOREA_CITY_COORDS.items():
            if k in q or q in v[2]:
                lat, lon, resolved_name = v
                break

    # 2. 사전에 없는 지역은 Open-Meteo Geocoding API 실시간 조회
    if lat is None or lon is None:
        geo_res = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": q, "count": 3, "language": "ko", "format": "json"},
            timeout=5
        )
        if geo_res.status_code == 200:
            geo_json = geo_res.json()
            results = geo_json.get("results") or []
            if results:
                best = results[0]
                lat = best.get("latitude")
                lon = best.get("longitude")
                admin1 = best.get("admin1", "")
                name_str = best.get("name", q)
                country = best.get("country", "")
                resolved_name = f"{country} {admin1} {name_str}".strip()

    if lat is None or lon is None:
        return None, f"`{q}` 지역의 위치 좌표를 찾을 수 없습니다. (예: `서울`, `부산`, `강남`, `수원`, `제주`, `도쿄` 등으로 입력해 주세요.)"

    # 3. Open-Meteo 실시간 기상 및 시간별/일별 예보 조회
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,surface_pressure",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
        "timezone": "Asia/Seoul",
        "forecast_days": 3
    }
    w_res = requests.get("https://api.open-meteo.com/v1/forecast", params=weather_params, timeout=6)
    if w_res.status_code != 200:
        return None, "기상 서버로부터 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."

    w_data = w_res.json()
    curr = w_data.get("current", {})
    daily = w_data.get("daily", {})
    hourly = w_data.get("hourly", {})

    # 4. Open-Meteo 실시간 대기질(미세먼지/초미세먼지) 조회
    pm10_val, pm25_val = None, None
    try:
        aq_res = requests.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={"latitude": lat, "longitude": lon, "current": "pm10,pm2_5", "timezone": "Asia/Seoul"},
            timeout=4
        )
        if aq_res.status_code == 200:
            aq_curr = aq_res.json().get("current", {})
            pm10_val = aq_curr.get("pm10")
            pm25_val = aq_curr.get("pm2_5")
    except Exception:
        pass

    w_code = curr.get("weather_code", 0)
    w_desc, w_emoji = WMO_WEATHER_MAP.get(w_code, ("🌤️ 맑음/구름", "🌤️"))
    temp = curr.get("temperature_2m", 0.0)
    feels_like = curr.get("apparent_temperature", temp)
    humidity = curr.get("relative_humidity_2m", 0)
    precip = curr.get("precipitation", 0.0)
    wind = curr.get("wind_speed_10m", 0.0)
    pressure = curr.get("surface_pressure", 1013.0)

    # 일별 최저/최고 및 강수확률
    d_min = (daily.get("temperature_2m_min") or [temp])[0]
    d_max = (daily.get("temperature_2m_max") or [temp])[0]
    d_pop = (daily.get("precipitation_probability_max") or [0])[0]
    d_uv = (daily.get("uv_index_max") or [0.0])[0]
    sunrise_raw = (daily.get("sunrise") or [""])[0]
    sunset_raw = (daily.get("sunset") or [""])[0]
    sunrise_hm = sunrise_raw.split("T")[1] if "T" in sunrise_raw else "-"
    sunset_hm = sunset_raw.split("T")[1] if "T" in sunset_raw else "-"

    # 내일 예보
    tmr_min = (daily.get("temperature_2m_min") or [0, d_min])[1] if len(daily.get("temperature_2m_min", [])) > 1 else d_min
    tmr_max = (daily.get("temperature_2m_max") or [0, d_max])[1] if len(daily.get("temperature_2m_max", [])) > 1 else d_max
    tmr_pop = (daily.get("precipitation_probability_max") or [0, 0])[1] if len(daily.get("precipitation_probability_max", [])) > 1 else 0
    tmr_code = (daily.get("weather_code") or [0, 0])[1] if len(daily.get("weather_code", [])) > 1 else 0
    tmr_desc, _ = WMO_WEATHER_MAP.get(tmr_code, ("🌤️ 맑음", "🌤️"))

    # 향후 12시간(3시간 간격 4포인트) 시간별 예보 추출
    now_hour_prefix = datetime.datetime.now(KST).strftime("%Y-%m-%dT%H:")
    h_times = hourly.get("time") or []
    h_temps = hourly.get("temperature_2m") or []
    h_pops = hourly.get("precipitation_probability") or []
    h_codes = hourly.get("weather_code") or []

    start_idx = 0
    for idx, t_str in enumerate(h_times):
        if t_str.startswith(now_hour_prefix[:13]):
            start_idx = idx
            break

    hourly_forecast = []
    for offset in (2, 5, 8, 11):
        target_i = start_idx + offset
        if target_i < len(h_times):
            t_label = h_times[target_i].split("T")[1][:5] if "T" in h_times[target_i] else h_times[target_i]
            _, h_emo = WMO_WEATHER_MAP.get(h_codes[target_i], ("", "🌤️"))
            hourly_forecast.append({
                "time": t_label,
                "emoji": h_emo,
                "temp": h_temps[target_i],
                "pop": h_pops[target_i] if target_i < len(h_pops) else 0
            })

    # 스마트 생활 조언 생성
    if precip > 0 or w_code >= 51 or d_pop >= 60:
        umbrella_tip = "☔ **우산 필수!** 비/눈 소식이나 높은 강수확률이 예보되어 있습니다."
    elif d_pop >= 30:
        umbrella_tip = "🌂 **접이식 우산 권장:** 갑작스러운 소나기 가능성이 조금 있습니다."
    else:
        umbrella_tip = "☀️ **우산 불필요:** 강수 확률이 낮아 쾌적한 외출이 가능합니다."

    if feels_like >= 28:
        outfit_tip = "👕 반팔, 얇은 셔츠, 반바지 (무더위 수분 섭취 유의)"
    elif feels_like >= 23:
        outfit_tip = "👚 반팔, 얇은 긴팔, 가벼운 면바지"
    elif feels_like >= 17:
        outfit_tip = "🧥 얇은 가디건, 맨투맨, 후드티, 긴바지"
    elif feels_like >= 11:
        outfit_tip = "🧥 자켓, 트렌치코트, 니트, 청바지 (일교차 주의)"
    elif feels_like >= 5:
        outfit_tip = "🧣 울 코트, 경량 패딩, 히트텍, 기모 의류"
    else:
        outfit_tip = "🧤 두꺼운 롱패딩, 목도리, 장갑, 방한용품 필수"

    return {
        "location": resolved_name or q,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "weather_desc": w_desc,
        "weather_emoji": w_emoji,
        "temp": temp,
        "feels_like": feels_like,
        "humidity": humidity,
        "precip": precip,
        "wind": wind,
        "pressure": pressure,
        "min_temp": d_min,
        "max_temp": d_max,
        "pop_max": d_pop,
        "uv_max": d_uv,
        "sunrise": sunrise_hm,
        "sunset": sunset_hm,
        "pm10_grade": _grade_pm10(pm10_val),
        "pm25_grade": _grade_pm25(pm25_val),
        "hourly": hourly_forecast,
        "tmr_desc": tmr_desc,
        "tmr_min": tmr_min,
        "tmr_max": tmr_max,
        "tmr_pop": tmr_pop,
        "umbrella_tip": umbrella_tip,
        "outfit_tip": outfit_tip,
    }, None


# ==========================================
# 8. 한국어 끝말잇기 & 두음법칙(Dueum-beopchik) 엔진
# ==========================================
DUEUM_MAP = {
    "녀": "여", "뇨": "요", "뉴": "유", "니": "이",
    "랴": "야", "려": "여", "례": "예", "료": "요", "류": "유", "리": "이",
    "라": "나", "래": "내", "로": "노", "뢰": "뇌", "루": "누", "르": "느",
}


def get_dueum_chars(last_char: str) -> list[str]:
    """끝 글자에 대해 표준 두음법칙이 적용된 허용 첫 글자 리스트를 반환합니다."""
    if not last_char:
        return []
    res = [last_char]
    if last_char in DUEUM_MAP:
        alt = DUEUM_MAP[last_char]
        if alt not in res:
            res.append(alt)
    return res


WORD_CHAIN_DICT = [
    "가방", "가수", "가을", "가족", "가지", "간식", "갈비", "감동", "감자", "강아지", "개구리", "거울", "거북이", "건물", "게임",
    "겨울", "결과", "결혼", "경찰", "계절", "계란", "고양이", "고구마", "고래", "고속도로", "공기", "공책", "공항", "과일", "과자",
    "과학", "관객", "광장", "교실", "교육", "구름", "구두", "국가", "국수", "군인", "귀걸이", "귤나무", "그림", "극장", "기차",
    "기억", "기적", "기타", "김밥", "김치", "꽃다발", "꿀벌", "꿈나라", "나비", "나무", "나라", "나침반", "낚시", "날씨", "남자",
    "낭만", "냉장고", "노래", "노트북", "녹차", "농구", "눈사람", "뉴스", "늑대", "다람쥐", "다리", "단어", "달력", "달빛", "닭고기",
    "당근", "대나무", "대학생", "도서관", "도시", "도토리", "독서", "동물원", "동전", "두부", "드라마", "등산", "딸기", "떡볶이",
    "라디오", "라면", "레몬", "로봇", "리듬", "마음", "마법", "마이크", "만화", "말투", "망원경", "매미", "머리", "메아리", "멜로디",
    "모자", "목소리", "무지개", "무대", "문구", "물고기", "미래", "미술", "미소", "바다", "바람", "바나나", "박물관", "반지", "발걸음",
    "밤하늘", "방학", "배낭", "백조", "버스", "번개", "별자리", "별빛", "병원", "보석", "보컬", "봄날", "부채", "비행기", "비누",
    "비밀", "비타민", "사과", "사자", "사진", "산책", "삼겹살", "상자", "새벽", "색깔", "생일", "선물", "선생님", "설탕", "섬유",
    "성공", "세카이", "세상", "소풍", "소나무", "소설", "손목시계", "수박", "수영장", "숟가락", "숲속", "스케치북", "스마트폰", "승리",
    "시간", "시계", "시장", "시험", "식당", "신발", "신호등", "실력", "심장", "아침", "아이스크림", "악기", "안경", "알람", "야구",
    "약속", "양말", "어깨", "어린이", "얼음", "엉덩이", "엘리베이터", "여름", "여행", "역사", "연필", "연주", "열쇠", "영화", "예술",
    "오늘", "오렌지", "오케스트라", "온도", "옷장", "우산", "우주", "우유", "운동장", "운명", "웃음", "원숭이", "유리", "유성", "유치원",
    "음악", "음료수", "의자", "이불", "이야기", "이어폰", "인형", "일요일", "일기장", "잎사귀", "자전거", "자동차", "자유", "잠자리",
    "장미", "장난감", "재능", "저녁", "전철", "전화기", "점심", "정원", "제비", "종이", "주머니", "주말", "지구", "지우개", "지하철",
    "진주", "질문", "집중", "창문", "책상", "천사", "철도", "청소", "초콜릿", "촛불", "추억", "축구", "축제", "출석", "춤사위",
    "친구", "침대", "카메라", "카나데", "카페", "칼국수", "캥거루", "컴퓨터", "컵라면", "코끼리", "콘서트", "코스모스", "크리스탈",
    "키보드", "타조", "탁구", "태양", "택시", "텔레비전", "토끼", "토마토", "통기타", "파도", "파란색", "파인애플", "편지", "평화",
    "포도", "포스터", "피아노", "하늘", "학교", "한강", "할머니", "항구", "해바라기", "햄버거", "행복", "향기", "호랑이", "호수",
    "화분", "화요일", "환경", "휴식", "희망", "힘찬", "강릉", "리본", "본능", "능력", "력사", "사랑", "랑데부", "부엌", "일기",
    "기쁨", "쁨이", "미쿠", "쿠키", "키위", "위성", "성악", "악보", "보름달", "달리기", "기차표", "표정", "정류장", "장갑", "갑옷"
]


def pick_bot_word(last_char: str, used_words: set[str]) -> str | None:
    """허용되는 첫 글자(두음법칙 포함)로 시작하는 미사용 단어를 봇 사전에서 선택합니다."""
    valid_starts = get_dueum_chars(last_char)
    candidates = [
        w for w in WORD_CHAIN_DICT
        if w not in used_words and len(w) >= 2 and w[0] in valid_starts
    ]
    if not candidates:
        return None
    return random.choice(candidates)


# ==========================================
# 9. 스마트 자연어 시간 파서 (/알림예약 용)
# ==========================================
def parse_natural_reminder_time(raw_input: str) -> tuple[datetime.datetime | None, str | None]:
    """
    '30분', '1시간 20분 뒤', '15:30', '오후 3시', '2026-12-25 09:00' 등 자연어 시간을
    KST 기준 미래의 datetime 객체와 한국어 설명 문자열로 변환합니다.
    """
    now = datetime.datetime.now(KST)
    s = (raw_input or "").strip()
    if not s:
        return None, "시간을 입력해 주세요. (예: `30분 뒤`, `1시간 후`, `15:30`)"

    # 1. YYYY-MM-DD HH:MM 형식
    m_full = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})$", s)
    if m_full:
        try:
            dt = datetime.datetime(
                int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3)),
                int(m_full.group(4)), int(m_full.group(5)), 0, tzinfo=KST
            )
            if dt <= now:
                return None, "이미 지난 시각입니다. 현재 시각 이후로 입력해 주세요."
            return dt, dt.strftime("%Y-%m-%d %H:%M KST")
        except ValueError:
            return None, "올바르지 않은 날짜/시간 형식입니다."

    # 2. HH:MM 24시간제 형식 (예: 15:30, 09:00)
    m_hm = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if m_hm:
        hh, mm = int(m_hm.group(1)), int(m_hm.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt <= now:
                dt += datetime.timedelta(days=1)
            return dt, dt.strftime("%Y-%m-%d %H:%M KST")

    # 3. 오전/오후 N시 [M분] 형식
    m_ampm = re.match(r"^(오전|오후)?\s*(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?", s)
    if m_ampm and ("뒤" not in s and "후" not in s):
        ampm = m_ampm.group(1)
        hh = int(m_ampm.group(2))
        mm = int(m_ampm.group(3) or 0)
        if ampm == "오후" and hh < 12:
            hh += 12
        elif ampm == "오전" and hh == 12:
            hh = 0
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt <= now:
                dt += datetime.timedelta(days=1)
            return dt, dt.strftime("%Y-%m-%d %H:%M KST")

    # 4. 상대 시간 (일, 시간/h, 분/m, 초/s)
    total_seconds = 0
    m_days = re.search(r"(\d+)\s*(?:일|d|day)", s, re.IGNORECASE)
    m_hours = re.search(r"(\d+)\s*(?:시간|h|hr|hour)", s, re.IGNORECASE)
    m_mins = re.search(r"(\d+)\s*(?:분|m|min)", s, re.IGNORECASE)
    m_secs = re.search(r"(\d+)\s*(?:초|s|sec)", s, re.IGNORECASE)

    if m_days:
        total_seconds += int(m_days.group(1)) * 86400
    if m_hours:
        total_seconds += int(m_hours.group(1)) * 3600
    if m_mins:
        total_seconds += int(m_mins.group(1)) * 60
    if m_secs:
        total_seconds += int(m_secs.group(1))

    # 숫자만 입력한 경우 분(minute) 단위로 간주
    if total_seconds == 0 and s.isdigit():
        total_seconds = int(s) * 60

    if total_seconds > 0:
        if total_seconds < 10:
            total_seconds = 10
        if total_seconds > 86400 * 365:
            return None, "알림 예약은 최대 1년 이내로만 설정할 수 있습니다."
        dt = now + datetime.timedelta(seconds=total_seconds)
        return dt, dt.strftime("%Y-%m-%d %H:%M:%S KST")

    return None, "시간 형식을 인식하지 못했습니다. (예: `30분 뒤`, `1시간 30분 후`, `15:30`, `오후 8시`)"


# ==========================================
# 28. 이모지 반응 역할 (Reaction Roles) 엔진
# ==========================================
def parse_emoji_for_reaction(emoji_raw: str, guild: Optional[discord.Guild] = None):
    """
    이모지 입력을 정규화하여 디스코드 add_reaction에 사용할 객체와 (표시용 문자열, 이모지이름, 이모지ID) 튜플을 반환합니다.
    - 커스텀 이모지: <:name:123456> 또는 <a:name:123456> 또는 123456
    - 유니코드 이모지: 📢, 🔥, 👍 등
    """
    if not emoji_raw:
        return None, "", None

    raw = str(emoji_raw).strip()

    # 1. 커스텀 이모지 태그: <:name:id> 또는 <a:name:id>
    m_tag = re.match(r"^<(a?):([a-zA-Z0-9_]+):(\d+)>$", raw)
    if m_tag:
        is_animated = bool(m_tag.group(1))
        name = m_tag.group(2)
        eid = int(m_tag.group(3))
        if guild:
            custom_e = discord.utils.get(guild.emojis, id=eid)
            if custom_e:
                return custom_e, f"<{'a' if is_animated else ''}:{name}:{eid}>", eid
        # 길드에 없더라도 PartialEmoji로 반응 추가 가능
        partial_e = discord.PartialEmoji(name=name, id=eid, animated=is_animated)
        return partial_e, f"<{'a' if is_animated else ''}:{name}:{eid}>", eid

    # 2. 숫자만 입력된 경우 (이모지 ID)
    if raw.isdigit():
        eid = int(raw)
        if guild:
            custom_e = discord.utils.get(guild.emojis, id=eid)
            if custom_e:
                return custom_e, str(custom_e), eid
        partial_e = discord.PartialEmoji(name="emoji", id=eid)
        return partial_e, f"<:emoji:{eid}>", eid

    # 3. 유니코드 기본 이모지
    # 공백이나 특수문자 제거 후 첫 번째 글자/클러스터 사용
    clean_unicode = raw.strip()
    return clean_unicode, clean_unicode, None


def check_role_assignable(bot_member: discord.Member, target_role: discord.Role) -> tuple[bool, str]:
    """
    봇이 해당 역할을 일반 유저에게 지급/회수할 수 있는지 권한 및 계층(Hierarchy)을 엄격 검증합니다.
    """
    if target_role.is_default():
        return False, "❌ `@everyone` 기본 역할은 반응 역할로 지정할 수 없습니다."

    if target_role.managed:
        return False, f"❌ `{target_role.name}` 역할은 봇 통합/부스터 전용 관리 역할이므로 수동으로 지급할 수 없습니다."

    if not bot_member.guild_permissions.manage_roles:
        return False, "🚨 봇에게 **'역할 관리(Manage Roles)'** 권한이 없습니다. 서버 설정에서 봇에게 역할 관리 권한을 부여해 주세요."

    if target_role >= bot_member.top_role:
        return (
            False,
            f"⚠️ **역할 서열(Hierarchy) 오류:**\n"
            f"지정하려는 `{target_role.name}` 역할이 봇의 최고 역할(`{bot_member.top_role.name}`)보다 높거나 같은 위치에 있습니다.\n"
            f"👉 **해결법:** 서버 설정 → [역할] 메뉴에서 **`{bot_member.top_role.name}`** 역할을 마우스로 끌어올려 **`{target_role.name}`**보다 위에 배치해 주세요!"
        )

    # 관리자(Administrator) 권한을 가진 위험한 역할 경고
    if target_role.permissions.administrator:
        return (
            False,
            f"⛔ `{target_role.name}` 역할은 **'서버 관리자(Administrator)'** 권한을 보유하고 있어 보안상 반응 역할로 배포할 수 없습니다."
        )

    return True, "OK"


def match_payload_emoji(payload_emoji: discord.PartialEmoji, target_entry: dict) -> bool:
    """디스코드 raw_reaction 이벤트의 PartialEmoji와 DB에 저장된 반응역할 이모지 항목이 일치하는지 비교합니다."""
    target_id = target_entry.get("emoji_id")
    target_name = target_entry.get("emoji_name")

    if payload_emoji.id and target_id:
        return int(payload_emoji.id) == int(target_id)

    # 유니코드 이모지 비교 (name 속성에 유니코드 이모지 문자가 들어감)
    if payload_emoji.name and target_name:
        return payload_emoji.name.strip() == str(target_name).strip()

    return False


def get_guild_reaction_roles(data: dict, guild_id: int) -> dict[str, dict]:
    """특정 길드에 등록된 모든 반응역할 메시지 매핑을 반환합니다."""
    rr_map = data.get("reaction_roles", {})
    return {
        mid: cfg for mid, cfg in rr_map.items()
        if int(cfg.get("guild_id", 0)) == int(guild_id)
    }


def save_reaction_role_entry(
    data: dict,
    message_id: int,
    guild_id: int,
    channel_id: int,
    roles: list[dict],
    title: str = "반응 역할 선택",
    description: str = "",
    mode: str = "multiple",
    creator_id: Optional[int] = None
):
    """반응역할 메시지 정보를 DB에 안전하게 저장합니다."""
    rr_map = data.setdefault("reaction_roles", {})
    mid_str = str(message_id)
    rr_map[mid_str] = {
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "title": title or "반응 역할 선택",
        "description": description or "",
        "mode": mode if mode in ("multiple", "unique") else "multiple",
        "roles": roles,
        "created_at": get_today_str(),
        "creator_id": int(creator_id) if creator_id else None
    }
    return rr_map[mid_str]


def remove_reaction_role_entry(data: dict, message_id: int) -> bool:
    """반응역할 등록 정보를 제거합니다."""
    rr_map = data.get("reaction_roles", {})
    mid_str = str(message_id)
    if mid_str in rr_map:
        del rr_map[mid_str]
        return True
    return False


