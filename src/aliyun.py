import json
import socket

import aiohttp_jinja2
from aiohttp import web

from aliyunsdkcore.client import AcsClient
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkslb.request.v20140515.SetBackendServersRequest import SetBackendServersRequest
from aliyunsdkalidns.request.v20150109.UpdateDomainRecordRequest import UpdateDomainRecordRequest
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordsRequest import DescribeDomainRecordsRequest
from aliyunsdkslb.request.v20140515.DescribeVServerGroupsRequest import DescribeVServerGroupsRequest
from aliyunsdkslb.request.v20140515.SetVServerGroupAttributeRequest import SetVServerGroupAttributeRequest
from aliyunsdkslb.request.v20140515.AddAccessControlListEntryRequest import AddAccessControlListEntryRequest
from aliyunsdkslb.request.v20140515.DescribeVServerGroupAttributeRequest import DescribeVServerGroupAttributeRequest
from aliyunsdkslb.request.v20140515.DescribeLoadBalancerAttributeRequest import DescribeLoadBalancerAttributeRequest


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
            _domain = domain.split("_")[0]
            domain_dic = config.get_domain(domain)
            virtual_name = domain_dic.get("slb_virtual_name")
            domain_slbs = domain_dic.get("slbs")
            domain_addr = socket.getaddrinfo(_domain, None)[0][4][0]
            req.set_accept_format('json')
            current_slbs = list()
            # 检查SLB的IP地址与当前解析IP一致，不一致不返回。过滤掉备用的SLB
            for slb in domain_slbs:
                req.set_LoadBalancerId(slb)
                req_resp = json.loads(client.do_action_with_exception(req).decode("utf8"))
                slb_addr = req_resp.get("Address", "")
                if domain_addr == slb_addr:
                    current_slbs.append("{}/{}".format(slb, virtual_name))
            resp = {domain: current_slbs}
            responses.append(resp)
        return dict(domains=responses)


async def get_slb_backends(request):
    if request.method == "POST":
        # 返回给用户的Response
        resp = dict()
        data = await request.post()
        slb_id, virtual_name = data.get("slb_id", "").split("/")
        # 获取SLB的基本信息，主要是名称，外网IP
        req = DescribeLoadBalancerAttributeRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(slb_id)
        req_response = json.loads(client.do_action_with_exception(req).decode("utf8"))
        resp["name"] = req_response.get("LoadBalancerName")
        resp["ip"] = req_response.get("Address")
        virtual_id = ""
        if virtual_name != "None":
            # 有虚拟组，获取虚拟组中的机器
            req = DescribeVServerGroupsRequest()
            req.set_accept_format("json")
            req.set_LoadBalancerId(slb_id)
            try:
                req_resp = json.loads(client.do_action_with_exception(req).decode("utf8"))
                for vgroup in req_resp.get("VServerGroups").get("VServerGroup"):
                    if vgroup.get("VServerGroupName") == virtual_name:
                        virtual_id = vgroup.get("VServerGroupId")
                        # 通过虚拟组ID获取后端服务器信息
                        req = DescribeVServerGroupAttributeRequest()
                        req.set_accept_format("json")
                        req.set_VServerGroupId(virtual_id)
                        req_response = json.loads(client.do_action_with_exception(req).decode("utf8"))
                        break
            except Exception as e:
                return web.json_response(status=500, text=str(e))
        backends = req_response.get("BackendServers", {}).get("BackendServer")
        if not backends:
            return web.json_response(status=500, text="No Servers")
        # Key为ECS ID, Value为权重
        backend_dic = {k.get("ServerId"): k.get("Weight") for k in backends}
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
            item['weight'] = backend_dic.get(item["id"])
            public_ips = instance.get("PublicIpAddress").get("IpAddress")
            if public_ips:
                item['public_ip'] = public_ips[0]
            if virtual_id:
                item['virtual_id'] = virtual_id
            _results.append(item)
        resp["servers"] = _results
        return web.json_response(resp)
    elif request == "GET":
        return web.Response(status=405)


async def change_slb_backend(request):
    ecs_id = request.query.get("ecsId")
    slb_with_virtual = request.query.get("slbId")
    slb_id, virtual_name = slb_with_virtual.split("/")
    action = request.query.get("action")
    if action == "online":
        weight = 100
    elif action == "offline":
        weight = 0
    else:
        return web.Response(status=500, text="不支持的操作")
    if virtual_name == "None":
        req = SetBackendServersRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(slb_id)
        data = dict(ServerId=ecs_id, weight=weight)
        req.set_BackendServers([data])
    else:
        virtual_id = request.query.get("virtual_id")
        req = DescribeVServerGroupAttributeRequest()
        req.set_accept_format("json")
        req.set_VServerGroupId(virtual_id)
        backends = list()
        try:
            req_response = json.loads(client.do_action_with_exception(req).decode("utf8"))
            for backend in req_response.get("BackendServers", {}).get("BackendServer"):
                if backend.get("ServerId") == ecs_id:
                    backend["Weight"] = weight
                backends.append(backend)
            req = SetVServerGroupAttributeRequest()
            req.set_accept_format("json")
            req.set_VServerGroupId(virtual_id)
            req.set_BackendServers(backends)
        except Exception as e:
            return web.json_response(status=500, text=str(e))
    try:
        response = client.do_action_with_exception(req)
        print("对SLB{}服务器{}执行{}操作".format(slb_id, ecs_id, action))
        return web.Response(status=200, text=response.decode("utf8"))
    except Exception as e:
        return web.Response(status=500, text=str(e))


@aiohttp_jinja2.template("dns.html")
async def dns_index(request):
    return {'domains': config.get_all_domains("dns")}


async def dns_get_ip(request):
    if request.method == 'POST':
        data = await request.post()
        _config_domain = data.get("domain")
        full_domain = _config_domain.split("_")[0]
        domain_dic = config.get_domain(_config_domain)
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


@aiohttp_jinja2.template("acl.html")
async def slb_add_ip(request):
    if request.method == 'GET':
        return {}
    elif request.method == 'POST':
        data = await request.post()
        ip, comment = data.get("ip", ""), data.get("comment", "")
        if not ip:
            return web.json_response({"status": "invalid ip"})
        req = AddAccessControlListEntryRequest()
        req.set_accept_format('json')
        req.set_AclId("acl-wz9lkxbst9kk1v57lz3ha")
        entrys = [{"entry": "{}/32".format(ip), "comment": comment}]
        req.set_AclEntrys(entrys)
        try:
            client.do_action_with_exception(req)
        except Exception:
            return web.json_response({"status": "error"})
        return web.json_response({"status": "success"})
