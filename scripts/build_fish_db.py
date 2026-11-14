#!/usr/bin/env python3
"""
scripts/build_fish_db.py
공개 생물다양성 API(iNaturalist Taxa + Wikidata Taxon Labels/Measurements)로부터
실제 공개 어류 데이터를 수집·정제하고, 기존 fishing_core.py의 140종 ID를 100% 보존하여
1,000종+ 초대규모 글로벌 어류 JSON 데이터베이스(fish_species_db.json)를 생성합니다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# ==========================================
# 표준 지역별 세부 구역 (Sub-Zone / Region) 매트릭스
# ==========================================
CANONICAL_ZONES: Dict[str, List[str]] = {
    "lake": [
        "수초 연안",
        "맑은 중층수",
        "깊은 심수층",
        "열대·아열대 대호",
    ],
    "river": [
        "상류 1급수 계곡",
        "중류 자갈 여울",
        "대하천 본류",
        "강·바다 기수역",
    ],
    "sea": [
        "연안 갯바위·내만",
        "산호초·열대 해역",
        "대륙붕·외해",
        "원양·회유 해역",
        "심해·해구",
    ],
}

# 과(Family) / 목(Order) 생물학 분류 메타:
# (habitat, zone, (min_cm_range, max_cm_range), (weight_a, weight_b), base_rarity, active_time, weather, bait, emoji, kr_family_label)
FAMILY_BIOLOGY: Dict[str, Tuple[str, str, Tuple[float, float], Tuple[float, float], int, str, str, str, str, str]] = {
    # --- FRESHWATER: LAKES & PONDS ---
    "Cyprinidae": ("lake", "수초 연안", (10.0, 52.0), (0.016, 3.02), 1, "all", "clear", "dough", "🐟", "잉어과"),
    "Acheilognathidae": ("lake", "수초 연안", (4.0, 10.5), (0.014, 3.00), 1, "day", "clear", "dough", "🐠", "납자루아과"),
    "Xenocyprididae": ("lake", "맑은 중층수", (12.0, 58.0), (0.011, 3.02), 2, "day", "clear", "dough", "🐟", "강준치·치리아과"),
    "Centrarchidae": ("lake", "수초 연안", (14.0, 48.0), (0.019, 3.05), 2, "day", "clear", "lure", "🐟", "검정우럭과"),
    "Percidae": ("lake", "맑은 중층수", (14.0, 46.0), (0.014, 3.02), 2, "day", "fog", "lure", "🐟", "농어·퍼치과"),
    "Esocidae": ("lake", "수초 연안", (38.0, 118.0), (0.0085, 3.04), 3, "day", "fog", "lure", "🐊", "강꼬치고기과"),
    "Osmeridae": ("lake", "맑은 중층수", (8.0, 22.0), (0.007, 3.05), 2, "night", "clear", "dough", "🐟", "빙어과"),
    "Cichlidae": ("lake", "열대·아열대 대호", (10.0, 42.0), (0.021, 3.02), 2, "day", "clear", "worm", "🐠", "시클리드과"),
    "Channidae": ("lake", "수초 연안", (32.0, 96.0), (0.012, 3.02), 3, "day", "fog", "lure", "🦈", "가물치과"),
    "Osteoglossidae": ("lake", "열대·아열대 대호", (48.0, 145.0), (0.008, 3.02), 4, "night", "rain", "golden", "🐉", "골설어과(아로와나)"),
    "Arapaimidae": ("lake", "열대·아열대 대호", (110.0, 260.0), (0.011, 3.00), 5, "day", "rain", "golden", "🐉", "아라파이마과"),
    "Osphronemidae": ("lake", "수초 연안", (5.0, 22.0), (0.016, 3.00), 2, "day", "fog", "worm", "🐠", "버들붕어·구라미과"),
    "Betta": ("lake", "수초 연안", (4.0, 9.0), (0.015, 3.00), 2, "day", "clear", "worm", "🐠", "투어류"),
    "Poeciliidae": ("lake", "수초 연안", (3.0, 8.5), (0.012, 2.98), 1, "day", "clear", "dough", "🐠", "송사리·난태생송사리과"),
    "Cyprinodontidae": ("lake", "수초 연안", (3.5, 9.5), (0.013, 3.00), 2, "day", "clear", "dough", "🐟", "키리피시과"),
    "Adrianichthyidae": ("lake", "수초 연안", (2.5, 5.5), (0.011, 2.95), 1, "day", "clear", "dough", "🐟", "송사리과"),
    "Aplocheilidae": ("lake", "열대·아열대 대호", (4.0, 10.0), (0.012, 3.00), 2, "day", "rain", "worm", "🐠", "킬리피시과"),
    "Nothobranchiidae": ("lake", "열대·아열대 대호", (3.5, 8.5), (0.013, 3.00), 3, "day", "rain", "worm", "🐠", "아프리카 킬리피시과"),
    "Acipenseridae": ("lake", "깊은 심수층", (65.0, 210.0), (0.0078, 3.02), 4, "all", "storm", "shrimp", "🦈", "철갑상어과"),
    "Polyodontidae": ("river", "대하천 본류", (85.0, 195.0), (0.0082, 3.00), 5, "all", "fog", "golden", "🔱", "주걱철갑상어과"),
    "Lepisosteidae": ("river", "대하천 본류", (55.0, 175.0), (0.0068, 3.04), 4, "day", "storm", "lure", "🐊", "레피소스테우스과(가아)"),
    "Amiidae": ("lake", "수초 연안", (40.0, 92.0), (0.012, 3.02), 4, "night", "fog", "lure", "🐊", "아미아과(보우핀)"),
    "Latidae": ("lake", "열대·아열대 대호", (48.0, 150.0), (0.015, 3.02), 4, "night", "clear", "shrimp", "👑", "라테스과"),
    "Coregonidae": ("lake", "깊은 심수층", (24.0, 58.0), (0.011, 3.02), 3, "night", "fog", "glow", "❄️", "백어아과"),
    "Lotidae": ("lake", "깊은 심수층", (30.0, 88.0), (0.009, 3.02), 3, "night", "fog", "worm", "🐟", "모오케과"),
    "Synbranchidae": ("lake", "수초 연안", (25.0, 72.0), (0.0022, 2.98), 2, "night", "rain", "worm", "🐍", "드렁허리과"),

    # --- FRESHWATER: RIVERS & STREAMS ---
    "Salmonidae": ("river", "상류 1급수 계곡", (24.0, 82.0), (0.013, 3.02), 3, "day", "clear", "lure", "🌈", "연어과"),
    "Leuciscidae": ("river", "중류 자갈 여울", (7.0, 24.0), (0.010, 3.02), 1, "day", "clear", "dough", "🐟", "황어·피라미과"),
    "Gobionidae": ("river", "중류 자갈 여울", (7.5, 24.0), (0.010, 3.02), 1, "day", "clear", "worm", "🐟", "모래무지아과"),
    "Danionidae": ("river", "대하천 본류", (4.0, 14.0), (0.010, 3.00), 1, "day", "clear", "dough", "🐠", "다니오·피라미아과"),
    "Tincidae": ("lake", "수초 연안", (20.0, 52.0), (0.017, 3.02), 2, "day", "fog", "dough", "🐟", "틴카과"),
    "Plecoglossidae": ("river", "상류 1급수 계곡", (13.0, 30.0), (0.010, 3.02), 2, "day", "clear", "dough", "🐟", "은어과"),
    "Cobitidae": ("river", "중류 자갈 여울", (7.0, 20.0), (0.0052, 3.02), 1, "night", "rain", "worm", "🐟", "미꾸리과"),
    "Nemacheilidae": ("river", "상류 1급수 계곡", (6.0, 15.0), (0.007, 3.00), 2, "night", "clear", "worm", "🐟", "종개과"),
    "Balitoridae": ("river", "상류 1급수 계곡", (5.0, 12.0), (0.009, 3.00), 2, "day", "clear", "worm", "🐟", "껍질미꾸리과"),
    "Botiidae": ("river", "대하천 본류", (8.0, 26.0), (0.011, 3.02), 2, "night", "rain", "worm", "🐠", "보티아과"),
    "Siluridae": ("river", "대하천 본류", (24.0, 95.0), (0.010, 3.02), 2, "night", "rain", "worm", "🐟", "메기과"),
    "Bagridae": ("river", "중류 자갈 여울", (14.0, 46.0), (0.013, 3.02), 2, "night", "rain", "worm", "🐡", "동자개과"),
    "Amblycipitidae": ("river", "상류 1급수 계곡", (7.0, 16.0), (0.011, 3.02), 2, "night", "rain", "worm", "🐟", "퉁가리과"),
    "Ictaluridae": ("river", "대하천 본류", (22.0, 88.0), (0.012, 3.02), 2, "night", "rain", "worm", "🐟", "북미메기과"),
    "Pimelodidae": ("river", "대하천 본류", (35.0, 125.0), (0.014, 3.02), 4, "night", "storm", "shrimp", "🐠", "피멜로두스메기과"),
    "Loricariidae": ("river", "대하천 본류", (10.0, 42.0), (0.015, 3.00), 2, "night", "all", "worm", "🐟", "로리카리아(플레코)과"),
    "Callichthyidae": ("river", "대하천 본류", (4.5, 11.0), (0.018, 3.00), 2, "all", "clear", "worm", "🐟", "칼리크티스(코리도라스)과"),
    "Clariidae": ("river", "대하천 본류", (25.0, 82.0), (0.011, 3.02), 2, "night", "rain", "worm", "🐟", "클라리아스과"),
    "Pangasiidae": ("river", "대하천 본류", (45.0, 165.0), (0.013, 3.02), 4, "all", "rain", "shrimp", "🦈", "팡가시우스과"),
    "Sinipercidae": ("river", "중류 자갈 여울", (18.0, 56.0), (0.017, 3.04), 3, "night", "fog", "lure", "🐯", "쏘가리과"),
    "Centropomidae": ("river", "강·바다 기수역", (30.0, 98.0), (0.013, 3.02), 3, "night", "rain", "lure", "🐟", "센트로포무스과(스누크)"),
    "Odontobutidae": ("river", "중류 자갈 여울", (8.0, 22.0), (0.015, 3.02), 1, "night", "all", "worm", "🐟", "동사리과"),
    "Characidae": ("river", "대하천 본류", (4.0, 22.0), (0.014, 3.02), 2, "day", "clear", "dough", "🐠", "카라신(테트라)과"),
    "Serrasalmidae": ("river", "대하천 본류", (15.0, 55.0), (0.024, 3.02), 3, "day", "rain", "shrimp", "🦈", "세라살무스(피라냐·파쿠)과"),
    "Alestidae": ("river", "대하천 본류", (25.0, 105.0), (0.014, 3.04), 4, "day", "storm", "lure", "🦈", "알레스테스(타이거피시)과"),
    "Erythrinidae": ("river", "대하천 본류", (24.0, 75.0), (0.014, 3.02), 3, "night", "fog", "lure", "🐟", "에리트리누스(울프피시)과"),
    "Gymnotidae": ("river", "대하천 본류", (45.0, 165.0), (0.005, 3.00), 4, "night", "storm", "glow", "⚡", "전기뱀장어과"),
    "Anguillidae": ("river", "강·바다 기수역", (38.0, 120.0), (0.0020, 3.04), 3, "night", "rain", "worm", "🐍", "뱀장어과"),
    "Mugilidae": ("river", "강·바다 기수역", (24.0, 68.0), (0.014, 3.00), 2, "day", "clear", "dough", "🐟", "숭어과"),
    "Petromyzontidae": ("river", "상류 1급수 계곡", (16.0, 56.0), (0.0018, 2.98), 4, "night", "fog", "glow", "🪱", "칠성장어과"),
    "Cottidae": ("river", "상류 1급수 계곡", (8.0, 28.0), (0.014, 3.02), 2, "night", "clear", "worm", "🐟", "둑중개과"),
    "Gasterosteidae": ("river", "강·바다 기수역", (4.5, 11.0), (0.011, 3.00), 2, "day", "clear", "dough", "🐟", "큰가시고기과"),
    "Lateolabracidae": ("river", "강·바다 기수역", (32.0, 96.0), (0.012, 3.02), 3, "night", "storm", "lure", "🐟", "농어과"),
    "Engraulidae": ("river", "강·바다 기수역", (9.0, 26.0), (0.007, 3.02), 1, "day", "clear", "dough", "🐟", "멸치과"),

    # --- MARINE: COASTAL, REEF, SHELF, PELAGIC, DEEP SEA ---
    "Sparidae": ("sea", "연안 갯바위·내만", (20.0, 72.0), (0.022, 3.01), 3, "all", "clear", "shrimp", "🐠", "도미과"),
    "Sebastidae": ("sea", "연안 갯바위·내만", (16.0, 52.0), (0.019, 3.02), 2, "night", "clear", "shrimp", "🐟", "볼락과"),
    "Scorpaenidae": ("sea", "연안 갯바위·내만", (14.0, 42.0), (0.020, 3.02), 2, "night", "all", "shrimp", "🐠", "양볼락·쏨뱅이과"),
    "Hexagrammidae": ("sea", "연안 갯바위·내만", (16.0, 48.0), (0.014, 3.02), 2, "day", "rain", "worm", "🐟", "쥐노래미과"),
    "Gobiidae": ("sea", "연안 갯바위·내만", (6.0, 22.0), (0.012, 3.00), 1, "all", "all", "worm", "🐟", "망둑어과"),
    "Oxudercidae": ("river", "강·바다 기수역", (7.0, 20.0), (0.011, 3.00), 1, "day", "clear", "worm", "🐟", "말뚝망둥어과"),
    "Blenniidae": ("sea", "연안 갯바위·내만", (6.0, 18.0), (0.011, 3.00), 1, "day", "clear", "worm", "🐟", "청베도라치과"),
    "Tripterygiidae": ("sea", "연안 갯바위·내만", (3.5, 9.0), (0.011, 3.00), 2, "day", "clear", "worm", "🐠", "먹베도라치과"),
    "Labridae": ("sea", "산호초·열대 해역", (14.0, 62.0), (0.017, 3.02), 2, "day", "clear", "shrimp", "🐠", "놀래기·비늘베도라치과"),
    "Scaridae": ("sea", "산호초·열대 해역", (24.0, 78.0), (0.019, 3.02), 3, "day", "clear", "shrimp", "🌈", "파랑비늘돔과"),
    "Pomacentridae": ("sea", "산호초·열대 해역", (6.0, 16.0), (0.021, 3.00), 1, "day", "clear", "dough", "🐠", "자리돔·흰동가리과"),
    "Chaetodontidae": ("sea", "산호초·열대 해역", (10.0, 24.0), (0.026, 3.00), 2, "day", "clear", "shrimp", "🐠", "나비고기과"),
    "Pomacanthidae": ("sea", "산호초·열대 해역", (14.0, 44.0), (0.026, 3.02), 3, "day", "clear", "shrimp", "👑", "청줄돔(엔젤피시)과"),
    "Acanthuridae": ("sea", "산호초·열대 해역", (16.0, 48.0), (0.023, 3.02), 2, "day", "clear", "dough", "🐠", "양쥐돔과"),
    "Zanclidae": ("sea", "산호초·열대 해역", (14.0, 26.0), (0.025, 3.00), 3, "day", "clear", "shrimp", "🐠", "깃대돔과"),
    "Epinephelidae": ("sea", "산호초·열대 해역", (32.0, 118.0), (0.019, 3.02), 4, "night", "storm", "shrimp", "👑", "바리과(그루퍼)"),
    "Serranidae": ("sea", "산호초·열대 해역", (16.0, 65.0), (0.018, 3.02), 3, "day", "clear", "shrimp", "🐠", "바리·꽃돔과"),
    "Lutjanidae": ("sea", "산호초·열대 해역", (24.0, 76.0), (0.018, 3.02), 3, "night", "clear", "shrimp", "🐠", "퉁돔(스내퍼)과"),
    "Haemulidae": ("sea", "산호초·열대 해역", (20.0, 56.0), (0.018, 3.02), 2, "night", "clear", "shrimp", "🐟", "하스돔과"),
    "Lethrinidae": ("sea", "산호초·열대 해역", (22.0, 64.0), (0.019, 3.02), 3, "night", "clear", "shrimp", "🐟", "갈돔과"),
    "Nemipteridae": ("sea", "대륙붕·외해", (15.0, 36.0), (0.016, 3.02), 2, "day", "clear", "shrimp", "🐠", "실꼬리돔과"),
    "Mullidae": ("sea", "산호초·열대 해역", (14.0, 38.0), (0.015, 3.02), 2, "day", "clear", "worm", "🐠", "촉수과"),
    "Apogonidae": ("sea", "산호초·열대 해역", (5.0, 14.0), (0.018, 3.00), 1, "night", "clear", "shrimp", "🐠", "동갈돔과"),
    "Holocentridae": ("sea", "산호초·열대 해역", (14.0, 36.0), (0.020, 3.00), 2, "night", "clear", "shrimp", "🐠", "얼게비늘과"),
    "Balistidae": ("sea", "산호초·열대 해역", (18.0, 52.0), (0.024, 3.00), 2, "day", "clear", "shrimp", "🐡", "쥐치복과"),
    "Monacanthidae": ("sea", "연안 갯바위·내만", (15.0, 42.0), (0.022, 3.00), 2, "day", "clear", "shrimp", "🐟", "쥐치과"),
    "Tetraodontidae": ("sea", "연안 갯바위·내만", (15.0, 52.0), (0.028, 3.00), 2, "day", "rain", "shrimp", "🐡", "참복과"),
    "Diodontidae": ("sea", "산호초·열대 해역", (22.0, 62.0), (0.032, 2.98), 3, "night", "clear", "shrimp", "🐡", "가시복과"),
    "Ostraciidae": ("sea", "산호초·열대 해역", (12.0, 36.0), (0.030, 2.98), 3, "day", "clear", "shrimp", "🐡", "거북복과"),
    "Syngnathidae": ("sea", "연안 갯바위·내만", (8.0, 28.0), (0.004, 2.90), 3, "day", "clear", "dough", "🐉", "실고기·해마과"),
    "Muraenidae": ("sea", "산호초·열대 해역", (45.0, 145.0), (0.0025, 3.02), 3, "night", "fog", "shrimp", "🐍", "곰치과"),
    "Congridae": ("sea", "대륙붕·외해", (40.0, 125.0), (0.0022, 3.02), 2, "night", "rain", "shrimp", "🐍", "붕장어과"),
    "Ophichthidae": ("sea", "연안 갯바위·내만", (30.0, 95.0), (0.0020, 3.00), 2, "night", "fog", "worm", "🐍", "바다뱀장어과"),
    "Kyphosidae": ("sea", "연안 갯바위·내만", (22.0, 56.0), (0.021, 3.02), 3, "day", "clear", "shrimp", "🐟", "황줄깜정이·벵에돔과"),
    "Girellidae": ("sea", "연안 갯바위·내만", (20.0, 54.0), (0.021, 3.02), 3, "day", "clear", "shrimp", "🐟", "벵에돔아과"),
    "Oplegnathidae": ("sea", "연안 갯바위·내만", (22.0, 66.0), (0.025, 3.00), 3, "day", "rain", "shrimp", "🐟", "돌돔과"),
    "Embiotocidae": ("sea", "연안 갯바위·내만", (14.0, 36.0), (0.018, 3.00), 1, "day", "all", "shrimp", "🐟", "망상어과"),
    "Sillaginidae": ("sea", "연안 갯바위·내만", (12.0, 29.0), (0.0085, 3.02), 1, "day", "clear", "worm", "🐟", "보리멸과"),
    "Platycephalidae": ("sea", "연안 갯바위·내만", (22.0, 66.0), (0.009, 3.02), 2, "day", "clear", "lure", "🐟", "양태과"),
    "Triglidae": ("sea", "대륙붕·외해", (18.0, 48.0), (0.012, 3.02), 2, "day", "all", "shrimp", "🐠", "성대과"),
    "Paralichthyidae": ("sea", "대륙붕·외해", (28.0, 92.0), (0.013, 3.02), 3, "all", "all", "lure", "🐟", "넙치과"),
    "Pleuronectidae": ("sea", "대륙붕·외해", (22.0, 82.0), (0.015, 3.00), 2, "day", "clear", "worm", "🐟", "가자미과"),
    "Soleidae": ("sea", "연안 갯바위·내만", (15.0, 42.0), (0.013, 3.00), 2, "night", "all", "worm", "🐟", "서대·납서대과"),
    "Cynoglossidae": ("sea", "대륙붕·외해", (18.0, 48.0), (0.009, 3.00), 2, "night", "all", "worm", "🐟", "참서대과"),
    "Sciaenidae": ("sea", "대륙붕·외해", (24.0, 86.0), (0.013, 3.02), 2, "night", "fog", "shrimp", "🐟", "민어과"),
    "Gadidae": ("sea", "대륙붕·외해", (35.0, 115.0), (0.012, 3.02), 3, "all", "fog", "lure", "🐟", "대구과"),
    "Merlucciidae": ("sea", "대륙붕·외해", (32.0, 98.0), (0.010, 3.02), 2, "night", "fog", "lure", "🐟", "민대구과"),
    "Clupeidae": ("sea", "대륙붕·외해", (13.0, 32.0), (0.010, 3.02), 1, "day", "clear", "dough", "🐟", "청어과"),
    "Carangidae": ("sea", "원양·회유 해역", (30.0, 125.0), (0.013, 3.02), 3, "day", "rain", "lure", "🐟", "전갱이·방어과"),
    "Scombridae": ("sea", "원양·회유 해역", (36.0, 195.0), (0.014, 3.02), 3, "day", "clear", "lure", "🐟", "고등어·다랑어과"),
    "Istiophoridae": ("sea", "원양·회유 해역", (140.0, 360.0), (0.0085, 3.02), 5, "day", "clear", "golden", "⚔️", "돛새치·청새치과"),
    "Xiphiidae": ("sea", "원양·회유 해역", (150.0, 380.0), (0.011, 3.02), 5, "night", "storm", "golden", "⚔️", "황새치과"),
    "Coryphaenidae": ("sea", "원양·회유 해역", (55.0, 165.0), (0.0095, 3.02), 4, "day", "clear", "lure", "🌈", "만새기과"),
    "Sphyraenidae": ("sea", "원양·회유 해역", (38.0, 145.0), (0.007, 3.02), 3, "day", "clear", "lure", "🦈", "꼬치고기(바라쿠다)과"),
    "Belonidae": ("sea", "원양·회유 해역", (32.0, 105.0), (0.004, 3.02), 2, "day", "clear", "lure", "🐟", "동갈치과"),
    "Hemiramphidae": ("sea", "연안 갯바위·내만", (18.0, 40.0), (0.0045, 3.02), 1, "day", "clear", "dough", "🐟", "학꽁치과"),
    "Exocoetidae": ("sea", "원양·회유 해역", (16.0, 38.0), (0.009, 3.02), 2, "day", "clear", "dough", "🦅", "날치과"),
    "Scomberesocidae": ("sea", "원양·회유 해역", (20.0, 42.0), (0.0045, 3.04), 1, "night", "clear", "dough", "🐟", "꽁치과"),
    "Trichiuridae": ("sea", "대륙붕·외해", (55.0, 155.0), (0.0009, 3.00), 3, "night", "clear", "shrimp", "⚔️", "갈치과"),
    "Pomatomidae": ("sea", "원양·회유 해역", (35.0, 105.0), (0.013, 3.02), 3, "day", "storm", "lure", "🐟", "게르치과"),
    "Rachycentridae": ("sea", "원양·회유 해역", (60.0, 160.0), (0.011, 3.02), 4, "day", "clear", "lure", "🦈", "날개다랑어·코비아과"),
    "Echeneidae": ("sea", "원양·회유 해역", (25.0, 78.0), (0.008, 3.00), 3, "all", "all", "shrimp", "🐟", "빨판상어과"),
    "Molidae": ("sea", "원양·회유 해역", (85.0, 240.0), (0.048, 2.95), 4, "day", "clear", "glow", "🐡", "개복치과"),
    "Lophiidae": ("sea", "심해·해구", (32.0, 105.0), (0.024, 2.98), 3, "night", "fog", "glow", "🐡", "아귀과"),
    "Antennariidae": ("sea", "산호초·열대 해역", (8.0, 26.0), (0.028, 2.98), 3, "all", "fog", "shrimp", "🐡", "씬벵이(개구리물고기)과"),
    "Ogcocephalidae": ("sea", "심해·해구", (10.0, 28.0), (0.022, 2.98), 3, "night", "fog", "glow", "🐡", "부치과"),
    "Myctophidae": ("sea", "심해·해구", (6.0, 18.0), (0.011, 3.02), 3, "night", "fog", "glow", "💠", "샛비늘치과"),
    "Macrouridae": ("sea", "심해·해구", (28.0, 92.0), (0.007, 3.00), 4, "night", "fog", "glow", "💠", "민태(긴꼬리대구)과"),
    "Regalecidae": ("sea", "심해·해구", (180.0, 560.0), (0.0006, 2.95), 5, "night", "fog", "golden", "🐉", "산갈치과"),
    "Trachipteridae": ("sea", "심해·해구", (80.0, 220.0), (0.002, 2.96), 4, "night", "fog", "glow", "🐉", "투라치과"),
    "Chiasmodontidae": ("sea", "심해·해구", (12.0, 28.0), (0.010, 3.00), 4, "night", "storm", "glow", "💠", "검은별치과"),
    "Stomiidae": ("sea", "심해·해구", (15.0, 42.0), (0.005, 3.00), 4, "night", "storm", "glow", "💠", "별악어치(용치)과"),
    "Anoplopomatidae": ("sea", "심해·해구", (45.0, 110.0), (0.013, 3.02), 3, "night", "fog", "glow", "🐟", "은대구과"),
    "Berycidae": ("sea", "심해·해구", (24.0, 62.0), (0.021, 3.02), 4, "night", "fog", "glow", "🐠", "금눈돔과"),
    "Zeidae": ("sea", "대륙붕·외해", (22.0, 58.0), (0.022, 3.00), 3, "all", "fog", "lure", "🐠", "달고기과"),
    "Lampridae": ("sea", "심해·해구", (65.0, 165.0), (0.028, 3.00), 5, "all", "fog", "golden", "🌈", "붉평치과"),
    "Bramidae": ("sea", "원양·회유 해역", (30.0, 75.0), (0.018, 3.02), 3, "night", "storm", "lure", "🐟", "새다래과"),
    "Stromateidae": ("sea", "대륙붕·외해", (18.0, 46.0), (0.024, 3.00), 2, "day", "fog", "shrimp", "🐟", "병어과"),
    "Ammodytidae": ("sea", "연안 갯바위·내만", (10.0, 26.0), (0.005, 3.00), 1, "day", "clear", "worm", "🐟", "까나리과"),
    "Trichodontidae": ("sea", "대륙붕·외해", (14.0, 30.0), (0.014, 3.02), 2, "night", "fog", "worm", "🐟", "도루묵과"),
    "Liparidae": ("sea", "심해·해구", (16.0, 52.0), (0.016, 3.00), 3, "night", "fog", "glow", "🐟", "꼼치과"),
    "Zoarcidae": ("sea", "심해·해구", (20.0, 65.0), (0.007, 3.00), 3, "night", "fog", "glow", "🐍", "등가시치과"),
    "Carcharhinidae": ("sea", "원양·회유 해역", (95.0, 265.0), (0.011, 3.02), 4, "all", "storm", "shrimp", "🦈", "흉상어과"),
    "Sphyrnidae": ("sea", "원양·회유 해역", (110.0, 320.0), (0.010, 3.02), 4, "day", "storm", "lure", "🦈", "귀상어과"),
    "Lamnidae": ("sea", "원양·회유 해역", (140.0, 420.0), (0.013, 3.04), 5, "all", "storm", "golden", "🦈", "악상어과"),
    "Alopiidae": ("sea", "원양·회유 해역", (150.0, 390.0), (0.007, 3.02), 5, "day", "clear", "golden", "🦈", "환도상어과"),
    "Triakidae": ("sea", "대륙붕·외해", (60.0, 145.0), (0.009, 3.02), 3, "night", "all", "shrimp", "🦈", "까치상어과"),
    "Scyliorhinidae": ("sea", "대륙붕·외해", (38.0, 88.0), (0.008, 3.02), 3, "night", "fog", "shrimp", "🦈", "두툽상어과"),
    "Heterodontidae": ("sea", "연안 갯바위·내만", (50.0, 130.0), (0.014, 3.02), 3, "night", "all", "shrimp", "🦈", "괭이상어과"),
    "Squalidae": ("sea", "심해·해구", (48.0, 115.0), (0.009, 3.02), 3, "night", "fog", "glow", "🦈", "곱상어과"),
    "Somniosidae": ("sea", "심해·해구", (140.0, 420.0), (0.012, 3.02), 5, "night", "storm", "golden", "🦈", "잠상어과"),
    "Rhincodontidae": ("sea", "원양·회유 해역", (320.0, 850.0), (0.012, 3.00), 5, "day", "clear", "golden", "🐳", "고래상어과"),
    "Cetorhinidae": ("sea", "원양·회유 해역", (280.0, 720.0), (0.011, 3.00), 5, "day", "fog", "golden", "🐳", "돌묵상어과"),
    "Orectolobidae": ("sea", "산호초·열대 해역", (70.0, 195.0), (0.015, 3.02), 4, "night", "clear", "shrimp", "🦈", "수염상어과"),
    "Stegostomatidae": ("sea", "산호초·열대 해역", (90.0, 230.0), (0.012, 3.02), 4, "day", "clear", "shrimp", "🦈", "얼룩상어과"),
    "Mobulidae": ("sea", "원양·회유 해역", (130.0, 420.0), (0.018, 2.86), 5, "day", "fog", "golden", "🦅", "쥐가오리과"),
    "Myliobatidae": ("sea", "대륙붕·외해", (60.0, 185.0), (0.018, 2.90), 4, "day", "clear", "shrimp", "🦅", "매가오리과"),
    "Dasyatidae": ("sea", "대륙붕·외해", (42.0, 145.0), (0.020, 2.92), 3, "all", "all", "shrimp", "🦅", "색가오리과"),
    "Rajidae": ("sea", "대륙붕·외해", (40.0, 125.0), (0.016, 2.94), 3, "night", "fog", "shrimp", "🦅", "홍어과"),
    "Torpedinidae": ("sea", "대륙붕·외해", (35.0, 110.0), (0.022, 2.94), 4, "night", "storm", "glow", "⚡", "전기가오리과"),
    "Pristidae": ("sea", "강·바다 기수역", (160.0, 420.0), (0.009, 3.02), 5, "all", "storm", "golden", "⚔️", "톱가오리과"),
    "Rhinobatidae": ("sea", "연안 갯바위·내만", (45.0, 125.0), (0.012, 3.00), 3, "day", "clear", "shrimp", "🦈", "가래상어과"),
    "Chimaeridae": ("sea", "심해·해구", (45.0, 115.0), (0.008, 3.00), 4, "night", "fog", "glow", "💠", "은상어과"),
    "Latimeriidae": ("sea", "심해·해구", (110.0, 195.0), (0.018, 3.02), 5, "night", "storm", "golden", "💠", "실러캔스과"),
    "Pterois": ("sea", "산호초·열대 해역", (16.0, 38.0), (0.018, 3.02), 3, "night", "clear", "shrimp", "🦁", "쏠배감펭속"),
    "Synanceiidae": ("sea", "산호초·열대 해역", (16.0, 42.0), (0.028, 3.00), 4, "all", "fog", "shrimp", "🐡", "쏠종개·스톤피시과"),
    "Megalopidae": ("sea", "원양·회유 해역", (80.0, 220.0), (0.012, 3.02), 4, "night", "storm", "lure", "👑", "풀잉어(타폰)과"),
    "Albulidae": ("sea", "연안 갯바위·내만", (32.0, 82.0), (0.011, 3.02), 3, "day", "clear", "shrimp", "🐟", "여을멸과"),
    "Elopidae": ("sea", "연안 갯바위·내만", (35.0, 92.0), (0.009, 3.02), 3, "day", "clear", "lure", "🐟", "당멸치과"),
    "Priacanthidae": ("sea", "대륙붕·외해", (18.0, 42.0), (0.021, 3.00), 2, "night", "clear", "shrimp", "🐠", "붉은메기(큰눈돔)과"),
    "Siganidae": ("sea", "산호초·열대 해역", (16.0, 38.0), (0.020, 3.00), 2, "day", "clear", "dough", "🐠", "독가시치과"),
    "Malacanthidae": ("sea", "대륙붕·외해", (22.0, 56.0), (0.013, 3.02), 3, "day", "clear", "shrimp", "🐠", "옥돔과"),
    "Uranoscopidae": ("sea", "대륙붕·외해", (16.0, 42.0), (0.022, 3.00), 2, "night", "fog", "worm", "🐡", "통구멍과"),
    "Trachinidae": ("sea", "대륙붕·외해", (16.0, 42.0), (0.011, 3.02), 2, "day", "clear", "worm", "🐟", "동갈양태·위버과"),
    "Pempheridae": ("sea", "산호초·열대 해역", (9.0, 20.0), (0.020, 3.00), 2, "night", "clear", "shrimp", "🐠", "주걱치과"),
    "Aulostomidae": ("sea", "산호초·열대 해역", (35.0, 85.0), (0.004, 3.00), 3, "day", "clear", "lure", "🐠", "대롱치(트럼펫피시)과"),
    "Fistulariidae": ("sea", "산호초·열대 해역", (45.0, 145.0), (0.0025, 3.00), 3, "day", "clear", "lure", "🐠", "홍대치과"),
    "Gempylidae": ("sea", "심해·해구", (55.0, 165.0), (0.006, 3.02), 4, "night", "fog", "glow", "⚔️", "갈치꼬치과"),
    "Alepisauridae": ("sea", "심해·해구", (70.0, 195.0), (0.005, 3.00), 4, "night", "storm", "glow", "⚔️", "란셋피시과"),
    "Anarhichadidae": ("sea", "심해·해구", (60.0, 145.0), (0.014, 3.02), 4, "all", "fog", "shrimp", "🐺", "늑대고기과"),
    "Cyclopteridae": ("sea", "대륙붕·외해", (15.0, 46.0), (0.032, 2.98), 3, "all", "fog", "shrimp", "🐡", "도치(뚝지)과"),
    "Gobiidae": ("sea", "연안 갯바위·내만", (6.0, 20.0), (0.012, 3.00), 1, "all", "all", "worm", "🐟", "망둑어과"),
    "Clinidae": ("sea", "연안 갯바위·내만", (8.0, 24.0), (0.011, 3.00), 2, "day", "clear", "worm", "🐟", "베도라치아목"),
    "Pholidae": ("sea", "연안 갯바위·내만", (12.0, 28.0), (0.005, 3.00), 1, "all", "all", "worm", "🐍", "황줄베도라치과"),
    "Stichaeidae": ("sea", "연안 갯바위·내만", (14.0, 38.0), (0.007, 3.00), 2, "night", "clear", "worm", "🐟", "장갱이과"),
    "Batrachoididae": ("sea", "연안 갯바위·내만", (15.0, 42.0), (0.022, 3.00), 2, "night", "fog", "worm", "🐡", "두꺼비고기과"),
    "Dactylopteridae": ("sea", "대륙붕·외해", (18.0, 46.0), (0.016, 3.00), 3, "day", "clear", "shrimp", "🦅", "날개달린성대(매가오리성대)과"),
    "Callionymidae": ("sea", "연안 갯바위·내만", (10.0, 26.0), (0.010, 3.00), 2, "day", "clear", "worm", "🐠", "돛양태과"),
    "Cirrhitidae": ("sea", "산호초·열대 해역", (8.0, 22.0), (0.020, 3.00), 2, "day", "clear", "shrimp", "🐠", "매퉁이·호크피시과"),
    "Synodontidae": ("sea", "연안 갯바위·내만", (16.0, 42.0), (0.009, 3.02), 2, "day", "clear", "lure", "🐟", "매퉁이과"),
    "Moronidae": ("river", "강·바다 기수역", (32.0, 96.0), (0.014, 3.02), 3, "night", "rain", "lure", "🐟", "모로네과(줄무늬농어)"),
    "Fundulidae": ("river", "강·바다 기수역", (5.0, 13.0), (0.012, 3.00), 1, "day", "clear", "worm", "🐟", "킬리피시아목"),
    "Atherinopsidae": ("sea", "연안 갯바위·내만", (12.0, 34.0), (0.008, 3.02), 1, "day", "clear", "dough", "🐟", "은줄멸과"),
    "Atherinidae": ("sea", "연안 갯바위·내만", (8.0, 18.0), (0.008, 3.00), 1, "day", "clear", "dough", "🐟", "색줄멸과"),
    "Scatophagidae": ("river", "강·바다 기수역", (14.0, 34.0), (0.025, 3.00), 2, "day", "clear", "dough", "🐠", "스카트과"),
    "Monodactylidae": ("river", "강·바다 기수역", (12.0, 25.0), (0.022, 3.00), 2, "day", "clear", "shrimp", "🐠", "모노닥틸루스과"),
    "Toxotidae": ("river", "강·바다 기수역", (14.0, 30.0), (0.020, 3.00), 3, "day", "clear", "worm", "🐠", "물총고기과"),
    "Polynemidae": ("sea", "연안 갯바위·내만", (25.0, 88.0), (0.012, 3.02), 3, "all", "fog", "shrimp", "🐟", "날가지숭어(스레드핀)과"),
    "Terapontidae": ("river", "강·바다 기수역", (14.0, 34.0), (0.018, 3.02), 2, "day", "clear", "worm", "🐟", "살벤자리과"),
    "Kuhliidae": ("river", "강·바다 기수역", (12.0, 28.0), (0.017, 3.02), 2, "day", "clear", "shrimp", "🐟", "은줄돔과"),
    "Gerreidae": ("sea", "연안 갯바위·내만", (12.0, 30.0), (0.017, 3.00), 1, "day", "clear", "worm", "🐟", "게레치과"),
    "Sparidae": ("sea", "연안 갯바위·내만", (20.0, 72.0), (0.022, 3.01), 3, "all", "clear", "shrimp", "🐠", "도미과"),
    "Pomacentridae": ("sea", "산호초·열대 해역", (6.0, 16.0), (0.021, 3.00), 1, "day", "clear", "dough", "🐠", "자리돔과"),
    "Cichlidae": ("lake", "열대·아열대 대호", (10.0, 42.0), (0.021, 3.02), 2, "day", "clear", "worm", "🐠", "시클리드과"),
    "Mormyridae": ("river", "대하천 본류", (16.0, 62.0), (0.010, 3.00), 3, "night", "fog", "worm", "🐘", "코끼리코고기과"),
    "Polypteridae": ("river", "대하천 본류", (24.0, 72.0), (0.010, 3.02), 4, "night", "rain", "worm", "🐉", "폴립테루스과"),
    "Notopteridae": ("river", "대하천 본류", (25.0, 85.0), (0.008, 3.00), 3, "night", "fog", "lure", "⚔️", "나이프피시과"),
    "Mastacembelidae": ("river", "대하천 본류", (20.0, 65.0), (0.004, 3.00), 3, "night", "rain", "worm", "🐍", "가시장어과"),
    "Tetraodontidae": ("sea", "연안 갯바위·내만", (15.0, 52.0), (0.028, 3.00), 2, "day", "rain", "shrimp", "🐡", "참복과"),
    "Scorpaenidae": ("sea", "연안 갯바위·내만", (14.0, 42.0), (0.020, 3.02), 2, "night", "all", "shrimp", "🐠", "양볼락과"),
}

# 한국어 어종명 키워드 기반 서식지·구역·희귀도 휴리스틱 보정
RIVER_KEYWORDS = (
    "피라미", "갈겨니", "버들", "송어", "연어", "산천어", "열목어", "모래무지", "미꾸", "미꾸라지",
    "종개", "꾸구리", "돌상어", "쉬리", "어름치", "은어", "쏘가리", "꺽지", "꺽저기", "메기", "동자개",
    "꼬치동자개", "대농갱이", "퉁가리", "눈치", "누치", "강준치", "뱀장어", "칠성장어", "가아", "테트라",
    "피라냐", "피라니아", "아로와나", "코리도라스", "플레코", "로리카리아", "전기뱀장어", "숭어", "가숭어",
    "둑중개", "황복", "실뱀장어", "참마자", "돌고기", "감돌고기", "흰수마자", "줄몰개", "몰개", "모치",
    "산메기", "미유기", "드렁허리", "바벨", "마시르", "살몬", "트라우트", "차르", "그레일링",
)
LAKE_KEYWORDS = (
    "붕어", "잉어", "배스", "블루길", "빙어", "가물치", "향어", "비단잉어", "니시키고이", "초어",
    "백련어", "대두어", "송사리", "버들붕어", "구라미", "베타", "구피", "플래티", "몰리", "킬리피시",
    "시클리드", "틸라피아", "디스커스", "엔젤피시", "오스카", "파이크", "머스켈런지", "퍼치", "왈아이",
    "선피시", "크래피", "보우핀", "철갑상어", "납자루", "납줄개", "각시붕어", "치리", "금붕어", "오물",
    "피라루쿠", "나일농어", "피콕", "아처피시",
)
SEA_KEYWORDS = (
    "상어", "가오리", "홍어", "돔", "다랑어", "참치", "고등어", "삼치", "방어", "부시리", "전갱이",
    "멸치", "정어리", "청어", "꽁치", "학꽁치", "갈치", "산갈치", "아귀", "복", "복어", "쥐치",
    "놀래기", "나비고기", "자리돔", "흰동가리", "크라운", "양쥐돔", "스내퍼", "퉁돔", "바리", "다금바리",
    "우럭", "볼락", "쏨뱅이", "노래미", "광어", "넙치", "가자미", "도다리", "서대", "대구", "명태",
    "민어", "조기", "부세", "농어", "숭어", "꼬치고기", "바라쿠다", "새치", "청새치", "황새치",
    "만새기", "개복치", "해마", "실고기", "곰치", "붕장어", "갯장어", "날치", "도루묵", "꼼치",
    "베도라치", "망상어", "양태", "성대", "촉수", "고둥어", "은대구", "금눈돔", "붉평치", "실러캔스",
    "만타", "래스", "그루퍼", "엔젤피시", "트리거", "거북복", "가시복", "블레니", "고비", "쏠배감펭",
)


def has_hangul(s: Optional[str]) -> bool:
    return bool(s and re.search(r"[\uac00-\ud7a3]", s))


def sanitize_kr_name(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    # 불필요한 위키/분류 접미사 제거
    s = re.sub(r"\s*\(어류\)|\s*\(물고기\)|\s*\(생물\)", "", s)
    return s.strip()


def make_species_id(sci_name: str, existing_ids: set) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", sci_name.lower()).strip("_")
    base = f"sp_{slug}"[:48].rstrip("_")
    if base not in existing_ids:
        existing_ids.add(base)
        return base
    h = hashlib.md5(sci_name.encode("utf-8")).hexdigest()[:6]
    cand = f"{base[:40]}_{h}"
    existing_ids.add(cand)
    return cand


def map_existing_canonical_zone(habitat: str, sub_zone: str, sp_name: str) -> str:
    sz = sub_zone
    if habitat == "lake":
        if any(k in sz for k in ("심수", "빙하", "심연", "바이칼", "차가운", "깊은", "냉수")):
            return "깊은 심수층"
        if any(k in sz for k in ("아마존", "아프리카", "열대", "틸라피아", "나일")):
            return "열대·아열대 대호"
        if any(k in sz for k in ("중층", "대호", "표층", "한랭", "전역")):
            return "맑은 중층수"
        return "수초 연안"
    if habitat == "river":
        if any(k in sz for k in ("기수", "하구", "하류", "동해")):
            return "강·바다 기수역"
        if any(k in sz for k in ("상류", "계곡", "1급수", "심산", "냉수", "소용돌이")):
            return "상류 1급수 계곡"
        if any(k in sz for k in ("본류", "대하천", "열대", "고대", "콩고", "깊은 소")):
            return "대하천 본류"
        return "중류 자갈 여울"
    # sea
    if any(k in sz for k in ("심해", "1,000m", "400m", "화산")):
        return "심해·해구"
    if any(k in sz for k in ("원양", "원도권", "조경", "대한해협", "태평양")):
        return "원양·회유 해역"
    if any(k in sz for k in ("산호", "열대", "아열대", "제주")):
        return "산호초·열대 해역"
    if any(k in sz for k in ("외해", "서남해", "인공어초", "서해 뻘", "한류")):
        return "대륙붕·외해"
    return "연안 갯바위·내만"


def load_original_140() -> List[Dict[str, Any]]:
    orig: List[Dict[str, Any]] = []
    db_path = os.path.join(ROOT_DIR, "fish_species_db.json")
    source_rows: List[Dict[str, Any]] = []
    if os.path.isfile(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                source_rows = [sp for sp in loaded if not str(sp.get("id", "")).startswith("sp_")]
        except Exception:
            source_rows = []
    if len(source_rows) < 140:
        import fishing_core
        source_rows = [sp for sp in fishing_core.FISH_SPECIES_DB if not str(sp.get("id", "")).startswith("sp_")]

    for sp in source_rows:
        item = dict(sp)
        item["zone"] = item.get("zone") or map_existing_canonical_zone(
            item["habitat"], item.get("sub_zone", ""), item["name"]
        )
        orig.append(item)
    return orig


def fetch_json(url: str, timeout: int = 18) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NorosiBotFishingETL/2.0 (https://norosi.bot)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_fish_families() -> Dict[int, str]:
    """iNaturalist에서 조기어류·연골어류 과(Family) ID -> 학명 맵을 수집"""
    fam_map: Dict[int, str] = {}
    urls = []
    for root_id in (47178, 47273, 196614):  # Actinopterygii, Elasmobranchii, Chondrichthyes
        for p in range(1, 5):
            urls.append(f"https://api.inaturalist.org/v1/taxa?taxon_id={root_id}&rank=family&per_page=200&page={p}")

    def _get(u: str):
        for _ in range(2):
            try:
                return fetch_json(u, 15)
            except Exception:
                time.sleep(0.4)
        return {}

    with ThreadPoolExecutor(max_workers=4) as ex:
        for d in ex.map(_get, urls):
            for r in d.get("results", []):
                tid = r.get("id")
                name = (r.get("name") or "").strip()
                if tid and name:
                    fam_map[int(tid)] = name
    return fam_map


def collect_inat_species() -> Dict[str, Dict[str, Any]]:
    """글로벌 최다 관측 어종 + 동아시아(한국/일본/대만) 어종 수집"""
    species: Dict[str, Dict[str, Any]] = {}
    urls: List[str] = []

    # 1. Global Actinopterygii top 9,000 species
    for p in range(1, 46):
        urls.append(
            f"https://api.inaturalist.org/v1/taxa?taxon_id=47178&rank=species&locale=ko&is_active=true&per_page=200&page={p}"
        )
    # 2. Sharks & Rays (Elasmobranchii) + Chimaeras (Holocephali) + Lampreys
    for tid, max_p in ((47273, 8), (48096, 3), (49644, 3)):
        for p in range(1, max_p + 1):
            urls.append(
                f"https://api.inaturalist.org/v1/taxa?taxon_id={tid}&rank=species&locale=ko&is_active=true&per_page=200&page={p}"
            )
    # 3. Freshwater-rich orders: Cypriniformes(49238), Characiformes(53445), Siluriformes(49235), Salmoniformes(47514), Cichliformes(55469), Cyprinodontiformes(47717)
    for tid, max_p in ((49238, 8), (53445, 5), (49235, 8), (47514, 3), (55469, 6), (47717, 4)):
        for p in range(1, max_p + 1):
            urls.append(
                f"https://api.inaturalist.org/v1/taxa?taxon_id={tid}&rank=species&locale=ko&is_active=true&per_page=200&page={p}"
            )
    # 4. East Asia Focus: Korea(6891), Japan(6739), Taiwan(7887)
    for place_id, max_p in ((6891, 10), (6739, 18), (7887, 10)):
        for p in range(1, max_p + 1):
            urls.append(
                f"https://api.inaturalist.org/v1/taxa?taxon_id=47178&place_id={place_id}&rank=species&locale=ko&is_active=true&per_page=200&page={p}"
            )
            if p <= 3:
                urls.append(
                    f"https://api.inaturalist.org/v1/taxa?taxon_id=47273&place_id={place_id}&rank=species&locale=ko&is_active=true&per_page=200&page={p}"
                )

    def _safe_get(u: str):
        for attempt in range(3):
            try:
                return fetch_json(u, 15)
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return {}

    print(f"🌐 iNaturalist {len(urls)}개 페이지 병렬 수집 시작...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for d in ex.map(_safe_get, urls):
            for r in d.get("results", []):
                sci = (r.get("name") or "").strip()
                parts = sci.split()
                if len(parts) < 2 or len(parts) > 3 or "×" in sci or r.get("extinct"):
                    continue
                if sci not in species:
                    raw_ko = r.get("preferred_common_name") or ""
                    ko = sanitize_kr_name(raw_ko) if has_hangul(raw_ko) else None
                    species[sci] = {
                        "sci": sci,
                        "ko": ko,
                        "en": (r.get("english_common_name") or "").strip(),
                        "obs": int(r.get("observations_count") or 0),
                        "ancestors": [int(x) for x in (r.get("ancestor_ids") or [])],
                        "wiki": (r.get("wikipedia_url") or "").strip(),
                        "len": None,
                        "mass": None,
                        "wd_desc": "",
                        "family_sci": "",
                    }
    print(f"✅ iNaturalist 고유 활성 어종 {len(species)}종 확보 (직접 한글명: {sum(1 for v in species.values() if v['ko'])}종)", flush=True)
    return species


def collect_wikidata_family_species(fam_map: Dict[int, str], species: Dict[str, Dict[str, Any]]) -> None:
    """Wikidata 2-hop 과(Family)->속(Genus)->종(Species) SPARQL 조회로 한국어 공식 라벨이 있는 전 세계 어종 대량 발굴"""
    fam_names = sorted(set(fam_map.values()) | set(FAMILY_BIOLOGY.keys()))
    batches = [fam_names[i : i + 25] for i in range(0, len(fam_names), 25)]
    print(f"🔬 Wikidata 2-hop 과(Family) {len(fam_names)}개 ({len(batches)}배치) 한국어 명칭 어종 발굴 시작...", flush=True)

    def _query_fam_batch(batch: List[str]):
        vals = " ".join('"' + s.replace('"', "") + '"' for s in batch)
        q = f"""SELECT ?famSci ?taxon ?ko ?en ?koDesc ?len WHERE {{
  VALUES ?famSci {{ {vals} }}
  ?fam wdt:P225 ?famSci .
  ?genus wdt:P171 ?fam .
  ?item wdt:P171 ?genus .
  ?item wdt:P105 wd:Q7432 .
  ?item wdt:P225 ?taxon .
  ?item rdfs:label ?ko . FILTER(LANG(?ko) = "ko")
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item schema:description ?koDesc . FILTER(LANG(?koDesc) = "ko") }}
  OPTIONAL {{ ?item wdt:P2043 ?len . }}
}}"""
        url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
        for attempt in range(3):
            try:
                return fetch_json(url, 25).get("results", {}).get("bindings", [])
            except Exception:
                time.sleep(0.9 * (attempt + 1))
        return []

    added_new = 0
    upgraded_ko = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for rows in ex.map(_query_fam_batch, batches):
            for b in rows:
                sci = (b.get("taxon", {}).get("value") or "").strip()
                parts = sci.split()
                if len(parts) < 2 or len(parts) > 3 or "×" in sci:
                    continue
                ko_val = b.get("ko", {}).get("value", "")
                if not ko_val or not has_hangul(ko_val):
                    continue
                clean_ko = sanitize_kr_name(ko_val)
                if not clean_ko or clean_ko.lower() == sci.lower():
                    continue
                fam_sci = (b.get("famSci", {}).get("value") or "").strip()
                en_val = (b.get("en", {}).get("value") or "").strip()
                desc_val = (b.get("koDesc", {}).get("value") or "").strip()
                cm_val = None
                if "len" in b:
                    try:
                        raw_l = float(b["len"]["value"])
                        if 0.02 <= raw_l <= 14.0:
                            cm_val = round(raw_l * 100.0, 1)
                        elif 14.0 < raw_l <= 1200.0:
                            cm_val = round(raw_l, 1)
                    except Exception:
                        pass

                if sci in species:
                    rec = species[sci]
                    if not rec["ko"]:
                        rec["ko"] = clean_ko
                        upgraded_ko += 1
                    if not rec.get("family_sci") and fam_sci:
                        rec["family_sci"] = fam_sci
                    if not rec.get("en") and en_val and en_val.lower() != sci.lower():
                        rec["en"] = en_val
                    if not rec.get("wd_desc") and desc_val and has_hangul(desc_val):
                        rec["wd_desc"] = desc_val
                    if rec.get("len") is None and cm_val:
                        rec["len"] = cm_val
                else:
                    species[sci] = {
                        "sci": sci,
                        "ko": clean_ko,
                        "en": en_val if en_val.lower() != sci.lower() else "",
                        "obs": 120,
                        "ancestors": [],
                        "wiki": "",
                        "len": cm_val,
                        "mass": None,
                        "wd_desc": desc_val if has_hangul(desc_val) else "",
                        "family_sci": fam_sci,
                    }
                    added_new += 1

    print(
        f"✅ Wikidata 2-hop 과 발굴 완료: 신규 +{added_new}종, 한글명 보완 +{upgraded_ko}종 (누적 한글명 {sum(1 for v in species.values() if v['ko'])}종)",
        flush=True,
    )


def enrich_from_wikidata(species: Dict[str, Dict[str, Any]]) -> None:
    """Wikidata SPARQL 배치 조회로 한국어 공식 라벨, 한국어 설명, 최대 체장 보강"""
    scis = [k for k, v in species.items() if not v.get("ko") or v.get("len") is None]
    batches = [scis[i : i + 180] for i in range(0, len(scis), 180)]
    print(f"📚 Wikidata SPARQL {len(batches)}개 배치 한국어 명칭·체장 보강 시작...", flush=True)

    def _query_batch(batch: List[str]):
        vals = " ".join('"' + s.replace('"', "") + '"' for s in batch)
        q = f"""SELECT ?taxon ?ko ?koDesc ?len WHERE {{
  VALUES ?taxon {{ {vals} }}
  ?item wdt:P225 ?taxon .
  OPTIONAL {{ ?item rdfs:label ?ko . FILTER(LANG(?ko) = "ko") }}
  OPTIONAL {{ ?item schema:description ?koDesc . FILTER(LANG(?koDesc) = "ko") }}
  OPTIONAL {{ ?item wdt:P2043 ?len . }}
}}"""
        url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
        for attempt in range(3):
            try:
                return fetch_json(url, 22).get("results", {}).get("bindings", [])
            except Exception:
                time.sleep(0.8 * (attempt + 1))
        return []

    added_ko = 0
    len_hits = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for rows in ex.map(_query_batch, batches):
            for b in rows:
                t = b.get("taxon", {}).get("value", "")
                if t not in species:
                    continue
                rec = species[t]
                ko_val = b.get("ko", {}).get("value", "")
                if ko_val and has_hangul(ko_val):
                    clean = sanitize_kr_name(ko_val)
                    if clean and clean.lower() != t.lower():
                        if not rec["ko"]:
                            rec["ko"] = clean
                            added_ko += 1
                desc_val = b.get("koDesc", {}).get("value", "")
                if desc_val and has_hangul(desc_val) and not rec["wd_desc"]:
                    rec["wd_desc"] = desc_val.strip()
                if "len" in b and rec["len"] is None:
                    try:
                        raw_l = float(b["len"]["value"])
                        if 0.02 <= raw_l <= 14.0:
                            cm_val = raw_l * 100.0
                        elif 14.0 < raw_l <= 1200.0:
                            cm_val = raw_l
                        else:
                            cm_val = None
                        if cm_val and 2.0 <= cm_val <= 1200.0:
                            rec["len"] = round(cm_val, 1)
                            len_hits += 1
                    except Exception:
                        pass

    print(
        f"✅ Wikidata 보강 완료: +{added_ko}종 추가 (총 한글명 어종 {sum(1 for v in species.values() if v['ko'])}종 / 체장 매칭 {len_hits}건)",
        flush=True,
    )


def classify_fish_entry(
    raw: Dict[str, Any],
    fam_map: Dict[int, str],
) -> Dict[str, Any]:
    sci = raw["sci"]
    name_kr = raw["ko"]
    ancestors = raw.get("ancestors", [])

    # 1. 과(Family) 식별
    family_sci = raw.get("family_sci", "")
    for aid in reversed(ancestors):
        if aid in fam_map:
            family_sci = fam_map[aid]
            break

    bio = FAMILY_BIOLOGY.get(family_sci)
    if not bio:
        # 속(Genus) 또는 키워드 기반 폴백 추정
        genus = sci.split()[0]
        if genus in FAMILY_BIOLOGY:
            bio = FAMILY_BIOLOGY[genus]

    if bio:
        hab, zone, cm_range, (wa, wb), base_rar, atime, pweather, pbait, emoji, fam_kr = bio
        min_def, max_def = cm_range
    else:
        # 키워드 기반 서식지 추론
        text_probe = f"{name_kr} {raw.get('wd_desc', '')} {raw.get('en', '')}".lower()
        if any(k in name_kr for k in RIVER_KEYWORDS) or any(
            w in text_probe for w in ("river", "stream", "creek", "brook", "darter", "loach", "trout", "salmon", "tetra", "catfish", "민물", "하천", "계곡")
        ):
            hab = "river"
            zone = "중류 자갈 여울"
            fam_kr = f"{family_sci or '담수'}어류"
            min_def, max_def = (9.0, 32.0)
            wa, wb = (0.012, 3.02)
            base_rar = 2
            atime, pweather, pbait, emoji = ("day", "clear", "worm", "🐟")
        elif any(k in name_kr for k in LAKE_KEYWORDS) or any(
            w in text_probe for w in ("lake", "pond", "cichlid", "carp", "crucian", "bass", "sunfish", "pike", "killifish", "호수", "저수지")
        ):
            hab = "lake"
            zone = "수초 연안"
            fam_kr = f"{family_sci or '호수'}어류"
            min_def, max_def = (10.0, 38.0)
            wa, wb = (0.015, 3.02)
            base_rar = 2
            atime, pweather, pbait, emoji = ("day", "clear", "dough", "🐟")
        else:
            hab = "sea"
            # 열대/산호 vs 심해 vs 연안
            if any(w in text_probe for w in ("deep", "lantern", "angler", "grenadier", "abyss", "심해")):
                zone = "심해·해구"
                base_rar = 3
                atime, pweather, pbait, emoji = ("night", "fog", "glow", "💠")
            elif any(w in text_probe for w in ("coral", "reef", "butterfly", "damsel", "wrasse", "parrot", "tang", "clown", "산호", "열대")):
                zone = "산호초·열대 해역"
                base_rar = 2
                atime, pweather, pbait, emoji = ("day", "clear", "shrimp", "🐠")
            elif any(w in text_probe for w in ("tuna", "marlin", "pelagic", "oceanic", "shark", "상어", "원양")) and "철갑상어" not in name_kr and "돌상어" not in name_kr:
                zone = "원양·회유 해역"
                base_rar = 3
                atime, pweather, pbait, emoji = ("day", "clear", "lure", "🦈")
            else:
                zone = "연안 갯바위·내만"
                base_rar = 1
                atime, pweather, pbait, emoji = ("all", "clear", "shrimp", "🐟")
            fam_kr = f"{family_sci or '해양'}어류"
            min_def, max_def = (16.0, 52.0)
            wa, wb = (0.015, 3.01)

    # 세부 한국어 키워드로 서식지 미세 보정 (담수 철갑상어·주걱철갑상어·돌상어는 제외)
    is_freshwater_sturgeon_or_loach = (
        family_sci in ("Acipenseridae", "Polyodontidae", "Gobionidae")
        or any(k in name_kr for k in ("철갑상어", "주걱상어", "돌상어"))
    )
    if "심해" in name_kr:
        hab, zone = "sea", "심해·해구"
        base_rar = max(base_rar, 3)
        pbait = "glow"
    elif "산호" in name_kr or "나비" in name_kr or "흰동가리" in name_kr:
        if hab == "sea":
            zone = "산호초·열대 해역"
            emoji = "🐠"
    elif (not is_freshwater_sturgeon_or_loach) and ("상어" in name_kr or "가오리" in name_kr or "새치" in name_kr):
        hab = "sea"
        if "민물" in name_kr or "담수" in name_kr or "강" in name_kr:
            hab, zone = "river", "대하천 본류"

    # 서식지-세부구역 정합성 강제 가드
    canonical_zones = {
        "lake": ("수초 연안", "맑은 중층수", "깊은 심수층", "열대·아열대 대호"),
        "river": ("상류 1급수 계곡", "중류 자갈 여울", "대하천 본류", "강·바다 기수역"),
        "sea": ("연안 갯바위·내만", "산호초·열대 해역", "대륙붕·외해", "원양·회유 해역", "심해·해구"),
    }
    if zone not in canonical_zones.get(hab, ()):
        zone = canonical_zones[hab][0]

    # 개체별 변동 시드 (결정론적 재현성)
    seed_int = int(hashlib.md5(sci.encode("utf-8")).hexdigest()[:8], 16)

    # 체장 계산 (Wikidata 실측 P2043이 있으면 우선 반영)
    if raw.get("len"):
        max_cm = round(float(raw["len"]), 1)
        min_cm = round(max(2.0, max_cm * 0.36), 1)
    else:
        spread_f = 0.80 + ((seed_int % 45) / 100.0)
        max_cm = round(max(4.0, max_def * spread_f), 1)
        min_cm = round(max(2.0, min(max_cm * 0.55, min_def * (0.85 + (seed_int % 25) / 100.0))), 1)
    if min_cm >= max_cm:
        max_cm = round(min_cm * 2.2, 1)

    # 희귀도 산출 (과 기본 희귀도 + 관측 빈도(obs) + 대형 어종 보정)
    obs = raw.get("obs", 100)
    rarity = base_rar
    if max_cm >= 180.0:
        rarity = max(rarity, 4)
    if max_cm >= 300.0 or (obs < 40 and max_cm >= 110.0):
        rarity = 5
    elif obs < 60 and rarity <= 2:
        rarity = min(4, rarity + 1)
    elif obs > 5000 and rarity == 2 and max_cm < 35.0:
        rarity = 1
    rarity = max(1, min(5, rarity))

    # 시간대/날씨 다양성 미세 분산 (모두 동일 조건에 몰리지 않게)
    if atime == "all" and (seed_int % 5 == 0):
        atime = "night" if hab != "lake" else "day"
    if rarity >= 4 and pbait not in ("glow", "golden", "lure", "shrimp"):
        pbait = "golden" if rarity == 5 else "lure"

    # 판매 골드 산정 (성급별 밸런스)
    gold_base_by_r = {1: 24, 2: 72, 3: 195, 4: 620, 5: 1900}
    size_bonus_gold = min(650, int(max_cm * 1.4))
    base_gold = int(gold_base_by_r[rarity] + size_bonus_gold * (0.25 + rarity * 0.12))

    # 설명 문구 생성
    hab_kr = {"lake": "호수·저수지", "river": "하천·강 유역", "sea": "바다"}[hab]
    en_suffix = f" ({raw['en']})" if raw.get("en") else ""
    wd_d = raw.get("wd_desc", "").strip()
    if wd_d and len(wd_d) >= 12 and "종" not in wd_d[:4]:
        desc = f"[{fam_kr}] {hab_kr} '{zone}' 서식 실제 어종{en_suffix}. {wd_d}"
    else:
        desc = f"[{fam_kr}] {hab_kr}의 '{zone}' 권역에 서식하는 공개 실측 어종{en_suffix}. 최대 약 {max_cm:.0f}cm까지 자랍니다."
    if len(desc) > 135:
        desc = desc[:132] + "..."

    return {
        "name": name_kr,
        "scientific_name": sci,
        "habitat": hab,
        "zone": zone,
        "sub_zone": zone,
        "rarity": rarity,
        "min_cm": min_cm,
        "max_cm": max_cm,
        "weight_a": round(wa, 5),
        "weight_b": round(wb, 2),
        "base_gold": base_gold,
        "active_time": atime,
        "prefer_weather": pweather,
        "prefer_bait": pbait,
        "emoji": emoji,
        "desc": desc,
        "source": "public_bio_db",
    }


def main():
    orig_list = load_original_140()
    print(f"📌 기존 보존 어종: {len(orig_list)}종 로드 완료", flush=True)

    existing_ids = {sp["id"] for sp in orig_list}
    existing_scis = {sp["scientific_name"].lower().split(" (")[0].strip() for sp in orig_list}
    existing_names = {sp["name"].strip() for sp in orig_list}

    fam_map = fetch_all_fish_families()
    print(f"🧬 어류 과(Family) 매핑 테이블 {len(fam_map)}개 구축 완료", flush=True)

    raw_species = collect_inat_species()
    collect_wikidata_family_species(fam_map, raw_species)
    enrich_from_wikidata(raw_species)

    # 정렬: 관측수 높은 순(인기/대표 어종 우선) + 한글명 보유 필터
    candidates = [v for v in raw_species.values() if v.get("ko")]
    candidates.sort(key=lambda x: -x.get("obs", 0))

    new_entries: List[Dict[str, Any]] = []
    for raw in candidates:
        sci_l = raw["sci"].lower().strip()
        kr_name = sanitize_kr_name(raw["ko"])
        if not kr_name or len(kr_name) < 2 or len(kr_name) > 36:
            continue
        # 영문자만 있거나 숫자/기호 위주 노이즈 제외
        if not has_hangul(kr_name):
            continue
        if sci_l in existing_scis:
            continue

        # 한글명 충돌 시 학명 종소명 표기로 명확히 구분 (완벽한 1:1 어종명 보장)
        if kr_name in existing_names:
            epithet = raw["sci"].split()[-1]
            kr_name = f"{kr_name} ({epithet})"
            if kr_name in existing_names:
                continue

        raw_copy = dict(raw)
        raw_copy["ko"] = kr_name
        entry = classify_fish_entry(raw_copy, fam_map)
        entry["id"] = make_species_id(raw["sci"], existing_ids)
        existing_scis.add(sci_l)
        existing_names.add(kr_name)
        new_entries.append(entry)

    all_species = orig_list + new_entries

    # 정렬: (habitat, rarity, min_cm, name)
    hab_order = {"lake": 0, "river": 1, "sea": 2}
    all_species.sort(key=lambda x: (hab_order.get(x["habitat"], 9), x["rarity"], x["min_cm"], x["name"]))

    out_paths = [
        os.path.join(ROOT_DIR, "fish_species_db.json"),
        os.path.join(ROOT_DIR, "public", "data", "fish_species_db.json"),
        os.path.join(ROOT_DIR, "public", "bot_files", "fish_species_db.json"),
    ]
    payload = json.dumps(all_species, ensure_ascii=False, separators=(",", ":"))
    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(payload)

    # 요약 출력
    by_h = {h: sum(1 for x in all_species if x["habitat"] == h) for h in ("lake", "river", "sea")}
    by_r = {r: sum(1 for x in all_species if x["rarity"] == r) for r in range(1, 6)}
    file_kb = os.path.getsize(out_paths[0]) / 1024.0
    print("=" * 60)
    print(f"🎉 최종 어종 데이터베이스 생성 완료: 총 {len(all_species)}종 ({file_kb:.1f} KB)")
    print(f"   • 서식지별: 호수 {by_h['lake']}종 · 강 {by_h['river']}종 · 바다 {by_h['sea']}종")
    print(f"   • 성급별: ★1({by_r[1]}) · ★2({by_r[2]}) · ★3({by_r[3]}) · ★4({by_r[4]}) · ★5({by_r[5]})")
    print("   • 동기화 경로: fish_species_db.json · public/data/fish_species_db.json · public/bot_files/fish_species_db.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
