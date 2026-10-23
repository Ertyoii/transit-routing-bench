"""Focused synthetic block-relative/absolute-coordinate and resume tests."""
import copy
import unittest
import post_stage as w
import conductor as c

class Coordinates(unittest.TestCase):
    def pair(self,index):
        block,segment=divmod(index,4)
        return {'block':block,'segment':segment},{'block':block,'segment':segment,'global_start_position':segment*84}
    def test_all8_actual_block_relative_coordinate_schema(self):
        for index in range(8):
            with self.subTest(index=index):w.validate_stage_coordinates(*self.pair(index),index)
    def test_block1_absolute_offset_is_not_plan_relative_offset(self):
        for index in range(4,8):
            stage,plan=self.pair(index);plan['global_start_position']=index*84
            with self.subTest(index=index),self.assertRaisesRegex(RuntimeError,'block-relative'):
                w.validate_stage_coordinates(stage,plan,index)
    def test_wrong_block_segment_and_bool_coordinates_rejected(self):
        for target in ('stage','plan'):
            for key,value in (('block',0),('segment',1),('block',True),('segment',False)):
                stage,plan=self.pair(4);(stage if target=='stage' else plan)[key]=value
                with self.subTest(target=target,key=key,value=value),self.assertRaises(RuntimeError):
                    w.validate_stage_coordinates(stage,plan,4)
    def test_negative_string_bool_or_wrong_relative_offsets_rejected(self):
        for value in (-1,'0',False,84,336):
            stage,plan=self.pair(4);plan['global_start_position']=value
            with self.subTest(value=value),self.assertRaises(RuntimeError):w.validate_stage_coordinates(stage,plan,4)
    def test_absolute_global_slice_remains_correct_for_block1(self):
        ready={'all672_state_rows':[{'id':'slot-%d'%i,'state':'PLANNED_UNSTARTED'} for i in range(672)]}
        for index in range(8):
            plan={'all84_state_rows':copy.deepcopy(ready['all672_state_rows'][index*84:(index+1)*84])}
            self.assertEqual(w.validate_stage_slice(ready,plan,index)[0]['id'],'slot-%d'%(index*84))
    def test_stage_local_or_shuffled_global_slice_rejected(self):
        ready={'all672_state_rows':[{'id':'slot-%d'%i} for i in range(672)]}
        for mode in ('block_local','reverse','short'):
            rows=copy.deepcopy(ready['all672_state_rows'][336:420])
            if mode=='block_local':rows=copy.deepcopy(ready['all672_state_rows'][:84])
            elif mode=='reverse':rows.reverse()
            else:rows.pop()
            with self.subTest(mode=mode),self.assertRaisesRegex(RuntimeError,'absolute ledger'):
                w.validate_stage_slice(ready,{'all84_state_rows':rows},4)
    def test_code_root_is_separate_from_existing_v2_state_root(self):
        from pathlib import Path
        self.assertEqual(w.WORK.name,'stage-workflow-v2')
        self.assertEqual(Path(c.__file__).resolve().parent.name,'stage-workflow-v3')
        self.assertFalse(hasattr(c,'resume_before'))

    def test_owner_must_launch4_then_use_existing_terminal4_interface(self):
        # Existing conductor's first operation is preserve(index), never launch
        # index. Therefore stage4 must already be terminal; stage3 is not retried.
        events=[]
        def preserve(s,index):
            events.append(('preserve_terminal',index))
            raise RuntimeError('synthetic terminal4 archive stop')
        with self.assertRaises(RuntimeError):
            c.conduct(None,4,preserve=preserve,launch=lambda s,i:events.append(('BAD_LAUNCH',i)))
        self.assertEqual(events,[('preserve_terminal',4)])


if __name__=='__main__':unittest.main(verbosity=2)
