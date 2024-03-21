import pprint
import time
from typing import List, Dict
import concurrent.futures

import asyncio
import aiohttp_jinja2
from aiohttp import web
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_cdn20180510 import models as cdn_20180510_models
from alibabacloud_cdn20180510.client import Client as Cdn20180510Client

import manager
from config import AppConfig, DomainConfig

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
            if conf.slb and not conf.invisible:
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
    confs = [domain_conf]
    if domain_conf.relatives:
        confs += [config.get_domain_config(other) for other in domain_conf.relatives]
    virtual_name = domain_conf.slb.backend_virtual_name
    option = manager.OperatorOption(
        slb_id=slb_id,
        ecs_id=ecs_id,
        virtual_id=virtual_id,
        action=action,
        virtual_name=virtual_name,
        port=port,
    )
    print(f"{domain}的对服务器{ecs_id}执行{action}操作")
    res = change_slbs_backend(confs, option)
    return web.json_response(res)


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


# use for internal
def get_slbs_backends(confs: List[DomainConfig]) -> Dict:
    conf_and_agent = {
        conf: manager.get_slb(conf.slb.type, config.slb_api.key, config.slb_api.secret, config.slb_api.region)
        for conf in confs
    }
    result = dict()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(confs)) as pool:
        tasks = {
            pool.submit(agent.get_backends,
                        slb_id=list(conf.slb.ids.keys())[0],
                        virtual_name=conf.slb.backend_virtual_name): conf
            for conf, agent in conf_and_agent.items()
        }
        for task in concurrent.futures.as_completed(tasks):
            conf = tasks[task]
            servers = task.result().get("servers")
            result[conf] = servers
    return result


def change_slbs_backend(confs: List[DomainConfig], option: manager.OperatorOption) -> List:
    conf_and_servers = get_slbs_backends(confs)
    for conf, servers in conf_and_servers.items():
        actives = {server.get("id"): None for server in servers if server.get("weight", 0) > 0}
        if len(actives) == 1 and option.action == "offline" and option.ecs_id in actives:
            return [dict(status=403, servers=[], text="当前主机下线后无可用主机")]
    conf_and_agent = {
        conf: manager.get_slb(conf.slb.type, config.slb_api.key, config.slb_api.secret, config.slb_api.region)
        for conf in confs
    }
    res = list()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(confs)) as pool:
        tasks = [
            pool.submit(
                agent.change_backend,
                slb_id=list(conf.slb.ids.keys())[0],
                option=manager.OperatorOption(
                    slb_id=list(conf.slb.ids.keys())[0],
                    ecs_id=option.ecs_id,
                    virtual_name=conf.slb.backend_virtual_name,
                    virtual_id=conf_and_servers[conf][0].get("virtual_id"),
                    action=option.action,
                    port=option.port
                )
            )
            for conf, agent in conf_and_agent.items()
        ]
        for task in concurrent.futures.as_completed(tasks):
            res.append(task.result())
    return res


if __name__ == '__main__':
  pass
