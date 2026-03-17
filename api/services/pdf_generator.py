import io
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import os

def generate_pdf(company_id: int, start_date, end_date, report_data: list) -> bytes:
    # Get the directory of the current file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(current_dir, "..", "templates")
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")
    
    html_out = template.render(
        company_id=company_id,
        start_date=start_date.strftime('%d.%m.%Y'),
        end_date=end_date.strftime('%d.%m.%Y'),
        workers=report_data
    )
    
    pdf_file = HTML(string=html_out).write_pdf()
    return pdf_file
