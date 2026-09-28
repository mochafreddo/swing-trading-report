# 이슈 #233 데이터 경로 표본 검증

## 2026-09-28 체결 식별 충돌과 정규장 분봉 대조

저장된 Alpaca 정상일 169페이지·1,688,109행을 원본 해시 검증 후 다시 분석했다. 같은 `(symbol, tape, exchange, id)`에 서로 다른 내용이 나온 13,907쌍 중 13,878쌍은 기존 조건표 기준 두 행 모두 마감 전 정규장 집계 후보였다. 나머지 29쌍은 한 행만 해당했다. AAPL·tape C·exchange D·ID 7005는 `13:30:00.030612324Z`의 327.47 USD × 5주와 `14:00:22.694857638Z`의 332.465 USD × 30주에 반복됐고, 두 행 모두 조건 `@, I`, 취소·오류 상태 `u`는 없었다. 따라서 시간외 조건을 제외하는 것만으로 ID 충돌이 사라지지 않는다. 같은 ID를 임의로 중복 제거하지 않았다. ID 충돌만으로 서로 다른 실제 거래인지 공급자 오류인지도 확정하지 않는다.

Yahoo 공개 5분봉을 새로 조회해 2026-09-11 뉴욕 09:30~16:00의 78개 구간을 모두 대조했다. Alpaca는 취소·오류 및 M/Q/9/T/U 조건을 제외한 마감 전 진단 합계이며, 두 공급자의 경제적 집계 계약이 같다는 전제는 아직 검증되지 않았다. Yahoo 응답에 함께 포함된 요청일 밖의 9월 25일 16:00 행은 비교에서 제외했다.

| 종목 | Yahoo 78개 구간 거래량 | Yahoo − Alpaca 합계 | 첫 5분 차이 | 나머지 77구간 차이 |
| --- | ---: | ---: | ---: | ---: |
| AAPL | 42,223,381 | 629,426 | 812,525 | -183,099 |
| MU | 18,810,292 | 1,475,666 | 1,517,235 | -41,569 |
| XOM | 8,564,414 | 47,586 | 58,521 | -10,935 |

큰 양의 차이는 첫 구간에 집중됐지만 이후 구간도 일치하지 않았다. 이를 개장 체결 누락이나 특정 공급자 오류라고 단정하지 않는다. 기존 일봉 대조에 더해 차이의 시간대를 좁혔을 뿐, 독립 거래량·정확 거래대금 검증은 계속 보류다. 원본 응답·분석 스크립트·해시·결과는 `runs/issue233-premarket-20260928/`의 `trade-identity-analysis.json`, `intraday-reference/`, `intraday-comparison.json`에 보존했다. 추가 Alpaca 인증 조회나 공급자 문의 발송은 하지 않았다.

## 2026-09-24 남은 경로의 추가 검증

### 최신 목록과 충돌 근거

공식 Nasdaq 디렉터리 두 파일을 다시 조회했다. 두 파일의 생성 표시는 `0924202607:00`이며 공개 GET 2회·4.702초였다. 기존 9월 14일 토스 기록의 7종목과 대조했을 때 KHC는 NYSE, PSNYW는 Class C-1 ADS (ADW), 나머지는 Nasdaq에 계속 표시됐다. 시점이 다른 자료이므로 현재 토스의 거래 가능 여부나 과거 상태를 확정하지 않는다. 런타임은 일반·유형별 목록의 충돌을 종목별 원문과 사유로 보존하도록 보강했다. 최신 토스 목록·상세 대조는 추가 토큰 발급 승인 후에 실행해야 한다.

- 로컬 원문·대조 기록: `runs/issue233-listing-directory-20260924/`
- [토스 종목 조회 명세](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/StockInfoApi.md)는 전체 목록을 페이지 없이 반환하고 일별로 갱신한다고 설명하지만 일반·유형별·상세 요청 사이의 원자적인 스냅샷은 보장하지 않는다.

### 여러 기업의 공식 IR 수집

공통 수집기에 상대 링크·다음 페이지·중첩 JSON-LD·발행 메타데이터와 Q4 공개 피드를 연결했다. 기본 출처는 11개 기업·12개 티커이며, GOOG와 GOOGL은 같은 Alphabet 공지를 사용한다. 출처 등록과 실제 일정 확인을 구분한다. 기업명, 발행 시각, 결과 발표 문장, 날짜 충돌과 취소·연기를 검사하며, 콜 날짜나 회계기간 종료일은 발표일로 대신하지 않는다. 시간대 없는 발행 날짜는 날짜 정밀도로 기록하고 당일 공지는 보류한다.

Q4 위젯의 실제 요청과 페이지 번호별 응답으로 공개 `GetPressReleaseList` 경로를 확인했다. `year=-1`, `bodyType=2`, `pageNumber`를 사용하고 명시적인 빈 페이지까지 읽는다. 작은 페이지를 마지막으로 간주하지 않는다. 전체 응답과 25개 단위 응답은 일부 기업에서 크기 제한을 초과해 5개 단위로 줄였다. 런타임의 4 MB 응답 상한과 리다이렉트 거절을 유지했다. 기업당 최대 200페이지를 넘으면 미확보로 남긴다. [Amazon IR의 공개 Q4 위젯](https://ir.aboutamazon.com/js/module/widgets/dist/latest/evergreen.q4Api.min.js)

NIKE 실제 공개 응답 137개에서 다음 결과 발표일 **2026-10-01**을 확인했다. 근거 공지의 발행 날짜는 **2026-08-28**, 발행 시각 정밀도는 날짜이며 콜 시간이 확정 발표 시각을 대신하지 않는다. 날짜를 설정에 넣지 않고 등록된 목록에서 피드를 따라 찾았다. 원본 응답과 수집 당시 소스 해시를 대조했고, 수정한 파서로 저장 응답을 재분류한 결과도 같았다. 이는 MU 외 실제 공지 수집의 근거이며 NIKE의 가격·거래량·후보 선정 성공을 뜻하지 않는다. [NIKE 공식 예고](https://investors.nike.com/investors/news-events-and-reports/investor-news/investor-news-details/2026/NIKE-Inc--Announces-First-Quarter-Fiscal-2027-Earnings-and-Conference-Call/default.aspx)

- 원문·당시 코드: `runs/issue233-nke-runtime-20260924/`
- 현재 코드 재분류: 같은 경로의 `current-reclassification.json`

최종 11개 기업 실행은 2026-09-24T11:46:45.923954+00:00 기준으로 365회 요청·385.391초였다. MU와 NKE는 위 확정일, GOOGL·META·XOM·COST는 지원 경로 조회 완료 후 다음 확정일 근거 미발견, NVDA는 10페이지 한도 미확보, AAPL·JPM은 형식 미지원으로 남았다. AMZN은 5개 단위 피드의 4번째 페이지도 4 MB 상한을 넘었고 MSFT는 리다이렉트로 실패했다. 수집 당시 고정한 소스로 네트워크 없는 재현이 일치했고, 리뷰에서 수정한 파서로 저장 응답을 재분류한 결과도 같았다. 기록은 `runs/issue233-ir-runtime-final-20260924/`에 소스와 함께 보존했다.

MSFT의 최초 목록 주소가 반환한 공식 목적지를 확인해 기본 설정을 `https://www.microsoft.com/en-us/investor/events/default`로 갱신했다. 새 주소로 2회 공개 요청을 실행했지만 후속 기사 링크의 리다이렉트로 계속 실패했다. 이를 일정 근거 미발견이나 수집 완료로 표시하지 않는다. 추가 기록은 `runs/issue233-msft-canonical-20260924/record.json`이다.

전체 이력을 읽는 현재 Q4 방식은 NIKE 한 기업에 137회 요청이 필요했다. 날짜 범위로 제한하는 제공자 계약을 검증한 뒤 최적화해야 한다. 동적 목록과 공지 표현을 모두 처리한 것은 아니며, 형식 미지원·수집 실패·조회 완료 후 근거 미발견을 구분해 보류한다. 실제 필요한 기업 전체의 지원 여부는 전체 가격 평가 후 다시 확인해야 한다.

### 체결 조건 분류와 독립 거래량 대조

저장된 Alpaca 정상일 169페이지를 추가 인증 조회 없이 재분류했다. 테이프별 조건표에 따라 취소·오류, 거래량 비반영, 시간외, 마감 전, 마감 이후 종가 체결, 미지정 조건을 별도 합계로 기록한다. 미확인 ID 중복을 임의로 제거하지 않으며 모든 합계는 진단값이다. `exact_regular_turnover_verified=false`와 검증 보류를 유지한다. [Alpaca 공식 조건표](https://docs.alpaca.markets/us/docs/market-data-faq), [정정 상태에 대한 제공자 답변](https://forum.alpaca.markets/t/persistent-ionq-sip-trade-bar-mismatch-2-trades-and-2-shares/19339)

| 2026-09-11 | 마감 전 + 마감 후 종가 조건 진단 거래량 | 9월 24일 조회한 Yahoo 일봉 거래량 | 차이 |
| --- | ---: | ---: | ---: |
| AAPL | 47,012,399 | 50,716,900 | 3,704,501 |
| MU | 18,573,979 | 21,740,300 | 3,166,321 |
| XOM | 10,470,270 | 11,362,400 | 892,130 |

Yahoo 공개 일봉은 3회 GET으로 조회해 심볼·USD·뉴욕 시간대와 날짜를 확인했다. 양쪽의 세션·정정·지연 보고 집계 계약이 같다고 입증하지 못했으므로 차이를 곧바로 누락 체결량이라고 단정하지 않는다. 세 종목 모두 독립 합계 일치를 입증하지 못했다. 식별자 충돌, 지연 보고 종료 시점과 historical 정정 계약도 남아 있어 조기 폐장일·20거래일 수집과 정확 동률 정렬로 확대하지 않는다. 공개 논의에도 historical ID의 안전한 유일성 키가 확정되어 있지 않다. [식별자 충돌 논의](https://forum.alpaca.markets/t/which-combination-of-fields-guarantees-uniqueness-in-historical-trade-records/17728)

- 조건별 진단: `runs/issue233-alpaca-normal-20260924-continued1/summary-condition-totals.json`
- 독립 응답·대조 및 원본 해시: `runs/issue233-volume-reference-20260924/record.json`, `comparison.json`

정확 거래대금의 대안은 현재 무료 경로에서 검증된 값을 찾거나, 제공자에게 식별자·정정·지연 보고 계약을 확인하는 것이다. 합계가 맞지 않는 값을 운영 순위에 넣는 것은 대안이 아니다. 외부 문의 초안은 기존 문서에 남아 있으며 이번 작업에서 문의를 발송하지 않았다.

## 2026-09-24 Alpaca 실제 조회 후속 결과

### 정상일 3종목의 요청 범위 수집 완료

사용자가 이어받기를 실행해 69페이지·688,109행을 206.430초에 추가 수집했다. 기존 기록을 합쳐 총 169페이지·1,688,109행이며 누적 수집 시간은 488.105초다. 마지막 `next_page_token`은 null이고 `collection_error`는 없다. 이는 2026-09-11의 세 종목, 정규장 시작부터 마감 5분 뒤까지 지정한 요청 범위에 대한 페이지 수집 완료이며 원천 데이터의 경제적 완전성이나 정확 거래대금 검증 완료를 뜻하지 않는다.

| 종목 | 저장 행 수 | 마감 시각 전 | 마감 시각 이후(정각 포함) |
| --- | ---: | ---: | ---: |
| AAPL | 972,339 | 971,689 | 650 |
| MU | 574,611 | 573,917 | 694 |
| XOM | 141,159 | 140,901 | 258 |

오프라인 재현에서 사용자 실행 요약과 완전히 같은 결과를 얻었다. 부모 파일 해시, 기존 100페이지의 동일성, 101번째 요청 토큰의 연결, 마지막 페이지를 확인했다. 새 기록 SHA-256은 `3d9f5aaa5c48512468c4b0ed331629262f203dcd3dbf7b7f94ebd1fc07f16d2d`다. AAPL/D 식별자 충돌 13,907건은 계속 남아 `validation_status=held`, `exact_regular_turnover_verified=false`다. MU·XOM의 표시 금액도 조건을 적용하지 않은 진단 합계다. [재현 요약](../runs/issue233-alpaca-normal-20260924-continued1/summary-replay.json), [이어받기 검증 기록](../runs/issue233-alpaca-normal-20260924-continued1/resume-audit.json)

조건 코드 `6`인 행은 AAPL 16:00:00.353393653, MU 16:00:00.583194116, XOM 16:04:28.21898086(모두 뉴욕 시각)에 관측했다. 공식 집계 규칙에서 이 코드는 Market Center Closing Trade다. 마감 전 시각만 선택하는 필터로는 이 행들을 놓친다. 이번 XOM 행이 5분 범위 안에 들어왔다는 사실만으로 다른 날짜의 모든 지연 보고가 포함된다고 가정하지 않는다. [Alpaca 조건 코드·집계 규칙](https://docs.alpaca.markets/us/docs/market-data-faq)

다음 단계는 저장된 전체 표본의 체결 식별·취소·정정·세션 적격성 검증이다. 아래에서 취소 표시와 세션 조건의 관측 결과를 구분한다. 조기 폐장일이나 20거래일의 추가 인증 조회는 아직 실행하지 않았고 #233은 미완료다.

### 취소·정정 표시와 세션 조건 검증

Alpaca 담당자는 2026-07-16 공개 답변에서 historical trades가 취소·정정 전 행도 반환하며 `u`로 상태를 나타낸다고 설명했다. `canceled`는 취소, `incorrect`는 정정으로 무효가 된 원행, `corrected`는 이전 원행의 대체 행이다. `canceled`와 `incorrect`는 봉 계산에서 제외한다는 설명도 확인했다. 이 답변은 `u`의 의미에 대한 근거이며, ID 충돌의 해결이나 모든 정정의 반영 완료 시각까지 보증하지 않는다. [Alpaca 담당자 답변](https://forum.alpaca.markets/t/persistent-ionq-sip-trade-bar-mismatch-2-trades-and-2-shares/19339/2)

| 종목 | `u=canceled` 행 | 마감 전 시간대의 `T`·`U` 조건 행 | 마감 정각 이후의 `6` 조건 행 |
| --- | ---: | ---: | ---: |
| AAPL | 7 | 32 | 1 |
| MU | 2 | 270 | 1 |
| XOM | 2 | 3 | 1 |

총 11개 취소 표시를 확인했고 `incorrect`·`corrected` 표시는 이번 자료에서 관측하지 못했다. 나머지 1,688,098행에는 `u`가 없었다. 공식 조건 설명에서 `T`·`U`는 시간외 체결 관련 조건이며 `6`은 Market Center Closing Trade다. 관측 시각만으로 정규장 포함 여부를 결정하면 마감 전의 시간외 조건 행을 포함하거나 마감 이후 종가 경매 조건 행을 제외할 수 있다. 조건 해석은 거래량·가격·VWAP마다 다르므로 이 표를 그대로 거래대금 산식으로 사용하지 않는다. [공식 조건·집계 규칙](https://docs.alpaca.markets/us/docs/market-data-faq)

진단 요약에 `trade_update_counts`, `session_condition_counts`, 종목별 최초 `closing_trade_examples`를 추가했다. 원문 행은 삭제하지 않는다. `u`가 있는 종목의 금액은 `null`로 보류하고, 알려지지 않은 값이나 null도 별도의 검토 사유로 표시한다. 따라서 이번 세 종목의 금액은 모두 `null`이다. 취소 행을 제외한 정확 거래대금을 구현했다는 뜻은 아니다. [새 재현 요약](../runs/issue233-alpaca-normal-20260924-continued1/summary-updates-and-sessions.json)

ID 재등장 13,907개는 모두 최초 행과 가격 및 시각이 달랐다. 변경 필드 조합은 `c,p,t` 1,381개, `c,p,s,t` 8,579개, `p,s,t` 3,261개, `p,t` 686개였다. 완전히 같은 행을 다시 받은 상황과 구분되며, 아직 같은 경제적 체결의 수정인지 독립 체결인지 확정하지 않았다. 공급자 게시판의 2025년 답변은 `(symbol, date, exchange, trade_id)`의 유일성을 설명하지만 후속 제보가 이를 문제 삼았고 공개 답변만으로 최종 해결을 확인하지 못했다. 현재 표본으로 공급자 확인이 필요하다. [ID 유일성 논의](https://forum.alpaca.markets/t/which-combination-of-fields-guarantees-uniqueness-in-historical-trade-records/17728), [관측 근거](../runs/issue233-alpaca-normal-20260924-continued1/trade-contract-evidence.json)

공급자에 확인할 질문은 다음과 같다. 이 질문을 외부로 전송하지 않았다.

- `GET /v2/stocks/trades`, `feed=sip`, `asof=2026-09-11`, AAPL의 tape C·exchange D·ID 6997은 `2026-09-11T13:30:00.012356286Z`에 가격 327.388·수량 1, `2026-09-11T14:00:06.626966223Z`에 가격 332.395·수량 1로 나타나며 두 행 모두 `u`가 없다. 독립 체결인지, 공개 응답에서 보장하는 최소 유일 키가 무엇인지 확인한다.
- historical `u`의 반영 완료 시점과 `incorrect`·`corrected`의 연결 규칙, 이후 재조회에서 과거 행의 상태가 바뀔 수 있는 기간을 확인한다.
- 정규장 거래대금 집계에 필요한 timestamp와 조건 조합, 정각 이후 종가 경매 및 지연 보고를 포괄하는 조회 범위를 확인한다. XOM의 `6` 조건 행은 `2026-09-11T20:04:28.21898086Z`에 나타났다.

새 CLI·기록·재현 검사에서 취소·정정·알 수 없는 상태와 조기 폐장 경계의 세션 조건을 수정 전 실패·수정 후 통과시켰다. 기존 검사를 포함한 48개 테스트와 자체 검사·구문 검사가 통과했다. 실제 169페이지 기록을 재현했고 원본 SHA-256도 유지됐다. 정정 대체 행과 조기 폐장일은 합성 사례이며 실제 표본으로 검증한 것은 아니다. Context7은 `fetch failed`, 공식 문서의 직접 HTTP 조회는 403이어서 웹 도구로 읽은 공식 문서와 담당자 공개 답변을 사용했다.

현재는 취소 행의 표기 방식과 단순 시간 필터의 한계를 확인한 단계다. ID 식별, 정정 반영 시점, 세션 포함 규칙, 독립 합계 대조를 확정하기 전에는 20거래일 확대나 운영 순위 계산으로 승격하지 않는다.

### 최초 100페이지 수집

사용자가 발급한 키를 터미널에 직접 입력해 2026-09-11 historical SIP를 조회했다. 100페이지·1,000,000행을 281.675초에 저장했고 수집 오류는 없었다. 저장된 본문의 SHA-256과 페이지 연결을 오프라인으로 확인했다. 수집 후 검증은 `duplicate_trade_identity_requires_review`로 중단됐다. 아래의 9월 15일 준비 상태는 당시 기록이며, 현재는 실제 SIP 접근이 확인된 상태다.

| 종목 | 저장 행 수 | 관측 범위(뉴욕 시각) |
| --- | ---: | --- |
| AAPL | 972,339 | 09:30:00~16:04:55 |
| MU | 27,661 | 09:30:00~09:35:18 |
| XOM | 0 | 아직 관측하지 못함 |

이 최초 실행은 다음 페이지가 남아 있어 전체 표본 수집을 마치지 못했다. 응답은 종목, 체결 시각 순으로 정렬되며 페이지 제한은 모든 종목의 합계에 적용된다. 당시 XOM의 미관측을 거래 없음으로 해석하지 않는다. [Alpaca historical trades 명세](https://docs.alpaca.markets/us/reference/stocktrades-1)

현재 검사 키 `(symbol, tape, exchange, trade_id)`가 다시 등장한 행은 최초 행 이후 13,907개이며 모두 AAPL의 거래소 코드 D에 해당했다. 이 행들은 각 키의 최초 행과 내용이 달랐다. 예를 들어 ID 6997은 09:30:00과 10:00:06에 서로 다른 가격으로 나타났다. 이는 현재 키만으로 유일성을 가정할 수 없다는 증거이며, 같은 경제적 체결이 중복됐다는 증거는 아니다. 행을 삭제하거나 타임스탬프를 키에 추가해 정확성이 입증됐다고 간주하지 않는다. 거래대금 검증은 계속 보류한다.

원본은 변경하지 않았으며 [오프라인 진단 결과](../runs/issue233-alpaca-normal-20260924-retry2/diagnosis.json)와 [재실행 스크립트](../runs/issue233-alpaca-normal-20260924-retry2/diagnose_saved.py)를 함께 남겼다. 20거래일 확대나 조기 폐장일 추가 조회는 아직 실행하지 않았다.

### 이어받기와 보류 결과 표시

구현·검증 결과와 남은 한계를 [#233 진행 댓글](https://github.com/mochafreddo/swing-trading-report/issues/233#issuecomment-5812072307)에 게시하고, 본문의 정확 거래대금 작업 항목을 갱신했다. 본문·댓글과 OPEN 상태를 다시 읽어 확인했다. 로컬 코드·문서의 커밋과 푸시는 아직 하지 않았다.

`probe_alpaca_trades.py --resume <record.json> --output <새 폴더>`는 원본의 본문 해시·페이지 연결·날짜·종목·feed를 검사한 뒤 마지막 `next_page_token`부터 추가 조회한다. `--max-pages`는 이번 실행에서 추가할 페이지 수이며 최대 100이다. 새 기록은 이전 페이지와 추가 페이지를 모두 포함해 단독으로 재현할 수 있고, `resumed_from_sha256`로 원본을 연결한다. `elapsed_seconds`는 이전 수집 시간을 포함한다. 이미 끝난 기록이나 손상된 기록은 인증정보 입력 전에 거절한다. 서버가 기존 페이지 토큰을 거절하면 오류를 기록하고 멈추며 처음부터 자동 재조회하지 않는다. 저장 토큰은 위 후속 실행에서 실제로 작동했으며 장기 유효 기간을 검증한 것은 아니다.

ID 충돌은 원문 행을 모두 보존하면서 `identity_recurrences`와 `validation_issues`에 표시한다. 충돌 종목과 미관측 종목의 `returned_row_amount_usd`는 `null`이며 나머지 값도 부분 응답의 진단 합계일 뿐이다. `collection_status`는 수집 완료·페이지 상한·중단·실패·진행 중을 구분하고, `validation_status=held`와 `exact_regular_turnover_verified=false`는 유지한다. 자료를 끝까지 받았다는 사실만으로 정확 거래대금 검증을 통과시키지 않는다.

새 코드로 기존 100만 행을 오프라인 재현해 `page_limit_reached`, AAPL/D 식별자 충돌 13,907건, 검증 보류를 확인했다. 원본 SHA-256은 `a9bd9706f7ac72fcc703cd26b32d5a829fdf5ceb70d52f84f280e3d373f4dbf2`로 수정 전후 동일했다. [변경 후 요약](../runs/issue233-alpaca-normal-20260924-retry2/summary-after-resume-fix.json)

CLI·기록·재현 경계의 새 테스트 6개와 기존 테스트를 합친 46개가 통과했다. 충돌 시 요약 중단, 이어받기 미지원, 요청 범위 변경 허용, 진행 중 기록의 실패 오분류는 수정 전 실패·수정 후 통과를 확인했다. 본문 해시 검증을 제거한 대조에서도 손상 기록 거절 테스트가 실패했다. 이어받기 요청과 중단·시간 초과·HTTP 오류는 합성 응답 검증이며, 실제 인증 조회는 추가로 실행하지 않았다.

공식 REST 명세는 페이지 토큰과 정렬을 설명하지만 이번에 관측한 ID 충돌의 해석을 확정할 근거는 확보하지 못했다. 실시간 API의 정정·취소 메시지 명세를 historical 응답의 정정 상태 보증으로 사용하지 않는다. 봉의 거래량과 VWAP에 포함되는 체결 범위도 다르므로 `v × vw`로 대체하지 않는다. [REST 명세](https://docs.alpaca.markets/us/reference/stocktrades-1), [실시간 정정·취소 명세](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), [집계 규칙](https://docs.alpaca.markets/us/docs/market-data-faq)

완료한 정상일 기록은 다음 명령으로 인증정보나 네트워크 없이 재현한다.

```sh
python3 probe_alpaca_trades.py --replay runs/issue233-alpaca-normal-20260924-continued1/record.json
```

체결 식별·정정·세션 적격성 검증은 계속 남아 있다. 세 종목 표본을 넘어 대량 수집으로 확대하기 전에는 페이지마다 전체 기록을 다시 쓰는 저장 방식도 증분 저장으로 바꿔야 한다. #233 전체 변경에 대한 최종 리뷰와 실제 전체 종목 실행은 이 단계의 검증에 포함되지 않는다.

## 2026-09-15 표본 검증 기록

2026-09-15에 승인한 세 가지 표본 검증 중 공개 목록과 기업 IR의 실제 조회를 수행했다. Alpaca는 사용자가 계정과 API 키가 없다고 확인했으므로 실제 조회를 하지 않았다. 목록 대조는 재현 가능한 보조 검증으로 사용할 수 있지만, 토스 목록의 완전성 문제를 해결하지는 못했다. 현재의 제한된 정적 IR 파서도 전체 종목 수집 경로로 채택하기에는 부족하다. #233은 미완료다.

| 경로 | 실행한 검증 | 채택 판단 |
| --- | --- | --- |
| 전체 목록 | 저장된 토스 세 실행 분석, Nasdaq 공식 디렉터리 2개 실제 조회, 7종목 대조 | 충돌 검출 경로로 사용 가능. 공급자 상태·종목 유형의 불일치를 자동 보정할 근거는 부족 |
| 기업 IR | 10개 기업 공식 목록과 관련 링크 조회 | MU의 미래 발표 예고 후보 1개 확보. 전체 종목의 확정 다음 발표일 수집 경로로는 아직 부족 |
| Alpaca 체결 | 조회 스크립트 준비, 합성 입력 검사 | 실제 접근·세션 집계·정정 반영·정확한 거래대금·처리량 모두 미검증. 계정·키 준비 대기 |

설계 결정은 [조사 문서](issue-233-data-research.md)와 [ADR-0002](adr/0002-verified-exclusion-before-remaining-collection.md)에 있다. 이 실험은 후보 선정·보고서 생성의 운영 구현을 변경하지 않는다.

2026-09-15에 [#233 본문](https://github.com/mochafreddo/swing-trading-report/issues/233)에 합의한 정책과 남은 작업을 반영하고, [진행 댓글](https://github.com/mochafreddo/swing-trading-report/issues/233#issuecomment-5673598456)에 검증 결과·한계·실험 코드의 로컬 미게시 상태를 기록했다. 게시한 본문과 댓글의 일치 및 OPEN 상태를 확인했다.

## 목록 대조

[검증 스크립트](../probe_universe_data.py)는 토스의 기존 공개 응답만 읽고, 현재 운영 코드의 목록 탐색 함수로 불일치를 다시 확인한다. 토스 인증 조회나 토큰 발급은 수행하지 않았다. 비교용 Nasdaq 디렉터리 조회는 2회·2.913초였다. Nasdaq 파일은 5,604행, 다른 거래소 파일은 7,616행이며 두 파일의 생성 표시는 `0914202621:31`이다. 클라이언트 조회 시각은 각각 2026-09-15T01:53:00.476731+00:00, 01:53:01.772621+00:00다. 파일 생성 표시와 클라이언트 조회 시각을 동일 시각으로 취급하지 않는다.

| 충돌 종목 | 저장된 토스 응답 | 조회한 공식 디렉터리 |
| --- | --- | --- |
| CPOP·IPDN·NFE·NXXT | Nasdaq 일반 목록에 포함, STOCK 목록에 없음, 상세 DELISTED | Nasdaq에 존재, ETF·테스트 종목 아님, Financial Status D |
| HUBC | Nasdaq 일반 목록에 포함, STOCK 목록에 없음, 상세 DELISTED | Nasdaq에 존재, ETF·테스트 종목 아님, Financial Status N |
| KHC | Nasdaq 일반 목록에 포함, STOCK 목록에 없음, 상세 DELISTED | 다른 거래소 파일의 NYSE 종목으로 존재 |
| PSNYW | Nasdaq 일반 목록의 STOCK, STOCK 목록에 없음, 상세 ACTIVE | Nasdaq 종목명에 Class C-1 ADS (ADW) 표시 |

공식 디렉터리의 Financial Status D는 상장 유지 요건 미충족을 뜻하며, 그 자체가 상장폐지를 뜻하지 않는다. 디렉터리의 상장·유형 정보를 토스의 거래 가능 여부로 대신할 수도 없다. [Nasdaq 필드 정의](https://nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs)

Kraft Heinz는 2026-08-26 공지에서 KHC의 NYSE 거래를 2026-09-14부터 시작할 예정이라고 발표했다. 현재 디렉터리의 NYSE 분류는 이 이전 일정과 부합한다. 따라서 저장 응답의 Nasdaq DELISTED를 회사 주식 전체의 상장폐지로 해석하면 안 된다. 다만 이 자료로 당시 토스의 NYSE 거래 지원이나 공급자 내부 갱신 시각까지 확인한 것은 아니다. [Kraft Heinz 공식 이전 공지](https://ir.kraftheinzcompany.com/news/kraft-heinz-to-transfer-stock-exchange-listing-to-nyse/0f3f933b-8f7f-4c91-a860-0cb6457f9d6f)

Polestar의 공식 공지도 PSNYW를 Class C-1 ADS로 구분한다. 이는 토스 응답의 STOCK·보통주 분류를 추가 검증해야 할 근거다. 종목명의 W 접미사만으로 유형을 판정하거나 다른 예탁증서를 탐색 대상에 자동 편입하지 않는다. [Polestar 공식 ADS 공지](https://investors.polestar.com/news-releases/news-release-details/polestar-announces-date-implementation-ads-ratio-change-11-130)

두 기업 공지는 공식 웹 페이지 조회로 읽었다. 별도 Python GET에서 KHC는 기사 본문이 없는 JavaScript 앱 HTML만 반환했고, Polestar 요청은 시간 초과였다. 이 별도 요청을 기사 본문의 자동 수집 성공으로 세지 않는다. 공식 디렉터리의 시점도 토스의 9월 14일 장전 응답보다 늦으므로 차이를 과거 상태로 소급 보정하지 않는다.

실제 저장 응답에서 7종목 차이와 상세 상태 충돌 6개를 확인했다. 일반 목록에서 AAPL 한 행을 제거한 대조 자료에서는 새 차이가 검출되어 원래 결과와 같아야 한다는 검사가 실패했다. 공식 디렉터리의 마지막 행 누락과 중복 심볼도 거절했다. 저장한 디렉터리로 네트워크 없이 재실행한 결과는 원래 분석·비교·검사 결과와 같았다.

- [실제 목록 기록](../runs/issue233-listing-probe-20260915/record.json)
- [오프라인 재실행 기록](../runs/issue233-listing-probe-replay-20260915/record.json)

## 기업 IR 표본

최종 실행은 2026-09-15T01:56:58.463475+00:00를 기준으로 22회 GET·16.506초였다. 10개 목록, NVIDIA의 Next 페이지 1개, 실적 관련 링크 11개를 조회했다. 링크에는 일반 분기실적 탐색 페이지도 포함되며, 모두 개별 발표 예고 기사는 아니다.

| 기업 | 목록 HTTP | 발견 링크 | 미래 발표 예고 후보 | 과거 결과 기사 |
| --- | --- | --- | --- | --- |
| MU | 200 | 2 | 1 | 0 |
| NVDA | 200 | 1 | 0 | 0 |
| AAPL | 200 | 0 | 0 | 0 |
| MSFT | 200 | 1 | 0 | 0 |
| AMZN | 200 | 1 | 0 | 0 |
| GOOGL | 200 | 1 | 0 | 0 |
| META | 200 | 1 | 0 | 0 |
| JPM | 200 | 1 | 0 | 0 |
| XOM | 200 | 3 | 0 | 2 |
| COST | 200 | 0 | 0 | 0 |

MU에서 2026-09-30 예고 후보를 추출했고 XOM의 2026-05-01·2026-07-31 발행 결과 기사는 과거 공지로 구분했다. 다른 9개 기업의 실적 일정이 없다는 결과는 아니다. 목록은 추가 한 페이지, 관련 링크는 기업당 최대 4개로 제한했고 JavaScript로 채워지는 목록은 처리하지 않았다. MU 역시 전체 공지와 이후 취소·변경을 확인한 것은 아니므로 이 실험의 상태는 `confirmed_candidate`이며 운영용 확정 다음 발표일의 증거로 승격하지 않는다.

현재 [IR 스크립트](../probe_earnings_sources.py)의 합성 검사에는 정상 예고 1개, 거절 사례 9개, 과거 사례 2개, 뉴욕 날짜 경계 사례 1개가 있다. 불확실성 가드를 제거하면 예상 공지 거절 검사가 실패한다. 검토 중에는 날짜만 있는 공지를 UTC 날짜로 비교하는 오류를 추가로 재현했다. 뉴욕에서 아직 같은 날짜인 경우 발행 시각이 미확인이라는 검사가 수정 전 실패하고 수정 후 통과했다. 실제 연기 공지는 이 표본에서 확보하지 못했으며 연기 거절은 합성 검증이다.

최종 수집 당시 코드로 오프라인 재현이 일치했다. 날짜 경계를 수정한 코드로 같은 저장 응답을 다시 분류한 결과도 모두 같았다. 원래 코드와 수정 코드는 구분해 보존했다. 최초 Alphabet 주소의 404와 이후 주소·메타데이터 보완을 포함한 세 번의 실행은 총 63회 GET이며, 위 표와 16.506초는 최종 실행만의 수치다.

- [기업별 원문·발견 경로·검사 상세](../runs/issue233-ir-probe-20260915/SUMMARY.md)
- [최종 수집 기록](../runs/issue233-ir-probe-20260915/final/record.json)
- [수정 후 재분류 결과](../runs/issue233-ir-probe-20260915/reclassification.json)

## Alpaca 준비 상태

사용자는 2026-09-15에 계정과 API 키가 없다고 답했다. [체결 검증 준비 스크립트](../probe_alpaca_trades.py)는 키 준비 뒤 숨김 입력으로 인증하고 historical SIP GET만 수행하도록 작성했다. 자격 증명을 인자·파일·환경변수로 받거나 토큰을 발급하는 경로는 없다. 이번에는 숨김 입력과 인증 GET 자체도 실행하지 않았다.

첫 실제 표본은 MU·AAPL·XOM의 2026-09-11 정상일과 2025-11-28 조기 폐장일로 고정했다. 후자의 13시 마감은 NYSE 공식 일정에 근거한다. 날짜는 표본 설정이며 일반 거래일 계산을 대체하지 않는다. [NYSE 2025~2027 일정](https://s2.q4cdn.com/154085107/files/doc_news/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar-2024.pdf)

스크립트는 정규장 시작부터 마감 5분 뒤까지 조회해 마감 전후 체결과 조건을 관찰하며 최대 100페이지에서 멈춘다. 다음 페이지가 남으면 불완전으로 표시한다. 마감 뒤 5분은 진단용 표본 범위로, 모든 지연 보고를 포함한다는 가정이 아니다. 반환 행의 가격×수량 합계는 진단값이며 정규장 적격 거래대금으로 사용하지 않는다. 페이지 연결·중복 식별자·조건을 검사해도 공급자의 취소·정정 반영, 체결 식별자의 유일성 계약, 세션 적격성이나 원천 누락까지 입증하지 못한다. [Alpaca historical trades 명세](https://docs.alpaca.markets/us/reference/stocktrades-1)

합성 검사에서 IEX 대입, 중복 체결, 잘못된 수치, 봉의 VWAP 대입, 페이지 토큰 필드 누락·순환, 다음 페이지 누락의 7개 대조를 검출했다. 정상일과 조기 폐장일의 마감 시각 체결을 관찰에 남기는 사례도 확인했다. 이 검사는 실제 무료 계정 권한이나 정확한 거래대금 검증을 대신하지 않는다. 모든 결과의 `exact_regular_turnover_verified`는 false이며 실제 일별 집계가 검증되기 전에는 20거래일로 확대하지 않는다.

## 재실행과 다음 판단

저장소 루트에서 공개 자료·합성 검사를 다음과 같이 재실행한다. 목록 실험의 출력 경로는 새 디렉터리여야 한다.

```sh
python3 probe_universe_data.py --records runs/issue233-preflight-20260914/record.json runs/issue233-preflight-revised-20260914/record.json runs/issue233-live-revised-20260914/record.json --directories-from runs/issue233-listing-probe-20260915/record.json --output runs/issue233-listing-probe-replay-new
python3 probe_earnings_sources.py --self-check
python3 runs/issue233-ir-probe-20260915/final/probe_source.py --replay runs/issue233-ir-probe-20260915/final
python3 probe_alpaca_trades.py --self-check
```

Alpaca 계정·키 준비와 사용 승인이 완료된 뒤에만 다음 명령의 실제 조회를 수행한다. 기존 출력 디렉터리는 거절하며 API 키와 비밀키는 터미널의 숨김 입력으로 받는다.

```sh
python3 probe_alpaca_trades.py --day 2026-09-11 --output runs/issue233-alpaca-normal
python3 probe_alpaca_trades.py --day 2025-11-28 --output runs/issue233-alpaca-early
```

다음 판단은 IR의 동적 목록과 추가 공지 범위를 처리할 수 있는 경로, 토스 목록 충돌을 해소할 최신 근거, Alpaca 계정 준비 후의 실제 체결 검증에 달려 있다. 표본에서 실패한 경로를 운영 코드에 바로 통합하거나 보류를 감춰 #233을 완료 처리하지 않는다. 런타임 코드·기존 계산 계약을 변경하지 않았으므로 기존 40개 운영 테스트는 반복하지 않았고, 새 스크립트의 자체 검사·오류 주입 대조·오프라인 재현·구문 검사를 실행했다. 모든 공개 원문 기록은 Git에서 제외된 `runs/`에 있으므로 다른 환경에서 재실행하려면 함께 복사해야 한다.
