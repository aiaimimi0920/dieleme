from __future__ import annotations

from tools.test.avm_pipeline_test_context import AvmPipelineTestBase
from tools.test.avm_pipeline_test_part_01 import AvmPipelineTestPart01
from tools.test.avm_pipeline_test_part_02 import AvmPipelineTestPart02
from tools.test.avm_pipeline_test_part_03 import AvmPipelineTestPart03
from tools.test.avm_pipeline_test_part_04 import AvmPipelineTestPart04
from tools.test.avm_pipeline_test_part_05 import AvmPipelineTestPart05
from tools.test.avm_pipeline_test_part_06 import AvmPipelineTestPart06


class TestAVMPipeline(
    AvmPipelineTestPart01,
    AvmPipelineTestPart02,
    AvmPipelineTestPart03,
    AvmPipelineTestPart04,
    AvmPipelineTestPart05,
    AvmPipelineTestPart06,
    AvmPipelineTestBase,
):
    pass
