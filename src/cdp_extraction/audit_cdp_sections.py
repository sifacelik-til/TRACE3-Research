import gzip,json
from collections import Counter,defaultdict
from src.cdp_extraction.build_cdp_section_datasets import *

unmapped=Counter(); collisions=Counter(); examples={}
for year in range(2016,2026):
    path=STAGE/f'{year}.jsonl.gz'
    if not path.exists():continue
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        for line in stream:
            r=json.loads(line);kind=record_type(r['question_code'],year)
            if not kind:continue
            fields=defaultdict(list)
            for h,v in r['fields'].items():
                if all(str(x).lower() in {'question not applicable','not applicable','n/a',''} for x in values(v)):continue
                f=field_for(kind,h,r['question_code'],year)
                if f:fields[f].append(label(h))
                elif year>=2022:unmapped[year,kind,r['question_code'],label(h)]+=1
            for f,hs in fields.items():
                if len(hs)>1:collisions[year,kind,f,tuple(hs)]+=1
            if year>=2024 and kind in {'initiative','internal_price','net_zero_target','verify_status','ets','carbon_tax'}:
                examples.setdefault((year,kind),r)
Path('tmp/pdfs/section_audit.json').write_text(json.dumps({'unmapped':[[*k,v] for k,v in sorted(unmapped.items())],'collisions':[[*k,v] for k,v in sorted(collisions.items())],'examples':list(examples.values())},indent=2,ensure_ascii=False),encoding='utf-8')
print('unmapped',len(unmapped),'collisions',len(collisions),'examples',len(examples))
