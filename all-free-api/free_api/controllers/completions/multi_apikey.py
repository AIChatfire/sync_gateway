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
from meutils.notice.feishu import send_message
from meutils.str_utils.regular_expression import parse_url
from meutils.db.redis_db import redis_client, redis_aclient
from meutils.config_utils.lark_utils import get_spreadsheet_values

from chatllm.schemas.openai_types import chat_completion, chat_completion_chunk
from chatllm.schemas.openai_api_protocol import ChatCompletionRequest, UsageInfo
from chatllm.utils.openai_utils import openai_response2sse, to_openai_completion_params

from openai import OpenAI, AsyncOpenAI


class Completions(object):
    def __init__(self, base_url: Optional[str] = None):
        self.provider = self.base_url = base_url or 'https://api.chatfire.cn/v1'

    async def acreate(self, request: ChatCompletionRequest, **kwargs):
        # logger.debug(str(request.messages))
        data = to_openai_completion_params(request)
        completion = None
        for i in range(10):  # 轮询个数
            api_key = redis_client.lpop(self.provider).decode()

            logger.debug(api_key)

            try:
                completion = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self.base_url,
                ).chat.completions.create(**data)

                redis_client.rpush(self.provider, api_key)  # 请求成功才会，放入右侧

            except Exception as e:  # Error code: 429 - {'error': {'message': 'Your account co1fvuucp7f01qu4l34g<ak-er3hzz411h1i11gwmzti> request reached max request: 3, please try again after 1 seconds', 'type': 'rate_limit_reached_error'}}
                if all(_ not in str(e) for _ in self.fatal_errors):
                    redis_client.rpush(self.provider, api_key)  # 不包含致命错误，可放入右侧

                logger.error(e)  # todo: 错误规避措施
                send_message(f"{api_key}:\n{e}", title=self.provider)

            return completion or await completion

    @diskcache(location='api_keys_cache', ttl=5 * 60, ignore=['self'])
    def get_and_update_api_keys(self, feishu_url):  # 保活
        """ todo： check key
        定时更新&空闲更新
                1、 通过飞书更新keys
                2、检测key
                3、更新key


                调用 => key有效性检查 => 当前key `60 // rpm +1` s后，放入keys右侧 => 轮询
                """
        # 获取keys
        df = get_spreadsheet_values(feishu_url=feishu_url, to_dataframe=True)
        api_keys = list(filter(None, df[0]))


        # 判断，更新
        if redis_client.get(feishu_url).decode() == str(api_keys):  # 之前逻辑有问题还以为异步没执行
            logger.debug("api_keys 未更新")
            return api_keys

        redis_client.set(feishu_url, str(api_keys), ex=30 * 24 * 3600)  # 更新标识

        redis_client.delete(self.provider)
        redis_client.rpush(self.provider, *api_keys)

        send_message(f"更新api_keys: \n{api_keys}", title=feishu_url)
        # logger.debug(api_keys)

        return api_keys

    @property
    def fatal_errors(self):
        return {'invalid_api_key', 'current state: suspended'}


if __name__ == '__main__':
    # print(arun(Completions().acreate(ChatCompletionRequest(messages=[{"role": "user", "content": "你是谁"}]))))
    feishu_url = "https://xchatllm.feishu.cn/sheets/Bmjtst2f6hfMqFttbhLcdfRJnNf?sheet=lX8pCZ"
    print(Completions(base_url='https://api.deepseek.com/v1').get_and_update_api_keys(feishu_url))
    pass
