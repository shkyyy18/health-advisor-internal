"""Read-only conversion of existing health evidence to dated daily JSON."""
from pathlib import Path
from datetime import datetime, timedelta
from statistics import mean
import argparse, json, sqlite3
from contextlib import closing
from health_review_snapshot import build_snapshot, moment, LOCAL

def summarize(rows):
    weights=[(r['date'],r['weight']['value']) for r in rows if r['weight']['value'] is not None]
    sleeps=[r['sleep']['duration'] for r in rows if r['sleep']['duration'] is not None]
    days=(datetime.fromisoformat(weights[-1][0])-datetime.fromisoformat(weights[0][0])).days if len(weights)>1 else 0
    return {'calendar_days':len(rows),'weight_days':len(weights),'weight_mean':mean(x[1] for x in weights) if weights else None,
            'weight_change':weights[-1][1]-weights[0][1] if days else None,
            'weight_change_per_calendar_day':(weights[-1][1]-weights[0][1])/days if days else None,
            'sleep_days':len(sleeps),'sleep_mean_hours':mean(sleeps) if sleeps else None,
            'observed_exercise_days':sum(bool(r['exercise']) for r in rows),
            'exercise_coverage':'recorded activities only; absent record does not establish rest'}

def chart(rows,field):
    values=[(r['date'],r[field]['value' if field=='weight' else 'duration']) for r in rows]
    known=[v for _,v in values if v is not None]
    low=min(known) if known else 0; high=max(known) if known else 0
    return '\n'.join(d+' '+('missing' if v is None else f'{v:.2f} '+(' '*round((v-low)/(high-low or 1)*24))+'*') for d,v in values)

def export(database,as_of,out):
    snapshot=build_snapshot(database,as_of)
    today=as_of.astimezone(LOCAL).date(); start=today-timedelta(days=29)
    rows={ (start+timedelta(days=i)).isoformat():{'schema_version':'1.1','date':(start+timedelta(days=i)).isoformat(),
            'weight':{'value':None,'unit':'kg'},'sleep':{'duration':None,'unit':'hours'},'exercise':None,
            'diet':{'water_intake':None},'sources':[]} for i in range(30)}
    for body in snapshot['body']['history']:
        d=moment(body['measured_at']).date().isoformat()
        if d in rows:
            rows[d]['weight']={'value':body['weight_kg'],'unit':'kg','time':body['measured_at']}
            rows[d]['sources'].append('sqlite:body_measurements')
    grouped={}
    for sleep in snapshot['sleep']['recent_records']:
        if sleep['candidate_main_night'] and moment(sleep['end_at']) and moment(sleep['end_at'])<=as_of:
            d=moment(sleep['end_at']).date().isoformat();grouped.setdefault(d,[]).append(sleep)
    for d,items in grouped.items():
        if d not in rows:continue
        # Multiple candidate records cannot establish a single complete night.
        if len(items)==1:
            rows[d]['sleep']={'duration':items[0]['reported_asleep_minutes']/60,'unit':'hours','bedtime':items[0]['start_at'],'wakeup':items[0]['end_at']}
        else:rows[d]['sleep']['quality_issue']='multiple_candidate_nights'
        rows[d]['sources'].append('sqlite:sleep_summaries; validated_by_health_review_snapshot')
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        for when,kind,seconds,distance in c.execute('SELECT start_date,sport_type,moving_time,distance FROM activities ORDER BY start_date'):
            dt=moment(when)
            if dt and dt<=as_of and dt.date().isoformat() in rows:
                row=rows[dt.date().isoformat()]
                if row['exercise'] is None:row['exercise']=[]
                row['exercise'].append({'type':kind,'duration_minutes':seconds/60 if seconds is not None else None,'distance_meters':distance})
                if 'sqlite:activities' not in row['sources']:row['sources'].append('sqlite:activities')
    ordered=list(rows.values())
    report={'as_of':as_of.isoformat(),'source':str(database),'windows':{str(n):summarize(ordered[-n:]) for n in (7,30)},'previous_7_days':summarize(ordered[-14:-7])}
    out.mkdir(parents=True,exist_ok=True)
    for d,row in rows.items():
        (out/f'{d}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    reportdir=out.parent/'weekly';reportdir.mkdir(exist_ok=True)
    (reportdir/f'trends-{today}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (reportdir/f'trends-{today}.md').write_text('# 健康趋势证据\n\n截止：'+as_of.isoformat()+'\n缺失不代表0。图表按本窗口最小/最大值归一，数值以标签为准。\n\n```json\n'+json.dumps(report['windows'],ensure_ascii=False,indent=2)+'\n```\n\n体重（kg）\n```\n'+chart(ordered[-7:],'weight')+'\n```\n\n睡眠（小时）\n```\n'+chart(ordered[-7:],'sleep')+'\n```\n',encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--as-of');p.add_argument('--database',type=Path,default=Path(__file__).resolve().parents[1]/'data/health.db');p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'data/daily');a=p.parse_args()
    dt=datetime.fromisoformat(a.as_of) if a.as_of else datetime.now(LOCAL)
    if dt.tzinfo is None:p.error('--as-of needs timezone')
    export(a.database,dt,a.output);print('Structured daily records and trend evidence exported; no diagnosis generated.')
