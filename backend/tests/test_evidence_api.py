"""GET /evidence/pain-points: role gate, empty field data, simulated labelling."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import pain_points
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, bearer

URL = "/api/v1/evidence/pain-points"
HEADER = ("id,date,role,area_type,runs_out,freq_per_month,replenish_source,replenish_minutes,"
          "replenish_cost_bdt,peak_times,lost_sales_note,excess_liquidity_issue,would_swap,"
          "swap_conditions,top_pain_point_tag,notes\n")


def test_agent_is_refused_and_staff_allowed(client: TestClient, seeded: Path) -> None:
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    for email in (DIST_DHAKA, ADMIN):
        assert client.get(URL, headers=bearer(client, email)).status_code == 200


def test_repo_field_file_has_header_only_and_personas_are_simulated() -> None:
    out = pain_points.build(Path(__file__).resolve().parents[2] / "data" / "field")
    assert out.field_interviews_count == 0
    assert all(p.field_count == 0 for p in out.pain_points)
    assert len(out.personas) == 6 and {p.label for p in out.personas} == {"SIMULATED"}
    assert out.incidence is not None and len(out.incidence.rows) == 3


def test_empty_field_dir_gives_zero_not_an_error(tmp_path: Path) -> None:
    out = pain_points.build(tmp_path, incidence=tmp_path / "missing.json")
    assert out.field_interviews_count == 0 and out.personas == [] and out.incidence is None
    assert len(out.pain_points) == len(pain_points.TAXONOMY)


def test_field_rows_are_counted_and_ranked_first(tmp_path: Path) -> None:
    row = "1,2026-01-01,agent,rural,cash,4,runner,120,0,,,,yes,,excess_liquidity,\n"
    (tmp_path / "interviews.csv").write_text(HEADER + row + row.replace("1,", "2,", 1),
                                             encoding="utf-8")
    out = pain_points.build(tmp_path)
    assert out.field_interviews_count == 2
    assert out.pain_points[0].tag == "excess_liquidity" and out.pain_points[0].field_count == 2


@pytest.mark.parametrize("tag", list(pain_points.TAXONOMY))
def test_every_tag_maps_to_a_feature_route(tag: str) -> None:
    assert pain_points.TAXONOMY[tag][4].startswith("/")
