import asyncio

import aiohttp_jinja2
from aiohttp import web

import config
from utils import run_remote_cmd, gener_cmd

NGINXS = config.NGINXS
DOMAINS = config.DOMAINS
NGINX_USER = config.NGINX_USER


@aiohttp_jinja2.template("nginx.html")
async def change_upstream(request):
    if request.method == "POST":
        data = await request.post()
        domain = data.get("domain")
        action = data.get("action")
        cmds = list()
        config_file = await config.get_domain_config(domain, 'config_file')
        for k, v in data.items():
            if not k.startswith("server"):
                continue
            host = v
            cmd = gener_cmd(action, host, str(config_file))
            cmds.append(cmd)
        if not cmds:
            return web.Response(text="请至少选择一台服务器进行操作!")
        # Set Server up/down
        user = NGINX_USER
        tasks = [
            run_remote_cmd(user, nginx, cmd)
            for nginx in NGINXS
            for cmd in cmds
        ]
        dones, _ = await asyncio.wait(tasks, timeout=5)
        results = [done.result() for done in dones]
        if not all(results):
            return web.Response(
                status=200,
                text="<html>执行服务器上/下线失败,请联系管理员查找原因<a href='/nginx'>返回</a><html>",
                content_type="text/html"
            )
        # Reload NGINX
        reload_tasks = [
            run_remote_cmd(user, nginx, "nginx -t&&nginx -s reload")
            for nginx in NGINXS
        ]
        relods, _ = await asyncio.wait(reload_tasks, timeout=5)
        if not all([relod.result() for relod in relods]):
            return web.Response(
                status=200, content_type='text/html',
                text="<html>执行服务器上/下线失败，请联系管理员查找原因<a href='/nginx'>返回</a></html>",
            )
        ok_html = "<html>执行{}动作成功<a href='/nginx'>返回</a></html>".format(action)
        return web.Response(status=200, charset="utf8", text=ok_html, content_type='text/html')
    elif request.method == "GET":
        return {'domains': DOMAINS}
    else:
        return web.Response(status=401)


async def get_domain_attrs(request):
    data = await request.post()
    domain = data.get("domain")
    attr = request.match_info['attr']
    servers = await config.get_domain_config(domain, attr)
    resp = dict(servers=servers)
    return web.json_response(resp)
