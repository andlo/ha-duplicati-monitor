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
    assert "| Server | Job | When | Result | Files | Warnings | Errors |" in rendered
    assert "|---|---|---|---|---|---|---|" in rendered
    assert "Fatal" in rendered
    assert "Success" in rendered

    # The critical regression check: header, separator, and data rows
    # must be CONTIGUOUS (no blank line between them), or the markdown
    # renderer will only render the header as a table and dump the
    # data rows as raw text - exactly the bug reported twice already.
    lines = [l for l in rendered.splitlines() if l.strip()]
    header_idx = next(i for i, l in enumerate(lines) if l.startswith("| Server"))
    assert lines[header_idx + 1].startswith("|---"), (
        "Separator row must immediately follow the header row"
    )
    assert lines[header_idx + 2].startswith("|"), (
        "First data row must immediately follow the separator row "
        "(no blank line) - got: " + repr(lines[header_idx + 2])
    )

    # Regression check #2 (andlo, 2026-07-12): Home Assistant's own
    # dashboard editor re-serialises pasted YAML and rewrites
    # `content: |` (literal) to `content: >` (folded) - collapsing
    # every line break into a single space before Jinja ever runs.
    # The template must render IDENTICALLY either way, since we can't
    # control what the editor does to it.
    folded = " ".join(
        line.strip() for line in content_template.splitlines() if line.strip()
    )
    folded_rendered = template_helper.Template(folded, hass).async_render()
    assert folded_rendered == rendered, (
        "Template output differs after simulating Home Assistant's "
        "content: | -> content: > re-serialisation (line breaks folded "
        "into spaces) - the template must not depend on source-level "
        "line breaks surviving."
    )


async def test_dashboard_template_survives_history_entries_missing_new_fields(
    hass, hass_client_no_auth
):
    """Real bug (andlo, 2026-07-12): history entries recorded before
    v0.3.3 don't have server_name/job_name/server_id/job_id - accessing
    a missing dict key via Jinja dot-notation (run.server_name) raises
    inside a for-loop, not just renders empty, breaking the whole
    template for anyone with pre-existing history. Must use
    run.get(...) throughout instead."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Duplicati", data={CONF_WEBHOOK_ID: "old-data-test"}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Post once so a job/device/history sensor exist...
    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/webhook/old-data-test",
        json={"server_id": "nas01", "job_id": "documents", "parsed_result": "Success"},
    )
    assert resp.status == 200
    await hass.async_block_till_done()

    # ...then inject a pre-0.3.3-style history entry (no server_name/
    # job_name/server_id/job_id keys at all) directly, like real
    # persisted data from before that field was added.
    store = hass.data[DOMAIN][entry.entry_id]
    old_style_entry = {
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "parsed_result": "Success",
        "end_time": "2026-01-01T00:00:00+00:00",
        "examined_files": 1,
        "warnings_count": 0,
        "errors_count": 0,
    }
    store["history"][("nas01", "documents")].insert(0, old_style_entry)

    with open("docs/dashboard.yaml") as f:
        dashboard = yaml.safe_load(f)
    markdown_card = next(
        c for c in dashboard["views"][0]["cards"] if c.get("type") == "markdown"
    )

    from homeassistant.helpers import template as template_helper

    # Must not raise.
    rendered = template_helper.Template(
        markdown_card["content"], hass
    ).async_render()
    assert "?" in rendered  # the old entry's missing server/job show as "?"
