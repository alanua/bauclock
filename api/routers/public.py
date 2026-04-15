from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.models import Company, CompanyPublicProfile, Site

router = APIRouter()
PUBLIC_UI_INDEX = Path("api/static/public-ui/index.html")


def _serialize_public_profile(profile: CompanyPublicProfile) -> dict[str, str | None]:
    return {
        "company_name": profile.company_name,
        "subtitle": profile.subtitle,
        "about_text": profile.about_text,
        "address": profile.address,
        "email": profile.email,
    }


async def _serialize_public_site_profile(db: AsyncSession, site: Site) -> dict[str, str | None]:
    company = await db.get(Company, site.company_id)
    return {
        "company_name": company.name if company else "Generalbau S.E.K. GmbH",
        "site_name": site.name,
        "address": site.address,
        "note": site.description,
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


@router.get("/api/public/company-profile/{slug}")
async def get_company_public_profile_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    profile = await _get_public_company_profile(db, slug=slug)
    return _serialize_public_profile(profile)


async def _get_public_site(db: AsyncSession, qr_token: str) -> Site:
    stmt = select(Site).where(Site.qr_token == qr_token, Site.is_active.is_(True))
    site = (await db.execute(stmt)).scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get("/api/public/sites/{qr_token}")
async def get_site_public_profile(qr_token: str, db: AsyncSession = Depends(get_db)):
    site = await _get_public_site(db, qr_token)
    return await _serialize_public_site_profile(db, site)


def _public_ui_shell() -> FileResponse | None:
    if not PUBLIC_UI_INDEX.exists():
        return None
    return FileResponse(PUBLIC_UI_INDEX, media_type="text/html")


def _fact(label: str, value: str | None) -> str:
    clean_value = (value or "").strip()
    if not clean_value:
        return ""
    return f"""<div class="fact">
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
      --bg: #f3efe7;
      --surface: #fffdf8;
      --surface-soft: #faf6ee;
      --text: #20342d;
      --muted: #65736c;
      --line: rgba(58, 76, 67, 0.12);
      --accent: #a9ddca;
      --accent-strong: #3d7f69;
      --shadow: 0 22px 52px rgba(49, 67, 58, 0.10), 0 7px 20px rgba(49, 67, 58, 0.07);
      --shadow-soft: 0 14px 34px rgba(49, 67, 58, 0.075), 0 3px 10px rgba(49, 67, 58, 0.045);
    }}
    * {{
      box-sizing: border-box;
    }}
    html {{
      min-width: 320px;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 12% 0%, rgba(169, 221, 202, 0.26), transparent 34%),
        linear-gradient(180deg, #fffaf2 0%, var(--bg) 100%);
      display: grid;
      place-items: center;
      padding: clamp(22px, 5vw, 58px) 18px;
    }}
    main {{
      width: min(780px, 100%);
      background: var(--surface);
      border: 1px solid rgba(255, 255, 255, 0.72);
      border-radius: 30px;
      box-shadow: var(--shadow);
      padding: clamp(26px, 6vw, 54px);
      position: relative;
      overflow: hidden;
    }}
    main::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(135deg, rgba(169, 221, 202, 0.18), transparent 36%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.66), transparent 28%);
    }}
    .content {{
      position: relative;
      display: grid;
      gap: clamp(22px, 4vw, 34px);
    }}
    .eyebrow {{
      width: fit-content;
      margin: 0;
      color: var(--accent-strong);
      background: rgba(169, 221, 202, 0.45);
      border: 1px solid rgba(107, 153, 136, 0.18);
      border-radius: 999px;
      box-shadow: var(--shadow-soft);
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(32px, 8vw, 56px);
      line-height: 1.02;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 16px 0 0;
      color: var(--muted);
      font-size: clamp(17px, 3vw, 21px);
      line-height: 1.5;
      max-width: 48ch;
    }}
    .about {{
      margin: 0;
      font-size: clamp(16px, 2.6vw, 18px);
      line-height: 1.65;
      max-width: 60ch;
    }}
    .facts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 14px;
    }}
    .fact {{
      min-width: 0;
      background: rgba(250, 246, 238, 0.82);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow-soft);
      padding: 16px;
    }}
    .label {{
      display: block;
      margin-bottom: 7px;
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      font-weight: 700;
    }}
    .value {{
      font-size: 16px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }}
    @media (max-width: 520px) {{
      body {{
        align-items: start;
        padding: 14px;
      }}
      main {{
        border-radius: 24px;
        padding: 24px;
      }}
      .facts {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="content">
      {body}
    </div>
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
    shell = _public_ui_shell()
    if shell:
        return shell

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
    site = await _get_public_site(db, qr_token)
    shell = _public_ui_shell()
    if shell:
        return shell

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
