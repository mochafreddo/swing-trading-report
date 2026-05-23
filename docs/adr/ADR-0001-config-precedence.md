# ADR-0001 — 설정 우선순위: config.yaml → .env → CLI

상태: 채택(Accepted)  •  날짜: 2025-11-06

## 배경

레포에 기본값을 두되, 비밀정보/실험값은 로컬에서 덮어쓰고, 실행 시 즉시 변경 가능한 방식이 필요합니다.

## 결정

설정 값은 다음 우선순위를 따릅니다.

1) `config.yaml` — 프로젝트 기본(비밀 아님)
2) `.env` — 개발자 로컬 오버라이드/비밀(커밋 금지)
3) CLI 플래그 — 실행 시 오버라이드(최우선)

단, KIS 시크릿(`KIS_APP_KEY`, `KIS_APP_SECRET`)은 `.env`/환경변수로만 허용하며 YAML 보관을 금지합니다.

YAML 로드는 선택사항(`pyyaml` 필요). 미설치 시에도 `.env`와 CLI만으로 작동합니다.

위 우선순위는 “`config.yaml`과 `.env`에 동일 키가 정의되지 않는다”는 전제가 성립할 때 적용됩니다. 두 경로에 같은 키가 동시에 존재하면 fail-closed로 차단합니다(`sab/config.py`의 `_enforce_env_yaml_conflict_policy`). 자세한 정책은 `ADR-0003-config-conflict-policy.md`를 함께 보세요.

## 결과

- 개발자 경험 향상: 예측 가능한 동작, 실행 단위 손쉬운 튜닝
- 비밀은 레포 밖 유지. 예시 파일(`config.example.yaml`, `.env.example`)로 키 문서화
- 로더 복잡성 소폭 증가 → 예시 파일/런북으로 완화

## 대안 검토

- `.env`만 사용: 단순하지만 임계치/시장 옵션이 많아지면 불편
- YAML만 사용: 실험/비밀 관리가 번거로움
