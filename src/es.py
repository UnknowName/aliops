from datetime import datetime, timedelta

import aiohttp.client
from aiohttp import web

from utils import AppConfig

config = AppConfig()
esinfo = config.get_attr("es")
if not esinfo:
    raise Exception("elasticsearch not config")
es_addr = esinfo.get("addr") if esinfo.get("addr") else "127.0.0.1"
es_port = esinfo.get("port") if esinfo.get("port") else "9200"
addr = f"http://{es_addr}:{es_port}/_search"


async def log_list(request):
    now = datetime.utcnow()
    before = now + timedelta(minutes=-5)
    query_time = before.strftime("%Y-%m-%d %H:%M:%S.000")
    query = {
        "_source": ["pay_channel", "server_ip", "timestamp"],
        "size": 100,
        "query": {
            "bool": {
                "must": [
                    {"match": {"error": 1}}
                ],
                "filter": [
                    {"range": {"timestamp": {"gte": query_time}}}
                ]
            }
        },
        "sort": {
            "timestamp": {"order": "desc"}
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(addr, json=query) as response:
            jsons = await response.json()
            return web.json_response(jsons["hits"])


async def sum_error(request):
    return None
