import os
import time
import asyncio
from queue import Queue

import aiohttp_jinja2
from aiohttp import web, ClientSession
from jinja2 import Environment, PackageLoader

LOG_QUEUE = {}
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
    resp_fmt = "<p style='color: {color};margin: 5px auto'>{name}&nbsp;{host}&nbsp; {status}</p>"
    for status, host in all_results:
        if status in [200, 301, 302]:
            ok += 1
            response += resp_fmt.format(color="green", host=host, status=status, name=servers.get(host))
        else:
            response += resp_fmt.format(color="red", host=host, status=status, name=servers.get(host))
    rate = ok / len(servers) * 100
    response += '<p style="color: green">Rate: {}%</p>'.format(rate)
    return web.Response(status=200, text=response, content_type="text/html", charset="utf8")


@aiohttp_jinja2.template("log.html")
async def recycle(request):
    if request.method == "POST":
        global LOG_QUEUE
        domain = os.getenv("domain", None)
        if domain is None:
            raise Exception("No domain env config")
        servers = [
            "172.18.0.208", "172.18.17.68", "172.18.0.206", "172.18.0.204",
            "172.18.0.205", "172.18.17.67", "172.18.17.64", "172.18.17.64"
        ]
        if not os.path.exists("task.yaml"):
            env = Environment(loader=PackageLoader('aliops', 'templates'))
            template = env.get_template('tasks.yaml')
            tasks_str = template.render(hosts=servers, domain=domain)
            with open("task.yaml", "w") as f:
                f.write(tasks_str)
        thread = await asyncio.create_subprocess_exec(
            "ansible-playbook", "-v", "task.yaml",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _key = "{}-{}".format(time.strftime("%Y%m%d%H%M%S"), thread.pid)
        stdout, _ = await thread.communicate()
        LOG_QUEUE[_key] = Queue()
        lines = (line for line in stdout.decode("utf8").split("\n") if line)
        for line in lines:
            LOG_QUEUE[_key].put(line)
        # 最后加一个结束标志
        LOG_QUEUE[_key].put("EOF")
        # 客户JS代码，获取日志时，带上此_key
        return web.json_response({"msg": _key})
    elif request.method == "GET":
        return {}
    else:
        return web.Response(status=403)


async def recycle_log(request):
    if request.method == "POST":
        global LOG_QUEUE
        data = await request.post()
        _key = data.get("key")
        queue = LOG_QUEUE.get(_key)
        if not _key or not queue:
            return web.Response(status=405, text="Key error")
        msg = dict(msg=queue.get())
        await asyncio.sleep(1)
        return web.json_response(msg)
    else:
        return web.Response(status=405)

