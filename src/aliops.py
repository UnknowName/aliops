import jinja2
import aiohttp_jinja2
from aiohttp import web

import es
import nginx
import aliyun
import check


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
        web.get('/cdn/cache', aliyun.flush_cache),
        web.post('/cdn/cache', aliyun.flush_cache),
        web.post('/slb/info', aliyun.get_slb_backends),
        web.get('/slb/change', aliyun.change_slb_backend),
        web.get('/slb/acl', aliyun.slb_add_ip),
        web.post('/slb/acl', aliyun.slb_add_ip),
        web.get('/dns', aliyun.dns_index),
        web.post('/dns/get_ip', aliyun.dns_get_ip),
        web.get('/dns/change', aliyun.dns_change_ip),
        web.get('/check/{domain}', check.check),
        web.get('/recycle', check.recycle),
        web.post('/recycle', check.recycle),
        web.post('/recycle/log', check.recycle_log),
        web.get('/log/sum', es.sum_error),
        web.get('/log/list', es.log_list),
    ]
    app.add_routes(routes)
    web.run_app(app, port=8080, access_log=None)


if __name__ == '__main__':
    main()
