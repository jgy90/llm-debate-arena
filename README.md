# AI Debate Arena

Claude와 Gemini가 실시간으로 토론하는 웹 앱입니다.

## 개요

- **Claude**: Claude Code CLI를 통해 호출 (Pro 플랜 쿼터 사용, API 키 불필요)
- **Gemini**: Whale 브라우저 자동화로 Gemini 웹을 직접 조작 (Google One AI Plus 구독 사용)
- **실시간 스트리밍**: SSE(Server-Sent Events)로 토론 진행 상황을 실시간 표시
- **토론 저장/불러오기**: 토론 기록을 JSON으로 저장하고 이어서 진행 가능

## 토론 흐름

1. **자료 조사**: Gemini가 주제를 웹 검색으로 조사
2. **개회 발언**: Claude와 Gemini가 각자 입장 제시
3. **반론 라운드**: 설정한 라운드 수만큼 서로 반론
4. **종합 결론**: Claude가 토론 전체를 요약·정리
5. **저장 & 계속**: 토론 기록 저장 후 추가 라운드 진행 가능

> Claude가 `[자료요청]: ...` 형식으로 끝내면 Gemini가 추가 자료를 조사해 제공합니다.

## 요구 사항

- **Python 3.9+**
- **Claude Code CLI** 설치 및 로그인 (`claude` 명령어 사용 가능한 상태)
- **Naver Whale 브라우저** — Gemini(gemini.google.com)에 Google 계정으로 로그인된 상태
- **Playwright** (`pip install playwright && playwright install chromium`)

## 설치

```bash
git clone <repo>
cd debate-arena

pip install -r requirements.txt
pip install playwright
playwright install chromium
```

## 실행

```bash
python app.py
```

브라우저에서 `http://localhost:5050` 접속

> Whale 브라우저가 **미리 실행 중**이고 Gemini에 **로그인된 상태**여야 합니다.

## 사용법

### 토론 시작

1. 토론 주제 입력 (예: `2026년 미국 경기침체 가능성`)
2. 라운드 수 선택 (2~5)
3. Claude / Gemini 모델 선택
4. `토론 시작` 버튼 클릭

### 저장 & 이어서 토론

- 토론 완료 후 **`💾 토론 저장`** 버튼으로 저장
- **`▶ 추가 라운드`** 버튼으로 현재 토론 이어서 진행
- 상단 **`📁 저장된 토론 불러오기`** 에서 이전 토론 보기 / 이어서 / 삭제

## 구조

```
debate-arena/
├── app.py              # Starlette ASGI 백엔드
├── templates/
│   └── index.html      # 프론트엔드 (SSE 스트리밍 UI)
├── debates/            # 저장된 토론 JSON 파일
├── requirements.txt
└── test_gemini_web.py  # Gemini 웹 연동 디버깅용
```

## 기술 스택

| 항목 | 내용 |
|------|------|
| 백엔드 | Python, Starlette, Uvicorn |
| 프론트엔드 | Vanilla JS, SSE |
| Claude 연동 | Claude Code CLI (`claude -p`) |
| Gemini 연동 | Whale 브라우저 AppleScript + Playwright CDP |
| 인코딩 | Base64 (AppleScript→JS 다중 이스케이프 우회) |

## Gemini 브라우저 자동화 원리

AppleScript로 Whale의 Gemini 탭에 JavaScript를 직접 실행합니다.

- 프롬프트는 **Base64 인코딩** 후 `atob()` + `decodeURIComponent()`로 디코딩 (한국어 깨짐 방지)
- 현재 활성 탭을 건드리지 않고 **백그라운드 탭**에서 입력/전송
- 응답 완료 감지: 텍스트 길이가 2회 연속 동일 → 완료로 판단
- 응답 읽기: 4,000자씩 청크로 분할 (AppleScript 반환값 크기 제한 우회)
- 2라운드부터는 **같은 탭**을 재사용 → Gemini 컨텍스트 유지

## 주의 사항

- Claude Code CLI의 **Pro 플랜 시간당 토큰 한도**에 걸릴 수 있습니다. 한도 초과 시 토론이 중단되며 리셋 시간이 표시됩니다.
- Gemini 응답 시간 초과(180초)가 발생하면 네트워크 상태나 Gemini 서비스 상태를 확인하세요.
- Whale 브라우저는 실행 중이어야 하며, 자동화 중 다른 작업으로 Gemini 탭을 닫으면 오류가 발생합니다.
