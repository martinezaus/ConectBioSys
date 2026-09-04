from app.api.hikvision import HikvisionAdapter
from app.api.zkteco import ZKTecoAdapter

ADAPTERS = {
	"hikvision": HikvisionAdapter,
	"zkteco": ZKTecoAdapter,
	# "Suprema": "",
    # "Anviz": "",
    # "Dahua":"",
    # "Matrix Comsec":"",
    # "Virdi":"",
    # "Hanvon":"",
    # "FingerTec":"",
    # "Nitgen":"",
    # "NEC":"",
    # "SecuGen":"",
}