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
        active["beat"] = max(1, _safe_int(active.get("beat"), 1))
        active["age"] = max(0, min(105, _safe_int(active.get("age"), 6)))
        active["quiet_in_stage"] = max(0, _safe_int(active.get("quiet_in_stage"), 0))
    return u


def _make_idle_diary_line(life: Dict[str, Any], age_at_year: int) -> Tuple[str, Dict[str, int]]:
    career = str(life.get("career") or "none")
    partner = life.get("partner_name")
    origin = ORIGINS.get(str(life.get("origin_id") or "orphanage"), ORIGINS["orphanage"])
    delta: Dict[str, int] = {}

    if age_at_year < 14:
        lines = [
            f"{origin['place']} 앞 골목에서 계절이 바뀌는 풍경을 눈에 담았다.",
            f"서툴지만 자신만의 리듬으로 하루를 버티며 한 뼘 더 자랐다.",
        ]
        delta = {"grit": 1, "empathy": 1}
    elif age_at_year < 19:
        lines = [
            "밤늦도록 책상 위 스탠드를 켜 두고 다가올 스무 살을 고민했다.",
            f"학창 시절의 틈새에서 자신이 진짜 좋아하는 일이 무엇인지 묵묵히 가늠했다.",
        ]
        delta = {"intellect": 1, "passion": 1}
    elif career == "artist":
        lines = [
            "누구도 알아주지 않는 날에도 붓과 악보를 손에서 놓지 않고 스케치를 쌓았다.",
            "비 오는 작업실 창밖을 바라보며 머릿속 멜로디와 색채를 한 줄 더 다듬었다.",
        ]
        delta = {"passion": 2, "empathy": 1}
    elif career == "scholar":
        lines = [
            "낡은 자료와 논문을 밤새 뒤지며 작은 가설 하나를 끈질기게 검증했다.",
            "실험실(서재)의 먼지 속에서 조용히 진실에 한 걸음 다가섰다.",
        ]
        delta = {"intellect": 2, "grit": 1}
    elif career == "entrepreneur":
        lines = [
            "장부와 시장의 흐름을 꼼꼼히 점검하며 다음 기회를 위한 밑천을 다졌다.",
            "수많은 거절 속에서도 거래처 사람들과 신뢰를 쌓아 기반을 넓혔다.",
        ]
        delta = {"wealth": 2, "passion": 1}
    elif career == "artisan":
        lines = [
            "매일 새벽 공방(가게) 문을 열고 도구를 닦으며 손끝의 숙련도를 높였다.",
            "단골손님들과 소박한 안부를 나누며 정직한 노동의 기쁨을 배웠다.",
        ]
        delta = {"grit": 2, "wealth": 1}
    elif career == "guardian":
        lines = [
            "현장의 낡은 기록철을 다시 훑어보며 놓친 단서가 없는지 꼼꼼히 살폈다.",
            "바쁜 일과 속에서도 약자들의 목소리에 귀를 기울이며 하루를 지켰다.",
        ]
        delta = {"empathy": 2, "grit": 1}
    elif career == "wanderer":
        lines = [
            "낯선 기차역과 항구의 벤치 위에서 마주친 사람들의 표정을 수첩에 옮겼다.",
            "정처 없는 길 위에서도 스스로를 돌보는 법을 익히며 견문을 넓혔다.",
        ]
        delta = {"passion": 1, "intellect": 1, "empathy": 1}
    elif career == "shadow":
        lines = [
            "조용한 뒷골목에서 암호와 소문을 정리하며 누구에게도 약점을 보이지 않았다.",
            "세상의 빈틈을 읽어 묵묵히 자금을 불렸지만 마음 한구석은 서늘했다.",
        ]
        delta = {"wealth": 2, "intellect": 1}
    else:
        lines = ["조용한 계절을 성실하게 건너며 내일의 선택을 준비했다."]
        delta = {"grit": 1}

    if partner and age_at_year >= 26 and random.random() < 0.35:
        lines.append(f"{partner}와(과) 나눈 따뜻한 저녁 식사가 고단한 한 해를 버티게 해 주었다.")
        delta["empathy"] = delta.get("empathy", 0) + 1

    return random.choice(lines), delta


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
# 6. 스토리 노드 빌더 (18개 연대기 비트 × 출신/직업/인연/플래그 완전 분기)
# ==========================================
def _fmt_vars(life: Dict[str, Any]) -> Dict[str, Any]:
    origin = ORIGINS.get(str(life.get("origin_id") or "orphanage"), ORIGINS["orphanage"])
    career = str(life.get("career") or "none")
    c_meta = CAREER_META.get(career, CAREER_META["none"])
    return {
        "name": life.get("name", "이름없는 이"),
        "hometown": life.get("hometown", "작은 마을"),
        "origin_place": origin["place"],
        "origin_item": origin["item"],
        "companion": life.get("companion_name", "지우"),
        "mentor": life.get("mentor_name", "백 선생"),
        "partner": life.get("partner_name") or life.get("adult_partner_name", "서연"),
        "adult_partner": life.get("adult_partner_name", "서연"),
        "career_label": c_meta["name"],
        "age": _safe_int(life.get("age"), 6),
    }


def _make_node(
    node_id: str,
    title: str,
    body: str,
    years_advance: int,
    choices: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "id": node_id,
        "title": title,
        "body": body,
        "years_advance": years_advance,
        "choices": choices,
    }


def build_current_node(life: Dict[str, Any]) -> Dict[str, Any]:
    """현재 캐릭터의 beat, origin, career, flags, 관계에 정확히 부합하는 스토리 장면을 생성합니다."""
    beat = max(1, min(18, _safe_int(life.get("beat"), 1)))
    origin_id = str(life.get("origin_id") or "orphanage")
    career = str(life.get("career") or "none")
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    v = _fmt_vars(life)
    age = v["age"]

    # ── BEAT 1 (Age 6 · 유년기 ①: 출신 맞춤형 첫 기억) ──
    if beat == 1:
        origin_bodies = {
            "orphanage": (
                f"비바람이 몰아치던 오후, {v['origin_place']}의 낡은 다락 창고에서 {v['name']}은(는) "
                f"누군가 버려둔 상자를 발견합니다. 상자 안에는 물 빠진 색연필 한 줌과 바닷새가 그려진 백과사전, "
                f"그리고 파도에 깎여 매끈해진 유리 조각이 들어 있었습니다."
            ),
            "noodle_shop": (
                f"해가 뜨기도 전인 새벽 4시, {v['origin_place']}의 김이 모락모락 피어오르는 주방 한켠. "
                f"여섯 살 {v['name']}은(는) 멸치 다듬는 할머니 옆에 쪼그려 앉아 시장 골목 사람들이 하루를 여는 소리를 듣습니다."
            ),
            "scholar_home": (
                f"먼지 냄새가 그윽한 {v['origin_place']}의 서재. 여섯 살 {v['name']}에게 어른들은 "
                f"'실수하지 않는 법'을 먼저 가르쳤지만, 아이의 시선은 서재 천장 작은 창으로 비치는 밤별에 닿아 있었습니다."
            ),
            "fallen_house": (
                f"붉은 압류 딱지가 붙기 시작한 {v['origin_place']}의 넓은 마루. "
                f"어른들의 한숨 소리가 커질수록 여섯 살 {v['name']}은(는) 서서히 깨달았습니다. 이 집에서 기댈 곳은 결국 자기 자신뿐이라는 것을."
            ),
            "artisan_shop": (
                f"초침 소리가 수십 개씩 겹쳐 울리는 {v['origin_place']}. "
                f"아버지가 잠시 자리를 비운 사이, {v['name']}의 눈앞에 태엽이 풀려 멈춰 선 낡은 회중시계 하나가 놓여 있습니다."
            ),
            "mountain_clinic": (
                f"이슬이 마르지 않은 {v['origin_place']}의 뒤뜰. "
                f"여섯 살 {v['name']}은(는) 상처 입은 산새 한 마리가 처마 밑에 떨어져 떨고 있는 것을 조심스럽게 두 손으로 감싸 안습니다."
            ),
        }
        return _make_node(
            "b1_origin",
            f"🌅 {age}세의 첫 기억 — {ORIGINS[origin_id]['name']}",
            origin_bodies.get(origin_id, origin_bodies["orphanage"]),
            3,
            [
                {
                    "id": "b1_curious",
                    "label": "🔍 원리와 이유를 끝까지 파고든다",
                    "hint": "지성 +6 · 사물의 이치와 별을 동경하는 씨앗",
                    "delta": {"intellect": 6, "empathy": 1},
                    "add_flags": ["curious_mind", "star_seed"],
                    "log": f"어린 눈빛으로 세상의 원리를 궁금해하며 낡은 노트에 첫 메모를 남겼다.",
                },
                {
                    "id": "b1_feel",
                    "label": "🎨 떠오른 감정과 풍경을 손으로 그려낸다",
                    "hint": "열정 +6 · 공감 +2 · 예술적 표현의 싹",
                    "delta": {"passion": 6, "empathy": 2},
                    "add_flags": ["art_spark"],
                    "log": f"그날 본 빛깔과 감정을 서툰 그림과 흥얼거림으로 표현해 냈다.",
                },
                {
                    "id": "b1_work",
                    "label": "🛡️ 직접 몸으로 부딪혀 보살피고 고쳐본다",
                    "hint": "근성 +6 · 자산 +2 · 현실 감각과 손기술",
                    "delta": {"grit": 6, "wealth": 2},
                    "add_flags": ["craft_hands"],
                    "log": f"말보다 먼저 손을 움직여 눈앞의 작은 문제를 스스로 해결해 냈다.",
                },
            ],
        )

    # ── BEAT 2 (Age 9 · 유년기 ②: 소꿉친구 {companion}과의 만남) ──
    if beat == 2:
        return _make_node(
            "b2_companion",
            f"☔ {age}세 — 처마 밑에서 만난 동갑내기 '{v['companion']}'",
            (
                f"소나기가 세차게 쏟아지던 하굣길, 낡은 문방구 처마 밑에 비를 피하던 {v['name']} 옆으로 "
                f"무릎이 까진 동갑내기 **{v['companion']}**가 숨을 헐떡이며 뛰어들었습니다. "
                f"두 아이의 손에는 각자 비에 젖은 우산 하나와 반쪽짜리 떡볶이 컵이 들려 있었습니다."
            ),
            3,
            [
                {
                    "id": "b2_close",
                    "label": f"☂️ 우산을 씌워주며 {v['companion']}와 함께 걷는다",
                    "hint": "공감 +7 · 평생 이어질 소중한 우정의 시작",
                    "delta": {"empathy": 7, "grit": 1},
                    "add_flags": ["comp_close"],
                    "log": f"비 오는 날 {v['companion']}와 우산을 나눠 쓰며 둘도 없는 소꿉친구가 되었다.",
                },
                {
                    "id": "b2_rival",
                    "label": f"🏃 \"누가 먼저 집까지 뛰어가나 내기할래?\"",
                    "hint": "열정 +6 · 근성 +3 · 서로를 자극하는 라이벌 인연",
                    "delta": {"passion": 6, "grit": 3},
                    "add_flags": ["comp_rival"],
                    "log": f"{v['companion']}와 빗속을 달리며 서로 지기 싫어하는 유쾌한 라이벌이 되었다.",
                },
                {
                    "id": "b2_solo",
                    "label": "📓 우산만 빌려주고 혼자 빗소리를 기록한다",
                    "hint": "지성 +6 · 자산 +2 · 독립적이고 고독한 기질",
                    "delta": {"intellect": 6, "wealth": 2},
                    "add_flags": ["comp_solo"],
                    "log": f"우산을 건넨 뒤 홀로 남아 빗물 흐르는 처마를 보며 혼자 생각하는 법을 익혔다.",
                },
            ],
        )

    # ── BEAT 3 (Age 12 · 유년기 ③: 환경의 첫 시련) ──
    if beat == 3:
        trial_desc = {
            "orphanage": f"원장 선생님이 편찮으시면서 {v['origin_place']}의 운영비가 끊길 위기에 놓였습니다. 열두 살 {v['name']} 앞에는 낡은 통장과 아이들의 불안한 눈빛이 놓여 있습니다.",
            "noodle_shop": f"대형 마트가 골목 어귀에 들어서면서 {v['origin_place']}의 손님이 반토막 났습니다. 밤늦도록 한숨 쉬는 어머니의 어깨가 유난히 작아 보입니다.",
            "scholar_home": f"집안 어른들이 바라는 성적에 한 문제 차이로 미끄러진 날, 싸늘한 서재의 침묵이 열두 살 {v['name']}의 어깨를 짓누릅니다.",
            "fallen_house": f"마지막으로 남아 있던 {v['origin_place']}마저 경매에 넘어가, {v['name']}의 가족은 단칸방으로 짐을 싸야만 했습니다.",
            "artisan_shop": f"아버지의 손가락 관절이 붓기 시작하면서, 정밀한 수리 의뢰들이 줄줄이 끊기고 공방 임대료 독촉장이 날아왔습니다.",
            "mountain_clinic": f"폭우로 산길이 끊긴 밤, 열이 펄펄 끓는 마을 노인을 업고 어른들이 아랫마을로 내려가야 하는 긴박한 상황이 벌어졌습니다.",
        }
        return _make_node(
            "b3_trial",
            f"🌩️ {age}세 — 어린 어깨에 내려앉은 첫 현실",
            trial_desc.get(origin_id, trial_desc["orphanage"]),
            2,
            [
                {
                    "id": "b3_protect",
                    "label": "💪 내가 당장 팔을 걷어붙여 곁의 사람들을 돕는다",
                    "hint": "근성 +7 · 자산 +4 · 책임감 있는 다짐",
                    "delta": {"grit": 7, "wealth": 4},
                    "add_flags": ["promise_protect"],
                    "log": "열두 살의 시련 앞에서 도망치지 않고, 내 힘으로 곁의 사람을 지키기로 다짐했다.",
                },
                {
                    "id": "b3_truth",
                    "label": "🧠 문제의 구조를 파악해 돌파구를 찾아낸다",
                    "hint": "지성 +7 · 공감 +2 · 본질을 꿰뚫는 시선",
                    "delta": {"intellect": 7, "empathy": 2},
                    "add_flags": ["promise_truth"],
                    "log": "막연한 걱정 대신 원인을 차분히 분석해 해결의 실마리를 찾는 힘을 길렀다.",
                },
                {
                    "id": "b3_express",
                    "label": "🎵 흔들리는 마음을 노래·글·그림으로 달래며 버틴다",
                    "hint": "열정 +7 · 공감 +3 · 예술로 승화하는 마음",
                    "delta": {"passion": 7, "empathy": 3},
                    "add_flags": ["promise_express"],
                    "log": "슬픔과 불안을 낡은 공책 한 권의 기록과 선율로 바꿔 마음을 단단히 묶었다.",
                },
            ],
        )

    # ── BEAT 4 (Age 14 · 청소년기 ①: 중학교 동아리와 적성) ──
    if beat == 4:
        return _make_node(
            "b4_aptitude",
            f"🏫 {age}세 — 사춘기의 오후, 마음이 끌리는 방과 후",
            (
                f"교복이 조금씩 몸에 익어갈 무렵, {v['name']}은(는) 자신이 가장 시간 가는 줄 모르고 몰두할 수 있는 영역을 발견합니다. "
                f"학교 게시판에 붙은 네 장의 모집 포스터 앞에서 당신의 발걸음이 멈춥니다."
            ),
            2,
            [
                {
                    "id": "b4_art",
                    "label": "🎨 문예·미술·음악창작반 (내 안의 이야기를 세상에)",
                    "hint": "열정 +7 · 공감 +2 · 예술 루트 적성+",
                    "delta": {"passion": 7, "empathy": 2},
                    "add_flags": ["apt_art"],
                    "log": "방과 후 낡은 예술실에 남아 색과 소리, 문장으로 세상을 번역하기 시작했다.",
                },
                {
                    "id": "b4_study",
                    "label": "🔬 과학·천문·독서탐구반 (세상의 법칙을 손에)",
                    "hint": "지성 +8 · 학문 루트 적성+ · 별의 씨앗",
                    "delta": {"intellect": 8},
                    "add_flags": ["apt_study", "star_seed"],
                    "log": "도서관과 과학실을 내 집처럼 드나들며 자연과 별, 인간의 구조를 탐구했다.",
                },
                {
                    "id": "b4_justice",
                    "label": "📰 교지편집·학생자치·봉사반 (세상의 부조리를 향해)",
                    "hint": "공감 +6 · 근성 +3 · 수호/언론 루트 적성+",
                    "delta": {"empathy": 6, "grit": 3},
                    "add_flags": ["apt_justice"],
                    "log": "학교 안팎의 억울한 목소리를 기록하고 곁의 친구들을 대변하기 시작했다.",
                },
                {
                    "id": "b4_craft",
                    "label": "🔧 실전 기술·장사·공방 아르바이트 (내 두 손의 가치)",
                    "hint": "자산 +6 · 근성 +5 · 장인/사업 루트 적성+",
                    "delta": {"wealth": 6, "grit": 5},
                    "add_flags": ["apt_craft"],
                    "log": "책상 앞보다 현장과 장사, 손기술 속에서 살아 움직이는 진짜 배움을 택했다.",
                },
            ],
        )

    # ── BEAT 5 (Age 16 · 청소년기 ②: 스승 {mentor}와 편법의 유혹) ──
    if beat == 5:
        mentor_ctx = "엄격하기로 소문난 원로 강사"
        if "apt_art" in flags:
            mentor_ctx = "무명의 괴짜 예술가"
        elif "apt_study" in flags:
            mentor_ctx = "은퇴한 대학 연구원"
        elif "apt_craft" in flags:
            mentor_ctx = "30년 경력의 베테랑 장인"
        elif "apt_justice" in flags:
            mentor_ctx = "현장을 누비던 퇴직 기자"

        return _make_node(
            "b5_mentor",
            f"🕯️ {age}세 — 스승 '{v['mentor']}'와(과) 첫 번째 지름길의 유혹",
            (
                f"고등학생이 된 {v['name']}은(는) {mentor_ctx} **{v['mentor']}**의 눈에 띄어 특별 지도를 받게 됩니다. "
                f"하지만 기초만 반복하는 혹독한 훈련에 지쳐갈 때쯤, 주변의 한 선배가 귓속말로 솔깃한 제안을 건넵니다.\n"
                f"> *\"야, 누가 요즘 고지식하게 기본기부터 파냐? 요령만 쓰면 대회 상도, 알바 수당도 바로 두 배야.\"*"
            ),
            2,
            [
                {
                    "id": "b5_honest",
                    "label": f"🧭 묵묵히 {v['mentor']}의 기본기를 끝까지 파고든다",
                    "hint": "근성 +6 · 지성 +4 · 정직하고 단단한 뿌리",
                    "delta": {"grit": 6, "intellect": 4},
                    "add_flags": ["honest_path", "mentor_loyal"],
                    "log": f"{v['mentor']} 밑에서 고된 기본기를 견뎌내며 정직한 실력의 뿌리를 내렸다.",
                },
                {
                    "id": "b5_shortcut",
                    "label": "🪙 선배의 요령을 배워 빠르게 성과와 돈을 챙긴다",
                    "hint": "자산 +8 · 열정 +4 · 공감 -4 · 편법의 유혹",
                    "delta": {"wealth": 8, "passion": 4, "empathy": -4},
                    "add_flags": ["shortcut_tempted"],
                    "log": "느린 정석 대신 빠른 요령과 편법의 달콤한 맛을 처음 알아버렸다.",
                },
                {
                    "id": "b5_rebel",
                    "label": f"🕊️ {v['mentor']}께 감사를 남기고 나만의 독자적 실험을 떠난다",
                    "hint": "열정 +7 · 지성 +3 · 기존 틀을 깨는 자유로운 기질",
                    "delta": {"passion": 7, "intellect": 3},
                    "add_flags": ["rebel_spirit"],
                    "log": f"{v['mentor']}의 틀마저 넘어 자기만의 방식을 찾겠다는 대담한 선언을 남겼다.",
                },
            ],
        )

    # ── BEAT 6 (Age 18 · 청소년기 ③: 졸업 전야의 약속) ──
    if beat == 6:
        if "comp_close" in flags or "comp_rival" in flags:
            rel_word = "어느새 누구보다 소중한 존재가 된" if "comp_close" in flags else "티격태격하던 날들을 지나 어느새 가장 서로를 잘 이해하는"
            return _make_node(
                "b6_promise_comp",
                f"🌙 {age}세 — 졸업 전날 밤, '{v['companion']}'와(과) 나눈 진심",
                (
                    f"열여덟의 마지막 겨울밤. {rel_word} **{v['companion']}**와(과) 학교 옥상(혹은 방파제)에 나란히 앉았습니다. "
                    f"하얀 입김 사이로 대학, 취업, 돈 걱정 같은 어른들의 이야기가 처음으로 두 사람 사이를 스칩니다. "
                    f"**{v['companion']}**가 조용히 먼저 말을 꺼냅니다.\n"
                    f"> *\"스무 살이 되면 우리, 각자 어디쯤 가 있을까?\"*"
                ),
                1,
                [
                    {
                        "id": "b6_comp_promise",
                        "label": f"🤝 \"어떤 길을 가든 20대에 다시 서로를 찾자\"고 약속한다",
                        "hint": "공감 +6 · 열정 +2 · 운명적 재회 약속",
                        "delta": {"empathy": 6, "passion": 2},
                        "add_flags": ["comp_promised"],
                        "log": f"{v['companion']}와 미래에도 서로의 편이 되어주자는 깊은 약속을 나누었다.",
                    },
                    {
                        "id": "b6_comp_warm",
                        "label": "✨ \"각자의 꿈에서 빛난 뒤에 멋지게 만나자\"며 응원한다",
                        "hint": "열정 +5 · 공감 +3 · 아련하지만 건강한 이별",
                        "delta": {"passion": 5, "empathy": 3},
                        "add_flags": ["comp_parted_warm"],
                        "log": f"{v['companion']}와 서로의 날개를 응원하며 웃음과 아쉬움이 섞인 작별을 했다.",
                    },
                    {
                        "id": "b6_comp_cold",
                        "label": "❄️ 목표에만 집중하기 위해 감정을 접고 거리를 둔다",
                        "hint": "지성 +5 · 근성 +5 · 공감 -4 · 고독한 야망",
                        "delta": {"intellect": 5, "grit": 5, "empathy": -4},
                        "add_flags": ["solo_focus"],
                        "log": "감정이 앞길을 붙잡을까 두려워 일부러 마음을 닫고 혼자만의 싸움을 택했다.",
                    },
                ],
            )
        return _make_node(
            "b6_promise_solo",
            f"🌠 {age}세 — 홀로 올려다본 열여덟의 겨울 하늘",
            (
                f"졸업을 앞둔 열여덟의 밤, {v['name']}은(는) 누구의 동행도 없이 홀로 옥상 계단에 앉아 별이 쏟아지는 밤하늘을 바라봅니다. "
                f"어린 날 주머니에 넣어 두었던 `{v['origin_item']}`을 만지작거리며, 곧 닥칠 스무 살의 세상에 무엇을 걸 것인지 스스로에게 묻습니다."
            ),
            1,
            [
                {
                    "id": "b6_solo_fame",
                    "label": "🔥 언젠가 온 세상이 내 이름을 기억하게 만들겠다",
                    "hint": "열정 +6 · 지성 +4 · 강렬한 성취욕",
                    "delta": {"passion": 6, "intellect": 4},
                    "add_flags": ["dream_fame"],
                    "log": "고독을 연료 삼아 언젠가 세상에 뚜렷한 흔적을 남기겠다고 다짐했다.",
                },
                {
                    "id": "b6_solo_star",
                    "label": "🌌 별빛과 사람의 마음을 잇는 삶의 의미를 찾고 싶다",
                    "hint": "지성 +7 · 공감 +5 · 숨겨진 통찰(별의 씨앗)",
                    "delta": {"intellect": 7, "empathy": 5},
                    "add_flags": ["star_seed"],
                    "log": "보이는 성공보다 삶과 시간이 건네는 깊은 질문에 답해보고 싶다는 소망을 품었다.",
                },
                {
                    "id": "b6_solo_grit",
                    "label": "💰 누구에게도 흔들리지 않을 단단한 기반을 세우겠다",
                    "hint": "근성 +6 · 자산 +6 · 자수성가의 의지",
                    "delta": {"grit": 6, "wealth": 6},
                    "add_flags": ["self_made"],
                    "log": "냉정한 세상 속에서 스스로를 지킬 현실적인 힘과 자산을 쌓기로 마음먹었다.",
                },
            ],
        )

    # ── BEAT 7 (Age 19 · 청년기 ①: 스무 살, 평생의 첫 진로 결정) ──
    if beat == 7:
        top2 = _pick_top_careers(stats, flags)
        def _tag(c_id: str) -> str:
            return " [추천]" if c_id in top2 else ""

        choices = [
            {
                "id": "c_artist",
                "label": f"🎨 예술·창작가의 길{_tag('artist')}",
                "hint": "열정 +6 · 화가·작곡가·작가 등 자유로운 표현의 세계로",
                "delta": {"passion": 6, "wealth": -2},
                "set_career": "artist",
                "log": "불확실한 생계를 각오하고 예술과 창작의 길에 첫 발을 내디뎠다.",
            },
            {
                "id": "c_scholar",
                "label": f"🔬 학자·의학·연구의 길{_tag('scholar')}",
                "hint": "지성 +6 · 밤을 새워 진리와 생명을 탐구하는 길로",
                "delta": {"intellect": 6, "grit": 1},
                "set_career": "scholar",
                "log": "두꺼운 전공서와 실험 노트를 안고 학문과 연구의 세계로 들어섰다.",
            },
            {
                "id": "c_entrepreneur",
                "label": f"💼 사업·청년 창업의 길{_tag('entrepreneur')}",
                "hint": "자산 +6 · 열정 +2 · 시장 한복판에서 부와 기회를 일구는 길로",
                "delta": {"wealth": 6, "passion": 2},
                "set_career": "entrepreneur",
                "log": "작은 종잣돈과 패기 하나로 치열한 사업의 바다에 뛰어들었다.",
            },
            {
                "id": "c_artisan",
                "label": f"🌿 장인·공방·요리의 길{_tag('artisan')}",
                "hint": "근성 +5 · 공감 +3 · 땀과 손끝으로 삶의 온기를 만드는 길로",
                "delta": {"grit": 5, "empathy": 3},
                "set_career": "artisan",
                "log": "화려한 스포트라이트 대신 내 손으로 물건과 음식을 빚어내는 장인의 길을 택했다.",
            },
            {
                "id": "c_guardian",
                "label": f"⚖️ 수호자·탐사언론의 길{_tag('guardian')}",
                "hint": "공감 +5 · 근성 +3 · 세상의 약자와 진실을 지키는 최전선으로",
                "delta": {"empathy": 5, "grit": 3},
                "set_career": "guardian",
                "log": "현장의 부조리에 눈감지 않기 위해 수사·구조·언론의 길을 선택했다.",
            },
        ]
        if "shortcut_tempted" in flags and _safe_int(stats.get("empathy"), 20) <= 26:
            choices.append({
                "id": "c_shadow",
                "label": "🎭 뒷세계 정보 브로커의 길",
                "hint": "자산 +10 · 공감 -5 · 이름 없이 어둠의 거래를 중개하는 위험한 길",
                "delta": {"wealth": 10, "empathy": -5},
                "set_career": "shadow",
                "add_flags": ["corrupted"],
                "log": "선량한 규칙에 등을 돌리고 도시의 그림자 속에서 비밀을 파는 브로커가 되었다.",
            })
        else:
            choices.append({
                "id": "c_wanderer",
                "label": f"🧭 방랑·세계 기록가의 길{_tag('wanderer')}",
                "hint": "열정 +4 · 지성 +4 · 정해진 울타리를 넘어 길 위에서 살아가는 길로",
                "delta": {"passion": 4, "intellect": 4},
                "set_career": "wanderer",
                "log": "남들이 정한 궤도를 거부하고 낡은 배낭을 메고 세상의 길 위로 나섰다.",
            })

        return _make_node(
            "b7_career",
            f"🚪 {age}세 — 스무 살의 문턱, 어떤 삶으로 걸어갈 것인가",
            (
                f"이제 누구의 보호막도 없이 스스로의 이름으로 서야 할 스무 살이 되었습니다. "
                f"지금까지 {v['name']}이(가) 걸어온 유년과 청소년의 조각들이 묵직하게 손에 잡힙니다. "
                f"어떤 직업을 택하느냐에 따라 앞으로 마주할 시련과 인연, 그리고 인생의 결말이 전혀 달라집니다."
            ),
            3,
            choices,
        )

    # ── BEAT 8 (Age 22 · 청년기 ②: 선택한 직업에서의 첫 데뷔와 혹독한 신고식) ──
    if beat == 8:
        debut_map = {
            "artist": (
                f"🎨 {age}세 — 빈털터리 첫 데뷔 무대, 그리고 거친 혹평",
                f"스물둘의 {v['name']}은(는) 반지하 방에서 3년을 매달린 첫 작품을 세상에 내놓았습니다. "
                f"그러나 평론가들은 \"재능은 보이나 투박하다\"며 냉담했고, 통장 잔고는 바닥을 드러냅니다.",
                [
                    {"id": "d_art_pure", "label": "🔥 혹평에 굴하지 않고 밤새 내 색깔을 더 벼린다", "hint": "열정 +7 · 근성 +3 · 순수 창작의 자존심", "delta": {"passion": 7, "grit": 3}, "add_flags": ["pure_art"], "log": "혹평과 가난을 삼키며 타협 없는 자신만의 작품 세계를 파고들었다."},
                    {"id": "d_art_pop", "label": "💰 당장 먹고살기 위해 유행하는 상업 외주도 겸한다", "hint": "자산 +7 · 공감 +2 · 현실과의 유연한 공존", "delta": {"wealth": 7, "empathy": 2}, "add_flags": ["commercial_skill"], "log": "상업 외주 작업으로 생계를 유지하면서도 틈틈이 창작의 불씨를 살렸다."},
                    {"id": "d_art_copy", "label": "⚠️ 유명 작가의 콘셉트를 슬쩍 베껴 빠르게 이름을 알린다", "hint": "자산 +9 · 열정 -4 · 공감 -5 · 어긋난 첫 발", "delta": {"wealth": 9, "passion": -4, "empathy": -5}, "add_flags": ["corrupted"], "log": "초조함 끝에 남의 아이디어를 차용해 단기간에 주목을 샀으나 가책이 남았다."},
                ],
            ),
            "scholar": (
                f"🔬 {age}세 — 새벽 연구실의 불빛과 임상/실험의 기로",
                f"스물둘의 연구원/의학도 {v['name']} 앞에는 밤낮없이 밀려드는 데이터와 아픈 이들의 현실이 놓여 있습니다. "
                f"지도교수는 화려한 스펙과 논문 실적을, 가슴속 양심은 현장과 사람의 회복을 가리킵니다.",
                [
                    {"id": "d_sch_heal", "label": "🩺 논문의 속도보다 눈앞의 생명과 안전을 최우선으로 삼는다", "hint": "공감 +7 · 지성 +3 · 치유자의 맹세", "delta": {"empathy": 7, "intellect": 3}, "add_flags": ["healer_oath"], "log": "화려한 명예보다 아픈 사람을 살리는 연구와 진료에 헌신하기로 맹세했다."},
                    {"id": "d_sch_deep", "label": "📚 남들이 외면하는 난제 연구에 청춘을 전부 걸어본다", "hint": "지성 +8 · 근성 +3 · 거장을 향한 외길", "delta": {"intellect": 8, "grit": 3}, "add_flags": ["masterwork_kept"], "log": "모두가 비효율적이라 말한 기초 난제 연구를 끝까지 파고들기 시작했다."},
                    {"id": "d_sch_stat", "label": "⚠️ 선배의 지시대로 애매한 실험 수치를 유리하게 다듬는다", "hint": "자산 +7 · 지성 -3 · 공감 -5 · 학자의 금기", "delta": {"wealth": 7, "intellect": -3, "empathy": -5}, "add_flags": ["corrupted"], "log": "빠른 학위와 승진을 위해 데이터 일부를 눈감고 넘기는 잘못된 타협을 했다."},
                ],
            ),
            "entrepreneur": (
                f"💼 {age}세 — 첫 사업 자금의 위기와 냉혹한 계약서",
                f"작은 사무실에서 야심 차게 문을 연 {v['name']}의 사업이 첫 납품 기한을 앞두고 자금난에 빠졌습니다. "
                f"이대로 무너지면 보증금까지 날릴 절체절명의 밤, 세 가지 선택지가 책상 위에 놓입니다.",
                [
                    {"id": "d_ent_grit", "label": "🛡️ 거래처를 직접 발로 뛰며 정공법으로 신뢰를 얻는다", "hint": "근성 +7 · 자산 +5 · 정직한 사업의 기초", "delta": {"grit": 7, "wealth": 5}, "add_flags": ["honest_path"], "log": "밤새 발품을 팔아 거래처를 설득한 끝에 정공법으로 첫 위기를 돌파했다."},
                    {"id": "d_ent_bold", "label": "🚀 전 재산을 추가 베팅해 신기술·신메뉴로 판을 뒤집는다", "hint": "열정 +6 · 자산 +8 · 근성 -3 · 승부사의 기질", "delta": {"passion": 6, "wealth": 8, "grit": -3}, "add_flags": ["high_roller"], "log": "퇴로를 끊는 승부수를 던져 기적처럼 첫 대박 계약을 따냈다."},
                    {"id": "d_ent_scam", "label": "⚠️ 원가를 속이고 하청 대금을 미뤄 당장의 흑자를 만든다", "hint": "자산 +11 · 공감 -7 · 신뢰를 판 대가", "delta": {"wealth": 11, "empathy": -7}, "add_flags": ["corrupted"], "log": "당장의 수익을 위해 약자의 대금을 깎는 비정한 방식에 손을 대고 말았다."},
                ],
            ),
            "artisan": (
                f"🌿 {age}세 — 하루 열두 시간, 땀방울로 빚은 첫 손님",
                f"남들보다 이른 아침마다 불을 지피고 톱밥과 밀가루를 뒤집어쓰던 {v['name']}. "
                f"드디어 온전히 자신의 손으로 만든 결과물을 첫 손님에게 내놓는 순간이 찾아옵니다.",
                [
                    {"id": "d_artn_craft", "label": "🔨 단가가 안 맞아도 최상급 재료와 정성만 고집한다", "hint": "근성 +6 · 공감 +4 · 장인의 고집", "delta": {"grit": 6, "empathy": 4}, "add_flags": ["masterwork_kept"], "log": "이윤이 적더라도 부끄럽지 않은 물건·음식만 내놓겠다는 장인의 원칙을 세웠다."},
                    {"id": "d_artn_local", "label": "🏘️ 동네 단골들의 사정과 입맛에 맞춘 따뜻한 공간으로 키운다", "hint": "공감 +7 · 자산 +4 · 골목의 등불", "delta": {"empathy": 7, "wealth": 4}, "add_flags": ["protect_local"], "log": "누구나 편히 들러 숨을 돌릴 수 있는 동네의 따뜻한 사랑방을 일구었다."},
                    {"id": "d_artn_eff", "label": "⚙️ 효율적인 기계 공정과 외주 납품을 도입해 규모를 키운다", "hint": "자산 +8 · 열정 -2 · 실리적 확장", "delta": {"wealth": 8, "passion": -2}, "add_flags": ["scaled_shop"], "log": "효율적인 생산 체계를 도입해 빠르게 가게 규모를 키우는 실리를 택했다."},
                ],
            ),
            "guardian": (
                f"⚖️ {age}세 — 첫 현장, 덮으라는 지시와 살아있는 증거",
                f"수습 딱지를 갓 뗀 {v['name']} 앞에 지역 유력 인사가 연루된 수상한 사고 기록이 떨어집니다. "
                f"상사는 조용히 서류를 서랍에 넣으라 눈짓하고, 피해자 가족은 문밖에서 떨고 있습니다.",
                [
                    {"id": "d_grd_truth", "label": "⚖️ 상부의 압력을 뿌리치고 밤새 진짜 증거를 캔다", "hint": "공감 +6 · 근성 +5 · 자산 -2 · 불굴의 수호자", "delta": {"empathy": 6, "grit": 5, "wealth": -2}, "add_flags": ["whistleblower", "honest_path"], "log": "수습 시절부터 권력의 눈치를 보지 않고 피해자 편에 서는 강골로 이름을 알렸다."},
                    {"id": "d_grd_smart", "label": "🧠 조용히 사본을 확보한 뒤 결정적 타이밍을 기다린다", "hint": "지성 +7 · 근성 +3 · 치밀한 전략", "delta": {"intellect": 7, "grit": 3}, "add_flags": ["patient_strategy"], "log": "성급히 부딪히기보다 증거를 치밀하게 모아 더 큰 판을 움직일 때를 기다렸다."},
                    {"id": "d_grd_obey", "label": "😶 현실의 벽 앞에서 눈을 감고 상부의 처분에 따른다", "hint": "자산 +7 · 공감 -6 · 첫 양심의 균열", "delta": {"wealth": 7, "empathy": -6}, "add_flags": ["corrupted"], "log": "불이익이 두려워 정의 대신 침묵을 택한 그날 밤, 잠을 이루지 못했다."},
                ],
            ),
            "wanderer": (
                f"🧭 {age}세 — 낯선 항구의 폭우, 여권도 동전도 젖어버린 밤",
                f"무작정 오른 배와 기차 끝에서, {v['name']}은(는) 말도 통하지 않는 낯선 항구 도시에 홀로 남겨집니다. "
                f"가방 속엔 젖어버린 수첩과 어린 날 챙겨온 `{v['origin_item']}`뿐입니다.",
                [
                    {"id": "d_wnd_write", "label": "✍️ 길 위의 낯선 이들에게 밥을 얻어먹으며 그들의 이야기를 적는다", "hint": "공감 +7 · 열정 +5 · 인간에 대한 깊은 시선", "delta": {"empathy": 7, "passion": 5}, "add_flags": ["star_seed"], "log": "낯선 이들의 친절에 빚지며 세상의 작은 이야기들을 수첩 가득 받아 적었다."},
                    {"id": "d_wnd_grit", "label": "⚓ 부두의 막노동과 선원 일을 도우며 스스로 노잣돈을 번다", "hint": "근성 +8 · 자산 +4 · 거친 생존력", "delta": {"grit": 8, "wealth": 4}, "add_flags": ["tough_survivor"], "log": "거친 바다와 노동 속에서 어떤 땅에서도 살아남을 강인한 생존력을 기르고 돌아왔다."},
                    {"id": "d_wnd_smug", "label": "🎭 항구 뒷골목의 수상한 밀수 심부름으로 큰돈을 만진다", "hint": "자산 +10 · 공감 -5 · 위험한 탈선", "delta": {"wealth": 10, "empathy": -5}, "set_career": "shadow", "add_flags": ["corrupted"], "log": "궁핍함 끝에 손댄 뒷거래를 계기로 어두운 그림자의 세계에 발을 들였다."},
                ],
            ),
            "shadow": (
                f"🎭 {age}세 — 가면 아래의 첫 거액, 그리고 피어나는 의심",
                f"차명 계좌와 암호화된 메모로 첫 큰돈을 쥔 스물둘의 {v['name']}. "
                f"그러나 의뢰인이 남긴 자료 속에는 평범한 소시민의 가정이 파괴될 정황이 담겨 있습니다.",
                [
                    {"id": "d_shd_cold", "label": "🧊 감정은 사치다. 의뢰 조건만 정확히 이행한다", "hint": "자산 +10 · 지성 +3 · 공감 -6 · 철저한 프로", "delta": {"wealth": 10, "intellect": 3, "empathy": -6}, "add_flags": ["corrupted"], "log": "죄책감을 지우는 법을 배우며 그림자 시장에서 이름 높은 브로커로 자리 잡았다."},
                    {"id": "d_shd_leak", "label": "🕳️ 익명으로 피해자에게 경고장만 몰래 보내 숨통을 틔워준다", "hint": "공감 +5 · 지성 +4 · 근성 -2 · 남아있는 인간성", "delta": {"empathy": 5, "intellect": 4, "grit": -2}, "add_flags": ["secret_mercy"], "log": "어둠 속에서도 최소한의 선만은 넘지 않으려 남몰래 누군가를 살려두었다."},
                ],
            ),
        }
        t, b, chs = debut_map.get(career, debut_map["artisan"])
        return _make_node(f"b8_{career}", t, b, 4, chs)

    # ── BEAT 9 (Age 26 · 청년기 ③: 사랑과 동반자의 분기) ──
    if beat == 9:
        if "comp_promised" in flags:
            return _make_node(
                "b9_reunion_comp",
                f"💐 {age}세 — 약속처럼 다시 찾아온 '{v['companion']}'",
                (
                    f"스물여섯의 봄비가 내리던 퇴근길, 작업실(직장) 문 앞에서 오래전 젖은 우산을 함께 썼던 **{v['companion']}**가 "
                    f"미소 지으며 서 있습니다. \"열여덟 밤에 한 약속, 난 아직도 기억해.\" "
                    f"삶이 치열할수록 함께 손잡을 사람이 있다는 것이 축복일지, 짐일지 마음이 요동칩니다."
                ),
                4,
                [
                    {
                        "id": "b9_commit_comp",
                        "label": f"💍 {v['companion']}의 손을 잡고 함께 미래를 꾸린다",
                        "hint": "공감 +8 · 열정 +3 · 동반자 확정",
                        "delta": {"empathy": 8, "passion": 3},
                        "set_partner": v["companion"],
                        "add_flags": ["has_partner", "partner_committed"],
                        "log": f"{v['companion']}와 다시 만나 서로의 평생 동반자가 되기로 약속했다.",
                    },
                    {
                        "id": "b9_miss_comp",
                        "label": "💔 지금 내 삶이 너무 버거워 눈물을 삼키며 돌려보낸다",
                        "hint": "근성 +4 · 열정 +3 · 공감 -3 · 아픈 이별(훗날의 여운)",
                        "delta": {"grit": 4, "passion": 3, "empathy": -3},
                        "add_flags": ["comp_missed", "solo_path"],
                        "log": f"{v['companion']}를 붙잡지 못한 죄책감과 그리움을 안고 홀로 일에 매달렸다.",
                    },
                ],
            )

        meet_scene = {
            "artist": f"작은 갤러리/공연장 뒤풀이에서 같은 감성을 알아본 **{v['adult_partner']}**",
            "scholar": f"밤새 불 켜진 도서관·응급실 맞은편에서 묵묵히 커피를 건넨 **{v['adult_partner']}**",
            "entrepreneur": f"거래처 미팅 끝에 빗길에서 우연히 마주친 따뜻하고 당찬 **{v['adult_partner']}**",
            "artisan": f"늘 같은 시간마다 공방(가게)에 들러 진심 어린 미소를 건네던 **{v['adult_partner']}**",
            "guardian": f"지친 현장 복귀길, 묵묵히 이야기를 들어주며 버팀목이 되어준 **{v['adult_partner']}**",
            "wanderer": f"낯선 여행지의 기차 칸에서 같은 지도를 펼쳐 들고 웃음을 터뜨린 **{v['adult_partner']}**",
            "shadow": f"가면을 쓴 당신의 진짜 이름을 묻지 않은 채 상처만 감싸안아 준 **{v['adult_partner']}**",
        }
        return _make_node(
            "b9_new_love",
            f"💞 {age}세 — 치열한 청춘 한가운데 피어난 인연 '{v['adult_partner']}'",
            (
                f"스물여섯, 앞만 보고 달리던 {v['name']}의 삶에 예상치 못한 온기가 스며듭니다. "
                f"{meet_scene.get(career, meet_scene['artisan'])}와(과) 어느덧 서로의 내일을 함께 그려보는 사이가 되었습니다."
            ),
            4,
            [
                {
                    "id": "b9_commit_new",
                    "label": f"💍 {v['adult_partner']}에게 마음을 열고 평생의 곁을 내어준다",
                    "hint": "공감 +8 · 근성 +2 · 가정을 이루는 길",
                    "delta": {"empathy": 8, "grit": 2},
                    "set_partner": v["adult_partner"],
                    "add_flags": ["has_partner", "partner_committed"],
                    "log": f"{v['adult_partner']}와 깊은 신뢰를 나누며 함께 살아갈 둥지를 꾸렸다.",
                },
                {
                    "id": "b9_stay_solo",
                    "label": "🕊️ 인연에 감사하면서도 지금은 내 길에 온전히 집중한다",
                    "hint": "지성 +4 · 열정 +5 · 독립적 행보",
                    "delta": {"intellect": 4, "passion": 5},
                    "add_flags": ["solo_path"],
                    "log": "누군가에게 얽매이기보다 자기 자신의 길을 끝까지 가보기로 정했다.",
                },
            ],
        )

    # ── BEAT 10 (Age 30 · 청년기 ④: 서른 살의 폭풍 — 양심 vs 출세 vs 전직) ──
    if beat == 10:
        storm_map = {
            "artist": (
                f"⛈️ {age}세 — 거대 기획사의 천문학적 계약서 vs 훼손되는 원작",
                f"서른의 {v['name']}에게 드디어 큰 기회가 찾아옵니다. 하지만 상대는 작품의 핵심 메시지를 전부 빼고 자극적인 유행만 넣으라 요구합니다.",
            ),
            "scholar": (
                f"⛈️ {age}세 — 제약사/연구단의 거액 스폰서 제의와 부작용 은폐",
                f"서른이 된 {v['name']}은(는) 핵심 프로젝트의 부작용 단서를 발견했습니다. 발표하면 모든 연구비와 직위가 날아가고, 덮으면 엄청난 부가 따라옵니다.",
            ),
            "entrepreneur": (
                f"⛈️ {age}세 — 동업자의 횡령 유혹과 무리한 상장 레이스",
                f"사업이 본궤도에 오른 서른 살, 핵심 파트너가 \"다들 이렇게 세금과 서류를 맞춘다\"며 장부 조작을 제안합니다.",
            ),
            "artisan": (
                f"⛈️ {age}세 — 재개발 철거 통보와 대기업 프랜차이즈 인수 제안",
                f"골목 터줏대감이 되어가던 {v['name']}의 가게/공방에 거대 자본이 거액의 권리금을 내밀며 브랜드를 넘기라 제안합니다.",
            ),
            "guardian": (
                f"⛈️ {age}세 — 거대 권력의 비리 제보, 곁을 노리는 협박 전화",
                f"서른의 {v['name']} 손에 윗선 전체를 뒤흔들 결정적 파일이 쥐어졌습니다. 보복과 가족(동료)의 위험이 눈앞에 어른거립니다.",
            ),
            "wanderer": (
                f"⛈️ {age}세 — 분쟁 지역의 기록 의뢰 vs 안전한 베스트셀러 계약",
                f"세상의 빛과 어둠을 기록하던 {v['name']}에게 아무도 가려 하지 않는 위험 지역의 진실을 전해달라는 간절한 요청이 도착합니다.",
            ),
            "shadow": (
                f"⛈️ {age}세 — 조직의 마지막 선을 넘는 의뢰, 혹은 탈출의 틈",
                f"그림자 세계의 정점에 가까워진 서른 살. 이제 단순 정보 중개를 넘어 돌이킬 수 없는 범죄의 공범이 될 기로에 섰습니다.",
            ),
        }
        st_title, st_body = storm_map.get(career, storm_map["artisan"])
        choices = [
            {
                "id": "b10_stand",
                "label": "⚖️ 손해를 보더라도 내 신념과 진실만큼은 절대 팔지 않는다",
                "hint": "공감 +6 · 지성 +4 · 자산 -5 · 올곧은 지조",
                "delta": {"empathy": 6, "intellect": 4, "wealth": -5},
                "add_flags": ["honest_path", "whistleblower"] if career == "guardian" else ["honest_path"],
                "remove_flags": ["corrupted"],
                "log": "서른 살의 큰 유혹 앞에서 손해를 감수하고 스스로의 양심과 원칙을 지켜냈다.",
            },
            {
                "id": "b10_compromise",
                "label": "💰 세상은 원래 타협하는 법. 눈을 질끈 감고 조건을 받아들인다",
                "hint": "자산 +14 · 공감 -8 · 지성 -2 · 어두운 성취",
                "delta": {"wealth": 14, "empathy": -8, "intellect": -2},
                "add_flags": ["corrupted"],
                "log": "부귀와 지위를 얻는 대신, 오랫동안 지켜온 원칙을 세상의 조건과 맞바꾸고 말았다.",
            },
        ]
        if origin_id == "noodle_shop" and career != "artisan":
            choices.append({
                "id": "b10_noodle_pivot",
                "label": "🍜 지친 욕심을 접고 어머니의 작은 국수집으로 돌아간다",
                "hint": "공감 +8 · 근성 +5 · 장인 루트로 전직(국수집 부활)",
                "delta": {"empathy": 8, "grit": 5},
                "set_career": "artisan",
                "add_flags": ["noodle_revival", "honest_path"],
                "remove_flags": ["corrupted"],
                "log": "화려한 경쟁에서 걸어 나와 시장통 낡은 국수집 불을 다시 지피는 새로운 길을 택했다.",
            })
        else:
            choices.append({
                "id": "b10_pivot_freedom",
                "label": "🧭 현 시스템에 환멸을 느껴 낡은 가방을 메고 새로운 길로 떠난다",
                "hint": "열정 +6 · 지성 +4 · 방랑·기록가로 전직",
                "delta": {"passion": 6, "intellect": 4},
                "set_career": "wanderer",
                "add_flags": ["honest_path"],
                "remove_flags": ["corrupted"],
                "log": "기존의 자리를 미련 없이 내려놓고 세상을 직접 두 발로 기록하는 방랑의 길을 택했다.",
            })
        return _make_node("b10_storm", st_title, st_body, 4, choices)

    # ── BEAT 11 (Age 34 · 청년기 ⑤: 가정의 무게 혹은 서른넷의 고독) ──
    if beat == 11:
        if "has_partner" in flags:
            return _make_node(
                "b11_family",
                f"🏡 {age}세 — '{v['partner']}'와(과) 함께 버티는 서른넷의 생활",
                (
                    f"어느덧 {v['partner']}와(과) 식구가 되어 살아가는 지도 여러 해. "
                    f"생활비와 {v['career_label']} 일에 치여 서로의 얼굴을 마주 보고 대화할 시간마저 점점 줄어들고 있습니다. "
                    f"오늘 밤, {v['partner']}가 식탁 앞에 조용히 마주 앉기를 청합니다."
                ),
                5,
                [
                    {
                        "id": "b11_fam_warm",
                        "label": "🫂 일을 조금 줄이더라도 사랑하는 사람의 눈을 보고 속마음을 나눈다",
                        "hint": "공감 +8 · 근성 +3 · 가정의 온기 수호",
                        "delta": {"empathy": 8, "grit": 3},
                        "add_flags": ["family_warm"],
                        "log": f"{v['partner']}의 손을 꼭 잡으며 바쁜 일상 속에서도 가장 소중한 온기를 지켜냈다.",
                    },
                    {
                        "id": "b11_fam_work",
                        "label": "💼 \"가족을 위해서야\"라며 더욱 치열하게 일터로만 파고든다",
                        "hint": "자산 +8 · 열정 +4 · 공감 -6 · 관계의 균열 위험",
                        "delta": {"wealth": 8, "passion": 4, "empathy": -6},
                        "add_flags": ["partner_strained"],
                        "log": "가족을 먹여 살린다는 명목으로 일에만 매몰되어 집 안의 대화가 서서히 식어갔다.",
                    },
                ],
            )
        return _make_node(
            "b11_solo_mature",
            f"🌆 {age}세 — 혼자 사는 원룸(작업실)의 촛불과 성숙",
            (
                f"서른넷이 된 {v['name']}은(는) 텅 빈 방 안으로 돌아와 신발을 벗습니다. "
                f"주변 친구들은 결혼식과 돌잔치로 바쁘지만, 당신의 책상 위에는 오직 자신이 쌓아 온 기록과 치열함만이 놓여 있습니다."
            ),
            5,
            [
                {
                    "id": "b11_solo_health",
                    "label": "🍵 내 몸과 마음을 다독이며 다음 도약을 위해 차분히 정돈한다",
                    "hint": "근성 +8 · 지성 +3 · 내면의 균형",
                    "delta": {"grit": 8, "intellect": 3},
                    "log": "조급함을 내려놓고 규칙적인 생활과 사색으로 서른넷의 고독을 단단히 다듬었다.",
                },
                {
                    "id": "b11_solo_burn",
                    "label": "🔥 잠을 줄여가며 오직 내 작업·목표에만 미친 듯이 몰두한다",
                    "hint": "열정 +9 · 지성 +5 · 근성 -8 · 건강 소모 주의",
                    "delta": {"passion": 9, "intellect": 5, "grit": -8},
                    "add_flags": ["overworked"],
                    "log": "몸이 보내는 경고를 무시한 채 밤낮없이 목표에 모든 체력을 쏟아부었다.",
                },
                {
                    "id": "b11_solo_share",
                    "label": "🤝 주변의 후배들과 이웃들에게 먼저 손을 내밀어 본다",
                    "hint": "공감 +8 · 열정 +2 · 연대의 회복",
                    "delta": {"empathy": 8, "passion": 2},
                    "add_flags": ["community_care"],
                    "log": "혼자라는 이유로 마음을 닫지 않고 동네와 후배들 사이에서 온기를 나누기 시작했다.",
                },
            ],
        )

    # ── BEAT 12 (Age 39 · 장년기 ①: 마흔을 앞둔 큰 고비 & 불꽃 같은 서른아홉 분기) ──
    if beat == 12:
        cur_grit = _safe_int(stats.get("grit"), 25)
        grit_warn = " (⚠️ 현재 건강/근성이 매우 낮아 위험합니다!)" if cur_grit <= 14 else ""
        return _make_node(
            "b12_crisis39",
            f"🔥 {age}세 — 마흔을 코앞에 둔 대위기, 무너지느냐 불태우느냐",
            (
                f"서른아홉의 한여름 밤, {v['name']}이(가) 몸담은 현장(혹은 이웃 건물)에 대형 화재와 연쇄 붕괴 위기가 동시에 닥칩니다. "
                f"안에는 아직 미처 빠져나오지 못한 아이(또는 평생 매달려온 원본 자료/이웃)가 남아 있고, 건물 밖에서는 대피 명령이 울립니다.{grit_warn}"
            ),
            5,
            [
                {
                    "id": "b12_heroic_risk",
                    "label": "🔥 목숨을 걸고 붕괴 직전의 불길 속으로 마지막까지 뛰어든다",
                    "hint": "영웅적 희생 (건강이 낮거나 극한 선택 시 [🔥 불꽃 같은 서른아홉] 엔딩 직행 가능)",
                    "delta": {"empathy": 10, "passion": 8, "grit": -18},
                    "add_flags": ["reckless_hero"],
                    "trigger_flame_if_low_grit": True,
                    "log": "서른아홉의 위기 속에서 자기 몸을 던져 소중한 생명과 가치를 구해냈다.",
                },
                {
                    "id": "b12_rescue_smart",
                    "label": "🛡️ 주변 사람들과 협력해 안전한 우회로를 뚫고 구조·수습한다",
                    "hint": "지성 +5 · 공감 +5 · 근성 +3 · 살아남은 지혜",
                    "delta": {"intellect": 5, "empathy": 5, "grit": 3},
                    "add_flags": ["wise_survivor"],
                    "log": "침착하게 주변과 힘을 모아 기적처럼 큰 피해를 막고 무사히 살아남았다.",
                },
                {
                    "id": "b12_flee",
                    "label": "💨 자신의 안위와 남은 가족·자산을 지키기 위해 한 발 물러선다",
                    "hint": "근성 +6 · 자산 +4 · 공감 -3 · 생존 본능",
                    "delta": {"grit": 6, "wealth": 4, "empathy": -3},
                    "log": "무모한 영웅심 대신 냉정하게 자신의 삶을 지켜내며 마흔의 문턱을 넘었다.",
                },
            ],
        )

    # ── BEAT 13 (Age 44 · 장년기 ②: 중년의 인연·떡밥 회수) ──
    if beat == 13:
        if "comp_missed" in flags or "comp_parted_warm" in flags:
            return _make_node(
                "b13_comp_mid_reunion",
                f"🍂 {age}세 — 26년 만의 기적 같은 재회, 흰머리가 섞인 '{v['companion']}'",
                (
                    f"마흔넷의 가을, 낯선 역 앞 횡단보도(혹은 오래된 서점)에서 {v['name']}은(는) 낯익은 목소리에 걸음을 멈춥니다. "
                    f"어느새 눈가에 잔주름이 진 **{v['companion']}**가 환하게 웃으며 서 있었습니다. "
                    f"\"오래 걸렸네, {v['name']}. 그동안 잘 지냈어?\""
                ),
                6,
                [
                    {
                        "id": "b13_old_promise",
                        "label": f"💞 늦었지만 이제라도 {v['companion']}와 남은 세월을 함께 걷는다",
                        "hint": "공감 +10 · 열정 +4 · [오래된 약속의 완성] 핵심 조건",
                        "delta": {"empathy": 10, "passion": 4},
                        "set_partner": v["companion"],
                        "add_flags": ["has_partner", "old_promise_kept"],
                        "remove_flags": ["partner_strained", "comp_missed"],
                        "log": f"수십 년의 우회 끝에 {v['companion']}와 다시 손을 맞잡고 늦깎이 동반자가 되었다.",
                    },
                    {
                        "id": "b13_warm_tea",
                        "label": "☕ 따뜻한 차 한 잔에 옛 시절을 추억하며 좋은 벗으로 남는다",
                        "hint": "공감 +5 · 지성 +4 · 담백한 여운",
                        "delta": {"empathy": 5, "intellect": 4},
                        "add_flags": ["peaceful_closure"],
                        "log": f"{v['companion']}와 지난 세월의 안부를 나눈 뒤 서로의 현재를 축복하며 배웅했다.",
                    },
                ],
            )

        if "has_partner" in flags:
            tone = (
                f"일 중독으로 식어 있던 {v['partner']}와의 거리는 어느새 깊은 침묵이 되었고,"
                if "partner_strained" in flags
                else f"십수 년을 함께 버텨온 {v['partner']}와(과)의 삶에도 중년의 큰 파도가 찾아와,"
            )
            return _make_node(
                "b13_mid_partner",
                f"🏠 {age}세 — 중년의 거센 바람, '{v['partner']}'의 눈물",
                (
                    f"마흔넷, {tone} 가정 경제와 건강 문제로 두 사람 모두 지쳐 있습니다. "
                    f"이 위기를 어떻게 건너느냐가 남은 후반생을 결정할 것입니다."
                ),
                6,
                [
                    {
                        "id": "b13_heal_fam",
                        "label": f"💐 자존심을 내려놓고 {v['partner']}에게 진심으로 사과하며 곁을 지킨다",
                        "hint": "공감 +9 · 근성 +3 · 관계 회복",
                        "delta": {"empathy": 9, "grit": 3},
                        "remove_flags": ["partner_strained"],
                        "add_flags": ["family_reconciled"],
                        "log": f"{v['partner']}에게 진심을 전하며 삐걱거리던 가정을 다시 따뜻하게 품어 안았다.",
                    },
                    {
                        "id": "b13_drift",
                        "label": "📄 서로의 짐을 덜어주자며 각자의 길을 가기로 합의한다",
                        "hint": "자산 -4 · 근성 +3 · 공감 -4 · 쓸쓸한 홀로서기",
                        "delta": {"wealth": -4, "grit": 3, "empathy": -4},
                        "clear_partner": True,
                        "remove_flags": ["has_partner", "partner_committed"],
                        "log": f"{v['partner']}와 긴 대화 끝에 각자의 평온을 위해 정중히 이별을 택했다.",
                    },
                ],
            )

        return _make_node(
            "b13_mentor_legacy",
            f"📦 {age}세 — 스승 '{v['mentor']}'가 남긴 마지막 편지와 나무 상자",
            (
                f"혼자 묵묵히 걸어온 마흔넷의 어느 날, 먼 지방에 계시던 옛 스승 **{v['mentor']}**의 부고와 함께 "
                f"낡은 나무 상자 하나가 배달됩니다. 상자 속에는 스승의 평생 기록과 미완의 노트, 그리고 짧은 편지가 들어 있었습니다.\n"
                f"> *\"자네라면 이 뒤에 올 사람들에게 길을 내어줄 수 있을 걸세.\"*"
            ),
            6,
            [
                {
                    "id": "b13_heir",
                    "label": f"🌟 {v['mentor']}의 뜻을 이어 후배와 제자를 키우기로 마음먹는다",
                    "hint": "공감 +8 · 지성 +5 · [세대를 잇는 스승] 계보",
                    "delta": {"empathy": 8, "intellect": 5},
                    "add_flags": ["mentor_heir", "teacher_path"],
                    "log": f"{v['mentor']}의 유지를 받들어 젊은 세대에게 아낌없이 경험을 나누기 시작했다.",
                },
                {
                    "id": "b13_solo_peak",
                    "label": "🔬 스승의 기록을 발판 삼아 내 개인의 정점에 도전한다",
                    "hint": "열정 +6 · 지성 +6 · 홀로 서는 거장",
                    "delta": {"passion": 6, "intellect": 6},
                    "add_flags": ["masterwork_kept"],
                    "log": f"{v['mentor']}의 유품에서 영감을 얻어 일생일대의 작품/연구에 착수했다.",
                },
            ],
        )

    # ── BEAT 14 (Age 50 · 장년기 ③: 지천명 — 죄업과 참회 / 부와 환원 / 새로운 꿈) ──
    if beat == 14:
        if "corrupted" in flags or career == "shadow":
            return _make_node(
                "b14_reckoning",
                f"⚖️ {age}세 — 지천명(知天命), 과거의 거짓이 문 앞까지 찾아오다",
                (
                    f"쉰 살을 넘긴 밤, 젊은 날 {v['name']}이(가) 편법과 그림자 속에서 묻어두었던 일들이 "
                    f"내부 조사와 언론 제보로 수면 위로 떠오르기 시작합니다. 도망칠 길도, 전부 털어놓을 길도 아직 열려 있습니다."
                ),
                6,
                [
                    {
                        "id": "b14_redeem",
                        "label": "🕯️ 모든 것을 내려놓고 자진 고백·배상하며 두 번째 삶을 산다",
                        "hint": "공감 +12 · 근성 +6 · 자산 -18 · [회개와 두 번째 봄] 루트",
                        "delta": {"empathy": 12, "grit": 6, "wealth": -18},
                        "add_flags": ["redeemed", "honest_path"],
                        "remove_flags": ["corrupted"],
                        "set_career": "artisan" if career == "shadow" else career,
                        "log": "쉰 살의 문턱에서 과거의 죄를 스스로 고백하고 죗값을 치르며 새사람으로 거듭났다.",
                    },
                    {
                        "id": "b14_hide",
                        "label": "🎭 더 두꺼운 돈과 비밀의 장막 뒤로 끝까지 모습을 감춘다",
                        "hint": "자산 +10 · 공감 -8 · 끝없는 불안",
                        "delta": {"wealth": 10, "empathy": -8},
                        "add_flags": ["corrupted"],
                        "log": "진실을 덮기 위해 또 다른 거짓과 돈을 쏟아부으며 누구도 믿지 못하는 삶을 이어갔다.",
                    },
                ],
            )

        if _safe_int(stats.get("wealth"), 0) >= 62 or career == "entrepreneur":
            return _make_node(
                "b14_empire_choice",
                f"🏛️ {age}세 — 손에 쥔 큰 부와 영향력, 어디에 쓸 것인가",
                (
                    f"어린 날 {v['origin_place']}에서 맨손으로 출발했던 {v['name']}은(는) 이제 제법 큰 자산과 이름을 거머쥐었습니다. "
                    f"쉰 살을 맞아, 이 힘을 어떻게 흘려보낼지 선택해야 합니다."
                ),
                6,
                [
                    {
                        "id": "b14_share",
                        "label": "🕊️ 장학재단·무료급식·지역 공방에 자산을 나누며 이웃을 살핀다",
                        "hint": "공감 +10 · 자산 -6 · 존경받는 어른",
                        "delta": {"empathy": 10, "wealth": -6},
                        "add_flags": ["philanthropy", "protect_local"],
                        "log": "모아온 부의 상당 부분을 젊은 세대와 어려운 이웃을 위해 아낌없이 환원했다.",
                    },
                    {
                        "id": "b14_expand",
                        "label": "👑 더 큰 제국과 업계의 정상을 향해 마지막 스퍼트를 올린다",
                        "hint": "자산 +12 · 열정 +5 · 공감 -4 · 제국의 정점",
                        "delta": {"wealth": 12, "passion": 5, "empathy": -4},
                        "add_flags": ["empire_ambition"],
                        "log": "쉰의 나이에도 야망을 꺾지 않고 더 거대한 사업과 영향력을 일구어 나갔다.",
                    },
                    {
                        "id": "b14_explore",
                        "label": "🧭 경영과 자리를 정리하고 평생 꿈꾸던 세계 여행에 나선다",
                        "hint": "열정 +8 · 지성 +5 · 늦깎이 모험",
                        "delta": {"passion": 8, "intellect": 5},
                        "add_flags": ["late_explorer"],
                        "log": "손에 쥐고 있던 직함을 내려놓고 뒤늦은 배낭을 꾸려 넓은 세상으로 떠났다.",
                    },
                ],
            )

        return _make_node(
            "b14_midlife_depth",
            f"🌿 {age}세 — 쉰 살의 오후, 내 인생의 진짜 무늬가 보이다",
            (
                f"인생의 반환점을 돈 {v['name']}. 겉으로 보기엔 소박한 삶일지라도, "
                f"지난 반세기 동안 부딪히고 견뎌낸 세월이 눈빛 속에 깊게 배어 있습니다."
            ),
            6,
            [
                {
                    "id": "b14_teach",
                    "label": "🌟 방황하는 젊은이들에게 내 기술과 시행착오를 전부 알려준다",
                    "hint": "공감 +9 · 지성 +4 · 스승의 길",
                    "delta": {"empathy": 9, "intellect": 4},
                    "add_flags": ["teacher_path"],
                    "log": "자신이 겪었던 숱한 실패를 자산 삼아 후배들의 시행착오를 줄여주는 스승이 되었다.",
                },
                {
                    "id": "b14_craft_deep",
                    "label": "🏆 남들이 은퇴를 말할 나이에 오히려 필생의 역작에 매달린다",
                    "hint": "열정 +7 · 지성 +5 · 거장의 집념",
                    "delta": {"passion": 7, "intellect": 5},
                    "add_flags": ["masterwork_kept"],
                    "log": "세월의 무게를 핑계 대지 않고 생애 가장 깊이 있는 작업에 몰입했다.",
                },
                {
                    "id": "b14_star",
                    "label": "🌌 저녁마다 작은 망원경과 노트를 꺼내 삶과 별의 의미를 적는다",
                    "hint": "지성 +8 · 공감 +5 · 내면의 완성(별의 씨앗)",
                    "delta": {"intellect": 8, "empathy": 5},
                    "add_flags": ["star_seed"],
                    "log": "삶의 속도를 늦추고 별빛과 인간의 시간이 어떻게 이어지는지 조용히 사색했다.",
                },
            ],
        )

    # ── BEAT 15 (Age 56 · 장년기 ④: 세대 교체와 내면의 성적표) ──
    if beat == 15:
        return _make_node(
            "b15_generation",
            f"🌅 {age}세 — 쉰여섯, 뒷모습이 되어가는 나날",
            (
                f"젊은 시절의 패기는 줄어들고 머리카락에는 흰 서리가 내렸습니다. "
                f"어느 날, 자신의 젊은 날을 꼭 닮은 스무 살 남짓한 후배가 찾아와 도움을 요청합니다."
            ),
            7,
            [
                {
                    "id": "b15_pass_torch",
                    "label": "🤝 내 자리와 노하우를 기꺼이 물려주고 뒤에서 든든히 밀어준다",
                    "hint": "공감 +8 · 근성 +3 · 세대를 잇는 손길",
                    "delta": {"empathy": 8, "grit": 3},
                    "add_flags": ["teacher_path"],
                    "log": "기득권을 쥐려 하기보다 다음 세대에게 길을 열어주는 어른으로 자리 잡았다.",
                },
                {
                    "id": "b15_protect_own",
                    "label": "🛡️ 아직 내 할 일이 남아있다며 마지막 현역의 자리를 지킨다",
                    "hint": "열정 +6 · 자산 +5 · 끝까지 꺾이지 않는 현역",
                    "delta": {"passion": 6, "wealth": 5},
                    "log": "나이에 지지 않겠다는 오기로 쉰여섯에도 최전선 현장을 묵묵히 지켰다.",
                },
                {
                    "id": "b15_heal_body",
                    "label": "🌿 무리했던 몸을 추스르며 가까운 사람들과의 시간을 늘린다",
                    "hint": "근성 +9 · 공감 +4 · 평온한 장수 준비",
                    "delta": {"grit": 9, "empathy": 4},
                    "log": "고장 나던 몸을 돌보고 소중한 이들의 이름을 한 번 더 불러주는 시간을 택했다.",
                },
            ],
        )

    # ── BEAT 16 (Age 63 · 노년기 ①: 은퇴와 마주 선 노년의 첫 아침) ──
    if beat == 16:
        partner_line = f"{v['partner']}와(과) 마주 앉은 아침 식탁에 " if "has_partner" in flags else "창가로 드는 고요한 햇살 아래 "
        return _make_node(
            "b16_retire",
            f"🍁 {age}세 — 예순셋의 아침, 손에서 명함을 내려놓다",
            (
                f"{partner_line}오랫동안 붙잡고 있던 시대의 역할이 서서히 다음 세대로 넘어갑니다. "
                f"평생을 살아온 {v['career_label']}의 시간을 뒤로하고, 남은 황혼기를 어떻게 채울지 정할 때입니다."
            ),
            7,
            [
                {
                    "id": "b16_community",
                    "label": "🕊️ 작은 동네 도서관·무료 진료·골목 가게로 이웃 곁에 남는다",
                    "hint": "공감 +8 · 근성 +4 · 따뜻한 동네의 등불",
                    "delta": {"empathy": 8, "grit": 4},
                    "add_flags": ["protect_local"],
                    "log": "은퇴 후에도 거창하지 않지만 이웃에게 꼭 필요한 작은 자리를 열었다.",
                },
                {
                    "id": "b16_memoir",
                    "label": "📜 평생의 실패와 깨달음을 한 권의 기록과 작품으로 남긴다",
                    "hint": "지성 +7 · 열정 +5 · 시대를 남기는 기록",
                    "delta": {"intellect": 7, "passion": 5},
                    "add_flags": ["memoir_written"],
                    "log": "평생 겪은 시련과 기쁨을 가감 없이 한 권의 기록과 유작에 담아냈다.",
                },
                {
                    "id": "b16_journey",
                    "label": "🧭 오래전 가보려다 미뤄뒀던 먼 곳으로 늦은 여행을 떠난다",
                    "hint": "열정 +7 · 근성 +3 · 자유로운 황혼",
                    "delta": {"passion": 7, "grit": 3},
                    "add_flags": ["late_explorer"],
                    "log": "미뤄왔던 여행 가방을 싸 들고 아직 보지 못한 바다와 산을 향해 발걸음을 옮겼다.",
                },
            ],
        )

    # ── BEAT 17 (Age 70 · 노년기 ②: 태어난 곳으로의 회귀 — 떡밥 완벽 회수) ──
    if beat == 17:
        has_star = "star_seed" in flags and _safe_int(stats.get("intellect"), 0) >= 52 and _safe_int(stats.get("empathy"), 0) >= 48
        choices = [
            {
                "id": "b17_forgive",
                "label": f"💧 오래된 {v['origin_item']}을(를) 안고 지나온 나와 화해한다",
                "hint": "공감 +8 · 지성 +4 · 온전한 삶의 화해",
                "delta": {"empathy": 8, "intellect": 4},
                "add_flags": ["reconciled_self"],
                "log": f"칠십이 넘어 처음 출발했던 {v['origin_place']}의 기억을 끌어안고 젊은 날의 자신을 용서했다.",
            },
            {
                "id": "b17_smile",
                "label": "🏡 세월이 바꿔놓은 풍경 속에서 살아온 모든 날에 감사한다",
                "hint": "근성 +6 · 공감 +6 · 넉넉한 평온",
                "delta": {"grit": 6, "empathy": 6},
                "add_flags": ["grateful_elder"],
                "log": "아프고 모자랐던 날들까지 모두 지금의 나를 만든 선물이었다며 조용히 미소 지었다.",
            },
        ]
        if has_star:
            choices.append({
                "id": "b17_cosmos",
                "label": "🌌 밤하늘 별빛 속에서 시간과 세월을 건너는 깊은 깨달음을 얻는다",
                "hint": "지성 +8 · 공감 +8 · [히든 엔딩] 별을 건너다 개방",
                "delta": {"intellect": 8, "empathy": 8},
                "add_flags": ["time_transcended"],
                "log": "칠십의 밤하늘 아래서 시간은 흐르는 것이 아니라 마음에 겹겹이 쌓이는 빛임을 깨달았다.",
            })

        return _make_node(
            "b17_homecoming",
            f"🏡 {age}세 — 육십여 년 만에 다시 선 '{v['origin_place']}'",
            (
                f"칠순을 넘긴 {v['name']}의 발걸음이 자신도 모르게 처음 삶의 시작점이었던 **{v['origin_place']}** 터 앞에 멈춥니다. "
                f"많은 것이 변했지만 문득 스치는 바람 냄새만은 예순 해 전 그날 그대로입니다. "
                f"주머니 깊숙이 간직해 온 `{v['origin_item']}`이(가) 손끝에 닿습니다."
            ),
            8,
            choices,
        )

    # ── BEAT 18 (Age 78~85 · 노년기 ③: 인생의 마지막 페이지) ──
    last_partner_msg = (
        f"손을 잡아주는 **{v['partner']}**의 주름진 온기 속에서, "
        if "has_partner" in flags
        else "평생 걸어온 길 위의 수많은 얼굴들을 떠올리며, "
    )
    choices_18 = [
        {
            "id": "b18_peace",
            "label": "🌅 사랑했던 이들의 이름을 하나씩 떠올리며 고요히 눈을 감는다",
            "hint": "인생의 아름다운 마침표",
            "delta": {"empathy": 4, "grit": 2},
            "add_flags": ["peaceful_end"],
            "log": "지나온 인연과 세월에게 마지막 감사를 건넨 뒤 평온히 눈을 감았다.",
        },
        {
            "id": "b18_final_work",
            "label": "✍️ 마지막 힘까지 모아 세상에 남길 마지막 한 줄(작품)을 끝맺는다",
            "hint": "열정 +5 · 지성 +3 · 끝까지 빛난 혼신",
            "delta": {"passion": 5, "intellect": 3},
            "add_flags": ["final_work_done"],
            "log": "숨이 닿는 마지막 순간까지 자신이 사랑했던 일의 마침표를 직접 찍었다.",
        },
    ]
    if "time_transcended" in flags:
        choices_18.append({
            "id": "b18_star_walk",
            "label": "🌌 은하수가 비치는 창가에서 시간의 저편으로 걸어 나간다",
            "hint": "히든 엔딩 전용 마무리",
            "delta": {"intellect": 4, "empathy": 4},
            "add_flags": ["cosmos_finale"],
            "log": "별빛으로 가득 찬 새벽, 세월의 경계를 조용히 건너 영원한 이야기가 되었다.",
        })
    return _make_node(
        "b18_finale",
        f"📖 {age}세 — 인생이라는 책의 마지막 페이지",
        (
            f"길고도 짧았던 한 사람의 세월. {last_partner_msg}{v['name']}은(는) 창밖으로 비치는 따스한 노을을 바라봅니다. "
            f"후회도, 찬란한 기쁨도, 뼈아픈 실수도 모두 한 권의 책이 되어 이제 마지막 문장을 기다리고 있습니다."
        ),
        0,
        choices_18,
    )


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
    elif "cosmos_finale" in flags and "time_transcended" in flags and intel >= 60 and empathy >= 56:
        eid = "hidden_star"
    elif "old_promise_kept" in flags or (
        "comp_promised" in flags
        and life.get("partner_name") == life.get("companion_name")
        and "partner_strained" not in flags
        and "corrupted" not in flags
    ):
        eid = "old_promise"
    elif "redeemed" in flags:
        eid = "redeemed_spring"
    elif career == "shadow" and "redeemed" not in flags:
        eid = "masked_shadow"
    elif "corrupted" in flags and "redeemed" not in flags:
        eid = "broken_crown"
    elif "noodle_revival" in flags or (origin_id == "noodle_shop" and career == "artisan" and empathy >= 52):
        eid = "noodle_universe"
    elif (career == "guardian" or "whistleblower" in flags) and "honest_path" in flags and empathy >= 50:
        eid = "truth_keeper"
    elif (career == "scholar" and "healer_oath" in flags) or (origin_id == "mountain_clinic" and empathy >= 58 and career in ("scholar", "artisan")):
        eid = "healer_hands"
    elif career in ("artist", "scholar") and passion >= 52 and wealth <= 46 and ("pure_art" in flags or "final_work_done" in flags):
        eid = "unheard_genius"
    elif career in ("artist", "scholar", "artisan") and "masterwork_kept" in flags and max(intel, passion, grit) >= 68:
        eid = "master_craft"
    elif ("mentor_heir" in flags or "teacher_path" in flags) and empathy >= 50 and "empire_ambition" not in flags:
        eid = "teacher_bridge"
    elif ("protect_local" in flags or "philanthropy" in flags) and empathy >= 52 and "empire_ambition" not in flags:
        eid = "village_lantern"
    elif (career == "entrepreneur" and (wealth >= 60 or "empire_ambition" in flags)) or (wealth >= 76 and career != "wanderer"):
        eid = "empire_builder"
    elif (career == "wanderer" and passion >= 46) or "late_explorer" in flags:
        eid = "horizon_writer"
    else:
        eid = "quiet_miracle"

    emeta = ENDINGS[eid]
    v = _fmt_vars(life)

    empire_flavor = (
        f"수많은 직원들과 사랑하는 {v['partner']}의 축하 속에 가업을 따스하게 물려주며 진정한 부자로 기억되었습니다."
        if ("has_partner" in flags and empathy >= 45)
        else "높은 펜트하우스 창문 너머로 화려한 도시 야경을 내려다보았지만, 문득 어릴 적 소박한 온기가 그리워지곤 했습니다."
    )
    quiet_flavor = (
        f"마지막 순간까지 곁을 지킨 {v['partner']}와(과) 이웃들의 웃음소리 속에서, 아무런 후회 없는 백 년의 미소를 남겼습니다."
        if "has_partner" in flags
        else f"좋아하던 차 한 잔의 향기와 창밖의 사계절을 사랑하며, 조용하지만 누구보다 충만한 한 생애를 마쳤습니다."
    )

    epilogue = emeta["epilogue"].format(
        name=v["name"],
        age=v["age"],
        origin_place=v["origin_place"],
        origin_item=v["origin_item"],
        companion=v["companion"],
        mentor=v["mentor"],
        partner=v["partner"],
        career_label=v["career_label"],
        empire_flavor=empire_flavor,
        quiet_flavor=quiet_flavor,
    )

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
            "age": 6,
            "beat": 1,
            "quiet_in_stage": 0,
            "time_scale": scale_id,
            "last_tick_at": now_f,
            "started_at": datetime.datetime.now(core.KST).isoformat(),
            "stats": copy.deepcopy(orig["stats"]),
            "flags": [],
            "chronicle": [
                f"👶 0세 — {hometown}의 {orig['place']}에서 '{full_name}'(으)로 태어났다. ({orig['hook']})"
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
    u.setdefault("history", []).insert(0, {
        "life_uid": life.get("life_uid"),
        "name": life.get("name"),
        "origin_id": life.get("origin_id"),
        "career": life.get("career"),
        "career_label": career_meta["name"],
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
        _apply_stat_delta(stats, chosen.get("delta") or {})

        flag_set = set(life.get("flags") or [])
        for f in chosen.get("add_flags") or []:
            flag_set.add(str(f))
        for f in chosen.get("remove_flags") or []:
            flag_set.discard(str(f))
        life["flags"] = sorted(flag_set)

        if chosen.get("set_career"):
            life["career"] = str(chosen["set_career"])
        if chosen.get("set_partner"):
            life["partner_name"] = str(chosen["set_partner"])
        if chosen.get("clear_partner"):
            life["partner_name"] = None

        log_text = str(chosen.get("log") or chosen.get("label") or "").strip()
        life.setdefault("chronicle", []).append(f"• {cur_age}세 — {log_text}")
        if len(life["chronicle"]) > 80:
            del life["chronicle"][:-80]

        life["last_action_summary"] = f"{cur_age}세의 선택: {log_text}"
        life["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()

        # 조기 영웅적 희생 / 건강 고갈 체크 (Beat 12)
        if chosen.get("trigger_flame_if_low_grit") and _safe_int(stats.get("grit"), 0) <= 16:
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
