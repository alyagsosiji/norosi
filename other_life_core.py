"""
norosi Bot - 「타인의인생」 코어 스토리 시뮬레이션 엔진 (other_life_core.py)
- 0세 탄생부터 노년/결말까지 한 타인의 일생을 인과관계·개연성 기반으로 살아가는 텍스트 RPG
- 균형 잡힌 실시간 시간 배율(45초=1년 표준 / 15초=1년 쾌속 / 3분=1년 슬로우 / 턴제 즉시) + 능동 분기 진행 지원
- 6대 출신 · 7대 진로(예술/학문/사업/장인/수호/방랑/그림자) · 동반자/스승 떡밥 회수 · 16종 멀티 엔딩 · 전기 도감
"""

from __future__ import annotations

import copy
import datetime
import random
import threading
from typing import Any, Dict, List, Optional, Tuple

import core
import other_life_narratives as ol_narratives
from other_life_narratives import HOMETOWN_META, SPECIALTY_CATALOG, get_role_context

_OTHER_LIFE_LOCK = threading.RLock()

DAILY_CRYSTAL_REWARD_LIMIT = 3
MIN_BEATS_FOR_REWARD = 10

# ==========================================
# 1. 시간 배율 프리셋 (실시간 흐름 + 능동 분기 진행 공존)
# ==========================================
TIME_SCALES: Dict[str, Dict[str, Any]] = {
    "balanced": {
        "id": "balanced",
        "name": "⚖️ 표준 세월 배율 (추천)",
        "emoji": "⚖️",
        "sec_per_year": 45,
        "desc": "실시간 45초마다 1년씩 일상이 흐르며, 선택지 클릭 시 다음 인생 분기(2~7년)로 즉시 이어집니다.",
        "short_desc": "45초=1년 실시간 일상숙성 + 클릭 즉시 분기 진행",
    },
    "brisk": {
        "id": "brisk",
        "name": "⚡ 쾌속 세월 배율",
        "emoji": "⚡",
        "sec_per_year": 15,
        "desc": "실시간 15초마다 1년씩 빠르게 일상 경험이 쌓이며, 원할 때마다 바로 분기를 넘길 수 있습니다.",
        "short_desc": "15초=1년 빠른 일상숙성 + 클릭 즉시 분기 진행",
    },
    "slow": {
        "id": "slow",
        "name": "🕰️ 슬로우 라이프",
        "emoji": "🕰️",
        "sec_per_year": 180,
        "desc": "실시간 3분마다 1년이 흐르며 하루 동안 느긋하게 한 사람의 인생을 동행합니다 (조기 진행 가능).",
        "short_desc": "3분=1년 느긋한 감성 배율 + 클릭 즉시 분기 진행",
    },
    "turn": {
        "id": "turn",
        "name": "📖 턴제 정주행",
        "emoji": "📖",
        "sec_per_year": 0,
        "desc": "실시간 대기 없이 오직 이야기 선택만으로 0세부터 엔딩까지 한 편의 소설처럼 정주행합니다.",
        "short_desc": "대기 없음 · 선택지 클릭만으로 빠르게 엔딩 감상",
    },
}

DEFAULT_TIME_SCALE = "balanced"

# ==========================================
# 2. 인물 시드 / 출신 배경 / 진로 / 5대 시기
# ==========================================
FIRST_NAMES = [
    "서율", "도현", "지안", "시우", "은채", "태오", "하린", "유건",
    "다온", "세훈", "서아", "민준", "수빈", "재원", "연우", "주원",
    "하율", "예린", "건우", "채원", "이안", "가온", "시현", "윤서",
]
SURNAMES = ["강", "윤", "한", "박", "최", "임", "송", "정", "백", "오", "진", "서", "조", "류"]
COMPANION_POOL = ["지우", "민재", "하은", "유진", "도윤", "수아", "현우", "소연", "준서", "채영"]
ADULT_PARTNER_POOL = ["서연", "태현", "해인", "지호", "나연", "우진", "예진", "승민"]
MENTOR_SURNAMES = ["백", "강", "문", "선우", "남", "차", "허", "유"]

HOMETOWNS = [
    "부산 영도의 바닷바람 부는 골목",
    "서울 북촌의 비탈진 기와집 옆",
    "강릉 주문진의 작은 포구",
    "전주 한옥마을 끝자락",
    "인천 차이나타운 너머 낡은 부두",
    "춘천 소양강 안개 낀 언덕",
    "여수 돌산의 붉은 등대 아래",
    "경주 황리단의 오래된 느티나무 곁",
]

STAGES: List[Tuple[str, str, str, int, int]] = [
    ("childhood", "🌱 유년기", "세상의 첫 질감을 배우는 시절", 0, 13),
    ("teen", "🎒 청소년기", "꿈과 인연, 방황이 싹트는 시절", 14, 18),
    ("youth", "🔥 청년기", "스스로 선택한 길 위에서 부딪히는 시절", 19, 36),
    ("midlife", "🏛️ 장년기", "선택의 무게와 과거가 되돌아오는 시절", 37, 61),
    ("elder", "🍂 노년기", "지나온 세월을 껴안고 마침표를 찍는 시절", 62, 100),
]

CAREER_META: Dict[str, Dict[str, str]] = {
    "none": {"name": "미정 (성장 중)", "emoji": "🌱"},
    "artist": {"name": "예술·창작가", "emoji": "🎨"},
    "scholar": {"name": "학자·연구자", "emoji": "🔬"},
    "entrepreneur": {"name": "사업·개척가", "emoji": "💼"},
    "artisan": {"name": "장인·생활인", "emoji": "🌿"},
    "guardian": {"name": "수호·언론인", "emoji": "⚖️"},
    "wanderer": {"name": "방랑·기록가", "emoji": "🧭"},
    "shadow": {"name": "그림자 브로커", "emoji": "🎭"},
}

ORIGINS: Dict[str, Dict[str, Any]] = {
    "orphanage": {
        "id": "orphanage",
        "name": "🌊 바닷가 보육원 '해송원'",
        "place": "바닷가 보육원 '해송원'",
        "item": "파도에 닳은 유리조각과 스케치북",
        "hook": "가진 것은 적었으나 파도 소리를 들으며 누구보다 단단히 자랐다.",
        "stats": {"intellect": 22, "passion": 26, "empathy": 26, "grit": 28, "wealth": 10},
    },
    "noodle_shop": {
        "id": "noodle_shop",
        "name": "🍜 시장통 24시 멸치국수집",
        "place": "시장통 멸치국수집",
        "item": "어머니의 무쇠 육수 국자",
        "hook": "새벽 4시 멸치 육수 향기와 시끌벅적한 시장 상인들의 웃음 속에서 컸다.",
        "stats": {"intellect": 20, "passion": 24, "empathy": 30, "grit": 26, "wealth": 16},
    },
    "scholar_home": {
        "id": "scholar_home",
        "name": "📚 오래된 한옥 서재 집안",
        "place": "한옥 서재 집안",
        "item": "먹 냄새 배인 만년필과 천문학 노트",
        "hook": "천장까지 쌓인 책들 사이에서 높은 기대를 짊어지고 첫 숨을 쉬었다.",
        "stats": {"intellect": 32, "passion": 22, "empathy": 20, "grit": 20, "wealth": 22},
    },
    "fallen_house": {
        "id": "fallen_house",
        "name": "🏚️ 몰락한 옛 저택의 막내",
        "place": "빛바랜 붉은 벽돌 저택",
        "item": "녹슨 가문 문장 열쇠",
        "hook": "한때의 영광과 빚쟁이들의 그림자 사이에서 일찍 어른의 눈빛을 배웠다.",
        "stats": {"intellect": 26, "passion": 28, "empathy": 18, "grit": 26, "wealth": 14},
    },
    "artisan_shop": {
        "id": "artisan_shop",
        "name": "🕰️ 골목 끝 시계·목공방",
        "place": "오래된 시계·목공 수리점",
        "item": "아버지의 황동 돋보기 루페",
        "hook": "째깍거리는 초침 소리와 대패질 소리 사이에서 묵묵히 손끝의 감각을 익혔다.",
        "stats": {"intellect": 24, "passion": 24, "empathy": 24, "grit": 28, "wealth": 18},
    },
    "mountain_clinic": {
        "id": "mountain_clinic",
        "name": "⛰️ 안개 낀 산골 약초방",
        "place": "안개 낀 산골 약초방",
        "item": "별자리와 약초가 그려진 낡은 수첩",
        "hook": "약초 달이는 향기와 밤하늘 은하수 아래에서 생명의 온도를 먼저 배웠다.",
        "stats": {"intellect": 26, "passion": 20, "empathy": 30, "grit": 26, "wealth": 12},
    },
}

# ==========================================
# 3. 16종 멀티 엔딩 카탈로그 (인과관계 기반 판정)
# ==========================================
ENDINGS: Dict[str, Dict[str, Any]] = {
    "hidden_star": {
        "id": "hidden_star",
        "emoji": "🌌",
        "title": "별을 건너다 [히든]",
        "rarity": "히든",
        "color": 0xA855F7,
        "base_crystal": 180,
        "summary": "평생 간직한 순수한 호기심과 흔들리지 않은 인간애로 시간의 경계 너머까지 사유한 삶",
        "epilogue": (
            "{age}세의 맑은 새벽, {name}은(는) 창밖 은하수를 올려다보며 어린 날 {origin_place}에서 품었던 첫 질문을 떠올렸습니다. "
            "평생 쌓은 통찰과 온기는 후대의 기록 속에 별빛처럼 남아, 세월이 흘러도 수많은 이의 밤길을 밝혀주었습니다."
        ),
    },
    "flame_39": {
        "id": "flame_39",
        "emoji": "🔥",
        "title": "불꽃 같은 서른아홉",
        "rarity": "전설",
        "color": 0xEF4444,
        "base_crystal": 130,
        "summary": "자신의 몸을 아끼지 않고 위기의 순간에 온몸을 던져 타인과 이상을 구해낸 짧은 생애",
        "epilogue": (
            "{age}세라는 이른 나이에 멈춰 선 시계. 그러나 {name}이(가) 불길과 시련 앞에서 마지막까지 놓지 않은 손은 "
            "살아남은 이들의 기억 속에서 결코 식지 않는 불꽃이 되어 영원히 타오릅니다."
        ),
    },
    "old_promise": {
        "id": "old_promise",
        "emoji": "🧑‍🤝‍🧑",
        "title": "오래된 약속의 완성",
        "rarity": "전설",
        "color": 0xF472B6,
        "base_crystal": 140,
        "summary": "어린 날 나눈 약속을 숱한 세월과 이별 너머에서 끝내 지켜낸 두 사람의 이야기",
        "epilogue": (
            "긴 우회를 돌아 마침내 한 지붕 아래에서 노년을 맞은 {name}과(와) {partner}. "
            "백발이 성성해진 두 사람이 창가에서 낡은 추억을 꺼내 웃던 그 오후, 세월은 가장 다정한 선물이 되었습니다."
        ),
    },
    "truth_keeper": {
        "id": "truth_keeper",
        "emoji": "⚖️",
        "title": "진실을 남긴 이름",
        "rarity": "전설",
        "color": 0x3B82F6,
        "base_crystal": 140,
        "summary": "거대한 권력과 유혹 앞에서도 굴복하지 않고 세상의 균형을 지켜낸 수호자의 일생",
        "epilogue": (
            "수많은 협박과 회유 속에서도 끝내 펜과 양심을 꺾지 않았던 {name}. "
            "{age}세에 조용히 자리를 물러났지만, 그가 남긴 기록 한 줄은 훗날 수천 명의 삶을 지키는 법과 상식이 되었습니다."
        ),
    },
    "master_craft": {
        "id": "master_craft",
        "emoji": "🏆",
        "title": "시대의 거장",
        "rarity": "전설",
        "color": 0xF59E0B,
        "base_crystal": 145,
        "summary": "편법을 멀리하고 한 분야를 평생 갈고닦아 시대를 대표하는 정점에 선 대가의 삶",
        "epilogue": (
            "{origin_place}에서 시작된 작은 손짓은 어느새 한 시대의 기준이 되었습니다. "
            "{age}세까지 정직한 땀을 멈추지 않은 {name}의 이름은 교과서와 박물관 가장 빛나는 자리에 새겨졌습니다."
        ),
    },
    "unheard_genius": {
        "id": "unheard_genius",
        "emoji": "📜",
        "title": "미완의 걸작",
        "rarity": "희귀",
        "color": 0x6366F1,
        "base_crystal": 120,
        "summary": "생전에는 세상의 인정을 받지 못한 채 가난했으나, 사후 수십 년 뒤 온 세상이 열광한 천재",
        "epilogue": (
            "화려한 박수 없이 낡은 작업실에서 생을 마친 {name}. 그러나 그가 남긴 낡은 노트와 원고 상자가 발견된 20년 뒤, "
            "세상은 비로소 시대를 너무 앞서갔던 한 거장의 고독 앞에 고개를 숙였습니다."
        ),
    },
    "healer_hands": {
        "id": "healer_hands",
        "emoji": "🩺",
        "title": "생명을 잇는 손",
        "rarity": "희귀",
        "color": 0x10B981,
        "base_crystal": 125,
        "summary": "출세 대신 아픈 이들의 곁을 지키는 길을 택해 수많은 생명을 다시 일으킨 치유자",
        "epilogue": (
            "화려한 대형 병원이 아닌 작은 진료소와 사람들의 곁을 지킨 {name}. "
            "{age}세의 장례식장에는 그가 평생 살려낸 수많은 이웃들이 국화 한 송이씩을 들고 끝없이 줄을 섰습니다."
        ),
    },
    "broken_crown": {
        "id": "broken_crown",
        "emoji": "💔",
        "title": "부서진 왕관",
        "rarity": "희귀",
        "color": 0x64748B,
        "base_crystal": 95,
        "summary": "성공과 편법의 유혹 끝에 신의를 잃고 공허한 몰락을 맞은 씁쓸한 교훈의 생애",
        "epilogue": (
            "한때 모든 것을 손에 넣었다 믿었지만, 거짓으로 쌓은 성은 세월의 바람 앞에 모래처럼 무너졌습니다. "
            "텅 빈 방에서 {origin_item}을 만지작거리던 {name}은(는) 너무 늦게 진짜 소중한 것의 이름을 떠올렸습니다."
        ),
    },
    "redeemed_spring": {
        "id": "redeemed_spring",
        "emoji": "🕯️",
        "title": "회개와 두 번째 봄",
        "rarity": "전설",
        "color": 0xFBBF24,
        "base_crystal": 135,
        "summary": "젊은 날의 오만과 잘못으로 추락했으나, 묵묵한 속죄와 봉사로 인생의 두 번째 봄을 맞은 이야기",
        "epilogue": (
            "과거의 잘못을 숨기지 않고 스스로 죗값을 치렀던 중년의 선택. "
            "바닥에서 다시 일어선 {name}은(는) 남은 생을 타인의 상처를 닦아주는 데 바치며, 가장 눈부신 두 번째 봄을 맞이했습니다."
        ),
    },
    "masked_shadow": {
        "id": "masked_shadow",
        "emoji": "🎭",
        "title": "가면 뒤의 그림자",
        "rarity": "희귀",
        "color": 0x475569,
        "base_crystal": 115,
        "summary": "아무에게도 본명을 밝히지 못한 채 세상의 어두운 뒷면에서 홀로 사라진 미스터리한 생애",
        "epilogue": (
            "수많은 비밀과 거래가 그의 손끝을 스쳐 갔지만, 정작 {name}의 진짜 이름을 불러주는 이는 세상에 남지 않았습니다. "
            "어느 비 오는 밤, 도시의 안개 속으로 사라진 뒤로는 그를 기억하는 소문만이 떠돌았습니다."
        ),
    },
    "empire_builder": {
        "id": "empire_builder",
        "emoji": "👑",
        "title": "제국의 설계자",
        "rarity": "희귀",
        "color": 0xEAB308,
        "base_crystal": 120,
        "summary": "시대의 흐름을 읽어 거대한 사업과 부를 일구며 수많은 이들의 삶을 움직인 거물",
        "epilogue": (
            "맨손으로 시작해 도시의 스카이라인을 바꾼 {name}의 이름. "
            "{empire_flavor}"
        ),
    },
    "horizon_writer": {
        "id": "horizon_writer",
        "emoji": "🧭",
        "title": "끝없는 지평선의 기록자",
        "rarity": "희귀",
        "color": 0x06B6D4,
        "base_crystal": 120,
        "summary": "한곳에 머무르지 않고 평생 세계의 길 위를 걸으며 낯선 풍경과 사람들을 기록한 자유인",
        "epilogue": (
            "일흔이 넘어서도 낡은 배낭과 수첩을 놓지 않았던 {name}. "
            "바다 너머 작은 항구 마을에서 마지막 편지를 부친 뒤, 그는 평생 사랑했던 지평선 너머로 자유롭게 여행을 떠났습니다."
        ),
    },
    "noodle_universe": {
        "id": "noodle_universe",
        "emoji": "🍜",
        "title": "국수 한 그릇의 우주",
        "rarity": "희귀",
        "color": 0xFB923C,
        "base_crystal": 125,
        "summary": "세상의 거친 풍파를 지나 따뜻한 국수 한 그릇으로 지친 이웃들을 어루만진 골목의 전설",
        "epilogue": (
            "화려한 성공보다도 비 오는 날 한 그릇의 온기를 택한 {name}. "
            "새벽 4시 불 켜진 골목 국수집은 반세기가 넘도록 지친 청춘과 늙은 이웃들이 마음을 기대는 세상의 등대가 되었습니다."
        ),
    },
    "teacher_bridge": {
        "id": "teacher_bridge",
        "emoji": "🌟",
        "title": "세대를 잇는 스승",
        "rarity": "희귀",
        "color": 0x38BDF8,
        "base_crystal": 120,
        "summary": "스스로 빛나는 자리 대신 제자들의 등 뒤에서 묵묵히 디딤돌이 되어준 위대한 스승",
        "epilogue": (
            "스승 {mentor}에게서 물려받은 가르침을 다음 세대의 손에 고스란히 쥐여준 {name}. "
            "{age}세의 교정과 공방에는 그가 길러낸 제자들의 웃음소리가 봄바람처럼 가득했습니다."
        ),
    },
    "village_lantern": {
        "id": "village_lantern",
        "emoji": "🕊️",
        "title": "작은 마을의 등불",
        "rarity": "일반",
        "color": 0x22C55E,
        "base_crystal": 100,
        "summary": "역사책에는 없지만, 함께 살아간 이웃 모두가 고마움을 잊지 못하는 선한 어른의 삶",
        "epilogue": (
            "크게 이름날 일은 없었어도 도움이 필요한 곳엔 언제나 가장 먼저 나타났던 {name}. "
            "{age}세를 일기로 눈을 감던 날, 온 동네 골목마다 그를 배웅하는 따뜻한 등불이 켜졌습니다."
        ),
    },
    "quiet_miracle": {
        "id": "quiet_miracle",
        "emoji": "🏡",
        "title": "평범하지만 가장 빛나는 기적",
        "rarity": "일반",
        "color": 0x14B8A6,
        "base_crystal": 100,
        "summary": "거창한 야망이나 극적인 파국 대신, 소박한 일상을 성실히 사랑하며 채운 온전한 백 년",
        "epilogue": (
            "누구보다 평범한 하루하루를 성실하게 쌓아 올린 {name}의 {age}년. "
            "{quiet_flavor}"
        ),
    },
}


# ==========================================
# 4. 보조 유틸리티
# ==========================================
def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or isinstance(val, bool):
            return default
        return int(float(val))
    except Exception:
        return default


def _clamp_stat(v: int) -> int:
    return max(0, min(100, int(v)))


def get_stage_for_age(age: int) -> Tuple[str, str, str]:
    for sid, label, desc, mn, mx in STAGES:
        if mn <= age <= mx:
            return sid, label, desc
    return STAGES[-1][0], STAGES[-1][1], STAGES[-1][2]


def _pick_top_careers(stats: Dict[str, int], flags: set) -> List[str]:
    scores = {
        "artist": stats.get("passion", 0) * 1.15 + stats.get("empathy", 0) * 0.6 + (15 if "apt_art" in flags else 0) + (10 if "promise_express" in flags else 0),
        "scholar": stats.get("intellect", 0) * 1.2 + (18 if "apt_study" in flags else 0) + (10 if "promise_truth" in flags else 0),
        "entrepreneur": stats.get("wealth", 0) * 1.1 + stats.get("passion", 0) * 0.5 + (15 if "shortcut_tempted" in flags else 0),
        "artisan": stats.get("grit", 0) * 1.0 + stats.get("empathy", 0) * 0.5 + (18 if "apt_craft" in flags else 0),
        "guardian": stats.get("empathy", 0) * 0.9 + stats.get("grit", 0) * 0.8 + (18 if "apt_justice" in flags else 0) + (10 if "honest_path" in flags else 0),
        "wanderer": stats.get("passion", 0) * 0.6 + stats.get("intellect", 0) * 0.5 + (18 if "rebel_spirit" in flags else 0),
    }
    ordered = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return ordered[:2]


# ==========================================
# 5. 유저 상태 초기화 & 시간 배율 진행 엔진
# ==========================================
def ensure_other_life_user(data: Dict[str, Any], guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    root = core.ensure_dict_path(data, "other_life_users", str(guild_id or 0))
    u_key = str(user_id)
    u = root.get(u_key)
    if not isinstance(u, dict):
        u = {}
        root[u_key] = u

    if user_name:
        u["user_name"] = user_name
    elif not u.get("user_name"):
        u["user_name"] = f"유저#{u_key[-4:]}"

    ts = str(u.get("preferred_scale") or DEFAULT_TIME_SCALE)
    u["preferred_scale"] = ts if ts in TIME_SCALES else DEFAULT_TIME_SCALE
    u["lives_completed"] = max(0, _safe_int(u.get("lives_completed"), 0))
    u["best_score"] = max(0, _safe_int(u.get("best_score"), 0))
    u["longest_age"] = max(0, _safe_int(u.get("longest_age"), 0))

    raw_endings = u.get("unlocked_endings")
    if isinstance(raw_endings, list):
        u["unlocked_endings"] = {str(e): 1 for e in raw_endings if str(e) in ENDINGS}
    elif isinstance(raw_endings, dict):
        u["unlocked_endings"] = {
            str(k): max(1, _safe_int(v, 1))
            for k, v in raw_endings.items()
            if str(k) in ENDINGS
        }
    else:
        u["unlocked_endings"] = {}

    u["history"] = [
        h for h in core.coerce_list_like(u.get("history"))
        if isinstance(h, dict) and h.get("name") and h.get("ending_id")
    ][:30]

    today_str = core.get_today_str()
    if u.get("reward_date") != today_str:
        u["reward_date"] = today_str
        u["daily_rewards"] = 0
    else:
        u["daily_rewards"] = max(0, _safe_int(u.get("daily_rewards"), 0))

    active = u.get("active_life")
    if active is not None and not isinstance(active, dict):
        u["active_life"] = None
    elif isinstance(active, dict):
        if active.get("time_scale") not in TIME_SCALES:
            active["time_scale"] = u["preferred_scale"]
        if not isinstance(active.get("stats"), dict):
            active["stats"] = {"intellect": 25, "passion": 25, "empathy": 25, "grit": 25, "wealth": 15}
        active["flags"] = [str(f) for f in core.coerce_list_like(active.get("flags")) if f]
        active["chronicle"] = [str(c) for c in core.coerce_list_like(active.get("chronicle")) if c]
        active["turning_points"] = [str(t) for t in core.coerce_list_like(active.get("turning_points")) if t]
        active["beat"] = max(1, _safe_int(active.get("beat"), 1))
        active["age"] = max(0, min(105, _safe_int(active.get("age"), 6)))
        active["quiet_in_stage"] = max(0, _safe_int(active.get("quiet_in_stage"), 0))
        if active.get("career") and active.get("career") != "none" and not active.get("specialty"):
            active["specialty"] = ol_narratives.resolve_specialty_id(active)
    return u


def _make_idle_diary_line(life: Dict[str, Any], age_at_year: int) -> Tuple[str, Dict[str, int]]:
    return ol_narratives.build_idle_diary_line(life, age_at_year)


def _stage_age_ceiling(beat: int, current_age: int) -> int:
    """실시간 시간 경과가 현재 스토리 챕터의 나이 맥락을 망가뜨리지 않도록 상한 부여"""
    if beat <= 3:
        return min(13, current_age + 2)
    if beat <= 6:
        return min(18, current_age + 2)
    if beat == 7:
        return min(21, current_age + 2)
    if beat <= 11:
        return min(36, current_age + 3)
    if beat <= 15:
        return min(60, current_age + 3)
    return min(92, current_age + 4)


def _apply_stat_delta(stats: Dict[str, int], delta: Dict[str, int]) -> None:
    for k in ("intellect", "passion", "empathy", "grit", "wealth"):
        if k in delta:
            stats[k] = _clamp_stat(_safe_int(stats.get(k), 20) + int(delta[k]))


def sync_life_time(life: Dict[str, Any], now_ts: Optional[float] = None) -> Tuple[int, List[str]]:
    """
    선택된 시간 배율(TIME_SCALES)에 따라 마지막 활동 이후 흐른 실제 시간만큼
    캐릭터의 일상 숙성(최대 3년/회)과 일기장 기록을 자연스럽게 반영합니다.
    (스토리 분기점 자체를 임의로 건너뛰지는 않으므로 스토리 개연성이 100% 유지됩니다.)
    """
    if not isinstance(life, dict) or life.get("finished"):
        return 0, []
    scale_id = str(life.get("time_scale") or DEFAULT_TIME_SCALE)
    scale = TIME_SCALES.get(scale_id, TIME_SCALES[DEFAULT_TIME_SCALE])
    sec_per_year = int(scale.get("sec_per_year", 0))
    now_f = float(now_ts if now_ts is not None else datetime.datetime.now(core.KST).timestamp())
    last_f = float(life.get("last_tick_at") or now_f)
    if sec_per_year <= 0:
        life["last_tick_at"] = now_f
        return 0, []

    elapsed = max(0.0, now_f - last_f)
    years_ready = int(elapsed // sec_per_year)
    if years_ready <= 0:
        return 0, []

    ceiling = _stage_age_ceiling(_safe_int(life.get("beat"), 1), _safe_int(life.get("age"), 6))
    cur_age = _safe_int(life.get("age"), 6)
    room = max(0, ceiling - cur_age)
    years_to_add = min(3, years_ready, room)
    if room <= 0:
        life["last_tick_at"] = now_f
        return 0, []
    if years_ready > years_to_add:
        # Capped by per-visit limit (3 yrs) or ceiling: keep only sub-interval remainder
        rem_sec = elapsed % sec_per_year
        life["last_tick_at"] = now_f - rem_sec
    else:
        life["last_tick_at"] = min(now_f, last_f + years_to_add * sec_per_year)
    if years_to_add <= 0:
        return 0, []

    added_logs: List[str] = []
    stats = life.setdefault("stats", {})
    chronicle = life.setdefault("chronicle", [])
    for step in range(years_to_add):
        y_age = cur_age + step + 1
        line, delta = _make_idle_diary_line(life, y_age)
        _apply_stat_delta(stats, delta)
        entry = f"⏳ {y_age}세 (세월의 흐름) — {line}"
        chronicle.append(entry)
        added_logs.append(entry)
    life["age"] = cur_age + years_to_add
    if len(chronicle) > 80:
        del chronicle[:-80]
    return years_to_add, added_logs


# ==========================================
# 6. 스토리 노드 빌더 (other_life_narratives 위임)
# ==========================================
def _fmt_vars(life: Dict[str, Any]) -> Dict[str, Any]:
    return ol_narratives.fmt_life_vars(life)


def build_current_node(life: Dict[str, Any]) -> Dict[str, Any]:
    """현재 캐릭터의 beat, origin, career, specialty, flags, 관계에 정확히 부합하는 스토리 장면을 생성합니다."""
    return ol_narratives.build_story_node(life)


# ==========================================
# 7. 엔딩 판정기 (완벽한 인과관계 검증)
# ==========================================
def _resolve_ending(life: Dict[str, Any], forced_flame: bool = False) -> Tuple[str, Dict[str, Any]]:
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    career = str(life.get("career") or "none")
    origin_id = str(life.get("origin_id") or "orphanage")

    intel = _safe_int(stats.get("intellect"), 0)
    passion = _safe_int(stats.get("passion"), 0)
    empathy = _safe_int(stats.get("empathy"), 0)
    grit = _safe_int(stats.get("grit"), 0)
    wealth = _safe_int(stats.get("wealth"), 0)

    if forced_flame:
        eid = "flame_39"
    elif "cosmos_finale" in flags and "time_transcended" in flags and intel >= 58 and empathy >= 54:
        eid = "hidden_star"
    elif "corrupted" not in flags and (
        "old_promise_kept" in flags
        or (
            "comp_promised" in flags
            and life.get("partner_name") == life.get("companion_name")
            and "partner_strained" not in flags
        )
    ):
        eid = "old_promise"
    elif "redeemed" in flags:
        eid = "redeemed_spring"
    elif career == "shadow" and "redeemed" not in flags:
        eid = "masked_shadow"
    elif "corrupted" in flags and "redeemed" not in flags:
        eid = "broken_crown"
    elif "noodle_revival" in flags or (origin_id == "noodle_shop" and career == "artisan" and empathy >= 48 and "empire_ambition" not in flags):
        eid = "noodle_universe"
    elif ("whistleblower" in flags or (career == "guardian" and "teacher_path" not in flags)) and "honest_path" in flags and empathy >= 48:
        eid = "truth_keeper"
    elif ("healer_oath" in flags and career in ("scholar", "artisan", "wanderer")) or (origin_id == "mountain_clinic" and empathy >= 56 and career in ("scholar", "artisan")):
        eid = "healer_hands"
    elif career in ("artist", "scholar") and passion >= 50 and wealth <= 46 and ("pure_art" in flags or "final_work_done" in flags):
        eid = "unheard_genius"
    elif career in ("artist", "scholar", "artisan") and "masterwork_kept" in flags and max(intel, passion, grit) >= 62:
        eid = "master_craft"
    elif ("mentor_heir" in flags or "teacher_path" in flags) and empathy >= 48 and "empire_ambition" not in flags:
        eid = "teacher_bridge"
    elif ("protect_local" in flags or "philanthropy" in flags) and empathy >= 50 and "empire_ambition" not in flags:
        eid = "village_lantern"
    elif (career == "entrepreneur" and (wealth >= 58 or "empire_ambition" in flags)) or (wealth >= 72 and career != "wanderer"):
        eid = "empire_builder"
    elif (career == "wanderer" and passion >= 44) or "late_explorer" in flags:
        eid = "horizon_writer"
    else:
        eid = "quiet_miracle"

    emeta = ENDINGS[eid]
    v = _fmt_vars(life)
    epilogue = ol_narratives.build_rich_ending_epilogue(life, eid, emeta, v)

    score = int(
        (intel + passion + empathy + grit + wealth) * 4
        + v["age"] * 8
        + (250 if emeta["rarity"] == "히든" else 150 if emeta["rarity"] == "전설" else 80 if emeta["rarity"] == "희귀" else 40)
    )
    return eid, {"meta": emeta, "epilogue": epilogue, "score": score}


# ==========================================
# 8. 공개 API (시작 / 선택 / 조용한 1년 / 시간 동기화 / 도감 / 랭킹)
# ==========================================
def start_new_life(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
    time_scale: Optional[str] = None,
    origin_id: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)

        scale_id = time_scale if time_scale in TIME_SCALES else u["preferred_scale"]
        u["preferred_scale"] = scale_id

        chosen_origin = origin_id if origin_id in ORIGINS else random.choice(list(ORIGINS.keys()))
        orig = ORIGINS[chosen_origin]

        full_name = random.choice(SURNAMES) + random.choice(FIRST_NAMES)
        comp_choices = [c for c in COMPANION_POOL if not full_name.endswith(c)]
        companion = random.choice(comp_choices)
        adult_choices = [a for a in ADULT_PARTNER_POOL if a != companion and not full_name.endswith(a)]
        adult_partner = random.choice(adult_choices)
        mentor = f"{random.choice(MENTOR_SURNAMES)} 선생"
        hometown = random.choice(HOMETOWNS)
        ht = ol_narratives.get_hometown_meta(hometown)
        ro_sfx = ol_narratives.p_ro(full_name)

        now_f = datetime.datetime.now(core.KST).timestamp()
        life = {
            "life_uid": f"{int(now_f)}_{random.randint(100, 999)}",
            "name": full_name,
            "hometown": hometown,
            "origin_id": chosen_origin,
            "companion_name": companion,
            "adult_partner_name": adult_partner,
            "mentor_name": mentor,
            "partner_name": None,
            "career": "none",
            "specialty": "none",
            "companion_rel": "stranger",
            "mentor_rel": "unknown",
            "prev_choice_id": "",
            "age": 6,
            "beat": 1,
            "quiet_in_stage": 0,
            "time_scale": scale_id,
            "last_tick_at": now_f,
            "started_at": datetime.datetime.now(core.KST).isoformat(),
            "stats": copy.deepcopy(orig["stats"]),
            "flags": [],
            "turning_points": [
                f"0세: {ht['city']}의 {orig['place']}에서 '{full_name}'{ro_sfx} 태어나다."
            ],
            "last_outcome": (
                f"{ol_narratives.j_i(ht['sensory'])} 스며드는 **{ht['city']}**의 **{orig['place']}**에서 작은 울음소리와 함께 세상에 눈을 떴습니다. "
                f"어린 손에 처음 쥔 유품은 **{orig['item']}**. {orig['hook']}"
            ),
            "chronicle": [
                f"👶 0세 — {ht['city']}의 {orig['place']}에서 '{full_name}'{ro_sfx} 태어났다. ({orig['hook']})"
            ],
            "finished": False,
            "ending_id": None,
            "ending_epilogue": None,
            "score": 0,
            "crystal_awarded": 0,
        }
        u["active_life"] = life
        core.save_data(data)
        return True, f"📖 새로운 타인의 인생 **'{full_name}'**의 이야기가 시작되었습니다!", copy.deepcopy(u)


def get_other_life_state(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
) -> Tuple[Dict[str, Any], int, List[str]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        before = copy.deepcopy(core.safe_get_dict(data, "other_life_users", str(guild_id or 0), str(user_id)))
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        years_added = 0
        idle_logs: List[str] = []
        if isinstance(u.get("active_life"), dict) and not u["active_life"].get("finished"):
            years_added, idle_logs = sync_life_time(u["active_life"])
        if years_added > 0 or u != before:
            core.save_data(data)
        return copy.deepcopy(u), years_added, idle_logs


def set_life_time_scale(
    guild_id: int | str,
    user_id: int | str,
    scale_id: str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    if scale_id not in TIME_SCALES:
        return False, "❌ 알 수 없는 시간 배율입니다.", {}
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        u["preferred_scale"] = scale_id
        if isinstance(u.get("active_life"), dict) and not u["active_life"].get("finished"):
            sync_life_time(u["active_life"])
            u["active_life"]["time_scale"] = scale_id
            u["active_life"]["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()
        core.save_data(data)
        sc = TIME_SCALES[scale_id]
        return True, f"⏱️ 시간 배율을 **{sc['name']}**(`{sc['short_desc']}`)로 변경했습니다!", copy.deepcopy(u)


def spend_quiet_year(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        life = u.get("active_life")
        if not isinstance(life, dict) or life.get("finished"):
            return False, "ℹ️ 현재 진행 중인 인생이 없습니다.", copy.deepcopy(u)

        sync_life_time(life)
        if _safe_int(life.get("quiet_in_stage"), 0) >= 2:
            return False, "⏳ 이번 시기의 조용한 수련(최대 2년)을 모두 보냈습니다. 이제 인생의 선택지를 골라 주세요!", copy.deepcopy(u)

        cur_age = _safe_int(life.get("age"), 6)
        ceiling = _stage_age_ceiling(_safe_int(life.get("beat"), 1), cur_age)
        if cur_age >= ceiling or cur_age >= 95:
            return False, "⏳ 다음 분기점의 문턱에 도달했습니다! 아래 선택지 중 하나를 선택해 주세요.", copy.deepcopy(u)

        new_age = cur_age + 1
        line, delta = _make_idle_diary_line(life, new_age)
        # Boost slightly for active quiet year
        for k in list(delta.keys()):
            delta[k] = delta[k] + 1
        _apply_stat_delta(life["stats"], delta)
        life["age"] = new_age
        life["quiet_in_stage"] = _safe_int(life.get("quiet_in_stage"), 0) + 1
        life["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()
        life["last_outcome"] = f"**{new_age}세**의 조용한 한 해 — {line}"
        entry = f"🕰️ {new_age}세 (조용한 한 해) — {line}"
        life.setdefault("chronicle", []).append(entry)
        core.save_data(data)
        return True, f"🕰️ **{new_age}세**의 조용한 한 해를 보내며 차분히 내면을 다졌습니다.", copy.deepcopy(u)


def _finalize_ending(data: Dict[str, Any], u: Dict[str, Any], user_id: int | str, user_name: str, forced_flame: bool = False) -> None:
    life = u["active_life"]
    eid, res = _resolve_ending(life, forced_flame=forced_flame)
    meta = res["meta"]
    score = res["score"]

    life["finished"] = True
    life["ending_id"] = eid
    life["ending_epilogue"] = res["epilogue"]
    life["score"] = score
    life.setdefault("chronicle", []).append(
        f"📖 {life['age']}세 — [엔딩: {meta['emoji']} {meta['title']}]"
    )

    u["lives_completed"] = _safe_int(u.get("lives_completed"), 0) + 1
    u["best_score"] = max(_safe_int(u.get("best_score"), 0), score)
    u["longest_age"] = max(_safe_int(u.get("longest_age"), 0), _safe_int(life.get("age"), 0))

    unlocked = u.setdefault("unlocked_endings", {})
    is_first_unlock = eid not in unlocked
    unlocked[eid] = _safe_int(unlocked.get(eid), 0) + 1

    # 일일 보상 상한 & 최소 진행 챕터 검증으로 어뷰징 방지
    today_str = core.get_today_str()
    if u.get("reward_date") != today_str:
        u["reward_date"] = today_str
        u["daily_rewards"] = 0

    beats_played = _safe_int(life.get("beat"), 1)
    crystal_gain = 0
    reward_note = ""
    if beats_played >= MIN_BEATS_FOR_REWARD:
        if u["daily_rewards"] < DAILY_CRYSTAL_REWARD_LIMIT:
            crystal_gain = int(meta["base_crystal"]) + (120 if is_first_unlock else 0)
            u["daily_rewards"] += 1
            prof = core.ensure_user_profile(data, str(user_id), user_name or u.get("user_name", ""))
            prof["crystals"] = _safe_int(prof.get("crystals"), 0) + crystal_gain
            first_tag = " (🆕 신규 엔딩 초회 보너스 +120💎 포함!)" if is_first_unlock else ""
            reward_note = f"+{crystal_gain:,}💎 지급 완료{first_tag}"
        else:
            reward_note = f"오늘 💎 보상 한도({DAILY_CRYSTAL_REWARD_LIMIT}회/일) 도달 — 도감·기록은 정상 등록!"
    else:
        reward_note = "최소 진행 기준 미달 (도감 등록 완료)"

    life["crystal_awarded"] = crystal_gain
    life["reward_note"] = reward_note
    life["is_first_unlock"] = is_first_unlock

    career_meta = CAREER_META.get(str(life.get("career") or "none"), CAREER_META["none"])
    role_ctx = get_role_context(life)
    u.setdefault("history", []).insert(0, {
        "life_uid": life.get("life_uid"),
        "name": life.get("name"),
        "origin_id": life.get("origin_id"),
        "career": life.get("career"),
        "career_label": career_meta["name"],
        "specialty_label": role_ctx["title"] if role_ctx["career"] != "none" else career_meta["name"],
        "age": life.get("age"),
        "ending_id": eid,
        "ending_title": meta["title"],
        "ending_emoji": meta["emoji"],
        "ending_rarity": meta["rarity"],
        "score": score,
        "finished_at": datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M"),
        "chronicle_tail": list(life.get("chronicle") or [])[-8:],
    })
    if len(u["history"]) > 30:
        del u["history"][30:]


def apply_life_choice(
    guild_id: int | str,
    user_id: int | str,
    choice_id: str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any], Optional[Dict[str, Any]]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        life = u.get("active_life")
        if not isinstance(life, dict) or life.get("finished"):
            return False, "ℹ️ 이미 마무리되었거나 진행 중인 인생이 없습니다.", copy.deepcopy(u), None

        sync_life_time(life)
        node = build_current_node(life)
        chosen = next((c for c in node["choices"] if c["id"] == choice_id), None)
        if not chosen:
            return False, "⚠️ 이미 지난 분기이거나 유효하지 않은 선택지입니다.", copy.deepcopy(u), None

        cur_age = _safe_int(life.get("age"), 6)
        stats = life.setdefault("stats", {})
        pre_grit = _safe_int(stats.get("grit"), 25)
        pre_flags = set(life.get("flags") or [])

        _apply_stat_delta(stats, chosen.get("delta") or {})

        flag_set = set(life.get("flags") or [])
        for f in chosen.get("add_flags") or []:
            flag_set.add(str(f))
        for f in chosen.get("remove_flags") or []:
            flag_set.discard(str(f))
        life["flags"] = sorted(flag_set)

        if chosen.get("set_career"):
            new_career = str(chosen["set_career"])
            if new_career != life.get("career"):
                life["specialty"] = ""
            life["career"] = new_career
        if chosen.get("set_specialty"):
            life["specialty"] = str(chosen["set_specialty"])
        elif life.get("career") and life.get("career") != "none":
            life["specialty"] = ol_narratives.resolve_specialty_id(life)

        if chosen.get("set_partner"):
            life["partner_name"] = str(chosen["set_partner"])
        if chosen.get("clear_partner"):
            life["partner_name"] = None
        if chosen.get("set_comp_rel"):
            life["companion_rel"] = str(chosen["set_comp_rel"])
        if chosen.get("set_mentor_rel"):
            life["mentor_rel"] = str(chosen["set_mentor_rel"])

        life["prev_choice_id"] = str(choice_id)

        log_text = str(chosen.get("log") or chosen.get("label") or "").strip()
        outcome_text = str(chosen.get("outcome") or "").strip()
        life["last_outcome"] = outcome_text or f"{cur_age}세의 선택 — {log_text}"
        life.setdefault("chronicle", []).append(f"• {cur_age}세 — {log_text}")
        if len(life["chronicle"]) > 80:
            del life["chronicle"][:-80]

        if chosen.get("tp"):
            tps = life.setdefault("turning_points", [])
            tp_str = str(chosen["tp"]).strip()
            if tp_str and (not tps or tps[-1] != tp_str):
                tps.append(tp_str)
            if len(tps) > 16:
                del tps[:-16]

        life["last_action_summary"] = f"{cur_age}세의 선택: {log_text}"
        life["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()

        # 조기 영웅적 희생 / 건강 고갈 체크 (Beat 12 — 경고 조건과 100% 동기화)
        will_flame = (pre_grit <= 22) or (pre_grit <= 28 and "overworked" in pre_flags)
        if chosen.get("trigger_flame_if_low_grit") and will_flame:
            _finalize_ending(data, u, user_id, user_name, forced_flame=True)
            core.save_data(data)
            return True, f"🔥 **{life['name']}**의 불꽃 같은 생애가 엔딩에 도달했습니다!", copy.deepcopy(u), copy.deepcopy(chosen)

        cur_beat = _safe_int(life.get("beat"), 1)
        if cur_beat >= 18:
            _finalize_ending(data, u, user_id, user_name, forced_flame=False)
            core.save_data(data)
            return True, f"📖 **{life['name']}**의 인생 이야기가 완결되었습니다!", copy.deepcopy(u), copy.deepcopy(chosen)

        prev_stage = get_stage_for_age(cur_age)[0]
        next_age = cur_age + max(1, _safe_int(node.get("years_advance"), 3))
        next_stage = get_stage_for_age(next_age)[0]
        life["age"] = next_age
        life["beat"] = cur_beat + 1
        if next_stage != prev_stage:
            life["quiet_in_stage"] = 0

        core.save_data(data)
        return True, f"📖 {next_age}세의 이야기로 이어집니다.", copy.deepcopy(u), copy.deepcopy(chosen)


def get_other_life_ranking(guild_id: int | str, limit: int = 10) -> List[Dict[str, Any]]:
    data = core.load_data()
    g_map = core.safe_get_dict(data, "other_life_users", str(guild_id or 0))
    rows: List[Dict[str, Any]] = []
    for u_key, raw in g_map.items():
        if not isinstance(raw, dict):
            continue
        unlocked = raw.get("unlocked_endings") or {}
        endings_cnt = len([k for k in unlocked.keys() if k in ENDINGS]) if isinstance(unlocked, dict) else len(set(unlocked))
        lives = max(0, _safe_int(raw.get("lives_completed"), 0))
        best_score = max(0, _safe_int(raw.get("best_score"), 0))
        if lives <= 0 and endings_cnt <= 0:
            continue
        rows.append({
            "user_id": str(u_key),
            "user_name": raw.get("user_name") or f"유저#{str(u_key)[-4:]}",
            "endings_cnt": endings_cnt,
            "lives_completed": lives,
            "best_score": best_score,
            "longest_age": max(0, _safe_int(raw.get("longest_age"), 0)),
        })
    rows.sort(key=lambda r: (r["endings_cnt"], r["best_score"], r["lives_completed"]), reverse=True)
    return rows[:limit]
