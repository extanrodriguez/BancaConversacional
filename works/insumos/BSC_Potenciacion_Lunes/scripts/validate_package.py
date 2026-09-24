"""Verifica integridad documental; no ejecuta el LLM, Redis ni pruebas bancarias."""
from pathlib import Path
from collections import Counter
import json,hashlib,re,sys
R=Path(__file__).resolve().parents[1]
def read(p):return json.loads((R/p).read_text(encoding='utf-8'))
def lines(p):return [json.loads(s) for s in (R/p).read_text(encoding='utf-8').splitlines() if s.strip()]
checks=[]
def check(name,condition):
    checks.append({'check':name,'passed':bool(condition)})
rows=read('fuentes/filas_344.json');cases=read('evaluacion/casos_236.json');mapping=read('evaluacion/cruce_236_kb.json')
cards=lines('kb/fichas_candidatas.jsonl');qa=lines('kb/fichas_qa.jsonl');chunks=lines('kb/chunks_qa.jsonl');rules=read('estrategia/reglas_funcionales_98.json')
ids={c['id'] for c in cards};qids={c['id'] for c in qa};rids={r['id'] for r in rules}
check('344 filas únicas de origen',len(rows)==344 and len({x['source_row'] for x in rows})==344)
check('236 casos únicos',len(cases)==236 and len({x['case_id'] for x in cases})==236)
check('236 asociaciones uno a uno',len(mapping)==236 and {x['case_id'] for x in mapping}=={x['case_id'] for x in cases})
check('36 escenarios multi-turno separados',sum(len(c['turns'])>1 for c in cases)==36)
check('MIX01-MIX10 son conversaciones',all(len(c['turns'])==2 for c in cases if c['case_id'].startswith('MIX')))
check('98 reglas fuera del RAG',len(rules)==98 and all(not r['retrieval_eligible'] for r in rules))
check('IDs de fichas únicos',len(ids)==len(cards))
check('QA es subconjunto elegible',qids<=ids and all(c['qa_eligible'] for c in qa))
check('44 fichas detalladas pendientes separadas',len(cards)-len(qa)==44)
check('Sin aprobación PROD inventada',all(not c['approved_for_prod'] for c in cards))
check('Fuentes bancarias solo filas generales',all(all(79<=n<=324 for n in c['source_rows']) for c in cards))
check('Todos los enlaces de conocimiento resuelven',all(set(m['knowledge_ids'])<=ids for m in mapping))
check('Todos los enlaces de reglas resuelven',all(set(m['behavior_rule_ids'])<=rids for m in mapping))
check('Ningún caso declara ejecución no realizada',all(c['current_execution_status']=='NOT_EXECUTED' for c in cases+mapping))
check('Fragmentos con padres elegibles y numeración',all(c['parent_id'] in qids and c['ordinal']>=1 for c in chunks))
check('Ninguna respuesta de ejemplo personal en conocimiento',not any(any(v in c['content'] for v in ['24,980.15','24980.15','4587']) for c in cards))
check('Texto completo Joven recuperado',any(c['id']=='vf01-r262' and 'historial crediticio' in c['content'] for c in qa))
check('Reclamaciones con orientación real',any(c['id']=='bsc-reclamaciones-orientacion' and 'documentación' in c['content'] for c in qa))
check('Misión y visión canónicas',{'vf01-r080','vf01-r082'}<=qids)
check('Fichas débito corregidas',all(c['object']=='tarjeta_debito' for c in cards if c['id'] in ['vf01-r278','vf01-r279','vf01-r280','vf01-r281','vf01-r282']))
check('Hashes de contenido válidos',all(c['content_hash']==hashlib.sha256(c['content'].encode()).hexdigest() for c in cards))
web=read('fuentes/ampliaciones_web.json')
check('Nueve ampliaciones publicables en QA',sum(bool(w['include_as_knowledge']) for w in web)==9)
check('Fuentes web con enlace oficial y fecha',all(w['url'].startswith(('https://bsc.com.do/','https://prousuario.gob.do/','https://sb.gob.do/','https://learn.microsoft.com/')) and w['retrieved_on']=='2026-09-19' for w in web))
schema=read('estrategia/turn_plan.schema.json')
objects=[]
def walk(x):
    if isinstance(x,dict):
        if x.get('type')=='object':objects.append(x)
        for v in x.values():walk(v)
    elif isinstance(x,list):
        for v in x:walk(v)
walk(schema)
check('Schema de referencia strict completo',all(o['additionalProperties'] is False and set(o['required'])==set(o['properties']) for o in objects))
check('31 recorridos de aceptación prioritaria',len(read('evaluacion/aceptacion_p0.json'))==31)
raw=(R/'fuentes/Base_de_Conocimiento_IA_VF01.MD').read_bytes()
check('SHA de la base original',hashlib.sha256(raw).hexdigest()=='5c5622c592361246e4019ffca711a35f7b9a844aa29d824e189d76c4ddf1cf23')
# El manifiesto se comprueba separadamente para que el reporte no se autorreferencie.
manifest_result=None
if (R/'MANIFEST_SHA256.json').exists():
    failures=[]
    for f,h in read('MANIFEST_SHA256.json')['files'].items():
        p=R/f
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:failures.append(f)
    manifest_result={'passed':not failures,'mismatches':failures}
report={'kind':'DOCUMENT_VALIDATION_ONLY','application_tests_executed':0,'passed':all(c['passed'] for c in checks),'checks':checks}
(R/'revision/VALIDACION_PAQUETE.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'document_checks_passed':sum(c['passed'] for c in checks),'document_checks_total':len(checks),'application_tests_executed':0,'manifest':manifest_result,'failures':[c['check'] for c in checks if not c['passed']]},ensure_ascii=False,indent=2))
sys.exit(0 if report['passed'] and (manifest_result is None or manifest_result['passed']) else 1)
