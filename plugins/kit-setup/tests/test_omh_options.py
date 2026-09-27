import json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config_store,omh_options,model_setup
class OmhOptionsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  config_store.write(self.root,{'delegation.provider':'kit-omniroute','delegation.model':'existing','providers.kit-omniroute.api':'http://omniroute:20128/v1'},remember=False)
  (self.root/'plugins/omh').mkdir(parents=True)
  self.fake=types.ModuleType('omh_enhancements');self.fake.enable_enhanced_omh=Mock(return_value={'status':'enabled','message':'ok'})
  import omh_enhancements
  for name in ('DEFAULT_EFFORTS','validate_chain'):setattr(self.fake,name,getattr(omh_enhancements,name))
  self.modules=patch.dict(sys.modules,{'omh_enhancements':self.fake});self.modules.start();self.addCleanup(self.modules.stop)
 def test_unconnected_provider_never_probed(self):
  with patch.object(model_setup,'probe') as probe:
   result=omh_options.save_route(self.root,'deep','stranger','model')
  self.assertEqual(result['status'],'failed');probe.assert_not_called()
 def test_keyed_provider_is_connected(self):
  (self.root/'.env').write_text('GEMINI_API_KEY=synthetic\n')
  self.assertIn('gemini',omh_options.available_providers(self.root))
 def test_failed_probe_saves_nothing(self):
  with patch.object(model_setup,'probe',return_value=(False,'offline')):
   result=omh_options.save_route(self.root,'deep','kit-omniroute','my-combo, other','high')
  self.assertEqual(result['status'],'failed');self.fake.enable_enhanced_omh.assert_not_called()
 def test_chain_probed_and_blank_effort_uses_recommendation(self):
  with patch.object(model_setup,'probe',return_value=(True,'ok')) as probe:
   omh_options.save_route(self.root,'deep','kit-omniroute','my-combo, kit-omniroute=second','')
  routes=self.fake.enable_enhanced_omh.call_args.kwargs['category_routes']
  self.assertEqual(routes,{'deep':[{'provider':'kit-omniroute','model':'my-combo','reasoning_effort':'high'},
                                    {'provider':'kit-omniroute','model':'second','reasoning_effort':'high'}]})
  self.assertEqual(probe.call_count,2)
 def test_quick_recommendation_is_low(self):
  with patch.object(model_setup,'probe',return_value=(True,'ok')):
   omh_options.save_route(self.root,'quick','kit-omniroute','my-combo')
  self.assertEqual(self.fake.enable_enhanced_omh.call_args.kwargs['category_routes']['quick'][0]['reasoning_effort'],'low')
 def test_invalid_effort_and_models_rejected(self):
  with patch.object(model_setup,'probe') as probe:
   for models,effort in (('good','auto'),('a:b',''),(','.join(f'm{i}' for i in range(6)),'')):
    self.assertEqual(omh_options.save_route(self.root,'deep','kit-omniroute',models,effort)['status'],'failed')
  probe.assert_not_called()
 def test_reset_removes_only_that_task(self):
  omh_options.save_route(self.root,'deep','kit-omniroute','-')
  self.assertEqual(self.fake.enable_enhanced_omh.call_args.kwargs,{'remove':('deep',)})
 def test_requires_installed_base(self):
  (self.root/'plugins/omh').rmdir()
  with patch.object(model_setup,'probe') as probe:
   self.assertEqual(omh_options.save_route(self.root,'deep','kit-omniroute','good')['status'],'failed')
  probe.assert_not_called()
