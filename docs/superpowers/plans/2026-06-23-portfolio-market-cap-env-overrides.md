# Portfolio Market Cap Env Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe environment overrides for `portfolio.max_new_entries_per_market.KR` and `portfolio.max_new_entries_per_market.US` so operators can temporarily tighten per-market entry caps without editing committed YAML defaults.

**Architecture:** Keep `config.yaml` as the primary source for committed non-secret defaults, and add two narrow env/YAML conflict-bound overrides: `PORTFOLIO_MAX_NEW_ENTRIES_KR` and `PORTFOLIO_MAX_NEW_ENTRIES_US`. Preserve existing portfolio guard semantics: market caps count only newly accepted `ENTER` rows in the current run, not existing active holdings.

**Tech Stack:** Python 3.14, `sab/config.py`, pytest config-contract tests, repository docs, existing `uv`/`just` validation commands.

## Global Constraints

- Make the smallest safe change that fully resolves the active backlog item.
- Keep `portfolio.max_active_holdings` behavior unchanged.
- Preserve existing YAML support for `portfolio.max_new_entries_per_market` with case-insensitive `KR`/`US` keys.
- Env/YAML duplicates must fail closed through the existing config conflict policy.
- Do not add env overrides for `portfolio.exposure_limits[]` in this change; list-shaped exposure policy remains YAML-only.
- Keep `.env.example` examples commented so the repository default `.env.example` does not conflict with committed `config.yaml`.
- Use Korean Conventional Commit messages if committing.

---

상태: Archive (completed)

이 계획은 2026-06-23 기준으로 구현, 문서화, 검증, 정리까지 완료되었다. 아래 체크박스는 완료 기록으로 유지한다.

## Design Decision

Choose env overrides rather than only documenting a local YAML workflow.

Reasons:

- `PORTFOLIO_MAX_ACTIVE_HOLDINGS` already exists as an env-bound portfolio guard, so per-market new-entry caps should follow the same operator model.
- Risk-off tightening is a short-lived operational override; env values are better suited than editing committed `config.yaml`.
- The existing conflict policy already gives the needed safety boundary: if a selected YAML config owns a cap, the matching env override must be removed or the YAML key must be omitted.
- Keeping the override per market avoids a fragile encoded map env such as `KR=0,US=1` and matches existing market-specific env naming such as `MARKET_CACHE_STALE_SESSIONS_KR`.

The new variables are:

| Env | YAML path | Meaning |
| --- | --- | --- |
| `PORTFOLIO_MAX_NEW_ENTRIES_KR` | `portfolio.max_new_entries_per_market.KR` | Max newly accepted KR `ENTER` rows in one `sab entry` run |
| `PORTFOLIO_MAX_NEW_ENTRIES_US` | `portfolio.max_new_entries_per_market.US` | Max newly accepted US `ENTER` rows in one `sab entry` run |

## File Structure

- Modify `sab/config.py`: add env/YAML bindings, parse env-backed KR/US market caps, and make conflict detection preserve current case-insensitive YAML market-key behavior.
- Modify `tests/test_config_validation_layers.py`: prove env parsing, null/omitted behavior, and invalid env rejection.
- Modify `tests/test_config_conflict_policy.py`: prove env/YAML duplicates fail closed, including lowercase YAML market keys.
- Modify `tests/test_env_example_v11.py`: prove `.env.example` documents the new env keys but keeps them inactive.
- Modify `tests/test_docs_state_contract.py`: prove configuration docs and deep reference document the new contract.
- Modify `.env.example`: add commented operator examples near existing portfolio env examples.
- Modify `docs/configuration.md`: add operator-facing rows and a risk-off usage note.
- Modify `docs/config-reference.md`: add binding rows, add runtime env summary rows, and remove KR/US market caps from YAML-only notes.
- Modify `TODOS.md`: move the active backlog item to Completed after code, docs, and tests pass.

## Scope Check

This is one config-loading contract. It should stay in one implementation task because the code, tests, docs, and backlog closeout all describe the same two env keys. There is no web runtime, Supabase schema, strategy-rule, or report-shape change.

### Task 1: Config Parser And Conflict Policy

**Files:**
- Modify: `sab/config.py`
- Test: `tests/test_config_validation_layers.py`
- Test: `tests/test_config_conflict_policy.py`

**Interfaces:**
- Consumes: existing `_ConfigParser`, `_ENV_YAML_CONFLICT_BINDINGS`, `_parse_optional_int`, and `_validate_portfolio_ranges`.
- Produces: `Config.portfolio.max_new_entries_kr` and `Config.portfolio.max_new_entries_us` resolved from env when the matching YAML key is absent.

- [x] **Step 1: Add failing env parsing tests**

In `tests/test_config_validation_layers.py`, add the two env keys to `_reset_config_env()`:

```python
"PORTFOLIO_MAX_NEW_ENTRIES_KR",
"PORTFOLIO_MAX_NEW_ENTRIES_US",
```

Add this test after `test_load_config_parses_portfolio_caps`:

```python
def test_load_config_parses_portfolio_market_caps_from_env_when_yaml_omits_caps(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "portfolio:\n  max_active_holdings: 8\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("PORTFOLIO_MAX_NEW_ENTRIES_KR", "0")
    monkeypatch.setenv("PORTFOLIO_MAX_NEW_ENTRIES_US", "2")

    cfg = load_config()

    assert cfg.portfolio.max_active_holdings == 8
    assert cfg.portfolio.max_new_entries_kr == 0
    assert cfg.portfolio.max_new_entries_us == 2
```

Add this parametrized invalid-env test near the invalid portfolio config tests:

```python
@pytest.mark.parametrize(
    ("env_key", "env_value", "error_path"),
    [
        (
            "PORTFOLIO_MAX_NEW_ENTRIES_KR",
            "true",
            "portfolio.max_new_entries_per_market.KR",
        ),
        (
            "PORTFOLIO_MAX_NEW_ENTRIES_US",
            "-1",
            "portfolio.max_new_entries_per_market.US",
        ),
    ],
)
def test_load_config_rejects_invalid_portfolio_market_cap_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    env_value: str,
    error_path: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("portfolio: {}\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv(env_key, env_value)

    with pytest.raises(ConfigLoadError, match=error_path):
        load_config()
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_config_validation_layers.py::test_load_config_parses_portfolio_market_caps_from_env_when_yaml_omits_caps \
  tests/test_config_validation_layers.py::test_load_config_rejects_invalid_portfolio_market_cap_env \
  -q
```

Expected: the env parsing test fails because the new env keys are not read yet.

- [x] **Step 3: Add failing conflict-policy tests**

In `tests/test_config_conflict_policy.py`, add the two env keys to `_reset_conflict_env()`:

```python
"PORTFOLIO_MAX_NEW_ENTRIES_KR",
"PORTFOLIO_MAX_NEW_ENTRIES_US",
```

Add this test after `test_load_config_rejects_entry_fatal_missing_price_ratio_env_yaml_conflict`:

```python
def test_load_config_rejects_portfolio_market_cap_env_yaml_conflict_case_insensitive(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
portfolio:
  max_new_entries_per_market:
    kr: 1
    US: 1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_conflict_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("PORTFOLIO_MAX_NEW_ENTRIES_KR", "0")
    monkeypatch.setenv("PORTFOLIO_MAX_NEW_ENTRIES_US", "0")

    with pytest.raises(
        ConfigLoadError,
        match="Config conflict policy violation",
    ) as exc:
        load_config()

    msg = str(exc.value)
    assert (
        "PORTFOLIO_MAX_NEW_ENTRIES_KR "
        "(portfolio.max_new_entries_per_market.KR)"
    ) in msg
    assert (
        "PORTFOLIO_MAX_NEW_ENTRIES_US "
        "(portfolio.max_new_entries_per_market.US)"
    ) in msg
```

- [x] **Step 4: Run conflict test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_config_conflict_policy.py::test_load_config_rejects_portfolio_market_cap_env_yaml_conflict_case_insensitive \
  -q
```

Expected: the test fails because the new env keys are not conflict-bound yet.

- [x] **Step 5: Add bindings and scoped conflict path detection**

In `sab/config.py`, add these rows immediately after `("PORTFOLIO_MAX_ACTIVE_HOLDINGS", "portfolio.max_active_holdings")`:

```python
(
    "PORTFOLIO_MAX_NEW_ENTRIES_KR",
    "portfolio.max_new_entries_per_market.KR",
),
(
    "PORTFOLIO_MAX_NEW_ENTRIES_US",
    "portfolio.max_new_entries_per_market.US",
),
```

Add this constant near `_DOTTED_ENV_YAML_BINDING_KEYS`:

```python
_PORTFOLIO_MARKET_CAP_PATH_PREFIX = "portfolio.max_new_entries_per_market."
```

Add these helpers above `_collect_env_yaml_conflicts`:

```python
def _portfolio_market_cap_yaml_path_exists(
    parser: _ConfigParser, yaml_path: str
) -> bool:
    if not yaml_path.startswith(_PORTFOLIO_MARKET_CAP_PATH_PREFIX):
        return parser.has_yaml_path(yaml_path)

    market = yaml_path.removeprefix(_PORTFOLIO_MARKET_CAP_PATH_PREFIX).strip().upper()
    raw_caps = parser.from_yaml("portfolio.max_new_entries_per_market")
    if raw_caps is None:
        return False
    if not isinstance(raw_caps, dict):
        return parser.has_yaml_path("portfolio.max_new_entries_per_market")
    return any(str(key).strip().upper() == market for key in raw_caps)


def _binding_yaml_path_exists(parser: _ConfigParser, yaml_path: str) -> bool:
    if yaml_path.startswith(_PORTFOLIO_MARKET_CAP_PATH_PREFIX):
        return _portfolio_market_cap_yaml_path_exists(parser, yaml_path)
    return parser.has_yaml_path(yaml_path)
```

Change `_collect_env_yaml_conflicts()` to use the new helper:

```python
def _collect_env_yaml_conflicts(parser: _ConfigParser) -> list[str]:
    conflicts: set[str] = set()
    for env_key, yaml_path in _ENV_YAML_CONFLICT_BINDINGS:
        if getenv(env_key) is None:
            continue
        if _binding_yaml_path_exists(parser, yaml_path):
            conflicts.add(f"{env_key} ({yaml_path})")
    return sorted(conflicts)
```

- [x] **Step 6: Refactor optional integer parsing for env-backed market caps**

In `sab/config.py`, replace `_parse_optional_int()` with this raw-value helper plus wrapper:

```python
def _parse_optional_int_raw(raw: Any, *, path: str, source: str) -> int | None:
    if raw is None:
        return None

    if isinstance(raw, bool):
        raise ConfigLoadError(
            f"Invalid config value '{path}': {source} must be an integer or null, got {raw!r}."
        )

    try:
        return int(raw)
    except (TypeError, ValueError) as err:
        raise ConfigLoadError(
            f"Invalid config value '{path}': {source} must be an integer or null, got {raw!r}."
        ) from err


def _parse_optional_int(
    parser: _ConfigParser, *, path: str, env_key: str | None = None
) -> int | None:
    env_value = getenv(env_key) if env_key is not None else None
    if env_value is not None:
        return _parse_optional_int_raw(
            env_value,
            path=path,
            source=f"environment variable '{env_key}'",
        )
    return _parse_optional_int_raw(
        parser.from_yaml(path),
        path=path,
        source=f"config.yaml '{path}'",
    )
```

Add this helper above `_parse_portfolio_section()`:

```python
def _parse_portfolio_market_cap(
    market_caps: dict[str, Any],
    *,
    market: str,
    env_value: str | None,
    env_key: str,
) -> int | None:
    path = f"portfolio.max_new_entries_per_market.{market}"
    if env_value is not None:
        return _parse_optional_int_raw(
            env_value,
            path=path,
            source=f"environment variable '{env_key}'",
        )

    for key, value in market_caps.items():
        if str(key).strip().upper() == market:
            return _parse_optional_int_raw(
                value,
                path=path,
                source=f"config.yaml '{path}'",
            )
    return None
```

In `_parse_portfolio_section()`, replace the nested `_market_cap_value()` function with calls that pass constant `getenv()` lookups:

```python
    max_new_entries_kr = _parse_portfolio_market_cap(
        market_caps,
        market="KR",
        env_value=getenv("PORTFOLIO_MAX_NEW_ENTRIES_KR"),
        env_key="PORTFOLIO_MAX_NEW_ENTRIES_KR",
    )
    max_new_entries_us = _parse_portfolio_market_cap(
        market_caps,
        market="US",
        env_value=getenv("PORTFOLIO_MAX_NEW_ENTRIES_US"),
        env_key="PORTFOLIO_MAX_NEW_ENTRIES_US",
    )

    return _PortfolioSection(
        max_active_holdings=_parse_optional_int(
            parser,
            path="portfolio.max_active_holdings",
            env_key="PORTFOLIO_MAX_ACTIVE_HOLDINGS",
        ),
        max_new_entries_kr=max_new_entries_kr,
        max_new_entries_us=max_new_entries_us,
        exposure_limits=_parse_portfolio_exposure_limits(parser),
    )
```

- [x] **Step 7: Run config tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_config_validation_layers.py::test_load_config_parses_portfolio_caps \
  tests/test_config_validation_layers.py::test_load_config_parses_portfolio_market_caps_from_env_when_yaml_omits_caps \
  tests/test_config_validation_layers.py::test_load_config_rejects_invalid_portfolio_market_cap_env \
  tests/test_config_validation_layers.py::test_load_config_rejects_invalid_portfolio_config \
  tests/test_config_conflict_policy.py::test_load_config_rejects_portfolio_market_cap_env_yaml_conflict_case_insensitive \
  tests/test_config_conflict_binding_sync.py \
  tests/test_runtime_config_contract.py::test_repository_config_has_entry_portfolio_caps \
  -q
```

Expected: all selected tests pass.

- [x] **Step 8: Commit Task 1**

Run:

```bash
git add sab/config.py tests/test_config_validation_layers.py tests/test_config_conflict_policy.py
git commit -m "feat(config): 시장별 신규 진입 cap env 추가" -m "PORTFOLIO_MAX_NEW_ENTRIES_KR/US를 portfolio.max_new_entries_per_market.KR/US와 동일한 conflict policy로 연결하고 기존 포트폴리오 가드 의미를 유지합니다."
```

### Task 2: Documentation And Contract Tests

**Files:**
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Test: `tests/test_env_example_v11.py`
- Test: `tests/test_docs_state_contract.py`

**Interfaces:**
- Consumes: `PORTFOLIO_MAX_NEW_ENTRIES_KR` and `PORTFOLIO_MAX_NEW_ENTRIES_US` from Task 1.
- Produces: operator docs that explain how to tighten caps without creating env/YAML conflicts.

- [x] **Step 1: Add failing `.env.example` contract test**

In `tests/test_env_example_v11.py`, add:

```python
def test_env_example_documents_portfolio_market_caps_without_active_override() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example_path.read_text(encoding="utf-8")
    active_keys = set(_extract_env_keys(env_example_path))

    assert "PORTFOLIO_MAX_NEW_ENTRIES_KR" in text
    assert "PORTFOLIO_MAX_NEW_ENTRIES_US" in text
    assert "portfolio.max_new_entries_per_market.KR" in text
    assert "portfolio.max_new_entries_per_market.US" in text
    assert "PORTFOLIO_MAX_NEW_ENTRIES_KR" not in active_keys
    assert "PORTFOLIO_MAX_NEW_ENTRIES_US" not in active_keys
```

- [x] **Step 2: Add failing docs contract test**

In `tests/test_docs_state_contract.py`, add:

```python
def test_config_docs_document_portfolio_market_cap_env_overrides() -> None:
    configuration_text = _read(Path("docs/configuration.md"))
    config_reference_text = _read(Path("docs/config-reference.md"))

    for env_key, yaml_path in (
        (
            "PORTFOLIO_MAX_NEW_ENTRIES_KR",
            "portfolio.max_new_entries_per_market.KR",
        ),
        (
            "PORTFOLIO_MAX_NEW_ENTRIES_US",
            "portfolio.max_new_entries_per_market.US",
        ),
    ):
        assert env_key in configuration_text
        assert yaml_path in configuration_text
        assert env_key in config_reference_text
        assert yaml_path in config_reference_text

    assert "risk-off" in configuration_text
    assert "`portfolio.exposure_limits[]`" in config_reference_text
    assert "`portfolio.max_new_entries_per_market.KR`" not in (
        config_reference_text.split("## YAML-Only Config Notes", 1)[1]
    )
```

- [x] **Step 3: Run docs tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_env_example_v11.py::test_env_example_documents_portfolio_market_caps_without_active_override \
  tests/test_docs_state_contract.py::test_config_docs_document_portfolio_market_cap_env_overrides \
  -q
```

Expected: both tests fail because docs do not mention the new env keys yet.

- [x] **Step 4: Update `.env.example`**

In `.env.example`, directly after `# PORTFOLIO_MAX_ACTIVE_HOLDINGS=8`, add:

```dotenv
# Optional: 시장별 신규 ENTER 후보 cap. risk-off 임시 축소에 사용하세요.
# 기본 운영값은 config.yaml `portfolio.max_new_entries_per_market.KR/US`입니다.
# YAML config가 해당 market cap을 정의하면 같은 env override를 함께 두지 마세요.
# PORTFOLIO_MAX_NEW_ENTRIES_KR=1
# PORTFOLIO_MAX_NEW_ENTRIES_US=1
```

- [x] **Step 5: Update `docs/configuration.md`**

In the environment-variable table, add these rows after `ENTRY_FATAL_MISSING_PRICE_RATIO`:

```markdown
| `PORTFOLIO_MAX_NEW_ENTRIES_KR` | no | `config.yaml` `portfolio.max_new_entries_per_market.KR` | `1` | `sab entry` | KR new-entry cap | Env/YAML conflict binding. Use for temporary risk-off tightening only when the selected YAML config omits the KR cap. |
| `PORTFOLIO_MAX_NEW_ENTRIES_US` | no | `config.yaml` `portfolio.max_new_entries_per_market.US` | `1` | `sab entry` | US new-entry cap | Env/YAML conflict binding. Use for temporary risk-off tightening only when the selected YAML config omits the US cap. |
```

In the `## Config YAML` section, append this paragraph after the paragraph that starts `Use config.local.yaml plus SAB_CONFIG=config.local.yaml`:

```markdown
For risk-off entry throttling, prefer a local uncommitted YAML file when the repository `config.yaml` already owns `portfolio.max_new_entries_per_market.KR/US`: copy `config.yaml` to `config.local.yaml`, lower only the desired market cap values, and run with `SAB_CONFIG=config.local.yaml`. The env overrides `PORTFOLIO_MAX_NEW_ENTRIES_KR` and `PORTFOLIO_MAX_NEW_ENTRIES_US` are available for environments whose selected YAML config omits the matching market cap; defining both sides for the same market fails closed.
```

- [x] **Step 6: Update `docs/config-reference.md`**

In `## Runtime Secrets And App Env`, add this row after `ENTRY_FATAL_MISSING_PRICE_RATIO`:

```markdown
| `PORTFOLIO_MAX_NEW_ENTRIES_KR`, `PORTFOLIO_MAX_NEW_ENTRIES_US` | `sab entry` | `portfolio.max_new_entries_per_market.KR/US`; env override only when the selected YAML config omits the matching market cap |
```

In `## CLI Config Override Bindings`, add these rows after `PORTFOLIO_MAX_ACTIVE_HOLDINGS`:

```markdown
| `PORTFOLIO_MAX_NEW_ENTRIES_KR` | `portfolio.max_new_entries_per_market.KR` | KR 신규 entry cap |
| `PORTFOLIO_MAX_NEW_ENTRIES_US` | `portfolio.max_new_entries_per_market.US` | US 신규 entry cap |
```

In `## YAML-Only Config Notes`, remove these two bullets:

```markdown
- `portfolio.max_new_entries_per_market.KR`
- `portfolio.max_new_entries_per_market.US`
```

Leave this bullet in place:

```markdown
- `portfolio.exposure_limits[]` (`dimension`, `value`, `max_active`; dimensions: `currency`, `sector`, `theme`, `beta_bucket`, `correlation_bucket`, `tag`)
```

- [x] **Step 7: Run docs tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_env_example_v11.py::test_env_example_documents_portfolio_market_caps_without_active_override \
  tests/test_env_example_v11.py::test_env_example_active_keys_do_not_conflict_with_config \
  tests/test_docs_state_contract.py::test_config_docs_document_portfolio_market_cap_env_overrides \
  tests/test_docs_state_contract.py::test_strategy_docs_include_swing_logic_improvement_contracts \
  -q
```

Expected: all selected tests pass.

- [x] **Step 8: Commit Task 2**

Run:

```bash
git add .env.example docs/configuration.md docs/config-reference.md tests/test_env_example_v11.py tests/test_docs_state_contract.py
git commit -m "docs(config): 시장별 entry cap override 문서화" -m "risk-off 상황에서 시장별 신규 진입 cap을 줄이는 env와 local YAML 사용 경계를 문서화합니다."
```

### Task 3: Backlog Closeout And Final Validation

**Files:**
- Modify: `TODOS.md`

**Interfaces:**
- Consumes: passing Task 1 and Task 2 tests.
- Produces: the active backlog item moved to Completed with the implementation summary.

- [x] **Step 1: Move backlog item to Completed**

In `TODOS.md`, remove the active item:

```markdown
- 2026-06-18: Consider environment overrides for `portfolio.max_new_entries_per_market.KR/US`, or document a local-config workflow for temporarily tightening market entry caps during risk-off regimes. `PORTFOLIO_MAX_ACTIVE_HOLDINGS` is env-bound, but per-market new-entry caps are currently YAML-only.
```

Add this item at the top of `## Completed`:

```markdown
- 2026-06-23: Added env/YAML-conflict-bound `PORTFOLIO_MAX_NEW_ENTRIES_KR` and `PORTFOLIO_MAX_NEW_ENTRIES_US` overrides for `portfolio.max_new_entries_per_market.KR/US`, while documenting the safer `config.local.yaml` workflow when committed YAML already owns the caps. `portfolio.exposure_limits[]` remains YAML-only.
```

- [x] **Step 2: Run focused full validation**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_config_validation_layers.py \
  tests/test_config_conflict_policy.py \
  tests/test_config_conflict_binding_sync.py \
  tests/test_runtime_config_contract.py \
  tests/test_env_example_v11.py \
  tests/test_docs_state_contract.py \
  -q
```

Expected: all selected tests pass.

- [x] **Step 3: Run repository quality gate if time allows**

Run:

```bash
just quality
```

Expected: Python quality gate passes. If this is too broad for the current run, record the focused pytest command from Step 2 as the completed validation and state why `just quality` was not run.

- [x] **Step 4: Commit closeout**

Run:

```bash
git add TODOS.md
git commit -m "chore(todo): 시장별 entry cap override 완료 기록" -m "PORTFOLIO_MAX_NEW_ENTRIES_KR/US 구현과 문서화가 끝난 active 항목을 완료로 이동합니다."
```

## Self-Review

- Spec coverage: the active backlog item asked to consider env overrides or document a local-config workflow. This plan does both: it implements env overrides and documents when to prefer `config.local.yaml`.
- Placeholder scan: no unresolved placeholders are intentionally left in code snippets or commands.
- Type consistency: the env names are consistently `PORTFOLIO_MAX_NEW_ENTRIES_KR` and `PORTFOLIO_MAX_NEW_ENTRIES_US`; the config fields remain `max_new_entries_kr` and `max_new_entries_us`.
- Risk check: the design preserves `portfolio.exposure_limits[]` as YAML-only because list-shaped env parsing would add a larger contract and is not needed for the active item.
