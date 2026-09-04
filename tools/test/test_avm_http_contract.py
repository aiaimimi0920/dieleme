from __future__ import annotations

from tools.test.avm_http_contract_base import AVMHttpContractBase
from tools.test.avm_http_contract_part_01 import AVMHttpContractPart01
from tools.test.avm_http_contract_part_02 import AVMHttpContractPart02
from tools.test.avm_http_contract_part_03 import AVMHttpContractPart03
from tools.test.avm_http_contract_part_04 import AVMHttpContractPart04
from tools.test.avm_http_contract_part_05 import AVMHttpContractPart05
from tools.test.avm_http_contract_part_06 import AVMHttpContractPart06
from tools.test.avm_http_contract_part_07 import AVMHttpContractPart07
from tools.test.avm_http_contract_part_08 import AVMHttpContractPart08
from tools.test.avm_http_contract_part_09 import AVMHttpContractPart09
from tools.test.avm_http_contract_part_10 import AVMHttpContractPart10
from tools.test.avm_http_contract_part_11 import AVMHttpContractPart11


class TestAVMHttpContract(
    AVMHttpContractPart01,
    AVMHttpContractPart02,
    AVMHttpContractPart03,
    AVMHttpContractPart04,
    AVMHttpContractPart05,
    AVMHttpContractPart06,
    AVMHttpContractPart07,
    AVMHttpContractPart08,
    AVMHttpContractPart09,
    AVMHttpContractPart10,
    AVMHttpContractPart11,
    AVMHttpContractBase,
):
    pass
