import os
import re
import sys
import copy
import time
import hmac
import socket
import hashlib
import logging
import asyncio
import datetime
import traceback
import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional, Any
from collections import OrderedDict, deque
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
                clean_text = core.redact_secrets(ANSI_ESCAPE_RE.sub("", self._line_buf))
                self._line_buf = ""
                if clean_text.strip():
                    prefix = "⚠️ [STDERR] " if self.is_stderr and "Traceback" in clean_text else ""
                    self.loop.call_soon_threadsafe(self._safe_put, prefix + clean_text)
        except Exception:
            pass

    def _safe_put(self, item: str):
        try:
            append_recent_terminal_log(item)
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
            msg = core.redact_secrets(ANSI_ESCAPE_RE.sub("", self.format(record)))
            if msg.strip():
                self.loop.call_soon_threadsafe(self._safe_put, msg + "\n")
        except Exception:
            pass

    def _safe_put(self, item: str):
        try:
            append_recent_terminal_log(item)
            if self.log_queue.qsize() < 500:
                self.log_queue.put_nowait(item)
        except Exception:
            pass


# 봇 상태 진단(/봇상태)에서 최근 터미널/시스템 로그를 조회하기 위한 인메모리 링 버퍼
RECENT_TERMINAL_LOG_LINES: deque[str] = deque(maxlen=80)


def append_recent_terminal_log(text: str) -> None:
    for ln in (text or "").splitlines():
        c = ln.strip()
        if c:
            RECENT_TERMINAL_LOG_LINES.append(core.redact_secrets(c)[:220])


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
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False),
        )
        self.start_time = datetime.datetime.now(core.KST)
        self._commands_synced = False
        self._web_started = False
        self._web_runner: Optional[web.AppRunner] = None
        self._handled_interaction_ids: OrderedDict[int, float] = OrderedDict()

        # 터미널 로그 브릿지 상태 변수
        self.terminal_log_queue: Optional[asyncio.Queue] = None
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._log_handler: Optional[DiscordQueueLoggingHandler] = None
        self._terminal_hooked = False
        self.recent_terminal_logs = RECENT_TERMINAL_LOG_LINES

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

    @staticmethod
    def _sanitize_github_url(url: Any, default: str = "https://github.com") -> str:
        s = str(url or "").strip()
        if s.startswith(("https://github.com/", "https://github.com", "https://avatars.githubusercontent.com/", "https://github.githubassets.com/")):
            return s
        return default

    async def handle_github_webhook(self, request: web.Request):
        """
        GitHub 저장소 Push 및 GitHub Actions 배포 성공/실패 이벤트를 수신하여
        설정된 디스코드 채널에 '🚀 업데이트 완료: [커밋 메시지]' 임베드를 실시간으로 전송합니다.
        """
        try:
            cl_hdr = getattr(request, "content_length", None)
            if isinstance(cl_hdr, int) and cl_hdr > 2 * 1024 * 1024:
                return web.json_response({"error": "Payload too large"}, status=413)
            raw_body = await request.read()
            if len(raw_body) > 2 * 1024 * 1024:
                return web.json_response({"error": "Payload too large"}, status=413)
            webhook_secret = (os.getenv("GITHUB_WEBHOOK_SECRET") or "").strip()
            if not webhook_secret:
                return web.json_response({"error": "Webhook secret is not configured"}, status=503)
            sig_header = request.headers.get("X-Hub-Signature-256", "")
            expected_sig = "sha256=" + hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            if not sig_header or not hmac.compare_digest(sig_header, expected_sig):
                return web.json_response({"error": "Invalid signature"}, status=401)
            sig_verified = True

            event = request.headers.get("X-GitHub-Event", "push")
            try:
                import json as _json
                payload = _json.loads(raw_body.decode("utf-8"))
            except Exception:
                return web.json_response({"error": "Invalid JSON"}, status=400)
            if not isinstance(payload, dict):
                return web.json_response({"error": "Invalid JSON object"}, status=400)

            data = core.get_cached_data_ro()
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

            # Query 파라미터(channel_id)는 서명이 검증되었거나 이미 설정된 채널 목록에 있을 때만 허용
            q_cid = request.query.get("channel_id")
            if q_cid and q_cid.isdigit():
                q_cid_int = int(q_cid)
                if sig_verified and q_cid_int not in seen_channel_ids:
                    target_channels_with_roles.append((q_cid_int, None))
                    seen_channel_ids.add(q_cid_int)

            embed = None
            role_mention = None

            if event == "ping":
                zen = str(payload.get("zen", "Keep it logically awesome."))[:200]
                repo_name = str(core.as_dict(payload.get("repository")).get("full_name", "저장소"))[:120]
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
                repo_full = str(repo.get("full_name", repo.get("name", "norosi")))[:120]
                repo_url = self._sanitize_github_url(repo.get("html_url"), "https://github.com")
                ref = str(payload.get("ref", ""))
                branch = (ref.split("/")[-1] if "/" in ref else (ref or "master"))[:80]
                pusher = str(core.as_dict(payload.get("pusher")).get("name", "개발자"))[:80]
                sender = core.as_dict(payload.get("sender"))
                sender_avatar = self._sanitize_github_url(
                    sender.get("avatar_url"),
                    "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
                )
                raw_commits = payload.get("commits")
                commits = raw_commits if isinstance(raw_commits, list) else []
                head_commit = core.as_dict(payload.get("head_commit") or (commits[-1] if commits else {}))

                raw_msg = str(head_commit.get("message", "새로운 변경사항 푸시 완료")).replace("```", "'''")
                first_line = raw_msg.strip().split("\n")[0]
                commit_id = str(head_commit.get("id") or "")[:7] or "latest"
                commit_url = self._sanitize_github_url(head_commit.get("url"), repo_url)
                compare_url = self._sanitize_github_url(payload.get("compare"), commit_url)

                added_cnt = len(head_commit.get("added") or [])
                modified_cnt = len(head_commit.get("modified") or [])
                removed_cnt = len(head_commit.get("removed") or [])

                embed_title = f"📦 GitHub 커밋 푸시됨 (`!업데이트` 대기): {first_line}"
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
                embed.set_footer(text=f"GitHub Push ({len(commits)}개 커밋) • 봇주인이 !업데이트 입력 시 봇에 일괄 반영됩니다")

            elif event == "workflow_run":
                action = payload.get("action", "")
                if action != "completed":
                    return web.json_response({"status": "ignored", "action": action})

                wf = core.as_dict(payload.get("workflow_run"))
                wf_name = str(wf.get("name", "Deploy"))[:100]
                conclusion = str(wf.get("conclusion", "success"))[:40]
                run_url = self._sanitize_github_url(wf.get("html_url"), "https://github.com")
                run_number = wf.get("run_number", 1)
                head_branch = str(wf.get("head_branch", "master"))[:80]
                head_commit = core.as_dict(wf.get("head_commit"))
                commit_msg = str(head_commit.get("message", "빌드 및 배포"))
                first_line = commit_msg.strip().split("\n")[0][:120]

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
                    title=title[:250],
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
                            await ch.send(
                                content=role_mention,
                                embed=embed,
                                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False),
                            )
                        except Exception as send_err:
                            print(f"⚠️ [GitHub 웹훅 메시지 전송 예외] 채널 {cid}: {send_err}", flush=True)

            return web.json_response({
                "status": "success",
                "event": event,
                "dispatched_channels": len(target_channels_with_roles)
            })
        except Exception as e:
            print(f"⚠️ [handle_github_webhook 예외] {core.redact_secrets(str(e))}", flush=True)
            return web.json_response({"error": "Internal webhook handler error"}, status=500)

    async def handle_emote_index(self, request: web.Request) -> web.Response:
        from cogs.emoji_upscale import handle_emote_index_http_request
        return await handle_emote_index_http_request(request)

    async def handle_emote_favicon(self, request: web.Request) -> web.Response:
        from cogs.emoji_upscale import handle_emote_favicon_http_request
        return await handle_emote_favicon_http_request(request)

    async def handle_emote_emoji(self, request: web.Request) -> web.Response:
        from cogs.emoji_upscale import handle_emote_cdn_http_request
        return await handle_emote_cdn_http_request(request, content_type="emoji")

    async def handle_emote_sticker(self, request: web.Request) -> web.Response:
        from cogs.emoji_upscale import handle_emote_cdn_http_request
        return await handle_emote_cdn_http_request(request, content_type="sticker")

    async def start_web_server(self):
        if self._web_started:
            return
        try:
            @web.middleware
            async def _security_headers_mw(req: web.Request, handler):
                resp = await handler(req)
                resp.headers.setdefault("X-Content-Type-Options", "nosniff")
                resp.headers.setdefault("X-Frame-Options", "DENY")
                resp.headers.setdefault("Referrer-Policy", "no-referrer")
                return resp

            app = web.Application(client_max_size=2 * 1024 * 1024, middlewares=[_security_headers_mw])
            app.router.add_get("/", self.handle_health_check)
            app.router.add_get("/cdn", self.handle_emote_index)
            app.router.add_get("/healthz", lambda _req: web.Response(text="ok"))
            app.router.add_get("/favicon.ico", self.handle_emote_favicon)
            app.router.add_get("/emoji/{id}", self.handle_emote_emoji)
            app.router.add_get("/e/{id}", self.handle_emote_emoji)
            app.router.add_get("/sticker/{id}", self.handle_emote_sticker)
            app.router.add_get("/s/{id}", self.handle_emote_sticker)
            app.router.add_post("/api/github/webhook", self.handle_github_webhook)
            app.router.add_post("/github/webhook", self.handle_github_webhook)
            app.router.add_post("/webhook/github", self.handle_github_webhook)
            app.router.add_post("/github", self.handle_github_webhook)
            # emote-cdn-rust 하위 호환 레거시 라우팅 (/{id}.webp)
            app.router.add_get("/{name}", self.handle_emote_emoji)

            runner = web.AppRunner(app)
            await runner.setup()
            bound_ports = []
            for p in dict.fromkeys([core.PORT, 53292]):
                try:
                    site = web.TCPSite(runner, "0.0.0.0", p)
                    await site.start()
                    bound_ports.append(p)
                except Exception:
                    continue
            if bound_ports:
                self._web_runner = runner
                self._web_started = True
                print(f"✅ norosi 헬스체크 · Emote CDN · GitHub 웹훅 서버 가동 완료 (포트: {', '.join(map(str, bound_ports))})", flush=True)
            else:
                await runner.cleanup()
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

        # 1. 닫힌/미생성 connector를 IPv4 우선 + DNS 캐시(300s) + Keep-Alive(60s) 저지연 커넥터로 교체
        conn = getattr(http_client, "connector", None)
        if conn is None or conn is discord.utils.MISSING or getattr(conn, "closed", False):
            try:
                http_client.connector = aiohttp.TCPConnector(
                    limit=0,
                    family=socket.AF_INET,
                    ttl_dns_cache=300,
                    keepalive_timeout=60.0,
                    enable_cleanup_closed=True,
                )
            except Exception:
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

    def prune_slash_tree_to_core(self) -> list[str]:
        """
        슬래시 명령어 트리(self.tree)에서 '/설정', '/도움말', '/후원'만 남기고
        나머지 모든 개별 슬래시 명령어를 트리에서 제거합니다.
        (각 Cog 인스턴스와 내부 커맨드 콜백은 그대로 보존되어 '/설정'에서 100% 정상 작동합니다.)
        """
        allowed_names = {"설정", "도움말", "후원"}
        for cmd in list(self.tree.get_commands()):
            if cmd.name not in allowed_names:
                self.tree.remove_command(cmd.name)
        return [c.name for c in self.tree.get_commands()]

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
        self.prune_slash_tree_to_core()

    async def setup_hook(self):
        # 0. VM 터미널 로그 실시간 캡처 활성화
        self.setup_terminal_log_capture()

        print("📦 [1/4] 데이터 캐시 로드 중...", flush=True)
        await asyncio.to_thread(core.load_data)

        # 글로벌 슬래시 커맨드 에러 핸들러 등록 ("명령어 응답 안함" 3초 타임아웃 차단)
        self.tree.on_error = self.on_app_command_error

        print("🔌 [2/4] Cogs 확장 모듈 등록 중 (전체 18종 Cogs · 슬래시 '/설정', '/도움말', '/후원' 통합)...", flush=True)
        # 서버 배포 파일 뒤바뀜(예: fishing_core.py에 cogs/fishing.py 덮어쓰기, cogs/gacha.py에 cogs/hsr.py 덮어쓰기) 사전 진단
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            integrity_checks = [
                ("fishing_core.py", "FISH_BY_HABITAT", "class FishingCog", "cogs/fishing.py가 fishing_core.py로 잘못 저장되었습니다"),
                (os.path.join("cogs", "gacha.py"), "class GachaCog", "class HSRCog", "cogs/hsr.py가 cogs/gacha.py로 잘못 저장되었습니다"),
                ("genshin_core.py", "genshin_artifact_autocomplete", None, "서버의 genshin_core.py가 구버전입니다 (최신 genshin_core.py로 교체 필요)"),
                ("hsr_core.py", "hsr_relic_autocomplete", None, "서버의 hsr_core.py가 구버전입니다 (최신 hsr_core.py로 교체 필요)"),
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
            "cogs.stats",
            "cogs.roles",
            "cogs.emoji_upscale",
            "cogs.routine",
            "cogs.help",
            "cogs.dashboard",
        ]
        failed_exts = []
        for ext in ext_list:
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
                if ext == "cogs.gacha" and self.get_cog("GachaCog") is None:
                    print(
                        "🚨 [파일 동기화 경고] 'cogs.gacha' 로드 후 GachaCog가 등록되지 않았습니다! "
                        "서버의 cogs/gacha.py 파일이 최신 버전으로 교체되었는지 확인해 주세요.",
                        flush=True,
                    )
            except Exception as e:
                print(f"⚠️ [{ext}] 확장 모듈 로드 예외: {e}", flush=True)
                failed_exts.append((ext, e))
        if len(failed_exts) == len(ext_list):
            raise failed_exts[0][1]

        kept_slashes = self.prune_slash_tree_to_core()
        print(f"🧹 [슬래시 명령어 통합 완료] 활성 슬래시 명령어 ({len(kept_slashes)}개): {', '.join('/' + n for n in kept_slashes)}", flush=True)

        # 등록된 반응역할 메시지의 Persistent View 동적 복원 (버튼 상호작용 영구 작동)
        try:
            from cogs.roles import PersistentReactionRoleView
            cached_d = core.get_cached_data_ro()
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

    @staticmethod
    def summarize_terminal_log_text(full_text: str) -> str:
        """VM 시스템/터미널 로그를 요약 버전(트레이스백 압축 · 핵심 상태/경고/오류 위주 1줄 요약)으로 변환합니다."""
        raw_lines = [ln.rstrip() for ln in (full_text or "").splitlines() if ln.strip()]
        if not raw_lines:
            return ""

        noise_tokens = ("DEBUG:", "heartbeat", "keepalive", "Gateway", "shard ID")
        condensed: list[str] = []
        idx = 0
        while idx < len(raw_lines):
            ln = raw_lines[idx]
            if ln.lstrip().startswith("Traceback (most recent call last):"):
                tb_end = idx + 1
                while tb_end < len(raw_lines) and (
                    raw_lines[tb_end].startswith("  ") or raw_lines[tb_end].lstrip().startswith("File ")
                ):
                    tb_end += 1
                err_line = raw_lines[tb_end].strip() if tb_end < len(raw_lines) else "Exception"
                collapsed_cnt = max(1, tb_end - idx)
                short_err = err_line[:130] + "..." if len(err_line) > 130 else err_line
                condensed.append(f"[❌ 예외 요약] {short_err} (스택 {collapsed_cnt}줄 축약)")
                idx = tb_end + 1
                continue

            if any(tok in ln for tok in noise_tokens):
                idx += 1
                continue

            clean_ln = ln.strip()
            if len(clean_ln) > 240:
                clean_ln = clean_ln[:240].rstrip() + "..."
            condensed.append(clean_ln)
            idx += 1

        if not condensed:
            return ""

        return "\n".join(condensed)

    @staticmethod
    def build_detailed_terminal_header(full_text: str) -> str:
        """상세 버전 터미널 로그 상단에 붙는 통계 헤더(발생 시각 KST · 총 줄 수 · 경고/오류/예외 개수)를 생성합니다."""
        lines = [ln for ln in full_text.splitlines() if ln.strip()]
        warn_cnt = sum(1 for ln in lines if re.search(r"\b(WARN|WARNING)\b|⚠️", ln))
        err_cnt = sum(1 for ln in lines if re.search(r"\b(ERROR|CRITICAL|FATAL)\b|❌", ln))
        tb_cnt = sum(1 for ln in lines if ln.lstrip().startswith("Traceback (most recent call last)"))
        now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"[📋 상세 로그 · {now_kst} KST · 총 {len(lines)}줄 · "
            f"⚠️ 경고 {warn_cnt} · ❌ 오류 {err_cnt} · 🧵 예외 스택 {tb_cnt}]\n"
        )

    @tasks.loop(seconds=3.0)
    async def terminal_log_dispatch_loop(self):
        """3초마다 VM 터미널 출력 큐를 확인하여 서버별 설정 버전(상세/요약)에 맞춰 안전하게 전송합니다."""
        if not self.terminal_log_queue or self.terminal_log_queue.empty():
            return

        data = core.get_cached_data_ro()
        channel_modes: dict[int, str] = {}

        # 1. 서버별 등록된 터미널 로그 채널 및 출력 버전(detailed / summary) 수집
        settings_d = core.as_dict(data.get("settings"))
        t_channels = settings_d.get("terminal_log_channels", {})
        t_modes = core.as_dict(settings_d.get("terminal_log_modes"))
        default_mode = "summary" if settings_d.get("terminal_log_default_mode") == "summary" else "detailed"

        if isinstance(t_channels, dict):
            for gk, cid in t_channels.items():
                if cid and str(cid).isdigit():
                    m_val = "summary" if t_modes.get(str(gk)) == "summary" else "detailed"
                    channel_modes[int(cid)] = m_val
        elif isinstance(t_channels, (list, set)):
            for cid in t_channels:
                if cid and str(cid).isdigit():
                    channel_modes[int(cid)] = default_mode

        # 2. 레거시 단일 설정 채널 ID도 포함
        legacy_id = settings_d.get("terminal_log_channel_id")
        if legacy_id and str(legacy_id).isdigit():
            channel_modes.setdefault(int(legacy_id), default_mode)

        if not channel_modes:
            while not self.terminal_log_queue.empty():
                try:
                    self.terminal_log_queue.get_nowait()
                except Exception:
                    break
            return

        detailed_channels = []
        summary_channels = []
        for cid, mode_str in list(channel_modes.items()):
            ch = await self.resolve_channel(cid)
            if ch:
                if mode_str == "summary":
                    summary_channels.append(ch)
                else:
                    detailed_channels.append(ch)

        if not detailed_channels and not summary_channels:
            return

        chunks = []
        while not self.terminal_log_queue.empty():
            try:
                chunk = self.terminal_log_queue.get_nowait()
                chunks.append(chunk)
            except asyncio.QueueEmpty:
                break

        if not chunks:
            return

        full_text = core.redact_secrets("".join(chunks).replace("```", "'''"))

        def _chunk_log_text(src_text: str, max_msgs: int = 2) -> list[str]:
            out_msgs = []
            buf = ""
            for line in src_text.splitlines(keepends=True):
                if len(buf) + len(line) > 1800:
                    if buf.strip():
                        out_msgs.append(buf.strip())
                    buf = line
                else:
                    buf += line
            if buf.strip():
                out_msgs.append(buf.strip())
            if len(out_msgs) > max_msgs:
                dropped_cnt = len(out_msgs) - max_msgs
                head_n = max(1, max_msgs - 1)
                out_msgs = out_msgs[:head_n] + [
                    f"... [⚠️ 터미널 출력 폭주 방어: 중간 로그 약 {dropped_cnt * 1800}자 생략됨. 서버 VM 콘솔 참조] ...\n" + out_msgs[-1],
                ]
            return out_msgs

        async def _send_batch(target_chs: list, msg_list: list[str]):
            if not target_chs or not msg_list:
                return
            for idx, msg in enumerate(msg_list):
                if not msg.strip():
                    continue
                payload = f"```log\n{msg.strip()}\n```"
                for ch in target_chs:
                    try:
                        await ch.send(payload)
                    except discord.HTTPException as he:
                        if he.status == 429:
                            self._orig_stderr.write(f"[TerminalLogger] 채널 {ch.id} 전송 429 감지(일시대기): {he}\n")
                        else:
                            self._orig_stderr.write(f"[TerminalLogger] 채널 {ch.id} 전송 HTTP 오류: {he}\n")
                    except Exception as e:
                        self._orig_stderr.write(f"[TerminalLogger] 채널 {ch.id} 전송 실패: {e}\n")
                if idx < len(msg_list) - 1:
                    await asyncio.sleep(1.1)

        if detailed_channels:
            # 상세 버전: 발생 시각·줄 수·경고/오류 통계 헤더를 붙이고, 폭주 방어 한도를 5개 메시지(약 9,000자)까지 확장
            await _send_batch(detailed_channels, _chunk_log_text(self.build_detailed_terminal_header(full_text) + full_text, max_msgs=5))
        if summary_channels:
            summary_txt = self.summarize_terminal_log_text(full_text)
            if summary_txt:
                await _send_batch(summary_channels, _chunk_log_text(summary_txt))

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
                if msg_id is not None:
                    msg_bucket = views.get(msg_id)
                    if isinstance(msg_bucket, dict) and key in msg_bucket:
                        item = msg_bucket.get(key)
                        item_view = getattr(item, "view", None)
                        if item_view is not None and not item_view.is_finished():
                            return True
                        # 종료되었거나 유실된 뷰 엔트리는 즉시 정리하여 폴백 복구 허용
                        msg_bucket.pop(key, None)
                none_bucket = views.get(None)
                if isinstance(none_bucket, dict) and key in none_bucket:
                    item = none_bucket.get(key)
                    item_view = getattr(item, "view", None)
                    if item_view is not None and not item_view.is_finished():
                        return True
                    none_bucket.pop(key, None)
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

        # 2. 레거시/단축 프리픽스 정규화 및 결정론적 커스텀 ID 패턴: norosi:{ViewClassName}:{item_name}
        orig_custom_id = custom_id
        _LEGACY_PREFIX_VIEW_MAP = {
            "countdown:": "CountdownCardView",
            "link_preview:": "LinkCleanupView",
            "raid_defense:": "RaidAlertControlView",
            "relay_novel:": "RelayNovelView",
            "temp_voice:": "TempVoiceControlView",
        }
        for pfx, v_cls_name in _LEGACY_PREFIX_VIEW_MAP.items():
            if custom_id.startswith(pfx):
                custom_id = f"norosi:{v_cls_name}:{custom_id.split(':', 1)[1]}"
                break

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
                                if getattr(child, "custom_id", None) in (custom_id, orig_custom_id):
                                    target_item = child
                                    break
                            if not target_item:
                                for child in view.children:
                                    cb_name = getattr(getattr(child, "callback", None), "__name__", "")
                                    if cb_name and (cb_name == item_name or item_name.startswith(f"{cb_name}_r")):
                                        target_item = child
                                        break
                                    if getattr(child, "label", None) == item_name:
                                        target_item = child
                                        break
                                    ph = getattr(child, "placeholder", None) or ""
                                    if ph and (ph == item_name or ph[:30] == item_name[:30]):
                                        target_item = child
                                        break
                                    child_cid = getattr(child, "custom_id", "") or ""
                                    if child_cid.endswith(f":{item_name}"):
                                        target_item = child
                                        break
                                    if (
                                        view_name == "Settings"
                                        and (item_name == "nav_back" or item_name.startswith("nav_back:"))
                                        and child_cid.startswith("norosi:Settings:nav_back")
                                    ):
                                        target_item = child
                                        break
                            if not target_item and interaction.data.get("component_type") in (3, 5, 6, 7, 8):
                                select_children = [
                                    c for c in view.children
                                    if isinstance(
                                        c,
                                        (
                                            discord.ui.Select,
                                            discord.ui.UserSelect,
                                            discord.ui.RoleSelect,
                                            discord.ui.ChannelSelect,
                                            discord.ui.MentionableSelect,
                                        ),
                                    )
                                ]
                                if len(select_children) == 1:
                                    target_item = select_children[0]
                            if not target_item and callable(getattr(view, "_page_num_on_select", None)):
                                m_page = re.search(r":(?:pnum|p|catpage_[a-z]+):(\d+)$", custom_id)
                                if m_page:
                                    try:
                                        allowed = await view.interaction_check(interaction)
                                    except Exception:
                                        allowed = True
                                    if not allowed:
                                        return
                                    await view._page_num_on_select(interaction, int(m_page.group(1)))
                                    if msg and not view.is_finished():
                                        self.attach_view_to_message(view, message_id=msg.id)
                                    return
                            if target_item and hasattr(target_item, "callback"):
                                try:
                                    allowed = await view.interaction_check(interaction)
                                except Exception:
                                    allowed = True
                                if not allowed:
                                    return
                                if hasattr(target_item, "_refresh_state"):
                                    try:
                                        target_item._refresh_state(interaction, interaction.data)
                                    except Exception:
                                        pass
                                try:
                                    await target_item.callback(interaction)
                                except Exception as cb_err:
                                    print(f"⚠️ [norosi 버튼 콜백 실행 예외] {cb_err}", flush=True)
                                    await core.safe_send_response(
                                        interaction,
                                        f"⚠️ 버튼 처리 중 오류가 발생했습니다: `{cb_err}`",
                                        ephemeral=True,
                                    )
                                if msg and not view.is_finished():
                                    vs = getattr(getattr(self, "_connection", None), "_view_store", None)
                                    synced = getattr(vs, "_synced_message_views", {}).get(msg.id) if vs else None
                                    if synced is None or synced is view or synced.is_finished():
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
                    elif "24/7" in cl or "상주" in cl:
                        target_btn = view.toggle_247_btn
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

            # 3-2. 올인원 통합 설정 (/설정) & 마스터 대시보드
            if "통합 설정" in embed_text or "마스터 대시보드" in embed_text or "norosi 통합 제어" in embed_text:
                try:
                    from cogs.dashboard import MasterDashboardView
                    data = core.get_cached_data()
                    view = MasterDashboardView(self, interaction.user, interaction.guild, data)
                    view.message = msg
                    try:
                        view._restore_from_message(interaction)
                    except Exception:
                        pass

                    if component_type in (3, 5, 6, 7, 8):
                        sel_val = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
                        select_children = [c for c in view.children if isinstance(c, discord.ui.Select)]
                        target_sel = None
                        for child in select_children:
                            if sel_val is not None and any(getattr(opt, "value", None) == sel_val for opt in getattr(child, "options", [])):
                                target_sel = child
                                break
                        if target_sel is None and select_children:
                            target_sel = select_children[0]
                        if target_sel is not None:
                            if hasattr(target_sel, "_refresh_state"):
                                try:
                                    target_sel._refresh_state(interaction, interaction.data)
                                except Exception:
                                    pass
                            try:
                                await target_sel.callback(interaction)
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
                    if component_type in (3, 5, 6, 7, 8):
                        sel_val = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
                        select_children = [c for c in view.children if isinstance(c, discord.ui.Select)]
                        target_sel = next(
                            (c for c in select_children if sel_val is not None and any(getattr(opt, "value", None) == sel_val for opt in getattr(c, "options", []))),
                            select_children[0] if select_children else None,
                        )
                        if target_sel is not None:
                            if hasattr(target_sel, "_refresh_state"):
                                try:
                                    target_sel._refresh_state(interaction, interaction.data)
                                except Exception:
                                    pass
                            try:
                                await target_sel.callback(interaction)
                            except Exception as cb_err:
                                print(f"⚠️ [플레이리스트 스튜디오 셀렉트 콜백 예외] {cb_err}", flush=True)
                            if msg:
                                self.attach_view_to_message(view, message_id=msg.id)
                            return
                    for child in view.children:
                        if clicked_label and getattr(child, "label", None) == clicked_label:
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
                    view = HelpCategoryView(self, author=interaction.user)
                    view.message = msg
                    if component_type in (3, 5, 6, 7, 8):
                        sel_val = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
                        select_children = [c for c in view.children if isinstance(c, discord.ui.Select)]
                        target_sel = next(
                            (c for c in select_children if sel_val is not None and any(getattr(opt, "value", None) == sel_val for opt in getattr(c, "options", []))),
                            select_children[0] if select_children else None,
                        )
                        if target_sel is not None:
                            if hasattr(target_sel, "_refresh_state"):
                                try:
                                    target_sel._refresh_state(interaction, interaction.data)
                                except Exception:
                                    pass
                            try:
                                await target_sel.callback(interaction)
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
                        if (custom_id and getattr(child, "custom_id", None) == custom_id) or (
                            clicked_label and getattr(child, "label", None) == clicked_label
                        ):
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
        봇 부팅 시 백그라운드에서 슬래시 명령어를 핵심 3종('/설정', '/도움말', '/후원')으로 단일화하여 동기화합니다.
        기존 길드별 잔류 슬래시 캐시도 정리하여 디스코드에서 핵심 슬래시 명령어 외의 항목이 남지 않게 합니다.
        """
        try:
            kept = self.prune_slash_tree_to_core()
            print(f"🌐 [백그라운드 동기화] 슬래시 명령어 단일화({', '.join('/' + k for k in kept)}) 동기화 시작...", flush=True)
            for g in list(self.guilds):
                try:
                    self.tree.clear_commands(guild=g)
                    await self.tree.sync(guild=g)
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
            synced_cmds = await self.tree.sync()
            print(f"✅ [동기화 완료] 슬래시 명령어 총 {len(synced_cmds)}개(/설정, /도움말, /후원) 글로벌 등록 완료!", flush=True)
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
            activity=discord.Game(name="🌠ㅣ/설정 · /도움말 · /후원")
        )

        if not self._commands_synced:
            self._commands_synced = True
            asyncio.create_task(self._safe_startup_sync())

        asyncio.create_task(self.update_all_dday_channels())

    async def on_guild_join(self, guild: discord.Guild):
        """새 디스코드 서버에 초대되었을 때 길드 명령어 캐시를 비우고 글로벌 명령어만 깔끔하게 단일 노출"""
        try:
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"✅ 신규 서버 입장 및 중복 길드 명령어 클린업 완료: {guild.name} ({guild.id})", flush=True)
        except Exception as e:
            print(f"⚠️ 신규 서버 명령어 클린업 오류 ({guild.name}): {e}", flush=True)

    async def update_all_dday_channels(self):
        if getattr(self, "_dday_update_running", False):
            return
        self._dday_update_running = True
        try:
            data = await asyncio.to_thread(core.load_data)
            ddays = core.as_dict(data.get("ddays"))
            if not ddays:
                return

            last_renames: dict[int, float] = getattr(self, "_dday_last_rename_ts", None)
            if last_renames is None:
                last_renames = {}
                self._dday_last_rename_ts = last_renames

            alert_ch_id = core.as_dict(data.get("settings")).get("dday_alert_channel_id")
            alert_channel = await self.resolve_channel(alert_ch_id) if alert_ch_id else None

            for name, info in list(ddays.items()):
                if not isinstance(info, dict):
                    continue
                ch_id = info.get("channel_id")
                if not ch_id:
                    continue
                channel = await self.resolve_channel(ch_id)
                if not channel or "date" not in info:
                    continue

                emoji = info.get("emoji", "🌠")
                plus_one_val = bool(info.get("plus_one", False))
                display_name = core.get_dday_display_name(name, info)
                new_name = core.format_dday_channel_name(display_name, info["date"], emoji, plus_one=plus_one_val)
                if getattr(channel, "name", None) != new_name:
                    now_m = time.monotonic()
                    # 디스코드 채널명 변경 버킷(10분당 2회) 과부하 방지: 동일 채널은 최소 310초 간격 보장
                    if now_m - last_renames.get(channel.id, 0.0) < 310.0:
                        continue
                    try:
                        await channel.edit(name=new_name)
                        last_renames[channel.id] = time.monotonic()
                    except discord.Forbidden:
                        ch_guild_id = getattr(getattr(channel, "guild", None), "id", None) or info.get("guild_id")
                        guild_alert_id = core.get_guild_setting(data, ch_guild_id, "dday_alert_channel_id")
                        target_alert = await self.resolve_channel(guild_alert_id) if guild_alert_id else alert_channel
                        if target_alert:
                            try:
                                await target_alert.send(
                                    f"🚨 **권한 오류:** 봇에게 `{channel.name}` 채널의 **'채널 관리'** 권한이 없습니다."
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"전광판 업데이트 오류 ({display_name}): {e}", flush=True)
        finally:
            self._dday_update_running = False

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

        today = datetime.datetime.now(core.KST).date()

        def _process_midnight_state():
            with core._DATA_LOCK:
                data = core.load_data()
                updated = False
                for name, info in list(core.as_dict(data.get("ddays")).items()):
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
                            info["date"] = t_date.strftime("%Y-%m-%d")
                            info["start_date"] = old_target_str
                            updated = True

                # 자정(00:00 KST) 멤버 생일 자동 축하 및 +500 크리스탈 단일 지급
                bday_map = core.as_dict(data.get("birthdays"))
                alert_ch_id = core.as_dict(data.get("settings")).get("dday_alert_channel_id")
                bday_notifications = []

                for u_key, b_info in list(bday_map.items()):
                    if not isinstance(b_info, dict):
                        continue
                    if b_info.get("month") == today.month and b_info.get("day") == today.day:
                        if b_info.get("last_celebrated_year") != today.year:
                            b_info["last_celebrated_year"] = today.year
                            uid = b_info.get("user_id") or int(u_key)
                            uname = b_info.get("user_name", "멤버")
                            prof = core.ensure_user_profile(data, u_key, uname)
                            prof["crystals"] = int(prof.get("crystals", 0)) + 500
                            updated = True

                            g_id = b_info.get("guild_id")
                            g_ch_id = None
                            if g_id:
                                g_settings = core.safe_get_dict(data, "guild_settings", str(g_id))
                                g_ch_id = g_settings.get("dday_alert_channel_id")
                            bday_notifications.append({
                                "uid": uid,
                                "uname": uname,
                                "crystals": prof["crystals"],
                                "memo": b_info.get("memo"),
                                "guild_ch_id": g_ch_id,
                            })

                if updated:
                    core.save_data(data)
                return alert_ch_id, bday_notifications

        alert_ch_id, bday_notifications = await asyncio.to_thread(_process_midnight_state)
        alert_ch = await self.resolve_channel(alert_ch_id) if alert_ch_id else None

        for item in bday_notifications:
            uid = item["uid"]
            uname = item["uname"]
            bday_embed = discord.Embed(
                title=f"🎂 Happy Birthday! 오늘은 {uname}님의 생일입니다! 🎉",
                description=(
                    f"🎊 <@{uid}>님, 일 년에 단 한 번뿐인 소중한 생일을 진심으로 축하드립니다!\n"
                    f"🎁 **세카이 생일 축하 보너스:** `+500 💎 크리스탈`이 지급되었습니다! (보유: `{item['crystals']:,}💎`)"
                    + (f"\n💬 **생일 소원:** *\"{item['memo']}\"*" if item.get("memo") else "")
                ),
                color=discord.Color.from_rgb(255, 105, 180),
                timestamp=datetime.datetime.now(core.KST)
            )
            target_ch = None
            if item.get("guild_ch_id"):
                target_ch = await self.resolve_channel(item["guild_ch_id"])
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

        # 매주 월요일 자정(00:00 KST) 주간 로또 복권 자동 추첨 및 당첨 발표
        if today.weekday() == 0:
            try:
                import economy_core
                ov = await asyncio.to_thread(economy_core.get_lottery_overview, 0)
                last_draw = ov.get("last_draw") if isinstance(ov.get("last_draw"), dict) else {}
                cur_wk = datetime.datetime.now(core.KST).strftime("%Y-W%W")
                if ov.get("total_tickets", 0) > 0 and last_draw.get("week_key") != cur_wk:
                    draw_rec = await asyncio.to_thread(economy_core.execute_lottery_draw, "auto_monday")
                    win_nums_str = ", ".join(str(x) for x in (draw_rec.get("winning_numbers") or []))
                    winners = draw_rec.get("winners") or []
                    win_lines = [
                        f"• **{w['best_rank']}등** <@{w['user_id']}> (`{w['user_name']}`) — **`+{w['total_prize']:,}💎`**"
                        for w in winners[:5]
                    ] or ["• 이번 회차 당첨자가 없어 1등 잭팟이 다음 회차로 이월되었습니다!"]
                    lot_embed = discord.Embed(
                        title=f"🎟️ 제 {draw_rec['round']}회차 주간 크리스탈 복권 추첨 결과!",
                        description=(
                            f"🎱 **당첨 번호:** **`[ {win_nums_str} ]`**\n"
                            f"💰 **총 상금 풀:** `{draw_rec['total_pot']:,}💎` · **판매 티켓:** `{draw_rec['ticket_count']:,}장`\n"
                            f"🏆 **1등({draw_rec['rank1_count']}명)** · **2등({draw_rec['rank2_count']}명)** · **3등({draw_rec['rank3_count']}명)**\n"
                            "━━━━━━━━━━━━━━━━\n"
                            + "\n".join(win_lines)
                        ),
                        color=discord.Color.gold(),
                        timestamp=datetime.datetime.now(core.KST),
                    )
                    lot_embed.set_footer(text=f"다음 회차 시작 잭팟: {draw_rec.get('next_jackpot', 1000):,}💎 • /설정에서 참여해 보세요!")

                    ann_map = draw_rec.get("announce_channels") or {}
                    sent_lot_chs: set[int] = set()
                    for ch_val in ann_map.values():
                        if ch_val and int(ch_val) not in sent_lot_chs:
                            ch_obj = await self.resolve_channel(int(ch_val))
                            if ch_obj:
                                try:
                                    await ch_obj.send(embed=lot_embed)
                                    sent_lot_chs.add(int(ch_val))
                                except Exception:
                                    pass
                    if not sent_lot_chs and alert_ch:
                        try:
                            await alert_ch.send(embed=lot_embed)
                        except Exception:
                            pass
            except Exception as lot_err:
                print(f"⚠️ [주간 복권 자동 추첨 예외] {lot_err}", flush=True)

        await self.update_all_dday_channels()

    @midnight_tasks.before_loop
    async def before_midnight_tasks(self):
        await self.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=7, minute=0, tzinfo=core.KST))
    async def morning_music_alert(self):
        data = await asyncio.to_thread(core.load_data)
        targets: list[tuple[int, dict]] = []
        seen_ch_ids: set[int] = set()

        guild_prefs_map = core.as_dict(data.get("guild_music_prefs"))
        for g_key, g_prefs in guild_prefs_map.items():
            if not isinstance(g_prefs, dict):
                continue
            gid_int = int(g_key) if str(g_key).isdigit() else None
            ch_id = g_prefs.get("channel_id") or core.get_guild_setting(data, gid_int, "dday_alert_channel_id", fallback_global=False)
            if ch_id and int(ch_id) not in seen_ch_ids:
                seen_ch_ids.add(int(ch_id))
                targets.append((int(ch_id), g_prefs))

        # 레거시 단일 전역 music_prefs 폴백 (아직 guild_music_prefs에 포함되지 않은 채널만)
        legacy_prefs = core.as_dict(data.get("music_prefs")) or core.DEFAULT_CONFIG["music_prefs"]
        legacy_ch_id = legacy_prefs.get("channel_id") or core.as_dict(data.get("settings")).get("dday_alert_channel_id")
        if legacy_ch_id and int(legacy_ch_id) not in seen_ch_ids:
            seen_ch_ids.add(int(legacy_ch_id))
            targets.append((int(legacy_ch_id), legacy_prefs))

        for target_ch_id, prefs in targets:
            channel = await self.resolve_channel(target_ch_id)
            if not channel:
                continue
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

        def _snapshot_schedules():
            with core._DATA_LOCK:
                data = core.load_data()
                raw_schedules = data.get("music_schedules")
                schedules_snap = copy.deepcopy(raw_schedules) if isinstance(raw_schedules, list) else []
                raw_reminders = data.get("reminders")
                reminders_snap = copy.deepcopy(raw_reminders) if isinstance(raw_reminders, list) else []
                base_prefs_snap = copy.deepcopy(core.as_dict(data.get("music_prefs")) or core.DEFAULT_CONFIG["music_prefs"])
                return schedules_snap, reminders_snap, base_prefs_snap

        schedules, reminders, base_prefs = await asyncio.to_thread(_snapshot_schedules)
        if not schedules and not reminders:
            return

        sent_schedule_keys = set()

        for sched in schedules:
            if not isinstance(sched, dict):
                continue
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
                sent_schedule_keys.add((sched.get("name"), sched.get("time"), sched.get("channel_id")))

        # /알림예약 개인 알리미 시각 도달 체크 및 발송
        now_ts = time.time()
        fired_reminders = False
        for rem in reminders:
            if not isinstance(rem, dict):
                continue
            if rem.get("trigger_ts", 0) <= now_ts:
                fired_reminders = True
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
                rem_embed.set_footer(text="norosi 스마트 개인 알리미 (/설정 ➔ 스마트 알림 예약)")

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

        if sent_schedule_keys or fired_reminders:
            def _save_schedules():
                with core._DATA_LOCK:
                    fresh_data = core.load_data()
                    if sent_schedule_keys:
                        fresh_scheds = fresh_data.get("music_schedules")
                        if isinstance(fresh_scheds, list):
                            for s in fresh_scheds:
                                if isinstance(s, dict) and (s.get("name"), s.get("time"), s.get("channel_id")) in sent_schedule_keys:
                                    s["last_sent"] = today_str
                    if fired_reminders:
                        fresh_raw_reminders = fresh_data.get("reminders")
                        fresh_reminders = [
                            r for r in (fresh_raw_reminders if isinstance(fresh_raw_reminders, list) else [])
                            if isinstance(r, dict) and r.get("trigger_ts", 0) > now_ts
                        ]
                        fresh_data["reminders"] = fresh_reminders
                    core.save_data(fresh_data)

            await asyncio.to_thread(_save_schedules)

    @custom_music_schedules_loop.before_loop
    async def before_custom_music_loop(self):
        await self.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=core.KST))
    async def morning_text_alert(self):
        data = await asyncio.to_thread(core.load_data)
        today_str = core.get_today_str()

        # 1. 나만의 비밀 디데이 & 타임캡슐 개인 DM 발송 체크
        dm_updated = False
        notified_secrets = []
        notified_partners = []
        for u_key, p_info in list(core.as_dict(data.get("user_profiles")).items()):
            if not isinstance(p_info, dict):
                continue
            secret_ddays = core.as_dict(p_info.get("secret_ddays"))
            for s_name, s_info in list(secret_ddays.items()):
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
                            notified_secrets.append((u_key, s_name))
                            dm_updated = True
                    except Exception as e:
                        print(f"⚠️ 비밀 디데이 DM 전송 실패 ({u_key}): {e}", flush=True)

        # 2. 파트너 공동 D-Day 당일 두 사람에게 DM 발송 체크
        for pair_key, pair_info in list(core.as_dict(data.get("partners")).items()):
            if not isinstance(pair_info, dict):
                continue
            uid_parts = str(pair_key).split("_")
            if len(uid_parts) != 2:
                continue
            for p_dday_name, p_dday_info in list(core.as_dict(pair_info.get("ddays")).items()):
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
                    notified_partners.append((pair_key, p_dday_name))
                    dm_updated = True

        if dm_updated:
            def _save_morning_dm():
                with core._DATA_LOCK:
                    fresh_data = core.load_data()
                    for u_k, s_n in notified_secrets:
                        s_dict = core.safe_get_dict(fresh_data, "user_profiles", u_k, "secret_ddays", s_n)
                        if s_dict:
                            s_dict["notified_date"] = today_str
                    for p_k, p_n in notified_partners:
                        p_dict = core.safe_get_dict(fresh_data, "partners", p_k, "ddays", p_n)
                        if p_dict:
                            p_dict["notified_date"] = today_str
                    core.save_data(fresh_data)

            await asyncio.to_thread(_save_morning_dm)

        # 3. 서버별 공개 오전 9시 D-Day 요약 알림 (각 서버 소속 D-Day만 격리 발송)
        all_ddays = core.as_dict(data.get("ddays"))
        if not all_ddays:
            return

        alert_targets: list[int] = []
        seen_alert_chs: set[int] = set()
        for _g_key, g_cfg in core.as_dict(data.get("guild_settings")).items():
            if not isinstance(g_cfg, dict):
                continue
            ch_id = g_cfg.get("dday_alert_channel_id")
            if ch_id and int(ch_id) not in seen_alert_chs:
                seen_alert_chs.add(int(ch_id))
                alert_targets.append(int(ch_id))

        legacy_alert_ch = core.as_dict(data.get("settings")).get("dday_alert_channel_id")
        if legacy_alert_ch and int(legacy_alert_ch) not in seen_alert_chs:
            seen_alert_chs.add(int(legacy_alert_ch))
            alert_targets.append(int(legacy_alert_ch))

        for alert_ch_id in alert_targets:
            channel = await self.resolve_channel(alert_ch_id)
            if not channel:
                continue

            ch_guild = getattr(channel, "guild", None)
            ddays = core.filter_guild_ddays(all_ddays, ch_guild, bot=self) if ch_guild else all_ddays
            if not ddays:
                continue

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
                plus_one_val = bool(info.get("plus_one", False))
                try:
                    diff, text = core.get_dday_info(date_str, plus_one=plus_one_val)
                except Exception:
                    continue
                shown_name = core.get_dday_display_name(name, info)
                display_name = f"{shown_name} 🔄" if info.get("repeat") else shown_name
                if diff >= 0:
                    bar_str = core.get_galaxy_progress_bar(info.get("start_date", today_str), date_str)
                    upcoming_lines.append(f"• **{display_name}** (`{date_str}`) — **`{text}`**\n  └ {bar_str}")
                    if diff < min_diff:
                        min_diff = diff
                elif diff >= -7:
                    plus_tag = " `(+1일 계산)`" if plus_one_val else ""
                    recent_past_lines.append(f"• ~~{display_name} ({date_str})~~ : `{text}`{plus_tag}")
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
                embed.set_footer(text=f"📦 7일 이상 경과한 지난 일정 {archived_count}개는 /설정 (D-Day 전광판 ➔ 지나간 D-Day)에서 확인할 수 있습니다.")

            embed.color = core.get_embed_color(min_diff if upcoming_lines else -1)
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"⚠️ 오전 9시 D-Day 알림 전송 오류 (채널 {alert_ch_id}): {e}", flush=True)

    @morning_text_alert.before_loop
    async def before_morning_text_alert(self):
        await self.wait_until_ready()


bot = NorosiBot()


# ==========================================
# 🖥️ VM 서버 터미널 로그 수신 채널 지정 명령어 (/설정 연동)
# ==========================================
def _parse_terminal_log_mode_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    norm = str(token).strip().lower()
    if norm in ("summary", "compact", "brief", "short", "요약", "요약본", "요약모드", "요약버전", "간략"):
        return "summary"
    if norm in ("detailed", "detail", "full", "raw", "상세", "상세본", "상세모드", "상세버전", "전체"):
        return "detailed"
    return None


async def set_terminal_log_channel_slash(
    interaction: discord.Interaction,
    채널: Optional[discord.TextChannel] = None,
    버전: Optional[str] = None,
):
    if not await bot.is_bot_owner_user(interaction.user):
        await core.safe_send_response(interaction, "❌ 이 명령어는 **봇 소유자**만 사용할 수 있습니다.", ephemeral=True)
        return

    await core.safe_defer(interaction, ephemeral=True)
    g_key = str(interaction.guild_id) if interaction.guild_id else "global"
    parsed_mode = _parse_terminal_log_mode_token(버전) or "detailed"

    def _update_tlog():
        with core._DATA_LOCK:
            data = core.load_data()
            settings_dict = core.ensure_dict_path(data, "settings")
            t_channels = core.ensure_dict_path(data, "settings", "terminal_log_channels")
            t_modes = core.ensure_dict_path(data, "settings", "terminal_log_modes")
            if 채널 is None:
                t_channels.pop(g_key, None)
                t_modes.pop(g_key, None)
                if not t_channels:
                    settings_dict["terminal_log_channel_id"] = None
            else:
                t_channels[g_key] = 채널.id
                t_modes[g_key] = parsed_mode
                settings_dict["terminal_log_channel_id"] = 채널.id
                settings_dict["terminal_log_default_mode"] = parsed_mode
            core.save_data(data)
            return len(t_channels)

    total_ch_cnt = await asyncio.to_thread(_update_tlog)

    if 채널 is None:
        await interaction.followup.send(f"🛑 **현재 서버({interaction.guild.name if interaction.guild else '글로벌'})의 VM 서버 터미널 로그 채널 전송이 해제되었습니다.**", ephemeral=True)
        print(f"ℹ️ [System] {interaction.user}에 의해 {interaction.guild}의 터미널 로그 채널 전송이 비활성화되었습니다.", flush=True)
    else:
        mode_badge = "⚡ 요약 버전 (핵심 라인·예외 스택 요약)" if parsed_mode == "summary" else "📋 상세 버전 (원문 전체 출력)"
        embed = discord.Embed(
            title="🖥️ VM 서버 터미널 실시간 로그 채널 지정 완료!",
            description=(
                f"이제부터 VM 서버 터미널(`stdout` / `stderr` / `logging`) 로그가 {채널.mention} 채널에 실시간으로 기록됩니다.\n\n"
                f"• **현재 채널:** {채널.mention} (`#{채널.name}`)\n"
                f"• **출력 버전:** {mode_badge}\n"
                f"• **전체 연동 서버:** 총 {total_ch_cnt}개 서버 채널에 실시간 동시 전송 중\n"
                "• **전송 주기:** `3초` 단위 버퍼링 묶음 전송 (도배 및 Rate Limit 완벽 방어)\n"
                "• **버전 전환 / 해제:** `/설정` → `⚙️ 고급 (4p)` → `VM 터미널 로그`"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"✅ [System] VM 터미널 실시간 로그 수신 채널이 #{채널.name} (ID: {채널.id}, 모드: {parsed_mode}, 서버: {interaction.guild})로 지정되었습니다. (총 {total_ch_cnt}개 서버 동시 전송)", flush=True)





# ==========================================
# 🖼️ 봇주 전용 봇 프로필 배너 변경 명령어 (/설정 연동)
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
    if not await asyncio.to_thread(core.is_safe_external_url, clean_url):
        raise ValueError("내부 네트워크 또는 안전하지 않은 주소의 URL은 사용할 수 없습니다.")
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(clean_url, allow_redirects=False) as resp:
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location", "")
                if not loc or not await asyncio.to_thread(core.is_safe_external_url, loc):
                    raise ValueError("안전하지 않은 리다이렉트 URL입니다.")
                async with session.get(loc, allow_redirects=False) as resp2:
                    resp = resp2
                    if resp.status != 200:
                        raise ValueError(f"이미지 다운로드 실패 (HTTP {resp.status})")
                    if resp.content_length and resp.content_length > MAX_BOT_BANNER_BYTES:
                        raise ValueError("이미지 용량이 10MB를 초과합니다.")
                    raw_bytes = await resp.content.read(MAX_BOT_BANNER_BYTES + 1)
            else:
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


async def set_bot_banner_slash(
    interaction: discord.Interaction,
    이미지: Optional[discord.Attachment] = None,
    이미지url: Optional[str] = None,
    초기화: bool = False
):
    if not await bot.is_bot_owner_user(interaction.user):
        await core.safe_send_response(
            interaction,
            "❌ 이 명령어는 **봇 소유자**(봇주)만 사용할 수 있습니다.",
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
        await core.safe_send_response(interaction, "❌ 이 조작은 **봇주**(Bot Owner)만 가능합니다.", ephemeral=True)
        return False

    @discord.ui.button(label="⚡ 현재 서버에 즉시 반영 (0초 반영)", style=discord.ButtonStyle.success, emoji="⚡", row=0)
    async def instant_sync_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_permission(interaction):
            return

        await core.safe_defer(interaction)
        try:
            bot.prune_slash_tree_to_core()
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
                    f"✅ **현재 서버**({target_guild.name if target_guild else '글로벌'})에 슬래시 명령어 `{g_cnt}개`(`/설정`, `/도움말`, `/후원`)가 0초 만에 즉시 등록되었습니다!\n"
                    f"👉 글로벌 슬래시 커맨드 총 `{len(synced_global)}개`도 전역 등록 완료되었습니다.\n\n"
                    "💡 모든 기능은 `/설정` 통합 허브 안에서 버튼으로 오류 없이 이용하실 수 있습니다!"
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
            bot.prune_slash_tree_to_core()
            synced = await bot.tree.sync()
            embed = discord.Embed(
                title="🌐 글로벌 슬래시 명령어 전역 동기화 완료!",
                description=(
                    f"✅ **총 `{len(synced)}개`**(`/설정`, `/도움말`, `/후원`)의 슬래시 명령어가 Discord API에 글로벌 등록되었습니다.\n"
                    "나머지 모든 기능은 `/설정` 통합 허브에서 이용 가능합니다."
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
            bot.prune_slash_tree_to_core()
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
                    "✅ 현재 서버의 길드 전용 캐시를 비우고 글로벌 단일 세트(`/설정`, `/도움말`, `/후원`)로 정돈했습니다.\n"
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
        ext_keys = [e for e in bot.extensions.keys() if e != "cogs.dashboard"]
        if "cogs.dashboard" in bot.extensions:
            ext_keys.append("cogs.dashboard")
        for ext in ext_keys:
            try:
                await bot.reload_extension(ext)
                reloaded.append(ext)
            except Exception as e:
                failed.append(f"{ext}: {e}")

        bot.prune_slash_tree_to_core()
        try:
            if self.guild:
                try:
                    bot.tree.clear_commands(guild=self.guild)
                    await bot.tree.sync(guild=self.guild)
                except Exception:
                    pass
            synced = await bot.tree.sync()
            sync_ok = f"글로벌 `{len(synced)}개` (`/설정`, `/도움말`, `/후원`) 갱신 완료"
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


def _format_commit_lines_highlighted(raw_lines: list[str], repo_url: str = "", limit: int = 10) -> str:
    """'8781bfd 커밋 제목' 형태의 git log --oneline 줄들을 커밋 ID를 굵은 배지/링크로 강조하고 제목과 명확히 구분해 포맷합니다."""
    out: list[str] = []
    for ln in (raw_lines or [])[:limit]:
        parts = ln.strip().split(" ", 1)
        if not parts or not parts[0]:
            continue
        sha = parts[0].strip()
        msg = (parts[1].strip() if len(parts) > 1 else "(메시지 없음)").replace("`", "ʼ")
        if len(msg) > 95:
            msg = msg[:95].rstrip() + "…"
        if repo_url:
            sha_badge = f"[**`[{sha}]`**]({repo_url}/commit/{sha})"
        else:
            sha_badge = f"**`[{sha}]`**"
        out.append(f"• {sha_badge}  ┃  {msg}")
    if len(raw_lines or []) > limit:
        out.append(f"  *(…외 `{len(raw_lines) - limit}건` 더 있음)*")
    return "\n".join(out)


# ==========================================
# 현재 봇에 반영 중인 GitHub 커밋/버전 및 누적 업데이트 반영 (봇 주인 전용)
# ==========================================
def get_local_head_short_sha() -> str:
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=5)
        return (p.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


async def build_git_version_embed_and_info() -> tuple[discord.Embed, dict]:
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    def _inspect_git_version() -> dict:
        def _run(cmd: list[str], timeout_s: int = 20) -> tuple[int, str]:
            try:
                p = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=timeout_s)
                out = ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
                return p.returncode, out
            except Exception as exc:
                return 1, str(exc)

        _, short_sha = _run(["git", "rev-parse", "--short", "HEAD"])
        _, full_sha = _run(["git", "rev-parse", "HEAD"])
        _, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch if branch and branch != "HEAD" else "master"
        _, subj = _run(["git", "log", "-1", "--format=%s"])
        _, author = _run(["git", "log", "-1", "--format=%an"])
        _, commit_ts = _run(["git", "log", "-1", "--format=%ct"])
        _, recent_commits = _run(["git", "log", "--oneline", "-n", "5"])
        _, remote_url = _run(["git", "config", "--get", "remote.origin.url"])

        _run(["git", "fetch", "origin", branch], timeout_s=15)
        behind_cnt = 0
        pending_commits: list[str] = []
        remote_commits: list[str] = []
        remote_sha = ""
        remote_full_sha = ""
        remote_subj = ""
        remote_ts = 0

        rc_r, r_sha = _run(["git", "rev-parse", "--short", f"origin/{branch}"])
        if rc_r == 0 and r_sha:
            remote_sha = r_sha
            _, remote_full_sha = _run(["git", "rev-parse", f"origin/{branch}"])
            _, remote_subj = _run(["git", "log", "-1", "--format=%s", f"origin/{branch}"])
            _, r_ts_txt = _run(["git", "log", "-1", "--format=%ct", f"origin/{branch}"])
            remote_ts = int(r_ts_txt) if r_ts_txt.isdigit() else 0
            _, rem_list_txt = _run(["git", "log", "--oneline", f"origin/{branch}", "-n", "5"])
            remote_commits = [ln.strip() for ln in rem_list_txt.splitlines() if ln.strip()]
            _, behind_txt = _run(["git", "rev-list", "--count", f"HEAD..origin/{branch}"])
            if behind_txt.isdigit():
                behind_cnt = int(behind_txt)
            if behind_cnt > 0:
                _, pend_txt = _run(["git", "log", "--oneline", f"HEAD..origin/{branch}", "-n", "15"])
                pending_commits = [ln.strip() for ln in pend_txt.splitlines() if ln.strip()]

        clean_repo_url = ""
        if remote_url:
            u = remote_url.strip()
            if u.startswith("git@github.com:"):
                u = "https://github.com/" + u[len("git@github.com:"):]
            if u.endswith(".git"):
                u = u[:-4]
            if u.startswith("https://github.com/"):
                clean_repo_url = u

        return {
            "short_sha": short_sha or "unknown",
            "full_sha": full_sha or "",
            "branch": branch,
            "subject": subj or "(커밋 메시지 없음)",
            "author": author or "-",
            "commit_unix": int(commit_ts) if commit_ts.isdigit() else 0,
            "recent_commits": [ln.strip() for ln in recent_commits.splitlines() if ln.strip()],
            "repo_url": clean_repo_url,
            "remote_sha": remote_sha or short_sha or "unknown",
            "remote_full_sha": remote_full_sha,
            "remote_subject": remote_subj or subj or "-",
            "remote_unix": remote_ts,
            "remote_commits": remote_commits,
            "behind_cnt": behind_cnt,
            "pending_commits": pending_commits,
        }

    info = await asyncio.to_thread(_inspect_git_version)
    short_sha = info["short_sha"]
    full_sha = info["full_sha"]
    remote_sha = info["remote_sha"]
    remote_full_sha = info["remote_full_sha"]
    repo_url = info["repo_url"]
    commit_link = f"[`{short_sha}`]({repo_url}/commit/{full_sha})" if (repo_url and full_sha) else f"`{short_sha}`"
    remote_link = f"[`{remote_sha}`]({repo_url}/commit/{remote_full_sha})" if (repo_url and remote_full_sha) else f"`{remote_sha}`"

    def _fmt_ts(ts_u: int) -> str:
        if ts_u > 0:
            kst_dt = datetime.datetime.fromtimestamp(ts_u, tz=core.KST).strftime("%Y-%m-%d %H:%M:%S KST")
            return f"`{kst_dt}` (<t:{ts_u}:R>)"
        return "-"

    behind_cnt = info["behind_cnt"]
    if behind_cnt > 0:
        sync_state = f"🟡 **GitHub에 미반영 업데이트 `{behind_cnt}건` 대기 중** (`{short_sha}` ➔ `{remote_sha}`)"
        color = discord.Color.gold()
    else:
        sync_state = f"🟢 **현재 봇과 GitHub 최신 버전이 동일합니다** (`{short_sha}`)"
        color = discord.Color.from_rgb(46, 204, 113)

    desc_lines = [
        f"• **동기화 상태:** {sync_state}",
        "",
        "**🤖 현재 봇에 반영 중인 버전 (`HEAD`)**",
        f"• **커밋:** {commit_link} (`{info['branch']}`) · **시각:** {_fmt_ts(info['commit_unix'])}",
        f"• **내용:** `{info['subject'][:140]}`",
        "",
        f"**🐙 현재 GitHub 최신 버전 (`origin/{info['branch']}`)**",
        f"• **커밋:** {remote_link} · **시각:** {_fmt_ts(info['remote_unix'])}",
        f"• **내용:** `{info['remote_subject'][:140]}`",
    ]

    if behind_cnt > 0 and info["pending_commits"]:
        pend_fmt = _format_commit_lines_highlighted(info["pending_commits"], repo_url=repo_url, limit=10)
        desc_lines.append(f"\n**📦 아직 반영되지 않은 대기 커밋 (`{behind_cnt}건`)**\n{pend_fmt}")

    if info["recent_commits"]:
        rec_fmt = _format_commit_lines_highlighted(info["recent_commits"], repo_url=repo_url, limit=5)
        desc_lines.append(f"\n**📌 현재 봇에 반영된 최근 커밋**\n{rec_fmt}")

    if info["remote_commits"]:
        rem_fmt = _format_commit_lines_highlighted(info["remote_commits"], repo_url=repo_url, limit=5)
        desc_lines.append(f"\n**🐙 현재 GitHub에 올라와 있는 최근 커밋**\n{rem_fmt}")

    embed = discord.Embed(
        title=f"🔖 norosi 버전 현황 — 봇 `{short_sha}` / GitHub `{remote_sha}`",
        description="\n".join(desc_lines)[:4000],
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    return embed, info


async def execute_github_update(force_restart: bool = False) -> tuple[discord.Embed, bool]:
    import importlib
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    def _git_pull_sync() -> dict:
        def _run(cmd: list[str]) -> tuple[int, str]:
            p = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=45)
            out = ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
            return p.returncode, out

        _, old_sha = _run(["git", "rev-parse", "--short", "HEAD"])
        _, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch if branch and branch != "HEAD" else "master"
        _, remote_url = _run(["git", "config", "--get", "remote.origin.url"])

        rc_f, out_f = _run(["git", "fetch", "origin", branch])
        if rc_f != 0:
            return {"ok": False, "err": f"git fetch 실패:\n{core.redact_secrets(out_f)[:600]}"}

        _, commits_txt = _run(["git", "log", "--oneline", f"HEAD..origin/{branch}", "-n", "25"])
        _, total_behind_txt = _run(["git", "rev-list", "--count", f"HEAD..origin/{branch}"])
        behind_cnt = int(total_behind_txt) if total_behind_txt.isdigit() else 0
        _, changed_txt = _run(["git", "diff", "--name-only", f"HEAD..origin/{branch}"])
        changed_files = [ln.strip() for ln in changed_txt.splitlines() if ln.strip()]

        if behind_cnt > 0:
            rc_p, _ = _run(["git", "pull", "--ff-only", "origin", branch])
            if rc_p != 0:
                _run(["git", "reset", "--hard", f"origin/{branch}"])
        _, new_sha = _run(["git", "rev-parse", "--short", "HEAD"])
        clean_repo_url = ""
        if remote_url:
            u = remote_url.strip()
            if u.startswith("git@github.com:"):
                u = "https://github.com/" + u[len("git@github.com:"):]
            if u.endswith(".git"):
                u = u[:-4]
            if u.startswith("https://github.com/"):
                clean_repo_url = u
        return {
            "ok": True,
            "branch": branch,
            "old_sha": old_sha,
            "new_sha": new_sha,
            "behind_cnt": behind_cnt,
            "commits": [ln.strip() for ln in commits_txt.splitlines() if ln.strip()],
            "changed_files": changed_files,
            "repo_url": clean_repo_url,
        }

    pull_info = await asyncio.to_thread(_git_pull_sync)
    if not pull_info.get("ok"):
        err_emb = discord.Embed(
            title="❌ GitHub 업데이트 가져오기 실패",
            description=f"```\n{pull_info.get('err')}\n```",
            color=discord.Color.red(),
        )
        return err_emb, False

    changed_files: list[str] = pull_info["changed_files"]
    bot_py_touched = ("bot.py" in changed_files) or ("requirements.txt" in changed_files)

    reloaded_cores: list[str] = []
    for mod_name in (
        "core",
        "economy_core",
        "genshin_core",
        "hsr_core",
        "fishing_core",
        "life_core",
        "other_life_endings",
        "other_life_narratives",
        "other_life_core",
        "routine_core",
        "sns_embed_core",
        "ticket_core",
        "community_core",
        "version_info",
    ):
        if mod_name in sys.modules and (not changed_files or f"{mod_name}.py" in changed_files or mod_name != "core"):
            try:
                if mod_name == "core":
                    saved_cache = getattr(core, "_DATA_CACHE", None)
                    saved_lock = getattr(core, "_DATA_LOCK", None)
                    saved_registry = dict(getattr(core, "SAFE_VIEW_REGISTRY", {}))
                    importlib.reload(sys.modules[mod_name])
                    if saved_cache is not None:
                        core._DATA_CACHE = saved_cache
                    if saved_lock is not None:
                        core._DATA_LOCK = saved_lock
                    if saved_registry:
                        core.SAFE_VIEW_REGISTRY.update(saved_registry)
                else:
                    importlib.reload(sys.modules[mod_name])
                if f"{mod_name}.py" in changed_files:
                    reloaded_cores.append(mod_name)
            except Exception as e:
                print(f"⚠️ [{mod_name}] 코어 모듈 리로드 오류: {e}", flush=True)

    reloaded_cogs: list[str] = []
    failed_cogs: list[str] = []
    ext_keys = [e for e in bot.extensions.keys() if e != "cogs.dashboard"]
    if "cogs.dashboard" in bot.extensions:
        ext_keys.append("cogs.dashboard")
    for ext in ext_keys:
        try:
            await bot.reload_extension(ext)
            reloaded_cogs.append(ext)
        except Exception as e:
            failed_cogs.append(f"`{ext}`: {e}")

    bot.prune_slash_tree_to_core()

    behind_cnt = pull_info["behind_cnt"]
    old_sha = pull_info["old_sha"]
    new_sha = pull_info["new_sha"]
    commits = pull_info["commits"]

    if behind_cnt == 0:
        header_line = f"ℹ️ **이미 최신 버전(`{new_sha}`)입니다.** 전체 모듈 `{len(reloaded_cogs)}개`를 다시 불러왔습니다."
    else:
        header_line = f"✅ **누적 커밋 `{behind_cnt}건` (`{old_sha}` ➔ `{new_sha}`) 다운로드 및 반영 완료!**"

    desc_lines = [
        header_line,
        f"• **브랜치:** `{pull_info['branch']}` · **변경 파일:** `{len(changed_files)}개` · **리로드된 모듈:** `{len(reloaded_cogs)}개`",
    ]
    if reloaded_cores:
        desc_lines.append(f"• **갱신된 코어:** {', '.join(f'`{m}`' for m in reloaded_cores)}")
    if commits:
        commit_fmt = _format_commit_lines_highlighted(commits, repo_url=pull_info.get("repo_url", ""), limit=15)
        desc_lines.append(f"\n**📝 이번에 반영된 GitHub 커밋 내역**\n{commit_fmt}")
    if failed_cogs:
        desc_lines.append("⚠️ **일부 모듈 리로드 오류:**\n" + "\n".join(failed_cogs[:5]))

    need_restart = force_restart or bot_py_touched
    if need_restart:
        desc_lines.append("\n🔄 **`bot.py` 본체 변경(또는 재시작 옵션)이 감지되어 잠시 후 봇 프로세스를 자동 재기동합니다.**")

    embed = discord.Embed(
        title="🚀 norosi GitHub 업데이트 반영 완료",
        description="\n".join(desc_lines)[:4000],
        color=discord.Color.from_rgb(46, 204, 113) if not failed_cogs else discord.Color.gold(),
        timestamp=datetime.datetime.now(core.KST),
    )
    return embed, need_restart


class OwnerVersionUpdateView(core.SafeView):
    """!현재버전 화면에서 대기 중인 업데이트를 원클릭 반영하거나 새로고침하는 봇 주인 전용 뷰"""

    def __init__(self, has_pending: bool = False):
        super().__init__(timeout=300)
        self.has_pending = bool(has_pending)
        self._sync_buttons()

    def _sync_buttons(self):
        self.btn_apply_update.style = discord.ButtonStyle.success if self.has_pending else discord.ButtonStyle.secondary
        self.btn_apply_update.label = "🚀 지금 업데이트 반영" if self.has_pending else "🔄 모듈 다시 불러오기"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not await bot.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ **👑 봇 주인(소유자)** 만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🚀 지금 업데이트 반영", style=discord.ButtonStyle.success, row=0)
    async def btn_apply_update(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        embed, need_restart = await execute_github_update(force_restart=False)
        self.has_pending = False
        self._sync_buttons()
        await core.safe_edit_response(interaction, embed=embed, view=self)
        if need_restart:
            await asyncio.to_thread(core.flush_pending_saves)
            await asyncio.sleep(1.5)
            os.execv(sys.executable, [sys.executable] + sys.argv)

    @discord.ui.button(label="🔄 버전 새로고침", style=discord.ButtonStyle.primary, row=0)
    async def btn_refresh_version(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        embed, info = await build_git_version_embed_and_info()
        self.has_pending = bool(info.get("behind_cnt", 0) > 0)
        self._sync_buttons()
        await core.safe_edit_response(interaction, embed=embed, view=self)


def _resolve_version_entries_sync() -> tuple[list[dict], str, str]:
    import importlib
    import subprocess
    import version_info
    importlib.reload(version_info)
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    def _run(cmd: list[str]) -> str:
        try:
            p = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=8)
            return (p.stdout or "").strip()
        except Exception:
            return ""

    head_sha = _run(["git", "rev-parse", "--short", "HEAD"]) or "unknown"
    remote_url = _run(["git", "config", "--get", "remote.origin.url"])
    clean_repo_url = ""
    if remote_url:
        u = remote_url.strip()
        if u.startswith("git@github.com:"):
            u = "https://github.com/" + u[len("git@github.com:"):]
        if u.endswith(".git"):
            u = u[:-4]
        if u.startswith("https://github.com/"):
            clean_repo_url = u

    entries: list[dict] = []
    seen_shas: set[str] = set()
    for raw_e in getattr(version_info, "VERSION_HISTORY", []):
        if not isinstance(raw_e, dict):
            continue
        e = dict(raw_e)
        c_sha = str(e.get("commit") or "").strip()
        if not c_sha or c_sha.upper() == "HEAD":
            c_sha = head_sha
            e["commit"] = c_sha
        seen_shas.add(c_sha[:7])
        entries.append(e)

    # version_info.py에 아직 수동 기재되지 않은 최근 Git 커밋도 누락 없이 자동 보완
    git_log_raw = _run(["git", "log", "-n", "12", "--format=%h|%cs|%s"])
    for ln in git_log_raw.splitlines():
        parts = ln.split("|", 2)
        if len(parts) != 3:
            continue
        g_sha, g_date, g_subj = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if g_sha[:7] in seen_shas:
            continue
        seen_shas.add(g_sha[:7])
        diff_stat = _run(["git", "show", "--stat", "--oneline", g_sha])
        stat_lines = [s.strip() for s in diff_stat.splitlines()[1:] if s.strip()][:6]
        entries.append({
            "commit": g_sha,
            "date": g_date,
            "title": g_subj,
            "added": [],
            "changed": [f"`{sl}`" for sl in stat_lines] if stat_lines else [g_subj],
            "security": [],
        })
    return entries, head_sha, clean_repo_url


class OwnerVersionChangelogView(core.SafeView):
    """봇 주인 전용 !버전 — GitHub 커밋 기준 버전별 추가/수정/보안 변경사항 열람 뷰"""

    def __init__(self, entries: list[dict] | None = None, head_sha: str = "", repo_url: str = "", index: int = 0):
        super().__init__(timeout=600)
        if not entries:
            entries, head_sha, repo_url = _resolve_version_entries_sync()
        self.entries = entries or []
        self.head_sha = head_sha or get_local_head_short_sha()
        self.repo_url = repo_url
        self.index = max(0, min(index, max(0, len(self.entries) - 1)))
        self._rebuild_items()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if msg and msg.embeds:
            title = getattr(msg.embeds[0], "title", "") or ""
            for i, e in enumerate(self.entries):
                sha = str(e.get("commit") or "")[:7]
                if sha and f"[{sha}]" in title:
                    self.index = i
                    self._rebuild_items()
                    break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not await bot.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ 이 화면은 **👑 봇 주인(소유자)** 만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    def _rebuild_items(self):
        self.clear_items()
        if self.entries:
            opts = []
            for i, e in enumerate(self.entries[:25]):
                sha = str(e.get("commit") or "-")[:7]
                is_cur = (sha == self.head_sha[:7])
                lbl = f"[{sha}] {'(현재 반영) ' if is_cur else ''}{str(e.get('title') or '')}"[:95]
                opts.append(
                    discord.SelectOption(
                        label=lbl,
                        value=str(i),
                        description=f"날짜: {e.get('date', '-')}"[:95],
                        default=(i == self.index),
                    )
                )
            sel = discord.ui.Select(
                placeholder="🔖 열람할 커밋 버전을 선택하세요...",
                options=opts,
                row=0,
                custom_id="norosi:OwnerVersionChangelogView:select",
            )
            sel.callback = self._on_select
            self.add_item(sel)

        prev_b = discord.ui.Button(
            label="◀ 최신 쪽",
            style=discord.ButtonStyle.secondary,
            disabled=(self.index <= 0),
            row=1,
            custom_id="norosi:OwnerVersionChangelogView:prev",
        )
        prev_b.callback = self._on_prev
        self.add_item(prev_b)

        next_b = discord.ui.Button(
            label="이전 커밋 ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(self.index >= len(self.entries) - 1),
            row=1,
            custom_id="norosi:OwnerVersionChangelogView:next",
        )
        next_b.callback = self._on_next
        self.add_item(next_b)

        cmp_b = discord.ui.Button(
            label="🐙 GitHub 동기화 비교",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="norosi:OwnerVersionChangelogView:cmp",
        )
        cmp_b.callback = self._on_compare
        self.add_item(cmp_b)

    def build_embed(self) -> discord.Embed:
        if not self.entries:
            return discord.Embed(title="📜 버전 변경 기록 없음", description="기록된 버전 내역이 없습니다.", color=discord.Color.greyple())
        cur = self.entries[self.index]
        sha = str(cur.get("commit") or "unknown")[:7]
        sha_link = f"[**`[{sha}]`**]({self.repo_url}/commit/{sha})" if self.repo_url else f"**`[{sha}]`**"
        is_active = (sha == self.head_sha[:7])
        active_badge = " · 🟢 **현재 봇 반영 버전**" if is_active else f" · (현재 반영: `{self.head_sha}`)"

        lines = [
            f"• **커밋 버전:** {sha_link}  ·  📅 `{cur.get('date', '-')}`{active_badge}",
            f"• **요약:** **{cur.get('title', '-')}**",
            "━━━━━━━━━━━━━━━━",
        ]
        added = cur.get("added") or []
        changed = cur.get("changed") or []
        sec = cur.get("security") or []
        if added:
            lines.append("**✨ 추가된 기능**")
            lines.extend(f"• {x}" for x in added)
            lines.append("")
        if changed:
            lines.append("**🛠️ 수정 및 개선 사항**")
            lines.extend(f"• {x}" for x in changed)
            lines.append("")
        if sec:
            lines.append("**🛡️ 보안 강화 내역**")
            lines.extend(f"• {x}" for x in sec)
            lines.append("")

        embed = discord.Embed(
            title=f"📜 norosi 버전 변경 기록 — [{sha}] ({self.index + 1}/{len(self.entries)})",
            description="\n".join(lines).strip()[:4000],
            color=discord.Color.from_rgb(0, 204, 221) if is_active else discord.Color.blurple(),
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed

    async def _on_select(self, interaction: discord.Interaction):
        val = (interaction.data or {}).get("values", ["0"])[0]
        if str(val).isdigit():
            self.index = max(0, min(int(val), len(self.entries) - 1))
        self._rebuild_items()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        self.index = max(0, self.index - 1)
        self._rebuild_items()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.index = min(len(self.entries) - 1, self.index + 1)
        self._rebuild_items()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_compare(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        emb, info = await build_git_version_embed_and_info()
        v = OwnerVersionUpdateView(has_pending=(info.get("behind_cnt", 0) > 0))
        await interaction.followup.send(embed=emb, view=v, ephemeral=True)


@bot.command(name="버전")
async def version_changelog_command(ctx: commands.Context, target_commit: Optional[str] = None):
    """[봇 주인 전용] version_info.py 및 GitHub 커밋 기준으로 각 버전에 무엇이 추가·수정되었는지 확인합니다."""
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **👑 봇 주인(소유자)** 만 사용할 수 있습니다.", delete_after=5)
        return
    entries, head_sha, repo_url = await asyncio.to_thread(_resolve_version_entries_sync)
    init_idx = 0
    if target_commit:
        q = target_commit.strip().lower().strip("[]`")
        for i, e in enumerate(entries):
            if str(e.get("commit") or "").lower().startswith(q):
                init_idx = i
                break
    view = OwnerVersionChangelogView(entries=entries, head_sha=head_sha, repo_url=repo_url, index=init_idx)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="현재버전")
async def current_version_command(ctx: commands.Context):
    """[봇 주인 전용] 현재 봇에 반영되어 실행 중인 Git 커밋과 GitHub 최신 커밋 목록을 비교합니다."""
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **👑 봇 주인(소유자)** 만 사용할 수 있습니다.", delete_after=5)
        return
    embed, info = await build_git_version_embed_and_info()
    view = OwnerVersionUpdateView(has_pending=(info.get("behind_cnt", 0) > 0))
    await ctx.send(embed=embed, view=view)


@bot.command(name="업데이트")
async def apply_github_updates_command(ctx: commands.Context, *args):
    """[봇 주인 전용] GitHub 원격 저장소에 쌓인 커밋을 가져와 봇에 일괄 반영합니다."""
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **👑 봇 주인(소유자)** 만 사용할 수 있습니다.", delete_after=5)
        return
    arg_str = " ".join(args).strip().lower()
    force_restart = any(k in arg_str for k in ("재시작", "restart", "리부트", "reboot"))
    status_msg = await ctx.send("⏳ **GitHub 원격 저장소(`origin`)에서 누적된 업데이트를 확인하고 반영하는 중...**")
    embed, need_restart = await execute_github_update(force_restart=force_restart)
    await status_msg.edit(content=None, embed=embed)
    if need_restart:
        await asyncio.to_thread(core.flush_pending_saves)
        await asyncio.sleep(1.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)


# ==========================================
# 봇 슬래시 명령어 동기화 마스터 (!sync)
# ==========================================
@bot.command(name="sync")
async def sync_guild_command(ctx: commands.Context, *args):
    if not await bot.is_bot_owner_user(ctx.author):
        await ctx.send("❌ 이 명령어는 **봇주**(Bot Owner)만 사용할 수 있습니다.", delete_after=5)
        return

    mode = " ".join(args).strip().lower() if args else ""
    g_name = ctx.guild.name if ctx.guild else "개인 DM"

    status_msg = await ctx.send(f"⏳ **[{g_name}]** 슬래시 명령어 동기화 처리 중...")

    if any(k in mode for k in ("리로드", "reload", "새로고침", "refresh")):
        ext_keys = [e for e in bot.extensions.keys() if e != "cogs.dashboard"]
        if "cogs.dashboard" in bot.extensions:
            ext_keys.append("cogs.dashboard")
        for ext in ext_keys:
            try:
                await bot.reload_extension(ext)
            except Exception as e:
                print(f"⚠️ [{ext}] 리로드 실패: {e}", flush=True)

    bot.prune_slash_tree_to_core()

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
                f"• 🏠 현재 서버({g_name}) 즉시 등록: **`{guild_cnt}개`** (`/설정`, `/도움말`, `/후원`)\n"
                f"• 💡 길드 전용 즉시 동기화 모드로 반영되었습니다."
            )
            title_text = f"⚡ [{g_name}] 길드 슬래시 명령어 동기화 완료!"
            desc_lead = f"🎉 **현재 서버에 길드 전용 슬래시 명령어 총 `{guild_cnt}개`가 등록되었습니다!**"
        else:
            reg_status = (
                f"• 🌐 글로벌 전역 명령어: **`{len(synced_global)}개`** (`/설정`, `/도움말`, `/후원`)\n"
                f"• 🧹 길드 캐시 정리: 중복 및 구 슬래시 커맨드 완전 제거 완료"
            )
            title_text = f"⚡ [{g_name}] 글로벌 슬래시 명령어 동기화 완료!"
            desc_lead = f"🎉 **글로벌 슬래시 명령어 총 `{len(synced_global)}개`(`/설정`, `/도움말`, `/후원`)로 단일화 동기화되었습니다!**"

        embed = discord.Embed(
            title=title_text,
            description=(
                f"{desc_lead}\n\n"
                "📊 **등록 상태:**\n"
                f"{reg_status}\n\n"
                "━━━━━━━━━━━━━━━━\n"
                "💡 **핵심 슬래시 명령어 3종 안내**\n"
                "• `/설정` : 일반 · 고급 · 미니게임 · 개인 4대 분류 통합 설정 대시보드\n"
                "• `/도움말` : 전체 기능의 `/설정` 경로 및 권한별 가독성 가이드\n"
                "• `/후원` : norosi 24시간 서버 운영비 후원 안내"
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
                raise
            except Exception as e:
                print(f"⚠️ 봇 연결 예외 발생 (15초 후 재시도): {e}", flush=True)
                traceback.print_exc()
                await _cleanup_bot_session()
                await asyncio.sleep(15)
            else:
                # 정상 종료 시 세션 정리 후 루프 탈출
                await _cleanup_bot_session()
                break
    finally:
        await _cleanup_bot_session()
        if getattr(bot, "_web_runner", None) is not None:
            try:
                await bot._web_runner.cleanup()
            except Exception:
                pass
            bot._web_runner = None
            bot._web_started = False


if __name__ == "__main__":
    if sys.platform != "win32":
        try:
            import uvloop
            uvloop.install()
        except Exception:
            pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
