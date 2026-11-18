#!/usr/bin/env python3
# ==============================================================================
# norosi 디스코드 봇 - 슬래시 명령어 전체(17대 Cogs · 83개 루트 / 129종 기능) 강제 재등록 유틸리티 (force_resync.py)
# ==============================================================================
import os
import sys
import time
import asyncio

# 메인 디렉토리 sys.path 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ⚡ 가상환경(venv) 자동 재전환 (시스템 파이썬으로 실행 시 venv 인터프리터로 재실행)
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")
VENV_PYTHON_WIN = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
HOME_VENV = os.path.join(os.path.expanduser("~"), "norosi", "venv", "bin", "python3")

target_venv = None
for p in (VENV_PYTHON, VENV_PYTHON_WIN, HOME_VENV):
    if os.path.exists(p):
        target_venv = p
        break

if target_venv and os.path.abspath(sys.executable) != os.path.abspath(target_venv):
    os.execv(target_venv, [target_venv] + sys.argv)

import discord
from discord.ext import commands

# ⚡ 외부 dotenv 패키지 없이 무의존성 .env 자체 파싱
def load_env_natively():
    env_paths = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.expanduser("~"), "norosi", ".env"),
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
                break
            except Exception:
                pass

load_env_natively()

# 파이썬-dotenv 패키지가 존재하는 경우 보조 로드
try:
    import dotenv
    dotenv.load_dotenv()
except Exception:
    pass

import core

TOKEN = core.TOKEN
if not TOKEN or TOKEN == "여기에_디스코드_봇_토큰_입력":
    print("❌ .env 파일에서 유효한 DISCORD_TOKEN을 찾을 수 없습니다. ~/norosi/.env 파일을 확인하세요.")
    sys.exit(1)

ALL_COG_EXTENSIONS = (
    "cogs.gacha",
    "cogs.genshin",
    "cogs.hsr",
    "cogs.fishing",
    "cogs.economy",
    "cogs.life",
    "cogs.other_life",
    "cogs.tickets",
    "cogs.community",
    "cogs.music",
    "cogs.dday",
    "cogs.logger",
    "cogs.ai",
    "cogs.stats",
    "cogs.roles",
    "cogs.emoji_upscale",
    "cogs.help",
    "cogs.dashboard",
)


class ForceSyncBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def is_bot_owner_user(self, user: discord.abc.User) -> bool:
        return await self.is_owner(user)

    async def setup_hook(self):
        print(f"📦 [1/3] {len(ALL_COG_EXTENSIONS)}대 Cogs 모듈 전체 로드 중...", flush=True)
        for idx, ext in enumerate(ALL_COG_EXTENSIONS, start=1):
            t0 = time.perf_counter()
            before_cnt = len(self.tree.get_commands())
            await self.load_extension(ext)
            after_cnt = len(self.tree.get_commands())
            dt_ms = (time.perf_counter() - t0) * 1000.0
            print(f"   ✓ [{idx:02d}/{len(ALL_COG_EXTENSIONS)}] {ext:<18} 로드 완료 ({dt_ms:6.1f}ms | 슬래시 +{after_cnt - before_cnt}개)")

    async def on_ready(self):
        print(f"✅ [2/3] Discord 로그인 성공: {self.user} (ID: {self.user.id})", flush=True)
        print("🧹 [3/3] 슬래시 명령어 캐시 완전 초기화 및 전체 재등록 시작...", flush=True)

        try:
            # 1. 연결된 모든 서버의 길드 캐시 명령어 완전 삭제
            cleared_guilds = 0
            for guild in self.guilds:
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    cleared_guilds += 1
                except Exception as ge:
                    print(f"   ⚠️ 길드({guild.name}) 캐시 정리 오류: {ge}")

            # 2. 글로벌 슬래시 명령어 트리 완전 재등록
            synced_cmds = await self.tree.sync()
            total_sub = sum(len(getattr(c, "options", []) or []) for c in synced_cmds)
            print("====================================================================")
            print(f"🎉 슬래시 명령어 동기화 성공: 루트 {len(synced_cmds)}개 (세부 옵션/서브커맨드 포함 {total_sub}개) 등록 완료!")
            print(f"   (정리된 서버 수: {cleared_guilds}곳 / 로드된 Cogs: {len(ALL_COG_EXTENSIONS)}개)")
            print("====================================================================")
            print("📋 등록된 슬래시 명령어 전체 목록:")
            for idx, cmd in enumerate(synced_cmds, start=1):
                print(f"   [{idx:02d}/{len(synced_cmds):02d}] /{cmd.name:<16} : {(cmd.description or '')[:44]}")
            print("====================================================================")
            print("💡 디스코드 앱에서 Ctrl + R (새로고침)을 누르면 즉시 명령어가 나타납니다!")

        except Exception as e:
            print(f"❌ 명령어 동기화 실패: {e}")
        finally:
            await self.close()

async def main():
    bot = ForceSyncBot()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())

