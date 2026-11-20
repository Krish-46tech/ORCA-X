from fastapi.testclient import TestClient
from app.main import app, calc, demo_series
c=TestClient(app)
def test_health(): assert c.get('/api/health').json()['status']=='ok'
def test_prompts(): assert len(c.get('/api/prompts').json())==10
def test_validation(): assert c.post('/api/research',json={'query':'short'}).status_code==422
def test_demo_provenance():
 r=c.post('/api/research',json={'query':'Analyze Arabian Sea SST trends'}).json()
 assert r['data_status']=='demonstration' and 'synthetic' in r['report']['data_availability']
def test_calculation(): assert calc(demo_series())['count']==44
def test_unknown_session(): assert c.get('/api/research/nope').status_code==404
