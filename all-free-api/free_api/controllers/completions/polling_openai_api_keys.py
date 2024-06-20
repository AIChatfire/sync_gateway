#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Project      : AI.  @by PyCharm
# @File         : multi_key_openai
# @Time         : 2024/5/22 14:16
# @Author       : betterme
# @WeChat       : meutils
# @Software     : PyCharm
# @Description  :


from meutils.pipe import *
from meutils.async_utils import async_to_sync
from meutils.notice.feishu import send_message as _send_message
from meutils.db.redis_db import redis_client, redis_aclient
from meutils.config_utils.lark_utils import get_spreadsheet_values

from meutils.llm.openai_utils import to_openai_completion_params, token_encoder
from meutils.schemas.openai_types import chat_completion, chat_completion_chunk, ChatCompletionRequest

from openai import OpenAI, AsyncOpenAI, APIStatusError

send_message = partial(
    _send_message,
    url="https://open.feishu.cn/open-apis/bot/v2/hook/e0db85db-0daf-4250-9131-a98d19b909a9",
    title="轮询api-keys"
)

redis_client.decode_responses = True


class Completions(object):
    def __init__(self, provider: Optional[str] = None, api_keys: Optional[List] = None):
        # provider = provider or "https://api.deepseek.com/v1|https://xchatllm.feishu.cn/sheets/Bmjtst2f6hfMqFttbhLcdfRJnNf?sheet=lVghgx"
        provider = provider or "redis:https://api.deepseek.com/v1|https://xchatllm.feishu.cn/sheets/Bmjtst2f6hfMqFttbhLcdfRJnNf?sheet=lVghgx"

        self.base_url, self.feishu_url = provider.lstrip("redis:").lstrip("redis=").split('|')
        self.redis_key = self.feishu_url if provider.startswith(("redis:", "redis=")) else None

        self.api_keys = api_keys  # 优先级更高

    async def acreate(self, request: ChatCompletionRequest, **kwargs):
        data = to_openai_completion_params(request)

        clent: Optional[AsyncOpenAI] = None
        for i in range(5):  # 轮询个数
            try:
                client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                completion = await client.chat.completions.create(**data)

                # 一般逆向api需要重新计算
                if completion and completion.usage.prompt_tokens == completion.usage.completion_tokens == 1:
                    # logger.debug(completion.usage)

                    prompt_tokens = len(token_encoder.encode(str(request.messages)))
                    completion_tokens = len(token_encoder.encode(str(completion)))

                    alfa: float = 1
                    completion.usage.prompt_tokens = int(alfa * prompt_tokens)
                    completion.usage.completion_tokens = int(alfa * completion_tokens)
                    completion.usage.total_tokens = completion.usage.prompt_tokens + completion.usage.completion_tokens

                return completion

            except APIStatusError as e:  # {'detail': 'Insufficient Balance'}
                logger.error(e)

                if e.status_code == 400:
                    send_message(f"{e.response}\n\n{e}")

                    chat_completion.choices[0].message.content = chat_completion_chunk.choices[0].delta.content = str(e)
                    return chat_completion_chunk if request.stream else chat_completion

                if i > 3:
                    send_message(f"{clent and clent.api_key}\n\n{e}\n\n{self.feishu_url}")

    @property
    def api_key(self):  # 轮询: todo: 异步
        if self.api_keys:
            return np.random.choice(self.api_keys)

        if self.redis_key:
            api_key = redis_client.lpop(self.redis_key).decode()  # b""
            if api_key:
                redis_client.rpush(self.redis_key, api_key)
            else:
                send_message(f"redis_key为空，请检查\n\n{self.redis_key}")

        else:
            api_keys = get_spreadsheet_values(feishu_url=self.feishu_url, to_dataframe=True)[0]
            api_key = np.random.choice(api_keys)

        return api_key


if __name__ == '__main__':
    pass
    print(arun(Completions().acreate(
        ChatCompletionRequest(model='deepseek-chat', messages=[{"role": "user", "content": "你是谁"}])
    )))
