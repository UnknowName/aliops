import asyncio

import aiohttp_jinja2
from aiohttp import web

import config
from utils import run_remote_cmd, gener_cmd
from utils import Gateway, check_equal

GLOBAL_NGINXS = config.NGINXS
DOMAINS = config.DOMAINS
GLOBAL_NGINX_USER = config.NGINX_USER


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
        domain_ngx = await config.get_domain_config(domain, 'nginx')
        if isinstance(domain_ngx, dict) and domain_ngx:
            nginxs = domain_ngx.get("hosts")
            nginx_user = domain_ngx.get("ssh_user")
        else:
            nginxs = GLOBAL_NGINXS
            nginx_user = GLOBAL_NGINX_USER
        tasks = [
            run_remote_cmd(nginx_user, nginx, cmd)
            for nginx in nginxs
            for cmd in cmds
        ]
        dones, _ = await asyncio.wait(tasks, timeout=5)
        results = [done.result() for done in dones]
        if not all(results):
            return web.Response(
                status=200,
                text="<html>执行服务器上/下线失败,请联系管理员查找原因<a href='nginx'>返回</a><html>",
                content_type="text/html"
            )
        # Reload NGINX
        reload_tasks = [
            run_remote_cmd(nginx_user, nginx, "nginx -t&&nginx -s reload")
            for nginx in nginxs
        ]
        relods, _ = await asyncio.wait(reload_tasks, timeout=5)
        if not all([relod.result() for relod in relods]):
            return web.Response(
                status=200, content_type='text/html',
                text="<html>执行服务器上/下线失败，请联系管理员查找原因<a href='nginx'>返回</a></html>",
            )
        ok_html = "<html>执行{}动作成功<a href='nginx'>返回</a></html>".format(action)
        return web.Response(status=200, charset="utf8", text=ok_html, content_type='text/html')
    elif request.method == "GET":
        domains = list()
        for domain in DOMAINS:
            _servers = await config.get_domain_config(domain, "backends")
            if _servers:
                domains.append(domain)
        return {'domains': domains}
    else:
        return web.Response(status=401)


"""
async def get_domain_attrs(request):
    data = await request.post()
    domain = data.get("domain")
    attr = request.match_info['attr']
    servers = await config.get_domain_config(domain, attr)
    resp = dict(servers=["#server 128.0.255.10:8088", "server 128.0.255.11:8080"], status="200", err_msg="")
    return web.json_response(resp)
"""


async def get_domain_attrs(request):
    data = await request.post()
    domain = data.get("domain", "")
    backend_port = await config.get_domain_config(domain, "backend_port")
    config_file = await config.get_domain_config(domain, 'config_file')
    domain_ngx = await config.get_domain_config(domain, 'nginx')
    if isinstance(domain_ngx, dict) and domain_ngx:
        nginxs = domain_ngx.get("hosts", [])
        nginx_user = domain_ngx.get("ssh_user", "")
    else:
        nginxs = GLOBAL_NGINXS
        nginx_user = GLOBAL_NGINX_USER
    all_servers = [
        Gateway(nginx_user, host).get_domain_servers(config_file, backend_port)
        for host in nginxs
    ]
    if not check_equal(all_servers):
        # 网关数据不一样，有可能是因为主机连接失败，打印到终端用于DEBUG
        print(all_servers)
        response = dict(servres=[], status="501", err_msg="网关数据不一致")
    else:
        ok, servers = all_servers.pop()
        if ok:
            response = dict(servers=tuple(servers), status="200", err_msg="")
        else:
            # 如果远程命令失败，servers变量是标准错误输出
            response = dict(servers=[], status="500", err_msg=servers)
    return web.json_response(response)
