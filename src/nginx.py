import logging

import aiohttp_jinja2
from aiohttp import web

from utils import AppConfig, check_equal, GatewayNGINX

log_fmt = "%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s"
logging.basicConfig(level=logging.INFO, format=log_fmt)
logger = logging.getLogger("aiohttp")
config = AppConfig()


async def get_domain_attrs(request):
    data = await request.post()
    domain = data.get("domain", "")
    nginx_user, nginxs = config.get_domain_nginxs(domain)
    config_file = config.get_domain(domain).get("config_file", "")
    backend_port = config.get_domain(domain).get("backend_port")
    all_servers = [
        GatewayNGINX(nginx_user, host).get_servers(config_file, backend_port)
        for host in nginxs
    ]
    if not check_equal(all_servers):
        # 网关数据不一样，有可能是因为主机连接失败，打印到终端用于DEBUG
        logger.info("执行获取{0}网关数据，数据不一致: {1}".format(domain, all_servers))
        response = dict(servres=[], status="501", err_msg="出现错误, 网关数据不一致")
    else:
        ok, servers = all_servers.pop()
        if ok and servers:
            response = dict(servers=tuple(servers), status="200", err_msg="")
        else:
            # 如果远程命令失败，servers变量是标准错误输出
            if not servers:
                stderr = "未能获取到后端服务器，请联系管理员确认配置无误"
            else:
                stderr = servers
            logger.info("获取upstreams失败,输出: {0}".format(stderr))
            response = dict(servers=[], status="500", err_msg=str(stderr))
    return web.json_response(response)


@aiohttp_jinja2.template("nginx.html")
async def change_upstream(request):
    if request.method == "GET":
        domains = config.get_all_domains("nginx")
        return {'domains': domains}
    elif request.method == "POST":
        data = await request.post()
        domain, down_option, up_option = data.get("domain"), data.get("down_option", ""), data.get("up_option", "")
        config_file = config.get_domain(domain).get("config_file", "")
        nginx_user, nginxs = config.get_domain_nginxs(domain)
        if not config_file:
            logger.error("{} Domain NGINX config file path not set!".format(domain))
            return web.json_response(status=500, data=dict(status=500, msg="配置文件有误或者未配置当前域名,请联系管理员修正"))
        up_servers, down_servers = data.get("up_servers", "").split(","), data.get("down_servers", "").split(",")
        upstream_dic = dict(up_servers=up_servers, down_servers=down_servers)
        operation_dic = dict(down=down_option, up=up_option)
        logger.info("Servers is : {0}".format(upstream_dic))
        outputs = [
            GatewayNGINX(nginx_user, host).change_servers(upstream_dic, operation_dic, config_file)
            for host in nginxs
        ]
        if all([success[0] for success in outputs]):
            return web.json_response(dict(status=200, msg="修改成功"))
        else:
            return web.json_response(data=dict(status=500, msg="操作失败,请联系管理员查看详细日志"))
    else:
        return web.Response(status=401)
