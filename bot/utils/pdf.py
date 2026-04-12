"""
PDF generation for bot - creates a simple PNG poster instead of PDF
to avoid WeasyPrint system dependencies in bot container.
"""
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import qrcode

def generate_site_pdf(qr_url: str, company_name: str, site_name: str, site_address: str = "") -> bytes:
    """
    Generates a printable PNG poster with QR code and site info.
    Returns PNG bytes (not PDF, but printable A4-like image).
    """
    # A4 at 150 DPI
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Generate QR code
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_size = 600
    qr_img = qr_img.resize((qr_size, qr_size))
    qr_x = (width - qr_size) // 2
    img.paste(qr_img, (qr_x, 200))

    # Text
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except Exception:
        font_large = ImageFont.load_default()
        font_med = font_large
        font_small = font_large

    # Title
    draw.text((width//2, 100), "SEK BauClock", font=font_large, fill="#1A56DB", anchor="mm")

    # Site name
    draw.text((width//2, 870), site_name, font=font_large, fill="#0D0D0D", anchor="mm")

    # Address
    if site_address:
        draw.text((width//2, 960), site_address, font=font_med, fill="#555555", anchor="mm")

    # Company
    draw.text((width//2, 1060), company_name, font=font_med, fill="#333333", anchor="mm")

    # Instruction
    draw.text((width//2, 1200), "Objektinformation", font=font_small, fill="#888888", anchor="mm")

    # Border
    draw.rectangle([(40, 40), (width-40, height-40)], outline="#1A56DB", width=4)

    buf = BytesIO()
    img.save(buf, format="PNG", dpi=(150, 150))
    buf.seek(0)
    return buf.read()
