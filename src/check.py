import asyncio

from aiohttp import web, ClientSession


SERVERS = {
    "shopapi.sissyun.com.cn": {
        '172.18.0.203': "O2O1",
        '172.18.17.71': "O2O2",
        '172.18.61.67': "BossDB",
        '172.18.17.70': "O2O4",
        '172.18.17.72': "O2O5",
        '172.18.17.69': "O2O8",
        '172.18.17.64': "O2O10",
        '172.18.17.67': "O2O11",
        '172.18.17.66': "O2O13",
        '172.18.17.63': "O2O14",
        '172.18.17.79': "O2O15",
        '172.18.17.78': "O2O16",
        '172.18.0.205': "O2O17",
        '172.18.0.204': "O2O18",
        '172.18.0.206': "O2O19",
        '172.18.0.208': "O2O20",
        '172.18.0.213': "O2O21",
        '172.18.0.212': "O2O22",
        '172.18.0.217': "O2O23",
        '172.18.0.216': "O2O24",
        '172.18.203.241': "O2O25",
        '172.18.203.243': "O2O26",
        '172.18.203.244': "O2O27"
    },

    "offline.shopapi.sissyun.com.cn": {
        "172.18.203.244:8097": "O2O27",
        "172.18.203.243:8097": "O2O26",
        "172.18.203.241:8097": "O2O25",
        "172.18.0.213:8097": "O2O21"
    }
}


async def _get_status(site: str, host: str):
    url = "http://{}/swagger/index.html".format(host)
    headers = dict(Host=site)
    try:
        async with ClientSession(headers=headers) as session:
            async with session.get(url, timeout=5) as resp:
                return resp.status, host
    except Exception as e:
        if str(e) == "":
            e = "Coroutine timeout"
        print("Get response from {host} error {err}".format(host=host, err=e))
        return 504, host


async def check(request):
    domain = request.match_info['domain']
    servers = SERVERS.get(domain)
    if not servers:
        return web.Response(status=200, text="当前站点未配置检测")
    tasks = [_get_status(domain, host) for host in servers]
    dones, _ = await asyncio.wait(tasks, timeout=6)
    all_results = [done.result() for done in dones]
    response = ""
    ok = 0
    for status, host in all_results:
        if status in [200, 301, 302]:
            ok += 1
        response += "{name}  {host}  {status}\n".format(host=host, status=status, name=servers.get(host))
    rate = ok / len(all_results) * 100
    response += '\nRate: {}%'.format(rate)
    return web.Response(status=200, text=response)
