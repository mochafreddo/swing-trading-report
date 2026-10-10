# 텔레그램 단건 전송

로컬 Mac에서 수동으로 만든 한 종목 보고서를 사용자와 봇의 개인 채팅에 전송합니다. 이 기능은 [#235](https://github.com/mochafreddo/swing-trading-report/issues/235)의 단건 전송 경로입니다. MU 기본 보고서는 항상 미리보기로 표시하며, 실제 전체 종목군 탐색 보고서나 마일스톤의 정시 전달 완료로 인정하지 않습니다. 예약 실행·Mac 복구·지연 전달 자동화는 포함하지 않습니다.

## 설정과 첫 전송

먼저 봇과의 개인 채팅을 시작하세요. `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID` 두 항목을 저장소·동기화 폴더 밖의 소유자 전용 파일에 준비하세요. 권한은 `600`이어야 합니다. 봇 토큰과 chat ID는 채팅, 명령 인자, 저장소 파일에 넣지 마세요. 파일을 지정하지 않으면 같은 이름의 환경변수를 사용합니다. 전송 설정 파일은 시세 인증 파일과 별도로 준비하세요. 다른 키가 포함되면 거부합니다.

[단건 실행 안내](single-run.md)에 따라 현재 코드로 새 실행을 만든 뒤 전송하세요. 저장된 공개 응답으로 보고서를 오프라인 재현해 무결성을 확인한 다음, [Telegram Bot API](https://core.telegram.org/bots/api#senddocument)의 `sendDocument`로 `report.md` 원문과 미리보기 설명을 한 번에 전송합니다. 긴 보고서를 여러 메시지로 나누지 않습니다. `getChat`으로 대상이 지정한 개인 채팅인지 확인하며, 그룹·채널·확인되지 않은 대상에는 보내지 않습니다.

```sh
python -B telegram_delivery.py send runs/mu-first \
  --credentials-file "$HOME/.local/share/swing-trading-report/telegram.env"
```

현재 코드·규칙과 맞지 않는 과거 실행은 전송하지 않습니다. 당시 코드에서 재현하거나 현재 코드로 새 실행을 만드세요. 기존 보고서와 실행 기록은 수정하지 않습니다. 별도 `delivery.json`에 보고서와 실행 기록의 SHA-256, 대상의 지문, 자료의 합성 여부, 전송 시도별 상태·시각·수신 확인을 연결합니다. 토큰·chat ID 원문·HTTP 오류 본문은 저장하지 않습니다.

## 응답과 수신 확인

`sent`는 API가 대상 개인 채팅의 메시지 ID와 발행 시각을 반환한 상태입니다. 사용자가 읽거나 수신을 확인했다는 뜻은 아닙니다. `not_sent`는 API가 명시적인 4xx 거절 응답을 반환한 상태입니다. 통신 중단·타임아웃·형식 오류·5xx·리디렉션·불완전한 응답은 `unknown`으로 남깁니다. 종료 코드 `0`은 API 성공 또는 수신 확인 저장, `2`는 미전송 또는 결과 불명확, `1`은 설정·무결성·중복 방지 등 실행 오류입니다.

전송 전에 `unknown`을 디스크에 저장하고 원자적으로 갱신합니다. 같은 실행 디렉터리를 대상으로 한 동시 전송은 잠금으로 차단합니다. 응답 확인 전에 프로세스가 중단되어도 `unknown`이 남으며, 다시 `send`를 실행해 자동 재전송하지 않습니다. 이 잠금과 기록은 해당 실행 디렉터리를 기준으로 하므로, 기록을 삭제하거나 디렉터리를 복제해 재전송하지 마세요.

개인 채팅을 직접 확인한 뒤 수신 결과를 기록하세요.

```sh
python -B telegram_delivery.py confirm runs/mu-first received
# 직접 확인했지만 받지 못한 경우에만 다음 명령을 사용하세요.
python -B telegram_delivery.py confirm runs/mu-first missing
```

위 두 확인 명령 중 실제 상태에 맞는 하나만 실행하세요. 마지막 시도에 대한 확인은 한 번만 기록합니다. `received` 이후에는 재전송할 수 없습니다. `missing` 확인 이후에만 같은 보고서와 같은 대상으로 한 번 수동 재전송할 수 있습니다.

```sh
python -B telegram_delivery.py retry runs/mu-first \
  --credentials-file "$HOME/.local/share/swing-trading-report/telegram.env"
```

새 시도의 수신 확인은 다시 필요합니다. 성공·거절·불명확 어느 결과에서도 자동 재시도하지 않으며, API가 제공한 재시도 대기시간도 자동 실행에 사용하지 않습니다.

## 전달 시각과 검증 범위

저장된 보고일의 검증된 거래일 달력에서 정규장 개장 시각을 읽고 60분을 빼 `scheduled_at`에 기록합니다. 일반 평일이나 고정 UTC 시각으로 대체하지 않습니다. API의 메시지 발행 시각이 그 예정 분의 시작 이상, 다음 분의 시작 미만이고 보고일·자료 확인 시각과 맞으면 `on_time=true`입니다. 다른 시각은 `timing=preview`입니다. 휴장일이나 달력 미검증이면 예정 시각 없이 미리보기로 남깁니다. `on_time`은 발행 시각에 대한 판정이며 사용자의 수신·열람 시각을 입증하지 않습니다. 한 종목·합성 자료의 `scope=single_symbol_preview`는 이 시각 판정과 별개로 유지합니다.

`transport=simulation`은 주입된 모의 전송, CLI의 `transport=telegram`은 실제 API 전송 경로입니다. 테스트에서 API 경계를 대체한 결과를 실제 수신으로 해석하지 마세요. 실제 개인 채팅 수신은 별도로 사용자가 확인해야 합니다. 전체 보고서의 정시 전달과 내용 검토는 최종 통합 티켓에 남깁니다.

```sh
python -B -m unittest test_telegram_delivery -v
```

이 검증은 합성 공개 응답으로 단건 보고서를 생성한 뒤 전송·수신 확인·수동 재전송 경계를 확인합니다. 실제 전송 전에 전체 검사와 불명확 응답의 자동 재전송 오류 주입 검사를 실행하세요. 정적 타입 검사 도구가 없는 환경에서는 타입 검사를 생략했다고 기록하며, 구문 검사나 Ruff 통과로 대신하지 않습니다. 실제 전송과 사용자 수신 확인 결과는 [검증 기록](issue-235-validation.md)을 확인하세요.
