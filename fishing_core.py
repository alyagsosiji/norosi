"""
fishing_core.py - Norosi 통합 낚시 엔진, 초대규모 글로벌 공개 어종 DB (호수·강·바다),
KST 시간/날씨 환경 로테이션, 세부 수역 탐사, 장비·미끼·수족관·도감·최대어 랭킹 및 PNG 포획 카드 생성기
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import io
import json
import math
import os
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import core

try:
    from PIL import Image, ImageDraw, ImageFilter
except Exception:
    Image = None
    ImageDraw = None
    ImageFilter = None

# ==========================================
# 스레드 안전 상태 락 (동시 포획/판매/수확 RMW 경합 방지)
# ==========================================
_FISHING_LOCK = core._DATA_LOCK

# ==========================================
# 낚시 출조(낚기) 4초 쿨타임 트래커 (유저별)
# ==========================================
FISHING_CAST_COOLDOWN_SECONDS: float = 4.0
FISHING_CAST_COOLDOWN: Dict[int, float] = {}


def check_and_update_fishing_cooldown(user_id: int | str, guild_id: int | str = 0) -> Tuple[bool, float]:
    """낚시 출조(낚기) 쿨타임(기본 4초 - 펫/요리 버프 감축, 최소 1.5초) 확인 및 갱신. (허용 여부, 남은 초) 반환."""
    uid = int(user_id)
    cd_sec = FISHING_CAST_COOLDOWN_SECONDS
    try:
        import life_core
        buffs = life_core.get_active_life_buffs(guild_id, uid)
        cd_reduce = float(buffs.get("cooldown_reduce", 0.0) or 0.0)
        if cd_reduce > 0:
            cd_sec = max(1.5, round(FISHING_CAST_COOLDOWN_SECONDS - cd_reduce, 2))
    except Exception:
        pass
    with _FISHING_LOCK:
        now = time.time()
        last = FISHING_CAST_COOLDOWN.get(uid, 0.0)
        elapsed = now - last
        if elapsed < cd_sec:
            rem = max(0.1, round(cd_sec - elapsed, 1))
            return False, rem
        FISHING_CAST_COOLDOWN[uid] = now
        return True, 0.0


def clear_fishing_cooldown(user_id: Optional[int | str] = None) -> None:
    """낚시 출조(낚기) 쿨타임 초기화 (user_id 미지정 시 전체 초기화)."""
    with _FISHING_LOCK:
        if user_id is None:
            FISHING_CAST_COOLDOWN.clear()
        else:
            FISHING_CAST_COOLDOWN.pop(int(user_id), None)

# ==========================================
# 서식지 & 환경 상수
# ==========================================
HABITATS: Dict[str, Dict[str, Any]] = {
    "lake": {
        "id": "lake",
        "name": "호수",
        "emoji": "🏞️",
        "label": "🏞️ 호수 (정수역·저수지·심수호)",
        "rgb": (42, 187, 155),
        "discord_color": 0x2ABB9B,
        "desc": "잔잔한 수초대부터 깊은 심수층까지 다양한 담수어와 거대 고대어가 서식하는 호수",
    },
    "river": {
        "id": "river",
        "name": "강",
        "emoji": "🌊",
        "label": "🌊 강 (1급수 계곡·본류·기수역)",
        "rgb": (66, 165, 245),
        "discord_color": 0x42A5F5,
        "desc": "맑은 여울의 계류어부터 강물과 바닷물이 만나는 기수역 회유어까지 역동적인 강",
    },
    "sea": {
        "id": "sea",
        "name": "바다",
        "emoji": "⚓",
        "label": "⚓ 바다 (연안 갯바위·외해·심해)",
        "rgb": (36, 98, 186),
        "discord_color": 0x2462BA,
        "desc": "갯바위 돔 어종부터 원양의 대물 참치와 심해의 전설 어종이 기다리는 망망대해",
    },
}

RARITY_META: Dict[int, Dict[str, Any]] = {
    1: {"stars": "★1", "full_stars": "★☆☆☆☆", "name": "일반", "emoji": "⚪", "rgb": (148, 163, 184), "discord_color": 0x94A3B8, "tank_rate": 3},
    2: {"stars": "★2", "full_stars": "★★☆☆☆", "name": "고급", "emoji": "🟢", "rgb": (52, 211, 153), "discord_color": 0x34D399, "tank_rate": 8},
    3: {"stars": "★3", "full_stars": "★★★☆☆", "name": "희귀", "emoji": "🔵", "rgb": (56, 189, 248), "discord_color": 0x38BDF8, "tank_rate": 22},
    4: {"stars": "★4", "full_stars": "★★★★☆", "name": "전설", "emoji": "🟡", "rgb": (250, 204, 21), "discord_color": 0xFACC15, "tank_rate": 60},
    5: {"stars": "★5", "full_stars": "★★★★★", "name": "신화", "emoji": "🟣", "rgb": (192, 132, 252), "discord_color": 0xC084FC, "tank_rate": 160},
}

WEATHERS: Dict[str, Dict[str, Any]] = {
    "clear": {
        "id": "clear",
        "name": "맑음",
        "emoji": "☀️",
        "rare_mult": 1.00,
        "size_mult": 1.00,
        "desc": "화창하고 시야가 탁 트여 전 어종이 고르게 활동합니다.",
    },
    "rain": {
        "id": "rain",
        "name": "비",
        "emoji": "🌧️",
        "rare_mult": 1.25,
        "size_mult": 1.05,
        "desc": "빗방울이 수면을 두드리며 경계심이 풀려 희귀어 입질이 늘고 대물이 떠오릅니다.",
    },
    "storm": {
        "id": "storm",
        "name": "폭풍우",
        "emoji": "⛈️",
        "rare_mult": 1.55,
        "size_mult": 1.12,
        "desc": "거친 파도와 저기압으로 평소 보기 힘든 ★4~★5 초거대 어종 출현율이 급상승합니다!",
    },
    "fog": {
        "id": "fog",
        "name": "안개",
        "emoji": "🌫️",
        "rare_mult": 1.32,
        "size_mult": 1.04,
        "desc": "물안개가 자욱이 깔려 밤·심수층의 신비로운 어종이 얕은 곳까지 올라옵니다.",
    },
}

# ==========================================
# 장비 & 미끼 마스터 데이터
# ==========================================
RODS: Dict[str, Dict[str, Any]] = {
    "bamboo": {
        "id": "bamboo",
        "tier": 1,
        "name": "대나무 민낚싯대",
        "emoji": "🎋",
        "price": 0,
        "rare_bonus": 0.0,
        "size_bonus": 0.0,
        "gold_bonus": 0.0,
        "desc": "가볍고 다루기 쉬운 기본 낚싯대 (모든 출조사 기본 지급)",
    },
    "carbon": {
        "id": "carbon",
        "tier": 2,
        "name": "카본 민물 올림대",
        "emoji": "🎣",
        "price": 1200,
        "rare_bonus": 0.15,
        "size_bonus": 0.05,
        "gold_bonus": 0.08,
        "desc": "탄성이 뛰어난 카본 소재! 희귀 확률 +15%, 체장 보너스 +5%",
    },
    "lure_mid": {
        "id": "lure_mid",
        "tier": 3,
        "name": "미들급 스핀 루어대",
        "emoji": "🪄",
        "price": 4500,
        "rare_bonus": 0.35,
        "size_bonus": 0.10,
        "gold_bonus": 0.15,
        "desc": "중대형 포식어 제압용 루어대! 희귀 확률 +35%, 판매가 +15%",
    },
    "deep_jig": {
        "id": "deep_jig",
        "tier": 4,
        "name": "심해 지깅 카본로드",
        "emoji": "🔱",
        "price": 14000,
        "rare_bonus": 0.60,
        "size_bonus": 0.16,
        "gold_bonus": 0.25,
        "desc": "깊은 해구와 심수층 대물을 끌어올리는 고강도 로드! 희귀 +60%",
    },
    "tournament": {
        "id": "tournament",
        "tier": 5,
        "name": "마스터 토너먼트 로드",
        "emoji": "🏆",
        "price": 38000,
        "rare_bonus": 0.95,
        "size_bonus": 0.22,
        "gold_bonus": 0.35,
        "desc": "프로 대회 우승자 전용 커스텀 로드! 월척 출현율 대폭 증가",
    },
    "poseidon": {
        "id": "poseidon",
        "tier": 6,
        "name": "포세이돈 삼지창 로드",
        "emoji": "⚡",
        "price": 95000,
        "rare_bonus": 1.45,
        "size_bonus": 0.30,
        "gold_bonus": 0.50,
        "desc": "신화 어종과의 승부를 위해 제련된 궁극의 낚싯대! 희귀 +145%, 판매 +50%",
    },
}

REELS: Dict[str, Dict[str, Any]] = {
    "basic_reel": {
        "id": "basic_reel",
        "tier": 1,
        "name": "기본 원형 릴",
        "emoji": "⭕",
        "price": 0,
        "window_sec": 5.5,
        "wait_reduce": 0.0,
        "trophy_bonus": 0.0,
        "desc": "안정적인 입질 대기(5.5초 + 유예 1.2초)를 제공하는 기본 릴",
    },
    "bearing_spin": {
        "id": "bearing_spin",
        "tier": 2,
        "name": "5베어링 스피닝 릴",
        "emoji": "⚙️",
        "price": 1000,
        "window_sec": 6.5,
        "wait_reduce": 0.25,
        "trophy_bonus": 0.05,
        "desc": "부드러운 드랙 성능! 당기기 시간 6.5초(+1.2초 유예), 입질 속도 단축",
    },
    "baitcaster": {
        "id": "baitcaster",
        "tier": 3,
        "name": "하이엔드 베이트 릴",
        "emoji": "🌀",
        "price": 3800,
        "window_sec": 7.5,
        "wait_reduce": 0.50,
        "trophy_bonus": 0.12,
        "desc": "정밀 기어비로 대물의 반항을 제압! 당기기 7.5초, 월척 확률 +12%",
    },
    "electric_deep": {
        "id": "electric_deep",
        "tier": 4,
        "name": "전동 딥씨 릴",
        "emoji": "🔋",
        "price": 12500,
        "window_sec": 8.5,
        "wait_reduce": 0.75,
        "trophy_bonus": 0.20,
        "desc": "고속 모터 권취! 당기기 8.5초(+1.2초 유예), 입질 대기 대폭 단축",
    },
    "chronos": {
        "id": "chronos",
        "tier": 5,
        "name": "크로노스 타임 릴",
        "emoji": "⏳",
        "price": 35000,
        "window_sec": 10.0,
        "wait_reduce": 1.00,
        "trophy_bonus": 0.30,
        "desc": "입질 순간을 늦추는 시공의 릴! 당기기 10초(+1.2초 유예), 월척 확률 +30%",
    },
}

NETS: Dict[str, Dict[str, Any]] = {
    "cast_net": {
        "id": "cast_net",
        "tier": 1,
        "name": "초보자 투망",
        "emoji": "🕸️",
        "price": 1500,
        "min_catch": 2,
        "max_catch": 3,
        "rare_bonus": 0.0,
        "size_bonus": 0.0,
        "desc": "상점 구매 전용 입문 투망! 1회 출조 시 2~3마리 동시 포획",
    },
    "trawl_net": {
        "id": "trawl_net",
        "tier": 2,
        "name": "삼중 자망 그물",
        "emoji": "🧶",
        "price": 5800,
        "min_catch": 2,
        "max_catch": 5,
        "rare_bonus": 0.06,
        "size_bonus": 0.03,
        "desc": "그물코가 촘촘한 삼중 어망! 1회 2~5마리 포획 · 희귀 +6%",
    },
    "silk_net": {
        "id": "silk_net",
        "tier": 3,
        "name": "강화 실크 어망",
        "emoji": "🧺",
        "price": 18500,
        "min_catch": 3,
        "max_catch": 7,
        "rare_bonus": 0.14,
        "size_bonus": 0.06,
        "desc": "고탄성 실크 어망! 1회 3~7마리 포획 · 희귀 +14% · 크기 +6%",
    },
    "deep_trawl": {
        "id": "deep_trawl",
        "tier": 4,
        "name": "심해 대형 트롤망",
        "emoji": "🚢",
        "price": 48000,
        "min_catch": 4,
        "max_catch": 9,
        "rare_bonus": 0.24,
        "size_bonus": 0.10,
        "desc": "대어 무리를 휩쓰는 트롤망! 1회 4~9마리 포획 · 희귀 +24%",
    },
    "poseidon_net": {
        "id": "poseidon_net",
        "tier": 5,
        "name": "만선 황금 대망",
        "emoji": "🌌",
        "price": 120000,
        "min_catch": 5,
        "max_catch": 10,
        "rare_bonus": 0.38,
        "size_bonus": 0.15,
        "desc": "전설의 황금 대망! 1회 5~10마리 대량 포획 · 희귀 +38% · 크기 +15%",
    },
}

BAITS: Dict[str, Dict[str, Any]] = {
    "dough": {
        "id": "dough",
        "name": "기본 곡물 떡밥",
        "emoji": "🍡",
        "price_per_pack": 0,
        "pack_qty": 0,
        "unlimited": True,
        "rare_mult": 1.00,
        "size_mult": 1.00,
        "desc": "무제한 사용 가능한 기본 떡밥",
    },
    "worm": {
        "id": "worm",
        "name": "싱싱한 붉은 지렁이",
        "emoji": "🪱",
        "price_per_pack": 120,
        "pack_qty": 10,
        "unlimited": False,
        "rare_mult": 1.25,
        "size_mult": 1.05,
        "desc": "담수·연안 어종이 강하게 반응 (10개 묶음 120🪙 / 희귀 ×1.25)",
    },
    "shrimp": {
        "id": "shrimp",
        "name": "활력 생물 크릴새우",
        "emoji": "🦐",
        "price_per_pack": 280,
        "pack_qty": 10,
        "unlimited": False,
        "rare_mult": 1.45,
        "size_mult": 1.10,
        "desc": "돔·농어·대형 육식어 선호 특급 생미끼 (10개 280🪙 / 희귀 ×1.45)",
    },
    "lure": {
        "id": "lure",
        "name": "메탈 지그 루어",
        "emoji": "🪝",
        "price_per_pack": 550,
        "pack_qty": 10,
        "unlimited": False,
        "rare_mult": 1.75,
        "size_mult": 1.15,
        "desc": "배스·쏘가리·방어·참치 등 대물 저격용 (10개 550🪙 / 희귀 ×1.75)",
    },
    "glow": {
        "id": "glow",
        "name": "야광 심해 집어 미끼",
        "emoji": "💠",
        "price_per_pack": 1100,
        "pack_qty": 10,
        "unlimited": False,
        "rare_mult": 2.20,
        "size_mult": 1.22,
        "desc": "야간·안개·폭풍우·심해어 유혹 극대화 (10개 1,100🪙 / 희귀 ×2.20)",
    },
    "golden": {
        "id": "golden",
        "name": "황금 전설 떡밥",
        "emoji": "✨",
        "price_per_pack": 2400,
        "pack_qty": 5,
        "unlimited": False,
        "rare_mult": 3.20,
        "size_mult": 1.32,
        "variant_mult": 1.40,
        "desc": "★4 전설 & ★5 신화 대물 전용 비기 미끼 (5개 2,400🪙 / 희귀 ×3.20)",
    },
    "live_minnow": {
        "id": "live_minnow",
        "name": "특제 생미끼",
        "emoji": "🐟",
        "price_per_pack": 0,
        "pack_qty": 5,
        "unlimited": False,
        "craft_only": True,
        "rare_mult": 1.95,
        "size_mult": 1.18,
        "variant_mult": 1.35,
        "desc": "공방에서 소형어(★1~2) 5마리를 분해해 제작! 희귀 ×1.95 · 크기 ×1.18 · 변이율 ↑",
    },
    "trophy_chum": {
        "id": "trophy_chum",
        "name": "대물 특제 집어제",
        "emoji": "🍖",
        "price_per_pack": 0,
        "pack_qty": 3,
        "unlimited": False,
        "craft_only": True,
        "rare_mult": 2.65,
        "size_mult": 1.30,
        "variant_mult": 1.65,
        "desc": "공방에서 소형어(★1~2) 12마리를 분해해 제작! 희귀 ×2.65 · 대물/변이율 대폭 ↑",
    },
}

# ==========================================
# 변이(이로치) · 최대 금관 / 최소 은관 메타
# ==========================================
VARIANT_META: Dict[str, Dict[str, Any]] = {
    "normal": {
        "id": "normal",
        "name": "일반",
        "emoji": "",
        "gold_mult": 1.00,
        "tank_mult": 1.00,
        "crystal_bonus": 0,
        "rgb": None,
        "body_rgb": None,
        "badge": None,
        "base_prob": 0.0,
    },
    "golden": {
        "id": "golden",
        "name": "황금 변이",
        "emoji": "✨",
        "gold_mult": 2.00,
        "tank_mult": 1.50,
        "crystal_bonus": 35,
        "rgb": (250, 204, 21),
        "body_rgb": (255, 215, 95),
        "badge": "황금 변이",
        "base_prob": 0.025,
    },
    "albino": {
        "id": "albino",
        "name": "알비노 변이",
        "emoji": "❄️",
        "gold_mult": 2.80,
        "tank_mult": 1.80,
        "crystal_bonus": 60,
        "rgb": (224, 242, 254),
        "body_rgb": (244, 249, 255),
        "badge": "알비노 변이",
        "base_prob": 0.010,
    },
    "abyssal": {
        "id": "abyssal",
        "name": "심해 발광 변이",
        "emoji": "🌌",
        "gold_mult": 4.00,
        "tank_mult": 2.50,
        "crystal_bonus": 120,
        "rgb": (168, 85, 247),
        "body_rgb": (147, 51, 234),
        "badge": "심해 발광",
        "base_prob": 0.0045,
    },
}

CROWN_META: Dict[str, Dict[str, Any]] = {
    "max_gold": {
        "id": "max_gold",
        "name": "최대 금관",
        "emoji": "🏆",
        "badge": "최대 금관",
        "gold_mult": 1.25,
        "first_crystal": 30,
        "rgb": (245, 158, 11),
    },
    "min_silver": {
        "id": "min_silver",
        "name": "최소 은관",
        "emoji": "🥈",
        "badge": "최소 은관",
        "gold_mult": 1.15,
        "first_crystal": 20,
        "rgb": (148, 163, 184),
    },
}

# ==========================================
# 해금형 특수 낚시터 (3종)
# ==========================================
SPECIAL_SPOTS: Dict[str, Dict[str, Any]] = {
    "glacier": {
        "id": "glacier",
        "name": "빙하 빙어호수",
        "short": "빙하 호수",
        "emoji": "🧊",
        "base_habitat": "lake",
        "req_level": 5,
        "req_pokedex": 20,
        "req_desc": "낚시 Lv.5 또는 도감 20종",
        "rare_mult": 1.35,
        "size_mult": 1.10,
        "variant_mult": 1.45,
        "treasure_bonus": 0.04,
        "discord_color": 0x67E8F9,
        "rgb": (56, 189, 248),
        "prefer_zones": ("깊은 심수층", "맑은 중층수"),
        "keywords": ("빙어", "송어", "연어", "철갑상어", "열목어", "공어", "심수"),
        "desc": "만년설 빙하 아래 투명한 냉수층! 희귀 ×1.35 · 변이 ×1.45 · 보물 발견율 +4%",
    },
    "coral_atoll": {
        "id": "coral_atoll",
        "name": "산호초 환초군도",
        "short": "산호 군도",
        "emoji": "🏝️",
        "base_habitat": "sea",
        "req_level": 10,
        "req_pokedex": 50,
        "req_desc": "낚시 Lv.10 또는 도감 50종",
        "rare_mult": 1.65,
        "size_mult": 1.15,
        "variant_mult": 1.80,
        "treasure_bonus": 0.07,
        "discord_color": 0x2DD4BF,
        "rgb": (20, 184, 166),
        "prefer_zones": ("산호초·열대 해역", "연안 갯바위·내만"),
        "keywords": ("돔", "나비", "산호", "놀래기", "바리", "복어", "만타", "거북"),
        "desc": "에메랄드빛 열대 산호초 군도! 희귀 ×1.65 · 변이 ×1.80 · 보물 발견율 +7%",
    },
    "mariana_trench": {
        "id": "mariana_trench",
        "name": "마리아나 심해 해구",
        "short": "마리아나 해구",
        "emoji": "🕳️",
        "base_habitat": "sea",
        "req_level": 18,
        "req_pokedex": 100,
        "req_desc": "낚시 Lv.18 또는 도감 100종",
        "rare_mult": 2.15,
        "size_mult": 1.24,
        "variant_mult": 2.40,
        "treasure_bonus": 0.10,
        "discord_color": 0x7C3AED,
        "rgb": (109, 40, 217),
        "prefer_zones": ("심해·해구", "원양·회유 해역"),
        "keywords": ("심해", "산갈치", "아귀", "실러캔스", "상어", "오징어", "참다랑어", "개복치"),
        "desc": "빛이 닿지 않는 전설의 심연! 희귀 ×2.15 · 변이 ×2.40 · 보물 발견율 +10%",
    },
}

# ==========================================
# 수족관 테마 & 먹이주기 상수
# ==========================================
TANK_THEMES: Dict[str, Dict[str, Any]] = {
    "coral": {
        "id": "coral",
        "name": "산호초 에메랄드 수조",
        "emoji": "🪸",
        "price": 0,
        "top_rgb": (10, 62, 86),
        "bot_rgb": (6, 26, 48),
        "accent_rgb": (45, 212, 191),
        "desc": "햇살이 비치는 에메랄드빛 기본 산호초 수족관 (무료 기본 제공)",
    },
    "deep_sea": {
        "id": "deep_sea",
        "name": "심해 아비스 네온 수조",
        "emoji": "🌌",
        "price": 6000,
        "top_rgb": (14, 16, 48),
        "bot_rgb": (5, 7, 24),
        "accent_rgb": (168, 85, 247),
        "desc": "신비로운 발광 플랑크톤과 네온 보랏빛이 감도는 심해 수조 (6,000🪙)",
    },
    "night_pond": {
        "id": "night_pond",
        "name": "달빛 연못 등불 수조",
        "emoji": "🌙",
        "price": 8000,
        "top_rgb": (24, 24, 62),
        "bot_rgb": (10, 18, 36),
        "accent_rgb": (250, 204, 21),
        "desc": "보름달과 황금빛 연등이 수면에 어른거리는 고요한 야경 연못 수조 (8,000🪙)",
    },
    "glacier": {
        "id": "glacier",
        "name": "빙하 오로라 수조",
        "emoji": "🧊",
        "price": 12000,
        "top_rgb": (12, 54, 74),
        "bot_rgb": (12, 24, 52),
        "accent_rgb": (103, 232, 249),
        "desc": "극지방의 오로라와 맑은 빙하 결정이 반짝이는 프리미엄 수조 (12,000🪙)",
    },
}

TANK_FEED_COST: int = 150
TANK_FEED_COOLDOWN_SEC: int = 2 * 3600
TANK_FEED_BUFF_SEC: int = 4 * 3600
TANK_FEED_BUFF_MULT: float = 1.35

# ==========================================
# 장비 강화 (+1 ~ +10) & 소형어 미끼 제작 공방
# ==========================================
ENHANCE_MAX_LEVEL: int = 10
ENHANCE_TABLE: List[Dict[str, Any]] = [
    {"target": 1, "cost": 400, "rate": 1.00},
    {"target": 2, "cost": 800, "rate": 0.95},
    {"target": 3, "cost": 1400, "rate": 0.90},
    {"target": 4, "cost": 2200, "rate": 0.82},
    {"target": 5, "cost": 3400, "rate": 0.75},
    {"target": 6, "cost": 5000, "rate": 0.65},
    {"target": 7, "cost": 7500, "rate": 0.55},
    {"target": 8, "cost": 11000, "rate": 0.45},
    {"target": 9, "cost": 16000, "rate": 0.38},
    {"target": 10, "cost": 24000, "rate": 0.30},
]

ENHANCE_SLOT_META: Dict[str, Dict[str, str]] = {
    "rod": {"name": "낚싯대", "emoji": "🎣", "effect": "단계당 희귀 +6% · 크기 +2% · 판매 +3%"},
    "reel": {"name": "릴", "emoji": "🌀", "effect": "단계당 입질유예 +0.25초 · 월척 +2.5%"},
    "net": {"name": "그물", "emoji": "🕸️", "effect": "단계당 그물희귀 +4% · 크기 +1.5% · 레이드 피해 +5%"},
}

BAIT_CRAFT_RECIPES: Dict[str, Dict[str, Any]] = {
    "live_minnow": {
        "id": "live_minnow",
        "name": "특제 생미끼 ×5 제작",
        "emoji": "🐟",
        "need_fish": 5,
        "max_rarity": 2,
        "yield_bait": "live_minnow",
        "yield_qty": 5,
        "desc": "미잠금 ★1~★2 소형어 5마리 분해 → 특제 생미끼 5개 (희귀 ×1.95 · 변이 ↑)",
    },
    "trophy_chum": {
        "id": "trophy_chum",
        "name": "대물 특제 집어제 ×3 제작",
        "emoji": "🍖",
        "need_fish": 12,
        "max_rarity": 2,
        "yield_bait": "trophy_chum",
        "yield_qty": 3,
        "desc": "미잠금 ★1~★2 소형어 12마리 분해 → 대물 특제 집어제 3개 (희귀 ×2.65 · 변이 대폭 ↑)",
    },
    "golden_extract": {
        "id": "golden_extract",
        "name": "황금 전설 떡밥 ×2 추출",
        "emoji": "✨",
        "need_fish": 25,
        "max_rarity": 2,
        "yield_bait": "golden",
        "yield_qty": 2,
        "desc": "미잠금 ★1~★2 소형어 25마리 농축 → 황금 전설 떡밥 2개 (희귀 ×3.20)",
    },
}

# ==========================================
# 돌발 보물상자 · 표류물 & 서버 협동 대어 보스 레이드
# ==========================================
DRIFT_LOOT_TABLE: List[Dict[str, Any]] = [
    {
        "id": "wooden_chest",
        "name": "낡은 해적 보물상자",
        "emoji": "📦",
        "weight": 38,
        "gold_range": (250, 650),
        "crystal_range": (0, 0),
        "bait": None,
        "flavor": "파도에 떠밀려온 나무 상자에서 반짝이는 금화를 건져 올렸습니다!",
    },
    {
        "id": "drift_bottle",
        "name": "표류하는 유리병 편지",
        "emoji": "🍾",
        "weight": 28,
        "gold_range": (80, 200),
        "crystal_range": (10, 25),
        "bait": ("lure", 4),
        "flavor": "누군가 남긴 항해 일지와 함께 고급 루어 미끼 묶음이 들어있었습니다!",
    },
    {
        "id": "pearl_clam",
        "name": "심해 흑진주 조개",
        "emoji": "🦪",
        "weight": 20,
        "gold_range": (180, 420),
        "crystal_range": (30, 75),
        "bait": None,
        "flavor": "조개 껍데기를 열자 영롱하게 빛나는 진주 크리스탈이 나타났습니다!",
    },
    {
        "id": "sunken_relic",
        "name": "고대 해저 유물함",
        "emoji": "🏺",
        "weight": 10,
        "gold_range": (900, 1800),
        "crystal_range": (45, 95),
        "bait": ("glow", 3),
        "flavor": "오랜 세월 바다 밑에 잠들어 있던 고대 문명의 보물함을 인양했습니다!",
    },
    {
        "id": "golden_chest",
        "name": "해적왕의 황금 보물상자",
        "emoji": "👑",
        "weight": 4,
        "gold_range": (2000, 4200),
        "crystal_range": (100, 180),
        "bait": ("golden", 2),
        "flavor": "전설 속 해적왕의 비밀 금고가 낚싯바늘에 걸려 올라왔습니다!!",
    },
]

BOSS_SPECIES_POOL: List[Dict[str, Any]] = [
    {
        "id": "kraken",
        "name": "심해의 크라켄",
        "emoji": "🐙",
        "max_hp": 3500,
        "duration_min": 45,
        "base_gold": 1200,
        "pool_gold": 4000,
        "base_crystals": 45,
        "pool_crystals": 120,
        "bait_id": "glow",
        "bait_qty": 4,
        "desc": "거대한 촉수로 어선을 휘감는 심해의 군주! 서버원들과 합동으로 릴을 당겨 제압하세요.",
    },
    {
        "id": "megalodon",
        "name": "태고의 메갈로돈",
        "emoji": "🦈",
        "max_hp": 4500,
        "duration_min": 45,
        "base_gold": 1500,
        "pool_gold": 5500,
        "base_crystals": 55,
        "pool_crystals": 160,
        "bait_id": "golden",
        "bait_qty": 2,
        "desc": "고대 대양을 지배하던 20m 초거대 백상아리! 강력한 장비 강화로 승부하세요.",
    },
    {
        "id": "leviathan",
        "name": "심연의 리바이어던",
        "emoji": "🐉",
        "max_hp": 6000,
        "duration_min": 60,
        "base_gold": 2000,
        "pool_gold": 8000,
        "base_crystals": 75,
        "pool_crystals": 240,
        "bait_id": "golden",
        "bait_qty": 3,
        "desc": "폭풍을 몰고 다니는 신화 속 바다 용! 처치 시 서버 최고급 보상이 지급됩니다.",
    },
    {
        "id": "golden_dragon_koi",
        "name": "천년 황금 용잉어",
        "emoji": "🐲",
        "max_hp": 3000,
        "duration_min": 40,
        "base_gold": 1300,
        "pool_gold": 4500,
        "base_crystals": 50,
        "pool_crystals": 150,
        "bait_id": "trophy_chum",
        "bait_qty": 4,
        "desc": "폭포를 거슬러 올라 용이 되기 직전의 신비한 황금 거대 잉어!",
    },
]

BOSS_ATTACK_COOLDOWN_SEC: float = 8.0
BOSS_SPAWN_COOLDOWN_SEC: int = 20 * 60
_BOSS_ATTACK_LAST: Dict[Tuple[int, int], float] = {}

DEFAULT_BAG_CAPACITY: int = 180
BAG_CAPACITY_TIERS: List[int] = [180, 300, 500, 1000, 2000]
BAG_UPGRADE_STEPS: Dict[int, Dict[str, Any]] = {
    180: {"next_cap": 300, "price": 35000, "tier_name": "고급 대용량 어망 가방", "emoji": "🎒"},
    300: {"next_cap": 500, "price": 95000, "tier_name": "원양 탐사 대용량 백팩", "emoji": "🧳"},
    500: {"next_cap": 1000, "price": 260000, "tier_name": "심해 어선 특수 냉장 수조함", "emoji": "🚢"},
    1000: {"next_cap": 2000, "price": 650000, "tier_name": "초대형 만선 크루즈 어창", "emoji": "🐳"},
}


def get_bag_capacity(u: Optional[Dict[str, Any]]) -> int:
    if not isinstance(u, dict):
        return DEFAULT_BAG_CAPACITY
    raw_cap = _safe_int(u.get("bag_capacity"), DEFAULT_BAG_CAPACITY)
    if raw_cap in BAG_CAPACITY_TIERS:
        return raw_cap
    valid = [t for t in BAG_CAPACITY_TIERS if t <= raw_cap]
    return max(valid) if valid else DEFAULT_BAG_CAPACITY


def get_next_bag_upgrade(u: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    cur = get_bag_capacity(u)
    step = BAG_UPGRADE_STEPS.get(cur)
    if not step:
        return None
    return {"cur_cap": cur, **step}


def get_variant_meta(variant_id: Optional[str]) -> Dict[str, Any]:
    return VARIANT_META.get(str(variant_id or "normal"), VARIANT_META["normal"])


def is_special_spot_unlocked(u: Optional[Dict[str, Any]], spot_id: str) -> bool:
    spot = SPECIAL_SPOTS.get(spot_id)
    if not spot or not isinstance(u, dict):
        return False
    lvl = max(1, _safe_int(u.get("level"), 1))
    pd = u.get("pokedex")
    pd_cnt = len(pd) if isinstance(pd, dict) else 0
    return lvl >= int(spot["req_level"]) or pd_cnt >= int(spot["req_pokedex"])


def get_unlocked_special_spots(u: Optional[Dict[str, Any]]) -> List[str]:
    return [sid for sid in SPECIAL_SPOTS if is_special_spot_unlocked(u, sid)]


def get_gear_enhance_levels(u: Optional[Dict[str, Any]]) -> Dict[str, int]:
    raw = u.get("gear_enhance") if isinstance(u, dict) else None
    if not isinstance(raw, dict):
        return {"rod": 0, "reel": 0, "net": 0}
    return {
        slot: max(0, min(ENHANCE_MAX_LEVEL, _safe_int(raw.get(slot), 0)))
        for slot in ("rod", "reel", "net")
    }


def get_gear_enhance_bonuses(u: Optional[Dict[str, Any]]) -> Dict[str, float]:
    lvls = get_gear_enhance_levels(u)
    has_net = bool(isinstance(u, dict) and u.get("net_id") in NETS)
    rod_lv = lvls["rod"]
    reel_lv = lvls["reel"]
    net_lv = lvls["net"] if has_net else 0
    return {
        "rod_lv": rod_lv,
        "reel_lv": reel_lv,
        "net_lv": lvls["net"],
        "rare_bonus": round(rod_lv * 0.06 + net_lv * 0.04, 4),
        "size_bonus": round(rod_lv * 0.02 + net_lv * 0.015, 4),
        "gold_bonus": round(rod_lv * 0.03, 4),
        "window_sec": round(reel_lv * 0.25, 2),
        "wait_reduce": round(reel_lv * 0.05, 2),
        "trophy_bonus": round(reel_lv * 0.025, 4),
        "boss_dmg_mult": round(1.0 + rod_lv * 0.08 + reel_lv * 0.04 + lvls["net"] * 0.05, 3),
    }


def get_gear_enhance_step(cur_level: int) -> Optional[Dict[str, Any]]:
    lv = max(0, int(cur_level or 0))
    if lv >= ENHANCE_MAX_LEVEL:
        return None
    return ENHANCE_TABLE[lv]


def is_tank_feed_buff_active(u: Optional[Dict[str, Any]], now_dt: Optional[datetime.datetime] = None) -> Tuple[bool, int]:
    """수족관 먹이주기 버프 활성 여부 및 남은 분(minutes) 반환"""
    if not isinstance(u, dict):
        return False, 0
    until_iso = u.get("tank_feed_buff_until")
    if not until_iso:
        return False, 0
    dt_now = now_dt or datetime.datetime.now(core.KST)
    try:
        until_dt = datetime.datetime.fromisoformat(str(until_iso))
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=core.KST)
        rem_sec = int((until_dt - dt_now).total_seconds())
        if rem_sec > 0:
            return True, max(1, (rem_sec + 59) // 60)
    except Exception:
        pass
    return False, 0



# ==========================================
# 세부 수역 (13개 표준 서식 구역) & 공개 어종 마스터 데이터베이스 (JSON 연동)
# ==========================================
CANONICAL_ZONES: Dict[str, List[str]] = {
    "lake": ["수초 연안", "맑은 중층수", "깊은 심수층", "열대·아열대 대호"],
    "river": ["상류 1급수 계곡", "중류 자갈 여울", "대하천 본류", "강·바다 기수역"],
    "sea": ["연안 갯바위·내만", "산호초·열대 해역", "대륙붕·외해", "원양·회유 해역", "심해·해구"],
}
def _sp(
    fid: str,
    name: str,
    sci: str,
    habitat: str,
    sub_zone: str,
    rarity: int,
    min_cm: float,
    max_cm: float,
    wa: float,
    wb: float,
    gold: int,
    atime: str = "all",
    pweather: str = "all",
    pbait: str = "dough",
    emoji: str = "🐟",
    desc: str = "",
) -> Dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "scientific_name": sci,
        "habitat": habitat,
        "sub_zone": sub_zone,
        "rarity": rarity,
        "min_cm": min_cm,
        "max_cm": max_cm,
        "weight_a": wa,
        "weight_b": wb,
        "base_gold": gold,
        "active_time": atime,
        "prefer_weather": pweather,
        "prefer_bait": pbait,
        "emoji": emoji,
        "desc": desc,
    }


_FALLBACK_ORIGINAL_140: List[Dict[str, Any]] = [
    # ------------------------------------------
    # 1. 🏞️ 호수 (46종)
    # ------------------------------------------
    _sp("lake_crucian", "토종붕어", "Carassius auratus", "lake", "수초 연안", 1, 12.0, 42.0, 0.018, 3.05, 45, "all", "clear", "dough", "🐟", "한국 저수지와 호수의 영원한 국민 어종. 월척(30.3cm+) 손맛이 일품."),
    _sp("lake_japanese_crucian", "떡붕어", "Carassius cuvieri", "lake", "중층 개방수역", 1, 15.0, 48.0, 0.020, 3.02, 50, "day", "clear", "dough", "🐟", "체고가 높고 납작하며 집단 회유하는 외래 정착 붕어."),
    _sp("lake_pale_chub", "피라미", "Zacco platypus", "lake", "얕은 호안", 1, 6.0, 16.0, 0.010, 3.02, 22, "day", "clear", "dough", "🐟", "맑은 호수 유입부에서 은빛으로 떼 지어 헤엄치는 소형 어류."),
    _sp("lake_topmouth", "참붕어", "Pseudorasbora parva", "lake", "수초 바닥층", 1, 5.0, 12.0, 0.011, 3.00, 18, "all", "all", "dough", "🐟", "입이 작고 튼튼해 전국 어느 호수나 저수지에서도 쉽게 만날 수 있다."),
    _sp("lake_bitterling", "각시붕어", "Rhodeus uyekii", "lake", "수초 틈새", 1, 4.0, 8.5, 0.014, 3.02, 26, "day", "clear", "dough", "🐠", "산란기 수컷의 무지개 혼인색이 한국 담수어 중 손꼽히게 아름다운 어종."),
    _sp("lake_rose_bitterling", "흰줄납줄개", "Rhodeus ocellatus", "lake", "완만한 호안", 1, 4.5, 9.0, 0.014, 3.00, 25, "day", "all", "dough", "🐠", "민물조개 안에 알을 낳아 키우는 독특한 습성을 지닌 예쁜 작은 물고기."),
    _sp("lake_sharpbelly", "치리", "Hemiculter eigenmanni", "lake", "호수 표층", 1, 10.0, 24.0, 0.008, 3.00, 30, "day", "clear", "dough", "🐟", "날렵한 유선형 체형으로 호수 표면을 빠르게 가로지른다."),
    _sp("lake_bluegill", "블루길", "Lepomis macrochirus", "lake", "선착장·수초", 1, 10.0, 28.0, 0.024, 3.05, 32, "day", "all", "worm", "🐟", "둥근 체형과 푸른 아가미 덮개가 특징인 왕성한 먹성의 호수 어종."),
    _sp("lake_medaka", "대륙송사리", "Oryzias sinensis", "lake", "잔잔한 수면", 1, 2.5, 4.8, 0.011, 2.95, 20, "day", "clear", "dough", "🐟", "눈이 크고 수면 바로 아래를 유영하는 자그마한 토종 송사리."),
    _sp("lake_paradise_fish", "버들붕어", "Macropodus ocellatus", "lake", "연꽃 습지", 1, 4.5, 9.5, 0.015, 3.00, 34, "day", "fog", "worm", "🐠", "공기 호흡이 가능한 라비린스 기관과 화려한 지느러미를 가진 담수 관상어."),
    _sp("lake_lizard_goby", "밀어", "Rhinogobius brunneus", "lake", "자갈 바닥층", 1, 5.0, 11.0, 0.012, 3.02, 24, "all", "all", "worm", "🐟", "배지느러미가 빨판처럼 변해 돌 표면에 딱 붙어 지내는 바닥 어류."),

    _sp("lake_smelt", "빙어", "Hypomesus nipponensis", "lake", "냉수 중층", 2, 7.0, 16.0, 0.007, 3.05, 65, "night", "clear", "dough", "🐟", "속이 비칠 만큼 투명하고 은은한 오이 향이 감도는 겨울 호수의 별미."),
    _sp("lake_carp", "잉어", "Cyprinus carpio", "lake", "호수 전역", 2, 28.0, 95.0, 0.019, 3.00, 95, "all", "rain", "dough", "🐟", "강인한 힘과 두 쌍의 수염을 자랑하는 동아시아 대표 대형 민물어."),
    _sp("lake_mirror_carp", "향어", "Cyprinus carpio nudus", "lake", "양어장·대형호", 2, 26.0, 82.0, 0.023, 3.00, 90, "day", "all", "dough", "🐟", "비늘이 거의 없고 체고가 두툼해 묵직한 손맛을 안겨주는 개량 잉어."),
    _sp("lake_largemouth_bass", "큰입배스", "Micropterus salmoides", "lake", "수몰나무·석축", 2, 20.0, 62.0, 0.016, 3.06, 85, "day", "clear", "lure", "🐟", "바늘털이 점프로 루어 낚시인들의 심장을 뛰게 만드는 담수 포식자."),
    _sp("lake_smallmouth_bass", "작은입배스", "Micropterus dolomieu", "lake", "암반 수역", 2, 18.0, 52.0, 0.017, 3.04, 88, "day", "rain", "lure", "🐟", "맑고 차가운 호수의 바위 지대를 선호하는 폭발적인 파이팅 능력자."),
    _sp("lake_yellow_catfish", "동자개 (빠가사리)", "Pseudobagrus fulvidraco", "lake", "진흙·자갈 바닥", 2, 12.0, 32.0, 0.014, 3.02, 75, "night", "rain", "worm", "🐡", "잡히면 '빠각빠각' 소리를 내며 가슴지느러미 가시를 세우는 노란 민물어."),
    _sp("lake_bullhead", "대농갱이", "Leiocassis ussuriensis", "lake", "깊은 호수 바닥", 2, 18.0, 55.0, 0.013, 3.02, 105, "night", "rain", "worm", "🐟", "동자개과 중 가장 크게 자라며 밤에 활발히 먹이 활동을 한다."),
    _sp("lake_catfish", "메기", "Silurus asotus", "lake", "어두운 수초·뻘", 2, 25.0, 80.0, 0.010, 3.02, 92, "night", "rain", "worm", "🐟", "긴 수염으로 진동을 감지하며 밤하늘 아래 묵직한 입질을 보여준다."),
    _sp("lake_swamp_eel", "드렁허리", "Monopterus albus", "lake", "진흙 호안", 2, 28.0, 78.0, 0.0022, 2.98, 98, "night", "rain", "worm", "🐍", "지느러미 없이 뱀처럼 길며 습한 밤에 호안 뻘을 누빈다."),
    _sp("lake_tilapia", "나일 틸라피아", "Oreochromis niloticus", "lake", "온수 호수", 2, 18.0, 54.0, 0.025, 3.00, 82, "day", "clear", "worm", "🐟", "입속에서 알을 부화시키는 구내부화 습성을 가진 강인한 어종."),
    _sp("lake_pond_smelt", "공어", "Hypomesus olidus", "lake", "한랭 호수", 2, 8.0, 18.0, 0.007, 3.04, 72, "night", "fog", "dough", "🐟", "북방계 찬물 호수에서 서식하는 빙어의 가까운 친척."),
    _sp("lake_lake_goby", "민물검정망둑", "Tridentiger brevispinis", "lake", "호수 암반 틈", 2, 5.5, 13.0, 0.013, 3.02, 62, "all", "all", "worm", "🐟", "작은 몸집에도 강한 영역 본능을 보이는 호수 바닥의 망둑어."),

    _sp("lake_snakehead", "가물치", "Channa argus", "lake", "밀집 연밭", 3, 40.0, 105.0, 0.012, 3.02, 210, "day", "fog", "lure", "🦈", "수초 사이로 치고 들어가는 파워와 수면 폭발 입질(탑워터)이 압권인 담수 제왕."),
    _sp("lake_koi", "비단잉어 (니시키고이)", "Cyprinus rubrofuscus", "lake", "맑은 정원호", 3, 30.0, 92.0, 0.019, 3.00, 240, "day", "clear", "dough", "🎏", "홍백·대정삼색 등 화려한 무늬를 뽐내며 유유히 헤엄치는 살아있는 보석."),
    _sp("lake_skygazer", "강준치", "Erythroculter erythropterus", "lake", "넓은 대호", 3, 32.0, 95.0, 0.009, 3.02, 195, "day", "clear", "lure", "🐟", "위로 솟은 입과 은빛 거체가 특징인 호수 루어 낚시의 고속 추격자."),
    _sp("lake_three_lips", "끄리", "Opsariichthys uncirostris", "lake", "호수 중·표층", 3, 20.0, 48.0, 0.011, 3.02, 185, "day", "clear", "lure", "🐟", "W자형으로 맞물린 턱을 가진 순수 토종 민물 육식어."),
    _sp("lake_steed_barbel", "누치", "Hemibarbus labeo", "lake", "자갈 호저", 3, 25.0, 62.0, 0.012, 3.02, 180, "all", "rain", "worm", "🐟", "단단한 체구와 힘찬 차고 나감으로 대물 낚시꾼을 긴장시키는 모래 바닥의 투사."),
    _sp("lake_barbel_chub", "눈불개", "Squaliobarbus curriculus", "lake", "큰 호수·댐", 3, 25.0, 60.0, 0.012, 3.02, 190, "day", "rain", "lure", "🐟", "붉은 눈 테두리가 강렬한 인상을 주는 대형 잉어과 어종."),
    _sp("lake_rainbow_trout", "무지개송어", "Oncorhynchus mykiss", "lake", "냉수 심수층", 3, 25.0, 78.0, 0.013, 3.02, 225, "day", "clear", "lure", "🌈", "옆구리에 영롱한 무지개빛 띠를 두른 화려한 고산 호수의 냉수어."),
    _sp("lake_brown_trout", "브라운송어", "Salmo trutta", "lake", "차가운 암반호", 3, 26.0, 85.0, 0.013, 3.02, 235, "night", "fog", "lure", "🐠", "검은 점과 붉은 반점이 조화를 이루며 경계심이 극도로 높은 영리한 송어."),
    _sp("lake_grass_carp", "초어", "Ctenopharyngodon idella", "lake", "수초 지대", 3, 45.0, 125.0, 0.014, 3.00, 230, "day", "clear", "dough", "🐟", "수초를 뜯어 먹으며 1미터가 훌쩍 넘게 자라는 초대형 담수어."),
    _sp("lake_silver_carp", "백련어", "Hypophthalmichthys molitrix", "lake", "대형 댐 표층", 3, 40.0, 115.0, 0.013, 3.02, 220, "all", "fog", "dough", "🐟", "놀라면 수면 위로 높게 뛰어오르는 성질을 가진 은백색의 거구."),
    _sp("lake_bighead_carp", "대두어", "Hypophthalmichthys nobilis", "lake", "대형 호수 중층", 3, 45.0, 130.0, 0.015, 3.02, 245, "all", "rain", "dough", "🐟", "커다란 머리와 묵직한 체중을 자랑하는 플랑크톤 여과 섭식 거대어."),
    _sp("lake_lake_trout", "호수송어 (레이크 트라우트)", "Salvelinus namaycush", "lake", "빙하 심수층", 3, 38.0, 118.0, 0.013, 3.04, 260, "all", "fog", "glow", "🐟", "수십 미터 깊은 차가운 호수 바닥에서만 살아가는 장수 냉수성 거인."),
    _sp("lake_walleye", "왈아이", "Sander vitreus", "lake", "밤안개 암반 호수", 3, 30.0, 82.0, 0.013, 3.02, 250, "night", "fog", "lure", "🐟", "어둠 속에서 유리구슬처럼 빛나는 눈으로 밤새 사냥하는 북방 대호의 인기 대상어."),

    _sp("lake_northern_pike", "노던 파이크", "Esox lucius", "lake", "북방 수초대", 4, 50.0, 135.0, 0.0085, 3.04, 620, "day", "fog", "lure", "🐊", "악어를 닮은 납작한 주둥이와 면도날 같은 이빨로 순간 가속하는 물의 늑대."),
    _sp("lake_muskellunge", "머스켈런지 (머스키)", "Esox masquinongy", "lake", "거대 북미 호수", 4, 70.0, 155.0, 0.0088, 3.05, 760, "day", "storm", "lure", "🐊", "'만 번 캐스팅해야 한 번 잡힌다'는 별명을 가진 전설의 대형 파이크."),
    _sp("lake_nile_perch", "나일농어", "Lates niloticus", "lake", "아프리카 대호", 4, 65.0, 185.0, 0.015, 3.02, 820, "night", "clear", "shrimp", "👑", "거대한 호수 생태계의 최정점에 서 있는 압도적인 크기의 열대 농어."),
    _sp("lake_baikal_omul", "바이칼 오물", "Coregonus migratorius", "lake", "바이칼 심수호", 4, 30.0, 62.0, 0.011, 3.02, 580, "night", "fog", "glow", "❄️", "지구에서 가장 깊고 맑은 바이칼 호수에만 서식하는 신비로운 고유 연어과 어종."),
    _sp("lake_beluga_sturgeon", "벨루가 철갑상어", "Huso huso", "lake", "카스피 심연", 4, 110.0, 320.0, 0.0082, 3.02, 920, "all", "storm", "shrimp", "🦈", "수억 년 전 공룡 시대의 갑옷 비늘을 그대로 간직한 현존 최대급 담수·기수 거인."),
    _sp("lake_siberian_sturgeon", "시베리아 철갑상어", "Acipenser baerii", "lake", "한랭 대호 바닥", 4, 65.0, 180.0, 0.0075, 3.02, 680, "night", "rain", "worm", "🦈", "오각형 몸단면과 뾰족한 주둥이로 바닥을 더듬는 살아있는 화석."),
    _sp("lake_peacock_bass", "피콕 배스", "Cichla ocellaris", "lake", "열대 인공호", 4, 35.0, 88.0, 0.018, 3.04, 650, "day", "clear", "lure", "🦚", "공작의 깃털을 닮은 황금·에메랄드 빛깔과 맹렬한 공격성을 지닌 트로피 어종."),

    _sp("lake_arapaima", "피라루쿠", "Arapaima gigas", "lake", "아마존 범람호", 5, 130.0, 290.0, 0.011, 3.00, 2100, "day", "rain", "golden", "🐉", "폐 호흡을 하며 물 밖으로 고개를 내미는 세계 최대급 담수 괴어. 붉은 비늘이 위엄을 뽐낸다."),
    _sp("lake_silver_arowana", "실버 아로와나", "Osteoglossum bicirrhosum", "lake", "고목 수몰호", 5, 55.0, 115.0, 0.0065, 3.02, 1650, "night", "fog", "golden", "🐉", "물 밖 곤충까지 뛰어올라 낚아채는 '물의 요정' 용어(龍魚)."),
    _sp("lake_asian_arowana", "황금 용어 (아시아 아로와나)", "Scleropages formosus", "lake", "비경의 호수", 5, 45.0, 95.0, 0.0085, 3.04, 2400, "all", "storm", "golden", "👑", "찬란한 순금빛 비늘과 두 개의 턱 수염이 행운과 신화를 부른다는 전설의 어류."),

    # ------------------------------------------
    # 2. 🌊 강 (46종)
    # ------------------------------------------
    _sp("river_dark_chub", "갈겨니", "Nipponocypris temminckii", "river", "상·중류 여울", 1, 7.0, 18.0, 0.010, 3.02, 24, "day", "clear", "dough", "🐟", "눈을 가로지르는 검은 띠가 매력적인 1~2급수 맑은 하천의 단골 손님."),
    _sp("river_minnow", "버들치", "Rhynchocypris oxycephalus", "river", "계곡 소용돌이", 1, 6.0, 15.0, 0.010, 3.02, 26, "all", "clear", "worm", "🐟", "차갑고 산소가 풍부한 산간 계곡 최상류에서 만날 수 있는 지표종."),
    _sp("river_sand_gudgeon", "모래무지", "Pseudogobio esocinus", "river", "모래 여울 바닥", 1, 10.0, 24.0, 0.009, 3.02, 32, "day", "clear", "worm", "🐟", "위험을 느끼면 고운 모래 속으로 몸을 파고들어 눈만 내놓는 귀여운 강물고기."),
    _sp("river_striped_shiner", "돌고기", "Pungtungia herzi", "river", "돌 틈 여울", 1, 7.0, 15.0, 0.011, 3.02, 25, "day", "all", "dough", "🐟", "주둥이부터 꼬리까지 뻗은 굵은 검은 줄이 인상적인 맑은 강물고기."),
    _sp("river_korean_steed", "참마자", "Hemibarbus longirostris", "river", "자갈·모래 여울", 1, 10.0, 22.0, 0.010, 3.02, 28, "day", "clear", "worm", "🐟", "긴 주둥이와 알록달록한 옆줄 점무늬를 가진 유유자적한 바닥 어종."),
    _sp("river_pond_loach", "미꾸리", "Misgurnus anguillicaudatus", "river", "하천 샛강·수로", 1, 9.0, 20.0, 0.0052, 3.02, 29, "night", "rain", "worm", "🐟", "비 오는 날 논둑길과 샛강에서 유난히 활발해지는 친근한 어종."),
    _sp("river_weather_loach", "미꾸라지", "Misgurnus mizolepis", "river", "유속 완만 수로", 1, 11.0, 24.0, 0.0055, 3.02, 31, "night", "rain", "worm", "🐟", "미꾸리보다 크고 체고가 높으며 장마철 하천의 기압 변화를 가장 먼저 감지한다."),
    _sp("river_spined_loach", "기름종개", "Cobitis hankugensis", "river", "자갈 하천 바닥", 1, 6.0, 13.0, 0.0050, 3.00, 34, "all", "clear", "worm", "🐟", "매끈한 몸과 화려한 얼룩무늬가 예쁜 한국 고유 바닥 소형어."),
    _sp("river_torrent_catfish", "밀자개", "Liobagrus mediadiposalis", "river", "자갈 여울 아래", 1, 6.5, 14.0, 0.011, 3.02, 36, "night", "rain", "worm", "🐟", "큰 돌 밑에 몸을 숨기고 밤에 나와 수서곤충을 사냥하는 한국 특산 작은 메기."),
    _sp("river_sleeper_goby", "동사리", "Odontobutis platycephala", "river", "하천 바위 틈", 1, 8.0, 20.0, 0.015, 3.02, 35, "night", "all", "worm", "🐟", "넙적한 머리로 돌 틈에 매복하다 지나가는 작은 물고기를 덮치는 토종 사냥꾼."),
    _sp("river_gudgeon_shrimp", "민물 징거미새우", "Macrobrachium nipponense", "river", "하천 수초·석축", 1, 5.0, 12.0, 0.016, 2.98, 28, "night", "clear", "worm", "🦐", "밤이 되면 긴 앞집게를 뻗어 미끼를 슬그머니 채가는 담수 새우."),

    _sp("river_sweetfish", "은어", "Plecoglossus altivelis", "river", "1급수 여울", 2, 13.0, 30.0, 0.010, 3.02, 82, "day", "clear", "dough", "🐟", "이끼만 먹고 살아 수박향이 나는 맑은 강의 대표 별미. 영역 다툼이 치열하다."),
    _sp("river_shiri", "쉬리", "Coreoleuciscus splendidus", "river", "급류 자갈 여울", 2, 8.0, 17.0, 0.010, 3.02, 78, "day", "clear", "worm", "🐠", "푸른빛과 주황빛이 어우러진 맑은 물의 상징, 자랑스런 한반도 고유종."),
    _sp("river_mandarin_perch", "꺽지", "Coreoperca herzi", "river", "산간 암반 여울", 2, 10.0, 24.0, 0.019, 3.02, 86, "day", "clear", "lure", "🐟", "아가미 뒤 선명한 파란 점과 화려한 세로줄이 멋진 계곡 루어의 정석."),
    _sp("river_kawamebari", "꺽저기", "Coreoperca kawamebari", "river", "남부 맑은 하천", 2, 8.0, 16.0, 0.018, 3.02, 90, "day", "fog", "lure", "🐟", "전남·서남해 하천 수초 지대에 국한되어 서식하는 귀한 토종 농어목 어종."),
    _sp("river_kumgang_minnow", "금강모치", "Rhynchocypris kumgangensis", "river", "최상류 1급수", 2, 6.5, 13.0, 0.010, 3.02, 85, "day", "clear", "worm", "🐟", "금강산 계곡에서 최초 발견된, 얼음처럼 차가운 물만 고집하는 청정 특산어."),
    _sp("river_black_shiner", "감돌고기", "Pseudopungtungia nigra", "river", "바위·여울 깊은곳", 2, 7.0, 14.0, 0.011, 3.02, 95, "day", "clear", "worm", "🐠", "선명한 노랑과 검정 띠를 두른 금강·만경강의 귀한 멸종위기 토종어."),
    _sp("river_kkuguri", "꾸구리", "Gobiobotia macrocephala", "river", "여울 자갈 바닥", 2, 7.0, 13.0, 0.010, 3.00, 92, "night", "clear", "worm", "🐟", "빛에 따라 동공 크기가 고양이 눈처럼 변하는 신기한 고유 담수어."),
    _sp("river_dolsangeo", "돌상어", "Gobiobotia brevibarba", "river", "거센 자갈 급류", 2, 6.5, 12.5, 0.010, 3.00, 94, "night", "rain", "worm", "🐟", "이름은 상어지만 한강·임진강 급류 바닥에서 사는 작고 용감한 고유종."),
    _sp("river_white_gudgeon", "흰수마자", "Gobiobotia naktongensis", "river", "고운 모래 여울", 2, 5.5, 11.0, 0.009, 3.00, 96, "day", "clear", "worm", "🐟", "하얀 수염 4쌍을 뽐내며 모래 밭을 지키는 우리나라 1급 보호 고유종."),
    _sp("river_eoreumchi", "어름치", "Hemibarbus mylodon", "river", "맑은 여울과 소", 2, 18.0, 44.0, 0.012, 3.02, 108, "day", "clear", "worm", "🐟", "산란 후 자갈을 물어 탑(산란탑)을 쌓는 모성애가 남다른 천연기념물급 명어."),
    _sp("river_miyugi", "미유기 (산메기)", "Silurus microdorsalis", "river", "계곡 깊은 소", 2, 14.0, 35.0, 0.009, 3.02, 88, "night", "rain", "worm", "🐟", "청정 계곡에서만 살며 살이 연하고 고소해 '깔딱메기'로 불리는 귀한 산메기."),
    _sp("river_duwoojaengi", "두우쟁이", "Saurogobio dabryi", "river", "대하천 모래바닥", 2, 12.0, 26.0, 0.0085, 3.00, 74, "all", "all", "worm", "🐟", "투명하게 빛나는 연한 호박색 체형을 지닌 넓은 강 하류 바닥 어종."),

    _sp("river_cherry_salmon", "산천어", "Oncorhynchus masou masou", "river", "냉수 계곡 소", 3, 18.0, 42.0, 0.012, 3.02, 215, "day", "clear", "lure", "🌈", "몸통의 보랏빛 파마크 무늬가 너무도 우아한 '계곡의 여왕'."),
    _sp("river_lenok", "열목어", "Brachymystax lenok", "river", "고산 냉수 심수소", 3, 25.0, 68.0, 0.012, 3.02, 245, "all", "fog", "lure", "🐠", "빙하기 때 내려와 한반도 심산 계곡에 남은 붉은 배의 살아있는 천연기념물."),
    _sp("river_masou_salmon", "시마연어 (송어)", "Oncorhynchus masou", "river", "하천~동해 회유", 3, 35.0, 72.0, 0.013, 3.02, 230, "all", "rain", "lure", "🐟", "바다로 내려갔다가 산란기에 은백색 거체로 모천을 거슬러 오르는 산천어의 모체."),
    _sp("river_chum_salmon", "연어", "Oncorhynchus keta", "river", "하구·본류 소상", 3, 50.0, 95.0, 0.013, 3.02, 240, "all", "rain", "shrimp", "🐟", "수만 km 북태평양을 돌고 자신이 태어난 강 냄새를 기억해 돌아오는 기적의 어종."),
    _sp("river_eel", "민물 장어 (뱀장어)", "Anguilla japonica", "river", "바위 틈·하류", 3, 38.0, 105.0, 0.0018, 3.04, 255, "night", "rain", "worm", "🐍", "머나먼 마리아나 해구 심해에서 태어나 강까지 헤엄쳐 온 신비한 스태미나 대명사."),
    _sp("river_mandarin_fish", "쏘가리", "Siniperca scherzeri", "river", "강 암반·급류 소", 3, 22.0, 58.0, 0.016, 3.04, 265, "night", "fog", "lure", "🐯", "호랑이 무늬와 민물 최고의 육질을 자랑해 '민물의 표범'으로 불리는 한국 최고 인기 어종."),
    _sp("river_estuary_anchovy", "웅어 (위어)", "Coilia nasus", "river", "기수역 갈대밭", 3, 20.0, 42.0, 0.0055, 3.00, 200, "day", "clear", "shrimp", "🐟", "칼날처럼 길고 날렵한 몸으로 서해 큰 강 하구 기수역을 회유하는 임금님 진상 어종."),
    _sp("river_mullet", "가숭어 (참숭어)", "Chelon haematocheilus", "river", "하구 기수역", 3, 28.0, 68.0, 0.014, 3.00, 195, "day", "clear", "dough", "🐟", "노란 눈테가 선명하며 물 위로 통통 뛰어오르는 힘찬 기수역 어종."),
    _sp("river_striped_mullet", "숭어", "Mugil cephalus", "river", "강 하구·연안", 3, 28.0, 72.0, 0.014, 3.00, 190, "day", "all", "dough", "🐟", "강과 바다를 자유로이 오가며 역동적인 입질과 달리기 실력을 보여주는 회유어."),
    _sp("river_river_puffer", "황복", "Takifugu obscurus", "river", "대하천 기수역", 3, 20.0, 45.0, 0.028, 3.00, 270, "day", "rain", "shrimp", "🐡", "봄마다 바다에서 임진강·한강으로 거슬러 오르는 황금빛 무늬의 최고급 회귀 복어."),
    _sp("river_spotted_seabass", "점농어", "Lateolabrax maculatus", "river", "하구·하류 보", 3, 35.0, 95.0, 0.012, 3.02, 240, "night", "rain", "lure", "🐟", "몸 측면에 선명한 검은 점이 찍혀 있으며 하구까지 깊이 거슬러 올라와 사냥한다."),
    _sp("river_korean_stumpy_catfish", "꼬치동자개", "Pseudobagrus brevicorpus", "river", "낙동강 맑은 여울", 3, 7.0, 15.0, 0.013, 3.02, 220, "night", "clear", "worm", "🐟", "한반도 낙동강 수계에만 서식하는 매우 희소하고 귀여운 천연기념물."),
    _sp("river_booboo_catfish", "퉁가리", "Liobagrus andersoni", "river", "상류 급류 바위", 3, 8.0, 18.0, 0.011, 3.02, 210, "night", "rain", "worm", "🐟", "한강·금강 최상류 급류에서 날카로운 가시로 자신을 지키는 고유종."),

    _sp("river_golden_mandarin", "황쏘가리", "Siniperca scherzeri (Golden)", "river", "비경 깊은 여울", 4, 28.0, 65.0, 0.016, 3.04, 780, "night", "fog", "lure", "👑", "온몸이 찬란한 황금빛으로 변이해 천연기념물 제190호로 지정된 영물."),
    _sp("river_giant_mottled_eel", "무태장어", "Anguilla marmorata", "river", "제주 천지연·남부강", 4, 70.0, 195.0, 0.0022, 3.05, 740, "night", "storm", "shrimp", "🐍", "아열대 해역과 남부 하천 깊은 소에 서식하는 거대 얼룩무늬 장어."),
    _sp("river_longsnout_catfish", "종어", "Leiocassis longirostris", "river", "금강·대하천 심층", 4, 40.0, 95.0, 0.011, 3.02, 720, "night", "rain", "worm", "👑", "예로부터 어종 중 으뜸이라 불려 '종어(宗魚)'라 칭송받은 전설적인 한국 하천의 귀족."),
    _sp("river_king_salmon", "킹살몬 (왕연어)", "Oncorhynchus tshawytscha", "river", "북방 대하천 급류", 4, 70.0, 145.0, 0.014, 3.02, 800, "all", "rain", "lure", "👑", "모든 연어 중 가장 거대하고 힘이 장사인 북태평양 대하천의 패왕."),
    _sp("river_lamprey", "칠성장어 (다묵장어)", "Lethenteron japonicum", "river", "모래 진흙 계류", 4, 15.0, 48.0, 0.0018, 2.98, 560, "night", "fog", "glow", "🪱", "턱이 없는 원시 어류의 모습을 5억 년간 간직해 온 신비로운 어류."),
    _sp("river_atlantic_salmon", "대서양 연어", "Salmo salar", "river", "북대서양 대하천", 4, 60.0, 130.0, 0.012, 3.02, 710, "day", "clear", "lure", "🐟", "여러 번 강과 바다를 왕복하며 산란하는 우아한 은빛 도약가."),
    _sp("river_redtail_catfish", "레드테일 캣피쉬", "Phractocephalus hemioliopterus", "river", "열대 대하천 심층", 4, 65.0, 165.0, 0.016, 3.02, 840, "night", "storm", "shrimp", "🐠", "선홍빛 꼬리지느러미가 인상적이며 거친 여울 밑바닥을 지배하는 초대형 메기."),

    _sp("river_paddlefish", "주걱철갑상어 (패들피쉬)", "Polyodon spathula", "river", "거대 본류 유역", 5, 100.0, 220.0, 0.0082, 3.00, 1850, "all", "fog", "golden", "🔱", "전기 감각으로 가득 찬 거대한 주걱 모양 주둥이를 지닌 고대 강물의 생존자."),
    _sp("river_alligator_gar", "엘리게이터 가아", "Atractosteus spatula", "river", "고대 유역 깊은물", 5, 115.0, 275.0, 0.0068, 3.04, 2150, "day", "storm", "golden", "🐊", "다이아몬드처럼 단단한 에나멜 갑옷 비늘과 악어 이빨을 지닌 거대한 살아있는 화석."),
    _sp("river_goliath_tigerfish", "골리앗 타이거피쉬", "Hydrocynus goliath", "river", "콩고 급류 협곡", 5, 85.0, 180.0, 0.014, 3.04, 2500, "day", "storm", "golden", "🦈", "거대한 송곳니와 폭발적인 근육으로 격류 속에서 사냥하는 민물 최강의 몬스터."),

    # ------------------------------------------
    # 3. ⚓ 바다 (48종)
    # ------------------------------------------
    _sp("sea_anchovy", "멸치", "Engraulis japonicus", "sea", "연안 표층", 1, 8.0, 16.0, 0.007, 3.02, 20, "day", "clear", "dough", "🐟", "거대한 은빛 떼를 지어 바다 생태계의 든든한 기반을 이루는 소형 회유어."),
    _sp("sea_sardine", "정어리", "Sardinops melanostictus", "sea", "연안~외해 표층", 1, 13.0, 26.0, 0.009, 3.02, 26, "day", "clear", "dough", "🐟", "둥근 몸통 옆면에 7~10개의 푸른 점이 나란히 찍힌 등푸른 물고기."),
    _sp("sea_horse_mackerel", "전갱이 (아지)", "Trachurus japonicus", "sea", "방파제 야간 집어", 1, 15.0, 38.0, 0.011, 3.02, 42, "night", "all", "shrimp", "🐟", "꼬리 쪽 단단한 모비늘과 밤새 불빛 아래를 맴도는 특유의 입질이 매력적인 어종."),
    _sp("sea_mackerel", "고등어", "Scomber japonicus", "sea", "연안·외해 표층", 1, 22.0, 48.0, 0.011, 3.02, 46, "day", "all", "shrimp", "🐟", "등의 물결무늬가 선명하며 좌우로 내달리는 스피드가 일품인 국민 생선."),
    _sp("sea_saury", "꽁치", "Cololabis saira", "sea", "동해 표층", 1, 20.0, 38.0, 0.0045, 3.04, 38, "night", "clear", "dough", "🐟", "은빛 칼날처럼 쭉 뻗은 체형과 집어등 불빛을 따라 몰려드는 가을의 진객."),
    _sp("sea_halfbeak", "학꽁치", "Hyporhamphus sajori", "sea", "잔잔한 연안 표층", 1, 18.0, 38.0, 0.0042, 3.02, 40, "day", "clear", "dough", "🐟", "긴 아래턱과 투명한 속살, 맑은 수면 바로 아래를 미끄러지듯 유영한다."),
    _sp("sea_whiting", "보리멸", "Sillago japonica", "sea", "모래 해변 바닥", 1, 12.0, 28.0, 0.0085, 3.02, 36, "day", "clear", "worm", "🐟", "백사장 원투 낚시에서 반짝이며 올라오는 하얀 모래의 공주."),
    _sp("sea_yellowfin_goby", "풀망둑", "Acanthogobius hasta", "sea", "갯벌·선착장 바닥", 1, 15.0, 42.0, 0.011, 3.00, 34, "all", "all", "worm", "🐟", "가을~겨울에 부쩍 살이 오르는 망둑어 중 가장 크게 자라는 어종."),
    _sp("sea_spotty_greenling", "노래미", "Hexagrammos agrammus", "sea", "해조류 암초대", 1, 14.0, 32.0, 0.014, 3.02, 39, "day", "all", "worm", "🐟", "바위틈에 숨어 갯지렁이를 노리는 친숙한 연안 갯바위 터줏대감."),
    _sp("sea_webfoot_octopus", "주꾸미", "Amphioctopus fangsiao", "sea", "서해 얕은 모래", 1, 12.0, 28.0, 0.014, 2.98, 48, "day", "clear", "lure", "🐙", "다리 밑에 둥근 황금빛 고리 무늬가 반짝이는 가을 선상 에깅의 주인공."),
    _sp("sea_surfperch", "망상어", "Ditrema temminckii", "sea", "방파제 테트라포드", 1, 14.0, 30.0, 0.018, 3.00, 35, "day", "all", "shrimp", "🐟", "알이 아닌 새끼를 직접 낳는 신기한 태생 연안어."),

    _sp("sea_rockfish_inermis", "볼락", "Sebastes inermis", "sea", "방파제 암초 야간", 2, 15.0, 32.0, 0.018, 3.02, 84, "night", "clear", "shrimp", "🐟", "큰 눈으로 야간에 먹이를 쫓으며 릴을 차고 내려가는 손맛이 중독적인 갯바위의 왕자."),
    _sp("sea_korean_rockfish", "조피볼락 (우럭)", "Sebastes schlegelii", "sea", "어초·암초 바닥", 2, 22.0, 58.0, 0.020, 3.02, 92, "all", "all", "shrimp", "🐟", "한국 바다 배낚시의 상징! 묵직하게 처박는 힘과 쫄깃한 식감 모두 최고."),
    _sp("sea_fat_greenling", "쥐노래미", "Hexagrammos otakii", "sea", "북방 암초·방파제", 2, 22.0, 52.0, 0.014, 3.02, 86, "day", "rain", "worm", "🐟", "노래미보다 훨씬 크고 힘이 좋아 추운 계절에도 연안에서 짜릿한 손맛을 준다."),
    _sp("sea_marbled_rockfish", "쏨뱅이", "Sebastiscus marmoratus", "sea", "테트라포드 바닥", 2, 14.0, 32.0, 0.020, 3.02, 78, "night", "all", "shrimp", "🐠", "붉은 얼룩 위장색으로 구멍 사이에 숨어 지내는 작지만 매운 낚시 대상어."),
    _sp("sea_spanish_mackerel", "삼치", "Scomberomorus niphonius", "sea", "외해·연안 표층", 2, 42.0, 108.0, 0.0085, 3.02, 118, "day", "clear", "lure", "🐟", "날카로운 이빨과 시속 60km의 폭발적 질주로 루어를 덮치는 가을바다의 어뢰."),
    _sp("sea_herring", "청어", "Clupea pallasii", "sea", "동해 냉수 표층", 2, 20.0, 38.0, 0.010, 3.02, 74, "night", "fog", "dough", "🐟", "짙은 쪽빛 등을 지녔으며 차가운 바다를 거대한 무리로 누빈다."),
    _sp("sea_yellow_croaker", "참조기", "Larimichthys polyactis", "sea", "서해 뻘·사질 바닥", 2, 18.0, 38.0, 0.014, 3.00, 110, "all", "fog", "shrimp", "🐟", "머리 속 딱딱한 이석과 황금빛 배, 예로부터 귀하게 여겨진 굴비의 원어."),
    _sp("sea_flathead", "양태 (장대)", "Platycephalus indicus", "sea", "모래 바닥 매복", 2, 26.0, 68.0, 0.009, 3.02, 95, "day", "clear", "lure", "🐟", "도마뱀처럼 납작한 머리로 모래 속에 몸을 감추고 기습하는 바닥 사냥꾼."),
    _sp("sea_black_scraper", "말쥐치", "Thamnaconus modestus", "sea", "중층 어초 주변", 2, 18.0, 40.0, 0.022, 3.00, 88, "day", "clear", "shrimp", "🐟", "작은 입으로 미끼만 쏙 빼먹는 '미끼 도둑'이지만 담백한 맛은 일품이다."),
    _sp("sea_cuttlefish", "갑오징어", "Sepia esculenta", "sea", "서해·남해 모래바닥", 2, 15.0, 36.0, 0.032, 2.95, 102, "day", "clear", "lure", "🦑", "몸속에 단단한 흰 뼈(갑)를 품고 묵직하게 끌려오는 묵직한 에깅 인기 어종."),
    _sp("sea_octopus", "참문어", "Octopus vulgaris", "sea", "남해 암반·자갈", 2, 30.0, 95.0, 0.026, 2.85, 115, "all", "all", "lure", "🐙", "높은 지능과 바위를 붙드는 괴력! 바닥에서 묵직한 돌처럼 버티다 올라온다."),
    _sp("sea_bigfin_squid", "무늬오징어 (아오리)", "Sepioteuthis lessoniana", "sea", "남해·제주 맑은연안", 2, 20.0, 55.0, 0.018, 2.95, 120, "night", "clear", "lure", "🦑", "연안 에깅 최고의 인기 스타! 제트 분사로 째는 역동적인 손맛을 선사한다."),

    _sp("sea_olive_flounder", "넙치 (광어)", "Paralichthys olivaceus", "sea", "모래·해저 암반 경계", 3, 35.0, 95.0, 0.013, 3.02, 225, "all", "all", "lure", "🐟", "두 눈이 왼쪽으로 몰린 매복의 귀재! 모래밭 위로 묵직하게 눕는 대물의 손맛."),
    _sp("sea_marbled_flounder", "문치가자미 (도다리)", "Pseudopleuronectes yokohamae", "sea", "연안 모래바닥", 3, 20.0, 48.0, 0.015, 3.00, 195, "day", "clear", "worm", "🐟", "오른쪽으로 두 눈이 쏠린 '봄 도다리'의 주인공."),
    _sp("sea_black_seabream", "감성돔", "Acanthopagrus schlegelii", "sea", "갯바위 여밭·조류", 3, 25.0, 62.0, 0.022, 3.02, 275, "all", "rain", "shrimp", "🐟", "'바다 찌낚시의 꽃'이자 5짜(50cm+)가 꿈의 기록으로 불리는 영리한 은빛 투사."),
    _sp("sea_red_seabream", "참돔", "Pagrus major", "sea", "깊은 여·조류 소통구", 3, 30.0, 95.0, 0.021, 3.00, 290, "day", "clear", "shrimp", "🐠", "선명한 분홍빛 자태와 푸른 반점이 영롱한 '바다의 여왕', 축하의 생선."),
    _sp("sea_striped_beakperch", "돌돔", "Oplegnathus fasciatus", "sea", "거친 본류 갯바위", 3, 24.0, 68.0, 0.025, 3.00, 310, "day", "rain", "shrimp", "🐟", "성게 껍질도 부수는 강력한 부리와 폭발적인 3단 처박기로 유명한 '갯바위의 제왕'."),
    _sp("sea_largescale_blackfish", "벵에돔", "Girella punctata", "sea", "외해 섬 포말 지대", 3, 22.0, 55.0, 0.021, 3.02, 260, "day", "clear", "shrimp", "🐟", "제주와 남해 외해 포말 속에서 날카롭고 순간적인 찌 빨림으로 손맛을 전한다."),
    _sp("sea_yellowtail", "방어", "Seriola quinqueradiata", "sea", "난류 조경 수역", 3, 45.0, 115.0, 0.013, 3.02, 285, "day", "rain", "lure", "🐟", "겨울철 찬 바다에서 기름이 올라 지칠 줄 모르는 체력으로 드랙을 터뜨리는 대형 회유어."),
    _sp("sea_amberjack", "부시리 (히라스)", "Seriola lalandi", "sea", "원도권 본류대", 3, 55.0, 155.0, 0.012, 3.02, 330, "day", "storm", "lure", "🦈", "방어보다 훨씬 날렵하고 갯바위·어초 밑으로 파고드는 괴력이 상상을 초월한다."),
    _sp("sea_hairtail", "갈치", "Trichiurus lepturus", "sea", "야간 심층~중층", 3, 60.0, 155.0, 0.0009, 3.00, 240, "night", "clear", "shrimp", "⚔️", "달빛 아래 거울처럼 반짝이는 '은빛 칼', 바다 위를 수직으로 유영하는 명품 어종."),
    _sp("sea_monkfish", "아귀", "Lophiomus setigerus", "sea", "심해 진흙 바닥", 3, 35.0, 105.0, 0.024, 2.98, 250, "night", "fog", "glow", "🐡", "머리의 발광 돌기로 물고기를 유혹하는 못생겼지만 깊은 맛이 일품인 심해 바닥의 복병."),
    _sp("sea_pacific_cod", "대구", "Gadus macrocephalus", "sea", "한류 심해 바닥", 3, 45.0, 110.0, 0.013, 3.02, 255, "all", "fog", "lure", "🐟", "커다란 입과 턱수염으로 찬 바다 밑바닥을 지키는 겨울 지깅의 대표 어종."),
    _sp("sea_seabass", "농어", "Lateolabrax japonicus", "sea", "갯바위 여울·포말", 3, 40.0, 102.0, 0.012, 3.02, 260, "night", "storm", "lure", "🐟", "거친 파도와 너울 속에서 바늘털이 점프로 낚시꾼과 기싸움을 벌이는 은빛 사냥꾼."),
    _sp("sea_brown_croaker", "민어", "Miichthys miiuy", "sea", "서남해 깊은 뻘·골", 3, 45.0, 115.0, 0.013, 3.02, 295, "night", "rain", "shrimp", "🐟", "부레에서 '꾸욱꾸욱' 북소리를 내며 여름철 최고의 보양식으로 손꼽히는 명어."),

    _sp("sea_longtooth_grouper", "다금바리 (자바리)", "Epinephelus bruneus", "sea", "제주 깊은 암반 굴", 4, 48.0, 130.0, 0.019, 3.02, 850, "night", "storm", "shrimp", "👑", "제주 바다 암초 깊은 굴 속에 숨어 사는 '바다의 전설'이자 귀하신 몸."),
    _sp("sea_convict_grouper", "능성어", "Hyporthodus septemfasciatus", "sea", "심해 인공어초", 4, 45.0, 138.0, 0.020, 3.02, 780, "night", "fog", "glow", "🐠", "7개의 짙은 세로줄과 어마어마한 괴력을 지닌 대형 바리과 어종."),
    _sp("sea_red_spotted_grouper", "붉바리", "Epinephelus akaara", "sea", "남해·제주 맑은암초", 4, 28.0, 62.0, 0.021, 3.00, 740, "day", "clear", "shrimp", "🐠", "주홍빛 몸통에 붉은 점이 총총 박혀 '바다의 보석'으로 불리는 최고급 바리류."),
    _sp("sea_striped_jewfish", "돗돔", "Stereolepis doederleini", "sea", "수심 400m 심해 암초", 4, 90.0, 210.0, 0.019, 3.02, 980, "all", "storm", "glow", "🐳", "전설 속에나 등장한다는 '용왕의 물고기'! 수십 kg의 육중한 전설어."),
    _sp("sea_mahi_mahi", "만새기 (마히마히)", "Coryphaena hippurus", "sea", "원양 유목 주변", 4, 65.0, 175.0, 0.0095, 3.02, 720, "day", "clear", "lure", "🌈", "빛나는 에메랄드와 황금빛으로 수면 위를 공중 회전하는 트롤링의 슈퍼스타."),
    _sp("sea_ocean_sunfish", "개복치", "Mola mola", "sea", "외해 표층~심층", 4, 90.0, 260.0, 0.048, 2.95, 860, "day", "clear", "glow", "🐡", "꼬리지느러미 없이 거대한 둥근 몸으로 일광욕을 즐기는 신비로운 바다의 순둥이."),
    _sp("sea_yellowfin_tuna", "황다랑어", "Thunnus albacares", "sea", "열대·아열대 원양", 4, 85.0, 205.0, 0.018, 3.00, 900, "day", "clear", "lure", "🐟", "긴 노란 지느러미가 멋지며 릴의 라인을 끝없이 끌고 나가는 빅게임의 주인공."),

    _sp("sea_bluefin_tuna", "태평양 참다랑어", "Thunnus orientalis", "sea", "대한해협·원양 심층", 5, 120.0, 300.0, 0.020, 3.00, 2200, "all", "storm", "golden", "👑", "초속 20m의 질주와 수백 kg의 위용! '바다의 검은 다이아몬드'로 불리는 궁극의 참치."),
    _sp("sea_blue_marlin", "청새치", "Makaira mazara", "sea", "태평양 푸른 외해", 5, 160.0, 380.0, 0.0085, 3.02, 2350, "day", "clear", "golden", "⚔️", "거대한 창 같은 주둥이를 휘두르며 바다 위를 수십 미터 도약하는 해양 최상위 포식자."),
    _sp("sea_oarfish", "대왕산갈치", "Regalecus glesne", "sea", "심해 1,000m 미지 영역", 5, 240.0, 680.0, 0.00055, 2.95, 2600, "night", "fog", "golden", "🐉", "붉은 갈기 지느러미와 수 미터 은백색 리본 몸체로 인어·용왕 사신 전설의 모델이 된 심해의 신비."),
    _sp("sea_manta_ray", "쥐가오리 (만타 레이)", "Mobula birostris", "sea", "푸른 심해 외해", 5, 180.0, 480.0, 0.018, 2.85, 2450, "day", "fog", "golden", "🦅", "거대한 날개를 펼치고 바다 속을 우아하게 비행하는 해양의 온순한 수호신."),
    _sp("sea_coelacanth", "실러캔스", "Latimeria chalumnae", "sea", "심해 화산 해저 동굴", 5, 110.0, 195.0, 0.018, 3.02, 3000, "night", "storm", "golden", "💠", "4억 년 전 데본기부터 모습을 바꾸지 않고 심해 동굴에 살아온 기적의 태고 신화어."),
]


def _normalize_fish_entry(sp: Dict[str, Any]) -> Dict[str, Any]:
    hab = sp.get("habitat", "lake")
    if hab not in HABITATS:
        hab = "lake"
    valid_zones = CANONICAL_ZONES[hab]
    zone = sp.get("zone") or ""
    if zone not in valid_zones:
        sz = str(sp.get("sub_zone") or "")
        if hab == "lake":
            if any(k in sz for k in ("심", "바이칼", "카스피", "냉수", "빙하", "깊은")):
                zone = "깊은 심수층"
            elif any(k in sz for k in ("아마존", "아프리카", "열대", "고목")):
                zone = "열대·아열대 대호"
            elif any(k in sz for k in ("중층", "표층", "개방", "대호", "대형")):
                zone = "맑은 중층수"
            else:
                zone = "수초 연안"
        elif hab == "river":
            if any(k in sz for k in ("상류", "계곡", "산간", "1급수", "고산", "최상류")):
                zone = "상류 1급수 계곡"
            elif any(k in sz for k in ("기수", "하구", "연안")):
                zone = "강·바다 기수역"
            elif any(k in sz for k in ("본류", "대하천", "고대", "협곡", "열대")):
                zone = "대하천 본류"
            else:
                zone = "중류 자갈 여울"
        else:
            if any(k in sz for k in ("심해", "해구", "화산", "400m", "1,000m")):
                zone = "심해·해구"
            elif any(k in sz for k in ("산호", "열대", "제주")):
                zone = "산호초·열대 해역"
            elif any(k in sz for k in ("원양", "대한해협", "태평양")):
                zone = "원양·회유 해역"
            elif any(k in sz for k in ("외해", "본류대", "조경", "동해")):
                zone = "대륙붕·외해"
            else:
                zone = "연안 갯바위·내만"

    out = dict(sp)
    out["id"] = str(sp.get("id", "")).strip()
    out["name"] = str(sp.get("name", "")).strip() or "미확인 어종"
    out["scientific_name"] = str(sp.get("scientific_name") or "").strip()
    out["habitat"] = hab
    out["zone"] = zone
    out["sub_zone"] = sp.get("sub_zone") or zone
    out["rarity"] = max(1, min(5, int(sp.get("rarity", 1))))
    out["min_cm"] = float(sp.get("min_cm", 10.0))
    out["max_cm"] = max(out["min_cm"] + 1.0, float(sp.get("max_cm", 30.0)))
    out["weight_a"] = float(sp.get("weight_a", 0.012))
    out["weight_b"] = float(sp.get("weight_b", 3.0))
    out["base_gold"] = int(sp.get("base_gold", 40))
    out["active_time"] = sp.get("active_time", "all") if sp.get("active_time") in ("day", "night", "all") else "all"
    out["prefer_weather"] = sp.get("prefer_weather", "all")
    out["prefer_bait"] = sp.get("prefer_bait", "dough") if sp.get("prefer_bait") in BAITS else "dough"
    out["emoji"] = sp.get("emoji") or "🐟"
    out["desc"] = sp.get("desc") or ""
    return out


def _dedup_species(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_ids = set()
    out: List[Dict[str, Any]] = []
    for sp in items:
        fid = sp.get("id")
        if not fid or fid in seen_ids:
            continue
        seen_ids.add(fid)
        out.append(sp)
    return out


def _load_fish_species_db() -> Tuple[List[Dict[str, Any]], str]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "fish_species_db.json"),
        os.path.join(base_dir, "public", "data", "fish_species_db.json"),
        os.path.join(base_dir, "public", "bot_files", "fish_species_db.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list) and len(raw) >= 140:
                    normalized = _dedup_species([
                        _normalize_fish_entry(sp)
                        for sp in raw
                        if isinstance(sp, dict) and sp.get("id") and sp.get("name")
                    ])
                    if len(normalized) >= 140:
                        rel_name = os.path.basename(path)
                        print(f"✅ [fishing_core] 글로벌 어종 DB 로드 완료: {len(normalized):,}종 ({rel_name})", flush=True)
                        return normalized, f"json:{rel_name}"
            except Exception as e:
                print(f"⚠️ [fishing_core] JSON 어종 DB 로드 실패({path}): {e}", flush=True)
    fallback = _dedup_species([_normalize_fish_entry(sp) for sp in _FALLBACK_ORIGINAL_140])
    print(
        f"🚨 [fishing_core] fish_species_db.json을 찾지 못해 기본 {len(fallback)}종 폴백으로 동작합니다! "
        f"(확인 경로: {base_dir}/fish_species_db.json)",
        flush=True,
    )
    return fallback, "fallback_140"


FISH_SPECIES_DB, FISH_DB_SOURCE = _load_fish_species_db()

FISH_BY_ID: Dict[str, Dict[str, Any]] = {f["id"]: f for f in FISH_SPECIES_DB}
FISH_BY_HABITAT: Dict[str, List[Dict[str, Any]]] = {
    h: [f for f in FISH_SPECIES_DB if f["habitat"] == h]
    for h in ("lake", "river", "sea")
}
FISH_BY_ZONE: Dict[Tuple[str, str], List[Dict[str, Any]]] = {
    (h, z): [f for f in FISH_BY_HABITAT[h] if f["zone"] == z]
    for h in ("lake", "river", "sea")
    for z in CANONICAL_ZONES[h]
}
FISH_BY_HABITAT_RARITY: Dict[Tuple[str, int], List[Dict[str, Any]]] = {
    (h, r): [f for f in FISH_BY_HABITAT[h] if f["rarity"] == r]
    for h in ("lake", "river", "sea")
    for r in range(1, 6)
}


def _has_hangul_fast(s: str) -> bool:
    for ch in s:
        if "\uac00" <= ch <= "\ud7a3":
            return True
    return False


# 자동완성·가중치 추첨용 고속 인메모리 인덱스 (10,000+종 < 2ms 검색)
_SEARCH_INDEX: List[Tuple[str, int, int, str, str, str, str, str, str, Dict[str, Any]]] = sorted(
    [
        (
            sp["id"],
            0 if (not sp["id"].startswith("sp_")) else (1 if _has_hangul_fast(sp["name"]) else 2),
            -int(sp["rarity"]),
            sp["name"],
            sp["name"].lower(),
            sp.get("scientific_name", "").lower(),
            (sp.get("zone") or sp.get("sub_zone") or "").lower(),
            HABITATS.get(sp["habitat"], HABITATS["lake"])["name"].lower(),
            sp.get("desc", "").lower(),
            sp,
        )
        for sp in FISH_SPECIES_DB
    ],
    key=lambda row: (row[1], row[2], row[3]),
)
_DEFAULT_AUTOCOMPLETE_SPECIES: List[Dict[str, Any]] = [row[9] for row in _SEARCH_INDEX[:25]]
_IS_HANGUL_SP_CACHE: Dict[str, bool] = {
    sp["id"]: _has_hangul_fast(sp["name"])
    for sp in FISH_SPECIES_DB
}


# ==========================================
# 일일 의뢰 템플릿
# ==========================================
DAILY_QUEST_POOL: List[Dict[str, Any]] = [
    {"id": "q_catch_5", "title": "🎣 기본 손맛 다지기 (물고기 5마리 낚기)", "type": "catch_total", "target": 5, "gold": 400, "crystals": 40},
    {"id": "q_catch_12", "title": "🌊 열혈 출조사 (물고기 12마리 낚기)", "type": "catch_total", "target": 12, "gold": 950, "crystals": 80},
    {"id": "q_lake_3", "title": "🏞️ 호수 탐험 (호수 어종 3마리 포획)", "type": "catch_lake", "target": 3, "gold": 450, "crystals": 40},
    {"id": "q_river_3", "title": "🌊 강물 여울 조사 (강 어종 3마리 포획)", "type": "catch_river", "target": 3, "gold": 450, "crystals": 40},
    {"id": "q_sea_3", "title": "⚓ 망망대해 항해 (바다 어종 3마리 포획)", "type": "catch_sea", "target": 3, "gold": 500, "crystals": 45},
    {"id": "q_rare_2", "title": "🔵 희귀 어종 사냥 (★3 이상 물고기 2마리)", "type": "catch_rare3", "target": 2, "gold": 800, "crystals": 75},
    {"id": "q_trophy_1", "title": "👑 대물 월척 사냥 (월척 1마리 낚기)", "type": "catch_trophy", "target": 1, "gold": 900, "crystals": 90},
    {"id": "q_sell_500", "title": "💰 어시장 거래왕 (물고기 판매로 500🪙 이상 벌기)", "type": "sell_gold", "target": 500, "gold": 550, "crystals": 50},
]


# ==========================================
# KST 시간대 & 2시간 주기 날씨 환경 엔진
# ==========================================
def get_current_fishing_env(now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    now_dt = now or datetime.datetime.now(core.KST)
    hour = now_dt.hour
    is_day = 6 <= hour < 18
    time_phase = "day" if is_day else "night"

    if hour in (5, 6, 7, 17, 18, 19):
        feeding_time = True
        feeding_label = "✨ 황금 피딩타임 (여명/황혼 · 입질·희귀 보너스 +20%)"
        feeding_mult = 1.20
    else:
        feeding_time = False
        feeding_label = "일반 물때"
        feeding_mult = 1.00

    if 6 <= hour < 11:
        time_label = "🌅 아침/오전 (낮)"
    elif 11 <= hour < 17:
        time_label = "☀️ 한낮 (낮)"
    elif 17 <= hour < 20:
        time_label = "🌇 해질녘 (피딩)"
    elif 20 <= hour < 24:
        time_label = "🌙 초저녁/밤 (밤)"
    else:
        time_label = "🌌 깊은 심야 (밤)"

    slot_idx = hour // 2
    next_slot_hour = (slot_idx + 1) * 2
    next_dt = now_dt.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(hours=next_slot_hour)
    rem_sec = max(60, int((next_dt - now_dt).total_seconds()))
    rem_h, rem_m = divmod(rem_sec // 60, 60)
    remain_str = f"{rem_h}시간 {rem_m}분" if rem_h > 0 else f"{rem_m}분"

    seed_str = f"{now_dt.strftime('%Y-%m-%d')}-slot-{slot_idx}"
    digest = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:8], 16)
    roll = digest % 100
    if roll < 46:
        weather_id = "clear"
    elif roll < 74:
        weather_id = "rain"
    elif roll < 90:
        weather_id = "fog"
    else:
        weather_id = "storm"

    w_meta = WEATHERS[weather_id]
    return {
        "now": now_dt,
        "hour": hour,
        "time_phase": time_phase,
        "time_label": time_label,
        "feeding_time": feeding_time,
        "feeding_label": feeding_label,
        "feeding_mult": feeding_mult,
        "weather_id": weather_id,
        "weather_name": w_meta["name"],
        "weather_emoji": w_meta["emoji"],
        "weather_desc": w_meta["desc"],
        "weather_rare_mult": w_meta["rare_mult"],
        "weather_size_mult": w_meta["size_mult"],
        "slot_idx": slot_idx,
        "remain_str": remain_str,
    }


# ==========================================
# 실시간 어시장 시세 변동 & 오늘의 특가 매입 엔진 (3시간 KST 주기)
# ==========================================
def get_current_fish_market(now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """3시간 KST 주기로 결정론적 실시간 어시장 시세(서식지/성급 배율 + 오늘의 특가 3종)를 산출합니다."""
    now_dt = now or datetime.datetime.now(core.KST)
    slot_idx = now_dt.hour // 3
    next_slot_hour = (slot_idx + 1) * 3
    next_dt = now_dt.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(hours=next_slot_hour)
    rem_sec = max(60, int((next_dt - now_dt).total_seconds()))
    rem_h, rem_m = divmod(rem_sec // 60, 60)
    remain_str = f"{rem_h}시간 {rem_m}분" if rem_h > 0 else f"{rem_m}분"

    seed_str = f"norosi-fish-market-{now_dt.strftime('%Y-%m-%d')}-slot-{slot_idx}"
    seed_int = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed_int)

    habs = ["lake", "river", "sea"]
    rng.shuffle(habs)
    surge_hab, steady_hab, dip_hab = habs[0], habs[1], habs[2]
    habitat_mults: Dict[str, float] = {
        surge_hab: round(rng.uniform(1.25, 1.45), 2),
        steady_hab: round(rng.uniform(1.02, 1.14), 2),
        dip_hab: round(rng.uniform(0.90, 0.98), 2),
    }

    boosted_rarity = rng.choice([1, 2, 3, 4])
    boosted_rarity_mult = round(rng.uniform(1.18, 1.35), 2)
    rarity_mults: Dict[int, float] = {
        r: (boosted_rarity_mult if r == boosted_rarity else 1.00)
        for r in range(1, 6)
    }

    featured_species: Dict[str, Dict[str, Any]] = {}
    for h_id in ("lake", "river", "sea"):
        cands = [
            sp for sp in _FALLBACK_ORIGINAL_140
            if sp.get("habitat") == h_id and 1 <= int(sp.get("rarity", 1)) <= 4
        ]
        if not cands:
            cands = FISH_BY_HABITAT.get(h_id) or FISH_SPECIES_DB[:10]
        chosen = rng.choice(cands)
        feat_mult = round(rng.uniform(1.80, 2.05), 2)
        featured_species[chosen["id"]] = {
            "id": chosen["id"],
            "name": chosen["name"],
            "emoji": chosen.get("emoji", "🐟"),
            "habitat": h_id,
            "rarity": int(chosen.get("rarity", 1)),
            "mult": feat_mult,
        }

    surge_name = HABITATS[surge_hab]["name"]
    surge_pct = int(round((habitat_mults[surge_hab] - 1.0) * 100))
    rm_name = RARITY_META[boosted_rarity]["stars"]
    headline = f"🔥 {surge_name} 어종 +{surge_pct}% 급등 · {rm_name} 매입강세 · 오늘의 특가 최대 ×2.05!"

    return {
        "slot_idx": slot_idx,
        "remain_str": remain_str,
        "surge_habitat": surge_hab,
        "habitat_mults": habitat_mults,
        "boosted_rarity": boosted_rarity,
        "rarity_mults": rarity_mults,
        "featured_species": featured_species,
        "headline": headline,
        "updated_label": f"{slot_idx * 3:02d}:00 ~ {min(24, (slot_idx + 1) * 3):02d}:00 KST",
    }


def compute_market_sell_price(
    fish_item: Dict[str, Any],
    market: Optional[Dict[str, Any]] = None,
) -> Tuple[int, float, List[str]]:
    """물고기 개체의 실시간 어시장 매입가(원가 × 서식지/성급/특가 배율)를 계산합니다."""
    base_gold = max(10, _safe_int(fish_item.get("gold"), 15))
    mk = market or get_current_fish_market()
    fid = str(fish_item.get("fish_id") or "")
    hab = str(fish_item.get("habitat") or "lake")
    rar = max(1, min(5, _safe_int(fish_item.get("rarity"), 1)))

    tags: List[str] = []
    feat = (mk.get("featured_species") or {}).get(fid)
    hab_mult = float((mk.get("habitat_mults") or {}).get(hab, 1.0))
    rar_mult = float((mk.get("rarity_mults") or {}).get(rar, 1.0))

    if isinstance(feat, dict):
        feat_mult = float(feat.get("mult", 1.85))
        total_mult = min(2.50, round(max(feat_mult, hab_mult * rar_mult), 2))
        tags.append(f"🔥오늘의특가 ×{total_mult:.2f}")
    else:
        total_mult = round(hab_mult * rar_mult, 2)
        if hab_mult >= 1.15:
            tags.append(f"📈{HABITATS.get(hab, HABITATS['lake'])['name']}강세")
        elif hab_mult < 0.99:
            tags.append("📉약보합")
        if rar_mult > 1.05:
            tags.append(f"⭐★{rar}수요↑")

    final_gold = max(10, int(round(base_gold * total_mult)))
    return final_gold, total_mult, tags


# ==========================================
# 유저 & 기록 데이터 구조 초기화/보장
# ==========================================
def _pick_daily_quests_for_date(date_str: str) -> List[Dict[str, Any]]:
    seed = int(hashlib.md5(f"norosi-fish-quest-{date_str}".encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    chosen = rng.sample(DAILY_QUEST_POOL, 3)
    return [
        {
            "id": q["id"],
            "title": q["title"],
            "type": q["type"],
            "target": q["target"],
            "progress": 0,
            "gold": q["gold"],
            "crystals": q["crystals"],
            "claimed": False,
        }
        for q in chosen
    ]


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or isinstance(val, bool):
            return int(val) if isinstance(val, bool) else default
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or isinstance(val, bool):
            return float(default)
        return float(val)
    except (TypeError, ValueError):
        return default


def ensure_fishing_user(data: dict, guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    g_map = core.ensure_dict_path(data, "fishing_users", g_key)

    u = g_map.get(u_key)
    if not isinstance(u, dict):
        u = {}
        g_map[u_key] = u

    if user_name:
        u["name"] = user_name
    elif not u.get("name"):
        u["name"] = f"낚시꾼({u_key[:4]})"

    u["gold"] = max(0, _safe_int(u.get("gold"), 300))  # 신규 출조자 초기 정착 지원금
    u["exp"] = max(0, _safe_int(u.get("exp"), 0))
    u["level"] = max(1, _safe_int(u.get("level"), 1))
    u["total_catches"] = max(0, _safe_int(u.get("total_catches"), 0))
    u["total_trophy"] = max(0, _safe_int(u.get("total_trophy"), 0))
    u["total_gold_earned"] = max(0, _safe_int(u.get("total_gold_earned"), 0))
    u["combo"] = max(0, min(20, _safe_int(u.get("combo"), 0)))
    u["max_combo"] = max(u["combo"], _safe_int(u.get("max_combo"), 0))
    u["treasures_found"] = max(0, _safe_int(u.get("treasures_found"), 0))
    u["boss_defeats"] = max(0, _safe_int(u.get("boss_defeats"), 0))
    u["duel_wins"] = max(0, _safe_int(u.get("duel_wins"), 0))
    u["duel_losses"] = max(0, _safe_int(u.get("duel_losses"), 0))
    u["gifts_sent"] = max(0, _safe_int(u.get("gifts_sent"), 0))
    u["gifts_received"] = max(0, _safe_int(u.get("gifts_received"), 0))

    u.setdefault("rod_id", "bamboo")
    u.setdefault("reel_id", "basic_reel")
    u.setdefault("net_id", None)
    if not isinstance(u.get("owned_rods"), list):
        rods = [str(r) for r in core.coerce_list_like(u.get("owned_rods")) if r]
        u["owned_rods"] = rods if rods else ["bamboo"]
    if not isinstance(u.get("owned_reels"), list):
        reels = [str(r) for r in core.coerce_list_like(u.get("owned_reels")) if r]
        u["owned_reels"] = reels if reels else ["basic_reel"]
    if not isinstance(u.get("owned_nets"), list):
        nets = [str(n) for n in core.coerce_list_like(u.get("owned_nets")) if n and str(n) in NETS]
        u["owned_nets"] = list(dict.fromkeys(nets))
    else:
        u["owned_nets"] = list(dict.fromkeys(str(n) for n in u["owned_nets"] if n and str(n) in NETS))

    # 장비 강화 (+0 ~ +10) & 실패 천장 보정
    raw_enh = u.get("gear_enhance")
    if not isinstance(raw_enh, dict):
        raw_enh = {}
    u["gear_enhance"] = {
        slot: max(0, min(ENHANCE_MAX_LEVEL, _safe_int(raw_enh.get(slot), 0)))
        for slot in ("rod", "reel", "net")
    }
    raw_pity = u.get("enhance_pity")
    if not isinstance(raw_pity, dict):
        raw_pity = {}
    u["enhance_pity"] = {
        slot: max(0, min(10, _safe_int(raw_pity.get(slot), 0)))
        for slot in ("rod", "reel", "net")
    }

    u.setdefault("selected_bait", "dough")
    u.setdefault("selected_habitat", "lake")
    u.setdefault("selected_zone", "all")
    if u.get("selected_spot") not in SPECIAL_SPOTS:
        u["selected_spot"] = None
    u["auto_mode"] = bool(u.get("auto_mode", False))

    # 수족관 테마 & 먹이주기
    if not isinstance(u.get("owned_tank_themes"), list):
        themes = [str(t) for t in core.coerce_list_like(u.get("owned_tank_themes")) if str(t) in TANK_THEMES]
        u["owned_tank_themes"] = list(dict.fromkeys(["coral"] + themes))
    else:
        cleaned_t = [str(t) for t in u["owned_tank_themes"] if str(t) in TANK_THEMES]
        u["owned_tank_themes"] = list(dict.fromkeys(["coral"] + cleaned_t))
    if u.get("tank_theme") not in TANK_THEMES or u.get("tank_theme") not in u["owned_tank_themes"]:
        u["tank_theme"] = "coral"
    u.setdefault("last_tank_feed", None)
    u.setdefault("tank_feed_buff_until", None)

    if not isinstance(u.get("baits"), dict):
        coerced_baits = core.coerce_dict_like(u.get("baits"))
        u["baits"] = coerced_baits if coerced_baits else {"worm": 5}
    u["bag"] = [
        x for x in core.coerce_list_like(u.get("bag"))
        if isinstance(x, dict) and x.get("uid") and x.get("name")
    ]
    if not isinstance(u.get("pokedex"), dict):
        u["pokedex"] = {str(k): v for k, v in core.coerce_dict_like(u.get("pokedex")).items() if isinstance(v, dict)}
    u["tank"] = [
        x for x in core.coerce_list_like(u.get("tank"))
        if isinstance(x, dict) and x.get("uid") and x.get("name")
    ]
    u["tank_slots"] = max(4, min(20, _safe_int(u.get("tank_slots"), 4)))
    u["bag_capacity"] = get_bag_capacity(u)
    if not u.get("last_tank_collect"):
        u["last_tank_collect"] = datetime.datetime.now(core.KST).isoformat()

    today_str = core.get_today_str()
    dq = u.get("daily_quests")
    if not isinstance(dq, dict) or dq.get("date") != today_str:
        u["daily_quests"] = {
            "date": today_str,
            "items": _pick_daily_quests_for_date(today_str),
        }
    else:
        valid_q = []
        for q in core.coerce_list_like(dq.get("items")):
            if isinstance(q, dict) and q.get("type"):
                q["target"] = max(1, _safe_int(q.get("target"), 1))
                q["progress"] = max(0, _safe_int(q.get("progress"), 0))
                valid_q.append(q)
        dq["items"] = valid_q if valid_q else _pick_daily_quests_for_date(today_str)

    # 유효성 가드
    if u.get("rod_id") not in RODS:
        u["rod_id"] = "bamboo"
    if u.get("reel_id") not in REELS:
        u["reel_id"] = "basic_reel"
    if u.get("net_id") not in NETS or u.get("net_id") not in u["owned_nets"]:
        u["net_id"] = None
    if u.get("selected_bait") not in BAITS:
        u["selected_bait"] = "dough"
    if u.get("selected_habitat") not in HABITATS:
        u["selected_habitat"] = "lake"
    if u.get("selected_zone") != "all" and u.get("selected_zone") not in CANONICAL_ZONES.get(u["selected_habitat"], []):
        u["selected_zone"] = "all"
    if u.get("selected_spot") and not is_special_spot_unlocked(u, u["selected_spot"]):
        u["selected_spot"] = None
    if "bamboo" not in u["owned_rods"]:
        u["owned_rods"].append("bamboo")
    if "basic_reel" not in u["owned_reels"]:
        u["owned_reels"].append("basic_reel")

    return u


def _calc_level_from_exp(exp: int) -> Tuple[int, int, int]:
    """누적 EXP로 (레벨, 현재레벨 EXP, 다음레벨 필요 EXP) 계산"""
    lvl = 1
    rem = max(0, int(exp))
    while True:
        need = 100 + (lvl - 1) * 45
        if rem < need or lvl >= 99:
            return lvl, rem, need
        rem -= need
        lvl += 1


def _compute_fish_weight_kg(sp: Dict[str, Any], length_cm: float) -> float:
    jitter = random.uniform(0.92, 1.09)
    raw_g = sp["weight_a"] * (length_cm ** sp["weight_b"]) * jitter
    w_kg = max(0.002, raw_g / 1000.0)
    if w_kg < 0.2:
        return round(w_kg, 3)
    return round(w_kg, 2)


def get_tank_pending_gold(u: Dict[str, Any], now: Optional[datetime.datetime] = None) -> Tuple[int, int]:
    """수족관 누적 골드와 시간당 수익 반환 (변이 보너스 + 먹이주기 +35% 버프 반영, 최대 24시간 누적)"""
    raw_tank = u.get("tank", [])
    tank = [item for item in raw_tank if isinstance(item, dict)] if isinstance(raw_tank, list) else []
    if not tank:
        return 0, 0
    now_dt = now or datetime.datetime.now(core.KST)
    last_iso = u.get("last_tank_collect")
    try:
        last_dt = datetime.datetime.fromisoformat(last_iso) if last_iso else now_dt
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=core.KST)
    except Exception:
        last_dt = now_dt
    elapsed_min = max(0, int((now_dt - last_dt).total_seconds() // 60))
    capped_min = min(elapsed_min, 24 * 60)

    hourly_rate = 0
    for item in tank:
        r = int(item.get("rarity", 1))
        base_r = RARITY_META.get(r, RARITY_META[1])["tank_rate"]
        if item.get("is_trophy"):
            base_r = int(base_r * 1.35)
        v_meta = get_variant_meta(item.get("variant"))
        if v_meta["tank_mult"] > 1.0:
            base_r = int(base_r * v_meta["tank_mult"])
        hourly_rate += base_r

    feed_active, _ = is_tank_feed_buff_active(u, now_dt)
    if feed_active:
        hourly_rate = int(round(hourly_rate * TANK_FEED_BUFF_MULT))

    pending = int((hourly_rate / 60.0) * capped_min)
    return pending, hourly_rate


# ==========================================
# 출조 준비 · 입질 대상 결정 · 포획 확정 엔진
# ==========================================
def get_user_fishing_summary(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    with _FISHING_LOCK:
        data = core.load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        had_u = isinstance(core.safe_get_dict(data, "fishing_users", g_key).get(u_key), dict)
        had_prof = isinstance(core.safe_get_dict(data, "user_profiles").get(u_key), dict)
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)
        env = get_current_fishing_env()
        market = get_current_fish_market(env["now"])
        pending_tank, hourly_tank = get_tank_pending_gold(u, env["now"])
        feed_active, feed_rem_min = is_tank_feed_buff_active(u, env["now"])
        lvl, rem_exp, need_exp = _calc_level_from_exp(u.get("exp", 0))
        prev_lvl = u.get("level")
        u["level"] = lvl
        life_buffs = {}
        try:
            import life_core
            life_buffs = life_core.get_active_life_buffs(guild_id, user_id, data=data)
        except Exception:
            life_buffs = {}
        if not had_u or not had_prof or prev_lvl != lvl:
            core.save_data(data)
        return {
            "user": copy.deepcopy(u),
            "crystals": max(0, _safe_int(prof.get("crystals"), 0)),
            "env": env,
            "market": market,
            "rod": RODS[u["rod_id"]],
            "reel": REELS[u["reel_id"]],
            "net": NETS.get(u.get("net_id")),
            "bait": BAITS[u["selected_bait"]],
            "enhance": get_gear_enhance_bonuses(u),
            "selected_spot": SPECIAL_SPOTS.get(u.get("selected_spot") or ""),
            "unlocked_spots": get_unlocked_special_spots(u),
            "bag_capacity": get_bag_capacity(u),
            "tank_pending": pending_tank,
            "tank_hourly": hourly_tank,
            "tank_theme": TANK_THEMES.get(u.get("tank_theme", "coral"), TANK_THEMES["coral"]),
            "tank_feed_active": feed_active,
            "tank_feed_rem_min": feed_rem_min,
            "rem_exp": rem_exp,
            "need_exp": need_exp,
            "life_buffs": life_buffs,
        }


def update_user_fishing_prefs(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
    habitat: Optional[str] = None,
    bait_id: Optional[str] = None,
    auto_mode: Optional[bool] = None,
    zone_filter: Optional[str] = None,
    spot_id: Optional[str] = None,
) -> Dict[str, Any]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        if spot_id is not None:
            if spot_id == "" or spot_id == "none":
                u["selected_spot"] = None
            elif spot_id in SPECIAL_SPOTS and is_special_spot_unlocked(u, spot_id):
                u["selected_spot"] = spot_id
                u["selected_habitat"] = SPECIAL_SPOTS[spot_id]["base_habitat"]
                u["selected_zone"] = "all"
        if habitat and habitat in HABITATS:
            if u.get("selected_habitat") != habitat and zone_filter is None:
                u["selected_zone"] = "all"
            u["selected_habitat"] = habitat
            if spot_id is None:
                u["selected_spot"] = None
        if zone_filter is not None:
            if zone_filter == "all" or zone_filter in CANONICAL_ZONES.get(u["selected_habitat"], []):
                u["selected_zone"] = zone_filter
            else:
                u["selected_zone"] = "all"
            if spot_id is None:
                u["selected_spot"] = None
        if bait_id and bait_id in BAITS:
            u["selected_bait"] = bait_id
        if auto_mode is not None:
            u["auto_mode"] = bool(auto_mode)
        core.save_data(data)
    return get_user_fishing_summary(guild_id, user_id, user_name)


def prepare_cast_parameters(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    """찌 던지기 시작 시 대기시간·당기기 허용시간·사용할 미끼·세부 수역·특수 낚시터 계산"""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        rod = RODS[u["rod_id"]]
        reel = REELS[u["reel_id"]]
        net = NETS.get(u.get("net_id"))
        enh = get_gear_enhance_bonuses(u)
        spot_id = u.get("selected_spot")
        if spot_id and not is_special_spot_unlocked(u, spot_id):
            spot_id = None
            u["selected_spot"] = None
        bait_id = u["selected_bait"]
        if bait_id != "dough" and _safe_int(u["baits"].get(bait_id), 0) <= 0:
            bait_id = "dough"
            u["selected_bait"] = "dough"
            core.save_data(data)
        bait = BAITS[bait_id]
        env = get_current_fishing_env()

        base_wait = random.uniform(1.8, 3.6)
        wait_sec = max(1.0, round(base_wait - reel["wait_reduce"] - enh["wait_reduce"], 2))
        window_sec = round(float(reel["window_sec"]) + enh["window_sec"], 2)
        grace_sec = 1.25  # 디스코드/모바일 렌더링 지연 보정 숨은 유예

        return {
            "habitat": SPECIAL_SPOTS[spot_id]["base_habitat"] if spot_id else u["selected_habitat"],
            "zone_filter": "all" if spot_id else u.get("selected_zone", "all"),
            "spot_id": spot_id,
            "spot": SPECIAL_SPOTS.get(spot_id) if spot_id else None,
            "bait_id": bait_id,
            "bait": bait,
            "rod": rod,
            "reel": reel,
            "net": net,
            "enhance": enh,
            "env": env,
            "wait_sec": wait_sec,
            "window_sec": window_sec,
            "grace_sec": grace_sec,
            "auto_mode": bool(u.get("auto_mode", False)),
        }


def reset_fishing_combo(guild_id: int | str, user_id: int | str) -> int:
    """입질 놓침 등으로 연속 성공 콤보를 초기화하고 직전 콤보 수치를 반환합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        prev = _safe_int(u.get("combo"), 0)
        if prev > 0:
            u["combo"] = 0
            core.save_data(data)
        return prev


import itertools

_SPECIES_CUM_WEIGHT_CACHE: Dict[Tuple[str, int, str, str, str, bool, str, str], Tuple[List[Dict[str, Any]], List[float]]] = {}


def _get_cached_species_cum_weights(
    habitat: str,
    chosen_rarity: int,
    time_phase: str,
    weather_id: str,
    bait_id: str,
    use_zone_focus: bool,
    zone_filter: str,
    spot_id: str = "",
) -> Tuple[List[Dict[str, Any]], List[float]]:
    cache_key = (
        habitat,
        chosen_rarity,
        time_phase,
        weather_id,
        bait_id,
        use_zone_focus,
        zone_filter if use_zone_focus else "all",
        spot_id or "",
    )
    cached = _SPECIES_CUM_WEIGHT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pool = FISH_BY_HABITAT.get(habitat) or FISH_SPECIES_DB
    bucket = FISH_BY_HABITAT_RARITY.get((habitat, chosen_rarity)) or pool
    spot_meta = SPECIAL_SPOTS.get(spot_id) if spot_id else None
    spot_zones = set(spot_meta.get("prefer_zones") or ()) if spot_meta else set()
    spot_kws = tuple(spot_meta.get("keywords") or ()) if spot_meta else ()

    weights: List[float] = []
    for sp in bucket:
        w = 1.0
        atime = sp["active_time"]
        if atime == time_phase:
            w *= 1.65
        elif atime != "all":
            w *= 0.50

        pw = sp["prefer_weather"]
        if pw == weather_id:
            w *= 1.55
        elif pw != "all" and weather_id != pw:
            w *= 0.85

        if sp["prefer_bait"] == bait_id:
            w *= 1.45

        if _IS_HANGUL_SP_CACHE.get(sp["id"], False):
            w *= 1.85

        if use_zone_focus and (sp.get("zone") == zone_filter or sp.get("sub_zone") == zone_filter):
            w *= 3.20

        if spot_meta:
            if (sp.get("zone") in spot_zones) or (sp.get("sub_zone") in spot_zones):
                w *= 2.80
            if spot_kws and any(kw in sp.get("name", "") for kw in spot_kws):
                w *= 2.20

        weights.append(max(0.05, w))

    cum_weights = list(itertools.accumulate(weights))
    if len(_SPECIES_CUM_WEIGHT_CACHE) > 256:
        _SPECIES_CUM_WEIGHT_CACHE.clear()
    _SPECIES_CUM_WEIGHT_CACHE[cache_key] = (bucket, cum_weights)
    return bucket, cum_weights


def _roll_species_weighted(
    habitat: str,
    rod: Dict[str, Any],
    bait: Dict[str, Any],
    env: Dict[str, Any],
    zone_filter: str = "all",
    pokedex_ids: Optional[set] = None,
    net: Optional[Dict[str, Any]] = None,
    life_rare_bonus: float = 0.0,
    extra_rare_bonus: float = 0.0,
    spot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """2단계 성급 정규화 추첨: (1) 장비·강화·콤보·특수터·미끼·날씨·생활버프 기반 성급 결정 → (2) 누적 가중치 캐시 기반 추첨"""
    spot_meta = SPECIAL_SPOTS.get(spot_id or "") if spot_id else None
    if spot_meta:
        habitat = spot_meta["base_habitat"]
    if habitat not in HABITATS:
        habitat = "lake"
    net_rare = float((net or {}).get("rare_bonus", 0.0))
    spot_rare_mult = float(spot_meta["rare_mult"]) if spot_meta else 1.0
    rare_factor = (
        (1.0 + rod["rare_bonus"] + net_rare + max(0.0, float(life_rare_bonus or 0.0)) + max(0.0, float(extra_rare_bonus or 0.0)))
        * bait["rare_mult"]
        * env["weather_rare_mult"]
        * env["feeding_mult"]
        * spot_rare_mult
    )
    use_zone_focus = bool(not spot_meta and zone_filter and zone_filter != "all" and zone_filter in CANONICAL_ZONES.get(habitat, []))

    avail_rarities = [r for r in range(1, 6) if FISH_BY_HABITAT_RARITY.get((habitat, r))]
    if not avail_rarities:
        avail_rarities = [1]

    tier_weights: List[float] = []
    for r in avail_rarities:
        if r == 1:
            tw = 54.0 / max(1.0, rare_factor ** 0.45)
        elif r == 2:
            tw = 28.0 * (1.0 + (rare_factor - 1.0) * 0.28)
        elif r == 3:
            tw = 13.0 * (1.0 + (rare_factor - 1.0) * 0.72)
        elif r == 4:
            tw = 3.8 * (1.0 + (rare_factor - 1.0) * 1.35)
        else:
            tw = 1.2 * (1.0 + (rare_factor - 1.0) * 1.75)
        tier_weights.append(max(0.2, tw))

    chosen_rarity = random.choices(avail_rarities, weights=tier_weights, k=1)[0]

    bucket, cum_weights = _get_cached_species_cum_weights(
        habitat,
        chosen_rarity,
        env["time_phase"],
        env["weather_id"],
        bait["id"],
        use_zone_focus,
        zone_filter,
        spot_id or "",
    )
    pick = random.choices(bucket, cum_weights=cum_weights, k=1)[0]
    if pokedex_ids is not None and pick["id"] in pokedex_ids and random.random() < 0.26:
        alt = random.choices(bucket, cum_weights=cum_weights, k=1)[0]
        if alt["id"] not in pokedex_ids:
            return alt
    return pick


def _roll_fish_variant(variant_mult: float = 1.0) -> str:
    """변이(이로치) 개체 추첨: 심해 발광 > 알비노 > 황금 > 일반"""
    m = max(1.0, min(5.0, float(variant_mult or 1.0)))
    r = random.random()
    p_abyssal = VARIANT_META["abyssal"]["base_prob"] * m
    if r < p_abyssal:
        return "abyssal"
    p_albino = p_abyssal + VARIANT_META["albino"]["base_prob"] * m
    if r < p_albino:
        return "albino"
    p_golden = p_albino + VARIANT_META["golden"]["base_prob"] * m
    if r < p_golden:
        return "golden"
    return "normal"


def _roll_treasure_drop(
    u: Dict[str, Any],
    prof: Dict[str, Any],
    env: Dict[str, Any],
    spot_meta: Optional[Dict[str, Any]],
    combo: int,
) -> Optional[Dict[str, Any]]:
    """출조 성공 시 확률적으로 돌발 보물상자/표류물을 인양합니다."""
    chance = 0.095
    if env.get("weather_id") == "storm":
        chance += 0.055
    elif env.get("weather_id") in ("rain", "fog"):
        chance += 0.025
    if spot_meta:
        chance += float(spot_meta.get("treasure_bonus", 0.0))
    chance += min(0.05, combo * 0.0025)
    if random.random() >= chance:
        return None

    weights = [int(item["weight"]) for item in DRIFT_LOOT_TABLE]
    picked = random.choices(DRIFT_LOOT_TABLE, weights=weights, k=1)[0]
    g_lo, g_hi = picked["gold_range"]
    c_lo, c_hi = picked["crystal_range"]
    gain_gold = random.randint(g_lo, g_hi) if g_hi > 0 else 0
    gain_crystals = random.randint(c_lo, c_hi) if c_hi > 0 else 0
    gain_bait_id = None
    gain_bait_qty = 0
    if picked.get("bait"):
        gain_bait_id, gain_bait_qty = picked["bait"]

    if gain_gold > 0:
        u["gold"] = _safe_int(u.get("gold"), 0) + gain_gold
        u["total_gold_earned"] = _safe_int(u.get("total_gold_earned"), 0) + gain_gold
    if gain_crystals > 0:
        prof["crystals"] = _safe_int(prof.get("crystals"), 0) + gain_crystals
    if gain_bait_id and gain_bait_qty > 0:
        baits = core.ensure_dict_path(u, "baits")
        baits[gain_bait_id] = _safe_int(baits.get(gain_bait_id), 0) + gain_bait_qty
    u["treasures_found"] = _safe_int(u.get("treasures_found"), 0) + 1

    bait_name = BAITS[gain_bait_id]["name"] if gain_bait_id in BAITS else ""
    return {
        "id": picked["id"],
        "name": picked["name"],
        "emoji": picked["emoji"],
        "flavor": picked["flavor"],
        "gold": gain_gold,
        "crystals": gain_crystals,
        "bait_id": gain_bait_id,
        "bait_name": bait_name,
        "bait_qty": gain_bait_qty,
    }


def finalize_fish_catch(
    guild_id: int | str,
    user_id: int | str,
    user_name: str,
    habitat: str,
    bait_id: Optional[str] = None,
    reaction_sec: Optional[float] = None,
    zone_filter: Optional[str] = None,
    spot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    채집 성공 시 어종·cm·kg·변이·금관/은관·콤보·보물상자·월척·신기록·도감·가방·일일퀘스트·크리스탈 보너스를 단일 락 안에서 원자적으로 저장합니다.
    그물 장착 시 1회 출조로 2~10마리를 동시 포획합니다.
    """
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)
        env = get_current_fishing_env()

        use_spot_id = spot_id if spot_id is not None else u.get("selected_spot")
        if use_spot_id and (use_spot_id not in SPECIAL_SPOTS or not is_special_spot_unlocked(u, use_spot_id)):
            use_spot_id = None
        spot_meta = SPECIAL_SPOTS.get(use_spot_id) if use_spot_id else None

        if spot_meta:
            habitat = spot_meta["base_habitat"]
        elif habitat not in HABITATS:
            habitat = u["selected_habitat"]

        use_zone = "all" if spot_meta else (zone_filter if zone_filter is not None else u.get("selected_zone", "all"))

        use_bait_id = bait_id or u.get("selected_bait", "dough")
        if use_bait_id not in BAITS:
            use_bait_id = "dough"
        if use_bait_id != "dough":
            cur_qty = _safe_int(u["baits"].get(use_bait_id), 0)
            if cur_qty > 0:
                u["baits"][use_bait_id] = cur_qty - 1
                if u["baits"][use_bait_id] <= 0:
                    u["baits"].pop(use_bait_id, None)
                    if u.get("selected_bait") == use_bait_id:
                        u["selected_bait"] = "dough"
            else:
                use_bait_id = "dough"

        rod = RODS[u["rod_id"]]
        reel = REELS[u["reel_id"]]
        net = NETS.get(u.get("net_id"))
        bait = BAITS[use_bait_id]
        enh = get_gear_enhance_bonuses(u)

        # 연속 성공 콤보 갱신 (최대 20콤보 -> 희귀 +30%, EXP +40%, 변이 +35%)
        new_combo = min(20, _safe_int(u.get("combo"), 0) + 1)
        u["combo"] = new_combo
        if new_combo > _safe_int(u.get("max_combo"), 0):
            u["max_combo"] = new_combo
        combo_rare_bonus = min(0.30, new_combo * 0.015)
        combo_exp_mult = 1.0 + min(0.40, new_combo * 0.02)
        combo_variant_mult = 1.0 + min(0.35, new_combo * 0.0175)

        # 생활 버프(요리 + 동반 펫 + 서버 공동 농장) 연동
        life_buffs = {}
        try:
            import life_core
            life_buffs = life_core.get_active_life_buffs(guild_id, user_id, data=data)
        except Exception:
            life_buffs = {}
        life_rare_bonus = _safe_float(life_buffs.get("rare_bonus"), 0.0)
        life_size_bonus = _safe_float(life_buffs.get("size_bonus"), 0.0)
        life_trophy_bonus = _safe_float(life_buffs.get("trophy_bonus"), 0.0)
        life_gold_bonus = _safe_float(life_buffs.get("gold_bonus"), 0.0)

        # 변이 확률 배율
        weather_var_mult = 1.35 if env["weather_id"] in ("storm", "fog") else (1.15 if env["weather_id"] == "rain" else 1.0)
        spot_var_mult = float(spot_meta["variant_mult"]) if spot_meta else 1.0
        bait_var_mult = float(bait.get("variant_mult", 1.0))
        total_variant_mult = weather_var_mult * spot_var_mult * bait_var_mult * combo_variant_mult

        # 그물 장착 시 2~10마리 범위 내 랜덤 포획, 미장착 시 1마리
        if net:
            min_c = max(2, min(10, _safe_int(net.get("min_catch"), 2)))
            max_c = max(min_c, min(10, _safe_int(net.get("max_catch"), 10)))
            catch_count = max(2, min(10, random.randint(min_c, max_c)))
        else:
            catch_count = 1

        pokedex = core.ensure_dict_path(u, "pokedex")
        pokedex_keys = set(pokedex.keys())
        bag = u.get("bag")
        if not isinstance(bag, list):
            bag = []
            u["bag"] = bag

        g_key = str(guild_id or 0)
        g_rec_map = core.ensure_dict_path(data, "fishing_records", g_key)
        caught_at = env["now"].strftime("%Y-%m-%d %H:%M")

        # 빠른 챔질 보너스 (0.2s~1.8s 내 반응 시 대물 보정)
        perfect_hook = bool(reaction_sec is not None and reaction_sec <= 1.8)
        net_size_bonus = float((net or {}).get("size_bonus", 0.0))
        spot_size_mult = float(spot_meta["size_mult"]) if spot_meta else 1.0
        extra_rare_bonus = enh["rare_bonus"] + combo_rare_bonus

        catches: List[Dict[str, Any]] = []
        just_caught_uids: set = set()
        total_crystal_bonus = 0
        all_bonus_reasons: List[str] = []
        total_gain_exp = 0
        auto_sold_items: List[Tuple[str, int]] = []
        cur_season = get_current_season_meta()

        for _ in range(catch_count):
            sp = _roll_species_weighted(
                habitat,
                rod,
                bait,
                env,
                zone_filter=use_zone,
                pokedex_ids=pokedex_keys,
                net=net,
                life_rare_bonus=life_rare_bonus,
                extra_rare_bonus=extra_rare_bonus,
                spot_id=use_spot_id,
            )

            # 체장(cm) 계산: 정규분포 중심 + 장비·강화·그물·특수터·날씨·반응속도·생활버프 보정
            span = sp["max_cm"] - sp["min_cm"]
            mu_ratio = (
                0.42
                + (rod["size_bonus"] + net_size_bonus + life_size_bonus + enh["size_bonus"]) * 0.25
                + (bait["size_mult"] - 1.0) * 0.25
                + (env["weather_size_mult"] - 1.0) * 0.35
                + (spot_size_mult - 1.0) * 0.35
            )
            if perfect_hook:
                mu_ratio += 0.08
            ratio = random.gauss(min(0.82, mu_ratio), 0.21)
            if random.random() < (0.07 + (reel["trophy_bonus"] + life_trophy_bonus + enh["trophy_bonus"]) * 0.20):
                ratio = random.uniform(0.84, 1.05)

            ratio = max(0.0, min(1.06, ratio))
            length_cm = round(sp["min_cm"] + span * ratio, 1)
            is_trophy = length_cm >= (sp["min_cm"] + span * 0.82)
            weight_kg = _compute_fish_weight_kg(sp, length_cm)

            # 최대 금관 / 최소 은관 판정
            crown: Optional[str] = None
            if ratio >= 0.94:
                crown = "max_gold"
            elif ratio <= 0.08:
                crown = "min_silver"

            # 변이(이로치) 판정: golden / albino / abyssal / normal
            variant = _roll_fish_variant(total_variant_mult)
            v_meta = get_variant_meta(variant)

            # 예상 판매 골드 산정 (+ 계절 제철 어종 1.25배 + 변이 + 금관/은관 + 강화 보너스)
            is_seasonal = is_seasonal_bonus_species(sp, cur_season["id"])
            size_factor = 0.80 + (ratio * 0.70)
            gold_val = int(sp["base_gold"] * size_factor * (1.0 + rod["gold_bonus"] + life_gold_bonus + enh["gold_bonus"]))
            if is_trophy:
                gold_val = int(gold_val * 1.40)
            if v_meta["gold_mult"] > 1.0:
                gold_val = int(gold_val * v_meta["gold_mult"])
            if crown and crown in CROWN_META:
                gold_val = int(gold_val * CROWN_META[crown]["gold_mult"])
            if is_seasonal:
                gold_val = int(gold_val * 1.25)
            gold_val = max(10, gold_val)

            uid_hex = uuid.uuid4().hex[:8]
            fish_inst = {
                "uid": uid_hex,
                "fish_id": sp["id"],
                "name": sp["name"],
                "scientific_name": sp["scientific_name"],
                "habitat": sp["habitat"],
                "zone": sp.get("zone") or sp.get("sub_zone", ""),
                "sub_zone": sp.get("sub_zone") or sp.get("zone", ""),
                "rarity": sp["rarity"],
                "emoji": sp["emoji"],
                "length_cm": length_cm,
                "weight_kg": weight_kg,
                "gold": gold_val,
                "is_trophy": is_trophy,
                "is_seasonal": is_seasonal,
                "variant": variant,
                "crown": crown,
                "spot_id": use_spot_id,
                "locked": sp["rarity"] >= 4 or is_trophy or variant != "normal" or crown is not None,
                "caught_at": caught_at,
            }

            bag.append(fish_inst)
            just_caught_uids.add(uid_hex)

            # 도감 업데이트 (최대/최소 체장, 금관/은관, 변이 이력 포함)
            is_first_catch = sp["id"] not in pokedex
            pokedex_keys.add(sp["id"])
            pd_rec = pokedex.get(sp["id"])
            is_personal_len_best = False
            is_personal_wt_best = False
            new_crown_unlocked = False
            new_variant_unlocked = False
            if not isinstance(pd_rec, dict):
                pd_rec = {
                    "count": 1,
                    "max_cm": length_cm,
                    "min_cm": length_cm,
                    "max_kg": weight_kg,
                    "max_crown": crown == "max_gold",
                    "min_crown": crown == "min_silver",
                    "variants": [variant] if variant != "normal" else [],
                    "first_caught": caught_at,
                }
                pokedex[sp["id"]] = pd_rec
                is_personal_len_best = True
                is_personal_wt_best = True
                new_crown_unlocked = crown is not None
                new_variant_unlocked = variant != "normal"
            else:
                pd_rec["count"] = _safe_int(pd_rec.get("count"), 0) + 1
                if length_cm > _safe_float(pd_rec.get("max_cm"), 0.0):
                    pd_rec["max_cm"] = length_cm
                    is_personal_len_best = True
                prev_min = _safe_float(pd_rec.get("min_cm"), 0.0)
                if prev_min <= 0 or length_cm < prev_min:
                    pd_rec["min_cm"] = length_cm
                if weight_kg > _safe_float(pd_rec.get("max_kg"), 0.0):
                    pd_rec["max_kg"] = weight_kg
                    is_personal_wt_best = True
                if crown == "max_gold" and not pd_rec.get("max_crown"):
                    pd_rec["max_crown"] = True
                    new_crown_unlocked = True
                if crown == "min_silver" and not pd_rec.get("min_crown"):
                    pd_rec["min_crown"] = True
                    new_crown_unlocked = True
                if variant != "normal":
                    v_list = pd_rec.get("variants")
                    if not isinstance(v_list, list):
                        v_list = []
                        pd_rec["variants"] = v_list
                    if variant not in v_list:
                        v_list.append(variant)
                        new_variant_unlocked = True

            # 서버 신기록 체크 (길이 & 무게 독립 기록)
            sp_rec = g_rec_map.get(sp["id"])
            if not isinstance(sp_rec, dict):
                sp_rec = {}
                g_rec_map[sp["id"]] = sp_rec

            new_server_len_record = False
            new_server_wt_record = False
            prev_len_rec = sp_rec.get("max_cm")
            if not isinstance(prev_len_rec, dict) or length_cm > _safe_float(prev_len_rec.get("val"), 0.0):
                sp_rec["max_cm"] = {
                    "val": length_cm,
                    "user_id": str(user_id),
                    "user_name": user_name,
                    "at": caught_at,
                }
                new_server_len_record = True

            prev_wt_rec = sp_rec.get("max_kg")
            if not isinstance(prev_wt_rec, dict) or weight_kg > _safe_float(prev_wt_rec.get("val"), 0.0):
                sp_rec["max_kg"] = {
                    "val": weight_kg,
                    "user_id": str(user_id),
                    "user_name": user_name,
                    "at": caught_at,
                }
                new_server_wt_record = True

            # 마일스톤 크리스탈 보너스 계산
            item_crystal = 0
            item_reasons: List[str] = []
            if is_first_catch:
                if sp["rarity"] == 5:
                    item_crystal += 200
                    item_reasons.append("★5 신화 첫 도감(+200💎)")
                elif sp["rarity"] == 4:
                    item_crystal += 100
                    item_reasons.append("★4 전설 첫 도감(+100💎)")
                elif sp["rarity"] == 3:
                    item_crystal += 30
                    item_reasons.append("★3 희귀 첫 도감(+30💎)")
                else:
                    item_crystal += 10
                    item_reasons.append("신규 도감 등록(+10💎)")

            if variant != "normal" and v_meta["crystal_bonus"] > 0:
                vc = int(v_meta["crystal_bonus"])
                item_crystal += vc
                item_reasons.append(f"{v_meta['emoji']} {v_meta['name']}(+{vc}💎)")

            if new_crown_unlocked and crown in CROWN_META:
                cc = int(CROWN_META[crown]["first_crystal"])
                item_crystal += cc
                item_reasons.append(f"{CROWN_META[crown]['emoji']} 첫 {CROWN_META[crown]['name']}(+{cc}💎)")

            if new_server_len_record or new_server_wt_record:
                item_crystal += 25 if (prev_len_rec or prev_wt_rec) else 15
                item_reasons.append("🏆 서버 신기록(+25💎)" if (prev_len_rec or prev_wt_rec) else "🏆 서버 첫 기록(+15💎)")

            total_crystal_bonus += item_crystal
            for r_txt in item_reasons:
                if r_txt not in all_bonus_reasons:
                    all_bonus_reasons.append(r_txt)

            # EXP 및 누적 통계 (콤보 보너스 반영)
            raw_exp = 14 + sp["rarity"] * 12 + (18 if is_trophy else 0) + (20 if is_first_catch else 0) + (25 if variant != "normal" else 0)
            item_exp = int(round(raw_exp * combo_exp_mult))
            total_gain_exp += item_exp
            u["total_catches"] = _safe_int(u.get("total_catches"), 0) + 1
            if is_trophy:
                u["total_trophy"] = _safe_int(u.get("total_trophy"), 0) + 1

            # 일일 의뢰 진행도 갱신
            for q in (core.as_dict(u.get("daily_quests")).get("items") or []):
                if not isinstance(q, dict) or q.get("claimed"):
                    continue
                qtype = q.get("type")
                q_tgt = max(1, _safe_int(q.get("target"), 1))
                if qtype == "catch_total":
                    q["progress"] = min(q_tgt, _safe_int(q.get("progress"), 0) + 1)
                elif qtype == f"catch_{habitat}":
                    q["progress"] = min(q_tgt, _safe_int(q.get("progress"), 0) + 1)
                elif qtype == "catch_rare3" and sp["rarity"] >= 3:
                    q["progress"] = min(q_tgt, _safe_int(q.get("progress"), 0) + 1)
                elif qtype == "catch_trophy" and is_trophy:
                    q["progress"] = min(q_tgt, _safe_int(q.get("progress"), 0) + 1)

            catches.append({
                "fish": fish_inst,
                "species": sp,
                "is_first_catch": is_first_catch,
                "is_personal_len_best": is_personal_len_best,
                "is_personal_wt_best": is_personal_wt_best,
                "new_server_len_record": new_server_len_record,
                "new_server_wt_record": new_server_wt_record,
                "new_crown_unlocked": new_crown_unlocked,
                "new_variant_unlocked": new_variant_unlocked,
                "crystal_bonus": item_crystal,
                "bonus_reasons": item_reasons,
                "gain_exp": item_exp,
            })

        # 돌발 보물상자 · 표류물 인양 체크
        treasure_drop = _roll_treasure_drop(u, prof, env, spot_meta, new_combo)

        # 가방 상한 초과 시 가장 오래된 미잠금 저등급부터 자동 판매 보전
        bag_cap = get_bag_capacity(u)
        while len(bag) > bag_cap:
            pop_idx = None
            for idx, old_item in enumerate(bag):
                if (
                    isinstance(old_item, dict)
                    and old_item.get("uid") not in just_caught_uids
                    and not old_item.get("locked")
                    and _safe_int(old_item.get("rarity"), 1) <= 2
                ):
                    pop_idx = idx
                    break
            if pop_idx is None:
                for idx, old_item in enumerate(bag):
                    if (
                        isinstance(old_item, dict)
                        and old_item.get("uid") not in just_caught_uids
                        and not old_item.get("locked")
                    ):
                        pop_idx = idx
                        break
            if pop_idx is None:
                break
            sold_item = bag.pop(pop_idx)
            sold_g = _safe_int(sold_item.get("gold"), 20)
            u["gold"] += sold_g
            auto_sold_items.append((sold_item.get("name", "물고기"), sold_g))

        auto_sold_msg = None
        if len(auto_sold_items) == 1:
            auto_sold_msg = f"가방 초과로 `{auto_sold_items[0][0]}` 자동 판매 (+{auto_sold_items[0][1]:,}🪙)"
        elif len(auto_sold_items) > 1:
            tot_auto_g = sum(g for _, g in auto_sold_items)
            auto_sold_msg = f"가방 초과로 기존 물고기 {len(auto_sold_items)}마리 자동 판매 (+{tot_auto_g:,}🪙)"

        if total_crystal_bonus > 0:
            prof["crystals"] = _safe_int(prof.get("crystals"), 0) + total_crystal_bonus

        old_lvl = _safe_int(u.get("level"), 1)
        u["exp"] = _safe_int(u.get("exp"), 0) + total_gain_exp
        new_lvl, rem_exp, need_exp = _calc_level_from_exp(u["exp"])
        u["level"] = new_lvl
        leveled_up = new_lvl > old_lvl
        if leveled_up:
            u["gold"] += new_lvl * 50

        # 진행 중인 주말/커스텀 낚시 대회 자동 기록 반영
        tournament_update = _record_tournament_catch_unlocked(
            data, guild_id, user_id, user_name, habitat, catches
        )

        # 폭풍우/피딩타임 중 서버 대어 보스 돌발 출현 체크 (길드 내 활성 보스 없을 때 낮은 확률)
        boss_spawned = _maybe_auto_spawn_boss_unlocked(data, guild_id, env, user_name)

        core.save_data(data)

        # 포획된 모든 물고기를 성급/변이/금관/신기록 순으로 정렬
        variant_rank = {"abyssal": 3, "albino": 2, "golden": 1, "normal": 0}
        catches.sort(
            key=lambda c: (
                variant_rank.get(c["fish"].get("variant", "normal"), 0),
                c["species"]["rarity"],
                1 if (c["new_server_len_record"] or c["new_server_wt_record"]) else 0,
                1 if c["fish"].get("crown") else 0,
                1 if c["fish"]["is_trophy"] else 0,
                1 if c["is_first_catch"] else 0,
                c["fish"]["gold"],
                c["fish"]["length_cm"],
            ),
            reverse=True,
        )
        primary = catches[0]

        return {
            "fish": primary["fish"],
            "species": primary["species"],
            "catches": catches,
            "catch_count": len(catches),
            "total_gold_value": sum(c["fish"]["gold"] for c in catches),
            "env": env,
            "rod": rod,
            "reel": reel,
            "net": net,
            "bait": bait,
            "enhance": enh,
            "spot": spot_meta,
            "combo": new_combo,
            "max_combo": u["max_combo"],
            "treasure_drop": treasure_drop,
            "boss_spawned": boss_spawned,
            "is_first_catch": primary["is_first_catch"],
            "is_personal_len_best": primary["is_personal_len_best"],
            "is_personal_wt_best": primary["is_personal_wt_best"],
            "new_server_len_record": primary["new_server_len_record"],
            "new_server_wt_record": primary["new_server_wt_record"],
            "any_first_catch": any(c["is_first_catch"] for c in catches),
            "any_server_record": any(c["new_server_len_record"] or c["new_server_wt_record"] for c in catches),
            "any_seasonal_bonus": any(c["fish"].get("is_seasonal") for c in catches),
            "any_variant": any(c["fish"].get("variant", "normal") != "normal" for c in catches),
            "any_crown": any(bool(c["fish"].get("crown")) for c in catches),
            "crystal_bonus": total_crystal_bonus,
            "bonus_reasons": all_bonus_reasons,
            "gain_exp": total_gain_exp,
            "leveled_up": leveled_up,
            "new_level": new_lvl,
            "perfect_hook": perfect_hook,
            "auto_sold_msg": auto_sold_msg,
            "user_gold": _safe_int(u.get("gold"), 0),
            "user_crystals": _safe_int(prof.get("crystals"), 0),
            "remaining_bait": _safe_int(u["baits"].get(use_bait_id), 0) if use_bait_id != "dough" else -1,
            "life_buffs": life_buffs,
            "tournament_update": tournament_update,
        }


# ==========================================
# 가방 · 실시간 시세 판매 · 스마트 정리 · 수족관 · 상점 · 도감 · 랭킹 · 퀘스트 액션
# ==========================================
def _add_sell_quest_progress(u: Dict[str, Any], sold_gold: int) -> None:
    for q in (core.as_dict(u.get("daily_quests")).get("items") or []):
        if isinstance(q, dict) and q.get("type") == "sell_gold" and not q.get("claimed"):
            q_tgt = max(1, _safe_int(q.get("target"), 1))
            q["progress"] = min(q_tgt, _safe_int(q.get("progress"), 0) + sold_gold)


def sell_fish_by_uid(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str, int]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        market = get_current_fish_market()
        for idx, item in enumerate(bag):
            if isinstance(item, dict) and item.get("uid") == uid:
                base_g = _safe_int(item.get("gold"), 15)
                gold, mult, tags = compute_market_sell_price(item, market)
                name = item.get("name", "물고기")
                bag.pop(idx)
                u["gold"] += gold
                u["total_gold_earned"] = _safe_int(u.get("total_gold_earned"), 0) + gold
                _add_sell_quest_progress(u, gold)
                core.save_data(data)
                diff = gold - base_g
                mk_note = f" ({' · '.join(tags)} {diff:+,}🪙)" if tags and diff != 0 else ""
                return True, f"💰 **{name}**을(를) 어시장에 판매해 `+{gold:,}🪙`을 획득했습니다!{mk_note} (보유: `{u['gold']:,}🪙`)", gold
        return False, "⚠️ 이미 판매되었거나 가방에 없는 개체입니다.", 0


def sell_fishes_by_uids(
    guild_id: int | str,
    user_id: int | str,
    uids: List[str],
    skip_locked: bool = False,
) -> Tuple[bool, str, int, int, List[str]]:
    target_set = {str(x) for x in (uids or []) if x}
    if not target_set:
        return False, "ℹ️ 판매할 물고기가 없습니다.", 0, 0, []
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        market = get_current_fish_market()
        kept = []
        sold_cnt = 0
        sold_gold = 0
        base_total = 0
        skipped_locked_uids: List[str] = []
        for item in bag:
            uid_s = str(item.get("uid") or "") if isinstance(item, dict) else ""
            if isinstance(item, dict) and uid_s in target_set:
                if skip_locked and item.get("locked", False):
                    kept.append(item)
                    skipped_locked_uids.append(uid_s)
                else:
                    sold_cnt += 1
                    base_total += _safe_int(item.get("gold"), 15)
                    mk_g, _, _ = compute_market_sell_price(item, market)
                    sold_gold += mk_g
            else:
                kept.append(item)
        if sold_cnt == 0:
            if skipped_locked_uids:
                return (
                    False,
                    f"🔒 선택한 물고기 `{len(skipped_locked_uids)}마리`가 모두 잠금 보호 상태입니다! 먼저 `[🔓 선택 잠금해제]`로 잠금을 풀어주세요.",
                    0,
                    0,
                    skipped_locked_uids,
                )
            return False, "⚠️ 이미 판매되었거나 가방에 없는 개체들입니다.", 0, 0, []
        u["bag"] = kept
        u["gold"] += sold_gold
        u["total_gold_earned"] = _safe_int(u.get("total_gold_earned"), 0) + sold_gold
        _add_sell_quest_progress(u, sold_gold)
        core.save_data(data)
        diff = sold_gold - base_total
        mk_note = f" · 📈 시세 `{diff:+,}🪙`" if diff != 0 else ""
        if skipped_locked_uids:
            msg = (
                f"💰 선택한 미잠금 물고기 `{sold_cnt}마리`를 판매해 `+{sold_gold:,}🪙`을 획득했습니다!{mk_note} "
                f"(보유: `{u['gold']:,}🪙` · 🔒 잠금 `{len(skipped_locked_uids)}마리` 제외)"
            )
        elif skip_locked:
            msg = f"💰 선택한 물고기 `{sold_cnt}마리`를 일괄 판매해 `+{sold_gold:,}🪙`을 획득했습니다!{mk_note} (보유: `{u['gold']:,}🪙`)"
        else:
            msg = f"💰 방금 잡은 물고기 `{sold_cnt}마리`를 일괄 판매해 `+{sold_gold:,}🪙`을 획득했습니다!{mk_note} (보유: `{u['gold']:,}🪙`)"
        return (
            True,
            msg,
            sold_cnt,
            sold_gold,
            skipped_locked_uids,
        )


def sell_all_unlocked_bag(
    guild_id: int | str,
    user_id: int | str,
    habitat_filter: str = "all",
    max_rarity: int = 5,
) -> Tuple[bool, str, int, int]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        market = get_current_fish_market()
        kept = []
        sold_cnt = 0
        sold_gold = 0
        base_total = 0
        for item in bag:
            if not isinstance(item, dict):
                continue
            h_ok = (habitat_filter == "all") or (item.get("habitat") == habitat_filter)
            r_ok = _safe_int(item.get("rarity"), 1) <= max_rarity
            if not item.get("locked", False) and h_ok and r_ok:
                sold_cnt += 1
                base_total += _safe_int(item.get("gold"), 15)
                mk_g, _, _ = compute_market_sell_price(item, market)
                sold_gold += mk_g
            else:
                kept.append(item)
        if sold_cnt == 0:
            scope = f"★1~★{max_rarity} " if max_rarity < 5 else ""
            return False, f"ℹ️ 판매할 수 있는(잠금 해제된) {scope}물고기가 없습니다.", 0, 0
        u["bag"] = kept
        u["gold"] += sold_gold
        u["total_gold_earned"] = _safe_int(u.get("total_gold_earned"), 0) + sold_gold
        _add_sell_quest_progress(u, sold_gold)
        core.save_data(data)
        diff = sold_gold - base_total
        mk_note = f" (📈 시세 `{diff:+,}🪙` 반영)" if diff != 0 else ""
        scope_txt = f"★1~★{max_rarity} " if max_rarity < 5 else ""
        return True, f"💰 잠금 해제된 {scope_txt}물고기 `{sold_cnt}마리`를 일괄 판매해 `+{sold_gold:,}🪙`를 벌었습니다!{mk_note} (보유: `{u['gold']:,}🪙`)", sold_cnt, sold_gold


def sell_bag_by_max_rarity(
    guild_id: int | str,
    user_id: int | str,
    max_rarity: int = 2,
    habitat_filter: str = "all",
) -> Tuple[bool, str, int, int]:
    """가방 내 미잠금 저등급(기본 ★1~★2) 물고기만 스마트 일괄 판매합니다."""
    return sell_all_unlocked_bag(guild_id, user_id, habitat_filter=habitat_filter, max_rarity=max(1, min(5, int(max_rarity))))


def sell_bag_duplicates_keep_best(
    guild_id: int | str,
    user_id: int | str,
    habitat_filter: str = "all",
) -> Tuple[bool, str, int, int]:
    """같은 어종이 여러 마리일 때 어종별 최고 개체(변이·금관·월척·최장) 1마리씩만 남기고 나머지 미잠금 중복 개체를 일괄 판매합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        market = get_current_fish_market()

        def _spec_score(it: Dict[str, Any]) -> Tuple[int, int, int, int, float, int]:
            v_rank = {"abyssal": 3, "albino": 2, "golden": 1}.get(str(it.get("variant") or "normal"), 0)
            return (
                1 if it.get("locked") else 0,
                v_rank,
                1 if it.get("crown") else 0,
                1 if it.get("is_trophy") else 0,
                _safe_float(it.get("length_cm"), 0.0),
                _safe_int(it.get("gold"), 0),
            )

        best_uid_by_sp: Dict[str, str] = {}
        best_score_by_sp: Dict[str, Tuple[int, int, int, int, float, int]] = {}
        for it in bag:
            if not isinstance(it, dict):
                continue
            sp_key = str(it.get("fish_id") or it.get("name") or "")
            uid_s = str(it.get("uid") or "")
            if not sp_key or not uid_s:
                continue
            sc = _spec_score(it)
            if sp_key not in best_score_by_sp or sc > best_score_by_sp[sp_key]:
                best_score_by_sp[sp_key] = sc
                best_uid_by_sp[sp_key] = uid_s

        kept = []
        sold_cnt = 0
        sold_gold = 0
        base_total = 0
        for it in bag:
            if not isinstance(it, dict):
                continue
            sp_key = str(it.get("fish_id") or it.get("name") or "")
            uid_s = str(it.get("uid") or "")
            h_ok = (habitat_filter == "all") or (it.get("habitat") == habitat_filter)
            is_best = best_uid_by_sp.get(sp_key) == uid_s
            if h_ok and not is_best and not it.get("locked", False):
                sold_cnt += 1
                base_total += _safe_int(it.get("gold"), 15)
                mk_g, _, _ = compute_market_sell_price(it, market)
                sold_gold += mk_g
            else:
                kept.append(it)

        if sold_cnt == 0:
            return False, "ℹ️ 정리할 중복 미잠금 물고기가 없습니다! (어종별 최고 개체 및 잠금 개체는 모두 보호됨)", 0, 0

        u["bag"] = kept
        u["gold"] += sold_gold
        u["total_gold_earned"] = _safe_int(u.get("total_gold_earned"), 0) + sold_gold
        _add_sell_quest_progress(u, sold_gold)
        core.save_data(data)
        diff = sold_gold - base_total
        mk_note = f" (📈 시세 `{diff:+,}🪙`)" if diff != 0 else ""
        return (
            True,
            f"✨ 어종별 최고 개체를 남기고 중복 물고기 `{sold_cnt}마리`를 깔끔하게 판매해 `+{sold_gold:,}🪙` 획득!{mk_note} (보유: `{u['gold']:,}🪙`)",
            sold_cnt,
            sold_gold,
        )


def sell_bag_market_featured(guild_id: int | str, user_id: int | str) -> Tuple[bool, str, int, int]:
    """현재 어시장 '오늘의 특가(×1.8~2.05)'에 해당하는 미잠금 물고기만 골라 고가에 즉시 판매합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        market = get_current_fish_market()
        feat_ids = set((market.get("featured_species") or {}).keys())
        kept = []
        sold_cnt = 0
        sold_gold = 0
        for it in bag:
            if not isinstance(it, dict):
                continue
            if not it.get("locked", False) and str(it.get("fish_id") or "") in feat_ids:
                sold_cnt += 1
                mk_g, _, _ = compute_market_sell_price(it, market)
                sold_gold += mk_g
            else:
                kept.append(it)
        if sold_cnt == 0:
            return False, "ℹ️ 가방에 판매 가능한(미잠금) 오늘의 특가 어종이 없습니다.", 0, 0
        u["bag"] = kept
        u["gold"] += sold_gold
        u["total_gold_earned"] = _safe_int(u.get("total_gold_earned"), 0) + sold_gold
        _add_sell_quest_progress(u, sold_gold)
        core.save_data(data)
        return True, f"🔥 오늘의 특가 어종 `{sold_cnt}마리`를 최고가 매입으로 판매해 `+{sold_gold:,}🪙` 획득! (보유: `{u['gold']:,}🪙`)", sold_cnt, sold_gold



def toggle_fish_lock(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        for item in u.get("bag", []):
            if isinstance(item, dict) and item.get("uid") == uid:
                item["locked"] = not bool(item.get("locked", False))
                state_txt = "🔒 잠금 설정" if item["locked"] else "🔓 잠금 해제"
                core.save_data(data)
                return True, f"{state_txt}: **{item.get('name', '물고기')}** (`{item.get('length_cm', 0)}cm`)"
        return False, "⚠️ 해당 물고기를 가방에서 찾지 못했습니다."


def set_fishes_lock_state(
    guild_id: int | str,
    user_id: int | str,
    uids: List[str],
    locked: bool,
) -> Tuple[bool, str, int]:
    target_set = {str(x) for x in (uids or []) if x}
    if not target_set:
        return False, "ℹ️ 먼저 가방에서 물고기를 선택해 주세요.", 0
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        matched = 0
        changed = 0
        for item in bag:
            if not isinstance(item, dict) or str(item.get("uid") or "") not in target_set:
                continue
            matched += 1
            if bool(item.get("locked", False)) != bool(locked):
                item["locked"] = bool(locked)
                changed += 1
        if matched == 0:
            return False, "⚠️ 선택한 물고기를 가방에서 찾지 못했습니다.", 0
        if changed == 0:
            state_lbl = "이미 모두 🔒 잠금 상태" if locked else "이미 모두 🔓 잠금 해제 상태"
            return False, f"ℹ️ 선택한 `{matched}마리`는 {state_lbl}입니다.", 0
        core.save_data(data)
        action_txt = "🔒 선택 잠금 완료" if locked else "🔓 선택 잠금 해제 완료"
        return True, f"{action_txt}: **`{changed}마리`** (총 `{matched}마리` 선택 중 변경)", changed


def release_fish_by_uid(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        for idx, item in enumerate(bag):
            if isinstance(item, dict) and item.get("uid") == uid:
                bag.pop(idx)
                bonus_exp = 15 + int(item.get("rarity", 1)) * 12
                u["exp"] = int(u.get("exp", 0)) + bonus_exp
                new_lvl, _, _ = _calc_level_from_exp(u["exp"])
                u["level"] = new_lvl
                core.save_data(data)
                return True, f"🌊 **{item.get('name', '물고기')}**을(를) 자연으로 방생했습니다! (`+{bonus_exp} EXP`)"
        return False, "⚠️ 이미 처리되었거나 가방에 없는 개체입니다."


def release_fishes_by_uids(guild_id: int | str, user_id: int | str, uids: List[str]) -> Tuple[bool, str, int, int, List[str]]:
    target_set = {str(x) for x in (uids or []) if x}
    if not target_set:
        return False, "ℹ️ 방생할 물고기가 없습니다.", 0, 0, []
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        kept = []
        rel_cnt = 0
        bonus_exp = 0
        for item in bag:
            if isinstance(item, dict) and str(item.get("uid") or "") in target_set:
                rel_cnt += 1
                bonus_exp += 15 + int(item.get("rarity", 1)) * 12
            else:
                kept.append(item)
        if rel_cnt == 0:
            return False, "⚠️ 이미 처리되었거나 가방에 없는 개체들입니다.", 0, 0, []
        u["bag"] = kept
        u["exp"] = int(u.get("exp", 0)) + bonus_exp
        new_lvl, _, _ = _calc_level_from_exp(u["exp"])
        u["level"] = new_lvl
        core.save_data(data)
        return (
            True,
            f"🌊 방금 잡은 물고기 `{rel_cnt}마리`를 자연으로 방생했습니다! (`+{bonus_exp:,} EXP`)",
            rel_cnt,
            bonus_exp,
            [],
        )


def move_fish_to_tank(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        tank = u.get("tank")
        if not isinstance(tank, list):
            tank = []
            u["tank"] = tank
        max_slots = int(u.get("tank_slots", 4))
        if len(tank) >= max_slots:
            return False, f"⚠️ 수족관 전시 슬롯(`{len(tank)}/{max_slots}`)이 가득 찼습니다! 상점에서 수족관을 확장하거나 어종을 꺼내주세요."
        bag = u.get("bag", [])
        for idx, item in enumerate(bag):
            if isinstance(item, dict) and item.get("uid") == uid:
                moved = bag.pop(idx)
                tank.append(moved)
                core.save_data(data)
                return True, f"🐠 **{moved.get('name', '물고기')}** (`{moved.get('length_cm', 0)}cm` · `{moved.get('weight_kg', 0)}kg`)을(를) 개인 수족관에 전시했습니다! (`{len(tank)}/{max_slots}`)"
        return False, "⚠️ 해당 물고기가 가방에 없습니다."


def move_fishes_to_tank(guild_id: int | str, user_id: int | str, uids: List[str]) -> Tuple[bool, str, int, List[str]]:
    ordered_uids = [str(x) for x in (uids or []) if x]
    if not ordered_uids:
        return False, "ℹ️ 전시할 물고기가 없습니다.", 0, []
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        tank = u.get("tank")
        if not isinstance(tank, list):
            tank = []
            u["tank"] = tank
        max_slots = int(u.get("tank_slots", 4))
        avail = max(0, max_slots - len(tank))
        if avail <= 0:
            return False, f"⚠️ 수족관 전시 슬롯(`{len(tank)}/{max_slots}`)이 가득 찼습니다! 상점에서 수족관을 확장하거나 어종을 꺼내주세요.", 0, ordered_uids

        bag = u.get("bag", [])
        uid_to_item = {
            str(it.get("uid")): it for it in bag
            if isinstance(it, dict) and it.get("uid")
        }
        moved_uids: set = set()
        moved_names: List[str] = []
        remaining_uids: List[str] = []
        for uid in ordered_uids:
            item = uid_to_item.get(uid)
            if not item:
                continue
            if len(moved_uids) < avail:
                tank.append(item)
                moved_uids.add(uid)
                moved_names.append(item.get("name", "물고기"))
            else:
                remaining_uids.append(uid)

        if not moved_uids:
            return False, "⚠️ 가방에 전시할 물고기가 없습니다.", 0, []
        u["bag"] = [it for it in bag if not (isinstance(it, dict) and str(it.get("uid") or "") in moved_uids)]
        core.save_data(data)
        preview = ", ".join(moved_names[:3]) + (f" 외 {len(moved_names) - 3}마리" if len(moved_names) > 3 else "")
        extra = f" (수족관 만석으로 `{len(remaining_uids)}마리` 가방 유지)" if remaining_uids else ""
        return (
            True,
            f"🐠 **{preview}** 총 `{len(moved_uids)}마리`를 개인 수족관에 전시했습니다! (`{len(tank)}/{max_slots}`){extra}",
            len(moved_uids),
            remaining_uids,
        )


def remove_fish_from_tank(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag")
        if not isinstance(bag, list):
            bag = []
            u["bag"] = bag
        bag_cap = get_bag_capacity(u)
        if len(bag) >= bag_cap:
            return False, f"⚠️ 가방이 가득 차서 수족관에서 물고기를 회수할 수 없습니다! (`{len(bag):,}/{bag_cap:,}`)"
        tank = u.get("tank", [])
        for idx, item in enumerate(tank):
            if isinstance(item, dict) and item.get("uid") == uid:
                removed = tank.pop(idx)
                bag.append(removed)
                core.save_data(data)
                return True, f"🎒 **{removed.get('name', '물고기')}**을(를) 수족관에서 가방으로 회수했습니다."
        return False, "⚠️ 수족관에서 해당 개체를 찾지 못했습니다."


def harvest_tank_gold(guild_id: int | str, user_id: int | str) -> Tuple[bool, str, int]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        now_dt = datetime.datetime.now(core.KST)
        pending, hourly = get_tank_pending_gold(u, now_dt)
        u["last_tank_collect"] = now_dt.isoformat()
        if pending <= 0:
            core.save_data(data)
            return False, f"ℹ️ 아직 수확할 수익이 모이지 않았습니다. (시간당 `{hourly:,}🪙` 생산 중)", 0
        u["gold"] += pending
        u["total_gold_earned"] = int(u.get("total_gold_earned", 0)) + pending
        core.save_data(data)
        return True, f"🪙 수족관 관람 수익 `+{pending:,}🪙`를 수확했습니다! (현재 보유: `{u['gold']:,}🪙`)", pending


def buy_or_equip_tank_theme(guild_id: int | str, user_id: int | str, theme_id: str) -> Tuple[bool, str]:
    """수족관 테마 구매 및 장착"""
    theme = TANK_THEMES.get(theme_id)
    if not theme:
        return False, "❌ 존재하지 않는 수족관 테마입니다."
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        owned = u["owned_tank_themes"]
        if theme_id in owned:
            u["tank_theme"] = theme_id
            core.save_data(data)
            return True, f"{theme['emoji']} **{theme['name']}** 테마를 수족관에 적용했습니다!"
        cost = int(theme["price"])
        if int(u.get("gold", 0)) < cost:
            return False, f"❌ 낚시 골드가 부족합니다! (필요: `{cost:,}🪙` / 보유: `{int(u.get('gold', 0)):,}🪙`)"
        u["gold"] -= cost
        owned.append(theme_id)
        u["tank_theme"] = theme_id
        core.save_data(data)
        return True, f"🎨 {theme['emoji']} **{theme['name']}** 테마를 구매하고 즉시 적용했습니다! (`-{cost:,}🪙` · 잔액 `{u['gold']:,}🪙`)"


def feed_aquarium_fish(guild_id: int | str, user_id: int | str) -> Tuple[bool, str, Dict[str, Any]]:
    """수족관 전시 물고기에게 먹이를 주어 4시간 +35% 수익 버프 & 전시어 소폭 성장(+0.5~1.4%) 적용"""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        tank = [it for it in (u.get("tank") or []) if isinstance(it, dict)]
        if not tank:
            return False, "ℹ️ 수족관에 전시된 물고기가 없어 먹이를 줄 수 없습니다! 먼저 가방에서 물고기를 전시해 주세요.", {}

        now_dt = datetime.datetime.now(core.KST)
        last_iso = u.get("last_tank_feed")
        if last_iso:
            try:
                last_dt = datetime.datetime.fromisoformat(str(last_iso))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=core.KST)
                elapsed = (now_dt - last_dt).total_seconds()
                if elapsed < TANK_FEED_COOLDOWN_SEC:
                    rem_min = max(1, int((TANK_FEED_COOLDOWN_SEC - elapsed + 59) // 60))
                    rh, rm = divmod(rem_min, 60)
                    rem_txt = f"{rh}시간 {rm}분" if rh > 0 else f"{rm}분"
                    return False, f"⏳ 물고기들이 아직 배부릅니다! **`{rem_txt}`** 후에 다시 먹이를 줄 수 있습니다.", {}
            except Exception:
                pass

        if int(u.get("gold", 0)) < TANK_FEED_COST:
            return False, f"❌ 고급 수족관 사료 비용이 부족합니다! (필요: `{TANK_FEED_COST:,}🪙` / 보유: `{int(u.get('gold', 0)):,}🪙`)", {}

        u["gold"] -= TANK_FEED_COST
        u["last_tank_feed"] = now_dt.isoformat()
        buff_until = now_dt + datetime.timedelta(seconds=TANK_FEED_BUFF_SEC)
        u["tank_feed_buff_until"] = buff_until.isoformat()

        grown_cnt = 0
        total_cm_gain = 0.0
        for item in tank:
            sp = FISH_BY_ID.get(str(item.get("fish_id") or ""))
            cur_cm = max(1.0, _safe_float(item.get("length_cm"), 10.0))
            max_cap = round(float(sp["max_cm"]) * 1.08, 1) if sp else round(cur_cm * 1.25, 1)
            if cur_cm < max_cap:
                pct = random.uniform(0.005, 0.014)
                add_cm = max(0.1, round(cur_cm * pct, 1))
                new_cm = min(max_cap, round(cur_cm + add_cm, 1))
                delta = round(new_cm - cur_cm, 1)
                if delta > 0:
                    item["length_cm"] = new_cm
                    if sp:
                        old_kg = _safe_float(item.get("weight_kg"), 0.01)
                        est_kg = _compute_fish_weight_kg(sp, new_cm)
                        item["weight_kg"] = max(old_kg, est_kg)
                    item["gold"] = max(_safe_int(item.get("gold"), 15), int(round(_safe_int(item.get("gold"), 15) * (1.0 + pct * 0.8))))
                    grown_cnt += 1
                    total_cm_gain += delta

        _, new_hourly = get_tank_pending_gold(u, now_dt)
        core.save_data(data)
        grow_note = f"전시어 `{grown_cnt}마리` 총 `+{total_cm_gain:.1f}cm` 성장!" if grown_cnt > 0 else "모든 전시어가 이미 최대 성장치에 도달했습니다!"
        return (
            True,
            f"🍖 수족관 먹이주기 완료! (`-{TANK_FEED_COST:,}🪙`) · **{grow_note}** · **4시간 동안 수족관 수익 +35%** (현재 시간당 `+{new_hourly:,}🪙`)",
            {"grown_cnt": grown_cnt, "total_cm_gain": round(total_cm_gain, 1), "hourly": new_hourly},
        )


def enhance_fishing_gear(guild_id: int | str, user_id: int | str, slot: str) -> Tuple[bool, str, Dict[str, Any]]:
    """장비 강화 (+0 → +10, 실패 시 파괴/하락 없음 + 천장 확률 +8% 누적)"""
    if slot not in ("rod", "reel", "net"):
        return False, "❌ 강화할 수 있는 장비 부위는 `rod`(낚싯대), `reel`(릴), `net`(그물)입니다.", {}
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        meta = ENHANCE_SLOT_META[slot]
        cur_lv = _safe_int(u["gear_enhance"].get(slot), 0)
        if cur_lv >= ENHANCE_MAX_LEVEL:
            return False, f"🏆 {meta['emoji']} **{meta['name']}**은(는) 이미 최고 강화 단계(`+{ENHANCE_MAX_LEVEL}`)에 도달했습니다!", {"level": cur_lv}

        step = ENHANCE_TABLE[cur_lv]
        cost = int(step["cost"])
        if int(u.get("gold", 0)) < cost:
            return False, f"❌ 강화 비용이 부족합니다! (`+{cur_lv}→+{cur_lv + 1}` 필요: `{cost:,}🪙` / 보유: `{int(u.get('gold', 0)):,}🪙`)", {"level": cur_lv}

        pity = _safe_int(u["enhance_pity"].get(slot), 0)
        eff_rate = min(1.0, float(step["rate"]) + pity * 0.08)
        u["gold"] -= cost

        success = random.random() < eff_rate
        if success:
            new_lv = cur_lv + 1
            u["gear_enhance"][slot] = new_lv
            u["enhance_pity"][slot] = 0
            core.save_data(data)
            return (
                True,
                f"✨ **강화 대성공!** {meta['emoji']} **{meta['name']} `+{cur_lv} → +{new_lv}`** 달성! (`-{cost:,}🪙` · 적용 확률 `{int(round(eff_rate * 100))}%` · 잔액 `{u['gold']:,}🪙`)",
                {"success": True, "old_level": cur_lv, "level": new_lv, "cost": cost, "rate": eff_rate},
            )

        u["enhance_pity"][slot] = min(10, pity + 1)
        next_pity_pct = int(round(min(1.0, float(step["rate"]) + u["enhance_pity"][slot] * 0.08) * 100))
        core.save_data(data)
        return (
            True,
            f"💨 **강화 실패** (안전 보호: 단계 유지 `+{cur_lv}` · `-{cost:,}🪙` · 잔액 `{u['gold']:,}🪙`)\n"
            f"🍀 장인의 기운이 쌓여 다음 시도 성공률이 **`{next_pity_pct}%`** 로 상승했습니다!",
            {"success": False, "old_level": cur_lv, "level": cur_lv, "cost": cost, "rate": eff_rate},
        )


def craft_bait_from_bag(guild_id: int | str, user_id: int | str, recipe_id: str) -> Tuple[bool, str, Dict[str, Any]]:
    """가방 속 미잠금 소형어(★1~★2)를 분해해 특제 생미끼/집어제/황금 떡밥을 제작합니다."""
    recipe = BAIT_CRAFT_RECIPES.get(recipe_id)
    if not recipe:
        return False, "❌ 존재하지 않는 미끼 제작 레시피입니다.", {}
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        need = int(recipe["need_fish"])
        max_r = int(recipe["max_rarity"])

        # 미잠금 ★1~2 물고기 중 가치가 낮은 것부터 우선 분해
        eligible_indices = [
            idx for idx, it in enumerate(bag)
            if isinstance(it, dict)
            and not it.get("locked", False)
            and _safe_int(it.get("rarity"), 1) <= max_r
        ]
        if len(eligible_indices) < need:
            return (
                False,
                f"❌ 재료 소형어(미잠금 ★1~★{max_r})가 부족합니다! (보유 `{len(eligible_indices)}마리` / 필요 `{need}마리`)",
                {"have": len(eligible_indices), "need": need},
            )

        eligible_indices.sort(key=lambda i: (_safe_int(bag[i].get("rarity"), 1), _safe_int(bag[i].get("gold"), 0)))
        consume_set = set(eligible_indices[:need])
        u["bag"] = [it for idx, it in enumerate(bag) if idx not in consume_set]

        y_bait = recipe["yield_bait"]
        y_qty = int(recipe["yield_qty"])
        baits = core.ensure_dict_path(u, "baits")
        baits[y_bait] = _safe_int(baits.get(y_bait), 0) + y_qty
        u["selected_bait"] = y_bait
        b_meta = BAITS[y_bait]
        core.save_data(data)
        return (
            True,
            f"🧪 미잠금 소형어 `{need}마리`를 분해해 {b_meta['emoji']} **{b_meta['name']} ×{y_qty}개**를 제작하고 장착했습니다! (총 `{baits[y_bait]}개` 보유)",
            {"bait_id": y_bait, "qty": y_qty, "total_qty": baits[y_bait], "consumed": need},
        )


def gift_fish_to_user(
    guild_id: int | str,
    sender_id: int | str,
    sender_name: str,
    receiver_id: int | str,
    receiver_name: str,
    uid: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """가방 속 미잠금 물고기 1마리를 같은 서버의 다른 유저에게 안전하게 선물(이동)합니다."""
    if str(sender_id) == str(receiver_id):
        return False, "❌ 자기 자신에게는 물고기를 선물할 수 없습니다!", None
    with _FISHING_LOCK:
        data = core.load_data()
        s_u = ensure_fishing_user(data, guild_id, sender_id, sender_name)
        r_u = ensure_fishing_user(data, guild_id, receiver_id, receiver_name)

        s_bag = s_u.get("bag", [])
        target_idx = None
        for idx, it in enumerate(s_bag):
            if isinstance(it, dict) and str(it.get("uid") or "") == str(uid):
                target_idx = idx
                break
        if target_idx is None:
            return False, "⚠️ 가방에서 해당 물고기를 찾지 못했습니다.", None

        fish_item = s_bag[target_idx]
        if fish_item.get("locked", False):
            return False, "🔒 잠금 보호 중인 물고기는 바로 선물할 수 없습니다! 먼저 가방에서 `[🔓 잠금해제]`해 주세요.", None

        r_bag = r_u.get("bag", [])
        r_cap = get_bag_capacity(r_u)
        if len(r_bag) >= r_cap:
            return False, f"⚠️ **{r_u['name']}**님의 낚시 가방이 가득 차서 선물할 수 없습니다! (`{len(r_bag):,}/{r_cap:,}`)", None

        gifted = copy.deepcopy(s_bag.pop(target_idx))
        gifted["uid"] = uuid.uuid4().hex[:8]
        gifted["locked"] = True  # 선물받은 개체는 실수 판매 방지를 위해 자동 잠금
        gifted["gifted_from"] = s_u["name"]
        gifted["gifted_at"] = datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M")
        r_bag.append(gifted)

        s_u["gifts_sent"] = _safe_int(s_u.get("gifts_sent"), 0) + 1
        r_u["gifts_received"] = _safe_int(r_u.get("gifts_received"), 0) + 1
        core.save_data(data)
        return (
            True,
            f"🎁 **{s_u['name']}**님이 **{r_u['name']}**님에게 {gifted.get('emoji', '🐟')} **★{gifted.get('rarity', 1)} {gifted.get('name', '물고기')}** (`{float(gifted.get('length_cm', 0)):.1f}cm`)을(를) 선물했습니다! *(받는 분 가방에 🔒 자동 잠금 보관)*",
            gifted,
        )


def roll_duel_cast(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    """1:1 대물 낚시 대결 1라운드 투척 결과를 유저 실제 장비/강화/날씨 기반으로 산출합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        rod = RODS[u["rod_id"]]
        reel = REELS[u["reel_id"]]
        net = NETS.get(u.get("net_id"))
        enh = get_gear_enhance_bonuses(u)
        bait = BAITS.get(u.get("selected_bait", "dough"), BAITS["dough"])
        env = get_current_fishing_env()
        hab = random.choice(["lake", "river", "sea"])
        sp = _roll_species_weighted(
            hab,
            rod,
            bait,
            env,
            net=net,
            extra_rare_bonus=enh["rare_bonus"],
        )
        span = sp["max_cm"] - sp["min_cm"]
        mu = 0.48 + (rod["size_bonus"] + enh["size_bonus"]) * 0.25 + (env["weather_size_mult"] - 1.0) * 0.30
        ratio = max(0.0, min(1.06, random.gauss(min(0.80, mu), 0.22)))
        if random.random() < (0.09 + (reel["trophy_bonus"] + enh["trophy_bonus"]) * 0.20):
            ratio = random.uniform(0.84, 1.05)
        length_cm = round(sp["min_cm"] + span * ratio, 1)
        is_trophy = length_cm >= (sp["min_cm"] + span * 0.82)
        variant = _roll_fish_variant(1.5)
        v_meta = get_variant_meta(variant)
        v_bonus = {"normal": 0, "golden": 140, "albino": 220, "abyssal": 340}.get(variant, 0)
        score = int(round(sp["rarity"] * 125 + ratio * 220 + (95 if is_trophy else 0) + v_bonus))
        return {
            "fish_id": sp["id"],
            "name": sp["name"],
            "emoji": sp["emoji"],
            "habitat": hab,
            "rarity": sp["rarity"],
            "length_cm": length_cm,
            "is_trophy": is_trophy,
            "variant": variant,
            "variant_emoji": v_meta["emoji"],
            "score": score,
        }


def settle_fishing_duel(
    guild_id: int | str,
    p1_id: int | str,
    p1_name: str,
    p2_id: int | str,
    p2_name: str,
    winner_id: Optional[int | str],
    wager: int = 0,
) -> Tuple[bool, str, int]:
    """1:1 낚시 대결 승패 기록 및 내기 골드 안전 정산"""
    safe_wager = max(0, int(wager or 0))
    with _FISHING_LOCK:
        data = core.load_data()
        u1 = ensure_fishing_user(data, guild_id, p1_id, p1_name)
        u2 = ensure_fishing_user(data, guild_id, p2_id, p2_name)
        if winner_id is None:
            core.save_data(data)
            return True, "🤝 극적인 **무승부!** 내기 골드는 변동 없이 양측 모두 반환되었습니다.", 0

        if str(winner_id) == str(p1_id):
            win_u, lose_u = u1, u2
        else:
            win_u, lose_u = u2, u1

        transferred = min(safe_wager, max(0, _safe_int(lose_u.get("gold"), 0)))
        if transferred > 0:
            lose_u["gold"] -= transferred
            win_u["gold"] += transferred
            win_u["total_gold_earned"] = _safe_int(win_u.get("total_gold_earned"), 0) + transferred
        win_u["duel_wins"] = _safe_int(win_u.get("duel_wins"), 0) + 1
        lose_u["duel_losses"] = _safe_int(lose_u.get("duel_losses"), 0) + 1
        core.save_data(data)
        wager_txt = f" · 내기 상금 **`+{transferred:,}🪙`** 획득!" if transferred > 0 else ""
        return True, f"🏆 **{win_u['name']}**님 대결 승리!{wager_txt}", transferred


# ==========================================
# 서버 협동 거대 대어 보스 레이드 엔진
# ==========================================
def _ensure_guild_boss_root(data: Dict[str, Any], guild_id: int | str) -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    root = core.ensure_dict_path(data, "fishing_boss_raids", g_key)
    if not isinstance(root.get("history"), list):
        root["history"] = []
    return root


def _create_boss_instance(sp: Dict[str, Any], now_dt: datetime.datetime, spawner_name: str, auto: bool = False) -> Dict[str, Any]:
    ends_dt = now_dt + datetime.timedelta(minutes=int(sp["duration_min"]))
    return {
        "uid": uuid.uuid4().hex[:8],
        "boss_id": sp["id"],
        "name": sp["name"],
        "emoji": sp["emoji"],
        "desc": sp["desc"],
        "max_hp": int(sp["max_hp"]),
        "hp": int(sp["max_hp"]),
        "base_gold": int(sp["base_gold"]),
        "pool_gold": int(sp["pool_gold"]),
        "base_crystals": int(sp["base_crystals"]),
        "pool_crystals": int(sp["pool_crystals"]),
        "bait_id": sp["bait_id"],
        "bait_qty": int(sp["bait_qty"]),
        "spawner_name": spawner_name,
        "is_auto": auto,
        "started_at": now_dt.isoformat(),
        "ends_at": ends_dt.isoformat(),
        "defeated": False,
        "participants": {},
    }


def _expire_boss_if_needed_unlocked(root: Dict[str, Any], now_dt: datetime.datetime) -> bool:
    active = root.get("active")
    if not isinstance(active, dict) or active.get("defeated"):
        return False
    try:
        ends_dt = datetime.datetime.fromisoformat(str(active.get("ends_at")))
        if ends_dt.tzinfo is None:
            ends_dt = ends_dt.replace(tzinfo=core.KST)
        if now_dt > ends_dt:
            active["expired"] = True
            hist = list(root.get("history") or [])
            hist.insert(0, {
                "name": active.get("name"),
                "emoji": active.get("emoji"),
                "defeated": False,
                "ended_at": now_dt.strftime("%Y-%m-%d %H:%M"),
                "participants_cnt": len(core.as_dict(active.get("participants"))),
                "mvp_name": "-",
            })
            root["history"] = hist[:15]
            root["active"] = None
            root["last_ended_at"] = now_dt.isoformat()
            return True
    except Exception:
        pass
    return False


def _maybe_auto_spawn_boss_unlocked(
    data: Dict[str, Any],
    guild_id: int | str,
    env: Dict[str, Any],
    trigger_user_name: str,
) -> Optional[Dict[str, Any]]:
    """폭풍우(8%) 또는 피딩타임(3.5%) 중 활성 보스가 없을 때 서버 대어 보스를 돌발 소환합니다."""
    root = _ensure_guild_boss_root(data, guild_id)
    now_dt = env.get("now") or datetime.datetime.now(core.KST)
    _expire_boss_if_needed_unlocked(root, now_dt)
    if isinstance(root.get("active"), dict) and not root["active"].get("defeated"):
        return None
    last_end = root.get("last_ended_at")
    if last_end:
        try:
            le_dt = datetime.datetime.fromisoformat(str(last_end))
            if le_dt.tzinfo is None:
                le_dt = le_dt.replace(tzinfo=core.KST)
            if (now_dt - le_dt).total_seconds() < BOSS_SPAWN_COOLDOWN_SEC:
                return None
        except Exception:
            pass
    prob = 0.08 if env.get("weather_id") == "storm" else (0.035 if env.get("feeding_time") else 0.0)
    if prob <= 0 or random.random() >= prob:
        return None
    sp = random.choice(BOSS_SPECIES_POOL)
    boss = _create_boss_instance(sp, now_dt, f"⛈️ 자연 돌발 ({trigger_user_name}님 목격)", auto=True)
    root["active"] = boss
    return copy.deepcopy(boss)


def get_fishing_boss_status(guild_id: int | str) -> Dict[str, Any]:
    """현재 서버의 협동 대어 보스 레이드 현황 반환"""
    with _FISHING_LOCK:
        data = core.load_data()
        now_dt = datetime.datetime.now(core.KST)
        root = _ensure_guild_boss_root(data, guild_id)
        dirty = _expire_boss_if_needed_unlocked(root, now_dt)
        if dirty:
            core.save_data(data)

        active = root.get("active")
        remain_str = ""
        cooldown_rem_min = 0
        rankings: List[Dict[str, Any]] = []
        if isinstance(active, dict) and not active.get("defeated"):
            try:
                ends_dt = datetime.datetime.fromisoformat(str(active.get("ends_at")))
                if ends_dt.tzinfo is None:
                    ends_dt = ends_dt.replace(tzinfo=core.KST)
                rem_sec = max(0, int((ends_dt - now_dt).total_seconds()))
                m, s = divmod(rem_sec, 60)
                remain_str = f"{m}분 {s}초"
            except Exception:
                remain_str = "진행 중"
            for uid_s, p in core.as_dict(active.get("participants")).items():
                if isinstance(p, dict):
                    rankings.append({
                        "user_id": str(uid_s),
                        "user_name": str(p.get("user_name") or f"출조사({uid_s[:4]})"),
                        "damage": _safe_int(p.get("damage"), 0),
                        "hits": _safe_int(p.get("hits"), 0),
                    })
            rankings.sort(key=lambda r: (-r["damage"], -r["hits"]))
        else:
            last_end = root.get("last_ended_at")
            if last_end:
                try:
                    le_dt = datetime.datetime.fromisoformat(str(last_end))
                    if le_dt.tzinfo is None:
                        le_dt = le_dt.replace(tzinfo=core.KST)
                    rem_cd = BOSS_SPAWN_COOLDOWN_SEC - (now_dt - le_dt).total_seconds()
                    if rem_cd > 0:
                        cooldown_rem_min = max(1, int((rem_cd + 59) // 60))
                except Exception:
                    pass

        return {
            "active": copy.deepcopy(active) if isinstance(active, dict) else None,
            "rankings": rankings,
            "remain_str": remain_str,
            "cooldown_rem_min": cooldown_rem_min,
            "history": copy.deepcopy((root.get("history") or [])[:8]),
        }


def spawn_fishing_boss(
    guild_id: int | str,
    spawner_id: int | str,
    spawner_name: str,
    boss_id: Optional[str] = None,
    bypass_cooldown: bool = False,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """서버 협동 대어 보스를 수동 소환합니다 (토벌/만료 후 20분 쿨타임)."""
    with _FISHING_LOCK:
        data = core.load_data()
        now_dt = datetime.datetime.now(core.KST)
        root = _ensure_guild_boss_root(data, guild_id)
        _expire_boss_if_needed_unlocked(root, now_dt)
        if isinstance(root.get("active"), dict) and not root["active"].get("defeated"):
            return False, f"⚠️ 이미 `{root['active']['emoji']} {root['active']['name']}` 레이드가 진행 중입니다!", copy.deepcopy(root["active"])

        if not bypass_cooldown and root.get("last_ended_at"):
            try:
                le_dt = datetime.datetime.fromisoformat(str(root["last_ended_at"]))
                if le_dt.tzinfo is None:
                    le_dt = le_dt.replace(tzinfo=core.KST)
                rem = BOSS_SPAWN_COOLDOWN_SEC - (now_dt - le_dt).total_seconds()
                if rem > 0:
                    rem_m = max(1, int((rem + 59) // 60))
                    return False, f"⏳ 해역이 아직 잠잠합니다! **`{rem_m}분`** 후에 새 대어 보스를 소환할 수 있습니다.", None
            except Exception:
                pass

        sp = next((b for b in BOSS_SPECIES_POOL if b["id"] == boss_id), None) or random.choice(BOSS_SPECIES_POOL)
        boss = _create_boss_instance(sp, now_dt, spawner_name or f"출조사({str(spawner_id)[:4]})", auto=False)
        root["active"] = boss
        core.save_data(data)
        return True, f"🚨 **거대 대어 출현 경보!!** {boss['emoji']} **`{boss['name']}`** (HP `{boss['max_hp']:,}`)이(가) 해역에 나타났습니다!", copy.deepcopy(boss)


def attack_fishing_boss(
    guild_id: int | str,
    user_id: int | str,
    user_name: str,
    bypass_cooldown: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """진행 중인 서버 대어 보스에게 합동 릴 당기기 공격을 가합니다. HP 0 도달 시 전원 보상 지급!"""
    cd_key = (int(guild_id or 0), int(user_id))
    now_mono = time.monotonic()
    with _FISHING_LOCK:
        if not bypass_cooldown:
            last_t = _BOSS_ATTACK_LAST.get(cd_key, 0.0)
            elapsed = now_mono - last_t
            if elapsed < BOSS_ATTACK_COOLDOWN_SEC:
                rem = max(0.5, round(BOSS_ATTACK_COOLDOWN_SEC - elapsed, 1))
                return False, f"⏳ 릴을 다시 감는 중입니다! **`{rem:.1f}초`** 후에 다시 당겨주세요.", {}

        data = core.load_data()
        now_dt = datetime.datetime.now(core.KST)
        root = _ensure_guild_boss_root(data, guild_id)
        _expire_boss_if_needed_unlocked(root, now_dt)
        boss = root.get("active")
        if not isinstance(boss, dict) or boss.get("defeated"):
            return False, "ℹ️ 현재 진행 중인 보스 레이드가 없습니다! `[🌊 보스 소환]` 버튼으로 대어를 불러내세요.", {}

        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        rod = RODS[u["rod_id"]]
        reel = REELS[u["reel_id"]]
        net = NETS.get(u.get("net_id"))
        enh = get_gear_enhance_bonuses(u)

        base_dmg = (
            120
            + int(rod["tier"]) * 48
            + int(reel["tier"]) * 32
            + (int(net["tier"]) * 24 if net else 0)
            + min(30, _safe_int(u.get("level"), 1)) * 6
        )
        base_dmg = int(round(base_dmg * enh["boss_dmg_mult"] * random.uniform(0.88, 1.16)))
        is_crit = random.random() < (0.16 + reel["trophy_bonus"] * 0.40)
        dmg = int(round(base_dmg * 1.65)) if is_crit else base_dmg
        dmg = max(50, dmg)

        prev_hp = max(0, _safe_int(boss.get("hp"), 0))
        actual_dmg = min(prev_hp, dmg)
        boss["hp"] = max(0, prev_hp - actual_dmg)

        p_map = boss.setdefault("participants", {})
        uid_s = str(user_id)
        p_ent = p_map.get(uid_s)
        if not isinstance(p_ent, dict):
            p_ent = {"user_name": user_name or u["name"], "damage": 0, "hits": 0}
            p_map[uid_s] = p_ent
        p_ent["user_name"] = user_name or u["name"]
        p_ent["damage"] = _safe_int(p_ent.get("damage"), 0) + actual_dmg
        p_ent["hits"] = _safe_int(p_ent.get("hits"), 0) + 1

        _BOSS_ATTACK_LAST[cd_key] = now_mono

        defeated_now = boss["hp"] <= 0
        rewards_summary: List[Dict[str, Any]] = []
        if defeated_now:
            boss["defeated"] = True
            total_dmg = max(1, sum(_safe_int(p.get("damage"), 0) for p in p_map.values() if isinstance(p, dict)))
            ranked_p = sorted(
                [(k, v) for k, v in p_map.items() if isinstance(v, dict)],
                key=lambda kv: -_safe_int(kv[1].get("damage"), 0),
            )
            mvp_id = ranked_p[0][0] if ranked_p else uid_s
            mvp_name = ranked_p[0][1].get("user_name", user_name) if ranked_p else user_name
            b_bait_id = boss.get("bait_id") or "glow"
            b_bait_qty = max(1, _safe_int(boss.get("bait_qty"), 2))

            for rank_i, (p_uid, p_info) in enumerate(ranked_p, 1):
                share = _safe_int(p_info.get("damage"), 0) / total_dmg
                g_gain = int(round(boss["base_gold"] + boss["pool_gold"] * share + (1500 if p_uid == mvp_id else 0)))
                c_gain = int(round(boss["base_crystals"] + boss["pool_crystals"] * share + (60 if p_uid == mvp_id else 0)))
                pu = ensure_fishing_user(data, guild_id, p_uid, p_info.get("user_name", ""))
                pprof = core.ensure_user_profile(data, p_uid, p_info.get("user_name", ""))
                pu["gold"] = _safe_int(pu.get("gold"), 0) + g_gain
                pu["total_gold_earned"] = _safe_int(pu.get("total_gold_earned"), 0) + g_gain
                pu["boss_defeats"] = _safe_int(pu.get("boss_defeats"), 0) + 1
                pprof["crystals"] = _safe_int(pprof.get("crystals"), 0) + c_gain
                if b_bait_id in BAITS:
                    p_baits = core.ensure_dict_path(pu, "baits")
                    p_baits[b_bait_id] = _safe_int(p_baits.get(b_bait_id), 0) + b_bait_qty
                rewards_summary.append({
                    "rank": rank_i,
                    "user_id": p_uid,
                    "user_name": p_info.get("user_name", "출조사"),
                    "damage": _safe_int(p_info.get("damage"), 0),
                    "gold": g_gain,
                    "crystals": c_gain,
                    "bait_name": BAITS.get(b_bait_id, {}).get("name", "특급 미끼"),
                    "bait_qty": b_bait_qty,
                    "is_mvp": p_uid == mvp_id,
                })

            hist = list(root.get("history") or [])
            hist.insert(0, {
                "name": boss["name"],
                "emoji": boss["emoji"],
                "defeated": True,
                "ended_at": now_dt.strftime("%Y-%m-%d %H:%M"),
                "participants_cnt": len(ranked_p),
                "mvp_name": mvp_name,
            })
            root["history"] = hist[:15]
            root["active"] = None
            root["last_ended_at"] = now_dt.isoformat()

        core.save_data(data)
        crit_txt = " 💥 **치명타!**" if is_crit else ""
        if defeated_now:
            return (
                True,
                f"🎉 **토벌 완료!!** {boss['emoji']} **{boss['name']}**에게 마지막 일격 `-{actual_dmg:,}`{crit_txt}으로 쓰러뜨렸습니다! 참가자 `{len(rewards_summary)}명` 전원에게 보상이 지급되었습니다!",
                {"damage": actual_dmg, "is_crit": is_crit, "defeated": True, "hp": 0, "rewards": rewards_summary, "boss_name": boss["name"], "boss_emoji": boss["emoji"]},
            )
        return (
            True,
            f"🎣 **{boss['name']}**에게 **`-{actual_dmg:,}`** 피해!{crit_txt} (남은 HP: `{boss['hp']:,} / {boss['max_hp']:,}`)",
            {"damage": actual_dmg, "is_crit": is_crit, "defeated": False, "hp": boss["hp"], "max_hp": boss["max_hp"]},
        )


def purchase_shop_item(guild_id: int | str, user_id: int | str, category: str, item_id: str) -> Tuple[bool, str]:
    if category == "tank_theme":
        return buy_or_equip_tank_theme(guild_id, user_id, item_id)
    if category == "enhance":
        ok, msg, _ = enhance_fishing_gear(guild_id, user_id, item_id)
        return ok, msg
    if category == "craft":
        ok, msg, _ = craft_bait_from_bag(guild_id, user_id, item_id)
        return ok, msg

    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        gold = int(u.get("gold", 0))

        if category == "rod":
            rod = RODS.get(item_id)
            if not rod:
                return False, "❌ 존재하지 않는 낚싯대입니다."
            if item_id in u["owned_rods"]:
                u["rod_id"] = item_id
                core.save_data(data)
                return True, f"{rod['emoji']} 이미 보유 중인 **{rod['name']}**을(를) 즉시 장착했습니다!"
            if gold < rod["price"]:
                return False, f"❌ 낚시 골드가 부족합니다! (필요: `{rod['price']:,}🪙` / 보유: `{gold:,}🪙`)"
            u["gold"] -= rod["price"]
            u["owned_rods"].append(item_id)
            u["rod_id"] = item_id
            core.save_data(data)
            return True, f"🎉 {rod['emoji']} **{rod['name']}** 구매 및 장착 완료! (`-{rod['price']:,}🪙`)"

        if category == "reel":
            reel = REELS.get(item_id)
            if not reel:
                return False, "❌ 존재하지 않는 릴입니다."
            if item_id in u["owned_reels"]:
                u["reel_id"] = item_id
                core.save_data(data)
                return True, f"{reel['emoji']} 이미 보유 중인 **{reel['name']}**을(를) 즉시 장착했습니다!"
            if gold < reel["price"]:
                return False, f"❌ 낚시 골드가 부족합니다! (필요: `{reel['price']:,}🪙` / 보유: `{gold:,}🪙`)"
            u["gold"] -= reel["price"]
            u["owned_reels"].append(item_id)
            u["reel_id"] = item_id
            core.save_data(data)
            return True, f"🎉 {reel['emoji']} **{reel['name']}** 구매 및 장착 완료! (`-{reel['price']:,}🪙`)"

        if category == "net":
            if item_id == "none":
                if u.get("net_id") is None:
                    return False, "ℹ️ 현재 장착 중인 그물이 없습니다. (기본 1마리 낚시 상태)"
                u["net_id"] = None
                core.save_data(data)
                return True, "🚫 그물을 장착 해제했습니다. 이제 기본 1마리씩 정밀 낚시를 진행합니다."
            net = NETS.get(item_id)
            if not net:
                return False, "❌ 존재하지 않는 그물입니다."
            if item_id in u["owned_nets"]:
                u["net_id"] = item_id
                core.save_data(data)
                return True, f"{net['emoji']} 이미 보유 중인 **{net['name']}**을(를) 즉시 장착했습니다! (1회 `{net['min_catch']}~{net['max_catch']}마리` 포획)"
            if gold < net["price"]:
                return False, f"❌ 낚시 골드가 부족합니다! (필요: `{net['price']:,}🪙` / 보유: `{gold:,}🪙`)"
            u["gold"] -= net["price"]
            u["owned_nets"].append(item_id)
            u["net_id"] = item_id
            core.save_data(data)
            return True, f"🎉 {net['emoji']} **{net['name']}** 구매 및 장착 완료! (`-{net['price']:,}🪙` · 1회 `{net['min_catch']}~{net['max_catch']}마리` 포획)"

        if category == "bait":
            bait = BAITS.get(item_id)
            if not bait or bait.get("unlimited"):
                u["selected_bait"] = "dough"
                core.save_data(data)
                return True, "🍡 기본 곡물 떡밥으로 장착했습니다."
            if bait.get("craft_only"):
                return False, f"🧪 **{bait['name']}**은(는) 상점 구매 불가 미끼입니다! `🧪 미끼제작` 탭에서 소형어를 분해해 제작하세요."
            cost = int(bait["price_per_pack"])
            qty = int(bait["pack_qty"])
            if gold < cost:
                return False, f"❌ 낚시 골드가 부족합니다! (필요: `{cost:,}🪙` / 보유: `{gold:,}🪙`)"
            u["gold"] -= cost
            u["baits"][item_id] = int(u["baits"].get(item_id, 0)) + qty
            u["selected_bait"] = item_id
            core.save_data(data)
            return True, f"🎉 {bait['emoji']} **{bait['name']} ×{qty}개** 구매 & 장착! (총 `{u['baits'][item_id]}개`)"

        if category == "tank_expand":
            cur_slots = int(u.get("tank_slots", 4))
            if cur_slots >= 20:
                return False, "🏆 이미 수족관이 최대 크기(20슬롯)까지 확장되었습니다!"
            cost = 600 + (cur_slots - 4) * 500
            if gold < cost:
                return False, f"❌ 수족관 확장 골드가 부족합니다! (필요: `{cost:,}🪙` / 보유: `{gold:,}🪙`)"
            u["gold"] -= cost
            u["tank_slots"] = cur_slots + 2
            core.save_data(data)
            return True, f"🐠 수족관 전시 슬롯이 `{cur_slots} → {u['tank_slots']}칸`으로 확장되었습니다! (`-{cost:,}🪙`)"

        if category == "bag_expand":
            nxt = get_next_bag_upgrade(u)
            if not nxt:
                return False, f"🏆 이미 낚시 가방이 최대 용량(`{BAG_CAPACITY_TIERS[-1]:,}칸`)까지 확장되었습니다!"
            cur_cap = int(nxt["cur_cap"])
            next_cap = int(nxt["next_cap"])
            cost = int(nxt["price"])
            if item_id not in ("expand", str(next_cap)):
                if str(item_id).isdigit() and int(item_id) <= cur_cap:
                    return False, f"✅ 이미 `{cur_cap:,}칸` 이상으로 확장되어 있습니다! 다음 단계는 `{next_cap:,}칸 ({cost:,}🪙)`입니다."
                req_str = f"{int(item_id):,}칸" if str(item_id).isdigit() else str(item_id)
                return False, f"⚠️ 가방 확장은 단계별 순차 업그레이드만 가능합니다! 현재 `{cur_cap:,}칸` → 다음 단계 `{next_cap:,}칸 ({cost:,}🪙)`을 먼저 구매해 주세요. (선택: {req_str})"
            if gold < cost:
                return False, f"❌ 가방 확장 골드가 부족합니다! (`{cur_cap:,}→{next_cap:,}칸` 필요: `{cost:,}🪙` / 보유: `{gold:,}🪙`)"
            u["gold"] -= cost
            u["bag_capacity"] = next_cap
            core.save_data(data)
            return True, (
                f"{nxt['emoji']} **{nxt['tier_name']}** 구매 완료! "
                f"낚시 가방 한도가 `{cur_cap:,} → {next_cap:,}마리`로 확장되었습니다! (`-{cost:,}🪙` · 잔액 `{u['gold']:,}🪙`)"
            )

        return False, "❌ 알 수 없는 상점 상품 분류입니다."


def claim_all_completed_quests(guild_id: int | str, user_id: int | str, user_name: str = "") -> Tuple[bool, str, int, int]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)
        claimed_cnt = 0
        gain_gold = 0
        gain_cry = 0
        for q in (core.as_dict(u.get("daily_quests")).get("items") or []):
            if isinstance(q, dict) and not q.get("claimed") and int(q.get("progress", 0)) >= int(q.get("target", 1)):
                q["claimed"] = True
                claimed_cnt += 1
                gain_gold += int(q.get("gold", 0))
                gain_cry += int(q.get("crystals", 0))
        if claimed_cnt == 0:
            return False, "ℹ️ 아직 수령 가능한 완료 의뢰가 없습니다.", 0, 0
        u["gold"] += gain_gold
        u["total_gold_earned"] = int(u.get("total_gold_earned", 0)) + gain_gold
        prof["crystals"] = int(prof.get("crystals", 0)) + gain_cry
        core.save_data(data)
        return True, f"🎁 일일 낚시 의뢰 **`{claimed_cnt}건`** 보상 수령! (`+{gain_gold:,}🪙` · `+{gain_cry:,}💎`)", gain_gold, gain_cry


# ==========================================
# 도감 통계 · 서버 최대어/도감 랭킹 조회
# ==========================================
_TOTAL_BY_RARITY: Dict[int, int] = {
    r: sum(1 for sp in FISH_SPECIES_DB if sp["rarity"] == r)
    for r in range(1, 6)
}


def get_fishing_pokedex_stats(guild_id: int | str, user_id: int | str) -> Dict[str, Any]:
    with _FISHING_LOCK:
        data = core.get_cached_data_ro()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        pd = copy.deepcopy(core.safe_get_dict(data, "fishing_users", g_key, u_key, "pokedex"))

    owned_by_hab = {"lake": 0, "river": 0, "sea": 0}
    owned_by_zone: Dict[Tuple[str, str], int] = {}
    owned_by_rar = {r: 0 for r in range(1, 6)}
    owned_total = 0
    max_crowns = 0
    min_crowns = 0
    variant_species_cnt = 0
    variant_counts = {"golden": 0, "albino": 0, "abyssal": 0}

    for sp_id, rec in pd.items():
        sp = FISH_BY_ID.get(sp_id)
        if not sp:
            continue
        owned_total += 1
        hab = sp.get("habitat", "lake")
        if hab in owned_by_hab:
            owned_by_hab[hab] += 1
        z = sp.get("zone") or sp.get("sub_zone") or ""
        owned_by_zone[(hab, z)] = owned_by_zone.get((hab, z), 0) + 1
        r = int(sp.get("rarity", 1))
        if r in owned_by_rar:
            owned_by_rar[r] += 1
        if isinstance(rec, dict):
            if rec.get("max_crown"):
                max_crowns += 1
            if rec.get("min_crown"):
                min_crowns += 1
            v_list = rec.get("variants")
            if isinstance(v_list, list) and v_list:
                variant_species_cnt += 1
                for vk in v_list:
                    if vk in variant_counts:
                        variant_counts[vk] += 1

    by_habitat: Dict[str, Dict[str, int]] = {}
    by_zone: Dict[str, Dict[str, Dict[str, int]]] = {}
    for hab in ("lake", "river", "sea"):
        all_sp = FISH_BY_HABITAT[hab]
        by_habitat[hab] = {"owned": owned_by_hab[hab], "total": len(all_sp)}
        z_map: Dict[str, Dict[str, int]] = {}
        for z in CANONICAL_ZONES[hab]:
            z_sp = FISH_BY_ZONE.get((hab, z), [])
            z_map[z] = {
                "owned": owned_by_zone.get((hab, z), 0),
                "total": len(z_sp),
            }
        by_zone[hab] = z_map

    by_rarity: Dict[int, Dict[str, int]] = {
        r: {"owned": owned_by_rar[r], "total": _TOTAL_BY_RARITY[r]}
        for r in range(1, 6)
    }

    total_species = len(FISH_SPECIES_DB)
    return {
        "total_species": total_species,
        "owned_total": owned_total,
        "by_habitat": by_habitat,
        "by_zone": by_zone,
        "by_rarity": by_rarity,
        "max_crowns": max_crowns,
        "min_crowns": min_crowns,
        "variant_species_cnt": variant_species_cnt,
        "variant_counts": variant_counts,
        "pokedex": pd,
    }



def get_fishing_leaderboard(guild_id: int | str, habitat_filter: str = "all") -> Dict[str, Any]:
    data = core.get_cached_data_ro()
    g_key = str(guild_id or 0)
    rec_map = core.safe_get_dict(data, "fishing_records", g_key)
    u_map = core.safe_get_dict(data, "fishing_users", g_key)

    len_records: List[Dict[str, Any]] = []
    wt_records: List[Dict[str, Any]] = []
    len_record_counts: Dict[str, int] = {}
    wt_record_counts: Dict[str, int] = {}

    for fid, r_obj in rec_map.items():
        if not isinstance(r_obj, dict):
            continue
        sp = FISH_BY_ID.get(fid)
        if not sp:
            continue
        if habitat_filter != "all" and sp["habitat"] != habitat_filter:
            continue
        trophy_cut = sp["min_cm"] + (sp["max_cm"] - sp["min_cm"]) * 0.80
        m_len = r_obj.get("max_cm")
        if isinstance(m_len, dict):
            val_cm = _safe_float(m_len.get("val"), 0.0)
            uid_s = str(m_len.get("user_id") or "")
            if uid_s:
                len_record_counts[uid_s] = len_record_counts.get(uid_s, 0) + 1
            len_records.append({
                "fish_id": fid,
                "name": sp["name"],
                "scientific_name": sp["scientific_name"],
                "sub_zone": sp["sub_zone"],
                "rarity": sp["rarity"],
                "habitat": sp["habitat"],
                "emoji": sp["emoji"],
                "min_cm": sp["min_cm"],
                "max_cm": sp["max_cm"],
                "is_trophy": val_cm >= trophy_cut,
                "val": val_cm,
                "user_id": m_len.get("user_id"),
                "user_name": m_len.get("user_name") or "낚시꾼",
                "at": m_len.get("at") or "",
            })
        m_wt = r_obj.get("max_kg")
        if isinstance(m_wt, dict):
            uid_s = str(m_wt.get("user_id") or "")
            if uid_s:
                wt_record_counts[uid_s] = wt_record_counts.get(uid_s, 0) + 1
            wt_records.append({
                "fish_id": fid,
                "name": sp["name"],
                "scientific_name": sp["scientific_name"],
                "sub_zone": sp["sub_zone"],
                "rarity": sp["rarity"],
                "habitat": sp["habitat"],
                "emoji": sp["emoji"],
                "min_cm": sp["min_cm"],
                "max_cm": sp["max_cm"],
                "val": _safe_float(m_wt.get("val"), 0.0),
                "user_id": m_wt.get("user_id"),
                "user_name": m_wt.get("user_name") or "낚시꾼",
                "at": m_wt.get("at") or "",
            })

    len_records.sort(key=lambda x: (-x["val"], -x["rarity"]))
    wt_records.sort(key=lambda x: (-x["val"], -x["rarity"]))

    dex_ranks: List[Dict[str, Any]] = []
    ranker_profiles: Dict[str, Dict[str, Any]] = {}
    for uid_s, u_obj in u_map.items():
        if not isinstance(u_obj, dict):
            continue
        pd = core.as_dict(u_obj.get("pokedex"))
        if habitat_filter == "all":
            cnt = len(pd)
        else:
            cnt = sum(1 for fid in pd if FISH_BY_ID.get(fid, {}).get("habitat") == habitat_filter)
        rod = RODS.get(u_obj.get("rod_id", "bamboo"), RODS["bamboo"])
        reel = REELS.get(u_obj.get("reel_id", "basic_reel"), REELS["basic_reel"])
        net = NETS.get(u_obj.get("net_id"))
        u_name = u_obj.get("name") or f"User({uid_s[:4]})"
        entry = {
            "user_id": uid_s,
            "user_name": u_name,
            "pokedex_cnt": cnt,
            "total_catches": _safe_int(u_obj.get("total_catches"), 0),
            "total_trophy": _safe_int(u_obj.get("total_trophy"), 0),
            "gold": _safe_int(u_obj.get("gold"), 0),
            "tank_cnt": len(core.coerce_list_like(u_obj.get("tank"))),
            "level": max(1, _safe_int(u_obj.get("level"), 1)),
            "rod_name": rod["name"],
            "rod_emoji": rod["emoji"],
            "reel_name": reel["name"],
            "reel_emoji": reel["emoji"],
            "net_name": net["name"] if net else "미장착",
            "net_emoji": net["emoji"] if net else "🚫",
            "net_range": f"{net['min_catch']}~{net['max_catch']}마리" if net else "1마리",
            "len_records_held": len_record_counts.get(uid_s, 0),
            "wt_records_held": wt_record_counts.get(uid_s, 0),
        }
        dex_ranks.append(entry)
        ranker_profiles[uid_s] = entry
    dex_ranks.sort(key=lambda x: (-x["pokedex_cnt"], -x["total_catches"]))

    return {
        "length_top": len_records,
        "weight_top": wt_records,
        "dex_top": dex_ranks,
        "ranker_profiles": ranker_profiles,
        "total_species_count": len(FISH_SPECIES_DB) if habitat_filter == "all" else len(FISH_BY_HABITAT.get(habitat_filter, [])),
    }


# ==========================================
# 자동완성 (고속 랭킹형 인메모리 DB 검색 - 전체 글로벌 어종 대응)
# ==========================================
def search_fish_species(query: str, limit: Optional[int] = 200, habitat_filter: str = "all") -> List[Dict[str, Any]]:
    """인메모리 인덱스를 이용해 한글/영문/학명/세부수역/설명 키워드로 어종 고속 검색"""
    q = (query or "").strip().lower()
    if not q:
        rows = [row[9] for row in _SEARCH_INDEX]
        if habitat_filter in HABITATS:
            rows = [sp for sp in rows if sp["habitat"] == habitat_filter]
        return rows[:limit] if limit else rows

    buckets: List[List[Dict[str, Any]]] = [[], [], [], [], [], []]
    for _, _, _, _, name_l, sci_l, zone_l, hab_l, desc_l, sp in _SEARCH_INDEX:
        if habitat_filter in HABITATS and sp["habitat"] != habitat_filter:
            continue
        if name_l == q:
            b = buckets[0]
        elif name_l.startswith(q):
            b = buckets[1]
        elif q in name_l:
            b = buckets[2]
        elif q in zone_l or q in hab_l:
            b = buckets[3]
        elif q in sci_l:
            b = buckets[4]
        elif q in desc_l:
            b = buckets[5]
        else:
            continue
        b.append(sp)

    picked: List[Dict[str, Any]] = []
    for b in buckets:
        picked.extend(b)
        if limit and len(picked) >= limit:
            return picked[:limit]
    return picked


async def fish_species_autocomplete(interaction, current: str):
    from discord import app_commands
    q = (current or "").strip()
    picked = _DEFAULT_AUTOCOMPLETE_SPECIES if not q else search_fish_species(q, limit=25)

    cands = []
    for sp in picked[:25]:
        hab = HABITATS.get(sp["habitat"], HABITATS["lake"])
        zone_txt = sp.get("zone") or sp.get("sub_zone", "")
        cands.append(app_commands.Choice(
            name=f"[{hab['name']}·{zone_txt}] ★{sp['rarity']} {sp['name']} ({sp['min_cm']}~{sp['max_cm']}cm)"[:100],
            value=str(sp["id"])[:100],
        ))
    return cands


# ==========================================
# Pillow 포획 인증 카드 PNG 생성기
# ==========================================
def _wrap_card_text_lines(draw, text: str, font, max_w: int, max_lines: int = 3) -> List[str]:
    """어종 설명 문자열을 픽셀 폭 기준으로 자연스럽게 여러 줄로 줄바꿈하여 잘림 없이 반환합니다."""
    clean = (text or "").strip()
    if not clean:
        return []
    if font is None:
        chunk = 44
        return [clean[i:i + chunk] for i in range(0, len(clean), chunk)][:max_lines]

    words = clean.split(" ")
    lines: List[str] = []
    cur = ""
    for w_tok in words:
        cand = f"{cur} {w_tok}".strip() if cur else w_tok
        if draw.textbbox((0, 0), cand, font=font)[2] <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
                cur = ""
            # 단일 토큰이 max_w보다 긴 경우 글자 단위로 분할
            if draw.textbbox((0, 0), w_tok, font=font)[2] <= max_w:
                cur = w_tok
            else:
                sub = ""
                for ch in w_tok:
                    if draw.textbbox((0, 0), sub + ch, font=font)[2] <= max_w:
                        sub += ch
                    else:
                        if sub:
                            lines.append(sub)
                        sub = ch
                cur = sub
    if cur:
        lines.append(cur)

    if len(lines) > max_lines:
        kept = lines[:max_lines - 1]
        tail = " ".join(lines[max_lines - 1:])
        while len(tail) > 4 and draw.textbbox((0, 0), tail + "…", font=font)[2] > max_w:
            tail = tail[:-1].rstrip()
        kept.append(tail + ("…" if tail != " ".join(lines[max_lines - 1:]) else ""))
        return kept
    return lines


def build_catch_card_bytes(
    catch_res: Dict[str, Any],
    user_name: str,
    catch_index: int = 0,
) -> Optional[io.BytesIO]:
    """포획 인증서 고화질 PNG 카드 생성 (변이 오라 · 최대 금관/최소 은관 · 특수 낚시터 · 다중 포획 지원)"""
    if Image is None or ImageDraw is None:
        return None
    try:
        catches = catch_res.get("catches")
        if isinstance(catches, list) and catches:
            idx = max(0, min(int(catch_index or 0), len(catches) - 1))
            selected = catches[idx] if isinstance(catches[idx], dict) else {}
            fish = selected.get("fish") or catch_res["fish"]
            sp = selected.get("species") or catch_res["species"]
            is_first_catch = bool(selected.get("is_first_catch", catch_res.get("is_first_catch")))
            new_len_rec = bool(selected.get("new_server_len_record", catch_res.get("new_server_len_record")))
            new_wt_rec = bool(selected.get("new_server_wt_record", catch_res.get("new_server_wt_record")))
            total_cards = len(catches)
        else:
            idx = 0
            fish = catch_res["fish"]
            sp = catch_res["species"]
            is_first_catch = bool(catch_res.get("is_first_catch"))
            new_len_rec = bool(catch_res.get("new_server_len_record"))
            new_wt_rec = bool(catch_res.get("new_server_wt_record"))
            total_cards = 1

        env = catch_res["env"]
        hab = HABITATS.get(sp.get("habitat", "lake"), HABITATS["lake"])
        spot_meta = catch_res.get("spot") or SPECIAL_SPOTS.get(str(fish.get("spot_id") or ""))
        rmeta = RARITY_META.get(int(sp.get("rarity", 1)), RARITY_META[1])
        v_id = str(fish.get("variant") or "normal")
        v_meta = get_variant_meta(v_id)
        crown_id = fish.get("crown")

        w, h = 880, 456
        img = Image.new("RGBA", (w, h), (10, 18, 34, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # 서식지/특수터 + 성급/변이 그라데이션 배경
        base_r, base_g, base_b = (spot_meta["rgb"] if isinstance(spot_meta, dict) and spot_meta.get("rgb") else hab["rgb"])
        rar_r, rar_g, rar_b = (v_meta["rgb"] if v_meta.get("rgb") else rmeta["rgb"])
        for y in range(h):
            t = y / h
            r = int(10 + base_r * 0.16 * (1 - t) + rar_r * 0.12 * t)
            g = int(18 + base_g * 0.18 * (1 - t) + rar_g * 0.12 * t)
            b = int(36 + base_b * 0.24 * (1 - t) + rar_b * 0.16 * t)
            draw.line([(0, y), (w, y)], fill=(min(255, r), min(255, g), min(255, b), 255))

        # 물결 데코 라인
        for wave_i in range(4):
            wy = 345 + wave_i * 22
            pts = []
            for x in range(0, w + 20, 20):
                pts.append((x, wy + int(math.sin(x * 0.025 + wave_i * 1.1) * 6)))
            draw.line(pts, fill=(rar_r, rar_g, rar_b, 48 + wave_i * 12), width=2)

        # 메인 프레임 보더
        border_w = 5 if v_id != "normal" else 4
        draw.rounded_rectangle([14, 14, w - 14, h - 14], radius=24, outline=(rar_r, rar_g, rar_b, 235), width=border_w)
        draw.rounded_rectangle([24, 24, w - 24, h - 24], radius=18, outline=(255, 255, 255, 45), width=1)

        font_title = core._get_grid_font(34, bold=True)
        font_hdr = core._get_grid_font(22, bold=True)
        font_med = core._get_grid_font(20, bold=False)
        font_sm = core._get_grid_font(16, bold=False)

        # 좌측 어종 심볼 서클 카드 (+ 변이 발광 오라)
        cx, cy = 152, 212
        if v_id != "normal" and v_meta.get("rgb"):
            vr, vg, vb = v_meta["rgb"]
            draw.ellipse([cx - 108, cy - 108, cx + 108, cy + 108], fill=(vr, vg, vb, 38))
            draw.ellipse([cx - 101, cy - 101, cx + 101, cy + 101], outline=(vr, vg, vb, 160), width=2)
        draw.ellipse([cx - 96, cy - 96, cx + 96, cy + 96], fill=(16, 28, 52, 238), outline=(rar_r, rar_g, rar_b, 235), width=4)
        draw.ellipse([cx - 82, cy - 82, cx + 82, cy + 82], outline=(255, 255, 255, 48), width=1)

        # 심플 벡터 물고기 실루엣 렌더링 (변이별 커스텀 컬러 & 눈/지느러미 표현)
        if v_meta.get("body_rgb"):
            br, bg, bb = v_meta["body_rgb"]
            body_col = (br, bg, bb, 248)
        else:
            rr, rg, rb = rmeta["rgb"]
            body_col = (rr, rg, rb, 238)
        fin_col = (103, 232, 249, 235) if v_id == "abyssal" else ((255, 230, 140, 235) if v_id == "golden" else (base_r, base_g, base_b, 235))
        tail_pts = [(cx - 64, cy - 26), (cx - 32, cy), (cx - 64, cy + 26)]
        draw.polygon(tail_pts, fill=body_col)
        draw.ellipse([cx - 42, cy - 32, cx + 56, cy + 32], fill=body_col)
        draw.polygon([(cx - 10, cy - 30), (cx + 18, cy - 52), (cx + 26, cy - 26)], fill=fin_col)
        if v_id == "abyssal":
            # 심해 발광 스팟
            for sx, sy in [(cx - 14, cy - 6), (cx + 2, cy + 6), (cx + 16, cy - 4)]:
                draw.ellipse([sx - 4, sy - 4, sx + 4, sy + 4], fill=(103, 232, 249, 235))
        draw.ellipse([cx + 28, cy - 12, cx + 40, cy], fill=(255, 255, 255, 255))
        pupil_col = (239, 68, 68, 255) if v_id == "albino" else ((56, 189, 248, 255) if v_id == "abyssal" else (12, 18, 30, 255))
        draw.ellipse([cx + 32, cy - 9, cx + 38, cy - 3], fill=pupil_col)

        # 좌측 하단 성급 배지 (& 다중 포획 시 카드 순번 표시)
        star_txt = core._sanitize_grid_text(rmeta["full_stars"])
        sb = draw.textbbox((0, 0), star_txt, font=font_hdr)
        sw = sb[2] - sb[0]
        draw.text((cx - sw // 2, cy + 110), star_txt, font=font_hdr, fill=(rar_r, rar_g, rar_b, 255))
        if total_cards > 1:
            seq_txt = core._sanitize_grid_text(f"포획 카드 {idx + 1} / {total_cards}")
            seq_b = draw.textbbox((0, 0), seq_txt, font=font_sm)
            seq_w = seq_b[2] - seq_b[0]
            draw.text((cx - seq_w // 2, cy + 140), seq_txt, font=font_sm, fill=(180, 215, 255, 235))

        # 우측 헤더: 서식지/특수터 & 도장 배지
        rx = 282
        sub_z = sp.get("sub_zone") or sp.get("zone") or ""
        loc_tag = f"{spot_meta['name']}" if isinstance(spot_meta, dict) else f"{hab['name']} · {sub_z}"
        hab_tag = core._sanitize_grid_text(f"[{loc_tag}]  |  {rmeta['name']} ({rmeta['stars']})")
        draw.text((rx, 42), hab_tag, font=font_sm, fill=(175, 215, 255, 240))

        # 특수 도장 (변이 / 금관·은관 / 신기록 / 월척 / 첫도감 / 다중)
        catch_count = max(total_cards, _safe_int(catch_res.get("catch_count"), 1))
        net_info = catch_res.get("net")
        badges = []
        if v_id != "normal" and v_meta.get("badge"):
            vr, vg, vb = v_meta["rgb"] or (250, 204, 21)
            b_fill = (vr, vg, vb, 255)
            txt_col = (20, 26, 40, 255) if v_id in ("golden", "albino") else (255, 255, 255, 255)
            badges.append((v_meta["badge"], b_fill, txt_col))
        if crown_id in CROWN_META:
            cm = CROWN_META[crown_id]
            cr, cg, cb = cm["rgb"]
            badges.append((cm["badge"], (cr, cg, cb, 255), (255, 255, 255, 255)))
        if total_cards > 1:
            badges.append((f"#{idx + 1}/{total_cards}마리", (14, 165, 233, 255), (255, 255, 255, 255)))
        if new_len_rec or new_wt_rec:
            badges.append(("서버 신기록!", (245, 158, 11, 255), (255, 255, 255, 255)))
        if fish.get("is_trophy") and crown_id != "max_gold":
            badges.append(("월척 대물", (239, 68, 68, 255), (255, 255, 255, 255)))
        if is_first_catch:
            badges.append(("NEW 도감", (16, 185, 129, 255), (255, 255, 255, 255)))

        bx_cur = w - 42
        for b_txt, b_col, t_col in badges[:3]:
            b_clean = core._sanitize_grid_text(b_txt)
            bb = draw.textbbox((0, 0), b_clean, font=font_sm)
            bw = (bb[2] - bb[0]) + 22
            bx_cur -= bw
            draw.rounded_rectangle([bx_cur, 36, bx_cur + bw, 66], radius=12, fill=b_col)
            draw.text((bx_cur + 11, 41), b_clean, font=font_sm, fill=t_col)
            bx_cur -= 8

        # 어종명 & 학명
        fish_name = core._sanitize_grid_text(fish["name"])
        if font_title is not None and fish_name:
            raw_name = fish_name
            cut_n = len(raw_name)
            max_title_w = w - rx - 42
            while cut_n > 6 and draw.textbbox((0, 0), fish_name, font=font_title)[2] > max_title_w:
                cut_n -= 1
                fish_name = raw_name[:cut_n].rstrip() + "…"
        draw.text((rx, 80), fish_name, font=font_title, fill=(255, 255, 255, 255))
        sci_name = core._sanitize_grid_text(f"{sp['scientific_name']}")
        draw.text((rx, 126), sci_name, font=font_med, fill=(180, 200, 230, 215))

        # 크기 · 무게 · 가치 메트릭 박스 3칸
        card_y = 166
        box_w = 176
        box_h = 92
        val_lbl = f"개체 가치 (#{idx + 1})" if total_cards > 1 else "추정 가치"
        val_gold = _safe_int(fish.get("gold"), 0)
        metrics = [
            ("체장 (Length)", f"{fish['length_cm']:.1f} cm", (56, 189, 248, 255)),
            ("무게 (Weight)", f"{fish['weight_kg']:.2f} kg" if fish['weight_kg'] >= 0.2 else f"{fish['weight_kg']:.3f} kg", (52, 211, 153, 255)),
            (val_lbl, f"{val_gold:,} G", (250, 204, 21, 255)),
        ]
        for m_i, (m_lbl, m_val, m_col) in enumerate(metrics):
            mx = rx + m_i * (box_w + 14)
            draw.rounded_rectangle([mx, card_y, mx + box_w, card_y + box_h], radius=14, fill=(14, 24, 44, 215), outline=(255, 255, 255, 45), width=1)
            draw.text((mx + 14, card_y + 11), core._sanitize_grid_text(m_lbl), font=font_sm, fill=(170, 190, 220, 230))
            val_clean = core._sanitize_grid_text(m_val)
            draw.text((mx + 14, card_y + 40), val_clean, font=font_hdr, fill=m_col)

        # 하단 어종 설명 박스 (최대 3줄 멀티라인 자동 줄바꿈)
        desc_clean = core._sanitize_grid_text(sp.get("desc", ""))
        max_desc_w = w - rx - 44
        desc_lines = _wrap_card_text_lines(draw, desc_clean, font_sm, max_desc_w, max_lines=3)
        desc_box_y = 272
        desc_box_h = 98
        draw.rounded_rectangle(
            [rx, desc_box_y, w - 34, desc_box_y + desc_box_h],
            radius=12,
            fill=(12, 22, 42, 185),
            outline=(rar_r, rar_g, rar_b, 85),
            width=1,
        )
        line_step = 26 if len(desc_lines) <= 2 else 24
        start_ty = desc_box_y + (desc_box_h - len(desc_lines) * line_step) // 2 - 1
        for l_idx, d_line in enumerate(desc_lines):
            draw.text((rx + 14, start_ty + l_idx * line_step), d_line, font=font_sm, fill=(230, 240, 255, 245))

        enh = catch_res.get("enhance") or {}
        rod_lv = _safe_int(enh.get("rod_lv"), 0)
        rod_name = core._sanitize_grid_text(catch_res["rod"]["name"]) + (f" +{rod_lv}" if rod_lv > 0 else "")
        net_str = f" + {core._sanitize_grid_text(net_info['name'])}" if isinstance(net_info, dict) and catch_count > 1 else ""
        weather_name = core._sanitize_grid_text(env["weather_name"])
        time_txt = "낮" if env["time_phase"] == "day" else "밤"
        combo_val = _safe_int(catch_res.get("combo"), 0)
        combo_str = f"  |  {combo_val}콤보" if combo_val >= 2 else ""
        angler = core._sanitize_grid_text(user_name)[:16]
        footer_txt = core._sanitize_grid_text(f"출조사: {angler}  |  장비: {rod_name}{net_str}{combo_str}  |  {time_txt} · {weather_name}  |  {fish['caught_at']} KST")
        max_footer_w = w - rx - 30
        if font_sm is not None and footer_txt:
            raw_ft = footer_txt
            cut_f = len(raw_ft)
            while cut_f > 16 and draw.textbbox((0, 0), footer_txt, font=font_sm)[2] > max_footer_w:
                cut_f -= 1
                footer_txt = raw_ft[:cut_f].rstrip() + "..."
        draw.text((rx, 392), footer_txt, font=font_sm, fill=(160, 185, 220, 215))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img.close()
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"⚠️ [fishing_core] 포획 카드 PNG 렌더링 예외: {e}", flush=True)
        return None


def build_aquarium_card_bytes(
    summary: Dict[str, Any],
    owner_name: str,
) -> Optional[io.BytesIO]:
    """개인 수족관에 전시된 물고기들을 테마 배경·기포·빛줄기와 함께 920x520 고화질 PNG 스냅샷으로 렌더링합니다."""
    if Image is None or ImageDraw is None:
        return None
    try:
        u = summary.get("user") if isinstance(summary, dict) else {}
        if not isinstance(u, dict):
            u = {}
        raw_tank = u.get("tank", [])
        tank = [it for it in (raw_tank if isinstance(raw_tank, list) else []) if isinstance(it, dict)]
        max_slots = _safe_int(u.get("tank_slots"), 4)
        theme_id = str(u.get("tank_theme") or "coral")
        theme = TANK_THEMES.get(theme_id, TANK_THEMES["coral"])
        hourly = _safe_int(summary.get("tank_hourly"), 0)
        feed_active = bool(summary.get("tank_feed_active", False))

        w, h = 920, 520
        img = Image.new("RGBA", (w, h), (8, 22, 42, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        tr, tg, tb = theme["top_rgb"]
        br, bg, bb = theme["bot_rgb"]
        ar, ag, ab = theme["accent_rgb"]

        # 수조 배경 수직 그라데이션
        for y in range(h):
            t = y / h
            r = int(tr * (1 - t) + br * t)
            g = int(tg * (1 - t) + bg * t)
            b = int(tb * (1 - t) + bb * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

        # 테마별 배경 연출 (빛줄기 / 달빛 / 오로라 / 심해 네온)
        if theme_id == "coral":
            for ray_x in (140, 360, 610, 790):
                draw.polygon([(ray_x, 0), (ray_x + 70, 0), (ray_x + 150, h - 80), (ray_x + 25, h - 80)], fill=(120, 240, 235, 18))
            # 모래 바닥 + 산호
            draw.rectangle([0, h - 68, w, h], fill=(194, 168, 120, 120))
            for cx_pos, col_c in [(90, (244, 114, 182, 165)), (210, (251, 146, 60, 155)), (740, (45, 212, 191, 155)), (845, (244, 114, 182, 155))]:
                draw.ellipse([cx_pos - 28, h - 108, cx_pos + 28, h - 42], fill=col_c)
                draw.ellipse([cx_pos - 16, h - 126, cx_pos + 16, h - 70], fill=col_c)
        elif theme_id == "deep_sea":
            for gx, gy, gr in [(160, 410, 75), (480, 440, 90), (770, 390, 70)]:
                draw.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=(ar, ag, ab, 28))
            draw.rectangle([0, h - 58, w, h], fill=(16, 12, 38, 190))
            for px, py in [(120, 140), (260, 210), (410, 130), (630, 190), (780, 150), (540, 310), (310, 340)]:
                draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(103, 232, 249, 175))
        elif theme_id == "night_pond":
            # 보름달 & 수면 반사
            draw.ellipse([750, 70, 842, 162], fill=(254, 243, 199, 215))
            draw.ellipse([736, 56, 856, 176], fill=(250, 204, 21, 35))
            for lx in (150, 390, 620):
                draw.ellipse([lx - 26, h - 72, lx + 26, h - 52], fill=(34, 197, 94, 145))
                draw.ellipse([lx - 9, h - 82, lx + 9, h - 64], fill=(251, 191, 36, 180))
        else:  # glacier
            for band_i, b_col in enumerate([(56, 189, 248, 32), (168, 85, 247, 28), (45, 212, 191, 30)]):
                pts = [(x, 105 + band_i * 22 + int(math.sin(x * 0.012 + band_i) * 20)) for x in range(0, w + 20, 20)]
                draw.line(pts, fill=b_col, width=18)
            draw.polygon([(0, h - 45), (140, h - 125), (270, h - 45)], fill=(186, 230, 253, 85))
            draw.polygon([(660, h - 45), (795, h - 135), (920, h - 45)], fill=(186, 230, 253, 85))
            draw.rectangle([0, h - 52, w, h], fill=(186, 230, 253, 95))

        # 상승 공기방울 데코
        for bi in range(18):
            bx = 55 + (bi * 49) % (w - 110)
            by = 95 + (bi * 73) % (h - 170)
            br_rad = 3 + (bi % 4) * 2
            draw.ellipse([bx - br_rad, by - br_rad, bx + br_rad, by + br_rad], outline=(220, 245, 255, 110), width=1)

        # 유리 수조 프레임 & 상단 헤더 바
        draw.rounded_rectangle([12, 12, w - 12, h - 12], radius=22, outline=(ar, ag, ab, 210), width=4)
        draw.rounded_rectangle([22, 22, w - 22, 74], radius=14, fill=(8, 18, 34, 195), outline=(255, 255, 255, 45), width=1)

        font_hdr = core._get_grid_font(22, bold=True)
        font_sm = core._get_grid_font(15, bold=False)
        font_xs = core._get_grid_font(13, bold=False)

        owner_clean = core._sanitize_grid_text(owner_name)[:16]
        theme_clean = core._sanitize_grid_text(theme["name"])
        hdr_left = core._sanitize_grid_text(f"{owner_clean}님의 수족관  |  {theme_clean} ({len(tank)}/{max_slots}칸)")
        draw.text((38, 36), hdr_left, font=font_hdr, fill=(255, 255, 255, 248))

        buff_tag = "  [먹이 +35%]" if feed_active else ""
        hdr_right = core._sanitize_grid_text(f"+{hourly:,} G/h{buff_tag}")
        rb_box = draw.textbbox((0, 0), hdr_right, font=font_sm)
        rw = rb_box[2] - rb_box[0]
        pill_col = (16, 185, 129, 225) if feed_active else (ar, ag, ab, 195)
        draw.rounded_rectangle([w - 40 - rw - 20, 32, w - 34, 64], radius=12, fill=pill_col)
        draw.text((w - 40 - rw - 10, 38), hdr_right, font=font_sm, fill=(10, 18, 30, 255))

        # 전시된 물고기들 렌더링 (최대 20마리, uid 해시 기반 안정적 배치)
        if not tank:
            empty_msg = core._sanitize_grid_text("아직 수족관에 전시된 물고기가 없습니다. 가방에서 대물을 전시해 보세요!")
            eb = draw.textbbox((0, 0), empty_msg, font=font_hdr)
            ew = eb[2] - eb[0]
            draw.text(((w - ew) // 2, h // 2 - 12), empty_msg, font=font_hdr, fill=(210, 230, 250, 210))
        else:
            n_fish = min(20, len(tank))
            cols = 4 if n_fish <= 8 else 5
            rows = max(1, math.ceil(n_fish / cols))
            zone_top, zone_bot = 98, h - 78
            zone_left, zone_right = 68, w - 68
            cell_w = (zone_right - zone_left) / max(1, cols)
            cell_h = (zone_bot - zone_top) / max(1, rows)

            for i, it in enumerate(tank[:20]):
                h_val = int(hashlib.md5(str(it.get("uid") or i).encode("utf-8")).hexdigest()[:8], 16)
                col_i = i % cols
                row_i = i // cols
                jx = ((h_val % 25) - 12)
                jy = (((h_val >> 5) % 21) - 10)
                fx = int(zone_left + (col_i + 0.5) * cell_w + jx)
                fy = int(zone_top + (row_i + 0.5) * cell_h + jy)
                face_right = (h_val & 1) == 0

                rar = max(1, min(5, _safe_int(it.get("rarity"), 1)))
                rm = RARITY_META.get(rar, RARITY_META[1])
                v_id = str(it.get("variant") or "normal")
                v_meta = get_variant_meta(v_id)
                if v_meta.get("body_rgb"):
                    fr, fg, fb = v_meta["body_rgb"]
                else:
                    fr, fg, fb = rm["rgb"]

                scale = 0.72 + (rar - 1) * 0.11 + (0.14 if it.get("is_trophy") else 0.0)
                if n_fish > 12:
                    scale *= 0.82
                bw = int(34 * scale)
                bh = int(18 * scale)
                d = 1 if face_right else -1

                # 변이 발광 오라
                if v_id != "normal" and v_meta.get("rgb"):
                    vr, vg, vb = v_meta["rgb"]
                    draw.ellipse([fx - bw - 10, fy - bh - 10, fx + bw + 10, fy + bh + 10], fill=(vr, vg, vb, 48))

                # 꼬리 + 몸통 + 등지느러미 + 눈
                tail = [(fx - d * (bw + int(16 * scale)), fy - int(14 * scale)), (fx - d * int(bw * 0.65), fy), (fx - d * (bw + int(16 * scale)), fy + int(14 * scale))]
                draw.polygon(tail, fill=(fr, fg, fb, 235))
                draw.ellipse([fx - bw, fy - bh, fx + bw, fy + bh], fill=(fr, fg, fb, 245), outline=(255, 255, 255, 90), width=1)
                fin = [(fx - d * int(6 * scale), fy - bh + 2), (fx + d * int(8 * scale), fy - bh - int(11 * scale)), (fx + d * int(14 * scale), fy - bh + 4)]
                draw.polygon(fin, fill=(ar, ag, ab, 215))
                ex = fx + d * int(bw * 0.52)
                ey = fy - int(bh * 0.22)
                draw.ellipse([ex - 4, ey - 4, ex + 4, ey + 4], fill=(255, 255, 255, 255))
                p_col = (239, 68, 68, 255) if v_id == "albino" else (12, 18, 30, 255)
                draw.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=p_col)

                # 하단 이름 & 크기 캡션
                tag_prefix = "★" if v_id != "normal" else ("*" if it.get("is_trophy") else "")
                nm = core._sanitize_grid_text(f"{tag_prefix}{str(it.get('name', '물고기'))[:8]} {float(it.get('length_cm', 0)):.0f}cm")
                nb = draw.textbbox((0, 0), nm, font=font_xs)
                nw = nb[2] - nb[0]
                draw.rounded_rectangle([fx - nw // 2 - 5, fy + bh + 4, fx + nw // 2 + 5, fy + bh + 22], radius=6, fill=(8, 16, 30, 175))
                draw.text((fx - nw // 2, fy + bh + 5), nm, font=font_xs, fill=(235, 245, 255, 240))

        # 바닥 워터마크
        ft_txt = core._sanitize_grid_text("NOROSI PRIVATE AQUARIUM  |  먹이주기: +35% 수익 & 전시어 성장")
        draw.text((32, h - 38), ft_txt, font=font_xs, fill=(215, 235, 255, 195))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img.close()
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"⚠️ [fishing_core] 수족관 PNG 렌더링 예외: {e}", flush=True)
        return None



# ==========================================
# 주말 낚시 대회 & 계절(제철) 한정 어종 토너먼트 엔진 (#8)
# ==========================================
SEASONS_META: Dict[str, Dict[str, Any]] = {
    "spring": {
        "id": "spring",
        "name": "봄 (Spring)",
        "emoji": "🌸",
        "months": (3, 4, 5),
        "color": 0xF472B6,
        "desc": "따스한 봄바람과 함께 산란기 혼인색이 물든 계류·기수역 어종과 봄 도다리·참돔이 활발합니다.",
        "species_ids": {
            "lake_bitterling", "lake_rose_bitterling", "lake_crucian", "lake_rainbow_trout",
            "river_sweetfish", "river_shiri", "river_cherry_salmon", "river_river_puffer",
            "river_masou_salmon", "sea_halfbeak", "sea_whiting", "sea_surfperch",
        },
        "keywords": ("도다리", "참돔", "볼락", "숭어", "붕어", "송어", "산천어", "황복", "은어", "학꽁치"),
    },
    "summer": {
        "id": "summer",
        "name": "여름 (Summer)",
        "emoji": "☀️",
        "months": (6, 7, 8),
        "color": 0x38BDF8,
        "desc": "수온이 오르며 배스·가물치·민물장어·농어·돌돔·부시리·다랑어 등 폭발적인 입질의 여름 대물이 날뜁니다.",
        "species_ids": {
            "lake_largemouth_bass", "lake_smallmouth_bass", "lake_snakehead", "lake_catfish",
            "lake_peacock_bass", "lake_arapaima", "river_eel", "river_mandarin_fish",
            "river_spotted_seabass", "river_giant_mottled_eel", "river_goliath_tigerfish",
            "sea_korean_rockfish", "sea_mackerel",
        },
        "keywords": ("배스", "가물치", "장어", "메기", "농어", "돌돔", "벤자리", "부시리", "다랑어", "새치", "상어"),
    },
    "autumn": {
        "id": "autumn",
        "name": "가을 (Autumn)",
        "emoji": "🍁",
        "months": (9, 10, 11),
        "color": 0xF59E0B,
        "desc": "가을 전어·주꾸미·삼치·감성돔·연어 소상철! 월동을 앞두고 살이 통통하게 오른 대물 시즌입니다.",
        "species_ids": {
            "lake_carp", "lake_koi", "lake_skygazer", "lake_northern_pike",
            "river_chum_salmon", "river_king_salmon", "river_atlantic_salmon", "river_golden_mandarin",
            "sea_horse_mackerel", "sea_saury", "sea_webfoot_octopus", "sea_spanish_mackerel",
            "sea_yellow_croaker",
        },
        "keywords": ("전어", "주꾸미", "갑오징어", "삼치", "감성돔", "갈치", "연어", "고등어", "꽁치", "잉어"),
    },
    "winter": {
        "id": "winter",
        "name": "겨울 (Winter)",
        "emoji": "❄️",
        "months": (12, 1, 2),
        "color": 0x60A5FA,
        "desc": "얼음 호수의 빙어·공어·레이크트라우트와 겨울 바다의 꽃 대방어·대구·우럭·감성돔이 제철을 맞습니다.",
        "species_ids": {
            "lake_smelt", "lake_pond_smelt", "lake_lake_trout", "lake_walleye",
            "lake_baikal_omul", "lake_siberian_sturgeon", "river_lenok", "river_kumgang_minnow",
            "sea_rockfish_inermis", "sea_fat_greenling", "sea_herring", "sea_yellowfin_goby",
        },
        "keywords": ("빙어", "공어", "방어", "대구", "명태", "열목어", "우럭", "노래미", "청어", "철갑상어", "심해"),
    },
}

TOURNAMENT_MODES: Dict[str, Dict[str, Any]] = {
    "max_cm": {
        "id": "max_cm",
        "name": "최장어 대물전 (Max Length)",
        "short": "📏 최장어(cm)",
        "emoji": "📏",
        "unit": "cm",
        "desc": "대회 기간 중 가장 길이가 긴 단일 대물(cm)을 낚은 출조사가 우승합니다! (제철 어종은 체장 환산 +15% 보너스)",
    },
    "total_kg": {
        "id": "total_kg",
        "name": "만선 합산 중량전 (Total Weight)",
        "short": "⚖️ 합산 중량(kg)",
        "emoji": "⚖️",
        "unit": "kg",
        "desc": "대회 기간 중 포획한 모든 물고기의 누적 무게(kg) 합산이 가장 높은 출조사가 우승합니다!",
    },
    "seasonal_pts": {
        "id": "seasonal_pts",
        "name": "계절 제철 포인트전 (Seasonal Trophy)",
        "short": "🌸 제철 포인트(pt)",
        "emoji": "🌸",
        "unit": "pt",
        "desc": "어종 성급·체장·월척 점수를 합산하며, 현재 계절의 제철 보너스 어종 포획 시 점수가 1.5배로 적용됩니다!",
    },
}

TOURNAMENT_PRIZES: List[Dict[str, Any]] = [
    {"rank": 1, "label": "🥇 1위 (챔피언)", "gold": 15000, "crystals": 500, "trophy": 1},
    {"rank": 2, "label": "🥈 2위 (준우승)", "gold": 8000, "crystals": 300, "trophy": 0},
    {"rank": 3, "label": "🥉 3위 (입상)", "gold": 4000, "crystals": 150, "trophy": 0},
]
TOURNAMENT_PARTICIPATION_PRIZE = {"gold": 1000, "crystals": 30}


def get_current_season_meta(now_dt: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    dt = now_dt or datetime.datetime.now(core.KST)
    m = dt.month
    for s_id, meta in SEASONS_META.items():
        if m in meta["months"]:
            return meta
    return SEASONS_META["spring"]


def is_seasonal_bonus_species(sp: Dict[str, Any], season_id: Optional[str] = None) -> bool:
    if not isinstance(sp, dict):
        return False
    s_meta = SEASONS_META.get(season_id or "") or get_current_season_meta()
    fid = str(sp.get("id") or "")
    if fid in s_meta["species_ids"]:
        return True
    name_str = str(sp.get("name") or "")
    return any(kw in name_str for kw in s_meta["keywords"])


def get_seasonal_featured_species(season_id: Optional[str] = None, habitat_filter: str = "all", limit: int = 18) -> List[Dict[str, Any]]:
    s_meta = SEASONS_META.get(season_id or "") or get_current_season_meta()
    s_id = s_meta["id"]
    matched: List[Dict[str, Any]] = []
    seen = set()
    for fid in s_meta["species_ids"]:
        sp = FISH_BY_ID.get(fid)
        if sp and (habitat_filter == "all" or sp.get("habitat") == habitat_filter):
            matched.append(sp)
            seen.add(fid)
    for sp in _FALLBACK_ORIGINAL_140:
        fid = sp["id"]
        if fid in seen:
            continue
        if habitat_filter != "all" and sp.get("habitat") != habitat_filter:
            continue
        if is_seasonal_bonus_species(sp, s_id):
            matched.append(sp)
            seen.add(fid)
    matched.sort(key=lambda x: (-int(x.get("rarity", 1)), -float(x.get("max_cm", 0))))
    return matched[:limit]


def compute_tournament_catch_points(fish: Dict[str, Any], sp: Dict[str, Any], season_id: Optional[str] = None) -> Tuple[int, bool]:
    """단일 물고기 포획의 계절 토너먼트 포인트 및 제철 어종 여부 계산."""
    rarity = max(1, _safe_int(sp.get("rarity") or fish.get("rarity"), 1))
    base_pts = {1: 25, 2: 55, 3: 130, 4: 320, 5: 800}.get(rarity, 25)
    length_cm = max(0.1, _safe_float(fish.get("length_cm"), 10.0))
    max_cm = max(1.0, _safe_float(sp.get("max_cm"), length_cm))
    size_ratio = min(1.2, length_cm / max_cm)
    pts = int(round(base_pts * (0.75 + size_ratio * 0.55)))
    if fish.get("is_trophy"):
        pts = int(round(pts * 1.35))
    v_id = str(fish.get("variant") or "normal")
    if v_id == "abyssal":
        pts = int(round(pts * 2.20))
    elif v_id == "albino":
        pts = int(round(pts * 1.85))
    elif v_id == "golden":
        pts = int(round(pts * 1.60))
    seasonal = is_seasonal_bonus_species(sp, season_id)
    if seasonal:
        pts = int(round(pts * 1.50))
    return max(10, pts), seasonal


def _ensure_guild_tournament_root(data: Dict[str, Any], guild_id: int | str) -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    root = core.ensure_dict_path(data, "fishing_tournaments", g_key)
    if not isinstance(root.get("history"), list):
        root["history"] = []
    return root


def _build_auto_weekend_tournament(now_dt: datetime.datetime, guild_id: int | str) -> Optional[Dict[str, Any]]:
    """토요일(5)·일요일(6) KST에는 주말 자동 낚시 대회를 생성합니다."""
    if now_dt.weekday() not in (5, 6):
        return None
    sat_date = (now_dt - datetime.timedelta(days=(now_dt.weekday() - 5))).date()
    sun_date = sat_date + datetime.timedelta(days=1)
    start_dt = datetime.datetime.combine(sat_date, datetime.time(0, 0, 0), tzinfo=core.KST)
    end_dt = datetime.datetime.combine(sun_date, datetime.time(23, 59, 59), tzinfo=core.KST)
    season = get_current_season_meta(now_dt)
    # 주차별로 3가지 대회 모드를 자동 순환
    iso_week = sat_date.isocalendar()[1]
    mode_order = ["seasonal_pts", "max_cm", "total_kg"]
    mode_id = mode_order[iso_week % len(mode_order)]
    m_meta = TOURNAMENT_MODES[mode_id]
    return {
        "id": f"weekend_{sat_date.isoformat()}",
        "title": f"{season['emoji']} 주말 정규 낚시 토너먼트 ({m_meta['short']})",
        "guild_id": int(guild_id or 0),
        "mode": mode_id,
        "habitat": "all",
        "season_id": season["id"],
        "is_auto_weekend": True,
        "host_id": 0,
        "host_name": "🤖 주말 자동 개최",
        "started_at": start_dt.isoformat(),
        "ends_at": end_dt.isoformat(),
        "settled": False,
        "participants": {},
    }


def _rank_tournament_participants(tourney: Dict[str, Any]) -> List[Dict[str, Any]]:
    mode = str(tourney.get("mode") or "seasonal_pts")
    p_map = core.as_dict(tourney.get("participants"))
    rows: List[Dict[str, Any]] = []
    for uid_s, p in p_map.items():
        if not isinstance(p, dict):
            continue
        score_cm = _safe_float(p.get("score_cm") or p.get("max_cm"), 0.0)
        raw_cm = _safe_float(p.get("max_cm"), 0.0)
        total_kg = _safe_float(p.get("total_kg"), 0.0)
        seasonal_pts = _safe_int(p.get("seasonal_pts"), 0)
        catch_cnt = _safe_int(p.get("catch_count"), 0)
        if catch_cnt <= 0:
            continue
        if mode == "max_cm":
            primary_score = score_cm
        elif mode == "total_kg":
            primary_score = total_kg
        else:
            primary_score = float(seasonal_pts)
        rows.append({
            "user_id": str(uid_s),
            "user_name": str(p.get("user_name") or f"낚시꾼({uid_s[:4]})"),
            "primary_score": primary_score,
            "score_cm": round(score_cm, 1),
            "max_cm": round(raw_cm, 1),
            "max_kg": round(_safe_float(p.get("max_kg"), 0.0), 3),
            "total_kg": round(total_kg, 2),
            "seasonal_pts": seasonal_pts,
            "catch_count": catch_cnt,
            "seasonal_catches": _safe_int(p.get("seasonal_catches"), 0),
            "best_fish_name": str(p.get("best_fish_name") or "물고기"),
            "best_fish_emoji": str(p.get("best_fish_emoji") or "🐟"),
            "best_fish_rarity": _safe_int(p.get("best_fish_rarity"), 1),
            "best_is_seasonal": bool(p.get("best_is_seasonal", False)),
            "updated_at": str(p.get("updated_at") or ""),
        })
    rows.sort(key=lambda r: (-r["primary_score"], -r["max_cm"], -r["catch_count"]))
    for idx, r in enumerate(rows, 1):
        r["rank"] = idx
    return rows


def _settle_tournament_unlocked(data: Dict[str, Any], guild_id: int | str, tourney: Dict[str, Any]) -> Dict[str, Any]:
    """락 내부에서 만료/종료된 대회 보상을 참가자들에게 지급하고 히스토리에 기록합니다."""
    ranked = _rank_tournament_participants(tourney)
    now_iso = datetime.datetime.now(core.KST).isoformat()
    awarded: List[Dict[str, Any]] = []
    for row in ranked:
        uid = row["user_id"]
        uname = row["user_name"]
        u_fish = ensure_fishing_user(data, guild_id, uid, uname)
        prof = core.ensure_user_profile(data, uid, uname)
        rank = row["rank"]
        prize = next((p for p in TOURNAMENT_PRIZES if p["rank"] == rank), None)
        if prize:
            g_gain = int(prize["gold"])
            c_gain = int(prize["crystals"])
            t_gain = int(prize["trophy"])
            badge = prize["label"]
        else:
            g_gain = int(TOURNAMENT_PARTICIPATION_PRIZE["gold"])
            c_gain = int(TOURNAMENT_PARTICIPATION_PRIZE["crystals"])
            t_gain = 0
            badge = f"🎖️ {rank}위 (완주 보상)"
        u_fish["gold"] = _safe_int(u_fish.get("gold"), 0) + g_gain
        u_fish["total_gold_earned"] = _safe_int(u_fish.get("total_gold_earned"), 0) + g_gain
        if t_gain > 0:
            u_fish["tournament_wins"] = _safe_int(u_fish.get("tournament_wins"), 0) + t_gain
        prof["crystals"] = _safe_int(prof.get("crystals"), 0) + c_gain
        awarded.append({
            **row,
            "badge": badge,
            "reward_gold": g_gain,
            "reward_crystals": c_gain,
            "reward_trophy": t_gain,
        })

    tourney["settled"] = True
    tourney["settled_at"] = now_iso
    tourney["final_rankings"] = awarded[:15]
    root = _ensure_guild_tournament_root(data, guild_id)
    hist = list(root.get("history") or [])
    hist.insert(0, copy.deepcopy(tourney))
    root["history"] = hist[:20]
    root["active"] = None
    return tourney


def _record_tournament_catch_unlocked(
    data: Dict[str, Any],
    guild_id: int | str,
    user_id: int | str,
    user_name: str,
    habitat: str,
    catches: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """finalize_fish_catch 내부(이미 _FISHING_LOCK 보유 중)에서 호출되어 대회 기록 및 제철 보너스를 반영합니다."""
    now_dt = datetime.datetime.now(core.KST)
    root = _ensure_guild_tournament_root(data, guild_id)
    active = root.get("active")

    # 기존 대회가 만료되었으면 자동 정산
    if isinstance(active, dict) and not active.get("settled"):
        try:
            ends_dt = datetime.datetime.fromisoformat(str(active.get("ends_at")))
            if ends_dt.tzinfo is None:
                ends_dt = ends_dt.replace(tzinfo=core.KST)
            if now_dt > ends_dt:
                _settle_tournament_unlocked(data, guild_id, active)
                active = None
        except Exception:
            pass

    # 주말이고 활성 대회가 없으면 주말 자동 대회 활성화
    if not isinstance(active, dict) or active.get("settled"):
        auto_wk = _build_auto_weekend_tournament(now_dt, guild_id)
        if auto_wk:
            hist_ids = {str(h.get("id")) for h in (root.get("history") or []) if isinstance(h, dict)}
            if auto_wk["id"] not in hist_ids:
                root["active"] = auto_wk
                active = auto_wk

    if not isinstance(active, dict) or active.get("settled"):
        return None

    req_hab = str(active.get("habitat") or "all")
    if req_hab != "all" and req_hab != habitat:
        return None

    season_id = str(active.get("season_id") or get_current_season_meta(now_dt)["id"])
    prev_ranks = _rank_tournament_participants(active)
    prev_leader_id = prev_ranks[0]["user_id"] if prev_ranks else None

    p_map = active.setdefault("participants", {})
    uid_s = str(user_id)
    entry = p_map.get(uid_s)
    if not isinstance(entry, dict):
        entry = {
            "user_id": uid_s,
            "user_name": user_name,
            "max_cm": 0.0,
            "score_cm": 0.0,
            "max_kg": 0.0,
            "total_kg": 0.0,
            "seasonal_pts": 0,
            "catch_count": 0,
            "seasonal_catches": 0,
            "best_fish_name": "",
            "best_fish_emoji": "🐟",
            "best_fish_rarity": 1,
            "best_is_seasonal": False,
            "updated_at": "",
        }
        p_map[uid_s] = entry
    entry["user_name"] = user_name or entry.get("user_name") or "낚시꾼"

    gained_pts_total = 0
    gained_kg_total = 0.0
    seasonal_hit_names: List[str] = []
    improved_best = False

    for c in catches:
        f = c["fish"]
        sp = c["species"]
        cm_val = _safe_float(f.get("length_cm"), 0.0)
        kg_val = _safe_float(f.get("weight_kg"), 0.0)
        pts, is_seasonal = compute_tournament_catch_points(f, sp, season_id)
        c["is_seasonal_bonus"] = is_seasonal
        c["tournament_pts"] = pts
        if is_seasonal and f["name"] not in seasonal_hit_names:
            seasonal_hit_names.append(f["name"])

        eff_cm = round(cm_val * (1.15 if is_seasonal else 1.0), 1)
        entry["catch_count"] = _safe_int(entry.get("catch_count"), 0) + 1
        entry["total_kg"] = round(_safe_float(entry.get("total_kg"), 0.0) + kg_val, 3)
        entry["seasonal_pts"] = _safe_int(entry.get("seasonal_pts"), 0) + pts
        if is_seasonal:
            entry["seasonal_catches"] = _safe_int(entry.get("seasonal_catches"), 0) + 1

        if eff_cm > _safe_float(entry.get("score_cm"), 0.0):
            entry["score_cm"] = eff_cm
            entry["max_cm"] = cm_val
            entry["max_kg"] = kg_val
            entry["best_fish_name"] = f["name"]
            entry["best_fish_emoji"] = f["emoji"]
            entry["best_fish_rarity"] = sp["rarity"]
            entry["best_is_seasonal"] = is_seasonal
            improved_best = True
        elif kg_val > _safe_float(entry.get("max_kg"), 0.0):
            entry["max_kg"] = kg_val

        gained_pts_total += pts
        gained_kg_total += kg_val

    entry["updated_at"] = now_dt.strftime("%H:%M:%S")
    new_ranks = _rank_tournament_participants(active)
    my_rank_row = next((r for r in new_ranks if r["user_id"] == uid_s), None)
    my_rank = my_rank_row["rank"] if my_rank_row else 1
    became_leader = (my_rank == 1) and (prev_leader_id != uid_s or improved_best)

    return {
        "tournament_id": active.get("id"),
        "title": active.get("title"),
        "mode": active.get("mode", "seasonal_pts"),
        "rank": my_rank,
        "total_participants": len(new_ranks),
        "became_leader": became_leader,
        "gained_pts": gained_pts_total,
        "gained_kg": round(gained_kg_total, 2),
        "seasonal_hit_names": seasonal_hit_names,
        "entry": copy.deepcopy(my_rank_row or entry),
    }


def get_fishing_tournament_status(guild_id: int | str) -> Dict[str, Any]:
    """현재 서버의 낚시 대회 현황(자동 만료 정산 및 주말 대회 자동 오픈 포함)을 반환합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        now_dt = datetime.datetime.now(core.KST)
        root = _ensure_guild_tournament_root(data, guild_id)
        active = root.get("active")
        dirty = False
        just_settled = None

        if isinstance(active, dict) and not active.get("settled"):
            try:
                ends_dt = datetime.datetime.fromisoformat(str(active.get("ends_at")))
                if ends_dt.tzinfo is None:
                    ends_dt = ends_dt.replace(tzinfo=core.KST)
                if now_dt > ends_dt:
                    just_settled = _settle_tournament_unlocked(data, guild_id, active)
                    active = None
                    dirty = True
            except Exception:
                pass

        if not isinstance(active, dict) or active.get("settled"):
            auto_wk = _build_auto_weekend_tournament(now_dt, guild_id)
            if auto_wk:
                hist_ids = {str(h.get("id")) for h in (root.get("history") or []) if isinstance(h, dict)}
                if auto_wk["id"] not in hist_ids:
                    root["active"] = auto_wk
                    active = auto_wk
                    dirty = True

        if dirty:
            core.save_data(data)

        season = get_current_season_meta(now_dt)
        rankings = _rank_tournament_participants(active) if isinstance(active, dict) else []
        remain_str = ""
        if isinstance(active, dict):
            try:
                ends_dt = datetime.datetime.fromisoformat(str(active.get("ends_at")))
                if ends_dt.tzinfo is None:
                    ends_dt = ends_dt.replace(tzinfo=core.KST)
                rem_sec = max(0, int((ends_dt - now_dt).total_seconds()))
                hrs, rem = divmod(rem_sec, 3600)
                mins, secs = divmod(rem, 60)
                remain_str = f"{hrs}시간 {mins}분" if hrs > 0 else f"{mins}분 {secs}초"
            except Exception:
                remain_str = "진행 중"

        return {
            "active": copy.deepcopy(active) if isinstance(active, dict) else None,
            "rankings": rankings,
            "remain_str": remain_str,
            "season": season,
            "featured_species": get_seasonal_featured_species(season["id"], limit=12),
            "history": copy.deepcopy((root.get("history") or [])[:5]),
            "just_settled": copy.deepcopy(just_settled) if isinstance(just_settled, dict) else None,
        }


def start_fishing_tournament(
    guild_id: int | str,
    host_id: int | str,
    host_name: str,
    mode: str = "seasonal_pts",
    habitat: str = "all",
    duration_min: int = 60,
    custom_title: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    """서버에 새로운 낚시 대회를 개최합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        now_dt = datetime.datetime.now(core.KST)
        root = _ensure_guild_tournament_root(data, guild_id)
        active = root.get("active")
        if isinstance(active, dict) and not active.get("settled"):
            try:
                ends_dt = datetime.datetime.fromisoformat(str(active.get("ends_at")))
                if ends_dt.tzinfo is None:
                    ends_dt = ends_dt.replace(tzinfo=core.KST)
                if now_dt > ends_dt:
                    _settle_tournament_unlocked(data, guild_id, active)
                    active = None
            except Exception:
                pass

        if isinstance(active, dict) and not active.get("settled") and not active.get("is_auto_weekend"):
            return False, f"⚠️ 이미 진행 중인 `{active.get('title', '낚시 대회')}`가 있습니다! 먼저 종료하거나 정산해 주세요.", copy.deepcopy(active)

        # 주말 자동 대회가 진행 중이었는데 커스텀 대회를 여는 경우 기존 주말 대회 참가 기록 보존 정산
        if isinstance(active, dict) and active.get("is_auto_weekend") and active.get("participants"):
            _settle_tournament_unlocked(data, guild_id, active)

        use_mode = mode if mode in TOURNAMENT_MODES else "seasonal_pts"
        use_hab = habitat if habitat in ("all", "lake", "river", "sea") else "all"
        dur = max(10, min(1440, int(duration_min or 60)))
        season = get_current_season_meta(now_dt)
        m_meta = TOURNAMENT_MODES[use_mode]
        hab_lbl = HABITATS[use_hab]["name"] if use_hab in HABITATS else "전 수역"
        title = (custom_title or "").strip()[:80] or f"🏆 {season['emoji']} [{hab_lbl}] {m_meta['name']}"
        end_dt = now_dt + datetime.timedelta(minutes=dur)

        new_tourney = {
            "id": f"tourney_{int(now_dt.timestamp())}",
            "title": title,
            "guild_id": int(guild_id or 0),
            "mode": use_mode,
            "habitat": use_hab,
            "season_id": season["id"],
            "is_auto_weekend": False,
            "host_id": int(host_id or 0),
            "host_name": str(host_name or "개최자")[:40],
            "duration_min": dur,
            "started_at": now_dt.isoformat(),
            "ends_at": end_dt.isoformat(),
            "settled": False,
            "participants": {},
        }
        root["active"] = new_tourney
        core.save_data(data)
        return True, f"🎉 **`{title}`** 대회가 시작되었습니다! (`{dur}분` 진행 · 종료: `{end_dt.strftime('%H:%M')} KST`)", copy.deepcopy(new_tourney)


def finish_fishing_tournament(guild_id: int | str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """진행 중인 낚시 대회를 즉시 종료하고 순위별 보상을 정산합니다."""
    with _FISHING_LOCK:
        data = core.load_data()
        root = _ensure_guild_tournament_root(data, guild_id)
        active = root.get("active")
        if not isinstance(active, dict) or active.get("settled"):
            return False, "ℹ️ 현재 진행 중인 낚시 대회가 없습니다.", None
        settled = _settle_tournament_unlocked(data, guild_id, active)
        core.save_data(data)
        return True, f"🏅 `{settled.get('title', '낚시 대회')}`가 종료되어 참가자 전원에게 시상 보상이 지급되었습니다!", copy.deepcopy(settled)

