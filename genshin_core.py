from __future__ import annotations

import os
import io
import re
import time
import json
import copy
import random
import asyncio
import datetime
import threading
from collections import OrderedDict
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter
import core

requests = core.requests

GENSHIN_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "genshin_kr_cache.json")
GENSHIN_CACHE_VERSION = 2
GENSHIN_CACHE_TTL = 60 * 60 * 24  # 24시간

_GENSHIN_DB_LOCK = threading.Lock()
_GENSHIN_DETAIL_LOCK = threading.Lock()
_GENSHIN_IMG_LOCK = threading.Lock()

GENSHIN_CHARS: list[dict] = []
GENSHIN_WEAPONS: list[dict] = []
GENSHIN_ARTIFACTS: list[dict] = []
GENSHIN_ARTIFACT_MAP: dict[str, dict] = {}
GENSHIN_ALL_ITEMS: dict[str, dict] = {}
_GENSHIN_LAST_FETCH: float = 0.0

_GENSHIN_DETAIL_CACHE: OrderedDict[str, dict] = OrderedDict()
_GENSHIN_IMG_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_GENSHIN_THUMB_CACHE: OrderedDict[str, bytes] = OrderedDict()

# ==========================================
# 원신 (Genshin Impact) 마스터 매핑 & 정통 풀 분류
# ==========================================
GENSHIN_ELEMENT_MAP = {
    "Fire": {
        "name": "불",
        "emoji": "🔥",
        "color": (239, 108, 77),
        "res_name": "열정의 불",
        "res_desc": "물·얼음 부착 시간 -40% · 파티 공격력 +25%",
    },
    "Water": {
        "name": "물",
        "emoji": "💧",
        "color": (66, 165, 245),
        "res_name": "치유의 물",
        "res_desc": "불 부착 시간 -40% · HP 최대치 +25%",
    },
    "Ice": {
        "name": "얼음",
        "emoji": "❄️",
        "color": (128, 222, 234),
        "res_name": "분쇄의 얼음",
        "res_desc": "번개 부착 시간 -40% · 빙결/얼음 적 치명타 확률 +15%",
    },
    "Electric": {
        "name": "번개",
        "emoji": "⚡",
        "color": (171, 120, 255),
        "res_name": "강력의 번개",
        "res_desc": "물 부착 시간 -40% · 번개 관련 반응 시 원소 입자 생성",
    },
    "Wind": {
        "name": "바람",
        "emoji": "🌪️",
        "color": (77, 208, 177),
        "res_name": "날렵한 바람",
        "res_desc": "스태미나 소모 -15% · 이동 속도 +10% · 스킬 재사용 대기시간 -5%",
    },
    "Grass": {
        "name": "풀",
        "emoji": "🌿",
        "color": (124, 198, 68),
        "res_name": "만생의 풀",
        "res_desc": "원소 마스터리 +50 (연소/활성/개화 반응 시 최대 +100)",
    },
    "Rock": {
        "name": "바위",
        "emoji": "🪨",
        "color": (235, 190, 88),
        "res_name": "부동의 바위",
        "res_desc": "보호막 강화 +15% · 보호막 존재 시 가하는 피해 +15% · 바위 내성 -20%",
    },
}

GENSHIN_WEAPON_TYPE_MAP = {
    "WEAPON_SWORD_ONE_HAND": {"name": "한손검", "emoji": "🗡️"},
    "WEAPON_CLAYMORE": {"name": "양손검", "emoji": "⚔️"},
    "WEAPON_POLE": {"name": "장병기", "emoji": "🔱"},
    "WEAPON_BOW": {"name": "활", "emoji": "🏹"},
    "WEAPON_CATALYST": {"name": "법구", "emoji": "📖"},
}

GENSHIN_REGION_MAP = {
    "MONDSTADT": "몬드",
    "LIYUE": "리월",
    "INAZUMA": "이나즈마",
    "SUMERU": "수메르",
    "FONTAINE": "폰타인",
    "NATLAN": "나타",
    "SNEZHNAYA": "스네즈나야",
    "SNEZHNAYA_STAR": "스네즈나야",
    "NODKRAI": "노드크라이",
    "NODKRAI_ZIBAI": "노드크라이",
    "FATUI": "우인단 (스네즈나야)",
    "OMNI_SCOURGE": "이세계 / 심연",
    "HVISION": "티바트",
    "RANGER": "이세계 (콜라보)",
    "MAINACTOR": "티바트 (여행자)",
}

GENSHIN_STAT_MAP = {
    "FIGHT_PROP_CRITICAL": "치명타 확률",
    "FIGHT_PROP_CRITICAL_HURT": "치명타 피해",
    "FIGHT_PROP_ATTACK_PERCENT": "공격력 (%)",
    "FIGHT_PROP_HP_PERCENT": "HP (%)",
    "FIGHT_PROP_DEFENSE_PERCENT": "방어력 (%)",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "원소 충전 효율",
    "FIGHT_PROP_ELEMENT_MASTERY": "원소 마스터리",
    "FIGHT_PROP_HEAL_ADD": "치유 보너스",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "물리 피해 보너스",
    "FIGHT_PROP_FIRE_ADD_HURT": "불 원소 피해 보너스",
    "FIGHT_PROP_WATER_ADD_HURT": "물 원소 피해 보너스",
    "FIGHT_PROP_ICE_ADD_HURT": "얼음 원소 피해 보너스",
    "FIGHT_PROP_ELEC_ADD_HURT": "번개 원소 피해 보너스",
    "FIGHT_PROP_WIND_ADD_HURT": "바람 원소 피해 보너스",
    "FIGHT_PROP_GRASS_ADD_HURT": "풀 원소 피해 보너스",
    "FIGHT_PROP_ROCK_ADD_HURT": "바위 원소 피해 보너스",
    "NONE": "-",
}

# 상시 5성 캐릭터 8종 (50/50 실패 및 상시 기원)
GENSHIN_STD_5_CHARS = {
    "10000003",  # 진
    "10000016",  # 다이루크
    "10000035",  # 치치
    "10000041",  # 모나
    "10000042",  # 각청
    "10000069",  # 타이나리
    "10000079",  # 데히야
    "10000109",  # 유메미즈키 미즈키
}

# 초기 지급 4성 3인 (상시 기원 & 스타라이트 상점 전용)
GENSHIN_STARTER_4_CHARS = {
    "10000021",  # 엠버
    "10000015",  # 케이아
    "10000006",  # 리사
}

# 상시 5성 무기 10종
GENSHIN_STD_5_WEAPONS = {
    "11501", "11502",  # 매의 검, 천공의 검
    "12501", "12502",  # 천공의 긍지, 늑대의 말로
    "13502", "13505",  # 천공의 마루, 화박연
    "14501", "14502",  # 천공의 두루마리, 사풍 원서
    "15501", "15502",  # 천공의 날개, 아모스의 활
}

# 기원 드랍 3성 무기 13종 (나머지 11종은 필드/상자 전용)
GENSHIN_3_WISH_WEAPONS = {
    "11301", "11302", "11306",  # 차가운 칼날, 여명신검, 비천어검
    "12301", "12302", "12305",  # 강철의 그림자, 피에 물든 대검, 드래곤 블러드 소드
    "13303",                    # 흑술창
    "14301", "14302", "14304",  # 마도 서론, 드래곤 슬레이어 영웅담, 비취 오브
    "15301", "15302", "15304",  # 까마귀 깃 활, 신궁의 서약, 탄궁
}

# 상시 4성 무기 18종
GENSHIN_STD_4_WEAPONS = {
    "11401", "11402", "11403", "11405",
    "12401", "12402", "12403", "12405",
    "13401", "13407",
    "14401", "14402", "14403", "14409",
    "15401", "15402", "15403", "15405",
}

# 무기 이벤트 기원 한정 4성 무기
GENSHIN_LIMITED_4_WEAPONS = {
    "11410", "11418", "11427", "11430", "11434",
    "12410", "12415", "12416", "12427", "12430",
    "13406", "13416", "13427", "13430", "13434",
    "14410", "14416", "14427", "14430", "14434", "14437",
    "15410", "15412", "15416", "15427", "15430", "15434", "15437",
}

# 스타라이트 상점 교환 전용 무기 (흑암 & 왕실 시리즈)
GENSHIN_SHOP_WEAPONS = {
    "11404", "11408",
    "12404", "12408",
    "13404", "13408",
    "14404", "14408",
    "15404", "15408",
}

GENSHIN_BANNER_CONFIGS = {
    "char1": {
        "name": "🌠 캐릭터 이벤트 기원 ①",
        "short_name": "캐릭터 픽업 ①",
        "currency_name": "뒤얽힌 인연",
        "hard_pity": 90,
        "soft_start": 74,
        "base_5_pct": 0.6,
        "base_4_pct": 5.1,
        "color": (245, 198, 92),
        "desc": "한정 5성 캐릭터 ① 픽업 (90천장 · 74소프트 · 50/50 · 포착된 광휘)",
    },
    "char2": {
        "name": "🌙 캐릭터 이벤트 기원 ②",
        "short_name": "캐릭터 픽업 ②",
        "currency_name": "뒤얽힌 인연",
        "hard_pity": 90,
        "soft_start": 74,
        "base_5_pct": 0.6,
        "base_4_pct": 5.1,
        "color": (122, 168, 255),
        "desc": "한정 5성 캐릭터 ② 복각·더블 픽업 (캐릭터 ①과 천장 스택 공유!)",
    },
    "weapon": {
        "name": "⚔️ 신의 주조 (무기 이벤트 기원)",
        "short_name": "신의 주조 (무기)",
        "currency_name": "뒤얽힌 인연",
        "hard_pity": 80,
        "soft_start": 63,
        "base_5_pct": 0.7,
        "base_4_pct": 6.0,
        "color": (255, 159, 67),
        "desc": "픽업 5성 무기 2종 75% (80천장 · 63소프트 · 운명의 궤도 1/1 확정!)",
    },
    "standard": {
        "name": "🌌 세상 여행 (상시 기원)",
        "short_name": "상시 기원",
        "currency_name": "만남의 인연",
        "hard_pity": 90,
        "soft_start": 74,
        "base_5_pct": 0.6,
        "base_4_pct": 5.1,
        "color": (94, 158, 255),
        "desc": "상시 5성 캐릭터/무기 50:50 · 초기 4성(엠버·케이아·리사) 포함",
    },
    "artifact": {
        "name": "🏛️ 성유물 비경 기원 (시간·요일 로테이션)",
        "short_name": "성유물 비경",
        "currency_name": "축성 비경 레진",
        "hard_pity": 10,
        "soft_start": 10,
        "base_5_pct": 18.0,
        "base_4_pct": 62.0,
        "color": (56, 214, 158),
        "desc": "시각·요일별 비경 세트 픽업 & 부위 가중 (★5 18% · 10연차 ★5 최소 2개 보장)",
    },
}

class _GenshinArtifactSlotCatalog(list):
    """성유물 부위 카탈로그 — 튜플 순회 (sk, sname, semoji, m_pool)와 dict 조회 (.get / .keys / [slot_code]) 모두 지원"""
    def __init__(self, entries: list[dict]):
        super().__init__(
            (e["short_key"], e["name"], e["emoji"], e["main_pool"])
            for e in entries
        )
        self._by_key: dict[str, dict] = {}
        self._equip_keys: list[str] = []
        for e in entries:
            self._equip_keys.append(e["code"])
            self._by_key[e["code"]] = e
            self._by_key[e["short_key"]] = e

    def keys(self):
        return list(self._equip_keys)

    def get(self, key: str, default=None):
        return self._by_key.get(str(key), default)

    def __getitem__(self, item):
        if isinstance(item, int):
            return super().__getitem__(item)
        return self._by_key[str(item)]


# 성유물 5부위 스펙 & 축성의 서리(Elixir) 제작 비용
GENSHIN_ARTIFACT_SLOTS = _GenshinArtifactSlotCatalog([
    {
        "code": "EQUIP_BRACER",
        "short_key": "flower",
        "name": "생명의 꽃",
        "short": "꽃",
        "emoji": "🌸",
        "icon_sfx": "4",
        "icon_idx": "4",
        "elixir_cost": 1,
        "main_stats": ["HP (+)", "HP"],
        "main_pool": ["HP (+)", "HP"],
        "weights": [100.0],
    },
    {
        "code": "EQUIP_NECKLACE",
        "short_key": "plume",
        "name": "죽음의 깃털",
        "short": "깃",
        "emoji": "🪶",
        "icon_sfx": "2",
        "icon_idx": "2",
        "elixir_cost": 1,
        "main_stats": ["공격력 (+)", "공격력"],
        "main_pool": ["공격력 (+)", "공격력"],
        "weights": [100.0],
    },
    {
        "code": "EQUIP_SHOES",
        "short_key": "sands",
        "name": "시간의 모래",
        "short": "시계",
        "emoji": "⏳",
        "icon_sfx": "5",
        "icon_idx": "5",
        "elixir_cost": 2,
        "main_stats": ["공격력 (%)", "HP (%)", "방어력 (%)", "원소 충전 효율", "원소 마스터리"],
        "main_pool": ["공격력 (%)", "HP (%)", "방어력 (%)", "원소 충전 효율", "원소 마스터리"],
        "weights": [26.68, 26.68, 26.64, 10.0, 10.0],
    },
    {
        "code": "EQUIP_RING",
        "short_key": "goblet",
        "name": "공간의 성배",
        "short": "성배",
        "emoji": "🏆",
        "icon_sfx": "1",
        "icon_idx": "1",
        "elixir_cost": 4,
        "main_stats": [
            "공격력 (%)", "HP (%)", "방어력 (%)",
            "불 원소 피해 보너스", "물 원소 피해 보너스", "번개 원소 피해 보너스",
            "얼음 원소 피해 보너스", "바람 원소 피해 보너스", "바위 원소 피해 보너스",
            "풀 원소 피해 보너스", "물리 피해 보너스", "원소 마스터리",
        ],
        "main_pool": [
            "공격력 (%)", "HP (%)", "방어력 (%)",
            "불 원소 피해 보너스", "물 원소 피해 보너스", "번개 원소 피해 보너스",
            "얼음 원소 피해 보너스", "바람 원소 피해 보너스", "바위 원소 피해 보너스",
            "풀 원소 피해 보너스", "물리 피해 보너스", "원소 마스터리",
        ],
        "weights": [19.25, 19.25, 19.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 2.5],
    },
    {
        "code": "EQUIP_DRESS",
        "short_key": "circlet",
        "name": "이성의 왕관",
        "short": "왕관",
        "emoji": "👑",
        "icon_sfx": "3",
        "icon_idx": "3",
        "elixir_cost": 3,
        "main_stats": ["치명타 확률", "치명타 피해", "공격력 (%)", "HP (%)", "방어력 (%)", "치유 보너스", "원소 마스터리"],
        "main_pool": ["치명타 확률", "치명타 피해", "공격력 (%)", "HP (%)", "방어력 (%)", "치유 보너스", "원소 마스터리"],
        "weights": [10.0, 10.0, 22.0, 22.0, 22.0, 10.0, 4.0],
    },
])

_GI_MAIN_BASE = {
    "HP (+)": (717.0, 4780.0, False),
    "HP": (717.0, 4780.0, False),
    "공격력 (+)": (47.0, 311.0, False),
    "공격력": (47.0, 311.0, False),
    "HP (%)": (7.0, 46.6, True),
    "HP%": (7.0, 46.6, True),
    "공격력 (%)": (7.0, 46.6, True),
    "공격력%": (7.0, 46.6, True),
    "방어력 (%)": (8.7, 58.3, True),
    "방어력%": (8.7, 58.3, True),
    "원소 충전 효율": (7.8, 51.8, True),
    "원소 마스터리": (28.0, 187.0, False),
    "치명타 확률": (4.7, 31.1, True),
    "치명타 피해": (9.3, 62.2, True),
    "치유 보너스": (5.4, 35.9, True),
    "물리 피해 보너스": (8.7, 58.3, True),
    "불 원소 피해 보너스": (7.0, 46.6, True),
    "물 원소 피해 보너스": (7.0, 46.6, True),
    "번개 원소 피해 보너스": (7.0, 46.6, True),
    "얼음 원소 피해 보너스": (7.0, 46.6, True),
    "바람 원소 피해 보너스": (7.0, 46.6, True),
    "바위 원소 피해 보너스": (7.0, 46.6, True),
    "풀 원소 피해 보너스": (7.0, 46.6, True),
}

GENSHIN_ARTIFACT_MAIN_VALUES: dict = dict(_GI_MAIN_BASE)
for _m_name, (_v0, _vm, _is_pct) in _GI_MAIN_BASE.items():
    for _rk, _sc in ((5, 1.0), (4, 0.75), (3, 0.55)):
        if _is_pct:
            GENSHIN_ARTIFACT_MAIN_VALUES[(_rk, _m_name)] = (f"+{_v0 * _sc:.1f}%", f"+{_vm * _sc:.1f}%")
        else:
            GENSHIN_ARTIFACT_MAIN_VALUES[(_rk, _m_name)] = (f"+{int(round(_v0 * _sc)):,}", f"+{int(round(_vm * _sc)):,}")

GENSHIN_ARTIFACT_SUBSTATS = [
    ("치명타 확률", [2.7, 3.1, 3.5, 3.9], True),
    ("치명타 피해", [5.4, 6.2, 7.0, 7.8], True),
    ("공격력 (%)", [4.1, 4.7, 5.3, 5.8], True),
    ("원소 충전 효율", [4.5, 5.2, 5.8, 6.5], True),
    ("원소 마스터리", [16.0, 19.0, 21.0, 23.0], False),
    ("HP (%)", [4.1, 4.7, 5.3, 5.8], True),
    ("방어력 (%)", [5.1, 5.8, 6.6, 7.3], True),
    ("공격력 (+)", [14.0, 16.0, 18.0, 19.0], False),
    ("HP (+)", [209.0, 239.0, 269.0, 299.0], False),
    ("방어력 (+)", [16.0, 19.0, 21.0, 23.0], False),
]

GENSHIN_ARTIFACT_SUB_MAX_MAP = {
    s[0]: float(s[1][-1]) for s in GENSHIN_ARTIFACT_SUBSTATS
}
GENSHIN_ARTIFACT_SUB_MAX_MAP.update({
    "공격력%": 5.8,
    "HP%": 5.8,
    "방어력%": 7.3,
})

# 스타라이트 상점 6개월 순환 4성 캐릭터 로테이션 (매월 2명씩 1·7 / 2·8 / 3·9 / 4·10 / 5·11 / 6·12월)
GENSHIN_STARGLITTER_CHAR_ROTATION = [
    ("10000031", "10000023"),  # 1·7월: 피슬 · 향릉
    ("10000024", "10000034"),  # 2·8월: 북두 · 노엘
    ("10000027", "10000025"),  # 3·9월: 응광 · 행추
    ("10000020", "10000021"),  # 4·10월: 레이저 · 엠버
    ("10000032", "10000006"),  # 5·11월: 베넷 · 리사
    ("10000014", "10000015"),  # 6·12월: 바바라 · 케이아
]

# 대표 픽업 프리셋 (봇주인 픽업설정용)
GENSHIN_BANNER_PRESETS = {
    "latest": {
        "label": "🌟 최신 캐릭터 자동 연동",
        "banner_name": "최신 버전 기원",
        "char1": None,
        "char2": None,
        "char_4_ids": [],
        "weapon_1": None,
        "weapon_2": None,
    },
    "snezhnaya_star": {
        "label": "❄️ 스네즈나야 여명 & 서리별 (미탸 / 베스나)",
        "banner_name": "서리별의 계시 & 봄바람의 우화",
        "char1": "10000136",  # 미탸
        "char2": "10000143",  # 베스나
        "char_4_ids": ["10000137", "10000148", "10000132"],  # 발레리, 알료샤, 프루네
        "weapon_1": "14525",  # 별빛 계시
        "weapon_2": "11522",  # 나비의 우화
    },
    "fontaine_archon": {
        "label": "💧 폰타인 물의 신 & 최고 심판관 (푸리나 / 느비예트)",
        "banner_name": "뭇별의 노래 & 궁정의 물결",
        "char1": "10000089",  # 푸리나
        "char2": "10000087",  # 느비예트
        "char_4_ids": ["10000088", "10000025", "10000031"],  # 샤를로트, 행추, 피슬
        "weapon_1": "11513",  # 고요히 샘솟는 빛
        "weapon_2": "14514",  # 영원히 샘솟는 법전
    },
    "natlan_archon": {
        "label": "🔥 나타 불의 신 & 밤바람 (마비카 / 시틀라리)",
        "banner_name": "태양을 품은 불꽃 & 별빛 장막",
        "char1": "10000106",  # 마비카
        "char2": "10000107",  # 시틀라리
        "char_4_ids": ["10000100", "10000032", "10000068"],  # 카치나, 베넷, 도리
        "weapon_1": "12514",  # 타오르는 천 개의 태양
        "weapon_2": "14517",  # 별지기의 시선
    },
    "inazuma_thunder": {
        "label": "⚡ 이나즈마 번개의 신 & 우인단 (라이덴 쇼군 / 아를레키노)",
        "banner_name": "영원의 정토 & 붉은 달의 그림자",
        "char1": "10000052",  # 라이덴 쇼군
        "char2": "10000096",  # 아를레키노
        "char_4_ids": ["10000056", "10000090", "10000032"],  # 쿠죠 사라, 슈브르즈, 베넷
        "weapon_1": "13509",  # 예초의 번개
        "weapon_2": "13512",  # 붉은 달의 형상
    },
    "sumeru_dendro": {
        "label": "🌿 수메르 풀의 신 & 유랑자 (나히다 / 방랑자)",
        "banner_name": "지혜의 달빛 & 부평초의 노래",
        "char1": "10000073",  # 나히다
        "char2": "10000075",  # 방랑자
        "char_4_ids": ["10000076", "10000074", "10000065"],  # 파루잔, 레일라, 쿠키 시노부
        "weapon_1": "14511",  # 떠오르는 천일 밤의 꿈
        "weapon_2": "14512",  # 툴레이툴라의 기억
    },
}

# 오프라인/네트워크 장애 대비 내장 최소 폴백 데이터
GENSHIN_EMBEDDED_FALLBACK_CHARS = [
    {"id": "10000089", "kind": "char", "name": "푸리나", "rank": 5, "element": "Water", "weapon_type": "WEAPON_SWORD_ONE_HAND", "region": "FONTAINE", "special_prop": "FIGHT_PROP_CRITICAL", "icon": "UI_AvatarIcon_Furina", "release": 1699416000, "pool_type": "한정"},
    {"id": "10000087", "kind": "char", "name": "느비예트", "rank": 5, "element": "Water", "weapon_type": "WEAPON_CATALYST", "region": "FONTAINE", "special_prop": "FIGHT_PROP_CRITICAL_HURT", "icon": "UI_AvatarIcon_Neuvillette", "release": 1695787200, "pool_type": "한정"},
    {"id": "10000052", "kind": "char", "name": "라이덴 쇼군", "rank": 5, "element": "Electric", "weapon_type": "WEAPON_POLE", "region": "INAZUMA", "special_prop": "FIGHT_PROP_CHARGE_EFFICIENCY", "icon": "UI_AvatarIcon_Shougun", "release": 1630468800, "pool_type": "한정"},
    {"id": "10000073", "kind": "char", "name": "나히다", "rank": 5, "element": "Grass", "weapon_type": "WEAPON_CATALYST", "region": "SUMERU", "special_prop": "FIGHT_PROP_ELEMENT_MASTERY", "icon": "UI_AvatarIcon_Nahida", "release": 1667361600, "pool_type": "한정"},
    {"id": "10000003", "kind": "char", "name": "진", "rank": 5, "element": "Wind", "weapon_type": "WEAPON_SWORD_ONE_HAND", "region": "MONDSTADT", "special_prop": "FIGHT_PROP_HEAL_ADD", "icon": "UI_AvatarIcon_Qin", "release": 1601265600, "pool_type": "상시"},
    {"id": "10000016", "kind": "char", "name": "다이루크", "rank": 5, "element": "Fire", "weapon_type": "WEAPON_CLAYMORE", "region": "MONDSTADT", "special_prop": "FIGHT_PROP_CRITICAL", "icon": "UI_AvatarIcon_Diluc", "release": 1601265600, "pool_type": "상시"},
    {"id": "10000041", "kind": "char", "name": "모나", "rank": 5, "element": "Water", "weapon_type": "WEAPON_CATALYST", "region": "MONDSTADT", "special_prop": "FIGHT_PROP_CHARGE_EFFICIENCY", "icon": "UI_AvatarIcon_Mona", "release": 1601265600, "pool_type": "상시"},
    {"id": "10000032", "kind": "char", "name": "베넷", "rank": 4, "element": "Fire", "weapon_type": "WEAPON_SWORD_ONE_HAND", "region": "MONDSTADT", "special_prop": "FIGHT_PROP_CHARGE_EFFICIENCY", "icon": "UI_AvatarIcon_Bennett", "release": 1601265600, "pool_type": "상시"},
    {"id": "10000025", "kind": "char", "name": "행추", "rank": 4, "element": "Water", "weapon_type": "WEAPON_SWORD_ONE_HAND", "region": "LIYUE", "special_prop": "FIGHT_PROP_ATTACK_PERCENT", "icon": "UI_AvatarIcon_Xingqiu", "release": 1601265600, "pool_type": "상시"},
    {"id": "10000031", "kind": "char", "name": "피슬", "rank": 4, "element": "Electric", "weapon_type": "WEAPON_BOW", "region": "MONDSTADT", "special_prop": "FIGHT_PROP_ATTACK_PERCENT", "icon": "UI_AvatarIcon_Fischl", "release": 1601265600, "pool_type": "상시"},
    {"id": "10000023", "kind": "char", "name": "향릉", "rank": 4, "element": "Fire", "weapon_type": "WEAPON_POLE", "region": "LIYUE", "special_prop": "FIGHT_PROP_ELEMENT_MASTERY", "icon": "UI_AvatarIcon_Xiangling", "release": 1601265600, "pool_type": "상시"},
]

GENSHIN_EMBEDDED_FALLBACK_WEAPONS = [
    {"id": "11509", "kind": "weapon", "name": "안개를 가르는 회광", "rank": 5, "weapon_type": "WEAPON_SWORD_ONE_HAND", "special_prop": "FIGHT_PROP_CRITICAL_HURT", "icon": "UI_EquipIcon_Sword_Narukami", "wish_source": "limited", "pool_type": "무기한정"},
    {"id": "13509", "kind": "weapon", "name": "예초의 번개", "rank": 5, "weapon_type": "WEAPON_POLE", "special_prop": "FIGHT_PROP_CHARGE_EFFICIENCY", "icon": "UI_EquipIcon_Pole_Narukami", "wish_source": "limited", "pool_type": "무기한정"},
    {"id": "11501", "kind": "weapon", "name": "매의 검", "rank": 5, "weapon_type": "WEAPON_SWORD_ONE_HAND", "special_prop": "FIGHT_PROP_PHYSICAL_ADD_HURT", "icon": "UI_EquipIcon_Sword_Falcon", "wish_source": "standard", "pool_type": "상시"},
    {"id": "12502", "kind": "weapon", "name": "늑대의 말로", "rank": 5, "weapon_type": "WEAPON_CLAYMORE", "special_prop": "FIGHT_PROP_ATTACK_PERCENT", "icon": "UI_EquipIcon_Claymore_Wolfmound", "wish_source": "standard", "pool_type": "상시"},
    {"id": "11403", "kind": "weapon", "name": "제례검", "rank": 4, "weapon_type": "WEAPON_SWORD_ONE_HAND", "special_prop": "FIGHT_PROP_CHARGE_EFFICIENCY", "icon": "UI_EquipIcon_Sword_Fossil", "wish_source": "standard", "pool_type": "상시"},
    {"id": "14402", "kind": "weapon", "name": "음유시인의 악장", "rank": 4, "weapon_type": "WEAPON_CATALYST", "special_prop": "FIGHT_PROP_CRITICAL_HURT", "icon": "UI_EquipIcon_Catalyst_Troupe", "wish_source": "standard", "pool_type": "상시"},
    {"id": "15402", "kind": "weapon", "name": "절현", "rank": 4, "weapon_type": "WEAPON_BOW", "special_prop": "FIGHT_PROP_ELEMENT_MASTERY", "icon": "UI_EquipIcon_Bow_Troupe", "wish_source": "standard", "pool_type": "상시"},
    {"id": "11302", "kind": "weapon", "name": "여명신검", "rank": 3, "weapon_type": "WEAPON_SWORD_ONE_HAND", "special_prop": "FIGHT_PROP_CRITICAL_HURT", "icon": "UI_EquipIcon_Sword_Dawn", "wish_source": "standard", "pool_type": "상시"},
    {"id": "14302", "kind": "weapon", "name": "드래곤 슬레이어 영웅담", "rank": 3, "weapon_type": "WEAPON_CATALYST", "special_prop": "FIGHT_PROP_HP_PERCENT", "icon": "UI_EquipIcon_Catalyst_Pulpfic", "wish_source": "standard", "pool_type": "상시"},
    {"id": "13303", "kind": "weapon", "name": "흑술창", "rank": 3, "weapon_type": "WEAPON_POLE", "special_prop": "FIGHT_PROP_HP_PERCENT", "icon": "UI_EquipIcon_Pole_Noire", "wish_source": "standard", "pool_type": "상시"},
]

GENSHIN_EMBEDDED_FALLBACK_ARTIFACTS = [
    {"id": "15048", "kind": "artifact", "item_key": "artifact:15048", "name": "용광로가 빚은 심장", "max_rank": 5, "min_rank": 4, "level_list": [4, 5], "bonus_2pc": "공격력+18%", "bonus_4pc": "별빛 반응 피해 +50%", "icon": "UI_RelicIcon_15048_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 127},
    {"id": "15020", "kind": "artifact", "item_key": "artifact:15020", "name": "절연의 기치", "max_rank": 5, "min_rank": 4, "level_list": [4, 5], "bonus_2pc": "원소 충전 효율 +20%", "bonus_4pc": "원소폭발 피해가 원충의 25%만큼 증가", "icon": "UI_RelicIcon_15020_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 90},
    {"id": "15032", "kind": "artifact", "item_key": "artifact:15032", "name": "황금 극단", "max_rank": 5, "min_rank": 4, "level_list": [4, 5], "bonus_2pc": "원소전투 스킬 피해 +20%", "bonus_4pc": "대기 시 원소전투 스킬 피해 추가 +25%", "icon": "UI_RelicIcon_15032_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 108},
    {"id": "15031", "kind": "artifact", "item_key": "artifact:15031", "name": "그림자 사냥꾼", "max_rank": 5, "min_rank": 4, "level_list": [4, 5], "bonus_2pc": "일반/강공격 피해 +15%", "bonus_4pc": "HP 증감 시 치명타 확률 최대 +36%", "icon": "UI_RelicIcon_15031_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 107},
    {"id": "15038", "kind": "artifact", "item_key": "artifact:15038", "name": "흑요석 비전", "max_rank": 5, "min_rank": 4, "level_list": [4, 5], "bonus_2pc": "밤혼 가호 시 피해 +15%", "bonus_4pc": "밤혼 소모 후 치명타 확률 +40%", "icon": "UI_RelicIcon_15038_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 115},
    {"id": "15006", "kind": "artifact", "item_key": "artifact:15006", "name": "불타오르는 화염의 마녀", "max_rank": 5, "min_rank": 4, "level_list": [4, 5], "bonus_2pc": "불 원소 피해 보너스 +15%", "bonus_4pc": "과부하/연소/증발/융해 반응 피해 증가", "icon": "UI_RelicIcon_15006_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 75},
    {"id": "10007", "kind": "artifact", "item_key": "artifact:10007", "name": "교관", "max_rank": 4, "min_rank": 3, "level_list": [3, 4], "bonus_2pc": "원소 마스터리 +80pt", "bonus_4pc": "원소 반응 발동 후 파티 원마 +120pt", "icon": "UI_RelicIcon_10007_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 20},
    {"id": "10005", "kind": "artifact", "item_key": "artifact:10005", "name": "전투광", "max_rank": 4, "min_rank": 3, "level_list": [3, 4], "bonus_2pc": "치명타 확률 +12%", "bonus_4pc": "HP 70% 미만 시 치확 +24%", "icon": "UI_RelicIcon_10005_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 18},
    {"id": "10010", "kind": "artifact", "item_key": "artifact:10010", "name": "모험가", "max_rank": 3, "min_rank": 1, "level_list": [1, 2, 3], "bonus_2pc": "HP 최대치 +1000pt", "bonus_4pc": "보물 상자 오픈 시 HP 30% 회복", "icon": "UI_RelicIcon_10010_4", "is_single_piece": False, "allowed_slots": list(GENSHIN_ARTIFACT_SLOTS.keys()), "sort_order": 10},
]


def _clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).replace("\xa0", " ").replace("\\n", "\n")
    s = re.sub(r"<color=[^>]+>|</color>|<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _should_exclude_avatar(cid: str, raw: dict, now_ts: float) -> bool:
    if cid.startswith("10000005") or cid.startswith("10000007"):  # 여행자
        return True
    if cid in ("10000117", "10000118", "10000062"):  # 별인형 / 에일로이
        return True
    if raw.get("beta"):
        return True
    elem = raw.get("element")
    if not elem or elem == "None":
        return True
    reg = str(raw.get("region") or "")
    if reg in ("MAINACTOR", "RANGER"):
        return True
    rel = raw.get("release") or 0
    if isinstance(rel, (int, float)) and rel > now_ts + 86400:
        return True
    return False


def _parse_genshin_items(avatar_items: dict, weapon_items: dict) -> tuple[list[dict], list[dict]]:
    now_ts = time.time()
    chars: list[dict] = []
    weapons: list[dict] = []

    for cid, raw in avatar_items.items():
        if not isinstance(raw, dict):
            continue
        cid_s = str(raw.get("id") or cid)
        if _should_exclude_avatar(cid_s, raw, now_ts):
            continue
        rank = int(raw.get("rank") or 4)
        if rank not in (4, 5):
            continue
        elem_code = str(raw.get("element") or "Wind")
        elem_info = GENSHIN_ELEMENT_MAP.get(elem_code, GENSHIN_ELEMENT_MAP["Wind"])
        wtype_code = str(raw.get("weaponType") or "WEAPON_SWORD_ONE_HAND")
        wtype_info = GENSHIN_WEAPON_TYPE_MAP.get(wtype_code, GENSHIN_WEAPON_TYPE_MAP["WEAPON_SWORD_ONE_HAND"])
        reg_code = str(raw.get("region") or "")
        reg_name = GENSHIN_REGION_MAP.get(reg_code, reg_code or "티바트")

        if rank == 5:
            if cid_s in GENSHIN_STD_5_CHARS:
                pool_type = "상시"
            else:
                pool_type = "한정"
        else:
            pool_type = "초기지급(상시)" if cid_s in GENSHIN_STARTER_4_CHARS else "상시"

        chars.append({
            "id": cid_s,
            "kind": "char",
            "item_key": f"char:{cid_s}",
            "name": _clean_text(raw.get("name")) or f"캐릭터 {cid_s}",
            "rank": rank,
            "rarity_label": "★★★★★" if rank == 5 else "★★★★",
            "element": elem_code,
            "element_name": elem_info["name"],
            "element_emoji": elem_info["emoji"],
            "weapon_type": wtype_code,
            "weapon_type_name": wtype_info["name"],
            "weapon_type_emoji": wtype_info["emoji"],
            "region": reg_code,
            "region_name": reg_name,
            "special_prop": str(raw.get("specialProp") or "NONE"),
            "special_prop_name": GENSHIN_STAT_MAP.get(str(raw.get("specialProp") or "NONE"), "-"),
            "icon": str(raw.get("icon") or ""),
            "release": int(raw.get("release") or 0),
            "pool_type": pool_type,
            "wishable": True,
        })

    for wid, raw in weapon_items.items():
        if not isinstance(raw, dict):
            continue
        wid_s = str(raw.get("id") or wid)
        if not wid_s.isdigit():
            continue
        w_int = int(wid_s)
        if not (11000 <= w_int < 16000):
            continue
        if raw.get("beta"):
            continue
        rank = int(raw.get("rank") or 3)
        if rank not in (3, 4, 5):
            continue

        wtype_code = str(raw.get("type") or raw.get("weaponType") or "WEAPON_SWORD_ONE_HAND")
        wtype_info = GENSHIN_WEAPON_TYPE_MAP.get(wtype_code, GENSHIN_WEAPON_TYPE_MAP["WEAPON_SWORD_ONE_HAND"])

        if rank == 5:
            if wid_s in GENSHIN_STD_5_WEAPONS:
                wish_source = "standard"
                pool_type = "상시"
                wishable = True
            else:
                wish_source = "limited"
                pool_type = "무기한정"
                wishable = True
        elif rank == 4:
            if wid_s in GENSHIN_STD_4_WEAPONS:
                wish_source = "standard"
                pool_type = "상시"
                wishable = True
            elif wid_s in GENSHIN_LIMITED_4_WEAPONS:
                wish_source = "limited"
                pool_type = "무기한정"
                wishable = True
            elif wid_s in GENSHIN_SHOP_WEAPONS:
                wish_source = "shop"
                pool_type = "스타라이트 상점"
                wishable = False
            else:
                wish_source = "non_gacha"
                pool_type = "단조/이벤트/기행"
                wishable = False
        else:
            if wid_s in GENSHIN_3_WISH_WEAPONS:
                wish_source = "standard"
                pool_type = "기원 상시"
                wishable = True
            else:
                wish_source = "chest"
                pool_type = "필드/상자"
                wishable = False

        weapons.append({
            "id": wid_s,
            "kind": "weapon",
            "item_key": f"weapon:{wid_s}",
            "name": _clean_text(raw.get("name")) or f"무기 {wid_s}",
            "rank": rank,
            "rarity_label": "★★★★★" if rank == 5 else ("★★★★" if rank == 4 else "★★★"),
            "weapon_type": wtype_code,
            "weapon_type_name": wtype_info["name"],
            "weapon_type_emoji": wtype_info["emoji"],
            "special_prop": str(raw.get("specialProp") or "NONE"),
            "special_prop_name": GENSHIN_STAT_MAP.get(str(raw.get("specialProp") or "NONE"), "-"),
            "icon": str(raw.get("icon") or ""),
            "wish_source": wish_source,
            "pool_type": pool_type,
            "wishable": wishable,
        })

    chars.sort(key=lambda x: (-x["rank"], -x["release"], x["id"]))
    weapons.sort(key=lambda x: (-x["rank"], -int(x["id"]) if str(x.get("id", "")).isdigit() else 0))
    return chars, weapons


def _parse_genshin_reliquaries(reliquary_items: dict) -> list[dict]:
    artifacts: list[dict] = []
    for rid, raw in (reliquary_items or {}).items():
        if not isinstance(raw, dict):
            continue
        rid_s = str(raw.get("id") or rid)
        if rid_s in ("15000", "15004", "15012"):
            continue
        if raw.get("beta"):
            continue
        level_list = [int(x) for x in (raw.get("levelList") or []) if str(x).isdigit()]
        if not level_list:
            continue
        max_rank = max(level_list)
        min_rank = min(level_list)
        if max_rank < 3:
            continue
        affix_map = raw.get("affixList") or {}
        affix_vals = [_clean_text(v) for _, v in sorted(affix_map.items(), key=lambda kv: str(kv[0])) if _clean_text(v)]
        if not affix_vals:
            continue
        is_single = len(affix_vals) == 1 or rid_s in ("15009", "15010", "15011", "15013")
        bonus_2pc = affix_vals[0]
        bonus_4pc = affix_vals[1] if len(affix_vals) > 1 else "1세트 효과: " + affix_vals[0]
        allowed_slots = ["EQUIP_DRESS"] if is_single else list(GENSHIN_ARTIFACT_SLOTS.keys())
        artifacts.append({
            "id": rid_s,
            "kind": "artifact",
            "item_key": f"artifact:{rid_s}",
            "name": _clean_text(raw.get("name")) or f"성유물 {rid_s}",
            "rank": max_rank,
            "max_rank": max_rank,
            "min_rank": min_rank,
            "level_list": sorted(level_list),
            "rarity_label": "★" * max_rank,
            "bonus_2pc": bonus_2pc,
            "bonus_4pc": bonus_4pc,
            "icon": str(raw.get("icon") or f"UI_RelicIcon_{rid_s}_4"),
            "is_single_piece": is_single,
            "allowed_slots": allowed_slots,
            "sort_order": int(raw.get("sortOrder") or 0),
            "pool_type": "5성 비경" if max_rank == 5 else ("4성 비경" if max_rank == 4 else "모험 비경"),
            "wishable": True,
        })
    artifacts.sort(key=lambda x: (-x["max_rank"], -int(x["id"]) if str(x["id"]).isdigit() else 0))
    return artifacts


def _normalize_fallback_artifacts() -> list[dict]:
    arts = []
    for a in GENSHIN_EMBEDDED_FALLBACK_ARTIFACTS:
        mr = int(a.get("max_rank", 5))
        arts.append({
            **a,
            "rank": mr,
            "rarity_label": "★" * mr,
            "pool_type": "5성 비경" if mr == 5 else ("4성 비경" if mr == 4 else "모험 비경"),
            "wishable": True,
        })
    arts.sort(key=lambda x: (-x["max_rank"], -int(x["id"]) if str(x["id"]).isdigit() else 0))
    return arts


def _set_db_state(chars: list[dict], weapons: list[dict], fetched_at: float, artifacts: list[dict] | None = None):
    global GENSHIN_CHARS, GENSHIN_WEAPONS, GENSHIN_ARTIFACTS, GENSHIN_ARTIFACT_MAP, GENSHIN_ALL_ITEMS, _GENSHIN_LAST_FETCH
    chars.sort(key=lambda x: (-x["rank"], -x.get("release", 0), x.get("id", "")))
    weapons.sort(key=lambda x: (-x["rank"], -int(x["id"]) if str(x.get("id", "")).isdigit() else 0))
    if not artifacts:
        artifacts = GENSHIN_ARTIFACTS or _normalize_fallback_artifacts()
    else:
        artifacts.sort(key=lambda x: (-x.get("max_rank", 5), -int(x["id"]) if str(x.get("id", "")).isdigit() else 0))
    GENSHIN_CHARS = chars
    GENSHIN_WEAPONS = weapons
    GENSHIN_ARTIFACTS = artifacts
    GENSHIN_ARTIFACT_MAP = {str(a["id"]): a for a in artifacts}
    merged: dict[str, dict] = {}
    for c in chars:
        merged[c["item_key"]] = c
    for w in weapons:
        merged[w["item_key"]] = w
    for a in artifacts:
        merged[a["item_key"]] = a
    GENSHIN_ALL_ITEMS = merged
    _GENSHIN_LAST_FETCH = fetched_at


def _normalize_fallback():
    chars = []
    for c in GENSHIN_EMBEDDED_FALLBACK_CHARS:
        elem = GENSHIN_ELEMENT_MAP.get(c["element"], GENSHIN_ELEMENT_MAP["Wind"])
        wt = GENSHIN_WEAPON_TYPE_MAP.get(c["weapon_type"], GENSHIN_WEAPON_TYPE_MAP["WEAPON_SWORD_ONE_HAND"])
        chars.append({
            **c,
            "item_key": f"char:{c['id']}",
            "rarity_label": "★★★★★" if c["rank"] == 5 else "★★★★",
            "element_name": elem["name"],
            "element_emoji": elem["emoji"],
            "weapon_type_name": wt["name"],
            "weapon_type_emoji": wt["emoji"],
            "region_name": GENSHIN_REGION_MAP.get(c["region"], c["region"]),
            "special_prop_name": GENSHIN_STAT_MAP.get(c["special_prop"], "-"),
            "wishable": True,
        })
    weapons = []
    for w in GENSHIN_EMBEDDED_FALLBACK_WEAPONS:
        wt = GENSHIN_WEAPON_TYPE_MAP.get(w["weapon_type"], GENSHIN_WEAPON_TYPE_MAP["WEAPON_SWORD_ONE_HAND"])
        weapons.append({
            **w,
            "item_key": f"weapon:{w['id']}",
            "rarity_label": "★★★★★" if w["rank"] == 5 else ("★★★★" if w["rank"] == 4 else "★★★"),
            "weapon_type_name": wt["name"],
            "weapon_type_emoji": wt["emoji"],
            "special_prop_name": GENSHIN_STAT_MAP.get(w["special_prop"], "-"),
            "wishable": True,
        })
    return chars, weapons


def hydrate_genshin_kr_cache_from_disk() -> bool:
    """디스크의 원신 한국어 DB 캐시가 있으면 즉시 메모리에 적재합니다."""
    if not os.path.exists(GENSHIN_CACHE_FILE):
        return False
    try:
        with open(GENSHIN_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if int(payload.get("schema_version") or 1) < GENSHIN_CACHE_VERSION:
            return False
        chars = payload.get("chars") or []
        weapons = payload.get("weapons") or []
        artifacts = payload.get("artifacts") or []
        fetched_at = float(payload.get("fetched_at") or 0.0)
        if chars and weapons and artifacts:
            _set_db_state(chars, weapons, fetched_at, artifacts)
            return True
    except Exception:
        pass
    return False


def load_genshin_kr_db(force_refresh: bool = False) -> tuple[list[dict], list[dict]]:
    """원신 한국어 DB(캐릭터·무기·성유물)를 실시간(gi.yatta.moe/kr)에서 동기화하고 로컬 캐시에 저장합니다."""
    with _GENSHIN_DB_LOCK:
        now = time.time()
        if not force_refresh and GENSHIN_CHARS and GENSHIN_WEAPONS and GENSHIN_ARTIFACTS and (now - _GENSHIN_LAST_FETCH < GENSHIN_CACHE_TTL):
            return GENSHIN_CHARS, GENSHIN_WEAPONS

        if not force_refresh and (not GENSHIN_CHARS or not GENSHIN_ARTIFACTS) and hydrate_genshin_kr_cache_from_disk():
            if now - _GENSHIN_LAST_FETCH < GENSHIN_CACHE_TTL:
                return GENSHIN_CHARS, GENSHIN_WEAPONS

        try:
            r_av = requests.get("https://gi.yatta.moe/api/v2/kr/avatar", timeout=15)
            r_wp = requests.get("https://gi.yatta.moe/api/v2/kr/weapon", timeout=15)
            r_art = requests.get("https://gi.yatta.moe/api/v2/kr/reliquary", timeout=15)
            if r_av.status_code == 200 and r_wp.status_code == 200:
                av_data = (r_av.json().get("data") or {}).get("items") or {}
                wp_data = (r_wp.json().get("data") or {}).get("items") or {}
                art_data = (r_art.json().get("data") or {}).get("items") or {} if r_art.status_code == 200 else {}
                chars, weapons = _parse_genshin_items(av_data, wp_data)
                artifacts = _parse_genshin_reliquaries(art_data) if art_data else _normalize_fallback_artifacts()
                if chars and weapons:
                    _set_db_state(chars, weapons, now, artifacts)
                    try:
                        tmp_f = f"{GENSHIN_CACHE_FILE}.tmp"
                        with open(tmp_f, "w", encoding="utf-8") as f:
                            json.dump({
                                "schema_version": GENSHIN_CACHE_VERSION,
                                "fetched_at": now,
                                "chars": chars,
                                "weapons": weapons,
                                "artifacts": artifacts,
                            }, f, ensure_ascii=False)
                        os.replace(tmp_f, GENSHIN_CACHE_FILE)
                    except Exception:
                        pass
                    return GENSHIN_CHARS, GENSHIN_WEAPONS
        except Exception as e:
            print(f"⚠️ [원신 DB 동기화 경고] {e}", flush=True)

        if GENSHIN_CHARS and GENSHIN_WEAPONS:
            if not GENSHIN_ARTIFACTS:
                _set_db_state(GENSHIN_CHARS, GENSHIN_WEAPONS, _GENSHIN_LAST_FETCH, _normalize_fallback_artifacts())
            return GENSHIN_CHARS, GENSHIN_WEAPONS

        fb_chars, fb_weapons = _normalize_fallback()
        _set_db_state(fb_chars, fb_weapons, 0.0, _normalize_fallback_artifacts())
        return GENSHIN_CHARS, GENSHIN_WEAPONS


def get_genshin_artifacts() -> list[dict]:
    if not GENSHIN_ARTIFACTS:
        load_genshin_kr_db()
    return GENSHIN_ARTIFACTS


def get_genshin_artifact_by_id(set_id: str | int) -> dict | None:
    if not GENSHIN_ARTIFACT_MAP:
        load_genshin_kr_db()
    return GENSHIN_ARTIFACT_MAP.get(str(set_id))


def fetch_genshin_detail_kr(item_id: str, kind: str = "char") -> dict:
    """캐릭터/무기/성유물 상세 정보(이명·운명의 자리·소속·소개 대사/설명/부위 스토리)를 지연 로드 후 캐시합니다."""
    cache_key = f"{kind}:{item_id}"
    with _GENSHIN_DETAIL_LOCK:
        if cache_key in _GENSHIN_DETAIL_CACHE:
            _GENSHIN_DETAIL_CACHE.move_to_end(cache_key)
            return _GENSHIN_DETAIL_CACHE[cache_key]

    endpoint = "avatar" if kind == "char" else ("reliquary" if kind == "artifact" else "weapon")
    detail_info: dict = {}
    try:
        res = requests.get(f"https://gi.yatta.moe/api/v2/kr/{endpoint}/{item_id}", timeout=10)
        if res.status_code == 200:
            d = res.json().get("data") or {}
            if kind == "char":
                fetter = d.get("fetter") or {}
                cv_kr = ((fetter.get("cv") or {}).get("KR") or "").strip() if isinstance(fetter.get("cv"), dict) else ""
                detail_info = {
                    "title": _clean_text(fetter.get("title")),
                    "detail": _clean_text(fetter.get("detail")),
                    "constellation": _clean_text(fetter.get("constellation")),
                    "native": _clean_text(fetter.get("native")),
                    "cv_kr": _clean_text(cv_kr),
                }
            elif kind == "artifact":
                suit = d.get("suit") or {}
                pieces = {}
                for sk, sv in suit.items():
                    if isinstance(sv, dict):
                        pieces[sk] = {
                            "name": _clean_text(sv.get("name")),
                            "description": _clean_text(sv.get("description")),
                            "icon": str(sv.get("icon") or ""),
                        }
                detail_info = {"pieces": pieces}
            else:
                detail_info = {
                    "description": _clean_text(d.get("description")),
                }
    except Exception:
        pass

    with _GENSHIN_DETAIL_LOCK:
        _GENSHIN_DETAIL_CACHE[cache_key] = detail_info
        while len(_GENSHIN_DETAIL_CACHE) > 256:
            _GENSHIN_DETAIL_CACHE.popitem(last=False)
    return detail_info


# ==========================================
# 일러스트 URL / 바이트 캐시 / WebP 리사이즈 (디스코드 7.8MB 한도 준수)
# ==========================================
def get_genshin_item_urls(item: dict, splash: bool = True) -> list[str]:
    icon = str(item.get("icon") or "")
    kind = item.get("kind", "char")
    if not icon:
        return []
    if kind == "artifact":
        slot_code = item.get("slot_code", "EQUIP_BRACER")
        idx_num = GENSHIN_ARTIFACT_SLOTS.get(slot_code, {}).get("icon_idx", 4)
        base_ic = re.sub(r"_\d+$", f"_{idx_num}", icon)
        return [
            f"https://gi.yatta.moe/assets/UI/reliquary/{base_ic}.png",
            f"https://enka.network/ui/{base_ic}.png",
            f"https://gi.yatta.moe/assets/UI/reliquary/{icon}.png",
            f"https://enka.network/ui/{icon}.png",
        ]
    if splash:
        if kind == "char":
            gacha_icon = icon.replace("UI_AvatarIcon_", "UI_Gacha_AvatarImg_")
            return [
                f"https://gi.yatta.moe/assets/UI/{gacha_icon}.png",
                f"https://enka.network/ui/{gacha_icon}.png",
                f"https://gi.yatta.moe/assets/UI/{icon}.png",
                f"https://enka.network/ui/{icon}.png",
            ]
        else:
            gacha_icon = icon.replace("UI_EquipIcon_", "UI_Gacha_EquipIcon_")
            return [
                f"https://gi.yatta.moe/assets/UI/{gacha_icon}.png",
                f"https://enka.network/ui/{gacha_icon}.png",
                f"https://gi.yatta.moe/assets/UI/{icon}.png",
                f"https://enka.network/ui/{icon}.png",
            ]
    return [
        f"https://gi.yatta.moe/assets/UI/{icon}.png",
        f"https://enka.network/ui/{icon}.png",
    ]


def get_genshin_primary_image_url(item: dict, splash: bool = True) -> str:
    urls = get_genshin_item_urls(item, splash=splash)
    return urls[0] if urls else ""


def _compress_splash_if_needed(raw_bytes: bytes, base_name: str, is_splash: bool) -> tuple[bytes, str]:
    """원신 가챠 스플래시 PNG(~1.8MB)를 선명한 WebP(~180KB)로 압축해 10연차 첨부 한도를 여유롭게 유지합니다."""
    if len(raw_bytes) <= 820_000 and not is_splash:
        return raw_bytes, f"{base_name}.png"
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            im = im.convert("RGBA")
            if max(im.size) > 1080:
                im.thumbnail((1080, 1080), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="WEBP", quality=86, method=4)
            webp_bytes = out.getvalue()
            if len(webp_bytes) < len(raw_bytes):
                return webp_bytes, f"{base_name}.webp"
    except Exception:
        pass
    return raw_bytes, f"{base_name}.png"


def fetch_genshin_item_image_bytes(item: dict, splash: bool = True) -> tuple[bytes | None, str | None]:
    kind = item.get("kind", "char")
    iid = str(item.get("id", "0"))
    slot_suffix = f":{item.get('slot_code', '')}" if kind == "artifact" else ""
    cache_key = f"gi:{'sp' if splash else 'ic'}:{kind}:{iid}{slot_suffix}"
    with _GENSHIN_IMG_LOCK:
        if cache_key in _GENSHIN_IMG_CACHE:
            _GENSHIN_IMG_CACHE.move_to_end(cache_key)
            return _GENSHIN_IMG_CACHE[cache_key]

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"gi_{kind}_{iid}_{item.get('slot_code', '')}_{'sp' if splash else 'ic'}")
    for url in get_genshin_item_urls(item, splash=splash):
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200 and r.content and len(r.content) > 512:
                b, fn = _compress_splash_if_needed(r.content, safe_id, splash)
                with _GENSHIN_IMG_LOCK:
                    _GENSHIN_IMG_CACHE[cache_key] = (b, fn)
                    while len(_GENSHIN_IMG_CACHE) > 96:
                        _GENSHIN_IMG_CACHE.popitem(last=False)
                return b, fn
        except Exception:
            continue
    return None, None


def fetch_genshin_thumb_bytes(item: dict) -> bytes | None:
    kind = item.get("kind", "char")
    iid = str(item.get("id", "0"))
    slot_suffix = f":{item.get('slot_code', '')}" if kind == "artifact" else ""
    cache_key = f"gi_th:{kind}:{iid}{slot_suffix}"
    with _GENSHIN_IMG_LOCK:
        if cache_key in _GENSHIN_THUMB_CACHE:
            _GENSHIN_THUMB_CACHE.move_to_end(cache_key)
            return _GENSHIN_THUMB_CACHE[cache_key]

    for url in get_genshin_item_urls(item, splash=False):
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200 and r.content and len(r.content) > 256:
                with _GENSHIN_IMG_LOCK:
                    _GENSHIN_THUMB_CACHE[cache_key] = r.content
                    while len(_GENSHIN_THUMB_CACHE) > 256:
                        _GENSHIN_THUMB_CACHE.popitem(last=False)
                return r.content
        except Exception:
            continue
    return None


# ==========================================
# KST 시각(시간대·요일) 연동 티바트 축복 & 비경 로테이션 엔진
# ==========================================
def get_genshin_time_schedule(now_dt: datetime.datetime | None = None) -> dict:
    """
    현재 한국 표준시(KST) 시각과 요일에 맞춰
    1) 캐릭터 상시/픽업외 원소 가중치
    2) 무기 기원 무기군 가중치
    3) 성유물 비경 로테이션 세트 및 부위 드롭 보너스를 반환합니다.
    """
    if now_dt is None:
        now_dt = datetime.datetime.now(core.KST)
    hour = now_dt.hour
    weekday = now_dt.weekday()  # 0=월 ... 6=일

    if 6 <= hour < 12:
        phase_key = "dawn"
        phase_name = "🌅 여명의 인도 (06:00~12:00)"
        boost_elements = ["Fire", "Grass"]
        boost_weapons = ["WEAPON_SWORD_ONE_HAND", "WEAPON_POLE"]
        boost_slot = "EQUIP_BRACER"
    elif 12 <= hour < 18:
        phase_key = "zenith"
        phase_name = "☀️ 천공의 정오 (12:00~18:00)"
        boost_elements = ["Rock", "Wind"]
        boost_weapons = ["WEAPON_CLAYMORE", "WEAPON_BOW"]
        boost_slot = "EQUIP_NECKLACE"
    elif 18 <= hour < 24:
        phase_key = "twilight"
        phase_name = "🌆 황혼의 주조 (18:00~24:00)"
        boost_elements = ["Water", "Electric"]
        boost_weapons = ["WEAPON_CATALYST", "WEAPON_SWORD_ONE_HAND"]
        boost_slot = "EQUIP_RING"
    else:
        phase_key = "abyss"
        phase_name = "🌌 심연의 별밤 (00:00~06:00)"
        boost_elements = ["Ice", "Water"]
        boost_weapons = ["WEAPON_POLE", "WEAPON_BOW", "WEAPON_CLAYMORE"]
        boost_slot = "EQUIP_DRESS" if hour % 2 == 0 else "EQUIP_SHOES"

    weekday_domains = [
        ("월요일 · 노드크라이/스네즈나야 지맥", ["15043", "15044", "15041", "15042"]),
        ("화요일 · 나타 흑요석/잿더미 성소", ["15038", "15037", "15039", "15040"]),
        ("수요일 · 폰타인 그림자/황금 극단", ["15031", "15032", "15035", "15036"]),
        ("목요일 · 수메르 숲의 기억/도금된 꿈", ["15025", "15026", "15028", "15027"]),
        ("금요일 · 이나즈마 절연의 기치/시메나와", ["15020", "15019", "15021", "15022"]),
        ("토요일 · 티바트 고대 비경 (청록/마녀/왕실)", ["15002", "15006", "15007", "15043", "15038"]),
        ("일요일 · 셀레스티아 전 비경 개방", ["15043", "15044", "15041", "15038", "15037", "15031", "15032", "15020"]),
    ]
    domain_label, featured_set_ids = weekday_domains[weekday]

    elem_labels = [f"{GENSHIN_ELEMENT_MAP[e]['emoji']}{GENSHIN_ELEMENT_MAP[e]['name']}" for e in boost_elements if e in GENSHIN_ELEMENT_MAP]
    wp_labels = [f"{GENSHIN_WEAPON_TYPE_MAP[w]['emoji']}{GENSHIN_WEAPON_TYPE_MAP[w]['name']}" for w in boost_weapons if w in GENSHIN_WEAPON_TYPE_MAP]
    slot_info = GENSHIN_ARTIFACT_SLOTS.get(boost_slot, GENSHIN_ARTIFACT_SLOTS["EQUIP_BRACER"])

    artifacts = get_genshin_artifacts()
    art_map = {str(a["id"]): a for a in artifacts}
    featured_sets = [art_map[sid] for sid in featured_set_ids if sid in art_map]
    if not featured_sets and artifacts:
        featured_sets = [a for a in artifacts if a.get("max_rank") == 5][:4]

    e0 = GENSHIN_ELEMENT_MAP.get(boost_elements[0], {"emoji": "✨", "name": "원소"})
    w0 = GENSHIN_WEAPON_TYPE_MAP.get(boost_weapons[0], {"emoji": "⚔️", "name": "무기"})
    phase_emoji = phase_name.split()[0] if phase_name else "🌠"
    feat_art = featured_sets[0] if featured_sets else None
    elem_str = "·".join(elem_labels)
    wp_str = "·".join(wp_labels)
    slot_lbl = f"{slot_info['emoji']}{slot_info['name']}"
    bonus_txt = f"원소 {elem_str} · 무기 {wp_str} · 비경 {slot_lbl} UP"
    rec_banner = "char1" if 6 <= hour < 12 else ("weapon" if 12 <= hour < 18 else "artifact")

    return {
        "hour": hour,
        "weekday": weekday,
        "time_str": now_dt.strftime("%H:%M KST"),
        "hour_str": now_dt.strftime("%H:%M KST"),
        "emoji": phase_emoji,
        "phase_emoji": phase_emoji,
        "phase_key": phase_key,
        "phase_name": phase_name,
        "period_name": phase_name,
        "desc": f"{domain_label} — {bonus_txt}",
        "bonus_text": bonus_txt,
        "buff_summary": bonus_txt,
        "char_elem_emoji": e0["emoji"],
        "char_elem_name": e0["name"],
        "weapon_type_name": wp_str,
        "boost_elements": boost_elements,
        "boost_element_label": elem_str,
        "boost_weapons": boost_weapons,
        "boost_weapon_label": wp_str,
        "boost_slot": boost_slot,
        "boost_slot_label": slot_lbl,
        "domain_label": domain_label,
        "featured_set_ids": [str(a["id"]) for a in featured_sets],
        "featured_sets": featured_sets,
        "featured_set_names": [a["name"] for a in featured_sets[:3]],
        "featured_artifact": feat_art,
        "rec_banner": rec_banner,
    }


def _weighted_choice(items: list[dict], weight_fn, rng: random.Random) -> dict:
    if not items:
        return {}
    weights = [max(0.05, float(weight_fn(it))) for it in items]
    tot = sum(weights)
    r = rng.uniform(0.0, tot)
    upto = 0.0
    for it, w in zip(items, weights):
        upto += w
        if r <= upto:
            return it
    return items[-1]


# ==========================================
# 캐릭터 / 무기 / 성유물 3종 차별화 5x2 10연차 결과 이미지 그리드 빌더
# ==========================================
def build_genshin_10pull_grid_bytes(drawn: list[dict], banner_key: str = "char1", header_tag: str = "") -> tuple[bytes | None, str | None]:
    """
    원신 배너 종류에 따라 완벽히 차별화된 5×2 결과판 이미지를 생성합니다:
    - char1/char2/standard: 셀레스티아 밤하늘·운명의 별자리 스타일
    - weapon: 신의 주조 황금 대장간·명정 룬 프레임 스타일
    - artifact: 각인의 비경·지맥의 고목 석판 & 부위/주옵/부옵 스타일
    """
    if not drawn:
        return None, None

    load_genshin_kr_db()
    sched = get_genshin_time_schedule()
    thumb_results: list[bytes | None] = [None] * len(drawn)
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(fetch_genshin_thumb_bytes, c) for c in drawn]
            for idx, fut in enumerate(futs):
                try:
                    thumb_results[idx] = fut.result(timeout=7)
                except Exception:
                    thumb_results[idx] = None
    except Exception:
        for idx, c in enumerate(drawn):
            thumb_results[idx] = fetch_genshin_thumb_bytes(c)

    try:
        cols, rows = 5, 2
        tile_w, tile_h = 280, 334 if banner_key == "artifact" else 326
        gap_x, gap_y = 20, 22
        pad_x, pad_top, pad_bot = 34, 88, 30
        canvas_w = pad_x * 2 + cols * tile_w + (cols - 1) * gap_x
        canvas_h = pad_top + rows * tile_h + (rows - 1) * gap_y + pad_bot

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (11, 16, 38, 255))
        draw = ImageDraw.Draw(canvas)
        rng = random.Random(42 + len(drawn) + (7 if banner_key == "weapon" else (19 if banner_key == "artifact" else 0)))

        if banner_key == "weapon":
            # 신의 주조: 흑요석·앰버 골드 대장간 그라데이션 + 대각선 주조 라인
            for y in range(canvas_h):
                t = y / max(1, canvas_h - 1)
                draw.line([(0, y), (canvas_w, y)], fill=(int(24 + 22 * t), int(14 + 14 * t), int(10 + 10 * t), 255))
            for i in range(-canvas_h, canvas_w, 90):
                draw.line([(i, 0), (i + canvas_h // 2, canvas_h)], fill=(255, 175, 70, 22), width=2)
            for _ in range(85):
                sx, sy = rng.randint(15, canvas_w - 15), rng.randint(15, canvas_h - 15)
                sr = rng.choice([1, 2, 2])
                draw.regular_polygon((sx, sy, sr + 1), 4, rotation=45, fill=(255, 196, 85, rng.randint(85, 210)))
            hdr_bg, hdr_outline, hdr_fg = (42, 24, 14, 240), (255, 190, 82, 235), (255, 222, 130, 255)
            time_tag = f"{sched['phase_name']} · {sched['boost_weapon_label']}"
        elif banner_key == "artifact":
            # 각인의 비경: 지맥의 고목 에메랄드·고대 유적 석판 그라데이션 + 룬 원형
            for y in range(canvas_h):
                t = y / max(1, canvas_h - 1)
                draw.line([(0, y), (canvas_w, y)], fill=(int(9 + 12 * t), int(24 + 24 * t), int(26 + 22 * t), 255))
            cx_m, cy_m = canvas_w // 2, canvas_h // 2 + 20
            for rad in (180, 320, 480):
                draw.ellipse([cx_m - rad, cy_m - rad, cx_m + rad, cy_m + rad], outline=(82, 235, 196, 28), width=2)
            for _ in range(90):
                sx, sy = rng.randint(15, canvas_w - 15), rng.randint(15, canvas_h - 15)
                sr = rng.choice([1, 2])
                col = (102, 245, 205, rng.randint(90, 210)) if rng.random() < 0.6 else (255, 218, 128, rng.randint(90, 200))
                draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=col)
            hdr_bg, hdr_outline, hdr_fg = (14, 38, 40, 240), (96, 232, 192, 230), (168, 255, 228, 255)
            time_tag = f"{sched['domain_label']} · {sched['boost_slot_label']}↑"
        else:
            # 캐릭터/상시 기원: 티바트 심야 셀레스티아 별자리 배경
            for y in range(canvas_h):
                t = y / max(1, canvas_h - 1)
                draw.line([(0, y), (canvas_w, y)], fill=(int(10 + 14 * t), int(15 + 18 * t), int(38 + 30 * t), 255))
            pts = []
            for _ in range(95):
                sx, sy = rng.randint(15, canvas_w - 15), rng.randint(15, canvas_h - 15)
                sr = rng.choice([1, 1, 2])
                alpha = rng.randint(90, 220)
                col = (245, 212, 130, alpha) if rng.random() < 0.35 else (195, 220, 255, alpha)
                draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=col)
                if len(pts) < 12 and rng.random() < 0.2:
                    pts.append((sx, sy))
            for i in range(len(pts) - 1):
                if abs(pts[i][0] - pts[i + 1][0]) < 320 and abs(pts[i][1] - pts[i + 1][1]) < 220:
                    draw.line([pts[i], pts[i + 1]], fill=(210, 225, 255, 38), width=1)
            hdr_bg, hdr_outline, hdr_fg = (20, 28, 62, 235), (230, 195, 106, 220), (255, 226, 138, 255)
            time_tag = f"{sched['phase_name']} · {sched['boost_element_label']}"

        b_cfg = GENSHIN_BANNER_CONFIGS.get(banner_key, GENSHIN_BANNER_CONFIGS["char1"])
        font_hdr = core._get_grid_font(26, bold=True)
        font_sub = core._get_grid_font(16, bold=False)
        font_name = core._get_grid_font(18, bold=True)
        font_meta = core._get_grid_font(14, bold=False)
        font_badge = core._get_grid_font(13, bold=True)

        draw.rounded_rectangle([24, 16, canvas_w - 24, 70], radius=14, fill=hdr_bg, outline=hdr_outline, width=2)
        hdr_prefix = "🏛️ 원신 비경 10회 토벌" if banner_key == "artifact" else ("⚔️ 신의 주조 10회 기원" if banner_key == "weapon" else "★ 원신 기원 10회 결과")
        hdr_title = core._sanitize_grid_text(f"{hdr_prefix} · {b_cfg['short_name']}")
        if header_tag:
            hdr_title += core._sanitize_grid_text(f" [{header_tag}]")
        draw.text((42, 28), hdr_title, font=font_hdr, fill=hdr_fg)

        r5_cnt = sum(1 for x in drawn if x.get("rank") == 5)
        r4_cnt = sum(1 for x in drawn if x.get("rank") == 4)
        stats_s = core._sanitize_grid_text(f"★5 {r5_cnt} · ★4 {r4_cnt}  |  {time_tag}")
        sw = draw.textbbox((0, 0), stats_s, font=font_sub)[2]
        draw.text((canvas_w - 42 - sw, 34), stats_s, font=font_sub, fill=(215, 232, 252, 235))

        for idx, item in enumerate(drawn[:10]):
            c_idx = idx % cols
            r_idx = idx // cols
            tx = pad_x + c_idx * (tile_w + gap_x)
            ty = pad_top + r_idx * (tile_h + gap_y)

            rank = int(item.get("rank", 3))
            kind = item.get("kind", "char")
            if rank == 5:
                bg_top, bg_bot = ((58, 48, 18), (24, 20, 12)) if kind != "artifact" else ((48, 52, 20), (18, 28, 22))
                border_col = (255, 208, 86, 255)
                inner_col = (255, 240, 175, 220)
                star_col = (255, 215, 92, 255)
            elif rank == 4:
                bg_top, bg_bot = (48, 28, 78), (24, 17, 46)
                border_col = (186, 128, 255, 255)
                inner_col = (224, 192, 255, 190)
                star_col = (212, 166, 255, 255)
            else:
                bg_top, bg_bot = (22, 42, 74), (14, 24, 46)
                border_col = (84, 168, 248, 235)
                inner_col = (158, 212, 255, 150)
                star_col = (130, 200, 255, 255)

            tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
            tdraw = ImageDraw.Draw(tile)
            tdraw.rounded_rectangle([0, 0, tile_w - 1, tile_h - 1], radius=18, fill=(*bg_bot, 250))
            for ly in range(4, 204):
                alpha_f = 1.0 - (ly / 204.0)
                rc = int(bg_bot[0] + (bg_top[0] - bg_bot[0]) * alpha_f)
                gc = int(bg_bot[1] + (bg_top[1] - bg_bot[1]) * alpha_f)
                bc = int(bg_bot[2] + (bg_top[2] - bg_bot[2]) * alpha_f)
                tdraw.line([(6, ly), (tile_w - 7, ly)], fill=(rc, gc, bc, 245))

            if kind == "char":
                elem_code = item.get("element")
                orb_rgb = GENSHIN_ELEMENT_MAP.get(elem_code, {}).get("color", border_col[:3])
                tdraw.ellipse([tile_w // 2 - 78, 26, tile_w // 2 + 78, 182], fill=(*orb_rgb, 55), outline=(*orb_rgb, 115), width=2)
            elif kind == "weapon":
                # 무기 전용 다이아몬드 주조 엠블럼 프레임
                tdraw.regular_polygon((tile_w // 2, 104, 78), 4, rotation=0, fill=(255, 185, 72, 42), outline=(*border_col[:3], 135))
                tdraw.regular_polygon((tile_w // 2, 104, 64), 8, rotation=22, fill=None, outline=(255, 225, 150, 85))
            else:
                # 성유물 전용 지맥의 고목 팔각 유물 석판 오라
                tdraw.regular_polygon((tile_w // 2, 102, 78), 8, rotation=22, fill=(76, 228, 188, 42), outline=(98, 245, 204, 130))
                tdraw.ellipse([tile_w // 2 - 58, 44, tile_w // 2 + 58, 160], fill=(255, 215, 110, 32), outline=(*border_col[:3], 110), width=1)

            tb = thumb_results[idx]
            if tb:
                try:
                    with Image.open(io.BytesIO(tb)) as ic:
                        ic = ic.convert("RGBA")
                        ic.thumbnail((168, 168), Image.Resampling.LANCZOS)
                        ix = (tile_w - ic.width) // 2
                        iy = 18 + (168 - ic.height) // 2
                        tile.alpha_composite(ic, (ix, iy))
                except Exception:
                    pass

            tdraw.rounded_rectangle([0, 0, tile_w - 1, tile_h - 1], radius=18, outline=border_col, width=4 if rank >= 4 else 3)
            if rank == 5:
                tdraw.rounded_rectangle([5, 5, tile_w - 6, tile_h - 6], radius=14, outline=inner_col, width=2)

            info_top = 196 if kind == "artifact" else 200
            tdraw.rounded_rectangle([6, info_top, tile_w - 7, tile_h - 7], radius=14, fill=(10, 14, 30, 232))
            tdraw.line([(16, info_top), (tile_w - 16, info_top)], fill=(*border_col[:3], 150), width=1)

            stars_txt = "★" * rank
            tdraw.text((16, info_top + 6), stars_txt, font=font_badge, fill=star_col)

            badge_x = tile_w - 14
            badges = []
            if item.get("is_new"):
                badges.append(("NEW", (38, 184, 128, 245), (255, 255, 255, 255)))
            if item.get("is_pickup"):
                badges.append(("UP", (232, 82, 82, 245), (255, 255, 255, 255)))
            if item.get("is_time_boost"):
                badges.append(("축복", (68, 178, 255, 245), (10, 18, 35, 255)))
            if item.get("is_radiance"):
                badges.append(("광휘", (255, 198, 60, 245), (30, 18, 0, 255)))
            elif item.get("is_fate_guaranteed"):
                badges.append(("궤도", (255, 150, 50, 245), (30, 15, 0, 255)))

            for b_txt, b_bg, b_fg in reversed(badges):
                sb_txt = core._sanitize_grid_text(b_txt)
                bb = tdraw.textbbox((0, 0), sb_txt, font=font_badge)
                bw = (bb[2] - bb[0]) + 12
                bx0 = badge_x - bw
                tdraw.rounded_rectangle([bx0, 12, badge_x, 34], radius=7, fill=b_bg)
                tdraw.text((bx0 + 6, 15), sb_txt, font=font_badge, fill=b_fg)
                badge_x = bx0 - 6

            if kind == "char":
                dup_badge = f"C{item.get('new_constellation', 0)}"
            elif kind == "weapon":
                dup_badge = f"R{item.get('new_refinement', 1)}"
            else:
                dup_badge = f"{item.get('slot_short', '성유물')} +{item.get('level', 0)}"
            if dup_badge:
                sd_txt = core._sanitize_grid_text(dup_badge)
                db = tdraw.textbbox((0, 0), sd_txt, font=font_badge)
                dw = (db[2] - db[0]) + 10
                tdraw.rounded_rectangle([tile_w - 16 - dw, info_top + 5, tile_w - 16, info_top + 24], radius=6, fill=(40, 52, 92, 230))
                tdraw.text((tile_w - 16 - dw + 5, info_top + 7), sd_txt, font=font_badge, fill=(235, 242, 255, 255))

            clean_name = core._sanitize_grid_text(item.get("name", ""))
            while len(clean_name) > 2 and tdraw.textbbox((0, 0), clean_name, font=font_name)[2] > (tile_w - 30):
                clean_name = clean_name[:-2] + "…"
            tdraw.text((16, info_top + 30), clean_name, font=font_name, fill=(248, 250, 255, 255))

            if kind == "char":
                sub_raw = f"{item.get('element_name', '')} · {item.get('weapon_type_name', '')} · {item.get('pool_type', '')}"
                sub_clean = core._sanitize_grid_text(sub_raw)
                while len(sub_clean) > 4 and tdraw.textbbox((0, 0), sub_clean, font=font_meta)[2] > (tile_w - 30):
                    sub_clean = sub_clean[:-2] + "…"
                tdraw.text((16, info_top + 58), sub_clean, font=font_meta, fill=(176, 196, 232, 240))
            elif kind == "weapon":
                sub_raw = f"{item.get('weapon_type_name', '')} · 부옵 {item.get('special_prop_name', '-')} · {item.get('pool_type', '')}"
                sub_clean = core._sanitize_grid_text(sub_raw)
                while len(sub_clean) > 4 and tdraw.textbbox((0, 0), sub_clean, font=font_meta)[2] > (tile_w - 30):
                    sub_clean = sub_clean[:-2] + "…"
                tdraw.text((16, info_top + 58), sub_clean, font=font_meta, fill=(245, 208, 152, 240))
            else:
                main_raw = f"주옵: {item.get('main_stat_name', 'HP')} {item.get('main_stat_val', '')}"
                main_clean = core._sanitize_grid_text(main_raw)
                while len(main_clean) > 4 and tdraw.textbbox((0, 0), main_clean, font=font_meta)[2] > (tile_w - 30):
                    main_clean = main_clean[:-2] + "…"
                tdraw.text((16, info_top + 56), main_clean, font=font_meta, fill=(142, 248, 212, 245))

                subs = item.get("substats") or []
                sub_line = " / ".join(f"{s['name']}+{s['display']}" for s in subs[:2])
                sub_clean = core._sanitize_grid_text(sub_line)
                while len(sub_clean) > 4 and tdraw.textbbox((0, 0), sub_clean, font=font_meta)[2] > (tile_w - 30):
                    sub_clean = sub_clean[:-2] + "…"
                tdraw.text((16, info_top + 78), sub_clean, font=font_meta, fill=(195, 212, 240, 235))

            idx_txt = f"#{idx + 1:02d}"
            tdraw.text((14, 12), idx_txt, font=font_badge, fill=(220, 230, 255, 210))

            canvas.alpha_composite(tile, (tx, ty))

        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="PNG", optimize=True)
        fn = f"genshin_10pull_{banner_key}_{int(time.time())}.png"
        return out.getvalue(), fn
    except Exception as e:
        print(f"⚠️ [원신 그리드 생성 오류] {e}", flush=True)
        return None, None


# ==========================================
# 유저 데이터 구조 · 픽업 해석 · 천장/확률 기원 엔진
# ==========================================
def ensure_genshin_user(data: dict, guild_id: int | str, user_id: int | str) -> dict:
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    root = data.setdefault("genshin_users", {})
    g_map = root.setdefault(g_key, {})
    u_data = g_map.get(u_key)
    if not isinstance(u_data, dict):
        u_data = {}
        g_map[u_key] = u_data

    u_data.setdefault("items", {})
    u_data.setdefault("artifacts", [])
    u_data.setdefault("total_pulls", 0)
    u_data.setdefault("pity_char", 0)
    u_data.setdefault("guaranteed_char", False)
    u_data.setdefault("loss_streak", 0)
    u_data.setdefault("pity_4_char", 0)
    u_data.setdefault("guaranteed_4_char", False)
    u_data.setdefault("pity_weapon", 0)
    u_data.setdefault("guaranteed_weapon", False)
    u_data.setdefault("pity_4_weapon", 0)
    u_data.setdefault("guaranteed_4_weapon", False)
    u_data.setdefault("fate_target_id", None)
    u_data.setdefault("fate_point", 0)
    u_data.setdefault("pity_standard", 0)
    u_data.setdefault("pity_4_standard", 0)
    u_data.setdefault("pity_artifact", 0)
    u_data.setdefault("pity_4_artifact", 0)
    u_data.setdefault("guaranteed_artifact", False)
    u_data.setdefault("target_artifact_set_id", None)
    u_data.setdefault("artifact_essence", 0)
    u_data.setdefault("sanctifying_elixir", 2)
    u_data.setdefault("starglitter", 0)
    u_data.setdefault("stardust", 0)
    u_data.setdefault("intertwined_fate", 0)
    u_data.setdefault("acquaint_fate", 0)
    u_data.setdefault("hero_wit", 0)
    u_data.setdefault("shop_monthly", {})
    u_data.setdefault("party", [])
    u_data.setdefault("profile_char", None)
    u_data.setdefault("profile_note", "")
    u_data.setdefault("history", [])
    return u_data


def resolve_effective_genshin_pickup(pickup_cfg: dict | None) -> dict:
    """설정된 원신 픽업을 유효한 실제 아이템 객체들로 해석합니다 (미설정 시 최신 캐릭터·무기 자동 할당)."""
    chars, weapons = load_genshin_kr_db()
    by_char = {c["id"]: c for c in chars}
    by_wp = {w["id"]: w for w in weapons}
    cfg = copy.deepcopy(pickup_cfg or {})

    lim_5_chars = [c for c in chars if c["rank"] == 5 and c["pool_type"] == "한정"]
    pool_4_chars = [c for c in chars if c["rank"] == 4 and c["id"] not in GENSHIN_STARTER_4_CHARS]
    lim_5_wps = [w for w in weapons if w["rank"] == 5 and w["wish_source"] == "limited"]
    gacha_4_wps = [w for w in weapons if w["rank"] == 4 and w["wishable"]]

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

    w1_id = cfg.get("weapon_1")
    w2_id = cfg.get("weapon_2")
    if not w1_id or w1_id not in by_wp:
        w1_id = lim_5_wps[0]["id"] if lim_5_wps else (weapons[0]["id"] if weapons else None)
    if not w2_id or w2_id not in by_wp:
        cand_w = [w["id"] for w in lim_5_wps if w["id"] != w1_id]
        w2_id = cand_w[0] if cand_w else w1_id

    w4_ids = [wid for wid in (cfg.get("weapon_4_ids") or []) if wid in by_wp and by_wp[wid].get("wishable")][:5]
    if len(w4_ids) < 5:
        lim4 = [w for w in gacha_4_wps if w["wish_source"] == "limited"]
        std4 = [w for w in gacha_4_wps if w["wish_source"] == "standard"]
        for w in (lim4[:2] + std4):
            if w["id"] not in w4_ids:
                w4_ids.append(w["id"])
            if len(w4_ids) >= 5:
                break

    sched = get_genshin_time_schedule()
    return {
        "banner_name": cfg.get("banner_name") or "티바트 이벤트 기원",
        "version_label": cfg.get("version_label") or "라이브 동기화",
        "char1": by_char.get(c1_id),
        "char2": by_char.get(c2_id),
        "char_4": [by_char[i] for i in c4_ids if i in by_char],
        "weapon_1": by_wp.get(w1_id),
        "weapon_2": by_wp.get(w2_id),
        "weapon_4": [by_wp[i] for i in w4_ids if i in by_wp],
        "artifact_sets": sched["featured_sets"],
        "time_schedule": sched,
        "raw": cfg,
    }


def _gi_soft_pity_prob(pity_after: int, banner_key: str) -> float:
    if banner_key == "artifact":
        if pity_after >= 10:
            return 1.0
        if pity_after >= 7:
            return min(1.0, 0.12 + 0.22 * (pity_after - 6))
        return 0.12
    if banner_key == "weapon":
        if pity_after >= 80:
            return 1.0
        if pity_after >= 63:
            return min(1.0, 0.007 + 0.07 * (pity_after - 62))
        return 0.007
    else:
        if pity_after >= 90:
            return 1.0
        if pity_after >= 74:
            return min(1.0, 0.006 + 0.06 * (pity_after - 73))
        return 0.006


def _gi_soft_4_prob(pity4_after: int, banner_key: str) -> float:
    if banner_key == "artifact":
        if pity4_after >= 3:
            return 1.0
        return 0.38
    base = 0.060 if banner_key == "weapon" else 0.051
    if pity4_after >= 10:
        return 1.0
    if pity4_after == 9:
        return base + 0.51
    return base


def _format_gi_stat_val(val: float, is_pct: bool) -> str:
    return f"{val:.1f}%" if is_pct else f"{int(round(val))}"


def compute_genshin_artifact_score(art_piece: dict) -> tuple[float, float, str]:
    """성유물 치명타 가치(CV = 치확*2 + 치피) 및 유효옵 환산 점수(RV)와 등급(SSS~B)을 계산합니다."""
    cv = 0.0
    rv = 0.0
    for s in (art_piece.get("substats") or []):
        sname = s.get("name", "")
        sval = float(s.get("value", 0.0))
        if sname == "치명타 확률":
            cv += sval * 2.0
            rv += (sval / 3.9) * 100.0
        elif sname == "치명타 피해":
            cv += sval
            rv += (sval / 7.8) * 100.0
        elif sname in ("공격력%", "원소 충전 효율", "원소 마스터리", "HP%", "방어력%"):
            max_t = GENSHIN_ARTIFACT_SUB_MAX_MAP.get(sname, 5.8)
            rv += (sval / max_t) * 85.0
    if cv >= 45.0 or rv >= 620.0:
        grade = "SSS (신화 종결)"
    elif cv >= 38.0 or rv >= 520.0:
        grade = "SS (비경 졸업)"
    elif cv >= 30.0 or rv >= 430.0:
        grade = "S (주력 세팅)"
    elif cv >= 20.0 or rv >= 320.0:
        grade = "A (실전 우수)"
    else:
        grade = "B (강화 재료)"
    return round(cv, 1), round(rv, 1), grade


def _generate_genshin_artifact_piece(
    set_obj: dict,
    rank: int,
    rng: random.Random,
    sched: dict,
    forced_slot: str | None = None,
    forced_main: str | None = None,
    forced_subs: list[str] | None = None,
    is_pickup: bool = False,
    pity_used: int = 1,
) -> dict:
    allowed_slots = set_obj.get("allowed_slots") or list(GENSHIN_ARTIFACT_SLOTS.keys())
    if forced_slot and forced_slot in allowed_slots:
        slot_code = forced_slot
        is_time_boost = (slot_code == sched.get("boost_slot"))
    else:
        boost_slot = sched.get("boost_slot", "EQUIP_BRACER")
        slot_weights = [1.85 if sc == boost_slot else 1.0 for sc in allowed_slots]
        tot_w = sum(slot_weights)
        r_s = rng.uniform(0.0, tot_w)
        acc = 0.0
        slot_code = allowed_slots[0]
        for sc, sw in zip(allowed_slots, slot_weights):
            acc += sw
            if r_s <= acc:
                slot_code = sc
                break
        is_time_boost = (slot_code == boost_slot)

    slot_meta = GENSHIN_ARTIFACT_SLOTS.get(slot_code, GENSHIN_ARTIFACT_SLOTS["EQUIP_BRACER"])
    main_pool = slot_meta["main_pool"]
    if forced_main and forced_main in main_pool:
        main_stat = forced_main
    else:
        main_stat = rng.choice(main_pool)

    lv = 0
    main_val = GENSHIN_ARTIFACT_MAIN_VALUES.get((rank, main_stat), ("+717", "+4,780"))[0]

    # 초기 부옵션 수 (5성: 3줄 80% / 4줄 20%, 4성: 2~3줄, 3성: 1~2줄)
    if rank == 5:
        init_cnt = 4 if (forced_subs or rng.random() < 0.25) else 3
    elif rank == 4:
        init_cnt = 3 if rng.random() < 0.40 else 2
    else:
        init_cnt = 2

    sub_candidates = [s for s in GENSHIN_ARTIFACT_SUBSTATS if s[0] != main_stat]
    chosen_subs: list[dict] = []
    used_names = set()
    if forced_subs:
        for fs in forced_subs:
            match = next((s for s in sub_candidates if s[0] == fs and s[0] not in used_names), None)
            if match:
                used_names.add(match[0])
                tier_val = float(match[1][-1])
                chosen_subs.append({
                    "name": match[0],
                    "value": round(tier_val, 1),
                    "is_pct": match[2],
                    "unit": "%" if match[2] else "",
                    "display": _format_gi_stat_val(tier_val, match[2]),
                    "rolls": 1,
                })
    while len(chosen_subs) < init_cnt and len(used_names) < len(sub_candidates):
        rem = [s for s in sub_candidates if s[0] not in used_names]
        pick_s = rng.choice(rem)
        used_names.add(pick_s[0])
        scale = 1.0 if rank == 5 else (0.80 if rank == 4 else 0.60)
        tier_val = float(rng.choice(pick_s[1])) * scale
        chosen_subs.append({
            "name": pick_s[0],
            "value": round(tier_val, 1),
            "is_pct": pick_s[2],
            "unit": "%" if pick_s[2] else "",
            "display": _format_gi_stat_val(tier_val, pick_s[2]),
            "rolls": 1,
        })

    piece_name = f"{set_obj['name']} · {slot_meta['name']}"
    uid_str = f"art_{set_obj['id']}_{slot_meta['icon_idx']}_{int(time.time() * 1000) % 10000000}_{rng.randint(100, 999)}"
    piece = {
        "uid": uid_str,
        "id": str(set_obj["id"]),
        "set_id": str(set_obj["id"]),
        "set_name": set_obj["name"],
        "kind": "artifact",
        "item_key": f"artifact:{set_obj['id']}",
        "name": piece_name,
        "rank": rank,
        "max_level": 20 if rank == 5 else (16 if rank == 4 else 12),
        "level": lv,
        "rarity_label": "★" * rank,
        "slot_code": slot_meta["code"],
        "slot_name": slot_meta["name"],
        "slot_short": slot_meta["short"],
        "slot_emoji": slot_meta["emoji"],
        "main_stat_name": main_stat,
        "main_stat": main_stat,
        "main_stat_val": main_val,
        "main_value": main_val,
        "substats": chosen_subs,
        "bonus_2pc": set_obj.get("bonus_2pc", ""),
        "bonus_4pc": set_obj.get("bonus_4pc", ""),
        "icon": set_obj.get("icon", f"UI_RelicIcon_{set_obj['id']}_4"),
        "pool_type": set_obj.get("pool_type", "5성 비경"),
        "is_pickup": is_pickup,
        "is_time_boost": is_time_boost,
        "pity_used": pity_used,
        "locked": (rank == 5),
    }
    cv, rv, grade = compute_genshin_artifact_score(piece)
    piece["cv"] = cv
    piece["rv"] = rv
    piece["grade"] = grade
    return piece


def _roll_single_genshin(
    state: dict,
    banner_key: str,
    eff_pickup: dict,
    std_5_chars: list[dict],
    std_4_chars: list[dict],
    all_std_4_chars_incl_starter: list[dict],
    std_5_wps: list[dict],
    wish_3_wps: list[dict],
    gacha_4_wps_non_limited: list[dict],
    rng: random.Random,
) -> dict:
    sched = eff_pickup.get("time_schedule") or get_genshin_time_schedule()
    boost_elems = set(sched.get("boost_elements") or [])
    boost_wps = set(sched.get("boost_weapons") or [])

    if banner_key == "artifact":
        state["pity_artifact"] = int(state.get("pity_artifact", 0)) + 1
        state["pity_4_artifact"] = int(state.get("pity_4_artifact", 0)) + 1
        p5 = _gi_soft_pity_prob(state["pity_artifact"], "artifact")
        p4 = _gi_soft_4_prob(state["pity_4_artifact"], "artifact")
        roll = rng.random()

        all_arts = get_genshin_artifacts()
        arts_5 = [a for a in all_arts if a.get("max_rank", 5) == 5] or all_arts
        arts_4 = [a for a in all_arts if 4 in (a.get("level_list") or [4, 5])] or arts_5
        arts_3 = [a for a in all_arts if 3 in (a.get("level_list") or [3, 4])] or arts_4

        target_sid = str(state.get("target_artifact_set_id") or "")
        target_set = GENSHIN_ARTIFACT_MAP.get(target_sid) if target_sid else None
        featured_sets = eff_pickup.get("artifact_sets") or arts_5[:4]

        if roll < p5:
            pity_used = state["pity_artifact"]
            state["pity_artifact"] = 0
            state["pity_4_artifact"] = 0
            if target_set and target_set.get("max_rank", 5) == 5:
                if state.get("guaranteed_artifact") or rng.random() < 0.65:
                    chosen_set = target_set
                    is_up = True
                    state["guaranteed_artifact"] = False
                else:
                    chosen_set = rng.choice(featured_sets or arts_5)
                    is_up = (chosen_set["id"] == target_set["id"])
                    state["guaranteed_artifact"] = not is_up
            else:
                if rng.random() < 0.75 and featured_sets:
                    chosen_set = rng.choice(featured_sets)
                    is_up = True
                else:
                    chosen_set = rng.choice(arts_5)
                    is_up = chosen_set["id"] in {s["id"] for s in featured_sets}
            return _generate_genshin_artifact_piece(chosen_set, 5, rng, sched, is_pickup=is_up, pity_used=pity_used)

        if roll < p5 + p4:
            state["pity_4_artifact"] = 0
            chosen_set = target_set if (target_set and rng.random() < 0.5) else rng.choice(featured_sets or arts_4)
            return _generate_genshin_artifact_piece(chosen_set, 4, rng, sched, is_pickup=False, pity_used=state["pity_artifact"])

        chosen_set = rng.choice(arts_3)
        return _generate_genshin_artifact_piece(chosen_set, 3, rng, sched, is_pickup=False, pity_used=state["pity_artifact"])

    if banner_key in ("char1", "char2"):
        state["pity_char"] += 1
        state["pity_4_char"] += 1
        p5 = _gi_soft_pity_prob(state["pity_char"], banner_key)
        p4 = _gi_soft_4_prob(state["pity_4_char"], banner_key)
        roll = rng.random()

        featured_c = eff_pickup["char1"] if banner_key == "char1" else eff_pickup["char2"]
        if not featured_c:
            featured_c = rng.choice(std_5_chars)

        if roll < p5:
            pity_used = state["pity_char"]
            state["pity_char"] = 0
            is_radiance = False
            if state["guaranteed_char"]:
                picked = dict(featured_c)
                picked["is_pickup"] = True
                state["guaranteed_char"] = False
            else:
                streak = int(state.get("loss_streak", 0))
                if streak >= 3:
                    picked = dict(featured_c)
                    picked["is_pickup"] = True
                    is_radiance = True
                    state["loss_streak"] = 0
                    state["guaranteed_char"] = False
                elif streak == 2:
                    r50 = rng.random()
                    if r50 < 0.75:
                        picked = dict(featured_c)
                        picked["is_pickup"] = True
                        is_radiance = (r50 >= 0.50)
                        state["loss_streak"] = 0
                        state["guaranteed_char"] = False
                    else:
                        picked = dict(_weighted_choice(std_5_chars, lambda c: 1.65 if c.get("element") in boost_elems else 1.0, rng))
                        picked["is_pickup"] = False
                        state["loss_streak"] = 3
                        state["guaranteed_char"] = True
                else:
                    r50 = rng.random()
                    if r50 < 0.55:
                        picked = dict(featured_c)
                        picked["is_pickup"] = True
                        is_radiance = (r50 >= 0.50)
                        state["loss_streak"] = 0
                        state["guaranteed_char"] = False
                    else:
                        picked = dict(_weighted_choice(std_5_chars, lambda c: 1.65 if c.get("element") in boost_elems else 1.0, rng))
                        picked["is_pickup"] = False
                        state["loss_streak"] = streak + 1
                        state["guaranteed_char"] = True
            picked["is_radiance"] = is_radiance
            picked["is_time_boost"] = (picked.get("element") in boost_elems)
            picked["pity_used"] = pity_used
            return picked

        if roll < p5 + p4:
            state["pity_4_char"] = 0
            c4_pickups = eff_pickup["char_4"]
            pickup_4_ids = {c["id"] for c in c4_pickups}
            if c4_pickups and (state["guaranteed_4_char"] or rng.random() < 0.50):
                picked = dict(rng.choice(c4_pickups))
                picked["is_pickup"] = True
                state["guaranteed_4_char"] = False
            else:
                if c4_pickups:
                    state["guaranteed_4_char"] = True
                off_pool = [c for c in std_4_chars if c["id"] not in pickup_4_ids] + gacha_4_wps_non_limited
                picked = dict(_weighted_choice(
                    off_pool or gacha_4_wps_non_limited,
                    lambda x: 1.6 if (x.get("element") in boost_elems or x.get("weapon_type") in boost_wps) else 1.0,
                    rng,
                ))
                picked["is_pickup"] = False
            picked["is_time_boost"] = (picked.get("element") in boost_elems or picked.get("weapon_type") in boost_wps)
            return picked

        picked = dict(_weighted_choice(wish_3_wps, lambda w: 1.5 if w.get("weapon_type") in boost_wps else 1.0, rng))
        picked["is_pickup"] = False
        return picked

    elif banner_key == "weapon":
        state["pity_weapon"] += 1
        state["pity_4_weapon"] += 1
        p5 = _gi_soft_pity_prob(state["pity_weapon"], "weapon")
        p4 = _gi_soft_4_prob(state["pity_4_weapon"], "weapon")
        roll = rng.random()

        w1 = eff_pickup["weapon_1"]
        w2 = eff_pickup["weapon_2"]
        promo_wps = [w for w in (w1, w2) if w]
        if not promo_wps:
            promo_wps = std_5_wps

        fate_id = state.get("fate_target_id")
        if fate_id not in {w["id"] for w in promo_wps}:
            fate_id = None

        if roll < p5:
            pity_used = state["pity_weapon"]
            state["pity_weapon"] = 0
            is_fate_guar = False
            if fate_id and int(state.get("fate_point", 0)) >= 1:
                target_w = next(w for w in promo_wps if w["id"] == fate_id)
                picked = dict(target_w)
                picked["is_pickup"] = True
                state["fate_point"] = 0
                state["guaranteed_weapon"] = False
                is_fate_guar = True
            elif state["guaranteed_weapon"] or rng.random() < 0.75:
                picked = dict(rng.choice(promo_wps))
                picked["is_pickup"] = True
                state["guaranteed_weapon"] = False
                if fate_id:
                    if picked["id"] == fate_id:
                        state["fate_point"] = 0
                    else:
                        state["fate_point"] = min(1, int(state.get("fate_point", 0)) + 1)
            else:
                picked = dict(_weighted_choice(std_5_wps, lambda w: 1.75 if w.get("weapon_type") in boost_wps else 1.0, rng))
                picked["is_pickup"] = False
                state["guaranteed_weapon"] = True
                if fate_id:
                    state["fate_point"] = min(1, int(state.get("fate_point", 0)) + 1)
            picked["is_fate_guaranteed"] = is_fate_guar
            picked["is_time_boost"] = (picked.get("weapon_type") in boost_wps)
            picked["pity_used"] = pity_used
            return picked

        if roll < p5 + p4:
            state["pity_4_weapon"] = 0
            w4_pickups = eff_pickup["weapon_4"]
            w4_ids = {w["id"] for w in w4_pickups}
            if w4_pickups and (state["guaranteed_4_weapon"] or rng.random() < 0.75):
                picked = dict(rng.choice(w4_pickups))
                picked["is_pickup"] = True
                state["guaranteed_4_weapon"] = False
            else:
                if w4_pickups:
                    state["guaranteed_4_weapon"] = True
                off_pool = std_4_chars + [w for w in gacha_4_wps_non_limited if w["id"] not in w4_ids]
                picked = dict(_weighted_choice(
                    off_pool or gacha_4_wps_non_limited,
                    lambda x: 1.65 if (x.get("weapon_type") in boost_wps or x.get("element") in boost_elems) else 1.0,
                    rng,
                ))
                picked["is_pickup"] = False
            picked["is_time_boost"] = (picked.get("weapon_type") in boost_wps)
            return picked

        picked = dict(_weighted_choice(wish_3_wps, lambda w: 1.5 if w.get("weapon_type") in boost_wps else 1.0, rng))
        picked["is_pickup"] = False
        return picked

    else:  # standard
        state["pity_standard"] += 1
        state["pity_4_standard"] += 1
        p5 = _gi_soft_pity_prob(state["pity_standard"], "standard")
        p4 = _gi_soft_4_prob(state["pity_4_standard"], "standard")
        roll = rng.random()

        if roll < p5:
            pity_used = state["pity_standard"]
            state["pity_standard"] = 0
            if rng.random() < 0.50:
                picked = dict(_weighted_choice(std_5_chars, lambda c: 1.75 if c.get("element") in boost_elems else 1.0, rng))
            else:
                picked = dict(_weighted_choice(std_5_wps, lambda w: 1.75 if w.get("weapon_type") in boost_wps else 1.0, rng))
            picked["is_pickup"] = False
            picked["is_time_boost"] = (picked.get("element") in boost_elems or picked.get("weapon_type") in boost_wps)
            picked["pity_used"] = pity_used
            return picked

        if roll < p5 + p4:
            state["pity_4_standard"] = 0
            if rng.random() < 0.50:
                picked = dict(_weighted_choice(all_std_4_chars_incl_starter, lambda c: 1.65 if c.get("element") in boost_elems else 1.0, rng))
            else:
                picked = dict(_weighted_choice(gacha_4_wps_non_limited, lambda w: 1.65 if w.get("weapon_type") in boost_wps else 1.0, rng))
            picked["is_pickup"] = False
            picked["is_time_boost"] = (picked.get("element") in boost_elems or picked.get("weapon_type") in boost_wps)
            return picked

        picked = dict(_weighted_choice(wish_3_wps, lambda w: 1.5 if w.get("weapon_type") in boost_wps else 1.0, rng))
        picked["is_pickup"] = False
        return picked


def _apply_gi_item_to_account(u_data: dict, item: dict, now_iso: str) -> tuple[int, int]:
    """유저 원신 보관함에 캐릭터/무기/성유물을 추가하고 돌파·재련·정수 및 스타라이트/스타더스트 획득량을 계산합니다."""
    kind = item.get("kind", "weapon")
    rank = int(item.get("rank", 3))
    items_map = u_data.setdefault("items", {})
    i_key = item["item_key"]

    if kind == "artifact":
        art_list = u_data.setdefault("artifacts", [])
        had_set = i_key in items_map
        item["is_new"] = not had_set
        piece_rec = copy.deepcopy(item)
        piece_rec["obtained_at"] = now_iso
        art_list.insert(0, piece_rec)
        # 보관함 최대 150개 유지 (잠금 해제된 3~4성 우선 자동 분해)
        if len(art_list) > 150:
            for idx_rm in range(len(art_list) - 1, -1, -1):
                if not art_list[idx_rm].get("locked") and art_list[idx_rm].get("rank", 5) < 5:
                    art_list.pop(idx_rm)
                    u_data["artifact_essence"] = int(u_data.get("artifact_essence", 0)) + 2
                    break
            del art_list[160:]

        # 도감/세트 요약 레코드도 items_map에 동기화
        existing_set = items_map.get(i_key)
        if existing_set:
            existing_set["count"] = int(existing_set.get("count", 1)) + 1
            existing_set["last_obtained_at"] = now_iso
            if piece_rec.get("cv", 0) > float(existing_set.get("best_cv", 0)):
                existing_set["best_cv"] = piece_rec.get("cv", 0)
        else:
            items_map[i_key] = {
                "id": item["id"],
                "kind": "artifact",
                "item_key": i_key,
                "name": item.get("set_name", item["name"]),
                "rank": rank,
                "rarity_label": "★" * rank,
                "bonus_2pc": item.get("bonus_2pc", ""),
                "bonus_4pc": item.get("bonus_4pc", ""),
                "icon": item.get("icon", ""),
                "pool_type": item.get("pool_type", "5성 비경"),
                "count": 1,
                "best_cv": item.get("cv", 0.0),
                "locked": (rank == 5),
                "obtained_at": now_iso,
                "last_obtained_at": now_iso,
            }

        gained_dust = 5 if rank == 3 else (10 if rank == 4 else 0)
        gained_essence = 1 if rank == 3 else (2 if rank == 4 else 4)
        u_data["stardust"] = int(u_data.get("stardust", 0)) + gained_dust
        u_data["artifact_essence"] = int(u_data.get("artifact_essence", 0)) + gained_essence
        item["gained_starglitter"] = 0
        item["gained_stardust"] = gained_dust
        item["gained_essence"] = gained_essence
        return 0, gained_dust

    existing = items_map.get(i_key)
    gained_glitter = 0
    gained_dust = 0

    if existing:
        existing["count"] = int(existing.get("count", 1)) + 1
        existing["last_obtained_at"] = now_iso
        existing["icon"] = item.get("icon", existing.get("icon", ""))
        existing["name"] = item.get("name", existing.get("name", ""))
        item["is_new"] = False
        if kind == "char":
            cur_c = int(existing.get("constellation", min(6, existing["count"] - 2)))
            if cur_c < 6:
                new_c = min(6, cur_c + 1)
                existing["constellation"] = new_c
                gained_glitter = 10 if rank == 5 else 2
            else:
                new_c = 6
                existing["constellation"] = 6
                gained_glitter = 25 if rank == 5 else 5
            item["new_constellation"] = new_c
        else:
            cur_r = int(existing.get("refinement", 1))
            new_r = min(5, cur_r + 1)
            existing["refinement"] = new_r
            item["new_refinement"] = new_r
            if rank == 5:
                gained_glitter = 10
            elif rank == 4:
                gained_glitter = 2
            else:
                gained_dust = 15
    else:
        item["is_new"] = True
        rec = {
            "id": item["id"],
            "kind": kind,
            "item_key": i_key,
            "name": item["name"],
            "rank": rank,
            "rarity_label": item["rarity_label"],
            "weapon_type": item.get("weapon_type", ""),
            "weapon_type_name": item.get("weapon_type_name", ""),
            "weapon_type_emoji": item.get("weapon_type_emoji", ""),
            "special_prop_name": item.get("special_prop_name", "-"),
            "icon": item.get("icon", ""),
            "pool_type": item.get("pool_type", "상시"),
            "count": 1,
            "level": 1,
            "locked": (rank == 5),
            "obtained_at": now_iso,
            "last_obtained_at": now_iso,
        }
        if kind == "char":
            rec["element"] = item.get("element", "Wind")
            rec["element_name"] = item.get("element_name", "바람")
            rec["element_emoji"] = item.get("element_emoji", "🌪️")
            rec["region_name"] = item.get("region_name", "티바트")
            rec["constellation"] = 0
            item["new_constellation"] = 0
        else:
            rec["refinement"] = 1
            item["new_refinement"] = 1
            if rank == 5:
                gained_glitter = 10
            elif rank == 4:
                gained_glitter = 2
            else:
                gained_dust = 15
        items_map[i_key] = rec

    u_data["starglitter"] = int(u_data.get("starglitter", 0)) + gained_glitter
    u_data["stardust"] = int(u_data.get("stardust", 0)) + gained_dust
    item["gained_starglitter"] = gained_glitter
    item["gained_stardust"] = gained_dust
    return gained_glitter, gained_dust


def _build_gi_pools():
    chars, weapons = load_genshin_kr_db()
    std_5_chars = [c for c in chars if c["rank"] == 5 and c["id"] in GENSHIN_STD_5_CHARS] or [c for c in chars if c["rank"] == 5]
    all_std_4_chars_incl = [c for c in chars if c["rank"] == 4]
    std_4_chars = [c for c in all_std_4_chars_incl if c["id"] not in GENSHIN_STARTER_4_CHARS] or all_std_4_chars_incl
    std_5_wps = [w for w in weapons if w["rank"] == 5 and w["wish_source"] == "standard"] or [w for w in weapons if w["rank"] == 5]
    wish_3_wps = [w for w in weapons if w["rank"] == 3 and w["wishable"]] or [w for w in weapons if w["rank"] == 3]
    gacha_4_wps_std = [w for w in weapons if w["rank"] == 4 and w["wish_source"] == "standard"] or [w for w in weapons if w["rank"] == 4 and w["wishable"]]
    return std_5_chars, std_4_chars, all_std_4_chars_incl, std_5_wps, wish_3_wps, gacha_4_wps_std


def execute_genshin_pull(guild_id: int, user_id: int, banner_key: str = "char1", count: int = 10, practice: bool = False) -> dict:
    """원신 기원(캐릭터/무기/상시/성유물 비경)을 1회 또는 10회 실행합니다."""
    if banner_key not in GENSHIN_BANNER_CONFIGS:
        banner_key = "char1"
    count = 10 if count >= 10 else 1

    load_genshin_kr_db()
    std_5_chars, std_4_chars, all_std_4_incl, std_5_wps, wish_3_wps, gacha_4_wps_std = _build_gi_pools()

    data = core.load_data()
    eff_pickup = resolve_effective_genshin_pickup(data.get("genshin_pickup"))
    u_data = ensure_genshin_user(data, guild_id, user_id)

    rng = random.SystemRandom()
    if practice:
        sim_state = copy.deepcopy(u_data)
        owned_items = u_data.get("items", {})
        drawn = []
        for _ in range(count):
            it = _roll_single_genshin(sim_state, banner_key, eff_pickup, std_5_chars, std_4_chars, all_std_4_incl, std_5_wps, wish_3_wps, gacha_4_wps_std, rng)
            prev = owned_items.get(it["item_key"])
            it["is_new"] = prev is None
            if it["kind"] == "char":
                it["new_constellation"] = min(6, int(prev.get("constellation", 0)) + 1) if prev else 0
            elif it["kind"] == "weapon":
                it["new_refinement"] = min(5, int(prev.get("refinement", 1)) + 1) if prev else 1
            it["gained_starglitter"] = 0
            it["gained_stardust"] = 0
            drawn.append(it)
        return {
            "drawn": drawn,
            "banner_key": banner_key,
            "eff_pickup": eff_pickup,
            "total_glitter": 0,
            "total_dust": 0,
            "user_state": sim_state,
            "practice": True,
        }

    now_iso = datetime.datetime.now(core.KST).isoformat()
    drawn = []
    tot_glitter = 0
    tot_dust = 0
    for _ in range(count):
        it = _roll_single_genshin(u_data, banner_key, eff_pickup, std_5_chars, std_4_chars, all_std_4_incl, std_5_wps, wish_3_wps, gacha_4_wps_std, rng)
        gg, gd = _apply_gi_item_to_account(u_data, it, now_iso)
        tot_glitter += gg
        tot_dust += gd
        drawn.append(it)

    u_data["total_pulls"] = int(u_data.get("total_pulls", 0)) + count

    # 기원 기록 (최근 50건) & 명예의 전당 갱신
    hist = u_data.setdefault("history", [])
    b_short = GENSHIN_BANNER_CONFIGS[banner_key]["short_name"]
    for it in drawn:
        if it["rank"] >= 4:
            hist.insert(0, {
                "name": it["name"],
                "kind": it["kind"],
                "rank": it["rank"],
                "is_pickup": bool(it.get("is_pickup")),
                "pity": it.get("pity_used"),
                "banner": b_short,
                "at": now_iso,
            })
    del hist[50:]

    _record_genshin_hof(data, guild_id, user_id, drawn, banner_key, now_iso)
    core.save_data(data)

    return {
        "drawn": drawn,
        "banner_key": banner_key,
        "eff_pickup": eff_pickup,
        "total_glitter": tot_glitter,
        "total_dust": tot_dust,
        "user_state": u_data,
        "practice": False,
    }


def _record_genshin_hof(data: dict, guild_id: int, user_id: int, drawn: list[dict], banner_key: str, now_iso: str):
    hof_root = data.setdefault("genshin_hall_of_fame", {})
    g_hof = hof_root.setdefault(str(guild_id or 0), {})
    if not isinstance(g_hof, dict):
        g_hof = {}
        hof_root[str(guild_id or 0)] = g_hof
    top_records = g_hof.setdefault("top_records", [])
    recent_5 = g_hof.setdefault("recent_5_logs", [])
    b_short = GENSHIN_BANNER_CONFIGS[banner_key]["short_name"]

    r5_items = [it for it in drawn if it.get("rank") == 5]
    if r5_items:
        for it in r5_items:
            recent_5.insert(0, {
                "uid": str(user_id),
                "name": it["name"],
                "kind": it["kind"],
                "is_pickup": bool(it.get("is_pickup")),
                "is_radiance": bool(it.get("is_radiance")),
                "pity": it.get("pity_used"),
                "banner": b_short,
                "at": now_iso,
            })
        del recent_5[25:]

        if len(drawn) == 10 and banner_key != "artifact":
            pickup_cnt = sum(1 for it in r5_items if it.get("is_pickup"))
            avg_pity = sum(int(it.get("pity_used") or 90) for it in r5_items) // len(r5_items)
            rec = {
                "uid": str(user_id),
                "r5_count": len(r5_items),
                "pickup_count": pickup_cnt,
                "min_pity": min(int(it.get("pity_used") or 90) for it in r5_items),
                "avg_pity": avg_pity,
                "items": [f"{'🎯' if it.get('is_pickup') else '★5'} {it['name']}({it.get('pity_used', '?')}스택)" for it in r5_items],
                "banner": b_short,
                "achieved_at": now_iso,
            }
            top_records.append(rec)
            top_records.sort(key=lambda r: (-r.get("r5_count", 0), -r.get("pickup_count", 0), r.get("min_pity", 99), r.get("achieved_at", "")))
            del top_records[10:]


# ==========================================
# 원신 성유물 전용 상호작용 (비경 집중·강화·환성 공양·축성의 서리)
# ==========================================
def set_genshin_artifact_target(guild_id: int, user_id: int, set_id: str | None) -> tuple[bool, str, dict]:
    """성유물 비경 집중 탐색 세트 지정"""
    load_genshin_kr_db()
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    if not set_id or set_id == "NONE":
        u_data["target_artifact_set_id"] = None
        core.save_data(data)
        return True, "🏛️ 비경 집중 탐색 세트가 해제되었습니다. (요일별 비경 로테이션 적용)", u_data
    art_set = GENSHIN_ARTIFACT_MAP.get(str(set_id))
    if not art_set:
        return False, "존재하지 않는 성유물 세트입니다.", u_data
    u_data["target_artifact_set_id"] = str(set_id)
    core.save_data(data)
    return True, f"🏛️ **비경 집중 세트 지정 완료:** `★{art_set['max_rank']} {art_set['name']}`\n• 2세트: {art_set['bonus_2pc']}", u_data


def enhance_genshin_artifact(guild_id: int, user_id: int, artifact_uid: str) -> tuple[bool, str, dict | None]:
    """성유물을 +4단계씩 최대 +20까지 강화하며 부옵션 추가/상승 및 CV·등급을 재계산합니다."""
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    arts = u_data.get("artifacts", [])
    target = next((a for a in arts if a.get("uid") == artifact_uid), None)
    if not target:
        return False, "보관함에서 해당 성유물을 찾을 수 없습니다.", None

    rank = int(target.get("rank", 5))
    max_lv = int(target.get("max_level", 20 if rank == 5 else 16))
    cur_lv = int(target.get("level", 0))
    if cur_lv >= max_lv:
        return False, f"**{target['name']}** 성유물은 이미 최고 강화 단계(`+{max_lv}`)입니다!", target

    cost_ess = 2 if rank == 5 else 1
    cur_ess = int(u_data.get("artifact_essence", 0))
    if cur_ess < cost_ess:
        return False, f"🧪 **축성의 정수**가 부족합니다! (필요: `{cost_ess}` / 보유: `{cur_ess}` · 성유물 비경 기원이나 분해로 획득)", target

    u_data["artifact_essence"] = cur_ess - cost_ess
    new_lv = min(max_lv, cur_lv + 4)
    target["level"] = new_lv

    # 주옵션 수치 보간
    m_stat = target.get("main_stat_name", "HP")
    v_start, v_max = GENSHIN_ARTIFACT_MAIN_VALUES.get((rank, m_stat), ("+717", "+4,780"))
    if new_lv >= max_lv:
        target["main_stat_val"] = v_max
    else:
        try:
            is_pct = "%" in v_max
            s_num = float(v_start.replace("+", "").replace(",", "").replace("%", ""))
            m_num = float(v_max.replace("+", "").replace(",", "").replace("%", ""))
            interp = s_num + (m_num - s_num) * (new_lv / float(max_lv))
            target["main_stat_val"] = f"+{interp:.1f}%" if is_pct else f"+{int(round(interp)):,}"
        except Exception:
            target["main_stat_val"] = v_max

    rng = random.SystemRandom()
    subs = target.setdefault("substats", [])
    used_names = {s["name"] for s in subs}
    scale = 1.0 if rank == 5 else (0.80 if rank == 4 else 0.60)

    if len(subs) < 4:
        cands = [s for s in GENSHIN_ARTIFACT_SUBSTATS if s[0] != m_stat and s[0] not in used_names]
        if cands:
            pick_s = rng.choice(cands)
            t_val = float(rng.choice(pick_s[1])) * scale
            subs.append({
                "name": pick_s[0],
                "value": round(t_val, 1),
                "is_pct": pick_s[2],
                "display": _format_gi_stat_val(t_val, pick_s[2]),
                "rolls": 1,
            })
            roll_msg = f"🆕 4번째 부옵션 개방: **{pick_s[0]} +{_format_gi_stat_val(t_val, pick_s[2])}**"
        else:
            roll_msg = "부옵션 강화 완료"
    else:
        up_sub = rng.choice(subs)
        meta_s = next((s for s in GENSHIN_ARTIFACT_SUBSTATS if s[0] == up_sub["name"]), None)
        add_val = (float(rng.choice(meta_s[1])) if meta_s else 3.5) * scale
        up_sub["value"] = round(float(up_sub.get("value", 0.0)) + add_val, 1)
        up_sub["rolls"] = int(up_sub.get("rolls", 1)) + 1
        up_sub["display"] = _format_gi_stat_val(up_sub["value"], bool(up_sub.get("is_pct")))
        roll_msg = f"✨ 부옵션 상승: **{up_sub['name']} ➔ +{up_sub['display']}** (`{up_sub['rolls']}회`)"

    cv, rv, grade = compute_genshin_artifact_score(target)
    target["cv"] = cv
    target["rv"] = rv
    target["grade"] = grade

    # 세트 최고 CV 갱신
    set_rec = u_data.get("items", {}).get(target.get("item_key", ""))
    if set_rec and cv > float(set_rec.get("best_cv", 0.0)):
        set_rec["best_cv"] = cv

    # +20 달성 시 보너스 축성의 서리 확률 또는 마일리지
    elixir_msg = ""
    if new_lv == 20 and rng.random() < 0.25:
        u_data["sanctifying_elixir"] = int(u_data.get("sanctifying_elixir", 0)) + 1
        elixir_msg = " · 💧 **축성의 서리 +1** 획득!"

    core.save_data(data)
    return True, f"🔨 **{target['name']}** `+{cur_lv}` ➔ **`+{new_lv}`** 강화 성공! (`-{cost_ess} 축성의 정수`)\n• {roll_msg}\n• 현재 치명타 가치(CV): **`{cv}점`** ({grade}){elixir_msg}", target


def toggle_genshin_artifact_lock(guild_id: int, user_id: int, artifact_uid: str) -> tuple[bool, bool, dict | None]:
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    target = next((a for a in u_data.get("artifacts", []) if a.get("uid") == artifact_uid), None)
    if not target:
        return False, False, None
    new_val = not bool(target.get("locked", False))
    target["locked"] = new_val
    core.save_data(data)
    return True, new_val, target


def salvage_genshin_artifacts(guild_id: int, user_id: int, max_rank_to_salvage: int = 4) -> tuple[bool, str, dict]:
    """잠금 해제된 3~4성(또는 미강화 5성 포함) 성유물을 일괄 분해하여 축성의 정수와 축성의 서리를 획득합니다."""
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    arts = u_data.get("artifacts", [])
    kept = []
    salvaged_cnt = 0
    gained_ess = 0
    r5_salvaged = 0
    for a in arts:
        rk = int(a.get("rank", 5))
        if not a.get("locked") and rk <= max_rank_to_salvage and int(a.get("level", 0)) == 0:
            salvaged_cnt += 1
            gained_ess += 6 if rk == 5 else (3 if rk == 4 else 1)
            if rk == 5:
                r5_salvaged += 1
        else:
            kept.append(a)

    if salvaged_cnt == 0:
        return False, "분해할 수 있는 잠금 해제 상태의 미강화 성유물이 없습니다.", u_data

    u_data["artifacts"] = kept
    u_data["artifact_essence"] = int(u_data.get("artifact_essence", 0)) + gained_ess
    gained_elixir = r5_salvaged // 3
    if gained_elixir > 0:
        u_data["sanctifying_elixir"] = int(u_data.get("sanctifying_elixir", 0)) + gained_elixir
    core.save_data(data)
    el_str = f" · 💧 **축성의 서리 +{gained_elixir}**" if gained_elixir else ""
    return True, f"♻️ 성유물 **{salvaged_cnt}개** 분해 완료! 🧪 **축성의 정수 +{gained_ess}**{el_str} (보유 정수: `{u_data['artifact_essence']}`)", u_data


def craft_genshin_artifact_strongbox(guild_id: int, user_id: int, set_id: str | None = None) -> tuple[bool, str, dict | None]:
    """신비한 공양(환성): 축성의 정수 12개를 소모하여 원하는 세트의 ★5 성유물을 즉시 연성합니다."""
    load_genshin_kr_db()
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    cur_ess = int(u_data.get("artifact_essence", 0))
    if cur_ess < 12:
        return False, f"🧪 **축성의 정수**가 부족합니다! (신비한 공양 필요: `12` / 보유: `{cur_ess}`)", None

    sid = str(set_id or u_data.get("target_artifact_set_id") or "")
    target_set = GENSHIN_ARTIFACT_MAP.get(sid)
    if not target_set or target_set.get("max_rank", 5) < 5:
        arts_5 = [a for a in get_genshin_artifacts() if a.get("max_rank", 5) == 5]
        target_set = arts_5[0] if arts_5 else None
    if not target_set:
        return False, "성유물 세트 정보를 불러올 수 없습니다.", None

    u_data["artifact_essence"] = cur_ess - 12
    sched = get_genshin_time_schedule()
    rng = random.SystemRandom()
    piece = _generate_genshin_artifact_piece(target_set, 5, rng, sched, is_pickup=True, pity_used=1)
    now_iso = datetime.datetime.now(core.KST).isoformat()
    _apply_gi_item_to_account(u_data, piece, now_iso)
    core.save_data(data)
    return True, f"⚗️ **[신비한 공양 성공]** `★★★★★ {piece['name']}` 획득! (`-12 축성의 정수`)\n• 주옵션: **{piece['main_stat_name']} {piece['main_stat_val']}** · 초기 CV: `{piece['cv']}점`", piece


def craft_genshin_artifact_elixir(
    guild_id: int,
    user_id: int,
    set_id: str,
    slot_code: str,
    main_stat: str,
    sub1: str = "치명타 확률",
    sub2: str = "치명타 피해",
) -> tuple[bool, str, dict | None]:
    """축성의 서리(성유물 변환기): 축성의 서리 1개를 소모해 세트·부위·주옵션·쌍치명 부옵션을 확정 지정하여 ★5 성유물을 제작합니다."""
    load_genshin_kr_db()
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    cur_el = int(u_data.get("sanctifying_elixir", 0))
    if cur_el < 1:
        return False, f"💧 **축성의 서리**가 부족합니다! (필요: `1` / 보유: `{cur_el}` · +20 강화 또는 5성 분해로 획득)", None

    target_set = GENSHIN_ARTIFACT_MAP.get(str(set_id))
    if not target_set:
        arts_5 = [a for a in get_genshin_artifacts() if a.get("max_rank", 5) == 5]
        target_set = arts_5[0] if arts_5 else None
    if not target_set:
        return False, "성유물 세트를 찾을 수 없습니다.", None

    u_data["sanctifying_elixir"] = cur_el - 1
    sched = get_genshin_time_schedule()
    rng = random.SystemRandom()
    forced_subs = [s for s in [sub1, sub2] if s and s != main_stat]
    piece = _generate_genshin_artifact_piece(
        target_set,
        5,
        rng,
        sched,
        forced_slot=slot_code,
        forced_main=main_stat,
        forced_subs=forced_subs,
        is_pickup=True,
        pity_used=1,
    )
    now_iso = datetime.datetime.now(core.KST).isoformat()
    _apply_gi_item_to_account(u_data, piece, now_iso)
    core.save_data(data)
    return True, f"💧 **[축성의 서리 연성 완료]** `★★★★★ {piece['name']}` 맞춤형 제작 성공! (`-1 축성의 서리`)\n• 주옵션: **{piece['main_stat_name']} {piece['main_stat_val']}** · 초기 CV: **`{piece['cv']}점`** ({piece['grade']})", piece


def toggle_genshin_item_lock(guild_id: int, user_id: int, item_key: str) -> tuple[bool, bool, dict | None]:
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    target = u_data.get("items", {}).get(item_key)
    if not target:
        return False, False, None
    new_val = not bool(target.get("locked", False))
    target["locked"] = new_val
    core.save_data(data)
    return True, new_val, target


def set_genshin_fate_path(guild_id: int, user_id: int, target_weapon_id: str | None) -> tuple[bool, str, dict]:
    """신의 주조(무기 이벤트 기원) 운명의 궤도 정해진 무기 변경 (변경 시 명정 포인트 0 초기화)"""
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    eff = resolve_effective_genshin_pickup(data.get("genshin_pickup"))
    w1, w2 = eff.get("weapon_1"), eff.get("weapon_2")

    if not target_weapon_id or target_weapon_id == "NONE":
        u_data["fate_target_id"] = None
        u_data["fate_point"] = 0
        core.save_data(data)
        return True, "🧭 **운명의 궤도** 선택이 해제되었습니다. (명정 포인트 `0/1`)", u_data

    valid = {w["id"]: w for w in (w1, w2) if w}
    if target_weapon_id not in valid:
        return False, "현재 진행 중인 신의 주조 픽업 5성 무기만 선택할 수 있습니다.", u_data

    old_target = u_data.get("fate_target_id")
    u_data["fate_target_id"] = target_weapon_id
    if old_target != target_weapon_id:
        u_data["fate_point"] = 0
    core.save_data(data)
    w_obj = valid[target_weapon_id]
    return True, f"🧭 **운명의 궤도 목표 설정 완료:** `★★★★★ {w_obj['name']}` (현재 명정: `{u_data['fate_point']}/1`)", u_data


def get_genshin_shop_catalog() -> dict:
    """이번 달 페이몬의 상점(스타라이트/스타더스트 교환) 품목을 반환합니다."""
    load_genshin_kr_db()
    month_idx = (datetime.datetime.now(core.KST).month - 1) % 6
    char_pair = GENSHIN_STARGLITTER_CHAR_ROTATION[month_idx]
    is_royal_month = (datetime.datetime.now(core.KST).month % 2 == 0)

    shop_chars = [GENSHIN_ALL_ITEMS[f"char:{cid}"] for cid in char_pair if f"char:{cid}" in GENSHIN_ALL_ITEMS]
    wp_series_prefix = "왕실" if is_royal_month else "흑암"
    shop_wps = [
        GENSHIN_ALL_ITEMS[f"weapon:{wid}"]
        for wid in sorted(GENSHIN_SHOP_WEAPONS)
        if f"weapon:{wid}" in GENSHIN_ALL_ITEMS and wp_series_prefix in GENSHIN_ALL_ITEMS[f"weapon:{wid}"]["name"]
    ]
    return {
        "month": datetime.datetime.now(core.KST).month,
        "month_key": datetime.datetime.now(core.KST).strftime("%Y-%m"),
        "chars": shop_chars,
        "weapons": shop_wps,
        "weapon_series_name": "왕실 시리즈" if is_royal_month else "흑암 시리즈",
    }


def purchase_genshin_shop_item(guild_id: int, user_id: int, offer_id: str) -> tuple[bool, str, dict]:
    """페이몬의 상점에서 스타라이트 또는 스타더스트로 상품 구매"""
    load_genshin_kr_db()
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    cat = get_genshin_shop_catalog()
    m_key = cat["month_key"]
    monthly = u_data.setdefault("shop_monthly", {})
    if monthly.get("month_key") != m_key:
        monthly.clear()
        monthly["month_key"] = m_key
        monthly["dust_intertwined"] = 0
        monthly["dust_acquaint"] = 0
        monthly["chars_bought"] = []
        monthly["dust_hero_wit"] = 0

    now_iso = datetime.datetime.now(core.KST).isoformat()

    if offer_id.startswith("buy_char:"):
        cid = offer_id.split(":", 1)[1]
        c_obj = next((c for c in cat["chars"] if c["id"] == cid), None)
        if not c_obj:
            return False, "이번 달 상점 로테이션 캐릭터가 아닙니다.", u_data
        bought = monthly.setdefault("chars_bought", [])
        if cid in bought:
            return False, f"이미 이번 달 **{c_obj['name']}** 교환 한도(월 1회)를 완료했습니다.", u_data
        if u_data["starglitter"] < 34:
            return False, f"주인 없는 스타라이트가 부족합니다! (필요: `34` / 보유: `{u_data['starglitter']}`)", u_data
        u_data["starglitter"] -= 34
        bought.append(cid)
        _apply_gi_item_to_account(u_data, dict(c_obj), now_iso)
        core.save_data(data)
        return True, f"✨ **★★★★ {c_obj['name']}** 영입 완료! (`-34 스타라이트`)", u_data

    if offer_id.startswith("buy_wp:"):
        wid = offer_id.split(":", 1)[1]
        w_obj = next((w for w in cat["weapons"] if w["id"] == wid), None)
        if not w_obj:
            return False, "현재 상점 무기 시리즈가 아닙니다.", u_data
        if u_data["starglitter"] < 24:
            return False, f"주인 없는 스타라이트가 부족합니다! (필요: `24` / 보유: `{u_data['starglitter']}`)", u_data
        u_data["starglitter"] -= 24
        _apply_gi_item_to_account(u_data, dict(w_obj), now_iso)
        core.save_data(data)
        return True, f"⚔️ **★★★★ {w_obj['name']}** 구매 완료! (`-24 스타라이트`)", u_data

    if offer_id == "glitter_intertwined":
        if u_data["starglitter"] < 5:
            return False, f"주인 없는 스타라이트가 부족합니다! (필요: `5` / 보유: `{u_data['starglitter']}`)", u_data
        u_data["starglitter"] -= 5
        u_data["intertwined_fate"] = int(u_data.get("intertwined_fate", 0)) + 1
        core.save_data(data)
        return True, "🌠 **뒤얽힌 인연 ×1**을 교환했습니다! (`-5 스타라이트`)", u_data

    if offer_id == "glitter_acquaint":
        if u_data["starglitter"] < 5:
            return False, f"주인 없는 스타라이트가 부족합니다! (필요: `5` / 보유: `{u_data['starglitter']}`)", u_data
        u_data["starglitter"] -= 5
        u_data["acquaint_fate"] = int(u_data.get("acquaint_fate", 0)) + 1
        core.save_data(data)
        return True, "🌌 **만남의 인연 ×1**을 교환했습니다! (`-5 스타라이트`)", u_data

    if offer_id == "dust_intertwined":
        used = int(monthly.get("dust_intertwined", 0))
        if used >= 5:
            return False, "이달의 스타더스트 뒤얽힌 인연 교환 한도(5/5회)를 모두 사용했습니다.", u_data
        if u_data["stardust"] < 75:
            return False, f"주인 없는 스타더스트가 부족합니다! (필요: `75` / 보유: `{u_data['stardust']}`)", u_data
        u_data["stardust"] -= 75
        monthly["dust_intertwined"] = used + 1
        u_data["intertwined_fate"] = int(u_data.get("intertwined_fate", 0)) + 1
        core.save_data(data)
        return True, f"🌠 **뒤얽힌 인연 ×1** 교환 완료! (`-75 스타더스트` · 이달 `{used + 1}/5회`)", u_data

    if offer_id == "dust_acquaint":
        used = int(monthly.get("dust_acquaint", 0))
        if used >= 5:
            return False, "이달의 스타더스트 만남의 인연 교환 한도(5/5회)를 모두 사용했습니다.", u_data
        if u_data["stardust"] < 75:
            return False, f"주인 없는 스타더스트가 부족합니다! (필요: `75` / 보유: `{u_data['stardust']}`)", u_data
        u_data["stardust"] -= 75
        monthly["dust_acquaint"] = used + 1
        u_data["acquaint_fate"] = int(u_data.get("acquaint_fate", 0)) + 1
        core.save_data(data)
        return True, f"🌌 **만남의 인연 ×1** 교환 완료! (`-75 스타더스트` · 이달 `{used + 1}/5회`)", u_data

    if offer_id == "dust_hero_wit":
        if u_data["stardust"] < 40:
            return False, f"주인 없는 스타더스트가 부족합니다! (필요: `40` / 보유: `{u_data['stardust']}`)", u_data
        u_data["stardust"] -= 40
        u_data["hero_wit"] = int(u_data.get("hero_wit", 0)) + 5
        core.save_data(data)
        return True, f"📘 **영웅의 경험 ×5** 구매 완료! (보유: `{u_data['hero_wit']}권` · 보관함 캐릭터 레벨업 가능)", u_data

    return False, "알 수 없는 상점 상품입니다.", u_data


def levelup_genshin_char(guild_id: int, user_id: int, item_key: str) -> tuple[bool, str, dict]:
    """영웅의 경험 ×2권을 소모해 보유 캐릭터 레벨을 Lv.1 -> Lv.90까지 성장시킵니다."""
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    c = u_data.get("items", {}).get(item_key)
    if not c or c.get("kind") != "char":
        return False, "보유 중인 캐릭터를 찾을 수 없습니다.", u_data
    cur_lv = int(c.get("level", 1))
    if cur_lv >= 90:
        return False, f"**{c['name']}** 캐릭터는 이미 최고 레벨(`Lv.90`)입니다!", u_data
    wit = int(u_data.get("hero_wit", 0))
    if wit < 2:
        return False, f"📘 **영웅의 경험**이 부족합니다! (`/원신 상점`에서 스타더스트 40으로 5권 구매 가능 · 보유 `{wit}권`)", u_data
    u_data["hero_wit"] = wit - 2
    new_lv = min(90, cur_lv + 10)
    c["level"] = new_lv
    core.save_data(data)
    return True, f"⬆️ **{c['name']}** 레벨업! `Lv.{cur_lv}` ➔ **`Lv.{new_lv}`** (`-2 영웅의 경험`)", u_data


def compute_genshin_char_power(char_obj: dict) -> int:
    rank = int(char_obj.get("rank", 4))
    lv = max(1, int(char_obj.get("level", 1)))
    constellation = max(0, min(6, int(char_obj.get("constellation", 0))))
    base = 12000 if rank == 5 else 8500
    lv_bonus = lv * (190 if rank == 5 else 140)
    c_mult = 1.0 + constellation * 0.12
    return int((base + lv_bonus) * c_mult)


def analyze_genshin_party(party_chars: list[dict]) -> dict:
    """4인 파티의 원소 공명(Elemental Resonance)과 전투력을 정밀 계산합니다."""
    if not party_chars:
        return {"resonances": [], "base_power": 0, "total_power": 0, "bonus_pct": 0}

    elem_counts: dict[str, int] = {}
    base_power = 0
    for c in party_chars[:4]:
        el = c.get("element", "Wind")
        elem_counts[el] = elem_counts.get(el, 0) + 1
        base_power += compute_genshin_char_power(c)

    resonances = []
    bonus_pct = 0
    for el_code, cnt in elem_counts.items():
        if cnt >= 2:
            info = GENSHIN_ELEMENT_MAP.get(el_code)
            if info:
                resonances.append({
                    "emoji": info["emoji"],
                    "name": info["res_name"],
                    "desc": info["res_desc"],
                })
                bonus_pct += 18

    if len(party_chars) == 4 and len(elem_counts) == 4:
        resonances.append({
            "emoji": "🌈",
            "name": "교직된 수호 (4원소)",
            "desc": "파티 내 4가지 원소 배치 · 모든 원소/물리 내성 +15%",
        })
        bonus_pct += 14

    total_power = int(base_power * (1.0 + bonus_pct / 100.0))
    return {
        "resonances": resonances,
        "base_power": base_power,
        "total_power": total_power,
        "bonus_pct": bonus_pct,
    }


def get_genshin_pokedex_stats(guild_id: int, user_id: int) -> dict:
    chars, weapons = load_genshin_kr_db()
    artifacts = get_genshin_artifacts()
    data = core.load_data()
    u_data = ensure_genshin_user(data, guild_id, user_id)
    owned_map = u_data.get("items", {})

    all_master = chars + weapons + artifacts
    wishable_master = [it for it in all_master if it.get("wishable", True)]

    owned_all = []
    unowned_all = []
    for it in all_master:
        ik = it["item_key"]
        if ik in owned_map:
            merged = {**it, **owned_map[ik]}
            owned_all.append(merged)
        else:
            unowned_all.append(dict(it))

    w_owned = sum(1 for it in wishable_master if it["item_key"] in owned_map)
    w_total = max(1, len(wishable_master))

    c5_tot = sum(1 for c in chars if c["rank"] == 5)
    c5_own = sum(1 for c in chars if c["rank"] == 5 and c["item_key"] in owned_map)
    c4_tot = sum(1 for c in chars if c["rank"] == 4)
    c4_own = sum(1 for c in chars if c["rank"] == 4 and c["item_key"] in owned_map)
    w5_tot = sum(1 for w in weapons if w["rank"] == 5)
    w5_own = sum(1 for w in weapons if w["rank"] == 5 and w["item_key"] in owned_map)
    w4_tot = sum(1 for w in weapons if w["rank"] == 4 and w["wishable"])
    w4_own = sum(1 for w in weapons if w["rank"] == 4 and w["wishable"] and w["item_key"] in owned_map)
    a5_tot = len(artifacts)
    a5_own = sum(1 for a in artifacts if a["item_key"] in owned_map)

    rate = (w_owned / w_total) * 100.0
    filled = int(round((rate / 100.0) * 10))
    bar = "🟨" * filled + "⬛" * max(0, 10 - filled)

    return {
        "total_all": len(all_master),
        "owned_total": len(owned_all),
        "wishable_total": w_total,
        "wishable_owned": w_owned,
        "rate": rate,
        "bar": bar,
        "c5": (c5_own, c5_tot),
        "c4": (c4_own, c4_tot),
        "w5": (w5_own, w5_tot),
        "w4": (w4_own, w4_tot),
        "art_sets": (a5_own, a5_tot),
        "owned_artifacts_count": len(u_data.get("artifacts", [])),
        "owned_items": owned_all,
        "unowned_items": unowned_all,
    }


def get_genshin_hall_of_fame(data: dict, guild_id: int) -> dict:
    hof = data.get("genshin_hall_of_fame", {}).get(str(guild_id or 0), {})
    if not isinstance(hof, dict):
        return {"top_records": [], "recent_5_logs": []}
    return {
        "top_records": list(hof.get("top_records") or []),
        "recent_5_logs": list(hof.get("recent_5_logs") or []),
    }


def apply_genshin_pickup_preset(preset_key: str) -> tuple[bool, str, dict]:
    load_genshin_kr_db()
    data = core.load_data()
    if preset_key == "reset":
        data["genshin_pickup"] = copy.deepcopy(core.DEFAULT_CONFIG["genshin_pickup"])
        core.save_data(data)
        return True, "🧹 원신 기원 픽업 설정이 기본값으로 초기화되었습니다.", resolve_effective_genshin_pickup(data["genshin_pickup"])

    preset = GENSHIN_BANNER_PRESETS.get(preset_key)
    if not preset:
        return False, "알 수 없는 프리셋입니다.", resolve_effective_genshin_pickup(data.get("genshin_pickup"))

    now_iso = datetime.datetime.now(core.KST).isoformat()
    cfg = {
        "char1": preset.get("char1"),
        "char2": preset.get("char2"),
        "char_4_ids": list(preset.get("char_4_ids") or []),
        "weapon_1": preset.get("weapon_1"),
        "weapon_2": preset.get("weapon_2"),
        "weapon_4_ids": [],
        "banner_name": preset.get("banner_name", "티바트 이벤트 기원"),
        "version_label": preset.get("label", "프리셋 연동"),
        "updated_at": now_iso,
    }
    data["genshin_pickup"] = cfg
    core.save_data(data)
    return True, f"🎯 **{preset['label']}** 픽업 적용 완료!", resolve_effective_genshin_pickup(cfg)


async def genshin_5star_char_autocomplete(interaction, current: str):
    from discord import app_commands
    chars, _ = load_genshin_kr_db()
    q = (current or "").strip().lower()
    cands = [c for c in chars if c["rank"] == 5 and (not q or q in c["name"].lower() or q in c["id"])]
    return [
        app_commands.Choice(name=f"★★★★★ {c['name']} ({c['element_emoji']}{c['element_name']} · {c['pool_type']})"[:100], value=c["id"])
        for c in cands[:25]
    ]


async def genshin_4star_char_autocomplete(interaction, current: str):
    from discord import app_commands
    chars, _ = load_genshin_kr_db()
    q = (current or "").strip().lower()
    cands = [c for c in chars if c["rank"] == 4 and c["id"] not in GENSHIN_STARTER_4_CHARS and (not q or q in c["name"].lower() or q in c["id"])]
    return [
        app_commands.Choice(name=f"★★★★ {c['name']} ({c['element_emoji']}{c['element_name']})"[:100], value=c["id"])
        for c in cands[:25]
    ]


async def genshin_5star_weapon_autocomplete(interaction, current: str):
    from discord import app_commands
    _, weapons = load_genshin_kr_db()
    q = (current or "").strip().lower()
    cands = [w for w in weapons if w["rank"] == 5 and (not q or q in w["name"].lower() or q in w["id"])]
    return [
        app_commands.Choice(name=f"★★★★★ {w['name']} ({w['weapon_type_emoji']}{w['weapon_type_name']} · {w['pool_type']})"[:100], value=w["id"])
        for c in cands[:0]
    ] + [
        app_commands.Choice(name=f"★★★★★ {w['name']} ({w['weapon_type_emoji']}{w['weapon_type_name']} · {w['pool_type']})"[:100], value=w["id"])
        for w in cands[:25]
    ]


async def genshin_owned_char_autocomplete(interaction, current: str):
    from discord import app_commands
    data = core.get_cached_data()
    g_key = str(interaction.guild_id or 0)
    u_key = str(interaction.user.id)
    items = data.get("genshin_users", {}).get(g_key, {}).get(u_key, {}).get("items", {})
    owned_chars = [v for v in items.values() if isinstance(v, dict) and v.get("kind") == "char"]
    owned_chars.sort(key=lambda c: (-c.get("rank", 4), -c.get("constellation", 0), c.get("name", "")))
    q = (current or "").strip().lower()
    res = []
    for c in owned_chars:
        if q and q not in c.get("name", "").lower() and q not in c.get("element_name", "").lower():
            continue
        res.append(app_commands.Choice(
            name=f"{'★5' if c.get('rank') == 5 else '★4'} {c.get('name')} ({c.get('constellation', 0)}돌 · Lv.{c.get('level', 1)})"[:100],
            value=c["item_key"],
        ))
        if len(res) >= 25:
            break
    return res

