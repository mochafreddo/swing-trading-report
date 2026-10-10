# #233 거래대금 무료 대안 조사

2026-10-10에 [ADR-0004](adr/0004-turnover-evidence-at-observation-time.md)의 거래대금 계약을 만족할 수 있는 무료 대안과 별도 공급자의 독립 집계 자료를 조사했다. 공식 문서로 접근 조건과 검증의 빈틈을 확인한 조사이며, 신규 계정·인증 조회·체험 활성화·유료 신청·외부 문의는 수행하지 않았다. 기존 Alpaca 실제 SIP 표본과 미해결 사항은 [데이터 경로 검증](issue-233-data-probe.md)에 기록되어 있다.

## 확인한 후보 경로

| 경로 | 공식 문서에서 확인한 접근 조건 | 정확성 검증의 남은 조건 | 현재 판단 |
| --- | --- | --- | --- |
| Alpaca historical SIP | Basic은 무료이며 historical 요청의 `end`가 15분 이상 과거이면 SIP를 구독 없이 조회할 수 있다고 설명한다. 체결 조회는 조건·시각·페이지 토큰을 제공한다. [요금·접근](https://docs.alpaca.markets/us/docs/about-market-data-api), [FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), [조회 명세](https://docs.alpaca.markets/us/reference/stocktrades-1) | 관측 시점까지의 취소·정정·지연 보고 반영 계약, 충돌 식별자 해석, 경매 포함 세션 규칙과 같은 기준의 독립 달러 대조가 미확정이다. 무료 접근 조건은 정확성 보증이 아니다. | 기존 경로의 계약 확인을 계속한다. 이미 수집한 표본을 검증하기 전 20거래일 대량 조회로 확대하지 않는다. |
| Massive(Polygon) | Stocks Basic은 무료지만 체결 단위 자료는 포함하지 않는다. 체결 조회는 상위 요금제에서 제공한다. [요금표](https://massive.com/pricing?product=stocks), [체결 조회](https://massive.com/docs/rest/stocks/trades-quotes/trades) | 취소 체결이 정정 표시와 함께 피드에 남고 일말 집계는 취소를 반영한다는 설명은 있지만, 요구한 관측 시점·정규장 달러 집계 계약까지 확인한 것은 아니다. [취소 체결 설명](https://massive.com/knowledge-base/article/how-much-does-massives-feeds-handle-canceled-trades) | 확인한 무료 요금제는 체결 합산 대안이 아니다. 유료 경로 채택은 별도 비용 결정과 정확성 검증이 필요하다. |
| Databento | 신규 계정의 historical credit은 일회성이고 만료된다. historical 자료는 사용량에 따라 과금한다. [요금·credit 조건](https://databento.com/pricing/), [FAQ](https://databento.com/docs/faqs) | `EQUS.MINI`는 개별 거래소 피드에서 구성한 자료이므로 SIP 전체 범위를 대신하지 않는다. 요구 범위의 SIP 자료 권한·견적, 세션·정정·관측 시점 계약은 미검증이다. [MINI 자료 정의](https://databento.com/docs/venues-and-datasets/equs-mini), [자료 목록](https://databento.com/docs/knowledge-base/datasets) | 지속적인 무료 자료원으로 채택하지 않는다. 일회성 독립 대조 가능성은 정확한 자료 종류·계약·견적을 확인한 뒤 판단한다. |

KIS·토스에서 별도 전시장 정규장 달러 합계를 제공하는지에 대한 최신 계약 조사는 이번 범위에 포함하지 않았다. 기존 KIS 분봉 하한을 정확한 합계나 독립 대조 자료로 승격하지 않는다. 이 조사는 모든 무료 자료원의 불가능성을 입증하지 않는다.

## 다음 검증 경계

경로별로 정규장 적격 체결, 개장·종가 경매, 유효 체결 식별, 취소·정정·지연 보고의 관측 시점 반영 계약을 먼저 확인한다. 별도 공급자의 독립 집계 자료는 같은 SIP 원천이어도 허용하지만, 세션·체결 조건·정정 기준이 같고 별도 집계라는 근거가 있어야 한다. 같은 공급자의 다른 API나 같은 응답의 재계산은 독립 대조가 아니다.

계약과 독립 대조 자료의 확보 가능성이 확인된 경로만 작은 표본으로 확인한 뒤 대량 수집으로 확대한다. 조사한 후보에서 확인되지 않은 계약은 미확인으로 남긴다. 공급자 무응답이나 문서 누락만으로 무료 경로가 불가능하다고 결론 내리지 않는다. 비용이나 요구사항을 변경할 필요가 입증되면 사용자와 별도 결정한다.

## 조사 도구와 한계

Context7의 Alpaca 검색은 `fetch failed`로 끝났다. 지정된 도구 runbook을 확인한 뒤 공식 공급자 문서를 웹으로 조회했다. 도구 오류는 공급자의 기능 부재 근거로 사용하지 않았다. 읽기 전용 `file_scout`에 요청한 추론 수준은 여러 공급자의 계약을 비교하기 위한 `medium`이다. 역할 선택은 도구 결과에 표시되지 않아 `dispatched-unverified`이며 실제 모델·추론 수준과 권한 강제 여부는 확인하지 못했다. 위 조사에는 실제 달러 기준값 확보·대조나 제공자 채택의 증거가 없다.
