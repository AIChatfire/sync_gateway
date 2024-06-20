#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Project      : AI.  @by PyCharm
# @File         : poll
# @Time         : 2024/5/22 08:46
# @Author       : betterme
# @WeChat       : meutils
# @Software     : PyCharm
# @Description  :

from meutils.pipe import *

from meutils.pipe import *
from meutils.notice.feishu import send_message
from meutils.str_utils.regular_expression import parse_url

from chatllm.schemas.openai_types import chat_completion, chat_completion_chunk
from chatllm.schemas.openai_api_protocol import ChatCompletionRequest, UsageInfo
from chatllm.utils.openai_utils import openai_response2sse, to_openai_completion_params

from openai import OpenAI, AsyncOpenAI


class Completions(object):
    def __init__(self, api_key=None):
        params = dict(
            api_key=api_key,
            base_url='https://api.chatfire.cn/v1',
            max_retries=1,
        )
        # 如果这一步就报错呢
        self.client = AsyncOpenAI(**params)

    def create(self, request: ChatCompletionRequest):
        logger.debug(str(request.messages))

        prompt = request.messages[-1].get('content')
        data = to_openai_completion_params(request)

        logger.debug(request.messages)

        return OpenAI().chat.completions.create(**data)

    async def acreate(self, request: ChatCompletionRequest, **kwargs):
        logger.debug(str(request.messages))

        prompt = request.messages[-1].get('content')
        data = to_openai_completion_params(request)

        logger.debug(str(request.messages))

        _ = await self.client.chat.completions.create(**data)

        return _
