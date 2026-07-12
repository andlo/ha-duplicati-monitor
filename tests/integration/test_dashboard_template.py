"""Verify docs/dashboard.yaml's markdown template actually renders
correctly against a real Home Assistant template engine - this exact
template broke twice already from untested YAML/Jinja assumptions."""
import yaml
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duplicati_monitor.const import DOMAIN, CONF_WEBHOOK_ID


async def test_dashboard_per_job_markdown_template_renders_correctly(
    hass, hass_client_no_auth
):
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati Monitor",  # deliberately not "Duplicati"
        data={CONF_WEBHOOK_ID: "duplicati-dash-test"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    for result in ("Success", "Fatal"):
        resp = await client.post(
            "/api/webhook/duplicati-dash-test",
            json={
                "server_id": "nas01",
                "job_id": "documents",
                "parsed_result": result,
                "examined_files": 42,
            },
        )
        assert resp.status == 200
    await hass.async_block_till_done()

    with open("docs/dashboard.yaml") as f:
        dashboard = yaml.safe_load(f)

    markdown_card = next(
        c for c in dashboard["views"][0]["cards"] if c.get("type") == "markdown"
    )
    content_template = markdown_card["content"]

    from homeassistant.helpers import template as template_helper

    tpl = template_helper.Template(content_template, hass)
    rendered = tpl.async_render()

    assert "documents" in rendered.lower() or "Duplicati Monitor" in rendered
    assert "| When | Result | Files | Warnings | Errors |" in rendered
    assert "|---|---|---|---|---|" in rendered
    assert "Fatal" in rendered
    assert "Success" in rendered

    # The critical regression check: header, separator, and data rows
    # must be CONTIGUOUS (no blank line between them), or the markdown
    # renderer will only render the header as a table and dump the
    # data rows as raw text - exactly the bug reported twice already.
    lines = [l for l in rendered.splitlines() if l.strip()]
    header_idx = next(i for i, l in enumerate(lines) if l.startswith("| When"))
    assert lines[header_idx + 1].startswith("|---"), (
        "Separator row must immediately follow the header row"
    )
    assert lines[header_idx + 2].startswith("|"), (
        "First data row must immediately follow the separator row "
        "(no blank line) - got: " + repr(lines[header_idx + 2])
    )
