"""
version_info.py — norosi 봇 GitHub 커밋 기준 버전 변경 기록 (봇 주인 전용 `!버전` 열람용)

새 업데이트 커밋을 올릴 때마다 VERSION_HISTORY 맨 앞에 항목을 추가해 무엇이 추가·수정·보안 강화되었는지 기록합니다.
각 항목의 `commit` 필드가 비어 있거나 "HEAD"이면 런타임에 실제 Git 커밋 해시를 자동으로 매칭합니다.
"""

from __future__ import annotations
from typing import Any

VERSION_HISTORY: list[dict[str, Any]] = [
    {
        "commit": "HEAD",
        "date": "2026-11-27",
        "title": "Discord 10062 Unknown Interaction 경고 로그 스팸 차단 및 자동 메시지 폴백 보강",
        "fixed": [
            "`core.py` (`safe_defer`, `safe_send_response`, `safe_edit_response`, `reconstruct_safe_view`): 디스코드 게이트웨이·네트워크 지연으로 3초 인터랙션 토큰이 만료(`404 Not Found / 10062: Unknown interaction`)되었을 때 경고 로그 스팸을 남기지 않고 만료 플래그(`_norosi_expired_10062`)를 기록한 뒤, 후속 `safe_edit_response` / `safe_send_response`에서 실패할 인터랙션 웹훅 호출을 건너뛰고 즉시 채널 메시지 직접 수정(`message.edit`) 또는 채널 전송으로 폴백하도록 개선",
            "`cogs/gacha.py` (`DuplicateConvertConfirmView`): 변환 완료 시 `edit_original_response` 직접 호출 대신 `core.safe_edit_response`를 경유하도록 통일하고, 재시작 후 뷰 복원(`reconstruct_safe_view`) 시에도 `preview_duplicate_cards` 데이터를 즉시 복구하도록 보강",
        ],
    },
    {
        "commit": "0a5ba57",
        "date": "2026-11-27",
        "title": "프로세카 중복 카드 변환 다중 선택·프리셋 일괄 선택 지원 및 산리오 콜라보·카드명 잘림 완벽 해결",
        "added": [
            "`core.py` (`preview_duplicate_cards`, `execute_duplicate_card_conversion`) & `cogs/gacha.py` (`DuplicateConvertConfirmView`): 중복 카드 변환소에서 **원하는 카드만 여러 개 동시에 다중 선택(`card_multi_select`)** 하거나 **필터·프리셋(`★1~2만`, `★1~3만`, `✦MR.5 MAX만`, `유닛별`)**, **`[☑️ 현재 페이지 전체선택]`**, **`[✨ 전체 일괄선택]`**, **`[💎 선택 카드 변환]`**, **`[🚀 전체 일괄 변환]`** 기능으로 자유롭게 변환할 수 있도록 업그레이드",
        ],
        "fixed": [
            "`cogs/gacha.py` (`MasterRankView`, `MyInventoryView`, `GachaCeilingExchangeView`, `SelectListGachaView`, `DuplicateConvertConfirmView`): 산리오 콜라보 등 카드 칭호(`feat. 한교동` ➔ `feat. 한교`)와 캐릭터 이름이 `[:6]`/`[:8]`/`[:30]` 슬라이싱으로 줄임말처럼 잘리던 문제를 전수 해결하여 최대 100자까지 전체 표기되도록 개선",
        ],
    },
    {
        "commit": "d498599",
        "date": "2026-11-27",
        "title": "프로세카 드롭다운 캐릭터 이름 전체 표시 및 잘림 방지",
        "changed": [
            "`cogs/gacha.py` (`MasterRankView`, `MyInventoryView`, `CardTradeView`, `EncyclopediaView`, `WardrobeView`): 캐릭터·카드 선택 드롭다운에서 성을 생략(`.split()[-1]`)하거나 짧은 글자 수(`[:26]`, `[:32]`, `[:34]`, `[:36]`)로 잘라내던 처리를 제거하고, **풀네임(`요이사키 카나데`, `호시노 이치카` 등)을 앞쪽에 배치하여 최대 100자까지 온전히 표시**되도록 개선",
        ],
    },
    {
        "commit": "3ec1429",
        "date": "2026-11-27",
        "title": "프로세카 마스터 랭크 MAX 카드 앞장 우선 정렬 · 앞장/뒷장 바로가기 버튼 추가",
        "changed": [
            "`cogs/gacha.py` (`MasterRankView`): 마스터 랭크 `MAX(✦MR.5)` 달성 시 카드가 목록 맨 뒤(뒷장)로 밀려나지 않고 **마스터 랭크 높은 순(`✦MR.5 ➔ MR.0`)으로 맨 앞장**에 위치하도록 정렬 기준 개선",
            "`cogs/gacha.py` (`MasterRankView`): 하단 페이지 이동 바에 **`[⏮️ 앞장]`** 과 **`[뒷장 ⏭️]`** 원클릭 이동 버튼 추가 (`[⏮️ 앞장] [◀ 이전] [📄 현재/전체] [다음 ▶] [뒷장 ⏭️]`)",
        ],
    },
    {
        "commit": "648a3ef",
        "date": "2026-11-27",
        "title": "웹훅 아바타 자동 복구 시 채팅 두 개 생겼다 사라지는 깜빡임 현상 완벽 해결",
        "fixed": [
            "`cogs/emoji_upscale.py` (`send_webhook_with_verified_avatar`, `prewarm_webhook_avatar_cache`, `_sync_webhook_avatar_in_place`): Discord 웹훅이 `avatar_url`을 드롭(`meta_dropped(avatar=None)`)할 때 새 웹훅 메시지를 먼저 또 보내고 기존 메시지를 삭제하던 사후 재전송 방식을 제거하고, 항상 **단 1회만 전송**하며 백그라운드에서 조용히 `direct_upload` 전략 전환 및 웹훅 아바타 동기화를 수행하도록 개선 (채팅이 두 개로 보였다가 하나로 사라지는 깜빡임 및 경고 로그 스팸 원천 차단)",
        ],
    },
    {
        "commit": "82da301",
        "date": "2026-11-26",
        "title": "프로세카 전역 픽업 배너 설정 영구 보존 · 봇주인 전용 권한 통일 · 수동 픽업 개선",
        "fixed": [
            "`core.py` (`_merge_local_and_remote` & `DEFAULT_CONFIG`): 로컬↔Firebase 병합 대상에 `gacha_pickup`(`updated_at` 타임스탬프 기준)을 추가하여 봇주인이 설정한 프로세카 전역 픽업 배너(`normal`/`fes`/`birthday`), 이벤트 연동, 유닛·캐릭터 픽업이 원격 DB 병합 시 초기화되던 현상 해결",
            "`cogs/gacha.py`: 가챠 결과창(`GachaPullAgainView`), 리세마라 연습창(`RerollSimulatorView`), 확률표(`ProsekaRatePaginationView`)의 배너 드롭다운을 **봇주인 전용 전역 배너 변경**으로 통일하여 드롭다운 변경 시에도 `gacha_pickup['banner_type']`에 즉시 영구 저장되고 재뽑기 시 이전 뷰의 배너 상태로 되돌아가지 않도록 수정",
            "`core.py` & `cogs/dashboard.py`: 수동 픽업 모달(`DashboardSekaiOwnerPickupModal`)에서 캐릭터 약칭(`카나데` ➔ `요이사키 카나데`) 및 다중 캐릭터(`카나데, 마후유`) 자동 매칭을 지원하고, 유닛/캐릭터를 비운 채 배너만 변경할 때 기존 이벤트·유닛·캐릭터 픽업이 증발하지 않고 유지되도록 개선",
        ],
        "added": [
            "`/설정` (`⚙️ 고급 4p` ➔ `🎯 [봇주인] 프로세카 글로벌 픽업 제어판`): 페스/생일 배너에서 일반 배너로 기존 픽업을 유지한 채 즉시 돌아올 수 있는 **`[🌟 일반 픽업 배너 (★4 3%)]`** 원클릭 버튼 추가",
        ],
        "security": [
            "`cogs/gacha.py` & `cogs/dashboard.py`: 프로세카 픽업 및 배너 변경·선택의 모든 경로(`set_pickup_cmd`, `DashboardSekaiOwnerPickupModal`, `GachaPullAgainView.banner_select`, `RerollSimulatorView.sim_banner_select`, `ProsekaRatePaginationView.banner_select`, `proseka_rate_list_cmd`)를 **봇주인(Bot Owner) 전용**으로 엄격히 제한",
        ],
    },
    {
        "commit": "8db19a9",
        "date": "2026-11-26",
        "title": "다중 자동역할 지급 · Firebase 즉시동기화 · 채널/역할 삭제 자동정리 등 11대 기능·안정성 업그레이드",
        "added": [
            "`👋 환영/작별 배너 설정`: 신규 멤버 입장 시 **여러 개의 역할(최대 10개) 동시 자동 지급** 지원, `[🚪 작별 카드 미리보기]` 버튼 및 한글/영문 색상 프리셋(`블루·그린·골드·핑크·퍼플·레드·민트·하늘·주황`) 입력 지원",
            "`⏳ 카운트다운 스튜디오 & 카드`: 스튜디오 내 **개별 타이머 선택 관리(`+10분 연장` / `즉시 취소`) 드롭다운**, 카운트다운 카드 **`[👥 알림 대기 명단]` 버튼** 및 **시각적 진행률 게이지 바(`████░░░░░░ 40%`)** 추가",
            "`🔊 임시 음성방`: 등록된 자동생성(트리거) 채널 **개별 제거 드롭다운**, **봇 필수 권한(`채널 관리` · `멤버 이동`) 실시간 진단**, 방장 퇴장 시 남은 멤버에게 **`[👑 방장 인계받기]` 안내 자동 발송** 추가",
            "`/설정` (`⚙️ 고급 4p` ➔ `💾 백업 & 동기화`): **`[🔥 Firebase 연결점검 & 즉시동기화]`** 원클릭 진단·푸시 버튼 추가",
        ],
        "changed": [
            "`/설정` 통합 기능 검색(`search_dashboard_features`): 3단계 세부 제어판(`sub_mode` 24종, 약 150개 하위 버튼)까지 검색 범위 확장",
            "`cogs/community.py` & `cogs/tickets.py`: 디스코드에서 채널·카테고리·스레드·역할 직접 삭제 시 1:1 티켓, 임시음성방, 고정메시지, 카운트다운, 릴레이소설, 환영/작별, 비상방어 DB 유령 설정 자동 정리(`on_guild_channel_delete` / `on_raw_thread_delete` / `on_guild_role_delete`)",
            "`core.py` & `community_core.py`: 로컬↔Firebase 병합 시 최신 수정 시각(`updated_at`) 우선 보존 및 종료 후 7일이 경과한 카운트다운·예약 이벤트 자동 청소(GC), 고정메시지 목록 조회 시 삭제된 채널 유령 데이터 자동 정리 적용",
        ],
    },
    {
        "commit": "5c6263a",
        "date": "2026-11-26",
        "title": "전 기능 UI 상호작용 · 영구 버튼 복구 · 핫리로드 무결성 전면 점검 및 수정",
        "changed": [
            "`core.py` & `bot.py`: 154개 전체 `SafeView`의 890여 개 버튼·드롭다운 전수 검증 — 단축 별칭 10종(`Help`, `AttRank`, `DDayChannelSetup`, `ProsekaRate`, `GenshinInv`, `HSRInv` 등) 및 커뮤니티 뷰 5종(`TempVoiceControlView`, `CountdownCardView`, `RelayNovelView`, `RaidAlertControlView`, `LinkCleanupView`)의 재시작 후 버튼 복구 100% 보장",
            "`bot.py`: `!업데이트` 핫리로드 시 14개 전체 코어 모듈 갱신, `core` 리로드 시 `SAFE_VIEW_REGISTRY` 보존, `cogs.dashboard` 최후순위 리로드 및 프로세스 재기동(`os.execv`) 직전 로컬·Firebase 대기 데이터 즉시 플러시 적용",
            "`cogs/community.py`: 임시 음성방 잠금·숨김 시 현재 방 안에 접속 중인 멤버들의 음성·채팅 권한이 차단되지 않도록 보호하고, 방장 인계 시 이전 방장의 채널 관리 권한을 회수하도록 개선",
            "`cogs/community.py`: 카운트다운 스튜디오에서 `[🛑 진행 중 타이머 전체 취소]` 실행 시 채널에 게시된 카운트다운 카드 메시지도 즉시 `[취소됨]` 상태로 갱신·비활성화되도록 개선",
            "`cogs/dashboard.py` & `bot.py`: `/설정` 통합 검색 결과 뷰(`DashboardSearchResultView`), 카운트다운 스튜디오(`CountdownStudioView`), `!버전` 변경기록 뷰(`OwnerVersionChangelogView`)의 메시지 기반 상태 복원(`_restore_from_message`) 보강",
        ],
    },
    {
        "commit": "176bf3d",
        "date": "2026-11-26",
        "title": "서버 관리자 기능 3종 추가·강화 (환영/작별 배너 · 임시음성방 카테고리 지정 · 실시간 카운트다운)",
        "added": [
            "`👋 환영/작별 배너 설정` (`/설정` ➔ `⚙️ 고급 3p`): 신규 멤버 입장·퇴장 시 800×260 PNG 배너 카드 자동 생성·발송, 입장 자동 역할 부여, 문구·색상 커스텀 및 실시간 미리보기 테스트 추가",
            "`⏳ 실시간 카운트다운 스튜디오` (`/설정` ➔ `⚙️ 고급 1p`): 내전·방송·시험·이벤트용 실시간 카운트다운 임베드 발행 (`10분/30분/1시간/2시간` 프리셋 및 시각 지정, 멤버 `[🔔 시작 알림 받기]` 구독, 관리자 `[+10분 연장]` · `[취소]`, 종료 시각 자동 알림)",
            "`🔊 임시음성방 설정` (`/설정` ➔ `⚙️ 고급 2p`): 카테고리 지정 드롭다운(`1️⃣`), 지정 카테고리에 자동생성 채널 개설 버튼, `[📁 새 카테고리+자동채널 생성]` 모달 및 다중 트리거 채널 지원 추가",
        ],
        "changed": [
            "임시 음성방의 카테고리 지정 및 자동생성 채널 추가·초기화 권한을 **서버 관리자(Administrator)** 전용으로 제한하고, 임시방 생성 시 지정 카테고리를 최우선 적용",
        ],
    },
    {
        "commit": "f37d0aa",
        "date": "2026-11-26",
        "title": "Firebase 공식 서비스 계정(OAuth2) 인증 지원 · 종료 시 원격 즉시 동기화",
        "added": [
            "외부 패키지 설치 없이 Google 서비스 계정 비공개 키(`FIREBASE_CREDENTIALS`)로 OAuth2 토큰을 자동 발급·갱신하는 Firebase 공식 인증 지원",
            "`.gitignore`에 Firebase 서비스 계정 키 패턴(`firebase-key.json`, `*-firebase-adminsdk-*.json`) 추가",
            "`!봇상태`에 Firebase 인증 방식(`서비스 계정` / `시크릿`) 표시 추가",
        ],
        "changed": [
            "봇 종료/재시작(`!업데이트 재시작`) 시 로컬뿐 아니라 Firebase에도 마지막 변경사항을 즉시 동기화하도록 보강",
            "Firebase 읽기/쓰기 타임아웃을 `5초` ➔ `15초`로 여유화하고 `norosi-default-rtdb` URL 차단 조건 제거",
        ],
    },
    {
        "commit": "a0f2c1f",
        "date": "2026-11-26",
        "title": "/설정 홈 하단 오늘 출석하기 버튼 제거",
        "changed": [
            "`/설정` 홈 화면 맨 아래에 표시되던 `[📅 오늘 출석하기]` 원클릭 버튼 제거",
        ],
    },
    {
        "commit": "ab995e0",
        "date": "2026-11-26",
        "title": "보안 6종 전면 강화 · 가독성/편의성 9종 마무리 · !버전 변경기록 시스템 도입",
        "added": [
            "봇 주인 전용 `!버전 [커밋ID]` 명령어 및 `version_info.py` 커밋별 상세 변경 기록 뷰(페이지 탐색 지원) 추가",
            "`/설정` 홈 화면에서 미출석 시 `[📅 오늘 출석하기]` 원클릭 버튼 자동 표시",
            "`❤️ 내 애청곡 보관함`에 `[▶️ 음성방 전체 재생]` 버튼 및 현재 페이지 곡 삭제 드롭다운 추가",
            "`🎮 게임 파티 모집` 보드에 방장 전용 `[📣 파티원 호출]` 알림 버튼 추가",
            "`🎂 멤버 생일 전광판` 상단에 오늘 생일 / 다음 가장 가까운 생일 주인공 하이라이트 배너 추가",
        ],
        "changed": [
            "`/도움말` 슬래시 옵션 이름을 `카테고리` · `검색` 한국어로 통일",
            "모바일 화면 줄바꿈 깨짐 방지를 위해 전체 파일의 가로 구분선을 16자(`━━━━━━━━━━━━━━━━`)로 통일",
            "열람·선택·검색 뷰 20여 종의 만료 시간을 `180초` ➔ `600초(10분)`로 연장",
            "`/설정` 카테고리·검색 결과 화면의 중복 페이지 표기 및 불필요한 버튼 반복 푸터 정리",
        ],
        "security": [
            "`sns_embed_core.py`: 매 리다이렉트 홉마다 공인 IP 재검증을 수행해 `302 Redirect` 경유 SSRF 우회 원천 차단",
            "`core.py` & `cogs/stats.py`: DB 내 `emote_cdn_signing_key` 및 URL 인증정보 로그 마스킹 + 전체 DB 백업 JSON에서 서명키 제외",
            "`bot.py`: 내장 웹서버 본문 `2MB` 상한(`413`) 및 `X-Content-Type-Options` · `X-Frame-Options` 보안 헤더 미들웨어 적용",
            "`core.py`: Pillow `Image.MAX_IMAGE_PIXELS = 25,000,000` 상한으로 초고해상도 이미지 압축 폭탄(OOM) 차단 및 첨부 파일명 정규화",
        ],
    },
    {
        "commit": "bac6f09",
        "date": "2026-11-26",
        "title": "전 기능 편의성·기능성 대폭 강화 및 전체 한국어 문구 자연스럽게 다듬기",
        "added": [
            "`!현재버전` 화면 내 `[🚀 지금 업데이트 반영]` 원클릭 버튼 및 `!봇상태` 내 `[🔖 버전 비교]` 버튼 연동",
            "프로세카(`스킵`·`3성일러`) / 원신(`스킵`) / 스타레일(`스킵`) 개인 설정 프로필 자동 저장",
            "원신·스타레일 가챠 결과에 `[⚔️ 파티 편성]` · `[📖 도감]` 바로가기 추가",
            "프로세카 보관함 카드 상세 뷰에 `[⚡ MAX 레벨 강화]` · `[🏆 MR 돌파]` 즉시 연동 추가",
            "낚시 포획 직후 `[🔒 잠금]` 원클릭 보호 버튼 및 `[📜 퀘스트]` 바로가기 추가",
            "일일 루틴 `[📅 즉시 출석체크]` 및 주간미션·환전소·쇼케이스·복권·칭호상점 양방향 이동 버튼 추가",
            "무드 라디오 `[⏭️ 다음 곡]` · `[📻 24/7 상주]`, 티켓 `[📄 대화록 저장]`, 예약이벤트 `[📣 참가자 호출]`, 비밀 D-Day 수정, 반응역할 죽은 연결 정리, 홈 단축바 숨기기 추가",
        ],
        "changed": [
            "22개 파일 전반의 어색한 기계식 조사(`을(를)`, `이(가)`, `(으)로` 49곳)를 자연스러운 한국어 문장으로 전면 교정",
            "미사용 구 슬래시 안내 문구를 실제 `/설정` 경로로 교체 및 `/도움말`·`README.md` 최신화",
        ],
    },
    {
        "commit": "07319b1",
        "date": "2026-11-26",
        "title": "봇 주인 전용 !봇상태 명령어 추가",
        "added": [
            "봇 주인만 사용할 수 있는 `!봇상태 [상세|요약]` 명령어 추가 (접속 서버 목록 · 최근 시스템 로그 · 자원 진단)",
        ],
        "changed": [],
    },
    {
        "commit": "1c7a302",
        "date": "2026-11-26",
        "title": "프로세카 가챠 💫 3성일러 ON/OFF 전환 버튼 추가",
        "added": [
            "프로세카 가챠 결과 화면에 연출 스킵과 동일한 방식의 `[💫 3성일러: OFF/ON]` 토글 버튼 추가 (기본 OFF, ON 시 ★3 ➔ ★4 순 표시)",
        ],
        "changed": [],
    },
    {
        "commit": "c9ceacb",
        "date": "2026-11-26",
        "title": "!업데이트 · !현재버전 수동 배포 체계 전환 및 불필요한 ! 명령어 정리",
        "added": [
            "봇 주인 전용 `!업데이트`(누적 GitHub 커밋 일괄 반영) 및 `!현재버전`(현재 반영 커밋 vs GitHub 최신 커밋 강조 비교) 추가",
        ],
        "changed": [
            "GitHub push 시 자동 원격 재시작 배포를 끄고 수동 `!업데이트` 반영 방식으로 전환",
            "일반 코그의 모든 `!` 단축어 및 `!터미널로그`·`!봇배너` 제거",
        ],
    },
    {
        "commit": "01c2a21",
        "date": "2026-11-26",
        "title": "감사/시스템 로그 상세·요약 2버전 완성 및 자동 고정메시지 상세 설정",
        "added": [
            "자동 고정 메시지 상세 설정 패널(갱신 방식 · N개 메시지 이후 · 마지막 메시지 N초 뒤 · 색상 · 제목 생략 가능) 추가",
            "봇 상태 진단에 접속 서버 목록 및 실시간 로그 연동 현황·최근 로그 표시 추가",
        ],
        "changed": [
            "서버 감사 로그 기본값을 요약 모드로 설정하고, 요약 모드에서도 발생 내역이 누락 없이 모두 표시되도록 개선",
            "로그 및 임베드 전반의 불필요한 모드 꼬리표와 중복 안내 푸터 제거",
        ],
    },
]
