# Changelog

## [1.34.0](https://github.com/mochafreddo/swing-trading-report/compare/v1.33.1...v1.34.0) (2026-08-15)


### Features

* **ai-brief:** fallback 설정 정규화 ([5562c19](https://github.com/mochafreddo/swing-trading-report/commit/5562c19ce96eb50703be7b12245d065b0e8db355))
* **ai-brief:** fallback 시각을 장전 deadline에 맞춤 ([af318ac](https://github.com/mochafreddo/swing-trading-report/commit/af318aca162fa29ea16bc1f80a185d527747d942))
* **ai-brief:** READY 후보를 AI brief 입력으로 확장 ([9e5b509](https://github.com/mochafreddo/swing-trading-report/commit/9e5b50985ad9c699b75cee21a467f660869374b6))
* **ai-brief:** source provider chain 병합 추가 ([1270b8b](https://github.com/mochafreddo/swing-trading-report/commit/1270b8b26fc336ec23cc96f23605ec34fbbc6713))
* **ai-brief:** source ref 모델 계약 추가 ([43695e2](https://github.com/mochafreddo/swing-trading-report/commit/43695e23d09306cc735782508c2bd8876ba49eef))
* **ai-brief:** timeout 시 fallback 모델을 시도 ([357f7c7](https://github.com/mochafreddo/swing-trading-report/commit/357f7c7c7da2ff3c9cb9f5beb1aa7b000a079ec0))
* **ai-brief:** watch 후보와 source chain 표시 추가 ([32f31d4](https://github.com/mochafreddo/swing-trading-report/commit/32f31d41e34102adbdefee1eb59564b97784da6a))
* **ai-brief:** 기사 reader로 source-backed 검증 강화 ([c67cc87](https://github.com/mochafreddo/swing-trading-report/commit/c67cc87ceea7c682dc7e430932a610efa76eb7fb))
* **ai-brief:** 기사 검증 메타데이터 검증 추가 ([37a50a7](https://github.com/mochafreddo/swing-trading-report/commit/37a50a7b3ee076645650d5a4585227da65ec8aa8))
* **ai-brief:** 기사 검증 요약과 상태 반영 ([24cce01](https://github.com/mochafreddo/swing-trading-report/commit/24cce01c9e1ec80287b096034ea9dc3ede0fa4aa))
* **ai-brief:** 기사 검증 티어를 평가에 반영 ([f4a86e3](https://github.com/mochafreddo/swing-trading-report/commit/f4a86e342a444697a92c1934c3ea5819d0fcf0c1))
* **ai-brief:** 기사 원문 읽기 보강 추가 ([e0e8757](https://github.com/mochafreddo/swing-trading-report/commit/e0e87575060e96005601b3ca88b1bcad7553c9d9))
* **ai-brief:** 기사 읽기 검증 타입 추가 ([e28dbea](https://github.com/mochafreddo/swing-trading-report/commit/e28dbea282578cd007a54e85711fc44b71a41f17))
* **ai-brief:** 기사 읽기 설정을 파이프라인에 연결 ([81cec0d](https://github.com/mochafreddo/swing-trading-report/commit/81cec0db11397f8ea6d40be26c6d3b46439ca271))
* **ai-brief:** 모델 latency probe 명령 추가 ([2f966dd](https://github.com/mochafreddo/swing-trading-report/commit/2f966dd54f5389f904f1d7c89c4979f6fb213f38))
* **ai-brief:** 모델 provider watch 후보 계약 추가 ([a3ad99b](https://github.com/mochafreddo/swing-trading-report/commit/a3ad99b55dfa48dfc6720299d4a1964aa35647ec))
* **ai-brief:** 모델 표시 문구를 한국어로 유도 ([9c27f29](https://github.com/mochafreddo/swing-trading-report/commit/9c27f29b7d21daf7d934ae37523c7efb9361ec3f))
* **ai-brief:** 스케줄 source chain 설정 지원 ([be9ae3c](https://github.com/mochafreddo/swing-trading-report/commit/be9ae3cca13c0df08b5c7f58b3e264e8671c64d0))
* **ai-brief:** 텔레그램 리치 텍스트 본문 렌더링 ([2c09566](https://github.com/mochafreddo/swing-trading-report/commit/2c09566a6df67dba082dd228608d83a84364787d))
* **ai-brief:** 텔레그램 알림 한국어화 ([4d9812f](https://github.com/mochafreddo/swing-trading-report/commit/4d9812f2e742d7ca3d7ffa0924021f12d98a40f7))
* **ai-brief:** 텔레그램 진단 문구를 한국어화 ([cddf15a](https://github.com/mochafreddo/swing-trading-report/commit/cddf15aa0c1114ed43269e3afecda5288ae2d324))
* **ai-brief:** 후보 역할 분류기 추가 ([f8ef0e1](https://github.com/mochafreddo/swing-trading-report/commit/f8ef0e14b93f85bcd04922df1287f064fcbd49b4))
* **ai-brief:** 후보 역할 분리 ([2ca364d](https://github.com/mochafreddo/swing-trading-report/commit/2ca364daeece2fda4dee4284410d6f081690c01d))
* **ai-brief:** 후보 역할 분리 ([9e96374](https://github.com/mochafreddo/swing-trading-report/commit/9e96374b7c9be5310646c3f9e6f8a31f369752df))
* **ai-brief:** 후보 확장과 source chain fallback 보강 ([89acece](https://github.com/mochafreddo/swing-trading-report/commit/89acecedf73422783cfa618fb36d39445f9b6548))
* **backtest:** historical runner 추가 ([eb48c42](https://github.com/mochafreddo/swing-trading-report/commit/eb48c427e5fdf3cc11f3a4fae4a8665e6ea48408))
* **backtest:** historical runner 추가 ([e577e44](https://github.com/mochafreddo/swing-trading-report/commit/e577e445aa8f618fe71400db23a1fb97e0bcaca0))
* **cli:** 예약 Sell AI Brief 전달 명령 추가 ([b2e6b21](https://github.com/mochafreddo/swing-trading-report/commit/b2e6b212afa351d93507f9a885f20e806fb52067))
* **config:** entry 가격 누락 임계치 설정 추가 ([d19682d](https://github.com/mochafreddo/swing-trading-report/commit/d19682db3164e8ea4892c3e3fe964660ceddd1d7))
* **config:** 스윙 운영 안전 기본값 강화 ([211bc55](https://github.com/mochafreddo/swing-trading-report/commit/211bc555c9ca6e34d802d7ea819b2d58899bef84))
* **config:** 시장별 신규 진입 cap env 추가 ([5135bff](https://github.com/mochafreddo/swing-trading-report/commit/5135bfff67374f72c06ecd3b9ebbed30032e378b))
* **db:** 보유 종목 entry_pattern 쓰기 활성화 ([982d885](https://github.com/mochafreddo/swing-trading-report/commit/982d88546868464428d5c534d6cc1be7d19e25f4))
* **db:** 보유 종목 진입 패턴 컬럼 추가 ([1fc9013](https://github.com/mochafreddo/swing-trading-report/commit/1fc9013bb681f384667e5803c4c35ceba9a7d51a))
* **decision-board:** V0 계약 경계를 정의한다 ([b545ea5](https://github.com/mochafreddo/swing-trading-report/commit/b545ea510fbcd89c055eb04227d30ff745eb670d))
* **decision-board:** 공개 근거 계약을 확장한다 ([836d475](https://github.com/mochafreddo/swing-trading-report/commit/836d475384ff622ab9cbbe1960576131aa56be45))
* **decision-board:** 로컬 섀도 러너를 추가한다 ([403d949](https://github.com/mochafreddo/swing-trading-report/commit/403d949f356776e6b86225e62f11caec72f94ee9))
* **decision-board:** 로컬 실행 저널을 추가한다 ([076867e](https://github.com/mochafreddo/swing-trading-report/commit/076867e50aff364806758ca7016639c8fb71cb5c))
* **decision-board:** 버전 고정 종목 승인 경계 추가 ([b020bba](https://github.com/mochafreddo/swing-trading-report/commit/b020bba1ddcfa7cd20408cd83321e5fc1a28e285))
* **decision-board:** 브로커 스냅샷을 원자적으로 봉인한다 ([6a3aaca](https://github.com/mochafreddo/swing-trading-report/commit/6a3aaca73e800e7fa265ceba9f1e45e128350f37))
* **decision-board:** 순수 의사결정 컴파일러를 추가한다 ([b24b602](https://github.com/mochafreddo/swing-trading-report/commit/b24b6023d1924b73689dc247710c8c1b2891a926))
* **decision-board:** 안전한 shadow 의사결정 보드를 도입한다 ([05d7d03](https://github.com/mochafreddo/swing-trading-report/commit/05d7d03ce30c129c1e7d31668a43fcd4c537676a))
* **decision-board:** 클레임 근거 검증 경계를 추가한다 ([7e50c8d](https://github.com/mochafreddo/swing-trading-report/commit/7e50c8d336b4864fd3caf476b0ffbc7e761e5b53))
* **entry:** 설정 기반 가격 누락 실패 기준 적용 ([1d9b5a6](https://github.com/mochafreddo/swing-trading-report/commit/1d9b5a63b73246d1adb80cdd942a2343c8514551))
* **entry:** 유동성 청산 가능성 지표 추가 ([7b9daa2](https://github.com/mochafreddo/swing-trading-report/commit/7b9daa2372f389b6e1aeab838b9e73c5a1b7aae2))
* **entry:** 유동성 청산 가능성 지표 추가 ([2f2ada6](https://github.com/mochafreddo/swing-trading-report/commit/2f2ada663e91c277cb05b8dfa092aa5d8e7ed97f))
* **entry:** 진입 가격 진단 필드를 추가한다 ([fb3ed1e](https://github.com/mochafreddo/swing-trading-report/commit/fb3ed1e4bbfcda94eda9fc059b3493d8bc4f833a))
* **entry:** 투자 준비도 컨텍스트 분리 ([ccb21f4](https://github.com/mochafreddo/swing-trading-report/commit/ccb21f4075648eb49a556d370c1ba4324f4382d6))
* **entry:** 포트폴리오 노출 상한 추가 ([2af8aa0](https://github.com/mochafreddo/swing-trading-report/commit/2af8aa0a5dd06d35ff92c73015beaae26cf75e41))
* **holdings:** 진입 패턴 YAML 계약 추가 ([ccd166b](https://github.com/mochafreddo/swing-trading-report/commit/ccd166b898a59af9cbde0480fb847ed73a2204c0))
* **holdings:** 토스 보유종목 동기화 추가 ([1172bea](https://github.com/mochafreddo/swing-trading-report/commit/1172bea96c1948ec4bab1f0a8c2ae6952668dced))
* **observability:** 운영 로그 준비도 보강 ([b93206f](https://github.com/mochafreddo/swing-trading-report/commit/b93206ff9496138fd9958091d829d0042dc6cfd9))
* **report:** Decision Board 멱등 저장 경계를 추가한다 ([c69711f](https://github.com/mochafreddo/swing-trading-report/commit/c69711f5437b183a53df550ecd31e159c255e7c7))
* **reports:** 리스크 가이드 공시 추가 ([d8dad23](https://github.com/mochafreddo/swing-trading-report/commit/d8dad2394e47892f770ed55945596ed86d3dd77e))
* **research:** 제한된 증거 조사 경계를 추가한다 ([180eadb](https://github.com/mochafreddo/swing-trading-report/commit/180eadb799c5dbc6dfa84d633a2a401bb4e9d96e))
* **scheduler:** launchd 실행 로그를 attempt 단위로 보존 ([301ce07](https://github.com/mochafreddo/swing-trading-report/commit/301ce07ee8e63fafc245005a994b0aed9762efe7))
* **scheduler:** scan sell 업로드 전환 계약 추가 ([b986d4c](https://github.com/mochafreddo/swing-trading-report/commit/b986d4c057671063c73fdd7166137bc12a28e0b0))
* **scheduler:** 로컬 예약 파이프라인 운영 안정화 ([92b50c0](https://github.com/mochafreddo/swing-trading-report/commit/92b50c0bc56d67703adee907935e80da9360a230))
* **scheduler:** 매도 스케줄 런타임 상태 검증 추가 ([aa23b71](https://github.com/mochafreddo/swing-trading-report/commit/aa23b717991098f6660eac449f5436c68a827f0d))
* **scheduler:** 범용 launchd wrapper 골격 추가 ([8d8f151](https://github.com/mochafreddo/swing-trading-report/commit/8d8f15158cda8941a8b03765064a67ad7b1ad8a8))
* **scheduler:** 범용 scheduled state key 추가 ([0ecb19d](https://github.com/mochafreddo/swing-trading-report/commit/0ecb19d0dfba811849a08a30c81c67fb7985f316))
* **scheduler:** 상태 JSON 파일을 원자적으로 기록 ([8871963](https://github.com/mochafreddo/swing-trading-report/commit/8871963436469b5aa802ca9545101f9b09a59758))
* **scheduler:** 예약 Sell AI Brief 전달 경로 추가 ([aeef68f](https://github.com/mochafreddo/swing-trading-report/commit/aeef68faa578fd5f92bae0c9a1626c79dfb1dfd7))
* **scheduler:** 예약 Sell AI Brief 전달 러너 추가 ([1c452f3](https://github.com/mochafreddo/swing-trading-report/commit/1c452f37e402ae7c891145f2d7415855763c3592))
* **scheduler:** 예약 매도 AI Brief 생성 경로 추가 ([74ba02b](https://github.com/mochafreddo/swing-trading-report/commit/74ba02bb167b73818b5c0a637f6b8ebe375cec66))
* **scheduler:** 예약 매도 AI Brief 생성 경로 추가 ([0beeb71](https://github.com/mochafreddo/swing-trading-report/commit/0beeb717b28e589cf6363185b98ed0ec883830b4))
* **sell-ai-brief:** 매도 AI 판단 리포트 추가 ([3f4b1f1](https://github.com/mochafreddo/swing-trading-report/commit/3f4b1f16a20c9aa5b6e28980e7165e2e45e440bf))
* **sell-ai-brief:** 매도 AI 판단 리포트 추가 ([040e5e7](https://github.com/mochafreddo/swing-trading-report/commit/040e5e7332b52468b76c7dd90233156ceeb31879))
* **sell:** 하이브리드 부분매도 액션 추가 ([2d97ca3](https://github.com/mochafreddo/swing-trading-report/commit/2d97ca3c6d7f2bc7fe314c58f6bb270a1138a59f))
* **smoke:** live 통합 스모크 점검 추가 ([d84d1b3](https://github.com/mochafreddo/swing-trading-report/commit/d84d1b3acc4a9dda77b0d847b7fab54b4f28b8eb))
* **strategy:** 시장 레짐 unavailable 정책 설정을 추가한다 ([188e353](https://github.com/mochafreddo/swing-trading-report/commit/188e35345c15d35c2eef2b8e8c30ef0ab613bc60))
* **strategy:** 시장 레짐 unavailable 차단 정책을 구현한다 ([ca90f78](https://github.com/mochafreddo/swing-trading-report/commit/ca90f78954f023c6d706d207771f3bf22d69606c))
* **strategy:** 하이브리드 품질 정책과 패턴별 타임스탑 적용 ([02bae8f](https://github.com/mochafreddo/swing-trading-report/commit/02bae8ffaa9fb7403efc703db41b7296362e72fa))
* **strategy:** 하이브리드 후보 품질 정렬을 추가한다 ([d73ed71](https://github.com/mochafreddo/swing-trading-report/commit/d73ed710e570de19f7fd319e17ea9559f15b5c64))
* **strategy:** 하이브리드 후보의 리스크 정합성을 표시한다 ([00325d0](https://github.com/mochafreddo/swing-trading-report/commit/00325d09288ca8065b5b6a672503c7b9f29b36d8))
* **toss:** 예약 보유 싱크 엔드포인트 추가 ([49b1ed6](https://github.com/mochafreddo/swing-trading-report/commit/49b1ed693a5a3d887d9deab7a35ca4ddad0827ab))
* **toss:** 일일 자동 싱크 실행기 추가 ([28c433b](https://github.com/mochafreddo/swing-trading-report/commit/28c433be662f8d003e8f18a370a89b417a57ee29))
* **toss:** 확인 문구 없이 보유 싱크 적용 ([dd59981](https://github.com/mochafreddo/swing-trading-report/commit/dd599817e5433af6081255e62b5eee716316666b))
* **web:** holdings entry_pattern 편집을 지원 ([9f47916](https://github.com/mochafreddo/swing-trading-report/commit/9f4791626a67cbba168afba4c79f9082a17c4ee6))
* **web:** Toss 동기화 diffHash 표시 ([a78edea](https://github.com/mochafreddo/swing-trading-report/commit/a78edea8e9056242cb57ba28c7ce1f1a9e44ff1b))
* **web:** 디시전 보드 리포트 화면을 추가한다 ([f9239d4](https://github.com/mochafreddo/swing-trading-report/commit/f9239d412216e3298366661e6f394e2015482a62))
* **web:** 토스 US 보유 자동 매핑 개선 ([1537ac1](https://github.com/mochafreddo/swing-trading-report/commit/1537ac119d97bffb1db86509e481a356f3c8f8a4))


### Bug Fixes

* **ai-brief:** fake provider watch 계약 검증 ([e34821e](https://github.com/mochafreddo/swing-trading-report/commit/e34821e067afe20b418c2b353617589ff19b2ef1))
* **ai-brief:** GitHub fallback에 모델 fallback 설정 전달 ([5f8d971](https://github.com/mochafreddo/swing-trading-report/commit/5f8d97111f36c4b426c9826e4480d811663ea1b6))
* **ai-brief:** latency probe 기록을 안전하게 정리 ([842b2be](https://github.com/mochafreddo/swing-trading-report/commit/842b2be281294882d787c46465d09ceb0c064ccf))
* **ai-brief:** legacy summary와 source chain 검증 축소 ([446f2a7](https://github.com/mochafreddo/swing-trading-report/commit/446f2a7d1f679d027c4c75dc1b52ce0ea4e01a27))
* **ai-brief:** lightpanda 내비게이션 실패 감지 ([5d6da57](https://github.com/mochafreddo/swing-trading-report/commit/5d6da570328c56378d56aece87f7b8ef4eeef9af))
* **ai-brief:** OpenAI 응답 신뢰 경계를 강화 ([8cae87a](https://github.com/mochafreddo/swing-trading-report/commit/8cae87a3586c7de23baa5c2b69e851b51455440a))
* **ai-brief:** provider 후보 역할 경계 검증 ([23f7729](https://github.com/mochafreddo/swing-trading-report/commit/23f77299b95992fe203d58e014be81d94f8eebaf))
* **ai-brief:** source chain fallback 진단 보존 ([06e1aa2](https://github.com/mochafreddo/swing-trading-report/commit/06e1aa2cbe3a29fffe3031c4cf8394618b3737fc))
* **ai-brief:** source chain universe 경계 보강 ([13cd396](https://github.com/mochafreddo/swing-trading-report/commit/13cd396208973072c4b5a6181513cd98b9498d48))
* **ai-brief:** source chain 검증과 실패 코드 보강 ([5f337cc](https://github.com/mochafreddo/swing-trading-report/commit/5f337cc8f50b66543fc88cb56685ab1880c4589e))
* **ai-brief:** source chain 계약과 legacy 평가 보강 ([1ed8af3](https://github.com/mochafreddo/swing-trading-report/commit/1ed8af30d16f9a277b1b7adeb5ccfbf6f40f8b43))
* **ai-brief:** source chain 병합 기준 보정 ([9e5ec67](https://github.com/mochafreddo/swing-trading-report/commit/9e5ec67d1a32669c8d39545ca33d11e73e4a9de1))
* **ai-brief:** source provider 요약 검증 강화 ([eeba3db](https://github.com/mochafreddo/swing-trading-report/commit/eeba3db3d6b65707cee9d3013e787d8766f8e927))
* **ai-brief:** source ref 항목 타입 계약 강화 ([92834b4](https://github.com/mochafreddo/swing-trading-report/commit/92834b48126ce72fbc8bb1e5e6be33c956f13d4c))
* **ai-brief:** veto 격리 검증 순서 보완 ([5d69fcc](https://github.com/mochafreddo/swing-trading-report/commit/5d69fcc45e109a14b4e67f236f1efc99e1a75b02))
* **ai-brief:** watch source ref 오류를 fallback 처리 ([578ae00](https://github.com/mochafreddo/swing-trading-report/commit/578ae00f781aa80168c04f618af646883ff0a701))
* **ai-brief:** watch 검증 경계 강화 ([fbf40d7](https://github.com/mochafreddo/swing-trading-report/commit/fbf40d78ed621ec05071b3c861ff2052cb67a40c))
* **ai-brief:** watch 후보 action 검증 보강 ([9549519](https://github.com/mochafreddo/swing-trading-report/commit/954951902a9262b0292b1fcddc118ba92cd72224))
* **ai-brief:** watch 후보 출력 안전 검증 ([69c7522](https://github.com/mochafreddo/swing-trading-report/commit/69c75221a892e573cc74dda5d06ace70f2a56364))
* **ai-brief:** 검토 추적 로그 보강 ([d61d5c9](https://github.com/mochafreddo/swing-trading-report/commit/d61d5c9e426a8b5c6e941f94022d802dfeb600b3))
* **ai-brief:** 검토 추적 로그 보강 ([a720fb2](https://github.com/mochafreddo/swing-trading-report/commit/a720fb215292954885f11e4e637c0989d93363aa))
* **ai-brief:** 기사 리더 접근 경계 강화 ([cfc09ff](https://github.com/mochafreddo/swing-trading-report/commit/cfc09ff98ab6ab0ef7941007868145faaa54205a))
* **ai-brief:** 기사 읽기 시도 수 집계 수정 ([b764d17](https://github.com/mochafreddo/swing-trading-report/commit/b764d17e255320bc1efd824d6818c55f332d924d))
* **ai-brief:** 레거시 평가 입력 호환성 복구 ([ac720f4](https://github.com/mochafreddo/swing-trading-report/commit/ac720f4fb52c81f0c427c52013c193ec5fd238f1))
* **ai-brief:** 리뷰 지적 한국어 알림 누락 보완 ([aa37940](https://github.com/mochafreddo/swing-trading-report/commit/aa37940aec9842a6773414d45e99c9d5568ccb10))
* **ai-brief:** 매수 후보 판단 품질 게이트 강화 ([09b9375](https://github.com/mochafreddo/swing-trading-report/commit/09b93752e2906e4f40b871150116bed2c7300707))
* **ai-brief:** 모델 티커 스키마를 후보로 제한 ([126b82a](https://github.com/mochafreddo/swing-trading-report/commit/126b82ab00b7d56ad3e25f33589d143520286976))
* **ai-brief:** 비정상 실행 URL 처리 보강 ([5ae8ca2](https://github.com/mochafreddo/swing-trading-report/commit/5ae8ca2fe0e2da65b56fc169b26d2edf6a3763d5))
* **ai-brief:** 새 artifact 필드 검증 강화 ([04ea6db](https://github.com/mochafreddo/swing-trading-report/commit/04ea6dbfab6ba349a40b2de7a096360816e3f322))
* **ai-brief:** 소스 체인 우선순위와 타임아웃 보정 ([1698b24](https://github.com/mochafreddo/swing-trading-report/commit/1698b248d59193e5a9ee7523e01086ca84a4f052))
* **ai-brief:** 스케줄 source chain origin 보존 ([44a71a3](https://github.com/mochafreddo/swing-trading-report/commit/44a71a330da77ab232f345c7a38c204d9ce954e0))
* **ai-brief:** 스케줄 source chain secret 조건 정밀화 ([e975714](https://github.com/mochafreddo/swing-trading-report/commit/e975714bb6db31035483f67ef492e1f8f960851b))
* **ai-brief:** 실제 entry 사유 분류 보정 ([f731830](https://github.com/mochafreddo/swing-trading-report/commit/f7318308bdebbf06a6d125796ee98715b88d87b5))
* **ai-brief:** 실패 watch 대체 문구를 한국어화 ([a4988c7](https://github.com/mochafreddo/swing-trading-report/commit/a4988c79dcb187c61f8679fcd919c1c7f7d68c8b))
* **ai-brief:** 실행 URL 링크 검증 강화 ([b89c30e](https://github.com/mochafreddo/swing-trading-report/commit/b89c30e474d8ec188fea858513a79afec1d5c257))
* **ai-brief:** 알림 영어 누수 추가 보완 ([079929e](https://github.com/mochafreddo/swing-trading-report/commit/079929e71fc94d0843c4b43005d887ad3bad096c))
* **ai-brief:** 알림 후보 집계와 legacy 표시 보정 ([cf74e9e](https://github.com/mochafreddo/swing-trading-report/commit/cf74e9ec0188dd222dc850f19d77663b37a4d671))
* **ai-brief:** 외부 오류 메시지 민감정보 차단 ([0780b68](https://github.com/mochafreddo/swing-trading-report/commit/0780b68116356f6e192e597a3703df62fa1bb86c))
* **ai-brief:** 운영 안전 기본값 회귀 보강 ([efe5a90](https://github.com/mochafreddo/swing-trading-report/commit/efe5a909aa587d0bd3da8f77c0e5926ce3663f5f))
* **ai-brief:** 잘못된 veto 후보를 경고로 격리 ([73af164](https://github.com/mochafreddo/swing-trading-report/commit/73af16426c5fc58a7da5fd5f64e42c01867780e7))
* **ai-brief:** 장문 실행 URL 링크 제한 ([75b8472](https://github.com/mochafreddo/swing-trading-report/commit/75b8472d91bbc97564a0fb41a93de13e72f6b7d7))
* **ai-brief:** 전체 보유 한도 후보 분류 추가 ([ca5b9f6](https://github.com/mochafreddo/swing-trading-report/commit/ca5b9f672af31d1f1ab9a111ae2d2c7afc83e3f3))
* **ai-brief:** 중복 source ref 계약 차단 ([f19323c](https://github.com/mochafreddo/swing-trading-report/commit/f19323c1f33aaa2fac52411806d32b3a3ebe5da1))
* **ai-brief:** 추천 rank 타입 계약 강화 ([0c163cb](https://github.com/mochafreddo/swing-trading-report/commit/0c163cb1170aec0cbea552bac23f721e037a9987))
* **ai-brief:** 추천 source ref 오류를 후보 단위로 격리 ([3418c53](https://github.com/mochafreddo/swing-trading-report/commit/3418c5383ed49794a4a0d4d104159014aa8cd633))
* **ai-brief:** 추천 후보 문구와 http-json 체인 URL 보정 ([80718dd](https://github.com/mochafreddo/swing-trading-report/commit/80718dda14cedcb0a6c4f73ef981968e0967a362))
* **ai-brief:** 캡 제외 후보의 원본 액션을 보존 ([2901ad3](https://github.com/mochafreddo/swing-trading-report/commit/2901ad3badce8c626a12f5d49ed52846cbaff27d))
* **ai-brief:** 텔레그램 HTML parse mode 전송 ([4849a04](https://github.com/mochafreddo/swing-trading-report/commit/4849a04678f2e981718e4b4148b9e71a84dbccca))
* **ai-brief:** 텔레그램 HTML 장문 전송 보강 ([7c3f2d3](https://github.com/mochafreddo/swing-trading-report/commit/7c3f2d3d0dbb15e7e0d7f52493eed9d7e2ea2892))
* **ai-brief:** 텔레그램 모델 입력 수 복원 ([bff964f](https://github.com/mochafreddo/swing-trading-report/commit/bff964f7828b77d25d52244a03c1b8ad5b242a87))
* **ai-brief:** 평가기 watch 후보와 요약 개수 검증 ([6d9d592](https://github.com/mochafreddo/swing-trading-report/commit/6d9d592ada7bbc39b400e8ca97791c0950c09bb3))
* **ai-brief:** 평가기를 확장 후보 계약에 맞춤 ([44813ab](https://github.com/mochafreddo/swing-trading-report/commit/44813ab38494f8ed6afab5bb8745345a6773432d))
* **ai-brief:** 품질 게이트와 업로드 순서 보정 ([a1fc564](https://github.com/mochafreddo/swing-trading-report/commit/a1fc5644cd51b06d78c26b5fa54cb8d1b274f817))
* **ai-brief:** 후보 역할 경계 계약 보정 ([8b6f97d](https://github.com/mochafreddo/swing-trading-report/commit/8b6f97d57495e736b0456f8677c0155ea79ff65e))
* **calendar:** 거래일 캘린더 실패 폐쇄 보강 ([29c7268](https://github.com/mochafreddo/swing-trading-report/commit/29c72685487d5e740e74ebbe8578a96beaf292fa))
* **ci:** scheduled preflight와 wrapper 보안 보강 ([8d624cc](https://github.com/mochafreddo/swing-trading-report/commit/8d624cc6567995f647ef01c88c2c948a6bbb6a96))
* **ci:** Web 교차언어 테스트 환경을 준비한다 ([3c51ad1](https://github.com/mochafreddo/swing-trading-report/commit/3c51ad1d1b23db6e50d24b46ed557645e4ea9e02))
* **ci:** 빈 스케줄 스캔 보고서 처리 보강 ([cc678e0](https://github.com/mochafreddo/swing-trading-report/commit/cc678e0fc555c167713fd9d279116e139ff5e459))
* **ci:** 수동 워크플로 동시성과 Supabase fallback 정렬 ([e379dec](https://github.com/mochafreddo/swing-trading-report/commit/e379dec2546980138b6d614aee0eeda3d1dff2fb))
* **ci:** 알림 토큰과 cleanup 동시성 보강 ([cbd6217](https://github.com/mochafreddo/swing-trading-report/commit/cbd6217d78832693913f0793a6d4059fa359422e))
* **cli:** 예약 Sell AI Brief 실패 상태를 전파 ([a3c1614](https://github.com/mochafreddo/swing-trading-report/commit/a3c161473b4c02363323328ae60b6d35d2fd8b07))
* **config:** entry 임계치 bool 검증 강화 ([e5ac348](https://github.com/mochafreddo/swing-trading-report/commit/e5ac348cb37df0aabd03a5f3b310c12fa26f0a06))
* **config:** env 예시 충돌과 정렬 문서를 보정한다 ([18bbd35](https://github.com/mochafreddo/swing-trading-report/commit/18bbd356cfaef0abbdf8f4eedf30966706d247b7))
* **config:** 설정 검증 실패 경로 보강 ([46ea8c1](https://github.com/mochafreddo/swing-trading-report/commit/46ea8c1f8805d06f135cfafadaad6884a235d777))
* **config:** 스윙 진입 한도 설정 보강 ([0452cb2](https://github.com/mochafreddo/swing-trading-report/commit/0452cb2beb760c905be076f210841e726db3995f))
* **config:** 운영 안전 기본값 우회 차단 ([034658c](https://github.com/mochafreddo/swing-trading-report/commit/034658ca0950432d74fd69426e9d44e3d821de4f))
* **decision-board:** V0 계약 검증 경계를 강화한다 ([8d1d806](https://github.com/mochafreddo/swing-trading-report/commit/8d1d806a2867ffe27475e576c661077ec45b9984))
* **decision-board:** V0 입력 경계를 엄격히 검증한다 ([673befb](https://github.com/mochafreddo/swing-trading-report/commit/673befb2688e1ab2d5d83a1711fd8ba1db2b91c1))
* **decision-board:** 공개 URL path 문법을 고정한다 ([08f114f](https://github.com/mochafreddo/swing-trading-report/commit/08f114f089151f09f437ee9daa747a259583cc73))
* **decision-board:** 공개 계약과 검증 경계를 강화한다 ([8b9fe73](https://github.com/mochafreddo/swing-trading-report/commit/8b9fe733aa1d8b6fd6d462d94449022387c4073a))
* **decision-board:** 공개 근거 URL을 제한한다 ([815395d](https://github.com/mochafreddo/swing-trading-report/commit/815395d835ba948e4a54413a62bb44ddfe2df165))
* **decision-board:** 근거 provenance 경계를 복원한다 ([a9cc28a](https://github.com/mochafreddo/swing-trading-report/commit/a9cc28a301a66bc4d119a17b2b10cc9b41396bf1))
* **decision-board:** 단일 스레드 FD 경계를 강제한다 ([3184f0c](https://github.com/mochafreddo/swing-trading-report/commit/3184f0c85a0c5f80620003932270f46075e96d4a))
* **decision-board:** 발급된 중첩 값의 소유권을 고정한다 ([9926fe7](https://github.com/mochafreddo/swing-trading-report/commit/9926fe7db650ae56829fd2d4e341f1b42afec0d3))
* **decision-board:** 봉인 시각과 종목 타입 경계를 강화 ([bdfc6fc](https://github.com/mochafreddo/swing-trading-report/commit/bdfc6fcdbcd87235e1f2ca95b8745270788a34c2))
* **decision-board:** 실행 저널 FD 소유권을 격리한다 ([8c75035](https://github.com/mochafreddo/swing-trading-report/commit/8c7503568bf8b6695a47b7140111990d9eab24e8))
* **decision-board:** 실행 저널 경계를 강화한다 ([c2b7816](https://github.com/mochafreddo/swing-trading-report/commit/c2b781688f805d38411af25dc1d36e3b1b2c1acd))
* **decision-board:** 실행 저널 경로 권한을 완결한다 ([0013646](https://github.com/mochafreddo/swing-trading-report/commit/0013646ba12057dc934554d64af869be05bbe159))
* **decision-board:** 실행 저널 권한을 고정한다 ([756a1c8](https://github.com/mochafreddo/swing-trading-report/commit/756a1c817e38069f311fb44c958f9c304a6841e4))
* **decision-board:** 저널 공개 값을 고정한다 ([9b8d3a4](https://github.com/mochafreddo/swing-trading-report/commit/9b8d3a42760c572d13bdeb7b7874a09551ec7dde))
* **decision-board:** 저널 트랜잭션 시그널 경계를 묶는다 ([e9d86be](https://github.com/mochafreddo/swing-trading-report/commit/e9d86be2bd957afe46a5ce3064dc5a8e3bf0352f))
* **decision-board:** 정렬 스칼라 발급 경계를 강화한다 ([47b2e69](https://github.com/mochafreddo/swing-trading-report/commit/47b2e698847dfbb76a70d64f8076f5e0e4d717bc))
* **decision-board:** 종목 승인 경계를 불변 검증으로 강화 ([2da514d](https://github.com/mochafreddo/swing-trading-report/commit/2da514d6f3f8a11720fff6af742a89eb7423e302))
* **decision-board:** 컴파일러 발급 권위를 결속한다 ([a61dc3b](https://github.com/mochafreddo/swing-trading-report/commit/a61dc3bdb8854af4ef2d0eec6616b21926a3e011))
* **decision-board:** 클레임 발급 권위를 스냅샷에 결속한다 ([9a96cce](https://github.com/mochafreddo/swing-trading-report/commit/9a96cce998697e6838af660c2ad9acf9a68cdfb0))
* **decision-board:** 파일 변경 진입 순서를 보강한다 ([0333b5e](https://github.com/mochafreddo/swing-trading-report/commit/0333b5e5e6957ca4e9fa5f23dfe0395817b6c75d))
* **deps:** 취약 의존성 패치 ([72afffd](https://github.com/mochafreddo/swing-trading-report/commit/72afffd6a4a3c3da0d0a2a57c036ec9160d6d385))
* **entry:** KIS 해외 현재가 스냅샷 신선도 보강 ([0f46f3e](https://github.com/mochafreddo/swing-trading-report/commit/0f46f3e04d4b588b5e95ece6041944db8a91fb79))
* **entry:** KIS 해외 현재가 스냅샷 신선도 보강 ([cf23277](https://github.com/mochafreddo/swing-trading-report/commit/cf2327777ea4905b8200f3ce59fa5093c5d01613))
* **entry:** US KIS 가격 스냅샷 방어를 보강한다 ([380b001](https://github.com/mochafreddo/swing-trading-report/commit/380b00150fccd435f8d6c23943291edfbcffa162))
* **entry:** 리스크 불일치 후보 자동 진입 차단 ([e99fcf2](https://github.com/mochafreddo/swing-trading-report/commit/e99fcf2b583cc02d98a1469faa9d013eee56325f))
* **entry:** 미국 KIS 진입가 스냅샷 신선도를 검증 ([ca268ea](https://github.com/mochafreddo/swing-trading-report/commit/ca268ea4528986d548e247140d57ab45a629a3de))
* **env:** 스레드 상속 컨텍스트의 환경 억제 누수 방지 ([d6c0973](https://github.com/mochafreddo/swing-trading-report/commit/d6c0973ead38ee1d18ad94978b9b147a348b7636))
* **holdings:** 토스 동기화 자릿수 비교 보정 ([47f8c27](https://github.com/mochafreddo/swing-trading-report/commit/47f8c27e571e1976722c8b99894efd72023089e1))
* **notify:** 슬랙 요약 필드의 줄 삽입을 차단 ([5911b63](https://github.com/mochafreddo/swing-trading-report/commit/5911b63622f1edc193e205c8237fb56795ec3440))
* **observability:** 내부 로그 구조화 보강 ([4ec7461](https://github.com/mochafreddo/swing-trading-report/commit/4ec74610535e82b904c68a72a1bd8881d1c571eb))
* **ops:** 운영 안전 기본값 보강 ([58103eb](https://github.com/mochafreddo/swing-trading-report/commit/58103eb5705deb7571a71c0ec5fa3b3a8cd357f5))
* **ops:** 운영 안전 기본값 회귀를 보강한다 ([241b400](https://github.com/mochafreddo/swing-trading-report/commit/241b400e36454e177218dcd79741d6199e43c7b5))
* **qa:** ISSUE-001 — 보조 evidence disclosure 접근성 보강 ([33601c0](https://github.com/mochafreddo/swing-trading-report/commit/33601c0fe71eb3fde01697bf542f78f35acd654e))
* **qa:** ISSUE-002 — evidence row 배지 overflow 방지 ([98103ac](https://github.com/mochafreddo/swing-trading-report/commit/98103ac1d84bc27e3d40a8fec9f69ac4e1a141a9))
* **replay:** adversarial 리뷰 지적사항 보강 ([42b43cb](https://github.com/mochafreddo/swing-trading-report/commit/42b43cb5f2b29c3024862813bfc2a09537695d27))
* **replay:** updater 오류 출력을 정리 ([b3af7f4](https://github.com/mochafreddo/swing-trading-report/commit/b3af7f41d3aac1d97489070028a117a26125f70a))
* **replay:** 기대값 갱신 경로 검증 강화 ([74e5665](https://github.com/mochafreddo/swing-trading-report/commit/74e566573f8c45453fc3d2d9f69366a34d78b6a5))
* **replay:** 리플레이 메타데이터 신뢰성 보강 ([533119e](https://github.com/mochafreddo/swing-trading-report/commit/533119ef6031a9768c943236a1b8ba1c7022d458))
* **replay:** 벤치마크 fixture 해석 공유화 ([899d9ca](https://github.com/mochafreddo/swing-trading-report/commit/899d9ca4a789a26cbeae3589ad96e6c1dd7f06e6))
* **report:** Decision Board 잠금과 인덱스 조회를 강화한다 ([ae83d73](https://github.com/mochafreddo/swing-trading-report/commit/ae83d73c5437710aa41baca93806e00414a980ea))
* **report:** Decision Board 저장 경쟁 조건을 차단한다 ([1b498f2](https://github.com/mochafreddo/swing-trading-report/commit/1b498f238d987a06c053d9d127063c824dbbfc86))
* **report:** Decision Board 정리와 최신 조회를 완결한다 ([516f788](https://github.com/mochafreddo/swing-trading-report/commit/516f78855cb388b40bda953b0ff906c0a7131fb4))
* **report:** Decision Board 중단 정리를 보장한다 ([d69c529](https://github.com/mochafreddo/swing-trading-report/commit/d69c529439b34d6ec7518481d1ec86ef4b29467f))
* **reports:** Decision Board 조회 안정성을 높인다 ([6a246d0](https://github.com/mochafreddo/swing-trading-report/commit/6a246d05fa29e4de6b4057419cc99586cbe36f4d))
* **reports:** Supabase 업로드 요청 예외 처리 ([dd2d079](https://github.com/mochafreddo/swing-trading-report/commit/dd2d07954004539eda2129594e763948225b1760))
* **reports:** 리포트 인덱스와 로컬 검증 강화 ([07dabe6](https://github.com/mochafreddo/swing-trading-report/commit/07dabe6bf7a9696f416311218a06eec85b20785b))
* **research:** 성공 결과와 부분 만료 경계를 봉인한다 ([ee193b9](https://github.com/mochafreddo/swing-trading-report/commit/ee193b9ec581d1b7ce9e05b818c21d239ed30e01))
* **research:** 입력 스냅샷 경계를 격리한다 ([1f1d75a](https://github.com/mochafreddo/swing-trading-report/commit/1f1d75a3db57603033c0c430fc42f44dc0bf5527))
* **research:** 증거 조사 신뢰 경계를 강화한다 ([560042e](https://github.com/mochafreddo/swing-trading-report/commit/560042ec47eeca8f37f3dd2c89aa6f965e7cf3aa))
* **research:** 최종 결과 경계를 심층 검증한다 ([89a3b2d](https://github.com/mochafreddo/swing-trading-report/commit/89a3b2df3a7df9a4f0ccd32f46298f8e253f1f60))
* **review:** 서브에이전트 검토 지적 사항 해결 ([a657762](https://github.com/mochafreddo/swing-trading-report/commit/a657762ee6e0abdcac07ed53c47e3e827880c60f))
* **review:** 코드 리뷰 지적 사항 보완 ([844fa4b](https://github.com/mochafreddo/swing-trading-report/commit/844fa4b4ca4f4ef693ce87dadf7a147361676d74))
* **safety:** 운영 안전 기본값 우회 차단 ([3c725a9](https://github.com/mochafreddo/swing-trading-report/commit/3c725a967b7662696a1535b487ebeeeaa74668ba))
* **scheduler:** AI Brief 보유목록 충돌 수정 ([601a745](https://github.com/mochafreddo/swing-trading-report/commit/601a7456d4755b18701201530f24214d7227c6df))
* **scheduler:** AI Brief 텔레그램 HTML 전송 설정 ([28d3a53](https://github.com/mochafreddo/swing-trading-report/commit/28d3a53db7003da8e68791cf029b5ffc4f052437))
* **scheduler:** AI 브리프 지연 알림 방어 강화 ([e7411d0](https://github.com/mochafreddo/swing-trading-report/commit/e7411d04e840da03113827b8cb954a46392cbb89))
* **scheduler:** entry failure storage key 보존 ([d9728d5](https://github.com/mochafreddo/swing-trading-report/commit/d9728d59988fca37e64fa31905097e6fc0496763))
* **scheduler:** entry 실패 진단에 report 경로 추가 ([b644b51](https://github.com/mochafreddo/swing-trading-report/commit/b644b511e5e90aa72308ce52491cb0e9a04240ca))
* **scheduler:** generic state attempt key shape 보강 ([56e8feb](https://github.com/mochafreddo/swing-trading-report/commit/56e8febeef587e0b5b606e39eb093146754e5d5a))
* **scheduler:** generic state key 공백 토큰을 거부 ([b7712fc](https://github.com/mochafreddo/swing-trading-report/commit/b7712fc6efab7394d740feab03468ecdd58300a3))
* **scheduler:** generic state key 안전 범위를 좁힘 ([260edfd](https://github.com/mochafreddo/swing-trading-report/commit/260edfd09cee8f57ad06364b686d21b0adda39f5))
* **scheduler:** generic wrapper 인자 검증 보강 ([c001d70](https://github.com/mochafreddo/swing-trading-report/commit/c001d700e48cf05d5a935a8890e8ca5410b94b81))
* **scheduler:** latency probe와 upload 계약을 fail-closed로 보강 ([7bd101e](https://github.com/mochafreddo/swing-trading-report/commit/7bd101e32af785561fdae81e8e31a6383936b2d3))
* **scheduler:** launchd attempt 로그 경로를 설계와 맞춤 ([224c739](https://github.com/mochafreddo/swing-trading-report/commit/224c739d7773bac9b9668d3a0a8db5c9ded28e42))
* **scheduler:** launchd host 로그 보안을 보강 ([0a01329](https://github.com/mochafreddo/swing-trading-report/commit/0a01329fe02af13f7fadd398a67b63f7e706d20a))
* **scheduler:** lock 상실 후 상태 게시를 차단한다 ([05b7a71](https://github.com/mochafreddo/swing-trading-report/commit/05b7a7125871e6e21f1853e3fdabd87cab384627))
* **scheduler:** scheduled pipeline review 지적사항 보완 ([8dcad92](https://github.com/mochafreddo/swing-trading-report/commit/8dcad92f3f439514c7c88b163dd6fa9ea9553611))
* **scheduler:** scheduled source 설정 방어 강화 ([afe0f11](https://github.com/mochafreddo/swing-trading-report/commit/afe0f1128ef46f1cf01607d428b2d2e107a0a7c7))
* **scheduler:** Sell AI Brief 알림 클레임 해제 조건 수정 ([f1161b6](https://github.com/mochafreddo/swing-trading-report/commit/f1161b65d0c528363251a4e69f8aafaf8381fce7))
* **scheduler:** Sell AI Brief 예약 전달 중복을 차단 ([98da72c](https://github.com/mochafreddo/swing-trading-report/commit/98da72ce6de81e852ab46a1ddf502e7758c44fda))
* **scheduler:** Sell AI Brief 재조정 실패 상태를 보존 ([d8b238f](https://github.com/mochafreddo/swing-trading-report/commit/d8b238f10f9b067ef9fc342e4714e036f951c830))
* **scheduler:** Sell AI Brief 전달 검증 보강 ([ab1be67](https://github.com/mochafreddo/swing-trading-report/commit/ab1be67571dcdbf6096d5dfdf282827e4d3fa40f))
* **scheduler:** Sell AI Brief 중복 알림을 차단 ([9e9adbe](https://github.com/mochafreddo/swing-trading-report/commit/9e9adbe29e949a44f3f381d3680d96a504101f33))
* **scheduler:** stale runner 외부 게시 차단 ([dfa5340](https://github.com/mochafreddo/swing-trading-report/commit/dfa534057c760f54636984dc3cebac629b2e83fa))
* **scheduler:** stdout 준비 실패를 host 알림으로 처리 ([564d9b9](https://github.com/mochafreddo/swing-trading-report/commit/564d9b98297fe2cbd1a31f005327cf98935264f3))
* **scheduler:** wrapper stdout 캡처 실패를 처리 ([b533a6e](https://github.com/mochafreddo/swing-trading-report/commit/b533a6ea9dd2975139335bd816951e555010ee89))
* **scheduler:** 구조화 실패의 host 알림 중복 억제 ([9820b28](https://github.com/mochafreddo/swing-trading-report/commit/9820b285a94c3b79e00e0854a24f791b301b1a70))
* **scheduler:** 락 상실 시 외부 쓰기 차단 ([44ca91a](https://github.com/mochafreddo/swing-trading-report/commit/44ca91a2321cab45b8495b2070f4db425ced871f))
* **scheduler:** 런타임 검증 기준을 생성 게이트와 맞춤 ([7da61eb](https://github.com/mochafreddo/swing-trading-report/commit/7da61eba6835e8810377a788350d885af94d7ec6))
* **scheduler:** 런타임 실패 경로를 안전하게 처리 ([d0a743e](https://github.com/mochafreddo/swing-trading-report/commit/d0a743e89f9ee732f927313a4704ae3bd174856d))
* **scheduler:** 리뷰 지적 운영 안전장치 보강 ([be7d6a8](https://github.com/mochafreddo/swing-trading-report/commit/be7d6a8b8fd78e94165080dde6a0085c35cdbd37))
* **scheduler:** 보유 종목 패턴을 스케줄 export에 보존 ([b3dd5d2](https://github.com/mochafreddo/swing-trading-report/commit/b3dd5d2f9c3692be92bb55e6bbadcad2682e0f5b))
* **scheduler:** 상태 파일 실패가 실행 결과를 덮지 않게 처리 ([b5e7f98](https://github.com/mochafreddo/swing-trading-report/commit/b5e7f98c6b8707ac0091da36824f24f058efa6b0))
* **scheduler:** 예약 Sell AI Brief 알림 중복 방지 보강 ([9f5497c](https://github.com/mochafreddo/swing-trading-report/commit/9f5497cdea9cf3d870eb1171fbf2054b9583ee3e))
* **scheduler:** 예약 매도 AI Brief 실행 경로 보강 ([1940cff](https://github.com/mochafreddo/swing-trading-report/commit/1940cff49870fd393edbf16658567b3cf3fb0370))
* **scheduler:** 예약 매도 AI Brief 안정성 보강 ([4199cdb](https://github.com/mochafreddo/swing-trading-report/commit/4199cdb2a2b307946f3d13ff8c255d950994e6ea))
* **scheduler:** 예약 파이프라인 내부 업로드를 억제한다 ([00b7c59](https://github.com/mochafreddo/swing-trading-report/commit/00b7c592ea13b58c3fdfb340d04a15dae7ddaaee))
* **scheduler:** 운영 안전 기본값 회귀 수정 ([5eed32e](https://github.com/mochafreddo/swing-trading-report/commit/5eed32eb156bf02b8c056a3e06baf3208931aef6))
* **sell:** 예약 생성 보유목록을 Supabase 스냅샷으로 고정 ([d8918e1](https://github.com/mochafreddo/swing-trading-report/commit/d8918e17f93475258ec3e094b59ab6de2bf8fe70))
* **sell:** 예약 생성 보유목록을 Supabase 스냅샷으로 고정 ([d77a533](https://github.com/mochafreddo/swing-trading-report/commit/d77a5334115893673458fc6997fef47caef7fa00))
* **snapshot:** DB 권위 토큰 경계를 강화한다 ([36642df](https://github.com/mochafreddo/swing-trading-report/commit/36642df13162f600d231ff7e32b7739d981b474d))
* **snapshot:** 브로커 스냅샷 봉인 경계를 강화 ([1c28ead](https://github.com/mochafreddo/swing-trading-report/commit/1c28eada89c95c35cd23d3f1c751d71f2d895e5b))
* **strategy:** hybrid 거래량 기준을 통일 ([5d1c843](https://github.com/mochafreddo/swing-trading-report/commit/5d1c8432677cf864a21507201700ca639aaa2a00))
* **strategy:** 리뷰 findings를 해결한다 ([fd070cb](https://github.com/mochafreddo/swing-trading-report/commit/fd070cbb09588c594ac99d68ec08b5bffbf81ba8))
* **strategy:** 스윙 로직 경계 조건 보강 ([3f6275f](https://github.com/mochafreddo/swing-trading-report/commit/3f6275fd3d9b5ee0b20311f11f666ec510f3c370))
* **strategy:** 시장 레짐 차단 시장 판정을 통일한다 ([7429678](https://github.com/mochafreddo/swing-trading-report/commit/7429678e023d183faf1edc5fb3cfe9852c3d00be))
* **test:** US replay fixture 날짜를 고정 ([7e2bc51](https://github.com/mochafreddo/swing-trading-report/commit/7e2bc5141c1002f2d166795a9de44f9f02ab63b7))
* **test:** US replay 시장 상태를 고정 ([a73c0fc](https://github.com/mochafreddo/swing-trading-report/commit/a73c0fc2defeba3b5fa39a66b6d0ee471d520558))
* **toss:** launchd 실행 PATH 부트스트랩 추가 ([7a8b228](https://github.com/mochafreddo/swing-trading-report/commit/7a8b2289b17e42f9501f5f641669688e2badf951))
* **toss:** 동기화 QA 실행 경계 강화 ([878ffdf](https://github.com/mochafreddo/swing-trading-report/commit/878ffdfaed5735d5a70c2be3eb74496339039c9f))
* **toss:** 신호 판단 전 자동 싱크 예약 ([c50e80b](https://github.com/mochafreddo/swing-trading-report/commit/c50e80b2da244f6b2a24207522a04f67e69c48e4))
* **toss:** 예약 동기화 누락 보유종목 격리 ([8d2fb1d](https://github.com/mochafreddo/swing-trading-report/commit/8d2fb1dd2a312d47f0551e7fa9b78d8e9d0ada53))
* **toss:** 예약 동기화 누락 보유종목을 격리 ([9818e12](https://github.com/mochafreddo/swing-trading-report/commit/9818e129f8ef0e809a73f1ae111eb39811211a0c))
* **toss:** 예약 실행 시간대 가드 추가 ([2e0298a](https://github.com/mochafreddo/swing-trading-report/commit/2e0298a3663151e0029302c88446ec3ef289224c))
* **toss:** 예약 싱크 실패 응답 계약 보강 ([c9017f8](https://github.com/mochafreddo/swing-trading-report/commit/c9017f8377a8358696f8998d5dc7fb853e5ae0c8))
* **toss:** 예약 싱크 실행 경계 보강 ([82c2d74](https://github.com/mochafreddo/swing-trading-report/commit/82c2d74734a73ca946e9688cbb46549042f5e493))
* **toss:** 자동 동기화 안전 경계 강화 ([aecd6a5](https://github.com/mochafreddo/swing-trading-report/commit/aecd6a5c5630cbbbc5dad3b6382c1230b5427b96))
* **toss:** 자동 싱크 env 적용과 실패 상태 검증 보강 ([2e8a372](https://github.com/mochafreddo/swing-trading-report/commit/2e8a37241c6e657657e00f3e6758adc2ce49dec2))
* **toss:** 자동 싱크 런타임 env 연결 보강 ([53f4e19](https://github.com/mochafreddo/swing-trading-report/commit/53f4e19b1df119eabf95e265cfee9e12ddd9660c))
* **toss:** 자동 싱크 오류 요약과 문서 정합성 보강 ([8f828a5](https://github.com/mochafreddo/swing-trading-report/commit/8f828a53100ce7c8732d06f4ee79c853d0e8158a))
* **web:** API JSON 응답과 본문 파싱 경계 강화 ([f408d45](https://github.com/mochafreddo/swing-trading-report/commit/f408d45ad84e4ac79eebce906bf0af565d876ec7))
* **web:** Docker build test 입력을 제외한다 ([7f7c7c3](https://github.com/mochafreddo/swing-trading-report/commit/7f7c7c3663cba924a64f381e16db5b8498822134))
* **web:** favicon 404 해소 ([38f382a](https://github.com/mochafreddo/swing-trading-report/commit/38f382ade58438572a51fe2b17b17b36188355b1))
* **web:** Next proxy 인증 경계를 복구 ([4262e89](https://github.com/mochafreddo/swing-trading-report/commit/4262e890bed4b36e2e3df75643c468bd900c97ff))
* **web:** T9 저널 reader 경계를 재사용한다 ([c194e2b](https://github.com/mochafreddo/swing-trading-report/commit/c194e2b39fe44a09d61efaffd1bb75dbe14d8dda))
* **web:** 디시전 보드 공개 경계를 강화한다 ([d65c5ce](https://github.com/mochafreddo/swing-trading-report/commit/d65c5ce187886c4091d8e191af68c23aed36e772))
* **web:** 로그인 검증 메시지를 인라인으로 표시 ([cf40b1c](https://github.com/mochafreddo/swing-trading-report/commit/cf40b1cb212f26d739e621d2b9ca57036172bdfa))
* **web:** 로컬 Docker 로그인 쿠키 설정 보정 ([00a622d](https://github.com/mochafreddo/swing-trading-report/commit/00a622dcb2a48901501031bfde5eeec339fef4bd))
* **web:** 로컬 저널 파일 경계를 강화한다 ([2fbbd41](https://github.com/mochafreddo/swing-trading-report/commit/2fbbd412b4a7ff298ac1dfee953fc8a2f9d077b4))
* **web:** 루트 env 로더 추가 ([f288003](https://github.com/mochafreddo/swing-trading-report/commit/f28800330df401920870037a56e67066b198a2dd))
* **web:** 루트 env를 웹 실행에 사용 ([041a4bc](https://github.com/mochafreddo/swing-trading-report/commit/041a4bc0d8321bac997ff2c62ad5e0ad5a8346a4))
* **web:** 리포트와 holdings 안전성을 보강 ([a825cba](https://github.com/mochafreddo/swing-trading-report/commit/a825cbaaac8b0dffa15c5e56f071a2bf32be63eb))
* **web:** 빈 리포트 검색에서 이전 선택을 제거한다 ([eddddde](https://github.com/mochafreddo/swing-trading-report/commit/eddddde651a01ddd5249b458954f2f67bb712b2a))
* **web:** 저널 helper Docker 경계를 고정한다 ([402344f](https://github.com/mochafreddo/swing-trading-report/commit/402344fa3027b26a2425ba31edfa4db0e8539839))
* **web:** 취약한 렌더링 의존성을 갱신한다 ([7f94211](https://github.com/mochafreddo/swing-trading-report/commit/7f942118c9e3d51a0de1c2e230d48b8a57c8a181))
* **web:** 토스 싱크 변경 그룹 간격 보정 ([8e97f73](https://github.com/mochafreddo/swing-trading-report/commit/8e97f73e8e2b0431f051ca9441b38a0b4a65a430))
* **web:** 토스 환경변수 compose 전달 ([4320f1a](https://github.com/mochafreddo/swing-trading-report/commit/4320f1af4eae6f526425185975e11bb26bbc3556))
* **workflow:** fatal entry 리포트 artifact 보존 ([acf615a](https://github.com/mochafreddo/swing-trading-report/commit/acf615a95c47b0969761c6779a79b8dbc59cc103))
* **workflow:** 예약 컨텍스트 output 주입을 차단한다 ([ea6e098](https://github.com/mochafreddo/swing-trading-report/commit/ea6e098db68d3879b8929095ff0d40ec63a8d27f))
* 코드베이스 리뷰 결함 수정 ([0b0e983](https://github.com/mochafreddo/swing-trading-report/commit/0b0e983a80562f76967ea2c3879406cc75b99d06))
* 코드베이스 리뷰 지적사항 보강 ([207ce67](https://github.com/mochafreddo/swing-trading-report/commit/207ce67feea25407cf7360d77535d31ff8c87e6c))


### Reverts

* **todos:** 범위 밖 줄바꿈 변경 되돌리기 ([fe8d776](https://github.com/mochafreddo/swing-trading-report/commit/fe8d776666518331a1b3844199bdbb686e87c091))


### Documentation

* **agents:** GPT-5.5 기준으로 에이전트 지침 정리 ([9ea6408](https://github.com/mochafreddo/swing-trading-report/commit/9ea640870e8035f68395c6c5fbacd9036d52e664))
* **agents:** 로컬 전용 지침 파일 안내 추가 ([d362287](https://github.com/mochafreddo/swing-trading-report/commit/d36228791d57d5ed567965e1179adcf0d10e8b7e))
* **agents:** 지침을 간소화 ([23cc0aa](https://github.com/mochafreddo/swing-trading-report/commit/23cc0aa4ac9d39cd06f68157e24e6c5744716503))
* **ai-brief:** source ref partial publish 구현 계획 추가 ([4d6a0a1](https://github.com/mochafreddo/swing-trading-report/commit/4d6a0a1e4174c046223cdfc8544a14bfb10572bc))
* **ai-brief:** source ref partial publish 설계 추가 ([002ecc8](https://github.com/mochafreddo/swing-trading-report/commit/002ecc8cfb19fad31043a24721bef70e555adf13))
* **ai-brief:** source ref partial publish 운영 계약 기록 ([30158bd](https://github.com/mochafreddo/swing-trading-report/commit/30158bd235df7e0e9ca6d8bb9988304a19380252))
* **ai-brief:** source ref 구현 상태 최신화 ([f624d99](https://github.com/mochafreddo/swing-trading-report/commit/f624d99dd2781506f9377739cb1d44d5384a74cc))
* **ai-brief:** 검토 추적 운영 문서 보강 ([9877e3e](https://github.com/mochafreddo/swing-trading-report/commit/9877e3eec936bf12f510bc96b1e609ed9d4282a9))
* **ai-brief:** 구현 계획 테스트 이름 보정 ([be407f3](https://github.com/mochafreddo/swing-trading-report/commit/be407f3ec56d8ed56229ff5b1d91a733d1f05629))
* **ai-brief:** 기사 리더 계약 최신화 ([4317bcf](https://github.com/mochafreddo/swing-trading-report/commit/4317bcf85bf7f0ec59ac113eb1421c243a2ac24e))
* **ai-brief:** 모델 veto 진단과 host 알림 기준 문서화 ([f244753](https://github.com/mochafreddo/swing-trading-report/commit/f2447530dc2644d80e8ebb1a4cf3574d9bc683d9))
* **ai-brief:** 모델 계약 문서 동기화 ([df8be29](https://github.com/mochafreddo/swing-trading-report/commit/df8be29962e61cafc79605d1a9435dd0e7ab94be))
* **ai-brief:** 모델 계약 알림 구현 계획 추가 ([866027c](https://github.com/mochafreddo/swing-trading-report/commit/866027ccde33783554ddb0c3c30adaebc8732d7d))
* **ai-brief:** 모델 계약 알림 설계 추가 ([12f098e](https://github.com/mochafreddo/swing-trading-report/commit/12f098e356413cbc187b26901d042676af46b09f))
* **ai-brief:** 설계 문서 상태 메타 보완 ([b21b436](https://github.com/mochafreddo/swing-trading-report/commit/b21b436a445cd3f54ade14fb34b4e5dcade80b2f))
* **ai-brief:** 설계 문서 상태 메타데이터 보정 ([d98ec00](https://github.com/mochafreddo/swing-trading-report/commit/d98ec006d883c6847e0d877a0f97adc411d80cdd))
* **ai-brief:** 텔레그램 리치 텍스트 구현 계획 추가 ([eafc5a4](https://github.com/mochafreddo/swing-trading-report/commit/eafc5a423868f35a9bd8f77d50d60f71396369dd))
* **ai-brief:** 텔레그램 리치 텍스트 설계 추가 ([70b3809](https://github.com/mochafreddo/swing-trading-report/commit/70b380957f143fc8da5fe434d063778fe14b246f))
* **ai-brief:** 텔레그램 알림 운영 문서 최신화 ([1ccdc45](https://github.com/mochafreddo/swing-trading-report/commit/1ccdc456d830cf11c0a5fce5c9ff18538d45fe94))
* **ai-brief:** 텔레그램 전송 계획 문구 정리 ([58f689d](https://github.com/mochafreddo/swing-trading-report/commit/58f689d77d9a0ad79cc0766335c2f24546edf0bb))
* **ai-brief:** 평가와 업로드 흐름 최신화 ([1af8363](https://github.com/mochafreddo/swing-trading-report/commit/1af8363a9b7bd763091205d0391ca045ae126a72))
* **ai-brief:** 한국어 알림 계약 문서화 ([eb3b732](https://github.com/mochafreddo/swing-trading-report/commit/eb3b732e0b0915f486362535420df0637d63e4a9))
* **ai-brief:** 한국어 알림 구현 계획 ([1968a39](https://github.com/mochafreddo/swing-trading-report/commit/1968a39e40a93b3fb1bf081f8353f381d17fb333))
* **ai-brief:** 한국어 알림 설계 상태 갱신 ([dad80da](https://github.com/mochafreddo/swing-trading-report/commit/dad80daab08b25a277c6ca21b55013c82448a79d))
* **ai-brief:** 한국어 텔레그램 알림 설계 ([444c6f6](https://github.com/mochafreddo/swing-trading-report/commit/444c6f604c06426904eb76414b911408a18a8ca2))
* **ai-brief:** 후보 확장 설계 추가 ([1834498](https://github.com/mochafreddo/swing-trading-report/commit/1834498c99790a560fe451fd80fe93365d74dc74))
* **ai-brief:** 후보 확장과 source chain 계약 정리 ([9f41ebc](https://github.com/mochafreddo/swing-trading-report/commit/9f41ebc795026be955cc4e1b8945bb9173f5c959))
* **architecture:** AI Brief 텔레그램 HTML 알림 기록 ([4369721](https://github.com/mochafreddo/swing-trading-report/commit/43697213cc41c664b55c35e3fdb6479f70714c74))
* **backtest:** 문서 진입점의 backtest 설명 보강 ([ae17596](https://github.com/mochafreddo/swing-trading-report/commit/ae175963027be448c97a52e014aea4b6bcdbb840))
* **config:** env 파일 역할 정리 ([986e2ff](https://github.com/mochafreddo/swing-trading-report/commit/986e2ff2888e8573cc2ea3fbf9c7db3dba284e16))
* **config:** 스윙 운영 안전 기본값 문서화 ([15e9ed0](https://github.com/mochafreddo/swing-trading-report/commit/15e9ed086f15d2d279f839cabab5d3a7625f92b7))
* **config:** 시장별 entry cap override 문서화 ([07831ce](https://github.com/mochafreddo/swing-trading-report/commit/07831cecf9420a48d7796b6abe54eeb8d2e8e8b4))
* **config:** 안전 기본값 문서 계약을 정정한다 ([caeb41e](https://github.com/mochafreddo/swing-trading-report/commit/caeb41e76daecba7804dfdeb83b8dacaeab9e30b))
* **decision-board:** shadow 졸업 기준을 문서화한다 ([6fa48b0](https://github.com/mochafreddo/swing-trading-report/commit/6fa48b01538b926b08c531c08e2ad75380b9d875))
* **decision-board:** 보안 재검토 결과를 기록한다 ([8715000](https://github.com/mochafreddo/swing-trading-report/commit/8715000d62d213f23a1c8bc62193d0a7c5e39e45))
* **decision-board:** 인접 보안 검증을 기록한다 ([d08dda9](https://github.com/mochafreddo/swing-trading-report/commit/d08dda993f70ad715a8827a902ac183c5c8d18f7))
* **decision-board:** 저널 헬퍼 경로를 바로잡는다 ([5f19661](https://github.com/mochafreddo/swing-trading-report/commit/5f19661a0b750cfe3c4de7616d9e621e2a36191d))
* **decision-board:** 최종 Python 게이트를 갱신한다 ([d255ab5](https://github.com/mochafreddo/swing-trading-report/commit/d255ab5b8d1888765a63abcee1dce0b795e3b1fa))
* **decision-board:** 최종 보안 검증을 기록한다 ([db72efe](https://github.com/mochafreddo/swing-trading-report/commit/db72efe20fe530c73d69d206bf4b2da71fcc54ae))
* **deploy:** 워크플로 트리거 설명 정정 ([692c1a3](https://github.com/mochafreddo/swing-trading-report/commit/692c1a351fa03ace3fb0e8de707b2538afa6f353))
* **design:** Evidence Ledger 디자인 시스템 추가 ([ab8cd5f](https://github.com/mochafreddo/swing-trading-report/commit/ab8cd5f15fde7ecec863e69cc0c03f8fd7d3c669))
* **design:** 디자인 리뷰 후속 항목 기록 ([c20ca46](https://github.com/mochafreddo/swing-trading-report/commit/c20ca4660186062698ace2a4ce021399adf6b570))
* **design:** 지연된 모바일 디자인 과제 기록 ([86c5a34](https://github.com/mochafreddo/swing-trading-report/commit/86c5a3446fb9bf39a0b81a74f24bea875a9e52d3))
* **holdings:** entry_pattern 운영 계약을 최신화 ([092762b](https://github.com/mochafreddo/swing-trading-report/commit/092762be0523fca232e51fdb6fcf51414018a003))
* **holdings:** 진입 패턴 운영 문서 갱신 ([4f4abbe](https://github.com/mochafreddo/swing-trading-report/commit/4f4abbea75b4dfff489d6f3d63ed8880bdf0dfd9))
* **ops:** 로컬 env 점검 절차를 정정 ([4a4dc6e](https://github.com/mochafreddo/swing-trading-report/commit/4a4dc6e023a93450719470113dfe29b36025f4ad))
* **plan:** AI 브리프 기사 검증 구현 계획 추가 ([6ede7de](https://github.com/mochafreddo/swing-trading-report/commit/6ede7de213e15ec80d58b9dfe0de4b35ae5a9045))
* **plan:** entry cap override 계획 완료 표시 ([88cf4cf](https://github.com/mochafreddo/swing-trading-report/commit/88cf4cffb8d9e0750ae5ae97f590f599589fd441))
* **plan:** entry_pattern 계획 검토 반영 ([918c2b4](https://github.com/mochafreddo/swing-trading-report/commit/918c2b4ac399e801756f0cbdabadd47f65733854))
* **plan:** env 파일 정리 계획 추가 ([ddf500d](https://github.com/mochafreddo/swing-trading-report/commit/ddf500dddbddce08b1a6917f4816ade3fe25f2fc))
* **plan:** hybrid 거래량 구현 계획 추가 ([2dad0a4](https://github.com/mochafreddo/swing-trading-report/commit/2dad0a451ea4982301ff5abd59b794d3b0dfc08f))
* **plan:** 스윙 운영 안전 구현 계획 추가 ([4e0f15f](https://github.com/mochafreddo/swing-trading-report/commit/4e0f15fc25231dd4a8b61cf5367c2dae47b6675c))
* **plan:** 시장별 entry cap override 설계 추가 ([5599e70](https://github.com/mochafreddo/swing-trading-report/commit/5599e704ae4b8704fc4f130e7c22b1f26726d054))
* **plan:** 예약 Sell AI Brief 전달 계획 추가 ([7dfe18b](https://github.com/mochafreddo/swing-trading-report/commit/7dfe18b3de91b2eb9ac058d23e7c7dd0e5de0559))
* **plan:** 진입 패턴 Phase A 안전 경계 보강 ([544352a](https://github.com/mochafreddo/swing-trading-report/commit/544352a29c43b284f0c21a23ffdafb1692935c85))
* **plan:** 진입 패턴 계획 검증 보강 ([1eb08bb](https://github.com/mochafreddo/swing-trading-report/commit/1eb08bbb8366399b14d0b655caae8bca10b9aabe))
* **plan:** 진입 패턴 계획 검토 보강 ([0b00660](https://github.com/mochafreddo/swing-trading-report/commit/0b00660be8fa240493b348aa5c51b9db7e82ec9e))
* **plan:** 진입 패턴 계획 리뷰 반영 ([02e4cf2](https://github.com/mochafreddo/swing-trading-report/commit/02e4cf2b3956133fd783a75d2798189103047b07))
* **plan:** 진입 패턴 계획 리뷰 반영 ([60ba259](https://github.com/mochafreddo/swing-trading-report/commit/60ba259d3042b795283cc7f4cc42b95f628ef2bc))
* **plan:** 진입 패턴 계획 리뷰 반영 ([31d48ce](https://github.com/mochafreddo/swing-trading-report/commit/31d48ce7ac2db91f62b0f278b2880b8b6ad40480))
* **plan:** 진입 패턴 계획 리뷰 반영 ([63fa9af](https://github.com/mochafreddo/swing-trading-report/commit/63fa9afce7e78c6b521772db59bd4f1105d613c0))
* **plan:** 진입 패턴 계획 리뷰 반영 ([a4daee1](https://github.com/mochafreddo/swing-trading-report/commit/a4daee1faf281d1432b160459a48847d5563d66d))
* **plan:** 진입 패턴 계획 리뷰 반영 ([3017cb8](https://github.com/mochafreddo/swing-trading-report/commit/3017cb89ba7f4cdc6c008627832a0857ed546b64))
* **plan:** 진입 패턴 계획 리뷰 반영 ([1b69079](https://github.com/mochafreddo/swing-trading-report/commit/1b69079bd1ad88ba1d3dd9b4678c8e2a1ea78ec7))
* **plan:** 진입 패턴 계획 리뷰 반영 ([a4e3799](https://github.com/mochafreddo/swing-trading-report/commit/a4e37996a995325ae2ca9ac9fe84fd0011ec84f3))
* **plan:** 진입 패턴 계획 리뷰 반영 ([be3c7ba](https://github.com/mochafreddo/swing-trading-report/commit/be3c7bab51f442b332ac20b00189d1b14110bad7))
* **plan:** 진입 패턴 계획 리뷰 반영 ([4b4a638](https://github.com/mochafreddo/swing-trading-report/commit/4b4a6386b2f79012cd32bf2277bb964a4f8b9626))
* **plan:** 진입 패턴 계획 리뷰 보완 ([d37173a](https://github.com/mochafreddo/swing-trading-report/commit/d37173aff9acddc11025367a186bb20223da8ebb))
* **plan:** 진입 패턴 계획 리뷰 피드백 반영 ([74a0052](https://github.com/mochafreddo/swing-trading-report/commit/74a00524564e1d6284d128bcf6e54ec965a9eadf))
* **plan:** 진입 패턴 계획 보강 ([f4cb22b](https://github.com/mochafreddo/swing-trading-report/commit/f4cb22bfcdef49a7272c70fdfa64e067fa68900a))
* **plan:** 진입 패턴 계획 실행 경계 보강 ([d310d7a](https://github.com/mochafreddo/swing-trading-report/commit/d310d7add1e6e6cb51a6e1579483dbab59300304))
* **plan:** 진입 패턴 보존 계획 보강 ([07ebcb8](https://github.com/mochafreddo/swing-trading-report/commit/07ebcb8344bdfa906b61981ef8831930f08c80dc))
* **plan:** 진입 패턴 보존 계획 보강 ([816ef52](https://github.com/mochafreddo/swing-trading-report/commit/816ef52864c3199132801173d1204454fd98176e))
* **plan:** 진입 패턴 보존 계획 보강 ([25a8edf](https://github.com/mochafreddo/swing-trading-report/commit/25a8edf1a86803df64c55799879d46062452017d))
* **plan:** 진입 패턴 보존 계획 보강 ([f03fc7a](https://github.com/mochafreddo/swing-trading-report/commit/f03fc7a318b42ad04eb7099a40cf20ac21565a59))
* **plan:** 진입 패턴 보존 계획 보강 ([662e2d3](https://github.com/mochafreddo/swing-trading-report/commit/662e2d3f798f74091f9fee2022ad3a9e73ea49e5))
* **plan:** 진입 패턴 보존 계획 보강 ([4562500](https://github.com/mochafreddo/swing-trading-report/commit/4562500460dafdee671e8a2cffec89fbd007be95))
* **qa:** favicon 404 후속 작업 기록 ([b57699a](https://github.com/mochafreddo/swing-trading-report/commit/b57699a38c517bc56b0890bbb3e5d81de2c01cb5))
* **qa:** 로컬 브라우저 QA 기준을 문서화한다 ([0b71534](https://github.com/mochafreddo/swing-trading-report/commit/0b715341621c821a99302dadf6026998a6398ac3))
* **replay:** 스윙 리플레이 커버리지 구현 계획 추가 ([9e6f2b2](https://github.com/mochafreddo/swing-trading-report/commit/9e6f2b2aa9461d2a7ba87df9f41914c0fc342a31))
* **replay:** 스윙 리플레이 커버리지 설계 추가 ([f89ecd6](https://github.com/mochafreddo/swing-trading-report/commit/f89ecd60c828901a56a73eb0f2c82125004a7106))
* **scheduler:** scheduled pipeline 문서 릴리스 보강 ([e946dc7](https://github.com/mochafreddo/swing-trading-report/commit/e946dc7cc4c3c50027b3ff91295b7786d0e334df))
* **scheduler:** 로컬 예약 파이프라인 설계 추가 ([441d01d](https://github.com/mochafreddo/swing-trading-report/commit/441d01d219c437e7b57b1dea9ab5da847210deee))
* **scheduler:** 로컬 예약 파이프라인 실행 계획 추가 ([ed44c1f](https://github.com/mochafreddo/swing-trading-report/commit/ed44c1f777717d882e7426791a58af0315a6c1e1))
* **scheduler:** 설계 리뷰 지적 반영 ([e2a2468](https://github.com/mochafreddo/swing-trading-report/commit/e2a2468f03be6ac716f0a7249e3100c037faaddb))
* **scheduler:** 예약 Sell AI Brief 전달 계약 문서화 ([47113da](https://github.com/mochafreddo/swing-trading-report/commit/47113da35e916c612bb3a8b14e9307024e6dc8e3))
* **scheduler:** 예약 매도 AI Brief 문서 보강 ([fafdd26](https://github.com/mochafreddo/swing-trading-report/commit/fafdd266f0a8435bd52648d38ca32fffe2218c6f))
* **sell-ai-brief:** 소스 체인 예시 보강 ([149f188](https://github.com/mochafreddo/swing-trading-report/commit/149f188e8b338ffff31e313482981da7a1164cc3))
* **specs:** AI 브리프 기사 검증 설계 추가 ([008b6a7](https://github.com/mochafreddo/swing-trading-report/commit/008b6a7fcac916454bb897fa644f1dcff6fbb468))
* **specs:** 상태 메타데이터 한국어 형식 추가 ([80c5fcc](https://github.com/mochafreddo/swing-trading-report/commit/80c5fccd843ad561dfc1d433d6e73b05d978aaad))
* **spec:** 서브에이전트 설계 리뷰 반영 ([7f32f27](https://github.com/mochafreddo/swing-trading-report/commit/7f32f2794d91608d81cf9bddfb792f2070771eb6))
* **spec:** 스윙 운영 안전 기본값 설계 추가 ([b195bed](https://github.com/mochafreddo/swing-trading-report/commit/b195bedb474848f76b9069a1ec4d740ce575d8ed))
* **strategy:** hybrid quality A 추세 필터 결정 문서화 ([e9cc4ab](https://github.com/mochafreddo/swing-trading-report/commit/e9cc4ab7201d6d0142c98a1fbf62aecdfc9ab81e))
* **strategy:** hybrid quality A 추세 필터 결정 문서화 ([7da22c5](https://github.com/mochafreddo/swing-trading-report/commit/7da22c50e4106ec734499304098e20391e755ba9))
* **strategy:** hybrid 거래량 기준을 문서화 ([60d9eb8](https://github.com/mochafreddo/swing-trading-report/commit/60d9eb86ad2e95e6bf2e568165c0fbdfb1e90d74))
* **strategy:** hybrid 거래량 의미 설계 추가 ([ed747db](https://github.com/mochafreddo/swing-trading-report/commit/ed747db748bd9e4a29939c91dac8315bc8278e35))
* **strategy:** 리플레이와 백테스트 범위 구분 ([c71eec6](https://github.com/mochafreddo/swing-trading-report/commit/c71eec66adcb4044d4dc2f93e640f4a39e23a6a7))
* **strategy:** 스윙 개선 계획 리뷰 지적을 반영한다 ([ad7f7b8](https://github.com/mochafreddo/swing-trading-report/commit/ad7f7b8935cbd038f4c03f7bc8011c85844df1c7))
* **strategy:** 스윙 개선 계획의 레짐 기록 책임을 명확히 한다 ([2ca499b](https://github.com/mochafreddo/swing-trading-report/commit/2ca499b4c5cbd7c2e166cef4f63fe46b7a739515))
* **strategy:** 스윙 개선 계획의 실행성 지적을 반영한다 ([fec321c](https://github.com/mochafreddo/swing-trading-report/commit/fec321c6b991017004c770fe2dd5c2711e19f148))
* **strategy:** 스윙 개선 계획의 잔여 리뷰 지적을 반영한다 ([371b703](https://github.com/mochafreddo/swing-trading-report/commit/371b7034473e8d594b415b770cf0fb618a1639ee))
* **strategy:** 스윙 개선 계획의 진입 진단 테스트를 보강한다 ([ba8efbf](https://github.com/mochafreddo/swing-trading-report/commit/ba8efbf6846c2bd951184aecb0a9a867678d93ab))
* **strategy:** 스윙 개선 계획의 테스트 계약을 보강한다 ([a6884ed](https://github.com/mochafreddo/swing-trading-report/commit/a6884ede656285327a0e8ea4810d8602ce46c20e))
* **strategy:** 스윙 개선 계획의 테스트 계약을 보강한다 ([76ab42f](https://github.com/mochafreddo/swing-trading-report/commit/76ab42f4e88ead3257eff624cc27882d8d5010c4))
* **strategy:** 스윙 개선 구현 계획을 작성한다 ([5a93c3b](https://github.com/mochafreddo/swing-trading-report/commit/5a93c3bce2f769f435c928f09d4a58681e0defd9))
* **strategy:** 스윙 개선 설정과 리포트 계약을 문서화한다 ([22a6c43](https://github.com/mochafreddo/swing-trading-report/commit/22a6c43e321f470c33c87b81602cc64139a92142))
* **strategy:** 스윙 개선 스펙 리뷰를 반영한다 ([0bbc5c0](https://github.com/mochafreddo/swing-trading-report/commit/0bbc5c0475f7680cdd83677072521bb1a1a96a2e))
* **strategy:** 스윙 로직 개선 설계를 추가한다 ([3b01330](https://github.com/mochafreddo/swing-trading-report/commit/3b01330844d5b3c201fc593c4157c949697cdec5))
* **todo:** AI Brief 구조 부채 추적 ([ac50588](https://github.com/mochafreddo/swing-trading-report/commit/ac50588d65a858b16dbb8e9a839a18b7db4b59dc))
* **todo:** quality_state 후속 과제 문구 정정 ([82704bc](https://github.com/mochafreddo/swing-trading-report/commit/82704bcb572d2239c4a8e7c36e421b152a396633))
* **todos:** TODO 줄바꿈을 soft-wrap으로 정리 ([43a79b2](https://github.com/mochafreddo/swing-trading-report/commit/43a79b2677a69fc6a01a7c3952a96e1b1b0b1b6e))
* **todos:** 미국 장후 매도 브리프 TODO 추가 ([a68ba11](https://github.com/mochafreddo/swing-trading-report/commit/a68ba11ce4a89ae99f2c4bc8d2dbeba47ff87d39))
* **todos:** 할 일 우선순위 정렬 ([579b5c5](https://github.com/mochafreddo/swing-trading-report/commit/579b5c5b2bb322c74ff404ac70bbff8d450f1635))
* **todos:** 히스토리컬 백테스트 후속 작업 추가 ([29b13fe](https://github.com/mochafreddo/swing-trading-report/commit/29b13feea9ca6da3c231769e1ce88a2d4928deff))
* **todo:** 스윙 전략 후속 과제 기록 ([fded12c](https://github.com/mochafreddo/swing-trading-report/commit/fded12c3d334f9323439a188a8f9fdfd70dd8155))
* **todo:** 예약 매도 구조 부채 추적 ([fe4fee2](https://github.com/mochafreddo/swing-trading-report/commit/fe4fee299c16986156b6fba0e61aff2ce3cfe29d))
* **todo:** 포지션 사이징 작업을 유예 ([ea8e4d6](https://github.com/mochafreddo/swing-trading-report/commit/ea8e4d6c487df2d11276ade75c5f3db51d4c3d25))
* **toss:** 일일 자동 싱크 구현 계획 추가 ([37b58e7](https://github.com/mochafreddo/swing-trading-report/commit/37b58e75acfdc741e8bed38e38d73560fc6798c5))
* **toss:** 일일 자동 싱크 설계 추가 ([2706249](https://github.com/mochafreddo/swing-trading-report/commit/27062490429ed6d5abf6f7d226aaee0a5f672034))
* **toss:** 일일 자동 싱크 운영 문서화 ([c21c64e](https://github.com/mochafreddo/swing-trading-report/commit/c21c64e19ce5257e2415017115e77e21d6c0e5fe))
* **toss:** 자동 매핑 설계 상태 메타 보강 ([ffe4a8b](https://github.com/mochafreddo/swing-trading-report/commit/ffe4a8ba9d4f5c797f2bf5b33af7363e44bd5a45))
* **toss:** 자동 싱크 설계 상태 갱신 ([8e31b35](https://github.com/mochafreddo/swing-trading-report/commit/8e31b35e8fe318554b390bca76b165c65599a6d1))
* **toss:** 자동 싱크 운영 문서 보강 ([07f658c](https://github.com/mochafreddo/swing-trading-report/commit/07f658c018c52a0760071f8faa04b5fed3ce5534))
* **web:** 인증 경계 운영 문서 최신화 ([02d0d65](https://github.com/mochafreddo/swing-trading-report/commit/02d0d65f06772e3220d3ad58529f90156caccd0a))
* 계획 문서 상태 메타 정리 ([a7eafa7](https://github.com/mochafreddo/swing-trading-report/commit/a7eafa73c94e59b82a0a2427ca913859b4383e90))
* 문서 체계 전면 개편 ([fd4b388](https://github.com/mochafreddo/swing-trading-report/commit/fd4b3887308615724b841d54012a9a36c068fd0c))
* 문서 탐색성과 검증 명령 정리 ([cd7ac77](https://github.com/mochafreddo/swing-trading-report/commit/cd7ac778be6f1f4ac977a76062e5b6df32e3602c))

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
