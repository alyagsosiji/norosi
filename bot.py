import os
import sys
import copy
import time
import asyncio
import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional, List, Dict, Any, Union
from aiohttp import web
import core
from cogs.music import MusicRecommendView


# ==========================================
# 메인 봇 클라이언트 및 스케줄러 (norosi)
# ==========================================
class NorosiBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        intents.invites = True
        intents.moderation = True
        intents.emojis_and_stickers = True
        intents.guilds = True
        intents.reactions = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.start_time = datetime.datetime.now(core.KST)
        self._commands_synced = False
        self._web_started = False

    async def is_bot_owner_user(self, user: discord.abc.User) -> bool:
        if not user:
            return False
        if core.BOT_OWNER_ID and user.id == core.BOT_OWNER_ID:
            return True
        extra_owners = os.getenv("BOT_OWNER_IDS", "")
        if extra_owners:
            try:
                owner_id_list = [int(i.strip()) for i in extra_owners.split(",") if i.strip().isdigit()]
                if user.id in owner_id_list:
                    return True
            except Exception:
                pass
        try:
            return await self.is_owner(user)
        except Exception:
            return False

    async def handle_health_check(self, request):
        return web.Response(text="norosi Bot is running 24/7!")

    async def start_web_server(self):
        if self._web_started:
            return
        try:
            app = web.Application()
            app.router.add_get("/", self.handle_health_check)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", core.PORT)
            await site.start()
            self._web_started = True
            print(f"✅ norosi 헬스체크 웹 서버 가동 완료 (포트: {core.PORT})", flush=True)
        except Exception as e:
            print(f"ℹ️ 웹 서버 시작 건너뜀 (포트 {core.PORT} 점유 중이거나 불필요 환경): {e}", flush=True)

    async def setup_hook(self):
        print("📦 [1/4] 데이터 캐시 로드 중...", flush=True)
        await asyncio.to_thread(core.load_data)

        # 글로벌 슬래시 커맨드 에러 핸들러 등록 ("명령어 응답 안함" 3초 타임아웃 차단)
        self.tree.on_error = self.on_app_command_error

        print("🔌 [2/4] Cogs 확장 모듈 등록 중 (gacha, music, dday, logger, ai, stats, roles, help)...", flush=True)
        ext_list = [
            "cogs.gacha",
            "cogs.music",
            "cogs.dday",
            "cogs.logger",
            "cogs.ai",
            "cogs.stats",
            "cogs.roles",
            "cogs.help",
        ]
        for ext in ext_list:
            try:
                if ext in self.extensions:
                    await self.reload_extension(ext)
                else:
                    await self.load_extension(ext)
            except Exception as e:
                print(f"⚠️ [{ext}] 확장 모듈 로드 예외: {e}", flush=True)
                raise

        # 등록된 반응역할 메시지의 Persistent View 동적 복원 (버튼 상호작용 영구 작동)
        try:
            from cogs.roles import PersistentReactionRoleView
            cached_d = core.get_cached_data()
            restored_cnt = 0
            for mid_s, cfg in cached_d.get("reaction_roles", {}).items():
                r_list = cfg.get("roles", [])
                if r_list and mid_s.isdigit():
                    self.add_view(PersistentReactionRoleView(r_list), message_id=int(mid_s))
                    restored_cnt += 1
            if restored_cnt > 0:
                print(f"🎭 반응역할 지속 View {restored_cnt}개 복원 완료", flush=True)
        except Exception as e:
            print(f"ℹ️ 반응역할 지속 View 복원 건너뜀: {e}", flush=True)


        print("📚 [3/4] 프로세카 한섭 DB 백그라운드 캐시 워밍 시작...", flush=True)
        asyncio.create_task(asyncio.to_thread(core.load_proseka_kr_db))

        print("⏰ [4/4] 4대 상주 스케줄러 루프 활성화...", flush=True)
        if not self.midnight_tasks.is_running():
            self.midnight_tasks.start()
        if not self.morning_music_alert.is_running():
            self.morning_music_alert.start()
        if not self.morning_text_alert.is_running():
            self.morning_text_alert.start()
        if not self.custom_music_schedules_loop.is_running():
            self.custom_music_schedules_loop.start()


    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """슬래시 명령어 처리 중 예외 발생 시 디스코드 타임아웃('응답 안함')을 원천 차단하는 에러 핸들러"""
        cmd_name = interaction.command.name if interaction.command else '알 수 없음'
        print(f"⚠️ [슬래시 커맨드 예외 포착] /{cmd_name}: {error}", flush=True)
        
        if isinstance(error, app_commands.MissingPermissions):
            err_msg = "❌ 이 명령어를 실행할 관리자/서버 권한이 부족합니다."
        elif isinstance(error, app_commands.BotMissingPermissions):
            err_msg = "🚨 봇에게 이 작업을 수행할 채널/서버 권한이 부족합니다."
        elif isinstance(error, app_commands.CommandOnCooldown):
            err_msg = f"⏳ **쿨다운 중:** {error.retry_after:.1f}초 후에 다시 시도해 주세요."
        else:
            err_msg = f"⚠️ `/{cmd_name}` 명령어 처리 중 일시적인 예외가 발생했습니다: `{error}`"

        try:
            if interaction.response.is_done():
                await interaction.followup.send(err_msg, ephemeral=True)
            else:
                await interaction.response.send_message(err_msg, ephemeral=True)
        except Exception as e:
            print(f"❌ [에러 메시지 송신 예외]: {e}", flush=True)

    async def resolve_channel(self, channel_id):
        """캐시 미스 시에도 채널을 안전하게 가져오는 헬퍼 (get_channel -> fetch_channel 폴백)"""
        if not channel_id:
            return None
        try:
            cid = int(channel_id)
        except (ValueError, TypeError):
            return None
        ch = self.get_channel(cid)
        if ch:
            return ch
        try:
            return await self.fetch_channel(cid)
        except Exception:
            return None

    async def on_ready(self):
        fb_status = "연동됨" if core.get_firebase_endpoint() else "로컬 + 인메모리 캐시 모드"
        print(f"✅ 로그인 완료: {self.user} (이름: norosi | ID: {self.user.id}) | 저장소: {fb_status}", flush=True)

        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="🌠ㅣ/메뉴 · /출석체크 · /도움말")
        )

        if not self._commands_synced:
            try:
                print("🔄 [명령어 동기화 시작] 길드 즉시 반영(0초 노출) 및 글로벌 슬래시 명령어 동기화 진행 중...", flush=True)

                # 1. 각 길드에 글로벌 명령어를 복사하여 즉시 0초 반영 (디스코드 전역 캐시 1시간 지연 방지)
                for guild in self.guilds:
                    try:
                        self.tree.copy_global_to(guild=guild)
                        await self.tree.sync(guild=guild)
                        print(f"⚡ [{guild.name}] 길드 슬래시 명령어 즉시 반영 완료", flush=True)
                    except Exception as ge:
                        print(f"⚠️ [{guild.name}] 길드 즉시 동기화 알림: {ge}", flush=True)

                # 2. 전역(글로벌) 슬래시 명령어 동기화 병행
                synced_cmds = await self.tree.sync()
                self._commands_synced = True
                print(
                    f"✅ [동기화 완료] 슬래시 명령어 총 {len(synced_cmds)}개 전역 및 길드 등록 완료!",
                    flush=True
                )
                print(f"📋 등록된 슬래시 명령어 {len(synced_cmds)}종 목록:", flush=True)
                for idx, cmd in enumerate(synced_cmds, start=1):
                    print(f"   [{idx:02d}/{len(synced_cmds)}] /{cmd.name} : {cmd.description[:35]}", flush=True)

            except Exception as e:
                print(f"⚠️ 명령어 동기화 오류: {e}", flush=True)

        await self.update_all_dday_channels()

    async def on_guild_join(self, guild: discord.Guild):
        """새 디스코드 서버에 초대되었을 때 길드 명령어 캐시를 비우고 글로벌 명령어만 깔끔하게 단일 노출"""
        try:
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"✅ 신규 서버 입장 및 중복 길드 명령어 클린업 완료: {guild.name} ({guild.id})", flush=True)
        except Exception as e:
            print(f"⚠️ 신규 서버 명령어 클린업 오류 ({guild.name}): {e}", flush=True)

    async def update_all_dday_channels(self):
        data = await asyncio.to_thread(core.load_data)
        ddays = data.get("ddays", {})
        if not ddays:
            return

        alert_ch_id = data.get("settings", {}).get("dday_alert_channel_id")
        alert_channel = await self.resolve_channel(alert_ch_id) if alert_ch_id else None

        for name, info in ddays.items():
            ch_id = info.get("channel_id")
            if not ch_id:
                continue
            channel = await self.resolve_channel(ch_id)
            if not channel or "date" not in info:
                continue

            emoji = info.get("emoji", "🌠")
            new_name = core.format_dday_channel_name(name, info["date"], emoji)
            if getattr(channel, "name", None) != new_name:
                try:
                    await channel.edit(name=new_name)
                except discord.Forbidden:
                    if alert_channel:
                        try:
                            await alert_channel.send(
                                f"🚨 **권한 오류:** 봇에게 `{channel.name}` 채널의 **'채널 관리'** 권한이 없습니다."
                            )
                        except Exception:
                            pass
                except Exception as e:
                    print(f"전광판 업데이트 오류 ({name}): {e}", flush=True)

        plat = track_info.get("platform", "YouTube")
        p_meta = core.PLAYLIST_PLATFORMS.get(plat, core.PLAYLIST_PLATFORMS["YouTube"])
        r, g, b = p_meta["color"]
        embed_color = discord.Color.from_rgb(r, g, b)

        if custom_title:
            title_prefix = f"🎧 {custom_title}"
        else:
            title_prefix = "🎧 오늘의 모닝 추천 음악" if is_morning else "🎧 세카이 감성 추천 음악"

        embed = discord.Embed(
            title=f"{title_prefix} ({p_meta['label']})",
            description=(
                f"### [{track_info['title']}]({track_info['url']})\n"
                f"🎤 **아티스트:** `{track_info['artist']}`\n"
                f"🌐 **플랫폼:** `{p_meta['label']}`"
            ),
            color=embed_color,
            url=track_info["url"],
            timestamp=datetime.datetime.now(core.KST)
        )

        if prefs.get("playlist_url"):
            footer_text = "추천 방식: 지정 플레이리스트 내 랜덤 선곡"
        else:
            cond = []
            if prefs.get("genre"):
                cond.append(f"장르: {prefs['genre']}")
            if prefs.get("artist"):
                cond.append(f"아티스트: {prefs['artist']}")
            footer_text = "추천 조건: " + ", ".join(cond) if cond else "추천 방식: 요일·시간대별 감성 자동 맞춤"

        embed.set_footer(text=f"{footer_text} • 하단 ❤️ 버튼으로 내 보관함에 저장 가능")
        if track_info.get("image"):
            embed.set_thumbnail(url=track_info["image"])

        view = MusicRecommendView(track_info, self, prefs, is_morning=is_morning)
        return embed, view

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=core.KST))
    async def midnight_tasks(self):
        await asyncio.to_thread(core.load_proseka_kr_db)

        data = await asyncio.to_thread(core.load_data)
        today = datetime.datetime.now(core.KST).date()
        updated = False

        for name, info in data.get("ddays", {}).items():
            if info.get("repeat"):
                date_val = info.get("date")
                if not date_val:
                    continue
                try:
                    t_date = datetime.datetime.strptime(date_val, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if t_date < today:
                    old_target_str = date_val
                    while t_date < today:
                        try:
                            t_date = t_date.replace(year=t_date.year + 1)
                        except ValueError:
                            t_date += datetime.timedelta(days=365)
                    info["date"] = t_date.strftime("%Y-%m-%d")
                    info["start_date"] = old_target_str
                    updated = True

        # 자정(00:00 KST) 멤버 생일 자동 축하 및 +500 크리스탈 지급
        bday_map = data.get("birthdays", {})
        alert_ch_id = data.get("settings", {}).get("dday_alert_channel_id")
        alert_ch = await self.resolve_channel(alert_ch_id) if alert_ch_id else None

        for u_key, b_info in bday_map.items():
            if not isinstance(b_info, dict):
                continue
            if b_info.get("month") == today.month and b_info.get("day") == today.day:
                if b_info.get("last_celebrated_year") != today.year:
                    b_info["last_celebrated_year"] = today.year
                    uid = b_info.get("user_id") or int(u_key)
                    uname = b_info.get("user_name", "멤버")
                    prof = core.ensure_user_profile(data, u_key, uname)
                    prof["crystals"] = prof.get("crystals", 0) + 500
                    updated = True

                    bday_embed = discord.Embed(
                        title=f"🎂 Happy Birthday! 오늘은 {uname}님의 생일입니다! 🎉",
                        description=(
                            f"🎊 <@{uid}>님, 일 년에 단 한 번뿐인 소중한 생일을 진심으로 축하드립니다!\n"
                            f"🎁 **세카이 생일 축하 보너스:** **`+500 💎 크리스탈`**이 지급되었습니다! (보유: `{prof['crystals']:,}💎`)"
                            + (f"\n💬 **생일 소원:** *\"{b_info['memo']}\"*" if b_info.get("memo") else "")
                        ),
                        color=discord.Color.from_rgb(255, 105, 180),
                        timestamp=datetime.datetime.now(core.KST)
                    )
                    if alert_ch:
                        try:
                            await alert_ch.send(content=f"🎉 <@{uid}>님 생일 축하합니다!!", embed=bday_embed)
                        except Exception:
                            pass
                    try:
                        user_obj = self.get_user(uid) or await self.fetch_user(uid)
                        if user_obj:
                            await user_obj.send(embed=bday_embed)
                    except Exception:
                        pass

        if updated:
            await asyncio.to_thread(core.save_data, data)

        await self.update_all_dday_channels()

    @midnight_tasks.before_loop
    async def before_midnight_tasks(self):
        await self.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=7, minute=0, tzinfo=core.KST))
    async def morning_music_alert(self):
        data = await asyncio.to_thread(core.load_data)
        prefs = data.get("music_prefs", core.DEFAULT_CONFIG["music_prefs"])
        target_ch_id = prefs.get("channel_id") or data.get("settings", {}).get("dday_alert_channel_id")
        if not target_ch_id:
            return

        channel = await self.resolve_channel(target_ch_id)
        if not channel:
            return

        track_info, error = await core.get_recommended_music(prefs)
        if error or not track_info:
            try:
                await channel.send(f"🎧 **오늘의 음악 추천 실패:** {error}")
            except Exception:
                pass
            return
        embed, view = self.build_music_embed_and_view(track_info, prefs, is_morning=True)
        try:
            await channel.send("☀️ **좋은 아침입니다! 오늘의 추천 곡을 확인해 보세요.**", embed=embed, view=view)
        except Exception:
            pass

    @morning_music_alert.before_loop
    async def before_morning_music_alert(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def custom_music_schedules_loop(self):
        now = datetime.datetime.now(core.KST)
        now_hm = now.strftime("%H:%M")
        today_str = now.strftime("%Y-%m-%d")

        data = await asyncio.to_thread(core.load_data)
        schedules = data.get("music_schedules", [])
        reminders = data.get("reminders", [])
        if not schedules and not reminders:
            return

        updated = False
        base_prefs = data.get("music_prefs", core.DEFAULT_CONFIG["music_prefs"])

        for sched in schedules:
            if sched.get("time") == now_hm and sched.get("last_sent") != today_str:
                ch_id = sched.get("channel_id")
                channel = await self.resolve_channel(ch_id) if ch_id else None
                if channel:
                    custom_prefs = copy.deepcopy(base_prefs)
                    if sched.get("genre"):
                        custom_prefs["genre"] = sched["genre"]
                        custom_prefs["playlist_url"] = None
                    track_info, err = await core.get_recommended_music(custom_prefs)
                    if track_info and not err:
                        label = sched.get("name") or f"{now_hm} 맞춤 추천 음악"
                        embed, view = self.build_music_embed_and_view(track_info, custom_prefs, custom_title=label)
                        try:
                            await channel.send(f"⏰ **`{label}` 시간이 되어 추천 곡이 도착했습니다!**", embed=embed, view=view)
                        except Exception:
                            pass
                sched["last_sent"] = today_str
                updated = True

        # /알림예약 개인 알리미 시각 도달 체크 및 발송
        now_ts = time.time()
        remaining_reminders = []
        for rem in reminders:
            if not isinstance(rem, dict):
                continue
            if rem.get("trigger_ts", 0) <= now_ts:
                updated = True
                uid = rem.get("user_id")
                ch_id = rem.get("channel_id")
                mode = rem.get("mode", "both")
                content_text = rem.get("content", "예약된 알림입니다.")

                rem_embed = discord.Embed(
                    title="⏰ 예약하신 스마트 알림 시간이 되었습니다!",
                    description=(
                        f"👤 **대상:** <@{uid}>\n"
                        f"📝 **알림 내용:**\n> **{content_text}**\n\n"
                        f"🕒 **예약 시각:** `{rem.get('trigger_str', '-')}`"
                    ),
                    color=discord.Color.from_rgb(0, 204, 221),
                    timestamp=now
                )
                rem_embed.set_footer(text="norosi 스마트 개인 알리미 (/알림예약)")

                sent_dm = False
                if mode in ("both", "dm") and uid:
                    try:
                        u_obj = self.get_user(uid) or await self.fetch_user(uid)
                        if u_obj:
                            await u_obj.send(content=f"🔔 <@{uid}>님, 예약하신 알림이 도착했습니다!", embed=rem_embed)
                            sent_dm = True
                    except Exception:
                        pass

                if mode in ("both", "channel") or (mode == "dm" and not sent_dm):
                    if ch_id:
                        ch_obj = await self.resolve_channel(ch_id)
                        if ch_obj:
                            try:
                                await ch_obj.send(content=f"🔔 <@{uid}>님, 예약하신 알림이 도착했습니다!", embed=rem_embed)
                            except Exception:
                                pass
            else:
                remaining_reminders.append(rem)

        if len(remaining_reminders) != len(reminders):
            data["reminders"] = remaining_reminders
            updated = True

        if updated:
            await asyncio.to_thread(core.save_data, data)

    @custom_music_schedules_loop.before_loop
    async def before_custom_music_loop(self):
        await self.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=core.KST))
    async def morning_text_alert(self):
        data = await asyncio.to_thread(core.load_data)
        today_str = core.get_today_str()

        # 1. 나만의 비밀 디데이 & 타임캡슐 개인 DM 발송 체크
        dm_updated = False
        for u_key, p_info in data.get("user_profiles", {}).items():
            secret_ddays = p_info.get("secret_ddays", {})
            for s_name, s_info in secret_ddays.items():
                try:
                    diff, _ = core.get_dday_info(s_info["date"])
                except Exception:
                    continue
                if diff == 0 and s_info.get("notified_date") != today_str:
                    try:
                        target_user = self.get_user(int(u_key)) or await self.fetch_user(int(u_key))
                        if target_user:
                            memo_text = s_info.get("memo") or "등록된 타임캡슐 메시지가 없습니다."
                            dm_embed = discord.Embed(
                                title=f"💌 비밀 디데이 & 타임캡슐 도착: {s_name}",
                                description=(
                                    f"오늘(**{s_info['date']}**)은 설정해 두신 **`{s_name}`** D-Day입니다!\n"
                                    f"└ {core.get_galaxy_progress_bar(s_info.get('start_date', today_str), s_info['date'])}\n\n"
                                    f"📜 **타임캡슐 메시지**\n> {memo_text}"
                                ),
                                color=discord.Color.from_rgb(255, 105, 180),
                                timestamp=datetime.datetime.now(core.KST)
                            )
                            await target_user.send(embed=dm_embed)
                            s_info["notified_date"] = today_str
                            dm_updated = True
                    except Exception as e:
                        print(f"⚠️ 비밀 디데이 DM 전송 실패 ({u_key}): {e}", flush=True)

        # 2. 파트너 공동 D-Day 당일 두 사람에게 DM 발송 체크
        for pair_key, pair_info in data.get("partners", {}).items():
            uid_parts = pair_key.split("_")
            if len(uid_parts) != 2:
                continue
            for p_dday_name, p_dday_info in pair_info.get("ddays", {}).items():
                try:
                    diff, _ = core.get_dday_info(p_dday_info["date"])
                except Exception:
                    continue
                if diff == 0 and p_dday_info.get("notified_date") != today_str:
                    for uid_str in uid_parts:
                        try:
                            u_obj = self.get_user(int(uid_str)) or await self.fetch_user(int(uid_str))
                            if u_obj:
                                p_embed = discord.Embed(
                                    title=f"💑 파트너 공동 D-Day 알림: {p_dday_name}",
                                    description=(
                                        f"오늘(**{p_dday_info['date']}**)은 파트너와 함께 등록한 **`{p_dday_name}`** D-Day입니다! 🎉\n"
                                        f"└ {core.get_galaxy_progress_bar(p_dday_info.get('start_date', today_str), p_dday_info['date'])}"
                                    ),
                                    color=discord.Color.from_rgb(255, 105, 180),
                                    timestamp=datetime.datetime.now(core.KST)
                                )
                                await u_obj.send(embed=p_embed)
                        except Exception:
                            pass
                    p_dday_info["notified_date"] = today_str
                    dm_updated = True

        if dm_updated:
            await asyncio.to_thread(core.save_data, data)

        # 3. 서버 공개 오전 9시 D-Day 요약 알림
        alert_ch_id = data.get("settings", {}).get("dday_alert_channel_id")
        if not alert_ch_id:
            return

        channel = await self.resolve_channel(alert_ch_id)
        if not channel:
            return

        ddays = data.get("ddays", {})
        if not ddays:
            return

        embed = discord.Embed(
            title="📅 오늘의 은하수 D-Day 현황 브리핑",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        upcoming_lines, recent_past_lines = [], []
        archived_count = 0
        min_diff = 9999

        for name, info in sorted(ddays.items(), key=lambda x: x[1].get("date", "9999-12-31")):
            date_str = info.get("date")
            if not date_str:
                continue
            try:
                diff, text = core.get_dday_info(date_str)
            except Exception:
                continue
            display_name = f"{name} 🔄" if info.get("repeat") else name
            if diff >= 0:
                bar_str = core.get_galaxy_progress_bar(info.get("start_date", today_str), date_str)
                upcoming_lines.append(f"• **{display_name}** (`{date_str}`) — **`{text}`**\n  └ {bar_str}")
                if diff < min_diff:
                    min_diff = diff
            elif diff >= -7:
                recent_past_lines.append(f"• ~~{display_name} ({date_str})~~ : `{text}`")
            else:
                archived_count += 1

        core.add_chunked_embed_fields(
            embed,
            base_name="🌠 진행 중인 일정",
            lines=upcoming_lines,
            empty_text="예정된 일정이 없습니다.",
            separator="\n\n"
        )

        if recent_past_lines:
            core.add_chunked_embed_fields(
                embed,
                base_name="🕒 최근 지난 일정 (7일 이내)",
                lines=recent_past_lines,
                separator="\n"
            )

        if archived_count > 0:
            embed.set_footer(text=f"📦 7일 이상 경과한 지난 일정 {archived_count}개는 /지나간디데이 추억 보관소에서 확인할 수 있습니다.")

        embed.color = core.get_embed_color(min_diff if upcoming_lines else -1)
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"⚠️ 오전 9시 D-Day 알림 전송 오류: {e}", flush=True)

    @morning_text_alert.before_loop
    async def before_morning_text_alert(self):
        await self.wait_until_ready()


bot = NorosiBot()


# (글로벌 슬래시 명령어 에러 핸들러는 NorosiBot.setup_hook에서 self.tree.on_error = self.on_app_command_error로 통합 관리됨)


# ==========================================
# 봇 슬래시 명령어 동기화 컨트롤 뷰 (대화형 버튼 UI)
# ==========================================
class SyncControlView(core.SafeView):
    def __init__(self, author: discord.User, guild: Optional[discord.Guild]):
        super().__init__(timeout=180)
        self.author = author
        self.guild = guild
        self.message: Optional[discord.Message] = None

    async def _check_permission(self, interaction: discord.Interaction) -> bool:
        if await bot.is_bot_owner_user(interaction.user):
            return True
        await core.safe_send_response(interaction, "❌ 이 조작은 **봇주(Bot Owner)**만 가능합니다.", ephemeral=True)
        return False

    @discord.ui.button(label="⚡ 현재 서버에 즉시 반영 (0초 반영)", style=discord.ButtonStyle.success, emoji="⚡", row=0)
    async def instant_sync_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_permission(interaction):
            return

        await core.safe_defer(interaction)
        try:
            g_cnt = 0
            if self.guild:
                bot.tree.copy_global_to(guild=self.guild)
                synced_guild = await bot.tree.sync(guild=self.guild)
                g_cnt = len(synced_guild)

            synced_global = await bot.tree.sync()

            embed = discord.Embed(
                title="⚡ 슬래시 명령어 현재 서버에 0초 즉시 반영 완료!",
                description=(
                    f"✅ **현재 서버({self.guild.name if self.guild else '글로벌'})**에 슬래시 명령어 **`{g_cnt}개`**(반응역할 포함)가 0초 만에 즉시 등록되었습니다!\n"
                    f"👉 글로벌 슬래시 커맨드 총 **`{len(synced_global)}개`**도 전역 등록 완료되었습니다.\n\n"
                    "💡 지금 즉시 채팅창에서 `/`를 누르시면 모든 신규 명령어가 나타납니다!"
                ),
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text=f"[봇주 전용] 실행자: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"⚠️ 즉시 동기화 오류: `{e}`", ephemeral=True)

    @discord.ui.button(label="🌐 글로벌 전역 동기화", style=discord.ButtonStyle.primary, emoji="🌐", row=0)
    async def global_sync_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_permission(interaction):
            return

        await core.safe_defer(interaction)
        try:
            synced = await bot.tree.sync()
            embed = discord.Embed(
                title="🌐 글로벌 슬래시 명령어 전역 동기화 완료!",
                description=(
                    f"✅ **총 `{len(synced)}개`**의 슬래시 명령어가 Discord API에 글로벌 등록되었습니다.\n"
                    "모든 참가 서버에서 사용 가능합니다."
                ),
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text=f"[봇주 전용] 실행자: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"⚠️ 글로벌 동기화 오류: `{e}`", ephemeral=True)

    @discord.ui.button(label="🧹 중복 정리 & 글로벌 단일화", style=discord.ButtonStyle.secondary, emoji="🧹", row=1)
    async def clean_sync_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_permission(interaction):
            return

        await core.safe_defer(interaction)
        try:
            app_id = bot.application_id or (bot.application.id if bot.application else bot.user.id)
            if self.guild:
                try:
                    await bot.http.bulk_upsert_guild_commands(app_id, self.guild.id, [])
                except Exception as ex:
                    print(f"⚠️ bulk_upsert_guild_commands notice: {ex}", flush=True)
                bot.tree.clear_commands(guild=self.guild)
                try:
                    await bot.tree.sync(guild=self.guild)
                except Exception:
                    pass

            synced_global = await bot.tree.sync()

            embed = discord.Embed(
                title="✨ 슬래시 명령어 중복 정리 완료!",
                description=(
                    "✅ 현재 서버의 길드 전용 캐시를 비우고 글로벌 단일 세트로 정돈했습니다.\n"
                    f"👉 글로벌 슬래시 명령어: **`{len(synced_global)}개`**"
                ),
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text=f"[봇주 전용] 실행자: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"⚠️ 동기화 처리 중 오류: `{e}`", ephemeral=True)

    @discord.ui.button(label="🔄 모듈 핫 리로드 & 동기화", style=discord.ButtonStyle.danger, emoji="🔄", row=1)
    async def reload_sync_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_permission(interaction):
            return

        await core.safe_defer(interaction)
        reloaded = []
        failed = []
        for ext in list(bot.extensions.keys()):
            try:
                await bot.reload_extension(ext)
                reloaded.append(ext)
            except Exception as e:
                failed.append(f"{ext}: {e}")

        try:
            if self.guild:
                try:
                    bot.tree.clear_commands(guild=self.guild)
                    await bot.tree.sync(guild=self.guild)
                except Exception:
                    pass
            synced = await bot.tree.sync()
            sync_ok = f"글로벌 `{len(synced)}개` 명령어 갱신 완료"
        except Exception as e:
            sync_ok = f"동기화 오류: {e}"

        desc = [
            f"✅ **확장 모듈 `{len(reloaded)}개` 재로딩 완료:**",
            ", ".join(f"`{r}`" for r in reloaded),
            "",
            f"📡 **슬래시 동기화:** {sync_ok}"
        ]
        if failed:
            desc.append("\n⚠️ **재로딩 실패 모듈:**\n" + "\n".join(f"• {f}" for f in failed))

        embed = discord.Embed(
            title="🔄 봇 Cogs 확장 모듈 핫 리로드 & 동기화 완료!",
            description="\n".join(desc),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text=f"[봇주 전용] 실행자: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)


# ==========================================
# 봇 슬래시 명령어 동기화 마스터 (!싱크, !sync, !동기화)
# ==========================================
@bot.command(name="sync", aliases=["싱크", "동기화", "재동기화", "명령어동기화", "싱크초기화", "동기화초기화", "중복해결", "중복정리"])
async def sync_guild_command(ctx: commands.Context, *args):
    """
    [봇주 전용] 채팅창에 !sync 또는 !동기화 입력 시 현재 서버에 0초 즉시 슬래시 명령어 반영
    """
    # 권한 검사: 봇주(Bot Owner) 전용
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **봇주(Bot Owner)**만 사용할 수 있습니다.", delete_after=5)
        return

    mode = " ".join(args).strip().lower() if args else ""
    g_name = ctx.guild.name if ctx.guild else "개인 DM"

    status_msg = await ctx.send(f"⏳ **[{g_name}]** 슬래시 명령어 동기화 처리 중...")

    # 1. 핫 리로드 요청 (!싱크 리로드 / !sync reload)
    if any(k in mode for k in ("리로드", "reload", "새로고침", "refresh")):
        reloaded = []
        for ext in list(bot.extensions.keys()):
            try:
                await bot.reload_extension(ext)
                reloaded.append(ext)
            except Exception as e:
                print(f"⚠️ [{ext}] 리로드 실패: {e}", flush=True)

    try:
        app_id = bot.application_id or (bot.application.id if bot.application else bot.user.id)
        is_clean_mode = any(k in mode for k in ("정리", "clean", "삭제", "초기화"))

        if is_clean_mode and ctx.guild:
            # 길드 전용 커맨드 정리 모드
            try:
                await bot.http.bulk_upsert_guild_commands(app_id, ctx.guild.id, [])
            except Exception:
                pass
            bot.tree.clear_commands(guild=ctx.guild)
            try:
                await bot.tree.sync(guild=ctx.guild)
            except Exception:
                pass
            guild_cnt = 0
        elif ctx.guild:
            # 기본 모드: 현재 서버에 즉시 0초 반영
            bot.tree.copy_global_to(guild=ctx.guild)
            synced_guild = await bot.tree.sync(guild=ctx.guild)
            guild_cnt = len(synced_guild)
        else:
            guild_cnt = 0

        # 글로벌 동기화 병행
        synced_global = await bot.tree.sync()

        view = SyncControlView(author=ctx.author, guild=ctx.guild)
        embed = discord.Embed(
            title=f"⚡ [{g_name}] 슬래시 명령어 0초 즉시 동기화 완료!",
            description=(
                f"🎉 **현재 서버에 슬래시 명령어 총 `{guild_cnt}개`가 0초 만에 즉시 반영되었습니다!**\n\n"
                "📊 **등록 상태:**\n"
                f"• 🏠 현재 서버({g_name}) 즉시 등록: **`{guild_cnt}개`** *(반응역할 포함 0초 만에 바로 작동)*\n"
                f"• 🌐 글로벌 전역 명령어: **`{len(synced_global)}개`** *(전역 등록 완료)*\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 **지금 바로 채팅창에서 `/`를 눌러 사용해 보세요!**\n"
                "• `/반응역할` 또는 `!반응역할` : 이모지 반응역할 스튜디오 호출\n"
                "• `/반응역할생성` : 지정 채널에 새 반응역할 안내 패널 즉시 발행\n"
                "• `/플레이리스트` 또는 `!플레이리스트` : 플레이리스트 스튜디오 호출\n"
                "• `/오디오테스트` 또는 `!오디오테스트` : 440Hz 비프음으로 오디오 즉시 자가진단"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text=f"[봇주 전용] norosi Sync Engine  ·  실행자: {ctx.author.display_name}")
        await status_msg.edit(content=None, embed=embed, view=view)
        view.message = status_msg
    except Exception as e:
        await status_msg.edit(content=f"⚠️ 동기화 처리 중 오류가 발생했습니다: `{e}`")


# ==========================================
# 일반 텍스트 명령어 에러 핸들러
# ==========================================
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어를 실행할 관리자 권한이 부족합니다.", delete_after=5)
        return
    if isinstance(error, commands.NotOwner):
        await ctx.send("❌ 이 명령어는 봇 소유자 전용입니다.", delete_after=5)
        return
    print(f"⚠️ [일반 명령어 오류] !{ctx.command.name if ctx.command else '알수없음'}: {error}", flush=True)
    try:
        await ctx.send(f"⚠️ 명령어 처리 중 오류 발생: `{error}`", delete_after=10)
    except Exception:
        pass


# ==========================================
# Render 배포 시 포트 타임아웃 및 크래시 방지용 안전 실행부
# ==========================================
async def main():
    print("==================================================================", flush=True)
    print(f"🚀 [STARTUP] norosi 봇 프로세스 시작 중 (PID: {os.getpid()})", flush=True)
    print(f"⏰ 현재 시각: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (서버) / {datetime.datetime.now(core.KST).strftime('%Y-%m-%d %H:%M:%S KST')} (한국)", flush=True)
    print("==================================================================", flush=True)

    await bot.start_web_server()

    # 토큰 실시간 확인 (다중 소스, 다중 키, 환경변수 덮어쓰기 지원)
    active_token = core.get_token()
    if not active_token:
        diag = core.get_env_diagnostics()
        print("❌ [치명적 오류] 유효한 DISCORD_TOKEN을 찾을 수 없습니다!", flush=True)
        print("------------------------------------------------------------------", flush=True)
        print(f"📁 현재 작업 디렉토리 (CWD): {diag.get('cwd')}", flush=True)
        print(f"📁 스크립트 위치: {diag.get('script_dir')}", flush=True)
        print(f"🔍 감지된 .env 파일 목록: {diag.get('found_env_files') or '없음 (0개 발견)'}", flush=True)
        print(f"🔑 .env에서 파싱된 키 목록: {diag.get('parsed_keys') or '없음'}", flush=True)
        print("------------------------------------------------------------------", flush=True)
        print("💡 [해결 방법 안내]", flush=True)
        print("1. 프로젝트 루트(/home/ubuntu/norosi 또는 bot.py가 위치한 폴더)에 .env 파일을 생성하세요.", flush=True)
        print("2. 파일 내용 예시:\n   DISCORD_TOKEN=your_bot_token_here", flush=True)
        print("3. 또는 GitHub Secrets에 DISCORD_TOKEN을 등록해 두면 배포 시 자동 주입됩니다.", flush=True)
        print("⏳ 30초마다 .env 파일을 재검색하여 토큰이 등록되면 자동으로 시작합니다...", flush=True)
        print("==================================================================", flush=True)

        while not active_token:
            await asyncio.sleep(30)
            core._load_env_file()
            active_token = core.get_token()
            if active_token:
                print(f"🎉 새 토큰이 감지되었습니다! (길이: {len(active_token)}) 봇 연결을 시작합니다...", flush=True)
                break

    core.TOKEN = active_token
    print(f"🔑 디스코드 게이트웨이 인증 및 연결 시도 중... (토큰 길이: {len(active_token)})", flush=True)
    while True:
        try:
            await bot.start(core.TOKEN)
        except discord.LoginFailure:
            print(
                "❌ 치명적 오류: 디스코드 토큰이 유효하지 않습니다! (LoginFailure)\n"
                "👉 Discord Developer Portal에서 Reset Token 후 .env 파일의 DISCORD_TOKEN을 갱신하세요.",
                flush=True
            )
            # 토큰이 파일에서 수정될 때까지 30초마다 대기하며 자동 재시도
            while True:
                await asyncio.sleep(30)
                core._load_env_file()
                new_token = core.get_token()
                if new_token and new_token != core.TOKEN:
                    print("🔄 새로운 토큰이 감지되어 연결을 재시도합니다...", flush=True)
                    core.TOKEN = new_token
                    break
        except Exception as e:
            print(f"⚠️ 봇 연결 예외 발생 (15초 후 재시도): {e}", flush=True)
            await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(main())
