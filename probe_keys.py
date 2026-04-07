# probe_keys.py
import os
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['FLAGS_use_mkldnn'] = '0'          # 禁用 oneDNN/MKL-DNN
os.environ['FLAGS_enable_pir_api'] = '0'      # 禁用 PIR API（规避 ConvertPirAttribute 报错）
os.environ['CUDA_VISIBLE_DEVICES'] = ''       # 强制 CPU

import glob, sys

MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
DET = os.path.join(MODELS, 'PP-OCRv5_server_det')
REC = os.path.join(MODELS, 'PP-OCRv5_server_rec')
ORI = os.path.join(MODELS, 'PP-LCNet_x1_0_textline_ori')

imgs = glob.glob(r'D:\Pyproject\pro2\*.png') + glob.glob(r'D:\Pyproject\pro2\*.jpg')
if not imgs:
    print('No test image found'); sys.exit(1)
img_path = imgs[0]
print('Test image:', img_path)

import paddle
paddle.device.set_device('cpu')

from paddleocr import PaddleOCR
ocr = PaddleOCR(
    text_detection_model_dir=DET,
    text_recognition_model_dir=REC,
    textline_orientation_model_dir=ORI,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=True,
    device='cpu',
)

results = list(ocr.predict(img_path))
print(f'\npredict returned {len(results)} result(s)')
for i, res in enumerate(results):
    print(f'\n--- result[{i}] type={type(res).__name__} ---')
    if hasattr(res, 'keys'):
        for k in res.keys():
            v = res[k]
            vtype = type(v).__name__
            if hasattr(v, '__len__'):
                print(f'  {k}: {vtype}  len={len(v)}')
                if len(v) > 0 and k not in ('input_img',):
                    first = v[0]
                    if hasattr(first, 'tolist'):
                        first = first.tolist()
                    print(f'    first={str(first)[:120]}')
            else:
                print(f'  {k}: {vtype}  val={str(v)[:80]}')
    if i >= 1:
        break
