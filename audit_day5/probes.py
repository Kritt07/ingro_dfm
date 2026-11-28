import json, time, sys
from pathlib import Path
from zipfile import ZipFile
import pymupdf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from normdoc2json.spreadsheets import extract_spreadsheet
from normdoc2json.pdf import _extract_tables
base=Path(__file__).parent
results={}
# Date values have an office:date-value and need not have display paragraphs.
xml='''<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"><office:body><office:spreadsheet><table:table table:name="Dates"><table:table-row><table:table-cell office:value-type="date" office:date-value="2026-11-25"/><table:table-cell office:value-type="time" office:time-value="PT1H30M"/></table:table-row></table:table></office:spreadsheet></office:body></office:document-content>'''
path=base/'dates.ods'
with ZipFile(path,'w') as z:
 z.writestr('mimetype','application/vnd.oasis.opendocument.spreadsheet');z.writestr('content.xml',xml)
r=extract_spreadsheet(path)
results['ods_dates']={'values':r.sheets[0].values,'warnings':r.warnings,'expected':['2026-11-25','PT1H30M']}
# An invalid cell on one sheet must not discard other valid sheets.
xml=xml.replace('office:value-type="date" office:date-value="2026-11-25"','office:value-type="float" office:value="broken"').replace('</office:spreadsheet>','<table:table table:name="Good"><table:table-row><table:table-cell office:value-type="float" office:value="42"/></table:table-row></table:table></office:spreadsheet>')
path=base/'partial.ods'
with ZipFile(path,'w') as z:
 z.writestr('mimetype','application/vnd.oasis.opendocument.spreadsheet');z.writestr('content.xml',xml)
try: results['ods_sheet_isolation']=str(extract_spreadsheet(path))
except Exception as exc: results['ods_sheet_isolation']=str(exc)
# Two borderless tables side by side must remain independent.
with pymupdf.open() as doc:
 page=doc.new_page()
 for y in (60,90,120):
  for x,value in [(50,'10'),(150,'20'),(350,'30'),(450,'40')]:page.insert_text((x,y),value)
 doc.save(base/'side_by_side.pdf')
 tables=_extract_tables(page,1)
 results['pdf_side_by_side']={'count':len(tables),'values':[t.values for t in tables],'expected_count':2}
(base/'probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
