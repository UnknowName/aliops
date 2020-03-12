import json
import socket

import aiohttp_jinja2
from aiohttp import web

from aliyunsdkcore.client import AcsClient
from aliyunsdkslb.request.v20140515.SetBackendServersRequest import SetBackendServersRequest
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkslb.request.v20140515.DescribeLoadBalancerAttributeRequest import DescribeLoadBalancerAttributeRequest
from aliyunsdkalidns.request.v20150109.UpdateDomainRecordRequest import UpdateDomainRecordRequest
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordsRequest import DescribeDomainRecordsRequest

from utils import AppConfig

config = AppConfig()
api_dic = config.get_attr("api")
aeskey, secret, region = api_dic.get("aeskey"), api_dic.get("aeskey_secret"), api_dic.get("region")
client = AcsClient(aeskey, secret, region)
dns_api = config.get_attr("dns_api")
dns_key, dns_secret, dns_region = dns_api.get("aeskey"), dns_api.get("aeskey_secret"), dns_api.get("region")
if dns_key and dns_region and dns_secret:
    dns_client = AcsClient(dns_key, dns_secret, dns_region)
else:
    dns_client = client


@aiohttp_jinja2.template("aliyun.html")
async def slb_index(request):
    if request.method == "GET":
        req = DescribeLoadBalancerAttributeRequest()
        responses = list()
        slb_domains = config.get_all_domains("slb")
        for domain in slb_domains:
            domain_dic = config.get_domain(domain)
            domain_slbs = domain_dic.get("slbs")
            domain_addr = socket.getaddrinfo(domain, None)[0][4][0]
            req.set_accept_format('json')
            current_slbs = list()
            # 检查SLB的IP地址与当前解析IP一致，不一致不返回。过滤掉备用的SLB
            for slb in domain_slbs:
                req.set_LoadBalancerId(slb)
                req_resp = json.loads(client.do_action_with_exception(req).decode("utf8"))
                slb_addr = req_resp.get("Address", "")
                if domain_addr == slb_addr:
                    current_slbs.append(slb)
            resp = {domain: current_slbs}
            responses.append(resp)
        return dict(domains=responses)


async def get_slb_backends(request):
    if request.method == "POST":
        # 返回给用户的Response
        resp = dict()
        data = await request.post()
        req = DescribeLoadBalancerAttributeRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(data.get("slb_id", ""))
        response = json.loads(client.do_action_with_exception(req).decode("utf8"))
        resp["name"] = response.get("LoadBalancerName")
        resp["ip"] = response.get("Address")
        default_backends = response.get("BackendServers").get("BackendServer")
        # Key为ECS ID, Value为权重
        backend_dic = {k.get("ServerId"): k.get("Weight") for k in default_backends}
        # 先获取SLB默认后端的ECS的ID，SLB只提供该API
        ecs_ids = [ecs_id for ecs_id in backend_dic]
        # 拿到ECS ID后，再获取该ECS详细信息，最终返回给页面渲染
        req = DescribeInstancesRequest()
        req.set_accept_format('json')
        req.set_PageSize(50)
        req.set_InstanceIds(ecs_ids)
        _response = json.loads(client.do_action_with_exception(req).decode("utf8"))
        instances = _response.get("Instances").get("Instance")
        _results = []
        for instance in instances:
            item = dict()
            # 返回的实例信息中，不包含该服务器在SLB中的权重
            item["name"] = instance.get("InstanceName")
            item["id"] = instance.get("InstanceId")
            if instance.get("InstanceNetworkType") == "classic":
                item['private_ip'] = instance.get("InnerIpAddress").get("IpAddress")[0]
            else:
                item['private_ip'] = instance.get("NetworkInterfaces").get("NetworkInterface")[0].get(
                    "PrimaryIpAddress")
            item['public_ip'] = instance.get("PublicIpAddress").get("IpAddress")[0]
            item['weight'] = backend_dic.get(item["id"])
            _results.append(item)
        resp["servers"] = _results
        return web.json_response(resp)
    elif request == "GET":
        return web.Response(status=405)


async def change_slb_backend(request):
    ecs_id = request.query.get("ecsId")
    slb_id = request.query.get("slbId")
    action = request.query.get("action")
    if action == "online":
        weight = 100
    elif action == "offline":
        weight = 0
    else:
        return web.Response(status=500, text="error")
    req = SetBackendServersRequest()
    req.set_accept_format('json')
    req.set_LoadBalancerId(slb_id)
    data = dict(ServerId=ecs_id, weight=weight)
    req.set_BackendServers([data])
    try:
        response = client.do_action_with_exception(req)
        print("对SLB{}服务器{}执行{}操作".format(slb_id, ecs_id, action))
        return web.Response(status=200, text=response.decode("utf8"))
    except Exception as e:
        print(e)
        return web.Response(status=500, text="error")


@aiohttp_jinja2.template("dns.html")
async def dns_index(request):
    return {'domains': config.get_all_domains("dns")}


async def dns_get_ip(request):
    if request.method == 'POST':
        data = await request.post()
        full_domain = data.get("domain")
        domain_dic = config.get_domain(full_domain)
        dns_domain = domain_dic.get('domain')
        if not dns_domain:
            print("The domain in config.yml not set domain attribute")
        # 通过索引切片，获取最前面的RR值。如www.unknowname.win取值www
        full_len = len(full_domain)
        domain_len = len(dns_domain) + 1
        query_keyword = full_domain[:full_len - domain_len]
        request = DescribeDomainRecordsRequest()
        request.set_accept_format('json')
        request.set_DomainName(dns_domain)
        request.set_Lang("en")
        request.set_PageSize(20)
        request.set_KeyWord(query_keyword)
        try:
            response = dns_client.do_action_with_exception(request)
            resp = str(response, encoding='utf-8')
            detail = json.loads(resp)
            backup_ips = domain_dic.get("ips")
            detail["BackupIPs"] = backup_ips
            return web.json_response(detail)
        except Exception as e:
            print(e)
        return web.json_response({})


async def dns_change_ip(request):
    domain = request.query.get("domain")
    ip = request.query.get("ip")
    domain_dic = config.get_domain(domain)
    backup_ips = domain_dic.get('ips')
    if ip not in backup_ips:
        resp = dict(msg="非法IP!修改只限已给定列表中的IP")
        return web.json_response(resp)
    record_id = request.query.get("id")
    domain_record, *_ = domain.split(".")
    request = UpdateDomainRecordRequest()
    request.set_accept_format('json')
    request.set_RecordId(record_id)
    request.set_RR(domain_record)
    request.set_Type("A")
    request.set_Value(ip)
    response = dns_client.do_action_with_exception(request)
    if json.loads(response.decode("utf8")).get("RecordId") == record_id:
        resp = dict(msg="OK")
        return web.json_response(resp)
    err_resp = dict(msg="error")
    return web.json_response(err_resp)
