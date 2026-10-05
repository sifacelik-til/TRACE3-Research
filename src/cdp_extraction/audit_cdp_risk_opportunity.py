import gzip,json
from collections import Counter,defaultdict
from pathlib import Path
from src.cdp_extraction.build_cdp_risk_opportunity import record_type,field_for,RISK_STAGE
from src.cdp_extraction.build_cdp_section_datasets import label,values

def main():
    headers=Counter();collisions=Counter();examples={}
    for year in range(2016,2026):
        with gzip.open(RISK_STAGE/f'{year}.jsonl.gz','rt',encoding='utf-8') as stream:
            for line in stream:
                r=json.loads(line);kind=record_type(r['question_code'],year)
                if not kind:continue
                mapped=defaultdict(list)
                for h,v in r['fields'].items():
                    f=field_for(kind,h,r['question_code'],year)
                    if all(str(x).lower() in {'question not applicable','not applicable','n/a',''} for x in values(v)):continue
                    if not f:headers[year,r['question_code'],kind,label(h)]+=1
                    else:mapped[f].append(label(h))
                for f,hs in mapped.items():
                    if len(hs)>1:collisions[year,kind,f,tuple(sorted(hs))]+=1
                if year>=2024:examples.setdefault((year,kind),r)
    Path('tmp/pdfs/risk_opportunity_audit.json').write_text(json.dumps({'unmapped':[[*k,v] for k,v in headers.items()],'collisions':[[*k,v] for k,v in collisions.items()],'examples':list(examples.values())},indent=2,ensure_ascii=False),encoding='utf-8')
    print('Unmapped',len(headers),'collisions',len(collisions))

if __name__=='__main__':main()
