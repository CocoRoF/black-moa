"""다시 찍기 전 데모 계정 되돌리기: 나와의 대화 지우기, 인박스 미팅 요청 보관, Google 연결 끊기."""
import sys; sys.path.insert(0, '.')
from mapi import call
tok = call('POST', '/api/auth/login', {'email': 'demo@memo-ora.com', 'password': __import__('os').environ['DEMO_PW']})[1]['access_token']
agent = __import__('os').environ.get('DEMO_AGENT', '06abbc3d-70c4-7c62-8000-087de0eb8621')
st, j = call('GET', f'/api/agents/{agent}/conversations', None, tok)
for c in j.get('items', []):
    print('del conv', c.get('title'), call('DELETE', f"/api/agents/{agent}/conversations/{c['id']}", None, tok)[0])
st, j = call('GET', '/api/inbox', None, tok)
for it in j.get('items', []):
    if it.get('status') not in ('archived',):
        print('archive', it['kind'], call('POST', f"/api/inbox/{it['id']}/status", {'status': 'archived'}, tok)[0])
st, j = call('GET', '/api/integrations', None, tok)
for c in j.get('connections', []):
    print('disconnect', c['provider'], call('DELETE', f"/api/integrations/{c['id']}", None, tok)[0])
