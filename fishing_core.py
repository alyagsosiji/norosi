"""
fishing_core.py - Norosi 통합 낚시 엔진, 글로벌 공개 어종 DB (호수·강·바다 1,300+종),
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
import threading
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
_FISHING_LOCK = threading.RLock()

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
        "desc": "★4 전설 & ★5 신화 대물 전용 비기 미끼 (5개 2,400🪙 / 희귀 ×3.20)",
    },
}


# ==========================================
# 세부 수역 (13개 표준 서식 구역) & 공개 어종 마스터 데이터베이스 (1,330+종 JSON 연동)
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

    _sp("sea_rockfish_inermis", "볼락", "Sebastes inermis", "sea", "방파제 암초 야간", 2, 15.0, 32.0, 0.018, 3.02, 84, "night", "calm" if False else "clear", "shrimp", "🐟", "큰 눈으로 야간에 먹이를 쫓으며 릴을 차고 내려가는 손맛이 중독적인 갯바위의 왕자."),
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


def _load_fish_species_db() -> List[Dict[str, Any]]:
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
                    normalized = [_normalize_fish_entry(sp) for sp in raw if isinstance(sp, dict) and sp.get("id") and sp.get("name")]
                    if len(normalized) >= 140:
                        return normalized
            except Exception as e:
                print(f"⚠️ [fishing_core] JSON 어종 DB 로드 실패({path}): {e}", flush=True)
    return [_normalize_fish_entry(sp) for sp in _FALLBACK_ORIGINAL_140]


FISH_SPECIES_DB: List[Dict[str, Any]] = _load_fish_species_db()

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


def ensure_fishing_user(data: dict, guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    f_users = data.setdefault("fishing_users", {})
    if not isinstance(f_users, dict):
        f_users = {}
        data["fishing_users"] = f_users
    g_map = f_users.setdefault(g_key, {})
    if not isinstance(g_map, dict):
        g_map = {}
        f_users[g_key] = g_map

    u = g_map.get(u_key)
    if not isinstance(u, dict):
        u = {}
        g_map[u_key] = u

    if user_name:
        u["name"] = user_name
    else:
        u.setdefault("name", f"낚시꾼({u_key[:4]})")

    u.setdefault("gold", 300)  # 신규 출조자 초기 정착 지원금
    u.setdefault("exp", 0)
    u.setdefault("level", 1)
    u.setdefault("total_catches", 0)
    u.setdefault("total_trophy", 0)
    u.setdefault("total_gold_earned", 0)
    u.setdefault("rod_id", "bamboo")
    u.setdefault("reel_id", "basic_reel")
    u.setdefault("owned_rods", ["bamboo"])
    u.setdefault("owned_reels", ["basic_reel"])
    u.setdefault("selected_bait", "dough")
    u.setdefault("selected_habitat", "lake")
    u.setdefault("selected_zone", "all")
    u.setdefault("auto_mode", False)
    u.setdefault("baits", {"worm": 5})  # 입문 선물 지렁이 5마리
    u.setdefault("bag", [])
    u.setdefault("pokedex", {})
    u.setdefault("tank", [])
    u.setdefault("tank_slots", 4)
    u.setdefault("last_tank_collect", datetime.datetime.now(core.KST).isoformat())

    today_str = core.get_today_str()
    dq = u.get("daily_quests")
    if not isinstance(dq, dict) or dq.get("date") != today_str or not isinstance(dq.get("items"), list):
        u["daily_quests"] = {
            "date": today_str,
            "items": _pick_daily_quests_for_date(today_str),
        }

    # 유효성 가드
    if u["rod_id"] not in RODS:
        u["rod_id"] = "bamboo"
    if u["reel_id"] not in REELS:
        u["reel_id"] = "basic_reel"
    if u["selected_bait"] not in BAITS:
        u["selected_bait"] = "dough"
    if u["selected_habitat"] not in HABITATS:
        u["selected_habitat"] = "lake"
    if u["selected_zone"] != "all" and u["selected_zone"] not in CANONICAL_ZONES.get(u["selected_habitat"], []):
        u["selected_zone"] = "all"
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
    """수족관 누적 골드와 경과 시간(분) 반환 (최대 24시간 누적)"""
    tank = u.get("tank", [])
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
        hourly_rate += base_r

    pending = int((hourly_rate / 60.0) * capped_min)
    return pending, hourly_rate


# ==========================================
# 출조 준비 · 입질 대상 결정 · 포획 확정 엔진
# ==========================================
def get_user_fishing_summary(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)
        env = get_current_fishing_env()
        pending_tank, hourly_tank = get_tank_pending_gold(u, env["now"])
        lvl, rem_exp, need_exp = _calc_level_from_exp(u.get("exp", 0))
        u["level"] = lvl
        core.save_data(data)
        return {
            "user": copy.deepcopy(u),
            "crystals": int(prof.get("crystals", 0)),
            "env": env,
            "rod": RODS[u["rod_id"]],
            "reel": REELS[u["reel_id"]],
            "bait": BAITS[u["selected_bait"]],
            "tank_pending": pending_tank,
            "tank_hourly": hourly_tank,
            "rem_exp": rem_exp,
            "need_exp": need_exp,
        }


def update_user_fishing_prefs(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
    habitat: Optional[str] = None,
    bait_id: Optional[str] = None,
    auto_mode: Optional[bool] = None,
    zone_filter: Optional[str] = None,
) -> Dict[str, Any]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        if habitat and habitat in HABITATS:
            if u.get("selected_habitat") != habitat and zone_filter is None:
                u["selected_zone"] = "all"
            u["selected_habitat"] = habitat
        if zone_filter is not None:
            if zone_filter == "all" or zone_filter in CANONICAL_ZONES.get(u["selected_habitat"], []):
                u["selected_zone"] = zone_filter
            else:
                u["selected_zone"] = "all"
        if bait_id and bait_id in BAITS:
            u["selected_bait"] = bait_id
        if auto_mode is not None:
            u["auto_mode"] = bool(auto_mode)
        core.save_data(data)
    return get_user_fishing_summary(guild_id, user_id, user_name)


def prepare_cast_parameters(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    """찌 던지기 시작 시 대기시간·당기기 허용시간·사용할 미끼·세부 수역 계산 (아직 미끼 차감 전 단계)"""
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        rod = RODS[u["rod_id"]]
        reel = REELS[u["reel_id"]]
        bait_id = u["selected_bait"]
        if bait_id != "dough" and int(u["baits"].get(bait_id, 0)) <= 0:
            bait_id = "dough"
            u["selected_bait"] = "dough"
            core.save_data(data)
        bait = BAITS[bait_id]
        env = get_current_fishing_env()

        base_wait = random.uniform(1.8, 3.6)
        wait_sec = max(1.1, round(base_wait - reel["wait_reduce"], 2))
        window_sec = float(reel["window_sec"])
        grace_sec = 1.25  # 디스코드/모바일 렌더링 지연 보정 숨은 유예

        return {
            "habitat": u["selected_habitat"],
            "zone_filter": u.get("selected_zone", "all"),
            "bait_id": bait_id,
            "bait": bait,
            "rod": rod,
            "reel": reel,
            "env": env,
            "wait_sec": wait_sec,
            "window_sec": window_sec,
            "grace_sec": grace_sec,
            "auto_mode": bool(u.get("auto_mode", False)),
        }


def _roll_species_weighted(
    habitat: str,
    rod: Dict[str, Any],
    bait: Dict[str, Any],
    env: Dict[str, Any],
    zone_filter: str = "all",
) -> Dict[str, Any]:
    pool = FISH_BY_HABITAT.get(habitat, FISH_BY_HABITAT["lake"])
    rare_factor = (
        (1.0 + rod["rare_bonus"])
        * bait["rare_mult"]
        * env["weather_rare_mult"]
        * env["feeding_mult"]
    )
    # 기본 성급별 가중치: ★1(100), ★2(46), ★3(16), ★4(3.6), ★5(0.85)
    base_rarity_w = {1: 100.0, 2: 46.0, 3: 16.0, 4: 3.6, 5: 0.85}
    use_zone_focus = bool(zone_filter and zone_filter != "all" and zone_filter in CANONICAL_ZONES.get(habitat, []))

    weights: List[float] = []
    for sp in pool:
        r = sp["rarity"]
        w = base_rarity_w.get(r, 10.0)
        if r == 2:
            w *= (1.0 + (rare_factor - 1.0) * 0.25)
        elif r == 3:
            w *= (1.0 + (rare_factor - 1.0) * 0.65)
        elif r == 4:
            w *= (1.0 + (rare_factor - 1.0) * 1.15)
        elif r >= 5:
            w *= (1.0 + (rare_factor - 1.0) * 1.40)

        # 시간대 보정
        atime = sp["active_time"]
        if atime == env["time_phase"]:
            w *= 1.65
        elif atime != "all":
            w *= 0.45

        # 날씨 선호 보정
        pw = sp["prefer_weather"]
        if pw == env["weather_id"]:
            w *= 1.55
        elif pw != "all" and env["weather_id"] != pw:
            w *= 0.80

        # 미끼 선호 보정
        if sp["prefer_bait"] == bait["id"]:
            w *= 1.40

        # 세부 수역 집중 탐색 보너스 (2.2x 가중치)
        if use_zone_focus and sp.get("zone") == zone_filter:
            w *= 2.20

        weights.append(max(0.05, w))

    return random.choices(pool, weights=weights, k=1)[0]


def finalize_fish_catch(
    guild_id: int | str,
    user_id: int | str,
    user_name: str,
    habitat: str,
    bait_id: Optional[str] = None,
    reaction_sec: Optional[float] = None,
    zone_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    채집 성공 시 어종·cm·kg·월척·신기록·도감·가방·일일퀘스트·크리스탈 보너스를 단일 락 안에서 원자적으로 저장합니다.
    """
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)
        env = get_current_fishing_env()

        if habitat not in HABITATS:
            habitat = u["selected_habitat"]

        use_zone = zone_filter if zone_filter is not None else u.get("selected_zone", "all")

        use_bait_id = bait_id or u.get("selected_bait", "dough")
        if use_bait_id not in BAITS:
            use_bait_id = "dough"
        if use_bait_id != "dough":
            cur_qty = int(u["baits"].get(use_bait_id, 0))
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
        bait = BAITS[use_bait_id]

        sp = _roll_species_weighted(habitat, rod, bait, env, zone_filter=use_zone)

        # 체장(cm) 계산: 정규분포 중심 + 장비·날씨·반응속도 보정
        span = sp["max_cm"] - sp["min_cm"]
        mu_ratio = 0.42 + rod["size_bonus"] * 0.25 + (bait["size_mult"] - 1.0) * 0.25 + (env["weather_size_mult"] - 1.0) * 0.35
        # 빠른 챔질 보너스 (0.2s~1.5s 내 반응 시 대물 보정)
        perfect_hook = False
        if reaction_sec is not None and reaction_sec <= 1.8:
            mu_ratio += 0.08
            perfect_hook = True
        ratio = random.gauss(min(0.78, mu_ratio), 0.20)
        # 월척 확률 보정 (릴 + 피딩타임)
        trophy_roll = random.random()
        if trophy_roll < (0.07 + reel["trophy_bonus"] * 0.20):
            ratio = random.uniform(0.84, 1.04)

        ratio = max(0.0, min(1.06, ratio))
        length_cm = round(sp["min_cm"] + span * ratio, 1)
        is_trophy = length_cm >= (sp["min_cm"] + span * 0.82)
        weight_kg = _compute_fish_weight_kg(sp, length_cm)

        # 황금/특대 변이 판정 (희귀 이벤트)
        variant = "normal"
        if random.random() < 0.025:
            variant = "golden"

        # 예상 판매 골드 산정
        size_factor = 0.80 + (ratio * 0.70)
        gold_val = int(sp["base_gold"] * size_factor * (1.0 + rod["gold_bonus"]))
        if is_trophy:
            gold_val = int(gold_val * 1.40)
        if variant == "golden":
            gold_val = int(gold_val * 2.00)
        gold_val = max(10, gold_val)

        # 가방 인스턴스 생성 & 즉시 저장 (증발 방지)
        uid_hex = uuid.uuid4().hex[:8]
        caught_at = env["now"].strftime("%Y-%m-%d %H:%M")
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
            "variant": variant,
            "locked": sp["rarity"] >= 4 or is_trophy,  # 전설/신화/월척 자동 보호
            "caught_at": caught_at,
        }

        bag = u.setdefault("bag", [])
        bag.append(fish_inst)
        # 가방 상한 180마리 초과 시 가장 오래된 미잠금 저등급 1마리 자동 판매 보전
        auto_sold_msg = None
        if len(bag) > 180:
            for idx, old_item in enumerate(bag[:-1]):
                if not old_item.get("locked") and old_item.get("rarity", 1) <= 2:
                    sold_item = bag.pop(idx)
                    u["gold"] += int(sold_item.get("gold", 20))
                    auto_sold_msg = f"가방 초과로 `{sold_item['name']}` 자동 판매 (+{sold_item.get('gold', 20)}🪙)"
                    break

        # 도감 업데이트
        pokedex = u.setdefault("pokedex", {})
        is_first_catch = sp["id"] not in pokedex
        pd_rec = pokedex.get(sp["id"])
        is_personal_len_best = False
        is_personal_wt_best = False
        if not isinstance(pd_rec, dict):
            pd_rec = {
                "count": 1,
                "max_cm": length_cm,
                "max_kg": weight_kg,
                "first_caught": caught_at,
            }
            pokedex[sp["id"]] = pd_rec
            is_personal_len_best = True
            is_personal_wt_best = True
        else:
            pd_rec["count"] = int(pd_rec.get("count", 0)) + 1
            if length_cm > float(pd_rec.get("max_cm", 0)):
                pd_rec["max_cm"] = length_cm
                is_personal_len_best = True
            if weight_kg > float(pd_rec.get("max_kg", 0)):
                pd_rec["max_kg"] = weight_kg
                is_personal_wt_best = True

        # 서버 신기록 체크 (길이 & 무게 독립 기록)
        g_key = str(guild_id or 0)
        f_records = data.setdefault("fishing_records", {})
        if not isinstance(f_records, dict):
            f_records = {}
            data["fishing_records"] = f_records
        g_rec_map = f_records.setdefault(g_key, {})
        sp_rec = g_rec_map.get(sp["id"])
        if not isinstance(sp_rec, dict):
            sp_rec = {}
            g_rec_map[sp["id"]] = sp_rec

        new_server_len_record = False
        new_server_wt_record = False
        prev_len_rec = sp_rec.get("max_cm")
        if not isinstance(prev_len_rec, dict) or length_cm > float(prev_len_rec.get("val", 0)):
            sp_rec["max_cm"] = {
                "val": length_cm,
                "user_id": str(user_id),
                "user_name": user_name,
                "at": caught_at,
            }
            new_server_len_record = True

        prev_wt_rec = sp_rec.get("max_kg")
        if not isinstance(prev_wt_rec, dict) or weight_kg > float(prev_wt_rec.get("val", 0)):
            sp_rec["max_kg"] = {
                "val": weight_kg,
                "user_id": str(user_id),
                "user_name": user_name,
                "at": caught_at,
            }
            new_server_wt_record = True

        # 마일스톤 크리스탈 보너스 계산 & 지급
        crystal_bonus = 0
        bonus_reasons: List[str] = []
        if is_first_catch:
            if sp["rarity"] == 5:
                crystal_bonus += 200
                bonus_reasons.append("★5 신화 첫 도감(+200💎)")
            elif sp["rarity"] == 4:
                crystal_bonus += 100
                bonus_reasons.append("★4 전설 첫 도감(+100💎)")
            elif sp["rarity"] == 3:
                crystal_bonus += 30
                bonus_reasons.append("★3 희귀 첫 도감(+30💎)")
            else:
                crystal_bonus += 10
                bonus_reasons.append("신규 도감 등록(+10💎)")

        if new_server_len_record or new_server_wt_record:
            # 서버 내 최초 등록 외 경쟁 경신일 때도 보너스, 최초도 소액 보너스
            crystal_bonus += 25 if (prev_len_rec or prev_wt_rec) else 15
            bonus_reasons.append("🏆 서버 신기록(+25💎)" if (prev_len_rec or prev_wt_rec) else "🏆 서버 첫 기록(+15💎)")

        if crystal_bonus > 0:
            prof["crystals"] = int(prof.get("crystals", 0)) + crystal_bonus

        # EXP 및 통계 갱신
        gain_exp = 14 + sp["rarity"] * 12 + (18 if is_trophy else 0) + (20 if is_first_catch else 0)
        old_lvl = int(u.get("level", 1))
        u["exp"] = int(u.get("exp", 0)) + gain_exp
        new_lvl, rem_exp, need_exp = _calc_level_from_exp(u["exp"])
        u["level"] = new_lvl
        leveled_up = new_lvl > old_lvl
        if leveled_up:
            u["gold"] += new_lvl * 50

        u["total_catches"] = int(u.get("total_catches", 0)) + 1
        if is_trophy:
            u["total_trophy"] = int(u.get("total_trophy", 0)) + 1

        # 일일 의뢰 진행도 갱신
        for q in u["daily_quests"]["items"]:
            if q.get("claimed"):
                continue
            qtype = q.get("type")
            if qtype == "catch_total":
                q["progress"] = min(q["target"], int(q.get("progress", 0)) + 1)
            elif qtype == f"catch_{habitat}":
                q["progress"] = min(q["target"], int(q.get("progress", 0)) + 1)
            elif qtype == "catch_rare3" and sp["rarity"] >= 3:
                q["progress"] = min(q["target"], int(q.get("progress", 0)) + 1)
            elif qtype == "catch_trophy" and is_trophy:
                q["progress"] = min(q["target"], int(q.get("progress", 0)) + 1)

        core.save_data(data)

        return {
            "fish": fish_inst,
            "species": sp,
            "env": env,
            "rod": rod,
            "reel": reel,
            "bait": bait,
            "is_first_catch": is_first_catch,
            "is_personal_len_best": is_personal_len_best,
            "is_personal_wt_best": is_personal_wt_best,
            "new_server_len_record": new_server_len_record,
            "new_server_wt_record": new_server_wt_record,
            "crystal_bonus": crystal_bonus,
            "bonus_reasons": bonus_reasons,
            "gain_exp": gain_exp,
            "leveled_up": leveled_up,
            "new_level": new_lvl,
            "perfect_hook": perfect_hook,
            "auto_sold_msg": auto_sold_msg,
            "user_gold": int(u["gold"]),
            "user_crystals": int(prof["crystals"]),
            "remaining_bait": int(u["baits"].get(use_bait_id, 0)) if use_bait_id != "dough" else -1,
        }


# ==========================================
# 가방 · 판매 · 수족관 · 상점 · 도감 · 랭킹 · 퀘스트 액션
# ==========================================
def sell_fish_by_uid(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str, int]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        for idx, item in enumerate(bag):
            if item.get("uid") == uid:
                gold = int(item.get("gold", 15))
                name = item.get("name", "물고기")
                bag.pop(idx)
                u["gold"] += gold
                u["total_gold_earned"] = int(u.get("total_gold_earned", 0)) + gold
                for q in u["daily_quests"]["items"]:
                    if q.get("type") == "sell_gold" and not q.get("claimed"):
                        q["progress"] = min(q["target"], int(q.get("progress", 0)) + gold)
                core.save_data(data)
                return True, f"💰 **{name}**을(를) 판매해 **`+{gold:,}🪙`**을 획득했습니다! (보유: `{u['gold']:,}🪙`)", gold
        return False, "⚠️ 이미 판매되었거나 가방에 없는 개체입니다.", 0


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
        kept = []
        sold_cnt = 0
        sold_gold = 0
        for item in bag:
            h_ok = (habitat_filter == "all") or (item.get("habitat") == habitat_filter)
            r_ok = int(item.get("rarity", 1)) <= max_rarity
            if not item.get("locked", False) and h_ok and r_ok:
                sold_cnt += 1
                sold_gold += int(item.get("gold", 15))
            else:
                kept.append(item)
        if sold_cnt == 0:
            return False, "ℹ️ 판매할 수 있는(잠금 해제된) 물고기가 없습니다.", 0, 0
        u["bag"] = kept
        u["gold"] += sold_gold
        u["total_gold_earned"] = int(u.get("total_gold_earned", 0)) + sold_gold
        for q in u["daily_quests"]["items"]:
            if q.get("type") == "sell_gold" and not q.get("claimed"):
                q["progress"] = min(q["target"], int(q.get("progress", 0)) + sold_gold)
        core.save_data(data)
        return True, f"💰 잠금 해제된 물고기 **`{sold_cnt}마리`**를 일괄 판매해 **`+{sold_gold:,}🪙`**를 벌었습니다! (보유: `{u['gold']:,}🪙`)", sold_cnt, sold_gold


def toggle_fish_lock(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        for item in u.get("bag", []):
            if item.get("uid") == uid:
                item["locked"] = not bool(item.get("locked", False))
                state_txt = "🔒 잠금 설정" if item["locked"] else "🔓 잠금 해제"
                core.save_data(data)
                return True, f"{state_txt}: **{item['name']}** (`{item['length_cm']}cm`)"
        return False, "⚠️ 해당 물고기를 가방에서 찾지 못했습니다."


def release_fish_by_uid(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        bag = u.get("bag", [])
        for idx, item in enumerate(bag):
            if item.get("uid") == uid:
                bag.pop(idx)
                bonus_exp = 15 + int(item.get("rarity", 1)) * 12
                u["exp"] = int(u.get("exp", 0)) + bonus_exp
                new_lvl, _, _ = _calc_level_from_exp(u["exp"])
                u["level"] = new_lvl
                core.save_data(data)
                return True, f"🌊 **{item['name']}**을(를) 자연으로 방생했습니다! (`+{bonus_exp} EXP`)"
        return False, "⚠️ 이미 처리되었거나 가방에 없는 개체입니다."


def move_fish_to_tank(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        tank = u.setdefault("tank", [])
        max_slots = int(u.get("tank_slots", 4))
        if len(tank) >= max_slots:
            return False, f"⚠️ 수족관 전시 슬롯(`{len(tank)}/{max_slots}`)이 가득 찼습니다! 상점에서 수족관을 확장하거나 어종을 꺼내주세요."
        bag = u.get("bag", [])
        for idx, item in enumerate(bag):
            if item.get("uid") == uid:
                moved = bag.pop(idx)
                tank.append(moved)
                core.save_data(data)
                return True, f"🐠 **{moved['name']}** (`{moved['length_cm']}cm` · `{moved['weight_kg']}kg`)을(를) 개인 수족관에 전시했습니다! (`{len(tank)}/{max_slots}`)"
        return False, "⚠️ 해당 물고기가 가방에 없습니다."


def remove_fish_from_tank(guild_id: int | str, user_id: int | str, uid: str) -> Tuple[bool, str]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id)
        tank = u.get("tank", [])
        for idx, item in enumerate(tank):
            if item.get("uid") == uid:
                removed = tank.pop(idx)
                u.setdefault("bag", []).append(removed)
                core.save_data(data)
                return True, f"🎒 **{removed['name']}**을(를) 수족관에서 가방으로 회수했습니다."
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
        return True, f"🪙 수족관 관람 수익 **`+{pending:,}🪙`**를 수확했습니다! (현재 보유: `{u['gold']:,}🪙`)", pending


def purchase_shop_item(guild_id: int | str, user_id: int | str, category: str, item_id: str) -> Tuple[bool, str]:
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

        if category == "bait":
            bait = BAITS.get(item_id)
            if not bait or bait.get("unlimited"):
                u["selected_bait"] = "dough"
                core.save_data(data)
                return True, "🍡 기본 곡물 떡밥으로 장착했습니다."
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
            return True, f"🐠 수족관 전시 슬롯이 **`{cur_slots} → {u['tank_slots']}칸`**으로 확장되었습니다! (`-{cost:,}🪙`)"

        return False, "❌ 알 수 없는 상점 상품 분류입니다."


def claim_all_completed_quests(guild_id: int | str, user_id: int | str, user_name: str = "") -> Tuple[bool, str, int, int]:
    with _FISHING_LOCK:
        data = core.load_data()
        u = ensure_fishing_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)
        claimed_cnt = 0
        gain_gold = 0
        gain_cry = 0
        for q in u["daily_quests"]["items"]:
            if not q.get("claimed") and int(q.get("progress", 0)) >= int(q.get("target", 1)):
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
def get_fishing_pokedex_stats(guild_id: int | str, user_id: int | str) -> Dict[str, Any]:
    data = core.get_cached_data()
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    u = data.get("fishing_users", {}).get(g_key, {}).get(u_key, {})
    pd = u.get("pokedex", {}) if isinstance(u, dict) else {}

    by_habitat: Dict[str, Dict[str, int]] = {}
    by_zone: Dict[str, Dict[str, Dict[str, int]]] = {}
    for hab in ("lake", "river", "sea"):
        all_sp = FISH_BY_HABITAT[hab]
        owned_cnt = sum(1 for sp in all_sp if sp["id"] in pd)
        by_habitat[hab] = {"owned": owned_cnt, "total": len(all_sp)}
        z_map: Dict[str, Dict[str, int]] = {}
        for z in CANONICAL_ZONES[hab]:
            z_sp = FISH_BY_ZONE.get((hab, z), [])
            z_map[z] = {
                "owned": sum(1 for sp in z_sp if sp["id"] in pd),
                "total": len(z_sp),
            }
        by_zone[hab] = z_map

    by_rarity: Dict[int, Dict[str, int]] = {}
    for r in range(1, 6):
        r_sp = [sp for sp in FISH_SPECIES_DB if sp["rarity"] == r]
        by_rarity[r] = {
            "owned": sum(1 for sp in r_sp if sp["id"] in pd),
            "total": len(r_sp),
        }

    total_species = len(FISH_SPECIES_DB)
    owned_total = sum(1 for sp in FISH_SPECIES_DB if sp["id"] in pd)
    return {
        "total_species": total_species,
        "owned_total": owned_total,
        "by_habitat": by_habitat,
        "by_zone": by_zone,
        "by_rarity": by_rarity,
        "pokedex": pd,
    }


def get_fishing_leaderboard(guild_id: int | str, habitat_filter: str = "all") -> Dict[str, Any]:
    data = core.get_cached_data()
    g_key = str(guild_id or 0)
    rec_map = data.get("fishing_records", {}).get(g_key, {})
    u_map = data.get("fishing_users", {}).get(g_key, {})

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
            val_cm = float(m_len.get("val", 0))
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
                "user_name": m_len.get("user_name", "낚시꾼"),
                "at": m_len.get("at", ""),
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
                "val": float(m_wt.get("val", 0)),
                "user_id": m_wt.get("user_id"),
                "user_name": m_wt.get("user_name", "낚시꾼"),
                "at": m_wt.get("at", ""),
            })

    len_records.sort(key=lambda x: (-x["val"], -x["rarity"]))
    wt_records.sort(key=lambda x: (-x["val"], -x["rarity"]))

    dex_ranks: List[Dict[str, Any]] = []
    ranker_profiles: Dict[str, Dict[str, Any]] = {}
    for uid_s, u_obj in u_map.items():
        if not isinstance(u_obj, dict):
            continue
        pd = u_obj.get("pokedex", {})
        if habitat_filter == "all":
            cnt = len(pd)
        else:
            cnt = sum(1 for fid in pd if FISH_BY_ID.get(fid, {}).get("habitat") == habitat_filter)
        rod = RODS.get(u_obj.get("rod_id", "bamboo"), RODS["bamboo"])
        reel = REELS.get(u_obj.get("reel_id", "basic_reel"), REELS["basic_reel"])
        u_name = u_obj.get("name", f"User({uid_s[:4]})")
        entry = {
            "user_id": uid_s,
            "user_name": u_name,
            "pokedex_cnt": cnt,
            "total_catches": int(u_obj.get("total_catches", 0)),
            "total_trophy": int(u_obj.get("total_trophy", 0)),
            "gold": int(u_obj.get("gold", 0)),
            "tank_cnt": len(u_obj.get("tank", [])),
            "level": int(u_obj.get("level", 1)),
            "rod_name": rod["name"],
            "rod_emoji": rod["emoji"],
            "reel_name": reel["name"],
            "reel_emoji": reel["emoji"],
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
# 자동완성 (0ms 랭킹형 인메모리 DB 검색 - 1,330+종 전수 대응)
# ==========================================
async def fish_species_autocomplete(interaction, current: str):
    from discord import app_commands
    q = (current or "").strip().lower()
    scored: List[Tuple[int, int, str, Dict[str, Any]]] = []
    for sp in FISH_SPECIES_DB:
        name_l = sp["name"].lower()
        sci_l = sp["scientific_name"].lower()
        zone_l = (sp.get("zone") or sp.get("sub_zone") or "").lower()
        hab_l = HABITATS[sp["habitat"]]["name"].lower()

        if not q:
            # 검색어 미입력 시 대표 고성급·원본 인기 어종 우선 노출
            is_orig = 0 if not sp["id"].startswith("sp_") else 1
            scored.append((is_orig, -sp["rarity"], sp["name"], sp))
            continue

        if name_l == q:
            rank = 0
        elif name_l.startswith(q):
            rank = 1
        elif q in name_l:
            rank = 2
        elif q in zone_l or q in hab_l:
            rank = 3
        elif q in sci_l:
            rank = 4
        else:
            continue
        scored.append((rank, -sp["rarity"], sp["name"], sp))

    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    cands = []
    for _, _, _, sp in scored[:25]:
        hab = HABITATS[sp["habitat"]]
        zone_txt = sp.get("zone") or sp.get("sub_zone", "")
        cands.append(app_commands.Choice(
            name=f"[{hab['name']}·{zone_txt}] ★{sp['rarity']} {sp['name']} ({sp['min_cm']}~{sp['max_cm']}cm)"[:100],
            value=sp["id"],
        ))
    return cands


# ==========================================
# Pillow 포획 인증 카드 PNG 생성기
# ==========================================
def build_catch_card_bytes(catch_res: Dict[str, Any], user_name: str) -> Optional[io.BytesIO]:
    """포획 인증서 고화질 PNG 카드 생성 (실패 시 None 반환 -> 텍스트 임베드 폴백)"""
    if Image is None or ImageDraw is None:
        return None
    try:
        fish = catch_res["fish"]
        sp = catch_res["species"]
        env = catch_res["env"]
        hab = HABITATS[sp["habitat"]]
        rmeta = RARITY_META[sp["rarity"]]

        w, h = 880, 420
        img = Image.new("RGBA", (w, h), (10, 18, 34, 255))
        draw = ImageDraw.Draw(img)

        # 서식지 + 성급 그라데이션 배경
        base_r, base_g, base_b = hab["rgb"]
        rar_r, rar_g, rar_b = rmeta["rgb"]
        for y in range(h):
            t = y / h
            r = int(10 + base_r * 0.16 * (1 - t) + rar_r * 0.10 * t)
            g = int(18 + base_g * 0.18 * (1 - t) + rar_g * 0.10 * t)
            b = int(36 + base_b * 0.24 * (1 - t) + rar_b * 0.14 * t)
            draw.line([(0, y), (w, y)], fill=(min(255, r), min(255, g), min(255, b), 255))

        # 물결 데코 라인
        for wave_i in range(4):
            wy = 315 + wave_i * 22
            pts = []
            for x in range(0, w + 20, 20):
                pts.append((x, wy + int(math.sin(x * 0.025 + wave_i * 1.1) * 6)))
            draw.line(pts, fill=(rar_r, rar_g, rar_b, 42 + wave_i * 12), width=2)

        # 메인 프레임 보더
        draw.rounded_rectangle([14, 14, w - 14, h - 14], radius=24, outline=(rar_r, rar_g, rar_b, 220), width=4)
        draw.rounded_rectangle([24, 24, w - 24, h - 24], radius=18, outline=(255, 255, 255, 38), width=1)

        font_title = core._get_grid_font(34, bold=True)
        font_hdr = core._get_grid_font(22, bold=True)
        font_big = core._get_grid_font(38, bold=True)
        font_med = core._get_grid_font(20, bold=False)
        font_sm = core._get_grid_font(16, bold=False)

        # 좌측 어종 심볼 서클 카드
        cx, cy = 152, 205
        draw.ellipse([cx - 96, cy - 96, cx + 96, cy + 96], fill=(16, 28, 52, 235), outline=(rar_r, rar_g, rar_b, 230), width=4)
        draw.ellipse([cx - 82, cy - 82, cx + 82, cy + 82], outline=(255, 255, 255, 45), width=1)

        # 심플 벡터 물고기 실루엣 렌더링 (이모지 폰트 깨짐 0% 방지)
        body_col = (255, 215, 95, 245) if fish.get("variant") == "golden" else (rar_r, rar_g, rar_b, 235)
        tail_pts = [(cx - 64, cy - 26), (cx - 32, cy), (cx - 64, cy + 26)]
        draw.polygon(tail_pts, fill=body_col)
        draw.ellipse([cx - 42, cy - 32, cx + 56, cy + 32], fill=body_col)
        draw.polygon([(cx - 10, cy - 30), (cx + 18, cy - 52), (cx + 26, cy - 26)], fill=(base_r, base_g, base_b, 235))
        draw.ellipse([cx + 28, cy - 12, cx + 40, cy], fill=(255, 255, 255, 255))
        draw.ellipse([cx + 32, cy - 9, cx + 38, cy - 3], fill=(12, 18, 30, 255))

        # 좌측 하단 성급 배지
        star_txt = core._sanitize_grid_text(rmeta["full_stars"])
        sb = draw.textbbox((0, 0), star_txt, font=font_hdr)
        sw = sb[2] - sb[0]
        draw.text((cx - sw // 2, cy + 110), star_txt, font=font_hdr, fill=(rar_r, rar_g, rar_b, 255))

        # 우측 헤더: 서식지 & 도장 배지
        rx = 282
        hab_tag = core._sanitize_grid_text(f"[{hab['name']} · {sp['sub_zone']}]  |  {rmeta['name']} ({rmeta['stars']})")
        draw.text((rx, 46), hab_tag, font=font_sm, fill=(175, 215, 255, 240))

        # 특수 도장 (신기록 / 월척 / 첫도감 / 황금변이)
        badges = []
        if catch_res.get("new_server_len_record") or catch_res.get("new_server_wt_record"):
            badges.append(("서버 신기록!", (245, 158, 11, 255)))
        if fish.get("is_trophy"):
            badges.append(("월척 대물", (239, 68, 68, 255)))
        if fish.get("variant") == "golden":
            badges.append(("황금 변이", (250, 204, 21, 255)))
        if catch_res.get("is_first_catch"):
            badges.append(("NEW 도감", (16, 185, 129, 255)))

        bx_cur = w - 42
        for b_txt, b_col in badges[:3]:
            b_clean = core._sanitize_grid_text(b_txt)
            bb = draw.textbbox((0, 0), b_clean, font=font_sm)
            bw = (bb[2] - bb[0]) + 22
            bx_cur -= bw
            draw.rounded_rectangle([bx_cur, 40, bx_cur + bw, 70], radius=12, fill=b_col)
            draw.text((bx_cur + 11, 45), b_clean, font=font_sm, fill=(255, 255, 255, 255))
            bx_cur -= 8

        # 어종명 & 학명
        fish_name = core._sanitize_grid_text(fish["name"])
        draw.text((rx, 86), fish_name, font=font_title, fill=(255, 255, 255, 255))
        sci_name = core._sanitize_grid_text(f"{sp['scientific_name']}")
        draw.text((rx, 134), sci_name, font=font_med, fill=(180, 200, 230, 215))

        # 크기 · 무게 · 가치 메트릭 박스 3칸
        card_y = 178
        box_w = 176
        box_h = 96
        metrics = [
            ("체장 (Length)", f"{fish['length_cm']:.1f} cm", (56, 189, 248, 255)),
            ("무게 (Weight)", f"{fish['weight_kg']:.2f} kg" if fish['weight_kg'] >= 0.2 else f"{fish['weight_kg']:.3f} kg", (52, 211, 153, 255)),
            ("추정 가치", f"{fish['gold']:,} G", (250, 204, 21, 255)),
        ]
        for idx, (m_lbl, m_val, m_col) in enumerate(metrics):
            mx = rx + idx * (box_w + 14)
            draw.rounded_rectangle([mx, card_y, mx + box_w, card_y + box_h], radius=14, fill=(14, 24, 44, 215), outline=(255, 255, 255, 45), width=1)
            draw.text((mx + 14, card_y + 12), core._sanitize_grid_text(m_lbl), font=font_sm, fill=(170, 190, 220, 230))
            val_clean = core._sanitize_grid_text(m_val)
            draw.text((mx + 14, card_y + 42), val_clean, font=font_hdr, fill=m_col)

        # 하단 설명 & 출조 환경 푸터
        desc_clean = core._sanitize_grid_text(sp["desc"])
        while len(desc_clean) > 10 and draw.textbbox((0, 0), desc_clean, font=font_sm)[2] > (w - rx - 46):
            desc_clean = desc_clean[:-2] + ".."
        draw.text((rx, 294), desc_clean, font=font_sm, fill=(220, 232, 248, 230))

        rod_name = core._sanitize_grid_text(catch_res["rod"]["name"])
        weather_name = core._sanitize_grid_text(env["weather_name"])
        time_txt = "낮" if env["time_phase"] == "day" else "밤"
        angler = core._sanitize_grid_text(user_name)[:18]
        footer_txt = core._sanitize_grid_text(f"출조사: {angler}  |  장비: {rod_name}  |  환경: {time_txt} · {weather_name}  |  {fish['caught_at']} KST")
        draw.text((rx, 352), footer_txt, font=font_sm, fill=(160, 185, 220, 215))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"⚠️ [fishing_core] 포획 카드 PNG 렌더링 예외: {e}", flush=True)
        return None
