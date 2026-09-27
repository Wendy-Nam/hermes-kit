"""Student-owned routes for the optional OMH enhancements. No instructor defaults."""
from pathlib import Path
from model_setup import MODEL
from upstream_omh import CATEGORIES

LABELS = {'quick':'짧고 간단한 작업', 'deep':'깊은 분석', 'architect':'설계',
          'artistry':'창작', 'ultrabrain':'고난도 추론', 'writing':'글쓰기',
          'visual-engineering':'화면·디자인 구현', 'capable':'일반 작업',
          'simple-work':'간단한 실행', 'deep-work':'복잡한 실행',
          'unspecified-low':'분류되지 않은 간단한 작업', 'unspecified-high':'분류되지 않은 복잡한 작업'}

def available_providers(data_dir):
    from config_store import read
    c=read(data_dir)
    names=set((c.get('providers') or {}).keys())
    for role in ('model','delegation'):
        item=c.get(role) or {}
        if isinstance(item,dict) and isinstance(item.get('provider'),str):names.add(item['provider'])
    return sorted(p for p in names if p not in ('auto','default','custom') and MODEL.fullmatch(p))

def save_route(data_dir, category, provider, model, effort, kind):
    if category not in CATEGORIES or provider not in available_providers(data_dir):
        return {'status':'failed','message':'작업 종류와 이미 연결한 제공자를 선택해 주세요.'}
    if not MODEL.fullmatch(model) or effort not in ('low','medium','high','xhigh','max') or kind not in ('model','combo'):
        return {'status':'failed','message':'정확한 모델/콤보 ID와 지원되는 추론 강도를 입력해 주세요.'}
    if not (Path(data_dir)/'plugins/omh').is_dir():
        return {'status':'failed','message':'먼저 OMH 기본 팩을 설치해 주세요.'}
    # An isolated, tool-free connection probe uses this student's existing keys.
    # Nothing is persisted when the selected route cannot answer.
    from model_setup import probe
    ok,message=probe(data_dir,role='aux',candidate=(provider,model))
    if not ok:return {'status':'failed','message':message}
    from omh_enhancements import enable_enhanced_omh
    return enable_enhanced_omh(data_dir,category_routes={category:[{
        'provider':provider,'model':model,'reasoning_effort':effort,'kind':kind}]},require_route=True)
