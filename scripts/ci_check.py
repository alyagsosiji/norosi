#!/usr/bin/env python3
"""
norosi 배포 전 자동 검증(CI) 스크립트 (네트워크 무의존 · 초고속 실행)
- 전체 .py 구문 컴파일(py_compile)
- AST 정적 검사: threading.Lock-across-await 데드락, 모달/버튼/셀렉트 길이 초과
- bot.py <-> deploy/force_resync.py 18개 코그 목록 일치 확인
- 핵심 보안 가드 회귀 테스트 (SSRF 차단, 시크릿 마스킹, 웹훅 Fail-Closed, AllowedMentions)
"""
import ast
import asyncio
import os
import pathlib
import py_compile
import sys
from unittest.mock import AsyncMock, MagicMock

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def check_syntax_and_ast() -> None:
    files = (
        sorted(BASE_DIR.glob("*.py"))
        + sorted((BASE_DIR / "cogs").glob("*.py"))
        + sorted((BASE_DIR / "deploy").glob("*.py"))
        + sorted((BASE_DIR / "scripts").glob("*.py"))
    )
    errors: list[str] = []
    for p in files:
        py_compile.compile(str(p), doraise=True)
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(p))

        for node in ast.walk(tree):
            # 1. threading.Lock held across await (deadlock)
            if isinstance(node, ast.With):
                for item in node.items:
                    ctx = ast.unparse(item.context_expr)
                    if "_DATA_LOCK" in ctx or "_LOCK" in ctx:
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Await):
                                errors.append(f"LOCK_ACROSS_AWAIT {p.name}:{node.lineno}")
                                break

            # 2. Discord UI literal length limits
            if isinstance(node, ast.ClassDef):
                for kw in node.keywords:
                    if kw.arg == "title" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        if len(kw.value.value) > 45:
                            errors.append(f"MODAL_TITLE_GT45 {p.name}:{node.lineno} ({len(kw.value.value)})")
            if isinstance(node, ast.Call):
                fn = ast.unparse(node.func)
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        val = kw.value.value
                        if fn.endswith("TextInput") and kw.arg == "label" and len(val) > 45:
                            errors.append(f"TEXTINPUT_LABEL_GT45 {p.name}:{node.lineno}")
                        if fn.endswith("TextInput") and kw.arg == "placeholder" and len(val) > 100:
                            errors.append(f"TEXTINPUT_PH_GT100 {p.name}:{node.lineno}")
                        if (fn.endswith("Button") or fn.endswith(".button")) and kw.arg == "label" and len(val) > 80:
                            errors.append(f"BUTTON_LABEL_GT80 {p.name}:{node.lineno}")
                        if fn.endswith("SelectOption") and kw.arg in ("label", "value", "description") and len(val) > 100:
                            errors.append(f"SELECTOPT_GT100 {p.name}:{node.lineno}")

    if errors:
        raise AssertionError("AST checks failed:\n  " + "\n  ".join(errors))
    print(f"[CI 1/3] Syntax & AST checks passed ({len(files)} files, 0 issues)")


def check_cog_list_sync() -> None:
    def _extract(path: pathlib.Path, var_name: str) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == var_name:
                        return [elt.value for elt in node.value.elts]
        raise RuntimeError(f"{var_name} not found in {path}")

    bot_cogs = _extract(BASE_DIR / "bot.py", "ext_list")
    resync_cogs = _extract(BASE_DIR / "deploy" / "force_resync.py", "ALL_COG_EXTENSIONS")
    assert bot_cogs == resync_cogs, f"Cog list mismatch: {bot_cogs} vs {resync_cogs}"
    print(f"[CI 2/3] Cog list sync passed ({len(bot_cogs)} cogs)")


def check_security_guards() -> None:
    import bot
    import core

    # 1. Playlist SSRF guard
    assert core.is_playlist_url("http://127.0.0.1:10000/sets/?soundcloud.com") == (False, "")
    assert core.is_playlist_url("http://169.254.169.254/playlist/?youtube.com") == (False, "")
    assert core.is_playlist_url("https://www.youtube.com/playlist?list=PL123456") == (True, "YouTube")

    # 2. Secret redaction
    os.environ["GITHUB_WEBHOOK_SECRET"] = "ci_dummy_webhook_secret_999"
    os.environ["SIGNING_KEY"] = "ci_dummy_signing_key_888"
    out = core.redact_secrets("leak ci_dummy_webhook_secret_999 ci_dummy_signing_key_888")
    assert "ci_dummy_webhook_secret_999" not in out and "ci_dummy_signing_key_888" not in out

    # 3. GitHub webhook fail-closed + AllowedMentions(everyone=False)
    async def _test_bot():
        os.environ["GITHUB_WEBHOOK_SECRET"] = ""
        b = bot.NorosiBot()
        assert b.allowed_mentions.everyone is False
        req = MagicMock()
        req.read = AsyncMock(return_value=b"{}")
        req.headers = {}
        resp = await b.handle_github_webhook(req)
        assert resp.status == 503, f"Expected 503 fail-closed, got {resp.status}"

    asyncio.run(_test_bot())

    # 4. Pillow decompression bomb cap + filename sanitizer + URL basic-auth redaction + version_info schema
    from PIL import Image
    import sns_embed_core
    import version_info
    assert Image.MAX_IMAGE_PIXELS and Image.MAX_IMAGE_PIXELS <= 30_000_000
    assert core.sanitize_attachment_filename("../../etc/passwd") == "etc_passwd"
    assert "secretpass" not in core.redact_secrets("https://user:secretpass@github.com/org/repo.git")
    assert hasattr(sns_embed_core, "_safe_session_get_bytes")
    assert isinstance(version_info.VERSION_HISTORY, list) and len(version_info.VERSION_HISTORY) >= 1
    print("[CI 3/3] Security guard regression checks passed")


def check_discord_markdown_integrity() -> None:
    import re
    import unicodedata

    def _is_punct(ch: str) -> bool:
        return bool(ch) and (unicodedata.category(ch).startswith("P") or ch in "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

    def _is_ws(ch: str) -> bool:
        return (not ch) or ch.isspace()

    files = sorted(BASE_DIR.glob("*.py")) + sorted((BASE_DIR / "cogs").glob("*.py"))
    errors: list[str] = []

    for p in files:
        rel = str(p.relative_to(BASE_DIR))
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=rel)
        parent_map = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parent_map[id(child)] = parent

        def _is_str_expr(n):
            return (
                (isinstance(n, ast.Constant) and isinstance(n.value, str))
                or isinstance(n, ast.JoinedStr)
                or (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and (_is_str_expr(n.left) or _is_str_expr(n.right)))
            )

        def _flatten(n) -> str:
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                return n.value
            if isinstance(n, ast.JoinedStr):
                return "".join(v.value if (isinstance(v, ast.Constant) and isinstance(v.value, str)) else "V" for v in n.values)
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                return _flatten(n.left) + _flatten(n.right)
            return "V"

        for node in ast.walk(tree):
            if not _is_str_expr(node):
                continue
            parent = parent_map.get(id(node))
            if parent is not None and _is_str_expr(parent):
                continue
            if isinstance(parent, ast.Expr) and isinstance(node, ast.Constant):
                continue
            if isinstance(parent, ast.Call):
                fn = parent.func.attr if isinstance(parent.func, ast.Attribute) else (parent.func.id if isinstance(parent.func, ast.Name) else "")
                if fn in ("compile", "sub", "search", "match", "findall", "finditer", "split", "fullmatch"):
                    continue
            s = _flatten(node)
            if not s or not re.search(r"[가-힣]", s):
                continue
            ln = getattr(node, "lineno", 0)
            nf = re.sub(r"```[\s\S]*?```", " ", s).replace("```", "")
            if re.search(r"(?<!`)``(?!`)", nf):
                errors.append(f"DOUBLE_BACKTICK {rel}:{ln}")
            for m in re.finditer(r"(?<!\*)\*\*([^*\n]+?)\*\*(?!\*)", nf):
                inner = m.group(1)
                b = nf[m.start() - 1] if m.start() > 0 else ""
                a = nf[m.end()] if m.end() < len(nf) else ""
                if inner[0].isspace() or inner[-1].isspace():
                    errors.append(f"BOLD_EDGE_SPACE {rel}:{ln} ({m.group(0)[:30]})")
                if b != "V" and _is_punct(inner[0]) and not (_is_ws(b) or _is_punct(b)):
                    errors.append(f"BOLD_OPEN_FLANK {rel}:{ln} ({b}{m.group(0)[:30]})")
                if a != "V" and _is_punct(inner[-1]) and not (_is_ws(a) or _is_punct(a)):
                    errors.append(f"BOLD_CLOSE_FLANK {rel}:{ln} ({m.group(0)[-30:]}{a})")

    if errors:
        raise AssertionError("Discord Markdown checks failed:\n  " + "\n  ".join(errors[:25]))
    print(f"[CI 4/4] Discord Markdown integrity checks passed ({len(files)} files, 0 issues)")


def main() -> None:
    check_syntax_and_ast()
    check_cog_list_sync()
    check_security_guards()
    check_discord_markdown_integrity()
    print("✅ ALL CI CHECKS PASSED!")


if __name__ == "__main__":
    main()
