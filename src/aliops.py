import asyncio

import jinja2
import aiohttp_jinja2
from aiohttp import web, ClientSession

import nginx
import aliyun


@aiohttp_jinja2.template("index.html")
async def index(request):
    return {}


def main():
    app = web.Application()
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader("templates"))
    routes = [
        web.get('/', index),
        web.get('/nginx', nginx.change_upstream),
        web.post('/nginx', nginx.change_upstream),
        web.post('/domain/{attr}', nginx.get_domain_attrs),
        web.get('/slb', aliyun.slb_index),
        web.post('/slb/info', aliyun.get_slb_backends),
        web.get('/slb/change', aliyun.change_slb_backend),
        web.get('/dns', aliyun.dns_index),
        web.post('/dns/get_ip', aliyun.dns_get_ip),
        web.get('/dns/change', aliyun.dns_change_ip),
        web.get('/check/{domain}', check),
    ]
    app.add_routes(routes)
    web.run_app(app, port=8080)


async def _get_status(site: str, host: str):
    url = "http://{}".format(host)
    headers = dict(Host=site)
    try:
        async with ClientSession(headers=headers) as session:
            async with session.get(url, timeout=5) as resp:
                return resp.status, host
    except Exception as e:
        print("host {host} occur error is {err}".format(host=host, err=e))
        return 504, host


async def check(request):
    domain = request.match_info['domain']
    servers = dict(
        O2O3='172.18.17.73', O2O4='172.18.17.70', O2O5='172.18.17.72', O2O6='172.18.17.74', O2O8='172.18.17.69',
        O2O9='172.18.17.68', O2O10='172.18.17.64', O2O11='172.18.17.67', O2O12='172.18.17.60', O2O13='172.18.17.66',
        O2O14='172.18.17.63', O2O15='172.18.17.79', O2O16='172.18.17.78', O2O17='172.18.0.205', O2O18='172.18.0.204',
        O2O19='172.18.0.206', O2O20='172.18.0.208', O2O21='172.18.0.213', O2O22='172.18.0.212', O2O23='172.18.0.217',
        O2O24='172.18.0.216', O2O25='172.18.203.241', O2O26='172.18.203.243', O2O27='172.18.203.244'
    )
    tasks = [_get_status(domain, host) for host in servers.values()]
    dones, _ = await asyncio.wait(tasks, timeout=6)
    all_results = [done.result() for done in dones]
    response = ""
    ok = 0
    for status, host in all_results:
        if status in [200, 301, 302]:
            ok += 1
        response += "{host}  {status}\n".format(host=host, status=status)
    rate = ok / len(all_results) * 100
    response += '\nRate: {}%'.format(rate)
    return web.Response(status=200, text=response)


if __name__ == '__main__':
    main()
