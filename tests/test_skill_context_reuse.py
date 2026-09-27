import ast
from pathlib import Path
import unittest
import importlib.util
spec=importlib.util.spec_from_file_location("reuse_patch",Path(__file__).resolve().parents[1]/"patches/core/patch-skill-context-reuse.py")
reuse_patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse_patch)
OLD, NEW, patched = reuse_patch.OLD, reuse_patch.NEW, reuse_patch.patched

class ReusePatchTests(unittest.TestCase):
    def fixture(self): return 'def instructions():\n    return (\n'+OLD+'\n    )\n'
    def test_patch_is_syntax_valid_and_preserves_loading_requirement(self):
        result,changed=patched(self.fixture());self.assertTrue(changed);ns={};exec(compile(ast.parse(result),'<fixture>','exec'),ns)
        text=ns['instructions']();self.assertIn('MUST obtain and follow',text);self.assertIn('without calling skill_view again',text)
    def test_new_message_alone_does_not_require_reload(self):
        result,_=patched(self.fixture());self.assertIn('merely because a new ',result)
    def test_missing_pruned_updated_reference_still_reload(self):
        result,_=patched(self.fixture())
        for term in ['absent, incomplete','pruned by compression','explicitly updated','unread reference file','old loaded marker alone']:
            self.assertIn(term,result)
    def test_idempotent(self):
        once,_=patched(self.fixture());twice,changed=patched(once);self.assertFalse(changed);self.assertEqual(once,twice)
    def test_drift_or_duplicate_refused(self):
        for source in ['def unrelated(): pass',self.fixture()+self.fixture()]:
            with self.assertRaises(ValueError):patched(source)
    def test_invalid_python_refused(self):
        with self.assertRaises(SyntaxError):patched(self.fixture()+'\ninvalid syntax !!!')


class StoredPromptTests(unittest.TestCase):
    def helper(self):
        HELPER = reuse_patch.HELPER
        ns={};exec(HELPER,ns);return ns['refresh_stored_skills_reuse_prompt']
    def old(self):
        RUNTIME_OLD = reuse_patch.RUNTIME_OLD
        return 'USER OVERLAY unchanged\n## Skills\n'+RUNTIME_OLD+'commands and workflows.\n<available_skills>\nx\n</available_skills>\nUSER TAIL unchanged'
    def test_exact_migration_preserves_overlay_and_roster(self):
        RUNTIME_OLD,RUNTIME_NEW = reuse_patch.RUNTIME_OLD,reuse_patch.RUNTIME_NEW
        value=self.old();result,changed=self.helper()(value);self.assertTrue(changed)
        self.assertEqual(result,value.replace(RUNTIME_OLD,RUNTIME_NEW,1));self.assertEqual(self.helper()(result),(result,False))
    def test_quoted_incomplete_duplicate_and_drift_are_untouched(self):
        for value in [self.old().replace('## Skills\n',''),self.old().replace('<available_skills>','no roster'),self.old()+self.old(),self.old().replace('Before replying','Before answering')]:
            self.assertEqual(self.helper()(value),(value,False))
    def test_restore_patch_persists_through_existing_api_and_is_idempotent(self):
        RESTORE_OLD,patched_restore = reuse_patch.RESTORE_OLD,reuse_patch.patched_restore
        source='def restore():\n    if True:\n'+RESTORE_OLD+' the original surface\n'
        result,changed=patched_restore(source);self.assertTrue(changed);self.assertIn('_persist_system_prompt(agent,',result);self.assertEqual(patched_restore(result),(result,False))

if __name__=='__main__':unittest.main()
