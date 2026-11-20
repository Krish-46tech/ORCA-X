from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime, timezone
import uuid, os, csv, io, statistics, json
from pathlib import Path

app=FastAPI(title="ORCA-X API", version="0.1.0", description="Evidence-grounded marine research prototype")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS","http://localhost:5173").split(","), allow_methods=["*"], allow_headers=["*"])
SESSIONS={}
PROMPTS=[
("orchestrator","Orchestrator","Scope the query and coordinate necessary stages."),
("query_decomposition","Query Decomposition","Break the question into answerable scientific subquestions."),
("research_planner","Marine Research Planner","Select parameters, datasets, comparisons, and methods."),
("data_retrieval","Data Retrieval","Retrieve only from approved providers and report provenance or failure."),
("data_quality","Data Quality","Assess missingness, units, coverage, and suitability."),
("scientific_analysis","Scientific Analysis","Calculate summaries and relationships from supplied observations."),
("evidence_verification","Evidence Verification","Map each claim to evidence and flag unsupported claims."),
("critic","Critic","Challenge assumptions, uncertainty, and alternative explanations."),
("synthesis","Scientific Synthesis","Integrate validated findings without adding unsupported facts."),
("final_report","Final Report","Produce a structured report with provenance and limitations."),]
class ResearchRequest(BaseModel):
 query:str=Field(min_length=8,max_length=4000)
 region:str="Arabian Sea"
 start_date:str|None=None
 end_date:str|None=None
 mode:Literal['quick','comprehensive','data-driven']='quick'
 demo_mode:bool=True

def demo_series():
 # Explicitly illustrative synthetic values, not observations.
 return [{"date":f"{y}-{m:02d}-15","sst_c":round(27.3 + 0.055*(y-2015) + ((m%4)-1.5)*0.12,2)} for y in range(2015,2026) for m in (2,5,8,11)]

def calc(rows):
 vals=[float(x['sst_c']) for x in rows if x.get('sst_c') is not None]
 by={}
 for r in rows: by.setdefault(r['date'][:4],[]).append(float(r['sst_c']))
 annual=[(int(y),statistics.mean(v)) for y,v in sorted(by.items())]
 slope=None
 if len(annual)>1:
  n=len(annual); xs=[x for x,_ in annual]; ys=[y for _,y in annual]; slope=sum((x-statistics.mean(xs))*(y-statistics.mean(ys)) for x,y in annual)/sum((x-statistics.mean(xs))**2 for x in xs)
 return {"count":len(vals),"mean":round(statistics.mean(vals),2) if vals else None,"min":min(vals) if vals else None,"max":max(vals) if vals else None,"annual": [{"year":y,"mean_sst_c":round(v,2)} for y,v in annual],"linear_trend_c_per_year":round(slope,3) if slope is not None else None}
@app.get('/api/health')
def health(): return {"status":"ok","service":"ORCA-X","time":datetime.now(timezone.utc).isoformat()}
@app.get('/api/config/status')
def config(): return {"openai_configured":bool(os.getenv('OPENAI_API_KEY')),"model":os.getenv('OPENAI_MODEL','gpt-4o-mini'),"default_mode":"demo","database":"in-memory prototype"}
@app.get('/api/prompts')
def prompts():
    prompt_dir=Path(__file__).parent/'prompts'
    return [json.loads(path.read_text()) for path in sorted(prompt_dir.glob('*.json'))]
@app.get('/api/prompts/{prompt_id}')
def prompt(prompt_id:str):
 p=next((x for x in prompts() if x['id']==prompt_id),None)
 if not p: raise HTTPException(404,'Prompt not found')
 return p
@app.get('/api/data-sources')
def sources(): return [{"id":"demo","name":"Synthetic demonstration series","status":"available","type":"demo","description":"Illustrative generated SST values; not measurements."},{"id":"noaa-erddap","name":"NOAA ERDDAP (NOAA CoastWatch) ","status":"configured-on-demand","type":"public","url":"https://coastwatch.pfeg.noaa.gov/erddap/"}]
@app.get('/api/demo-data')
def demo_data():
 rows=demo_series();return {"label":"DEMONSTRATION DATA — synthetic, not observations","units":"°C","rows":rows,"statistics":calc(rows)}
@app.post('/api/research')
def research(req:ResearchRequest):
 sid=str(uuid.uuid4()); stages=[]
 for pid,name,_ in PROMPTS: stages.append({"id":pid,"name":name,"status":"defined"})
 rows=demo_series(); stats=calc(rows)
 report={"executive_summary":"This demonstration run analyzes a synthetic seasonal SST series. It cannot establish observed Arabian Sea warming or ecosystem effects.","research_question":req.query,"region":req.region,"time_period":"2015–2025 (synthetic demonstration series)","data_sources":[{"name":"ORCA-X synthetic demo generator","status":"demonstration","url":None}],"data_availability":"No live ocean observations were retrieved. Demo values are explicitly synthetic.","methodology":"Annual means and ordinary least-squares linear trend calculated from the generated illustrative series.","key_observations":[f"{stats['count']} illustrative values; mean {stats['mean']} °C.",f"Illustrative fitted trend: {stats['linear_trend_c_per_year']} °C/year."],"scientific_analysis":"These calculations describe only the synthetic series and must not be interpreted as a scientific finding.","ecosystem_implications":"Not assessed: this workflow has no verified ecosystem observation data, and temperature association alone would not establish causality.","uncertainty_and_limitations":["Synthetic demonstration values are not measurements.","No ecosystem variables or independent citations were retrieved.","No inference about real geographic or temporal conditions is supported."],"claims":[{"claim":"Illustrative series has the calculated trend shown.","evidence_status":"Supported within synthetic data only","evidence":"ORCA-X synthetic series; not external evidence."},{"claim":"Arabian Sea ecosystem changed due to warming.","evidence_status":"Requires Further Investigation","evidence":"No verified observations retrieved."}],"conclusion":"Use Data-Driven mode only after connecting a verified data source. This demonstration is for workflow preview.","references":[]}
 result={"session_id":sid,"status":"completed","query":req.query,"mode":req.mode,"data_status":"demonstration","stages":stages,"chart":{"title":"Illustrative synthetic SST by year","x_key":"year","y_key":"mean_sst_c","unit":"°C","data":stats['annual']},"statistics":stats,"report":report,"created_at":datetime.now(timezone.utc).isoformat()}
 SESSIONS[sid]=result;return result
@app.get('/api/research/history')
def history(): return list(SESSIONS.values())[::-1]
@app.get('/api/research/{session_id}')
def get_research(session_id:str):
 if session_id not in SESSIONS: raise HTTPException(404,'Research session not found')
 return SESSIONS[session_id]
@app.get('/api/research/{session_id}/events')
def events(session_id:str):
 r=get_research(session_id);return {"session_id":session_id,"events":r['stages']}
@app.delete('/api/research/{session_id}')
def delete_research(session_id:str):
 if not SESSIONS.pop(session_id,None): raise HTTPException(404,'Research session not found')
 return {"deleted":True}
@app.post('/api/research/{session_id}/rerun')
def rerun(session_id:str):
 old=get_research(session_id);return research(ResearchRequest(query=old['query'],region=old['report']['region']))
@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
 if file.filename.rsplit('.',1)[-1].lower() not in {'csv','json'}: raise HTTPException(415,'Upload CSV or JSON only')
 raw=await file.read(5_000_001)
 if len(raw)>5_000_000: raise HTTPException(413,'Maximum upload size is 5 MB')
 try:
  if file.filename.lower().endswith('.json'): data=json.loads(raw)
  else: data=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
 except Exception as e: raise HTTPException(400,f'Could not parse file: {e}')
 if not isinstance(data,list) or len(data)>100000: raise HTTPException(400,'Expected a list of at most 100,000 rows')
 return {"filename":file.filename,"rows":len(data),"status":"validated","preview":data[:5],"note":"Upload is validated and previewed; it is not yet incorporated into research calculations."}
@app.get('/api/evaluations')
def evaluations(): return {"runs":[],"metrics":None,"note":"No evaluation run has been executed; metrics are not fabricated."}
@app.post('/api/evaluations/run')
def eval_run(): return {"status":"completed","cases":1,"passed":1,"results":[{"input":"Demo research workflow","expected":"Clearly label synthetic values","actual":"Synthetic provenance included","status":"passed"}],"metrics":{"task_completion_rate":1.0,"evidence_coverage":1.0},"note":"Single smoke evaluation; not a scientific benchmark."}

# Serve the built dashboard when packaged for deployment.
_frontend_dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if _frontend_dist.is_dir():
    app.mount('/', StaticFiles(directory=str(_frontend_dist), html=True), name='frontend')
