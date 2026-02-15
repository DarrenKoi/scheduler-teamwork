# Flask Job Scheduler - CLAUDE.md

> Flask + APScheduler 기반 Python 작업 스케줄러 프로젝트의 Claude Code 가이드

---

## 📌 프로젝트 개요

- **목적**: Python 스크립트를 주기적으로 실행하고 웹 대시보드에서 관리하는 스케줄러
- **기술 스택**: Flask (backend), APScheduler, Nuxt (frontend), SQLite, uv
- **소유자**: Daeyoung (SK Hynix AI/DT TF)

---

## 📁 프로젝트 구조

```
job-scheduler/
├── src/                    # 백엔드 코드
│   ├── app.py              # Flask 웹 서버 (port 5050)
│   ├── job_manager.py      # 작업 관리 엔진
│   ├── config.yaml         # 서버/스케줄러 설정
│   └── templates/          # (Legacy) Jinja2 웹 UI
├── jobs/                   # 실행 가능한 작업 폴더
│   └── {task_name}/
│       ├── main.py         # 실행 스크립트
│       ├── job.yaml        # 스케줄 설정 (선택, UI에서 자동 생성 가능)
│       └── pyproject.toml  # (Optional) uv 프로젝트 설정
├── frontend/               # Nuxt UI (port 3000)
│   └── app/                # pages, components
├── data/                   # SQLite DB (jobs.db)
├── logs/                   # 스케줄러 및 작업 실행 로그
└── pyproject.toml          # 백엔드 의존성
```

---

## 🛠️ 개발 명령어

```bash
# 백엔드
uv sync                     # 의존성 설치
uv run src/app.py           # Flask 서버 실행 (localhost:5050)

# 프론트엔드
cd frontend && npm install  # 의존성 설치
cd frontend && npm run dev  # Nuxt 개발 서버 (localhost:3000)
cd frontend && npm run lint
cd frontend && npm run typecheck
cd frontend && npm run build
```

---

## ✍️ 코딩 스타일

- **Python**: 4칸 들여쓰기, `snake_case` (함수/변수), `PascalCase` (클래스), 타입 힌트 권장
- **Vue/TypeScript**: Nuxt + ESLint 기본 규칙, 2칸 들여쓰기
- **파일명**: `snake_case` 또는 `kebab-case`, 기존 컨벤션 따름
- **문서**: 한국어 기본, 기술 용어 영어 병기, Why → What → How → References 구조

---

## 🔒 보안 및 설정

- 비밀 정보, API 키, 내부 엔드포인트 커밋 금지
- 환경별 설정은 환경 변수 또는 로컬 오버라이드 사용
- `src/config.yaml` 변경 시 주의 (포트, 스캔 주기, 보존 설정 등)

---

## ⚠️ 환경 참고 사항

- 회사 방화벽으로 외부 LLM API 사용 불가 → 내부 OpenAI 호환 API 사용
- 코드 예제에 OpenAI/Anthropic 등 외부 API 사용하지 않을 것

---

*Extracted from root CLAUDE.md & AGENTS.md — 2026-02-14*
