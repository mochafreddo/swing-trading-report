# #233 증거 범위 검증

이 문서는 2026-10-10에 합의한 IR 증거 범위와 거래대금 관측 시점 기준의 구현·검증 결과를 설명한다. #233은 미완료 상태다. 정확한 거래대금에 필요한 공급자 계약과 독립 달러 대조, 실제 후보가 포함된 전체 실행의 증거는 아직 확보하지 못했다.

## 실제 공개 IR 자료

Repligen의 공식 Q4 보도자료 목록을 필터 없이 끝까지 수집했다. 공급자 건수와 중복 없는 수집 건수는 각각 368건이며, 본문이 비어 있던 PDF 원문 106건도 공식 CDN에서 직접 읽었다. Quarterly Results 페이지가 같은 보도자료 자료원의 earnings·financials 태그를 사용하는 연결도 확인했다. 총 요청은 184건이다. 인증정보는 사용하지 않았다.

관측 시점의 다음 확정 발표일은 찾지 못해 `next_confirmed_earnings_not_found`로 보류했다. 이 결과는 Repligen의 공개 자료원 범위 확인이며 전체 종목군의 실적 경로 지원이나 실제 선정 후보를 입증하지 않는다. 삭제된 공지나 별도 비공개 연락은 검증 범위 밖이다. CDN 접두사 매핑은 관측한 공식 PDF 이동 경로를 지원하는 규칙이며 모든 가능한 과거 URL의 이동을 입증한 것은 아니다.

공개 원문·요청 시각·판정과 당시 코드·계약은 Git에서 제외된 `runs/issue233-rgen-scope-20261010/`에 보존했다. `python3 -B runs/issue233-rgen-scope-20261010/replay_ir.py`로 네트워크 없이 184개 응답을 재생해 같은 판정과 보고서를 확인했다. 이는 전체 종목 실행이 아닌 IR 수집 경계의 기록·재현 검사다. PDF 추출에는 설치된 `pdftotext`가 필요하며, 도구 상태나 추출 결과가 달라지면 재현은 거절된다.

## 자동 검사

전체 실행→보고서·기록·오프라인 재현과 공식 IR 수집→일정 판정의 두 경계를 검사한다. 합성 자료를 사용하는 기업별 범위 검토 설정은 테스트용이며 실제 출처 검토 증거로 사용하지 않는다. PDF가 후보 판정과 보고서·기록·재현까지 이어지는 전체 실행 검사는 외부 추출 프로세스를 모의한다. 실제 PDF 추출은 위 공개 IR 실행으로 별도 확인했다.

전체 단위 테스트 142개와 Alpaca·IR 프로브 자체 검증, Ruff 린트·포맷 및 actionlint가 통과했다. 기존 음성 대조 121개도 모두 정상 구현의 통과와 오류 구현의 실패를 확인했다.

건수 대조 무시, 발행사 자료 연결 검증 생략, PDF 원문 대신 임의 텍스트 사용의 세 오류를 `mutation-probe.py`로 주입했다. 같은 환경에서 정상 구현은 통과하고 각 변형은 실패했다. 원본 소스는 변경되지 않았다.

정적 타입 검사기는 설치되어 있지 않아 실행하지 않았다. 새 패키지는 설치하지 않았다. 공급자 역사적 체결의 고유성·취소·정정·지연 보고 계약과 같은 정규장 범위의 독립 달러 대조는 확인되지 않았다. 거래대금 하한 미달과 정확한 거래대금이 필요한 동률은 계속 보류한다.

## 근거

- [Repligen 보도자료](https://investors.repligen.com/press-releases/default.aspx), [Quarterly Results](https://investors.repligen.com/financials/quarterly-results/default.aspx)
- [Q4 목록 API](https://studioapi.q4inc.com/adhc/getpressreleaselist), [목록 건수 API](https://studioapi.q4inc.com/adhc/getpressreleaselistcount), [필터 형식](https://studioapi.q4inc.com/adhc/types)
- [IR 증거 범위 결정](adr/0003-earnings-evidence-scope.md), [거래대금 관측 시점 결정](adr/0004-turnover-evidence-at-observation-time.md)

## 코드 리뷰

`code-review` 스킬에 따라 Standards와 Spec을 독립적인 읽기 전용 `reviewer`에게 병렬로 맡겼다. 요청 추론 수준은 기본값 `high`이며 조정하지 않았다. 도구는 작업 경로만 반환했으므로 역할 선택 상태는 `dispatched-unverified`다. 실제 모델·추론 수준과 권한 강제 여부는 확인하지 못했다. 검토자는 파일을 수정하지 않았다고 보고했으며 구현·검증 책임은 주 세션이 유지했다.

Standards 검토의 함수 설명 개선은 반영했고 새 로직의 음성 대조 근거도 확인했다. Spec 검토의 PDF 전체 실행 경계 검사 권고와 외부 추출 도구 제약 설명을 반영했다. 차단할 새 구현 결함은 발견하지 않았지만 정확한 거래대금과 실제 후보 실행이라는 #233 완료 조건은 여전히 남아 있다. 두 검토 모두 모든 이력 변경의 완전 검토나 전체 테스트 재실행을 주장하지 않는다.
