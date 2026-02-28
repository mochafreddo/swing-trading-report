# Changelog

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
