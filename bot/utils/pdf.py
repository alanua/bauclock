import base64
from io import BytesIO
from weasyprint import HTML
from bot.utils.qr import generate_qr_code

def generate_site_pdf(company_name: str, site_name: str, site_address: str, qr_link: str) -> BytesIO:
    """
    Generates a print-ready A4 PDF with the site QR code and branding.
    """
    # Generate QR code image
    qr_bio = generate_qr_code(qr_link)
    qr_base64 = base64.b64encode(qr_bio.getvalue()).decode('utf-8')

    html_content = f"""
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: 'Helvetica', 'Arial', sans-serif;
                color: #333;
                text-align: center;
                margin: 0;
                padding: 0;
            }}
            .header {{
                margin-bottom: 50px;
            }}
            .company-name {{
                font-size: 24px;
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 10px;
            }}
            .site-info {{
                font-size: 18px;
                color: #7f8c8d;
                margin-bottom: 40px;
            }}
            .qr-container {{
                margin: 50px 0;
            }}
            .qr-code {{
                width: 300px;
                height: 300px;
            }}
            .instruction {{
                font-size: 22px;
                font-weight: bold;
                color: #e67e22;
                margin-top: 30px;
            }}
            .branding {{
                position: absolute;
                bottom: 0;
                width: 100%;
                font-size: 14px;
                color: #bdc3c7;
                border-top: 1px solid #eee;
                padding-top: 10px;
            }}
            .logo {{
                font-size: 28px;
                font-weight: 900;
                color: #2c3e50;
                letter-spacing: -1px;
            }}
            .logo span {{
                color: #e67e22;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">SEK <span>Zeiterfassung</span></div>
        </div>
        
        <div class="company-name">{company_name}</div>
        <div class="site-info">
            <strong>{site_name}</strong><br>
            {site_address or ''}
        </div>

        <div class="qr-container">
            <img src="data:image/png;base64,{qr_base64}" class="qr-code" alt="QR Code">
        </div>

        <div class="instruction">
            Scan mit Telegram für Zeiterfassung
        </div>

        <div class="branding">
            SEK Zeiterfassung - Die moderne Lösung für Baustellen
        </div>
    </body>
    </html>
    """
    
    pdf_bio = BytesIO()
    HTML(string=html_content).write_pdf(pdf_bio)
    pdf_bio.seek(0)
    return pdf_bio
