import os
import re
import sys
import copy
import time
import signal
import logging
import asyncio
import datetime
import traceback
try:
    import aiohttp
    from aiohttp import web
except ImportError:
    aiohttp = None
    web = None
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional, Dict, Any
from collections import OrderedDict
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
        self._web_runner: Optional[Any] = None
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

    async def handle_github_webhook(self, request):
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
            if not isinstance(payload, dict):
                return web.json_response({"error": "Invalid JSON object"}, status=400)

            data = core.get_cached_data()
            configs = core.as_dict(core.get_github_webhook_configs(data))

            # 대상 채널 및 멘션 역할 탐색: 연동된 모든 서버 채널에 동시 전파
            target_channels_with_roles = []
            seen_channel_ids = set()

            for gid, cfg in configs.items():
                if not isinstance(cfg, dict):
                    continue
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
                repo_name = core.as_dict(payload.get("repository")).get("full_name", "저장소")
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
                repo = core.as_dict(payload.get("repository"))
                repo_full = repo.get("full_name", repo.get("name", "norosi"))
                repo_url = repo.get("html_url", "https://github.com")
                ref = payload.get("ref", "")
                branch = ref.split("/")[-1] if "/" in ref else (ref or "master")
                pusher = core.as_dict(payload.get("pusher")).get("name", "개발자")
                sender = core.as_dict(payload.get("sender"))
                sender_avatar = sender.get("avatar_url", "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png")
                raw_commits = payload.get("commits")
                commits = raw_commits if isinstance(raw_commits, list) else []
                head_commit = core.as_dict(payload.get("head_commit") or (commits[-1] if commits else {}))

                raw_msg = head_commit.get("message", "새로운 변경사항 푸시 완료")
                first_line = raw_msg.strip().split("\n")[0]
                commit_id = (head_commit.get("id") or "")[:7] or "latest"
                commit_url = head_commit.get("url", repo_url)
                compare_url = payload.get("compare", commit_url)

                added_cnt = len(head_commit.get("added") or [])
                modified_cnt = len(head_commit.get("modified") or [])
                removed_cnt = len(head_commit.get("removed") or [])

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

                wf = core.as_dict(payload.get("workflow_run"))
                wf_name = wf.get("name", "Deploy")
                conclusion = wf.get("conclusion", "success")
                run_url = wf.get("html_url", "")
                run_number = wf.get("run_number", 1)
                head_branch = wf.get("head_branch", "master")
                head_commit = core.as_dict(wf.get("head_commit"))
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
            self._web_runner = runner
            self._web_started = True
            print(f"✅ norosi 헬스체크 및 GitHub 웹훅 서버 가동 완료 (포트: {core.PORT})", flush=True)
        except Exception as e:
            print(f"ℹ️ 웹 서버 시작 건너뜀 (포트 {core.PORT} 점유 중이거나 불필요 환경): {e}", flush=True)

    async def ensure_fresh_http_session(self):
        """
        재연결/재시도 시 discord.py HTTPClient에 닫힌 aiohttp.ClientSession 또는
        닫힌 TCPConnector가 남아 'RuntimeError: Session is closed'가 발생하는 문제를 원천 차단합니다.
        """
        if self.is_closed():
            try:
                self.clear()
            except Exception:
                pass

        http_client = getattr(self, "http", None)
        if http_client is None:
            return

        # 1. 닫힌 connector가 남아있으면 None으로 되돌려 새 ClientSession이 정상 커넥터를 생성하게 함
        conn = getattr(http_client, "connector", None)
        if conn is not None and conn is not discord.utils.MISSING:
            if getattr(conn, "closed", False):
                try:
                    http_client.connector = None
                except Exception:
                    pass

        # 2. 닫힌 __session이 남아있으면 discord.utils.MISSING으로 초기화해 static_login()이 새 세션을 생성하게 함
        for attr_name in ("_HTTPClient__session", "_session"):
            if hasattr(http_client, attr_name):
                sess = getattr(http_client, attr_name, discord.utils.MISSING)
                if sess is not None and sess is not discord.utils.MISSING:
                    if getattr(sess, "closed", False):
                        try:
                            setattr(http_client, attr_name, discord.utils.MISSING)
                        except Exception:
                            pass

    async def login(self, token: str) -> None:
        await self.ensure_fresh_http_session()
        await super().login(token)

    async def add_cog(self, cog: commands.Cog, /, *, override: bool = False, **kwargs) -> None:
        cog_name = getattr(cog, "__cog_name__", type(cog).__name__)
        if not override and self.get_cog(cog_name) is not None:
            print(
                f"⚠️ [Cog 중복 등록 방지] '{cog_name}' Cog가 이미 등록되어 있어 기존 Cog를 교체합니다. "
                "(서버의 cogs/*.py 파일이 최신 버전으로 모두 동기화되었는지 확인해 주세요.)",
                flush=True,
            )
            override = True
        await super().add_cog(cog, override=override, **kwargs)

    async def setup_hook(self):
        boot_t0 = time.perf_counter()
        # 0. VM 터미널 로그 실시간 캡처 활성화
        self.setup_terminal_log_capture()

        db_t0 = time.perf_counter()
        loaded_data = await asyncio.to_thread(core.load_data)
        db_ms = (time.perf_counter() - db_t0) * 1000.0
        log_mode = core.get_terminal_log_mode(loaded_data)
        mode_badge = "요약 버전(SUMMARY)" if log_mode == "summary" else "상세 버전(DETAILED)"

        print("==================================================================", flush=True)
        if log_mode == "detailed":
            print(f"📦 [1/4] 로컬 & 하이브리드 데이터 캐시 로드 및 무결성 점검 중... (로그 모드: {mode_badge})", flush=True)
        try:
            db_file_kb = os.path.getsize(core.DATA_FILE) / 1024.0 if os.path.exists(core.DATA_FILE) else 0.0
            u_prof_cnt = len(core.as_dict(loaded_data.get("user_profiles")))
            gacha_g_cnt = len(core.as_dict(loaded_data.get("gacha_users")))
            gi_g_cnt = len(core.as_dict(loaded_data.get("genshin_users")))
            hsr_g_cnt = len(core.as_dict(loaded_data.get("hsr_users")))
            fish_g_cnt = len(core.as_dict(loaded_data.get("fishing_users")))
            dday_cnt = len(core.as_dict(loaded_data.get("ddays")))
            bday_cnt = len(core.as_dict(loaded_data.get("birthdays")))
            rr_cnt = len(core.as_dict(loaded_data.get("reaction_roles")))
            fb_mode = "Firebase 클라우드 연동" if core.get_firebase_endpoint() else "로컬 JSON + 인메모리 캐시"
            if log_mode == "summary":
                print(
                    f"📦 [1/4] 데이터 캐시 로드 완료 ({db_ms:.1f}ms | {db_file_kb:,.1f}KB | 유저 {u_prof_cnt:,}명 · D-Day {dday_cnt:,}건 | {fb_mode})",
                    flush=True,
                )
            else:
                print(
                    f"   ✓ 데이터 캐시 로드 완료 ({db_ms:.1f}ms | 파일 크기: {db_file_kb:,.1f}KB | 모드: {fb_mode})\n"
                    f"   ✓ 주요 컬렉션 요약: 유저 프로필 {u_prof_cnt:,}명 · D-Day {dday_cnt:,}건 · 생일 {bday_cnt:,}건 · 반응역할 패널 {rr_cnt:,}개\n"
                    f"   ✓ 게임별 활성 서버 풀: 프로세카 {gacha_g_cnt}곳 · 원신 {gi_g_cnt}곳 · 스타레일 {hsr_g_cnt}곳 · 낚시 {fish_g_cnt}곳",
                    flush=True,
                )
        except Exception as stat_err:
            print(f"   ℹ️ 데이터 캐시 통계 요약 생략: {stat_err}", flush=True)

        # 글로벌 슬래시 커맨드 에러 핸들러 등록 ("명령어 응답 안함" 3초 타임아웃 차단)
        self.tree.on_error = self.on_app_command_error

        if log_mode == "detailed":
            print("\n------------------------------------------------------------------", flush=True)
            print("\n🔌 [2/4] 17대 Cogs 확장 모듈 로드 및 명령어 트리 빌드 중...", flush=True)
        # 서버 배포 파일 뒤바뀜(예: fishing_core.py에 cogs/fishing.py 덮어쓰기, cogs/gacha.py에 cogs/hsr.py 덮어쓰기) 사전 진단
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            integrity_checks = [
                ("fishing_core.py", "FISH_BY_HABITAT", "class FishingCog", "cogs/fishing.py가 fishing_core.py로 잘못 저장되었습니다"),
                (os.path.join("cogs", "gacha.py"), "class GachaCog", "class HSRCog", "cogs/hsr.py가 cogs/gacha.py로 잘못 저장되었습니다"),
            ]
            for rel_path, must_have, must_not_have, hint in integrity_checks:
                full_path = os.path.join(base_dir, rel_path)
                if os.path.isfile(full_path):
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        txt = fp.read()
                    if (must_not_have and must_not_have in txt) or (must_have and must_have not in txt):
                        print(
                            f"🚨 [파일 불일치 감지] '{rel_path}' 내용이 올바르지 않습니다 ({hint}). "
                            f"최신 '{rel_path}' 원본 파일로 서버 파일을 교체해 주세요!",
                            flush=True,
                        )
        except Exception:
            pass

        # 구버전 community_core.py가 서버에 남아있어도 cogs.community / cogs.dashboard 로드 시 AttributeError가 발생하지 않도록 사전 보정
        try:
            import community_core as _cc
            if not hasattr(_cc, "STICKY_COLOR_MAP"):
                _cc.STICKY_COLOR_MAP = {
                    "gold": 0xF1C40F,
                    "blue": 0x3498DB,
                    "green": 0x2ECC71,
                    "pink": 0xFF69B4,
                    "purple": 0x9B59B6,
                    "red": 0xE74C3C,
                }
            if not hasattr(_cc, "STICKY_COLOR_LABELS"):
                _cc.STICKY_COLOR_LABELS = {
                    "gold": "🌟 골드 (노랑)",
                    "blue": "💙 블루 (파랑)",
                    "green": "💚 그린 (초록)",
                    "pink": "🩷 핑크 (분홍)",
                    "purple": "💜 퍼플 (보라)",
                    "red": "❤️ 레드 (빨강)",
                }
            if not hasattr(_cc, "RAID_ACTION_LABELS"):
                _cc.RAID_ACTION_LABELS = {
                    "timeout": "⏳ 60분 타임아웃(활동 제한)",
                    "kick": "👢 즉시 추방 (Kick)",
                    "quarantine": "🔒 격리 역할 부여 (신규 격리)",
                }
            if not hasattr(_cc, "get_relay_completed_list") and hasattr(_cc, "get_completed_relay_novels"):
                _cc.get_relay_completed_list = _cc.get_completed_relay_novels
            if not hasattr(_cc, "get_relay_archives") and hasattr(_cc, "get_completed_relay_novels"):
                _cc.get_relay_archives = _cc.get_completed_relay_novels
        except Exception:
            pass

        ext_list = [
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
            "cogs.help",
            "cogs.dashboard",
        ]
        failed_exts = []
        loaded_exts = []
        for idx, ext in enumerate(ext_list, start=1):
            ext_t0 = time.perf_counter()
            before_slash = len(self.tree.get_commands())
            before_prefix = len(self.commands)
            try:
                if ext in self.extensions:
                    try:
                        await self.reload_extension(ext)
                    except Exception:
                        try:
                            await self.unload_extension(ext)
                        except Exception:
                            pass
                        await self.load_extension(ext)
                else:
                    await self.load_extension(ext)
                ext_ms = (time.perf_counter() - ext_t0) * 1000.0
                after_slash = len(self.tree.get_commands())
                after_prefix = len(self.commands)
                added_slash = max(0, after_slash - before_slash)
                added_prefix = max(0, after_prefix - before_prefix)
                loaded_exts.append(ext)
                if log_mode == "detailed":
                    print(
                        f"   [{idx:02d}/{len(ext_list):02d}] ✓ {ext:<16} 로드 성공 ({ext_ms:6.1f}ms | 슬래시 +{added_slash} · 프리픽스 +{added_prefix})",
                        flush=True,
                    )
                if ext == "cogs.gacha" and self.get_cog("GachaCog") is None:
                    print(
                        "🚨 [파일 동기화 경고] 'cogs.gacha' 로드 후 GachaCog가 등록되지 않았습니다! "
                        "서버의 cogs/gacha.py 파일이 최신 버전으로 교체되었는지 확인해 주세요.",
                        flush=True,
                    )
            except Exception as e:
                ext_ms = (time.perf_counter() - ext_t0) * 1000.0
                print(f"   [{idx:02d}/{len(ext_list):02d}] ⚠️ {ext:<16} 로드 실패 ({ext_ms:6.1f}ms): {e}", flush=True)
                failed_exts.append((ext, e))
        if len(failed_exts) == len(ext_list):
            raise failed_exts[0][1]

        top_cmds = self.tree.get_commands()
        sub_cmd_cnt = 0
        for cmd in top_cmds:
            if isinstance(cmd, app_commands.Group):
                sub_cmd_cnt += len(cmd.commands)
            else:
                sub_cmd_cnt += 1
        if log_mode == "summary":
            print(
                f"🔌 [2/4] Cogs 모듈 {len(loaded_exts)}/{len(ext_list)}개 로드 완료 "
                f"(슬래시 루트 {len(top_cmds)}개/세부 {sub_cmd_cnt}종 · 프리픽스(!) {len(self.commands)}개 · SafeView {len(core.SAFE_VIEW_REGISTRY)}종)",
                flush=True,
            )
        else:
            print(
                f"   📊 [Cogs 요약] 성공: {len(loaded_exts)}/{len(ext_list)}개 모듈 | "
                f"슬래시 루트: {len(top_cmds)}개 (세부 실행 커맨드: {sub_cmd_cnt}종) | "
                f"프리픽스(!) 명령어: {len(self.commands)}개 | "
                f"등록된 SafeView 클래스: {len(core.SAFE_VIEW_REGISTRY)}종",
                flush=True,
            )

        self.register_persistent_views()

        if log_mode == "detailed":
            print("------------------------------------------------------------------", flush=True)
            print("📚 [3/4] 게임 마스터 DB (프로세카 · 원신 · 스타레일 · 낚시 · 타인의인생) 백그라운드 워밍 시작...", flush=True)
        asyncio.create_task(self._warm_master_databases(log_mode))

        if log_mode == "detailed":
            print("------------------------------------------------------------------", flush=True)
            print("⏰ [4/4] 상주 스케줄러 및 VM 터미널 로그 브릿지 루프 활성화...", flush=True)
        scheduler_specs = [
            ("midnight_tasks", self.midnight_tasks, "매일 00:00 KST 자정 DB 갱신 · 반복 D-Day · 생일 축하"),
            ("morning_music_alert", self.morning_music_alert, "매일 07:00 KST 모닝 추천 음악 자동 발송"),
            ("morning_text_alert", self.morning_text_alert, "매일 09:00 KST D-Day 브리핑 · 비밀 타임캡슐 DM"),
            ("custom_music_schedules_loop", self.custom_music_schedules_loop, "30초 주기 맞춤 음악 알람 · 개인 예약 알림(/알림예약)"),
            ("terminal_log_dispatch_loop", self.terminal_log_dispatch_loop, "3초 주기 VM 터미널 로그 디스코드 브릿지"),
        ]
        for loop_name, loop_obj, loop_desc in scheduler_specs:
            if not loop_obj.is_running():
                loop_obj.start()
            if log_mode == "detailed":
                print(f"   ✓ [{loop_name}] 가동 중 — {loop_desc}", flush=True)

        total_boot_ms = (time.perf_counter() - boot_t0) * 1000.0
        if log_mode == "summary":
            print(
                f"⏰ [4/4] 상주 스케줄러 {len(scheduler_specs)}종 가동 완료 | 초기 부팅 파이프라인 {total_boot_ms:.1f}ms (로그 모드: {mode_badge})",
                flush=True,
            )
        else:
            print(f"✨ [setup_hook 완료] 초기 부팅 파이프라인 준비 완료 (소요 시간: {total_boot_ms:.1f}ms | 로그 모드: {mode_badge})", flush=True)
        print("==================================================================", flush=True)

    async def _warm_master_databases(self, log_mode: Optional[str] = None):
        """프로세카(미래시 포함), 원신, 스타레일, 낚시, 타인의인생 마스터 DB를 백그라운드에서 워밍하고 공개 통계를 로그로 출력합니다."""
        w_t0 = time.perf_counter()
        eff_mode = log_mode or core.get_terminal_log_mode()
        p_cards = p_costumes = p_quotes = fc_cnt = 0
        g_chars = g_weaps = g_arts = 0
        h_chars = h_lcs = h_relics = 0
        fish_total = endings_total = origins_total = specs_total = 0

        try:
            await asyncio.to_thread(core.load_proseka_kr_db)
            p_cards = len(getattr(core, "PROSEKA_CARDS", []) or [])
            p_costumes = len(getattr(core, "PROSEKA_COSTUMES", []) or [])
            p_quotes = len(getattr(core, "PROSEKA_QUOTES", []) or [])
            if eff_mode == "detailed":
                print(
                    f"   🎵 [DB 워밍: 프로세카] 한국어 마스터 DB 준비 완료 — 카드 {p_cards:,}장 · 3D 의상 {p_costumes:,}종 · 대사 {p_quotes:,}개",
                    flush=True,
                )
            fc_list = await asyncio.to_thread(core.get_event_forecast_list, True)
            fc_cnt = len(fc_list or [])
            if fc_list and eff_mode == "detailed":
                today_s = datetime.datetime.now(core.KST).strftime("%Y-%m-%d")
                cur_ev = next((e for e in fc_list if e.get("kr_estimated_start", "") <= today_s <= e.get("kr_estimated_end", "")), None)
                nxt_ev = next((e for e in fc_list if e.get("kr_estimated_start", "") > today_s), None)
                ev_target = cur_ev or nxt_ev or fc_list[-1]
                st_lbl = "진행중" if cur_ev else "차기예정"
                print(
                    f"   📅 [DB 워밍: 프세카 미래시] 한섭·일섭 미래시 일정표 준비 완료 — 총 {len(fc_list)}개 이벤트 (#{fc_list[0]['id']}~#{fc_list[-1]['id']}) | "
                    f"{st_lbl}: #{ev_target['id']} {ev_target['name']} ({ev_target['kr_estimated_start']}~{ev_target['kr_estimated_end']})",
                    flush=True,
                )
        except Exception as e:
            print(f"   ⚠️ [DB 워밍: 프로세카] 로드 경고: {e}", flush=True)

        try:
            import genshin_core
            await asyncio.to_thread(genshin_core.load_genshin_kr_db)
            g_chars = len(getattr(genshin_core, "GENSHIN_CHARS", []) or [])
            g_weaps = len(getattr(genshin_core, "GENSHIN_WEAPONS", []) or [])
            g_arts = len(getattr(genshin_core, "GENSHIN_ARTIFACTS", []) or [])
            if eff_mode == "detailed":
                print(
                    f"   🌠 [DB 워밍: 원신] 한국어 마스터 DB 준비 완료 — 캐릭터 {g_chars:,}명 · 무기 {g_weaps:,}종 · 성유물 세트 {g_arts:,}종",
                    flush=True,
                )
        except Exception as e:
            print(f"   ⚠️ [DB 워밍: 원신] 로드 경고: {e}", flush=True)

        try:
            import hsr_core
            await asyncio.to_thread(hsr_core.load_hsr_kr_db)
            h_chars = len(getattr(hsr_core, "HSR_CHARS", []) or [])
            h_lcs = len(getattr(hsr_core, "HSR_LIGHT_CONES", []) or [])
            h_relics = len(getattr(hsr_core, "HSR_RELICS", []) or [])
            if eff_mode == "detailed":
                print(
                    f"   🚄 [DB 워밍: 스타레일] 한국어 마스터 DB 준비 완료 — 캐릭터 {h_chars:,}명 · 광추 {h_lcs:,}종 · 유물 세트 {h_relics:,}종",
                    flush=True,
                )
        except Exception as e:
            print(f"   ⚠️ [DB 워밍: 스타레일] 로드 경고: {e}", flush=True)

        try:
            import fishing_core, other_life_core
            fish_total = sum(len(v) for v in getattr(fishing_core, "FISH_BY_HABITAT", {}).values())
            endings_total = len(getattr(other_life_core, "ENDINGS", {}) or {})
            origins_total = len(getattr(other_life_core, "ORIGINS", {}) or {})
            specs_total = len(getattr(other_life_core, "SPECIALTY_CATALOG", {}) or {})
            w_ms = (time.perf_counter() - w_t0) * 1000.0
            if eff_mode == "summary":
                print(
                    f"📚 [3/4] 마스터 DB 워밍 완료 ({w_ms:.0f}ms | 프세카 {p_cards:,}장·미래시 {fc_cnt}건 · 원신 {g_chars}명 · 스타레일 {h_chars}명 · 어종 {fish_total:,}종 · 엔딩 {endings_total:,}종)",
                    flush=True,
                )
            else:
                print(
                    f"   🎣 [DB 워밍: 낚시 & 타인의인생] 어종 DB {fish_total:,}종 · 타인의인생 엔딩 {endings_total:,}종 (출신 {origins_total}종 · 세부전공 {specs_total}종) 확인 완료 (총 {w_ms:.0f}ms)",
                    flush=True,
                )
        except Exception as e:
            print(f"   ℹ️ [DB 워밍: 보조 DB] 확인 생략: {e}", flush=True)

    @tasks.loop(seconds=3.0)
    async def terminal_log_dispatch_loop(self):
        """3초마다 VM 터미널 출력 큐를 확인하여 지정된 모든 서버 채널로 안전하게 묶음 전송 (레이트 리밋 방어 탑재)"""
        if not self.terminal_log_queue or self.terminal_log_queue.empty():
            return

        data = core.get_cached_data()
        target_channel_ids = set()

        # 1. 서버별 등록된 터미널 로그 채널 목록 수집
        settings_d = core.as_dict(data.get("settings"))
        t_channels = settings_d.get("terminal_log_channels", {})
        if isinstance(t_channels, dict):
            for cid in t_channels.values():
                if cid and str(cid).isdigit():
                    target_channel_ids.add(int(cid))
        elif isinstance(t_channels, (list, set)):
            for cid in t_channels:
                if cid and str(cid).isdigit():
                    target_channel_ids.add(int(cid))

        # 2. 레거시 단일 설정 채널 ID도 포함
        legacy_id = settings_d.get("terminal_log_channel_id")
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
        log_mode = core.get_terminal_log_mode(data)

        # 요약 버전(summary) 설정 시: 반복적인 하위 상세 라인이나 일반 INFO 트레이스는 생략하고 핵심 단계/경고/오류만 추출
        if log_mode == "summary":
            summary_keep_markers = (
                "🚀", "📦", "🔌", "📚", "⏰", "✨", "✅", "⚠️", "🚨", "❌", "🛑", "🎉", "🔑", "🌐",
                "[STARTUP", "[READY", "[무로시로그]", "[ERROR]", "[WARNING]", "[CRITICAL]",
                "Traceback", "Exception", "Error:",
            )
            filtered_lines = []
            for raw_line in full_text.splitlines(keepends=True):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("====", "----")):
                    continue
                if any(marker in stripped for marker in summary_keep_markers):
                    filtered_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
            full_text = "".join(filtered_lines)
            if not full_text.strip():
                return

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

    def register_persistent_views(self):
        """영구(Persistent) View들을 봇 ViewStore에 등록/재등록합니다 (초기 부팅 및 핫 리로드 시 호출)."""
        try:
            from cogs.roles import PersistentReactionRoleView
            cached_d = core.get_cached_data()
            restored_cnt = 0
            for mid_s, cfg in core.as_dict(cached_d.get("reaction_roles")).items():
                if not isinstance(cfg, dict):
                    continue
                r_list = cfg.get("roles", [])
                if r_list and str(mid_s).isdigit():
                    self.add_view(PersistentReactionRoleView(r_list), message_id=int(mid_s))
                    restored_cnt += 1
            if restored_cnt > 0:
                print(f"🎭 반응역할 지속 View {restored_cnt}개 복원 완료", flush=True)
        except Exception as e:
            print(f"ℹ️ 반응역할 지속 View 복원 건너뜀: {e}", flush=True)

        try:
            from cogs.tickets import TicketPanelView, TicketControlView
            self.add_view(TicketPanelView())
            self.add_view(TicketControlView())
            print("🎫 1:1 티켓 영구 View (패널/제어) 등록 완료", flush=True)
        except Exception as e:
            print(f"ℹ️ 1:1 티켓 영구 View 등록 건너뜀: {e}", flush=True)

        try:
            from cogs.community import LinkCleanupView, RaidAlertControlView, RelayNovelView
            self.add_view(LinkCleanupView())
            self.add_view(RaidAlertControlView())
            self.add_view(RelayNovelView())
            print("🛡️ 커뮤니티 영구 View (링크/비상방어/릴레이소설) 등록 완료", flush=True)
        except Exception as e:
            print(f"ℹ️ 커뮤니티 영구 View 등록 건너뜀: {e}", flush=True)

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

        # 1-B. 커뮤니티 및 1:1 티켓 전용 고정 custom_id 폴백
        non_prefix_view_map = {
            "link_preview:delete": ("LinkCleanupView",),
            "raid_defense:unlock": ("RaidAlertControlView",),
            "raid_defense:logs": ("RaidAlertControlView",),
            "relay_novel:write": ("RelayNovelView",),
            "relay_novel:preview": ("RelayNovelView",),
            "relay_novel:finish": ("RelayNovelView",),
        }
        if custom_id in non_prefix_view_map or custom_id.startswith("norosi:Ticket"):
            try:
                target_cls_name = non_prefix_view_map.get(custom_id, (None,))[0]
                if not target_cls_name and custom_id.startswith("norosi:Ticket"):
                    target_cls_name = custom_id.split(":", 2)[1]
                v_cls = core.SAFE_VIEW_REGISTRY.get(target_cls_name or "")
                if v_cls:
                    v_inst = core.reconstruct_safe_view(v_cls, interaction)
                    if v_inst:
                        for ch_item in v_inst.children:
                            if getattr(ch_item, "custom_id", None) == custom_id and hasattr(ch_item, "callback"):
                                await ch_item.callback(interaction)
                                return
            except Exception as e:
                print(f"⚠️ [전용 영구 뷰 폴백 예외] {custom_id}: {e}", flush=True)

        # 2. 결정론적 커스텀 ID 패턴: norosi:{ViewClassName}:{item_name}
        if custom_id.startswith("norosi:"):
            parts = custom_id.split(":", 2)
            if len(parts) >= 3:
                raw_view_name = parts[1]
                legacy_view_aliases = {
                    "forecast": "EventForecastView",
                }
                view_name = legacy_view_aliases.get(raw_view_name, raw_view_name)
                item_name = parts[2]
                legacy_item_aliases = {
                    ("EventForecastView", "prev"): "on_prev_month",
                    ("EventForecastView", "cur"): "on_current_month",
                    ("EventForecastView", "next"): "on_next_month",
                    ("EventForecastView", "all"): "on_show_all_list",
                }
                item_name = legacy_item_aliases.get((view_name, item_name), item_name)
                view_cls = core.SAFE_VIEW_REGISTRY.get(view_name)
                if view_cls:
                    try:
                        view = core.reconstruct_safe_view(view_cls, interaction)
                        if view:
                            if view_name == "MasterDashboardView" and msg and msg.embeds:
                                e_title = (msg.embeds[0].title or "")
                                if "원신" in e_title:
                                    view.current_tab = "genshin"
                                elif "스타레일" in e_title:
                                    view.current_tab = "hsr"
                                elif "프로세카" in e_title or "가챠" in e_title:
                                    view.current_tab = "gacha"
                                elif "낚시" in e_title:
                                    view.current_tab = "fishing"
                                elif "통합 경제" in e_title or "생활 라이프" in e_title or "경제" in e_title:
                                    view.current_tab = "economy"
                                elif "D-Day" in e_title or "집중 대시보드" in e_title or "라이프" in e_title:
                                    view.current_tab = "life"
                                elif "음악" in e_title or "플레이리스트" in e_title or "DJ" in e_title:
                                    view.current_tab = "music"
                                elif "역할" in e_title or "서버 관리" in e_title or "커뮤니티" in e_title:
                                    view.current_tab = "admin"
                                elif "미니게임" in e_title or "파티 모집" in e_title or "타인의 인생" in e_title:
                                    view.current_tab = "game"
                                elif "통계" in e_title or "호스트" in e_title:
                                    view.current_tab = "stats"
                                if hasattr(view, "refresh_components"):
                                    view.refresh_components()
                            elif view_name == "OtherLifeCollectionView" and msg and msg.embeds:
                                e_title = (msg.embeds[0].title or "")
                                if "수집 요약" in e_title:
                                    view.tab = "summary"
                                elif "전기 아카이브" in e_title:
                                    view.tab = "history"
                                else:
                                    view.tab = "endings"
                                if hasattr(view, "_rebuild"):
                                    view._rebuild()
                            elif view_name == "OtherLifeGameView":
                                if item_name in ("origin_select", "start_life", "resume_life") and getattr(view, "mode", "") != "setup":
                                    view.mode = "setup"
                                    if hasattr(view, "_rebuild"):
                                        view._rebuild()

                            target_item = None
                            for child in view.children:
                                if getattr(child, "custom_id", None) == custom_id:
                                    target_item = child
                                    break
                            if not target_item:
                                for child in view.children:
                                    cb_obj = getattr(child, "callback", None)
                                    inner_cb = getattr(cb_obj, "callback", None)
                                    cb_names = {
                                        getattr(cb_obj, "__name__", ""),
                                        getattr(inner_cb, "__name__", ""),
                                    }
                                    if item_name in cb_names or f"_on_{item_name}" in cb_names:
                                        target_item = child
                                        break
                                    if getattr(child, "label", None) == item_name:
                                        target_item = child
                                        break
                            if target_item and hasattr(target_item, "callback"):
                                if hasattr(view, "interaction_check"):
                                    try:
                                        allowed = await view.interaction_check(interaction)
                                        if not allowed:
                                            return
                                    except Exception as chk_err:
                                        print(f"⚠️ [norosi interaction_check 예외] {chk_err}", flush=True)
                                if hasattr(target_item, "_refresh_state"):
                                    try:
                                        target_item._refresh_state(interaction, interaction.data)
                                    except Exception:
                                        pass
                                try:
                                    await target_item.callback(interaction)
                                except Exception as cb_err:
                                    print(f"⚠️ [norosi 버튼 콜백 실행 예외] {view_name}.{item_name}: {cb_err}", flush=True)
                                    try:
                                        await view.on_error(interaction, cb_err, target_item)
                                    except Exception:
                                        pass
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return

                            # 다른 탭/모드/배너 상태에서 동적으로 생성된 버튼 메서드 직접 호출 폴백
                            direct_cb = None
                            if view_name == "OtherLifeGameView" and item_name.startswith("choice:") and hasattr(view, "_make_choice_cb"):
                                direct_cb = view._make_choice_cb(item_name.split(":", 1)[1])
                            else:
                                cand = getattr(view, item_name, None) or getattr(view, f"_on_{item_name}", None)
                                if callable(cand):
                                    direct_cb = cand
                            if direct_cb is not None:
                                if hasattr(view, "interaction_check"):
                                    try:
                                        allowed = await view.interaction_check(interaction)
                                        if not allowed:
                                            return
                                    except Exception as chk_err:
                                        print(f"⚠️ [norosi interaction_check 예외] {chk_err}", flush=True)
                                try:
                                    sig_params = list(inspect.signature(direct_cb).parameters.values())
                                    if len(sig_params) <= 1:
                                        await direct_cb(interaction)
                                    else:
                                        await direct_cb(interaction, None)
                                except Exception as cb_err:
                                    print(f"⚠️ [norosi 직접 메서드 실행 예외] {view_name}.{item_name}: {cb_err}", flush=True)
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return
                    except Exception as e:
                        print(f"⚠️ [norosi 뷰 복구 예외] {view_name}.{item_name}: {e}", flush=True)

        # 3. 코드 반영 전 구버전 메시지(랜덤 hex custom_id) 지능형 매칭 및 복구
        if msg:
            embed_text = ""
            e_title_only = ""
            if msg.embeds:
                emb = msg.embeds[0]
                e_title_only = emb.title or ""
                embed_text = f"{e_title_only} {emb.description or ''}"

            clicked_label = ""
            component_type = interaction.data.get("component_type", 2)
            for row in getattr(msg, "components", []):
                for child in getattr(row, "children", []):
                    if child.custom_id == custom_id:
                        clicked_label = getattr(child, "label", "") or ""
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
                            await core.safe_send_response(interaction, f"⚠️ 버튼 처리 중 오류가 발생했습니다: `{cb_err}`", ephemeral=True)
                        if msg:
                            self.attach_view_to_message(view, message_id=msg.id)
                        return
                except Exception as e:
                    print(f"⚠️ [음성 플레이어 리모컨 구버전 복구 예외] {e}", flush=True)

            # 3-2. 올인원 마스터 대시보드
            if "대시보드" in e_title_only or "마스터 대시보드" in embed_text or "norosi 통합 제어" in embed_text:
                try:
                    from cogs.dashboard import MasterDashboardView
                    data = core.get_cached_data()
                    view = MasterDashboardView(self, interaction.user, interaction.guild, data)
                    view.message = msg
                    if "원신" in e_title_only:
                        view.current_tab = "genshin"
                    elif "스타레일" in e_title_only:
                        view.current_tab = "hsr"
                    elif "프로세카" in e_title_only or "가챠" in e_title_only:
                        view.current_tab = "gacha"
                    elif "통합 경제" in e_title_only or "생활 라이프" in e_title_only or "경제" in e_title_only:
                        view.current_tab = "economy"
                    elif "라이프" in e_title_only or "D-Day" in e_title_only:
                        view.current_tab = "life"
                    elif "음악" in e_title_only or "플레이리스트" in e_title_only:
                        view.current_tab = "music"
                    elif "역할" in e_title_only or "서버 관리" in e_title_only:
                        view.current_tab = "admin"
                    elif "미니게임" in e_title_only or "파티 모집" in e_title_only:
                        view.current_tab = "game"
                    elif "통계" in e_title_only or "호스트" in e_title_only:
                        view.current_tab = "stats"
                    view.refresh_components()

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
                                    await core.safe_send_response(interaction, f"⚠️ 메뉴 처리 중 오류가 발생했습니다: `{cb_err}`", ephemeral=True)
                                if msg:
                                    self.attach_view_to_message(view, message_id=msg.id)
                                return
                    elif "새로고침" in clicked_label:
                        try:
                            await view._on_refresh_clicked(interaction)
                        except Exception as cb_err:
                            print(f"⚠️ [마스터 대시보드 새로고침 콜백 예외] {cb_err}", flush=True)
                            await core.safe_send_response(interaction, f"⚠️ 새로고침 중 오류가 발생했습니다: `{cb_err}`", ephemeral=True)
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
                                    await core.safe_send_response(interaction, f"⚠️ 버튼 처리 중 오류가 발생했습니다: `{cb_err}`", ephemeral=True)
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
                                await core.safe_send_response(interaction, f"⚠️ 버튼 처리 중 오류가 발생했습니다: `{cb_err}`", ephemeral=True)
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
            sync_t0 = time.perf_counter()
            log_mode = core.get_terminal_log_mode()
            if log_mode == "detailed":
                print("🌐 [백그라운드 동기화] 글로벌 슬래시 명령어 트리 Discord API 동기화 시작...", flush=True)
            synced_cmds = await self.tree.sync()
            sync_ms = (time.perf_counter() - sync_t0) * 1000.0
            if log_mode == "summary":
                print(f"✅ [동기화 완료] 글로벌 슬래시 명령어 총 {len(synced_cmds)}개 등록 완료 ({sync_ms:.0f}ms)", flush=True)
            else:
                cmd_names_preview = ", ".join(f"/{c.name}" for c in synced_cmds[:15])
                more_tag = f" 외 {len(synced_cmds) - 15}개" if len(synced_cmds) > 15 else ""
                print(
                    f"✅ [동기화 완료] 글로벌 슬래시 명령어 총 {len(synced_cmds)}개 등록 완료! ({sync_ms:.0f}ms)\n"
                    f"   📋 등록 명령어 샘플: {cmd_names_preview}{more_tag}",
                    flush=True,
                )
        except discord.HTTPException as e:
            if e.status == 429:
                print(f"⏳ [동기화 알림] Discord API 속도 제한(429 Rate Limit) 감지: {e}. 백그라운드에서 대기 후 자동 재시도됩니다.", flush=True)
            else:
                print(f"⚠️ [동기화 오류] 슬래시 명령어 등록 중 HTTP 예외: {e}", flush=True)
        except Exception as e:
            print(f"⚠️ [동기화 오류] 백그라운드 명령어 동기화 예외: {e}", flush=True)

    async def on_ready(self):
        fb_status = "연동됨 (Firebase Realtime DB)" if core.get_firebase_endpoint() else "로컬 JSON + 인메모리 캐시 모드"
        guild_cnt = len(self.guilds)
        total_members = sum(getattr(g, "member_count", 0) or len(getattr(g, "members", [])) for g in self.guilds)
        ws_ping_ms = round(self.latency * 1000, 1) if self.latency and self.latency > 0 else 0.0
        sekai_t = core.get_proseka_sekai_time_theme()
        data = core.get_cached_data()
        t_channels = core.as_dict(core.as_dict(data.get("settings")).get("terminal_log_channels"))
        log_mode = core.get_terminal_log_mode(data)
        mode_badge = "요약 버전(SUMMARY)" if log_mode == "summary" else "상세 버전(DETAILED)"
        print("==================================================================", flush=True)
        if log_mode == "summary":
            print(
                f"✅ [READY/요약] {self.user} 준비 완료 (핑 {ws_ping_ms}ms · 서버 {guild_cnt:,}곳/{total_members:,}명 · {fb_status} · 세카이 {sekai_t['hour_str']} · 터미널채널 {len(t_channels)}곳)",
                flush=True,
            )
        else:
            print(f"✅ [READY] 무로시(norosi) 디스코드 게이트웨이 연결 및 준비 완료! (로그 모드: {mode_badge})", flush=True)
            print(f"   • 봇 계정     : {self.user} (ID: {self.user.id})", flush=True)
            print(f"   • 게이트웨이  : WebSocket 핑 {ws_ping_ms}ms | 연결 서버 {guild_cnt:,}곳 (총 멤버 약 {total_members:,}명)", flush=True)
            print(f"   • 데이터 엔진 : {fb_status} | 터미널 브릿지 연동 채널 {len(t_channels)}곳 | 로그 모드: {mode_badge}", flush=True)
            print(f"   • 세카이 시각 : {sekai_t['hour_str']} ({sekai_t['phase_name']}) — {sekai_t['unit_label']} / {sekai_t['attr_label']}", flush=True)
            if self.guilds:
                guild_summary = ", ".join(f"{g.name}({getattr(g, 'member_count', 0) or 0}명)" for g in self.guilds[:8])
                if len(self.guilds) > 8:
                    guild_summary += f" 외 {len(self.guilds) - 8}곳"
                print(f"   • 접속 서버   : {guild_summary}", flush=True)
        print("==================================================================", flush=True)

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
        ddays = core.as_dict(data.get("ddays"))
        if not ddays:
            return

        alert_ch_id = core.as_dict(data.get("settings")).get("dday_alert_channel_id")
        alert_channel = await self.resolve_channel(alert_ch_id) if alert_ch_id else None

        for name, info in ddays.items():
            if not isinstance(info, dict):
                continue
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
            asyncio.to_thread(core.refresh_proseka_dbs, True),
            asyncio.to_thread(genshin_core.load_genshin_kr_db, True),
            asyncio.to_thread(hsr_core.load_hsr_kr_db, True),
            return_exceptions=True,
        )

        data = await asyncio.to_thread(core.load_data)
        today = datetime.datetime.now(core.KST).date()
        dday_repeat_updates: Dict[str, tuple[str, str]] = {}
        bday_celebrated: Dict[str, int] = {}

        for name, info in core.as_dict(data.get("ddays")).items():
            if not isinstance(info, dict):
                continue
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
                    new_date_str = t_date.strftime("%Y-%m-%d")
                    info["date"] = new_date_str
                    info["start_date"] = old_target_str
                    dday_repeat_updates[name] = (new_date_str, old_target_str)

        # 자정(00:00 KST) 멤버 생일 자동 축하 및 +500 크리스탈 지급
        bday_map = core.as_dict(data.get("birthdays"))
        alert_ch_id = core.as_dict(data.get("settings")).get("dday_alert_channel_id")
        alert_ch = await self.resolve_channel(alert_ch_id) if alert_ch_id else None

        for u_key, b_info in bday_map.items():
            if not isinstance(b_info, dict):
                continue
            if b_info.get("month") == today.month and b_info.get("day") == today.day:
                if b_info.get("last_celebrated_year") != today.year:
                    b_info["last_celebrated_year"] = today.year
                    bday_celebrated[str(u_key)] = today.year
                    uid = b_info.get("user_id") or int(u_key)
                    uname = b_info.get("user_name", "멤버")
                    prof = core.ensure_user_profile(data, u_key, uname)
                    prof["crystals"] = prof.get("crystals", 0) + 500

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
                        g_settings = core.safe_get_dict(data, "guild_settings", str(g_id))
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

        if dday_repeat_updates or bday_celebrated:
            def _commit_midnight_updates():
                with core._DATA_LOCK:
                    fresh_data = core.load_data()
                    changed = False
                    fresh_ddays = core.ensure_dict_path(fresh_data, "ddays")
                    for d_name, (new_d, new_s) in dday_repeat_updates.items():
                        if isinstance(fresh_ddays.get(d_name), dict):
                            fresh_ddays[d_name]["date"] = new_d
                            fresh_ddays[d_name]["start_date"] = new_s
                            changed = True
                    fresh_bdays = core.ensure_dict_path(fresh_data, "birthdays")
                    for u_k, yr in bday_celebrated.items():
                        b_rec = fresh_bdays.get(u_k)
                        if isinstance(b_rec, dict) and b_rec.get("last_celebrated_year") != yr:
                            b_rec["last_celebrated_year"] = yr
                            prof = core.ensure_user_profile(fresh_data, u_k, b_rec.get("user_name", "멤버"))
                            prof["crystals"] = int(prof.get("crystals", 0) or 0) + 500
                            changed = True
                    if changed:
                        core.save_data(fresh_data)
            await asyncio.to_thread(_commit_midnight_updates)

        await self.update_all_dday_channels()

    @midnight_tasks.before_loop
    async def before_midnight_tasks(self):
        await self.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=7, minute=0, tzinfo=core.KST))
    async def morning_music_alert(self):
        data = await asyncio.to_thread(core.load_data)
        guild_mps = core.as_dict(data.get("guild_music_prefs"))
        targets = []
        seen_channels = set()
        for g_key, g_mp in guild_mps.items():
            if not isinstance(g_mp, dict):
                continue
            ch_id = g_mp.get("channel_id")
            if ch_id and ch_id not in seen_channels:
                targets.append((core.get_guild_music_prefs(data, g_key), ch_id))
                seen_channels.add(ch_id)

        global_mp = core.get_guild_music_prefs(data, 0)
        fallback_ch_id = global_mp.get("channel_id") or core.as_dict(data.get("settings")).get("dday_alert_channel_id")
        if fallback_ch_id and fallback_ch_id not in seen_channels:
            targets.append((None, fallback_ch_id))
            seen_channels.add(fallback_ch_id)

        for prefs, target_ch_id in targets:
            channel = await self.resolve_channel(target_ch_id)
            if not channel:
                continue
            if prefs is None:
                ch_gid = getattr(getattr(channel, "guild", None), "id", 0) or 0
                prefs = core.get_guild_music_prefs(data, ch_gid)

            track_info, error = await core.get_recommended_music(prefs)
            if error or not track_info:
                try:
                    await channel.send(f"🎧 **오늘의 음악 추천 실패:** {error}")
                except Exception:
                    pass
                continue
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
        raw_schedules = data.get("music_schedules")
        schedules = raw_schedules if isinstance(raw_schedules, list) else []
        raw_reminders = data.get("reminders")
        reminders = raw_reminders if isinstance(raw_reminders, list) else []
        if not schedules and not reminders:
            return

        sent_sched_keys: set[str] = set()
        fired_rem_ids: set[str] = set()

        def _sched_key(s: dict) -> str:
            return str(s.get("id") or f"{s.get('time')}|{s.get('channel_id')}|{s.get('name')}")

        for sched in schedules:
            if not isinstance(sched, dict):
                continue
            if sched.get("time") == now_hm and sched.get("last_sent") != today_str:
                ch_id = sched.get("channel_id")
                channel = await self.resolve_channel(ch_id) if ch_id else None
                if channel:
                    sched_gid = sched.get("guild_id") or getattr(getattr(channel, "guild", None), "id", 0) or 0
                    custom_prefs = copy.deepcopy(core.get_guild_music_prefs(data, sched_gid))
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
                sent_sched_keys.add(_sched_key(sched))

        # /알림예약 개인 알리미 시각 도달 체크 및 발송
        now_ts = time.time()
        for rem in reminders:
            if not isinstance(rem, dict):
                continue
            if rem.get("trigger_ts", 0) <= now_ts:
                if rem.get("id") is not None:
                    fired_rem_ids.add(str(rem.get("id")))
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

        if sent_sched_keys or fired_rem_ids:
            def _commit_music_and_rem_updates():
                with core._DATA_LOCK:
                    fresh_data = core.load_data()
                    changed = False
                    fresh_scheds = fresh_data.get("music_schedules")
                    if isinstance(fresh_scheds, list) and sent_sched_keys:
                        for s_item in fresh_scheds:
                            if isinstance(s_item, dict) and _sched_key(s_item) in sent_sched_keys:
                                if s_item.get("last_sent") != today_str:
                                    s_item["last_sent"] = today_str
                                    changed = True
                    fresh_raw_reminders = fresh_data.get("reminders")
                    if isinstance(fresh_raw_reminders, list):
                        new_rems = [
                            r for r in fresh_raw_reminders
                            if isinstance(r, dict)
                            and str(r.get("id")) not in fired_rem_ids
                            and r.get("trigger_ts", 0) > now_ts
                        ]
                        if len(new_rems) != len(fresh_raw_reminders):
                            fresh_data["reminders"] = new_rems
                            changed = True
                    if changed:
                        core.save_data(fresh_data)
            await asyncio.to_thread(_commit_music_and_rem_updates)

    @custom_music_schedules_loop.before_loop
    async def before_custom_music_loop(self):
        await self.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=core.KST))
    async def morning_text_alert(self):
        data = await asyncio.to_thread(core.load_data)
        today_str = core.get_today_str()

        # 1. 나만의 비밀 디데이 & 타임캡슐 개인 DM 발송 체크
        notified_secrets: list[tuple[str, str]] = []
        notified_partners: list[tuple[str, str]] = []
        for u_key, p_info in core.as_dict(data.get("user_profiles")).items():
            if not isinstance(p_info, dict):
                continue
            secret_ddays = core.as_dict(p_info.get("secret_ddays"))
            for s_name, s_info in secret_ddays.items():
                if not isinstance(s_info, dict) or not s_info.get("date"):
                    continue
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
                            notified_secrets.append((str(u_key), s_name))
                    except Exception as e:
                        print(f"⚠️ 비밀 디데이 DM 전송 실패 ({u_key}): {e}", flush=True)

        # 2. 파트너 공동 D-Day 당일 두 사람에게 DM 발송 체크
        for pair_key, pair_info in core.as_dict(data.get("partners")).items():
            if not isinstance(pair_info, dict):
                continue
            uid_parts = str(pair_key).split("_")
            if len(uid_parts) != 2:
                continue
            for p_dday_name, p_dday_info in core.as_dict(pair_info.get("ddays")).items():
                if not isinstance(p_dday_info, dict) or not p_dday_info.get("date"):
                    continue
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
                    notified_partners.append((str(pair_key), p_dday_name))

        if notified_secrets or notified_partners:
            def _commit_morning_notified():
                with core._DATA_LOCK:
                    fresh_data = core.load_data()
                    changed = False
                    fresh_profiles = core.as_dict(fresh_data.get("user_profiles"))
                    for u_k, s_n in notified_secrets:
                        s_map = core.as_dict(core.as_dict(fresh_profiles.get(u_k)).get("secret_ddays"))
                        if isinstance(s_map.get(s_n), dict) and s_map[s_n].get("notified_date") != today_str:
                            s_map[s_n]["notified_date"] = today_str
                            changed = True
                    fresh_partners = core.as_dict(fresh_data.get("partners"))
                    for pk, pdn in notified_partners:
                        pd_map = core.as_dict(core.as_dict(fresh_partners.get(pk)).get("ddays"))
                        if isinstance(pd_map.get(pdn), dict) and pd_map[pdn].get("notified_date") != today_str:
                            pd_map[pdn]["notified_date"] = today_str
                            changed = True
                    if changed:
                        core.save_data(fresh_data)
            await asyncio.to_thread(_commit_morning_notified)

        # 3. 서버 공개 오전 9시 D-Day 요약 알림
        alert_ch_id = core.as_dict(data.get("settings")).get("dday_alert_channel_id")
        if not alert_ch_id:
            return

        channel = await self.resolve_channel(alert_ch_id)
        if not channel:
            return

        ddays = core.as_dict(data.get("ddays"))
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

        valid_ddays = [(n, inf) for n, inf in ddays.items() if isinstance(inf, dict)]
        for name, info in sorted(valid_ddays, key=lambda x: x[1].get("date", "9999-12-31")):
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
# 🖥️ VM 서버 터미널 로그 수신 채널 & 무로시 로그 모드(요약/상세) 설정
# ==========================================
def build_norosi_log_config_embed(guild: Optional[discord.Guild] = None, status_note: str = "") -> discord.Embed:
    data = core.get_cached_data()
    settings_d = core.as_dict(data.get("settings"))
    t_channels = core.as_dict(settings_d.get("terminal_log_channels"))
    cur_mode = core.get_terminal_log_mode(data)
    g_key = str(guild.id) if guild else "global"
    linked_cid = t_channels.get(g_key) or settings_d.get("terminal_log_channel_id")
    ch_txt = f"<#{linked_cid}> (`ID: {linked_cid}`)" if linked_cid else "미지정 (`/터미널로그채널 채널:#채널`)"

    mode_title = "📋 요약 버전 (Summary Mode)" if cur_mode == "summary" else "🔍 상세 버전 (Detailed Mode)"
    color = discord.Color.from_rgb(56, 189, 248) if cur_mode == "summary" else discord.Color.from_rgb(16, 185, 129)
    note_block = f"\n> {status_note}\n" if status_note else ""

    embed = discord.Embed(
        title="🪵 무로시(norosi) 구동 & 터미널 브릿지 로그 설정",
        description=(
            "봇 부팅 파이프라인(`STARTUP` · `[1/4]~[4/4]` · `READY`)과 디스코드 터미널 로그 채널(`3초 브릿지`)의 출력 상세도를 실시간으로 전환합니다.\n"
            f"{note_block}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **현재 로그 모드:** **{mode_title}** (`{cur_mode}`)\n"
            f"• **현재 서버 로그 채널:** {ch_txt} *(전체 연동 서버: `{len(t_channels)}곳`)*\n"
            "• **보안 필터링:** 토큰·API 키·비밀번호·개인정보는 두 모드 모두 **100% 비노출** 보장\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.add_field(
        name="📋 요약 버전 (Summary)",
        value=(
            "• 부팅 `[STARTUP]` · `[1/4]~[4/4]` · `[READY]` 단계당 **핵심 1줄 요약**만 출력\n"
            "• 개별 17개 Cog 로드 행 및 일반 `INFO` 트레이스 생략 (경고/오류 발생 시에만 즉시 노출)\n"
            "• 디스코드 터미널 로그 채널의 메시지 양을 최소화하고 싶을 때 추천"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔍 상세 버전 (Detailed — 기본값)",
        value=(
            "• Python/OS/RSS/디스크·확장 모듈 7종 상태·개별 17대 Cogs 로드(`ms`/슬래시/프리픽스 증감) 전체 출력\n"
            "• 프로세카(미래시 #154~#225)·원신·스타레일·36,700종 어종·1,000종 엔딩 마스터 DB 상세 지표 출력\n"
            "• 5대 상주 스케줄러 상태 및 접속 길드 요약 포함"
        ),
        inline=False,
    )
    embed.set_footer(text="하단 버튼 또는 /무로시로그 모드:[요약/상세] · !무로시로그 요약/상세 로 언제든 전환 가능")
    return embed


class NorosiLogConfigView(core.SafeView):
    """무로시 구동 및 터미널 브릿지 로그의 요약 버전 / 상세 버전을 원클릭 전환하는 뷰"""

    def __init__(self, author: Optional[discord.abc.User] = None, guild: Optional[discord.Guild] = None):
        super().__init__(timeout=300)
        self.author = author
        self.guild = guild
        self.status_note = ""
        self._sync_button_styles()

    def _sync_button_styles(self):
        cur_mode = core.get_terminal_log_mode()
        self.btn_summary.style = discord.ButtonStyle.primary if cur_mode == "summary" else discord.ButtonStyle.secondary
        self.btn_detailed.style = discord.ButtonStyle.success if cur_mode == "detailed" else discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        return build_norosi_log_config_embed(self.guild, self.status_note)

    async def _check_perm(self, interaction: discord.Interaction) -> bool:
        is_owner = await bot.is_bot_owner_user(interaction.user)
        is_admin = bool(
            interaction.guild and isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )
        if not (is_owner or is_admin):
            await core.safe_send_response(
                interaction,
                "❌ 로그 모드 변경은 **서버 관리자** 또는 **봇 소유자**만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="📋 요약 버전으로 설정", style=discord.ButtonStyle.secondary, row=0, custom_id="norosi:NorosiLogConfigView:btn_summary")
    async def btn_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction):
            return
        await core.safe_defer(interaction)
        await asyncio.to_thread(core.set_terminal_log_mode, "summary")
        self.status_note = "✅ 무로시 로그 모드가 **📋 요약 버전 (Summary)**으로 변경되었습니다!"
        self._sync_button_styles()
        print(f"⚙️ [무로시로그] {interaction.user}에 의해 로그 출력 모드가 '요약 버전(summary)'으로 전환되었습니다.", flush=True)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔍 상세 버전으로 설정", style=discord.ButtonStyle.success, row=0, custom_id="norosi:NorosiLogConfigView:btn_detailed")
    async def btn_detailed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction):
            return
        await core.safe_defer(interaction)
        await asyncio.to_thread(core.set_terminal_log_mode, "detailed")
        self.status_note = "✅ 무로시 로그 모드가 **🔍 상세 버전 (Detailed)**으로 변경되었습니다!"
        self._sync_button_styles()
        print(f"⚙️ [무로시로그] {interaction.user}에 의해 로그 출력 모드가 '상세 버전(detailed)'으로 전환되었습니다.", flush=True)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🧪 현재 모드로 샘플 로그 출력", style=discord.ButtonStyle.secondary, row=0, custom_id="norosi:NorosiLogConfigView:btn_test_log")
    async def btn_test_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction):
            return
        await core.safe_defer(interaction)
        cur_mode = core.get_terminal_log_mode()
        sekai_t = core.get_proseka_sekai_time_theme()
        ws_ping_ms = round(bot.latency * 1000, 1) if bot.latency and bot.latency > 0 else 0.0
        if cur_mode == "summary":
            print(
                f"✅ [무로시로그/요약 점검] {bot.user} 정상 가동 중 (핑 {ws_ping_ms}ms · 서버 {len(bot.guilds)}곳 · 세카이 {sekai_t['hour_str']})",
                flush=True,
            )
        else:
            print(
                f"✅ [무로시로그/상세 점검] {bot.user} 상태 브리핑 — WebSocket {ws_ping_ms}ms | "
                f"연결 서버 {len(bot.guilds)}곳 | Cogs {len(bot.extensions)}개 | SafeView {len(core.SAFE_VIEW_REGISTRY)}종 | "
                f"세카이 {sekai_t['hour_str']} ({sekai_t['phase_name']} · {sekai_t['unit_label']})",
                flush=True,
            )
        self.status_note = f"🧪 현재 모드(`{cur_mode}`)로 터미널 콘솔에 샘플 진단 로그를 출력했습니다!"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


@bot.tree.command(name="무로시로그", description="[관리자/봇주] 무로시 구동 및 터미널 브릿지 로그를 요약 버전 또는 상세 버전으로 설정합니다.")
@app_commands.describe(모드="전환할 로그 출력 버전 (미선택 시 현재 설정 패널 열기)")
@app_commands.choices(모드=[
    app_commands.Choice(name="📋 요약 버전 (Summary — 핵심 단계·경고·오류만 간결 출력)", value="summary"),
    app_commands.Choice(name="🔍 상세 버전 (Detailed — 모듈·마스터DB·스케줄러·환경 전체 상세 출력)", value="detailed"),
])
@app_commands.default_permissions(administrator=True)
async def norosi_log_mode_slash(interaction: discord.Interaction, 모드: Optional[app_commands.Choice[str]] = None):
    is_owner = await bot.is_bot_owner_user(interaction.user)
    is_admin = bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
    if not (is_owner or is_admin):
        await core.safe_send_response(interaction, "❌ 이 명령어는 **봇 소유자** 또는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
        return

    await core.safe_defer(interaction, ephemeral=True)
    view = NorosiLogConfigView(author=interaction.user, guild=interaction.guild)
    if 모드 is not None:
        new_mode = await asyncio.to_thread(core.set_terminal_log_mode, 모드.value)
        mode_kr = "📋 요약 버전 (Summary)" if new_mode == "summary" else "🔍 상세 버전 (Detailed)"
        view.status_note = f"✅ 무로시 로그 출력 모드가 **{mode_kr}**으로 설정되었습니다!"
        view._sync_button_styles()
        print(f"⚙️ [무로시로그] {interaction.user}에 의해 로그 출력 모드가 '{mode_kr}'({new_mode})으로 설정되었습니다.", flush=True)
    msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
    view.message = msg


@bot.command(name="무로시로그", aliases=["로그모드", "구동로그", "logmode"])
async def norosi_log_mode_prefix(ctx: commands.Context, 모드: Optional[str] = None):
    is_owner = await bot.is_bot_owner_user(ctx.author)
    is_admin = bool(ctx.guild and isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator)
    if not (is_owner or is_admin):
        await ctx.send("❌ 이 명령어는 **봇 소유자** 또는 **서버 관리자**만 사용할 수 있습니다.", delete_after=5)
        return

    view = NorosiLogConfigView(author=ctx.author, guild=ctx.guild)
    if 모드:
        new_mode = await asyncio.to_thread(core.set_terminal_log_mode, 모드)
        mode_kr = "📋 요약 버전 (Summary)" if new_mode == "summary" else "🔍 상세 버전 (Detailed)"
        view.status_note = f"✅ 무로시 로그 출력 모드가 **{mode_kr}**으로 설정되었습니다!"
        view._sync_button_styles()
        print(f"⚙️ [무로시로그] {ctx.author}에 의해 로그 출력 모드가 '{mode_kr}'({new_mode})으로 설정되었습니다.", flush=True)
    msg = await ctx.send(embed=view.build_embed(), view=view)
    view.message = msg


@bot.tree.command(name="터미널로그채널", description="[관리자/봇주] VM 서버 터미널 실시간 로그를 기록할 채널 및 로그 버전(요약/상세)을 설정합니다.")
@app_commands.describe(
    채널="터미널 로그를 실시간으로 받아볼 텍스트 채널 (비워두면 전송 해제)",
    모드="무로시 구동 및 터미널 로그 출력 버전 (요약 버전 / 상세 버전, 선택)",
)
@app_commands.choices(모드=[
    app_commands.Choice(name="📋 요약 버전 (Summary — 핵심 단계·경고·오류만 간결 출력)", value="summary"),
    app_commands.Choice(name="🔍 상세 버전 (Detailed — 모듈·마스터DB·스케줄러·환경 전체 상세 출력)", value="detailed"),
])
@app_commands.default_permissions(administrator=True)
async def set_terminal_log_channel_slash(
    interaction: discord.Interaction,
    채널: Optional[discord.TextChannel] = None,
    모드: Optional[app_commands.Choice[str]] = None,
):
    is_owner = await bot.is_bot_owner_user(interaction.user)
    is_admin = bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
    if not (is_owner or is_admin):
        await core.safe_send_response(interaction, "❌ 이 명령어는 **봇 소유자** 또는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
        return

    await core.safe_defer(interaction, ephemeral=True)
    g_key = str(interaction.guild_id) if interaction.guild_id else "global"
    ch_id = 채널.id if 채널 is not None else None
    chosen_mode = 모드.value if 모드 is not None else None

    def _update_terminal_ch() -> tuple[int, str]:
        with core._DATA_LOCK:
            data = core.load_data()
            settings_dict = core.ensure_dict_path(data, "settings")
            t_channels = core.ensure_dict_path(data, "settings", "terminal_log_channels")
            if chosen_mode is not None:
                settings_dict["terminal_log_mode"] = core.normalize_log_mode_value(chosen_mode)
            if ch_id is None and chosen_mode is None:
                t_channels.pop(g_key, None)
                if not t_channels:
                    settings_dict["terminal_log_channel_id"] = None
            elif ch_id is not None:
                t_channels[g_key] = ch_id
                settings_dict["terminal_log_channel_id"] = ch_id
            core.save_data(data)
            return len(t_channels), core.get_terminal_log_mode(data)

    total_linked, active_mode = await asyncio.to_thread(_update_terminal_ch)
    mode_kr = "📋 요약 버전 (Summary)" if active_mode == "summary" else "🔍 상세 버전 (Detailed)"
    view = NorosiLogConfigView(author=interaction.user, guild=interaction.guild)

    if 채널 is None and chosen_mode is not None:
        view.status_note = f"✅ 무로시 로그 모드가 **{mode_kr}**으로 변경되었습니다!"
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)
        print(f"⚙️ [무로시로그] {interaction.user}에 의해 로그 출력 모드가 '{mode_kr}'({active_mode})으로 변경되었습니다.", flush=True)
    elif 채널 is None:
        await interaction.followup.send(
            f"🛑 **현재 서버({interaction.guild.name if interaction.guild else '글로벌'})의 VM 서버 터미널 로그 채널 전송이 해제되었습니다.** (현재 로그 모드: {mode_kr})",
            view=view,
            ephemeral=True,
        )
        print(f"ℹ️ [System] {interaction.user}에 의해 {interaction.guild}의 터미널 로그 채널 전송이 비활성화되었습니다.", flush=True)
    else:
        embed = discord.Embed(
            title="🖥️ VM 서버 터미널 실시간 로그 채널 지정 완료!",
            description=(
                f"이제부터 VM 서버 터미널(`stdout` / `stderr` / `logging`)로 출력되는 로그가 {채널.mention} 채널에도 실시간으로 기록됩니다.\n\n"
                f"• **현재 채널:** {채널.mention} (`#{채널.name}`)\n"
                f"• **로그 출력 모드:** **{mode_kr}** (`/무로시로그` 또는 아래 버튼으로 요약/상세 즉시 전환)\n"
                f"• **전체 연동 서버:** 총 {total_linked}개 서버 채널에 실시간 동시 전송 중\n"
                "• **전송 주기:** `3초` 단위 버퍼링 묶음 전송 (도배 및 Rate Limit 완벽 방어)\n"
                "• **해제 방법:** `/터미널로그채널` 명령어를 채널 옵션 없이 실행"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        print(f"✅ [System] VM 터미널 실시간 로그 수신 채널이 #{채널.name} (ID: {채널.id}, 서버: {interaction.guild}, 모드: {active_mode})로 지정되었습니다. (총 {total_linked}개 서버 동시 전송)", flush=True)


@bot.command(name="터미널로그", aliases=["터미널로그채널", "서버터미널", "vm로그", "콘솔로그"])
async def set_terminal_log_channel_prefix(ctx: commands.Context, arg1: Optional[str] = None, arg2: Optional[str] = None):
    is_owner = await bot.is_bot_owner_user(ctx.author)
    is_admin = bool(ctx.guild and isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator)
    if not (is_owner or is_admin):
        await ctx.send("❌ 이 명령어는 **봇 소유자** 또는 **서버 관리자**만 사용할 수 있습니다.", delete_after=5)
        return

    # `!터미널로그 요약` 또는 `!터미널로그 상세` 입력 시 로그 모드 즉시 변경
    mode_keywords = ("요약", "요약버전", "summary", "compact", "상세", "상세버전", "detailed", "detail", "full")
    if arg1 and arg1.strip().lower() in mode_keywords and not arg2:
        new_mode = await asyncio.to_thread(core.set_terminal_log_mode, arg1)
        mode_kr = "📋 요약 버전 (Summary)" if new_mode == "summary" else "🔍 상세 버전 (Detailed)"
        view = NorosiLogConfigView(author=ctx.author, guild=ctx.guild)
        view.status_note = f"✅ 무로시 로그 모드가 **{mode_kr}**으로 전환되었습니다!"
        await ctx.send(embed=view.build_embed(), view=view)
        print(f"⚙️ [무로시로그] {ctx.author}에 의해 로그 출력 모드가 '{mode_kr}'({new_mode})으로 전환되었습니다.", flush=True)
        return

    channel: Optional[discord.TextChannel] = None
    if ctx.message.channel_mentions:
        channel = ctx.message.channel_mentions[0]
    elif arg1 and arg1.isdigit() and ctx.guild:
        ch_cand = ctx.guild.get_channel(int(arg1))
        if isinstance(ch_cand, discord.TextChannel):
            channel = ch_cand

    chosen_mode = None
    for cand in (arg1, arg2):
        if cand and cand.strip().lower() in mode_keywords:
            chosen_mode = core.normalize_log_mode_value(cand)

    g_key = str(ctx.guild.id) if ctx.guild else "global"
    ch_id = channel.id if channel is not None else None

    def _update_terminal_ch_prefix() -> tuple[int, str]:
        with core._DATA_LOCK:
            data = core.load_data()
            settings_dict = core.ensure_dict_path(data, "settings")
            t_channels = core.ensure_dict_path(data, "settings", "terminal_log_channels")
            if chosen_mode is not None:
                settings_dict["terminal_log_mode"] = chosen_mode
            if ch_id is None:
                t_channels.pop(g_key, None)
                if not t_channels:
                    settings_dict["terminal_log_channel_id"] = None
            else:
                t_channels[g_key] = ch_id
                settings_dict["terminal_log_channel_id"] = ch_id
            core.save_data(data)
            return len(t_channels), core.get_terminal_log_mode(data)

    total_linked, active_mode = await asyncio.to_thread(_update_terminal_ch_prefix)
    mode_kr = "📋 요약 버전 (Summary)" if active_mode == "summary" else "🔍 상세 버전 (Detailed)"
    view = NorosiLogConfigView(author=ctx.author, guild=ctx.guild)

    if channel is None:
        await ctx.send(
            f"🛑 **현재 서버({ctx.guild.name if ctx.guild else '글로벌'})의 VM 서버 터미널 로그 채널 기록이 비활성화되었습니다.** "
            f"(특정 채널에 켜려면 `!터미널로그 #채널`, 로그 버전 변경은 `!무로시로그 요약` 또는 `!무로시로그 상세`)",
            view=view,
        )
    else:
        await ctx.send(
            f"🖥️ **VM 서버 터미널 로그 채널 지정 완료:** 이제부터 터미널 출력이 {channel.mention} 채널에 **{mode_kr}**으로 실시간 기록됩니다! (총 {total_linked}개 서버 채널 동시 전송)",
            view=view,
        )
        print(f"✅ [System] VM 터미널 실시간 로그 수신 채널이 #{channel.name} (ID: {channel.id}, 서버: {ctx.guild}, 모드: {active_mode})로 지정되었습니다. (총 {total_linked}개 서버 동시 전송)", flush=True)


# ==========================================
# 🖼️ 봇주 전용 봇 프로필 배너 변경 명령어 (/봇배너, !봇배너)
# ==========================================
MAX_BOT_BANNER_BYTES = 10 * 1024 * 1024  # 10MB


def _is_valid_banner_image_bytes(raw_bytes: bytes, content_type: str = "", filename: str = "") -> bool:
    if not raw_bytes:
        return False
    ct = (content_type or "").lower()
    fn = (filename or "").lower()
    if ct.startswith("image/"):
        return True
    if any(fn.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return True
    # 매직 바이트 검사 (PNG, JPEG, GIF, WEBP)
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return True
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return True
    if raw_bytes.startswith(b"RIFF") and raw_bytes[8:12] == b"WEBP":
        return True
    return False


async def _download_banner_bytes_from_url(url: str) -> bytes:
    clean_url = (url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("이미지 URL은 `http://` 또는 `https://`로 시작해야 합니다.")
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(clean_url, allow_redirects=True) as resp:
            if resp.status != 200:
                raise ValueError(f"이미지 다운로드 실패 (HTTP {resp.status})")
            if resp.content_length and resp.content_length > MAX_BOT_BANNER_BYTES:
                raise ValueError("이미지 용량이 10MB를 초과합니다.")
            raw_bytes = await resp.content.read(MAX_BOT_BANNER_BYTES + 1)
            if len(raw_bytes) > MAX_BOT_BANNER_BYTES:
                raise ValueError("이미지 용량이 10MB를 초과합니다.")
            ct = resp.headers.get("Content-Type", "")
            if not _is_valid_banner_image_bytes(raw_bytes, content_type=ct, filename=clean_url.split("?")[0]):
                raise ValueError("지원되는 이미지 형식(PNG, JPG, GIF, WEBP)이 아닙니다.")
            return raw_bytes


@bot.tree.command(name="봇배너", description="[봇주 전용] 봇의 디스코드 프로필 배너 이미지를 조회, 변경 또는 초기화합니다.")
@app_commands.describe(
    이미지="새 배너로 설정할 이미지 파일 (PNG, JPG, GIF, WEBP · 최대 10MB)",
    이미지url="새 배너로 설정할 이미지 URL (파일 미첨부 시 사용)",
    초기화="True 선택 시 봇 프로필 배너를 제거합니다."
)
@app_commands.default_permissions(administrator=True)
async def set_bot_banner_slash(
    interaction: discord.Interaction,
    이미지: Optional[discord.Attachment] = None,
    이미지url: Optional[str] = None,
    초기화: bool = False
):
    if not await bot.is_bot_owner_user(interaction.user):
        await core.safe_send_response(
            interaction,
            "❌ 이 명령어는 **봇 소유자(봇주)**만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    await core.safe_defer(interaction, ephemeral=True)

    if not bot.user:
        await interaction.followup.send("⚠️ 봇이 아직 디스코드에 연결되지 않았습니다.", ephemeral=True)
        return

    try:
        if 초기화:
            await bot.user.edit(banner=None)
            embed = discord.Embed(
                title="🗑️ 봇 프로필 배너 초기화 완료",
                description="봇의 디스코드 프로필 배너가 깔끔하게 제거되었습니다.",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text=f"[봇주 전용] 요청자: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, ephemeral=True)
            print(f"🖼️ [BotBanner] {interaction.user}에 의해 봇 프로필 배너가 초기화되었습니다.", flush=True)
            return

        if 이미지 is None and not (이미지url and 이미지url.strip()):
            try:
                fetched_user = await bot.fetch_user(bot.user.id)
                current_banner = fetched_user.banner.url if fetched_user.banner else None
            except Exception:
                current_banner = bot.user.banner.url if bot.user.banner else None

            embed = discord.Embed(
                title="🖼️ 현재 봇 프로필 배너 정보",
                description=(
                    (f"✅ **현재 배너가 설정되어 있습니다.**\n[원본 이미지 열기]({current_banner})" if current_banner else "ℹ️ **현재 설정된 봇 배너가 없습니다.**")
                    + "\n\n**변경 방법 (봇주 전용):**\n"
                    "• `/봇배너 이미지:<파일첨부>` 또는 `/봇배너 이미지url:<주소>`\n"
                    "• 배너 제거: `/봇배너 초기화:True`"
                ),
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST)
            )
            if current_banner:
                embed.set_image(url=current_banner)
            embed.set_footer(text="[봇주 전용] 권장 크기: 680x240px 이상 · PNG/JPG/GIF/WEBP")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if 이미지 is not None:
            if 이미지.size and 이미지.size > MAX_BOT_BANNER_BYTES:
                await interaction.followup.send("❌ 이미지 용량은 최대 `10MB` 이하만 업로드할 수 있습니다.", ephemeral=True)
                return
            img_bytes = await 이미지.read()
            if not _is_valid_banner_image_bytes(img_bytes, content_type=이미지.content_type or "", filename=이미지.filename or ""):
                await interaction.followup.send("❌ 지원되는 이미지 파일(`PNG`, `JPG`, `GIF`, `WEBP`)을 첨부해 주세요.", ephemeral=True)
                return
        else:
            img_bytes = await _download_banner_bytes_from_url(이미지url or "")

        await bot.user.edit(banner=img_bytes)
        try:
            fetched_user = await bot.fetch_user(bot.user.id)
            new_banner_url = fetched_user.banner.url if fetched_user.banner else None
        except Exception:
            new_banner_url = bot.user.banner.url if bot.user.banner else None

        embed = discord.Embed(
            title="🖼️ 봇 프로필 배너 변경 완료!",
            description="봇의 디스코드 프로필 배너가 새 이미지로 성공적으로 적용되었습니다! ✨",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST)
        )
        if new_banner_url:
            embed.set_image(url=new_banner_url)
        embed.set_footer(text=f"[봇주 전용] 변경자: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"🖼️ [BotBanner] {interaction.user}에 의해 봇 프로필 배너가 변경되었습니다.", flush=True)

    except ValueError as ve:
        await interaction.followup.send(f"❌ **입력 오류:** {ve}", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ 디스코드 API 권한 부족으로 봇 배너를 변경할 수 없습니다.", ephemeral=True)
    except discord.HTTPException as he:
        await interaction.followup.send(f"⚠️ 디스코드 배너 업데이트 실패: `{he}` (이미지 크기·형식·비율을 확인해 주세요.)", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ 봇 배너 변경 중 예외 발생: `{e}`", ephemeral=True)


@bot.command(name="봇배너", aliases=["배너", "봇배너변경", "botbanner"])
async def set_bot_banner_prefix(ctx: commands.Context, arg: Optional[str] = None):
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **봇 소유자(봇주)**만 사용할 수 있습니다.", delete_after=5)
        return

    if not bot.user:
        await ctx.send("⚠️ 봇이 아직 디스코드에 연결되지 않았습니다.", delete_after=5)
        return

    try:
        if arg and arg.strip().lower() in ("초기화", "제거", "삭제", "reset", "none", "clear"):
            await bot.user.edit(banner=None)
            await ctx.send("🗑️ **봇 프로필 배너가 성공적으로 초기화(제거)되었습니다.**")
            print(f"🖼️ [BotBanner] {ctx.author}에 의해 봇 프로필 배너가 초기화되었습니다.", flush=True)
            return

        if ctx.message.attachments:
            att = ctx.message.attachments[0]
            if att.size and att.size > MAX_BOT_BANNER_BYTES:
                await ctx.send("❌ 이미지 용량은 최대 `10MB` 이하만 업로드할 수 있습니다.", delete_after=8)
                return
            img_bytes = await att.read()
            if not _is_valid_banner_image_bytes(img_bytes, content_type=att.content_type or "", filename=att.filename or ""):
                await ctx.send("❌ 지원되는 이미지 파일(`PNG`, `JPG`, `GIF`, `WEBP`)을 첨부해 주세요.", delete_after=8)
                return
        elif arg and arg.strip().startswith(("http://", "https://")):
            img_bytes = await _download_banner_bytes_from_url(arg.strip())
        else:
            try:
                fetched_user = await bot.fetch_user(bot.user.id)
                current_banner = fetched_user.banner.url if fetched_user.banner else None
            except Exception:
                current_banner = bot.user.banner.url if bot.user.banner else None
            embed = discord.Embed(
                title="🖼️ 봇 프로필 배너 안내 (봇주 전용)",
                description=(
                    (f"• **현재 배너:** [이미지 보기]({current_banner})\n" if current_banner else "• **현재 배너:** 설정되지 않음\n")
                    + "• **변경:** 이미지 첨부 후 `!봇배너` 또는 `!봇배너 <이미지URL>`\n"
                    + "• **제거:** `!봇배너 초기화`"
                ),
                color=discord.Color.from_rgb(0, 204, 221)
            )
            if current_banner:
                embed.set_image(url=current_banner)
            await ctx.send(embed=embed)
            return

        await bot.user.edit(banner=img_bytes)
        try:
            fetched_user = await bot.fetch_user(bot.user.id)
            new_banner_url = fetched_user.banner.url if fetched_user.banner else None
        except Exception:
            new_banner_url = bot.user.banner.url if bot.user.banner else None

        embed = discord.Embed(
            title="🖼️ 봇 프로필 배너 변경 완료!",
            description="봇의 디스코드 프로필 배너가 성공적으로 적용되었습니다! ✨",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST)
        )
        if new_banner_url:
            embed.set_image(url=new_banner_url)
        await ctx.send(embed=embed)
        print(f"🖼️ [BotBanner] {ctx.author}에 의해 봇 프로필 배너가 변경되었습니다.", flush=True)

    except ValueError as ve:
        await ctx.send(f"❌ **입력 오류:** {ve}", delete_after=8)
    except discord.Forbidden:
        await ctx.send("❌ 디스코드 API 권한 부족으로 봇 배너를 변경할 수 없습니다.", delete_after=8)
    except discord.HTTPException as he:
        await ctx.send(f"⚠️ 디스코드 배너 업데이트 실패: `{he}`", delete_after=10)
    except Exception as e:
        await ctx.send(f"⚠️ 봇 배너 변경 중 예외 발생: `{e}`", delete_after=10)


# ==========================================
# 봇 슬래시 명령어 동기화 컨트롤 뷰 (대화형 버튼 UI)
# ==========================================
class SyncControlView(core.SafeView):
    def __init__(self, author: Optional[discord.User] = None, guild: Optional[discord.Guild] = None):
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
            target_guild = self.guild or interaction.guild
            if target_guild:
                bot.tree.copy_global_to(guild=target_guild)
                synced_guild = await bot.tree.sync(guild=target_guild)
                g_cnt = len(synced_guild)

            synced_global = await bot.tree.sync()

            embed = discord.Embed(
                title="⚡ 슬래시 명령어 현재 서버에 0초 즉시 반영 완료!",
                description=(
                    f"✅ **현재 서버({target_guild.name if target_guild else '글로벌'})**에 슬래시 명령어 **`{g_cnt}개`**(반응역할·터미널로그 포함)가 0초 만에 즉시 등록되었습니다!\n"
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
        bot.register_persistent_views()

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
        bot.register_persistent_views()

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
                "• `/깃허브연동` : GitHub 푸시 및 Actions 알림 채널 연동\n"
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
    import platform
    import shutil
    py_ver = sys.version.split()[0]
    dpy_ver = getattr(discord, "__version__", "unknown")
    os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    disk_free_gb = 0.0
    try:
        disk_free_gb = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__))).free / (1024 ** 3)
    except Exception:
        pass
    rss_mb = 0.0
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fp:
            for line in fp:
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) / 1024.0
                    break
    except Exception:
        pass

    opt_mods = []
    for mod_label, mod_name in [
        ("Pillow", "PIL"),
        ("aiohttp", "aiohttp"),
        ("PyNaCl", "nacl"),
        ("DAVE(davey)", "davey"),
        ("Gemini(genai)", "google.genai"),
        ("yt-dlp", "yt_dlp"),
        ("Spotipy", "spotipy"),
    ]:
        try:
            __import__(mod_name)
            opt_mods.append(f"{mod_label}:ON")
        except Exception:
            opt_mods.append(f"{mod_label}:OFF")

    init_log_mode = core.get_terminal_log_mode()
    print("==================================================================", flush=True)
    if init_log_mode == "summary":
        print(
            f"🚀 [STARTUP/요약] 무로시(norosi) 기동 시작 (PID: {os.getpid()} | Python {py_ver} · discord.py {dpy_ver} | RSS {rss_mb:.1f}MB · Disk {disk_free_gb:.2f}GB)",
            flush=True,
        )
    else:
        print(f"🚀 [STARTUP] 무로시(norosi) 올인원 봇 엔진 기동 시작 (PID: {os.getpid()} | 로그 모드: 상세 버전)", flush=True)
        print(f"⏰ 부팅 시각  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (서버) / {datetime.datetime.now(core.KST).strftime('%Y-%m-%d %H:%M:%S KST')} (한국)", flush=True)
        print(f"🖥️ 런타임 환경: Python {py_ver} · discord.py {dpy_ver} · OS: {os_info}", flush=True)
        print(f"💾 시스템 자원: 초기 메모리 RSS {rss_mb:.1f}MB · 디스크 여유 공간 {disk_free_gb:.2f}GB · CWD: {os.getcwd()}", flush=True)
        print(f"🧩 확장 모듈  : {' | '.join(opt_mods)}", flush=True)
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
    print(f"🔑 디스코드 게이트웨이 인증 및 연결 시도 중... (토큰 확인됨 · 길이: {len(active_token)}자)", flush=True)

    async def _cleanup_bot_session():
        # 백그라운드 스케줄러 루프가 재시도 대기 중 닫힌 세션을 참조하지 않도록 안전하게 중단
        for loop_attr in (
            "midnight_tasks",
            "morning_music_alert",
            "morning_text_alert",
            "custom_music_schedules_loop",
            "terminal_log_dispatch_loop",
        ):
            loop_obj = getattr(bot, loop_attr, None)
            if loop_obj is not None:
                try:
                    if loop_obj.is_running():
                        loop_obj.cancel()
                        task = loop_obj.get_task()
                        if task is not None and not task.done():
                            await asyncio.wait([task], timeout=2.0)
                except Exception:
                    pass

        try:
            if not bot.is_closed():
                await bot.close()
        except Exception:
            pass

        http_client = getattr(bot, "http", None)
        if http_client is not None:
            try:
                await http_client.close()
            except Exception:
                pass
            # close() 이후에도 열려 있거나 닫힌 채 남아있는 내부 세션을 확실히 닫고 MISSING으로 초기화
            for attr_name in ("_HTTPClient__session", "_session"):
                if hasattr(http_client, attr_name):
                    sess = getattr(http_client, attr_name, discord.utils.MISSING)
                    if sess is not None and sess is not discord.utils.MISSING:
                        try:
                            if not getattr(sess, "closed", True):
                                await sess.close()
                        except Exception:
                            pass
                        try:
                            setattr(http_client, attr_name, discord.utils.MISSING)
                        except Exception:
                            pass
            conn = getattr(http_client, "connector", None)
            if conn is not None and conn is not discord.utils.MISSING and getattr(conn, "closed", False):
                try:
                    http_client.connector = None
                except Exception:
                    pass

        for loaded_ext in list(getattr(bot, "extensions", {}).keys()):
            try:
                await bot.unload_extension(loaded_ext)
            except Exception:
                pass

        try:
            bot.clear()
        except Exception:
            pass

        await bot.ensure_fresh_http_session()

    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    _shutdown_requested = False

    def _request_shutdown(sig_name: str):
        nonlocal _shutdown_requested
        if _shutdown_requested:
            return
        _shutdown_requested = True
        print(f"🛑 [SHUTDOWN] {sig_name} 시그널 수신 — 대기 중인 설정 저장 및 Firebase 동기화를 완료한 뒤 안전 종료합니다...", flush=True)
        if main_task is not None and not main_task.done():
            main_task.cancel()

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(_sig, _request_shutdown, _sig.name)
        except (NotImplementedError, ValueError, RuntimeError):
            pass

    _cleaned_once = False
    try:
        while True:
            try:
                await bot.ensure_fresh_http_session()
                await bot.start(core.TOKEN)
            except discord.LoginFailure:
                print("❌ 치명적 오류: 디스코드 토큰이 유효하지 않습니다! (LoginFailure)", flush=True)
                await _cleanup_bot_session()
                while True:
                    await asyncio.sleep(30)
                    core._load_env_file()
                    new_token = core.get_token()
                    if new_token and new_token != core.TOKEN:
                        print("🔄 새로운 토큰이 감지되어 연결을 재시도합니다...", flush=True)
                        core.TOKEN = new_token
                        break
            except asyncio.CancelledError:
                await _cleanup_bot_session()
                _cleaned_once = True
                raise
            except Exception as e:
                print(f"⚠️ 봇 연결 예외 발생 (15초 후 재시도): {e}", flush=True)
                traceback.print_exc()
                await _cleanup_bot_session()
                await asyncio.sleep(15)
            else:
                # 정상 종료 시 세션 정리 후 루프 탈출
                await _cleanup_bot_session()
                _cleaned_once = True
                break
    finally:
        if not _cleaned_once:
            await _cleanup_bot_session()
        try:
            await asyncio.to_thread(core.flush_firebase_sync, 4.0)
        except Exception:
            try:
                core.flush_firebase_sync(4.0)
            except Exception:
                pass
        if getattr(bot, "_web_runner", None) is not None:
            try:
                await bot._web_runner.cleanup()
            except Exception:
                pass
            bot._web_runner = None
            bot._web_started = False


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        try:
            core.flush_firebase_sync(2.0)
        except Exception:
            pass
