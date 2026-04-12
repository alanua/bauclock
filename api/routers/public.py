from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.models import Company, CompanyPublicProfile, Site

router = APIRouter()


def _serialize_public_profile(profile: CompanyPublicProfile) -> dict[str, str | None]:
    return {
        "company_name": profile.company_name,
        "subtitle": profile.subtitle,
        "about_text": profile.about_text,
        "address": profile.address,
        "email": profile.email,
    }


async def _get_public_company_profile(
    db: AsyncSession,
    *,
    slug: str = "sek",
) -> CompanyPublicProfile:
    stmt = select(CompanyPublicProfile).where(
        CompanyPublicProfile.slug == slug,
        CompanyPublicProfile.is_active.is_(True),
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Company public profile not found")
    return profile


@router.get("/api/public/company-profile")
async def get_company_public_profile(db: AsyncSession = Depends(get_db)):
    profile = await _get_public_company_profile(db, slug="sek")
    return _serialize_public_profile(profile)


def _fact(label: str, value: str | None) -> str:
    clean_value = (value or "").strip()
    if not clean_value:
        return ""
    return f"""<div>
  <span class="label">{escape(label)}</span>
  <div class="value">{escape(clean_value)}</div>
</div>"""


def _public_page(title: str, body: str) -> HTMLResponse:
    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --surface: #ffffff;
      --text: #1b1f24;
      --muted: #637083;
      --line: #dde3ea;
      --accent: #2f6f5e;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
      display: grid;
      place-items: center;
      padding: 32px 18px;
    }}
    main {{
      width: min(720px, 100%);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(24px, 5vw, 42px);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(28px, 6vw, 44px);
      line-height: 1.05;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.5;
    }}
    .about {{
      margin: 28px 0 0;
      font-size: 17px;
      line-height: 1.65;
    }}
    .facts {{
      display: grid;
      gap: 18px;
      margin-top: 32px;
      padding-top: 24px;
      border-top: 1px solid var(--line);
    }}
    .label {{
      display: block;
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 13px;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .value {{
      font-size: 17px;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.get("/company", response_class=HTMLResponse)
async def get_default_company_public_page(db: AsyncSession = Depends(get_db)):
    return await get_company_public_page("sek", db)


@router.get("/c/{slug}", response_class=HTMLResponse)
async def get_company_public_page(slug: str, db: AsyncSession = Depends(get_db)):
    profile = await _get_public_company_profile(db, slug=slug)
    facts = "\n".join(
        item
        for item in [
            _fact("Adresse", profile.address),
            _fact("E-Mail", profile.email),
        ]
        if item
    )
    return _public_page(
        profile.company_name,
        f"""
<p class="eyebrow">Unternehmen</p>
<h1>{escape(profile.company_name)}</h1>
<p class="subtitle">{escape(profile.subtitle)}</p>
<p class="about">{escape(profile.about_text)}</p>
<div class="facts">{facts}</div>
""",
    )


@router.get("/s/{qr_token}", response_class=HTMLResponse)
async def get_site_public_page(qr_token: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Site).where(Site.qr_token == qr_token, Site.is_active.is_(True))
    site = (await db.execute(stmt)).scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    company = await db.get(Company, site.company_id)
    company_name = company.name if company else "Generalbau S.E.K. GmbH"
    facts = "\n".join(
        item
        for item in [
            _fact("Unternehmen", company_name),
            _fact("Adresse", site.address),
            _fact("Hinweis", site.description),
        ]
        if item
    )
    return _public_page(
        site.name,
        f"""
<p class="eyebrow">Objekt</p>
<h1>{escape(site.name)}</h1>
<div class="facts">{facts}</div>
""",
    )
