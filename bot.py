import os
import re
import sys
import copy
import time
import logging
import asyncio
import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional, List, Dict, Any, Union
from collections import OrderedDict
from aiohttp import web
import core
from cogs.music import MusicRecommendView


# ==========================================
# 🖥️ VM 서버 터미널(stdout / stderr / logging) 실시간 디스코드 채널 브릿지
# ==========================================
ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


class TerminalStreamTee:
    """VM 터미널(systemd journal) 출력을 유지하면서 동시에 디스코드 로그 큐로 전달하는 스트림 래퍼"""
    def __init__(self, original_stream, log_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, is_stderr: bool = False):
        self.original_stream = original_stream
        self.log_queue = log_queue
        self.loop = loop
        self.is_stderr = is_stderr
        self._line_buf = ""

    def write(self, message: str):
        try:
            self.original_stream.write(message)
            self.original_stream.flush()
        except Exception:
            pass

        if not message:
            return

        # 무한 루프 및 레이트 리밋 피드백 방지: 디스코드 HTTP 전송 자체 로그나 게이트웨이 메시지, 레이트 리밋 등은 채널 전송 제외
        lower_msg = message.lower()
        if any(ign in lower_msg for ign in ("[terminallogger]", "discord.http", "discord.gateway", "discord.webhook", "rate limit", "rate limited", "429")):
            return

        try:
            self._line_buf += message
            if "\n" in self._line_buf or len(self._line_buf) > 500:
                clean_text = ANSI_ESCAPE_RE.sub("", self._line_buf)
                self._line_buf = ""
                if clean_text.strip():
                    prefix = "⚠️ [STDERR] " if self.is_stderr and "Traceback" in clean_text else ""
                    self.loop.call_soon_threadsafe(self._safe_put, prefix + clean_text)
        except Exception:
            pass

    def _safe_put(self, item: str):
        try:
            if self.log_queue.qsize() < 500:
                self.log_queue.put_nowait(item)
        except Exception:
            pass

    def flush(self):
        try:
            self.original_stream.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self):
        return self.original_stream.fileno()


class DiscordQueueLoggingHandler(logging.Handler):
    """Python logging 모듈(INFO, WARNING, ERROR) 로그를 디스코드 전송 큐로 전달하는 핸들러"""
    def __init__(self, log_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__(level=logging.INFO)
        self.log_queue = log_queue
        self.loop = loop
        self.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        # 무한 루프 및 레이트 리밋 피드백 방지: 디스코드/aiohttp 자체 내부 로그는 터미널에만 출력하고 채널로 재전송하지 않음
        if record.name.startswith(("discord", "aiohttp")):
            return
        try:
            msg = ANSI_ESCAPE_RE.sub("", self.format(record))
            if msg.strip():
                self.loop.call_soon_threadsafe(self._safe_put, msg + "\n")
        except Exception:
            pass

    def _safe_put(self, item: str):
        try:
            if self.log_queue.qsize() < 500:
                self.log_queue.put_nowait(item)
        except Exception:
            pass


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
        self._handled_interaction_ids: OrderedDict[int, float] = OrderedDict()

        # 터미널 로그 브릿지 상태 변수
        self.terminal_log_queue: Optional[asyncio.Queue] = None
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._log_handler: Optional[DiscordQueueLoggingHandler] = None
        self._terminal_hooked = False

    def setup_terminal_log_capture(self):
        """VM 터미널로 출력되는 stdout, stderr, logging 스트림을 가로채어 큐에 적재"""
        if self._terminal_hooked:
            return
        loop = asyncio.get_running_loop()
        self.terminal_log_queue = asyncio.Queue(maxsize=500)
        sys.stdout = TerminalStreamTee(self._orig_stdout, self.terminal_log_queue, loop, is_stderr=False)
        sys.stderr = TerminalStreamTee(self._orig_stderr, self.terminal_log_queue, loop, is_stderr=True)

        self._log_handler = DiscordQueueLoggingHandler(self.terminal_log_queue, loop)
        logging.getLogger().addHandler(self._log_handler)
        self._terminal_hooked = True

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

    async def handle_github_webhook(self, request: web.Request):
        """
        GitHub 저장소 Push 및 GitHub Actions 배포 성공/실패 이벤트를 수신하여
        설정된 디스코드 채널에 '🚀 업데이트 완료: [커밋 메시지]' 임베드를 실시간으로 전송합니다.
        """
        try:
            event = request.headers.get("X-GitHub-Event", "push")
            try:
                payload = await request.json()
            except Exception:
                return web.json_response({"error": "Invalid JSON"}, status=400)

            data = core.get_cached_data()
            configs = core.get_github_webhook_configs(data)

            # 대상 채널 및 멘션 역할 탐색: 연동된 모든 서버 채널에 동시 전파
            target_channels_with_roles = []
            seen_channel_ids = set()

            for gid, cfg in configs.items():
                if cfg.get("enabled", True) and cfg.get("channel_id"):
                    cid = cfg["channel_id"]
                    if cid not in seen_channel_ids:
                        target_channels_with_roles.append((cid, cfg.get("role_id")))
                        seen_channel_ids.add(cid)

            # Query 파라미터(channel_id)가 명시된 경우에도 포함 (중복 방지)
            q_cid = request.query.get("channel_id")
            if q_cid and q_cid.isdigit():
                q_cid_int = int(q_cid)
                if q_cid_int not in seen_channel_ids:
                    target_channels_with_roles.append((q_cid_int, None))
                    seen_channel_ids.add(q_cid_int)

            embed = None
            role_mention = None

            if event == "ping":
                zen = payload.get("zen", "Keep it logically awesome.")
                repo_name = payload.get("repository", {}).get("full_name", "저장소")
                embed = discord.Embed(
                    title="🏓 GitHub 웹훅(Webhook) 연결 성공!",
                    description=(
                        f"• **연동 저장소:** `{repo_name}`\n"
                        f"• **GitHub Zen:** *\"{zen}\"*\n\n"
                        f"✅ 깃허브 푸시(Push) 및 GitHub Actions 배포 알림 수신 준비가 완료되었습니다! 🚀"
                    ),
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.now(core.KST)
                )
                embed.set_footer(text="GitHub Webhook Ping • norosi 연동 테스트")

            elif event == "push":
                repo = payload.get("repository", {}) or {}
                repo_full = repo.get("full_name", repo.get("name", "norosi"))
                repo_url = repo.get("html_url", "https://github.com")
                ref = payload.get("ref", "")
                branch = ref.split("/")[-1] if "/" in ref else (ref or "master")
                pusher = payload.get("pusher", {}).get("name", "개발자")
                sender = payload.get("sender", {})
                sender_avatar = sender.get("avatar_url", "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png")
                commits = payload.get("commits", []) or []
                head_commit = payload.get("head_commit", {}) or (commits[-1] if commits else {})

                raw_msg = head_commit.get("message", "새로운 변경사항 푸시 완료")
                first_line = raw_msg.strip().split("\n")[0]
                commit_id = (head_commit.get("id") or "")[:7] or "latest"
                commit_url = head_commit.get("url", repo_url)
                compare_url = payload.get("compare", commit_url)

                added_cnt = len(head_commit.get("added", []))
                modified_cnt = len(head_commit.get("modified", []))
                removed_cnt = len(head_commit.get("removed", []))

                embed_title = f"🚀 업데이트 완료: {first_line}"
                if len(embed_title) > 250:
                    embed_title = embed_title[:247] + "..."

                embed = discord.Embed(
                    title=embed_title,
                    url=commit_url,
                    color=discord.Color.from_rgb(46, 204, 113),  # 상쾌한 에메랄드 그린
                    timestamp=datetime.datetime.now(core.KST)
                )
                desc_lines = [
                    f"📦 **저장소:** [`{repo_full}`]({repo_url})  ·  🌿 **브랜치:** `{branch}`",
                    f"👤 **커밋 작성자:** `{pusher}`  ·  🔖 **커밋:** [`{commit_id}`]({commit_url})",
                    "",
                    "### 📝 커밋 상세 내용",
                    f"```{raw_msg[:900]}```",
                    f"📂 **파일 변경:** `+{added_cnt} 추가` · `~{modified_cnt} 수정` · `-{removed_cnt} 삭제`",
                    f"🔗 [커밋 비교 및 세부 코드 변경내역 보기 (GitHub)]({compare_url})"
                ]
                embed.description = "\n".join(desc_lines)
                embed.set_thumbnail(url=sender_avatar)
                embed.set_footer(text=f"GitHub Push Event • 총 {len(commits)}개 커밋 반영 완료 • norosi Live Deploy")

            elif event == "workflow_run":
                action = payload.get("action", "")
                if action != "completed":
                    return web.json_response({"status": "ignored", "action": action})

                wf = payload.get("workflow_run", {}) or {}
                wf_name = wf.get("name", "Deploy")
                conclusion = wf.get("conclusion", "success")
                run_url = wf.get("html_url", "")
                run_number = wf.get("run_number", 1)
                head_branch = wf.get("head_branch", "master")
                head_commit = wf.get("head_commit", {}) or {}
                commit_msg = head_commit.get("message", "빌드 및 배포")
                first_line = commit_msg.strip().split("\n")[0]

                if conclusion == "success":
                    title = f"🎉 GitHub Actions 배포 성공: {wf_name} (#{run_number})"
                    color = discord.Color.from_rgb(46, 204, 113)
                    status_badge = "✅ **배포 완료 (Success)**"
                elif conclusion == "failure":
                    title = f"🚨 GitHub Actions 배포 실패: {wf_name} (#{run_number})"
                    color = discord.Color.red()
                    status_badge = "❌ **배포 실패 (Failed)**"
                else:
                    title = f"ℹ️ GitHub Actions 상태 알림: {wf_name} ({conclusion})"
                    color = discord.Color.gold()
                    status_badge = f"⚠️ **상태: {conclusion}**"

                embed = discord.Embed(
                    title=title,
                    url=run_url,
                    color=color,
                    timestamp=datetime.datetime.now(core.KST)
                )
                desc_lines = [
                    f"🚀 **워크플로우:** `{wf_name}`  ·  {status_badge}",
                    f"🌿 **브랜치:** `{head_branch}`  ·  🔖 **실행 번호:** `#{run_number}`",
                    f"💬 **트리거 커밋:** `{first_line}`",
                    f"🔗 [GitHub Actions 빌드/배포 로그 확인하기]({run_url})"
                ]
                embed.description = "\n".join(desc_lines)
                embed.set_footer(text="GitHub Actions CI/CD • norosi 자동 배포")

            if embed and target_channels_with_roles:
                for cid, role_id in target_channels_with_roles:
                    ch = await self.resolve_channel(cid)
                    if ch:
                        role_mention = f"<@&{role_id}>" if role_id else None
                        try:
                            await ch.send(content=role_mention, embed=embed)
                        except Exception as send_err:
                            print(f"⚠️ [GitHub 웹훅 메시지 전송 예외] 채널 {cid}: {send_err}", flush=True)

            return web.json_response({
                "status": "success",
                "event": event,
                "dispatched_channels": len(target_channels_with_roles)
            })
        except Exception as e:
            print(f"⚠️ [handle_github_webhook 예외] {e}", flush=True)
            return web.json_response({"error": str(e)}, status=500)

    async def start_web_server(self):
        if self._web_started:
            return
        try:
            app = web.Application()
            app.router.add_get("/", self.handle_health_check)
            app.router.add_post("/api/github/webhook", self.handle_github_webhook)
            app.router.add_post("/github/webhook", self.handle_github_webhook)
            app.router.add_post("/webhook/github", self.handle_github_webhook)
            app.router.add_post("/github", self.handle_github_webhook)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", core.PORT)
            await site.start()
            self._web_started = True
            print(f"✅ norosi 헬스체크 및 GitHub 웹훅 서버 가동 완료 (포트: {core.PORT})", flush=True)
        except Exception as e:
            print(f"ℹ️ 웹 서버 시작 건너뜀 (포트 {core.PORT} 점유 중이거나 불필요 환경): {e}", flush=True)

    async def setup_hook(self):
        # 0. VM 터미널 로그 실시간 캡처 활성화
        self.setup_terminal_log_capture()

        print("📦 [1/4] 데이터 캐시 로드 중...", flush=True)
        await asyncio.to_thread(core.load_data)

        # 글로벌 슬래시 커맨드 에러 핸들러 등록 ("명령어 응답 안함" 3초 타임아웃 차단)
        self.tree.on_error = self.on_app_command_error

        print("🔌 [2/4] Cogs 확장 모듈 등록 중 (gacha, genshin, hsr, music, dday, logger, ai, stats, roles, help, dashboard)...", flush=True)
        ext_list = [
            "cogs.gacha",
            "cogs.genshin",
            "cogs.hsr",
            "cogs.music",
            "cogs.dday",
            "cogs.logger",
            "cogs.ai",
            "cogs.stats",
            "cogs.roles",
            "cogs.help",
            "cogs.dashboard",
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

        print("📚 [3/4] 프로세카 · 원신 · 스타레일 한국어 DB 백그라운드 캐시 워밍 시작...", flush=True)
        asyncio.create_task(asyncio.to_thread(core.load_proseka_kr_db))
        import genshin_core, hsr_core
        asyncio.create_task(asyncio.to_thread(genshin_core.load_genshin_kr_db))
        asyncio.create_task(asyncio.to_thread(hsr_core.load_hsr_kr_db))

        print("⏰ [4/4] 상주 스케줄러 및 VM 터미널 로그 브릿지 루프 활성화...", flush=True)
        if not self.midnight_tasks.is_running():
            self.midnight_tasks.start()
        if not self.morning_music_alert.is_running():
            self.morning_music_alert.start()
        if not self.morning_text_alert.is_running():
            self.morning_text_alert.start()
        if not self.custom_music_schedules_loop.is_running():
            self.custom_music_schedules_loop.start()
        if not self.terminal_log_dispatch_loop.is_running():
            self.terminal_log_dispatch_loop.start()

    @tasks.loop(seconds=3.0)
    async def terminal_log_dispatch_loop(self):
        """3초마다 VM 터미널 출력 큐를 확인하여 지정된 모든 서버 채널로 안전하게 묶음 전송 (레이트 리밋 방어 탑재)"""
        if not self.terminal_log_queue or self.terminal_log_queue.empty():
            return

        data = core.get_cached_data()
        target_channel_ids = set()

        # 1. 서버별 등록된 터미널 로그 채널 목록 수집
        t_channels = data.get("settings", {}).get("terminal_log_channels", {})
        if isinstance(t_channels, dict):
            for cid in t_channels.values():
                if cid and str(cid).isdigit():
                    target_channel_ids.add(int(cid))
        elif isinstance(t_channels, (list, set)):
            for cid in t_channels:
                if cid and str(cid).isdigit():
                    target_channel_ids.add(int(cid))

        # 2. 레거시 단일 설정 채널 ID도 포함
        legacy_id = data.get("settings", {}).get("terminal_log_channel_id")
        if legacy_id and str(legacy_id).isdigit():
            target_channel_ids.add(int(legacy_id))

        if not target_channel_ids:
            # 채널이 지정되지 않은 상태면 큐가 쌓이지 않도록 비움
            while not self.terminal_log_queue.empty():
                try:
                    self.terminal_log_queue.get_nowait()
                except Exception:
                    break
            return

        resolved_channels = []
        for cid in list(target_channel_ids):
            ch = await self.resolve_channel(cid)
            if ch:
                resolved_channels.append(ch)

        if not resolved_channels:
            return

        # 큐에서 쌓인 모든 로그 텍스트를 청크 단위로 추출
        chunks = []
        while not self.terminal_log_queue.empty():
            try:
                chunk = self.terminal_log_queue.get_nowait()
                chunks.append(chunk)
            except asyncio.QueueEmpty:
                break

        if not chunks:
            return

        # 로그 텍스트 합치기 및 코드블록 특수문자 치환
        full_text = "".join(chunks).replace("```", "'''")

        # 디스코드 2,000자 제한을 준수하도록 ~1,800자 단위 메시지 리스트로 분할
        messages_to_send = []
        buf = ""
        for line in full_text.splitlines(keepends=True):
            if len(buf) + len(line) > 1800:
                if buf.strip():
                    messages_to_send.append(buf.strip())
                buf = line
            else:
                buf += line
        if buf.strip():
            messages_to_send.append(buf.strip())

        if not messages_to_send:
            return

        # 과도한 출력(폭주) 발생 시 채널 도배 및 429 방지: 최대 2개 메시지만 전송하고 중간은 생략
        if len(messages_to_send) > 2:
            dropped_cnt = len(messages_to_send) - 2
            messages_to_send = [
                messages_to_send[0],
                f"... [⚠️ 터미널 출력 폭주 방어: 중간 로그 약 {dropped_cnt * 1800}자 생략됨. 서버 VM 콘솔 참조] ...\n" + messages_to_send[-1]
            ]

        # 디스코드 채널 레이트 리밋(5초당 5회) 준수를 위해 메시지 간 1.1초 간격 전송
        for idx, msg in enumerate(messages_to_send):
            if not msg.strip():
                continue
            payload = f"```log\n{msg.strip()}\n```"
            for ch in resolved_channels:
                try:
                    await ch.send(payload)
                except discord.HTTPException as he:
                    if he.status == 429:
                        self._orig_stderr.write(f"[TerminalLogger] 채널 {ch.id} 전송 429 감지(일시대기): {he}\n")
                    else:
                        self._orig_stderr.write(f"[TerminalLogger] 채널 {ch.id} 전송 HTTP 오류: {he}\n")
                except Exception as e:
                    self._orig_stderr.write(f"[TerminalLogger] 채널 {ch.id} 전송 실패: {e}\n")

            if idx < len(messages_to_send) - 1:
                await asyncio.sleep(1.1)

    @terminal_log_dispatch_loop.before_loop
    async def before_terminal_log_dispatch(self):
        await self.wait_until_ready()

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
            await core.safe_send_response(interaction, err_msg, ephemeral=True)
        except Exception as e:
            print(f"❌ [에러 메시지 송신 예외]: {e}", flush=True)

    def is_component_handled_by_view_store(self, interaction: discord.Interaction) -> bool:
        """
        discord.py의 내부 ViewStore가 이미 해당 컴포넌트(버튼/셀렉트)를 메모리에서 추적하고 있는지 확인합니다.
        추적 중이라면 discord.py가 자체 디스패치 루프(_scheduled_task)를 통해 콜백을 안전하게 호출하므로
        on_interaction에서 중복 실행하지 않고 즉시 위임합니다.
        """
        try:
            vs = getattr(getattr(self, "_connection", None), "_view_store", None)
            if not vs:
                return False
            data = getattr(interaction, "data", {}) or {}
            custom_id = data.get("custom_id")
            component_type = data.get("component_type", 2)
            if not custom_id:
                return False

            key = (component_type, custom_id)
            msg = interaction.message
            msg_id = msg.id if msg else None

            views = getattr(vs, "_views", None)
            if isinstance(views, dict):
                if msg_id is not None and key in views.get(msg_id, {}):
                    return True
                if key in views.get(None, {}):
                    return True
        except Exception:
            pass
        return False

    def attach_view_to_message(self, view: discord.ui.View, message_id: Optional[int] = None):
        """
        메모리 유실된 뷰를 디스코드 ViewStore에 안전하게 등록합니다.
        timeout 유무와 무관하게 message_id에 바인딩하여 후속 클릭이 네이티브로 동작하게 합니다.
        """
        try:
            vs = getattr(getattr(self, "_connection", None), "_view_store", None)
            if vs and message_id is not None:
                vs.add_view(view, message_id)
            elif vs:
                vs.add_view(view, None)
            else:
                self.add_view(view, message_id=message_id)
        except Exception:
            try:
                self.add_view(view, message_id=message_id)
            except Exception:
                pass

    async def on_interaction(self, interaction: discord.Interaction):
        """
        컴포넌트(버튼, 드롭다운 메뉴) 상호작용 발생 시
        코드 반영이나 봇 재시작으로 인해 ViewStore에서 유실된 이전 버튼을 지능적으로 복구·실행합니다.
        """
        if interaction.type == discord.InteractionType.component:
            # 1. 이미 응답 완료되었거나 유효하지 않은 인터랙션 즉시 패스
            if interaction.response.is_done():
                return

            # 2. 동일한 인터랙션 중복 실행 방지 (Snowflake id 기반)
            i_id = getattr(interaction, "id", None)
            if i_id:
                if i_id in self._handled_interaction_ids:
                    return
                self._handled_interaction_ids[i_id] = time.time()
                if len(self._handled_interaction_ids) > 1000:
                    for _ in range(200):
                        self._handled_interaction_ids.popitem(last=False)

            # 3. 현재 메모리의 ViewStore가 이미 추적 중인 활성 뷰인 경우 discord.py 내부 디스패처가 처리하도록 위임
            if self.is_component_handled_by_view_store(interaction):
                return

            await self.handle_persistent_button_fallback(interaction)

    async def handle_persistent_button_fallback(self, interaction: discord.Interaction):
        """
        봇 재시작 또는 코드 업데이트로 인해 discord.py의 메모리 ViewStore에서 유실된
        모든 이전 버튼 및 UI 상호작용을 지능적으로 복구·실행하여 '먹통 현상'을 영구 차단합니다.
        (단, 수정/삭제된 명령어의 버튼은 정중한 안내 메시지로 전환)
        """
        custom_id = str(interaction.data.get("custom_id", "") or "").strip()
        msg = interaction.message

        # 1. 반응역할 버튼 (rr_btn_{role_id})
        if custom_id.startswith("rr_btn_"):
            try:
                from cogs.roles import PersistentRoleButton
                role_id = int(custom_id.replace("rr_btn_", "").strip())
                btn = PersistentRoleButton(role_id=role_id, label="역할")
                await btn.callback(interaction)
                return
            except Exception as e:
                print(f"⚠️ [반응역할 폴백 예외] {e}", flush=True)

        # 2. 결정론적 커스텀 ID 패턴: norosi:{ViewClassName}:{item_name}
        if custom_id.startswith("norosi:"):
            parts = custom_id.split(":", 2)
            if len(parts) >= 3:
                view_name = parts[1]
                item_name = parts[2]
                view_cls = core.SAFE_VIEW_REGISTRY.get(view_name)
                if view_cls:
                    try:
                        view = core.reconstruct_safe_view(view_cls, interaction)
                        if view:
                            target_item = None
                            for child in view.children:
                                if getattr(child, "custom_id", None) == custom_id:
                                    target_item = child
                                    break
                            if not target_item:
                                for child in view.children:
                                    cb_name = getattr(getattr(child, "callback", None), "__name__", "")
                                    if cb_name == item_name:
                                        target_item = child
                                        break
                                    if getattr(child, "label", None) == item_name:
                                        target_item = child
                                        break
                            if target_item and hasattr(target_item, "callback"):
                                if hasattr(target_item, "_refresh_state"):
                                    try:
                                        target_item._refresh_state(interaction, interaction.data)
                                    except Exception:
                                        pass
                                try:
                                    await target_item.callback(interaction)
                                except Exception as cb_err:
                                    print(f"⚠️ [norosi 버튼 콜백 실행 예외] {cb_err}", flush=True)
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return
                    except Exception as e:
                        print(f"⚠️ [norosi 뷰 복구 예외] {view_name}.{item_name}: {e}", flush=True)

        # 3. 코드 반영 전 구버전 메시지(랜덤 hex custom_id) 지능형 매칭 및 복구
        if msg:
            embed_text = ""
            if msg.embeds:
                emb = msg.embeds[0]
                embed_text = f"{emb.title or ''} {emb.description or ''}"

            clicked_label = ""
            clicked_emoji = ""
            component_type = interaction.data.get("component_type", 2)
            for row in getattr(msg, "components", []):
                for child in getattr(row, "children", []):
                    if child.custom_id == custom_id:
                        clicked_label = getattr(child, "label", "") or ""
                        clicked_emoji = getattr(child, "emoji", "") or ""
                        break

            # 3-1. 음성채널 자동재생 대시보드 (리모컨)
            if "순차 자동재생 대시보드" in embed_text or "실시간 스트리밍 중" in embed_text or "실시간 리모컨" in embed_text:
                try:
                    import cogs.music
                    player = cogs.music.get_voice_player(self, interaction.guild)
                    view = cogs.music.VoicePlayerControlView(player)
                    view.message = msg
                    target_btn = None

                    cl = clicked_label.lower()
                    if "이전" in cl:
                        target_btn = view.prev_track_btn
                    elif "일시정지" in cl or "재생" in cl:
                        target_btn = view.pause_resume_btn
                    elif "다음" in cl:
                        target_btn = view.next_track_btn
                    elif "순환" in cl or "반복" in cl:
                        target_btn = view.loop_btn
                    elif "정지" in cl or "퇴장" in cl:
                        target_btn = view.stop_btn
                    elif "-15%" in cl:
                        target_btn = view.vol_down_btn
                    elif "+15%" in cl:
                        target_btn = view.vol_up_btn
                    elif "셔플" in cl:
                        target_btn = view.shuffle_queue_btn
                    elif "취침" in cl or "타이머" in cl:
                        target_btn = view.sleep_timer_btn
                    elif "담기" in cl or "스크랩" in cl:
                        target_btn = view.grab_current_track_btn
                    elif "헤드셋" in cl:
                        target_btn = view.toggle_deaf_btn
                    elif "재연결" in cl or "새로고침" in cl:
                        target_btn = view.refresh_audio_btn
                    elif "배속" in cl:
                        target_btn = view.speed_toggle_btn
                    elif component_type in (3, 5, 6, 7, 8):
                        target_btn = view.jump_select

                    if target_btn and hasattr(target_btn, "callback"):
                        if hasattr(target_btn, "_refresh_state"):
                            try:
                                target_btn._refresh_state(interaction, interaction.data)
                            except Exception:
                                pass
                        try:
                            await target_btn.callback(interaction)
                        except Exception as cb_err:
                            print(f"⚠️ [음성 플레이어 콜백 예외] {cb_err}", flush=True)
                        if msg:
                            self.attach_view_to_message(view, message_id=msg.id)
                        return
                except Exception as e:
                    print(f"⚠️ [음성 플레이어 리모컨 구버전 복구 예외] {e}", flush=True)

            # 3-2. 올인원 마스터 대시보드
            if "마스터 대시보드" in embed_text or "norosi 통합 제어" in embed_text:
                try:
                    from cogs.dashboard import MasterDashboardView
                    data = core.get_cached_data()
                    view = MasterDashboardView(self, interaction.user, interaction.guild, data)
                    view.message = msg

                    if component_type in (3, 5, 6, 7, 8):
                        for child in view.children:
                            if isinstance(child, discord.ui.Select):
                                if hasattr(child, "_refresh_state"):
                                    try:
                                        child._refresh_state(interaction, interaction.data)
                                    except Exception:
                                        pass
                                try:
                                    await child.callback(interaction)
                                except Exception as cb_err:
                                    print(f"⚠️ [마스터 대시보드 셀렉트 콜백 예외] {cb_err}", flush=True)
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return
                    elif "새로고침" in clicked_label:
                        try:
                            await view._on_refresh_clicked(interaction)
                        except Exception as cb_err:
                            print(f"⚠️ [마스터 대시보드 새로고침 콜백 예외] {cb_err}", flush=True)
                        if msg:
                            self.attach_view_to_message(view, message_id=msg.id)
                        return
                    else:
                        for child in view.children:
                            if getattr(child, "label", None) == clicked_label:
                                if hasattr(child, "_refresh_state"):
                                    try:
                                        child._refresh_state(interaction, interaction.data)
                                    except Exception:
                                        pass
                                try:
                                    await child.callback(interaction)
                                except Exception as cb_err:
                                    print(f"⚠️ [마스터 대시보드 버튼 콜백 예외] {cb_err}", flush=True)
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return
                except Exception as e:
                    print(f"⚠️ [마스터 대시보드 구버전 복구 예외] {e}", flush=True)

            # 3-3. 플레이리스트 보관함 / 스튜디오
            if "플레이리스트 보관함" in embed_text or "플레이리스트 스튜디오" in embed_text:
                try:
                    from cogs.music import PlaylistStudioView
                    data = core.get_cached_data()
                    view = PlaylistStudioView(interaction.user, interaction.user, data)
                    view.message = msg
                    for child in view.children:
                        if getattr(child, "label", None) == clicked_label:
                            if hasattr(child, "_refresh_state"):
                                try:
                                    child._refresh_state(interaction, interaction.data)
                                except Exception:
                                    pass
                            try:
                                await child.callback(interaction)
                            except Exception as cb_err:
                                print(f"⚠️ [플레이리스트 스튜디오 콜백 예외] {cb_err}", flush=True)
                            if msg:
                                self.attach_view_to_message(view, message_id=msg.id)
                            return
                except Exception as e:
                    print(f"⚠️ [플레이리스트 스튜디오 구버전 복구 예외] {e}", flush=True)

            # 3-4. 도움말 카테고리
            if "도움말" in embed_text or "명령어 가이드" in embed_text:
                try:
                    from cogs.help import HelpCategoryView
                    view = HelpCategoryView(self)
                    view.message = msg
                    if component_type in (3, 5, 6, 7, 8):
                        for child in view.children:
                            if isinstance(child, discord.ui.Select):
                                if hasattr(child, "_refresh_state"):
                                    try:
                                        child._refresh_state(interaction, interaction.data)
                                    except Exception:
                                        pass
                                try:
                                    await child.callback(interaction)
                                except Exception as cb_err:
                                    print(f"⚠️ [도움말 셀렉트 콜백 예외] {cb_err}", flush=True)
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return
                except Exception as e:
                    print(f"⚠️ [도움말 구버전 복구 예외] {e}", flush=True)

            # 3-5. 서버 종합 통계
            if "서버 종합 통계" in embed_text or "서버 통계" in embed_text:
                try:
                    from cogs.stats import ServerStatsDashboardView
                    data = core.get_cached_data()
                    view = ServerStatsDashboardView(interaction.guild, data)
                    view.message = msg
                    for child in view.children:
                        if getattr(child, "label", None) == clicked_label:
                            if hasattr(child, "_refresh_state"):
                                try:
                                    child._refresh_state(interaction, interaction.data)
                                except Exception:
                                    pass
                            try:
                                await child.callback(interaction)
                            except Exception as cb_err:
                                print(f"⚠️ [통계 대시보드 콜백 예외] {cb_err}", flush=True)
                            if msg:
                                self.attach_view_to_message(view, message_id=msg.id)
                            return
                except Exception as e:
                    print(f"⚠️ [통계 대시보드 구버전 복구 예외] {e}", flush=True)

            # 3-6. 출석체크 및 오늘의 운세
            if "출석체크" in clicked_label or "운세" in clicked_label:
                try:
                    from cogs.dday import AttendanceQuickActionView
                    view = AttendanceQuickActionView(self, interaction.user)
                    view.message = msg
                    for child in view.children:
                        if getattr(child, "label", None) == clicked_label:
                            if hasattr(child, "_refresh_state"):
                                try:
                                    child._refresh_state(interaction, interaction.data)
                                except Exception:
                                    pass
                            try:
                                await child.callback(interaction)
                            except Exception as cb_err:
                                print(f"⚠️ [출석체크 콜백 예외] {cb_err}", flush=True)
                            if msg:
                                self.attach_view_to_message(view, message_id=msg.id)
                            return
                except Exception as e:
                    print(f"⚠️ [출석체크 버튼 복구 예외] {e}", flush=True)

        # 4. 수정/삭제된 명령어의 버튼이거나 도저히 복구할 수 없는 경우 (사용자가 요청한 예외 케이스)
        # Discord의 붉은색 '이 상호작용에 실패했습니다' 대신 친절한 안내 메시지 송출
        if not interaction.response.is_done():
            try:
                await core.safe_send_response(
                    interaction,
                    "💡 **봇 업데이트 안내:** 이전 버전에서 생성된 패널이거나 변경된 기능의 버튼입니다.\n"
                    "최신 버전으로 정상 이용하시려면 해당 명령어를 다시 실행해 주세요! ✨",
                    ephemeral=True
                )
            except Exception:
                pass

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

    async def _safe_startup_sync(self):
        """
        봇 부팅 시 백그라운드에서 안전하게 글로벌 슬래시 명령어를 동기화합니다.
        길드 루프 동기화(copy_global_to)를 제거하여 Discord HTTP 429(Rate Limit)를 방지하고,
        on_ready가 멈추지 않도록 비동기 백그라운드 태스크로 처리합니다.
        특정 길드 즉시 반영은 '!동기화' 또는 '!싱크' 명령어로 언제든 수행 가능합니다.
        """
        try:
            print("🌐 [백그라운드 동기화] 글로벌 슬래시 명령어 동기화 시작...", flush=True)
            synced_cmds = await self.tree.sync()
            print(f"✅ [동기화 완료] 슬래시 명령어 총 {len(synced_cmds)}개 글로벌 등록 완료!", flush=True)
        except discord.HTTPException as e:
            if e.status == 429:
                print(f"⏳ [동기화 알림] Discord API 속도 제한(429 Rate Limit) 감지: {e}. 백그라운드에서 대기 후 자동 재시도됩니다.", flush=True)
            else:
                print(f"⚠️ [동기화 오류] 슬래시 명령어 등록 중 HTTP 예외: {e}", flush=True)
        except Exception as e:
            print(f"⚠️ [동기화 오류] 백그라운드 명령어 동기화 예외: {e}", flush=True)

    async def on_ready(self):
        fb_status = "연동됨" if core.get_firebase_endpoint() else "로컬 + 인메모리 캐시 모드"
        print(f"✅ 로그인 완료: {self.user} (이름: norosi | ID: {self.user.id}) | 저장소: {fb_status}", flush=True)

        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="🌠ㅣ/메뉴 · /출석체크 · /도움말")
        )

        if not self._commands_synced:
            self._commands_synced = True
            asyncio.create_task(self._safe_startup_sync())

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

    def build_music_embed_and_view(self, track_info: dict, prefs: dict, is_morning: bool = False, custom_title: Optional[str] = None):
        """추천 음악 임베드 및 MusicRecommendView를 생성하는 헬퍼 메서드 (누락되었던 함수 선언부 복원)"""
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
        import genshin_core, hsr_core
        await asyncio.gather(
            asyncio.to_thread(core.load_proseka_kr_db),
            asyncio.to_thread(genshin_core.load_genshin_kr_db),
            asyncio.to_thread(hsr_core.load_hsr_kr_db),
            return_exceptions=True,
        )

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
                    target_ch = None
                    g_id = b_info.get("guild_id")
                    if g_id:
                        g_settings = data.get("guild_settings", {}).get(str(g_id), {})
                        g_ch_id = g_settings.get("dday_alert_channel_id")
                        if g_ch_id:
                            target_ch = await self.resolve_channel(g_ch_id)
                    if not target_ch and alert_ch:
                        target_ch = alert_ch

                    if target_ch:
                        try:
                            await target_ch.send(content=f"🎉 <@{uid}>님 생일 축하합니다!!", embed=bday_embed)
                        except Exception:
                            pass
                    try:
                        user_obj = self.get_user(uid) or await self.fetch_user(uid)
                        if user_obj:
                            await user_obj.send(embed=bday_embed)
                    except Exception:
                        pass

        if updated:
            fresh_data = await asyncio.to_thread(core.load_data)
            fresh_data["ddays"] = data["ddays"]
            fresh_data["birthdays"] = data["birthdays"]
            for u_k, u_prof in data.get("user_profiles", {}).items():
                if u_k in fresh_data.get("user_profiles", {}):
                    fresh_data["user_profiles"][u_k]["crystals"] = u_prof.get("crystals", 0)
            await asyncio.to_thread(core.save_data, fresh_data)

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
            fresh_data = await asyncio.to_thread(core.load_data)
            fresh_data["music_schedules"] = data.get("music_schedules", [])
            fresh_reminders = [r for r in fresh_data.get("reminders", []) if isinstance(r, dict) and r.get("trigger_ts", 0) > now_ts]
            fresh_data["reminders"] = fresh_reminders
            await asyncio.to_thread(core.save_data, fresh_data)

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


# ==========================================
# 🖥️ VM 서버 터미널 로그 수신 채널 지정 명령어 (/터미널로그채널, !터미널로그)
# ==========================================
@bot.tree.command(name="터미널로그채널", description="[관리자/봇주] VM 서버 터미널(stdout/stderr)로 출력되는 실시간 로그를 기록할 채널을 지정하거나 해제합니다.")
@app_commands.describe(채널="터미널 로그를 실시간으로 받아볼 텍스트 채널 (비워두면 전송 해제)")
@app_commands.default_permissions(administrator=True)
async def set_terminal_log_channel_slash(interaction: discord.Interaction, 채널: Optional[discord.TextChannel] = None):
    is_owner = await bot.is_bot_owner_user(interaction.user)
    is_admin = bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
    if not (is_owner or is_admin):
        await core.safe_send_response(interaction, "❌ 이 명령어는 **봇 소유자** 또는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
        return

    await core.safe_defer(interaction, ephemeral=True)
    data = await asyncio.to_thread(core.load_data)

    g_key = str(interaction.guild_id) if interaction.guild_id else "global"
    t_channels = data.setdefault("settings", {}).setdefault("terminal_log_channels", {})

    if 채널 is None:
        t_channels.pop(g_key, None)
        if not t_channels:
            data.setdefault("settings", {})["terminal_log_channel_id"] = None
        await asyncio.to_thread(core.save_data, data)
        await interaction.followup.send(f"🛑 **현재 서버({interaction.guild.name if interaction.guild else '글로벌'})의 VM 서버 터미널 로그 채널 전송이 해제되었습니다.**", ephemeral=True)
        print(f"ℹ️ [System] {interaction.user}에 의해 {interaction.guild}의 터미널 로그 채널 전송이 비활성화되었습니다.", flush=True)
    else:
        t_channels[g_key] = 채널.id
        data.setdefault("settings", {})["terminal_log_channel_id"] = 채널.id
        await asyncio.to_thread(core.save_data, data)
        embed = discord.Embed(
            title="🖥️ VM 서버 터미널 실시간 로그 채널 지정 완료!",
            description=(
                f"이제부터 VM 서버 터미널(`stdout` / `stderr` / `logging`)로 출력되는 모든 로그가 {채널.mention} 채널에도 실시간으로 기록됩니다.\n\n"
                f"• **현재 채널:** {채널.mention} (`#{채널.name}`)\n"
                f"• **전체 연동 서버:** 총 {len(t_channels)}개 서버 채널에 실시간 동시 전송 중\n"
                "• **전송 주기:** `3초` 단위 버퍼링 묶음 전송 (도배 및 Rate Limit 완벽 방어)\n"
                "• **해제 방법:** `/터미널로그채널` 명령어를 채널 옵션 없이 실행"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"✅ [System] VM 터미널 실시간 로그 수신 채널이 #{채널.name} (ID: {채널.id}, 서버: {interaction.guild})로 지정되었습니다. (총 {len(t_channels)}개 서버 동시 전송)", flush=True)


@bot.command(name="터미널로그", aliases=["터미널로그채널", "서버터미널", "vm로그", "콘솔로그"])
async def set_terminal_log_channel_prefix(ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
    is_owner = await bot.is_bot_owner_user(ctx.author)
    is_admin = bool(ctx.guild and isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator)
    if not (is_owner or is_admin):
        await ctx.send("❌ 이 명령어는 **봇 소유자** 또는 **서버 관리자**만 사용할 수 있습니다.", delete_after=5)
        return

    data = await asyncio.to_thread(core.load_data)
    g_key = str(ctx.guild.id) if ctx.guild else "global"
    t_channels = data.setdefault("settings", {}).setdefault("terminal_log_channels", {})

    if channel is None:
        t_channels.pop(g_key, None)
        if not t_channels:
            data.setdefault("settings", {})["terminal_log_channel_id"] = None
        await asyncio.to_thread(core.save_data, data)
        await ctx.send(f"🛑 **현재 서버({ctx.guild.name if ctx.guild else '글로벌'})의 VM 서버 터미널 로그 채널 기록이 비활성화되었습니다.** (특정 채널에 켜려면 `!터미널로그 #채널` 입력)")
    else:
        t_channels[g_key] = channel.id
        data.setdefault("settings", {})["terminal_log_channel_id"] = channel.id
        await asyncio.to_thread(core.save_data, data)
        await ctx.send(f"🖥️ **VM 서버 터미널 로그 채널 지정 완료:** 이제부터 터미널 출력이 {channel.mention} 채널에 실시간으로 기록됩니다! (총 {len(t_channels)}개 서버 채널 동시 전송)")
        print(f"✅ [System] VM 터미널 실시간 로그 수신 채널이 #{channel.name} (ID: {channel.id}, 서버: {ctx.guild})로 지정되었습니다. (총 {len(t_channels)}개 서버 동시 전송)", flush=True)


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
                    f"✅ **현재 서버({self.guild.name if self.guild else '글로벌'})**에 슬래시 명령어 **`{g_cnt}개`**(반응역할·터미널로그 포함)가 0초 만에 즉시 등록되었습니다!\n"
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
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **봇주(Bot Owner)**만 사용할 수 있습니다.", delete_after=5)
        return

    mode = " ".join(args).strip().lower() if args else ""
    g_name = ctx.guild.name if ctx.guild else "개인 DM"

    status_msg = await ctx.send(f"⏳ **[{g_name}]** 슬래시 명령어 동기화 처리 중...")

    if any(k in mode for k in ("리로드", "reload", "새로고침", "refresh")):
        for ext in list(bot.extensions.keys()):
            try:
                await bot.reload_extension(ext)
            except Exception as e:
                print(f"⚠️ [{ext}] 리로드 실패: {e}", flush=True)

    try:
        app_id = bot.application_id or (bot.application.id if bot.application else bot.user.id)
        is_clean_mode = any(k in mode for k in ("정리", "clean", "삭제", "초기화"))
        is_guild_only = any(k in mode for k in ("길드", "guild", "서버"))

        if is_clean_mode and ctx.guild:
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
            synced_global = await bot.tree.sync()
        elif is_guild_only and ctx.guild:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced_guild = await bot.tree.sync(guild=ctx.guild)
            guild_cnt = len(synced_guild)
            synced_global = []
        else:
            # 기본 동기화: 중복 커맨드 방지를 위해 길드 로컬 캐시를 정리하고 글로벌 단일 세트로 동기화
            if ctx.guild:
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
            synced_global = await bot.tree.sync()

        view = SyncControlView(author=ctx.author, guild=ctx.guild)
        if is_guild_only:
            reg_status = (
                f"• 🏠 현재 서버({g_name}) 즉시 등록: **`{guild_cnt}개`**\n"
                f"• 💡 길드 전용 즉시 동기화 모드로 반영되었습니다."
            )
            title_text = f"⚡ [{g_name}] 길드 슬래시 명령어 동기화 완료!"
            desc_lead = f"🎉 **현재 서버에 길드 전용 슬래시 명령어 총 `{guild_cnt}개`가 등록되었습니다!**"
        else:
            reg_status = (
                f"• 🌐 글로벌 전역 명령어: **`{len(synced_global)}개`**\n"
                f"• 🧹 길드 캐시 정리: 중복 슬래시 커맨드 방지 완료"
            )
            title_text = f"⚡ [{g_name}] 글로벌 슬래시 명령어 동기화 완료!"
            desc_lead = f"🎉 **글로벌 슬래시 명령어 총 `{len(synced_global)}개`가 동기화되었습니다! (중복 방지됨)**"

        embed = discord.Embed(
            title=title_text,
            description=(
                f"{desc_lead}\n\n"
                "📊 **등록 상태:**\n"
                f"{reg_status}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 **지금 바로 채팅창에서 `/`를 눌러 사용해 보세요!**\n"
                "• `/깃허브연동` 또는 `/깃허브알림` : GitHub 푸시 및 Actions 알림 채널 연동\n"
                "• `/터미널로그채널` 또는 `!터미널로그 #채널` : VM 터미널 로그 실시간 채널 기록\n"
                "• `/반응역할` 또는 `!반응역할` : 이모지 반응역할 스튜디오 호출\n"
                "• `/플레이리스트` 또는 `!플레이리스트` : 플레이리스트 스튜디오 호출"
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
# Render 및 GCP VM 크래시 방지용 안전 실행부
# ==========================================
async def main():
    print("==================================================================", flush=True)
    print(f"🚀 [STARTUP] norosi 봇 프로세스 시작 중 (PID: {os.getpid()})", flush=True)
    print(f"⏰ 현재 시각: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (서버) / {datetime.datetime.now(core.KST).strftime('%Y-%m-%d %H:%M:%S KST')} (한국)", flush=True)
    print("==================================================================", flush=True)

    await bot.start_web_server()

    active_token = core.get_token()
    if not active_token:
        diag = core.get_env_diagnostics()
        print("❌ [치명적 오류] 유효한 DISCORD_TOKEN을 찾을 수 없습니다!", flush=True)
        print(f"📁 현재 작업 디렉토리 (CWD): {diag.get('cwd')}", flush=True)
        print(f"🔍 감지된 .env 파일 목록: {diag.get('found_env_files') or '없음'}", flush=True)
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
            print("❌ 치명적 오류: 디스코드 토큰이 유효하지 않습니다! (LoginFailure)", flush=True)
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
