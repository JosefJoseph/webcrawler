import json
import os
from datetime import datetime
import pandas as pd
from fpdf import FPDF

def generate_filename(base_name, domain, format_ext):
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    safe_domain = domain.replace('https://', '').replace('http://', '').replace('/', '_').replace('.', '_')
    return f"exports/{base_name}_{safe_domain}_{timestamp}.{format_ext}"

def export_to_json(results_df, domain):
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'json')
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(results_df.to_dict(orient='records'), f, ensure_ascii=False, indent=4)
    return filename

def export_to_csv(results_df, domain):
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'csv')
    results_df.to_csv(filename, index=False, encoding='utf-8')
    return filename

def export_to_pdf(results_df, domain):
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'pdf')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Crawl Results for {domain}", ln=True)
    pdf.ln(10)
    for _, row in results_df.iterrows():
        pdf.cell(200, 10, txt=str(row.to_dict()), ln=True)
    pdf.output(filename)
    return filename

def export_to_markdown(results_df, domain):
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'md')
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"# Crawl Results for {domain}\n\n")
        f.write(results_df.to_markdown(index=False))
    return filename