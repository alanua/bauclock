from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from db.models import CompanyPublicProfile, Site, Company
from api.config import settings

router = APIRouter()


def _serialize_public_profile(profile: CompanyPublicProfile) -> dict[str, str | None]:
    return {
        "company_name": profile.company_name,
        "subtitle": profile.subtitle,
        "about_text": profile.about_text,
        "address": profile.address,
        "email": profile.email,
    }


@router.get("/api/public/company-profile")
async def get_company_public_profile(db: AsyncSession = Depends(get_db)):
    stmt = select(CompanyPublicProfile).where(
        CompanyPublicProfile.slug == "sek",
        CompanyPublicProfile.is_active.is_(True),
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Company public profile not found")

    return _serialize_public_profile(profile)

@router.get("/s/{qr_token}", response_class=HTMLResponse)
async def get_site_public_page(qr_token: str, request: Request, db: AsyncSession = Depends(get_db)):
    # 1. Fetch site and company
    stmt = select(Site).where(Site.qr_token == qr_token, Site.is_active == True)
    result = await db.execute(stmt)
    site = result.scalar_one_or_none()
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
        
    company = await db.get(Company, site.company_id)
    
    # 2. Link for Telegram
    bot_username = settings.BOT_USERNAME
    tg_redirect_url = f"https://t.me/{bot_username}?start={qr_token}"
    
    # 3. Build HTML with premium responsive CSS
    html_content = f"""
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{site.name} | SEK Zeiterfassung</title>
        <style>
            :root {{
                --primary: #e67e22;
                --primary-hover: #d35400;
                --secondary: #2c3e50;
                --bg: #f4f7f6;
                --text: #333;
                --light-text: #7f8c8d;
            }}
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: var(--bg);
                color: var(--text);
                margin: 0;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                padding: 20px;
                box-sizing: border-box;
            }}
            .card {{
                background: white;
                padding: 40px;
                border-radius: 24px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.05);
                max-width: 400px;
                width: 100%;
                text-align: center;
                transition: transform 0.3s ease;
            }}
            .logo {{
                font-size: 32px;
                font-weight: 900;
                color: var(--secondary);
                margin-bottom: 30px;
                letter-spacing: -1.5px;
            }}
            .logo span {{
                color: var(--primary);
            }}
            h1 {{
                font-size: 24px;
                margin: 0 0 10px 0;
                color: var(--secondary);
            }}
            p {{
                margin: 5px 0;
                color: var(--light-text);
                line-height: 1.5;
            }}
            .info-box {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #eee;
                text-align: left;
            }}
            .info-item {{
                margin-bottom: 15px;
            }}
            .info-label {{
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 1px;
                font-weight: bold;
                color: var(--primary);
                display: block;
                margin-bottom: 4px;
            }}
            .info-value {{
                font-size: 16px;
                font-weight: 500;
            }}
            .btn-container {{
                margin-top: 35px;
            }}
            .btn {{
                display: inline-block;
                background-color: var(--primary);
                color: white;
                text-decoration: none;
                padding: 14px 28px;
                border-radius: 12px;
                font-weight: bold;
                font-size: 16px;
                transition: all 0.2s ease;
                box-shadow: 0 4px 12px rgba(230, 126, 34, 0.2);
            }}
            .btn:hover {{
                background-color: var(--primary-hover);
                transform: translateY(-2px);
                box-shadow: 0 6px 15px rgba(230, 126, 34, 0.3);
            }}
            .btn:active {{
                transform: translateY(0);
            }}
            @media (max-width: 480px) {{
                .card {{
                    padding: 30px 20px;
                }}
                .btn {{
                    width: 100%;
                    box-sizing: border-box;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="logo">SEK <span>Zeiterfassung</span></div>
            
            <h1>{site.name}</h1>
            <p>{site.address or ''}</p>

            <div class="info-box">
                <div class="info-item">
                    <span class="info-label">Unternehmen</span>
                    <span class="info-value">{company.name}</span>
                </div>
                {f'''<div class="info-item">
                    <span class="info-label">Telefon</span>
                    <span class="info-value">{company.phone}</span>
                </div>''' if company.phone else ''}
                {f'''<div class="info-item">
                    <span class="info-label">E-Mail</span>
                    <span class="info-value">{company.email}</span>
                </div>''' if company.email else ''}
            </div>

            <div class="btn-container">
                <a href="{tg_redirect_url}" class="btn">
                  📱 Zeiterfassung öffnen
                </a>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
