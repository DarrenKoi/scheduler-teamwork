# Python Job Scheduler

> Flask + APScheduler 기반의 Python 작업 스케줄러. 웹 대시보드에서 작업 상태 확인, 수동 실행, 로그 조회 가능.

## 왜 필요한가? (Why)

- Python 스크립트를 주기적으로 실행해야 하는 경우 (데이터 수집, 보고서 생성, 자동화 등)
- Windows Task Scheduler/cron 대신 웹 UI로 관리하고 싶은 경우
- 작업 실행 기록과 로그를 한 곳에서 확인하고 싶은 경우
- 팀원들과 간편하게 Python 자동화 스크립트를 공유하고 실행하고 싶은 경우

## 핵심 개념 (What)

### 아키텍처

```
jobs/                         # 작업 폴더 (Flattened Structure)
├── {task_name}/
│   ├── pyproject.toml        # (Optional) uv 프로젝트 설정
│   ├── job.yaml              # 스케줄 설정 (자동 생성 가능)
│   └── main.py               # 실행 스크립트

src/
├── app.py                    # Flask 웹 서버
├── job_manager.py            # 작업 관리 엔진
├── config.yaml               # 서버 설정
└── templates/                # (Legacy) Jinja2 웹 UI
```

### 작업 구조

각 작업은 `jobs/{task_name}/` 디렉토리에 위치합니다. 
최소한 실행할 Python 스크립트 하나만 있으면 되며, `job.yaml`은 웹 UI에서 설정을 통해 자동 생성할 수 있습니다.

**job.yaml 예시:**

```yaml
name: "My Task"
description: "무엇을 하는 작업인지 설명"

schedule:
  type: interval        # "interval" 또는 "cron"
  minutes: 30           # interval: seconds, minutes, hours
  # type: cron
  # hour: 9
  # minute: 0

entry_point: main.py    # 실행할 파일 (기본값: main.py)
timeout: 3600           # 타임아웃 초 (기본값: 3600)
```

### 스케줄 타입

| 타입 | 설명 | 옵션 예시 |
|------|------|-----------|
| `interval` | 일정 간격으로 반복 | `seconds: 30`, `minutes: 5`, `hours: 1` |
| `cron` | cron 표현식 | `hour: 9`, `minute: 0`, `day_of_week: "mon-fri"` |

## 어떻게 사용하는가? (How)

### 1. 설치

```bash
cd web-development/python/flask/job-scheduler
uv sync
```

### 2. 서버 실행 (Backend)

```bash
uv run src/app.py
```
Backend runs on http://localhost:5050

### 3. 모던 프론트엔드 실행 (Nuxt UI)

새로운 Nuxt 기반의 대시보드를 사용하여 작업을 관리합니다.

```bash
cd frontend
npm install
npm run dev
```
Frontend runs on http://localhost:3000 (proxies requests to backend at 5050).

### 4. 작업 추가 및 관리

**간편한 웹 업로드 (Recommended)**
1.  Frontend 대시보드 우측 상단의 **"Add New Job"** 버튼을 클릭합니다.
2.  **Task Name**을 입력합니다 (유일한 ID로 사용됩니다).
3.  작성한 `.py` 스크립트 파일을 드래그 앤 드롭합니다.
4.  (선택) `job.yaml` 파일이 없다면 **"Configure Job"** 토글을 켜서 UI에서 바로 스케줄(Interval/Cron)을 설정합니다.
5.  **"Create Job"**을 클릭하면 작업이 등록되고 스케줄링이 시작됩니다.

**작업 수정**
*   대시보드 리스트에서 톱니바퀴 아이콘(**Edit Configuration**)을 클릭하여 실행 스크립트나 스케줄을 언제든지 변경할 수 있습니다.

**Option B: Manual CLI**
```bash
# 1. 작업 디렉토리 생성
mkdir -p jobs/my_daily_report

# 2. 스크립트 작성
cat > jobs/my_daily_report/main.py << 'EOF'
def main():
    print("Report generated!")

if __name__ == "__main__":
    main()
EOF

# 3. job.yaml 작성 (선택 사항, 없으면 UI에서 설정 가능)
cat > jobs/my_daily_report/job.yaml << 'EOF'
name: "Daily Report"
schedule:
  type: interval
  hours: 24
EOF

# 4. 대시보드 자동 반영 (기본 60초 주기 스캔)
```

### 5. 주요 기능

- **Dashboard**: 모든 작업을 한눈에 볼 수 있는 리스트 뷰. 상태(Running, Failed), 다음 실행 시간 확인.
- **Easy Config**: YAML 파일을 직접 작성하지 않아도 UI에서 스케줄 설정 가능.
- **Run History**: 각 작업의 실행 이력, 성공/실패 여부, 실행 시간, 로그 조회.
- **Manual Run**: "Run" 버튼으로 즉시 작업 실행.
- **Live Updates**: 작업 상태 및 시스템 상태(업데이트 대기 등) 실시간 반영.

### 6. 설정 변경

`src/config.yaml`에서 서버 포트, 스캔 주기 등을 설정할 수 있습니다.

```yaml
server:
  port: 5050

scheduler:
  scan_interval_seconds: 60  # 파일 변경 감지 주기

log_retention:
  days: 30                   # 로그 보존 기간
```

## 참고 자료 (References)

- [APScheduler 공식 문서](https://apscheduler.readthedocs.io/)
- [Flask 공식 문서](https://flask.palletsprojects.com/)
- [uv - Python 패키지 매니저](https://docs.astral.sh/uv/)
- [Nuxt UI](https://ui.nuxt.com/)
