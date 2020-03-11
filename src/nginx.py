import aiohttp_jinja2
from aiohttp import web

from utils import AppConfig, Gateway, check_equal

config = AppConfig()


async def get_domain_attrs(request):
    data = await request.post()
    domain = data.get("domain", "")
    nginx_user, nginxs = config.get_domain_nginxs(domain)
    config_file = config.get_domain(domain).get("config_file", "")
    backend_port = config.get_domain(domain).get("backend_port")
    all_servers = [
        Gateway(nginx_user, host).get_domain_servers(config_file, backend_port)
        for host in nginxs
    ]
    if not check_equal(all_servers):
        # 网关数据不一样，有可能是因为主机连接失败，打印到终端用于DEBUG
        print("执行获取{0}网关数据，数据不一致: {1}".format(domain, all_servers))
        response = dict(servres=[], status="501", err_msg="网关数据不一致")
    else:
        ok, servers = all_servers.pop()
        if ok:
            response = dict(servers=tuple(servers), status="200", err_msg="")
        else:
            # 如果远程命令失败，servers变量是标准错误输出
            response = dict(servers=[], status="500", err_msg=servers)
    return web.json_response(response)


@aiohttp_jinja2.template("nginx.html")
async def change_upstream(request):
    if request.method == "GET":
        domains = config.get_all_domains("nginx")
        return {'domains': domains}
    elif request.method == "POST":
        data = await request.post()
        domain, action = data.get("domain"), data.get("action")
        nginx_user, nginxs = config.get_domain_nginxs(domain)
        config_file = config.get_domain(domain).get("config_file", "")
        if not config_file:
            print("Domain NGINX config file path not set!")
        _servers = list()
        for k, v in data.items():
            if not k.startswith("server"):
                continue
            _servers.append(v)
        outputs = [
            Gateway(nginx_user, host).set_upstreams_status(_servers, action, config_file)
            for host in nginxs
        ]
        if all([success[0] for success in outputs]):
            ok_html = "<html>执行{}动作成功<a href='nginx'>返回</a></html>".format(action)
            return web.Response(status=200, charset="utf8", text=ok_html, content_type='text/html')
        else:
            return web.Response(status=500, charset="utf8", content_type="text/html", text="Failed")
    else:
        return web.Response(status=401)
