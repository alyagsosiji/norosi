"""
cogs/help.py - norosi bot help: 통합 설정(/설정) 반영 & 권한별(일반·관리자·봇주인) 가독성 최적화 가이드
"""

import asyncio
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

PERM_BADGE_MAP = {
    "user": "👤 일반 이용자",
    "admin": "🛡️ 서버 관리자",
    "owner": "👑 봇 주인",
}

PERM_SHORT_BADGE = {
    "user": "[👤일반]",
    "admin": "[🛡️관리자]",
    "owner": "[👑봇주인]",
}

# ==========================================
# 전체 슬래시 명령어 & 통합 설정(/설정) 완벽 카탈로그 (13대 카테고리 분류)
# ==========================================
COMMAND_CATALOG: List[Dict[str, Any]] = [
    # 0. ⚙️ 통합 설정 & 봇 관리 (admin)
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/설정",
        "perm": "user",
        "settings_path": "⚙️ /설정 홈 (일반·고급·미니게임·개인)",
        "desc": "대시보드와 메뉴를 하나로 통합한 컴포넌트 V2 스타일 올인원 설정 허브! [🌐 일반 · ⚙️ 고급 · 🎮 미니게임 · 👤 개인] 4대 분류, [⬅️ 뒤로가기], 14페이지 통합 페이지네이션으로 84개 전 기능을 누락 없이 제어합니다.",
        "params": "카테고리: [홈/일반/고급/미니게임/개인(선택)]",
        "example": "/설정 또는 !설정 (!대시보드, !메뉴 호환)",
        "source": "cogs/dashboard.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/도움말",
        "perm": "user",
        "settings_path": "🌐 일반 > 📖 통합 도움말",
        "desc": "전체 명령어 및 `/설정` 구조의 카테고리별·권한별(👤일반 / 🛡️관리자 / 👑봇주인) 상세 가이드 열람",
        "params": "category: [카테고리(선택)] search: [검색어(선택)]",
        "example": "/도움말 category:admin",
        "source": "cogs/help.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/로그채널설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 📜 감사 로그 설정",
        "desc": "[서버 관리자] 메시지 삭제·수정, 멤버 입퇴장, 음성방 이동 등 7대 실시간 감사 로그 채널 설정",
        "params": "채널: [#채널] 상태: [활성화/비활성화]",
        "example": "/로그채널설정 채널:#서버-로그 상태:활성화",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/공지발송",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 📢 공지 발송 스튜디오",
        "desc": "[서버 관리자] 추천 템플릿(점검·이벤트·수칙·보상), 6대 테마 컬러, 멘션 전환, 사전 미리보기를 지원하는 공지 스튜디오",
        "params": "채널/중요도/멘션/테마색상/제목/내용/배너이미지 (미입력 시 스튜디오 오픈)",
        "example": "/공지발송",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/반응역할",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 🎭 반응역할 스튜디오",
        "desc": "[서버 관리자] 이모지 반응 역할 및 버튼형 역할 패널 제작·목록 조회·해제 통합 스튜디오",
        "params": "없음 (스튜디오 패널 자동 실행)",
        "example": "/반응역할",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/역할버튼제작",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 🔘 역할버튼 패널 제작",
        "desc": "[서버 관리자] 팝업 모달창에서 제목, 본문, 버튼 이름과 이모지를 직접 입력해 깔끔한 역할 버튼 패널 발행",
        "params": "채널: [#채널(선택)]",
        "example": "/역할버튼제작 채널:#역할선택",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/역할버튼생성",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 🔘 역할버튼 패널 제작",
        "desc": "[서버 관리자] 슬래시 옵션으로 제목·본문·역할·버튼이모지를 지정해 역할 버튼 패널 즉시 발행",
        "params": "제목: [제목] 본문: [본문] 역할: [@역할] 버튼이름: [이름] 버튼이모지: [이모지]",
        "example": "/역할버튼생성 제목:주민등록 본문:버튼을 눌러주세요 역할:@주민",
        "source": "cogs/roles.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/이모지업스케일",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 🔍 이모지 업스케일 설정",
        "desc": "[서버 관리자] 커스텀 이모지(1~3개) 전송 시 emote-cdn-rust(160x160 Lanczos3 WebP · 24h 캐시) 방식으로 자동 확대 ON/OFF",
        "params": "동작: [켜기(ON)/끄기(OFF)/상태확인(선택)]",
        "example": "/이모지업스케일 동작:🟢 켜기 (ON)",
        "source": "cogs/emoji_upscale.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/메시지삭제",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > 🧹 채널 메시지 청소",
        "desc": "[서버 관리자] 채널 메시지를 조건별(유저, 봇, 미디어, 키워드)로 최대 100개 일괄 청소",
        "params": "개수: [1~100] 유저: [@유저] 봇만: [True/False] 미디어만: [True/False] 키워드: [단어]",
        "example": "/메시지삭제 개수:30 봇만:True",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/비활성유저조회",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > 👻 비활성 멤버 감사",
        "desc": "[서버 관리자] 지정 기준일(7~90일) 동안 활동이 없는 멤버 조회 및 TXT 명단 다운로드",
        "params": "기준일수: [7일/14일/30일/60일/90일(기본: 30일)]",
        "example": "/비활성유저조회 기준일수:30",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/깃허브연동",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > 🐙 GitHub 웹훅 연동",
        "desc": "[서버 관리자] 채널에 GitHub 커밋 푸시 및 Actions 배포 완료 알림 연동 (/깃허브알림 단축 명령어 지원)",
        "params": "채널: [#채널(선택)] 역할멘션: [@역할(선택)] 연동해제: [True/False(선택)]",
        "example": "/깃허브연동 채널:#업데이트-알림",
        "source": "cogs/logger.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/터미널로그채널",
        "perm": "owner",
        "settings_path": "⚙️ 고급 4p > 🖥️ 터미널 로그 채널",
        "desc": "[봇 주인 전용] 호스트 서버 실시간 콘솔 출력(stdout/stderr)을 전송할 디스코드 채널 지정 또는 해제",
        "params": "채널: [#채널(선택, 미입력 시 해제)]",
        "example": "/터미널로그채널 채널:#터미널-로그",
        "source": "bot.py",
    },
    {
        "category": "admin",
        "cat_label": "⚙️ 통합 설정 & 서버 관리",
        "name": "/서버백업",
        "perm": "owner",
        "settings_path": "⚙️ 고급 4p > 💾 전체 DB 백업 & 동기화",
        "desc": "[봇 주인 전용] 현재 서버 구조 또는 전체 봇 DB를 JSON 파일로 안전하게 백업",
        "params": "모드: [현재서버구조/전체DB]",
        "example": "/서버백업 모드:전체DB",
        "source": "cogs/stats.py",
    },

    # 1. 🎮 출석 & 프로세카 가챠 (cards)
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/출석체크",
        "perm": "user",
        "settings_path": "🌐 일반 1p > 📅 즉시 출석체크",
        "desc": "자정(00:00) 기준 서버별 하루 1회 출석 도장 및 크리스탈(100~2,000💎 + 마이세카이/생활 버프) 획득",
        "params": "없음",
        "example": "/출석체크",
        "source": "cogs/dday.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/출석달력",
        "perm": "user",
        "settings_path": "🌐 일반 1p > 🗓️ 월간 출석달력",
        "desc": "이번 달 출석 캘린더 및 7/14/21/28일 개근 마일스톤 현황 조회",
        "params": "유저: [@유저(선택)]",
        "example": "/출석달력",
        "source": "cogs/dday.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/출석랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "현재 서버 또는 전체 서버의 출석 순위(누적 출석일 / 연속 출석일) 보드",
        "params": "범위: [서버/전체] 기준: [누적/연속]",
        "example": "/출석랭킹 범위:서버 기준:연속",
        "source": "cogs/dday.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/프로세카뽑기",
        "perm": "user",
        "settings_path": "🎮 미니게임 1p > 🎵 프로세카 뽑기",
        "desc": "프로세카 한섭 뽑기 (🌟일반·🎊페스·🎂생일 / 5×2 결과판 / 리세마라 연습 / 일일 운명 다시 뽑기)",
        "params": "횟수: [1회/10회] 배너: [일반/페스/생일] 연출: [표시/스킵] 모드: [일반/연습/운명/생일무료]",
        "example": "/프로세카뽑기 횟수:10회 뽑기 배너:🎊 컬러풀 페스티벌 (★4 2배)",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/내캐릭터",
        "perm": "user",
        "settings_path": "👤 개인 1p > 🎒 프로세카 내캐릭터",
        "desc": "보유 카드 보관함 조회·검색, 각성 전/후 일러스트 전환, ✦MR 확인, 🔒잠금 및 중복 변환 관리",
        "params": "유저: [@유저(선택)] 검색어: [캐릭터명(선택)]",
        "example": "/내캐릭터 검색어:카나데",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/카드도감",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "캐릭터별 수집률(%)과 미보유/보유 카드를 탭별 10개씩 페이지로 확인",
        "params": "유저: [@유저(선택)] 초기탭: [수집률/미보유카드/보유카드(선택)]",
        "example": "/카드도감 초기탭:미보유 카드",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/카드강화",
        "perm": "user",
        "settings_path": "👤 개인 1p > 🎸 프로세카 덱·강화·마스터",
        "desc": "크리스탈을 소모하여 보유 카드 레벨과 종합력 상승 (MAX 달성 시 보너스 💎 지급)",
        "params": "카드선택: [보유카드] 강화단계: [+1레벨/+10레벨/MAX]",
        "example": "/카드강화 카드선택:101 강화단계:MAX",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/마스터랭크",
        "perm": "user",
        "settings_path": "👤 개인 1p > 🎸 프로세카 덱·강화·마스터",
        "desc": "중복 카드 1장(0💎) 또는 크리스탈로 마스터 랭크(✦0~5) 돌파 (성급·중복보유 필터 지원, MR.2 어나더 컬러 해금)",
        "params": "카드선택: [보유카드(선택)]",
        "example": "/마스터랭크",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/라이브",
        "perm": "user",
        "settings_path": "🎮 미니게임 1p > ⚔️ 세카이 라이브",
        "desc": "5인 유닛 덱·속성·유닛·3D 의상 시너지로 세카이 라이브 플레이 (1일 3회 보상 & 7스탬프 완주 +300💎)",
        "params": "곡: [세카이 라이브 곡 선택(선택)]",
        "example": "/라이브",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/중복카드변환",
        "perm": "user",
        "settings_path": "👤 개인 1p > 💎 중복카드 크리스탈 변환",
        "desc": "2장 이상 중복 보유 카드(원본 및 🔒잠금 제외)를 성급별 크리스탈로 일괄 환전",
        "params": "없음",
        "example": "/중복카드변환",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/카드교환",
        "perm": "user",
        "settings_path": "👤 개인 1p > 🔄 카드 교환·선물 장터",
        "desc": "크리스탈 100개를 사용하여 다른 유저와 보유 카드를 1:1 실시간 교환",
        "params": "상대유저: [@유저] 내카드: [카드(선택)] 상대카드: [카드(선택)]",
        "example": "/카드교환 상대유저:@친구",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/카드선물",
        "perm": "user",
        "settings_path": "👤 개인 1p > 🔄 카드 교환·선물 장터",
        "desc": "크리스탈 50개를 사용하여 파트너에게 보유 카드 선물",
        "params": "내카드: [카드] 메시지: [축하메시지(선택)]",
        "example": "/카드선물 내카드:101 메시지:선물이야!",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/마이세카이",
        "perm": "user",
        "settings_path": "🎮 미니게임 3p > 🏠 마이세카이 룸",
        "desc": "나만의 미니 룸 테마와 세카이 가구를 배치하고 매일 출석체크 추가 크리스탈 이자 획득",
        "params": "유저: [@유저(선택)]",
        "example": "/마이세카이",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/의상",
        "perm": "user",
        "settings_path": "👤 개인 1p > 👗 3D 의상실 & 제작",
        "desc": "캐릭터별 3D 의상 착용, 어나더 컬러 3종 전환(✦MR.2 해금) 및 가챠 의상 제작",
        "params": "캐릭터: [캐릭터이름(선택)]",
        "example": "/의상 캐릭터:호시노 이치카",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/덱편성",
        "perm": "user",
        "settings_path": "👤 개인 1p > 🎸 프로세카 덱·강화·마스터",
        "desc": "보유 카드 중 최대 5장을 골라 리더와 멤버로 5인 유닛 덱 편성 및 총 종합력 계산",
        "params": "리더: [카드] 멤버2~5: [카드 4장(선택)]",
        "example": "/덱편성 리더:101",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/오시설정",
        "perm": "user",
        "settings_path": "👤 개인 1p > 💖 오시(최애) 캐릭터 설정",
        "desc": "내 프로필 카드에 대표로 표시될 최애(오시) 캐릭터 설정",
        "params": "캐릭터: [26인 캐릭터 선택]",
        "example": "/오시설정 캐릭터:요이사키 카나데",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/내프로필",
        "perm": "user",
        "settings_path": "🌐 일반 1p > 🎸 프로세카 프로필",
        "desc": "오시 일러스트, 마이세카이, 5인 덱(✦MR), 라이브 기록, 출석 일수, 크리스탈, 가챠 통계 종합 조회",
        "params": "유저: [@유저(선택)]",
        "example": "/내프로필",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/가챠랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "서버 도감 수집률·★4 보유 순위 및 단일 10연차 명예의 전당·최근 ★4 획득 로그 조회",
        "params": "없음",
        "example": "/가챠랭킹",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/프로세카확률목록",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "한국 서버 배너별(🌟일반·🎊페스·🎂생일) 상세 확률 및 픽업 카드 명단 조회",
        "params": "배너: [일반/페스/생일(선택)]",
        "example": "/프로세카확률목록",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/픽업설정",
        "perm": "owner",
        "settings_path": "⚙️ 고급 4p > 🎯 프로세카 픽업 설정",
        "desc": "[봇 주인 전용] 현재 한섭 진행 중 이벤트에 맞춰 픽업 자동 연동 또는 유닛/캐릭터 직접 설정",
        "params": "모드: [이벤트 자동맞춤/수동설정/초기화]",
        "example": "/픽업설정 모드:🎯 현재 한섭 이벤트에 자동 맞추기 (실시간 DB)",
        "source": "cogs/gacha.py",
    },
    {
        "category": "cards",
        "cat_label": "🎮 출석 & 프로세카 가챠",
        "name": "/서버캐릭터초기화",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > ⚠️ 서버 데이터 초기화",
        "desc": "[서버 관리자] 현재 디스코드 서버 유저들의 프로세카 캐릭터 보관함 초기화",
        "params": "없음",
        "example": "/서버캐릭터초기화",
        "source": "cogs/gacha.py",
    },

    # 2. 🌠 원신 기원 & 도감 & 상점 (genshin)
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 기원",
        "perm": "user",
        "settings_path": "🎮 미니게임 1p > 🌠 원신 기원",
        "desc": "원신 5대 배너(캐릭터①·②/신의주조 무기/성유물 비경/상시) 기원! KST 2시간 시각별 픽업 로테이션·포착된 광휘 지원",
        "params": "배너: [캐릭터①/②/신의주조/성유물비경/상시] 횟수: [10회/1회]",
        "example": "/원신 기원 배너:🏺 성유물 비경 기원 횟수:10회 기원",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 운명의궤도",
        "perm": "user",
        "settings_path": "🎮 미니게임 1p > 🗡️ 원신 운명의 궤도",
        "desc": "신의 주조(무기 이벤트 기원) 목표 5성 무기를 지정하여 명정 포인트 1/1 확정 보장 설정",
        "params": "버튼 UI로 픽업 무기 선택/해제",
        "example": "/원신 운명의궤도",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 보관함",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🎒 원신 보관함 & 육성",
        "desc": "보유 캐릭터(C0~C6)·무기(R1~R5)·성유물(5부위 주옵/부옵 감정) 필터 조회, 잠금🔒, Lv.1~90 육성",
        "params": "필터: [전체/캐릭터/무기/성유물/★5/★4/잠금]",
        "example": "/원신 보관함",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 도감",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "원신 전체 캐릭터·무기·성유물 세트 도감 수집률 및 미보유 목록 열람",
        "params": "탭: [보유/미보유/전체] 분류: [전체/캐릭터/무기/성유물]",
        "example": "/원신 도감",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 상점",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🛒 원신 페이몬 상점",
        "desc": "페이몬의 상점! 스타라이트 월간 ★4 캐릭터·무기 & 스타더스트 인연·영웅의 경험 교환",
        "params": "없음 (드롭다운 교환)",
        "example": "/원신 상점",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 파티편성",
        "perm": "user",
        "settings_path": "👤 개인 2p > ⚔️ 원신 4인 파티 & 프로필",
        "desc": "보유 캐릭터 4인으로 파티를 구성하고 원소 공명 및 전투력 계산",
        "params": "슬롯1~4: [보유캐릭터 자동완성(선택)]",
        "example": "/원신 파티편성",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 프로필",
        "perm": "user",
        "settings_path": "👤 개인 2p > ⚔️ 원신 4인 파티 & 프로필",
        "desc": "여행자 쇼케이스 카드(대표 캐릭터·상태문구 설정, 기원 천장 스택, 주력 캐릭터) 조회",
        "params": "대상: [@유저] 대표캐릭터: [선택] 상태문구: [선택]",
        "example": "/원신 프로필",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 확률",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "현재 시각(KST) 기준 원신 5대 배너 픽업 정보와 천장/포착된 광휘/운명의 궤도 확률표 확인",
        "params": "배너: [캐릭터①/②/무기/성유물/상시]",
        "example": "/원신 확률",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "서버 원신 수집 랭킹, 10연 명예의 전당(최다 ★5·저스택), 최근 ★5 획득 속보 조회",
        "params": "없음",
        "example": "/원신 랭킹",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 픽업설정",
        "perm": "owner",
        "settings_path": "⚙️ 고급 4p > 🌠 원신 픽업 로테이션",
        "desc": "[봇 주인 전용] 원신 기원 픽업을 KST 시각별 자동 로테이션·프리셋 또는 수동 지정으로 변경",
        "params": "프리셋/캐릭터1·2/사성1~3/무기1·2/성유물1·2",
        "example": "/원신 픽업설정 프리셋:⏰ KST 시각별 자동 로테이션",
        "source": "cogs/genshin.py",
    },
    {
        "category": "genshin",
        "cat_label": "🌠 원신 (기원·도감·상점)",
        "name": "/원신 서버초기화",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > ⚠️ 서버 데이터 초기화",
        "desc": "[서버 관리자] 현재 서버의 원신 기원/보관함 데이터 초기화",
        "params": "없음",
        "example": "/원신 서버초기화",
        "source": "cogs/genshin.py",
    },

    # 3. 🚄 붕괴: 스타레일 워프 & 아카이브 & 상점 (hsr)
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 워프",
        "perm": "user",
        "settings_path": "🎮 미니게임 1p > 🚄 스타레일 워프",
        "desc": "스타레일 5대 배너(캐릭터①·②/광추 75:25/터널유물·장신구/상시) 워프! KST 2시간 시각별 픽업 로테이션 지원",
        "params": "배너: [캐릭터①/②/광추/유물/상시] 횟수: [10회/1회]",
        "example": "/스타레일 워프 배너:🏺 터널 유물 & 차원 장신구 워프 횟수:10회 워프",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 상시300선택",
        "perm": "user",
        "settings_path": "🎮 미니게임 1p > ⭐ 스타레일 상시 300선택",
        "desc": "뭇별의 워프(상시) 누적 300회 달성 시 상시 5성 캐릭터 7명 중 1명 확정 초대",
        "params": "드롭다운으로 상시 5성 직접 선택",
        "example": "/스타레일 상시300선택",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 보관함",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🎒 스타레일 보관함 & 육성",
        "desc": "보유 캐릭터(E0~E6)·광추(S1~S5)·유물(6부위 주옵/부옵 감정) 필터 조회, 잠금🔒, Lv.1~80 육성",
        "params": "필터: [전체/캐릭터/광추/유물/★5/★4/잠금]",
        "example": "/스타레일 보관함",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 도감",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "스타레일 전체 캐릭터·광추·유물/장신구 세트 아카이브 수집률 및 보유/미보유 확인",
        "params": "탭: [보유/미보유/전체] 분류: [전체/캐릭터/광추/유물]",
        "example": "/스타레일 도감",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 상점",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🛒 스타레일 별빛·헤르타 상점",
        "desc": "별빛 교환(600별빛 상시 5성 광추·월간 ★4), 헤르타 상점(채권 5성 광추), 불멸의 잔재 티켓 교환",
        "params": "탭 & 드롭다운 교환",
        "example": "/스타레일 상점",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 파티편성",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🛸 스타레일 4인 편대 & 프로필",
        "desc": "4인 개척 편대를 구성하고 딜러·서포터·생존 밸런스 및 약점 격파 시너지 분석",
        "params": "슬롯1~4: [보유캐릭터 자동완성(선택)]",
        "example": "/스타레일 파티편성",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 프로필",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🛸 스타레일 4인 편대 & 프로필",
        "desc": "개척자 쇼케이스 카드(대표 캐릭터·상태문구 설정, 워프 스택 및 300회 진행률, 편대 전투력) 조회",
        "params": "대상: [@유저] 대표캐릭터: [선택] 상태문구: [선택]",
        "example": "/스타레일 프로필",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 확률",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "현재 시각(KST) 기준 스타레일 5대 배너 픽업 정보 및 캐릭터 50/50 · 광추 75/25 확률표 확인",
        "params": "배너: [캐릭터①/②/광추/유물/상시]",
        "example": "/스타레일 확률",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "서버 스타레일 수집 랭킹 · 10연 워프 명예의 전당 · 최근 ★5 도약 속보 조회",
        "params": "없음",
        "example": "/스타레일 랭킹",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 픽업설정",
        "perm": "owner",
        "settings_path": "⚙️ 고급 4p > 🚄 스타레일 픽업 로테이션",
        "desc": "[봇 주인 전용] 스타레일 이벤트 워프 픽업을 KST 시각별 자동 로테이션·프리셋 또는 수동 지정으로 변경",
        "params": "프리셋/캐릭터1·2/사성1~3/광추1·2/유물1·2",
        "example": "/스타레일 픽업설정 프리셋:⏰ KST 시각별 자동 로테이션",
        "source": "cogs/hsr.py",
    },
    {
        "category": "hsr",
        "cat_label": "🚄 스타레일 (워프·상점·편대)",
        "name": "/스타레일 서버초기화",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > ⚠️ 서버 데이터 초기화",
        "desc": "[서버 관리자] 현재 서버의 스타레일 워프/보관함 데이터 초기화",
        "params": "없음",
        "example": "/스타레일 서버초기화",
        "source": "cogs/hsr.py",
    },

    # 4. 🎣 통합 낚시 & 대회 (fishing)
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 출조",
        "perm": "user",
        "settings_path": "🎮 미니게임 2p > 🎣 낚시 출조 허브",
        "desc": "🏞️호수·🌊강·⚓바다 36,700+종 글로벌 어종 DB + 13개 세부 수역 입질 미니게임 & 포획 인증서 카드",
        "params": "장소: [호수/강/바다] 미끼: [떡밥/지렁이/크릴/루어/야광/황금] 빠른모드: [예/아니오]",
        "example": "/낚시 출조 장소:바다 미끼:메탈 지그 루어",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 가방",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🐟 낚시 가방 & 수족관",
        "desc": "잡은 물고기 보관함(길이·무게·가치) 필터 조회, 🔒 잠금 보호, 개별/일괄 판매 및 수족관 이동",
        "params": "장소: [전체/호수/강/바다] 성급: [전체/★1~★5]",
        "example": "/낚시 가방 장소:바다",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 도감",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📖 통합 도감 허브",
        "desc": "호수·강·바다별 어종 수집률(%), 성급·세부 수역 필터, 개인 최고 cm/kg 및 자동완성 검색",
        "params": "탭: [호수/강/바다/미보유] 어종검색: [자동완성 물고기명]",
        "example": "/낚시 도감 어종검색:태평양 참다랑어",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 수족관",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🐟 낚시 가방 & 수족관",
        "desc": "아끼는 대물을 프라이빗 어항(최대 20칸)에 전시하고 시간당 낚시 골드 수익 수확",
        "params": "유저: [@유저(선택)]",
        "example": "/낚시 수족관",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 상점",
        "perm": "user",
        "settings_path": "🎮 미니게임 2p > 🛒 낚시 장비 상점",
        "desc": "낚싯대 6티어(포세이돈 로드), 릴 5티어(크로노스 릴), 특급 미끼, 수족관 슬롯 확장권 구매",
        "params": "분류: [낚싯대/릴/미끼/수족관확장]",
        "example": "/낚시 상점 분류:낚싯대",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "서버 내 최대 길이(cm) · 최대 무게(kg) · 도감 수집왕 순위표 & 랭커 상세 조회 (`/낚시랭킹` 단축 명령어 지원)",
        "params": "기준: [최대길이/최대무게/도감] 장소: [전체/호수/강/바다]",
        "example": "/낚시 랭킹 기준:최대길이",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 퀘스트",
        "perm": "user",
        "settings_path": "🎮 미니게임 2p > 📜 일일 낚시 퀘스트",
        "desc": "매일 KST 00:00 갱신되는 일일 낚시 의뢰 3종 완료 시 낚시 골드(🪙) + 크리스탈(💎) 보상 수령",
        "params": "없음",
        "example": "/낚시 퀘스트",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 프로필",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🐟 낚시 가방 & 수족관",
        "desc": "낚시꾼 레벨·경험치·장착 장비·골드·크리스탈·수족관·도감 수집률 종합 라이선스 조회",
        "params": "유저: [@멤버(선택)]",
        "example": "/낚시 프로필",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 환경",
        "perm": "user",
        "settings_path": "🎮 미니게임 2p > 🌦️ 실시간 낚시 환경",
        "desc": "현재 KST 낮/밤·피딩타임·2시간 주기 날씨(맑음/비/폭풍우/안개) 및 추천 대물 예보",
        "params": "없음",
        "example": "/낚시 환경",
        "source": "cogs/fishing.py",
    },
    {
        "category": "fishing",
        "cat_label": "🎣 통합 낚시 (호수·강·바다)",
        "name": "/낚시 대회",
        "perm": "user",
        "settings_path": "🎮 미니게임 2p > 🏆 주말·제철 낚시대회",
        "desc": "주말 낚시 대회 & 계절 한정 어종(+25%🪙·1.5배 점수) 토너먼트 실시간 순위표 조회 및 개최·정산 (`/낚시대회` 지원)",
        "params": "동작: [현황/개최/정산(선택)] 종목: [최장어/총중량/제철포인트(선택)]",
        "example": "/낚시 대회",
        "source": "cogs/fishing.py",
    },

    # 5. 💳 통합 경제 & 프로필카드 & 칭호 (economy)
    {
        "category": "economy",
        "cat_label": "💳 통합 경제 & 프로필카드",
        "name": "/프로필카드",
        "perm": "user",
        "settings_path": "🌐 일반 1p > 🪪 통합 프로필카드",
        "desc": "프로세카·원신·스타레일·낚시·생활·칭호·배지를 한 장에 담은 고화질 PNG 통합 프로필 카드 발급 (`/경제 프로필카드` 지원)",
        "params": "유저: [@멤버(선택)]",
        "example": "/프로필카드",
        "source": "cogs/economy.py",
    },
    {
        "category": "economy",
        "cat_label": "💳 통합 경제 & 프로필카드",
        "name": "/경제 송금",
        "perm": "user",
        "settings_path": "👤 개인 2p > 💸 크리스탈 송금",
        "desc": "다른 서버 멤버에게 크리스탈(💎)을 안전하게 송금합니다 (5% 세금 차감 · 일일 최대 5,000💎 한도)",
        "params": "받는유저: [@멤버] 금액: [10~5000💎] 메모: [선택]",
        "example": "/경제 송금 받는유저:@친구 금액:500",
        "source": "cogs/economy.py",
    },
    {
        "category": "economy",
        "cat_label": "💳 통합 경제 & 프로필카드",
        "name": "/경제 칭호",
        "perm": "user",
        "settings_path": "👤 개인 2p > 🏷️ 칭호 상점 & 업적 배지",
        "desc": "크리스탈·낚시골드로 특별 칭호를 구매·장착하고, 자동 해금된 업적 배지 쇼케이스를 관리합니다",
        "params": "없음 (상점 & 장착 뷰 오픈)",
        "example": "/경제 칭호",
        "source": "cogs/economy.py",
    },
    {
        "category": "economy",
        "cat_label": "💳 통합 경제 & 프로필카드",
        "name": "/경제 랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "서버 크리스탈 · 낚시 골드 · 통합 순자산(Net Worth) 부자 랭킹을 확인합니다",
        "params": "없음",
        "example": "/경제 랭킹",
        "source": "cogs/economy.py",
    },

    # 6. 🌾 농장 & 공동농장 & 펫 & 요리 (life)
    {
        "category": "life",
        "cat_label": "🌾 생활 (농장·공동농장·펫·요리)",
        "name": "/생활 대시보드",
        "perm": "user",
        "settings_path": "🎮 미니게임 3p > 🌿 생활 통합 현황판",
        "desc": "개인 농장 · 서버 공동농장 · 펫 · 요리 및 현재 적용 중인 패시브 버프를 한눈에 관리하는 통합 현황판",
        "params": "없음",
        "example": "/생활 대시보드",
        "source": "cogs/life.py",
    },
    {
        "category": "life",
        "cat_label": "🌾 생활 (농장·공동농장·펫·요리)",
        "name": "/생활 농장",
        "perm": "user",
        "settings_path": "🎮 미니게임 3p > 🌾 개인 농장",
        "desc": "나만의 개인 밭에 작물 씨앗을 심고 물주기·비료주기·수확·판매를 진행합니다",
        "params": "없음",
        "example": "/생활 농장",
        "source": "cogs/life.py",
    },
    {
        "category": "life",
        "cat_label": "🌾 생활 (농장·공동농장·펫·요리)",
        "name": "/생활 공동농장",
        "perm": "user",
        "settings_path": "🎮 미니게임 3p > 🤝 서버 공동 농장",
        "desc": "서버 전체 유저와 함께 가꾸는 서버 공동 농장(Lv.1~10 · 일일 배당금 · 전 서버원 버프)을 엽니다",
        "params": "없음",
        "example": "/생활 공동농장",
        "source": "cogs/life.py",
    },
    {
        "category": "life",
        "cat_label": "🌾 생활 (농장·공동농장·펫·요리)",
        "name": "/생활 펫",
        "perm": "user",
        "settings_path": "🎮 미니게임 3p > 🐾 펫 키우기",
        "desc": "6종의 귀여운 펫을 입양·먹이주기·교감하며 낚시 입질/크기 및 출석체크 보너스 버프를 받습니다",
        "params": "없음",
        "example": "/생활 펫",
        "source": "cogs/life.py",
    },
    {
        "category": "life",
        "cat_label": "🌾 생활 (농장·공동농장·펫·요리)",
        "name": "/생활 요리",
        "perm": "user",
        "settings_path": "🎮 미니게임 3p > 🍳 요리 주방 & 버프",
        "desc": "낚시로 잡은 미잠금 ★1~2 물고기와 수확한 농작물로 요리를 만들어 강력한 버프를 획득합니다 (`/생활 버프` 지원)",
        "params": "없음",
        "example": "/생활 요리",
        "source": "cogs/life.py",
    },

    # 7. 👶 타인의 삶 — 인생 시뮬레이션 (other_life)
    {
        "category": "other_life",
        "cat_label": "👶 타인의 삶 (인생 시뮬레이션)",
        "name": "/인생 플레이",
        "perm": "user",
        "settings_path": "🎮 미니게임 4p > 👶 타인의 삶 플레이",
        "desc": "0세 탄생부터 황혼까지 매 턴 선택지로 운명을 개척하는 1,000종 멀티 엔딩 인생 시뮬레이션 RPG (`!인생` 지원)",
        "params": "이름: [주인공 이름(선택)]",
        "example": "/인생 플레이",
        "source": "cogs/other_life.py",
    },
    {
        "category": "other_life",
        "cat_label": "👶 타인의 삶 (인생 시뮬레이션)",
        "name": "/인생 도감",
        "perm": "user",
        "settings_path": "🎮 미니게임 4p > 📜 타인의 삶 엔딩 도감",
        "desc": "해금한 1,000종 멀티 엔딩 도감(등급 필터·검색·수집률)과 내가 살아온 역대 생애 전기 아카이브 열람",
        "params": "유저: [@멤버(선택)]",
        "example": "/인생 도감",
        "source": "cogs/other_life.py",
    },
    {
        "category": "other_life",
        "cat_label": "👶 타인의 삶 (인생 시뮬레이션)",
        "name": "/인생 랭킹",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 🏆 통합 랭킹 허브",
        "desc": "서버 유저들의 타인의 삶 엔딩 수집률 · 최고 인생 점수 명예의 전당을 확인합니다",
        "params": "없음",
        "example": "/인생 랭킹",
        "source": "cogs/other_life.py",
    },

    # 8. 🎫 1:1 티켓 & 임시음성방 & 커뮤니티 방어 (tickets)
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/티켓 설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 🎫 1:1 문의 티켓 관리",
        "desc": "[서버 관리자] 서버의 1:1 문의 티켓 카테고리, 담당자 역할, 로그 채널, 생성 방식(채널/스레드) 설정",
        "params": "카테고리/담당역할/로그채널/생성방식/인당최대수",
        "example": "/티켓 설정",
        "source": "cogs/tickets.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/티켓 패널생성",
        "perm": "admin",
        "settings_path": "⚙️ 고급 1p > 🎫 1:1 문의 티켓 관리",
        "desc": "[서버 관리자] 유저가 버튼을 눌러 즉시 1:1 비밀 문의방을 열 수 있는 영구 안내 패널 발행",
        "params": "채널: [#채널(선택)] 제목: [선택] 설명: [선택]",
        "example": "/티켓 패널생성 채널:#문의하기",
        "source": "cogs/tickets.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/티켓 닫기",
        "perm": "user",
        "settings_path": "⚙️ 고급 1p > 🎫 1:1 문의 티켓 관리",
        "desc": "현재 진행 중인 1:1 문의 티켓을 종료하고 UTF-8 `.txt` 대화 기록(트랜스크립트)을 보존합니다 (`/티켓 목록`, `/티켓 멤버추가` 지원)",
        "params": "사유: [종료 사유(선택)]",
        "example": "/티켓 닫기",
        "source": "cogs/tickets.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/임시음성방",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 🔊 내 임시음성방 리모컨 / ⚙️ 고급 1p > 생성기 설정",
        "desc": "입장 시 개인 음성방이 자동 생성되고 전원 퇴장 시 삭제되는 Join-to-Create 생성기 설정(관리자) 및 방장 리모컨(이름/정원/잠금/숨김/방장인계)",
        "params": "메뉴: [리모컨호출(일반)/관리자설정(관리자)]",
        "example": "/임시음성방",
        "source": "cogs/community.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/고정메시지 설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 📌 자동 고정 메시지",
        "desc": "[서버 관리자] 채팅이 올라와도 항상 채널 최하단에 공지/규칙 임베드를 유지하는 Sticky Message 설정 (`/고정메시지 토글/해제/목록` 지원)",
        "params": "채널: [#채널(선택)] 주기: [메시지 수] 색상: [선택]",
        "example": "/고정메시지 설정",
        "source": "cogs/community.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/링크보정 설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 🔗 SNS 링크 보정 설정",
        "desc": "[서버 관리자] X(트위터)·인스타·틱톡·픽시브 미리보기 보정 및 추적 태그(utm 등) 자동 제거 설정 (`/링크보정 채널제외` 지원)",
        "params": "없음 (설정 뷰 오픈)",
        "example": "/링크보정 설정",
        "source": "cogs/community.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/비상모드 설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 🚨 레이드 비상 방어",
        "desc": "[서버 관리자] 단시간 대량 입장(Raid) 자동 감지 임계치, 신규 계정 기준일, 자동 초대 중지 및 격리/타임아웃 설정 (`/비상모드 발동/해제/상태` 지원)",
        "params": "없음 (방어 설정 뷰 오픈)",
        "example": "/비상모드 설정",
        "source": "cogs/community.py",
    },
    {
        "category": "tickets",
        "cat_label": "🎫 티켓 & 임시음성방 & 보안",
        "name": "/릴레이소설 시작",
        "perm": "user",
        "settings_path": "🎮 미니게임 4p > ✍️ 릴레이 소설 공방",
        "desc": "채널 멤버들이 한 줄씩 이어 쓰는 협동 릴레이 소설 개설 (블라인드/전체공개 모드 지원, `/릴레이소설 현황/목록/중단` 지원)",
        "params": "제목: [제목] 첫문장: [첫 줄] 목표턴: [3~30턴] 공개모드: [블라인드/전체공개]",
        "example": "/릴레이소설 시작 제목:세카이의 밤 첫문장:자정이 되자 휴대폰 화면이 빛났다.",
        "source": "cogs/community.py",
    },

    # 9. 📅 D-Day & 생일 & 라이프 (dday)
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/생일등록",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🎂 내 생일 & 파트너 기념일",
        "desc": "내 생일을 등록해 당일 자정 축하 알림과 +500💎 보너스를 받고 서버 멤버 생일 전광판 확인",
        "params": "동작: [등록/전광판/삭제] 월: [1~12] 일: [1~31] 메모: [생일소원]",
        "example": "/생일등록 동작:register 월:2 일:10 메모:축하해주세요!",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/디데이목록",
        "perm": "user",
        "settings_path": "🌐 일반 1p > 📆 서버 디데이 보드",
        "desc": "등록된 모든 D-Day 일정의 진행 상황을 은하수 잔디 막대 그래프로 확인 (`/지나간디데이` 포함)",
        "params": "없음",
        "example": "/디데이목록",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/디데이추가",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 📅 디데이 전광판 관리",
        "desc": "[서버 관리자] 새 서버 D-Day 일정을 추가하고 선택한 카테고리에 음성 전광판 채널 자동 생성 (`/전광판설정`, `/디데이삭제` 지원)",
        "params": "이름: [제목] 날짜: [YYYY-MM-DD] 카테고리: [채널위치(선택)] 이모지: [아이콘(선택)]",
        "example": "/디데이추가 이름:수능 날짜:2026-11-19",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/비밀디데이",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🔒 나만의 비밀 디데이",
        "desc": "나만 볼 수 있는 비밀 D-Day 및 타임캡슐(목표일 오전 9시 개인 DM 전송) 관리",
        "params": "동작: [비밀보드/추가/목록/삭제] 이름: [제목] 날짜: [YYYY-MM-DD]",
        "example": "/비밀디데이 동작:추가 이름:자격증시험 날짜:2026-11-25",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/파트너",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🎂 내 생일 & 파트너 기념일",
        "desc": "연인·친구와 파트너를 맺어 공동 D-Day와 둘만의 공유 음악 보관함 관리",
        "params": "동작: [보드열기/신청/공동디데이추가/삭제/공유음악/해제] 유저: [@파트너]",
        "example": "/파트너 동작:보드열기",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/집중모드",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🍅 뽀모도로 집중모드",
        "desc": "뽀모도로 스터디 타이머 (집중 시간과 휴식 시간 사이클 안내 및 집중 보상 지급)",
        "params": "동작: [시작/중지] 집중시간: [분] 휴식시간: [분] 세트수: [횟수]",
        "example": "/집중모드 동작:시작 집중시간:25 휴식시간:5 세트수:4",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/하드코어스터디",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🔥 하드코어 스터디",
        "desc": "자격증/코딩 전용 50분 집중 · 10분 휴식 사이클 및 은하수 보라잔디(🟪)와 대량 크리스탈 획득",
        "params": "동작: [시작/중지/현황] 목표: [과목/내용] 목표시간: [50~250분]",
        "example": "/하드코어스터디 동작:시작 목표:코딩테스트 목표시간:100",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/오늘목표",
        "perm": "user",
        "settings_path": "👤 개인 3p > 🌱 오늘목표 은하수 잔디",
        "desc": "오늘의 할 일(To-Do) 목록을 관리하고 최근 7일간의 은하수 잔디(🌌🌠🌑) 달성",
        "params": "새목표: [할일내용(선택)]",
        "example": "/오늘목표 새목표:프로세카 5판 플레이",
        "source": "cogs/dday.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/미래시",
        "perm": "user",
        "settings_path": "🌐 일반 1p > 🔮 프로세카 미래시·이벤트",
        "desc": "프로세카 한국 서버의 다가오는 이벤트 미래시 일정과 상세 타임라인 카드 확인 (`/이벤트`로 한섭/일섭 실시간 이벤트 조회)",
        "params": "년도: [2026] 월: [1~12월]",
        "example": "/미래시 년도:2026 월:11",
        "source": "cogs/gacha.py",
    },
    {
        "category": "dday",
        "cat_label": "📅 D-Day & 생일 & 라이프",
        "name": "/알림설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 📅 디데이 전광판 관리",
        "desc": "[서버 관리자] 매일 오전 9시 D-Day 브리핑 알림을 받을 텍스트 채널과 기본 카테고리 설정",
        "params": "알림채널: [#채널] 기본카테고리: [카테고리]",
        "example": "/알림설정 알림채널:#디데이알림",
        "source": "cogs/dday.py",
    },

    # 10. 🎲 미니게임 & 파티 모집 (games)
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 파티 모집",
        "name": "/모집",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 🤝 파티원 모집 생성",
        "desc": "프로세카 협력 라이브, 롤, 발로란트, 스팀 등 모든 게임 파티원 실시간 모집 (팝업 모달 지원, 풀방 시 전원 자동 멘션)",
        "params": "옵션 없이 실행 시 모달 팝업, 또는 게임/인원수/목표/방번호 지정",
        "example": "/모집",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 파티 모집",
        "name": "/끝말잇기",
        "perm": "user",
        "settings_path": "🎮 미니게임 4p > 🔤 끝말잇기 대결",
        "desc": "표준 두음법칙이 완벽 적용되는 실시간 끝말잇기 배틀! (봇 1:1 또는 유저 대결, 승리 시 +150💎)",
        "params": "상대유저: [@멤버(선택)] 시작단어: [첫단어(선택)]",
        "example": "/끝말잇기 시작단어:세카이",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 파티 모집",
        "name": "/러시안룰렛",
        "perm": "user",
        "settings_path": "🎮 미니게임 4p > 🔫 러시안룰렛 서바이벌",
        "desc": "6연발 리볼버에 실탄을 장전하고 방아쇠를 당겨 누적 상금(💎)을 획득하는 스릴 생존 게임",
        "params": "실탄수: [1~5발(선택)] 참가비: [0~500💎(선택)]",
        "example": "/러시안룰렛 실탄수:1 참가비:50",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 파티 모집",
        "name": "/날씨",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 🌤️ 실시간 전국 날씨",
        "desc": "기상청(KMA)/ECMWF 실시간 관측 기온, 체감온도, 미세먼지(PM10/PM2.5), 강수확률 및 우산 가이드",
        "params": "지역: [도시/시/군/구 이름]",
        "example": "/날씨 지역:서울",
        "source": "cogs/stats.py",
    },
    {
        "category": "games",
        "cat_label": "🎲 미니게임 & 파티 모집",
        "name": "/알림예약",
        "perm": "user",
        "settings_path": "👤 개인 3p > ⏰ 스마트 알림예약",
        "desc": "'30분 뒤', '1시간 후', '15:30' 등 자연어로 예약하면 정확한 시각에 DM 및 채널 멘션으로 알림 발송",
        "params": "시간: [자연어/시각] 내용: [알림메모] 방식: [DM+채널/채널만/DM만]",
        "example": "/알림예약 시간:30분 뒤 내용:라면 불 끄기",
        "source": "cogs/dday.py",
    },

    # 11. 📊 서버/유저 통계 & 건의 (stats)
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계 & 건의",
        "name": "/유저정보",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 🔍 멤버 상세 정보",
        "desc": "멤버의 디스코드 가입일, 서버 입장 순번(#N번째), 보유 역할, 출석/크리스탈/채팅량 상세 분석",
        "params": "유저: [@멤버(선택)]",
        "example": "/유저정보",
        "source": "cogs/stats.py",
    },
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계 & 건의",
        "name": "/서버통계",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 📊 서버 종합 통계",
        "desc": "서버의 일일/주간 채팅량, Top3 활성 채널, 실시간 음성 통화 인원, 출석률 및 시간대별 분포",
        "params": "기간: [일간/주간] 상세보기: [요약/상세]",
        "example": "/서버통계",
        "source": "cogs/stats.py",
    },
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계 & 건의",
        "name": "/건의",
        "perm": "user",
        "settings_path": "🌐 일반 3p > 📮 봇 건의 & 피드백",
        "desc": "봇 개발진/운영진에게 익명 또는 계정 공개로 건의 및 버그 제보 접수 (스크린샷 첨부 지원)",
        "params": "유형: [익명/계정공개] 제목: [한줄요약(선택)] 내용: [상세내용(선택)]",
        "example": "/건의",
        "source": "cogs/stats.py",
    },
    {
        "category": "stats",
        "cat_label": "📊 서버/유저 통계 & 건의",
        "name": "/봇상태",
        "perm": "admin",
        "settings_path": "⚙️ 고급 3p > 🖥️ 호스트 봇 상태 진단",
        "desc": "[서버 관리자] 봇 호스트 시스템 리소스(RAM RSS, CPU 로드, 디스크 용량, 핑, 업타임) 실시간 확인",
        "params": "없음",
        "example": "/봇상태",
        "source": "cogs/stats.py",
    },

    # 12. 🎵 음악 & 플레이리스트 (music)
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플레이리스트",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 💿 플레이리스트 스튜디오",
        "desc": "유튜브·스포티파이·사운드클라우드 기반 나만의 플레이리스트 제작, 음성채널 순차 자동재생 및 리모컨 제어",
        "params": "동작: [스튜디오/음성자동재생/음성리모컨/음성정지/곡추가/새플리/공유]",
        "example": "/플레이리스트",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리재생",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 🎧 음성채널 음악 리모컨",
        "desc": "내 음성채널에서 플레이리스트를 지정 순번부터 즉시 자동재생 (`!플리재생`, `/배속`, `/헤드셋`, `/오디오테스트` 지원)",
        "params": "플리선택: [선택] 시작순번: [숫자(기본: 1)]",
        "example": "/플리재생 시작순번:1",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/플리곡추가",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 💿 플레이리스트 스튜디오",
        "desc": "내 플레이리스트에 곡(제목 또는 링크)을 빠르게 추가 (`/플리목록`, `/플리가져오기`, `/플리곡삭제` 지원)",
        "params": "곡: [제목/링크] 아티스트: [선택] 플리선택: [선택]",
        "example": "/플리곡추가 곡:NewJeans Hype Boy",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/음악지금추천",
        "perm": "user",
        "settings_path": "🌐 일반 2p > 🎧 음성채널 음악 리모컨",
        "desc": "현재 시간과 감성에 어울리는 프로세카/보컬로이드 노래를 즉시 추천 (`/내음악보관함` 하트 저장 지원)",
        "params": "없음",
        "example": "/음악지금추천",
        "source": "cogs/music.py",
    },
    {
        "category": "music",
        "cat_label": "🎵 음악 & 플레이리스트",
        "name": "/음악추천설정",
        "perm": "admin",
        "settings_path": "⚙️ 고급 2p > 🎵 정기 음악알림 설정",
        "desc": "[서버 관리자] 매일 오전 7시 모닝 음악 추천 채널 및 맞춤형 정기 음악 알람(`/음악알림추가`) 설정",
        "params": "채널: [#채널] 플랫폼: [유튜브/스포티파이/사운드클라우드/랜덤]",
        "example": "/음악추천설정 채널:#음악추천",
        "source": "cogs/music.py",
    },
]

CATEGORY_META = [
    ("admin", "⚙️ 통합 설정(/설정) & 서버 관리", "`/설정` (일반·고급·미니게임·개인 통합 허브), 감사로그, 공지발송, 반응역할, 이모지업스케일, 백업"),
    ("cards", "🎮 출석 & 프로세카 가챠", "`/출석체크`, `/프로세카뽑기`, `/마스터랭크`, `/라이브`, `/마이세카이`, `/의상`, `/덱편성`"),
    ("genshin", "🌠 원신 기원 & 도감 & 상점", "`/원신 기원`, `/원신 운명의궤도`, `/원신 보관함`, `/원신 상점`, `/원신 파티편성`"),
    ("hsr", "🚄 스타레일 워프 & 아카이브 & 상점", "`/스타레일 워프`, `/스타레일 상시300선택`, `/스타레일 보관함`, `/스타레일 상점`, `/스타레일 파티편성`"),
    ("fishing", "🎣 통합 낚시 & 주말·제철 대회", "`/낚시 출조`, `/낚시 대회`, `/낚시 가방`, `/낚시 수족관`, `/낚시 상점`, `/낚시 퀘스트`"),
    ("economy", "💳 통합 경제 & 프로필카드 & 칭호", "`/프로필카드`, `/경제 송금`, `/경제 칭호`, `/경제 랭킹`"),
    ("life", "🌾 생활 — 농장 · 공동농장 · 펫 · 요리", "`/생활 대시보드`, `/생활 농장`, `/생활 공동농장`, `/생활 펫`, `/생활 요리`"),
    ("other_life", "👶 타인의 삶 — 1,000엔딩 인생 RPG", "`/인생 플레이`, `/인생 도감`, `/인생 랭킹`"),
    ("tickets", "🎫 1:1 티켓 & 임시음성방 & 보안·릴레이", "`/티켓 설정`, `/티켓 패널생성`, `/임시음성방`, `/고정메시지 설정`, `/링크보정 설정`, `/비상모드 설정`"),
    ("dday", "📅 D-Day & 생일 & 스터디·목표", "`/디데이목록`, `/생일등록`, `/파트너`, `/비밀디데이`, `/오늘목표`, `/집중모드`, `/하드코어스터디`"),
    ("games", "🎲 미니게임 & 파티 모집 & 유틸", "`/모집`, `/끝말잇기`, `/러시안룰렛`, `/날씨`, `/알림예약`"),
    ("stats", "📊 서버/유저 통계 & 건의 & 봇상태", "`/유저정보`, `/서버통계`, `/건의`, `/봇상태`"),
    ("music", "🎵 음악 & 플레이리스트 & 음성재생", "`/플레이리스트`, `/플리재생`, `/플리곡추가`, `/음악지금추천`, `/음악추천설정`"),
]

CATEGORY_DROPDOWN_OPTIONS = [
    ("all", "🌟 전체 요약 & /설정 가이드 (홈)", "4대 설정 분류(일반·고급·미니게임·개인) 및 13대 카테고리 한눈에 보기", "🌐"),
    ("admin", "⚙️ 통합 설정(/설정) & 서버 관리", "/설정, /로그채널설정, /공지발송, /반응역할, /이모지업스케일 등", "⚙️"),
    ("cards", "🎮 출석 & 프로세카 가챠", "/출석체크, /프로세카뽑기, /마스터랭크, /라이브, /마이세카이 등", "🎮"),
    ("genshin", "🌠 원신 기원·도감·상점", "/원신 기원, /원신 운명의궤도, /원신 보관함, /원신 상점, /원신 파티편성", "🌠"),
    ("hsr", "🚄 스타레일 워프·상점·편대", "/스타레일 워프, /스타레일 상시300선택, /스타레일 보관함, /스타레일 상점", "🚄"),
    ("fishing", "🎣 통합 낚시 & 주말·제철 대회", "/낚시 출조, /낚시 대회, /낚시 가방, /낚시 수족관, /낚시 상점 등", "🎣"),
    ("economy", "💳 통합 경제 & 프로필카드 & 칭호", "/프로필카드, /경제 송금, /경제 칭호, /경제 랭킹", "💳"),
    ("life", "🌾 생활 (농장·공동농장·펫·요리)", "/생활 대시보드, /생활 농장, /생활 공동농장, /생활 펫, /생활 요리", "🌾"),
    ("other_life", "👶 타인의 삶 (인생 시뮬레이션)", "/인생 플레이, /인생 도감, /인생 랭킹", "👶"),
    ("tickets", "🎫 1:1 티켓 & 임시음성방 & 보안", "/티켓 설정, /임시음성방, /고정메시지 설정, /비상모드 설정, /릴레이소설", "🎫"),
    ("dday", "📅 D-Day & 생일 & 스터디·목표", "/디데이목록, /생일등록, /파트너, /오늘목표, /집중모드, /하드코어스터디", "📅"),
    ("games", "🎲 미니게임 & 파티 모집 & 날씨", "/모집, /끝말잇기, /러시안룰렛, /날씨, /알림예약", "🎲"),
    ("stats", "📊 서버/유저 통계 & 건의 & 봇상태", "/유저정보, /서버통계, /건의, /봇상태", "📊"),
    ("music", "🎵 음악 & 플레이리스트 & 음성재생", "/플레이리스트, /플리재생, /플리곡추가, /음악지금추천, /음악추천설정", "🎵"),
]


def _filter_catalog(category: str = "all", search_kw: str = "", perm_filter: str = "all") -> List[Dict[str, Any]]:
    filtered = COMMAND_CATALOG
    if category != "all":
        filtered = [c for c in filtered if c["category"] == category]
    if perm_filter in ("user", "admin", "owner"):
        filtered = [c for c in filtered if c.get("perm", "user") == perm_filter]
    if search_kw.strip():
        kw = search_kw.strip().lower()
        filtered = [
            c for c in filtered
            if kw in c["name"].lower()
            or kw in c["desc"].lower()
            or kw in c["example"].lower()
            or kw in c["cat_label"].lower()
            or kw in c.get("settings_path", "").lower()
        ]
    return filtered


def build_help_embed(
    category: str = "all",
    search_kw: str = "",
    page: int = 0,
    perm_filter: str = "all",
) -> discord.Embed:
    """
    가독성을 극대화한 norosi 통합 도움말 임베드 빌더.
    - `/설정` (일반·고급·미니게임·개인) 구조 안내 및 권한 등급(👤일반 / 🛡️관리자 / 👑봇주인) 명확 구분
    """
    total_cmds = len(COMMAND_CATALOG)
    user_cnt = sum(1 for c in COMMAND_CATALOG if c.get("perm") == "user")
    admin_cnt = sum(1 for c in COMMAND_CATALOG if c.get("perm") == "admin")
    owner_cnt = sum(1 for c in COMMAND_CATALOG if c.get("perm") == "owner")

    header_links = (
        f"📜 **[이용약관]({TERMS_URL})**  ·  "
        f"🔒 **[개인정보처리방침]({PRIVACY_URL})**  ·  "
        f"💬 **[공식 서포트 서버]({SUPPORT_SERVER_URL})**"
    )

    # 1. 전체 요약 홈 보드 (category=='all' & page==0 & 검색/권한필터 없음)
    if category == "all" and not search_kw.strip() and perm_filter == "all" and page == 0:
        desc_lines = [
            header_links,
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "### ⚙️ 슬래시 명령어 완전 통합 안내 — `/설정` & `/도움말` 단일화!",
            "> 복잡한 개별 슬래시 명령어들을 모두 정리하고 **`/설정`**과 **`/도움말`** 2개만 남겼습니다!\n"
            "> 채팅창에 **`/설정`**(`!설정`)을 입력한 뒤 **`🌐 일반`** · **`⚙️ 고급`** · **`🎮 미니게임`** · **`👤 개인`** 버튼과 **`⬅️ 뒤로가기`**, **`◀ 이전 / 다음 ▶` 통합 페이지네이션(1~14p)**으로 모든 기능을 오류 없이 조작할 수 있습니다.",
            "",
            "### 🔐 권한 등급 안내 (누가 사용할 수 있나요?)",
            f"• **`👤 일반 이용자` ({user_cnt}종):** 출석, 가챠, 낚시, 농장, 인생게임, 음악, 내 프로필/보관함 (`🌐 일반` · `🎮 미니게임` · `👤 개인`)\n"
            f"• **`🛡️ 서버 관리자` ({admin_cnt}종):** 감사로그, 공지발송, 반응역할, 이모지 업스케일(스티커 크기·모바일 호환), 티켓/음성방/고정메시지/비상모드 (`⚙️ 고급 1~3p`)\n"
            f"• **`👑 봇 주인` ({owner_cnt}종):** 3대 게임 픽업 배너 로테이션, 터미널 로그, 전체 DB 백업/동기화/봇배너 (`⚙️ 고급 4p`)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "👇 **드롭다운**으로 카테고리를 고르거나, **권한 필터 버튼** / **`다음 ▶`** 버튼으로 `/설정` 내 정확한 버튼 위치를 확인하세요!",
        ]
        embed = discord.Embed(
            title="📖 norosi 통합 도움말 & `/설정` 가이드",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=datetime.datetime.now(core.KST),
        )

        # 가독성을 위해 핵심 카테고리를 깔끔한 요약 블록으로 그룹핑
        for cat_key, cat_title, cat_summary in CATEGORY_META:
            cat_items = [c for c in COMMAND_CATALOG if c["category"] == cat_key]
            u_c = sum(1 for c in cat_items if c.get("perm") == "user")
            a_c = sum(1 for c in cat_items if c.get("perm") == "admin")
            o_c = sum(1 for c in cat_items if c.get("perm") == "owner")
            badge_parts = []
            if u_c:
                badge_parts.append(f"`👤일반 {u_c}`")
            if a_c:
                badge_parts.append(f"`🛡️관리자 {a_c}`")
            if o_c:
                badge_parts.append(f"`👑봇주인 {o_c}`")
            badge_str = " ".join(badge_parts)

            embed.add_field(
                name=f"{cat_title}  ({len(cat_items)}종)",
                value=f"{badge_str}\n└ {cat_summary}",
                inline=False,
            )

        embed.set_footer(
            text=f"슬래시 명령어는 /설정 · /도움말 2종으로 통합 완료! (총 {total_cmds}종 기능 수록)  •  [⚙️ 통합 설정 (/설정) 열기] 버튼으로 즉시 실행"
        )
        return embed

    # 2. 상세 카드 보기 (카테고리 / 권한 필터 / 검색어 / 페이지 이동)
    filtered = _filter_catalog(category=category, search_kw=search_kw, perm_filter=perm_filter)

    if not filtered:
        embed = discord.Embed(
            title="🔍 도움말 검색 결과 없음",
            description=(
                f"{header_links}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ 요청하신 조건(검색어: `{search_kw or '없음'}` / 권한: `{PERM_BADGE_MAP.get(perm_filter, '전체')}`)과 일치하는 기능이 없습니다.\n\n"
                "💡 **추천 검색어:** `설정`, `마스터랭크`, `원신`, `스타레일`, `낚시`, `농장`, `인생`, `티켓`, `임시음성방`, `이모지업스케일`\n"
                "👉 아래 **`[🏠 전체 요약]`** 버튼을 눌러 전체 카테고리를 확인해 보세요!"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="norosi Help Assistant  •  /설정 으로 모든 기능을 버튼으로 실행할 수 있습니다.")
        return embed

    per_page = 4
    total_pages = max(1, math.ceil(len(filtered) / per_page))

    is_all_unfiltered = (category == "all" and not search_kw.strip() and perm_filter == "all" and page > 0)
    eff_page = (page - 1) if is_all_unfiltered else page
    eff_page = max(0, min(eff_page, total_pages - 1))

    start_i = eff_page * per_page
    page_items = filtered[start_i : start_i + per_page]

    cat_header = "🌟 전체 기능 상세" if category == "all" else page_items[0]["cat_label"]
    perm_header = "👥 전체 권한" if perm_filter == "all" else PERM_BADGE_MAP.get(perm_filter, "👥 전체")
    display_curr_page = eff_page + 1

    desc_lines = [
        header_links,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📂 **분류:** **{cat_header}**  ·  🔐 **권한 필터:** **{perm_header}**",
        f"📄 **표시 범위:** 총 **`{len(filtered)}개`** 중 **`{start_i + 1}~{start_i + len(page_items)}번째`**  (페이지 **`{display_curr_page} / {total_pages}`**)",
        "💡 *모든 기능은 `/설정`으로 통합되었으며, 각 항목 우측의 **`⚙️ /설정 위치`** 버튼을 눌러 즉시 실행할 수 있습니다.*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    embed = discord.Embed(
        title=f"📖 norosi 상세 도움말 — {cat_header}",
        description="\n".join(desc_lines),
        color=discord.Color.from_rgb(0, 204, 221),
        timestamp=datetime.datetime.now(core.KST),
    )

    for item in page_items:
        perm_key = item.get("perm", "user")
        perm_tag = PERM_SHORT_BADGE.get(perm_key, "[👤일반]")
        settings_loc = item.get("settings_path") or "⚙️ /설정 허브"
        cmd_label = item["name"] if item["name"] in ("/설정", "/도움말") else f"{item['name'].lstrip('/')} (통합됨)"
        field_name = f"🔹 `{cmd_label}`  {perm_tag}  ·  📍 `{settings_loc}`"
        field_value = (
            f"> {item['desc']}\n"
            f"• **실행 위치:** `{settings_loc}`  ｜  **세부 기능:** `{item['params']}`"
        )
        embed.add_field(name=field_name, value=field_value, inline=False)

    embed.set_footer(
        text=f"페이지 {display_curr_page}/{total_pages} (총 {len(filtered)}개)  •  [🏠 전체 요약]으로 홈 복귀  •  [⚙️ 통합 설정 (/설정)]으로 즉시 실행"
    )
    return embed


class HelpCategorySelect(discord.ui.Select):
    """13대 카테고리 선택 드롭다운"""
    def __init__(self, parent_view: "HelpCategoryView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="📂 열람할 기능 카테고리를 선택하세요 (전체 13대 분류)...",
            min_values=1,
            max_values=1,
            options=self._build_options(parent_view.category),
            row=0,
        )

    def _build_options(self, current_cat: str):
        opts = []
        for val, label, desc, emoji in CATEGORY_DROPDOWN_OPTIONS:
            opts.append(
                discord.SelectOption(
                    label=label[:100],
                    value=val,
                    description=desc[:100],
                    emoji=emoji,
                    default=(val == current_cat),
                )
            )
        return opts

    def refresh_options(self):
        self.options = self._build_options(self.parent_view.category)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.category = self.values[0]
        self.parent_view.search_kw = ""
        self.parent_view.page = 0
        self.refresh_options()
        self.parent_view.update_buttons()
        embed = build_help_embed(
            self.parent_view.category,
            self.parent_view.search_kw,
            self.parent_view.page,
            self.parent_view.perm_filter,
        )
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class HelpCategoryView(core.SafeView):
    """페이지네이션(◀/▶), 권한별 필터(일반/관리자/봇주인), 통합 설정(/설정) 바로가기를 지원하는 도움말 뷰"""
    def __init__(
        self,
        bot_instance=None,
        category: str = "all",
        search_kw: str = "",
        author=None,
        perm_filter: str = "all",
    ):
        super().__init__(timeout=600)
        self.bot_instance = bot_instance
        self.category = category
        self.search_kw = search_kw
        self.author = author
        self.perm_filter = perm_filter
        self.page = 0
        self.category_select = HelpCategorySelect(self)
        self.add_item(self.category_select)
        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author and interaction.user.id != self.author.id:
            await core.safe_send_response(
                interaction,
                content="❌ 도움말을 호출한 본인만 버튼을 조작할 수 있습니다. (`/도움말` 또는 `/설정`을 입력해 보세요!)",
                ephemeral=True,
            )
            return False
        return True

    def _get_filtered(self):
        return _filter_catalog(
            category=self.category,
            search_kw=self.search_kw,
            perm_filter=self.perm_filter,
        )

    def _total_pages(self) -> int:
        filtered = self._get_filtered()
        return max(1, math.ceil(len(filtered) / 4))

    def _max_page(self) -> int:
        if self.category == "all" and not self.search_kw.strip() and self.perm_filter == "all":
            return math.ceil(len(COMMAND_CATALOG) / 4)
        return max(0, math.ceil(len(self._get_filtered()) / 4) - 1)

    def update_buttons(self):
        max_p = self._max_page()
        total_p = self._total_pages()
        is_all_home_capable = (self.category == "all" and not self.search_kw.strip() and self.perm_filter == "all")

        # 권한 필터 버튼 하이라이트
        self.perm_all_btn.style = discord.ButtonStyle.primary if self.perm_filter == "all" else discord.ButtonStyle.secondary
        self.perm_user_btn.style = discord.ButtonStyle.primary if self.perm_filter == "user" else discord.ButtonStyle.secondary
        self.perm_admin_btn.style = discord.ButtonStyle.primary if self.perm_filter == "admin" else discord.ButtonStyle.secondary
        self.perm_owner_btn.style = discord.ButtonStyle.primary if self.perm_filter == "owner" else discord.ButtonStyle.secondary

        if is_all_home_capable:
            if self.page == 0:
                self.prev_page_btn.disabled = True
                self.next_page_btn.disabled = False
                self.page_indicator_btn.label = f"🏠 요약 홈 (상세 {total_p}p)"
            else:
                self.prev_page_btn.disabled = False
                self.next_page_btn.disabled = (self.page >= max_p)
                self.page_indicator_btn.label = f"📄 {self.page} / {total_p}"
        else:
            self.prev_page_btn.disabled = (self.page <= 0)
            self.next_page_btn.disabled = (self.page >= max_p)
            self.page_indicator_btn.label = f"📄 {self.page + 1} / {total_p}"

    # Row 1: 권한 등급별 원클릭 필터 (일반 이용자 / 서버 관리자 / 봇 주인 명확 구분)
    @discord.ui.button(label="👥 전체 권한", style=discord.ButtonStyle.primary, row=1)
    async def perm_all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.perm_filter = "all"
        self.page = 0 if self.category != "all" else 1
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page, self.perm_filter)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="👤 일반 이용자", style=discord.ButtonStyle.secondary, row=1)
    async def perm_user_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.perm_filter = "user"
        self.page = 0
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page, self.perm_filter)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🛡️ 서버 관리자", style=discord.ButtonStyle.secondary, row=1)
    async def perm_admin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.perm_filter = "admin"
        self.page = 0
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page, self.perm_filter)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="👑 봇 주인", style=discord.ButtonStyle.secondary, row=1)
    async def perm_owner_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.perm_filter = "owner"
        self.page = 0
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page, self.perm_filter)
        await interaction.response.edit_message(embed=embed, view=self)

    # Row 2: 페이지네이션 & 통합 설정(/설정) 바로가기
    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=2)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page, self.perm_filter)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def page_indicator_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_p = self._max_page()
        self.page = min(max_p, self.page + 1)
        self.update_buttons()
        embed = build_help_embed(self.category, self.search_kw, self.page, self.perm_filter)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏠 전체 요약", style=discord.ButtonStyle.primary, row=2)
    async def home_summary_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "all"
        self.search_kw = ""
        self.perm_filter = "all"
        self.page = 0
        self.category_select.refresh_options()
        self.update_buttons()
        embed = build_help_embed("all", "", 0, "all")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⚙️ 통합 설정 (/설정) 열기", style=discord.ButtonStyle.success, row=2)
    async def open_quick_menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        bot_ref = self.bot_instance or interaction.client
        data = await asyncio.to_thread(core.load_data)
        from cogs.dashboard import MasterDashboardView
        view = MasterDashboardView(bot_ref, interaction.user, interaction.guild, data)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="도움말",
        description="📖 norosi 통합 도움말 — /설정(일반·고급·미니게임·개인) 구조 및 권한별(일반·관리자·봇주인) 상세 가이드",
    )
    @app_commands.describe(
        category="열람할 카테고리 선택 (전체 요약 / 통합 설정 / 가챠 / 낚시 / 경제 / 생활 / 인생 / 티켓 / 음악 등)",
        search="검색할 명령어 이름 또는 키워드 (예: 설정, 마스터랭크, 원신, 스타레일, 낚시, 농장, 인생, 티켓)",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="🌟 전체 요약 & /설정 가이드 (홈)", value="all"),
            app_commands.Choice(name="⚙️ 통합 설정(/설정) & 서버 관리", value="admin"),
            app_commands.Choice(name="🎮 출석 & 프로세카 가챠", value="cards"),
            app_commands.Choice(name="🌠 원신 기원 & 도감 & 상점", value="genshin"),
            app_commands.Choice(name="🚄 스타레일 워프 & 아카이브 & 상점", value="hsr"),
            app_commands.Choice(name="🎣 통합 낚시 & 주말·제철 대회", value="fishing"),
            app_commands.Choice(name="💳 통합 경제 & 프로필카드 & 칭호", value="economy"),
            app_commands.Choice(name="🌾 농장 & 공동농장 & 펫 & 요리", value="life"),
            app_commands.Choice(name="👶 타인의 삶 — 인생 시뮬레이션", value="other_life"),
            app_commands.Choice(name="🎫 1:1 티켓 & 임시음성방 & 커뮤니티 방어", value="tickets"),
            app_commands.Choice(name="📅 D-Day & 생일 & 스터디·목표", value="dday"),
            app_commands.Choice(name="🎲 미니게임 & 파티 모집 & 날씨", value="games"),
            app_commands.Choice(name="📊 서버/유저 통계 & 건의 & 봇상태", value="stats"),
            app_commands.Choice(name="🎵 음악 & 플레이리스트 & 음성재생", value="music"),
        ]
    )
    async def help_cmd(
        self,
        interaction: discord.Interaction,
        category: Optional[app_commands.Choice[str]] = None,
        search: Optional[str] = "",
    ):
        await core.safe_defer(interaction, ephemeral=True)
        cat_val = category.value if category else "all"
        embed = build_help_embed(category=cat_val, search_kw=search or "", page=0, perm_filter="all")
        view = HelpCategoryView(
            bot_instance=self.bot,
            category=cat_val,
            search_kw=search or "",
            author=interaction.user,
            perm_filter="all",
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @commands.command(name="도움말", aliases=["help", "도움", "명령어", "가이드"])
    async def prefix_help(self, ctx: commands.Context, *, 검색: Optional[str] = ""):
        """채팅창에 !도움말 또는 !help 입력 시 즉시 통합 도움말 & /설정 가이드 호출"""
        embed = build_help_embed(category="all", search_kw=검색 or "", page=0, perm_filter="all")
        view = HelpCategoryView(
            bot_instance=self.bot,
            category="all",
            search_kw=검색 or "",
            author=ctx.author,
            perm_filter="all",
        )
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    bot.remove_command("help")
    await bot.add_cog(HelpCog(bot))
