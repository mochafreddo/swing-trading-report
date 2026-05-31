# Changelog

## [1.33.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.33.0...v1.33.1) (2026-05-31)


### Bug Fixes

* **ci:** mise 런타임 버전을 갱신한다 ([39b565e](https://github.com/mochafreddo/swing-trading-report/commit/39b565ecbe6bfd11330d926e386da4797e482d08))
* **config:** 설정 로드와 Ruff 범위를 바로잡는다 ([546b34e](https://github.com/mochafreddo/swing-trading-report/commit/546b34e1b9d245b5dd5eae7e587450fa61bed53b))
* **toolchain:** pnpm 11 lockfile을 보강한다 ([b99db2d](https://github.com/mochafreddo/swing-trading-report/commit/b99db2d99f68c0d827f9a3c6aa02aa39ff8d0213))
* **web:** pnpm override 적용 위치를 바로잡는다 ([2f67b48](https://github.com/mochafreddo/swing-trading-report/commit/2f67b48d8cd191b2abf1ab3c0f38759bc2ae8363))
* **web:** 웹 의존성 갱신 CI 실패를 복구한다 ([af55300](https://github.com/mochafreddo/swing-trading-report/commit/af553006bf95162543733eed6f4204ac824abd8a))
* **web:** 직접 실행 바인드 가드 우회를 막는다 ([251b894](https://github.com/mochafreddo/swing-trading-report/commit/251b894b65a210948a437d3251bae34c9d1e0a34))


### Documentation

* 문서 구조와 설정 참조 정리 ([a5e1c47](https://github.com/mochafreddo/swing-trading-report/commit/a5e1c4739c893b2a2a703d4bdb544cbd8327b6eb))

## [1.33.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.32.3...v1.33.0) (2026-05-31)


### Features

* **ai-brief:** runtime guard skip 아티팩트 저장 ([9b0009d](https://github.com/mochafreddo/swing-trading-report/commit/9b0009d1bf0cfffd800939bf70a9f40f67dfbbf3))
* **scheduler:** 로컬 Docker AI Brief 스케줄러 구현 ([d538546](https://github.com/mochafreddo/swing-trading-report/commit/d538546464a613a9b595f42908feaa4f555ecb1c))


### Bug Fixes

* **calendar:** KR 휴장일 현재연도 보강 누락 수정 ([24ffe27](https://github.com/mochafreddo/swing-trading-report/commit/24ffe277f59e840ac06b1c4817035223658d9d70))
* **ci:** cleanup 워크플로 입력 검증 강화 ([898af8a](https://github.com/mochafreddo/swing-trading-report/commit/898af8ab43e3182f933a68a24672a35268d11596))
* **entry:** 치명적 가격 누락 리포트 업로드 방지 ([97d0c7e](https://github.com/mochafreddo/swing-trading-report/commit/97d0c7e20e9e03683719a12ea65fe9a076445b37))
* **report:** 잘못된 리포트 JSON 업로드 차단 ([4b80c47](https://github.com/mochafreddo/swing-trading-report/commit/4b80c471570bb96ddede75e147df66567aabd430))
* **scan:** KR KIS 스크리너 장애 시 평가 계속 ([8f4eae1](https://github.com/mochafreddo/swing-trading-report/commit/8f4eae10779ed0bac95ff693b1267cb63102a152))
* **scan:** 스윙 로직 경계와 리포트 재현성 보강 ([a1f714a](https://github.com/mochafreddo/swing-trading-report/commit/a1f714a842bb9db496f8282fda8936cd573404e6))
* **scan:** 스윙 평가 기준 정렬 ([b1f292e](https://github.com/mochafreddo/swing-trading-report/commit/b1f292ed27813a585b9051a61992942640d8fdef))
* **scheduler:** Docker 실행 이미지와 venv 격리 수정 ([61b7e6c](https://github.com/mochafreddo/swing-trading-report/commit/61b7e6cc3d6a5a3ba49c3068ea056f09fb6ed7db))
* **scheduler:** 런타임 락 만료 기준을 DB 시간으로 고정 ([822fbb3](https://github.com/mochafreddo/swing-trading-report/commit/822fbb3e78ab2bcb37db35349a13bf90196618f5))
* **scheduler:** 로컬 Docker 스케줄러 리뷰 이슈 해결 ([35851d0](https://github.com/mochafreddo/swing-trading-report/commit/35851d0a797abf4578bc0e0726b84b31fec713de))
* **scheduler:** 예약 AI Brief 산출물 경로를 명시적으로 추적 ([f4535bc](https://github.com/mochafreddo/swing-trading-report/commit/f4535bccbbcaf4b1226d740677d57b81d70654fc))
* **signals:** 스윙 평가 경계 조건 보정 ([4f8b179](https://github.com/mochafreddo/swing-trading-report/commit/4f8b1795e8388472a30b2aae70ea71aa057bdd1d))
* **signals:** 지표 미계산을 시스템 이슈로 분리 ([bbc7589](https://github.com/mochafreddo/swing-trading-report/commit/bbc75894af18331b55b18be40fcb71cb4e94b0a2))
* **strategy:** 스윙 가드 경계 조건 보정 ([74c5d12](https://github.com/mochafreddo/swing-trading-report/commit/74c5d12ad93b20ecae9b01ea3699460a78b18be6))
* **validation:** 리뷰 findings를 해결한다 ([783ff06](https://github.com/mochafreddo/swing-trading-report/commit/783ff06b577633ed5ea935d9ef7cf40d64565026))
* **web:** 로컬 바인딩 가드와 폰트 빌드를 결정적으로 정리 ([92c0da8](https://github.com/mochafreddo/swing-trading-report/commit/92c0da88d15f980ddbbe61aa0514b9dbef7b0474))
* **web:** 보유목록 YAML 숫자 검증 강화 ([0cd5dbd](https://github.com/mochafreddo/swing-trading-report/commit/0cd5dbd5f86b57274feefd49df33e5512db8176c))
* **web:** 티커 디렉터리 캐시 갱신 보정 ([9f3a710](https://github.com/mochafreddo/swing-trading-report/commit/9f3a71094dfdebc2708eef27dd4fe3f04b35c7cc))


### Documentation

* **agents:** AGENTS.md에 Project Overview 추가 ([a57a42f](https://github.com/mochafreddo/swing-trading-report/commit/a57a42f41c19d9846606ade1434d1a38a0cc6087))
* **env:** MIN_HISTORY_BARS env 오버라이드 예시 추가 ([2efb784](https://github.com/mochafreddo/swing-trading-report/commit/2efb784b1ab9f8f0b657c9989aa6a01dbd1a49f5))
* **index:** Codex 팀 가이드를 저장소 운영 문서로 재분류 ([90ab06c](https://github.com/mochafreddo/swing-trading-report/commit/90ab06ce4583caa8d3525450698bce74c8541e97))
* **index:** docs/README.md에 독자별 시작 지점 안내 추가 ([c34b8bc](https://github.com/mochafreddo/swing-trading-report/commit/c34b8bc584db20fbc3035ecea60b9c878da7e238))
* **readme:** AI Brief provider 중복 문단 축약 ([2b1b55c](https://github.com/mochafreddo/swing-trading-report/commit/2b1b55c426d5be5f2fa011d8b315823816a2e27f))
* **runbook:** 분기 보호 체크명 정정과 웹 헬스체크·장애 참조 보강 ([a520bf5](https://github.com/mochafreddo/swing-trading-report/commit/a520bf588727aac50b2df743a9e506a4d88779e8))
* scheduled AI Brief·CLI·전략 문서를 현재 구현과 동기화 ([6311312](https://github.com/mochafreddo/swing-trading-report/commit/6311312bfcb5f031739d7fba29d8d2a8a6f76b5e))
* **todo:** 리팩토링 후속 과제 기록 ([8454610](https://github.com/mochafreddo/swing-trading-report/commit/845461062b6074d526f6d41075b923891e4bdfda))

## [1.32.3](https://github.com/mochafreddo/swing-trading-report/compare/v1.32.2...v1.32.3) (2026-05-27)


### Bug Fixes

* **strategy:** 스윙 로직 보강 ([cd38e57](https://github.com/mochafreddo/swing-trading-report/commit/cd38e57105701eac971d16f8a0cd4bdb5dab82bf))
* **strategy:** 스윙 진입·매도 가드 정정 ([224e753](https://github.com/mochafreddo/swing-trading-report/commit/224e753b997450d07d97a0170785409adec33c27))

## [1.32.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.32.1...v1.32.2) (2026-05-27)


### Bug Fixes

* **ai-brief:** 미국 장전 스케줄 지연 대응 ([22e50ff](https://github.com/mochafreddo/swing-trading-report/commit/22e50ffe981f023dc10993006a275727d2b5e7ea))
* **signals:** 스윙 돌파 RSI 미산출 후보를 차단 ([62df475](https://github.com/mochafreddo/swing-trading-report/commit/62df4751e3a29498663f020ebb017b80bcd899c6))
* **strategy:** 스윙 로직 경계 검증 강화 ([c62fd8c](https://github.com/mochafreddo/swing-trading-report/commit/c62fd8c8bbeb9c35b66316f6f743930ce936e010))
* **strategy:** 스윙 로직 데이터 기준 보정 ([a9bc17e](https://github.com/mochafreddo/swing-trading-report/commit/a9bc17ef1f725f9d81f031cb8c8695dde4320bd1))
* **strategy:** 스윙 진입 신호 가드 보강 ([8764926](https://github.com/mochafreddo/swing-trading-report/commit/8764926480fca3442ff0f974234606988759f8f8))


### Documentation

* **config:** 하이브리드 전략 샘플 설정을 정리 ([3897b8f](https://github.com/mochafreddo/swing-trading-report/commit/3897b8f28aacb2b0fd7b2aa8eef58696128acc05))

## [1.32.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.32.0...v1.32.1) (2026-05-23)


### Documentation

* **ai-brief:** US 기본 소스 제공자를 Finnhub로 확정 ([608c980](https://github.com/mochafreddo/swing-trading-report/commit/608c980b2f07dcc215c009391e390a62b10d5570))
* **todo:** 작업 문서 정리 ([11ea0c7](https://github.com/mochafreddo/swing-trading-report/commit/11ea0c7203a3f4534adec85274327844fc2b27fc))

## [1.32.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.31.1...v1.32.0) (2026-05-22)


### Features

* **ai-brief:** 브리프 판단 상태를 명시한다 ([#161](https://github.com/mochafreddo/swing-trading-report/issues/161)) ([acbb8d2](https://github.com/mochafreddo/swing-trading-report/commit/acbb8d2123d8a89a8861dc22a77f7c96b0bcb243))


### Bug Fixes

* **notification:** AI Brief 빈 추천 사유 표시 ([93ae5e2](https://github.com/mochafreddo/swing-trading-report/commit/93ae5e2b69d26b22cf0cc0ab68253938e33d1605))
* **notification:** 텔레그램 알림을 생략 없이 전송 ([47296c8](https://github.com/mochafreddo/swing-trading-report/commit/47296c80c033849cf8cfa8f203e1d667cceec3fb))


### Documentation

* **ai-brief:** US 소스 제공자 검증 결과 문서화 ([82756bc](https://github.com/mochafreddo/swing-trading-report/commit/82756bc376fdc9f5173cac80936b8f2608ede32c))
* **ai-brief:** US 소스 제공자 재검증 결과 추가 ([ed691cd](https://github.com/mochafreddo/swing-trading-report/commit/ed691cdf7fa90a16aea84c5dea8941cda2de910e))

## [1.31.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.31.0...v1.31.1) (2026-05-20)


### Bug Fixes

* **ci:** requests 타입 검사 실패 수정 ([5154de0](https://github.com/mochafreddo/swing-trading-report/commit/5154de0a8593472ad94989ec7ffe8e1b70c55feb))

## [1.31.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.30.2...v1.31.0) (2026-05-15)


### Features

* **ai-brief:** scheduled run에서 빈 watchlist 결과를 success로 처리한다 ([5219a1e](https://github.com/mochafreddo/swing-trading-report/commit/5219a1e873e2c07adb85903597e95c80d25a8061))
* **ai-brief:** scheduled source provider를 시장별로 분리한다 ([df6a999](https://github.com/mochafreddo/swing-trading-report/commit/df6a9992731e7f092f7e1764b5445c0d39747f71))


### Documentation

* **todos:** AI Brief에 design doc origin 노트 추가 ([e5b677b](https://github.com/mochafreddo/swing-trading-report/commit/e5b677b29e97bf17531b4161db4e6fad68630b45))
* **todos:** Phase 2 목표와 완료 조건 추가 ([a9afc36](https://github.com/mochafreddo/swing-trading-report/commit/a9afc368120d25ffae3579a71bb46cf44fb758e8))

## [1.30.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.30.1...v1.30.2) (2026-05-14)


### Bug Fixes

* **release:** uv 락 JSONPath를 TOML 구조에 맞춘다 ([0cec063](https://github.com/mochafreddo/swing-trading-report/commit/0cec06345c6c6acc6f93948db49ff5ba4123b767))

## [1.30.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.30.0...v1.30.1) (2026-05-14)


### Bug Fixes

* **release:** uv 락 버전을 릴리스 자동화에 포함한다 ([8c52805](https://github.com/mochafreddo/swing-trading-report/commit/8c52805648284eda7af62b6ea6585058632c559c))

## [1.30.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.29.1...v1.30.0) (2026-05-14)


### Features

* **ai-brief:** Benzinga 뉴스 소스 제공자 추가 ([#149](https://github.com/mochafreddo/swing-trading-report/issues/149)) ([722ed82](https://github.com/mochafreddo/swing-trading-report/commit/722ed8275653c8624c79cc4bf9a1ac9632c93b10))

## [1.29.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.29.0...v1.29.1) (2026-05-14)


### Bug Fixes

* **release:** uv 락 버전을 1.29.0으로 동기화한다 ([97d04cd](https://github.com/mochafreddo/swing-trading-report/commit/97d04cd7a8706f5dfabcfc33681e31a1ff69571a))

## [1.29.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.28.0...v1.29.0) (2026-05-14)


### Features

* **ai-brief:** Marketaux 뉴스 소스 provider 추가 ([#146](https://github.com/mochafreddo/swing-trading-report/issues/146)) ([8c62cc9](https://github.com/mochafreddo/swing-trading-report/commit/8c62cc904509be718e98a9452ea1566a44fc638e))

## [1.28.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.27.0...v1.28.0) (2026-05-14)


### Features

* **ai-brief:** Alpha Vantage 뉴스 제공자 추가 ([#144](https://github.com/mochafreddo/swing-trading-report/issues/144)) ([92f3cb4](https://github.com/mochafreddo/swing-trading-report/commit/92f3cb4d74caac21f28d5f5646bfbff9d8de0b94))

## [1.27.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.26.2...v1.27.0) (2026-05-14)


### Features

* **ai-brief:** Polygon News source provider 추가 ([#142](https://github.com/mochafreddo/swing-trading-report/issues/142)) ([e2871c0](https://github.com/mochafreddo/swing-trading-report/commit/e2871c0341a82c0068371ee89b1d33680debb34d))

## [1.26.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.26.1...v1.26.2) (2026-05-13)


### Bug Fixes

* **ci:** 워크플로 출력 리다이렉션 경고 수정 ([#139](https://github.com/mochafreddo/swing-trading-report/issues/139)) ([bcb1a78](https://github.com/mochafreddo/swing-trading-report/commit/bcb1a78fecafdd0c2684959ddcfd57201f7bf8d3))

## [1.26.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.26.0...v1.26.1) (2026-05-13)


### Bug Fixes

* **release:** uv 락 버전을 1.26.0으로 동기화한다 ([d0d77bd](https://github.com/mochafreddo/swing-trading-report/commit/d0d77bd86130e7c94e27012c8c5f32e073a26202))

## [1.26.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.25.1...v1.26.0) (2026-05-13)


### Features

* **ai-brief:** 추천 artifact 평가기를 추가한다 ([#136](https://github.com/mochafreddo/swing-trading-report/issues/136)) ([fc42118](https://github.com/mochafreddo/swing-trading-report/commit/fc42118c1ceb51207a241c55c013ac46d65036f9))

## [1.25.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.25.0...v1.25.1) (2026-05-13)


### Bug Fixes

* **ci:** uv 락 파일 버전을 1.25.0으로 동기화 ([7467d92](https://github.com/mochafreddo/swing-trading-report/commit/7467d92e993e6236ddec0951ebad7f0cd8c4b7d6))

## [1.25.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.24.0...v1.25.0) (2026-05-13)


### Features

* **ai-brief:** source eval 비교 모드 추가 ([#132](https://github.com/mochafreddo/swing-trading-report/issues/132)) ([445fb7e](https://github.com/mochafreddo/swing-trading-report/commit/445fb7e562a1b93b4b893a03b98431e16874ae31))

## [1.24.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.23.0...v1.24.0) (2026-05-13)


### Features

* **ai-brief:** Naver News source provider 추가 ([#130](https://github.com/mochafreddo/swing-trading-report/issues/130)) ([518599d](https://github.com/mochafreddo/swing-trading-report/commit/518599db75529df167159dbfaac08249dcb61c48))

## [1.23.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.22.2...v1.23.0) (2026-05-12)


### Features

* **ai-brief:** Finnhub Company News source provider 추가

## [1.22.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.22.1...v1.22.2) (2026-05-12)


### Bug Fixes

* **web:** Next.js 보안 패치 적용 ([d2569f4](https://github.com/mochafreddo/swing-trading-report/commit/d2569f4404d6cb4df780f78e78b23326a903cd63))

## [1.22.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.22.0...v1.22.1) (2026-05-08)


### Bug Fixes

* **web:** postcss 취약 버전 해소 ([55ec0a7](https://github.com/mochafreddo/swing-trading-report/commit/55ec0a7f22d0729d24f195d569ee2533cc984f22))

## [1.22.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.21.1...v1.22.0) (2026-05-08)


### Features

* **ai-brief:** live RSS feed URL 수집을 지원한다 ([#119](https://github.com/mochafreddo/swing-trading-report/issues/119)) ([73ec98c](https://github.com/mochafreddo/swing-trading-report/commit/73ec98c0fde713271a72fd3b35b880b0dfdede03))

## [1.21.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.21.0...v1.21.1) (2026-05-07)


### Bug Fixes

* **ai-brief:** 빈 entry 후보 보고서를 허용한다 ([8d86658](https://github.com/mochafreddo/swing-trading-report/commit/8d8665859c33a2202acb12b30542d609b7c4b0a2))

## [1.21.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.20.0...v1.21.0) (2026-05-07)


### Features

* **ai-brief:** 캡처 feed 소스 수집기 추가 ([#115](https://github.com/mochafreddo/swing-trading-report/issues/115)) ([5e889ce](https://github.com/mochafreddo/swing-trading-report/commit/5e889ce7911887caace0d23dce2bebed1b73d9a5))

## [1.20.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.19.0...v1.20.0) (2026-05-06)


### Features

* **ai-brief:** Supabase와 웹 Reports 지원 추가 ([#112](https://github.com/mochafreddo/swing-trading-report/issues/112)) ([44cb07a](https://github.com/mochafreddo/swing-trading-report/commit/44cb07a63b8da6ad09add3ccd031f81f79bf8101))
* **ai-brief:** 수동 워크플로 추가 ([#109](https://github.com/mochafreddo/swing-trading-report/issues/109)) ([6ce6455](https://github.com/mochafreddo/swing-trading-report/commit/6ce64550913affd593ae48dece0d4b3ab2e83c89))
* **ai-brief:** 수동 워크플로우 알림 발송 지원 ([#110](https://github.com/mochafreddo/swing-trading-report/issues/110)) ([b15146c](https://github.com/mochafreddo/swing-trading-report/commit/b15146c2b74ba5a766e34c3dec3ff1ee77f139a8))
* **ai-brief:** 알림 텍스트 builder 추가 ([#107](https://github.com/mochafreddo/swing-trading-report/issues/107)) ([3016dc3](https://github.com/mochafreddo/swing-trading-report/commit/3016dc30899ec2dc13de934a64e546b7ac4a6a6d))
* **ai-brief:** 예약 실행 워크플로 추가 ([7420fbc](https://github.com/mochafreddo/swing-trading-report/commit/7420fbc71b8e77cf3c8c4fe25daf6cdd18cc42b3))
* **ai-brief:** 오프라인 source eval 추가 ([#114](https://github.com/mochafreddo/swing-trading-report/issues/114)) ([45d30c5](https://github.com/mochafreddo/swing-trading-report/commit/45d30c5972468985b3c3c31ae5f0481a6b6b6407))
* **ai-brief:** 외부 HTTP JSON 소스 공급자 추가 ([#113](https://github.com/mochafreddo/swing-trading-report/issues/113)) ([9af20d1](https://github.com/mochafreddo/swing-trading-report/commit/9af20d16371a4d81fa2f49a5afe7c4ba46e24591))

## [1.19.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.18.0...v1.19.0) (2026-05-05)


### Features

* **ai-brief:** 로컬 source provider 추가 ([e9d48db](https://github.com/mochafreddo/swing-trading-report/commit/e9d48db4085b773a7589b42c53ab3568b6034c74))

## [1.18.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.17.1...v1.18.0) (2026-05-05)


### Features

* **ai-brief:** OpenAI 모델 provider 추가 ([#103](https://github.com/mochafreddo/swing-trading-report/issues/103)) ([8d27cdb](https://github.com/mochafreddo/swing-trading-report/commit/8d27cdb0194aa10ccf986b9292e3b3906c94a812))

## [1.17.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.17.0...v1.17.1) (2026-05-05)


### Bug Fixes

* **cli:** JSON 로그 포맷 초기화 실패를 고친다 ([#101](https://github.com/mochafreddo/swing-trading-report/issues/101)) ([e1b0e0c](https://github.com/mochafreddo/swing-trading-report/commit/e1b0e0c441ac5b03dc87a17a170700c3f51a4c67))

## [1.17.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.16.4...v1.17.0) (2026-05-05)


### Features

* **ai-brief:** 로컬 진입 브리프 MVP 추가 ([0f6ae72](https://github.com/mochafreddo/swing-trading-report/commit/0f6ae72c2510afca0ec1f3bda29ad86047bb822c))

## [1.16.4](https://github.com/mochafreddo/swing-trading-report/compare/v1.16.3...v1.16.4) (2026-05-04)


### Bug Fixes

* **web:** React Hooks lint 실패를 해결한다 ([1668b8c](https://github.com/mochafreddo/swing-trading-report/commit/1668b8cd74c917c40fb78140db2eeff7f7db179e))

## [1.16.3](https://github.com/mochafreddo/swing-trading-report/compare/v1.16.2...v1.16.3) (2026-05-04)


### Bug Fixes

* **audit:** Trivy 보안 감사 실패 해결 ([05f6478](https://github.com/mochafreddo/swing-trading-report/commit/05f647888b4d50b876d1473d61f8126a52ea2c44))

## [1.16.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.16.1...v1.16.2) (2026-04-01)


### Bug Fixes

* **quality:** mypy dotenv 의존성을 개발 환경에 포함한다 ([e39fe40](https://github.com/mochafreddo/swing-trading-report/commit/e39fe406d96276ab3c85978a7e44efb3ff47ff3b))
* **web:** 제목 가시성과 감소 모션 대응을 보강한다 ([3636b79](https://github.com/mochafreddo/swing-trading-report/commit/3636b79b851102e51bec0dbed197906906268bb0))

## [1.16.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.16.0...v1.16.1) (2026-03-31)


### Bug Fixes

* **ci:** 공급망 방어를 강화한다 ([1f92829](https://github.com/mochafreddo/swing-trading-report/commit/1f928295e713fe217b31f4cadf97adcdcc91785b))
* **deps:** 감사 취약 의존성을 상향한다 ([119f682](https://github.com/mochafreddo/swing-trading-report/commit/119f682b2b8292590de5885b1a1c829bb638f20e))

## [1.16.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.15.0...v1.16.0) (2026-03-28)


### Features

* **metrics:** 운영 메트릭 대시보드 추가 ([65c08de](https://github.com/mochafreddo/swing-trading-report/commit/65c08de31fcf1f1a3c9c09e198baf37d4a5e47ad))

## [1.15.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.14.0...v1.15.0) (2026-03-28)


### Features

* **entry:** 엔트리 포트폴리오 가드 추가 ([0d0fcd1](https://github.com/mochafreddo/swing-trading-report/commit/0d0fcd19f523a4cfffd050b5445f1ed0d71338db))

## [1.14.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.13.0...v1.14.0) (2026-03-28)


### Features

* **scan:** 시장 레짐 SMA200 필터를 추가 ([aadf215](https://github.com/mochafreddo/swing-trading-report/commit/aadf2153fe2aaa741d3008639631e860048ddaef))

## [1.13.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.12.0...v1.13.0) (2026-03-28)


### Features

* **holdings:** holdings.yaml import/export 마무리 ([f602fa3](https://github.com/mochafreddo/swing-trading-report/commit/f602fa33cabe8c87512e1d43f77ecaa50dd7ed15))

## [1.12.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.11.2...v1.12.0) (2026-03-27)


### Features

* **reports:** entry 리포트 웹 통합 ([702958a](https://github.com/mochafreddo/swing-trading-report/commit/702958a0858e42f67d3474bc4eb25cfcc5d8915b))
* **scan:** raw 기준가 보강을 후보 배치화 ([da75694](https://github.com/mochafreddo/swing-trading-report/commit/da756945e160e044002230b79ff2441d4b1bbef9))
* **web:** 운영 콘솔 UI 디자인 개선 ([cd19536](https://github.com/mochafreddo/swing-trading-report/commit/cd19536615b7c5349e4a004ab06493d2e9438a89))


### Bug Fixes

* **scan:** fail-closed 테스트 호환성을 복원 ([9c6c484](https://github.com/mochafreddo/swing-trading-report/commit/9c6c484a86861b961305df592070d7288d79f482))
* **strategy:** 스윙 데이터 신선도와 엔트리 가드 계약 정렬 ([4573f3c](https://github.com/mochafreddo/swing-trading-report/commit/4573f3c3c3081f12ad0b01aa9cbc51df3f47930d))

## [1.11.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.11.1...v1.11.2) (2026-03-27)


### Bug Fixes

* **renovate:** Node 런타임 자동 머지 차단 ([9e58923](https://github.com/mochafreddo/swing-trading-report/commit/9e58923392ceff4248722613cce5283f17d7e331))
* **web:** 깨진 Node Alpine 다이제스트 롤백 ([c5199f3](https://github.com/mochafreddo/swing-trading-report/commit/c5199f3edfb4a8b2342fd90ba8eac605147b72be))

## [1.11.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.11.0...v1.11.1) (2026-03-26)


### Bug Fixes

* **ci:** mise 파이썬 lock 설정을 정합화 ([7670aa7](https://github.com/mochafreddo/swing-trading-report/commit/7670aa75f0d6db551c9fd1c86e4b084ee2d0aef7))
* **ci:** mise 파이썬 프리컴파일 flavor를 고정 ([d913574](https://github.com/mochafreddo/swing-trading-report/commit/d913574a5cfb77ae293347ddd7596b9c5154c04c))

## [1.11.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.6...v1.11.0) (2026-03-10)


### Features

* **web:** 운영 콘솔 UI를 개편한다 ([032e97c](https://github.com/mochafreddo/swing-trading-report/commit/032e97c5bf6c1d8dbe02b90e0486c9fe18c1a238))

## [1.10.6](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.5...v1.10.6) (2026-03-09)


### Bug Fixes

* **renovate:** 자동 머지 경로를 Renovate로 고정 ([97605c3](https://github.com/mochafreddo/swing-trading-report/commit/97605c34f787dc98275a00b6cee24f26b6ea673a))

## [1.10.5](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.4...v1.10.5) (2026-03-08)


### Bug Fixes

* **review:** 2026-03-08 리뷰 이슈 반영 ([3f0ab73](https://github.com/mochafreddo/swing-trading-report/commit/3f0ab7335c350ed08953d0b5b1f0614496401080))
* **web:** 리포트 캐시 테스트 타입 오류 수정 ([595a674](https://github.com/mochafreddo/swing-trading-report/commit/595a674b66a3eb1aeda0ccca91ead3c6d92a3e34))

## [1.10.4](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.3...v1.10.4) (2026-03-06)


### Bug Fixes

* **reports:** URL 선택 상태 동기화를 안정화 ([0c7d309](https://github.com/mochafreddo/swing-trading-report/commit/0c7d309cf22b91752fc0cc502b3ef1cc66c67b90))
* **web:** 콘솔 초기 로딩 오류를 숨기지 않는다 ([b30739d](https://github.com/mochafreddo/swing-trading-report/commit/b30739da87cdf266684c57fd89a57b6bccefaecc))

## [1.10.3](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.2...v1.10.3) (2026-03-06)


### Bug Fixes

* **strategy:** 엔트리·평가 로직을 mixed market 계약에 맞춘다 ([3e84070](https://github.com/mochafreddo/swing-trading-report/commit/3e84070fff44652d563e2d15a351b6efa3868056))

## [1.10.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.1...v1.10.2) (2026-03-06)


### Bug Fixes

* **strategy:** 핵심 로직 계약 정합성 반영 ([268074c](https://github.com/mochafreddo/swing-trading-report/commit/268074c3bfb1322954059386260c63f44fdd1aec))

## [1.10.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.10.0...v1.10.1) (2026-03-06)


### Bug Fixes

* **review:** 2026-03-06 리뷰 이슈 후속 조치 반영 ([e422905](https://github.com/mochafreddo/swing-trading-report/commit/e4229050effa7e52a90c683e893b0d4961b322bf))

## [1.10.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.9.0...v1.10.0) (2026-03-05)


### Features

* review-2026-03-05 개선 사항 반영 ([1b4d0d9](https://github.com/mochafreddo/swing-trading-report/commit/1b4d0d91c3ca338bff6c860be42b3cba2570260b))

## [1.9.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.8.1...v1.9.0) (2026-03-05)


### Features

* **renovate:** 저위험 업데이트 자동 머지 확대 ([681aa16](https://github.com/mochafreddo/swing-trading-report/commit/681aa1663fe239c16bf96e6e2c77b02c5baa71e6))

## [1.8.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.8.0...v1.8.1) (2026-03-05)


### Bug Fixes

* **renovate:** Node 버전 원자적 그룹핑 및 mise.lock 자동 동기화 ([e13a510](https://github.com/mochafreddo/swing-trading-report/commit/e13a510b70e38dc9c60b57dfd0ec619f552f715f))

## [1.8.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.7.4...v1.8.0) (2026-03-04)


### Features

* **holdings:** add-buy 멱등성 및 sell 평가 하드닝 ([46aee09](https://github.com/mochafreddo/swing-trading-report/commit/46aee09d6ff8aa3e00dc712ae70e2a559490b44f))

## [1.7.4](https://github.com/mochafreddo/swing-trading-report/compare/v1.7.3...v1.7.4) (2026-03-04)


### Bug Fixes

* **web:** 리포트 새로고침 라벨 테스트 기대값 수정 ([6902892](https://github.com/mochafreddo/swing-trading-report/commit/69028920dd87c5470e608208ed4d7d2cffdc3bbc))

## [1.7.3](https://github.com/mochafreddo/swing-trading-report/compare/v1.7.2...v1.7.3) (2026-03-04)


### Bug Fixes

* **web:** UX 개선 — 삭제 확인, 입력 보조, 말줄임표 통일 ([fcaec29](https://github.com/mochafreddo/swing-trading-report/commit/fcaec29ef8d38192b880eb984202af78d3b04c12))

## [1.7.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.7.1...v1.7.2) (2026-03-03)


### Bug Fixes

* **market-data:** 캐시 신선도 정책과 캔들 정합성 개선 ([09f1971](https://github.com/mochafreddo/swing-trading-report/commit/09f1971458925e7d640ccae7cb71b86ef4901286))

## [1.7.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.7.0...v1.7.1) (2026-03-03)


### Bug Fixes

* **strategy:** entry/scan 전략 모드 계약 정합화 ([063a966](https://github.com/mochafreddo/swing-trading-report/commit/063a9666bac1c927f0e3370e4366f104cf7da19c))

## [1.7.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.6.1...v1.7.0) (2026-03-03)


### Features

* **holdings:** 추가매수 입력 및 유효성 검증 강화 ([48bbbb4](https://github.com/mochafreddo/swing-trading-report/commit/48bbbb472ae6f72de0f98cd29ec5373f456157ac))


### Bug Fixes

* **web:** add-buy catch-all 라우트 빌드 오류 수정 ([3c77a6e](https://github.com/mochafreddo/swing-trading-report/commit/3c77a6ed4f1bd96d47c0bdba1ae993dafb282b3a))

## [1.6.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.6.0...v1.6.1) (2026-03-03)


### Bug Fixes

* **ci:** audit 워크플로 Trivy 버전 고정 ([cba1d1c](https://github.com/mochafreddo/swing-trading-report/commit/cba1d1c412125d513123b256b5e1fe866d5e9332))

## [1.6.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.5.1...v1.6.0) (2026-02-28)


### Features

* **report:** 매수 후보 근거 구조화 및 상세 표시 고도화 ([f3cf338](https://github.com/mochafreddo/swing-trading-report/commit/f3cf338d1deac75987d7866057b84ecf46a24f6e))
* **web:** 리포트 페이지 캐시 계층과 새로고침 플로우 추가 ([3d0273e](https://github.com/mochafreddo/swing-trading-report/commit/3d0273e3df2833db84edcdc242eef94b61d4d2d9))


### Bug Fixes

* **reports:** 키 동기화 루프로 인한 무한 로딩 재발 방지 ([df6a507](https://github.com/mochafreddo/swing-trading-report/commit/df6a50779c226eda91a323299a79754c2766a5b7))

## [1.5.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.5.0...v1.5.1) (2026-02-28)


### Bug Fixes

* **web:** 리포트 summary 텍스트 overflow를 방지 ([b92d328](https://github.com/mochafreddo/swing-trading-report/commit/b92d328002978597866638f4a859132107613979))

## [1.5.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.4.1...v1.5.0) (2026-02-28)


### Features

* **web:** 홀딩스 티커 검색 UX와 기본값 개선 ([7bfb088](https://github.com/mochafreddo/swing-trading-report/commit/7bfb088c607a6968fc03ffca63f49e1c6a1c33f9))

## [1.4.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.4.0...v1.4.1) (2026-02-28)


### Bug Fixes

* **ci:** scan/watchlist와 sell US 클래스 심볼 폴백 오류 수정 ([14cb0a1](https://github.com/mochafreddo/swing-trading-report/commit/14cb0a12ae30313193098db21772b3bce1eacb25))

## [1.4.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.3.3...v1.4.0) (2026-02-27)


### Features

* **core:** 티커/홀딩스 입력 검증을 fail-closed로 강화 ([ce9cb48](https://github.com/mochafreddo/swing-trading-report/commit/ce9cb48340a759cffdd38236f598d59cec684b6c))


### Bug Fixes

* **calendar:** PMC break 경고 억제를 안전하게 적용 ([a10a6ac](https://github.com/mochafreddo/swing-trading-report/commit/a10a6ac2339d134a413b346b7c9b7e4ebcea025a))
* **kis:** 해외 시세/랭킹/스크리너 안정성 개선 ([40fb095](https://github.com/mochafreddo/swing-trading-report/commit/40fb095b575a05173fadaf7519319e284e1861c6))
* **scan:** watchlist/screener 경계를 fail-closed로 강화 ([3e08841](https://github.com/mochafreddo/swing-trading-report/commit/3e088415b0b2c728e573c918eef0cc9a3af22ca3))
* **signals:** eval_index 시장 추론에서 거래소를 우선 ([93a8150](https://github.com/mochafreddo/swing-trading-report/commit/93a8150306a66e36e879f3912005bc0b5f3557ec))
* **signals:** 갭 필터 ATR을 신호 전 값으로 계산 ([2ea1e68](https://github.com/mochafreddo/swing-trading-report/commit/2ea1e68736869977bd2a37adeda5528ed0588553))
* **web:** holdings 티커를 strict exchange suffix로 정규화 ([0ea3c9d](https://github.com/mochafreddo/swing-trading-report/commit/0ea3c9d2d98e2ff0fc0d8ecf7ad4a7a1c3076718))

## [1.3.3](https://github.com/mochafreddo/swing-trading-report/compare/v1.3.2...v1.3.3) (2026-02-26)


### Bug Fixes

* **entry:** eval_date 기반 signal_eval_date 정합성 ([#13](https://github.com/mochafreddo/swing-trading-report/issues/13)) ([4fed4e6](https://github.com/mochafreddo/swing-trading-report/commit/4fed4e6cd074c25c1c3c35618bd02fe82f3ff777))

## [1.3.2](https://github.com/mochafreddo/swing-trading-report/compare/v1.3.1...v1.3.2) (2026-02-26)


### Bug Fixes

* **signals:** fail-closed 갭 필터 및 ATR 트레일 보강 ([#11](https://github.com/mochafreddo/swing-trading-report/issues/11)) ([13251f4](https://github.com/mochafreddo/swing-trading-report/commit/13251f4a0ad1ff37b3b3481632a2513d2a267d4f))

## [1.3.1](https://github.com/mochafreddo/swing-trading-report/compare/v1.3.0...v1.3.1) (2026-02-26)


### Bug Fixes

* **strategy:** 하이브리드 매수/엔트리/세션 메타 보정 ([#9](https://github.com/mochafreddo/swing-trading-report/issues/9)) ([e29b1f6](https://github.com/mochafreddo/swing-trading-report/commit/e29b1f65c2df19dd81b867a41e1c2a6aa810f71a))

## [1.3.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.2.0...v1.3.0) (2026-02-26)


### ⚠ BREAKING CHANGES

* **overseas:** config.yaml is now tracked (removed from .gitignore)
* **core, docs:** Buy report filename changed from reports/YYYY-MM-DD.md to reports/YYYY-MM-DD.buy.md. Update any scripts or references.

### Features

* **cleanup:** 리포트 retention 정리 워크플로우 추가 ([940088f](https://github.com/mochafreddo/swing-trading-report/commit/940088f4cff1f4be0f3421889f9f5d03167f2698))
* **cli,reports:** implement sab sell and generate Sell/Review report ([974064d](https://github.com/mochafreddo/swing-trading-report/commit/974064d4005ddbdf4e7ddf8fe29ff2e90ed84599))
* **cli:** load dotenv before running commands ([ca1633e](https://github.com/mochafreddo/swing-trading-report/commit/ca1633e4f359ed2d2c005856c837bd275142899b))
* **config:** allow overriding watchlist file path ([2affe49](https://github.com/mochafreddo/swing-trading-report/commit/2affe493831e1cc62dd785debcb4a7cb6f6c92d2))
* **core, docs:** split Buy/Sell/Entry; add config.yaml, screener cache, PyKRX fallback, holdings + sell rules; rename Buy report ([2e745d9](https://github.com/mochafreddo/swing-trading-report/commit/2e745d96ccc7feeb7f6c746f8a114a0ef45f1703))
* **core:** v1.3 진입/매도 평가 계약을 구현 ([65f4108](https://github.com/mochafreddo/swing-trading-report/commit/65f410832b7a007710ee596c75a3daddf84dd790))
* **db:** holdings 테이블 및 RLS 마이그레이션 추가 ([051c47d](https://github.com/mochafreddo/swing-trading-report/commit/051c47d25e0eb19a92f48dafcdb9bea40c7dfa04))
* **eval:** add provider parameter to choose_eval_index for EOD-only feeds ([21a81a9](https://github.com/mochafreddo/swing-trading-report/commit/21a81a9211e332472edbebce76af0fb63ef9d177))
* **fx:** add KIS-based automatic USD/KRW rate resolution with caching ([ed5485a](https://github.com/mochafreddo/swing-trading-report/commit/ed5485a84cb7e87387d790a6357ff2fccbe471d8))
* **holdings:** API 하드닝과 커서 페이지네이션 도입 ([c76cd51](https://github.com/mochafreddo/swing-trading-report/commit/c76cd51537eb845326a8ee8dd3713e61242ddfec))
* **hybrid:** add SMA/EMA buy & sell workflows ([6e234c4](https://github.com/mochafreddo/swing-trading-report/commit/6e234c4f83569de92efc9e08db129260f33d3648))
* **logging:** add timestamped TZ-aware logs ([ffb9d34](https://github.com/mochafreddo/swing-trading-report/commit/ffb9d34e167b71609ef69a0b902f2774ac42539c))
* **notify:** 텔레그램 알림을 리포트 본문으로 전환 ([482b624](https://github.com/mochafreddo/swing-trading-report/commit/482b62406ea9b1a3f62e34af0ba37acd48e139ce))
* **overseas:** add US market support with KIS integration ([fff892a](https://github.com/mochafreddo/swing-trading-report/commit/fff892a56b358ba6c553bb158ac99429407f9c54))
* **report:** JSON 아티팩트 생성과 Supabase 업로드 연동 ([c84381a](https://github.com/mochafreddo/swing-trading-report/commit/c84381af4cfb100819bdc267d5bf5669092c6233))
* scaffold KR swing report CLI with KIS API, uv, docs, and MIT license ([05f0c3b](https://github.com/mochafreddo/swing-trading-report/commit/05f0c3b0b52adcab538371cffbb61bc08c12a826))
* **sell:** add profit target zone review in hybrid sell logic ([b4fb02a](https://github.com/mochafreddo/swing-trading-report/commit/b4fb02a528b04776e87814fbee3af4fbb5721c43))
* **sell:** add usd fx support to sell workflow ([30ba7cb](https://github.com/mochafreddo/swing-trading-report/commit/30ba7cbeab46f67332f28ee681afc40ffa306b39))
* **signals:** implement daily candle evaluation index logic ([76bdc6a](https://github.com/mochafreddo/swing-trading-report/commit/76bdc6a82f4d40d4f9c9e86136fda5971e8f5904))
* **storage:** reports 버킷 마이그레이션과 키 생성 규칙 추가 ([b0ab9f7](https://github.com/mochafreddo/swing-trading-report/commit/b0ab9f7a26cc0d57c92a3d516bdab0ad54041cd5))
* **supabase:** runtime_state 테이블과 로그인 스로틀 RPC 추가 ([532a539](https://github.com/mochafreddo/swing-trading-report/commit/532a539ea1ddd29a0e0c18e6805978a0016786b9))
* **web:** holdings 비활성(quantity&lt;=0) UX 정책 반영 ([34e0de9](https://github.com/mochafreddo/swing-trading-report/commit/34e0de9228f55649ed0ad28825d3c370cc9b51dc))
* **web:** holdings 티커 수정 허용 ([026bb9a](https://github.com/mochafreddo/swing-trading-report/commit/026bb9a98ecc4edaaf9bc6b3ce63f0db266589d4))
* **web:** M5 웹 UI 및 API 라우트 추가 ([ab523ea](https://github.com/mochafreddo/swing-trading-report/commit/ab523ea8cb067f67d5e8da90932e2dffdb023516))
* **web:** 로그인 스로틀/스토리지 키 캐시를 runtime_state로 이전 ([721a981](https://github.com/mochafreddo/swing-trading-report/commit/721a9819e646ae1a6c999c2100d88847878ea4f3))
* **web:** 로그인 페이지와 세션 쿠키 인증 도입 ([15d2c45](https://github.com/mochafreddo/swing-trading-report/commit/15d2c45b7ff157ef100854caa62a0de95bebdc03))
* **web:** 리포트 목록 조회 캐시·병렬 검색 도입 ([a1539ae](https://github.com/mochafreddo/swing-trading-report/commit/a1539aea8f15435872065c2d78926fe6f7611d92))
* **web:** 접근성 및 런 트리거 UX 개선 ([a0399cc](https://github.com/mochafreddo/swing-trading-report/commit/a0399cc31ed6854bae92a4527b03b12c9a9b71ec))


### Bug Fixes

* **actions:** 알림 조건 파싱 오류 수정 ([73ef6a3](https://github.com/mochafreddo/swing-trading-report/commit/73ef6a36c203a90de1a50fa205707bb30350b410))
* **calendar:** 미국 휴장일 판정 경로를 data_dir로 통일 ([8f52671](https://github.com/mochafreddo/swing-trading-report/commit/8f526716b827a4b10ced6d7ff1a067fe0550cde8))
* **cleanup:** Storage 삭제와 report_index 정합성 유지 ([5afeaef](https://github.com/mochafreddo/swing-trading-report/commit/5afeaef6c868425ec86ce4555640c5121a5c440b))
* **config:** config.yaml/.env 중복 키 충돌 시 즉시 실패 ([7f9d746](https://github.com/mochafreddo/swing-trading-report/commit/7f9d7466694a21a9314b3aa9aa6785d475d71362))
* **config:** config/holdings 파싱 실패 시 fail-closed 적용 ([11b1dfc](https://github.com/mochafreddo/swing-trading-report/commit/11b1dfce979698ef9c444a5bb4e9bbb162acd159))
* **config:** KIS 시크릿을 환경변수 전용으로 강제 ([bb22f4e](https://github.com/mochafreddo/swing-trading-report/commit/bb22f4eaba21c3005564106114aa89bdce0d52cb))
* **config:** 운영/CI strict 설정 파싱 적용 ([11c2d7c](https://github.com/mochafreddo/swing-trading-report/commit/11c2d7c6fb9cdb1b38993271309ff0328da5fb9b))
* **core:** P1/P2 트레이딩 이슈 일괄 수정 ([26e98d1](https://github.com/mochafreddo/swing-trading-report/commit/26e98d17693638c0c085973a51fe5ab1ee95d75a))
* **core:** 스캔/스크리너 운용 안정성 하드닝 ([ec794ed](https://github.com/mochafreddo/swing-trading-report/commit/ec794ed741a6c72a6781306defba208485b26941))
* **core:** 조기폐장 세션 판정과 매도 평가 로직 보정 ([1cea8a5](https://github.com/mochafreddo/swing-trading-report/commit/1cea8a5c0a6e48d24a3cd0fce2a174cdda58cc35))
* **core:** 평가 예외를 fail-closed로 강화 ([8c069c5](https://github.com/mochafreddo/swing-trading-report/commit/8c069c5a2dab093e469821ce70d3f01cbca667b6))
* **data:** KR 내장 휴일 데이터 오타 수정 ([dbb785e](https://github.com/mochafreddo/swing-trading-report/commit/dbb785ea4dee617ab22abdc55fa0e9fcca243c91))
* **data:** 휴일 캐시 로더 구조 검증 강화 ([32e945b](https://github.com/mochafreddo/swing-trading-report/commit/32e945be55a9f35c82d6f3c0e22a7f2786a5c079))
* **docker:** 컨테이너 기본 엔트리를 prod로 전환 ([64d6abd](https://github.com/mochafreddo/swing-trading-report/commit/64d6abd6cbf9e6d5c275cca3e393a65767726ef7))
* **env_loader:** load_dotenv 호출 타입 오류 수정 ([4ae68f3](https://github.com/mochafreddo/swing-trading-report/commit/4ae68f361f631d774da89063b275c29068039206))
* harden US screener fallback and token refresh ([22cf0fc](https://github.com/mochafreddo/swing-trading-report/commit/22cf0fc50fb9a615c7c8190dcc49a95f31362c40))
* **holdings:** holdings.yaml 로더를 fail-closed로 강화 ([47e2c0f](https://github.com/mochafreddo/swing-trading-report/commit/47e2c0f5012a5c58b198b224b30e410fe6ffad4c))
* **kis:** refresh token on volume rank EGW00123 errors ([c527b02](https://github.com/mochafreddo/swing-trading-report/commit/c527b027ced01c24ff5409bd9c8c99d75d77a984))
* **kis:** 토큰 만료 파싱과 캐시 상태 로그를 보강 ([a608551](https://github.com/mochafreddo/swing-trading-report/commit/a6085514c2fba18c00b5cb19078cacfd125f0723))
* **kis:** 토큰 발급 제한(EGW00133) 재시도 추가 ([5038c61](https://github.com/mochafreddo/swing-trading-report/commit/5038c617f8d8d1898b42fa9d4ee15a6f1f681fb6))
* make cache and report writes atomic ([c6a209e](https://github.com/mochafreddo/swing-trading-report/commit/c6a209e7e96d08f6f580e66b8f9b45f9d380dfd3))
* **market-data:** 캐시 stale 상한 적용 ([0a98b50](https://github.com/mochafreddo/swing-trading-report/commit/0a98b50199c2609ee354bc78c54445b8cea4a52f))
* **market-data:** 휴장일 필터와 수집 실패 처리 개선 ([9556020](https://github.com/mochafreddo/swing-trading-report/commit/9556020eb61170278bb31c674eb8bcd6181bc826))
* mypy 타입 오류를 정리하고 코드 안정성 개선 ([938f2af](https://github.com/mochafreddo/swing-trading-report/commit/938f2af1fc3cebc8285442583ee787eedf740d68))
* python-dotenv 미설치 환경의 .env 로딩 실패 수정 ([8effa3a](https://github.com/mochafreddo/swing-trading-report/commit/8effa3a2607fce90f22d360af0e778ec902b930b))
* **refactor:** scan/sell 누락 shim 경로 복원 ([9a63c92](https://github.com/mochafreddo/swing-trading-report/commit/9a63c92e2a751e5bfe24ae85d47dd2e57ae20d84))
* **report:** CI 인덱스 실패를 즉시 실패 처리 ([ce26414](https://github.com/mochafreddo/swing-trading-report/commit/ce26414c0e59dd0fdced05a2c4c0ab632b8692e8))
* **reports:** 인덱스 기반 검색 내결함성 강화 ([38192f7](https://github.com/mochafreddo/swing-trading-report/commit/38192f7b2534b98c3fc7945a13a61dd50cf37fdd))
* **report:** 리포트 시간 라벨 KST 고정 해소 ([8b65d43](https://github.com/mochafreddo/swing-trading-report/commit/8b65d43568b1485eb14513d040f20fe19488acac))
* **report:** 매도 요약표 수량의 소수점 표시 보존 ([c6ddb41](https://github.com/mochafreddo/swing-trading-report/commit/c6ddb4166b5bc907644eb046509c346cede47034))
* **scan:** sab 스캔 이슈 6건 일괄 개선 ([0a2f0d4](https://github.com/mochafreddo/swing-trading-report/commit/0a2f0d49c984cba4913213a83749ef7607d01aa9))
* **scan:** scan --limit을 최종 평가 상한으로 고정 ([3cb48e6](https://github.com/mochafreddo/swing-trading-report/commit/3cb48e6c5768766251ab131e3ec13e82fc601064))
* **scan:** 스크리너 단독 유니버스 보호와 하이브리드 필터를 보강 ([f2ad47c](https://github.com/mochafreddo/swing-trading-report/commit/f2ad47ce5b1ea212e31adc9f82f350650384de36))
* **scan:** 캐시 우선 수집과 후보 정렬 안정성 개선 ([50ce844](https://github.com/mochafreddo/swing-trading-report/commit/50ce84494f32656217161fa7cef8ec086768e6ad))
* **security:** holdings 조회 경계 강화 ([b6a6ca8](https://github.com/mochafreddo/swing-trading-report/commit/b6a6ca837a32ce0eb6d6a8a17d804224f4457174))
* **sell:** 수익률 계산 및 표시 일관성 보정 ([20fd63a](https://github.com/mochafreddo/swing-trading-report/commit/20fd63a5aebc5ebf845d90e3e4799dd61db511ad))
* **sell:** 종가 평가 fail-safe 로직 강화 ([2c9f6d0](https://github.com/mochafreddo/swing-trading-report/commit/2c9f6d0f874300bab08b676ec38ab932cfa0ca79))
* **signals:** ATR 트레일링 스탑 발동 로직 수정 ([7d21269](https://github.com/mochafreddo/swing-trading-report/commit/7d21269692e818e7794a7c169a227a05c5b17660))
* **signals:** ETF 제외 필터 과소탐지 보강 ([97c0a4c](https://github.com/mochafreddo/swing-trading-report/commit/97c0a4c07ef7c3c5bf26f0c52cae50846650784b))
* **signals:** 하이브리드 신호·해외 스크리너 회귀 이슈 수정 ([d74dd73](https://github.com/mochafreddo/swing-trading-report/commit/d74dd73e48c611b900ab202d80ab9dba3a570bb3))
* **spec:** v1.1 정합성 이슈 보완 ([f79b65a](https://github.com/mochafreddo/swing-trading-report/commit/f79b65a5276f3144bb2986c8a49009306eafbb08))
* **supabase:** Secret key 우선 사용 및 키 검증 강화 ([aced709](https://github.com/mochafreddo/swing-trading-report/commit/aced7092f8f585c0f76ae3d4e5bd58663580e82c))
* **trading:** 매매/리스크 핵심 로직 보강 ([2379c5a](https://github.com/mochafreddo/swing-trading-report/commit/2379c5a80b5091c8ad0bfbb021fdbf95e47e06a2))
* **us:** use confirmed-close ranks; harden holiday merge + rank pagination ([f4fbbb9](https://github.com/mochafreddo/swing-trading-report/commit/f4fbbb908ecd2a0882ca16608e7b2ed6345ea6f7))
* **web:** /api/run 입력정책을 워크플로와 정렬 ([3152626](https://github.com/mochafreddo/swing-trading-report/commit/315262630ecdd0572f3daa5aa0092db44941d63a))
* **web:** holdings path ticker 검증 정책 통일 ([161cc78](https://github.com/mochafreddo/swing-trading-report/commit/161cc78857ef31257d361d632e1c214dc3e7fa4d))
* **web:** holdings 슬래시 티커 라우팅 지원 ([9b59c0c](https://github.com/mochafreddo/swing-trading-report/commit/9b59c0c245c838135e60aac36a33a9a0af80dc02))
* **web:** holdings 티커 별칭 정합성 강화 ([7df9d96](https://github.com/mochafreddo/swing-trading-report/commit/7df9d968d3e4ccc6571b4bd97211fbff545407c5))
* **web:** local-request-guard에서 x-forwarded-host 신뢰 제거 ([9c7a716](https://github.com/mochafreddo/swing-trading-report/commit/9c7a716449516ad8ac5a170d63f40fdeb408db64))
* **web:** Reports 검색 범위 정책 명확화 ([9a11fb9](https://github.com/mochafreddo/swing-trading-report/commit/9a11fb98ec84a4fffa260b292bc8fc03b64c00a0))
* **web:** reports 페이지 Suspense 경계 추가 ([bd05939](https://github.com/mochafreddo/swing-trading-report/commit/bd0593959bc749af2c07a0fc82b1a165bdfd4514))
* **web:** 로컬 요청 가드 정책 정렬 ([c2f51cc](https://github.com/mochafreddo/swing-trading-report/commit/c2f51ccdadeb2bc753e84618562ead2565056f68))
* **web:** 로컬 요청 가드와 바인딩을 안전하게 정리 ([e3162ab](https://github.com/mochafreddo/swing-trading-report/commit/e3162ab417049af2f17fd8effb5c9fdac48dd9de))
* **web:** 로컬 전용 API 경계 강화 ([14ddbf8](https://github.com/mochafreddo/swing-trading-report/commit/14ddbf8168b40a215960ddbb4f79a2f8f15acbee))
* **web:** 리액트 성능 리스크 3건 개선 ([0f00f0c](https://github.com/mochafreddo/swing-trading-report/commit/0f00f0c578a90d2110a6d9735fb4156856a83bcb))
* **web:** 실행 경로별 env 검증 분리 ([0f097e8](https://github.com/mochafreddo/swing-trading-report/commit/0f097e886998fc887703b2cb6afaac2268ea80ad))
* **web:** 콘솔 SSR 프리패치 안정성 개선 ([f0f593c](https://github.com/mochafreddo/swing-trading-report/commit/f0f593c4b3ae731e5b3e3f03cefafb8ed8f1290d))
* **web:** 포트포워딩 same-origin 오탐 수정 ([c4f497f](https://github.com/mochafreddo/swing-trading-report/commit/c4f497f7f6f0dd9fa48bab1ab504a439a2682d5c))
* **web:** 프론트엔드 리뷰 지적사항 일괄 반영 ([ce9990b](https://github.com/mochafreddo/swing-trading-report/commit/ce9990b25bad1a382edfba0108e442699a5960bd))
* **workflow:** 액션 설정 충돌과 시크릿 의존성 정리 ([a051f86](https://github.com/mochafreddo/swing-trading-report/commit/a051f86d17925adc059d234e150ecd37ce6e1097))


### Performance Improvements

* **reports:** report_index 기반 조회로 전환 ([d35cd97](https://github.com/mochafreddo/swing-trading-report/commit/d35cd972358f6b0ea6dea8d24e1f1cbb7cf027b0))
* **reports:** 검색 페이징 비용을 줄입니다 ([fb8e204](https://github.com/mochafreddo/swing-trading-report/commit/fb8e204dfc9adf9ba09e70e80b7f9ca234a68d77))
* **web:** 미들웨어 matcher로 실행 범위 제한 ([09de575](https://github.com/mochafreddo/swing-trading-report/commit/09de5757bff760e7debe620c0d0e8919f3191377))


### Miscellaneous Chores

* **release:** release-please를 main push로 실행 ([c50ca44](https://github.com/mochafreddo/swing-trading-report/commit/c50ca4404fcc386d01334c4f4b3bb6fdc0a40ee0))
