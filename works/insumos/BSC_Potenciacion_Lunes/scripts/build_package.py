"""Construcción local reproducible. Solo Python estándar; no llama Azure ni Core.
Ejecutar desde cualquier carpeta: python scripts/build_package.py
La selección editorial es explícita; no es un clasificador para producción.
"""
from pathlib import Path
from collections import Counter, defaultdict
import json, re, hashlib, unicodedata

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'bsc-kb-2026-09-19-candidate-1'
def read(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
def write(p, data):
    target=ROOT/p; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def lines(p, data):
    (ROOT/p).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data),encoding='utf-8')
def norm(s): return ' '.join(re.sub(r'[^a-z0-9 ]',' ',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()).split())
def uniq(a): return list(dict.fromkeys(a))
rows=read('fuentes/filas_344.json'); byrow={x['source_row']:x for x in rows}
cases=read('evaluacion/casos_236.json')

# Encabezados sin cuerpo: se conservan como relaciones, nunca como respuesta.
HEADERS={79:[],115:[114,116,117],176:[89,177,180],185:[102,186],187:[91,188,189,190],191:[192],193:[194],195:list(range(196,218)),218:list(range(219,227)),227:list(range(229,248)),228:list(range(229,233)),233:list(range(234,248)),248:[249],256:list(range(257,277)),277:list(range(278,290)),290:list(range(291,302)),302:list(range(303,307)),313:list(range(314,319))}
TITLE={177:'Multicrédito BSC: modalidad',178:'Multicrédito BSC: modalidad',179:'Crédito Diferido: segmentación',180:'Cuotas BSC: línea adicional y cuotas',181:'Crédito Diferido: formas de utilización',182:'Crédito Diferido: cuotas',183:'Crédito Diferido: límite y plazo',184:'Crédito Diferido: funcionamiento',186:'Multicrédito: intereses y características',188:'Cuotas BSC: tasa y límite',189:'Cuotas BSC: modalidades de pago',190:'Cuotas BSC: usos',192:'Crédito Diferido: requisitos',194:'Crédito Diferido: solicitud y apertura',196:'Crédito Diferido: consumos permitidos',197:'Crédito Diferido: seguridad de uso',198:'Multicrédito: activación y bloqueo',199:'Cuotas BSC: solicitud por canales',200:'Multicrédito: territorio y moneda',201:'Multicrédito: avances por centros de negocios',202:'Crédito Diferido: amortización por consumo',203:'Crédito Diferido: canales y funcionamiento',204:'Crédito Diferido: estado de cuenta',205:'Multicrédito: límite de avances',206:'Multicrédito: límite para compras',207:'Multicrédito: consumo mínimo',208:'Multicrédito: aumento de límite',209:'Multicrédito: disminución de límite',210:'Multicrédito: emisión, renovación y seguro',211:'Crédito Diferido: referencia al tarifario',212:'Crédito Diferido: corte y pago',213:'Crédito Diferido: cambio de fechas',214:'Crédito Diferido: pérdida o robo',215:'Crédito Diferido: domiciliación de cuotas',216:'Crédito Diferido: pagos recurrentes',217:'Multicrédito: pago mínimo mensual',219:'Crédito Diferido: mora',220:'Crédito Diferido: avance de efectivo',221:'Crédito Diferido: emisión',222:'Crédito Diferido: renovación',223:'Crédito Diferido: reemplazo',224:'Crédito Diferido: moneda',225:'Crédito Diferido: penalidades',226:'Crédito Diferido: cálculo de intereses',249:'Crédito Diferido: seguro voluntario',250:'Crédito Diferido: canales de cancelación',251:'Crédito Diferido: canales de cancelación',252:'Crédito Diferido: condiciones de cancelación',253:'Crédito Diferido: recepción y bloqueo',254:'Crédito Diferido: plazo de cancelación',255:'Crédito Diferido: carta de saldo',278:'Tarjeta de Débito Visa Clásica',279:'Tarjeta de Débito Visa Gold',280:'Tarjeta de Débito Visa Platinum',281:'Tarjeta de Débito Visa Infinite',282:'Tarjeta de Débito Visa Joven',283:'Tarjeta de Débito Visa Junior',284:'Tarjeta de Débito Mi Negocio',285:'Tarjeta de débito: requisitos, solicitud y activación',286:'Tarjeta de débito: condiciones de uso',287:'Tarjeta de débito: cargos',288:'Tarjeta de débito: conversión de moneda',289:'Tarjeta de débito: cancelación',303:'Préstamos: requisitos generales',304:'Préstamos: documentos por garantía',305:'Préstamos: solicitud',306:'Préstamos: condiciones de uso',307:'Préstamos: condiciones financieras',308:'Préstamos: cuotas, pagos y tasa',309:'Préstamos: cargos y cancelación anticipada',310:'Préstamos: cargos y cancelación anticipada',311:'Préstamos: garantías y refinanciación',312:'Préstamos: canales de cancelación',314:'Cuenta de ahorro personal',315:'Cuenta corriente personal',316:'Cuentas de efectivo: características',317:'Cuentas de efectivo: apertura',318:'Cuentas de efectivo: cargos',319:'Cancelación de productos: procedimiento general',320:'Reclamaciones: apertura, documentación y seguimiento',321:'Derechos y obligaciones del usuario',322:'Derechos y obligaciones del usuario',323:'Liberación de garantías: procedimiento',324:'Fallecimiento de titular: orientación a familiares'}
for i in range(229,248): TITLE.setdefault(i,f'Crédito Diferido: responsabilidades y derechos, cláusula {i-228}')

# Estas filas requieren revisión del contenido detallado antes de responderlo como condición vigente.
# Conservamos íntegro el candidato y damos resúmenes acotados para los recorridos prioritarios.
REVIEW={124:'Plazo de gracia específico: confirmar alcance y vigencia.',163:'Cambio regulatorio publicado 17-09-2026; no reconciliado con el texto de VF01.',165:'Cambio regulatorio publicado 17-09-2026; confirmar efectos.',186:'Condiciones financieras cuantificadas sin vigencia explícita.',188:'Tasa/condiciones variables sin vigencia explícita.',192:'Requisitos y umbrales de elegibilidad sin fecha de aprobación.',205:'Límite cuantificado sin versión de condiciones.',206:'Límite cuantificado sin versión de condiciones.',207:'Consumo mínimo sin versión de condiciones.',212:'Fechas y penalidades específicas requieren confirmar alcance.',226:'Fórmula incompleta: referencia a sumar una tasa sin operandos completos.',254:'Plazo contractual específico sin aprobación documentada.',269:'Requisitos de edad/ingresos; texto ambiguo sobre porcentaje de renta.',272:'Recompensas y límites numéricos variables; revisar reglamento vigente.',274:'Inconsistencia potencial: mora/sobregiro como fijo y como porcentaje entre filas.',275:'Metodología financiera; no habilita cálculo personal.',284:'La definición está truncada; verificar integridad del cuerpo de origen.',285:'Tiempos de entrega y requisitos requieren vigencia.',289:'Plazos de cancelación no validados externamente.',303:'Requisitos y elegibilidad específicos sujetos a validación de Producto.',307:'Porcentajes de financiamiento y elegibilidad específicos sin versión vigente.',308:'Plazos y cambios contractuales sujetos a validación.',309:'Mora del 5% y plazos sin contraste con tarifario vigente.',310:'Duplicado de condiciones de cargos bajo título de metodología.',311:'Elegibilidad y garantías específicas sin versión aprobada.',312:'Plazos/canales de cancelación a confirmar.',319:'Tabla de canales por producto ausente en conversión y plazos específicos.',320:'Diferencias de alcance: VF01 menciona débito/crédito en 180 días; ProUsuario solo crédito. No ampliar por inferencia.',321:'Derechos/plazos regulatorios: revisión de alcance.',322:'Derechos/plazos regulatorios: revisión de alcance.',323:'Requisitos legales y plazo de vehículo a confirmar.',324:'Teléfono 809-227-1222 difiere del contacto público del banco; reglas sucesorales específicas no verificadas.'}

def clean_body(text):
    ls=text.replace('\r','').splitlines()
    ls=[x.strip() for x in ls if not x.strip().startswith('Contexto Banca Santa Cruz') and x.strip()!='Definiciones:']
    # Solo quitar párrafos idénticos; nunca conciliar cláusulas diferentes.
    paras=re.split(r'\n\s*\n','\n'.join(ls)); seen=set();out=[]
    for p in paras:
        p=p.strip(); k=norm(p)
        if p and k not in seen:out.append(p);seen.add(k)
    if len(out)==2:
        first=out[0].split('\n',1)
        if len(first)==2 and norm(first[1])==norm(out[1]):out=out[:1]
    return '\n\n'.join(out)

def domain_object(n,row):
    if n in (80,81,82,83):return 'institucional','banco'
    if 176<=n<=255:return 'credito_diferido','credito_diferido'
    if 257<=n<=276:return 'tarjetas','tarjeta_credito'
    if 278<=n<=289:return 'tarjetas','tarjeta_debito'
    if 290<=n<=312:return 'prestamos','prestamo'
    if 313<=n<=318:return 'cuentas','cuenta'
    if n>=319:return 'procedimientos',{319:'cancelacion',320:'reclamacion',321:'derechos',322:'derechos',323:'garantia',324:'sucesion'}[n]
    return 'glosario','concepto'

cards=[]; row_to_doc={}; normalized={}; extraction=[]
for r in rows:
    n=r['source_row']
    if not 79<=n<=324:continue
    if n in HEADERS:
        extraction.append({'source_row':n,'disposition':'heading_only','related_rows':HEADERS[n]});continue
    title=TITLE.get(n,r['Dato / subintención objetivo']);body=clean_body(r['Criterio de aceptación origen'])
    if not body:body=r['Definición funcional del dato'].strip()
    # Solo duplicados con mismo tema/cuerpo. La unión conserva todos los renglones.
    key=(norm(title),norm(body))
    if key in normalized:
        c=normalized[key];c['source_rows'].append(n);row_to_doc[n]=c['id'];extraction.append({'source_row':n,'disposition':'exact_duplicate','canonical_id':c['id']});continue
    domain,obj=domain_object(n,r); cid=f'vf01-r{n:03d}'
    kind='procedure' if domain=='procedimientos' or any(w in norm(title) for w in ['solicitud','cancelacion','perdida','bloqueo','requisitos']) else ('definition' if domain=='glosario' else 'product_knowledge')
    issues=[]
    if n in REVIEW: issues.append(REVIEW[n])
    # Revisión automática declarada como tal, para números normativos/comerciales no verificados.
    numeric_conditions=bool(re.search(r'\d+\s*(?:%|\([^)]*\)\s*)?(?:d[ií]as|meses|a[nñ]os)|\d+\s*%|RD\$\s*\d|US\$\s*\d',body,re.I))
    if numeric_conditions and not issues:issues.append('Condición numérica detectada: confirmar versión/vigencia; alerta automática, no juicio de invalidez.')
    c=dict(id=cid,title=title,content=body,domain=domain,object=obj,content_kind=kind,language='es-DO',country='DO',source_type='user_supplied_bank_workbook',source_file='Base_de_Conocimiento_IA_VF01.MD',source_sheet='Matriz_Cuentas',source_rows=[n],source_column='Criterio de aceptación origen',source_original_reference=r['Observaciones'],source_status=r['Estado'],approval_status='approval_not_evidenced',approved_for_prod=False,valid_from=None,valid_to=None,reviewed_on='2026-09-19',version=VERSION,qa_eligible=not issues,review_reasons=issues,contains_personal_data=False,related_case_ids=[],web_source_ids=[])
    c['content_hash']=hashlib.sha256(body.encode()).hexdigest()
    cards.append(c);normalized[key]=c;row_to_doc[n]=cid
    extraction.append({'source_row':n,'disposition':'recovered','canonical_id':cid,'definition_was_shorter':len(r['Definición funcional del dato'])<len(body)*.4,'title_corrected':n in TITLE,'qa_eligible':c['qa_eligible']})
for n,target in HEADERS.items():row_to_doc[n]=[row_to_doc[x] for x in target if x in row_to_doc]

# Fichas editoriales de alcance reducido. No agregan tasas, cálculos ni plazos.
SAFE=[
('bsc-reclamaciones-orientacion','Cómo iniciar una reclamación',[320],'procedimientos','reclamacion','Puedes presentar una reclamación por el Centro de Contacto, en un Centro de Negocios o mediante BSC en Línea. Describe el motivo y conserva los soportes de la operación. Después del registro, la documentación de tu caso y su número se envían al correo registrado. Los soportes dependen del motivo: por ejemplo, constancia de devolución, factura o evidencia del pago por otro medio. Para seguimiento, usa el Centro de Contacto o un Centro de Negocios. Este asistente explica el proceso; no registra una reclamación por sí mismo.'),
('bsc-fallecidos-orientacion','Fallecimiento: etapas de información y retiro',[324],'procedimientos','sucesion','El primer paso es notificar el fallecimiento en una sucursal, presentando inicialmente el acta de defunción. La solicitud de información o certificación de productos corresponde al cónyuge, sucesores o su representante legal, acreditando esa condición. El retiro de fondos requiere completar la documentación sucesoral y la revisión del Banco. Solicitar información y solicitar el retiro son etapas distintas. La sucursal debe confirmar los documentos aplicables a cada familiar o representante. Este chat no consulta productos de la persona fallecida ni determina quién tiene derecho a heredar.'),
('bsc-cancelacion-orientacion','Cancelación general y monto personal de cancelación',[319,312,289,250,252,255],'procedimientos','cancelacion','El procedimiento depende del producto. Antes del cierre se revisan saldos, cargos, operaciones pendientes y compromisos aplicables. Para préstamos, el documento suministrado contempla BSC en Línea, Centro de Contacto y Centros de Negocios; para débito, Centros de Negocios. Al finalizar corresponde recibir la constancia aplicable. El monto para cancelar un préstamo concreto debe venir de una consulta autorizada y con su fecha de referencia. Explicar el procedimiento o consultar ese monto no cancela el producto.'),
('bsc-garantias-orientacion','Liberación de garantías: distinguir inmueble y vehículo',[323],'procedimientos','garantia','Tras pagar completamente el préstamo, corresponde gestionar la liberación de la garantía con la documentación del Banco. El trámite cambia según sea un inmueble o un vehículo: la hipoteca requiere gestión ante la Jurisdicción Inmobiliaria; la garantía de vehículo se canaliza con el oficial del Banco. Confirma el tipo de garantía para recibir la lista de documentos y el trámite que corresponde. La liquidación del préstamo no demuestra por sí sola que la garantía ya fue liberada.'),
('bsc-recompensas-orientacion','Puntos, cashback y Smartcash',[114,116,117,125,127,272],'tarjetas','recompensas','Puntos Santa Cruz, cashback y Smartcash son mecanismos de recompensas diferentes. Los puntos se acumulan y se redimen según su programa. Cashback devuelve una proporción de consumos elegibles; puede tener condiciones fijas o promocionales. Smartcash corresponde al programa descrito para compras PriceSmart. La participación, categorías, tasas de acumulación, topes y vencimientos deben consultarse en las condiciones vigentes de la tarjeta y del programa; el saldo personal de recompensas se obtiene del contexto autorizado.'),
('bsc-pago-minimo-contextual','Pago mínimo: tarjeta de crédito y Multicrédito',[104,123,217],'glosario','pago_minimo','El pago mínimo es un concepto que debe leerse dentro del producto. La base define para Multicrédito la suma de las cuotas pagables del mes y las comisiones presentadas. Para una tarjeta de crédito, el mínimo es el abono mínimo requerido según las condiciones del producto; no equivale necesariamente al balance total. Para decir cuánto debe pagar una persona se necesita el dato de su producto, moneda y período. No se traslada una fórmula de Multicrédito a una tarjeta rotativa.'),
]
for cid,title,refs,domain,obj,body in SAFE:
    cards.append(dict(id=cid,title=title,content=body,domain=domain,object=obj,content_kind='scoped_editorial_summary',language='es-DO',country='DO',source_type='derived_from_user_supplied_bank_workbook',source_file='Base_de_Conocimiento_IA_VF01.MD',source_sheet='Matriz_Cuentas',source_rows=refs,source_column='Criterio de aceptación origen',source_status='Propuesta funcional',approval_status='approval_not_evidenced',approved_for_prod=False,valid_from=None,valid_to=None,reviewed_on='2026-09-19',version=VERSION,qa_eligible=True,review_reasons=[],contains_personal_data=False,related_case_ids=[],web_source_ids=[],content_hash=hashlib.sha256(body.encode()).hexdigest()))

web=read('fuentes/ampliaciones_web.json')
for w in web:
    if w.get('include_as_knowledge'):
        body=w['summary'];cards.append(dict(id=w['id'],title=w['title'],content=body,domain=w['domain'],object=w['object'],content_kind='public_reference',language='es-DO',country='DO',source_type='official_public_website',source_url=w['url'],source_rows=[],source_file=None,source_sheet=None,source_column=None,source_status='web_verified_excerpt',approval_status='approval_not_evidenced',approved_for_prod=False,valid_from=None,valid_to=None,reviewed_on='2026-09-19',version=VERSION,qa_eligible=True,review_reasons=[],contains_personal_data=False,related_case_ids=[],web_source_ids=[w['id']],content_hash=hashlib.sha256(body.encode()).hexdigest()))

# Asociación editorial de cada caso a filas concretas. No usa coincidencia de palabras
# como supuesto oráculo y NO significa que el software pase el caso.
M={}
def family(prefix,maps):
    for i,refs in enumerate(maps,1):M[f'{prefix}{i:02}']=refs
family('P',[[26,27,32,335],[26,27,31,34,335],[67,68,70,335],[67,69,71,335],[46,48,52,53,335],[9,10,11,335],[9,26,335],[10,26,70,335],[26,27,35,340],[48,51,53,55,340],[9,26,67,335],[30,32,68,70,335],[67,68,69,335],[9,11,335],[48,53,55,335]])
family('C',[[6,9,10,11],[24,27,31,32],[44,48,52,53],[64,67,68,70,71],[22,24,25,27,31],[42,44,45,48,53],[64,67,69,6,10,11,333],[24,26,31,64,67,70,333]])
family('D',[[4,22,62,328],[4,9,10,328],[32,53,70,72,328],[48,69,328],[4,9],[30,31],[319,71,334],[148,273,287,318,328],[26,27,328],[320,133]])
family('R',[[7,9,10,11,334],[25,26,32,334],[65,67,69,70,334],[45,48,52,53,334]])
family('X',[[20,26,32,341],[325,10],[325,70,72],[326],[331,9],[331,38],[332],[344,332],[330,48,69,158],[343,26]])
family('IG',[[80,81,82,83],[84,85],[88],[99,100],[95,99],[97,98],[174,175],[96,167],[105],[134,139,225],[126,120],[124],[125,114,272],[116,117],[142,143,144,164],[163,165],[166],[168],[159],[160]])
family('CD',[[89,177,180],[102,180,188,189],[192,194],[194,198,199],[196,200,203],[200,224],[201,205,220],[206,207],[208,209],[221,222,223],[210,249],[212,213,219],[104,217],[219,220,225,226],[197,198,214],[215,216],[202,204],[250,252,253,254,255],[252,254,255],[229,230,231,232,234,236,238,239,240,241,243,244,245,246,247]])
family('TC',[list(range(257,269)),[257,259,260,261],[262],[258],[267,268],[265,266,268],[265,266],[269,270],[272,114,125,127],[273,274],[110,111,112],[118],[119],[275,276],[123,26,29],[128,129]])
family('TD',[list(range(278,285)),[278,280],[149],[287],[288],[286,288],[289],[130,149]])
family('PR',[list(range(291,302)),[291,293],[291,292],[294,295,297,298],[295],[294,296],[297,298,299],[300],[301],[303,304],[305],[307,308,309],[308,310,69],[309,312,71],[312]])
family('CE',[[142,143,144,314,315,316],[314,315],[314,316],[315,316],[317],[317],[318],[144,164,171]])
family('GR',[[319],[319,289,312],[320],[320,133],[321,322],[321,322],[323],[323],[324],[324],[324],[324]])
family('CTX',[[89,177,180,192,194,219,250,335],[102,207,205,220,214],[260,261,340],[291,293,303,304,294,295],[163,165],[97,98,119,124],[320,321,322],[323],[324]])
family('DA',[[328,192,269,303,317],[328,194,305,317],[328,330,148],[328,319],[340],[340,330],[340,328],[340,328],[113,249,328],[200,271,286,328]])
family('MIX',[[98,32],[123,31],[143,10],[105,67],[39,53],[121,26],[102,177,332],[291,293,63],[273,34],[312,71]])
family('CMP',[[102,180,188,189],[102,180,188,189],[89,130,180],[102,180,188,189],[142,143],[142,143,144,164],[314,315,318],[166,314],[130,149],[130,149],[257,259,260],[260,261],[262,257],[258,257],[267,268],[265,266],[264],[265,257],[265,266],[291,293],[291,292],[295,297],[296,294],[299,291],[300,291],[39,46,48,53,142],[50],[97,98],[123,121],[110,111,112],[119,120],[118,120],[114,125],[116,117],[99,100],[174,175],[163,165],[134,139,225],[102,180,188,189,219,250,255],[259,260,261],[314,315],[291,293,303,304],[267,268,265],[130,149,273,287],[39,48,53,142],[123,121],[118,119,120],list(range(291,302))])
family('CC',[[102,180,188,207,250,255,340],[260,261,259,340],[143,142,144,164,340],[291,293,303,304,294,295,340],[130,149,273,287,334,340]])
family('CA',[[340,328],[340],[340,330],[340],[340,328],[340,272],[340,330],[340]])
assert set(M)=={c['case_id'] for c in cases},(set(M)-{c['case_id'] for c in cases},{c['case_id'] for c in cases}-set(M))

M.update({'P06':[8,11,12,335],'P07':[11,26,335],'P08':[11,26,70,335],'P11':[11,26,67,335],'P14':[11,12,335],'C01':[3,11,12],'C07':[64,67,69,3,11,12,333],'D01':[22,62,328],'D02':[5,11,328],'D05':[8,9,11],'R01':[4,11,12,334],'X02':[325,11],'X05':[331,11],'MIX03':[143,11]})
FIELDS={11:'account.ledger_balance|account.available_balance',12:'account.transactions',26:'credit_card.current_debt',27:'credit_card.available_credit',28:'credit_card.credit_limit',29:'credit_card.statement_balance',31:'credit_card.minimum_payment',32:'credit_card.cutoff_date|credit_card.payment_due_date',33:'credit_card.points',34:'credit_card.transactions',46:'deposit.opening_amount',47:'deposit.opening_date',48:'deposit.interest_rate',49:'deposit.term',50:'deposit.interest_payment_mode',51:'deposit.current_balance',52:'deposit.interest_earned',53:'deposit.maturity_date',66:'loan.disbursed_amount',67:'loan.outstanding_balance',68:'loan.installment_amount',69:'loan.interest_rate',70:'loan.next_payment_date',71:'loan.payoff_amount',72:'loan.maturity_date',73:'loan.transactions',74:'loan.status'}
# Vérifier los renglones de cuentas: los IDs se ajustan al dato real en VF01.
for n in range(2,19):
    t=norm(byrow[n]['Dato / subintención objetivo'])
    if 'saldo actual' in t and 'disponible' not in t:FIELDS[n]='account.ledger_balance'
    if 'saldo disponible' in t:FIELDS[n]='account.available_balance'
    if 'transacciones' in t or 'movimientos' in t:FIELDS[n]='account.transactions'

SPECIAL_GAPS={
 'P02':'Movimientos requieren una capacidad real; no crear historial con RAG.',
 'P04':'Saldo pendiente no equivale al saldo para cancelar; vigencia del monto obligatoria.',
 'P06':'No sustituir cuenta corriente por ahorro. Ledger y movimientos deben existir.',
 'P11':'Separar activos y deudas; no sumar monedas ni netear productos sin solicitud y regla.',
 'P12':'Definir ventana de pago próximo; no confundir vencimiento final con próxima cuota.',
 'P15':'Respetar exclusión de balance y comparación de fecha mínima.',
 'IG12':'Plazo de gracia en la fuente requiere validación contractual.',
 'IG16':'Revisar circular de 17-09-2026 antes de publicar plazos normativos.',
 'TC02':'Gold y Clásica tienen descripción prácticamente idéntica; no hay comparativa completa de beneficios/costos.',
 'TC03':'No inferir edad exacta de Visa Joven; conservar tipo crédito frente a débito.',
 'TC14':'La documentación no habilita por sí sola cálculos de intereses de un cliente.',
 'TD02':'Las descripciones no prueban una diferencia concreta de beneficios/tarifas.',
 'PR13':'Fila 310 repite cargos bajo título metodología; no hay fórmula personal validada.',
 'GR01':'Tabla canal×producto incompleta; explicar lo respaldado y pedir producto.',
 'GR09':'Orientación general sí; no revelar productos de un familiar por parentesco declarado.',
 'MIX05':'El bloque DAP especifica consultas personales, pero falta ficha comercial general suficiente de certificados.',
 'MIX07':'Ausencia solo demostrable con inventario completo y origen confiable.',
 'MIX09':'Cargos posibles en KB no prueban un cargo realmente aplicado; requiere movimientos.',
 'CMP26':'Falta ficha comercial general de certificados; campos personales no la sustituyen.',
 'CMP27':'La modalidad personal del certificado no constituye una definición comercial completa.',
 'CMP45':'Falta ficha comercial de depósitos, no completar con una recomendación inventada.',
}
allbyid={c['id']:c for c in cards};mappings=[]
for c in cases:
    refs=M[c['case_id']]; docs=[]
    for n in refs:
        value=row_to_doc.get(n,[]);docs.extend(value if isinstance(value,list) else [value])
    for cid,_,rr,*_ in SAFE:
        if set(rr)&set(refs):docs.append(cid)
    for w in web:
        if w.get('include_as_knowledge') and c['case_id'] in w.get('case_ids',[]):docs.append(w['id'])
    docs=uniq(docs)
    for d in docs:allbyid[d]['related_case_ids'].append(c['case_id'])
    rules=[f'vf01-r{n:03d}' for n in refs if n<79 or n>=325]
    fields=uniq([f for n in refs if n in FIELDS for f in FIELDS[n].split('|')])
    mode='knowledge'
    if fields:mode='mixed' if docs else 'personal'
    elif c['case_id'].startswith(('DA','CA','D')):mode='context_dependent'
    elif c['case_id'].startswith('X'):mode='security_or_conversation'
    if c['case_id']=='MIX07':mode='mixed';fields=['portfolio.product_presence']
    if c['case_id']=='MIX08':fields=['portfolio.products']
    gaps=[]
    if c['case_id'] in SPECIAL_GAPS:gaps.append(SPECIAL_GAPS[c['case_id']])
    if fields:gaps.append('Conectar y comprobar estos campos en el snapshot real; no se auditó aquí el contrato Core ni se ejecutó /turn.')
    if any(not allbyid[d]['qa_eligible'] for d in docs):gaps.append('Parte de la fuente detallada requiere revisión; hay resumen acotado solo cuando se indica.')
    if len(c['turns'])>1:gaps.append('Ejecutar turnos separados en la misma sesión; no enviar flechas como una sola pregunta.')
    strategies=['E01_intencion_completa','E04_evidencia_por_faceta','E08_respuesta_natural']
    if fields:strategies+=['E02_resolucion_productos','E03_memoria_tipificada']
    if len(c['turns'])>1:strategies+=['E03_memoria_tipificada']
    if c['case_id'].startswith(('CMP','CC','CA')) or 'compar' in norm(c['question']):strategies+=['E05_comparaciones']
    if c['case_id'].startswith('P') or mode=='mixed':strategies+=['E06_multitarea']
    if c['case_id'].startswith('X') or c['case_id'] in ['GR09','GR10','GR11','GR12']:strategies+=['E07_seguridad_con_alcance']
    mappings.append(dict(case_id=c['case_id'],mapping_type='editorial_source_and_behavior_mapping',mapping_is_execution_evidence=False,mode=mode,source_rows=refs,knowledge_ids=docs,behavior_rule_ids=rules,candidate_tool_fields=fields,field_scope_note='Capacidades mencionadas por las reglas asociadas; el oráculo debe precisar solo las facetas pedidas en cada turno.',strategies=uniq(strategies),expected=c['expected'],gaps=gaps,current_execution_status='NOT_EXECUTED',coverage_status='SOURCE_AND_GAPS_IDENTIFIED'))
    c['current_execution_status']='NOT_EXECUTED';c['turn_count']=len(c['turns']);c['family']=re.match('[A-Z]+',c['case_id']).group()
    c['historical_label_is_oracle']=False
    if c['case_id'] in ['TC03','GR03','GR09']:c['visual_review']='Historical Cumple contradicted by inspected screenshot; use semantic oracle.'
write('evaluacion/casos_236.json',cases);write('evaluacion/cruce_236_kb.json',mappings)

# Reglas y pruebas quedan fuera del corpus recuperable.
rules=[]
for r in rows:
    n=r['source_row']
    if n<79 or n>=325:
        rules.append(dict(id=f'vf01-r{n:03d}',source_row=n,domain=r['Producto'],target=r['Dato / subintención objetivo'],business_rule=r['Regla de negocio'],selection_rule=r['Regla selección de producto'],currency_rule=r['Regla de moneda'],context_rule=r['Regla de contexto'],required_data=r['Datos / campos requeridos'],prohibited=r['Elementos prohibidos'],security=r['Autenticación / seguridad'],pending=r['Brecha / pendiente'],source_status=r['Estado'],retrieval_eligible=False))
write('estrategia/reglas_funcionales_98.json',rules)
lines('kb/fichas_candidatas.jsonl',cards)
eligible=[c for c in cards if c['qa_eligible']]
lines('kb/fichas_qa.jsonl',eligible)
write('revision/trazabilidad_filas_246.json',extraction)
write('revision/revision_contenido.json',[{k:c[k] for k in ['id','title','source_rows','review_reasons']} for c in cards if not c['qa_eligible']])

# Cada ficha conserva su identidad; los fragmentos retienen procedencia y orden.
chunks=[]
for c in eligible:
    paras=c['content'].split('\n\n');parts=[];current=''
    for p in paras:
        if len(current)+len(p)>2200 and current:parts.append(current);current=''
        current=(current+'\n\n'+p).strip()
    if current:parts.append(current)
    for i,p in enumerate(parts,1):
        chunks.append(dict(id=c['id']+f'-c{i:02}',parent_id=c['id'],ordinal=i,title=c['title'],content=p,domain=c['domain'],object=c['object'],content_kind=c['content_kind'],language='es-DO',country='DO',source_rows=c['source_rows'],source_url=c.get('source_url'),version=VERSION,qa_eligible=True,approval_status=c['approval_status'],approved_for_prod=False,valid_from=None,valid_to=None,related_case_ids=c['related_case_ids']))
lines('kb/chunks_qa.jsonl',chunks)
md=['# Base de conocimiento BSC — selección para QA','',f'Versión: {VERSION}. Este documento contiene conocimiento, no resultados de pruebas ni datos de clientes. La vigencia de condiciones financieras no se presume. El campo approved_for_prod permanece false porque el adjunto no acredita aprobación.','']
for c in eligible:
    md += [f"## {c['id']} — {c['title']}",'',f"Fuente: {c.get('source_url') or ('VF01 / Matriz_Cuentas / filas '+', '.join(map(str,c['source_rows'])))}",'',c['content'],'']
(ROOT/'kb/Base_Conocimiento_BSC_QA.md').write_text('\n'.join(md),encoding='utf-8')

# Catálogo semántico: no representa códigos del Core ni productos del cliente.
products=[]
for n in list(range(257,269))+list(range(278,285))+[291,292,293,294,295,296,297,298,299,300,301,314,315]:
    cid=row_to_doc[n];c=allbyid[cid];title=c['title'];aliases=[title]
    simple=re.sub(r'^Tarjeta de (Crédito|Débito)\s*','',title,flags=re.I)
    if simple!=title:aliases.append(simple)
    if 'Joven' in title:aliases+=['joven','tarjeta joven']
    if 'Gold' in title:aliases+=['gold','dorada']
    if 'Platinum' in title:aliases+=['platinum','platino']
    if 'Clásica' in title:aliases+=['clasica','classic']
    products.append(dict(catalog_id='bsc-catalog-r'+str(n),name=title,family=c['object'],aliases=uniq(aliases),knowledge_id=cid,core_codes=[],core_mapping_status='UNVERIFIED',alias_alone_proves_ownership=False))
for key,name,fam,aliases,ns in [('multicredito','Multicrédito BSC','credito_diferido',['multicredito','multicrédito','multicredito empleado'],[102,177]),('cuotas','Cuotas BSC','credito_diferido',['cuotas bsc','cuotas santa cruz'],[91,180]),('deposito','Certificado / depósito a plazo','deposito',['certificado','deposito a plazo','dap','certificado financiero'],[])]:
    products.append(dict(catalog_id='bsc-catalog-'+key,name=name,family=fam,aliases=aliases,knowledge_ids=[row_to_doc[n] for n in ns],core_codes=[],core_mapping_status='UNVERIFIED',alias_alone_proves_ownership=False))
write('catalogo/productos_alias.json',{'version':VERSION,'usage':'Resolver candidatos junto al snapshot. No afirmar tenencia ni crear códigos Core. Joven, Gold, Platinum e Infinite pueden tener varias familias.','products':products})
field_entries=[]
for n,fs in FIELDS.items():
    for f in fs.split('|'):
        field_entries.append(dict(field=f,source_rule=f'vf01-r{n:03d}',meaning=byrow[n]['Definición funcional del dato'],core_json_path=None,mapping_status='VERIFY_IN_CHECKOUT',on_missing='FIELD_NOT_AVAILABLE',on_zero='Preservar cero si fue retornado explícitamente',on_unknown='No convertir a cero ni a producto inexistente',source_fetched_at_required=True))
write('catalogo/campos_semanticos.json',field_entries)
taxonomy={
 'version':VERSION,'note':'Taxonomía semántica propuesta, extensible, independiente del naming del contrato Core.',
 'domains':[
  {'domain':'personal','actions':[{'action':'consultar','objects':[{'object':o,'fields':[f for v in FIELDS.values() for f in v.split('|') if f.startswith(prefix)]} for o,prefix in [('cuenta','account.'),('tarjeta_credito','credit_card.'),('deposito','deposit.'),('prestamo','loan.')]]},{'action':'consultar_tenencia','objects':[{'object':'portafolio','fields':['product_presence','completeness','source']}]},{'action':'comparar','objects':[{'object':'productos_propios','fields':['requested_fields','currency','as_of']}]}]},
  {'domain':'conocimiento','actions':[{'action':a,'objects':[{'object':o,'fields':fs} for o,fs in [('producto',['descripcion','requisitos','usos','cargos','canales','condiciones']),('concepto',['definicion','diferencias']),('banco',['mision','vision'])]]} for a in ['explicar','comparar','orientar_solicitud']]},
  {'domain':'procedimientos','actions':[{'action':'orientar','objects':[{'object':o,'fields':['etapas','documentos','canales','condiciones','plazos_verificados']} for o in ['reclamacion','cancelacion','liberacion_garantia','fallecimiento']]}]},
  {'domain':'conversacion','actions':[{'action':a,'objects':[{'object':'sesion','fields':['pending_tasks','personal_focus','knowledge_focus','compare_set','references']}]} for a in ['aclarar','corregir','retomar','cambiar_tema']]},
  {'domain':'seguridad','actions':[{'action':'proteger','objects':[{'object':o,'fields':['scope','reason_code']} for o in ['credenciales','titularidad','instrucciones_internas']]}]}
 ]}
write('catalogo/taxonomia_dominio_accion_objeto_campo.json',taxonomy)
stats=dict(source_rows=len(rows),knowledge_source_rows=246,behavior_rows=len(rules),cases=len(cases),multi_turn_cases=sum(len(c['turns'])>1 for c in cases),heading_multiturn=sum(c['source_format']=='heading' for c in cases),table_multiturn=sum(c['source_format']=='table' and len(c['turns'])>1 for c in cases),source_heading_only=len(HEADERS),candidate_cards=len(cards),qa_cards=len(eligible),qa_chunks=len(chunks),review_cards=len(cards)-len(eligible),families=dict(Counter(c['family'] for c in cases)),current_executed=0,visual_samples_reviewed=6,source_statuses=dict(Counter(r['Estado'] for r in rows)),source_declared_coverage=dict(Counter(str(r['Cobertura funcional %']) for r in rows)),recovered_from_short_definition=sum(x.get('definition_was_shorter',False) for x in extraction))
write('revision/estadisticas.json',stats)
print(json.dumps(stats,ensure_ascii=False,indent=2))
