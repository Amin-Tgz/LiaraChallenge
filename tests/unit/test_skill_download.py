from __future__ import annotations

import httpx

from src.main import create_app


async def test_skill_download_returns_markdown_attachment_instead_of_the_spa() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/skill/SKILL.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert "name: liara-docs-rescue" in response.text
    assert "<!doctype html>" not in response.text.lower()
