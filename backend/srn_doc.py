import io
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _d(v):
    if not v:
        return ""
    try:
        return datetime.fromisoformat(str(v)[:10]).strftime("%d-%m-%Y")
    except ValueError:
        return str(v)


def srn_context(srn, project, approvals, history):
    """Flatten an SRN into the sections of the reference SRN document."""
    rows = []
    for i, it in enumerate(srn.get("items", []), 1):
        rows.append([str(i), f"{it['cr_number']} {it.get('title', '')}" + (" (partial)" if it.get("scope") == "partial" else ""),
                     it.get("module", ""), it.get("description", ""), it.get("impact", "Yes")])
    for b in srn.get("bug_items", []):
        rows.append([str(len(rows) + 1), f"{b['number']} {b.get('title', '')}", b.get("module", ""), b.get("fix_notes", ""), "Yes"])
    valid = [a for a in approvals if a.get("valid") and a["decision"] == "APPROVE"]
    by_stage = {}
    for a in valid:
        by_stage.setdefault(a["stage"], a)
    stages = list(by_stage.values())
    return {
        "company": srn.get("company_name") or "Company",
        "title": f"Release for {srn.get('application_name') or project['name']} {srn.get('release_version', '')}",
        "team": srn.get("team_name") or project.get("name"),
        "history": [[h.get("release_version", ""), _d(h.get("release_date")), h.get("author_name", "")] for h in history],
        "services": [[s.get("name", ""), _d(s.get("released_date") or srn.get("release_date")), s.get("impact", "Yes")] for s in srn.get("supporting_services", [])],
        "details": [
            [f"Product Name: {srn.get('application_name', '')}", f"Module Name: {', '.join(srn.get('impacted_modules', [])) or srn.get('application_name', '')}"],
            [f"SRN No: {srn['number']}", f"Author Name: {srn.get('author_name', '')}"],
            [f"Intended Prod Version: {srn.get('intended_prod_version', '')}", f"Version: {srn.get('release_version', '')}"],
            [f"SRN Type: {srn.get('release_type', '')}", f"Environment: {srn.get('environment', 'UAT')}"],
            [f"Release Date: {_d(srn.get('release_date'))}", f"Technology: {', '.join(srn.get('tech_stack', []))}"],
        ],
        "summary": srn.get("summary", ""),
        "description": srn.get("description", ""),
        "rows": rows,
        "deployment": srn.get("deployment_instructions", ""),
        "rollback": srn.get("rollback_instructions", ""),
        "build_ref": srn.get("build_ref", ""),
        "testing": srn.get("testing_evidence", ""),
        "signoff": [["Prepared By:", srn.get("author_name", ""), _d(srn.get("submitted_at") or srn.get("created_at"))]]
        + [[("Reviewed By:" if i < len(stages) - 1 else "Approved By:"), f"{a['approver_name']} ({a['role_label']})", _d(a["at"])] for i, a in enumerate(stages)],
        "revision": srn.get("revision", 1),
    }


def _table(doc, header, rows):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = h
        for r in c.paragraphs[0].runs:
            r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
    doc.add_paragraph()


def build_docx(ctx):
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10)
    for line, size in [(ctx["company"], 16), ("Software Release Note", 14), (ctx["title"], 12), (ctx["team"], 11)]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(line)
        r.bold, r.font.size = True, Pt(size)
        r.font.color.rgb = RGBColor(0x1E, 0x3A, 0x8A)
    doc.add_paragraph(f"Document revision: R{ctx['revision']}").alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_heading("Version History", level=2)
    _table(doc, ["Version", "Date", "Release By"], ctx["history"])
    doc.add_heading("Supporting Services", level=2)
    _table(doc, ["Supporting Service", "Released Date", "Impact"], ctx["services"] or [["-", "", ""]])
    doc.add_heading("SOFTWARE RELEASE NOTES", level=1)
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for a, b in ctx["details"]:
        cells = t.add_row().cells
        cells[0].text, cells[1].text = a, b
    doc.add_paragraph()
    doc.add_heading("Summary:", level=2)
    doc.add_paragraph(ctx["summary"] or "-")
    if ctx["description"]:
        doc.add_paragraph(ctx["description"])
    doc.add_heading("1.1 Contents of this Release", level=2)
    _table(doc, ["Sr.No.", "CR's/Bugs", "Module/Programs", "Description", "Impact"], ctx["rows"])
    for label, key in [("Testing Evidence", "testing"), ("Deployment Instructions", "deployment"), ("Rollback Instructions", "rollback"), ("Build / Commit Reference", "build_ref")]:
        if ctx[key]:
            doc.add_heading(label, level=3)
            doc.add_paragraph(ctx[key])
    _table(doc, ["", "Name, Signature, and Designation", "Date"], [])
    t = doc.tables[-1]
    for row in ctx["signoff"]:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = v
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_pdf(ctx):
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    ss = getSampleStyleSheet()
    body = ss["BodyText"]
    el = []
    for line, style in [(ctx["company"], "Title"), ("Software Release Note", "Heading2"), (ctx["title"], "Heading3"), (ctx["team"], "Normal")]:
        p = Paragraph(line, ss[style])
        p.style.alignment = 1
        el.append(p)
    el.append(Spacer(1, 10))

    def tbl(header, rows, widths=None):
        data = ([header] if header else []) + [[Paragraph(str(c).replace("\n", "<br/>"), body) for c in r] for r in rows]
        t = Table(data or [[""]], colWidths=widths, repeatRows=1 if header else 0)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
                              + ([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0"))] if header else [])))
        el.append(t)
        el.append(Spacer(1, 10))

    el.append(Paragraph("Version History", ss["Heading3"]))
    tbl(["Version", "Date", "Release By"], ctx["history"])
    el.append(Paragraph("Supporting Services", ss["Heading3"]))
    tbl(["Supporting Service", "Released Date", "Impact"], ctx["services"] or [["-", "", ""]])
    el.append(Paragraph("SOFTWARE RELEASE NOTES", ss["Heading2"]))
    tbl(None, ctx["details"])
    el.append(Paragraph("Summary:", ss["Heading3"]))
    el.append(Paragraph((ctx["summary"] or "-").replace("\n", "<br/>"), body))
    el.append(Paragraph("1.1 Contents of this Release", ss["Heading3"]))
    tbl(["Sr.No.", "CR's/Bugs", "Module/Programs", "Description", "Impact"], ctx["rows"], [40, 120, 100, 210, 50])
    for label, key in [("Testing Evidence", "testing"), ("Deployment Instructions", "deployment"), ("Rollback Instructions", "rollback"), ("Build / Commit Reference", "build_ref")]:
        if ctx[key]:
            el.append(Paragraph(label, ss["Heading4"]))
            el.append(Paragraph(ctx[key].replace("\n", "<br/>"), body))
    el.append(Spacer(1, 10))
    tbl(["", "Name, Signature, and Designation", "Date"], ctx["signoff"])
    pdf.build(el)
    return buf.getvalue()
