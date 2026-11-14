"""붕괴: 스타레일 (Honkai: Star Rail) 워프 · 유물 감정 · 도감 · 별빛/헤르타 상점 · 편대 시너지 코어 엔진

- 실시간 한국어 DB 연동: sr.yatta.moe/api/v2/kr + StarRailRes GitHub 한국어 인덱스 + 로컬 캐시(hsr_kr_cache.json) + 내장 폴백
- 정통 워프 & 유물 감정 메커니즘 (시각별 KST 실시간 로테이션 탑재):
  * 캐릭터 이벤트 워프 ①/② (90천장 · 74소프트 +6%/뽑 · 기본 0.6% · 50/50 & 확정 천장 · 두 픽업 간 천장 공유)
  * 광추 이벤트 워프 '빛의 자취' (80천장 · 66소프트 +7%/뽑 · 기본 0.8% · 75/25 & 확정 천장 · 전용 광추 더블 픽업 연동)
  * 침식된 터널 · 차원 장신구 유물 워프 (50천장 · 35소프트 +6%/뽑 · 기본 ★5 2.5% · 픽업 세트 80% · 6부위 주옵션/부옵션 감정)
  * 상시 '뭇별의 워프' (90천장 · 300회 달성 시 상시 5성 캐릭터 1명 직접 선택!)
- 성혼(E0~E6) & 광추 중첩(S1~S5) & 유물 강화(+15) 자동 누적 + 꺼지지 않는 별빛 / 불멸의 잔재 / 헤르타 채권 자동 정산
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
from typing import Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

import core

requests = core.requests

HSR_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hsr_kr_cache.json")
HSR_CACHE_TTL = 60 * 60 * 12  # 12시간마다 백그라운드 갱신

_HSR_DB_LOCK = threading.Lock()
_HSR_IMG_LOCK = threading.Lock()
_HSR_DETAIL_LOCK = threading.Lock()

HSR_CHARS: list[dict] = []
HSR_LIGHT_CONES: list[dict] = []
HSR_RELICS: list[dict] = []
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

# 5성 한정 캐릭터 -> 전용 5성 광추 매핑 (캐릭터 픽업에 맞춰 광추 픽업 자동 연동)
HSR_SIGNATURE_LCS = {
    "1503": "23065",  # 펄 -> 고독한 별을 위해
    "1513": "23064",  # 어벤츄린•웨이브 -> 오직 하나의 승리
    "1512": "23063",  # 로빈•서머레토 -> 내일로 향하는 멜로디
    "1509": "23062",  # 길가메시 -> 하늘의 사슬조차 끊어내리
    "1510": "23061",  # 히메코•노바 -> 언젠가 별들과 다시 만날 때
    "1508": "23060",  # 토오사카 린 -> 보석에 새긴 붉은 마술
    "1507": "23059",  # 천야•블레이드 -> 이 생명이 다할 때까지
    "1505": "23058",  # 에바네시아 -> 달빛이 서리는 밤에
    "1506": "23057",  # 은랑 LV.999 -> 우주를 해킹하는 법
    "1504": "23056",  # 애쉬베일 -> 거짓말의 종말
    "1502": "23054",  # 효광 -> 그녀가 보기로 결심했을 때
    "1501": "23053",  # 스파키 -> 현란한 파도타기 세상
    "1415": "23052",  # 키레네 -> 이 순간처럼 영원한 사랑
    "1414": "23051",  # 단항•등황 -> 어디든 갈 수 있어
    "1321": "23050",  # 달리아 -> 그녀의 불꽃을 잊지 말라
    "1413": "23049",  # 에버나이트 -> 긴 밤의 별빛에게
    "1412": "23048",  # 케리드라 -> 황금 피가 새긴 시대
    "1410": "23047",  # 히실렌스 -> 바다는 왜 노래하는가
    "1015": "23046",  # 아처 -> 이상이 불타는 지옥
    "1014": "23045",  # 세이버 -> 보답 없는 왕관
    "1408": "23044",  # 파이논 -> 이와 같이 타오르는 여명
    "1406": "23043",  # 사이퍼 -> 바람에 흩날리는 거짓말
    "1409": "23042",  # 히아킨 -> 무지개가 영원히 하늘에 머물길
    "1405": "23041",  # 아낙사 -> 생명은 태워야 하는 법
    "1407": "23040",  # 카스토리스 -> 이별이 더 아름답도록
    "1404": "23039",  # 마이데이 -> 앞길을 불태우는 피의 불꽃
    "1403": "23038",  # 트리비 -> 시간이 한 송이 꽃이라면
    "1401": "23037",  # 더 헤르타 -> 추궁할 수 없는 곳을 향해
    "1402": "23036",  # 아글라이아 -> 시간을 직조하는 황금
    "1313": "23034",  # 선데이 -> 대지로 돌아온 비행
    "1309": "23026",  # 로빈 -> 찬란하게 빛나는 밤
    "1310": "23025",  # 반디 -> 꿈은 어디로 돌아가야 하는가
    "1308": "23024",  # 아케론 -> 흘러가는 강가를 따라
    "1307": "23023",  # 블랙 스완 -> 시간의 기억에 대한 재구성
    "1306": "23021",  # 스파클 -> 속세에서의 유희
    "1305": "23020",  # Dr. 레이시오 -> 순수 사유의 세례
    "1303": "23019",  # 완•매 -> 거울 속 지난날의 나
    "1302": "23018",  # 아젠티 -> 눈에 담긴 순간
    "1217": "23017",  # 곽향 -> 섬뜩한 밤
    "1112": "23016",  # 토파즈&복순이 -> 고민, 그리고 행복
    "1212": "23014",  # 경류 -> 이 몸이 검이니
    "1213": "23015",  # 단항•음월 -> 태양보다 밝게 빛나는 것
    "1208": "23011",  # 부현 -> 그녀는 두 눈을 감았네
    "1005": "23006",  # 카프카 -> 필요한 건 기다림뿐
    "1205": "23009",  # 블레이드 -> 닿을 수 없는 저편
    "1203": "23008",  # 나찰 -> 관의 울림
    "1006": "23007",  # 은랑 -> 내리는 비
    "1204": "23010",  # 경원 -> 동트기 전
    "1102": "23001",  # 제레 -> 야경 속에서
    "1304": "23022",  # 어벤츄린 -> 운명은 언제나 불공평하다
    "1315": "23027",  # 부트힐 -> 두 번째 생명을 향해
    "1314": "23028",  # 제이드 -> 희망은 무가치한가
    "1221": "23029",  # 운리 -> 해 질 녘 시작되는 춤
    "1218": "23030",  # 초구 -> 무수한 봄날들
    "1220": "23031",  # 비소 -> 나는 사냥을 떠나리
    "1222": "23032",  # 영사 -> 오직 향만이 변함없이
    "1317": "23033",  # 라파 -> 인법첩•현란한 파마
    "1225": "23035",  # 망귀인 -> 먼 곳의 귀로
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

# 터널 유물 4부위 & 차원 장신구 2부위 감정 데이터
HSR_CAVERN_SLOTS = [
    {"code": "HEAD", "name": "머리", "emoji": "🪖", "main_stats": ["HP +705"]},
    {"code": "HAND", "name": "핸드", "emoji": "🧤", "main_stats": ["공격력 +352"]},
    {"code": "BODY", "name": "바디", "emoji": "🧥", "main_stats": ["치명타 확률 +32.4%", "치명타 피해 +64.8%", "공격력 +43.2%", "HP +43.2%", "치유량 보너스 +34.5%", "효과 명중 +43.2%"]},
    {"code": "FOOT", "name": "풋", "emoji": "🥾", "main_stats": ["속도 +25", "공격력 +43.2%", "HP +43.2%", "방어력 +54.0%"]},
]
HSR_PLANAR_SLOTS = [
    {"code": "NECK", "name": "차원 구체", "emoji": "🌐", "main_stats": ["물리 속성 피해 +38.8%", "화염 속성 피해 +38.8%", "얼음 속성 피해 +38.8%", "번개 속성 피해 +38.8%", "바람 속성 피해 +38.8%", "양자 속성 피해 +38.8%", "허수 속성 피해 +38.8%", "공격력 +43.2%", "HP +43.2%"]},
    {"code": "OBJECT", "name": "연결 매듭", "emoji": "🪢", "main_stats": ["에너지 회복효율 +19.4%", "격파 특수효과 +64.8%", "공격력 +43.2%", "HP +43.2%", "방어력 +54.0%"]},
]
HSR_RELIC_SUBSTATS = [
    "치명타 확률 +3.2%",
    "치명타 피해 +6.4%",
    "속도 +2.6",
    "공격력 +4.3%",
    "격파 특수효과 +6.4%",
    "효과 명중 +4.3%",
    "효과 저항 +4.3%",
    "HP +4.3%",
    "방어력 +5.4%",
]

# KST 시각 연동 2시간 간격 은하열차 로테이션 테마 (하루 12슬롯)
HSR_TIME_ROTATION_CHAR_PAIRS = [
    ("1503", "1501", "🪐 개척 최신 — 펄 & 스파키"),
    ("1513", "1512", "🎭 환락의 축복 — 어벤츄린•웨이브 & 로빈•서머레토"),
    ("1509", "1508", "⚔️ 성배의 영령 — 길가메시 & 토오사카 린"),
    ("1510", "1507", "🌠 신성 개척 — 히메코•노바 & 천야•블레이드"),
    ("1505", "1506", "🌌 성간 해커 — 에바네시아 & 은랑 LV.999"),
    ("1504", "1502", "🕵️ 탐정과 장군 — 애쉬베일 & 효광"),
    ("1415", "1414", "❄️ 영원의 기억 — 키레네 & 단항•등황"),
    ("1408", "1407", "☀️ 앰포리어스 황금의 후예 — 파이논 & 카스토리스"),
    ("1014", "1015", "👑 Fate/stay night 콜라보 — 세이버 & 아처"),
    ("1401", "1402", "📘 지니어스와 황금실 — 더 헤르타 & 아글라이아"),
    ("1308", "1310", "🔥 페나코니 꿈의 무대 — 아케론 & 반디"),
    ("1309", "1313", "🎵 질서와 화합의 남매 — 로빈 & 선데이"),
]

HSR_TIME_ROTATION_RELIC_PAIRS = [
    ("130", "326"),  # 빛나는 공훈의 마법 소녀 / 천 개의 별이 모인 도시
    ("129", "325"),  # 신응에 답하는 점술가 / 펑크로드 스테이지 Zero
    ("128", "324"),  # 그림자를 감춘 달빛 / 영원의 땅 앰포리어스
    ("127", "323"),  # 천지를 재창조한 구세주 / 즐거움에 취한 바다의 일각
    ("126", "322"),  # 거친 파도를 헤치는 선장 / 꿈을 엮는 요정의 낙원
    ("125", "321"),  # 해와 번개의 여전사 / 사색하는 거목의 정원
    ("124", "320"),  # 망국을 애도하는 시인 / 고요한 습골지
    ("123", "319"),  # 개선을 노래하는 영웅 / 바다에 잠긴 루샤카
    ("122", "318"),  # 지식의 바다에 빠진 학자 / 기묘한 나나 낙원
    ("121", "317"),  # 다시 길을 나서는 사제 / 도람 왕조의 주조소
    ("120", "316"),  # 바람과 구름을 가르는 용맹 / 모프소스의 무적 함대
    ("119", "315"),  # 곤충 재앙을 잠재우는 철기군 / 달리는 늑대의 도람 왕조
]

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
    "relic": {
        "name": "🏺 침식된 터널 · 차원 장신구 (유물 감정 워프)",
        "short_name": "유물 워프",
        "currency_name": "개척력 농축 에테르",
        "hard_pity": 50,
        "soft_start": 35,
        "base_5_pct": 2.5,
        "base_4_pct": 18.0,
        "color": (118, 232, 196),
        "desc": "시각별 픽업 ★5 터널 유물/차원 장신구 80% 집중 드랍 · 50천장 · 주옵션/부옵션 4줄 감정!",
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
}

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
    "time_rotation": {
        "label": "⏰ KST 시각 연동 2시간 자동 로테이션 (캐릭터·광추·유물 동시 회전)",
        "banner_name": "시각 연동 은하열차 워프",
        "char1": None,
        "char2": None,
        "char_4_ids": [],
        "lc_1": None,
        "lc_2": None,
        "relic_1": None,
        "relic_2": None,
    },
    "latest": {
        "label": "✨ 최신 개척 캐릭터 (펄 / 스파키)",
        "banner_name": "은하열차 최신 워프",
        "char1": "1503",
        "char2": "1501",
        "char_4_ids": ["1301", "1223", "1202"],
        "lc_1": "23065",
        "lc_2": "23053",
        "relic_1": "130",
        "relic_2": "326",
    },
    "elation_stage": {
        "label": "🎭 환락의 축복 스테이지 (어벤츄린•웨이브 / 로빈•서머레토)",
        "banner_name": "환락의 스포트라이트",
        "char1": "1513",
        "char2": "1512",
        "char_4_ids": ["1301", "1202", "1106"],
        "lc_1": "23064",
        "lc_2": "23063",
        "relic_1": "129",
        "relic_2": "325",
    },
    "fate_collab": {
        "label": "👑 Fate/stay night 콜라보 (세이버 / 아처 / 길가메시 / 토오사카 린)",
        "banner_name": "성배전쟁 스페셜 워프",
        "char1": "1014",
        "char2": "1509",
        "char_4_ids": ["1301", "1223", "1106"],
        "lc_1": "23045",
        "lc_2": "23062",
        "relic_1": "127",
        "relic_2": "324",
    },
    "amphoreus_dawn": {
        "label": "☀️ 앰포리어스 황금의 후예 (파이논 / 카스토리스)",
        "banner_name": "여명의 구세주 & 사신의 포옹",
        "char1": "1408",  # 파이논
        "char2": "1407",  # 카스토리스
        "char_4_ids": ["1301", "1202", "1106"],  # 갤러거, 정운, 페라
        "lc_1": "23044",  # 이와 같이 타오르는 여명
        "lc_2": "23040",  # 이별이 더 아름답도록
        "relic_1": "127",
        "relic_2": "320",
    },
    "amphoreus_memory": {
        "label": "❄️ 영원의 기억과 찬란한 지식 (키레네 / 더 헤르타)",
        "banner_name": "영원한 사랑의 시 & 지니어스의 서곡",
        "char1": "1415",  # 키레네
        "char2": "1401",  # 더 헤르타
        "char_4_ids": ["1223", "1013", "1009"],  # 맥택, 헤르타, 아스타
        "lc_1": "23052",  # 이 순간처럼 영원한 사랑
        "lc_2": "23037",  # 추궁할 수 없는 곳을 향해
        "relic_1": "122",
        "relic_2": "324",
    },
    "penacony_dream": {
        "label": "🌌 페나코니 꿈의 무대 (아케론 / 반디)",
        "banner_name": "공허의 칼날 & 불타는 반딧불",
        "char1": "1308",  # 아케론
        "char2": "1310",  # 반디
        "char_4_ids": ["1301", "1106", "1214"],  # 갤러거, 페라, 설의
        "lc_1": "23024",  # 흘러가는 강가를 따라
        "lc_2": "23025",  # 꿈은 어디로 돌아가야 하는가
        "relic_1": "119",
        "relic_2": "317",
    },
    "ipc_harmony": {
        "label": "🎵 은하 화합 슈퍼 서포트 (로빈 / 선데이)",
        "banner_name": "꿈의 노래 & 질서의 여명",
        "char1": "1309",  # 로빈
        "char2": "1313",  # 선데이
        "char_4_ids": ["1202", "1201", "1110"],  # 정운, 청작, 링스
        "lc_1": "23026",  # 찬란하게 빛나는 밤
        "lc_2": "23034",  # 대지로 돌아온 비행
        "relic_1": "121",
        "relic_2": "319",
    },
}

# 오프라인/네트워크 장애 대비 내장 폴백 데이터
HSR_EMBEDDED_FALLBACK_CHARS = [
    {"id": "1503", "name": "펄", "rank": 5, "path": "Memory", "element": "Imaginary", "release": 1776000000, "pool_type": "한정"},
    {"id": "1513", "name": "어벤츄린•웨이브", "rank": 5, "path": "Elation", "element": "Imaginary", "release": 1775500000, "pool_type": "한정"},
    {"id": "1512", "name": "로빈•서머레토", "rank": 5, "path": "Elation", "element": "Physical", "release": 1775000000, "pool_type": "한정"},
    {"id": "1509", "name": "길가메시", "rank": 5, "path": "Mage", "element": "Imaginary", "release": 1774500000, "pool_type": "콜라보 한정"},
    {"id": "1510", "name": "히메코•노바", "rank": 5, "path": "Memory", "element": "Fire", "release": 1774000000, "pool_type": "한정"},
    {"id": "1508", "name": "토오사카 린", "rank": 5, "path": "Elation", "element": "Fire", "release": 1773500000, "pool_type": "콜라보 한정"},
    {"id": "1507", "name": "천야•블레이드", "rank": 5, "path": "Elation", "element": "Wind", "release": 1773000000, "pool_type": "한정"},
    {"id": "1505", "name": "에바네시아", "rank": 5, "path": "Elation", "element": "Ice", "release": 1772500000, "pool_type": "한정"},
    {"id": "1506", "name": "은랑 LV.999", "rank": 5, "path": "Elation", "element": "Quantum", "release": 1772000000, "pool_type": "한정"},
    {"id": "1504", "name": "애쉬베일", "rank": 5, "path": "Rogue", "element": "Thunder", "release": 1771500000, "pool_type": "한정"},
    {"id": "1502", "name": "효광", "rank": 5, "path": "Elation", "element": "Physical", "release": 1771000000, "pool_type": "한정"},
    {"id": "1501", "name": "스파키", "rank": 5, "path": "Elation", "element": "Fire", "release": 1770500000, "pool_type": "한정"},
    {"id": "1415", "name": "키레네", "rank": 5, "path": "Memory", "element": "Ice", "release": 1762300000, "pool_type": "한정"},
    {"id": "1014", "name": "세이버", "rank": 5, "path": "Warrior", "element": "Wind", "release": 1752100000, "pool_type": "콜라보 한정"},
    {"id": "1015", "name": "아처", "rank": 5, "path": "Rogue", "element": "Quantum", "release": 1752100000, "pool_type": "콜라보 한정"},
    {"id": "1408", "name": "파이논", "rank": 5, "path": "Warrior", "element": "Physical", "release": 1751446800, "pool_type": "한정"},
    {"id": "1407", "name": "카스토리스", "rank": 5, "path": "Memory", "element": "Quantum", "release": 1744189200, "pool_type": "한정"},
    {"id": "1401", "name": "더 헤르타", "rank": 5, "path": "Mage", "element": "Ice", "release": 1736935200, "pool_type": "한정"},
    {"id": "1308", "name": "아케론", "rank": 5, "path": "Warlock", "element": "Thunder", "release": 1711533600, "pool_type": "한정"},
    {"id": "1310", "name": "반디", "rank": 5, "path": "Warrior", "element": "Fire", "release": 1718787600, "pool_type": "한정"},
    {"id": "1309", "name": "로빈", "rank": 5, "path": "Shaman", "element": "Physical", "release": 1715158800, "pool_type": "한정"},
    {"id": "1313", "name": "선데이", "rank": 5, "path": "Shaman", "element": "Imaginary", "release": 1733280000, "pool_type": "한정"},
    {"id": "1003", "name": "히메코", "rank": 5, "path": "Mage", "element": "Fire", "release": 1682460000, "pool_type": "상시"},
    {"id": "1004", "name": "웰트", "rank": 5, "path": "Warlock", "element": "Imaginary", "release": 1682460000, "pool_type": "상시"},
    {"id": "1101", "name": "브로냐", "rank": 5, "path": "Shaman", "element": "Wind", "release": 1682460000, "pool_type": "상시"},
    {"id": "1104", "name": "게파드", "rank": 5, "path": "Knight", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
    {"id": "1107", "name": "클라라", "rank": 5, "path": "Warrior", "element": "Physical", "release": 1682460000, "pool_type": "상시"},
    {"id": "1209", "name": "연경", "rank": 5, "path": "Rogue", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
    {"id": "1211", "name": "백로", "rank": 5, "path": "Priest", "element": "Thunder", "release": 1682460000, "pool_type": "상시"},
    {"id": "1301", "name": "갤러거", "rank": 4, "path": "Priest", "element": "Fire", "release": 1711533600, "pool_type": "상시"},
    {"id": "1223", "name": "맥택", "rank": 4, "path": "Rogue", "element": "Thunder", "release": 1725900000, "pool_type": "상시"},
    {"id": "1202", "name": "정운", "rank": 4, "path": "Shaman", "element": "Thunder", "release": 1682460000, "pool_type": "상시"},
    {"id": "1106", "name": "페라", "rank": 4, "path": "Warlock", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
    {"id": "1001", "name": "Mar. 7th (보존)", "rank": 4, "path": "Knight", "element": "Ice", "release": 1682460000, "pool_type": "상시"},
]

HSR_EMBEDDED_FALLBACK_LCS = [
    {"id": "23065", "name": "「아하」가 처음 울리는 순간", "rank": 5, "path": "Elation", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23064", "name": "파도에 내던진 한여름", "rank": 5, "path": "Elation", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23063", "name": "그대는 나아가 노래하리니", "rank": 5, "path": "Elation", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23062", "name": "보이는 것이 곧 나", "rank": 5, "path": "Rogue", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23061", "name": "고요히 빛나는 불티", "rank": 5, "path": "Rogue", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23060", "name": "별이 밤하늘을 밝힐 때", "rank": 5, "path": "Warrior", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23059", "name": "연옥을 불사른 새로운 몸", "rank": 5, "path": "Warrior", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23058", "name": "다음 꽃피는 계절의 만남", "rank": 5, "path": "Memory", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23057", "name": "갤럭시 시티에 오신 것을 환영합니다", "rank": 5, "path": "Mage", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23056", "name": "거짓말의 종막", "rank": 5, "path": "Warlock", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23054", "name": "그녀가 보기로 결심했을 때", "rank": 5, "path": "Shaman", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23053", "name": "눈부신 파키의 세상", "rank": 5, "path": "Elation", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23052", "name": "이 순간처럼 영원한 사랑", "rank": 5, "path": "Memory", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23051", "name": "끝없는 산과 강을 거치더라도", "rank": 5, "path": "Knight", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23044", "name": "이와 같이 타오르는 여명", "rank": 5, "path": "Warrior", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23040", "name": "이별이 더 아름답도록", "rank": 5, "path": "Memory", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23037", "name": "추궁할 수 없는 곳을 향해", "rank": 5, "path": "Mage", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23024", "name": "흘러가는 강가를 따라", "rank": 5, "path": "Warlock", "warp_source": "limited", "pool_type": "광추한정"},
    {"id": "23000", "name": "은하철도의 밤", "rank": 5, "path": "Mage", "warp_source": "standard", "pool_type": "상시"},
    {"id": "23003", "name": "아직 전투는 끝나지 않았다", "rank": 5, "path": "Shaman", "warp_source": "standard", "pool_type": "상시"},
    {"id": "24000", "name": "어떤 에이언즈의 몰락", "rank": 5, "path": "Warrior", "warp_source": "herta", "pool_type": "헤르타 상점"},
    {"id": "21018", "name": "댄스! 댄스! 댄스!", "rank": 4, "path": "Shaman", "warp_source": "standard", "pool_type": "상시"},
    {"id": "21015", "name": "땀방울처럼 빛나는 결심", "rank": 4, "path": "Warlock", "warp_source": "standard", "pool_type": "상시"},
    {"id": "20000", "name": "화살촉", "rank": 3, "path": "Rogue", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20001", "name": "풍작", "rank": 3, "path": "Priest", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20002", "name": "천경", "rank": 3, "path": "Warrior", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20003", "name": "앰버", "rank": 3, "path": "Knight", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20004", "name": "그윽", "rank": 3, "path": "Warlock", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20005", "name": "합창", "rank": 3, "path": "Shaman", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20006", "name": "아카이브", "rank": 3, "path": "Mage", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20012", "name": "맞물린 톱니", "rank": 3, "path": "Shaman", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20021", "name": "불타는 그림자", "rank": 3, "path": "Memory", "warp_source": "standard", "pool_type": "상시(3성)"},
    {"id": "20023", "name": "비웃음", "rank": 3, "path": "Elation", "warp_source": "standard", "pool_type": "상시(3성)"},
]

# 최신 터널 유물(125~134) 및 차원 장신구(320~330) 한국어 공식 세트 효과
HSR_RELIC_SET_BONUSES_KR: dict[str, tuple[str, str]] = {
    "134": ("치명타 피해 16% 증가", "장착한 캐릭터가 일반 공격으로 가하는 피해가 36% 증가한다. 장착한 캐릭터가 일반 공격 발동 시 장착한 캐릭터의 공격력이 20% 증가한다, 지속 시간: 2턴"),
    "133": ("속도 6% 증가", "장착한 캐릭터가 다른 단일 아군에게 전투 스킬 또는 필살기 발동 시, 스킬 목표의 환락도가 16% 증가한다(3턴), [훌륭한 솜씨에는 보상을] 10pt 이상 시 모든 아군 치명타 피해 12% 증가"),
    "132": ("HP 최대치 12% 증가", "장착한 캐릭터가 방어력 감소 상태의 적에게 가하는 치명타 피해가 28% 증가하며, 방어력 감소 부여 시 모든 아군이 가하는 피해가 15% 증가한다(2턴)"),
    "131": ("공격력 12% 증가", "장착한 캐릭터가 전투 진입 시/전투 스킬 발동 시 전투 스킬과 필살기가 가하는 피해가 18% 증가한다(최대 3스택)"),
    "130": ("속도 6% 증가", "전투 진입 전 장착한 캐릭터의 속도가 120/160 이상일 시 치명타 확률이 10%/18% 증가하며, 첫 환락 스킬 발동 시 모든 아군의 환락도가 10% 증가한다"),
    "129": ("치명타 피해 16% 증가", "장착한 캐릭터와 기억 정령이 가하는 환락 피해가 목표의 방어력을 10% 무시하고, 웃음 포인트 누적에 따라 추가로 최대 10% 방어력을 무시한다"),
    "128": ("제공하는 실드량 10% 증가", "장착한 캐릭터가 제공하는 실드량이 12% 증가하고, 아군이 장착한 캐릭터가 제공한 실드 보유 시 치명타 피해가 15% 증가한다"),
    "127": ("치명타 확률 8% 증가", "일반 공격 또는 전투 스킬 발동 후 기억 정령이 필드에 있으면 장착 캐릭터와 기억 정령의 HP 최대치가 24% 증가하고 모든 아군이 가하는 피해가 15% 증가한다"),
    "126": ("치명타 피해 16% 증가", "장착한 캐릭터가 다른 아군의 스킬 목표가 되면 [조력]을 획득하고, 필살기 발동 시 2스택을 소모해 공격력을 48% 증가시킨다(1턴)"),
    "125": ("속도 6% 증가", "장착한 캐릭터와 기억 정령이 아군에게 치유 제공 시 [단비]를 획득해 속도가 6% 증가하고 모든 아군의 치명타 피해가 15% 증가한다(2턴)"),
    "330": ("장착한 캐릭터의 속도가 6% 증가하고, 속도가 145 이상일 시 전투 진입 후 모든 아군의 격파 특수효과가 18% 증가한다", ""),
    "329": ("장착한 캐릭터의 속도가 6% 증가한다. 장착한 캐릭터의 환락도가 40% 이상일 경우 전투 진입 시 즉시 행동 게이지가 40% 증가한다", ""),
    "328": ("전투 진입 시 장착한 캐릭터의 에너지 최대치가 200pt 이상일 경우 초과한 에너지 1pt당 가하는 피해가 0.2% 증가한다(최대 32%)", ""),
    "327": ("장착한 캐릭터의 치명타 확률이 8% 증가하며, 개척 동행 동료와 함께 편성 시 치명타 피해가 32% 증가한다", ""),
    "326": ("장착한 캐릭터가 추가 공격 발동 시 공격력이 24% 증가하며(2턴), 적 처치 시 모든 아군의 치명타 피해가 12% 증가한다", ""),
    "325": ("장착한 캐릭터의 환락도가 8% 증가하며, 전투 중 환락도가 40%/80% 도달 시 치명타 피해가 20%/32% 증가한다", ""),
    "324": ("장착한 캐릭터의 치명타 피해가 16% 증가하며, 같은 턴에 전투 스킬 포인트를 3pt 이상 소모 시 추가로 치명타 피해가 32% 증가한다(3턴)", ""),
    "323": ("장착한 캐릭터의 치명타 확률이 8% 증가하며, 기억 정령이 필드에 있을 시 모든 아군의 속도가 8% 증가한다", ""),
    "322": ("장착한 캐릭터의 공격력이 12% 증가하며, 공격력이 2400/3600 이상일 시 가하는 지속 피해가 추가로 12%/24% 증가한다", ""),
    "321": ("파티 내 현재 필드에 있는 아군 수가 4명이 아닐 경우 1명 많을/적을 때마다 장착 캐릭터와 기억 정령이 가하는 피해가 9%/12% 증가한다", ""),
    "320": ("장착한 캐릭터의 속도가 6% 증가하며, 속도가 135/180 이상일 경우 장착 캐릭터와 기억 정령의 치유량이 12%/20% 증가한다", ""),
}

HSR_EMBEDDED_FALLBACK_RELICS = [
    {"id": "134", "name": "금단의 열매를 삼킨 이단", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71065", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["134"][0], "bonus_4p": HSR_RELIC_SET_BONUSES_KR["134"][1]},
    {"id": "133", "name": "꿈같은 유희 속 별을 밝히는 연극인", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71064", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["133"][0], "bonus_4p": HSR_RELIC_SET_BONUSES_KR["133"][1]},
    {"id": "130", "name": "천명에 응해 먼 길을 떠난 점술가", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71055", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["130"][0], "bonus_4p": HSR_RELIC_SET_BONUSES_KR["130"][1]},
    {"id": "129", "name": "빛나는 공훈의 마법 소녀", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71054", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["129"][0], "bonus_4p": HSR_RELIC_SET_BONUSES_KR["129"][1]},
    {"id": "128", "name": "별빛에 숨은 은둔자", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71053", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["128"][0], "bonus_4p": HSR_RELIC_SET_BONUSES_KR["128"][1]},
    {"id": "127", "name": "천지를 재창조한 구세주", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71052", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["127"][0], "bonus_4p": HSR_RELIC_SET_BONUSES_KR["127"][1]},
    {"id": "330", "name": "아공간 이상 사물 수용소", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": True, "icon": "71063", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["330"][0], "bonus_4p": ""},
    {"id": "329", "name": "신의 순간의 환락", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": True, "icon": "71062", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["329"][0], "bonus_4p": ""},
    {"id": "326", "name": "천 개의 별이 모인 도시", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": True, "icon": "71057", "bonus_2p": HSR_RELIC_SET_BONUSES_KR["326"][0], "bonus_4p": ""},
    {"id": "102", "name": "들이삭과 동행하는 거너", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": False, "icon": "71001", "bonus_2p": "공격력 12% 증가", "bonus_4p": "장착한 캐릭터의 속도가 6% 증가하고, 일반 공격으로 가하는 피해가 10% 증가한다"},
    {"id": "301", "name": "우주 봉인 정거장", "rank": 5, "level_list": [2, 3, 4, 5], "is_planar": True, "icon": "71012", "bonus_2p": "장착한 캐릭터의 공격력이 12% 증가하며, 속도가 120 이상일 경우 공격력이 추가로 12% 증가한다", "bonus_4p": ""},
]


def _clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).replace("\xa0", " ").replace("\\n", "\n")
    s = re.sub(r"<color=[^>]+>|</color>|</?unbreak>|</?i>|</?b>|<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _format_hsr_char_name(cid: str, raw_name: str, path_code: str) -> str:
    name = _clean_text(raw_name).replace("\n", " ").strip()
    if cid == "1001":
        return "Mar. 7th (보존)"
    if cid == "1224":
        return "Mar. 7th (수렵)"
    if cid.isdigit() and int(cid) >= 8000:
        path_kr = HSR_PATH_MAP.get(path_code, {}).get("name", path_code)
        return f"개척자 ({path_kr})"
    return name or f"캐릭터 {cid}"


def _should_exclude_hsr_char(cid: str, raw: dict, now_ts: float) -> bool:
    if not cid.isdigit():
        return True
    cid_i = int(cid)
    # 남개척자(8001, 8003, 8005, 8007, 8009)는 포함하고 여개척자(짝수 ID)만 중복 제외하여 운명의 길별 개척자 5종을 모두 반영
    if cid_i >= 8000 and (cid_i % 2 == 0):
        return True
    if raw.get("beta"):
        return True
    return False


def _parse_hsr_items(
    y_avatars: dict | None,
    y_lcs: dict | None,
    sr_avatars: dict | None = None,
    sr_lcs: dict | None = None,
    y_relics: dict | None = None,
    sr_relics: dict | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    now_ts = time.time()
    chars: list[dict] = []
    lcs: list[dict] = []
    relics: list[dict] = []

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

        if cid_s.isdigit() and int(cid_s) >= 8000:
            pool_type = "주인공(기본)"
            warpable = False
        elif rank == 5:
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
            pool_type = "상시(3성)"
            warpable = True

        lcs.append({
            "id": lid_s,
            "kind": "lc",
            "item_key": f"lc:{lid_s}",
            "name": name,
            "rank": rank,
            "rarity_label": "★" * rank,
            "path": path_code,
            "path_name": path_info["name"],
            "path_emoji": path_info["emoji"],
            "icon": str(raw.get("icon") or lid_s),
            "warp_source": warp_source,
            "pool_type": pool_type,
            "warpable": warpable,
        })

    # 유물/차원 장신구 세트 파싱 (공식 DB 기준 levelList [2, 3, 4, 5], 최고 등급 ★5, 터널/장신구 워프 시 5★/4★/3★ 드랍)
    rel_ids = set()
    if isinstance(y_relics, dict):
        rel_ids.update(str(k) for k in y_relics.keys())
    if isinstance(sr_relics, dict):
        rel_ids.update(str(k) for k in sr_relics.keys())

    for rid_s in rel_ids:
        if not rid_s.isdigit():
            continue
        yr = (y_relics or {}).get(rid_s) or {}
        sr = (sr_relics or {}).get(rid_s) or {}
        if yr.get("beta"):
            continue
        name = _clean_text(yr.get("name") or sr.get("name") or f"유물 {rid_s}")
        is_planar = bool(yr.get("isPlanarSuit")) if "isPlanarSuit" in yr else (int(rid_s) >= 300)
        desc_list = sr.get("desc") if isinstance(sr.get("desc"), list) else []
        kr_bonus = HSR_RELIC_SET_BONUSES_KR.get(rid_s)
        if kr_bonus:
            b2, b4 = kr_bonus
        else:
            b2 = _clean_text(desc_list[0]) if len(desc_list) >= 1 else ("차원 장신구 2세트 효과 발동" if is_planar else "터널 유물 2세트 효과 발동")
            b4 = _clean_text(desc_list[1]) if len(desc_list) >= 2 else ("" if is_planar else "터널 유물 4세트 효과 발동")
        icon_code = str(yr.get("icon") or rid_s)
        suit_label = "차원 장신구" if is_planar else "터널 유물"
        suit_emoji = "🌐" if is_planar else "🏺"
        lv_list = yr.get("levelList") if isinstance(yr.get("levelList"), list) and yr.get("levelList") else [2, 3, 4, 5]
        max_rk = max(int(x) for x in lv_list if isinstance(x, (int, float))) if lv_list else 5

        relics.append({
            "id": rid_s,
            "kind": "relic",
            "item_key": f"relic:{rid_s}",
            "name": name,
            "rank": max_rk,
            "level_list": lv_list,
            "rarity_label": "★" * max_rk,
            "is_planar": is_planar,
            "path": "Memory" if is_planar else "Warrior",
            "path_name": suit_label,
            "path_emoji": suit_emoji,
            "icon": icon_code,
            "bonus_2p": b2,
            "bonus_4p": b4,
            "pool_type": suit_label,
            "warpable": True,
        })

    chars.sort(key=lambda x: (-x["rank"], -x["release"], -int(x["id"]) if x["id"].isdigit() else 0))
    lcs.sort(key=lambda x: (-x["rank"], 0 if x.get("warp_source") == "limited" else 1, -int(x["id"]) if x["id"].isdigit() else 0))
    relics.sort(key=lambda x: (-x["rank"], 1 if x.get("is_planar") else 0, -int(x["id"]) if x["id"].isdigit() else 0))
    return chars, lcs, relics


def _set_db_state(chars: list[dict], lcs: list[dict], fetched_at: float, relics: list[dict] | None = None):
    global HSR_CHARS, HSR_LIGHT_CONES, HSR_RELICS, HSR_ALL_ITEMS, _HSR_LAST_FETCH
    chars = [c for c in chars if int(c.get("rank", 0)) in (4, 5)]
    lcs = [l for l in lcs if int(l.get("rank", 0)) in (3, 4, 5)]
    HSR_CHARS = chars
    HSR_LIGHT_CONES = lcs
    if relics is not None:
        cleaned_relics = []
        for r in relics:
            rid_s = str(r.get("id", ""))
            lv_list = r.get("level_list") or [2, 3, 4, 5]
            rk = max(int(x) for x in lv_list if isinstance(x, (int, float))) if lv_list else 5
            r["rank"] = rk
            r["level_list"] = lv_list
            r["rarity_label"] = "★" * rk
            if rid_s in HSR_RELIC_SET_BONUSES_KR:
                r["bonus_2p"], r["bonus_4p"] = HSR_RELIC_SET_BONUSES_KR[rid_s]
            cleaned_relics.append(r)
        cleaned_relics.sort(key=lambda x: (-x["rank"], 1 if x.get("is_planar") else 0, -int(x["id"]) if str(x.get("id", "")).isdigit() else 0))
        HSR_RELICS = cleaned_relics
    elif not HSR_RELICS:
        _, _, HSR_RELICS = _normalize_fallback()
    merged: dict[str, dict] = {}
    for c in chars:
        merged[c["item_key"]] = c
    for l in lcs:
        merged[l["item_key"]] = l
    for r in HSR_RELICS:
        merged[r["item_key"]] = r
    HSR_ALL_ITEMS = merged
    _HSR_LAST_FETCH = fetched_at


def _normalize_fallback() -> tuple[list[dict], list[dict], list[dict]]:
    chars = []
    for c in HSR_EMBEDDED_FALLBACK_CHARS:
        if int(c.get("rank", 0)) not in (4, 5):
            continue
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
        if int(l.get("rank", 0)) not in (3, 4, 5):
            continue
        pi = HSR_PATH_MAP.get(l["path"], HSR_PATH_MAP["Warrior"])
        lcs.append({
            **l,
            "kind": "lc",
            "item_key": f"lc:{l['id']}",
            "rarity_label": "★" * int(l["rank"]),
            "path_name": pi["name"],
            "path_emoji": pi["emoji"],
            "icon": l["id"],
            "warpable": (l["warp_source"] in ("standard", "limited")),
        })
    relics = []
    for r in HSR_EMBEDDED_FALLBACK_RELICS:
        is_pl = bool(r.get("is_planar"))
        suit_label = "차원 장신구" if is_pl else "터널 유물"
        rk = int(r.get("rank", 5))
        relics.append({
            **r,
            "kind": "relic",
            "item_key": f"relic:{r['id']}",
            "rank": rk,
            "level_list": r.get("level_list", [2, 3, 4, 5]),
            "rarity_label": "★" * rk,
            "path": "Memory" if is_pl else "Warrior",
            "path_name": suit_label,
            "path_emoji": "🌐" if is_pl else "🏺",
            "pool_type": suit_label,
            "warpable": True,
        })
    return chars, lcs, relics


def hydrate_hsr_kr_cache_from_disk() -> bool:
    """디스크의 스타레일 한국어 DB 캐시가 있으면 즉시 메모리에 적재합니다."""
    if not os.path.exists(HSR_CACHE_FILE):
        return False
    try:
        with open(HSR_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        chars = payload.get("chars") or []
        lcs = payload.get("light_cones") or []
        relics = payload.get("relics") or []
        fetched_at = float(payload.get("fetched_at") or 0.0)
        if chars and lcs:
            _set_db_state(chars, lcs, fetched_at, relics if relics else None)
            return True
    except Exception:
        pass
    return False


def load_hsr_kr_db(force_refresh: bool = False) -> tuple[list[dict], list[dict]]:
    """붕괴: 스타레일 한국어 DB를 실시간(sr.yatta.moe & StarRailRes)에서 동기화하고 캐시합니다."""
    with _HSR_DB_LOCK:
        now = time.time()
        if not force_refresh and HSR_CHARS and HSR_LIGHT_CONES and HSR_RELICS and (now - _HSR_LAST_FETCH < HSR_CACHE_TTL):
            return HSR_CHARS, HSR_LIGHT_CONES

        if not force_refresh and not HSR_CHARS and hydrate_hsr_kr_cache_from_disk():
            if HSR_RELICS and (now - _HSR_LAST_FETCH < HSR_CACHE_TTL):
                return HSR_CHARS, HSR_LIGHT_CONES

        y_av = y_lc = y_rel = sr_av = sr_lc = sr_rel = None
        try:
            r1 = requests.get("https://sr.yatta.moe/api/v2/kr/avatar", timeout=15)
            r2 = requests.get("https://sr.yatta.moe/api/v2/kr/equipment", timeout=15)
            r3 = requests.get("https://sr.yatta.moe/api/v2/kr/relic", timeout=15)
            if r1.status_code == 200 and r2.status_code == 200:
                y_av = (r1.json().get("data") or {}).get("items") or {}
                y_lc = (r2.json().get("data") or {}).get("items") or {}
            if r3.status_code == 200:
                y_rel = (r3.json().get("data") or {}).get("items") or {}
        except Exception as e:
            print(f"⚠️ [스타레일 yatta 동기화 경고] {e}", flush=True)

        try:
            r_sr_rel = requests.get("https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_min/kr/relic_sets.json", timeout=12)
            if r_sr_rel.status_code == 200:
                sr_rel = r_sr_rel.json()
        except Exception:
            pass

        if not (y_av and y_lc):
            try:
                r3_av = requests.get("https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_min/kr/characters.json", timeout=15)
                r4_lc = requests.get("https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_min/kr/light_cones.json", timeout=15)
                if r3_av.status_code == 200 and r4_lc.status_code == 200:
                    sr_av = r3_av.json()
                    sr_lc = r4_lc.json()
            except Exception as e:
                print(f"⚠️ [스타레일 StarRailRes 동기화 경고] {e}", flush=True)

        if (y_av and y_lc) or (sr_av and sr_lc):
            chars, lcs, relics = _parse_hsr_items(y_av, y_lc, sr_av, sr_lc, y_rel, sr_rel)
            if not relics:
                _, _, relics = _normalize_fallback()
            if chars and lcs:
                _set_db_state(chars, lcs, now, relics)
                try:
                    tmp_f = f"{HSR_CACHE_FILE}.tmp"
                    with open(tmp_f, "w", encoding="utf-8") as f:
                        json.dump({"fetched_at": now, "chars": chars, "light_cones": lcs, "relics": relics}, f, ensure_ascii=False)
                    os.replace(tmp_f, HSR_CACHE_FILE)
                except Exception:
                    pass
                return HSR_CHARS, HSR_LIGHT_CONES

        if HSR_CHARS and HSR_LIGHT_CONES:
            return HSR_CHARS, HSR_LIGHT_CONES

        fb_c, fb_l, fb_r = _normalize_fallback()
        _set_db_state(fb_c, fb_l, 0.0, fb_r)
        return HSR_CHARS, HSR_LIGHT_CONES


def fetch_hsr_detail_kr(item_id: str, kind: str = "char") -> dict:
    """캐릭터/광추/유물 상세 정보(소속·소개 대사·한국어 성우·세트 효과)를 지연 로드 후 캐시합니다."""
    cache_key = f"{kind}:{item_id}"
    with _HSR_DETAIL_LOCK:
        if cache_key in _HSR_DETAIL_CACHE:
            _HSR_DETAIL_CACHE.move_to_end(cache_key)
            return _HSR_DETAIL_CACHE[cache_key]

    if kind == "relic":
        rel_obj = HSR_ALL_ITEMS.get(f"relic:{item_id}") or {}
        b2 = rel_obj.get("bonus_2p") or ""
        b4 = rel_obj.get("bonus_detail") or rel_obj.get("bonus_4p") or ""
        desc = f"2세트: {b2}" + (f" / 4세트: {b4}" if b4 else "")
        detail_info = {
            "description": desc,
            "skill_name": rel_obj.get("path_name", "유물 세트"),
            "bonus_2p": b2,
            "bonus_4p": b4,
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
    iid = str(item.get("id") or "")
    icon = str(item.get("icon") or iid)
    kind = item.get("kind", "char")
    if not iid and not icon:
        return []
    if kind == "char":
        if splash:
            return [
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/image/character_preview/{iid}.png",
                f"https://sr.yatta.moe/hsr/assets/UI/avatar/large/{icon}.png",
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/character/{iid}.png",
            ]
        return [
            f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/character/{iid}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/avatar/medium/{icon}.png",
        ]
    elif kind == "relic":
        return [
            f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/relic/{iid}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/relic/{icon}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/item/{icon}.png",
        ]
    else:
        if splash:
            return [
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/image/light_cone_preview/{iid}.png",
                f"https://sr.yatta.moe/hsr/assets/UI/equipment/large/{icon}.png",
                f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/light_cone/{iid}.png",
            ]
        return [
            f"https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/icon/light_cone/{iid}.png",
            f"https://sr.yatta.moe/hsr/assets/UI/equipment/medium/{icon}.png",
        ]


def get_hsr_primary_image_url(item: dict, splash: bool = True) -> str:
    urls = get_hsr_item_urls(item, splash=splash)
    return urls[0] if urls else ""


def _compress_hsr_if_needed(raw_bytes: bytes, base_name: str, is_splash: bool) -> tuple[bytes, str]:
    if Image is None or not is_splash or len(raw_bytes) <= 450 * 1024:
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
    cache_key = f"{'sp' if splash else 'ic'}:{item.get('kind')}:{item.get('id')}"
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
    cache_key = f"{item.get('kind')}:{item.get('id')}"
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
# 은하열차 코스믹 보라-골드-홀로그램 5x2 10연 워프 합성 이미지
# ==========================================
def build_hsr_10pull_grid_bytes(drawn: list[dict], banner_key: str = "char1", header_tag: str = "") -> io.BytesIO:
    """은하열차 워프 결과(최대 10종)를 코스믹 보라-골드 홀로그램 테마 5x2 카드로 렌더링합니다."""
    if Image is None or ImageDraw is None:
        return io.BytesIO()
    if not drawn:
        drawn = [{"name": "워프 데이터 없음", "rank": 3, "kind": "lc", "id": ""}]

    cols = 5 if len(drawn) > 1 else 1
    rows = 2 if len(drawn) > 5 else 1
    card_w, card_h = (194, 240) if cols == 5 else (320, 380)
    pad_x, pad_y = 14, 14
    margin_x, top_h, bot_h = 24, 52, 24
    width = margin_x * 2 + cols * card_w + (cols - 1) * pad_x
    height = top_h + rows * card_h + (rows - 1) * pad_y + bot_h

    # 코스믹 성간 우주 배경 (#0D081C -> #1D1138)
    canvas = Image.new("RGBA", (width, height), (14, 9, 30, 255))
    bg_draw = ImageDraw.Draw(canvas)
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(13 + 17 * t)
        g = int(8 + 11 * t)
        b = int(30 + 30 * t)
        bg_draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # 성간 별빛 입자
    srng = random.Random(42 + len(drawn))
    for _ in range(95):
        sx = srng.randint(8, width - 8)
        sy = srng.randint(8, height - 8)
        sb = srng.randint(150, 255)
        bg_draw.point((sx, sy), fill=(sb, int(sb * 0.92), 255, 190))

    # 은하열차 홀로그램 상단/하단 골드 라인
    bg_draw.rectangle([0, 0, width, 4], fill=(248, 200, 92, 255))
    bg_draw.rectangle([0, height - 3, width, height], fill=(166, 108, 255, 210))

    b_cfg = HSR_BANNER_CONFIGS.get(banner_key, HSR_BANNER_CONFIGS["char1"])
    f_hdr = core._get_grid_font(18, bold=True)
    f_sub = core._get_grid_font(13, bold=False)
    f_name = core._get_grid_font(13 if cols == 5 else 18, bold=True)
    f_badge = core._get_grid_font(11 if cols == 5 else 14, bold=True)

    title_txt = core._sanitize_grid_text(f"★ 은하열차 워프 결과 — {b_cfg['short_name']}")
    bg_draw.text((margin_x, 14), title_txt, font=f_hdr, fill=(255, 224, 146, 255))
    if header_tag:
        ht = core._sanitize_grid_text(header_tag)
        tw = bg_draw.textlength(ht, font=f_sub)
        bg_draw.text((width - margin_x - tw, 18), ht, font=f_sub, fill=(208, 186, 255, 235))

    # 썸네일 병렬 다운로드
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
            card_top = (66, 44, 14)
            card_bot = (34, 19, 44)
            border_c = (255, 206, 86, 255)
            accent_c = (255, 118, 178, 255)
            stars_txt = "★★★★★"
            star_c = (255, 226, 112, 255)
        elif rank == 4:
            card_top = (44, 24, 82)
            card_bot = (24, 15, 48)
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

        if rank >= 4:
            glow_w = card_w - 20
            cd.ellipse([10, 8, 10 + glow_w, 8 + glow_w], fill=elem_rgb + (36,))

        tb = thumb_map.get(idx)
        img_area_h = card_h - (54 if cols == 5 else 72)
        if tb:
            try:
                art = Image.open(io.BytesIO(tb)).convert("RGBA")
                pad_art = 8 if kind in ("lc", "relic") else 4
                max_aw = card_w - pad_art * 2
                max_ah = img_area_h - 12
                art.thumbnail((max_aw, max_ah), Image.Resampling.LANCZOS)
                ax = (card_w - art.width) // 2
                ay = (img_area_h - art.height) // 2 + 4
                card_im.alpha_composite(art, (ax, ay))
            except Exception:
                pass

        bar_y0 = img_area_h
        cd.rectangle([0, bar_y0, card_w, card_h], fill=(12, 9, 26, 232))
        cd.line([(0, bar_y0), (card_w, bar_y0)], fill=border_c, width=2)

        if item.get("is_new"):
            cd.rounded_rectangle([7, 7, 47, 25], radius=4, fill=(255, 198, 62, 245))
            cd.text((13, 9), "NEW", font=f_badge, fill=(22, 16, 12, 255))
        elif kind == "char" and "new_eidolon" in item:
            elbl = f"E{item['new_eidolon']}"
            cd.rounded_rectangle([7, 7, 39, 25], radius=4, fill=(138, 72, 235, 235))
            cd.text((13, 9), elbl, font=f_badge, fill=(255, 245, 255, 255))
        elif kind == "relic" and "new_level" in item:
            rlbl = f"+{item['new_level']}"
            cd.rounded_rectangle([7, 7, 45, 25], radius=4, fill=(38, 188, 152, 235))
            cd.text((11, 9), rlbl, font=f_badge, fill=(245, 255, 252, 255))
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
        cd.text((8, bar_y0 + 7), disp_name, font=f_name, fill=(248, 244, 255, 255))

        path_kr = item.get("path_name", "")
        if kind == "char":
            meta_txt = f"{stars_txt} {item.get('element_name', '')}·{path_kr}"
        elif kind == "relic":
            meta_txt = f"{stars_txt} {item.get('slot_name', path_kr)} · {item.get('main_stat', '')}"
        else:
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
# 유저 계정 데이터 구조 & 워프 확률 엔진
# ==========================================
def ensure_hsr_user(data: dict, guild_id: int, user_id: int) -> dict:
    users_root = data.setdefault("hsr_users", {})
    g_map = users_root.setdefault(str(guild_id or 0), {})
    u_data = g_map.setdefault(str(user_id), {})
    u_data.setdefault("items", {})
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
    # 유물 감정 워프 스택
    u_data.setdefault("pity_relic", 0)
    u_data.setdefault("guaranteed_relic", False)
    u_data.setdefault("pity_4_relic", 0)
    # 상시 워프 스택 & 300뽑 5성 선택권
    u_data.setdefault("pity_standard", 0)
    u_data.setdefault("pity_4_standard", 0)
    u_data.setdefault("standard_total_pulls", 0)
    u_data.setdefault("standard_300_claimed", False)
    # 고유 재화
    u_data.setdefault("starlight", 0)        # 꺼지지 않는 별빛
    u_data.setdefault("embers", 0)           # 불멸의 잔재
    u_data.setdefault("herta_bond", 4)       # 헤르타 채권 (초기 환영 지급 4장)
    u_data.setdefault("herta_progress", 0)   # 10연차당 +1 헤르타 채권 누적 카운터
    u_data.setdefault("special_pass", 0)     # 별의 궤도 전용티켓
    u_data.setdefault("standard_pass", 0)    # 별의 궤도 티켓
    u_data.setdefault("traveler_guide", 0)   # 여행 가이드 (레벨업 Lv.1~80)
    u_data.setdefault("shop_monthly", {})
    u_data.setdefault("party", [])           # 4인 파티 item_key 목록
    u_data.setdefault("profile_char", None)  # 개척자 카드 대표 캐릭터
    u_data.setdefault("profile_note", "")    # 한마디 상태 문구
    u_data.setdefault("history", [])

    # 유물 세트 효과 및 성급 라벨 보정 (캐릭터 5★/4★, 광추 5★/4★/3★, 유물 5★/4★/3★ 모두 보존)
    items_map = u_data.get("items")
    if isinstance(items_map, dict) and items_map:
        to_del = []
        for ik, rec in list(items_map.items()):
            if not isinstance(rec, dict):
                to_del.append(ik)
                continue
            master = HSR_ALL_ITEMS.get(ik)
            if rec.get("kind") == "relic" and master:
                rec["bonus_2p"] = master.get("bonus_2p", rec.get("bonus_2p", ""))
                rec["bonus_4p"] = master.get("bonus_4p", rec.get("bonus_4p", ""))
            rk = int(rec.get("rank") or (master.get("rank", 3) if master else 3))
            rec["rank"] = rk
            rec["rarity_label"] = "★" * rk
        for ik in to_del:
            items_map.pop(ik, None)

    return u_data


def get_hsr_time_rotation_context(now_dt: datetime.datetime | None = None) -> dict:
    """현재 한국 표준시(KST) 2시간 단위 블록에 맞춰 캐릭터·광추·유물 픽업을 동적으로 계산합니다."""
    now = now_dt or datetime.datetime.now(core.KST)
    slot_idx = (now.day * 12 + (now.hour // 2)) % len(HSR_TIME_ROTATION_CHAR_PAIRS)
    rel_idx = (now.day * 12 + (now.hour // 2)) % len(HSR_TIME_ROTATION_RELIC_PAIRS)
    start_hour = (now.hour // 2) * 2
    end_hour = (start_hour + 2) % 24
    c1_id, c2_id, theme_label = HSR_TIME_ROTATION_CHAR_PAIRS[slot_idx]
    r1_id, r2_id = HSR_TIME_ROTATION_RELIC_PAIRS[rel_idx]
    return {
        "slot_idx": slot_idx,
        "window_str": f"{start_hour:02d}:00~{end_hour:02d}:00 KST",
        "theme_label": theme_label,
        "char1_id": c1_id,
        "char2_id": c2_id,
        "lc_1_id": HSR_SIGNATURE_LCS.get(c1_id),
        "lc_2_id": HSR_SIGNATURE_LCS.get(c2_id),
        "relic_1_id": r1_id,
        "relic_2_id": r2_id,
    }


def resolve_effective_hsr_pickup(pickup_cfg: dict | None) -> dict:
    """설정된 스타레일 워프 픽업을 실제 캐릭터/광추/유물 객체로 해석합니다 (시각별 자동 로테이션 포함)."""
    chars, lcs = load_hsr_kr_db()
    by_char = {c["id"]: c for c in chars}
    by_lc = {l["id"]: l for l in lcs}
    by_rel = {r["id"]: r for r in HSR_RELICS}
    cfg = copy.deepcopy(pickup_cfg or {})

    lim_5_chars = [c for c in chars if c["rank"] == 5 and c["pool_type"] in ("한정", "콜라보 한정")]
    pool_4_chars = [c for c in chars if c["rank"] == 4 and c["warpable"]]
    lim_5_lcs = [l for l in lcs if l["rank"] == 5 and l["warp_source"] == "limited"]
    std_4_lcs = [l for l in lcs if l["rank"] == 4 and l["warp_source"] == "standard"]

    rot = get_hsr_time_rotation_context()

    c1_id = cfg.get("char1")
    c2_id = cfg.get("char2")
    is_time_rot_c = False
    if not c1_id or c1_id not in by_char:
        c1_id = rot["char1_id"] if rot["char1_id"] in by_char else (lim_5_chars[0]["id"] if lim_5_chars else (chars[0]["id"] if chars else None))
        is_time_rot_c = True
    if not c2_id or c2_id not in by_char or c2_id == c1_id:
        if rot["char2_id"] in by_char and rot["char2_id"] != c1_id:
            c2_id = rot["char2_id"]
        else:
            cand = [c["id"] for c in lim_5_chars if c["id"] != c1_id]
            c2_id = cand[0] if cand else c1_id

    c4_ids = [cid for cid in (cfg.get("char_4_ids") or []) if cid in by_char][:3]
    if len(c4_ids) < 3 and pool_4_chars:
        offset = (rot["slot_idx"] * 3) % max(1, len(pool_4_chars))
        rotated_4 = pool_4_chars[offset:] + pool_4_chars[:offset]
        for c in rotated_4:
            if c["id"] not in c4_ids:
                c4_ids.append(c["id"])
            if len(c4_ids) >= 3:
                break

    # 광추 픽업: 미지정 시 현재 픽업 5성 캐릭터의 전용 광추를 최우선 매칭!
    l1_id = cfg.get("lc_1")
    l2_id = cfg.get("lc_2")
    if not l1_id or l1_id not in by_lc:
        sig1 = HSR_SIGNATURE_LCS.get(c1_id or "")
        l1_id = sig1 if (sig1 and sig1 in by_lc) else (lim_5_lcs[0]["id"] if lim_5_lcs else (lcs[0]["id"] if lcs else None))
    if not l2_id or l2_id not in by_lc or l2_id == l1_id:
        sig2 = HSR_SIGNATURE_LCS.get(c2_id or "")
        if sig2 and sig2 in by_lc and sig2 != l1_id:
            l2_id = sig2
        else:
            cand_l = [l["id"] for l in lim_5_lcs if l["id"] != l1_id]
            l2_id = cand_l[0] if cand_l else l1_id

    l4_ids = [lid for lid in (cfg.get("lc_4_ids") or []) if lid in by_lc and by_lc[lid].get("warpable")][:3]
    if len(l4_ids) < 3 and std_4_lcs:
        l_off = (rot["slot_idx"] * 3) % max(1, len(std_4_lcs))
        rot_l4 = std_4_lcs[l_off:] + std_4_lcs[:l_off]
        for l in rot_l4:
            if l["id"] not in l4_ids:
                l4_ids.append(l["id"])
            if len(l4_ids) >= 3:
                break

    # 유물 세트 픽업: 시각별 자동 로테이션 또는 수동 지정
    r1_id = cfg.get("relic_1")
    r2_id = cfg.get("relic_2")
    if not r1_id or r1_id not in by_rel:
        r1_id = rot["relic_1_id"] if rot["relic_1_id"] in by_rel else (HSR_RELICS[0]["id"] if HSR_RELICS else None)
    if not r2_id or r2_id not in by_rel or r2_id == r1_id:
        if rot["relic_2_id"] in by_rel and rot["relic_2_id"] != r1_id:
            r2_id = rot["relic_2_id"]
        else:
            cand_r = [r["id"] for r in HSR_RELICS if r["id"] != r1_id]
            r2_id = cand_r[0] if cand_r else r1_id

    b_name = cfg.get("banner_name")
    if not b_name or b_name in ("별을 향한 도약", "시각 연동 은하열차 워프") or is_time_rot_c:
        b_name = f"{rot['theme_label']} ({rot['window_str']})"

    return {
        "banner_name": b_name,
        "version_label": cfg.get("version_label") or f"⏰ {rot['window_str']} 실시간 로테이션",
        "time_window": rot["window_str"],
        "char1": by_char.get(c1_id),
        "char2": by_char.get(c2_id),
        "char_4": [by_char[i] for i in c4_ids if i in by_char],
        "lc_1": by_lc.get(l1_id),
        "lc_2": by_lc.get(l2_id),
        "lc_4": [by_lc[i] for i in l4_ids if i in by_lc],
        "relic_1": by_rel.get(r1_id),
        "relic_2": by_rel.get(r2_id),
        "raw": cfg,
    }


def _hsr_soft_pity_prob(pity_after: int, banner_key: str) -> float:
    if banner_key == "relic":
        if pity_after >= 50:
            return 1.0
        if pity_after >= 35:
            return min(1.0, 0.025 + 0.065 * (pity_after - 34))
        return 0.025
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
        if pity4_after >= 10:
            return 1.0
        if pity4_after >= 8:
            return 0.55
        return 0.18
    base = 0.066 if banner_key == "lc" else 0.051
    if pity4_after >= 10:
        return 1.0
    if pity4_after == 9:
        return base + 0.51
    return base


def _decorate_rolled_relic(base_set: dict, rank: int, rng: random.Random) -> dict:
    """터널 유물(4부위) 또는 차원 장신구(2부위)를 부위·주옵션·부옵션과 함께 감정 생성합니다."""
    picked = dict(base_set)
    is_pl = bool(picked.get("is_planar"))
    slots = HSR_PLANAR_SLOTS if is_pl else HSR_CAVERN_SLOTS
    slot = rng.choice(slots)
    main_stat = rng.choice(slot["main_stats"])
    sub_cnt = 4 if rank == 5 else (3 if rank == 4 else 2)
    subs = rng.sample(HSR_RELIC_SUBSTATS, k=min(sub_cnt, len(HSR_RELIC_SUBSTATS)))

    picked["rank"] = rank
    picked["rarity_label"] = "★" * rank
    picked["slot_code"] = slot["code"]
    picked["slot_name"] = f"{slot['emoji']}{slot['name']}"
    picked["main_stat"] = main_stat
    picked["sub_stats"] = subs
    picked["bonus_detail"] = f"{slot['emoji']}{slot['name']} [{main_stat}] · 부옵: {', '.join(subs)}"
    return picked


def _roll_single_hsr(
    state: dict,
    banner_key: str,
    eff_pickup: dict,
    std_5_chars: list[dict],
    std_4_chars: list[dict],
    std_5_lcs: list[dict],
    std_4_lcs: list[dict],
    std_3_lcs: list[dict],
    rng: random.Random,
) -> dict:
    """스타레일 워프 단일 추첨 (공식 DB 성급 기준: 5★ / 4★ / 3★ 워프 및 터널/장신구 5★ / 4★ / 3★ 감정)"""
    if banner_key in ("char1", "char2"):
        state["pity_char"] += 1
        state["pity_4_char"] += 1
        p5 = _hsr_soft_pity_prob(state["pity_char"], banner_key)
        p4 = _hsr_soft_4_prob(state["pity_4_char"], banner_key)
        roll = rng.random()

        featured_c = eff_pickup["char1"] if banner_key == "char1" else eff_pickup["char2"]
        if not featured_c:
            featured_c = rng.choice(std_5_chars)

        if roll < p5:
            pity_used = state["pity_char"]
            state["pity_char"] = 0
            if state["guaranteed_char"] or rng.random() < 0.50:
                picked = dict(featured_c)
                picked["is_pickup"] = True
                state["guaranteed_char"] = False
            else:
                picked = dict(rng.choice(std_5_chars))
                picked["is_pickup"] = False
                state["guaranteed_char"] = True
            picked["pity_used"] = pity_used
            return picked

        if state["pity_4_char"] >= 10 or roll < p5 + p4:
            state["pity_4_char"] = 0
            c4_pickups = eff_pickup["char_4"]
            p4_ids = {c["id"] for c in c4_pickups}
            if c4_pickups and (state["guaranteed_4_char"] or rng.random() < 0.50):
                state["guaranteed_4_char"] = False
                picked = dict(rng.choice(c4_pickups))
                picked["is_pickup"] = True
                return picked
            else:
                state["guaranteed_4_char"] = True
                non_pickup_4_chars = [c for c in std_4_chars if c["id"] not in p4_ids] or std_4_chars
                if rng.random() < 0.50:
                    picked = dict(rng.choice(non_pickup_4_chars))
                else:
                    picked = dict(rng.choice(std_4_lcs))
                picked["is_pickup"] = False
                return picked

        picked = dict(rng.choice(std_3_lcs))
        picked["is_pickup"] = False
        return picked

    elif banner_key == "lc":
        state["pity_lc"] += 1
        state["pity_4_lc"] += 1
        p5 = _hsr_soft_pity_prob(state["pity_lc"], "lc")
        p4 = _hsr_soft_4_prob(state["pity_4_lc"], "lc")
        roll = rng.random()

        lc_pool = [l for l in (eff_pickup.get("lc_1"), eff_pickup.get("lc_2")) if l]
        if not lc_pool:
            lc_pool = [rng.choice(std_5_lcs)]

        if roll < p5:
            pity_used = state["pity_lc"]
            state["pity_lc"] = 0
            if state["guaranteed_lc"] or rng.random() < 0.75:
                picked = dict(rng.choice(lc_pool))
                picked["is_pickup"] = True
                state["guaranteed_lc"] = False
            else:
                picked = dict(rng.choice(std_5_lcs))
                picked["is_pickup"] = False
                state["guaranteed_lc"] = True
            picked["pity_used"] = pity_used
            return picked

        if state["pity_4_lc"] >= 10 or roll < p5 + p4:
            state["pity_4_lc"] = 0
            l4_pickups = eff_pickup["lc_4"]
            l4_ids = {l["id"] for l in l4_pickups}
            if l4_pickups and (state["guaranteed_4_lc"] or rng.random() < 0.75):
                state["guaranteed_4_lc"] = False
                picked = dict(rng.choice(l4_pickups))
                picked["is_pickup"] = True
                return picked
            else:
                state["guaranteed_4_lc"] = True
                non_pickup_4_lcs = [l for l in std_4_lcs if l["id"] not in l4_ids] or std_4_lcs
                if rng.random() < 0.50:
                    picked = dict(rng.choice(non_pickup_4_lcs))
                else:
                    picked = dict(rng.choice(std_4_chars))
                picked["is_pickup"] = False
                return picked

        picked = dict(rng.choice(std_3_lcs))
        picked["is_pickup"] = False
        return picked

    elif banner_key == "relic":
        state["pity_relic"] = int(state.get("pity_relic", 0)) + 1
        state["pity_4_relic"] = int(state.get("pity_4_relic", 0)) + 1
        p5 = _hsr_soft_pity_prob(state["pity_relic"], "relic")
        p4 = _hsr_soft_4_prob(state["pity_4_relic"], "relic")
        roll = rng.random()

        all_relics = HSR_RELICS or HSR_EMBEDDED_FALLBACK_RELICS
        feat_relics = [r for r in (eff_pickup.get("relic_1"), eff_pickup.get("relic_2")) if r]
        if not feat_relics:
            feat_relics = all_relics[:2]

        if roll < p5:
            pity_used = state["pity_relic"]
            state["pity_relic"] = 0
            state["pity_4_relic"] = 0
            if state.get("guaranteed_relic") or rng.random() < 0.80:
                base_r = rng.choice(feat_relics)
                is_pk = True
                state["guaranteed_relic"] = False
            else:
                off_r = [r for r in all_relics if r["id"] not in {x["id"] for x in feat_relics}] or all_relics
                base_r = rng.choice(off_r)
                is_pk = False
                state["guaranteed_relic"] = True
            picked = _decorate_rolled_relic(base_r, 5, rng)
            picked["is_pickup"] = is_pk
            picked["pity_used"] = pity_used
            return picked

        if state["pity_4_relic"] >= 10 or roll < p5 + p4:
            state["pity_4_relic"] = 0
            base_r = rng.choice(feat_relics) if rng.random() < 0.65 else rng.choice(all_relics)
            picked = _decorate_rolled_relic(base_r, 4, rng)
            picked["is_pickup"] = (base_r["id"] in {x["id"] for x in feat_relics})
            return picked

        base_r = rng.choice(all_relics)
        picked = _decorate_rolled_relic(base_r, 3, rng)
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
                picked = dict(rng.choice(std_5_chars))
            else:
                picked = dict(rng.choice(std_5_lcs))
            picked["is_pickup"] = False
            picked["pity_used"] = pity_used
            return picked

        if state["pity_4_standard"] >= 10 or roll < p5 + p4:
            state["pity_4_standard"] = 0
            if rng.random() < 0.50:
                picked = dict(rng.choice(std_4_chars))
            else:
                picked = dict(rng.choice(std_4_lcs))
            picked["is_pickup"] = False
            return picked

        picked = dict(rng.choice(std_3_lcs))
        picked["is_pickup"] = False
        return picked


def _apply_hsr_item_to_account(u_data: dict, item: dict, now_iso: str) -> tuple[int, int]:
    """유저 스타레일 보관함에 캐릭터/광추/유물을 추가하고 성혼(E0~E6)/중첩(S1~S5)/강화(+3~+15) 및 별빛/잔재를 계산합니다."""
    items_map = u_data.setdefault("items", {})
    i_key = item["item_key"]
    rank = int(item.get("rank", 3))
    kind = item.get("kind", "lc")

    existing = items_map.get(i_key)
    gained_starlight = 0
    gained_embers = 20 if rank <= 3 else (30 if rank == 5 else 20)

    if existing:
        existing["count"] = int(existing.get("count", 1)) + 1
        existing["last_obtained_at"] = now_iso
        existing["name"] = item.get("name", existing.get("name", ""))
        item["is_new"] = False
        if rank > int(existing.get("rank", 3)):
            existing["rank"] = rank
            existing["rarity_label"] = "★" * rank
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
        elif kind == "relic":
            cur_lv = int(existing.get("level", 3))
            new_lv = min(15, cur_lv + 3)
            existing["level"] = new_lv
            existing["superimposition"] = min(5, int(existing.get("superimposition", 1)) + 1)
            if item.get("slot_name"):
                existing["slot_name"] = item["slot_name"]
                existing["main_stat"] = item.get("main_stat", "")
                existing["sub_stats"] = item.get("sub_stats", [])
                existing["bonus_detail"] = item.get("bonus_detail", "")
            item["new_level"] = new_lv
            item["new_super"] = existing["superimposition"]
            if rank == 5:
                gained_starlight = 16
            elif rank == 4:
                gained_starlight = 4
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
        item["is_new"] = True
        rec = {
            "id": item["id"],
            "kind": kind,
            "item_key": i_key,
            "name": item["name"],
            "rank": rank,
            "rarity_label": "★" * rank,
            "path": item.get("path", "Warrior"),
            "path_name": item.get("path_name", "파멸"),
            "path_emoji": item.get("path_emoji", "⚔️"),
            "pool_type": item.get("pool_type", "상시"),
            "count": 1,
            "level": 3 if kind == "relic" else 1,
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
        elif kind == "relic":
            rec["is_planar"] = bool(item.get("is_planar"))
            rec["slot_name"] = item.get("slot_name", "🪖머리")
            rec["main_stat"] = item.get("main_stat", "HP +705")
            rec["sub_stats"] = item.get("sub_stats", [])
            rec["bonus_2p"] = item.get("bonus_2p", "")
            rec["bonus_4p"] = item.get("bonus_4p", "")
            rec["bonus_detail"] = item.get("bonus_detail", "")
            rec["superimposition"] = 1
            item["new_level"] = 3
            item["new_super"] = 1
            if rank == 5:
                gained_starlight = 16
            elif rank == 4:
                gained_starlight = 4
        else:
            rec["superimposition"] = 1
            item["new_super"] = 1
            if rank == 5:
                gained_starlight = 40
            elif rank == 4:
                gained_starlight = 8
        items_map[i_key] = rec

    u_data["starlight"] = int(u_data.get("starlight", 0)) + gained_starlight
    u_data["embers"] = int(u_data.get("embers", 0)) + gained_embers
    item["gained_starlight"] = gained_starlight
    item["gained_embers"] = gained_embers
    return gained_starlight, gained_embers


def _build_hsr_pools():
    chars, lcs = load_hsr_kr_db()
    std_5_chars = [c for c in chars if c["rank"] == 5 and c["id"] in HSR_STD_5_CHARS] or [c for c in chars if c["rank"] == 5 and c.get("warpable", True)]
    std_4_chars = [c for c in chars if c["rank"] == 4 and c["warpable"]] or [c for c in chars if c["rank"] == 4]
    std_5_lcs = [l for l in lcs if l["rank"] == 5 and l["warp_source"] == "standard"] or [l for l in lcs if l["rank"] == 5]
    std_4_lcs = [l for l in lcs if l["rank"] == 4 and l["warp_source"] == "standard"] or [l for l in lcs if l["rank"] == 4 and l["warpable"]]
    std_3_lcs = [l for l in lcs if l["rank"] == 3] or std_4_lcs
    return std_5_chars, std_4_chars, std_5_lcs, std_4_lcs, std_3_lcs


def execute_hsr_warp(guild_id: int, user_id: int, banner_key: str = "char1", count: int = 10, practice: bool = False) -> dict:
    """붕괴: 스타레일 워프/유물 감정을 1회 또는 10회 실행합니다."""
    if banner_key not in HSR_BANNER_CONFIGS:
        banner_key = "char1"
    count = 10 if count >= 10 else 1

    load_hsr_kr_db()
    std_5_chars, std_4_chars, std_5_lcs, std_4_lcs, std_3_lcs = _build_hsr_pools()

    data = core.load_data()
    eff_pickup = resolve_effective_hsr_pickup(data.get("hsr_pickup"))
    u_data = ensure_hsr_user(data, guild_id, user_id)

    rng = random.SystemRandom()
    if practice:
        sim_state = copy.deepcopy(u_data)
        owned_items = u_data.get("items", {})
        drawn = []
        for _ in range(count):
            it = _roll_single_hsr(sim_state, banner_key, eff_pickup, std_5_chars, std_4_chars, std_5_lcs, std_4_lcs, std_3_lcs, rng)
            prev = owned_items.get(it["item_key"])
            it["is_new"] = prev is None
            if it["kind"] == "char":
                it["new_eidolon"] = min(6, int(prev.get("eidolon", 0)) + 1) if prev else 0
            elif it["kind"] == "relic":
                it["new_level"] = min(15, int(prev.get("level", 3)) + 3) if prev else 3
                it["new_super"] = min(5, int(prev.get("superimposition", 1)) + 1) if prev else 1
            else:
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
        }

    now_iso = datetime.datetime.now(core.KST).isoformat()
    drawn = []
    tot_sl = 0
    tot_em = 0
    for _ in range(count):
        it = _roll_single_hsr(u_data, banner_key, eff_pickup, std_5_chars, std_4_chars, std_5_lcs, std_4_lcs, std_3_lcs, rng)
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
                "name": it["name"],
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
    }


def _record_hsr_hof(data: dict, guild_id: int, user_id: int, drawn: list[dict], banner_key: str, now_iso: str):
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


def toggle_hsr_item_lock(guild_id: int, user_id: int, item_key: str) -> tuple[bool, bool, dict | None]:
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
    data = core.load_data()
    u_data = ensure_hsr_user(data, guild_id, user_id)
    cat = get_hsr_shop_catalog()
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


def levelup_hsr_relic(guild_id: int, user_id: int, item_key: str) -> tuple[bool, str, dict]:
    """불멸의 잔재 ×20을 소모해 보유 유물을 +3강씩 최대 +15강까지 강화합니다."""
    data = core.load_data()
    u_data = ensure_hsr_user(data, guild_id, user_id)
    rel = u_data.get("items", {}).get(item_key)
    if not rel or rel.get("kind") != "relic":
        return False, "보유 중인 유물을 찾을 수 없습니다.", u_data
    cur_lv = int(rel.get("level", 3))
    if cur_lv >= 15:
        return False, f"🏺 **{rel['name']}** 유물은 이미 최고 강화 단계(`+15강`)입니다!", u_data
    embers = int(u_data.get("embers", 0))
    if embers < 20:
        return False, f"🫧 **불멸의 잔재**가 부족합니다! (필요: `20` / 보유: `{embers}`)", u_data
    u_data["embers"] = embers - 20
    new_lv = min(15, cur_lv + 3)
    rel["level"] = new_lv
    subs = list(rel.get("sub_stats") or [])
    if len(subs) < 4:
        avail = [s for s in HSR_RELIC_SUBSTATS if s not in subs]
        if avail:
            subs.append(random.choice(avail))
            rel["sub_stats"] = subs
    core.save_data(data)
    return True, f"🔨 **{rel['name']}** 유물 강화 성공! `+{cur_lv}` ➔ **`+{new_lv}`** (`-20 불멸의 잔재`)", u_data


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
    relics = HSR_RELICS or []
    data = core.load_data()
    u_data = ensure_hsr_user(data, guild_id, user_id)
    owned_map = u_data.get("items", {})

    all_master = chars + lcs + relics
    warp_master = [it for it in all_master if it.get("warpable", True)]

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
    l3_tot = sum(1 for l in lcs if l["rank"] == 3)
    l3_own = sum(1 for l in lcs if l["rank"] == 3 and l["item_key"] in owned_map)
    r5_tot = len(relics)
    r5_own = sum(1 for r in relics if r["item_key"] in owned_map)

    rate = (len(owned_all) / max(1, len(all_master))) * 100.0
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
        "l3": (l3_own, l3_tot),
        "r5": (r5_own, r5_tot),
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
    data = core.load_data()
    if preset_key in ("reset", "time_rotation"):
        data["hsr_pickup"] = copy.deepcopy(core.DEFAULT_CONFIG["hsr_pickup"])
        core.save_data(data)
        eff = resolve_effective_hsr_pickup(data["hsr_pickup"])
        msg = "⏰ 스타레일 워프가 **KST 시각 연동 2시간 자동 로테이션** 모드로 설정되었습니다!" if preset_key == "time_rotation" else "🧹 스타레일 워프 픽업 설정이 기본값(시각 연동 로테이션)으로 초기화되었습니다."
        return True, msg, eff

    preset = HSR_BANNER_PRESETS.get(preset_key)
    if not preset:
        return False, "알 수 없는 프리셋입니다.", resolve_effective_hsr_pickup(data.get("hsr_pickup"))

    now_iso = datetime.datetime.now(core.KST).isoformat()
    cfg = {
        "char1": preset.get("char1"),
        "char2": preset.get("char2"),
        "char_4_ids": list(preset.get("char_4_ids") or []),
        "lc_1": preset.get("lc_1"),
        "lc_2": preset.get("lc_2"),
        "lc_4_ids": [],
        "relic_1": preset.get("relic_1"),
        "relic_2": preset.get("relic_2"),
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


async def hsr_relic_autocomplete(interaction, current: str):
    from discord import app_commands
    load_hsr_kr_db()
    q = (current or "").strip().lower()
    cands = [r for r in HSR_RELICS if not q or q in r["name"].lower() or q in r["id"]]
    return [
        app_commands.Choice(name=f"🏺 {r['name']} ({r['path_name']})"[:100], value=r["id"])
        for r in cands[:25]
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
