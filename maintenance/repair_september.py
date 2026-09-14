"""Repair September 2026 only, using local clock records as evidence."""
import json
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from sqlalchemy import text
from resources.config_path import crear_engine_externo, cargar_config_conexion
from app.api.asistencias import MAPA_METODO_A_CVER

START, END = '2026-09-01', '2026-10-01'
OUT = Path('maintenance')

def fingerprint(row):
    return (str(row['fecha']), str(row['hora']).zfill(8), str(row['tipo']), int(row['reloj']), int(row['c_ver']))

def audit(c):
    employees = defaultdict(set)
    for r in c.execute(text('SELECT id, n_reloj FROM empleados')).mappings():
        employees[str(r['n_reloj']).strip()].add(r['id'])
    evidence = defaultdict(set)
    unknown = 0
    with sqlite3.connect('file:data/marcaciones.db?mode=ro', uri=True) as db:
        for device, card, stamp, event, method in db.execute('SELECT dispositivo_id, empleado_id, fecha_hora, tipo_evento, metodo FROM marcaciones WHERE fecha_hora >= ? AND fecha_hora < ?', (START, END)):
            ids = employees.get(str(card).strip(), set())
            if len(ids) != 1 or event not in (0, 1):
                unknown += 1
                continue
            try:
                dt = datetime.fromisoformat(stamp)
                key = (dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M:%S'), 'E' if event == 0 else 'S', int(device), MAPA_METODO_A_CVER.get(str(method).lower(), 3))
                evidence[key].add((int(card), next(iter(ids))))
            except (TypeError, ValueError):
                unknown += 1
    rows = [dict(r) for r in c.execute(text('SELECT * FROM asistencias WHERE fecha >= :start AND fecha < :end'), {'start':START, 'end':END}).mappings()]
    existing = {(fingerprint(r), r['empleados_id']) for r in rows}
    plan, skipped = [], Counter()
    for r in rows:
        key = fingerprint(r)
        matches = evidence.get(key, set())
        targets = {target for card,target in matches if card == r['empleados_id'] and target != card}
        if not targets:
            continue
        if any(target == r['empleados_id'] for card,target in matches):
            skipped['also_matches_correct_employee'] += 1
            continue
        if len(targets) != 1:
            skipped['ambiguous_target'] += 1
            continue
        target = next(iter(targets))
        if (key, target) in existing:
            skipped['correct_record_already_exists'] += 1
            continue
        plan.append({'before':r, 'new_empleados_id':target})
    return plan, dict(skipped), unknown

if __name__ == '__main__':
    engine = crear_engine_externo(cargar_config_conexion())
    if '--apply' not in sys.argv:
        with engine.connect() as c:
            plan, skipped, unknown = audit(c)
        path = OUT / 'septiembre_2026_plan.json'
        path.write_text(json.dumps({'plan':plan, 'skipped':skipped, 'local_unresolved':unknown}, default=str, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'candidates':len(plan), 'employee_pairs':dict(Counter(str((x['before']['empleados_id'], x['new_empleados_id'])) for x in plan)), 'skipped':skipped, 'local_unresolved':unknown}, ensure_ascii=False))
    else:
        saved = json.loads((OUT/'septiembre_2026_plan.json').read_text(encoding='utf-8'))
        backup = OUT / ('septiembre_2026_backup_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
        with engine.begin() as c:
            plan, skipped, unknown = audit(c)
            serialized = json.loads(json.dumps(plan, default=str))
            if serialized != saved['plan']:
                raise RuntimeError('El plan cambió; volver a auditar antes de aplicar.')
            locked = {r['id']:dict(r) for r in c.execute(text('SELECT * FROM asistencias WHERE fecha >= :start AND fecha < :end FOR UPDATE'), {'start':START,'end':END}).mappings()}
            for item in plan:
                if locked.get(item['before']['id']) != item['before']:
                    raise RuntimeError('Una asistencia cambió desde la auditoría.')
            backup.write_text(json.dumps({'status':'before_update', 'plan':plan}, default=str, ensure_ascii=False, indent=2), encoding='utf-8')
            params = [{'new':item['new_empleados_id'], 'id':item['before']['id'], 'old':item['before']['empleados_id'], 'start':START, 'end':END} for item in plan]
            if params:
                result = c.execute(text('UPDATE asistencias SET empleados_id=:new WHERE id=:id AND empleados_id=:old AND fecha >= :start AND fecha < :end'), params)
                if result.rowcount != len(plan):
                    raise RuntimeError('Cantidad inesperada de filas modificadas.')
            after = {r['id']:dict(r) for r in c.execute(text('SELECT * FROM asistencias WHERE fecha >= :start AND fecha < :end'), {'start':START,'end':END}).mappings()}
            expected = {key:dict(value) for key,value in locked.items()}
            for item in plan:
                expected[item['before']['id']]['empleados_id'] = item['new_empleados_id']
            if after != expected:
                raise RuntimeError('Verificación fallida; se revierte la transacción.')
        (OUT/'septiembre_2026_resultado.json').write_text(json.dumps({'updated':len(plan), 'backup':str(backup), 'skipped':skipped}, indent=2), encoding='utf-8')
        print('COMMIT OK',len(plan),'BACKUP',backup)
