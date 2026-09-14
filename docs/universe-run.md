# 전체 종목군 평가 실행

NYSE·Nasdaq의 토스 거래 가능 보통주 목록을 구성하고, 종목별 판정과 최대 3개 후보의 기본 보고서를 만듭니다. 전체 탐색 범위와 보류 사유는 [평가 계약](universe-run-contract.md)을 확인하세요. Python 3.11 이상과 표준 라이브러리를 사용합니다.

## 실행

기존 [인증정보 준비](single-run.md#인증정보-준비)에 따라 비공개 파일을 준비한 뒤 실행하세요. 출력에는 존재하지 않는 새 디렉터리를 지정하세요.

```sh
python3 universe_run.py run \
  --credentials-file "$HOME/.local/share/swing-trading-report/credentials.env" \
  --output runs/universe-first
```

액세스 토큰이 없을 때만 `--issue-tokens`를 명시하세요. 토스는 기존 토큰을 무효화하며 KIS는 알림톡을 발송할 수 있습니다. 토큰은 메모리에만 유지하고 자동 재발급·재시도하지 않습니다. 계좌·보유·주문 API는 사용하지 않습니다.

`report.md`에서 후보·전체 목록 범위·선정·제외·보류 건수와 사유를 확인하세요. `record.json`에는 모든 종목의 정규화 입력·판정·원본 응답·확인 시각이 있습니다. 목록 확보는 필수 입력을 모두 검증했다는 뜻이 아닙니다. 일부 종목을 보류해도 확인된 다른 종목의 결과는 유지합니다. 수집 중 개장 시각을 넘기면 늦게 수집한 종목을 보류합니다.

종료 코드 `0`은 검증된 범위에서 후보 선정 또는 조건 탈락, `2`는 전체 목록 미확보·순위 미확정·전체 평가 불가, `1`은 실행·인증·재현 오류입니다. 일부 보류는 보고서와 기록에서 별도로 확인하세요. 전체 목록이 불완전한 결과를 전체 탐색 성공으로 취급하지 마세요.

## 실적 일정 출처

기본 출처는 기존에 확인한 MU 기업 IR입니다. 다른 종목은 출처 미등록으로 보류합니다. 날짜를 입력해 보류를 해제하는 옵션은 없습니다. 기업의 공식 출처를 확인한 뒤 공개 설정 JSON을 `--earnings-sources`로 전달할 수 있습니다. 등록은 회사명·목록 URL·기사 URL 접두사만 받습니다.

```json
{
  "MU": {
    "company": "Micron Technology",
    "listing_url": "https://www.micron.com/about/press/news",
    "article_prefix": "https://investors.micron.com/news/press-release/"
  }
}
```

수집기는 목록의 절대 링크와 기사 JSON-LD의 `NewsArticle`을 읽습니다. `기업명 to Report Fiscal ... Results on Month Day, Year` 형태의 확정 공지를 인식하며, 예상·잠정·취소·연기 또는 해석할 수 없는 공지는 보류합니다. 설정만 추가했다고 그 기업의 실제 공지 수집을 검증한 것은 아닙니다.

## 현재 한계

거래대금은 기존 KIS 정규장 분봉의 하한으로 유동성 기준 통과만 확인합니다. 거래량 증가 배율이 같은 후보의 정확한 거래대금 비교는 아직 지원하지 않습니다. 이 종목들은 순위 미확정으로 보류하며, 보고서의 나머지 후보를 전체 종목군 상위 순위로 해석하면 안 됩니다. 정확한 거래대금 출처 확보가 필요합니다.

호출은 순차로 수행합니다. 전체 목록은 6회, 종목 상세는 최대 200개씩, 달력은 실행당 한 번 구성하고 시세는 각 종목별로 조회합니다. 실제 소요 시간과 실패 요청은 기록에 남습니다. 이 실행 외 프로세스와 호출 한도를 공유하는 제어는 없습니다. 전체 대상의 실제 수집·평가 검증과 MU 외 기업 IR 경로의 검증은 아직 완료하지 않았습니다.

## 오프라인 재현과 검증

```sh
python3 universe_run.py replay runs/universe-first
python3 -m unittest test_universe_run -v
python3 -m unittest discover -v
python3 check_negative_controls.py
python3 -m py_compile single_run.py universe_run.py test_single_run.py test_universe_run.py check_negative_controls.py
```

재현은 인증정보와 네트워크를 사용하지 않습니다. 원본 응답·판정·순위·계산 가격·보고서와 코드·규칙·계약의 일치를 확인합니다. `runs/`는 Git에서 제외되므로 다른 체크아웃에서 재현하려면 실행 기록과 동일한 코드 버전을 함께 준비하세요. 문법 검사는 정적 타입 검사를 대신하지 않습니다.
