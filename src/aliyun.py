import pprint
import time
import asyncio

import aiohttp_jinja2
from aiohttp import web
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_cdn20180510 import models as cdn_20180510_models
from alibabacloud_cdn20180510.client import Client as Cdn20180510Client


import manager
from config import AppConfig

config = AppConfig()


@aiohttp_jinja2.template("cdn.html")
async def flush_cache(request):
    if request.method == "GET":
        return {}
    elif request.method == "POST":
        data = await request.post()
        url = data.get("urls").replace("\r", " ").replace("\n", " ")
        if url == "":
            return web.Response(status=200, text="URL为空")
        _config = open_api_models.Config(config.api.key, config.api.secret)
        _config.endpoint = 'cdn.aliyuncs.com'
        cdn_client = Cdn20180510Client(_config)
        tasks = list()
        security_token = time.asctime()
        for _url in url.split():
            url_type = "file"
            if _url.endswith("/"):
                url_type = "directory"
            req = cdn_20180510_models.RefreshObjectCachesRequest(
                object_type=url_type,
                object_path=_url,
                security_token=security_token
            )
            task = cdn_client.refresh_object_caches_async(req)
            tasks.append(task)
        try:
            _dones, _ = await asyncio.wait(tasks)
            results = [_done.result() for _done in _dones]
            body_dicts = [r.to_map().get("body") for r in results]
        except Exception as e:
            body_dicts = [dict(ErrorMessage=str(e))]
        return web.json_response(body_dicts)
    return web.Response(status=403, text=request.method)


@aiohttp_jinja2.template("aliyun.html")
async def slb_index(request):
    if request.method == "GET":
        responses = list()
        for domain, conf in config.domain.items():
            if conf.slb:
                responses.append({domain: conf.slb.ids})
        return dict(domains=responses)
    return {}


async def get_slb_backends(request):
    if request.method != "POST":
        return web.Response(status=405, text=request.method)
    data = await request.post()
    slb_id, domain = data.get("slb_id").split(":")
    domain_conf = config.get_domain_config(domain)
    slb_agent = manager.get_slb(domain_conf.slb.type, config.slb_api.key, config.slb_api.secret, config.slb_api.region)
    response = slb_agent.get_backends(slb_id, domain_conf.slb.backend_virtual_name)
    return web.json_response(response)


async def change_slb_backend(request):
    ecs_id = request.query.get("ecsId")
    virtual_id = request.query.get("virtual_id")
    slb_with_virtual = request.query.get("slbId")
    slb_id, domain = slb_with_virtual.split(":")
    action = request.query.get("action")
    port = request.query.get("port")
    domain_conf = config.get_domain_config(domain)
    slb_agent = manager.get_slb(domain_conf.slb.type, config.slb_api.key, config.slb_api.secret, config.slb_api.region)
    virtual_name = domain_conf.slb.backend_virtual_name
    option = manager.OperatorOption(
        slb_id=slb_id,
        ecs_id=ecs_id,
        virtual_id=virtual_id,
        action=action,
        virtual_name=virtual_name,
        port=port,
    )
    # 检查当前负载是否再下线后没有机器了
    print("对SLB{}服务器{}执行{}操作".format(slb_id, option.ecs_id, option.action))
    if option.action == "offline":
        backend_resp = slb_agent.get_backends(slb_id, option.virtual_name)
        backends = backend_resp.get("servers")
        actives = list(server for server in backends if server.get("weight") != 0)
        if len(actives) == 1:
            return web.Response(status=403, text="当前只有一台主机在线")
    resp = slb_agent.change_backend(slb_id, option)
    return web.Response(status=200, text=resp.get("text"))


@aiohttp_jinja2.template("dns.html")
async def dns_index(request):
    return {'domains': [domain for domain, sub_conf in config.domain.items() if sub_conf.domain is not None]}


async def dns_get_ip(request):
    if request.method == 'POST':
        data = await request.post()
        domain = data.get("domain")
        full_domain = domain.split("_")[0]
        domain_conf = config.get_domain_config(domain)
        dns_domain = domain_conf.domain
        if not dns_domain:
            print("The domain in config.yml not set domain attribute")
        # 通过索引切片，获取最前面的RR值。如www.unknowname.win取值www
        full_len = len(full_domain)
        domain_len = len(dns_domain) + 1
        query_keyword = full_domain[:full_len - domain_len]
        agent = manager.DNSAgent(config.dns_api.key, config.dns_api.secret, config.dns_api.region)
        response = agent.get_record(dns_domain, query_keyword)
        response["BackupIPs"] = list(domain_conf.ip.keys())
        return web.json_response(response)


async def dns_change_ip(request):
    domain = request.query.get("domain")
    ip = request.query.get("ip")
    domain_conf = config.get_domain_config(domain)
    backup_ips = domain_conf.ip
    if ip not in backup_ips:
        resp = dict(msg="非法IP!修改只限已给定列表中的IP")
        return web.json_response(resp)
    record_id = request.query.get("id")
    domain_record, *_ = domain.split(".")
    agent = manager.DNSAgent(config.dns_api.key, config.dns_api.secret, config.dns_api.region)
    print(f"修改{domain_conf.domain}记录{domain_record}的新IP为{ip}")
    resp = agent.change_record(domain_conf.domain, domain_record, record_id, ip)
    return web.json_response(resp)


@aiohttp_jinja2.template("acl.html")
async def slb_add_ip(request):
    if request.method == 'GET':
        return {}
    elif request.method == 'POST':
        data = await request.post()
        ip, comment = data.get("ip", None), data.get("comment", "")
        if not ip:
            return web.json_response({"status": "invalid ip"})
        agent = manager.ACLAgent(config.slb_api.key, config.slb_api.secret, config.slb_api.region)
        resp = agent.add_ip(ip, comment)
        return web.json_response(resp)
