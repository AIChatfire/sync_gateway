#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Project      : AI.  @by PyCharm
# @File         : vv
# @Time         : 2024/5/21 18:57
# @Author       : betterme
# @WeChat       : meutils
# @Software     : PyCharm
# @Description  : https://github.com/OpenBMB/MiniCPM-V?tab=readme-ov-file
# test.py    Need more than 16GB memory to run.
import torch
from PIL import Image
from transformers import AutoModel, AutoTokenizer

model = AutoModel.from_pretrained('openbmb/MiniCPM-Llama3-V-2_5-int4', trust_remote_code=True, low_cpu_mem_usage=True)
model = model.to(device='mps')

# tokenizer = AutoTokenizer.from_pretrained('openbmb/MiniCPM-Llama3-V-2_5', trust_remote_code=True)
# model.eval()
#
# image = Image.open('./assets/hk_OCR.jpg').convert('RGB')
# question = 'Where is this photo taken?'
# msgs = [{'role': 'user', 'content': question}]
#
# answer, context, _ = model.chat(
#     image=image,
#     msgs=msgs,
#     context=None,
#     tokenizer=tokenizer,
#     sampling=True
# )
# print(answer)
