"""Independent review fixtures: synthetic values only; no real network or vault."""
import json
import pytest
from fastapi.testclient import TestClient
import app.main as main
from app.security.policy import PolicyStore

SECRET = 'ReviewStreamSecret73!'

class Vault:
    def available(self): return True
    def configured(self): return True
    async def list_items(self): return []

class Model:
    def __init__(self, kind): self.kind=kind; self.step=0
    async def complete(self, *args, **kwargs):
        return json.dumps({'action':'final','answer':'password='+SECRET,'citations':[]})
    async def stream_complete(self, *args, on_reasoning=None, **kwargs):
        self.step += 1
        if self.kind == 'reasoning' and on_reasoning:
            # Also covers a secret straddling two provider delta boundaries.
            await on_reasoning('password=ReviewStream')
            await on_reasoning('Secret73!')
        if self.kind == 'action' and self.step == 1:
            return json.dumps({'action':'search','query':'password='+SECRET})
        return await self.complete()

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE_DIR', str(tmp_path/'workspace'))
    monkeypatch.setenv('DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setenv('POLICY_FILE', str(tmp_path/'policy.yaml'))
    monkeypatch.delenv('LOCAL_KEY_FILE', raising=False)
    monkeypatch.setattr(main, 'VaultwardenAdapter', lambda s:Vault())
    monkeypatch.setattr(main, 'get_active_provider', lambda s:Model('reasoning'))
    monkeypatch.setattr(main, 'get_security_provider', lambda s:None)
    monkeypatch.setattr(main.Worker, 'start', lambda s:None)
    with TestClient(main.app) as c: yield c

@pytest.mark.parametrize('kind', ['reasoning','action'])
def test_all_stream_output_obeys_same_secret_gate(client, kind):
    model=Model(kind)
    main.app.state.ctx.get_provider=lambda:model
    response=client.post('/api/query/stream',json={'question':'介绍已有资料'})
    assert response.status_code == 200
    events=[]
    for block in response.text.split('\n\n'):
        lines=block.splitlines()
        if len(lines)>=2:
            events.append((lines[0][7:],json.loads(lines[1][6:])))
    answer=next(v['answer'] for k,v in events if k=='answer')
    assert SECRET not in answer, 'final answer itself should be clean'
    trace=''.join(v.get('text','') if k=='reasoning' else v.get('query','') for k,v in events)
    print('case',kind,'final_is_clean',SECRET not in answer,'trace_contains_secret',SECRET in trace)
    assert SECRET not in trace, 'unsafe model output bypassed gate through '+kind


def test_custom_rule_is_applied_to_stream_trace(client):
    class CustomModel:
        async def stream_complete(self,*args,on_reasoning=None,**kwargs):
            await on_reasoning('内部标识 LOCAL-PIN:4826')
            return json.dumps({'action':'final','answer':'内部标识 LOCAL-PIN:4826','citations':[]})
    main.app.state.ctx.get_provider=lambda:CustomModel()
    PolicyStore(main.app.state.ctx.settings.policy_file).add_custom_rule({'name':'local_pin','pattern':r'LOCAL-PIN:\d{4}','kind':'credential'})
    response=client.post('/api/query/stream',json={'question':'介绍已有资料'})
    assert 'LOCAL-PIN:4826' not in response.text
