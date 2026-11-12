"""
cogs/help.py - norosi bot help: 전체 55개 슬래시 명령어 통합 도움말 & 가독성 최적화 가이드
"""

import math
import datetime
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Any
import core

TERMS_URL = "https://app.notion.com/p/40f0518d0603809ea4bde601d93fbffb?source=copy_link"
PRIVACY_URL = "https://app.notion.com/p/40f0518d06038048b0c6ea1052ce23e7?source=copy_link"
SUPPORT_SERVER_URL = "https://discord.gg/6utpaS7s52"

# ==========================================
# 전체 55개 슬래시 명령어 완벽 카탈로그 (7대 카테고리 분류)
# ==========================================
COMMAND_CATALOG: List[Dict[str, Any]] = [
    # 1. 🎮 출석 & 카드/가챠 (18종)
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/출석체크",
        "desc": "자정(00:00) 기준 각 서버별 하루 1회 출석 도장 및 크리스탈(100~2000💎) 획득",
        "params": "없음",
        "example": "/출석체크",
        "source": "cogs/dday.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/출석달력",
        "desc": "이번 달 출석 캘린더 및 7/14/21/28일 개근 보상 마일스톤 현황 조회",
        "params": "유저: [@유저(선택)]",
        "example": "/출석달력",
        "source": "cogs/dday.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/출석랭킹",
        "desc": "현재 서버 또는 전체 서버의 출석 순위(누적 출석일 / 연속 출석일)",
        "params": "범위: [서버/전체] 기준: [누적/연속]",
        "example": "/출석랭킹 범위:서버 기준:연속",
        "source": "cogs/dday.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/프로세카뽑기",
        "desc": "프로세카 한국 서버 캐릭터 뽑기 (1회 단차 또는 ★3 이상 확정 10회 연차)",
        "params": "횟수: [1회 뽑기(단차) / 10회 뽑기(10연차)]",
        "example": "/프로세카뽑기 횟수:10회 뽑기",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/내캐릭터",
        "desc": "내가 뽑은 카드 보관함 검색, 일러스트(각성 전·후), 🔒잠금, 중복 변환 관리",
        "params": "유저: [@유저(선택)] 검색어: [캐릭터명(선택)]",
        "example": "/내캐릭터 검색어:카나데",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/카드도감",
        "desc": "캐릭터별 수집률(%)과 아직 획득하지 못한 미보유 카드 탭별 확인",
        "params": "유저: [@유저(선택)] 초기탭: [수집률/미보유카드/보유카드(선택)]",
        "example": "/카드도감 초기탭:미보유 카드",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/카드강화",
        "desc": "크리스탈을 소모하여 보유 카드의 레벨과 종합력 상승 (MAX 달성 시 보너스 💎 지급)",
        "params": "카드선택: [보유카드] 강화단계: [+1레벨/+10레벨/MAX]",
        "example": "/카드강화 카드선택:101 강화단계:MAX",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/중복카드변환",
        "desc": "2장 이상 중복 보유 카드(원본 및 🔒잠금 제외)를 성급별 크리스탈로 일괄 환전",
        "params": "없음",
        "example": "/중복카드변환",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/카드교환",
        "desc": "크리스탈 100개를 사용하여 다른 유저와 보유 카드를 1:1 실시간 교환 (카드 미선택 시 드롭다운 장터 스튜디오 오픈)",
        "params": "상대유저: [@유저] 내카드: [카드(선택)] 상대카드: [카드(선택)]",
        "example": "/카드교환 상대유저:@친구",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/카드선물",
        "desc": "크리스탈 50개를 사용하여 나의 소중한 파트너에게 보유 카드 선물",
        "params": "내카드: [카드] 메시지: [축하메시지(선택)]",
        "example": "/카드선물 내카드:101 메시지:선물이야!",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/마이세카이",
        "desc": "나만의 미니 룸 테마와 세카이 가구를 꾸미고 매일 출석체크 추가 크리스탈 이자(패시브 보너스) 획득",
        "params": "유저: [@유저(선택, 타인 방 구경)]",
        "example": "/마이세카이",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/덱편성",
        "desc": "보유 카드 중 최대 5장을 골라 리더와 멤버로 나만의 5인 유닛 덱 편성 및 총 종합력 계산",
        "params": "리더: [카드] 멤버2~5: [카드 4장(선택)]",
        "example": "/덱편성 리더:101 멤버2:102 멤버3:103 멤버4:104 멤버5:105",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/오시설정",
        "desc": "내 프로필 카드 및 @노로시 멘션 시 대표로 표시될 최애(오시) 캐릭터 설정",
        "params": "캐릭터: [26인 캐릭터 선택]",
        "example": "/오시설정 캐릭터:요이사키 카나데",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/내프로필",
        "desc": "오시 일러스트, 마이세카이, 5인 덱 종합력, 출석 일수, 크리스탈, 은하수 잔디, 가챠 통계 종합 조회",
        "params": "유저: [@유저(선택)]",
        "example": "/내프로필",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/가챠랭킹",
        "desc": "현재 서버의 도감 수집률 TOP 5, ★4·생일 최다 보유자, 누적 뽑기 순위",
        "params": "없음",
        "example": "/가챠랭킹",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/프로세카확률목록",
        "desc": "한국 서버 모든 캐릭터(한정 포함) 텍스트 명단 및 성급별 상세 확률 조회",
        "params": "없음",
        "example": "/프로세카확률목록",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/픽업설정",
        "desc": "[봇 관리자] 프로세카 뽑기의 픽업 유닛, 픽업 캐릭터, 한정 카드 포함 여부 설정",
        "params": "유닛: [선택] 캐릭터: [선택] 한정포함: [예/아니오]",
        "example": "/픽업설정 유닛:25시 캐릭터:카나데 한정포함:True",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 카드/가챠",
        "name": "/서버캐릭터초기화",
        "desc": "[서버 관리자] 현재 디스코드 서버 유저들의 프로세카 캐릭터 보관함 초기화",
        "params": "없음",
        "example": "/서버캐릭터초기화",
        "source": "cogs/gacha.py",
    },

    # 2. 🎲 미니게임 & 생활 유틸리티 (4종 - NEW!)
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 유틸",
        "name": "/끝말잇기",
        "desc": "표준 두음법칙이 완벽 적용되는 실시간 끝말잇기 배틀! (봇 1:1 또는 유저 대결, 승리 시 +150💎)",
        "params": "상대유저: [@멤버(선택)] 시작단어: [첫단어(선택)]",
        "example": "/끝말잇기 시작단어:세카이",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 유틸",
        "name": "/러시안룰렛",
        "desc": "6연발 리볼버에 실탄을 장전하고 방아쇠를 당겨 누적 상금(💎)을 획득하는 스릴 생존 게임",
        "params": "실탄수: [1~5발(선택)] 참가비: [0~500💎(선택)]",
        "example": "/러시안룰렛 실탄수:1 참가비:50",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 유틸",
        "name": "/날씨",
        "desc": "기상청(KMA)/ECMWF 실시간 관측 기온, 체감온도, 미세먼지(PM10/PM2.5), 시간별 강수확률 및 우산 가이드",
        "params": "지역: [도시/시/군/구 이름]",
        "example": "/날씨 지역:서울",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 유틸",
        "name": "/알림예약",
        "desc": "'30분 뒤', '1시간 후', '15:30' 등 자연어로 예약하면 정확한 시각에 DM 및 채널 멘션으로 개인 알림 발송",
        "params": "시간: [자연어/시각] 내용: [알림메모] 방식: [DM+채널/채널만/DM만]",
        "example": "/알림예약 시간:30분 뒤 내용:라면 불 끄기",
        "source": "cogs/dday.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 파티 모집 & 게임",
        "name": "/모집",
        "desc": "프로세카 협력 라이브뿐 아니라 롤, 발로란트, 스팀, 배그 등 모든 게임 파티원 모집 (선택 목록 없이 직접 작성 팝업 모달 지원, 인원수 2~20명, 목표 자유 작성, 룸코드, 실시간 참가/취소, 풀방 자동 멘션)",
        "params": "(옵션 없이 실행 시 직접 작성 모달 팝업) 또는 게임: [직접작성] 인원수: [2~20명] 목표: [직접작성] 방번호: [선택] 시간: [선택] 메모: [선택]",
        "example": "/모집 (작성 모달 열기) 또는 /모집 게임:프로세카 인원수:5 목표:치어풀 파밍",
        "source": "cogs/stats.py",
    },

    # 3. 📊 서버/유저 통계 & 상태 (3종)
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계",
        "name": "/유저정보",
        "desc": "멤버의 디스코드 가입일, 서버 입장 순번(#N번째), 보유 역할, 부스트, 출석/크리스탈/채팅량 상세 분석",
        "params": "유저: [@멤버(선택, 미지정 시 본인)]",
        "example": "/유저정보 유저:@친구",
        "source": "cogs/stats.py",
    },
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계",
        "name": "/서버통계",
        "desc": "서버의 실제 일일/주간 채팅량, Top3 활성 채널, 실시간 음성 통화 인원, 출석률 및 시간대별 분포",
        "params": "기간: [일간/주간] 상세보기: [요약/상세]",
        "example": "/서버통계 기간:일간 상세보기:summary",
        "source": "cogs/stats.py",
    },
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계 & 건의",
        "name": "/건의",
        "desc": "봇 개발진/운영진에게 익명 또는 계정 공개로 건의 및 피드백 접수 (이미지/미디어 첨부 지원, 약관 준수)",
        "params": "유형: [익명/계정공개] 제목: [한줄요약(선택)] 내용: [상세내용(선택)] 첨부파일: [스크린샷/이미지(선택)]",
        "example": "/건의 유형:anonymous 제목:버그제보",
        "source": "cogs/stats.py",
    },
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계 & 건의",
        "name": "/봇상태",
        "desc": "[서버 관리자 전용] 봇 호스트 시스템 리소스(RAM RSS, CPU 로드, 디스크 용량, 핑, 업타임) 실시간 확인",
        "params": "없음",
        "example": "/봇상태",
        "source": "cogs/stats.py",
    },

    # 4. 📅 D-Day & 생일 & 라이프 (14종)
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/생일등록",
        "desc": "내 생일을 등록해 당일 자정 축하 알림과 +500💎 보너스를 받고, 다가오는 서버 멤버 생일 전광판 확인",
        "params": "동작: [등록/전광판/삭제] 월: [1~12] 일: [1~31] 메모: [생일소원]",
        "example": "/생일등록 동작:register 월:2 일:10 메모:축하해주세요!",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/디데이목록",
        "desc": "등록된 모든 D-Day 일정의 진행 상황을 은하수 잔디 막대 그래프로 확인",
        "params": "없음",
        "example": "/디데이목록",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/디데이추가",
        "desc": "새 D-Day 일정을 추가하고 선택한 카테고리에 전광판 채널 자동 생성",
        "params": "이름: [제목] 날짜: [YYYY-MM-DD] 카테고리: [채널위치(선택)] 이모지: [아이콘(선택)] 시작일: [시작일(선택)] 매년반복: [True/False(선택)] 채널생성: [True/False(선택)]",
        "example": "/디데이추가 이름:새학기 날짜:2026-03-02",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/전광판설정",
        "desc": "특정 D-Day 전광판 채널의 이모지, 날짜, 카테고리를 변경하고 즉시 반영",
        "params": "이름: [디데이이름] 날짜: [YYYY-MM-DD] 카테고리: [위치] 이모지: [아이콘]",
        "example": "/전광판설정 이름:기말고사 날짜:2026-12-10",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/비밀디데이",
        "desc": "나만 볼 수 있는 비밀 D-Day 및 타임캡슐(목표일 오전 9시 개인 DM 전송) 관리",
        "params": "동작: [비밀보드/추가/목록/삭제(선택)] 이름: [제목(선택)] 날짜: [날짜(선택)] 타임캡슐메시지: [메모(선택)]",
        "example": "/비밀디데이 동작:추가 이름:자격증시험 날짜:2026-11-25",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/파트너",
        "desc": "연인·친구와 파트너를 맺어 공동 D-Day와 둘만의 공유 음악 보관함 관리",
        "params": "동작: [보드열기/신청/공동디데이추가/삭제/공유음악/해제(선택)] 유저: [@파트너(신청시)] 이름: [일정명(디데이시)] 날짜: [날짜(디데이시)]",
        "example": "/파트너 동작:기념일추가 이름:100일 날짜:2026-12-15",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/집중모드",
        "desc": "뽀모도로 스터디 타이머 (집중 시 음성 자동 음소거, 휴식 시 해제 및 힐링 음악)",
        "params": "동작: [시작/중지] 집중시간: [분] 휴식시간: [분] 세트수: [횟수] 음성채널: [#음성(선택)]",
        "example": "/집중모드 동작:시작 집중시간:25 휴식시간:5 세트수:4",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/하드코어스터디",
        "desc": "자격증/코딩 전용 50분 집중/10분 휴식 음성 안내 사이클 및 은하수 보라잔디(🟪)와 대량 크리스탈 획득",
        "params": "동작: [시작/중지/현황] 목표: [과목/내용] 목표시간: [50/100/150/200/250분] 음성채널: [#채널(선택)]",
        "example": "/하드코어스터디 동작:시작 목표:정보처리기능사 실기 목표시간:100",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/지나간디데이",
        "desc": "목표일이 지나 추억 보관소로 이동된 지난 D-Day 일정들을 모아보기",
        "params": "없음",
        "example": "/지나간디데이",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/디데이삭제",
        "desc": "드롭다운 메뉴에서 D-Day를 선택해 삭제 (생성된 음성 전광판 채널도 함께 삭제)",
        "params": "없음",
        "example": "/디데이삭제",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/오늘목표",
        "desc": "오늘의 할 일(To-Do) 목록을 관리하고 최근 7일간의 은하수 잔디(🌌🌠🌑) 달성",
        "params": "새목표: [할일내용(선택)]",
        "example": "/오늘목표 새목표:프로세카 5판 플레이",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/미래시",
        "desc": "프로세카 한국 서버의 다가오는 이벤트 미래시 일정과 상세 타임라인 카드 확인",
        "params": "년도: [2026] 월: [1~12월]",
        "example": "/미래시 년도:2026 월:11",
        "source": "cogs/gacha.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/이벤트",
        "desc": "프로세카 한국 서버(KR) 또는 일본 서버(JP)의 실시간 진행 중인 이벤트/가챠 배너",
        "params": "서버: [한국서버(KR)/일본서버(JP)]",
        "example": "/이벤트 서버:한국서버(KR)",
        "source": "cogs/gacha.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/알림설정",
        "desc": "매일 오전 9시 D-Day 알림을 받을 텍스트 채널과 디데이 기본 카테고리 설정",
        "params": "알림채널: [#채널] 기본카테고리: [카테고리]",
        "example": "/알림설정 알림채널:#디데이알림",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/데이터초기화",
        "desc": "[서버 관리자] 서버의 모든 D-Day(전광판 채널 포함) 및 설정을 초기화",
        "params": "없음",
        "example": "/데이터초기화",
        "source": "cogs/dday.py",
    },

    # 5. 💬 AI 세카이 캐릭터 대화 (2종)
    {
        "category": "ai",
        "cat_label": "💬 AI 세카이 대화",
        "name": "/인공지능대화",
        "desc": "구글 Gemini AI로 프로세카 캐릭터(카나데, 미쿠 등)와 실시간 1:1 대화",
        "params": "메시지: [전할말] 캐릭터: [선택]",
        "example": "/인공지능대화 메시지:안녕! 캐릭터:kanade",
        "source": "cogs/ai.py",
    },
    {
        "category": "ai",
        "cat_label": "💬 AI 세카이 대화",
        "name": "/인공지능캐릭터설정",
        "desc": "기본 대화 캐릭터 지정 또는 나만의 맞춤 프롬프트(말투/성격/관계성) 설정",
        "params": "기본캐릭터: [카나데/미쿠/미즈키...]",
        "example": "/인공지능캐릭터설정 기본캐릭터:kanade",
        "source": "cogs/ai.py",
    },

    # 6. 🎵 음악 & 플레이리스트 (5종)
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플레이리스트",
        "desc": "유튜브·스포티파이·사운드클라우드 중 원하는 플랫폼으로 플레이리스트를 만들고, 음성채널에서 1번 곡부터 순번대로 자동재생(리모컨·반복·볼륨·취침타이머·순번변경) 및 채널 공유",
        "params": "동작: [스튜디오/음성자동재생/음성리모컨/음성정지/곡추가/새플리/공유(선택)] 플랫폼: [유튜브/스포티파이/사운드클라우드(선택)] 플리선택: [내플리(선택)] 곡제목또는링크: [곡명/URL(선택)] 아티스트: [가수(선택)] 유저: [@유저(선택)]",
        "example": "/플레이리스트 동작:음성채널에서 플리 1번 곡부터 순번대로 자동재생 시작",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리재생",
        "desc": "내 음성채널에서 플레이리스트를 1번 곡부터 순번대로 즉시 자동재생 시작 (텍스트 `!플리재생 [순번]` 지원)",
        "params": "플리선택: [플레이리스트(선택)] 시작순번: [숫자(기본: 1)] 유저: [@유저(선택)]",
        "example": "/플리재생 시작순번:1",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리곡추가",
        "desc": "내 플레이리스트에 곡(제목 또는 유튜브·스포티파이·사클 링크)을 빠르게 추가 (중복 방지 필터링, 텍스트 `!플리추가` 지원)",
        "params": "곡: [제목/링크] 아티스트: [가수(선택)] 플리선택: [플레이리스트(선택)] 중복허용: [참/거짓(기본: 거짓)]",
        "example": "/플리곡추가 곡:NewJeans Hype Boy",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리목록",
        "desc": "내(또는 특정 유저의) 모든 플레이리스트 목록과 수록곡 현황 조회 (텍스트 `!플리목록` 지원)",
        "params": "유저: [@유저(선택)]",
        "example": "/플리목록",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리가져오기",
        "desc": "외부 유튜브·스포티파이·사운드클라우드 플레이리스트 링크를 통째로 나만의 플레이리스트로 변환 (텍스트 `!플리가져오기` 지원)",
        "params": "링크: [URL] 새플리이름: [이름(선택)] 기존플리선택: [담을플리(선택)]",
        "example": "/플리가져오기 링크:https://www.youtube.com/playlist?list=...",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리곡삭제",
        "desc": "내 플레이리스트에서 원하는 곡을 선택하거나 번호(예: 3 / 1,4,7 / 10-15) 또는 제목으로 삭제 (텍스트 `!플리삭제` 지원)",
        "params": "곡: [곡선택/번호/제목(선택)] 플리선택: [플레이리스트(선택)]",
        "example": "/플리곡삭제 곡:3",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/오디오테스트",
        "desc": "음성채널에 접속하여 5초간 선명한 펄스 비프음(A5 880Hz)을 송출하며 DAVE E2EE 및 디스코드 클라이언트 음향 자가진단 (텍스트 `!오디오테스트` 즉시 지원)",
        "params": "없음",
        "example": "/오디오테스트",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/헤드셋",
        "desc": "봇의 헤드셋 끄기(청각 차단 / deafen) 상태를 실시간 제어 (음악 봇 공식 권장 사양 지원, 텍스트 `!헤드셋` 즉시 지원)",
        "params": "모드: [토글 / 끄기(청각차단 On) / 켜기(청각차단 Off)(선택)]",
        "example": "/헤드셋 모드:끄기",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/배속",
        "desc": "음성채널 플레이리스트 재생 속도(배속)를 0.5x~2.0x 조절 (기본: 1.0x, 리모컨 버튼 및 텍스트 `!배속` 지원)",
        "params": "속도: [0.5x ~ 2.0x(선택, 기본: 1.0x)]",
        "example": "/배속 속도:1.25",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/음악지금추천",
        "desc": "현재 시간 및 감성에 어울리는 프로세카/보컬로이드 노래를 즉시 1곡 추천 (내 플레이리스트 원클릭 담기 지원)",
        "params": "없음",
        "example": "/음악지금추천",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/음악알림추가",
        "desc": "원하는 시간(HH:MM)과 채널을 등록해 맞춤형 정기 자동 음악 알람 수신",
        "params": "동작: [타이머보드/추가/목록/삭제(선택)] 시간: [HH:MM] 채널: [#채널(선택)] 이름: [제목(선택)] 장르: [장르(선택)] 삭제할알림: [선택(삭제시)]",
        "example": "/음악알림추가 동작:추가 시간:22:30 이름:수면음악",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/내음악보관함",
        "desc": "추천 음악에서 하트(❤️)를 눌러 보관함에 담은 애청곡 목록 조회 및 셔플 듣기",
        "params": "없음",
        "example": "/내음악보관함",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/음악추천설정",
        "desc": "매일 오전 7시 모닝 음악 추천을 받을 텍스트 채널과 장르/플랫폼 설정",
        "params": "채널: [#채널] 플랫폼: [유튜브/스포티파이/사운드클라우드/랜덤] 장르: [장르(선택)] 아티스트: [가수(선택)] 플레이리스트링크: [URL(선택)]",
        "example": "/음악추천설정 채널:#음악추천",
        "source": "cogs/music.py",
    },

    # 7. ⚙️ 봇 관리 & 감사 로그 (7종)
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 마스터 대시보드",
        "name": "/대시보드",
        "desc": "norosi 봇의 모든 7대 카테고리 기능(가챠, 일정, 음악, 역할, 게임, 통계)을 탭으로 넘나드는 올인원 마스터 대시보드",
        "params": "탭: [홈/가챠/일정/음악/역할/게임/통계(선택)]",
        "example": "/대시보드",
        "source": "cogs/dashboard.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 마스터 대시보드",
        "name": "/메뉴",
        "desc": "명령어 타이핑 없이 버튼 하나로 모든 봇 기능을 1초 만에 실행하는 슈퍼 대시보드 리모컨",
        "params": "없음",
        "example": "/메뉴",
        "source": "cogs/dashboard.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 감사",
        "name": "/로그채널설정",
        "desc": "[서버 관리자] 7대 카테고리(메시지 삭제/수정, 멤버 입퇴장 등) 실시간 감사 로그 설정",
        "params": "채널: [#채널] 상태: [활성화/비활성화]",
        "example": "/로그채널설정 채널:#서버-로그 상태:활성화",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 감사",
        "name": "/메시지삭제",
        "desc": "[서버 관리자] 채널 메시지를 조건별(유저, 봇, 미디어, 키워드)로 최대 100개 간편 청소",
        "params": "개수: [1~100] 유저: [@유저] 봇만: [True/False] 미디어만: [True/False] 키워드: [단어]",
        "example": "/메시지삭제 개수:50 봇만:True",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 감사·백업",
        "name": "/서버백업",
        "desc": "[봇 소유자 전용] 현재 서버 채널/역할/카테고리 구조 또는 전체 봇 DB를 JSON 파일로 안전 백업",
        "params": "모드: [현재서버구조/전체DB]",
        "example": "/서버백업 모드:guild",
        "source": "cogs/stats.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 공지",
        "name": "/공지발송",
        "desc": "[서버 관리자 전용] 추천 템플릿(점검·이벤트·수칙·보상), 6대 테마 컬러, 원클릭 멘션 전환, 실시간 내용 수정 및 사전 검수를 지원하는 공지 발송 스튜디오",
        "params": "채널/중요도/멘션/테마색상/제목/내용/배너이미지 (모두 선택 사항, 미입력 시 스튜디오 자동 실행)",
        "example": "/공지발송",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 멤버 조회",
        "name": "/비활성유저조회",
        "desc": "[서버 관리자 전용] 지정 기준일(7~90일) 동안 출석/채팅/프로필 활동이 없는 유령/비활성 멤버 조회 및 활동률 바, TXT 명단 다운로드",
        "params": "기준일수: [7일/14일/30일/60일/90일(선택, 기본: 30일)]",
        "example": "/비활성유저조회 기준일수:30",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 배포 알림",
        "name": "/깃허브연동 (또는 /깃허브알림)",
        "desc": "현재 채널 또는 지정한 채널에 GitHub 푸시 및 Actions 배포 알림을 즉시 연동 및 Webhook 주소 발급",
        "params": "채널: [#채널(선택, 미입력 시 현재 채널)] 역할멘션: [@역할(선택)] 연동해제: [True/False(선택)]",
        "example": "/깃허브연동 채널:#공지-업데이트",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 역할",
        "name": "/반응역할",
        "desc": "[서버 관리자 전용] 이모지 반응 역할 제작, 기존 메시지 연결, 현황 조회 및 삭제 종합 스튜디오",
        "params": "없음 (스튜디오 패널 자동 실행)",
        "example": "/반응역할",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 역할",
        "name": "/반응역할생성",
        "desc": "[서버 관리자 전용] 지정 채널에 새 반응역할 안내 패널 발행 (이모지 자동 리액션 및 하이브리드 버튼 제공)",
        "params": "채널: [#채널] 제목: [패널제목] 역할1: [@역할] 이모지1: [이모지] ...",
        "example": "/반응역할생성 채널:#역할선택 제목:알림역할선택 역할1:@공지알림 이모지1:📢",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 역할",
        "name": "/반응역할목록",
        "desc": "[서버 관리자 전용] 현재 서버에 등록된 반응역할 전체 목록 조회 및 원클릭 등록 해제",
        "params": "없음",
        "example": "/반응역할목록",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 역할",
        "name": "/반응역할삭제",
        "desc": "[서버 관리자 전용] 메시지 링크 또는 ID를 지정하여 반응역할 바인딩 해제",
        "params": "메시지링크_또는_id: [메시지링크 또는 ID]",
        "example": "/반응역할삭제 메시지링크_또는_id:https://discord.com/channels/...",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 역할",
        "name": "/역할버튼제작",
        "desc": "[서버 관리자 전용] 팝업 모달창에서 제목, 본문, 버튼 이름과 이모지를 직접 작성하여 역할 버튼 패널 발행",
        "params": "채널: [#채널(선택)]",
        "example": "/역할버튼제작 채널:#주민등록",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 역할",
        "name": "/역할버튼생성",
        "desc": "[서버 관리자 전용] 제목, 본문, 버튼 이름과 이모지를 직접 옵션으로 지정하여 깔끔한 역할 버튼 패널 즉시 발행",
        "params": "제목: [제목] 본문: [본문내용] 역할: [@역할] 버튼이름: [이름] 버튼이모지: [이모지] ...",
        "example": "/역할버튼생성 제목:어두운세상의주민되기 본문:아래버튼을눌러주세요! 역할:@주민 버튼이름:[ 이용자 ] 버튼이모지:🌑",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 봇 관리 & 안내",
        "name": "/도움말",
        "desc": "전체 69개 슬래시 명령어의 카테고리별 상세 가이드 및 대화형 페이지별 열람",
        "params": "category: [카테고리(선택)] search: [검색어(선택)]",
        "example": "/도움말 category:admin search:반응역할",
        "source": "cogs/help.py",
    },
]

CATEGORY_META = [
    ("cards", "🎮 출석 & 카드/가챠 (18종 · 4페이지)", "출석체크, 프로세카 뽑기, 마이세카이, 카드교환, 카드강화, 덱편성 등"),
    ("dday", "📅 D-Day & 생일 & 라이프 (14종 · 3페이지)", "멤버 생일 전광판, 공용/비밀 D-Day, 파트너, 미래시, 뽀모도로 집중모드 등"),
    ("admin", "⚙️ 봇 관리 & 마스터 대시보드 (14종 · 3페이지)", "올인원 /대시보드, /메뉴, 반응역할(/반응역할, /역할버튼제작), 공지발송 등"),
    ("games", "🎲 미니게임 & 파티 모집 (5종 · 1페이지)", "파티원 모집, 끝말잇기(두음법칙), 러시안룰렛, 초정밀 실시간 날씨, 스마트 알림예약"),
    ("stats", "📊 서버/유저 통계 & 건의 (4종 · 1페이지)", "멤버 상세 유저정보, 실시간 서버통계 보드, 호스트 봇상태, 익명/공개 건의"),
    ("music", "🎵 음악 & 플레이리스트 (12종 · 3페이지)", "나만의 음악 플레이리스트 제작·공유(유튜브/스포티파이/사클), 음성 순차재생, 플리재생/추가/삭제, 오디오테스트, 헤드셋제어"),
    ("ai", "💬 AI 세카이 대화 (2종 · 1페이지)", "구글 Gemini AI 기반 프로세카 캐릭터 대화 및 맞춤 페르소나"),
]

CATEGORY_DROPDOWN_OPTIONS = [
    ("all", "🌟 전체 명령어 한눈에 보기 (69종 요약판)", "7대 카테고리 요약 보드 (다음 버튼으로 14페이지 상세)", "🌐"),
    ("cards", "🎮 출석 & 카드/가챠 (18종 · 4페이지)", "/출석체크, /프로세카뽑기, /마이세카이, /카드교환, /카드강화 등", "🎮"),
    ("dday", "📅 D-Day & 생일 & 라이프 (14종 · 3페이지)", "/디데이추가, /생일등록, /파트너, /집중모드 등", "📅"),
    ("admin", "⚙️ 봇 관리 & 마스터 대시보드 (14종 · 3페이지)", "/대시보드, /메뉴, /반응역할, /역할버튼제작, /공지발송 등", "⚙️"),
    ("games", "🎲 미니게임 & 파티 모집 (5종 · 1페이지)", "/모집, /끝말잇기, /러시안룰렛, /날씨, /알림예약", "🎲"),
    ("stats", "📊 서버/유저 통계 & 건의 (4종 · 1페이지)", "/서버통계, /유저정보, /건의, /봇상태", "📊"),
    ("music", "🎵 음악 & 플레이리스트 (12종 · 3페이지)", "/플레이리스트, /플리재생, /플리곡추가, /플리목록, /오디오테스트 등", "🎵"),
    ("ai", "💬 AI 세카이 대화 (2종 · 1페이지)", "/인공지능대화, /인공지능캐릭터설정", "💬"),
]


def build_help_embed(category: str = "all", search_kw: str = "", page: int = 0) -> discord.Embed:
    """
    가독성을 극대화한 norosi bot help 임베드 빌더.
    - category=='all' & page==0 & 검색어 없음: 전체 54개 명령어를 7대 카테고리별로 한눈에 볼 수 있는 요약 대시보드 제공
    - 특정 카테고리 선택 또는 페이지 이동 시: 페이지당 5개씩 깔끔하고 가독성 높은 카드 레이아웃 제공
    """
    total_cmds = len(COMMAND_CATALOG)
    header_links = (
        f"📜 **[이용약관]({TERMS_URL})**  ·  "
        f"🔒 **[개인정보처리방침]({PRIVACY_URL})**  ·  "
        f"💬 **[공식 서포트 서버]({SUPPORT_SERVER_URL})**"
    )

    # 1. 전체 카테고리 한눈에 보기 (요약 보드 모드)
    if category == "all" and not search_kw.strip() and page == 0:
        desc_lines = [
            header_links,
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"✨ **norosi**는 총 **`{total_cmds}종`**의 기능을 제공하는 올인원 세카이 & 커뮤니티 봇입니다.",
            "💡 명령어를 직접 치기 번거로울 땐 **`/메뉴`** 버튼 리모컨으로 모든 기능을 원클릭 조작할 수 있습니다!",
            "👇 **아래 카테고리 드롭다운**을 선택하거나 **`다음 ▶` 버튼**으로 1페이지부터 상세 가이드를 열람하세요."
        ]
        embed = discord.Embed(
            title="🌌 norosi 종합 가이드 허브",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        for cat_key, cat_title, cat_summary in CATEGORY_META:
            cat_cmds = [f"`{c['name']}`" for c in COMMAND_CATALOG if c["category"] == cat_key]
            cmd_line = " · ".join(cat_cmds)
            embed.add_field(
                name=f"{cat_title}",
                value=f"> *{cat_summary}*\n{cmd_line}",
                inline=False
            )

        embed.set_footer(text=f"전체 {total_cmds}개 슬래시 명령어 요약판  •  [다음 ▶] 버튼으로 1페이지부터 상세 가이드 보기  •  /메뉴 로 원클릭 실행")
        return embed

    # 2. 카테고리별 또는 검색어 필터링 상세 카드 보기
    filtered = COMMAND_CATALOG
    if category != "all":
        filtered = [c for c in filtered if c["category"] == category]

    if search_kw.strip():
        kw = search_kw.strip().lower()
        filtered = [
            c for c in filtered
            if kw in c["name"].lower() or kw in c["desc"].lower() or kw in c["example"].lower() or kw in c["cat_label"].lower()
        ]

    if not filtered:
        embed = discord.Embed(
            title="🔍 norosi 검색 결과 없음",
            description=(
                f"{header_links}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ **`{search_kw}`** 키워드와 일치하는 명령어를 찾지 못했습니다.\n\n"
                "💡 **추천 검색어:** `마이세카이`, `교환`, `뽑기`, `출석`, `모집`, `날씨`, `생일`, `음악`, `파트너`\n"
                "👉 아래 드롭다운에서 **'전체 명령어 한눈에 보기'**를 선택해 전체 목록을 둘러보세요!"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="norosi Help Assistant")
        return embed

    per_page = 5
    total_pages = max(1, math.ceil(len(filtered) / per_page))

    is_all_detail = (category == "all" and not search_kw.strip() and page > 0)
    eff_page = (page - 1) if is_all_detail else page
    eff_page = max(0, min(eff_page, total_pages - 1))

    start_i = eff_page * per_page
    page_items = filtered[start_i:start_i + per_page]

    cat_header = "🌟 전체 명령어 상세 가이드" if category == "all" else page_items[0]["cat_label"]
    display_curr_page = eff_page + 1

    desc_lines = [
        header_links,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📂 **카테고리:** **{cat_header}** (총 `{len(filtered)}개` 중 `{start_i + 1}~{start_i + len(page_items)}번째` 표시)",
        f"📖 **페이지:** **`{display_curr_page} / {total_pages}`** *(하단 버튼으로 이동하거나 다른 카테고리를 선택하세요)*"
    ]

    embed = discord.Embed(
        title=f"📖 norosi 명령어 상세 안내 ({cat_header})",
        description="\n".join(desc_lines),
        color=discord.Color.from_rgb(0, 204, 221),
        timestamp=datetime.datetime.now(core.KST)
    )

    for item in page_items:
        field_name = f"🔹 `{item['name']}`  ·  {item['cat_label']}"
        field_value = (
            f"> {item['desc']}\n"
            f"• ⚙️ **옵션:** `{item['params']}`\n"
            f"• 💡 **예시:** `{item['example']}`"
        )
        embed.add_field(name=field_name, value=field_value, inline=False)

    embed.set_footer(text=f"페이지 {display_curr_page}/{total_pages}  •  총 {len(filtered)}개 명령어  •  [🏠 전체 요약] 버튼으로 요약판 복귀")
    return embed


class HelpCategorySelect(discord.ui.Select):
    """7대 카테고리 선택 드롭다운 (현재 선택 상태 default 반영 및 페이지 안내)"""
    def __init__(self, parent_view: "HelpCategoryView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="📂 열람할 기능 카테고리를 선택하세요...",
            min_values=1,
            max_values=1,
            options=self._build_options(parent_view.category),
            row=0
        )

    def _build_options(self, current_cat: str):
        opts = []
        for val, label, desc, emoji in CATEGORY_DROPDOWN_OPTIONS:
            opts.append(discord.SelectOption(
                label=label,
                value=val,
                description=desc,
                emoji=emoji,
                default=(val == current_cat)
            ))
        return opts

    def refresh_options(self):
        self.options = self._build_options(self.parent_view.category)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.category = self.values[0]
        self.parent_view.search_kw = ""
        self.parent_view.page = 0
        self.refresh_options()
        self.parent_view.update_buttons()
        embed = build_help_embed(self.parent_view.category, self.parent_view.search_kw, self.parent_view.page)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class HelpCategoryView(core.SafeView):
    """페이지네이션(◀/▶) 및 카테고리 빠른 전환, 올인원 메뉴 바로가기를 지원하는 도움말 뷰"""
    def __init__(self, bot_instance=None, category: str = "all", search_kw: str = ""):
        super().__init__(timeout=300)
        self.bot_instance = bot_instance
        self.category = category
        self.search_kw = search_kw
        self.page = 0
        self.category_select = HelpCategorySelect(self)
        self.add_item(self.category_select)
        self.update_buttons()

    def _get_filtered(self):
        filtered = COMMAND_CATALOG
        if self.category != "all":
            filtered = [c for c in filtered if c["category"] == self.category]
        if self.search_kw.strip():
            kw = self.search_kw.strip().lower()
            filtered = [c for c in filtered if kw in c["name"].lower() or kw in c["desc"].lower() or kw in c["example"].lower()]
        return filtered

    def _total_pages(self) -> int:
        filtered = self._get_filtered()
        return max(1, math.ceil(len(filtered) / 5))

    def _max_page(self) -> int:
        if self.category == "all" and not self.search_kw.strip():
            return math.ceil(len(COMMAND_CATALOG) / 5)
        return max(0, math.ceil(len(self._get_filtered()) / 5) - 1)

    def update_buttons(self):
        max_p = self._max_page()
        total_p = self._total_pages()
        is_all_mode = (self.category == "all" and not self.search_kw.strip())

        if is_all_mode:
            if self.page == 0:
                self.prev_page_btn.disabled = True
                self.next_page_btn.disabled = False
                self.page_indicator_btn.label = "🏠 요약판"
            else:
                self.prev_page_btn.disabled = False
                self.next_page_btn.disabled = (self.page >= max_p)
                self.page_indicator_btn.label = f"📄 {self.page} / {total_p}"
        else:
            self.prev_page_btn.disabled = (self.page <= 0)
            self.next_page_btn.disabled = (self.page >= max_p)
            self.page_indicator_btn.label = f"📄 {self.page + 1} / {total_p}"

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def page_indicator_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_p = self._max_page()
        self.page = min(max_p, self.page + 1)
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏠 전체 요약", style=discord.ButtonStyle.primary, row=1)
    async def home_summary_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "all"
        self.search_kw = ""
        self.page = 0
        self.category_select.refresh_options()
        self.update_buttons()
        embed = build_help_embed("all", "", 0)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🧭 올인원 메뉴 열기", style=discord.ButtonStyle.success, row=1)
    async def open_quick_menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        bot_ref = self.bot_instance or interaction.client
        data = await core.asyncio.to_thread(core.load_data)
        dday_cog = bot_ref.get_cog("DDayCog")
        if dday_cog:
            from cogs.dday import QuickMenuHubView
            view = QuickMenuHubView(bot_ref, interaction.user, interaction.guild, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)
        else:
            await interaction.followup.send("💡 채팅창에 `/메뉴`를 입력하시면 올인원 리모컨을 즉시 열 수 있습니다!", ephemeral=True)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="도움말", description="norosi bot help - 전체 66개 슬래시 명령어 한눈에 보기 및 카테고리별 상세 가이드")
    @app_commands.describe(
        category="안내받을 카테고리 (all/games/cards/dday/stats/ai/music/admin)",
        search="검색할 명령어 이름 또는 키워드 (예: 반응역할, 플레이리스트, 플리재생, 플리곡추가, 오디오테스트, 헤드셋, 교환, 모집)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🌟 전체 명령어 한눈에 보기 (66종 요약판)", value="all"),
        app_commands.Choice(name="🎮 출석 & 카드/가챠 (18종 · 4페이지)", value="cards"),
        app_commands.Choice(name="📅 D-Day & 생일 & 라이프 (14종 · 3페이지)", value="dday"),
        app_commands.Choice(name="⚙️ 봇 관리 & 역할·공지·감사 (11종 · 3페이지)", value="admin"),
        app_commands.Choice(name="🎲 미니게임 & 파티 모집 (5종 · 1페이지)", value="games"),
        app_commands.Choice(name="📊 서버/유저 통계 & 건의 (4종 · 1페이지)", value="stats"),
        app_commands.Choice(name="🎵 음악 & 플레이리스트 (12종 · 3페이지)", value="music"),
        app_commands.Choice(name="💬 AI 세카이 대화 (2종 · 1페이지)", value="ai"),
    ])
    async def help_cmd(
        self,
        interaction: discord.Interaction,
        category: Optional[app_commands.Choice[str]] = None,
        search: Optional[str] = ""
    ):
        await core.safe_defer(interaction, ephemeral=True)
        cat_val = category.value if category else "all"
        embed = build_help_embed(category=cat_val, search_kw=search or "", page=0)
        view = HelpCategoryView(bot_instance=self.bot, category=cat_val, search_kw=search or "")
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @commands.command(name="도움말", aliases=["help", "도움", "명령어"])
    async def prefix_help(self, ctx: commands.Context, *, 검색: Optional[str] = ""):
        """채팅창에 !도움말 또는 !help 입력 시 즉시 57종 올인원 가이드 및 카테고리 대시보드 호출"""
        embed = build_help_embed(category="all", search_kw=검색 or "", page=0)
        view = HelpCategoryView(bot_instance=self.bot, category="all", search_kw=검색 or "")
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))

