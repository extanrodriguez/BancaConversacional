from html.parser import HTMLParser
from pathlib import Path
import re,json,html
class Rows(HTMLParser):
 def __init__(self): super().__init__();self.rows=[];self.cells=[];self.cell=None;self.images=[]
 def handle_starttag(self,tag,attrs):
  if tag=='tr': self.cells=[];self.images=[]
  if tag=='td': self.cell=[]
  if tag=='img':
   a=dict(attrs)
   if 'src' in a:self.images.append(a['src'])
 def handle_data(self,data):
  if self.cell is not None:self.cell.append(data)
 def handle_endtag(self,tag):
  if tag=='td' and self.cell is not None:self.cells.append(' '.join(' '.join(self.cell).split()));self.cell=None
  if tag=='tr' and self.cells:self.rows.append((self.cells,self.images))
ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'fuentes/Guia_236.MD').read_text(encoding='utf-8'); p=Rows();p.feed(s);cases=[]
for td,images in p.rows:
 if len(td)>=5 and re.fullmatch(r'[A-Z]+\d+',td[0]):
  q=td[1]
  cases.append(dict(case_id=td[0],question=q,turns=[x.strip() for x in q.split('→')],expected=td[2],historical_result=td[3],recommendation=td[4],images=images,source_format='table'))
for m in re.finditer(r'^## ([A-Z]+\d+)\s*\n(.*?)(?=^##? |\Z)',s,re.M|re.S):
 id,b=m.groups(); turns=re.findall(r'^\d+\. (.+)',b,re.M)
 exp=re.search(r'Validación esperada:\s*(.+)',b);res=re.search(r'\| Resultado \| (.+?) \|',b);rec=re.search(r'\| Recomendación \| (.+?) \|',b)
 cases.append(dict(case_id=id,question=' → '.join(turns),turns=turns,expected=exp.group(1) if exp else '',historical_result=res.group(1) if res else '',recommendation=rec.group(1) if rec else '',images=re.findall(r'\]\((images/[^)]+)\)',b),source_format='heading'))
cases.sort(key=lambda x:s.index(x['case_id']))
assert len(cases)==236,len(cases)
assert len({c['case_id'] for c in cases})==236
(ROOT/'evaluacion/casos_236.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2))
print('Casos extraídos:',len(cases))
print('MULTITURN',sum(len(c['turns'])>1 for c in cases))
