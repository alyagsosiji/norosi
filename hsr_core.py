"""붕괴: 스타레일 (Honkai: Star Rail) 워프 · 도감 · 별빛/헤르타 상점 · 파티 시너지 코어 엔진

- 실시간 한국어 DB 연동: sr.yatta.moe/api/v2/kr + StarRailRes GitHub 한국어 인덱스 + 로컬 캐시(hsr_kr_cache.json) + 내장 폴백
- 정통 워프 메커니즘:
  * 캐릭터 이벤트 워프 ①/② (90천장 · 74소프트 +6%/뽑 · 기본 0.6% · 50/50 & 확정 천장 · 두 픽업 간 천장 공유)
  * 광추 이벤트 워프 '빛의 자취' (80천장 · 66소프트 +7%/뽑 · 기본 0.8% · 75/25 & 확정 천장)
  * 상시 '뭇별의 워프' (90천장 · 300회 달성 시 상시 5성 캐릭터 1명 직접 선택!)
- 성혼(E0~E6) & 광추 중첩(S1~S5) 자동 누적 + 꺼지지 않는 별빛 / 불멸의 잔재 / 헤르타 채권 자동 정산
"""
from __future__ import annotations

import copy
import datetime
import io
import json
import os
import random
import re
import threading
import time
from collections import OrderedDict

import core

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None
    ImageDraw = None

requests = core.requests

_HSR_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HSR_CACHE_FILE = os.path.join(_HSR_BASE_DIR, "hsr_kr_cache.json")
HSR_CACHE_TTL = 60 * 60 * 12  # 12시간마다 백그라운드 갱신
HSR_CACHE_VERSION = 2

_HSR_DB_LOCK = threading.Lock()
_HSR_IMG_LOCK = threading.Lock()
_HSR_DETAIL_LOCK = threading.Lock()

HSR_CHARS: list[dict] = []
HSR_LIGHT_CONES: list[dict] = []
HSR_RELICS: list[dict] = []
HSR_RELIC_MAP: dict[str, dict] = {}
HSR_ALL_ITEMS: dict[str, dict] = {}
_HSR_LAST_FETCH: float = 0.0

_HSR_IMG_CACHE: OrderedDict[str, bytes] = OrderedDict()
_HSR_THUMB_CACHE: OrderedDict[str, bytes] = OrderedDict()
_HSR_DETAIL_CACHE: OrderedDict[str, dict] = OrderedDict()

# 운명의 길 9종 (기억 · 환락 포함)
HSR_PATH_MAP = {
    "Warrior": {"name": "파멸", "emoji": "⚔️", "role": "메인/브루저 딜러", "role_tag": "dps"},
    "Rogue": {"name": "수렵", "emoji": "🏹", "role": "단일 폭딜러", "role_tag": "dps"},
    "Mage": {"name": "지식", "emoji": "📘", "role": "광역 딜러", "role_tag": "dps"},
    "Shaman": {"name": "화합", "emoji": "🎵", "role": "버프 서포터", "role_tag": "sup"},
    "Warlock": {"name": "공허", "emoji": "🕸️", "role": "디버프/지속피해", "role_tag": "sup"},
    "Knight": {"name": "보존", "emoji": "🛡️", "role": "실드/탱커", "role_tag": "sus"},
    "Priest": {"name": "풍요", "emoji": "🌿", "role": "힐러/생존", "role_tag": "sus"},
    "Memory": {"name": "기억", "emoji": "🕊️", "role": "기억정령/만능", "role_tag": "dps"},
    "Elation": {"name": "환락", "emoji": "🎭", "role": "추공/아하 축복", "role_tag": "dps"},
}

# 전투 속성 7종
HSR_ELEMENT_MAP = {
    "Physical": {"name": "물리", "emoji": "⚔️", "color": (212, 218, 232)},
    "Fire": {"name": "화염", "emoji": "🔥", "color": (255, 99, 71)},
    "Ice": {"name": "얼음", "emoji": "❄️", "color": (91, 211, 255)},
    "Thunder": {"name": "번개", "emoji": "⚡", "color": (190, 118, 255)},
    "Wind": {"name": "바람", "emoji": "🌪️", "color": (72, 232, 165)},
    "Quantum": {"name": "양자", "emoji": "🌌", "color": (118, 134, 255)},
    "Imaginary": {"name": "허수", "emoji": "✨", "color": (248, 212, 86)},
}

# 상시 5성 캐릭터 7인 (별빛 50/50 & 상시 300회 선택권 대상)
HSR_STD_5_CHARS = {
    "1003",  # 히메코
    "1004",  # 웰트
    "1101",  # 브로냐
    "1104",  # 게파드
    "1107",  # 클라라
    "1209",  # 연경
    "1211",  # 백로
}

# 콜라보 5성 캐릭터 (한정/특별 픽업 시에만 등장 — 상시/이탈 드랍 제외)
HSR_COLLAB_5_CHARS = {
    "1014",  # 세이버
    "1015",  # 아처
    "1508",  # 토오사카 린
    "1509",  # 길가메시
}

# 배포 전용 4성 캐릭터 (랜덤 워프 제외 — 도감/상점에서 별도 관리)
HSR_NON_WARP_4_CHARS = {
    "1224",  # Mar. 7th · 수렵
}

# 상시 5성 광추 7종 (별빛 교환 600개 및 상시/픽뚫 대상)
HSR_STD_5_LCS = {
    "23000",  # 은하철도의 밤 (히메코)
    "23002",  # 대체할 수 없는 것 (클라라)
    "23003",  # 아직 전투는 끝나지 않았다 (브로냐)
    "23004",  # 세계의 이름으로 (웰트)
    "23005",  # 승리의 순간 (게파드)
    "23012",  # 깊게 든 단잠 (연경)
    "23013",  # 세월은 흐를 뿐 (백로)
}

# 망각의 정원 / 광추 박물 교환 4성 광추 (워프 제외, 상점 교환 가능)
HSR_FORGOTTEN_HALL_LCS = {
    "21021", "21022", "21023", "21024", "21025", "21026", "21027",
    "21035", "21036", "21037", "21038", "21039", "21040", "21041",
    "21050", "21064", "21065",
}

# 무명의 공훈(배틀패스) 4성 광추 (워프 제외)
HSR_BP_LCS = {
    "21028", "21029", "21030", "21031", "21032", "21033", "21034",
    "21052", "21054", "21057", "21058", "21060", "21061", "21062", "21066",
}

# 22xxx = 이벤트 배포 4성 광추, 24xxx = 헤르타 상점 5성 광추
HSR_EVENT_LC_PREFIX = "22"
HSR_HERTA_LC_PREFIX = "24"

HSR_BANNER_CONFIGS = {
    "char1": {
        "name": "🚆 캐릭터 이벤트 워프 ①",
        "short_name": "캐릭터 워프 ①",
        "currency_name": "별의 궤도 전용티켓",
        "hard_pity": 90,
        "soft_start": 74,
        "base_5_pct": 0.6,
        "base_4_pct": 5.1,
        "color": (182, 122, 255),
        "desc": "한정 5성 캐릭터 ① 픽업 (90천장 · 74소프트 +6% · 50/50 & 확정)",
    },
    "char2": {
        "name": "🌠 캐릭터 이벤트 워프 ②",
        "short_name": "캐릭터 워프 ②",
        "currency_name": "별의 궤도 전용티켓",
        "hard_pity": 90,
        "soft_start": 74,
        "base_5_pct": 0.6,
        "base_4_pct": 5.1,
        "color": (255, 184, 88),
        "desc": "한정 5성 캐릭터 ② 복각·더블 워프 (캐릭터 ①과 천장 공유)",
    },
    "lc": {
        "name": "🪩 빛의 자취 (광추 이벤트 워프)",
        "short_name": "광추 워프",
        "currency_name": "별의 궤도 전용티켓",
        "hard_pity": 80,
        "soft_start": 66,
        "base_5_pct": 0.8,
        "base_4_pct": 6.6,
        "color": (94, 212, 255),
        "desc": "픽업 5성 광추 75% (80천장 · 66소프트 +7% · 확정 보장)",
    },
    "standard": {
        "name": "🌌 뭇별의 워프 (상시 워프)",
        "short_name": "상시 워프",
        "currency_name": "별의 궤도 티켓",
        "hard_pity": 90,
        "soft_start": 74,
        "base_5_pct": 0.6,
        "base_4_pct": 5.1,
        "color": (124, 152, 255),
        "desc": "상시 5성 캐릭터/광추 50:50 · 300회 누적 시 상시 5성 직접 선택!",
    },
    "relic": {
        "name": "🏛️ 침식된 터널 & 차원 장신구 (유물 워프)",
        "short_name": "유물 터널",
        "currency_name": "개척력 농축 수정",
        "hard_pity": 10,
        "soft_start": 7,
        "base_5_pct": 12.0,
        "base_4_pct": 38.0,
        "color": (82, 232, 206),
        "desc": "요일·시각별 터널/시뮬레이션 로테이션 · 10회 내 ★5 유물 확정 + 부위·주옵·부옵 부여",
    },
}

class _HSRRelicSlotCatalog(list):
    """스타레일 유물 부위 카탈로그 — 리스트 순회 (for s in HSR_RELIC_SLOTS) 및 dict 조회 (.get / [code]) 동시 지원"""
    def __init__(self, entries: list[dict]):
        super().__init__(entries)
        self._by_key: dict[str, dict] = {}
        for e in entries:
            self._by_key[e["code"]] = e
            self._by_key[e["key"]] = e

    def keys(self):
        return [e["code"] for e in self]

    def get(self, key: str, default=None):
        return self._by_key.get(str(key), default)

    def __getitem__(self, item):
        if isinstance(item, int):
            return super().__getitem__(item)
        return self._by_key[str(item)]


# 터널 유물 4부위 & 차원 장신구 2부위 및 주옵션 테이블
HSR_RELIC_SLOTS = _HSRRelicSlotCatalog([
    {
        "code": "HEAD",
        "key": "head",
        "name": "머리",
        "short": "머리",
        "emoji": "🪖",
        "idx": 0,
        "icon_idx": 0,
        "is_planar": False,
        "planar": False,
        "main_pool": ["HP"],
    },
    {
        "code": "HAND",
        "key": "hands",
        "name": "핸드",
        "short": "핸드",
        "emoji": "🧤",
        "idx": 1,
        "icon_idx": 1,
        "is_planar": False,
        "planar": False,
        "main_pool": ["공격력"],
    },
    {
        "code": "BODY",
        "key": "body",
        "name": "바디",
        "short": "바디",
        "emoji": "🥋",
        "idx": 2,
        "icon_idx": 2,
        "is_planar": False,
        "planar": False,
        "main_pool": ["치명타 확률", "치명타 피해", "공격력%", "HP%", "방어력%", "치유량 보너스", "효과 명중"],
    },
    {
        "code": "FOOT",
        "key": "feet",
        "name": "다리",
        "short": "다리",
        "emoji": "👢",
        "idx": 3,
        "icon_idx": 3,
        "is_planar": False,
        "planar": False,
        "main_pool": ["속도", "공격력%", "HP%", "방어력%"],
    },
    {
        "code": "NECK",
        "key": "sphere",
        "name": "차원 구체",
        "short": "구체",
        "emoji": "🔮",
        "idx": 0,
        "icon_idx": 0,
        "is_planar": True,
        "planar": True,
        "main_pool": [
            "물리 속성 피해 증가", "화염 속성 피해 증가", "얼음 속성 피해 증가",
            "번개 속성 피해 증가", "바람 속성 피해 증가", "양자 속성 피해 증가",
            "허수 속성 피해 증가", "공격력%", "HP%", "방어력%",
        ],
    },
    {
        "code": "OBJECT",
        "key": "rope",
        "name": "연결 매듭",
        "short": "매듭",
        "emoji": "🪢",
        "idx": 1,
        "icon_idx": 1,
        "is_planar": True,
        "planar": True,
        "main_pool": ["에너지 회복효율", "격파 특수효과", "공격력%", "HP%", "방어력%"],
    },
])

_HSR_MAIN_BY_RANK = {
    (5, "HP"): ("+112", "+705"),
    (5, "공격력"): ("+56", "+352"),
    (5, "HP%"): ("+6.9%", "+43.2%"),
    (5, "공격력%"): ("+6.9%", "+43.2%"),
    (5, "방어력%"): ("+8.6%", "+54.0%"),
    (5, "속도"): ("+4", "+25"),
    (5, "치명타 확률"): ("+5.2%", "+32.4%"),
    (5, "치명타 확률%"): ("+5.2%", "+32.4%"),
    (5, "치명타 피해"): ("+10.4%", "+64.8%"),
    (5, "치명타 피해%"): ("+10.4%", "+64.8%"),
    (5, "격파 특수효과"): ("+10.4%", "+64.8%"),
    (5, "에너지 회복효율"): ("+3.1%", "+19.4%"),
    (5, "치유량 보너스"): ("+5.5%", "+34.5%"),
    (5, "효과 명중"): ("+6.9%", "+43.2%"),
    (5, "물리 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (5, "화염 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (5, "얼음 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (5, "번개 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (5, "바람 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (5, "양자 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (5, "허수 속성 피해 증가"): ("+6.2%", "+38.8%"),
    (4, "HP"): ("+90", "+564"),
    (4, "공격력"): ("+45", "+282"),
    (4, "HP%"): ("+5.5%", "+34.5%"),
    (4, "공격력%"): ("+5.5%", "+34.5%"),
    (4, "방어력%"): ("+6.9%", "+43.2%"),
    (4, "속도"): ("+3", "+20"),
    (4, "치명타 확률"): ("+4.1%", "+25.9%"),
    (4, "치명타 피해"): ("+8.3%", "+51.8%"),
    (4, "격파 특수효과"): ("+8.3%", "+51.8%"),
    (4, "에너지 회복효율"): ("+2.5%", "+15.5%"),
    (4, "치유량 보너스"): ("+4.4%", "+27.6%"),
    (4, "효과 명중"): ("+5.5%", "+34.5%"),
    (4, "물리 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (4, "화염 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (4, "얼음 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (4, "번개 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (4, "바람 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (4, "양자 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (4, "허수 속성 피해 증가"): ("+5.0%", "+31.1%"),
    (3, "HP"): ("+67", "+423"),
    (3, "공격력"): ("+33", "+211"),
    (3, "HP%"): ("+4.1%", "+25.9%"),
    (3, "공격력%"): ("+4.1%", "+25.9%"),
    (3, "방어력%"): ("+5.2%", "+32.4%"),
    (3, "속도"): ("+2", "+15"),
    (3, "치명타 확률"): ("+3.1%", "+19.4%"),
    (3, "치명타 피해"): ("+6.2%", "+38.8%"),
    (3, "격파 특수효과"): ("+6.2%", "+38.8%"),
    (3, "에너지 회복효율"): ("+1.9%", "+11.6%"),
    (3, "치유량 보너스"): ("+3.3%", "+20.7%"),
    (3, "효과 명중"): ("+4.1%", "+25.9%"),
    (3, "물리 속성 피해 증가"): ("+3.7%", "+23.3%"),
    (3, "화염 속성 피해 증가"): ("+3.7%", "+23.3%"),
    (3, "얼음 속성 피해 증가"): ("+3.7%", "+23.3%"),
    (3, "번개 속성 피해 증가"): ("+3.7%", "+23.3%"),
    (3, "바람 속성 피해 증가"): ("+3.7%", "+23.3%"),
    (3, "양자 속성 피해 증가"): ("+3.7%", "+23.3%"),
    (3, "허수 속성 피해 증가"): ("+3.7%", "+23.3%"),
}

HSR_RELIC_MAIN_VALUES: dict = dict(_HSR_MAIN_BY_RANK)
for (_rk, _st), _pair in _HSR_MAIN_BY_RANK.items():
    if _rk == 5:
        HSR_RELIC_MAIN_VALUES[_st] = _pair

HSR_RELIC_SUBSTATS = [
    ("치명타 확률", (2.6, 2.9, 3.2), "%"),
    ("치명타 피해", (5.2, 5.8, 6.5), "%"),
    ("속도", (2.0, 2.3, 2.6), ""),
    ("공격력%", (3.5, 3.9, 4.3), "%"),
    ("격파 특수효과", (5.2, 5.8, 6.5), "%"),
    ("HP%", (3.5, 3.9, 4.3), "%"),
    ("방어력%", (4.3, 4.9, 5.4), "%"),
    ("효과 명중", (3.5, 3.9, 4.3), "%"),
    ("효과 저항", (3.5, 3.9, 4.3), "%"),
    ("공격력", (17.0, 19.0, 21.0), ""),
    ("HP", (34.0, 38.0, 42.0), ""),
    ("방어력", (17.0, 19.0, 21.0), ""),
]

HSR_RELIC_SUB_MAX_MAP = {name: tiers[-1] for name, tiers, _ in HSR_RELIC_SUBSTATS}

# 별빛 상점 6개월 순환 4성 캐릭터 로테이션 (매월 2명)
HSR_STARLIGHT_CHAR_ROTATION = [
    ("1001", "1105"),  # 1·7월: Mar. 7th (보존) · 나타샤
    ("1002", "1103"),  # 2·8월: 단항 · 서벌
    ("1008", "1009"),  # 3·9월: 아를란 · 아스타
    ("1108", "1109"),  # 4·10월: 삼포 · 후크
    ("1106", "1201"),  # 5·11월: 페라 · 청작
    ("1202", "1206"),  # 6·12월: 정운 · 소상
]

# 대표 픽업 프리셋 (봇 주인 픽업설정용)
HSR_BANNER_PRESETS = {
    "latest": {
        "label": "✨ 최신 개척 캐릭터 자동 연동",
        "banner_name": "은하열차 최신 워프",
        "char1": None,
        "char2": None,
        "char_4_ids": [],
        "lc_1": None,
        "lc_2": None,
    },
    "elation_aha": {
        "label": "🎭 아하의 환락 & 별빛 축제 (에반스 / 블레이드·환락)",
        "banner_name": "끝없는 웃음의 연회 & 주사위의 유혹",
        "char1": "1511",  # 에반스
        "char2": "1513",  # 블레이드 (환락)
        "char_4_ids": ["1301", "1223", "1106"],  # 갤러거, 맥택, 페라
        "lc_1": "23065",  # 내일이 찾아올 때까지
        "lc_2": "23064",  # 행운의 주사위 한 알
    },
    "amphoreus_dawn": {
        "label": "☀️ 앰포리어스 황금의 후예 (파이논 / 카스토리스)",
        "banner_name": "여명의 구세주 & 사신의 포옹",
        "char1": "1408",  # 파이논
        "char2": "1407",  # 카스토리스
        "char_4_ids": ["1301", "1202", "1106"],  # 갤러거, 정운, 페라
        "lc_1": "23044",  # 이와 같이 타오르는 여명
        "lc_2": "23040",  # 이별이 더 아름답도록
    },
    "amphoreus_memory": {
        "label": "❄️ 영원의 기억과 찬란한 지식 (키레네 / 더 헤르타)",
        "banner_name": "영원한 사랑의 시 & 지니어스의 서곡",
        "char1": "1415",  # 키레네
        "char2": "1401",  # 더 헤르타
        "char_4_ids": ["1223", "1013", "1009"],  # 맥택, 헤르타, 아스타
        "lc_1": "23052",  # 이 순간처럼 영원한 사랑
        "lc_2": "23037",  # 추궁할 수 없는 곳을 향해
    },
    "penacony_dream": {
        "label": "🌌 페나코니 꿈의 무대 (아케론 / 반디)",
        "banner_name": "공허의 칼날 & 불타는 반딧불",
        "char1": "1308",  # 아케론
        "char2": "1310",  # 반디
        "char_4_ids": ["1301", "1106", "1214"],  # 갤러거, 페라, 설의
        "lc_1": "23024",  # 흘러가는 강가를 따라
        "lc_2": "23025",  # 꿈은 어디로 돌아가야 하는가
    },
    "ipc_harmony": {
        "label": "🎵 은하 화합 슈퍼 서포트 (로빈 / 선데이)",
        "banner_name": "꿈의 노래 & 질서의 여명",
        "char1": "1309",  # 로빈
        "char2": "1313",  # 선데이
        "char_4_ids": ["1202", "1201", "1110"],  # 정운, 청작, 링스
        "lc_1": "23026",  # 찬란하게 빛나는 밤
        "lc_2": "23034",  # 대지로 돌아온 비행
    },
}

# 오프라인/네트워크 장애 대비 내장 폴백 데이터
HSR_EMBEDDED_FALLBACK_CHARS = [
    {"id": "1511", "name": "에반스", "rank": 5, "path": "Elation", "element": "Thunder", "release": 1779660000, "pool_type": "한정"},
    {"id": "1513", "name": "블레이드", "rank": 5, "path": "Elation", "element": "Quantum", "release": 1777932000, "pool_type": "한정"},
    {"id": "1408", "name": "파이논", "rank": 5, "path": "Warrior", "element": "Physical", "release": 1751446800, "pool_type": "한정"},
    {"id": "1407", "name": "카스토리스", "rank": 5, "path": "Memory", "element": "Quantum", "release": 1744189200, "pool_type": "한정"},
    {"id": "1401", "name": "더 헤르타", "rank": 5, "path": "Mage", "element": "Ice", "release": 1736935200, "pool_type": "한정"},
    {"id": "1308", "name": "아케론", "rank": 5, "path": "Warlock", "element": "Thunder", "release": 1711533600, "pool_type": "한정"},
    {"id": "1310", "name": "반디", "rank": 5, "path": "Warrior", "element": "Fire", "release": 1718787600, "pool_type": "한정"},
    {"id": "1309", "name": "로빈", "rank": 5, "path": "Shaman", "element": "Physical", "release": 1715158800, "pool_type": "한정"},
    {"id": "1003", "name": "히메코", "rank": 5, "path": "Mage", "element": "Fire", "release": 1682460000, "pool_type": "상시"},
    {"id": "1004", "name": "웰트", "rank": 5, "path": "Warlock", "element": "Imaginary", "release": 1682460000, "pool_type": "상시"},
    {"id": "1101", "name": "브로냐", "rank": 5, "path": "Shaman", "element": "Wind", "release": 1682460000, "pool_type": "상시"},
    {"id": "1104", "name": "게파드", "rank": 5, "path": "Knight", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
    {"id": "1107", "name": "클라라", "rank": 5, "path": "Warrior", "element": "Physical", "release": 1682460000, "pool_type": "상시"},
    {"id": "1209", "name": "연경", "rank": 5, "path": "Rogue", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
    {"id": "1211", "name": "백로", "rank": 5, "path": "Priest", "element": "Thunder", "release": 1682460000, "pool_type": "상시"},
    {"id": "1301", "name": "갤러거", "rank": 4, "path": "Priest", "element": "Fire", "release": 1711533600, "pool_type": "상시"},
    {"id": "1202", "name": "정운", "rank": 4, "path": "Shaman", "element": "Thunder", "release": 1682460000, "pool_type": "상시"},
    {"id": "1106", "name": "페라", "rank": 4, "path": "Warlock", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
    {"id": "1001", "name": "Mar. 7th (보존)", "rank": 4, "path": "Knight", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
]

HSR_EMBEDDED_FALLBACK_LCS = [
    {"id": "23065", "name": "내일이 찾아올 때까지", "rank": 5, "path": "Elation", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23064", "name": "행운의 주사위 한 알", "rank": 5, "path": "Elation", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23024", "name": "흘러가는 강가를 따라", "rank": 5, "path": "Warlock", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23040", "name": "이별이 더 아름답도록", "rank": 5, "path": "Memory", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23000", "name": "은하철도의 밤", "rank": 5, "path": "Mage", "warp_source": "standard", "pool_type": "상시"},
    {"id": "23003", "name": "아직 전투는 끝나지 않았다", "rank": 5, "path": "Shaman", "warp_source": "standard", "pool_type": "상시"},
    {"id": "24000", "name": "어떤 에이언즈의 몰락", "rank": 5, "path": "Warrior", "warp_source": "herta", "pool_type": "헤르타 상점"},
    {"id": "21018", "name": "댄스! 댄스! 댄스!", "rank": 4, "path": "Shaman", "warp_source": "standard", "pool_type": "상시"},
    {"id": "21015", "name": "땀방울처럼 빛나는 결심", "rank": 4, "path": "Warlock", "warp_source": "standard", "pool_type": "상시"},
    {"id": "20012", "name": "맞물린 톱니", "rank": 3, "path": "Shaman", "warp_source": "standard", "pool_type": "워프 상시"},
    {"id": "20015", "name": "증식", "rank": 3, "path": "Priest", "warp_source": "standard", "pool_type": "워프 상시"},
]

HSR_EMBEDDED_FALLBACK_RELICS = [
    {"id": "130", "kind": "relic", "item_key": "relic:130", "name": "빛나는 공훈의 마법 소녀", "is_planar": False, "bonus_2pc": "치명타 피해 +16%", "bonus_4pc": "환락 피해 방어 무시 +10% (웃음 포인트 중첩)", "icon": "71058"},
    {"id": "129", "kind": "relic", "item_key": "relic:129", "name": "천명에 응해 먼 길을 떠난 점술가", "is_planar": False, "bonus_2pc": "속도 +6%", "bonus_4pc": "고속 시 치명타 확률 최대 +18% & 환락 피해 +10%", "icon": "71056"},
    {"id": "128", "kind": "relic", "item_key": "relic:128", "name": "천지를 재창조한 구세주", "is_planar": False, "bonus_2pc": "치명타 확률 +8%", "bonus_4pc": "기억 정령 소환 시 파티 치피 증가", "icon": "71054"},
    {"id": "125", "kind": "relic", "item_key": "relic:125", "name": "망국의 비애를 노래하는 시인", "is_planar": False, "bonus_2pc": "양자 속성 피해 +10%", "bonus_4pc": "저속 시 치명타 확률 최대 +32% (기억 정령 적용)", "icon": "71048"},
    {"id": "124", "kind": "relic", "item_key": "relic:124", "name": "개선가를 울리는 영웅", "is_planar": False, "bonus_2pc": "공격력 +12%", "bonus_4pc": "기억 정령 필드 존재 시 속도 +6% & 치피 +30%", "icon": "71046"},
    {"id": "122", "kind": "relic", "item_key": "relic:122", "name": "지식의 바다에 빠진 학자", "is_planar": False, "bonus_2pc": "치명타 확률 +8%", "bonus_4pc": "필살기 및 전투 스킬 피해 +20%", "icon": "71042"},
    {"id": "119", "kind": "relic", "item_key": "relic:119", "name": "곤충 재앙을 잠재우는 철기군", "is_planar": False, "bonus_2pc": "격파 특수효과 +16%", "bonus_4pc": "격파/슈퍼 격파 방어 무시", "icon": "71036"},
    {"id": "117", "kind": "relic", "item_key": "relic:117", "name": "사수에 잠수한 선구자", "is_planar": False, "bonus_2pc": "디버프 상태 적에게 가하는 피해 +12%", "bonus_4pc": "치확 +4% & 디버프 적 치피 최대 +24%", "icon": "71032"},
    {"id": "326", "kind": "relic", "item_key": "relic:326", "name": "천 개의 별이 모인 도시", "is_planar": True, "bonus_2pc": "추가 공격 시 공격력 +24%, 처치 시 전투 중 치피 +24%", "bonus_4pc": "차원 장신구 2세트 전용", "icon": "71061"},
    {"id": "325", "kind": "relic", "item_key": "relic:325", "name": "점가 제로 지점: 펑크로드", "is_planar": True, "bonus_2pc": "환락도 +12% & 환락도에 비례해 치명타 피해 최대 +36%", "bonus_4pc": "차원 장신구 2세트 전용", "icon": "71060"},
    {"id": "324", "kind": "relic", "item_key": "relic:324", "name": "영원의 땅 앰포리어스", "is_planar": True, "bonus_2pc": "치명타 확률 +8% & 기억 정령 필드 존재 시 아군 전체 속도 +8%", "bonus_4pc": "차원 장신구 2세트 전용", "icon": "71055"},
    {"id": "320", "kind": "relic", "item_key": "relic:320", "name": "기묘한 나나 낙원", "is_planar": True, "bonus_2pc": "치명타 피해 +16% & 소환물 존재 시 치피 +32% 추가", "bonus_4pc": "차원 장신구 2세트 전용", "icon": "71045"},
]


def _clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).replace("\xa0", " ").replace("\\n", "\n")
    s = re.sub(r"<color=[^>]+>|</color>|</?unbreak>|</?i>|</?b>|<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _format_hsr_skill_desc(desc: str, params: dict | list | None = None) -> str:
    if not desc:
        return ""
    text = str(desc)
    if isinstance(params, dict):
        for k, v in params.items():
            val = v[0] if isinstance(v, list) and v else v
            try:
                fval = float(val)
                if f"#{k}[i]%" in text or f"#{k}[f1]%" in text:
                    rep = f"{int(round(fval * 100))}%" if abs(fval * 100 - round(fval * 100)) < 0.05 else f"{fval * 100:.1f}%"
                else:
                    rep = str(int(round(fval))) if abs(fval - round(fval)) < 0.01 else f"{fval:.1f}"
            except Exception:
                rep = str(val)
            text = re.sub(rf"#{re.escape(str(k))}\[[^\]]+\]%?", rep, text)
    return _clean_text(text)


def _format_hsr_char_name(cid: str, raw_name: str, path_code: str) -> str:
    name = _clean_text(raw_name).replace("\n", " ").strip()
    if cid == "1001":
        return "Mar. 7th (보존)"
    if cid == "1224":
        return "Mar. 7th (수렵)"
    return name or f"캐릭터 {cid}"


def _should_exclude_hsr_char(cid: str, raw: dict, now_ts: float) -> bool:
    if not cid.isdigit():
        return True
    if int(cid) >= 8000:  # 개척자(주인공) 제외
        return True
    if raw.get("beta"):
        return True
    rel = raw.get("release")
    if isinstance(rel, (int, float)) and rel > now_ts + 86400:
        return True
    return False


def _parse_hsr_items(
    y_avatars: dict | None,
    y_lcs: dict | None,
    sr_avatars: dict | None = None,
    sr_lcs: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    now_ts = time.time()
    chars: list[dict] = []
    lcs: list[dict] = []

    av_src = y_avatars if isinstance(y_avatars, dict) and y_avatars else (sr_avatars or {})
    lc_src = y_lcs if isinstance(y_lcs, dict) and y_lcs else (sr_lcs or {})

    for cid, raw in av_src.items():
        if not isinstance(raw, dict):
            continue
        cid_s = str(raw.get("id") or cid)
        if _should_exclude_hsr_char(cid_s, raw, now_ts):
            continue
        sr_fallback = (sr_avatars or {}).get(cid_s) or {}

        rank = int(raw.get("rank") or raw.get("rarity") or sr_fallback.get("rarity") or 4)
        if rank not in (4, 5):
            continue

        types = raw.get("types") or {}
        path_code = str(types.get("pathType") or raw.get("path") or sr_fallback.get("path") or "Warrior")
        elem_code = str(types.get("combatType") or raw.get("element") or sr_fallback.get("element") or "Physical")
        path_info = HSR_PATH_MAP.get(path_code, HSR_PATH_MAP["Warrior"])
        elem_info = HSR_ELEMENT_MAP.get(elem_code, HSR_ELEMENT_MAP["Physical"])

        raw_name = raw.get("name") or sr_fallback.get("name") or f"캐릭터 {cid_s}"
        name = _format_hsr_char_name(cid_s, raw_name, path_code)

        if rank == 5:
            if cid_s in HSR_STD_5_CHARS:
                pool_type = "상시"
                warpable = True
            elif cid_s in HSR_COLLAB_5_CHARS:
                pool_type = "콜라보 한정"
                warpable = True
            else:
                pool_type = "한정"
                warpable = True
        else:
            if cid_s in HSR_NON_WARP_4_CHARS:
                pool_type = "배포/상점"
                warpable = False
            else:
                pool_type = "상시"
                warpable = True

        chars.append({
            "id": cid_s,
            "kind": "char",
            "item_key": f"char:{cid_s}",
            "name": name,
            "rank": rank,
            "rarity_label": "★★★★★" if rank == 5 else "★★★★",
            "path": path_code,
            "path_name": path_info["name"],
            "path_emoji": path_info["emoji"],
            "path_role": path_info["role"],
            "role_tag": path_info["role_tag"],
            "element": elem_code,
            "element_name": elem_info["name"],
            "element_emoji": elem_info["emoji"],
            "icon": str(raw.get("icon") or cid_s),
            "release": int(raw.get("release") or 0),
            "pool_type": pool_type,
            "warpable": warpable,
        })

    for lid, raw in lc_src.items():
        if not isinstance(raw, dict):
            continue
        lid_s = str(raw.get("id") or lid)
        if not lid_s.isdigit():
            continue
        if raw.get("beta"):
            continue
        sr_fallback = (sr_lcs or {}).get(lid_s) or {}

        rank = int(raw.get("rank") or raw.get("rarity") or sr_fallback.get("rarity") or 3)
        if rank not in (3, 4, 5):
            continue

        types = raw.get("types") or {}
        path_code = str(types.get("pathType") or raw.get("path") or sr_fallback.get("path") or "Warrior")
        path_info = HSR_PATH_MAP.get(path_code, HSR_PATH_MAP["Warrior"])
        name = _clean_text(raw.get("name") or sr_fallback.get("name") or f"광추 {lid_s}").replace("\n", " ").strip()

        if rank == 5:
            if lid_s in HSR_STD_5_LCS:
                warp_source = "standard"
                pool_type = "상시"
                warpable = True
            elif lid_s.startswith(HSR_HERTA_LC_PREFIX):
                warp_source = "herta"
                pool_type = "헤르타 상점"
                warpable = False
            else:
                warp_source = "limited"
                pool_type = "광추한정"
                warpable = True
        elif rank == 4:
            if lid_s.startswith(HSR_EVENT_LC_PREFIX):
                warp_source = "event_shop"
                pool_type = "이벤트/잔재상점"
                warpable = False
            elif lid_s in HSR_FORGOTTEN_HALL_LCS:
                warp_source = "manifest_shop"
                pool_type = "망각의정원/상점"
                warpable = False
            elif lid_s in HSR_BP_LCS:
                warp_source = "bp"
                pool_type = "무명의 공훈"
                warpable = False
            else:
                warp_source = "standard"
                pool_type = "상시"
                warpable = True
        else:
            warp_source = "standard"
            pool_type = "워프 상시"
            warpable = True

        lcs.append({
            "id": lid_s,
            "kind": "lc",
            "item_key": f"lc:{lid_s}",
            "name": name,
            "rank": rank,
            "rarity_label": "★★★★★" if rank == 5 else ("★★★★" if rank == 4 else "★★★"),
            "path": path_code,
            "path_name": path_info["name"],
            "path_emoji": path_info["emoji"],
            "icon": str(raw.get("icon") or lid_s),
            "warp_source": warp_source,
            "pool_type": pool_type,
            "warpable": warpable,
        })

    chars.sort(key=lambda x: (-x["rank"], -x["release"], -int(x["id"]) if x["id"].isdigit() else 0))
    lcs.sort(key=lambda x: (-x["rank"], -int(x["id"]) if x["id"].isdigit() else 0))
    return chars, lcs


def _parse_hsr_relics(yatta_rl: dict | None, sr_rl: dict | None = None) -> list[dict]:
    relics: list[dict] = []
    source = yatta_rl or sr_rl or {}
    for rid, raw in source.items():
        if not isinstance(raw, dict):
            continue
        rid_str = str(raw.get("id") or rid)
        if not rid_str.isdigit():
            continue
        rid_int = int(rid_str)
        name = _clean_text(raw.get("name"))
        if not name or name.startswith("{"):
            continue
        level_list = raw.get("levelList") or []
        max_rank = max([int(x) for x in level_list if str(x).isdigit()] or [5])
        if max_rank < 4:
            continue
        is_planar = bool(raw.get("isPlanarSuit")) or rid_int >= 300
        sk_list = raw.get("skillList") or {}
        if isinstance(sk_list, dict):
            set2 = _format_hsr_skill_desc(sk_list.get("2") or next(iter(sk_list.values()), ""))
            set4 = "" if is_planar else _format_hsr_skill_desc(sk_list.get("4") or "")
        else:
            set2 = ""
            set4 = ""
        icon_raw = str(raw.get("icon") or rid_str)
        s2 = set2 or "2세트 고유 효과 발동"
        s4 = set4 or ("차원 장신구 2세트 전용" if is_planar else "4세트 고유 효과 발동")
        relics.append({
            "id": rid_str,
            "kind": "relic",
            "item_key": f"relic:{rid_str}",
            "name": name,
            "rank": 5 if max_rank >= 5 else 4,
            "rarity_label": "★★★★★" if max_rank >= 5 else "★★★★",
            "is_planar": is_planar,
            "relic_type": "차원 장신구 (2세트)" if is_planar else "터널 유물 (4세트)",
            "set2": s2,
            "set4": "" if is_planar else set4,
            "set_2pc": s2,
            "set_4pc": s4,
            "bonus_2pc": s2,
            "bonus_4pc": s4,
            "icon": icon_raw,
            "pool_type": "차원 장신구" if is_planar else "침식된 터널",
            "warpable": True,
        })
    relics.sort(key=lambda x: (-x["rank"], x["is_planar"], -int(x["id"])))
    return relics


def _normalize_fallback_relics() -> list[dict]:
    out = []
    for r in HSR_EMBEDDED_FALLBACK_RELICS:
        is_pl = bool(r.get("is_planar"))
        s2 = r.get("set2") or r.get("set_2pc") or r.get("bonus_2pc") or "2세트 고유 효과 발동"
        s4 = r.get("set4") or r.get("set_4pc") or r.get("bonus_4pc") or ("차원 장신구 2세트 전용" if is_pl else "4세트 고유 효과 발동")
        out.append({
            **r,
            "kind": "relic",
            "item_key": f"relic:{r['id']}",
            "rank": int(r.get("rank") or 5),
            "rarity_label": "★★★★★",
            "relic_type": "차원 장신구 (2세트)" if is_pl else "터널 유물 (4세트)",
            "set2": s2,
            "set4": "" if is_pl else s4,
            "set_2pc": s2,
            "set_4pc": s4,
            "bonus_2pc": s2,
            "bonus_4pc": s4,
            "icon": str(r.get("icon") or r["id"]),
            "pool_type": "차원 장신구" if is_pl else "침식된 터널",
            "warpable": True,
        })
    return out


def _set_db_state(chars: list[dict], lcs: list[dict], fetched_at: float, relics: list[dict] | None = None):
    global HSR_CHARS, HSR_LIGHT_CONES, HSR_RELICS, HSR_RELIC_MAP, HSR_ALL_ITEMS, _HSR_LAST_FETCH
    HSR_CHARS = chars
    HSR_LIGHT_CONES = lcs
    if relics is not None:
        HSR_RELICS = relics
    elif not HSR_RELICS:
        HSR_RELICS = _normalize_fallback_relics()
    HSR_RELIC_MAP = {r["id"]: r for r in HSR_RELICS}
    merged: dict[str, dict] = {}
    for c in chars:
        merged[c["item_key"]] = c
    for l in lcs:
        merged[l["item_key"]] = l
    for r in HSR_RELICS:
        merged[r["item_key"]] = r
    HSR_ALL_ITEMS = merged
    _HSR_LAST_FETCH = fetched_at


def _normalize_fallback() -> tuple[list[dict], list[dict]]:
    chars = []
    for c in HSR_EMBEDDED_FALLBACK_CHARS:
        pi = HSR_PATH_MAP.get(c["path"], HSR_PATH_MAP["Warrior"])
        ei = HSR_ELEMENT_MAP.get(c["element"], HSR_ELEMENT_MAP["Physical"])
        chars.append({
            **c,
            "kind": "char",
            "item_key": f"char:{c['id']}",
            "rarity_label": "★★★★★" if c["rank"] == 5 else "★★★★",
            "path_name": pi["name"],
            "path_emoji": pi["emoji"],
            "path_role": pi["role"],
            "role_tag": pi["role_tag"],
            "element_name": ei["name"],
            "element_emoji": ei["emoji"],
            "icon": c["id"],
            "warpable": True,
        })
    lcs = []
    for l in HSR_EMBEDDED_FALLBACK_LCS:
        pi = HSR_PATH_MAP.get(l["path"], HSR_PATH_MAP["Warrior"])
        lcs.append({
            **l,
            "kind": "lc",
            "item_key": f"lc:{l['id']}",
            "rarity_label": "★★★★★" if l["rank"] == 5 else ("★★★★" if l["rank"] == 4 else "★★★"),
            "path_name": pi["name"],
            "path_emoji": pi["emoji"],
            "icon": l["id"],
            "warpable": (l["warp_source"] in ("standard", "limited")),
        })
    return chars, lcs


def hydrate_hsr_kr_cache_from_disk() -> bool:
    """디스크의 스타레일 한국어 DB 캐시가 있으면 즉시 메모리에 적재합니다."""
    if not os.path.exists(HSR_CACHE_FILE):
        return False
    try:
        with open(HSR_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if int(payload.get("version") or 1) < HSR_CACHE_VERSION:
            return False
        chars = payload.get("chars") or []
        lcs = payload.get("light_cones") or []
        relics = payload.get("relics") or []
        fetched_at = float(payload.get("fetched_at") or 0.0)
        if chars and lcs and relics:
            _set_db_state(chars, lcs, fetched_at, relics=relics)
            return True
    except Exception:
        pass
    return False


def load_hsr_kr_db(force_refresh: bool = False) -> tuple[list[dict], list[dict]]:
    """붕괴: 스타레일 한국어 DB(캐릭터/광추/유물)를 실시간(sr.yatta.moe & StarRailRes)에서 동기화하고 캐시합니다."""
    with _HSR_DB_LOCK:
        now = time.time()
        if not force_refresh and HSR_CHARS and HSR_LIGHT_CONES and HSR_RELICS and (now - _HSR_LAST_FETCH < HSR_CACHE_TTL):
            return HSR_CHARS, HSR_LIGHT_CONES

        if not force_refresh and (not HSR_CHARS or not HSR_RELICS) and hydrate_hsr_kr_cache_from_disk():
            if now - _HSR_LAST_FETCH < HSR_CACHE_TTL:
                return HSR_CHARS, HSR_LIGHT_CONES

        y_av = y_lc = y_rl = sr_av = sr_lc = None
        try:
            r1 = requests.get("https://sr.yatta.moe/api/v2/kr/avatar", timeout=15)
            r2 = requests.get("https://sr.yatta.moe/api/v2/kr/equipment", timeout=15)
            if r1.status_code == 200 and r2.status_code == 200:
                y_av = (r1.json().get("data") or {}).get("items") or {}
                y_lc = (r2.json().get("data") or {}).get("items") or {}
            try:
                r_rl = requests.get("https://sr.yatta.moe/api/v2/kr/relic", timeout=15)
                if r_rl.status_code == 200:
                    y_rl = (r_rl.json().get("data") or {}).get("items") or {}
            except Exception:
                pass
        except Exception as e:
            print(f"⚠️ [스타레일 yatta 동기화 경고] {e}", flush=True)

        if not (y_av and y_lc):
            try:
                r3 = requests.get("https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_min/kr/characters.json", timeout=15)
                r4 = requests.get("https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_min/kr/light_cones.json", timeout=15)
                if r3.status_code == 200 and r4.status_code == 200:
                    sr_av = r3.json()
                    sr_lc = r4.json()
            except Exception as e:
                print(f"⚠️ [스타레일 StarRailRes 동기화 경고] {e}", flush=True)

        relics = _parse_hsr_relics(y_rl) if y_rl else (HSR_RELICS or _normalize_fallback_relics())
        if not relics:
            relics = _normalize_fallback_relics()

        if (y_av and y_lc) or (sr_av and sr_lc):
            chars, lcs = _parse_hsr_items(y_av, y_lc, sr_av, sr_lc)
            if chars and lcs:
                _set_db_state(chars, lcs, now, relics=relics)
                try:
                    tmp_f = f"{HSR_CACHE_FILE}.tmp"
                    with open(tmp_f, "w", encoding="utf-8") as f:
                        json.dump({
                            "version": HSR_CACHE_VERSION,
                            "fetched_at": now,
                            "chars": chars,
                            "light_cones": lcs,
                            "relics": relics,
                        }, f, ensure_ascii=False)
                    os.replace(tmp_f, HSR_CACHE_FILE)
                except Exception:
                    pass
                return HSR_CHARS, HSR_LIGHT_CONES

        if HSR_CHARS and HSR_LIGHT_CONES:
            return HSR_CHARS, HSR_LIGHT_CONES

        fb_c, fb_l = _normalize_fallback()
        _set_db_state(fb_c, fb_l, 0.0, relics=relics)
        return HSR_CHARS, HSR_LIGHT_CONES


def get_hsr_relics() -> list[dict]:
    if not HSR_RELICS:
        load_hsr_kr_db()
    return HSR_RELICS


def get_hsr_relic_by_id(relic_id: str) -> dict | None:
    if not HSR_RELIC_MAP:
        load_hsr_kr_db()
    return HSR_RELIC_MAP.get(str(relic_id))


def fetch_hsr_detail_kr(item_id: str, kind: str = "char") -> dict:
    """캐릭터/광추/유물 상세 정보(소속·소개 대사·한국어 성우·광추/유물 세트 효과)를 지연 로드 후 캐시합니다."""
    cache_key = f"{kind}:{item_id}"
    with _HSR_DETAIL_LOCK:
        if cache_key in _HSR_DETAIL_CACHE:
            _HSR_DETAIL_CACHE.move_to_end(cache_key)
            return _HSR_DETAIL_CACHE[cache_key]

    if kind == "relic":
        r_obj = get_hsr_relic_by_id(item_id) or {}
        s2 = r_obj.get("set2") or r_obj.get("set_2pc") or ""
        s4 = r_obj.get("set4") or r_obj.get("set_4pc") or ""
        detail_info = {
            "set2": s2,
            "set4": s4,
            "set_2pc": s2,
            "set_4pc": s4,
            "relic_type": r_obj.get("relic_type", "터널 유물"),
            "description": f"2세트: {s2 or '-'}" + (f" / 4세트: {s4}" if s4 else ""),
        }
        with _HSR_DETAIL_LOCK:
            _HSR_DETAIL_CACHE[cache_key] = detail_info
        return detail_info

    endpoint = "avatar" if kind == "char" else "equipment"
    detail_info: dict = {}
    try:
        res = requests.get(f"https://sr.yatta.moe/api/v2/kr/{endpoint}/{item_id}", timeout=10)
        if res.status_code == 200:
            d = res.json().get("data") or {}
            if kind == "char":
                fetter = d.get("fetter") or {}
                cv_obj = fetter.get("cv") if isinstance(fetter.get("cv"), dict) else {}
                cv_kr = (cv_obj.get("CV_KR") or cv_obj.get("KR") or "").strip()
                detail_info = {
                    "faction": _clean_text(fetter.get("faction")),
                    "description": _clean_text(fetter.get("description")),
                    "cv_kr": _clean_text(cv_kr),
                }
            else:
                sk = d.get("skill") or {}
                detail_info = {
                    "description": _clean_text(d.get("description")),
                    "skill_name": _clean_text(sk.get("name")),
                }
    except Exception:
        pass

    with _HSR_DETAIL_LOCK:
        _HSR_DETAIL_CACHE[cache_key] = detail_info
        while len(_HSR_DETAIL_CACHE) > 256:
            _HSR_DETAIL_CACHE.popitem(last=False)
    return detail_info


# ==========================================
# 일러스트 URL / 바이트 캐시 / WebP 리사이즈 (디스코드 7.8MB 한도 준수)
# ==========================================
def get_hsr_item_urls(item: dict, splash: bool = True) -> list[str]:
    iid = str(item.get("id") or item.get("icon") or "")
    kind = item.get("kind", "char")
    if not iid:
        return []
    if kind == "char":
        if splash:
            return [
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/image/character_preview/{iid}.png",
                f"https://sr.yatta.moe/hsr/assets/UI/avatar/large/{iid}.png",
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/character/{iid}.png",
            ]
        return [
            f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/character/{iid}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/avatar/medium/{iid}.png",
        ]
    elif kind == "relic":
        icon_name = str(item.get("icon") or iid)
        slot_idx = item.get("slot_idx")
        urls = []
        if slot_idx is not None:
            urls.append(f"https://sr.yatta.moe/hsr/assets/UI/relic/{iid}_{slot_idx}.png")
            urls.append(f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/relic/{iid}_{slot_idx}.png")
        urls.extend([
            f"https://sr.yatta.moe/hsr/assets/UI/relic/{icon_name}.png",
            f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/relic/{iid}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/relic/{iid}_0.png",
        ])
        return urls
    else:
        if splash:
            return [
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/image/light_cone_preview/{iid}.png",
                f"https://sr.yatta.moe/hsr/assets/UI/equipment/large/{iid}.png",
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/light_cone/{iid}.png",
            ]
        return [
            f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/light_cone/{iid}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/equipment/medium/{iid}.png",
        ]


def get_hsr_primary_image_url(item: dict, splash: bool = True) -> str:
    urls = get_hsr_item_urls(item, splash=splash)
    return urls[0] if urls else ""


def _compress_hsr_if_needed(raw_bytes: bytes, base_name: str, is_splash: bool) -> tuple[bytes, str]:
    if not is_splash or len(raw_bytes) <= 450 * 1024:
        return raw_bytes, f"{base_name}.png"
    try:
        im = Image.open(io.BytesIO(raw_bytes))
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        max_dim = 1080
        if im.width > max_dim or im.height > max_dim:
            im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=88, method=4)
        return buf.getvalue(), f"{base_name}.webp"
    except Exception:
        return raw_bytes, f"{base_name}.png"


def fetch_hsr_item_image_bytes(item: dict, splash: bool = True) -> tuple[bytes | None, str]:
    slot_suffix = f":{item.get('slot_code', '')}" if item.get("kind") == "relic" else ""
    cache_key = f"{'sp' if splash else 'ic'}:{item.get('kind')}:{item.get('id')}{slot_suffix}"
    with _HSR_IMG_LOCK:
        if cache_key in _HSR_IMG_CACHE:
            _HSR_IMG_CACHE.move_to_end(cache_key)
            raw = _HSR_IMG_CACHE[cache_key]
            base_n = f"hsr_{item.get('kind')}_{item.get('id')}"
            return _compress_hsr_if_needed(raw, base_n, is_splash=splash)

    urls = get_hsr_item_urls(item, splash=splash)
    raw_bytes = None
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200 and len(r.content) > 512:
                raw_bytes = r.content
                break
        except Exception:
            continue

    if not raw_bytes:
        return None, "hsr.png"

    with _HSR_IMG_LOCK:
        _HSR_IMG_CACHE[cache_key] = raw_bytes
        while len(_HSR_IMG_CACHE) > 80:
            _HSR_IMG_CACHE.popitem(last=False)

    base_n = f"hsr_{item.get('kind')}_{item.get('id')}"
    return _compress_hsr_if_needed(raw_bytes, base_n, is_splash=splash)


def fetch_hsr_thumb_bytes(item: dict) -> bytes | None:
    slot_suffix = f":{item.get('slot_code', '')}" if item.get("kind") == "relic" else ""
    cache_key = f"{item.get('kind')}:{item.get('id')}{slot_suffix}"
    with _HSR_IMG_LOCK:
        if cache_key in _HSR_THUMB_CACHE:
            _HSR_THUMB_CACHE.move_to_end(cache_key)
            return _HSR_THUMB_CACHE[cache_key]

    urls = get_hsr_item_urls(item, splash=False) + get_hsr_item_urls(item, splash=True)
    raw = None
    for url in urls:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200 and len(r.content) > 512:
                raw = r.content
                break
        except Exception:
            continue

    if raw:
        with _HSR_IMG_LOCK:
            _HSR_THUMB_CACHE[cache_key] = raw
            while len(_HSR_THUMB_CACHE) > 220:
                _HSR_THUMB_CACHE.popitem(last=False)
    return raw


# ==========================================
# KST 시각 연동 은하열차 항법 스케줄 (캐릭터 / 광추 / 유물 시간대별 차별화)
# ==========================================
def get_hsr_time_schedule(now_dt: datetime.datetime | None = None) -> dict:
    """한국 표준시(KST) 시각에 따라 은하열차 캐릭터/광추/유물 워프 보너스와 추천 배너를 다르게 제공합니다."""
    now = now_dt or datetime.datetime.now(core.KST)
    hour = now.hour
    weekday = now.weekday()

    path_rot = [
        ("Warrior", "⚔️ 파멸", "Elation", "🎭 환락"),
        ("Mage", "🎓 지식", "Memory", "🕊️ 기억"),
        ("Rogue", "🏹 수렵", "Priest", "🌿 풍요"),
        ("Warlock", "🕸️ 공허", "Knight", "🛡️ 보존"),
        ("Shaman", "🎵 화합", "Memory", "🕊️ 기억"),
        ("Elation", "🎭 환락", "Warrior", "⚔️ 파멸"),
        ("Memory", "🕊️ 기억", "Shaman", "🎵 화합"),
    ]
    p1_code, p1_lbl, p2_code, p2_lbl = path_rot[weekday % 7]

    if 6 <= hour < 12:
        slot_id = "morning_char"
        slot_name = "🌅 파밍의 여명 항로 (06:00~12:00 KST)"
        rec_banner = "char1"
        rec_label = "🌠 캐릭터 이벤트 워프 집중 시간"
        bonus_desc = f"오전 항로: **{p1_lbl} · {p2_lbl}** 운명의 길 캐릭터 4★/상시 출현 가중치 **1.8배 UP**"
        boost_paths = {p1_code, p2_code}
        relic_4sub_bonus = 0.0
        planar_focus = False
    elif 12 <= hour < 18:
        slot_id = "afternoon_lc"
        slot_name = "☀️ 유광의 정오 항로 (12:00~18:00 KST)"
        rec_banner = "lc"
        rec_label = "🪩 광추 이벤트 워프 집중 시간"
        bonus_desc = f"오후 항로: **{p1_lbl} · {p2_lbl}** 광추 출현 가중치 **1.8배 UP** & 4★ 광추 획득 시 잔재 보너스"
        boost_paths = {p1_code, p2_code}
        relic_4sub_bonus = 0.0
        planar_focus = False
    elif 18 <= hour < 24:
        slot_id = "evening_cavern"
        slot_name = "🌆 침식된 황혼 항로 (18:00~24:00 KST)"
        rec_banner = "relic"
        rec_label = "🕳️ 침식된 터널 · 4세트 유물 집중 시간"
        bonus_desc = "저녁 항로: **터널 유물(4세트)** 드랍 가중치 UP & ★5 유물 **태생 4줄(유효 부옵) 등장 확률 +18% UP**"
        boost_paths = {p1_code, p2_code}
        relic_4sub_bonus = 0.18
        planar_focus = False
    else:
        slot_id = "midnight_planar"
        slot_name = "🌌 시뮬레이션 심야 항로 (00:00~06:00 KST)"
        rec_banner = "relic"
        rec_label = "🪐 차원 분열 · 장신구 & 고점 유물 집중 시간"
        bonus_desc = "심야 항로: **차원 장신구(2세트)** 집중 드랍 & ★5 유물 **태생 4줄 확률 +25% · 치명/속도 부옵 가중치 UP**"
        boost_paths = {p1_code, p2_code}
        relic_4sub_bonus = 0.25
        planar_focus = True

    all_relics = get_hsr_relics()
    r5_list = [r for r in all_relics if r.get("rank") == 5] or all_relics
    if r5_list:
        day_seed = now.timetuple().tm_yday + weekday
        rot_relics = [r5_list[(day_seed * 2 + i) % len(r5_list)] for i in range(min(2, len(r5_list)))]
    else:
        rot_relics = []

    elem_order = ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]
    elem_code = elem_order[(weekday * 2 + (hour // 6)) % len(elem_order)]
    elem_info = HSR_ELEMENT_MAP.get(elem_code, HSR_ELEMENT_MAP["Quantum"])
    p1_info = HSR_PATH_MAP.get(p1_code, HSR_PATH_MAP["Warrior"])
    phase_emoji = slot_name.split()[0] if slot_name else "🚄"
    now_str = now.strftime("%H:%M KST")

    return {
        "now_str": now_str,
        "hour_str": now_str,
        "hour": hour,
        "slot_id": slot_id,
        "slot_name": slot_name,
        "phase_emoji": phase_emoji,
        "phase_name": slot_name,
        "recommended_banner": rec_banner,
        "rec_banner": rec_banner,
        "recommended_label": rec_label,
        "bonus_desc": bonus_desc,
        "buff_summary": f"속성 {elem_info['emoji']}{elem_info['name']} · 운명 {p1_lbl}/{p2_lbl} UP",
        "char_elem_emoji": elem_info["emoji"],
        "char_elem_name": elem_info["name"],
        "lc_path_emoji": p1_info["emoji"],
        "lc_path_name": p1_info["name"],
        "boost_paths": boost_paths,
        "boost_path_labels": f"{p1_lbl} / {p2_lbl}",
        "relic_4sub_bonus": relic_4sub_bonus,
        "planar_focus": planar_focus,
        "FeaturedRelics": rot_relics,
        "featured_relic_sets": rot_relics,
    }


# ==========================================
# 은하열차 3종 비주얼 테마 (캐릭터 / 광추 / 유물) 5x2 10연 워프 합성 이미지
# ==========================================
def build_hsr_10pull_grid_bytes(drawn: list[dict], banner_key: str = "char1", header_tag: str = "") -> io.BytesIO | None:
    """배너/아이템 종류(캐릭터/광추/유물)와 KST 시각에 맞춰 서로 다른 스타일의 5x2 카드로 렌더링합니다."""
    if Image is None or ImageDraw is None:
        return None
    if not drawn:
        drawn = [{"name": "워프 데이터 없음", "rank": 3, "kind": "lc", "id": ""}]

    sched = get_hsr_time_schedule()
    if banner_key == "relic" or any(d.get("kind") == "relic" for d in drawn):
        visual_mode = "relic"
    elif banner_key == "lc":
        visual_mode = "lc"
    else:
        visual_mode = "char"

    cols = 5 if len(drawn) > 1 else 1
    rows = 2 if len(drawn) > 5 else 1
    card_w, card_h = (194, 244) if cols == 5 else (320, 386)
    pad_x, pad_y = 14, 14
    margin_x, top_h, bot_h = 24, 56, 24
    width = margin_x * 2 + cols * card_w + (cols - 1) * pad_x
    height = top_h + rows * card_h + (rows - 1) * pad_y + bot_h

    canvas = Image.new("RGBA", (width, height), (14, 9, 30, 255))
    bg_draw = ImageDraw.Draw(canvas)
    for y in range(height):
        t = y / max(1, height - 1)
        if visual_mode == "relic":
            r = int(10 + 18 * t)
            g = int(18 + 20 * t)
            b = int(34 + 34 * t)
        elif visual_mode == "lc":
            r = int(14 + 26 * t)
            g = int(16 + 18 * t)
            b = int(42 + 38 * t)
        else:
            r = int(13 + 17 * t)
            g = int(8 + 11 * t)
            b = int(30 + 30 * t)
        bg_draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    srng = random.Random(42 + len(drawn))
    for _ in range(95):
        sx = srng.randint(8, width - 8)
        sy = srng.randint(8, height - 8)
        sb = srng.randint(150, 255)
        bg_draw.point((sx, sy), fill=(sb, int(sb * 0.92), 255, 190))

    if visual_mode == "relic":
        bg_draw.rectangle([0, 0, width, 4], fill=(0, 224, 218, 255))
        bg_draw.rectangle([0, height - 3, width, height], fill=(248, 200, 92, 220))
        hdr_color = (146, 248, 245, 255)
        mode_prefix = "🕳️ 침식된 터널 · 유물 토벌 결과"
    elif visual_mode == "lc":
        bg_draw.rectangle([0, 0, width, 4], fill=(124, 212, 255, 255))
        bg_draw.rectangle([0, height - 3, width, height], fill=(196, 146, 255, 220))
        hdr_color = (196, 232, 255, 255)
        mode_prefix = "🪩 세월의 응고 · 광추 워프 결과"
    else:
        bg_draw.rectangle([0, 0, width, 4], fill=(248, 200, 92, 255))
        bg_draw.rectangle([0, height - 3, width, height], fill=(166, 108, 255, 210))
        hdr_color = (255, 224, 146, 255)
        mode_prefix = "★ 은하열차 캐릭터 워프 결과"

    b_cfg = HSR_BANNER_CONFIGS.get(banner_key, HSR_BANNER_CONFIGS["char1"])
    f_hdr = core._get_grid_font(18, bold=True)
    f_sub = core._get_grid_font(12, bold=False)
    f_name = core._get_grid_font(13 if cols == 5 else 18, bold=True)
    f_badge = core._get_grid_font(11 if cols == 5 else 13, bold=True)

    title_txt = core._sanitize_grid_text(f"{mode_prefix} — {b_cfg['short_name']}")
    bg_draw.text((margin_x, 10), title_txt, font=f_hdr, fill=hdr_color)

    sub_left = core._sanitize_grid_text(f"{sched['slot_name']} · {sched['recommended_label']}")
    bg_draw.text((margin_x, 34), sub_left, font=f_sub, fill=(204, 196, 238, 225))

    if header_tag:
        ht = core._sanitize_grid_text(header_tag)
        tw = bg_draw.textlength(ht, font=f_sub)
        bg_draw.text((width - margin_x - tw, 14), ht, font=f_sub, fill=(208, 186, 255, 235))

    thumb_map: dict[int, bytes | None] = {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {idx: ex.submit(fetch_hsr_thumb_bytes, item) for idx, item in enumerate(drawn)}
        for idx, fut in futs.items():
            try:
                thumb_map[idx] = fut.result(timeout=10)
            except Exception:
                thumb_map[idx] = None

    for idx, item in enumerate(drawn):
        r_idx = idx // cols
        c_idx = idx % cols
        x0 = margin_x + c_idx * (card_w + pad_x)
        y0 = top_h + r_idx * (card_h + pad_y)

        rank = int(item.get("rank", 3))
        kind = item.get("kind", "lc")
        elem_code = item.get("element", "Physical")
        elem_rgb = HSR_ELEMENT_MAP.get(elem_code, {}).get("color", (164, 128, 255))

        if rank == 5:
            card_top = (28, 52, 54) if kind == "relic" else ((34, 42, 74) if kind == "lc" else (66, 44, 14))
            card_bot = (16, 24, 38) if kind == "relic" else ((22, 20, 48) if kind == "lc" else (34, 19, 44))
            border_c = (255, 206, 86, 255)
            accent_c = (72, 242, 230, 255) if kind == "relic" else ((130, 220, 255, 255) if kind == "lc" else (255, 118, 178, 255))
            stars_txt = "★★★★★"
            star_c = (255, 226, 112, 255)
        elif rank == 4:
            card_top = (34, 28, 72) if kind == "relic" else (44, 24, 82)
            card_bot = (18, 16, 42)
            border_c = (176, 114, 255, 255)
            accent_c = (118, 224, 255, 255)
            stars_txt = "★★★★"
            star_c = (212, 168, 255, 255)
        else:
            card_top = (22, 34, 62)
            card_bot = (14, 20, 38)
            border_c = (94, 178, 255, 235)
            accent_c = (118, 210, 255, 180)
            stars_txt = "★★★"
            star_c = (146, 214, 255, 255)

        card_im = Image.new("RGBA", (card_w, card_h), card_bot + (255,))
        cd = ImageDraw.Draw(card_im)
        for cy in range(card_h):
            t = cy / max(1, card_h - 1)
            cr = int(card_top[0] + (card_bot[0] - card_top[0]) * t)
            cg = int(card_top[1] + (card_bot[1] - card_top[1]) * t)
            cb = int(card_top[2] + (card_bot[2] - card_top[2]) * t)
            cd.line([(0, cy), (card_w, cy)], fill=(cr, cg, cb, 255))

        img_area_h = card_h - (58 if cols == 5 else 76)
        if kind == "relic":
            cx_m, cy_m = card_w // 2, img_area_h // 2 + 2
            rad = min(card_w, img_area_h) // 2 - 14
            ring_col = (72, 242, 230, 85) if rank == 5 else (176, 114, 255, 70)
            cd.ellipse([cx_m - rad, cy_m - rad, cx_m + rad, cy_m + rad], outline=ring_col, width=2)
            cd.ellipse([cx_m - rad + 10, cy_m - rad + 10, cx_m + rad - 10, cy_m + rad - 10], fill=(32, 64, 78, 42))
        elif kind == "lc":
            cd.rounded_rectangle([14, 12, card_w - 14, img_area_h - 8], radius=8, outline=accent_c[:3] + (90,), width=1)
        elif rank >= 4:
            glow_w = card_w - 20
            cd.ellipse([10, 8, 10 + glow_w, 8 + glow_w], fill=elem_rgb + (36,))

        tb = thumb_map.get(idx)
        if tb:
            try:
                art = Image.open(io.BytesIO(tb)).convert("RGBA")
                pad_art = 16 if kind == "relic" else (10 if kind == "lc" else 4)
                max_aw = card_w - pad_art * 2
                max_ah = img_area_h - 14
                art.thumbnail((max_aw, max_ah), Image.Resampling.LANCZOS)
                ax = (card_w - art.width) // 2
                ay = (img_area_h - art.height) // 2 + 4
                card_im.alpha_composite(art, (ax, ay))
            except Exception:
                pass

        bar_y0 = img_area_h
        cd.rectangle([0, bar_y0, card_w, card_h], fill=(12, 9, 26, 236))
        cd.line([(0, bar_y0), (card_w, bar_y0)], fill=border_c, width=2)

        if kind == "relic":
            slot_lbl = core._sanitize_grid_text(f"{item.get('slot_name', '유물')}")
            cd.rounded_rectangle([6, 6, 72, 24], radius=4, fill=(18, 42, 56, 235), outline=accent_c, width=1)
            cd.text((11, 8), slot_lbl, font=f_badge, fill=(215, 255, 252, 255))
            grade_lbl = str(item.get("grade", "A"))
            g_col = (255, 198, 62, 245) if grade_lbl in ("SSS", "SS", "S") else (112, 184, 255, 230)
            cd.rounded_rectangle([card_w - 42, 6, card_w - 6, 24], radius=4, fill=g_col)
            cd.text((card_w - 34, 8), grade_lbl, font=f_badge, fill=(18, 14, 22, 255))
        else:
            if item.get("is_new"):
                cd.rounded_rectangle([7, 7, 47, 25], radius=4, fill=(255, 198, 62, 245))
                cd.text((13, 9), "NEW", font=f_badge, fill=(22, 16, 12, 255))
            elif kind == "char" and "new_eidolon" in item:
                elbl = f"E{item['new_eidolon']}"
                cd.rounded_rectangle([7, 7, 39, 25], radius=4, fill=(138, 72, 235, 235))
                cd.text((13, 9), elbl, font=f_badge, fill=(255, 245, 255, 255))
            elif kind == "lc" and rank >= 4 and "new_super" in item:
                slbl = f"S{item['new_super']}"
                cd.rounded_rectangle([7, 7, 39, 25], radius=4, fill=(64, 152, 235, 235))
                cd.text((13, 9), slbl, font=f_badge, fill=(245, 252, 255, 255))

            if item.get("is_pickup"):
                cd.rounded_rectangle([card_w - 39, 7, card_w - 7, 25], radius=4, fill=(255, 76, 148, 245))
                cd.text((card_w - 31, 9), "UP", font=f_badge, fill=(255, 255, 255, 255))

        disp_name = core._sanitize_grid_text(item.get("name", ""))
        max_tw = card_w - 14
        while len(disp_name) > 2 and cd.textlength(disp_name, font=f_name) > max_tw:
            disp_name = disp_name[:-2] + "…"
        cd.text((8, bar_y0 + 6), disp_name, font=f_name, fill=(248, 244, 255, 255))

        if kind == "relic":
            main_stat = item.get("main_stat", "주옵션")
            sub_cnt = len(item.get("substats") or [])
            meta_txt = f"{stars_txt} {main_stat} ({sub_cnt}부옵)"
        elif kind == "char":
            path_kr = item.get("path_name", "")
            meta_txt = f"{stars_txt} {item.get('element_name', '')}·{path_kr}"
        else:
            path_kr = item.get("path_name", "")
            meta_txt = f"{stars_txt} {path_kr} 광추"
        meta_txt = core._sanitize_grid_text(meta_txt)
        while len(meta_txt) > 3 and cd.textlength(meta_txt, font=f_badge) > max_tw:
            meta_txt = meta_txt[:-2] + "…"
        cd.text((8, bar_y0 + (28 if cols == 5 else 38)), meta_txt, font=f_badge, fill=star_c)

        bw = 3 if rank == 5 else (2 if rank == 4 else 1)
        cd.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=8, outline=border_c, width=bw)
        if rank == 5:
            cd.rounded_rectangle([4, 4, card_w - 5, card_h - 5], radius=6, outline=accent_c, width=1)
        elif rank == 4:
            cd.rounded_rectangle([3, 3, card_w - 4, card_h - 4], radius=6, outline=accent_c, width=1)

        canvas.alpha_composite(card_im, (x0, y0))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


# ==========================================
# 유저 계정 데이터 구조 & 워프 확률 엔진 (캐릭터 / 광추 / 유물)
# ==========================================
def ensure_hsr_user(data: dict, guild_id: int, user_id: int) -> dict:
    users_root = data.setdefault("hsr_users", {})
    g_map = users_root.setdefault(str(guild_id or 0), {})
    u_data = g_map.setdefault(str(user_id), {})
    u_data.setdefault("items", {})
    u_data.setdefault("relics", [])
    u_data.setdefault("relic_seq", 0)
    u_data.setdefault("total_pulls", 0)
    # 캐릭터 이벤트 워프 스택 (①/② 공유)
    u_data.setdefault("pity_char", 0)
    u_data.setdefault("guaranteed_char", False)
    u_data.setdefault("pity_4_char", 0)
    u_data.setdefault("guaranteed_4_char", False)
    # 광추 이벤트 워프 스택
    u_data.setdefault("pity_lc", 0)
    u_data.setdefault("guaranteed_lc", False)
    u_data.setdefault("pity_4_lc", 0)
    u_data.setdefault("guaranteed_4_lc", False)
    # 침식된 터널 유물 토벌 스택
    u_data.setdefault("pity_relic", 0)
    u_data.setdefault("pity_4_relic", 0)
    u_data.setdefault("target_relic_set", None)
    # 상시 워프 스택 & 300뽑 5성 선택권
    u_data.setdefault("pity_standard", 0)
    u_data.setdefault("pity_4_standard", 0)
    u_data.setdefault("standard_total_pulls", 0)
    u_data.setdefault("standard_300_claimed", False)
    # 고유 재화
    u_data.setdefault("starlight", 0)            # 꺼지지 않는 별빛
    u_data.setdefault("embers", 0)               # 불멸의 잔재
    u_data.setdefault("herta_bond", 4)           # 헤르타 채권 (초기 환영 지급 4장)
    u_data.setdefault("herta_progress", 0)       # 10연차당 +1 헤르타 채권 누적 카운터
    u_data.setdefault("special_pass", 0)         # 별의 궤도 전용티켓
    u_data.setdefault("standard_pass", 0)        # 별의 궤도 티켓
    u_data.setdefault("traveler_guide", 0)       # 여행 가이드 (레벨업 Lv.1~80)
    u_data.setdefault("relic_remains", 200)      # 유물 잔해 (합성기 100개 -> ★5 유물 1개)
    u_data.setdefault("self_modeling_resin", 2)  # 자가 변형 레진 (주옵션 확정 주조)
    u_data.setdefault("shop_monthly", {})
    u_data.setdefault("party", [])               # 4인 파티 item_key 목록
    u_data.setdefault("profile_char", None)      # 개척자 카드 대표 캐릭터
    u_data.setdefault("profile_note", "")        # 한마디 상태 문구
    u_data.setdefault("history", [])
    return u_data


def resolve_effective_hsr_pickup(pickup_cfg: dict | None) -> dict:
    """설정된 스타레일 워프 픽업을 실제 캐릭터/광추/유물 객체로 해석합니다."""
    chars, lcs = load_hsr_kr_db()
    relics = get_hsr_relics()
    by_char = {c["id"]: c for c in chars}
    by_lc = {l["id"]: l for l in lcs}
    by_rl = {r["id"]: r for r in relics}
    cfg = copy.deepcopy(pickup_cfg or {})

    lim_5_chars = [c for c in chars if c["rank"] == 5 and c["pool_type"] in ("한정", "콜라보 한정")]
    pool_4_chars = [c for c in chars if c["rank"] == 4 and c["warpable"]]
    lim_5_lcs = [l for l in lcs if l["rank"] == 5 and l["warp_source"] == "limited"]
    std_4_lcs = [l for l in lcs if l["rank"] == 4 and l["warp_source"] == "standard"]

    c1_id = cfg.get("char1")
    c2_id = cfg.get("char2")
    if not c1_id or c1_id not in by_char:
        c1_id = lim_5_chars[0]["id"] if lim_5_chars else (chars[0]["id"] if chars else None)
    if not c2_id or c2_id not in by_char:
        cand = [c["id"] for c in lim_5_chars if c["id"] != c1_id]
        c2_id = cand[0] if cand else c1_id

    c4_ids = [cid for cid in (cfg.get("char_4_ids") or []) if cid in by_char][:3]
    if len(c4_ids) < 3:
        for c in pool_4_chars:
            if c["id"] not in c4_ids:
                c4_ids.append(c["id"])
            if len(c4_ids) >= 3:
                break

    l1_id = cfg.get("lc_1")
    l2_id = cfg.get("lc_2")
    if not l1_id or l1_id not in by_lc:
        l1_id = lim_5_lcs[0]["id"] if lim_5_lcs else (lcs[0]["id"] if lcs else None)
    if not l2_id or l2_id not in by_lc:
        cand_l = [l["id"] for l in lim_5_lcs if l["id"] != l1_id]
        l2_id = cand_l[0] if cand_l else l1_id

    l4_ids = [lid for lid in (cfg.get("lc_4_ids") or []) if lid in by_lc and by_lc[lid].get("warpable")][:3]
    if len(l4_ids) < 3:
        for l in std_4_lcs:
            if l["id"] not in l4_ids:
                l4_ids.append(l["id"])
            if len(l4_ids) >= 3:
                break

    sched = get_hsr_time_schedule()
    feat_relics = sched.get("FeaturedRelics") or relics[:2]
    r1 = by_rl.get(str(cfg.get("relic_1") or "")) or (feat_relics[0] if feat_relics else (relics[0] if relics else None))
    r2 = by_rl.get(str(cfg.get("relic_2") or "")) or (feat_relics[1] if len(feat_relics) > 1 else r1)

    return {
        "banner_name": cfg.get("banner_name") or "은하열차 이벤트 워프",
        "version_label": cfg.get("version_label") or "라이브 동기화",
        "char1": by_char.get(c1_id),
        "char2": by_char.get(c2_id),
        "char_4": [by_char[i] for i in c4_ids if i in by_char],
        "lc_1": by_lc.get(l1_id),
        "lc_2": by_lc.get(l2_id),
        "lc_4": [by_lc[i] for i in l4_ids if i in by_lc],
        "relic_1": r1,
        "relic_2": r2,
        "raw": cfg,
    }


def _hsr_soft_pity_prob(pity_after: int, banner_key: str) -> float:
    if banner_key == "relic":
        if pity_after >= 10:
            return 1.0
        if pity_after >= 7:
            return min(1.0, 0.16 + 0.24 * (pity_after - 6))
        return 0.16
    if banner_key == "lc":
        if pity_after >= 80:
            return 1.0
        if pity_after >= 66:
            return min(1.0, 0.008 + 0.07 * (pity_after - 65))
        return 0.008
    else:
        if pity_after >= 90:
            return 1.0
        if pity_after >= 74:
            return min(1.0, 0.006 + 0.06 * (pity_after - 73))
        return 0.006


def _hsr_soft_4_prob(pity4_after: int, banner_key: str) -> float:
    if banner_key == "relic":
        return 1.0
    base = 0.066 if banner_key == "lc" else 0.051
    if pity4_after >= 10:
        return 1.0
    if pity4_after == 9:
        return base + 0.51
    return base


def compute_hsr_relic_score(piece: dict) -> tuple[float, float, str]:
    """스타레일 유물 치명타 가치(CV = 치확*2 + 치피) 및 종합 점수(RV: 치명+속도+격특+공% 합산)와 등급을 계산합니다."""
    cv = 0.0
    rv = 0.0
    for s in piece.get("substats") or []:
        nm = s.get("name", "")
        val = float(s.get("value", 0.0))
        if nm == "치명타 확률":
            cv += val * 2.0
            rv += val * 2.0
        elif nm == "치명타 피해":
            cv += val
            rv += val
        elif nm == "속도":
            rv += val * 2.5
        elif nm in ("격파 특수효과", "공격력%", "효과 명중"):
            rv += val * 0.75
    cv = round(cv, 1)
    rv = round(rv, 1)
    if rv >= 46.0 or cv >= 38.0:
        grade = "SSS"
    elif rv >= 38.0 or cv >= 30.0:
        grade = "SS"
    elif rv >= 30.0 or cv >= 22.0:
        grade = "S"
    elif rv >= 20.0:
        grade = "A"
    else:
        grade = "B"
    return cv, rv, grade


def _generate_hsr_relic_piece(
    relic_set: dict,
    rank: int,
    rng: random.Random,
    sched: dict | None = None,
    forced_slot_code: str | None = None,
    forced_main_stat: str | None = None,
) -> dict:
    is_planar = bool(relic_set.get("is_planar"))
    valid_slots = [s for s in HSR_RELIC_SLOTS if bool(s["is_planar"]) == is_planar]
    if forced_slot_code:
        f_norm = str(forced_slot_code).strip().upper()
        slot_info = next(
            (s for s in valid_slots if str(s.get("code", "")).upper() == f_norm or str(s.get("key", "")).upper() == f_norm),
            None,
        ) or rng.choice(valid_slots)
    else:
        slot_info = rng.choice(valid_slots)

    if forced_main_stat and forced_main_stat in slot_info["main_pool"]:
        main_stat = forced_main_stat
    else:
        main_stat = rng.choice(slot_info["main_pool"])

    four_sub_prob = (0.25 if rank == 5 else 0.10) + float((sched or {}).get("relic_4sub_bonus") or 0.0)
    sub_cnt = (4 if rng.random() < min(0.75, four_sub_prob) else 3) if rank == 5 else (3 if rng.random() < 0.7 else 2)

    cand_subs = [s for s in HSR_RELIC_SUBSTATS if s[0] != main_stat]
    chosen_subs = []
    pool_copy = list(cand_subs)
    for _ in range(min(sub_cnt, len(pool_copy))):
        weights = []
        for s_name, _, _ in pool_copy:
            w = 1.0
            if (sched or {}).get("planar_focus") and s_name in ("치명타 확률", "치명타 피해", "속도"):
                w = 1.45
            weights.append(w)
        picked = rng.choices(pool_copy, weights=weights, k=1)[0]
        pool_copy.remove(picked)
        s_name, tiers, unit = picked
        val = round(rng.choice(tiers) * (1.0 if rank == 5 else 0.8), 1 if unit == "%" else 0)
        chosen_subs.append({"name": s_name, "value": val, "unit": unit, "rolls": 1})

    m_pair = HSR_RELIC_MAIN_VALUES.get((rank, main_stat)) or HSR_RELIC_MAIN_VALUES.get(main_stat) or ("+6.9%", "+43.2%")
    m_val_str = m_pair[0] if isinstance(m_pair, tuple) else str(m_pair)
    uid_str = f"rel_{relic_set['id']}_{slot_info['idx']}_{int(time.time() * 1000) % 10000000}_{rng.randint(100, 999)}"
    piece = {
        "uid": uid_str,
        "id": relic_set["id"],
        "kind": "relic",
        "item_key": f"relic:{relic_set['id']}",
        "name": relic_set["name"],
        "rank": rank,
        "rarity_label": "★★★★★" if rank == 5 else "★★★★",
        "is_planar": is_planar,
        "relic_type": relic_set.get("relic_type", "터널 유물"),
        "slot_code": slot_info["code"],
        "slot_idx": slot_info["idx"],
        "slot_name": slot_info["name"],
        "slot_emoji": slot_info["emoji"],
        "main_stat": main_stat,
        "main_value": m_val_str,
        "substats": chosen_subs,
        "init_sub_count": len(chosen_subs),
        "level": 0,
        "set2": relic_set.get("set2", ""),
        "set4": relic_set.get("set4", ""),
        "set_2pc": relic_set.get("set_2pc") or relic_set.get("set2", ""),
        "set_4pc": relic_set.get("set_4pc") or relic_set.get("set4", ""),
        "icon": relic_set.get("icon", relic_set["id"]),
        "pool_type": relic_set.get("pool_type", "침식된 터널"),
    }
    cv, rv, grade = compute_hsr_relic_score(piece)
    piece["cv"] = cv
    piece["rv"] = rv
    piece["score"] = rv
    piece["grade"] = grade
    return piece


def _roll_single_hsr(
    state: dict,
    banner_key: str,
    eff_pickup: dict,
    std_5_chars: list[dict],
    std_4_chars: list[dict],
    std_5_lcs: list[dict],
    warp_3_lcs: list[dict],
    std_4_lcs: list[dict],
    rng: random.Random,
    sched: dict | None = None,
) -> dict:
    sched = sched or get_hsr_time_schedule()
    boost_paths = sched.get("boost_paths") or set()

    def _weighted_choice(items: list[dict], boost_mult: float = 1.8) -> dict:
        if not items:
            return {}
        if not boost_paths:
            return rng.choice(items)
        weights = [boost_mult if it.get("path") in boost_paths else 1.0 for it in items]
        return rng.choices(items, weights=weights, k=1)[0]

    if banner_key == "relic":
        state["pity_relic"] = int(state.get("pity_relic", 0)) + 1
        p5 = _hsr_soft_pity_prob(state["pity_relic"], "relic")
        roll = rng.random()
        all_relics = get_hsr_relics()
        r5_sets = [r for r in all_relics if r.get("rank") == 5] or all_relics

        target_id = str(state.get("target_relic_set") or "")
        target_set = get_hsr_relic_by_id(target_id) if target_id else None
        if not target_set:
            if sched.get("planar_focus"):
                planar_sets = [r for r in r5_sets if r.get("is_planar")]
                target_set = rng.choice(planar_sets) if planar_sets else (eff_pickup.get("relic_1") or r5_sets[0])
            else:
                cavern_sets = [r for r in r5_sets if not r.get("is_planar")]
                target_set = eff_pickup.get("relic_1") or (rng.choice(cavern_sets) if cavern_sets else r5_sets[0])

        if roll < p5:
            pity_used = state["pity_relic"]
            state["pity_relic"] = 0
            if rng.random() < 0.75 and target_set:
                chosen_set = target_set
                is_up = True
            else:
                chosen_set = rng.choice(r5_sets)
                is_up = (target_set and chosen_set["id"] == target_set["id"])
            piece = _generate_hsr_relic_piece(chosen_set, 5, rng, sched=sched)
            piece["is_pickup"] = bool(is_up)
            piece["pity_used"] = pity_used
            return piece
        else:
            chosen_set = target_set if (target_set and rng.random() < 0.65) else rng.choice(r5_sets)
            piece = _generate_hsr_relic_piece(chosen_set, 4, rng, sched=sched)
            piece["is_pickup"] = False
            return piece

    if banner_key in ("char1", "char2"):
        state["pity_char"] += 1
        state["pity_4_char"] += 1
        p5 = _hsr_soft_pity_prob(state["pity_char"], banner_key)
        p4 = _hsr_soft_4_prob(state["pity_4_char"], banner_key)
        roll = rng.random()

        featured_c = eff_pickup["char1"] if banner_key == "char1" else eff_pickup["char2"]
        if not featured_c:
            featured_c = _weighted_choice(std_5_chars)

        if roll < p5:
            pity_used = state["pity_char"]
            state["pity_char"] = 0
            if state["guaranteed_char"] or rng.random() < 0.50:
                picked = dict(featured_c)
                picked["is_pickup"] = True
                state["guaranteed_char"] = False
            else:
                picked = dict(_weighted_choice(std_5_chars))
                picked["is_pickup"] = False
                state["guaranteed_char"] = True
            picked["pity_used"] = pity_used
            return picked

        if roll < p5 + p4:
            state["pity_4_char"] = 0
            c4_pickups = eff_pickup["char_4"]
            p4_ids = {c["id"] for c in c4_pickups}
            if c4_pickups and (state["guaranteed_4_char"] or rng.random() < 0.50):
                picked = dict(_weighted_choice(c4_pickups))
                picked["is_pickup"] = True
                state["guaranteed_4_char"] = False
            else:
                if c4_pickups:
                    state["guaranteed_4_char"] = True
                off_pool = [c for c in std_4_chars if c["id"] not in p4_ids] + std_4_lcs
                picked = dict(_weighted_choice(off_pool or std_4_lcs))
                picked["is_pickup"] = False
            return picked

        picked = dict(_weighted_choice(warp_3_lcs))
        picked["is_pickup"] = False
        return picked

    elif banner_key == "lc":
        state["pity_lc"] += 1
        state["pity_4_lc"] += 1
        p5 = _hsr_soft_pity_prob(state["pity_lc"], "lc")
        p4 = _hsr_soft_4_prob(state["pity_4_lc"], "lc")
        roll = rng.random()

        featured_l = eff_pickup["lc_1"] or eff_pickup["lc_2"]
        if not featured_l:
            featured_l = _weighted_choice(std_5_lcs)

        if roll < p5:
            pity_used = state["pity_lc"]
            state["pity_lc"] = 0
            if state["guaranteed_lc"] or rng.random() < 0.75:
                picked = dict(featured_l)
                picked["is_pickup"] = True
                state["guaranteed_lc"] = False
            else:
                picked = dict(_weighted_choice(std_5_lcs))
                picked["is_pickup"] = False
                state["guaranteed_lc"] = True
            picked["pity_used"] = pity_used
            return picked

        if roll < p5 + p4:
            state["pity_4_lc"] = 0
            l4_pickups = eff_pickup["lc_4"]
            l4_ids = {l["id"] for l in l4_pickups}
            if l4_pickups and (state["guaranteed_4_lc"] or rng.random() < 0.75):
                picked = dict(_weighted_choice(l4_pickups))
                picked["is_pickup"] = True
                state["guaranteed_4_lc"] = False
            else:
                if l4_pickups:
                    state["guaranteed_4_lc"] = True
                off_pool = std_4_chars + [l for l in std_4_lcs if l["id"] not in l4_ids]
                picked = dict(_weighted_choice(off_pool or std_4_lcs))
                picked["is_pickup"] = False
            return picked

        picked = dict(_weighted_choice(warp_3_lcs))
        picked["is_pickup"] = False
        return picked

    else:  # standard
        state["pity_standard"] += 1
        state["pity_4_standard"] += 1
        p5 = _hsr_soft_pity_prob(state["pity_standard"], "standard")
        p4 = _hsr_soft_4_prob(state["pity_4_standard"], "standard")
        roll = rng.random()

        if roll < p5:
            pity_used = state["pity_standard"]
            state["pity_standard"] = 0
            if rng.random() < 0.50:
                picked = dict(_weighted_choice(std_5_chars))
            else:
                picked = dict(_weighted_choice(std_5_lcs))
            picked["is_pickup"] = False
            picked["pity_used"] = pity_used
            return picked

        if roll < p5 + p4:
            state["pity_4_standard"] = 0
            if rng.random() < 0.50:
                picked = dict(_weighted_choice(std_4_chars))
            else:
                picked = dict(_weighted_choice(std_4_lcs))
            picked["is_pickup"] = False
            return picked

        picked = dict(_weighted_choice(warp_3_lcs))
        picked["is_pickup"] = False
        return picked


def _apply_hsr_item_to_account(u_data: dict, item: dict, now_iso: str) -> tuple[int, int]:
    """유저 스타레일 보관함에 캐릭터/광추/유물을 추가하고 성혼/중첩/유물 잔해 및 별빛/잔재를 계산합니다."""
    items_map = u_data.setdefault("items", {})
    i_key = item["item_key"]
    rank = int(item.get("rank", 3))
    kind = item.get("kind", "lc")

    if kind == "relic":
        relic_list = u_data.setdefault("relics", [])
        seq = int(u_data.get("relic_seq", 0)) + 1
        u_data["relic_seq"] = seq
        uid = f"R{seq}"
        existing_set = items_map.get(i_key)
        item["is_new"] = existing_set is None
        item["uid"] = uid

        if existing_set:
            existing_set["count"] = int(existing_set.get("count", 1)) + 1
            existing_set["last_obtained_at"] = now_iso
            if rank > int(existing_set.get("rank", 4)):
                existing_set["rank"] = rank
                existing_set["rarity_label"] = "★★★★★"
        else:
            items_map[i_key] = {
                "id": item["id"],
                "kind": "relic",
                "item_key": i_key,
                "name": item["name"],
                "rank": rank,
                "rarity_label": item["rarity_label"],
                "is_planar": bool(item.get("is_planar")),
                "relic_type": item.get("relic_type", "터널 유물"),
                "set2": item.get("set2", ""),
                "set4": item.get("set4", ""),
                "pool_type": item.get("pool_type", "침식된 터널"),
                "count": 1,
                "level": 0,
                "locked": (rank == 5),
                "obtained_at": now_iso,
                "last_obtained_at": now_iso,
            }

        if rank == 5:
            piece_rec = {
                "uid": uid,
                "set_id": item["id"],
                "name": item["name"],
                "rank": 5,
                "rarity_label": item.get("rarity_label", "★★★★★"),
                "is_planar": bool(item.get("is_planar")),
                "slot_code": item.get("slot_code", "HEAD"),
                "slot_idx": item.get("slot_idx", 0),
                "slot_name": item.get("slot_name", "머리"),
                "slot_emoji": item.get("slot_emoji", "🪖"),
                "main_stat": item.get("main_stat", "HP"),
                "main_value": item.get("main_value", "705"),
                "substats": copy.deepcopy(item.get("substats") or []),
                "level": int(item.get("level", 0)),
                "cv": float(item.get("cv", 0.0)),
                "rv": float(item.get("rv", 0.0)),
                "score": float(item.get("score", item.get("rv", 0.0))),
                "grade": item.get("grade", "A"),
                "locked": item.get("grade") in ("SSS", "SS"),
                "obtained_at": now_iso,
            }
            relic_list.insert(0, piece_rec)
            if len(relic_list) > 200:
                unlocked_idxs = [i for i in range(len(relic_list) - 1, -1, -1) if not relic_list[i].get("locked")]
                for rm_i in unlocked_idxs[:len(relic_list) - 200]:
                    relic_list.pop(rm_i)
                    u_data["relic_remains"] = int(u_data.get("relic_remains", 0)) + 10
            gained_remains = 10
            gained_embers = 15
        else:
            gained_remains = 15
            gained_embers = 8
            u_data["relic_remains"] = int(u_data.get("relic_remains", 0)) + gained_remains

        u_data["embers"] = int(u_data.get("embers", 0)) + gained_embers
        item["gained_starlight"] = 0
        item["gained_embers"] = gained_embers
        item["gained_remains"] = gained_remains
        return 0, gained_embers

    existing = items_map.get(i_key)
    gained_starlight = 0
    gained_embers = 0

    if existing:
        existing["count"] = int(existing.get("count", 1)) + 1
        existing["last_obtained_at"] = now_iso
        existing["name"] = item.get("name", existing.get("name", ""))
        item["is_new"] = False
        if kind == "char":
            cur_e = int(existing.get("eidolon", min(6, existing["count"] - 2)))
            if cur_e < 6:
                new_e = min(6, cur_e + 1)
                existing["eidolon"] = new_e
                gained_starlight = 40 if rank == 5 else 8
            else:
                new_e = 6
                existing["eidolon"] = 6
                gained_starlight = 100 if rank == 5 else 20
            item["new_eidolon"] = new_e
        else:
            cur_s = int(existing.get("superimposition", 1))
            new_s = min(5, cur_s + 1)
            existing["superimposition"] = new_s
            item["new_super"] = new_s
            if rank == 5:
                gained_starlight = 40
            elif rank == 4:
                gained_starlight = 8
            else:
                gained_embers = 20
    else:
        item["is_new"] = True
        rec = {
            "id": item["id"],
            "kind": kind,
            "item_key": i_key,
            "name": item["name"],
            "rank": rank,
            "rarity_label": item["rarity_label"],
            "path": item.get("path", "Warrior"),
            "path_name": item.get("path_name", "파멸"),
            "path_emoji": item.get("path_emoji", "⚔️"),
            "pool_type": item.get("pool_type", "상시"),
            "count": 1,
            "level": 1,
            "locked": (rank == 5),
            "obtained_at": now_iso,
            "last_obtained_at": now_iso,
        }
        if kind == "char":
            rec["element"] = item.get("element", "Physical")
            rec["element_name"] = item.get("element_name", "물리")
            rec["element_emoji"] = item.get("element_emoji", "⚔️")
            rec["path_role"] = item.get("path_role", "딜러")
            rec["role_tag"] = item.get("role_tag", "dps")
            rec["eidolon"] = 0
            item["new_eidolon"] = 0
        else:
            rec["superimposition"] = 1
            item["new_super"] = 1
            if rank == 5:
                gained_starlight = 40
            elif rank == 4:
                gained_starlight = 8
            else:
                gained_embers = 20
        items_map[i_key] = rec

    u_data["starlight"] = int(u_data.get("starlight", 0)) + gained_starlight
    u_data["embers"] = int(u_data.get("embers", 0)) + gained_embers
    item["gained_starlight"] = gained_starlight
    item["gained_embers"] = gained_embers
    return gained_starlight, gained_embers


def _build_hsr_pools():
    chars, lcs = load_hsr_kr_db()
    std_5_chars = [c for c in chars if c["rank"] == 5 and c["id"] in HSR_STD_5_CHARS] or [c for c in chars if c["rank"] == 5]
    std_4_chars = [c for c in chars if c["rank"] == 4 and c["warpable"]] or [c for c in chars if c["rank"] == 4]
    std_5_lcs = [l for l in lcs if l["rank"] == 5 and l["warp_source"] == "standard"] or [l for l in lcs if l["rank"] == 5]
    warp_3_lcs = [l for l in lcs if l["rank"] == 3]
    std_4_lcs = [l for l in lcs if l["rank"] == 4 and l["warp_source"] == "standard"] or [l for l in lcs if l["rank"] == 4 and l["warpable"]]
    return std_5_chars, std_4_chars, std_5_lcs, warp_3_lcs, std_4_lcs


def execute_hsr_warp(guild_id: int, user_id: int, banner_key: str = "char1", count: int = 10, practice: bool = False) -> dict:
    """붕괴: 스타레일 워프(캐릭터/광추/상시/침식된 터널 유물)를 1회 또는 10회 실행합니다."""
    if banner_key not in HSR_BANNER_CONFIGS:
        banner_key = "char1"
    count = 10 if count >= 10 else 1

    load_hsr_kr_db()
    std_5_chars, std_4_chars, std_5_lcs, warp_3_lcs, std_4_lcs = _build_hsr_pools()
    sched = get_hsr_time_schedule()

    with core._DATA_LOCK:
        data = core.load_data()
        eff_pickup = resolve_effective_hsr_pickup(data.get("hsr_pickup"))
        u_data = ensure_hsr_user(data, guild_id, user_id)

        rng = random.SystemRandom()
        if practice:
            sim_state = copy.deepcopy(u_data)
            owned_items = u_data.get("items", {})
            drawn = []
            for _ in range(count):
                it = _roll_single_hsr(sim_state, banner_key, eff_pickup, std_5_chars, std_4_chars, std_5_lcs, warp_3_lcs, std_4_lcs, rng, sched=sched)
                prev = owned_items.get(it["item_key"])
                it["is_new"] = prev is None
                if it["kind"] == "char":
                    it["new_eidolon"] = min(6, int(prev.get("eidolon", 0)) + 1) if prev else 0
                elif it["kind"] == "lc":
                    it["new_super"] = min(5, int(prev.get("superimposition", 1)) + 1) if prev else 1
                it["gained_starlight"] = 0
                it["gained_embers"] = 0
                drawn.append(it)
            return {
                "drawn": drawn,
                "banner_key": banner_key,
                "eff_pickup": eff_pickup,
                "total_starlight": 0,
                "total_embers": 0,
                "gained_bonds": 0,
                "user_state": sim_state,
                "practice": True,
                "schedule": sched,
            }

        now_iso = datetime.datetime.now(core.KST).isoformat()
        drawn = []
        tot_sl = 0
        tot_em = 0
        for _ in range(count):
            it = _roll_single_hsr(u_data, banner_key, eff_pickup, std_5_chars, std_4_chars, std_5_lcs, warp_3_lcs, std_4_lcs, rng, sched=sched)
            gs, ge = _apply_hsr_item_to_account(u_data, it, now_iso)
            tot_sl += gs
            tot_em += ge
            drawn.append(it)

        u_data["total_pulls"] = int(u_data.get("total_pulls", 0)) + count
        if banner_key == "standard":
            u_data["standard_total_pulls"] = int(u_data.get("standard_total_pulls", 0)) + count

        # 10연차당 헤르타 채권 +1 지급 (은하 시뮬레이션 보너스)
        prog = int(u_data.get("herta_progress", 0)) + count
        gained_bonds = prog // 10
        u_data["herta_progress"] = prog % 10
        if gained_bonds > 0:
            u_data["herta_bond"] = int(u_data.get("herta_bond", 0)) + gained_bonds

        hist = u_data.setdefault("history", [])
        b_short = HSR_BANNER_CONFIGS[banner_key]["short_name"]
        for it in drawn:
            if it["rank"] >= 4:
                hist.insert(0, {
                    "name": it["name"] if it["kind"] != "relic" else f"{it['name']} ({it.get('slot_name', '유물')}·{it.get('main_stat', '')})",
                    "kind": it["kind"],
                    "rank": it["rank"],
                    "is_pickup": bool(it.get("is_pickup")),
                    "pity": it.get("pity_used"),
                    "banner": b_short,
                    "at": now_iso,
                })
        del hist[50:]

        _record_hsr_hof(data, guild_id, user_id, drawn, banner_key, now_iso)
        core.save_data(data)

        return {
            "drawn": drawn,
            "banner_key": banner_key,
            "eff_pickup": eff_pickup,
            "total_starlight": tot_sl,
            "total_embers": tot_em,
            "gained_bonds": gained_bonds,
            "user_state": u_data,
            "practice": False,
            "schedule": sched,
        }


def _record_hsr_hof(data: dict, guild_id: int, user_id: int, drawn: list[dict], banner_key: str, now_iso: str):
    if banner_key == "relic":
        return
    hof_root = data.setdefault("hsr_hall_of_fame", {})
    g_hof = hof_root.setdefault(str(guild_id or 0), {})
    if not isinstance(g_hof, dict):
        g_hof = {}
        hof_root[str(guild_id or 0)] = g_hof
    top_records = g_hof.setdefault("top_records", [])
    recent_5 = g_hof.setdefault("recent_5_logs", [])
    b_short = HSR_BANNER_CONFIGS[banner_key]["short_name"]

    r5_items = [it for it in drawn if it.get("rank") == 5]
    if r5_items:
        for it in r5_items:
            recent_5.insert(0, {
                "uid": str(user_id),
                "name": it["name"],
                "kind": it["kind"],
                "is_pickup": bool(it.get("is_pickup")),
                "pity": it.get("pity_used"),
                "banner": b_short,
                "at": now_iso,
            })
        del recent_5[25:]

        if len(drawn) == 10:
            pickup_cnt = sum(1 for it in r5_items if it.get("is_pickup"))
            min_p = min(int(it.get("pity_used") or 90) for it in r5_items)
            rec = {
                "uid": str(user_id),
                "r5_count": len(r5_items),
                "pickup_count": pickup_cnt,
                "min_pity": min_p,
                "items": [f"{'🎯' if it.get('is_pickup') else '★5'} {it['name']}({it.get('pity_used', '?')}스택)" for it in r5_items],
                "banner": b_short,
                "achieved_at": now_iso,
            }
            top_records.append(rec)
            top_records.sort(key=lambda r: (-r.get("r5_count", 0), -r.get("pickup_count", 0), r.get("min_pity", 99), r.get("achieved_at", "")))
            del top_records[10:]


# ==========================================
# 침식된 터널 · 유물 강화 / 분해 / 만능 합성기 / 자가 변형 레진 시스템
# ==========================================
def set_hsr_relic_target(guild_id: int, user_id: int, relic_id: str | None) -> tuple[bool, str, dict]:
    load_hsr_kr_db()
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        if not relic_id or relic_id == "auto":
            u_data["target_relic_set"] = None
            core.save_data(data)
            return True, "🕳️ 침식된 터널 집중 세트가 **시간대별 자동 추천 세트**로 설정되었습니다.", u_data
        r_obj = get_hsr_relic_by_id(relic_id)
        if not r_obj:
            return False, "선택한 유물 세트를 찾을 수 없습니다.", u_data
        u_data["target_relic_set"] = r_obj["id"]
        core.save_data(data)
        return True, f"🎯 침식된 터널 집중 파밍 세트가 **`{r_obj['name']}`** ({r_obj['relic_type']})로 지정되었습니다! (★5 획득 시 75% 확률로 해당 세트 드랍)", u_data


def enhance_hsr_relic(guild_id: int, user_id: int, relic_uid: str, to_max: bool = False) -> tuple[bool, str, dict | None]:
    """보유 중인 ★5 유물을 +3 단계씩(또는 to_max=True 시 최대 +15까지) 강화하며, 부옵션 추가/상승을 적용합니다."""
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        relic_list = u_data.get("relics", [])
        target = next((r for r in relic_list if r.get("uid") == relic_uid), None)
        if not target:
            return False, "해당 유물을 찾을 수 없습니다.", None
        start_lv = int(target.get("level", 0))
        if start_lv >= 15:
            return False, f"**{target['name']} ({target.get('slot_name', '')})** 유물은 이미 최고 단계(`+15`)입니다!", target

        cost_remains = 10
        if int(u_data.get("relic_remains", 0)) < cost_remains:
            return False, f"유물 잔해가 부족합니다! (필요: `{cost_remains}개` / 보유: `{u_data.get('relic_remains', 0)}개` · 유물 토벌 또는 분해로 획득)", target

        rng = random.SystemRandom()
        subs = target.setdefault("substats", [])
        main_stat = target.get("main_stat", "")
        rank = int(target.get("rank", 5))
        m_pair = HSR_RELIC_MAIN_VALUES.get((rank, main_stat)) or HSR_RELIC_MAIN_VALUES.get(main_stat)

        steps = 0
        total_spent = 0
        roll_msgs = []
        cur_lv = start_lv

        while cur_lv < 15 and int(u_data.get("relic_remains", 0)) >= cost_remains:
            u_data["relic_remains"] = int(u_data.get("relic_remains", 0)) - cost_remains
            total_spent += cost_remains
            steps += 1
            new_lv = min(15, cur_lv + 3)
            target["level"] = new_lv
            cur_lv = new_lv

            if isinstance(m_pair, tuple) and len(m_pair) == 2:
                v_start, v_max = m_pair
                if new_lv >= 15:
                    target["main_value"] = v_max
                else:
                    try:
                        is_pct = "%" in str(v_max)
                        s_num = float(str(v_start).replace("+", "").replace(",", "").replace("%", ""))
                        m_num = float(str(v_max).replace("+", "").replace(",", "").replace("%", ""))
                        interp = s_num + (m_num - s_num) * (new_lv / 15.0)
                        target["main_value"] = f"+{interp:.1f}%" if is_pct else f"+{int(round(interp)):,}"
                    except Exception:
                        pass

            existing_names = {s["name"] for s in subs}
            if len(subs) < 4:
                cands = [s for s in HSR_RELIC_SUBSTATS if s[0] != main_stat and s[0] not in existing_names]
                if cands:
                    s_name, tiers, unit = rng.choice(cands)
                    val = round(rng.choice(tiers), 1 if unit == "%" else 0)
                    subs.append({"name": s_name, "value": val, "unit": unit, "rolls": 1})
                    roll_msgs.append(f"🆕 4번째 부옵션 **`{s_name} +{val}{unit}`** 개방!")
                else:
                    roll_msgs.append("부옵션 개방 완료!")
            else:
                chosen = rng.choice(subs)
                s_def = next((s for s in HSR_RELIC_SUBSTATS if s[0] == chosen["name"]), None)
                tiers = s_def[1] if s_def else [3.0, 3.4, 3.8]
                unit = chosen.get("unit", "%")
                inc = round(rng.choice(tiers), 1 if unit == "%" else 0)
                old_v = chosen["value"]
                chosen["value"] = round(old_v + inc, 1 if unit == "%" else 0) if unit == "%" else int(old_v + inc)
                chosen["rolls"] = int(chosen.get("rolls", 1)) + 1
                roll_msgs.append(f"✨ **`{chosen['name']}`** (`+{old_v}{unit}` ➔ **`+{chosen['value']}{unit}`**)")

            if not to_max:
                break

        cv, rv, grade = compute_hsr_relic_score(target)
        target["cv"] = cv
        target["rv"] = rv
        target["score"] = rv
        target["grade"] = grade
        if grade in ("SSS", "SS"):
            target["locked"] = True

        summary_roll = roll_msgs[-1] if len(roll_msgs) == 1 else f"✨ `{steps}단계` 연속 강화 완료 (마지막: {roll_msgs[-1]})"
        core.save_data(data)
        return True, f"🔨 **{target['name']} ({target.get('slot_name', '')})** `+{start_lv}` ➔ **`+{cur_lv}`** 강화 성공! (`-{total_spent} 유물 잔해`)\n└ {summary_roll} · 현재 등급 **`{grade}`** (CV `{cv}` / RV `{rv}`)", target


def toggle_hsr_relic_lock(guild_id: int, user_id: int, relic_uid: str) -> tuple[bool, bool, dict | None]:
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        target = next((r for r in u_data.get("relics", []) if r.get("uid") == relic_uid), None)
        if not target:
            return False, False, None
        target["locked"] = not bool(target.get("locked", False))
        core.save_data(data)
        return True, target["locked"], target


def salvage_hsr_relics(guild_id: int, user_id: int, max_grade: str = "A") -> tuple[bool, str, dict]:
    """잠금되지 않은 ★4 또는 B/A등급 +0강 유물을 일괄 분해하여 유물 잔해와 자가 변형 레진을 획득합니다."""
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        relic_list = u_data.get("relics", [])
        kept = []
        salvaged_cnt = 0
        for r in relic_list:
            if r.get("locked") or int(r.get("level", 0)) != 0:
                kept.append(r)
                continue
            if max_grade == "4star":
                if int(r.get("rank", 5)) <= 4:
                    salvaged_cnt += 1
                else:
                    kept.append(r)
            elif max_grade in ("B", "5star_low"):
                if r.get("grade", "B") in ("B",):
                    salvaged_cnt += 1
                else:
                    kept.append(r)
            else:
                if r.get("grade", "B") in ("A", "B"):
                    salvaged_cnt += 1
                else:
                    kept.append(r)

        if salvaged_cnt == 0:
            empty_msg = (
                "분해할 수 있는 미잠금 ★4 유물이 없습니다. (워프 획득 ★4 유물은 자동으로 잔해 `+15`로 환원됩니다)"
                if max_grade == "4star"
                else "분해할 수 있는 미잠금 +0강 B이하 등급 유물이 없습니다."
            )
            return False, empty_msg, u_data

        gained_remains = salvaged_cnt * 20
        gained_resin = salvaged_cnt // 10
        u_data["relics"] = kept
        u_data["relic_remains"] = int(u_data.get("relic_remains", 0)) + gained_remains
        if gained_resin > 0:
            u_data["self_modeling_resin"] = int(u_data.get("self_modeling_resin", 0)) + gained_resin
        core.save_data(data)

        resin_txt = f" · 🧪 **자가 변형 레진 +{gained_resin}개**" if gained_resin > 0 else ""
        return True, f"♻️ 미잠금 유물 **{salvaged_cnt}개** 분해 완료! ➔ 🧩 **유물 잔해 +{gained_remains}개**{resin_txt} (보유 잔해: `{u_data['relic_remains']}개`)", u_data


def craft_hsr_relic_synthesizer(guild_id: int, user_id: int, set_id: str, slot_code: str | None = None) -> tuple[bool, str, dict | None]:
    """만능 합성기: 유물 잔해 100개를 소모하여 원하는 세트의 ★5 유물을 즉시 합성합니다."""
    load_hsr_kr_db()
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        if int(u_data.get("relic_remains", 0)) < 100:
            return False, f"🧩 **유물 잔해**가 부족합니다! (필요: `100개` / 보유: `{u_data.get('relic_remains', 0)}개`)", None
        r_set = get_hsr_relic_by_id(set_id) or (get_hsr_relics()[0] if get_hsr_relics() else None)
        if not r_set:
            return False, "선택한 유물 세트를 찾을 수 없습니다.", None

        u_data["relic_remains"] = int(u_data.get("relic_remains", 0)) - 100
        rng = random.SystemRandom()
        sched = get_hsr_time_schedule()
        piece = _generate_hsr_relic_piece(r_set, 5, rng, sched=sched, forced_slot_code=slot_code)
        now_iso = datetime.datetime.now(core.KST).isoformat()
        _apply_hsr_item_to_account(u_data, piece, now_iso)
        core.save_data(data)
        return True, f"⚗️ **만능 합성기 연성 완료!** `★★★★★ {piece['name']}` ({piece['slot_emoji']}{piece['slot_name']} · 주옵 `{piece['main_stat']}` · 등급 `{piece['grade']}`) 획득!", piece


def craft_hsr_relic_resin(
    guild_id: int,
    user_id: int,
    set_id: str,
    slot_code: str,
    main_stat: str,
) -> tuple[bool, str, dict | None]:
    """자가 변형 레진 1개 + 유물 잔해 100개로 세트·부위·주옵션 및 치명/속도 부옵션을 확정 주조합니다."""
    load_hsr_kr_db()
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        if int(u_data.get("self_modeling_resin", 0)) < 1:
            return False, f"🧪 **자가 변형 레진**이 부족합니다! (필요: `1개` / 보유: `{u_data.get('self_modeling_resin', 0)}개` · 유물 10개 분해 시 1개 획득)", None
        if int(u_data.get("relic_remains", 0)) < 100:
            return False, f"🧩 **유물 잔해**가 부족합니다! (필요: `100개` / 보유: `{u_data.get('relic_remains', 0)}개`)", None

        r_set = get_hsr_relic_by_id(set_id) or (get_hsr_relics()[0] if get_hsr_relics() else None)
        if not r_set:
            return False, "선택한 유물 세트를 찾을 수 없습니다.", None

        u_data["self_modeling_resin"] = int(u_data.get("self_modeling_resin", 0)) - 1
        u_data["relic_remains"] = int(u_data.get("relic_remains", 0)) - 100

        rng = random.SystemRandom()
        sched = get_hsr_time_schedule()
        piece = _generate_hsr_relic_piece(r_set, 5, rng, sched=sched, forced_slot_code=slot_code, forced_main_stat=main_stat)

        subs = piece.get("substats") or []
        sub_names = {s["name"] for s in subs}
        for pref in ("치명타 확률", "치명타 피해", "속도"):
            if pref != piece["main_stat"] and pref not in sub_names and len(subs) < 4:
                s_def = next((x for x in HSR_RELIC_SUBSTATS if x[0] == pref), None)
                if s_def:
                    subs.append({"name": pref, "value": s_def[1][-1], "unit": s_def[2], "rolls": 1})
                    sub_names.add(pref)

        cv, rv, grade = compute_hsr_relic_score(piece)
        piece["cv"] = cv
        piece["rv"] = rv
        piece["grade"] = grade
        piece["locked"] = True

        now_iso = datetime.datetime.now(core.KST).isoformat()
        _apply_hsr_item_to_account(u_data, piece, now_iso)
        core.save_data(data)
        return True, f"🧪 **자가 변형 레진 맞춤 주조 완료!** `★★★★★ {piece['name']}` ({piece['slot_emoji']}{piece['slot_name']} · 주옵 **`{piece['main_stat']}`** · 등급 **`{piece['grade']}`**)", piece


def toggle_hsr_item_lock(guild_id: int, user_id: int, item_key: str) -> tuple[bool, bool, dict | None]:
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        target = u_data.get("items", {}).get(item_key)
        if not target:
            return False, False, None
        new_val = not bool(target.get("locked", False))
        target["locked"] = new_val
        core.save_data(data)
        return True, new_val, target


def claim_hsr_standard_300(guild_id: int, user_id: int, char_id: str) -> tuple[bool, str, dict]:
    """뭇별의 워프(상시 워프) 누적 300회 달성 보상: 상시 5성 캐릭터 7명 중 1명 확정 초대"""
    load_hsr_kr_db()
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        std_pulls = int(u_data.get("standard_total_pulls", 0))
        if std_pulls < 300:
            return False, f"상시 워프 누적 횟수가 부족합니다! (`{std_pulls}/300회` · `{300 - std_pulls}회` 더 필요)", u_data
        if u_data.get("standard_300_claimed"):
            return False, "이미 상시 워프 300회 5성 선택 권리를 사용하셨습니다!", u_data
        if char_id not in HSR_STD_5_CHARS:
            return False, "상시 5성 캐릭터(히메코/웰트/브로냐/게파드/클라라/연경/백로)만 선택할 수 있습니다.", u_data
        c_obj = HSR_ALL_ITEMS.get(f"char:{char_id}")
        if not c_obj:
            return False, "선택한 캐릭터 정보를 찾을 수 없습니다.", u_data

        now_iso = datetime.datetime.now(core.KST).isoformat()
        u_data["standard_300_claimed"] = True
        _apply_hsr_item_to_account(u_data, dict(c_obj), now_iso)
        core.save_data(data)
        return True, f"🎊 **상시 300회 특별 초대 완료!** `★★★★★ {c_obj['name']}` ({c_obj['element_emoji']}{c_obj['path_name']})님이 은하열차에 합류했습니다!", u_data


def get_hsr_shop_catalog() -> dict:
    """별빛 교환 / 불멸의 잔재 / 헤르타 상점 품목을 반환합니다."""
    load_hsr_kr_db()
    now = datetime.datetime.now(core.KST)
    m_idx = (now.month - 1) % 6
    char_pair = HSR_STARLIGHT_CHAR_ROTATION[m_idx]

    shop_chars = [HSR_ALL_ITEMS[f"char:{cid}"] for cid in char_pair if f"char:{cid}" in HSR_ALL_ITEMS]
    std_5_lcs = [HSR_ALL_ITEMS[f"lc:{lid}"] for lid in sorted(HSR_STD_5_LCS) if f"lc:{lid}" in HSR_ALL_ITEMS]
    herta_lcs = [
        l for l in HSR_LIGHT_CONES
        if l["rank"] == 5 and l["warp_source"] == "herta"
    ]
    special_4_lcs = [
        l for l in HSR_LIGHT_CONES
        if l["rank"] == 4 and l["warp_source"] in ("event_shop", "manifest_shop")
    ]
    return {
        "month": now.month,
        "month_key": now.strftime("%Y-%m"),
        "chars": shop_chars,
        "std_5_lcs": std_5_lcs,
        "herta_lcs": herta_lcs,
        "special_4_lcs": special_4_lcs,
    }


def purchase_hsr_shop_item(guild_id: int, user_id: int, offer_id: str) -> tuple[bool, str, dict]:
    """별빛 / 불멸의 잔재 / 헤르타 채권 상점 구매"""
    load_hsr_kr_db()
    cat = get_hsr_shop_catalog()
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        m_key = cat["month_key"]
        monthly = u_data.setdefault("shop_monthly", {})
        if monthly.get("month_key") != m_key:
            monthly.clear()
            monthly["month_key"] = m_key
            monthly["embers_special_pass"] = 0
            monthly["embers_standard_pass"] = 0
            monthly["chars_bought"] = []

        now_iso = datetime.datetime.now(core.KST).isoformat()

        if offer_id.startswith("buy_char:"):
            cid = offer_id.split(":", 1)[1]
            c_obj = next((c for c in cat["chars"] if c["id"] == cid), None)
            if not c_obj:
                return False, "이번 달 별빛 교환 캐릭터가 아닙니다.", u_data
            bought = monthly.setdefault("chars_bought", [])
            if cid in bought:
                return False, f"이번 달 **{c_obj['name']}** 교환 한도(월 1회)를 이미 사용했습니다.", u_data
            if u_data["starlight"] < 140:
                return False, f"꺼지지 않는 별빛이 부족합니다! (필요: `140` / 보유: `{u_data['starlight']}`)", u_data
            u_data["starlight"] -= 140
            bought.append(cid)
            _apply_hsr_item_to_account(u_data, dict(c_obj), now_iso)
            core.save_data(data)
            return True, f"✨ **★★★★ {c_obj['name']}** 영입 완료! (`-140 꺼지지 않는 별빛`)", u_data

        if offer_id.startswith("buy_5lc:"):
            lid = offer_id.split(":", 1)[1]
            l_obj = next((l for l in cat["std_5_lcs"] if l["id"] == lid), None)
            if not l_obj:
                return False, "별빛 상점 상시 5성 광추가 아닙니다.", u_data
            if u_data["starlight"] < 600:
                return False, f"꺼지지 않는 별빛이 부족합니다! (필요: `600` / 보유: `{u_data['starlight']}`)", u_data
            u_data["starlight"] -= 600
            _apply_hsr_item_to_account(u_data, dict(l_obj), now_iso)
            core.save_data(data)
            return True, f"🪩 **★★★★★ {l_obj['name']}** 광추 교환 완료! (`-600 꺼지지 않는 별빛`)", u_data

        if offer_id.startswith("herta_lc:"):
            lid = offer_id.split(":", 1)[1]
            l_obj = next((l for l in cat["herta_lcs"] if l["id"] == lid), None)
            if not l_obj:
                return False, "헤르타 상점 5성 광추가 아닙니다.", u_data
            if u_data["herta_bond"] < 8:
                return False, f"헤르타 채권이 부족합니다! (필요: `8` / 보유: `{u_data['herta_bond']}`)", u_data
            u_data["herta_bond"] -= 8
            _apply_hsr_item_to_account(u_data, dict(l_obj), now_iso)
            core.save_data(data)
            return True, f"🧪 **헤르타 상점 ★★★★★ {l_obj['name']}** 교환 완료! (`-8 헤르타 채권`)", u_data

        if offer_id == "herta_superimposer":
            owned_herta = [
                it for it in u_data.get("items", {}).values()
                if it.get("kind") == "lc" and str(it.get("id", "")).startswith(HSR_HERTA_LC_PREFIX) and int(it.get("superimposition", 1)) < 5
            ]
            if not owned_herta:
                return False, "중첩 가능한 S5 미만 헤르타 5성 광추를 보유하고 있지 않습니다.", u_data
            if u_data["herta_bond"] < 2:
                return False, f"헤르타 채권이 부족합니다! (필요: `2` / 보유: `{u_data['herta_bond']}`)", u_data
            owned_herta.sort(key=lambda x: int(x.get("superimposition", 1)))
            target = owned_herta[0]
            u_data["herta_bond"] -= 2
            old_s = int(target.get("superimposition", 1))
            target["superimposition"] = min(5, old_s + 1)
            core.save_data(data)
            return True, f"🔧 **중첩기(특제)** 적용! `{target['name']}` 중첩 **`S{old_s} ➔ S{target['superimposition']}`** (`-2 헤르타 채권`)", u_data

        if offer_id.startswith("manifest_lc:"):
            lid = offer_id.split(":", 1)[1]
            l_obj = next((l for l in cat["special_4_lcs"] if l["id"] == lid), None)
            if not l_obj:
                return False, "잔재/광추 박물 교환 대상이 아닙니다.", u_data
            if u_data["embers"] < 160:
                return False, f"불멸의 잔재가 부족합니다! (필요: `160` / 보유: `{u_data['embers']}`)", u_data
            u_data["embers"] -= 160
            _apply_hsr_item_to_account(u_data, dict(l_obj), now_iso)
            core.save_data(data)
            return True, f"🪩 **★★★★ {l_obj['name']}** 교환 완료! (`-160 불멸의 잔재`)", u_data

        if offer_id == "sl_special_pass":
            if u_data["starlight"] < 20:
                return False, f"꺼지지 않는 별빛이 부족합니다! (필요: `20` / 보유: `{u_data['starlight']}`)", u_data
            u_data["starlight"] -= 20
            u_data["special_pass"] = int(u_data.get("special_pass", 0)) + 1
            core.save_data(data)
            return True, "🎫 **별의 궤도 전용티켓 ×1** 교환 완료! (`-20 별빛`)", u_data

        if offer_id == "sl_standard_pass":
            if u_data["starlight"] < 20:
                return False, f"꺼지지 않는 별빛이 부족합니다! (필요: `20` / 보유: `{u_data['starlight']}`)", u_data
            u_data["starlight"] -= 20
            u_data["standard_pass"] = int(u_data.get("standard_pass", 0)) + 1
            core.save_data(data)
            return True, "🎟️ **별의 궤도 티켓 ×1** 교환 완료! (`-20 별빛`)", u_data

        if offer_id == "embers_special_pass":
            used = int(monthly.get("embers_special_pass", 0))
            if used >= 5:
                return False, "이달의 불멸의 잔재 전용티켓 교환 한도(5/5회)를 모두 사용했습니다.", u_data
            if u_data["embers"] < 90:
                return False, f"불멸의 잔재가 부족합니다! (필요: `90` / 보유: `{u_data['embers']}`)", u_data
            u_data["embers"] -= 90
            monthly["embers_special_pass"] = used + 1
            u_data["special_pass"] = int(u_data.get("special_pass", 0)) + 1
            core.save_data(data)
            return True, f"🎫 **별의 궤도 전용티켓 ×1** 교환 완료! (`-90 불멸의 잔재` · 이달 `{used + 1}/5회`)", u_data

        if offer_id == "embers_standard_pass":
            used = int(monthly.get("embers_standard_pass", 0))
            if used >= 5:
                return False, "이달의 불멸의 잔재 상시 티켓 교환 한도(5/5회)를 모두 사용했습니다.", u_data
            if u_data["embers"] < 90:
                return False, f"불멸의 잔재가 부족합니다! (필요: `90` / 보유: `{u_data['embers']}`)", u_data
            u_data["embers"] -= 90
            monthly["embers_standard_pass"] = used + 1
            u_data["standard_pass"] = int(u_data.get("standard_pass", 0)) + 1
            core.save_data(data)
            return True, f"🎟️ **별의 궤도 티켓 ×1** 교환 완료! (`-90 불멸의 잔재` · 이달 `{used + 1}/5회`)", u_data

        if offer_id == "embers_traveler_guide":
            if u_data["embers"] < 60:
                return False, f"불멸의 잔재가 부족합니다! (필요: `60` / 보유: `{u_data['embers']}`)", u_data
            u_data["embers"] -= 60
            u_data["traveler_guide"] = int(u_data.get("traveler_guide", 0)) + 5
            core.save_data(data)
            return True, f"📘 **여행 가이드 ×5** 구매 완료! (보유: `{u_data['traveler_guide']}권`)", u_data

        return False, "알 수 없는 상점 상품입니다.", u_data


def levelup_hsr_char(guild_id: int, user_id: int, item_key: str) -> tuple[bool, str, dict]:
    """여행 가이드 ×2권을 소모해 보유 캐릭터 레벨을 Lv.1 -> Lv.80까지 육성합니다."""
    with core._DATA_LOCK:
        data = core.load_data()
        u_data = ensure_hsr_user(data, guild_id, user_id)
        c = u_data.get("items", {}).get(item_key)
        if not c or c.get("kind") != "char":
            return False, "보유 중인 캐릭터를 찾을 수 없습니다.", u_data
        cur_lv = int(c.get("level", 1))
        if cur_lv >= 80:
            return False, f"**{c['name']}** 캐릭터는 이미 최고 레벨(`Lv.80`)입니다!", u_data
        guides = int(u_data.get("traveler_guide", 0))
        if guides < 2:
            return False, f"📘 **여행 가이드**가 부족합니다! (`/스타레일 상점`에서 불멸의 잔재 60으로 5권 구매 · 보유 `{guides}권`)", u_data
        u_data["traveler_guide"] = guides - 2
        new_lv = min(80, cur_lv + 10)
        c["level"] = new_lv
        core.save_data(data)
        return True, f"⬆️ **{c['name']}** 승급·육성 완료! `Lv.{cur_lv}` ➔ **`Lv.{new_lv}`** (`-2 여행 가이드`)", u_data


def compute_hsr_char_power(char_obj: dict) -> int:
    rank = int(char_obj.get("rank", 4))
    lv = max(1, int(char_obj.get("level", 1)))
    eidolon = max(0, min(6, int(char_obj.get("eidolon", 0))))
    base = 13500 if rank == 5 else 9200
    lv_bonus = lv * (220 if rank == 5 else 160)
    e_mult = 1.0 + eidolon * 0.13
    return int((base + lv_bonus) * e_mult)


def analyze_hsr_party(party_chars: list[dict]) -> dict:
    """4인 스타레일 편대의 운명의 길 조합 시너지와 속성 격파 커버리지를 계산합니다."""
    if not party_chars:
        return {"synergies": [], "base_power": 0, "total_power": 0, "bonus_pct": 0, "elem_count": 0}

    role_counts = {"dps": 0, "sup": 0, "sus": 0}
    path_counts: dict[str, int] = {}
    elems: set[str] = set()
    base_power = 0

    for c in party_chars[:4]:
        p = c.get("path", "Warrior")
        tag = c.get("role_tag") or HSR_PATH_MAP.get(p, {}).get("role_tag", "dps")
        role_counts[tag] = role_counts.get(tag, 0) + 1
        path_counts[p] = path_counts.get(p, 0) + 1
        elems.add(c.get("element", "Physical"))
        base_power += compute_hsr_char_power(c)

    synergies = []
    bonus_pct = 0

    if role_counts["dps"] >= 1 and role_counts["sup"] >= 1 and role_counts["sus"] >= 1:
        synergies.append("⚖️ **안정 균형 편대** (딜러+서포터+생존 조합 · 파티 화력/안정성 +22%)")
        bonus_pct += 22
    if role_counts["sup"] >= 2 and role_counts["dps"] >= 1:
        synergies.append("🎵 **쌍화합·공허 증폭 조합** (하이퍼캐리 시너지 · 치명/피해 증가 +16%)")
        bonus_pct += 16
    if role_counts["sus"] >= 1:
        synergies.append("🛡️ **불멸의 수호 라인** (풍요·보존 생존 확보 · 파티 지구력 +10%)")
        bonus_pct += 10
    if len(elems) >= 3:
        synergies.append(f"💥 **다속성 약점 격파 ({len(elems)}속성)** (은하 혼돈/종말 대응력 +14%)")
        bonus_pct += 14
    if path_counts.get("Memory", 0) >= 2:
        synergies.append("🕊️ **기억의 연쇄** (다중 기억정령 동시 전개 · +12%)")
        bonus_pct += 12
    if path_counts.get("Elation", 0) >= 2 or path_counts.get("Rogue", 0) >= 2:
        synergies.append("🎭 **추가 공격/고속 연타** (행동 게이지 턴 압축 시너지 · +12%)")
        bonus_pct += 12

    total_power = int(base_power * (1.0 + bonus_pct / 100.0))
    return {
        "synergies": synergies,
        "base_power": base_power,
        "total_power": total_power,
        "bonus_pct": bonus_pct,
        "elem_count": len(elems),
    }


def get_hsr_pokedex_stats(guild_id: int, user_id: int) -> dict:
    chars, lcs = load_hsr_kr_db()
    relics = get_hsr_relics()
    data = core.load_data()
    u_data = ensure_hsr_user(data, guild_id, user_id)
    owned_map = u_data.get("items", {})

    all_master = chars + lcs + relics
    warp_master = [it for it in (chars + lcs) if it.get("warpable", True)]

    owned_all = []
    unowned_all = []
    for it in all_master:
        ik = it["item_key"]
        if ik in owned_map:
            owned_all.append({**it, **owned_map[ik]})
        else:
            unowned_all.append(dict(it))

    w_owned = sum(1 for it in warp_master if it["item_key"] in owned_map)
    w_total = max(1, len(warp_master))

    c5_tot = sum(1 for c in chars if c["rank"] == 5)
    c5_own = sum(1 for c in chars if c["rank"] == 5 and c["item_key"] in owned_map)
    c4_tot = sum(1 for c in chars if c["rank"] == 4)
    c4_own = sum(1 for c in chars if c["rank"] == 4 and c["item_key"] in owned_map)
    l5_tot = sum(1 for l in lcs if l["rank"] == 5)
    l5_own = sum(1 for l in lcs if l["rank"] == 5 and l["item_key"] in owned_map)
    l4_tot = sum(1 for l in lcs if l["rank"] == 4)
    l4_own = sum(1 for l in lcs if l["rank"] == 4 and l["item_key"] in owned_map)
    r_tot = len(relics)
    r_own = sum(1 for r in relics if r["item_key"] in owned_map)

    rate = (w_owned / w_total) * 100.0
    filled = int(round((rate / 100.0) * 10))
    bar = "🟪" * filled + "⬛" * max(0, 10 - filled)

    return {
        "total_all": len(all_master),
        "owned_total": len(owned_all),
        "warpable_total": w_total,
        "warpable_owned": w_owned,
        "rate": rate,
        "bar": bar,
        "c5": (c5_own, c5_tot),
        "c4": (c4_own, c4_tot),
        "l5": (l5_own, l5_tot),
        "l4": (l4_own, l4_tot),
        "relic_sets": (r_own, r_tot),
        "relic_pieces_count": len(u_data.get("relics", [])),
        "owned_items": owned_all,
        "unowned_items": unowned_all,
    }


def get_hsr_hall_of_fame(data: dict, guild_id: int) -> dict:
    hof = data.get("hsr_hall_of_fame", {}).get(str(guild_id or 0), {})
    if not isinstance(hof, dict):
        return {"top_records": [], "recent_5_logs": []}
    return {
        "top_records": list(hof.get("top_records") or []),
        "recent_5_logs": list(hof.get("recent_5_logs") or []),
    }


def apply_hsr_pickup_preset(preset_key: str) -> tuple[bool, str, dict]:
    load_hsr_kr_db()
    with core._DATA_LOCK:
        data = core.load_data()
        now_iso = datetime.datetime.now(core.KST).isoformat()
        if preset_key == "reset":
            reset_cfg = copy.deepcopy(core.DEFAULT_CONFIG["hsr_pickup"])
            reset_cfg["updated_at"] = now_iso
            data["hsr_pickup"] = reset_cfg
            core.save_data(data)
            return True, "🧹 스타레일 워프 픽업 설정이 기본값으로 초기화되었습니다.", resolve_effective_hsr_pickup(reset_cfg)

        preset = HSR_BANNER_PRESETS.get(preset_key)
        if not preset:
            return False, "알 수 없는 프리셋입니다.", resolve_effective_hsr_pickup(data.get("hsr_pickup"))

        cfg = {
            "mode": "preset",
            "char1": preset.get("char1"),
            "char2": preset.get("char2"),
            "char_4_ids": list(preset.get("char_4_ids") or []),
            "lc_1": preset.get("lc_1"),
            "lc_2": preset.get("lc_2"),
            "lc_4_ids": [],
            "banner_name": preset.get("banner_name", "은하열차 이벤트 워프"),
            "version_label": preset.get("label", "프리셋 연동"),
            "updated_at": now_iso,
        }
        data["hsr_pickup"] = cfg
        core.save_data(data)
        return True, f"🎯 **{preset['label']}** 워프 픽업 적용 완료!", resolve_effective_hsr_pickup(cfg)


async def hsr_5star_char_autocomplete(interaction, current: str):
    from discord import app_commands
    chars, _ = load_hsr_kr_db()
    q = (current or "").strip().lower()
    cands = [c for c in chars if c["rank"] == 5 and (not q or q in c["name"].lower() or q in c["id"])]
    return [
        app_commands.Choice(name=f"★★★★★ {c['name']} ({c['element_emoji']}{c['path_name']} · {c['pool_type']})"[:100], value=c["id"])
        for c in cands[:25]
    ]


async def hsr_4star_char_autocomplete(interaction, current: str):
    from discord import app_commands
    chars, _ = load_hsr_kr_db()
    q = (current or "").strip().lower()
    cands = [c for c in chars if c["rank"] == 4 and c["warpable"] and (not q or q in c["name"].lower() or q in c["id"])]
    return [
        app_commands.Choice(name=f"★★★★ {c['name']} ({c['element_emoji']}{c['path_name']})"[:100], value=c["id"])
        for c in cands[:25]
    ]


async def hsr_5star_lc_autocomplete(interaction, current: str):
    from discord import app_commands
    _, lcs = load_hsr_kr_db()
    q = (current or "").strip().lower()
    cands = [l for l in lcs if l["rank"] == 5 and (not q or q in l["name"].lower() or q in l["id"])]
    return [
        app_commands.Choice(name=f"★★★★★ {l['name']} ({l['path_emoji']}{l['path_name']} · {l['pool_type']})"[:100], value=l["id"])
        for l in cands[:25]
    ]


async def hsr_owned_char_autocomplete(interaction, current: str):
    from discord import app_commands
    data = core.get_cached_data()
    g_key = str(interaction.guild_id or 0)
    u_key = str(interaction.user.id)
    items = data.get("hsr_users", {}).get(g_key, {}).get(u_key, {}).get("items", {})
    owned = [v for v in items.values() if isinstance(v, dict) and v.get("kind") == "char"]
    owned.sort(key=lambda c: (-c.get("rank", 4), -c.get("eidolon", 0), c.get("name", "")))
    q = (current or "").strip().lower()
    res = []
    for c in owned:
        if q and q not in c.get("name", "").lower() and q not in c.get("path_name", "").lower():
            continue
        res.append(app_commands.Choice(
            name=f"{'★5' if c.get('rank') == 5 else '★4'} {c.get('name')} (E{c.get('eidolon', 0)} · Lv.{c.get('level', 1)})"[:100],
            value=c["item_key"],
        ))
        if len(res) >= 25:
            break
    return res


async def hsr_relic_set_autocomplete(interaction, current: str):
    from discord import app_commands
    relics = get_hsr_relics()
    q = (current or "").strip().lower()
    cands = [
        r for r in relics
        if not q or q in r["name"].lower() or q in str(r["id"]) or q in (r.get("set_2pc") or "").lower()
    ]
    return [
        app_commands.Choice(
            name=f"💠 {r['name']} ({'차원' if r.get('is_planar') else '터널'} · {(r.get('set_2pc') or '')[:35]})"[:100],
            value=str(r["id"]),
        )
        for r in cands[:25]
    ]


