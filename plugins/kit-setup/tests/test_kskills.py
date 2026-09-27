import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import components
SEED=ROOT.parents[1]/'seed' if (ROOT.parents[1]/'seed/kskill').is_dir() else Path('/opt/kit/seed')

class VendoredKSkills(unittest.TestCase):
    def test_every_listed_skill_is_vendored_and_verifies(self):
        spec=json.loads((ROOT/'kskills.json').read_text())
        names=set(components.kskill_names(list(spec['kits'])))
        self.assertEqual(names,{p.name for p in (SEED/'kskill').iterdir() if p.is_dir()})
        for name in names:
            doc=components._manifest(SEED/'kskill'/name,name)
            text=(SEED/'kskill'/name/'SKILL.md').read_text()
            self.assertTrue(text.startswith('---\nname: '+name+'\n'),name)
            self.assertNotIn('npx',text,name)
            self.assertFalse(any(f.startswith('scripts/test_') for f in doc['files']),name)
            for path in __import__('re').findall(r'/opt/data/skills/k-skill/([a-z0-9-]+/\S+?\.(?:py|md))',text):
                self.assertTrue((SEED/'kskill'/path).is_file(),path)
        self.assertIn('MIT',(SEED/'kskill/LICENSE').read_text())

    def test_selection_adds_job_sets_and_dependencies(self):
        common=components.kskill_names([])
        self.assertIn('korea-weather',common);self.assertNotIn('biz-health-check',common)
        sales=components.kskill_names(['sales'])
        self.assertIn('nts-tax-delinquency',sales);self.assertEqual(len(sales),len(set(sales)))

    def test_install_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            rows=components.retry_components(data,selected_kits=['job'],seed_dir=SEED)
            row=next(r for r in rows if r['id']=='k-skill')
            self.assertEqual(row['status'],'installed',row)
            for name in components.kskill_names(['job']):
                self.assertTrue((data/'skills/k-skill'/name/'SKILL.md').is_file(),name)
            self.assertTrue((data/'skills/k-skill/fsc-corporate-info/scripts/fsc_corporate_info.py').is_file())
            again=next(r for r in components.retry_components(data,seed_dir=SEED) if r['id']=='k-skill')
            self.assertEqual(again['status'],'installed')
            edited=data/'skills/k-skill/korea-weather/SKILL.md';edited.write_text('student edit')
            components.retry_components(data,seed_dir=SEED)
            self.assertEqual(edited.read_text(),'student edit')

if __name__=='__main__':unittest.main()
