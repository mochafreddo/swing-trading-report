# swing-trading-report

미국 주식의 장전 매수 후보와 매매 계획을 제공하고 스윙 트레이딩 학습을 돕는 개인 도구다. 기존 구현을 정리하고 처음부터 재구축하며, Git 이력과 라이선스는 유지한다.

첫 마일스톤의 요구사항과 완료 기준을 확정했으며, 아직 구현은 시작하지 않았다. 운영 환경은 로컬 Mac이며, 보고서는 텔레그램으로 전달한다. AI 설명에는 OpenAI API를 사용하고 주문은 사용자가 직접 실행한다.

- [첫 버전의 요구사항](docs/requirements.md)
- [첫 보고서 구현 계획](docs/first-milestone.md)
- [도메인 용어](CONTEXT.md)
- [AI 입력 범위 결정](docs/adr/0001-public-data-ai.md)
- [한 종목 평가 실행](docs/single-run.md)
- [텔레그램 단건 전송과 수신 확인](docs/telegram-delivery.md)
- [전체 종목군 평가 실행과 현재 한계](docs/universe-run.md)
- [CI 설계와 로컬 검증](docs/ci-design.md)
