import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import importer

def chat():
    return {"id":"one","title":"제목", "current_node":"answer", "mapping":{
        "root":{"parent":None,"message":None},
        "question":{"parent":"root","message":{"author":{"role":"user"},"content":{"parts":["질문"]}}},
        "answer":{"parent":"question","message":{"author":{"role":"assistant"},"content":{"parts":["선택 답"]}}},
        "other":{"parent":"question","message":{"author":{"role":"assistant"},"content":{"parts":["버린 분기"]}}}}}

class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.inbox=self.root/"vaults/personal/Inbox/import";self.inbox.mkdir(parents=True)
        self.archive=self.inbox/"export.zip"
    def tearDown(self):self.tmp.cleanup()
    def write(self,rows,extra=None):
        with zipfile.ZipFile(self.archive,"w") as z:
            z.writestr("conversations.json",json.dumps(rows))
            if extra:z.writestr(*extra)
    def run_import(self):return importer.import_export(self.archive,self.root)
    def files(self):return list((self.root/"vaults/personal/Archive").rglob("*.md"))
    def test_branch_idempotence_and_user_edit_preserved(self):
        self.write([chat()]);self.assertTrue(self.run_import()[0])
        f=self.files()[0];content=f.read_text();self.assertIn("선택 답",content);self.assertNotIn("버린 분기",content)
        self.assertIn("동일 내용 1개",self.run_import()[1])
        f.write_text("my edit");self.assertIn("기존 파일 1개 보존",self.run_import()[1]);self.assertEqual(f.read_text(),"my edit")
    def test_claude_and_markup_as_text(self):
        self.write([{"uuid":"c1","name":"Claude","chat_messages":[{"sender":"human","text":"![x](https://bad)\n```"},
            {"sender":"assistant","content":[{"type":"text","text":"답"}]}]}])
        self.assertTrue(self.run_import()[0]);f=self.files()[0]
        self.assertEqual(f.parent.name,"claude");self.assertIn("````text",f.read_text())
    def test_traversal_rejected_before_writes(self):
        for name in ("../bad","/bad","x\\bad","C:/bad"):
            self.write([chat()],(name,"bad"));self.assertFalse(self.run_import()[0]);self.assertFalse(self.files())
    def test_zip_symlink_rejected(self):
        entry=zipfile.ZipInfo("link");entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
        self.write([chat()],(entry,"/tmp"));self.assertFalse(self.run_import()[0])
    def test_size_rejected(self):
        self.write([chat()])
        with patch.object(importer,"MAX_JSON",2):self.assertFalse(self.run_import()[0])
    def test_output_symlink_rejected(self):
        self.write([chat()]);target=self.root/"elsewhere";target.mkdir()
        (self.root/"vaults/personal/Archive").symlink_to(target,target_is_directory=True)
        self.assertFalse(self.run_import()[0]);self.assertFalse(list(target.iterdir()))
    def test_input_symlink_and_nonprivate_rejected(self):
        self.write([chat()]);other=self.root/"elsewhere.zip";self.archive.rename(other);self.archive.symlink_to(other)
        self.assertFalse(self.run_import()[0]);self.assertFalse(importer.import_export(other,self.root)[0])
    def test_invalid_branch_and_duplicate_ids_atomic_validation(self):
        invalid=chat();invalid["current_node"]="missing"
        self.write([chat(),invalid]);self.assertFalse(self.run_import()[0]);self.assertFalse(self.files())
        duplicate=chat();duplicate["title"]="different"
        self.write([chat(),duplicate]);self.assertFalse(self.run_import()[0]);self.assertFalse(self.files())

if __name__=="__main__":unittest.main()
