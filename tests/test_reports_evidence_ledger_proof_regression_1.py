from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROOF_PATH = REPO_ROOT / "docs/design/reports-evidence-ledger-proof.html"


class _ProofParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[dict[str, str | None]] = []
        self.divs_by_id: dict[str, dict[str, str | None]] = {}
        self.scripts: list[str] = []
        self._capturing_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "button":
            self.buttons.append(attributes)
        if tag == "div" and "id" in attributes:
            element_id = attributes["id"]
            if element_id is not None:
                self.divs_by_id[element_id] = attributes
        if tag == "script":
            self._capturing_script = True

    def handle_data(self, data: str) -> None:
        if self._capturing_script:
            self.scripts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._capturing_script = False


def _parse_proof() -> _ProofParser:
    parser = _ProofParser()
    parser.feed(PROOF_PATH.read_text(encoding="utf-8"))
    return parser


def test_secondary_evidence_disclosure_uses_accessible_button() -> None:
    # Regression: ISSUE-001 — secondary evidence disclosure was not exposed as a button.
    # Found by /qa on 2026-07-08
    # Report: .gstack/qa-reports/qa-report-file-2026-07-08.md
    parser = _parse_proof()

    toggle_buttons = [
        attrs for attrs in parser.buttons if "data-disclosure-toggle" in attrs
    ]

    assert len(toggle_buttons) == 1
    toggle = toggle_buttons[0]
    assert toggle["type"] == "button"
    assert toggle["aria-expanded"] == "true"

    controlled_panel_id = toggle["aria-controls"]
    assert controlled_panel_id in parser.divs_by_id

    scripts = "\n".join(parser.scripts)
    assert 'button.setAttribute("aria-expanded", String(!expanded))' in scripts
    assert "target.hidden = expanded" in scripts
