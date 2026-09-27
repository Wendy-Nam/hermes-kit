import ast,asyncio,json,logging,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
import importlib.util,textwrap
patch_path=Path(__file__).resolve().parents[1]/'patches/core/patch-vision-inbound.py'
spec=importlib.util.spec_from_file_location('vision_patch',patch_path);vp=importlib.util.module_from_spec(spec);spec.loader.exec_module(vp)
source=textwrap.dedent(vp.NEW_BLOCK);tree=ast.parse(source)
node=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_enrich_message_with_vision')
ns={'asyncio':asyncio,'json':json,'logger':logging.getLogger('test'),'List':list}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'isolated-method','exec'),ns)
fn=ns[node.name]
class Tests(unittest.IsolatedAsyncioTestCase):
 async def call(self,worker,text='한글을 읽어줘',paths=None):
  mods={'tools.vision_tools':types.SimpleNamespace(vision_analyze_tool=worker),'agent.memory_manager':types.SimpleNamespace(sanitize_context=lambda x:x)}
  with patch.dict(sys.modules,mods):return await fn(None,text,['a','b','c'] if paths is None else paths)
 async def test_concurrency_and_question(self):
  active=peak=0;seen=[]
  async def worker(**kw):
   nonlocal active,peak
   seen.append(kw['user_prompt']);active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1;return json.dumps({'success':True,'analysis':'합성결과'})
  result=await self.call(worker);self.assertEqual(peak,2);self.assertEqual(len(seen),3);self.assertIn('한글을 읽어줘',seen[0]);self.assertIn('untrusted data',seen[0]);self.assertEqual(result.count('합성결과'),3)
 async def test_timeout_cancels_without_retry(self):
  cancelled=[]
  async def worker(**kw):
   try:await asyncio.sleep(5)
   finally:cancelled.append(kw['image_url'])
  real=asyncio.wait
  async def short(tasks,timeout):self.assertEqual(timeout,30);return await real(tasks,timeout=.02)
  with patch.object(asyncio,'wait',short):result=await self.call(worker,paths=['a','b'])
  self.assertEqual(len(cancelled),2);self.assertIn('do not automatically call vision_analyze',result)
 async def test_error_has_no_invented_content(self):
  async def worker(**kw):raise ValueError('secret-do-not-log')
  result=await self.call(worker,paths=['a']);self.assertNotIn('secret-do-not-log',result);self.assertIn('unavailable',result)
 async def test_no_images(self):
  async def worker(**kw):raise AssertionError()
  self.assertEqual(await self.call(worker,text='hello',paths=[]),'hello')
class PatchTests(unittest.TestCase):
 def test_idempotent(self):
  source='class Inbound:\n'+vp.NEW_BLOCK+vp.END+' = ""\n'
  self.assertEqual(vp.patch_source(source),source)
 def test_unknown_anchor_fail_closed(self):
  with self.assertRaises(ValueError):vp.patch_source('class Inbound: pass')
if __name__=='__main__':unittest.main()
