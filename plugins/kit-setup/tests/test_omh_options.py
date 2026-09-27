import sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config_store,omh_options,model_setup
class OmhOptionsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  config_store.write(self.root,{'delegation.provider':'kit-omniroute','delegation.model':'existing','providers.kit-omniroute.api':'http://omniroute:20128/v1'},remember=False)
  (self.root/'plugins/omh').mkdir(parents=True)
 def test_unconnected_provider_never_probed(self):
  with patch.object(model_setup,'probe') as probe:
   result=omh_options.save_route(self.root,'deep','stranger','model','medium','model')
  self.assertEqual(result['status'],'failed');probe.assert_not_called()
 def test_failed_probe_does_not_modify_config(self):
  before=(self.root/'config.yaml').read_bytes()
  with patch.object(model_setup,'probe',return_value=(False,'offline')):
   result=omh_options.save_route(self.root,'deep','kit-omniroute','my-combo','medium','combo')
  self.assertEqual(result['status'],'failed');self.assertEqual((self.root/'config.yaml').read_bytes(),before)
 def test_combo_identity_passed_to_enhancement_without_guessing_family(self):
  fake=types.ModuleType('omh_enhancements');fake.enable_enhanced_omh=Mock(return_value={'status':'enabled','message':'ok'})
  with patch.dict(sys.modules,{'omh_enhancements':fake}),patch.object(model_setup,'probe',return_value=(True,'ok')):
   omh_options.save_route(self.root,'deep','kit-omniroute','my-combo','medium','combo')
  routes=fake.enable_enhanced_omh.call_args.kwargs['category_routes'];self.assertEqual(routes['deep'][0]['kind'],'combo');self.assertEqual(routes['deep'][0]['model'],'my-combo')
 def test_invalid_route_kind_rejected(self):
  with patch.object(model_setup,'probe') as probe:
   self.assertEqual(omh_options.save_route(self.root,'deep','kit-omniroute','good','medium','auto')['status'],'failed')
  probe.assert_not_called()
 def test_requires_installed_base(self):
  (self.root/'plugins/omh').rmdir()
  with patch.object(model_setup,'probe') as probe:
   self.assertEqual(omh_options.save_route(self.root,'deep','kit-omniroute','good','medium','model')['status'],'failed')
  probe.assert_not_called()
